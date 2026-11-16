"""Proctor route: records a reminder the in-browser proctor gave the candidate.

The camera is analysed in the browser and no frame is ever sent here. The only thing this
route accepts is which rule fired and for how long, so that the reminder shows in the Agent
inspector and the Activity log like every other decision. The body has two fields and room
for nothing else: there is no field an image or free text could ride in, and it is capped at
a few hundred bytes before it is parsed.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app import stubs
from app.config import get_settings
from app.memory import repository as memory
from app.models import TraceEvent
from app.tracing import store
from app.tracing.context import new_id, now_iso

router = APIRouter(prefix="/sessions", tags=["proctor"])

MAX_BODY_BYTES = 256  # a reminder is about 50 bytes; an image is not
MAX_SECONDS = 3600.0
EVENTS_PER_MINUTE = 12  # per session. The browser sends at most 6: two rules, 20 s apart each
PROCTORED_MODES = {"interview", "blitz", "call"}


@dataclass(frozen=True)
class Check:
    name: str  # the step name in the trace
    decision: str
    seen: str  # what the detector saw; the duration is appended to make the reason
    said: str  # the reminder, word for word as web/src/proctor/rules.ts speaks it


CHECKS: dict[str, Check] = {
    "eyes_off_screen": Check("eyes_check", "reminded: eyes", "no face facing the screen", "Eyes on the screen, please."),
    "hands_not_visible": Check("hands_check", "reminded: hands", "fewer than two hands in view", "Let me see both hands, please."),
}


class ProctorEventIn(BaseModel):
    """One reminder. Strict and closed: unknown fields and loosely typed values are refused."""

    model_config = ConfigDict(extra="forbid", strict=True)

    rule: Literal["eyes_off_screen", "hands_not_visible"]
    seconds: float = Field(gt=0, le=MAX_SECONDS, allow_inf_nan=False, description="How long the condition had held.")


class ProctorEventOut(BaseModel):
    trace_id: str
    decision: str
    reason: str


_recent: dict[str, deque[float]] = {}


def reset_rate_limit() -> None:
    """Forget recent reminders. For tests."""
    _recent.clear()


def _within_limit(session_id: str) -> bool:
    now = time.monotonic()
    for sid in [sid for sid, calls in _recent.items() if not calls or now - calls[-1] > 60]:
        del _recent[sid]  # sessions that have gone quiet: keeps the table from growing
    calls = _recent.setdefault(session_id, deque())
    while calls and now - calls[0] > 60:
        calls.popleft()
    if len(calls) >= EVENTS_PER_MINUTE:
        return False
    calls.append(now)
    return True


async def _small_body(request: Request) -> bytes:
    """Read the body, giving up as soon as it is larger than a reminder can be."""
    too_large = HTTPException(status_code=413, detail=f"A proctor event is at most {MAX_BODY_BYTES} bytes.")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise too_large
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BODY_BYTES:
            raise too_large
    return body


def _require_proctored_session(session_id: str) -> None:
    if get_settings().use_stubs:
        if not stubs.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return  # stub sessions do not keep their mode
    session = memory.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.mode not in PROCTORED_MODES:
        raise HTTPException(status_code=409, detail="Proctor runs in interview, blitz and call modes only.")


@router.post(
    "/{session_id}/proctor-events", status_code=201, response_model=ProctorEventOut,
    # The body is read by hand so its size can be capped first; this keeps it in the API docs.
    openapi_extra={"requestBody": {"required": True, "content": {"application/json": {"schema": ProctorEventIn.model_json_schema()}}}},
)
async def record_reminder(session_id: str, request: Request) -> ProctorEventOut:
    """Record that the proctor reminded the candidate. Written as a guard decision with its reason."""
    raw = await _small_body(request)
    try:
        body = ProctorEventIn.model_validate_json(raw)
    except ValidationError as exc:
        detail = exc.errors(include_url=False, include_context=False, include_input=False)
        raise HTTPException(status_code=422, detail=detail) from exc
    _require_proctored_session(session_id)
    if not _within_limit(session_id):
        raise HTTPException(status_code=429, detail="Too many proctor events for this session in the last minute.")

    check = CHECKS[body.rule]
    held = f"for {body.seconds:.1f} s"
    reason = f"{check.seen} {held}"
    # One event per reminder, not a whole turn: a reminder every 20 s must not push the student's
    # real turns out of the inspector's replay or fill the activity log with turn.start and turn.end.
    trace_id = new_id("trc")
    store.emit(TraceEvent(
        event_id=new_id("evt"), trace_id=trace_id, span_id=new_id("spn"), parent_span_id=None,
        session_id=session_id, seq=0, ts=now_iso(), actor="proctor", type="guard.input", name=check.name,
        status="ok", latency_ms=None, model=None, tokens_in=None, tokens_out=None, cost_usd=None,
        input=f"{body.rule} {held}", output=check.said, decision=check.decision, reason=reason,
    ))
    return ProctorEventOut(trace_id=trace_id, decision=check.decision, reason=reason)
