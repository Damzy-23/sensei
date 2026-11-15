"""Tool: escalate a session to a human mentor. Human-in-the-loop as a traced call."""

from __future__ import annotations

from app.memory import repository as memory
from app.models import Ticket
from app.tracing.context import span


def escalate_to_mentor(session: memory.Session, rule: str, stuck_reason: str) -> Ticket:
    with span("escalation", "escalation.created", "escalate_to_mentor", stuck_reason) as st:
        last_coach = next((m.text for m in reversed(memory.transcript(session.session_id)) if m.actor == "coach"), "")
        intervention = (
            f"Student is at hint level {session.hint_level} with {session.failed_runs} consecutive failed runs. "
            + (f"Last coach message: {last_coach}" if last_coach else "No coach message yet.")
        )
        ticket = memory.create_ticket(session, stuck_reason, intervention)
        session.escalated = True
        st.decision, st.reason, st.output = "escalated", f"rule {rule}: {stuck_reason}", ticket.id
        return ticket
