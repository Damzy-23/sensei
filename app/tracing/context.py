"""Span context. trace_id and parent_span_id travel in contextvars, so nested and async
calls link up without passing ids around.

Usage:
    async with ...            (nothing special)
    with turn(session_id):    one per student message (or /runs request)
        with span(actor, event_type, name, input_text) as st:
            st.decision, st.reason, st.model, st.tokens_in, ...  # set inside the block

A span emits one event when it finishes. turn() emits turn.start on entry and turn.end on exit.
follow_up() re-enters a finished turn's trace for work that runs after the reply was sent.
If a span runs with no active turn it goes into an "offline" trace.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import Actor, EventStatus, EventType, TraceEvent
from app.tracing import prices, redact, store


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


@dataclass
class TraceCtx:
    trace_id: str
    session_id: str
    seq: int = 0
    root_span_id: str | None = None  # the turn's own span: what follow_up() hangs later work under

    def next_seq(self) -> int:
        self.seq += 1
        return self.seq


@dataclass
class SpanState:
    span_id: str
    parent_span_id: str | None
    actor: Actor
    event_type: EventType
    name: str
    input: str | None = None
    output: str | None = None
    status: EventStatus = "ok"
    decision: str | None = None
    reason: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: float | None = None  # set for priced calls that are not token-based (e.g. a web search)


_trace: ContextVar[TraceCtx | None] = ContextVar("sensei_trace", default=None)
_current: ContextVar[SpanState | None] = ContextVar("sensei_span", default=None)


def current_trace() -> TraceCtx | None:
    return _trace.get()


def current_span() -> SpanState | None:
    return _current.get()


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)


def _emit(tctx: TraceCtx, st: SpanState, event_type: EventType, latency_ms: float | None) -> None:
    if st.status == "error" and not st.decision:
        st.decision = "error"
        st.reason = st.reason or st.output or "error"
    ev = TraceEvent(
        event_id=new_id("evt"),
        trace_id=tctx.trace_id,
        span_id=st.span_id,
        parent_span_id=st.parent_span_id,
        session_id=tctx.session_id,
        seq=tctx.next_seq(),
        ts=now_iso(),
        actor=st.actor,
        type=event_type,
        name=st.name,
        status=st.status,
        latency_ms=latency_ms,
        model=st.model,
        tokens_in=st.tokens_in,
        tokens_out=st.tokens_out,
        cost_usd=st.cost_usd if st.cost_usd is not None else prices.cost_usd(st.model, st.tokens_in, st.tokens_out),
        input=redact.sanitize(st.input),
        output=redact.sanitize(st.output),
        decision=redact.sanitize(st.decision),
        reason=redact.sanitize(st.reason),
    )
    store.emit(ev)


@contextmanager
def turn(session_id: str, name: str = "turn") -> Iterator[TraceCtx]:
    """Open a trace for one student message (or one /runs request)."""
    tctx = TraceCtx(trace_id=new_id("trc"), session_id=session_id)
    trace_token = _trace.set(tctx)
    root = SpanState(
        span_id=new_id("spn"),
        parent_span_id=None,
        actor="orchestrator",
        event_type="turn.end",
        name=name,
    )
    tctx.root_span_id = root.span_id
    _emit(tctx, root, "turn.start", None)
    span_token = _current.set(root)
    start = time.perf_counter()
    try:
        yield tctx
    except BaseException as exc:
        root.status = "error"
        root.output = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _current.reset(span_token)
        try:
            _emit(tctx, root, "turn.end", _ms(start))
        finally:
            _trace.reset(trace_token)


@contextmanager
def follow_up(tctx: TraceCtx) -> Iterator[TraceCtx]:
    """Re-enter a turn's trace after it has ended, for work that must not hold up the reply.

    Spans opened inside join the same trace under the turn's span, numbered after turn.end,
    so the inspector shows them with the turn they belong to. Emits no event of its own:
    turn.end has already recorded when the reply was ready.
    """
    root = SpanState(
        span_id=tctx.root_span_id or new_id("spn"),
        parent_span_id=None,
        actor="orchestrator",
        event_type="turn.end",
        name="turn",
    )
    trace_token = _trace.set(tctx)
    span_token = _current.set(root)
    try:
        yield tctx
    finally:
        _current.reset(span_token)
        _trace.reset(trace_token)


@contextmanager
def span(actor: Actor, event_type: EventType, name: str, input_text: str | None = None) -> Iterator[SpanState]:
    """Record one unit of work as a span under the current parent."""
    tctx = _trace.get()
    trace_token = None
    if tctx is None:
        tctx = TraceCtx(trace_id=new_id("trc"), session_id="offline")
        trace_token = _trace.set(tctx)

    parent = _current.get()
    st = SpanState(
        span_id=new_id("spn"),
        parent_span_id=parent.span_id if parent is not None else None,
        actor=actor,
        event_type=event_type,
        name=name,
        input=input_text,
    )
    span_token = _current.set(st)
    start = time.perf_counter()
    try:
        yield st
    except BaseException as exc:
        st.status = "error"
        st.output = st.output or f"{type(exc).__name__}: {exc}"
        raise
    finally:
        _current.reset(span_token)
        try:
            _emit(tctx, st, event_type, _ms(start))
        finally:
            if trace_token is not None:
                _trace.reset(trace_token)
