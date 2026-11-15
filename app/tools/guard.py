"""guard actor. Input and output checks. Logic lives in app/guards/; these tools are the traced entry points."""

from __future__ import annotations

from typing import Any

from app.tracing.registry import tool


@tool("guard", "classify_input", "guard.input")
async def classify_input(session_id: str, text: str) -> dict[str, Any]:
    """Fast-model classifier: ok | answer_request | injection | off_topic | frustration."""
    raise NotImplementedError("classify_input: built in Phase 4")


@tool("guard", "regex_precheck", "guard.input")
def regex_precheck(text: str) -> dict[str, Any]:
    """Rule-based check for injection and solution-reveal phrasing. Runs before the model."""
    raise NotImplementedError("regex_precheck: built in Phase 4")


@tool("guard", "leak_check", "guard.output")
def leak_check(reply: str, level: int, reference_solution: str) -> dict[str, Any]:
    """Code-block rules per level, similarity to the reference, and a model judge."""
    raise NotImplementedError("leak_check: built in Phase 4")


@tool("guard", "policy_check", "guard.output")
def policy_check(reply: str, level: int) -> dict[str, Any]:
    """Length limit and that the reply matches the unlocked hint level."""
    raise NotImplementedError("policy_check: built in Phase 4")
