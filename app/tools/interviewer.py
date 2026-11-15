"""interviewer actor. Frames the problem and asks follow-ups in Interview and Blitz modes."""

from __future__ import annotations

from typing import Any

from app import bank, state
from app.agents import rules
from app.llm.client import call
from app.tracing.registry import tool


@tool("interviewer", "get_problem", "tool.call")
def get_problem(problem_id: str) -> dict[str, Any]:
    """Public problem view. Never includes the reference solution or hidden tests."""
    view = bank.get_public(problem_id)
    if view is None:
        raise KeyError(f"unknown problem: {problem_id}")
    return view.model_dump()


@tool("interviewer", "llm_followup", "tool.call")
async def llm_followup(session_id: str, problem_id: str, mode: str) -> str:
    """Model call: one complexity or edge-case follow-up question."""
    public = bank.get_public(problem_id)
    if public is None:
        raise KeyError(f"unknown problem: {problem_id}")
    result = await call(
        "fast",
        "You are a calm technical interviewer. Reply with JSON only.",
        [{"role": "user", "content": rules.followup_prompt(public.title, mode)}],
        actor="interviewer",
        name="llm_followup",
        json_schema={"required": ["question"]},
        max_tokens=120,
    )
    return str((result.data or {}).get("question", "")).strip()


@tool("interviewer", "record_answer", "tool.call")
def record_answer(session_id: str, question: str, answer: str) -> None:
    """Store the student's answer to a follow-up. The question itself is stored by the orchestrator."""
    state.add_message(session_id, "student", answer)
