"""hint_coach actor. Hint ladder: gating in code, wording from the model."""

from __future__ import annotations

from typing import Any

from app.tracing.registry import tool


@tool("hint_coach", "get_hint_level", "tool.call")
def get_hint_level(session_id: str) -> int:
    """Current unlocked hint level, 0 to 5."""
    raise NotImplementedError("get_hint_level: built in Phase 4")


@tool("hint_coach", "unlock_hint", "tool.call")
def unlock_hint(session_id: str, requested: bool) -> dict[str, Any]:
    """Grant level N+1 only if asked AND (a failed run since last unlock OR min_wait elapsed)."""
    raise NotImplementedError("unlock_hint: built in Phase 4")


@tool("hint_coach", "llm_hint", "llm.call")
async def llm_hint(session_id: str, problem_id: str, level: int, code: str, last_failure: str) -> str:
    """Model call: Socratic hint at exactly `level`, max 60 words, no solution."""
    raise NotImplementedError("llm_hint: built in Phase 5")
