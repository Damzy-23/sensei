"""Session state, messages, runs, hints, mastery, tickets and eval runs, stored in SQLite.

Writes take the shared write lock. Reads are plain SELECTs. Raw SQL stays in this
module so the rest of the code works with pydantic models.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.db import get_conn, write_lock
from app.models import ChatActor, ChatMessage, Mode, RunIn, SessionState


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class SessionRecord(BaseModel):
    session_id: str
    created_at: str
    updated_at: str
    problem_id: str | None = None
    mode: Mode = "learn"
    hint_level: int = 0
    failed_runs: int = 0  # consecutive failed runs
    hints_used: int = 0
    guard_violations: int = 0
    frustration_flags: int = 0
    solved_streak: int = 0
    problem_started_at: str | None = None
    escalated: bool = False


_SESSION_FIELDS = set(SessionRecord.model_fields) - {"session_id", "created_at", "updated_at"}


def _execute(sql: str, params: tuple[Any, ...] = ()) -> None:
    with write_lock:
        get_conn().execute(sql, params)


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in get_conn().execute(sql, params).fetchall()]


# ---------- sessions ----------


def create_session() -> str:
    session_id = _id("ses")
    now = _now()
    _execute(
        "INSERT INTO sessions (session_id, created_at, updated_at) VALUES (?, ?, ?)",
        (session_id, now, now),
    )
    return session_id


def get_session(session_id: str) -> SessionRecord | None:
    rows = _rows("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    if not rows:
        return None
    row = rows[0]
    row["escalated"] = bool(row["escalated"])
    return SessionRecord(**row)


def update_session(session_id: str, **fields: Any) -> SessionRecord:
    unknown = set(fields) - _SESSION_FIELDS
    if unknown:
        raise ValueError(f"unknown session fields: {sorted(unknown)}")
    if not fields:
        record = get_session(session_id)
        if record is None:
            raise KeyError(session_id)
        return record
    values = {k: (int(v) if isinstance(v, bool) else v) for k, v in fields.items()}
    assignments = ", ".join(f"{k} = ?" for k in values)
    _execute(
        f"UPDATE sessions SET {assignments}, updated_at = ? WHERE session_id = ?",
        (*values.values(), _now(), session_id),
    )
    record = get_session(session_id)
    if record is None:
        raise KeyError(session_id)
    return record


def state_view(session_id: str) -> SessionState | None:
    """The public GET /sessions/{id}/state payload, built from the stored record."""
    record = get_session(session_id)
    if record is None:
        return None
    elapsed = 0
    if record.problem_started_at:
        started = datetime.fromisoformat(record.problem_started_at)
        elapsed = max(0, int((datetime.now(timezone.utc) - started).total_seconds()))
    return SessionState(
        session_id=session_id,
        problem_id=record.problem_id,
        mode=record.mode,
        hint_level=record.hint_level,
        failed_runs=record.failed_runs,
        hints_used=record.hints_used,
        time_on_problem=elapsed,
        mastery=get_mastery(session_id),
        escalated=record.escalated,
        countdown_seconds=None,
    )


# ---------- messages ----------


def add_message(session_id: str, actor: ChatActor, text: str, trace_id: str | None = None) -> ChatMessage:
    msg_id = _id("msg")
    ts = _now()
    _execute(
        "INSERT INTO messages (id, session_id, actor, text, ts, trace_id) VALUES (?, ?, ?, ?, ?, ?)",
        (msg_id, session_id, actor, text, ts, trace_id),
    )
    return ChatMessage(id=msg_id, session_id=session_id, actor=actor, text=text, ts=ts, trace_id=trace_id)


def list_messages(session_id: str) -> list[ChatMessage]:
    rows = _rows("SELECT * FROM messages WHERE session_id = ? ORDER BY rowid", (session_id,))
    return [ChatMessage(**r) for r in rows]


# ---------- runs ----------


def add_run(session_id: str, problem_id: str, run: RunIn) -> str:
    run_id = _id("run")
    failures = json.dumps([f.model_dump() for f in run.failures])
    _execute(
        "INSERT INTO runs (id, session_id, problem_id, code, passed, failed, total, failures_json, runtime_ms, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (run_id, session_id, problem_id, run.code, run.passed, run.failed, run.total, failures, run.runtime_ms, _now()),
    )
    return run_id


def latest_runs(session_id: str, limit: int = 20) -> list[dict[str, Any]]:
    rows = _rows(
        "SELECT * FROM runs WHERE session_id = ? ORDER BY rowid DESC LIMIT ?",
        (session_id, limit),
    )
    for row in rows:
        row["failures"] = json.loads(row.pop("failures_json"))
    return rows


# ---------- hints ----------


def add_hint(session_id: str, problem_id: str, level: int) -> None:
    _execute(
        "INSERT INTO hints (id, session_id, problem_id, level, created_at) VALUES (?, ?, ?, ?, ?)",
        (_id("hnt"), session_id, problem_id, level, _now()),
    )


def list_hints(session_id: str) -> list[dict[str, Any]]:
    return _rows("SELECT * FROM hints WHERE session_id = ? ORDER BY rowid", (session_id,))


def last_unlock_at(session_id: str) -> str | None:
    rows = _rows("SELECT created_at FROM hints WHERE session_id = ? ORDER BY rowid DESC LIMIT 1", (session_id,))
    return rows[0]["created_at"] if rows else None


def failed_runs_since(session_id: str, since: str | None) -> int:
    """Failed runs created after `since` (all failed runs when since is None)."""
    if since is None:
        rows = _rows("SELECT COUNT(*) AS n FROM runs WHERE session_id = ? AND failed > 0", (session_id,))
    else:
        rows = _rows(
            "SELECT COUNT(*) AS n FROM runs WHERE session_id = ? AND failed > 0 AND created_at > ?",
            (session_id, since),
        )
    return int(rows[0]["n"])


# ---------- mastery ----------


def get_mastery(session_id: str) -> dict[str, float]:
    rows = _rows("SELECT pattern, score FROM mastery WHERE session_id = ?", (session_id,))
    return {r["pattern"]: float(r["score"]) for r in rows}


def set_mastery(session_id: str, pattern: str, score: float) -> None:
    _execute(
        "INSERT INTO mastery (session_id, pattern, score) VALUES (?, ?, ?)"
        " ON CONFLICT (session_id, pattern) DO UPDATE SET score = excluded.score",
        (session_id, pattern, score),
    )
