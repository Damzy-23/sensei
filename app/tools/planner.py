"""planner actor. Per-pattern mastery (Elo-style) and next-problem selection."""

from __future__ import annotations

from typing import Any

from app import bank
from app.tracing.registry import tool


@tool("planner", "get_mastery", "tool.call")
def get_mastery(session_id: str) -> dict[str, float]:
    """Mastery score per pattern."""
    raise NotImplementedError("get_mastery: built in Phase 5")


@tool("planner", "update_mastery", "tool.call")
def update_mastery(session_id: str, pattern: str, outcome: float, difficulty: str) -> float:
    """Elo-style update after a solve (outcome 1.0) or an abandon (0.0). Returns the new score."""
    raise NotImplementedError("update_mastery: built in Phase 5")


@tool("planner", "query_problem_bank", "tool.call")
def query_problem_bank(pattern: str | None, difficulty: str | None) -> list[dict[str, Any]]:
    """Problems matching the filters, without hidden data."""
    return [p.model_dump() for p in bank.query(pattern=pattern, difficulty=difficulty)]  # type: ignore[arg-type]


@tool("planner", "select_next_problem", "tool.call")
def select_next_problem(session_id: str) -> str:
    """Weakest pattern near the student's difficulty. Returns a problem id."""
    raise NotImplementedError("select_next_problem: built in Phase 5")
