"""Activity log: the agents' actions with a per-agent summary.

A mentor sees every session. Anyone else sees the sessions they hold, and beside them
the whole system's totals as bare numbers (see app/api/auth.py for who holds what).
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app import stubs
from app.api.auth import Viewer, current_viewer, scope_enforced
from app.config import get_settings
from app.models import TraceEvent
from app.tracing import store

router = APIRouter(prefix="/logs", tags=["logs"])
log = logging.getLogger(__name__)

FILTER_WINDOW = 1000  # events read when a filter is on, so the filtered list is not cut short
OWN_WINDOW = 1000  # a visitor's own sessions are read whole, up to this many events
STUB_SESSION = "ses_demo_0001"
STUB_SESSIONS_SHOWN = 150  # more sample turns than the largest `limit` can return


class ActorSummary(BaseModel):
    actor: str
    events: int
    model_calls: int
    tool_calls: int
    blocked: int
    errors: int
    tokens_in: int
    tokens_out: int
    cost_usd: float


class Totals(BaseModel):
    """What the whole system has done. Numbers only: this model has no field that could
    carry a message, code or an id, so it is safe to return to any visitor."""

    events: int
    model_calls: int
    tool_calls: int
    cost_usd: float


class ActivityLog(BaseModel):
    events: list[TraceEvent]
    summary: list[ActorSummary]
    durable: bool  # True when read from the Firestore archive
    scope: Literal["all", "own"]  # whose sessions `events` and `summary` cover
    totals_all: Totals | None  # every session, whatever the scope; null if it could not be read


def summarise(events: list[TraceEvent]) -> list[ActorSummary]:
    by_actor: dict[str, ActorSummary] = {}
    for ev in events:
        s = by_actor.setdefault(ev.actor, ActorSummary(actor=ev.actor, events=0, model_calls=0, tool_calls=0,
                                                        blocked=0, errors=0, tokens_in=0, tokens_out=0, cost_usd=0.0))
        s.events += 1
        s.model_calls += ev.type == "llm.call"
        s.tool_calls += ev.type.startswith("tool")
        s.blocked += ev.status == "blocked"
        s.errors += ev.status == "error"
        s.tokens_in += ev.tokens_in or 0
        s.tokens_out += ev.tokens_out or 0
        s.cost_usd += ev.cost_usd or 0.0
    return sorted(by_actor.values(), key=lambda s: s.events, reverse=True)


def _count(events: list[TraceEvent]) -> Totals:
    return Totals(
        events=len(events),
        model_calls=sum(ev.type == "llm.call" for ev in events),
        tool_calls=sum(ev.type.startswith("tool") for ev in events),
        cost_usd=sum(ev.cost_usd or 0.0 for ev in events),
    )


def _stored_totals() -> Totals | None:
    """The totals are an extra on the page: if they cannot be read, the log is still served."""
    try:
        return Totals(**store.totals())
    except Exception:  # noqa: BLE001
        log.exception("could not read the activity totals")
        return None


def _stub_turn(session_id: str) -> list[TraceEvent]:
    """The sample turn as one session's own, newest first. Stub mode stores no events: every
    session replays the same turn, as its inspector does. Event ids are made unique per
    session, so two sessions' rows are never taken for the same row."""
    events = list(reversed(stubs.stub_trace_events(session_id)))
    if session_id == STUB_SESSION:
        return events
    return [ev.model_copy(update={"event_id": f"{ev.event_id}_{session_id[4:]}"}) for ev in events]


def _stub_log(viewer: Viewer, scoped: bool) -> tuple[list[TraceEvent], Totals]:
    if not scoped:
        events = _stub_turn(STUB_SESSION)
        return events, _count(events)
    every = [STUB_SESSION, *reversed(stubs.session_ids())]
    shown = every if viewer.sees_all else [s for s in viewer.sessions if s in every]
    one = _count(_stub_turn(STUB_SESSION))
    totals = Totals(events=one.events * len(every), model_calls=one.model_calls * len(every),
                    tool_calls=one.tool_calls * len(every), cost_usd=one.cost_usd * len(every))
    return [ev for s in shown[:STUB_SESSIONS_SHOWN] for ev in _stub_turn(s)], totals


@router.get("", response_model=ActivityLog)
async def activity_log(
    actor: str | None = None,
    type: str | None = Query(default=None, description="Event type prefix, e.g. llm, tool, guard"),
    session_id: str | None = Query(default=None, description="Narrows the list. It never widens what the caller may see."),
    limit: int = Query(default=300, ge=1, le=1000),
    viewer: Viewer = Depends(current_viewer),
) -> ActivityLog:
    from app.tracing import archive

    stubbed = get_settings().use_stubs
    if stubbed:
        events, totals_all = _stub_log(viewer, scope_enforced())
    else:
        if viewer.sees_all:
            events = store.recent_events(limit if not (actor or type or session_id) else FILTER_WINDOW)
        else:  # only the caller's sessions are read, so nobody else's event is in hand to leak
            events = store.events_for_sessions(viewer.sessions, OWN_WINDOW)
        totals_all = _stored_totals()
    summary = summarise(events)
    if actor:
        events = [e for e in events if e.actor == actor]
    if type:
        events = [e for e in events if e.type.startswith(type)]
    if session_id:
        events = [e for e in events if e.session_id == session_id]
    return ActivityLog(
        events=events[:limit], summary=summary, durable=archive.enabled() and not stubbed,
        scope="all" if viewer.sees_all else "own", totals_all=totals_all,
    )
