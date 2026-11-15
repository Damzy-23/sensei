"""planner actor. Per-pattern mastery (Elo-style) and next-problem selection."""

from __future__ import annotations

from typing import Any

from app import bank, state
from app.agents import rules
from app.tracing.registry import tool


@tool("planner", "get_mastery", "tool.call")
def get_mastery(session_id: str) -> dict[str, float]:
    """Mastery score per pattern, on [0, 1]."""
    return state.get_mastery(session_id)


@tool("planner", "update_mastery", "tool.call")
def update_mastery(session_id: str, pattern: str, outcome: float, difficulty: str) -> float:
    """Elo-style update after a solve (outcome 1.0) or an abandon (0.0). Returns the new score."""
    current = state.get_mastery(session_id).get(pattern, 0.0)
    updated = rules.elo_update(current, outcome, difficulty)
    state.set_mastery(session_id, pattern, updated)
    return updated


@tool("planner", "query_problem_bank", "tool.call")
def query_problem_bank(pattern: str | None, difficulty: str | None) -> list[dict[str, Any]]:
    """Problems matching the filters, without hidden data."""
    return [p.model_dump() for p in bank.query(pattern=pattern, difficulty=difficulty)]  # type: ignore[arg-type]


@tool("planner", "select_next_problem", "tool.call")
def select_next_problem(session_id: str) -> str:
    """Weakest pattern, at the difficulty that matches the student's mastery there."""
    problems = bank.list_problems()
    patterns = list(dict.fromkeys(p.pattern for p in problems))
    mastery = state.get_mastery(session_id)
    pattern = rules.pick_pattern(mastery, patterns)
    if pattern is None:
        raise LookupError("the problem bank is empty")
    difficulty = rules.target_difficulty(mastery.get(pattern, 0.0))
    candidates = bank.query(pattern=pattern, difficulty=difficulty) or bank.query(pattern=pattern)  # type: ignore[arg-type]
    return candidates[0].id
