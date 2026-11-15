"""Sensei FastAPI app.

SSE framing: each message is `event: <name>` + `data: <json>` + blank line.
Event names: `trace` (one per TraceEvent), `final` (FinalEvent), `end`, and `:` keepalive comments.
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
from app.tools.client import run_tests
from app.tracing import store
from app.tracing.context import turn

app = FastAPI(title="Sensei API", version="0.2.0")

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


# ---------- sessions ----------


@app.post("/sessions", status_code=201, response_model=SessionCreated)
async def create_session() -> SessionCreated:
    return SessionCreated(session_id=state.create_session())


@app.post("/sessions/{session_id}/message")
async def post_message(session_id: str, body: MessageIn) -> StreamingResponse:
    _require_session(session_id)
    if bank.get_public(body.problem_id) is None:
        raise HTTPException(status_code=404, detail="problem not found")

    trace_id = stubs.run_stub_turn(session_id, body.text)
    events = store.load_trace(trace_id)
    final = stubs.stub_final(trace_id, session_id)
    state.update_session(session_id, problem_id=body.problem_id)
    state.add_message(session_id, "student", body.text, trace_id=trace_id)
    state.add_message(session_id, "coach", final.reply, trace_id=trace_id)

    async def stream() -> AsyncIterator[str]:
        for ev in events:
            yield sse("trace", ev)
            await asyncio.sleep(0.05)  # simulate streaming latency
        yield sse("final", final)

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/sessions/{session_id}/runs", response_model=RunOut)
async def post_run(session_id: str, body: RunIn) -> RunOut:
    _require_session(session_id)
    if bank.get_public(body.problem_id) is None:
        raise HTTPException(status_code=404, detail="problem not found")
    with turn(session_id, name="runs"):
        await run_tests(session_id, body)
        return stubs.stub_run_out(body)


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
    return stubs.list_tickets()


@app.get("/mentor/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: str) -> TicketDetail:
    ticket = stubs.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket


@app.post("/mentor/tickets/{ticket_id}/reply", response_model=ChatMessage)
async def reply_ticket(ticket_id: str, body: MentorReplyIn) -> ChatMessage:
    msg = stubs.add_mentor_reply(ticket_id, body.text)
    if msg is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return msg


@app.post("/mentor/tickets/{ticket_id}/resolve", response_model=Ticket)
async def resolve_ticket(ticket_id: str) -> Ticket:
    ticket = stubs.resolve_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket


# ---------- eval ----------


@app.get("/eval/results", response_model=EvalResults)
async def eval_results() -> EvalResults:
    return stubs.stub_eval_results()
