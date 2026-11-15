"""escalation actor. Mentor tickets: create, notify, relay replies into the student chat."""

from __future__ import annotations

from typing import Any

from app import state
from app.llm.client import call
from app.tracing.context import current_span
from app.tracing.registry import tool


@tool("escalation", "create_ticket", "escalation.created")
async def create_ticket(session_id: str, stuck_reason: str) -> dict[str, Any]:
    """Write a ticket with transcript, latest code, stuck reason and a suggested intervention."""
    record = state.get_session(session_id)
    if record is None:
        raise KeyError(f"unknown session: {session_id}")
    problem_id = record.problem_id or "unknown"
    runs = state.latest_runs(session_id, limit=1)
    latest_code = runs[0]["code"] if runs else ""
    transcript = "\n".join(f"{m.actor}: {m.text}" for m in state.list_messages(session_id)[-12:])

    intervention = "Check in with the student and ask what they have tried so far."
    try:
        result = await call(
            "reasoning",
            "You coach mentors. Reply with JSON only.",
            [{"role": "user", "content": (
                f"A student is stuck on '{problem_id}'. Stuck reason: {stuck_reason}.\n"
                f"Transcript:\n{transcript}\n\nLatest code:\n<<<{latest_code[:1500]}>>>\n\n"
                "Suggest one short, concrete intervention for the mentor. Do not write the solution. "
                "Reply with JSON only: {\"intervention\": \"...\"}."
            )}],
            actor="escalation",
            name="llm_intervention",
            json_schema={"required": ["intervention"]},
            max_tokens=200,
        )
        intervention = str((result.data or {}).get("intervention", intervention))
    except Exception as exc:  # noqa: BLE001 - a ticket must still be created without the model
        st = current_span()
        if st is not None:
            st.output = f"intervention fell back to default: {type(exc).__name__}"

    ticket_id = state.create_ticket(session_id, problem_id, stuck_reason, latest_code, intervention)
    return {"id": ticket_id, "session_id": session_id, "problem_id": problem_id}


@tool("escalation", "notify_mentor", "escalation.created")
def notify_mentor(ticket_id: str) -> None:
    """The mentor dashboard polls open tickets; this records that the ticket is queued."""
    if state.get_ticket_row(ticket_id) is None:
        raise KeyError(f"unknown ticket: {ticket_id}")
    st = current_span()
    if st is not None:
        st.output = f"ticket {ticket_id} queued for the mentor dashboard"


@tool("escalation", "relay_mentor_message", "mentor.message")
def relay_mentor_message(ticket_id: str, text: str) -> str:
    """Insert the mentor reply into the student's chat as actor=mentor. Returns the message id."""
    row = state.get_ticket_row(ticket_id)
    if row is None:
        raise KeyError(f"unknown ticket: {ticket_id}")
    msg = state.add_mentor_message(row["session_id"], text)
    return msg.id
