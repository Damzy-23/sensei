"""Session routes: create, message (SSE), test runs, state, live trace stream.

With SENSEI_USE_STUBS=1 these serve the Phase 1 stub data; otherwise they call
the orchestrator.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import catalog, stubs
from app.api.sse import sse
from app.config import get_settings
from app.memory import repository as memory
from app.models import (
    ChatMessage, Debrief, FinalEvent, MessageIn, PanelView, RunIn, RunOut, SessionCreated, SessionCreateIn, SessionState,
    TraceEvent,
)
from app.orchestrator import panel
from app.orchestrator import turn as orchestrator
from app.tracing import store

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _stubbed() -> bool:
    return get_settings().use_stubs


def _require_session(session_id: str) -> None:
    exists = stubs.session_exists(session_id) if _stubbed() else memory.get_session(session_id) is not None
    if not exists:
        raise HTTPException(status_code=404, detail="session not found")


def _require_problem(problem_id: str) -> None:
    found = stubs.get_problem(problem_id) if _stubbed() else catalog.find_problem(problem_id)
    if found is None:
        raise HTTPException(status_code=404, detail="problem not found")


@router.post("", status_code=201, response_model=SessionCreated)
async def create_session(body: SessionCreateIn | None = None) -> SessionCreated:
    if _stubbed():
        return SessionCreated(session_id=stubs.create_session())
    return SessionCreated(session_id=memory.create_session(body.mode if body else "learn").session_id)


async def _stub_message_stream(session_id: str) -> AsyncIterator[str]:
    for ev in stubs.stub_turn_events(session_id):
        yield sse("trace", ev)
        await asyncio.sleep(0.05)  # simulate streaming latency
    final: FinalEvent = stubs.stub_final(session_id)
    yield sse("final", final)
    # The picture follows the reply, as it does from the real illustrator.
    for ev in stubs.stub_drawing_events(session_id):
        yield sse("trace", ev)
        await asyncio.sleep(0.05)
    yield sse("drawing", stubs.stub_drawing())


async def _trace_frames(task: asyncio.Task, queue: asyncio.Queue[TraceEvent]) -> AsyncIterator[str]:
    """Forward trace events as they are written, until the task is done and the queue is empty."""
    while not (task.done() and queue.empty()):
        try:
            yield sse("trace", await asyncio.wait_for(queue.get(), timeout=0.1))
        except asyncio.TimeoutError:
            continue


async def _message_stream(session_id: str, body: MessageIn) -> AsyncIterator[str]:
    """Run the turn and forward its trace events as they are written, then the final event.

    A hint coach reply may then get a picture: the illustrator's trace events and one
    `drawing` event follow `final` on the same stream. The reply never waits for them.
    """
    queue = store.subscribe(session_id)
    tasks: list[asyncio.Task] = [asyncio.create_task(orchestrator.run_turn(session_id, body))]
    try:
        async for frame in _trace_frames(tasks[0], queue):
            yield frame
        try:
            result = tasks[0].result()
        except orchestrator.TurnError as exc:
            yield sse("error", {"message": str(exc), "trace_id": exc.trace_id})
            return
        yield sse("final", result.final)
        if result.sketch is None:
            return
        tasks.append(asyncio.create_task(orchestrator.illustrate(result.sketch)))
        async for frame in _trace_frames(tasks[1], queue):
            yield frame
        drawing = tasks[1].result()
        if drawing is not None:
            yield sse("drawing", drawing)
    finally:
        store.unsubscribe(session_id, queue)
        for task in tasks:
            if not task.done():
                task.cancel()


@router.post("/{session_id}/message")
async def post_message(session_id: str, body: MessageIn) -> StreamingResponse:
    _require_session(session_id)
    _require_problem(body.problem_id)
    stream = _stub_message_stream(session_id) if _stubbed() else _message_stream(session_id, body)
    return StreamingResponse(stream, media_type="text/event-stream")


@router.post("/{session_id}/runs", response_model=RunOut)
async def post_run(session_id: str, body: RunIn) -> RunOut:
    _require_session(session_id)
    _require_problem(body.problem_id)
    return stubs.stub_run_out(body) if _stubbed() else orchestrator.run_report(session_id, body)


@router.get("/{session_id}/state", response_model=SessionState)
async def get_state(session_id: str) -> SessionState:
    _require_session(session_id)
    if _stubbed():
        return stubs.stub_state(session_id)
    return orchestrator.state(memory.get_session(session_id))  # type: ignore[arg-type]


@router.get("/{session_id}/mentor-messages", response_model=list[ChatMessage])
async def mentor_messages(session_id: str) -> list[ChatMessage]:
    """Replies a human mentor has sent into this session, oldest first. The student's chat polls this."""
    _require_session(session_id)
    if _stubbed():
        return []
    return [m for m in memory.transcript(session_id, limit=200) if m.actor == "mentor"]


@router.get("/{session_id}/events")
async def session_events(session_id: str, request: Request) -> StreamingResponse:
    """Live trace stream for the agent inspector: stored events first, then new ones as written."""
    _require_session(session_id)

    async def stub_stream() -> AsyncIterator[str]:
        for ev in stubs.stub_trace_events(session_id):
            yield sse("trace", ev)
            await asyncio.sleep(0.02)
        yield sse("end", {"reason": "stub replay complete"})

    async def live_stream() -> AsyncIterator[str]:
        queue = store.subscribe(session_id)
        try:
            for ev in store.load_session_events(session_id):
                yield sse("trace", ev)
            while not await request.is_disconnected():
                try:
                    yield sse("trace", await asyncio.wait_for(queue.get(), timeout=1.0))
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            store.unsubscribe(session_id, queue)

    return StreamingResponse(stub_stream() if _stubbed() else live_stream(), media_type="text/event-stream")


@router.get("/{session_id}/panel", response_model=PanelView)
async def get_panel(session_id: str) -> PanelView:
    """The interview panel's notes so far, and the score each dimension has earned."""
    _require_session(session_id)
    if _stubbed():
        return PanelView(active=False, notes=[], scores=panel.scores([]))
    return panel.view(memory.get_session(session_id))  # type: ignore[arg-type]


@router.post("/{session_id}/debrief", response_model=Debrief)
async def post_debrief(session_id: str) -> Debrief:
    """End the interview: scored feedback written from the observer's notes."""
    _require_session(session_id)
    if _stubbed():
        raise HTTPException(status_code=409, detail="Feedback needs the real agents: set SENSEI_USE_STUBS=0.")
    try:
        return await panel.run_debrief(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except orchestrator.TurnError as exc:
        raise HTTPException(status_code=502, detail={"message": str(exc), "trace_id": exc.trace_id}) from exc
