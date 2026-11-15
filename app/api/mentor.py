"""Human-in-the-loop routes: the mentor's escalation queue."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import stubs
from app.config import get_settings
from app.memory import repository as memory
from app.models import ChatMessage, MentorReplyIn, Ticket, TicketDetail
from app.tracing.context import span, turn

router = APIRouter(prefix="/mentor", tags=["mentor"])


def _stubbed() -> bool:
    return get_settings().use_stubs


def _found(item):  # noqa: ANN001, ANN202
    if item is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return item


@router.get("/tickets", response_model=list[Ticket])
async def list_tickets() -> list[Ticket]:
    return stubs.list_tickets() if _stubbed() else memory.list_tickets()


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: str) -> TicketDetail:
    return _found(stubs.get_ticket(ticket_id) if _stubbed() else memory.get_ticket(ticket_id))


@router.post("/tickets/{ticket_id}/reply", response_model=ChatMessage)
async def reply_ticket(ticket_id: str, body: MentorReplyIn) -> ChatMessage:
    if _stubbed():
        return _found(stubs.add_mentor_reply(ticket_id, body.text))
    ticket = _found(memory.get_ticket(ticket_id))
    with turn(ticket.session_id, name="mentor_reply") as trace:
        with span("mentor", "mentor.message", "mentor_reply", body.text) as st:
            st.decision, st.reason = "replied", f"human mentor answered ticket {ticket_id}"
            return memory.add_message(ticket.session_id, "mentor", body.text, trace.trace_id)


@router.post("/tickets/{ticket_id}/resolve", response_model=Ticket)
async def resolve_ticket(ticket_id: str) -> Ticket:
    if _stubbed():
        return _found(stubs.resolve_ticket(ticket_id))
    ticket = _found(memory.resolve_ticket(ticket_id))
    session = memory.get_session(ticket.session_id)
    if session is not None:
        session.release_from_mentor()
        memory.save_session(session)
    return ticket
