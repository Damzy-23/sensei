"""SQLite access in WAL mode. One connection per process; writes serialised by a lock.

Phase 2 creates only the `events` table. Phase 3 adds sessions, messages, runs,
hints, mastery, tickets and eval_runs to SCHEMA.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id       TEXT PRIMARY KEY,
    trace_id       TEXT NOT NULL,
    span_id        TEXT NOT NULL,
    parent_span_id TEXT,
    session_id     TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    ts             TEXT NOT NULL,
    actor          TEXT NOT NULL,
    type           TEXT NOT NULL,
    name           TEXT NOT NULL,
    status         TEXT NOT NULL,
    latency_ms     REAL,
    model          TEXT,
    tokens_in      INTEGER,
    tokens_out     INTEGER,
    cost_usd       REAL,
    input          TEXT,
    output         TEXT,
    decision       TEXT,
    reason         TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_trace ON events (trace_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_session ON events (session_id, ts);
"""

write_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
_conn_path: Path | None = None


def get_conn() -> sqlite3.Connection:
    """Return the shared connection, opening it (and creating the schema) on first use.

    Reopens automatically if SENSEI_DB_PATH changed, which the tests rely on.
    """
    global _conn, _conn_path
    path = get_settings().db_path
    with write_lock:
        if _conn is None or _conn_path != path:
            if _conn is not None:
                _conn.close()
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.executescript(SCHEMA)
            _conn, _conn_path = conn, path
        return _conn


def reset_connection() -> None:
    """Close the shared connection. Used by tests that switch databases."""
    global _conn, _conn_path
    with write_lock:
        if _conn is not None:
            _conn.close()
        _conn, _conn_path = None, None
