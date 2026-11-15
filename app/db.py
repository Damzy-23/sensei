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

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    problem_id        TEXT,
    mode              TEXT NOT NULL DEFAULT 'learn',
    hint_level        INTEGER NOT NULL DEFAULT 0,
    failed_runs       INTEGER NOT NULL DEFAULT 0,
    hints_used        INTEGER NOT NULL DEFAULT 0,
    guard_violations  INTEGER NOT NULL DEFAULT 0,
    frustration_flags INTEGER NOT NULL DEFAULT 0,
    solved_streak     INTEGER NOT NULL DEFAULT 0,
    problem_started_at TEXT,
    escalated         INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (session_id),
    actor      TEXT NOT NULL,
    text       TEXT NOT NULL,
    ts         TEXT NOT NULL,
    trace_id   TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, ts);
CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    session_id    TEXT NOT NULL REFERENCES sessions (session_id),
    problem_id    TEXT NOT NULL,
    code          TEXT NOT NULL,
    passed        INTEGER NOT NULL,
    failed        INTEGER NOT NULL,
    total         INTEGER NOT NULL,
    failures_json TEXT NOT NULL,
    runtime_ms    INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON runs (session_id, created_at);
CREATE TABLE IF NOT EXISTS hints (
    id         TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions (session_id),
    problem_id TEXT NOT NULL,
    level      INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mastery (
    session_id TEXT NOT NULL REFERENCES sessions (session_id),
    pattern    TEXT NOT NULL,
    score      REAL NOT NULL,
    PRIMARY KEY (session_id, pattern)
);
CREATE TABLE IF NOT EXISTS tickets (
    id                    TEXT PRIMARY KEY,
    session_id            TEXT NOT NULL REFERENCES sessions (session_id),
    problem_id            TEXT NOT NULL,
    status                TEXT NOT NULL,
    stuck_reason          TEXT NOT NULL,
    latest_code           TEXT NOT NULL,
    suggested_intervention TEXT NOT NULL,
    created_at            TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS eval_runs (
    id           TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL,
    results_json TEXT
);
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
