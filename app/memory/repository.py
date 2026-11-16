"""Session memory behind one interface: state, transcript, tickets.

SQLite (app.db) is the store every read uses. The functions here are the only way the
rest of the app reads or writes memory, so the store can change without touching callers.

SQLite starts empty on every deploy, so each write is also mirrored to a durable copy
(app.memory.durable). When a session or ticket is asked for and SQLite does not have it,
it is copied back in from there and reads carry on from SQLite. A restore is all or nothing:
if any part of the copy cannot be read, nothing is written and MemoryUnavailable is raised,
so the next request restores the session whole.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone

from app.db import get_conn, write_lock
from app.memory import durable
from app.memory.durable import MemoryUnavailable

__all__ = ["MemoryUnavailable"]  # the API answers it with 503; see app.main
from app.models import ChatActor, ChatMessage, Mode, Ticket, TicketDetail

BLITZ_SECONDS = 600
RESTORED_TICKETS = 200  # how many of the newest tickets come back into the mentor queue after a restart
LOOK_AGAIN_SECONDS = 15.0  # how long "the durable copy has no such session or ticket" is believed

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
MESSAGE_COLUMNS = ("id", "session_id", "actor", "text", "ts", "trace_id")
TICKET_COLUMNS = (
    "id", "session_id", "problem_id", "status", "stuck_reason", "created_at", "latest_code", "suggested_intervention",
)

log = logging.getLogger(__name__)
_tickets_loaded = False  # the mentor queue is filled from the durable copy once per process
_not_in_copy: dict[str, float] = {}  # session or ticket id -> when the durable copy was last asked for it and had nothing


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
    code_lines_given: int = 0  # lines of code the coach has given on the current problem
    student_turns: int = 0  # messages the student has sent on the current problem
    panel_notes: list[dict] = field(default_factory=list)  # the observer's signals for the current problem

    def time_on_problem(self) -> int:
        if self.problem_started_at is None:
            return 0
        return max(0, int((_now() - datetime.fromisoformat(self.problem_started_at)).total_seconds()))

    def release_from_mentor(self) -> None:
        """The mentor has dealt with it. Clear what triggered the escalation as well as the flag:
        otherwise the counters are still over their limits and the very next message would
        escalate again. The hint level stays where it was; hints_used drops back to it so
        "still stuck after the last hint" needs a fresh request to fire."""
        self.escalated = False
        self.frustration_flags = 0
        self.guard_violations = 0
        self.hints_used = min(self.hints_used, self.hint_level)

    def start_problem(self, problem_id: str) -> None:
        """Switch problem: the hint ladder and run counters start again."""
        if self.problem_id == problem_id:
            return
        self.problem_id, self.problem_started_at = problem_id, now_iso()
        self.hint_level = self.failed_runs = self.hints_used = self.code_lines_given = self.student_turns = 0
        self.panel_notes = []


# ---------- sessions ----------


def create_session(mode: Mode = "learn") -> Session:
    session = Session(session_id=new_id("ses"), mode=mode)
    save_session(session)
    return session


def _session_row(session_id: str) -> sqlite3.Row | None:
    """The stored session. After a restart SQLite does not have it: then it is restored first."""
    query = "SELECT data FROM sessions WHERE session_id = ?"
    row = _conn().execute(query, (session_id,)).fetchone()
    if row is None and _restore_session(session_id):
        row = _conn().execute(query, (session_id,)).fetchone()
    return row


def get_session(session_id: str) -> Session | None:
    row = _session_row(session_id)
    return Session(**json.loads(row["data"])) if row else None


def save_session(session: Session) -> None:
    data = json.dumps(session.__dict__)
    with write_lock:
        _conn().execute(
            "INSERT INTO sessions (session_id, data) VALUES (?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET data = excluded.data",
            (session.session_id, data),
        )
        # Mirrored inside the lock (here and below), so copies are queued in the order SQLite took the writes.
        durable.put(
            durable.SESSIONS, session.session_id,
            {"session_id": session.session_id, "data": data, "updated_at": now_iso()},
        )


# ---------- transcript ----------


def add_message(session_id: str, actor: ChatActor, text: str, trace_id: str | None = None) -> ChatMessage:
    msg = ChatMessage(id=new_id("msg"), session_id=session_id, actor=actor, text=text, ts=now_iso(), trace_id=trace_id)
    with write_lock:
        cursor = _conn().execute(
            "INSERT INTO messages (id, session_id, actor, text, ts, trace_id) VALUES (?,?,?,?,?,?)",
            (msg.id, msg.session_id, msg.actor, msg.text, msg.ts, msg.trace_id),
        )
        # seq is the order of writing: ts alone cannot order two messages of the same millisecond.
        durable.put(durable.MESSAGES, msg.id, {**msg.model_dump(), "seq": cursor.lastrowid})
    return msg


def transcript(session_id: str, limit: int = 50) -> list[ChatMessage]:
    """The newest `limit` messages, oldest first. Ordered by time, then by order of writing: a
    message can reach SQLite before the older conversation is restored, so rowid alone is not enough."""
    rows = _conn().execute(
        "SELECT * FROM (SELECT rowid AS r, * FROM messages WHERE session_id = ? ORDER BY ts DESC, rowid DESC LIMIT ?)"
        " ORDER BY ts, r",
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
        _mirror_ticket(ticket.id)
    return ticket


def list_tickets() -> list[Ticket]:
    try:
        _load_tickets()
    except MemoryUnavailable:
        pass  # the queue still answers with what SQLite has; the rest comes once the copy answers
    rows = _conn().execute("SELECT * FROM tickets ORDER BY created_at DESC").fetchall()
    return [Ticket(**{k: row[k] for k in Ticket.model_fields}) for row in rows]


def _find_ticket(ticket_id: str) -> sqlite3.Row | None:
    return _conn().execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()


def _ticket_row(ticket_id: str) -> sqlite3.Row | None:
    """The stored ticket. After a restart SQLite may not have it: then it is restored first."""
    row = _find_ticket(ticket_id)
    if row is None and durable.enabled():
        _load_tickets()
        row = _find_ticket(ticket_id)
        if row is None and not _believed_missing(ticket_id):  # not one of the newest: ask for it by id
            ticket = durable.fetch_ticket(ticket_id)
            if ticket is None:
                _remember_missing(ticket_id)
            elif _copy_in(tickets=[ticket]):
                row = _find_ticket(ticket_id)
    return row


def get_ticket(ticket_id: str) -> TicketDetail | None:
    row = _ticket_row(ticket_id)
    if row is None:
        return None
    _session_row(row["session_id"])  # after a restart the transcript comes back with its session
    return TicketDetail(**dict(row), transcript=transcript(row["session_id"]))


def resolve_ticket(ticket_id: str) -> Ticket | None:
    row = _ticket_row(ticket_id)  # after a restart this restores the ticket, so there is a row to change
    if row is None:
        return None
    _session_row(row["session_id"])  # and its session, before anything is written: this may raise
    with write_lock:
        _conn().execute("UPDATE tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
        _mirror_ticket(ticket_id)
    detail = get_ticket(ticket_id)
    return Ticket(**{k: getattr(detail, k) for k in Ticket.model_fields}) if detail else None


def _mirror_ticket(ticket_id: str) -> None:
    """Queue the ticket's whole row, as it now stands, for the durable copy. Call with the write lock held."""
    row = _find_ticket(ticket_id) if durable.enabled() else None
    if row is not None:
        durable.put(durable.TICKETS, ticket_id, dict(row))


