"""Session memory behind one interface: state, transcript, tickets.

SQLite today (app.db). The functions here are the only way the rest of the app
reads or writes memory, so the store can change without touching callers.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.db import get_conn, write_lock
from app.models import ChatActor, ChatMessage, Mode, Ticket, TicketDetail

BLITZ_SECONDS = 600

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, actor TEXT NOT NULL,
    text TEXT NOT NULL, ts TEXT NOT NULL, trace_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, ts);
CREATE TABLE IF NOT EXISTS tickets (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL, problem_id TEXT NOT NULL,
    status TEXT NOT NULL, stuck_reason TEXT NOT NULL, created_at TEXT NOT NULL,
    latest_code TEXT NOT NULL, suggested_intervention TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return _now().isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _conn():
    conn = get_conn()
    conn.executescript(SCHEMA)
    return conn


@dataclass
class Session:
    session_id: str
    mode: Mode = "learn"
    problem_id: str | None = None
    problem_started_at: str | None = None
    hint_level: int = 0
    failed_runs: int = 0
    hints_used: int = 0
    guard_violations: int = 0
    frustration_flags: int = 0
    escalated: bool = False
    latest_code: str = ""
    mastery: dict[str, float] = field(default_factory=dict)
    panel_notes: list[dict] = field(default_factory=list)  # the observer's signals for the current problem

    def time_on_problem(self) -> int:
        if self.problem_started_at is None:
            return 0
        return max(0, int((_now() - datetime.fromisoformat(self.problem_started_at)).total_seconds()))

    def start_problem(self, problem_id: str) -> None:
        """Switch problem: the hint ladder and run counters start again."""
        if self.problem_id == problem_id:
            return
        self.problem_id, self.problem_started_at = problem_id, now_iso()
        self.hint_level = self.failed_runs = self.hints_used = 0
        self.panel_notes = []


# ---------- sessions ----------


def create_session(mode: Mode = "learn") -> Session:
    session = Session(session_id=new_id("ses"), mode=mode)
    save_session(session)
    return session


def get_session(session_id: str) -> Session | None:
    row = _conn().execute("SELECT data FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return Session(**json.loads(row["data"])) if row else None


def save_session(session: Session) -> None:
    with write_lock:
        _conn().execute(
            "INSERT INTO sessions (session_id, data) VALUES (?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET data = excluded.data",
            (session.session_id, json.dumps(session.__dict__)),
        )


# ---------- transcript ----------


def add_message(session_id: str, actor: ChatActor, text: str, trace_id: str | None = None) -> ChatMessage:
    msg = ChatMessage(id=new_id("msg"), session_id=session_id, actor=actor, text=text, ts=now_iso(), trace_id=trace_id)
    with write_lock:
        _conn().execute(
            "INSERT INTO messages (id, session_id, actor, text, ts, trace_id) VALUES (?,?,?,?,?,?)",
            (msg.id, msg.session_id, msg.actor, msg.text, msg.ts, msg.trace_id),
        )
    return msg


def transcript(session_id: str, limit: int = 50) -> list[ChatMessage]:
    rows = _conn().execute(
        "SELECT * FROM (SELECT rowid AS r, * FROM messages WHERE session_id = ? ORDER BY rowid DESC LIMIT ?) ORDER BY r",
        (session_id, limit),
    ).fetchall()
    return [ChatMessage(**{k: row[k] for k in ChatMessage.model_fields}) for row in rows]


# ---------- tickets ----------


def create_ticket(session: Session, stuck_reason: str, suggested_intervention: str) -> Ticket:
    ticket = Ticket(
        id=new_id("tkt"), session_id=session.session_id, problem_id=session.problem_id or "",
        status="open", stuck_reason=stuck_reason, created_at=now_iso(),
    )
    with write_lock:
        _conn().execute(
            "INSERT INTO tickets VALUES (?,?,?,?,?,?,?,?)",
            (ticket.id, ticket.session_id, ticket.problem_id, ticket.status, ticket.stuck_reason,
             ticket.created_at, session.latest_code, suggested_intervention),
        )
    return ticket


def list_tickets() -> list[Ticket]:
    rows = _conn().execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
    return [Ticket(**{k: row[k] for k in Ticket.model_fields}) for row in rows]


def get_ticket(ticket_id: str) -> TicketDetail | None:
    row = _conn().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        return None
    return TicketDetail(**dict(row), transcript=transcript(row["session_id"]))


def resolve_ticket(ticket_id: str) -> Ticket | None:
    with write_lock:
        _conn().execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
    detail = get_ticket(ticket_id)
    return Ticket(**{k: getattr(detail, k) for k in Ticket.model_fields}) if detail else None
