"""orchestrator actor. State reads and writes, mode selection, routing, escalation entry point."""

from __future__ import annotations

from typing import Any

from app import state
from app.orchestrator.modes import ModeSignals, select_mode as choose_mode
from app.orchestrator.routing import route
from app.policy import load_policy
from app.tools import escalation as escalation_tools
from app.tracing.context import current_span
from app.tracing.registry import tool


@tool("orchestrator", "read_state", "tool.call")
def read_state(session_id: str) -> dict[str, Any]:
    """Load the session state row."""
    record = state.get_session(session_id)
    if record is None:
        raise KeyError(f"unknown session: {session_id}")
    return record.model_dump()


@tool("orchestrator", "write_state", "tool.call")
def write_state(session_id: str, patch: dict[str, Any]) -> None:
    """Merge a patch into the session state row."""
    state.update_session(session_id, **patch)


@tool("orchestrator", "select_mode", "mode.decision")
def select_mode(signals: dict[str, Any]) -> dict[str, Any]:
    """Pure code, no LLM. Returns the mode, the rule that fired, and the signals it read."""
    sig = ModeSignals(
        current_mode=signals["current_mode"],
        consecutive_failed_runs=int(signals["consecutive_failed_runs"]),
        hint_level=int(signals["hint_level"]),
        last_solved=bool(signals["last_solved"]),
        hints_on_solve=int(signals["hints_on_solve"]),
        pattern_mastery=float(signals["pattern_mastery"]),
        solved_streak_under_target=int(signals["solved_streak_under_target"]),
    )
    choice = choose_mode(sig, load_policy().modes)
    st = current_span()
    if st is not None:
        st.decision = choice.mode
        st.reason = f"{choice.rule}: {choice.reason}"
    return {"mode": choice.mode, "rule": choice.rule, "reason": choice.reason, "signals": choice.signals}


@tool("orchestrator", "route_agent", "tool.call")
def route_agent(mode: str, intent: str) -> str:
    """Pick the one agent that handles this message."""
    return route(intent)  # type: ignore[arg-type]


@tool("orchestrator", "create_escalation", "escalation.created")
async def create_escalation(session_id: str, reason: str) -> str:
    """Open a mentor ticket for this session and mark the session escalated. Returns the ticket id."""
    ticket = await escalation_tools.create_ticket(session_id, reason)
    escalation_tools.notify_mentor(ticket["id"])
    state.update_session(session_id, escalated=True)
    return ticket["id"]




__all__ = ["read_state", "write_state", "select_mode", "route_agent", "create_escalation", "escalation_for", "Intent"]
