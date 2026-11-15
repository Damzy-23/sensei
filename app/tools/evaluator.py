"""evaluator actor. Reads run results, classifies failures, checks complexity."""

from __future__ import annotations

from typing import Any

from app.tracing.registry import tool


@tool("evaluator", "read_run_result", "tool.call")
def read_run_result(session_id: str) -> dict[str, Any]:
    """Latest run for this session, with failure classification."""
    raise NotImplementedError("read_run_result: built in Phase 5")


@tool("evaluator", "analyze_complexity", "llm.call")
async def analyze_complexity(code: str, expected_complexity: str) -> dict[str, Any]:
    """Model call (reasoning model): time and space complexity of the student's code."""
    raise NotImplementedError("analyze_complexity: built in Phase 5")


@tool("evaluator", "static_check", "tool.call")
def static_check(code: str) -> dict[str, Any]:
    """AST checks: syntax, missing return, unused names. No execution."""
    raise NotImplementedError("static_check: built in Phase 5")
