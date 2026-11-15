"""Human-in-the-loop routes: the mentor's escalation queue."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import stubs
from app.models import ChatMessage, MentorReplyIn, Ticket, TicketDetail

router = APIRouter(prefix="/mentor", tags=["mentor"])


@router.get("/tickets", response_model=list[Ticket])
async def list_tickets() -> list[Ticket]:
    return stubs.list_tickets()


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: str) -> TicketDetail:
    ticket = stubs.get_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket


@router.post("/tickets/{ticket_id}/reply", response_model=ChatMessage)
async def reply_ticket(ticket_id: str, body: MentorReplyIn) -> ChatMessage:
    msg = stubs.add_mentor_reply(ticket_id, body.text)
    if msg is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return msg


@router.post("/tickets/{ticket_id}/resolve", response_model=Ticket)
async def resolve_ticket(ticket_id: str) -> Ticket:
    ticket = stubs.resolve_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return ticket
