"""Provenance Guard - Flask application.

Three-signal ensemble + production layer + browser UI.
Pipeline: rate-limit gate -> 3 signals (LLM, stylometry, phrase) -> confidence scorer
-> transparency label -> audit log -> response. Appeals flip status to under_review and
log alongside the original decision. UI served at GET / (auto-opens on launch).

Public response field names follow the assignment spec:
    content_id, attribution, confidence, label
Attribution values: likely_ai | likely_human | uncertain

RATE LIMITS (per client IP):
  /submit : 10 per minute; 100 per day
  /appeal : 5 per minute; 50 per day
"""
import os
import re
import uuid
import threading
import webbrowser
from datetime import datetime, timezone

from flask import Flask, request, jsonify, send_from_directory
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from llm_signal import run_llm_signal
from stylometry import run_stylometry_signal
from signal_phrases import run_phrase_signal
from scorer import classify
from labels import generate_label
import audit
import store

app = Flask(__name__)

limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri="memory://")


def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text))


@app.get("/")
def index():
    """Serve the single-page browser UI."""
    return send_from_directory(app.root_path, "index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/submit")
@limiter.limit("10 per minute;100 per day")
def submit():
    """Run all three signals + the scorer, attach the label, store, log, and respond."""
    data = request.get_json(silent=True) or {}
    text = data.get("text")
    creator_id = data.get("creator_id")
    content_type = data.get("content_type", "other")

    if not text or not str(text).strip():
        return (jsonify({"error": "Field 'text' is required and must be non-empty.",
                         "code": "bad_input"}), 400)

    content_id = uuid.uuid4().hex[:12]
    timestamp = _now_iso()

    # --- Detection pipeline: three independent signals -------------------------
    signals = {
        "llm": run_llm_signal(text),
        "stylometry": run_stylometry_signal(text),
        "phrase": run_phrase_signal(text),
    }

    # --- Confidence Scorer (ensemble) -> label ---------------------------------
    scored = classify(signals, _word_count(text))
    attribution = scored["attribution"]
    confidence = scored["confidence"]
    label = generate_label(attribution)

    signals_used = [name for name, sig in signals.items() if sig.get("available")]

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

    # --- Audit log: a "decision" entry with all signals + combined result ------
    audit.write_entry({
        "entry_type": "decision",
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": timestamp,
        "attribution": attribution,
        "confidence": confidence,
        "raw_score": scored["raw_score"],
        "evidence_trust": scored["evidence_trust"],
        "llm_score": signals["llm"].get("score"),
        "stylometry_score": signals["stylometry"].get("score"),
        "phrase_score": signals["phrase"].get("score"),
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
        "signals": signals,
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
        return (jsonify({"error": "Fields 'content_id' and 'creator_reasoning' are required.",
                         "code": "bad_input"}), 400)

    submission = store.get_submission(content_id)
    if submission is None:
        return (jsonify({"error": f"No submission found for content_id '{content_id}'.",
                         "code": "not_found"}), 404)

    timestamp = _now_iso()
    appeal_id = uuid.uuid4().hex[:12]

    store.set_status(content_id, "under_review")

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


def _open_browser_once(url: str):
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()


if __name__ == "__main__":
    # Run with:  python app.py   (default port 5001; macOS AirPlay uses 5000)
    # Override port:  PORT=8000 python app.py     Disable auto-open:  OPEN_BROWSER=0 python app.py
    port = int(os.environ.get("PORT", 5001))
    if os.environ.get("OPEN_BROWSER", "1") == "1" and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        _open_browser_once(f"http://localhost:{port}/")
    app.run(debug=True, port=port)
