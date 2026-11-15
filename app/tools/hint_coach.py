"""hint_coach actor. Hint ladder: gating in code, wording from the model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app import state
from app.guards.ladder import decide_unlock
from app.policy import load_policy
from app.tracing.registry import tool


def _seconds_since(iso: str | None) -> float | None:
    if iso is None:
        return None
    then = datetime.fromisoformat(iso)
    return max(0.0, (datetime.now(timezone.utc) - then).total_seconds())


@tool("hint_coach", "get_hint_level", "tool.call")
def get_hint_level(session_id: str) -> int:
    """Current unlocked hint level, 0 to 5."""
    record = state.get_session(session_id)
    if record is None:
        raise KeyError(f"unknown session: {session_id}")
    return record.hint_level


@tool("hint_coach", "unlock_hint", "tool.call")
def unlock_hint(session_id: str, requested: bool) -> dict[str, Any]:
    """Grant level N+1 only if asked AND (a failed run since last unlock OR min_wait elapsed)."""
    record = state.get_session(session_id)
    if record is None:
        raise KeyError(f"unknown session: {session_id}")

    last_unlock = state.last_unlock_at(session_id)
    # Before the first hint, the wait is measured from when the student started the problem.
    since_reference = last_unlock if last_unlock is not None else record.problem_started_at
    decision = decide_unlock(
        record.hint_level,
        requested=requested,
        failed_runs_since_unlock=state.failed_runs_since(session_id, last_unlock),
        seconds_since_last_unlock=_seconds_since(since_reference),
        ladder=load_policy().hint_ladder,
    )
    if decision.granted:
        state.update_session(session_id, hint_level=decision.level, hints_used=record.hints_used + 1)
        state.add_hint(session_id, record.problem_id or "unknown", decision.level)
    return {"granted": decision.granted, "level": decision.level, "reason": decision.reason}


@tool("hint_coach", "llm_hint", "llm.call")
async def llm_hint(session_id: str, problem_id: str, level: int, code: str, last_failure: str) -> str:
    """Model call: Socratic hint at exactly `level`, max 60 words, no solution."""
    raise NotImplementedError("llm_hint: built in Phase 5")
