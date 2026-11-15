"""Sensei FastAPI app.

SSE framing: each message is `event: <name>` + `data: <json>` + blank line.
Event names: `trace` (one per TraceEvent, live), `final` (FinalEvent), `error`, `end`,
and `:` keepalive comments.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app import bank, state, stubs
from app.models import (
    ChatMessage,
    EvalResults,
    FinalEvent,
    MentorReplyIn,
    MessageIn,
    Problem,
    ProblemDetail,
    RunIn,
    RunOut,
    SessionCreated,
    SessionState,
    Ticket,
    TicketDetail,
    TraceTree,
)
from app.eval import winrate
from app.orchestrator.pipeline import handle_message, handle_run
from app.tools import escalation as escalation_tools
from app.tracing import store

app = FastAPI(title="Sensei API", version="0.3.0")

# Open CORS for development (hackathon scope).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def sse(event: str, data: BaseModel | dict) -> str:
    payload = data.model_dump_json() if isinstance(data, BaseModel) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


def _require_session(session_id: str) -> None:
    if state.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")


def _ticket_view(row: dict) -> Ticket:
    return Ticket(
        id=row["id"],
        session_id=row["session_id"],
        problem_id=row["problem_id"],
        status=row["status"],
        stuck_reason=row["stuck_reason"],
        created_at=row["created_at"],
    )


# ---------- sessions ----------


@app.post("/sessions", status_code=201, response_model=SessionCreated)
async def create_session() -> SessionCreated:
    return SessionCreated(session_id=state.create_session())


@app.post("/sessions/{session_id}/message")
async def post_message(session_id: str, body: MessageIn) -> StreamingResponse:
    """Run one turn and stream its trace events live, then the final reply."""
    _require_session(session_id)
    if bank.get_public(body.problem_id) is None:
        raise HTTPException(status_code=404, detail="problem not found")

    queue = store.subscribe(session_id)
    task = asyncio.create_task(handle_message(session_id, body.text, body.problem_id, body.code))

    async def stream() -> AsyncIterator[str]:
        try:
            while not task.done() or not queue.empty():
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                yield sse("trace", ev)
            result = await task
            yield sse("final", FinalEvent(
                reply=result.reply,
                mode=result.mode,  # type: ignore[arg-type]
                hint_level=result.hint_level,
                escalated=result.escalated,
                trace_id=result.trace_id,
            ))
        except Exception as exc:  # noqa: BLE001 - surfaced to the client, not swallowed
            yield sse("error", {"message": f"{type(exc).__name__}: {exc}"})
        finally:
            store.unsubscribe(session_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/sessions/{session_id}/runs", response_model=RunOut)
async def post_run(session_id: str, body: RunIn) -> RunOut:
    _require_session(session_id)
    if bank.get_public(body.problem_id) is None:
        raise HTTPException(status_code=404, detail="problem not found")
    return RunOut(**await handle_run(session_id, body))


@app.get("/sessions/{session_id}/state", response_model=SessionState)
async def get_state(session_id: str) -> SessionState:
    view = state.state_view(session_id)
    if view is None:
        raise HTTPException(status_code=404, detail="session not found")
    return view


@app.get("/sessions/{session_id}/events")
async def session_events(session_id: str, request: Request, follow: bool = True) -> StreamingResponse:
    """Agent inspector feed. Replays stored events, then (if follow=true) streams live ones.

    follow=false replays and ends with `event: end`. Tests and the simulator use it.
    """
    _require_session(session_id)

    async def stream() -> AsyncIterator[str]:
        queue = store.subscribe(session_id) if follow else None
        seen: set[str] = set()
        try:
            for ev in store.load_session_events(session_id):
                seen.add(ev.event_id)
                yield sse("trace", ev)
            if queue is None:
                yield sse("end", {"reason": "replay complete"})
                return
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if ev.event_id not in seen:
                    yield sse("trace", ev)
        finally:
            if queue is not None:
                store.unsubscribe(session_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ---------- problems ----------


@app.get("/problems", response_model=list[Problem])
async def list_problems() -> list[Problem]:
    return bank.list_problems()


@app.get("/problems/{problem_id}", response_model=ProblemDetail)
async def get_problem(problem_id: str) -> ProblemDetail:
    problem = bank.get_public(problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="problem not found")
    return problem


# ---------- traces ----------


@app.get("/traces/{trace_id}", response_model=TraceTree)
async def get_trace(trace_id: str) -> TraceTree:
    events = store.load_trace(trace_id)
    if not events:
        raise HTTPException(status_code=404, detail="trace not found")
    return TraceTree(trace_id=trace_id, session_id=events[0].session_id, roots=store.build_tree(events))


# ---------- mentor ----------


@app.get("/mentor/tickets", response_model=list[Ticket])
async def list_tickets() -> list[Ticket]:
    return [_ticket_view(row) for row in state.list_ticket_rows()]


@app.get("/mentor/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: str) -> TicketDetail:
    row = state.get_ticket_row(ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return TicketDetail(
        **_ticket_view(row).model_dump(),
        transcript=state.list_messages(row["session_id"]),
        latest_code=row["latest_code"],
        suggested_intervention=row["suggested_intervention"],
    )


@app.post("/mentor/tickets/{ticket_id}/reply", response_model=ChatMessage)
async def reply_ticket(ticket_id: str, body: MentorReplyIn) -> ChatMessage:
    if state.get_ticket_row(ticket_id) is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    message_id = escalation_tools.relay_mentor_message(ticket_id, body.text)
    return next(m for m in state.list_messages(state.get_ticket_row(ticket_id)["session_id"]) if m.id == message_id)  # type: ignore[index]


@app.post("/mentor/tickets/{ticket_id}/resolve", response_model=Ticket)
async def resolve_ticket(ticket_id: str) -> Ticket:
    row = state.resolve_ticket_row(ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return _ticket_view(row)


# ---------- eval ----------


@app.get("/eval/results", response_model=EvalResults)
async def eval_results() -> EvalResults:
    """Real results once scripts/run_eval.py has written them; the stub until then."""
    real = winrate.load_results(winrate.RESULTS_DIR / "results.json")
    return real if real is not None else stubs.stub_eval_results()
