"""Session routes: create, message (SSE), test runs, state, live trace stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app import stubs
from app.api.sse import sse
from app.models import FinalEvent, MessageIn, RunIn, RunOut, SessionCreated, SessionState

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _require_session(session_id: str) -> None:
    if not stubs.session_exists(session_id):
        raise HTTPException(status_code=404, detail="session not found")


def _require_problem(problem_id: str) -> None:
    if stubs.get_problem(problem_id) is None:
        raise HTTPException(status_code=404, detail="problem not found")


@router.post("", status_code=201, response_model=SessionCreated)
async def create_session() -> SessionCreated:
    return SessionCreated(session_id=stubs.create_session())


@router.post("/{session_id}/message")
async def post_message(session_id: str, body: MessageIn) -> StreamingResponse:
    _require_session(session_id)
    _require_problem(body.problem_id)

    async def stream() -> AsyncIterator[str]:
        for ev in stubs.stub_trace_events(session_id):
            yield sse("trace", ev)
            await asyncio.sleep(0.05)  # simulate streaming latency
        final: FinalEvent = stubs.stub_final(session_id)
        yield sse("final", final)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.post("/{session_id}/runs", response_model=RunOut)
async def post_run(session_id: str, body: RunIn) -> RunOut:
    _require_session(session_id)
    _require_problem(body.problem_id)
    return stubs.stub_run_out(body)


@router.get("/{session_id}/state", response_model=SessionState)
async def get_state(session_id: str) -> SessionState:
    _require_session(session_id)
    return stubs.stub_state(session_id)


@router.get("/{session_id}/events")
async def session_events(session_id: str) -> StreamingResponse:
    """Live trace stream for the agent inspector. Phase 1 stub: replays one turn then ends."""
    _require_session(session_id)

    async def stream() -> AsyncIterator[str]:
        for ev in stubs.stub_trace_events(session_id):
            yield sse("trace", ev)
            await asyncio.sleep(0.02)
        yield sse("end", {"reason": "stub replay complete"})

    return StreamingResponse(stream(), media_type="text/event-stream")
