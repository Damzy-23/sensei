"""Human-in-the-loop routes: the mentor's escalation queue.

A mentor works the whole queue. Anyone else sees, and may answer, only the tickets of
the sessions they hold (see app/api/auth.py). Someone else's ticket answers 404, the
same as a ticket that does not exist, so ticket ids cannot be probed.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import stubs
from app.api.auth import Viewer, current_viewer
from app.config import get_settings
from app.memory import repository as memory
from app.models import ChatMessage, MentorReplyIn, Ticket, TicketDetail
from app.tracing.context import span, turn

router = APIRouter(prefix="/mentor", tags=["mentor"])


class QueueScope(BaseModel):
    scope: Literal["all", "own"]  # whose tickets this caller's queue holds


def _stubbed() -> bool:
    return get_settings().use_stubs


def _found(item):  # noqa: ANN001, ANN202
    if item is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    return item


def _ticket(ticket_id: str, viewer: Viewer) -> TicketDetail:
    """The ticket, if it exists and this viewer may see it. Checked before any write."""
    ticket = stubs.get_ticket(ticket_id) if _stubbed() else memory.get_ticket(ticket_id)
    return _found(ticket if ticket is not None and viewer.can_see(ticket.session_id) else None)


@router.get("/scope", response_model=QueueScope)
async def queue_scope(viewer: Viewer = Depends(current_viewer)) -> QueueScope:
    """Lets the Mentor screen say whether it shows the whole queue or the caller's own tickets."""
    return QueueScope(scope="all" if viewer.sees_all else "own")


@router.get("/tickets", response_model=list[Ticket])
async def list_tickets(viewer: Viewer = Depends(current_viewer)) -> list[Ticket]:
    tickets = stubs.list_tickets() if _stubbed() else memory.list_tickets()
    return [t for t in tickets if viewer.can_see(t.session_id)]


@router.get("/tickets/{ticket_id}", response_model=TicketDetail)
async def get_ticket(ticket_id: str, viewer: Viewer = Depends(current_viewer)) -> TicketDetail:
    return _ticket(ticket_id, viewer)


@router.post("/tickets/{ticket_id}/reply", response_model=ChatMessage)
async def reply_ticket(ticket_id: str, body: MentorReplyIn, viewer: Viewer = Depends(current_viewer)) -> ChatMessage:
    ticket = _ticket(ticket_id, viewer)
    if _stubbed():
        return _found(stubs.add_mentor_reply(ticket_id, body.text))
    with turn(ticket.session_id, name="mentor_reply") as trace:
        with span("mentor", "mentor.message", "mentor_reply", body.text) as st:
            st.decision, st.reason = "replied", f"human mentor answered ticket {ticket_id}"
            return memory.add_message(ticket.session_id, "mentor", body.text, trace.trace_id)


@router.post("/tickets/{ticket_id}/resolve", response_model=Ticket)
async def resolve_ticket(ticket_id: str, viewer: Viewer = Depends(current_viewer)) -> Ticket:
    _ticket(ticket_id, viewer)
    if _stubbed():
        return _found(stubs.resolve_ticket(ticket_id))
    ticket = _found(memory.resolve_ticket(ticket_id))
    session = memory.get_session(ticket.session_id)
    if session is not None:
        session.release_from_mentor()
        memory.save_session(session)
    return ticket
