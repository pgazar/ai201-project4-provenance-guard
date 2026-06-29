"""Submission store (M5).

The audit log is an append-only ledger (history). A submission's *current status* is
mutable state -- it flips from "classified" to "under_review" when appealed. Those are
two different concerns, so submission state lives here, keyed by content_id, persisted
as a JSON object in submissions.json.

This is what the appeal endpoint looks up (to confirm a content_id exists) and updates
(to set status = under_review).
"""
import os
import json
import threading

_PATH = os.environ.get(
    "SUBMISSIONS_PATH",
    os.path.join(os.path.dirname(__file__), "submissions.json"),
)
_lock = threading.Lock()


def _load() -> dict:
    if not os.path.exists(_PATH):
        return {}
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    with open(_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_submission(content_id: str, record: dict) -> dict:
    """Store a new submission's state."""
    with _lock:
        data = _load()
        data[content_id] = record
        _save(data)
    return record


def get_submission(content_id: str):
    """Return a submission's state, or None if the content_id is unknown."""
    with _lock:
        return _load().get(content_id)


def set_status(content_id: str, status: str):
    """Update a submission's status. Returns the updated record, or None if unknown."""
    with _lock:
        data = _load()
        if content_id not in data:
            return None
        data[content_id]["status"] = status
        _save(data)
        return data[content_id]
