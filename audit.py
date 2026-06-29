"""Structured audit log (JSON Lines).

Every attribution decision is appended as one JSON object per line to audit_log.jsonl.
This is the canonical, structured record (not print statements). M3 writes a simple
entry; M4 extends it (real confidence, both signals); M5 adds appeal entries.

Entry shape (M3):
    {
      "content_id": "...",
      "creator_id": "test-user-1",
      "timestamp": "2026-06-28T21:31:20.231Z",
      "attribution": "likely_ai",
      "confidence": null,          # placeholder until the M4 scorer
      "llm_score": 0.81,           # Signal A (signal 1) score
      "status": "classified"
    }
"""
import os
import json
import threading

_LOG_PATH = os.environ.get(
    "AUDIT_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "audit_log.jsonl"),
)
_lock = threading.Lock()


def write_entry(entry: dict) -> dict:
    """Append one structured entry to the audit log. Returns the entry."""
    with _lock:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def get_log(limit: int | None = None) -> list:
    """Return audit entries, most recent first. Optional limit caps the count."""
    if not os.path.exists(_LOG_PATH):
        return []
    entries = []
    with open(_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # skip a corrupt line rather than crash the whole read
    entries.reverse()  # newest first
    if limit is not None:
        entries = entries[:limit]
    return entries
