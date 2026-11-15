"""Event store: one `events` table, live fan-out to SSE subscribers, and tree building."""

from __future__ import annotations

import asyncio
from collections import defaultdict

from app.db import get_conn, write_lock
from app.models import TraceEvent, TraceNode

COLUMNS: list[str] = list(TraceEvent.model_fields)
_SUBSCRIBERS: dict[str, set[asyncio.Queue[TraceEvent]]] = defaultdict(set)


class TraceValidationError(ValueError):
    """Raised when a guard or mode event is written without a decision and reason."""


def validate(ev: TraceEvent) -> None:
    needs_reason = ev.actor == "guard" or ev.type == "mode.decision"
    if needs_reason and ev.status != "error" and (not ev.decision or not ev.reason):
        raise TraceValidationError(f"{ev.type} '{ev.name}' must include decision and reason")


def emit(ev: TraceEvent) -> None:
    """Validate, persist, then push to live subscribers of the session."""
    validate(ev)
    values = [getattr(ev, c) for c in COLUMNS]
    placeholders = ",".join("?" for _ in COLUMNS)
    with write_lock:
        get_conn().execute(f"INSERT INTO events ({','.join(COLUMNS)}) VALUES ({placeholders})", values)
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
    rows = get_conn().execute(
        "SELECT * FROM events WHERE session_id = ? ORDER BY rowid DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [TraceEvent(**dict(row)) for row in reversed(rows)]  # oldest first


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
