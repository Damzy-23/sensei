"""Event store: one `events` table, live fan-out to SSE subscribers, and tree building."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Sequence

from app.db import get_conn, write_lock
from app.tracing import archive
from app.models import TraceEvent, TraceNode

COLUMNS: list[str] = list(TraceEvent.model_fields)
_SUBSCRIBERS: dict[str, set[asyncio.Queue[TraceEvent]]] = defaultdict(set)


class TraceValidationError(ValueError):
    """Raised when a guard or mode event is written without a decision and reason."""


def validate(ev: TraceEvent) -> None:
    # Decision events only: a guard's own model call is an llm.call and carries usage, not a verdict.
    needs_reason = ev.type in {"guard.input", "guard.output", "mode.decision"}
    if needs_reason and ev.status != "error" and (not ev.decision or not ev.reason):
        raise TraceValidationError(f"{ev.type} '{ev.name}' must include decision and reason")


def emit(ev: TraceEvent) -> None:
    """Validate, persist, then push to live subscribers of the session."""
    validate(ev)
    values = [getattr(ev, c) for c in COLUMNS]
    placeholders = ",".join("?" for _ in COLUMNS)
    with write_lock:
        get_conn().execute(f"INSERT INTO events ({','.join(COLUMNS)}) VALUES ({placeholders})", values)
    archive.mirror(ev)
    for queue in tuple(_SUBSCRIBERS.get(ev.session_id, ())):
        try:
            queue.put_nowait(ev)
        except asyncio.QueueFull:
            pass  # slow inspector: drop the live copy; the event is still in the table


def subscribe(session_id: str) -> asyncio.Queue[TraceEvent]:
    queue: asyncio.Queue[TraceEvent] = asyncio.Queue(maxsize=1000)
    _SUBSCRIBERS[session_id].add(queue)
    return queue


def unsubscribe(session_id: str, queue: asyncio.Queue[TraceEvent]) -> None:
    subscribers = _SUBSCRIBERS.get(session_id)
    if subscribers is None:
        return
    subscribers.discard(queue)
    if not subscribers:
        _SUBSCRIBERS.pop(session_id, None)


def load_trace(trace_id: str) -> list[TraceEvent]:
    rows = get_conn().execute("SELECT * FROM events WHERE trace_id = ? ORDER BY rowid", (trace_id,)).fetchall()
    return [TraceEvent(**dict(row)) for row in rows]


def load_session_events(session_id: str, limit: int = 200) -> list[TraceEvent]:
    """The most recent `limit` events of a session, oldest first."""
    rows = get_conn().execute(
        "SELECT * FROM events WHERE session_id = ? ORDER BY rowid DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [TraceEvent(**dict(row)) for row in reversed(rows)]


def recent_events(limit: int = 500) -> list[TraceEvent]:
    """Across all sessions, newest first: from Firestore when archiving is on (it outlives
    restarts), otherwise from the local table."""
    if archive.enabled():
        return archive.recent(limit)
    rows = get_conn().execute("SELECT * FROM events ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
    return [TraceEvent(**dict(row)) for row in rows]


def events_for_sessions(session_ids: Sequence[str], limit: int = 500) -> list[TraceEvent]:
    """The newest `limit` events of these sessions, newest first. The query names the
    sessions, so no other session's event is ever loaded, however busy the log is."""
    if not session_ids:
        return []
    if archive.enabled():
        return archive.for_sessions(list(session_ids), limit)
    marks = ",".join("?" for _ in session_ids)
    rows = get_conn().execute(
        f"SELECT * FROM events WHERE session_id IN ({marks}) ORDER BY rowid DESC LIMIT ?",
        (*session_ids, limit),
    ).fetchall()
    return [TraceEvent(**dict(row)) for row in rows]


def totals() -> dict[str, float]:
    """How much the whole system has done, over every stored event of every session.
    Counts and spend only: no text and no ids, so it is safe to show to anyone."""
    if archive.enabled():
        return archive.totals()
    row = get_conn().execute(
        "SELECT COUNT(*) AS events, COALESCE(SUM(type = 'llm.call'), 0) AS model_calls, "
        "COALESCE(SUM(type LIKE 'tool%'), 0) AS tool_calls, COALESCE(SUM(cost_usd), 0.0) AS cost_usd FROM events"
    ).fetchone()
    return dict(row)


def build_tree(events: list[TraceEvent]) -> list[TraceNode]:
    """Build the span tree. A span can emit a start and an end event; the node shows the
    last event for that span (final status and latency)."""
    last: dict[str, TraceEvent] = {}
    order: list[str] = []
    for ev in events:
        if ev.span_id not in last:
            order.append(ev.span_id)
        last[ev.span_id] = ev

    nodes = {span_id: TraceNode(event=last[span_id]) for span_id in order}
    roots: list[TraceNode] = []
    for span_id in order:
        parent = last[span_id].parent_span_id
        if parent is not None and parent in nodes:
            nodes[parent].children.append(nodes[span_id])
        else:
            roots.append(nodes[span_id])
    return roots
