"""Provenance Guard - Flask application.

Milestone 5 complete: detection pipeline + scorer + transparency label + appeals +
audit log + rate limiting. Rate limiting is the GATE -- it runs before the expensive
detection work, so abuse is refused cheaply.

Public response field names follow the assignment spec:
    content_id, attribution, confidence, label
Attribution values: likely_ai | likely_human | uncertain

RATE LIMITS (per client IP), documented for the README:
  /submit : 10 per minute; 100 per day
      A real writer checks their own work occasionally -- even an active user revising a
      few pieces rarely exceeds a handful of submissions per minute or dozens per day.
      10/min absorbs honest bursts while blocking a script that would fire hundreds of
      requests; 100/day caps sustained abuse while comfortably covering a heavy day.
  /appeal : 5 per minute; 50 per day
      Appeals are rarer than submissions and each one queues costly human review, so the
      limit is tighter -- flooding appeals would be a denial-of-service on reviewers.
"""
import os
import re
import uuid
from datetime import datetime, timezone

from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from llm_signal import run_llm_signal
from stylometry import run_stylometry_signal
from scorer import classify
from labels import generate_label
import audit
import store

app = Flask(__name__)

# Rate limiter (the gate). In-memory storage is fine for local dev / this project.
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


def _now_iso():
    """Current time as an ISO-8601 UTC string with a 'Z' suffix and ms precision."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


@app.get("/health")
def health():
    """Ops convenience: confirms the app is up."""
    return jsonify({"status": "ok"})


@app.post("/submit")
@limiter.limit("10 per minute;100 per day")
def submit():
    """Run both signals + the scorer, attach the label, store state, log, and respond."""
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")
    content_type = data.get("content_type", "other")

    if not text or not str(text).strip():
        return (
            jsonify({"error": "Field 'text' is required and must be non-empty.",
                     "code": "bad_input"}),
            400,
        )

    content_id = uuid.uuid4().hex[:12]
    timestamp = _now_iso()

    # --- Detection pipeline -> Confidence Scorer -> label ----------------------
    llm = run_llm_signal(text)
    stylometry = run_stylometry_signal(text)
    scored = classify(llm, stylometry, _word_count(text))
    attribution = scored["attribution"]
    confidence = scored["confidence"]
    label = generate_label(attribution)

    signals_used = [name for name, sig in (("llm", llm), ("stylometry", stylometry))
                    if sig.get("available")]

    # --- Persist mutable submission state (for appeals) ------------------------
    store.save_submission(content_id, {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": attribution,
        "confidence": confidence,
        "raw_score": scored["raw_score"],
        "text_excerpt": str(text)[:160],
        "status": "classified",
    })

    # --- Audit log: a "decision" entry with both signals + combined result -----
    audit.write_entry({
        "entry_type": "decision",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": attribution,
        "confidence": confidence,
        "raw_score": scored["raw_score"],
        "evidence_trust": scored["evidence_trust"],
        "llm_score": llm.get("score"),
        "stylometry_score": stylometry.get("score"),
        "signals_used": signals_used,
        "status": "classified",
    })

    response = {
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "raw_score": scored["raw_score"],
        "evidence_trust": scored["evidence_trust"],
        "signals": {"llm": llm, "stylometry": stylometry},
        "status": "classified",
        "timestamp": timestamp,
        "creator_id": creator_id,
        "content_type": content_type,
    }
    return jsonify(response), 200


@app.post("/appeal")
@limiter.limit("5 per minute;50 per day")
def appeal():
    """Contest a classification: flip status to under_review and log the appeal."""
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id")
    creator_reasoning = data.get("creator_reasoning")

    if not content_id or not creator_reasoning or not str(creator_reasoning).strip():
        return (
            jsonify({"error": "Fields 'content_id' and 'creator_reasoning' are required.",
                     "code": "bad_input"}),
            400,
        )

    submission = store.get_submission(content_id)
    if submission is None:
        return (
            jsonify({"error": f"No submission found for content_id '{content_id}'.",
                     "code": "not_found"}),
            404,
        )

    timestamp = _now_iso()
    appeal_id = uuid.uuid4().hex[:12]

    # Update the content's status (mutable state) ...
    store.set_status(content_id, "under_review")

    # ... and log the appeal alongside the original decision (append-only ledger).
    audit.write_entry({
        "entry_type": "appeal",
        "appeal_id": appeal_id,
        "content_id": content_id,
        "creator_id": submission.get("creator_id"),
        "timestamp": timestamp,
        "appeal_reasoning": creator_reasoning,
        "status": "under_review",
        "original_attribution": submission.get("attribution"),
        "original_confidence": submission.get("confidence"),
    })

    return jsonify({
        "appeal_id": appeal_id,
        "content_id": content_id,
        "status": "under_review",
        "original_attribution": submission.get("attribution"),
        "appeal_reasoning": creator_reasoning,
        "message": "Your appeal has been recorded; this content is now under review.",
        "timestamp": timestamp,
    }), 200


@app.get("/log")
def get_log():
    """Return recent audit entries as JSON. Optional ?limit=N. (No auth: for grading.)"""
    limit = request.args.get("limit", default=None, type=int)
    return jsonify({"entries": audit.get_log(limit)})


if __name__ == "__main__":
    # Local dev server. Run with:  python app.py
    # Default port is 5001 because macOS AirPlay Receiver occupies port 5000.
    # Override with:  PORT=8000 python app.py
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, port=port)
