"""Submission store (M5) -- SQLite-backed.

The audit log (audit.py) is an append-only ledger. A submission's *current status* is
mutable state -- it flips from "classified" to "under_review" when appealed. That mutable
state lives here, keyed by content_id.

Why SQLite instead of a JSON file: the previous version read the whole file, mutated it
in memory, and rewrote the whole file on every write. Under concurrent load two requests
can both read the old state and the second write silently clobbers the first -- a lock
around separate _load/_save calls doesn't fix this across processes. SQLite gives us
atomic read-modify-write for free: `set_status` is now a single UPDATE statement, which
the database executes atomically (and WAL mode + a busy timeout let concurrent writers
wait their turn instead of failing). Same idea as the append-only audit log, applied to
mutable state too.

Public interface is unchanged: save_submission / get_submission / set_status.
"""
import os
import json
import sqlite3

_PATH = os.environ.get(
    "SUBMISSIONS_PATH",
    os.path.join(os.path.dirname(__file__), "submissions.db"),
)


def _connect() -> sqlite3.connect:
    conn = sqlite3.connect(_PATH, timeout=5.0)        # wait up to 5s for a locked db
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")           # better concurrent read/write
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


def _init() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS submissions ("
            "  content_id TEXT PRIMARY KEY,"
            "  status     TEXT NOT NULL,"
            "  record     TEXT NOT NULL"            # full submission dict as JSON
            ")"
        )


_init()


def save_submission(content_id: str, record: dict) -> dict:
    """Store (or replace) a submission's state. Atomic upsert."""
    status = record.get("status", "classified")
    payload = json.dumps(record, ensure_ascii=False)
    with _connect() as conn:                           # `with` = one transaction
        conn.execute(
            "INSERT INTO submissions (content_id, status, record) VALUES (?, ?, ?) "
            "ON CONFLICT(content_id) DO UPDATE SET status=excluded.status, record=excluded.record",
            (content_id, status, payload),
        )
    return record


def get_submission(content_id: str):
    """Return a submission's state, or None if the content_id is unknown."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT status, record FROM submissions WHERE content_id = ?",
            (content_id,),
        ).fetchone()
    if row is None:
        return None
    record = json.loads(row["record"])
    record["status"] = row["status"]                   # status column is authoritative
    return record


def set_status(content_id: str, status: str):
    """Update a submission's status atomically. Returns the updated record, or None.

    This is a single UPDATE -- the database performs the read-modify-write as one atomic
    operation, so concurrent appeals can't overwrite each other.
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE submissions SET status = ? WHERE content_id = ?",
            (status, content_id),
        )
        if cur.rowcount == 0:                          # content_id didn't exist
            return None
    return get_submission(content_id)
