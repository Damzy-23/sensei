"""orchestrator actor. State reads and writes, mode selection, routing, escalation entry point."""

from __future__ import annotations

from typing import Any

from app.tracing.registry import tool


@tool("orchestrator", "read_state", "tool.call")
def read_state(session_id: str) -> dict[str, Any]:
    """Load the session state row."""
    raise NotImplementedError("read_state: built in Phase 3")


@tool("orchestrator", "write_state", "tool.call")
def write_state(session_id: str, patch: dict[str, Any]) -> None:
    """Merge a patch into the session state row."""
    raise NotImplementedError("write_state: built in Phase 3")


@tool("orchestrator", "select_mode", "mode.decision")
def select_mode(signals: dict[str, Any]) -> dict[str, Any]:
    """Pure code, no LLM. Returns {mode, decision, reason} from config/policy.yaml rules."""
    raise NotImplementedError("select_mode: built in Phase 5")


@tool("orchestrator", "route_agent", "tool.call")
def route_agent(mode: str, intent: str) -> str:
    """Pick the one agent that handles this message."""
    raise NotImplementedError("route_agent: built in Phase 5")


@tool("orchestrator", "create_escalation", "escalation.created")
def create_escalation(session_id: str, reason: str) -> str:
    """Open a mentor ticket for this session. Returns the ticket id."""
    raise NotImplementedError("create_escalation: built in Phase 5")
