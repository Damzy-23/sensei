"""Activity log: every agent action across all sessions, with a per-agent summary."""

from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app import stubs
from app.config import get_settings
from app.models import TraceEvent
from app.tracing import store

router = APIRouter(prefix="/logs", tags=["logs"])


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


class ActivityLog(BaseModel):
    events: list[TraceEvent]
    summary: list[ActorSummary]
    durable: bool  # True when read from the Firestore archive


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


@router.get("", response_model=ActivityLog)
async def activity_log(
    actor: str | None = None,
    type: str | None = Query(default=None, description="Event type prefix, e.g. llm, tool, guard"),
    session_id: str | None = None,
    limit: int = Query(default=300, ge=1, le=1000),
) -> ActivityLog:
    from app.tracing import archive

    if get_settings().use_stubs:
        events = list(reversed(stubs.stub_trace_events("ses_demo_0001")))
    else:
        events = store.recent_events(limit if not (actor or type or session_id) else 1000)
    summary = summarise(events)
    if actor:
        events = [e for e in events if e.actor == actor]
    if type:
        events = [e for e in events if e.type.startswith(type)]
    if session_id:
        events = [e for e in events if e.session_id == session_id]
    return ActivityLog(events=events[:limit], summary=summary, durable=archive.enabled() and not get_settings().use_stubs)