# ---------- after a restart: restore from the durable copy ----------


# A browser that still holds an id from before the copy existed asks for it every few seconds.
# Each miss is a network read, so "the copy has no such thing" is believed for a while.


def _believed_missing(key: str) -> bool:
    asked = _not_in_copy.get(key)
    return asked is not None and time.monotonic() - asked < LOOK_AGAIN_SECONDS


def _remember_missing(key: str) -> None:
    if len(_not_in_copy) >= 5_000:  # never grows without limit
        _not_in_copy.clear()
    _not_in_copy[key] = time.monotonic()


def _restore_session(session_id: str) -> bool:
    """SQLite has no such session. If the durable copy does, bring it back in one go with its
    whole transcript and its tickets. True when the session is now in SQLite.

    Raises MemoryUnavailable when any part of the copy could not be read: then nothing is written."""
    if not durable.enabled() or _believed_missing(session_id):
        return False
    doc = durable.fetch_session(session_id)
    if doc is None:
        _remember_missing(session_id)
        return False
    try:
        # Only the fields Session has today: a copy written by an older version may carry others.
        known = {f.name for f in fields(Session)}
        stored = {k: v for k, v in json.loads(doc["data"]).items() if k in known}
        data = json.dumps(Session(**{**stored, "session_id": session_id}).__dict__)
    except Exception:  # noqa: BLE001 - a copy that cannot be parsed is treated as no copy
        log.exception("could not read the durable copy of session %s", session_id)
        _remember_missing(session_id)
        return False
    messages = durable.fetch_messages(session_id)  # both read before anything is written
    tickets = durable.fetch_tickets(RESTORED_TICKETS, session_id)
    return _copy_in(sessions=[(session_id, data)], messages=messages, tickets=tickets)


def _load_tickets() -> None:
    """After a restart the mentor queue is empty: fill it from the durable copy, once per process.
    A failed read raises MemoryUnavailable and is tried again on a later call."""
    global _tickets_loaded
    if _tickets_loaded or not durable.enabled():
        return
    if _copy_in(tickets=durable.fetch_tickets(RESTORED_TICKETS)):
        _tickets_loaded = True


def reset_restore_state() -> None:
    """Forget what this process has already loaded from the durable copy, and past failures.
    Tests use it to act out a restart."""
    global _tickets_loaded
    _tickets_loaded = False
    _not_in_copy.clear()
    durable.reset()


def _copy_in(
    sessions: Iterable[tuple[str, str]] = (), messages: Iterable[dict] = (), tickets: Iterable[dict] = (),
) -> bool:
    """Write restored rows into SQLite in one transaction, under the write lock. They do not go
    through the functions above, so nothing is mirrored back. A row that is already here is kept
    (it is at least as new as its copy), so restoring twice leaves one of each."""
    try:
        inserts = [
            ("sessions", ("session_id", "data"), list(sessions)),
            ("messages", MESSAGE_COLUMNS, [tuple(m.get(c) for c in MESSAGE_COLUMNS) for m in messages]),
            ("tickets", TICKET_COLUMNS, [tuple(t.get(c) for c in TICKET_COLUMNS) for t in tickets]),
        ]
        with write_lock:
            conn = _conn()
            conn.execute("BEGIN")
            with conn:  # commits, or rolls back if a row cannot be written
                for table, columns, rows in inserts:
                    marks = ",".join("?" for _ in columns)
                    conn.executemany(f"INSERT OR IGNORE INTO {table} ({','.join(columns)}) VALUES ({marks})", rows)
        return True
    except Exception:  # noqa: BLE001 - rows that cannot be written are treated as no copy
        log.exception("could not write restored rows into SQLite")
        return False
