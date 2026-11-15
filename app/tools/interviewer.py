"""interviewer actor. Frames the problem and asks follow-ups in Interview and Blitz modes."""

from __future__ import annotations

from typing import Any

from app.tracing.registry import tool


@tool("interviewer", "get_problem", "tool.call")
def get_problem(problem_id: str) -> dict[str, Any]:
    """Public problem view. Never includes the reference solution or hidden tests."""
    raise NotImplementedError("get_problem: built in Phase 3")


@tool("interviewer", "llm_followup", "llm.call")
async def llm_followup(session_id: str, problem_id: str, mode: str) -> str:
    """Model call: one complexity or edge-case follow-up question."""
    raise NotImplementedError("llm_followup: built in Phase 5")


@tool("interviewer", "record_answer", "tool.call")
def record_answer(session_id: str, question: str, answer: str) -> None:
    """Store the student's answer to a follow-up."""
    raise NotImplementedError("record_answer: built in Phase 5")
