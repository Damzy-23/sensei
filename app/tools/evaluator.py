"""evaluator actor. Reads run results, classifies failures, checks complexity."""

from __future__ import annotations

from typing import Any

from app import state
from app.agents import rules
from app.llm.client import call
from app.tracing.registry import tool


@tool("evaluator", "read_run_result", "tool.call")
def read_run_result(session_id: str) -> dict[str, Any]:
    """Latest run for this session, with the failure type classified."""
    rows = state.latest_runs(session_id, limit=1)
    if not rows:
        return {"found": False}
    run = rows[0]
    run["found"] = True
    run["solved"] = run["failed"] == 0 and run["total"] > 0
    run["failure_type"] = None if run["solved"] else rules.classify_failure(run["failures"])
    return run


@tool("evaluator", "analyze_complexity", "tool.call")
async def analyze_complexity(code: str, expected_complexity: str) -> dict[str, Any]:
    """Model call (reasoning model): time and space complexity of the student's code."""
    result = await call(
        "reasoning",
        "You are a precise algorithms reviewer. Reply with JSON only.",
        [{"role": "user", "content": rules.complexity_prompt(code, expected_complexity)}],
        actor="evaluator",
        name="analyze_complexity",
        json_schema={"required": ["time", "space"]},
        max_tokens=300,
    )
    data = result.data or {}
    return {
        "time": str(data.get("time", "unknown")),
        "space": str(data.get("space", "unknown")),
        "feedback": str(data.get("feedback", "")),
    }


@tool("evaluator", "static_check", "tool.call")
def static_check(code: str) -> dict[str, Any]:
    """AST checks: syntax and missing return values. Nothing is executed."""
    issues = rules.static_issues(code)
    return {"ok": not issues, "issues": issues}
