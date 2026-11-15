"""escalation actor. Mentor tickets: create, notify, relay replies into the student chat."""

from __future__ import annotations

from typing import Any

from app.tracing.registry import tool


@tool("escalation", "create_ticket", "escalation.created")
def create_ticket(session_id: str, stuck_reason: str) -> dict[str, Any]:
    """Write a ticket with transcript, latest code, stuck reason and a suggested intervention."""
    raise NotImplementedError("create_ticket: built in Phase 5")


@tool("escalation", "notify_mentor", "escalation.created")
def notify_mentor(ticket_id: str) -> None:
    """Notify the mentor dashboard that a ticket is waiting."""
    raise NotImplementedError("notify_mentor: built in Phase 5")


@tool("escalation", "relay_mentor_message", "mentor.message")
def relay_mentor_message(ticket_id: str, text: str) -> str:
    """Insert the mentor reply into the student's chat as actor=mentor. Returns the message id."""
    raise NotImplementedError("relay_mentor_message: built in Phase 5")
