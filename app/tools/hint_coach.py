"""hint_coach actor. Hint ladder: gating in code, wording from the model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app import bank, state
from app.agents import rules
from app.config import get_settings
from app.guards.ladder import decide_unlock
from app.llm.client import call
from app.llm.models import ModelNotConfigured, resolve
from app.policy import load_policy
from app.tracing.context import current_span
from app.tracing.registry import tool


def _seconds_since(iso: str | None) -> float | None:
    if iso is None:
        return None
    then = datetime.fromisoformat(iso)
    return max(0.0, (datetime.now(timezone.utc) - then).total_seconds())


def _hint_model() -> tuple[str, str | None]:
    """HINT_MODEL=tuned uses the fine-tuned endpoint when configured, otherwise base (logged)."""
    if get_settings().hint_model != "tuned":
        return "hint_base", None
    try:
        resolve("hint_tuned")
        return "hint_tuned", None
    except ModelNotConfigured as exc:
        return "hint_base", f"tuned unavailable ({exc}); using base"


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


@tool("hint_coach", "llm_hint", "tool.call")
async def llm_hint(
    session_id: str,
    problem_id: str,
    level: int,
    code: str,
    last_failure: str,
    stricter: bool = False,
) -> dict[str, Any]:
    """Model call: Socratic hint at exactly `level`, max 60 words, no solution.

    Returns the model's own {level, hint}; the output guard checks that the level matches.
    """
    public = bank.get_public(problem_id)
    if public is None:
        raise KeyError(f"unknown problem: {problem_id}")
    policy = load_policy()
    seed = bank.get_hint_seeds(problem_id)[level]
    model_key, note = _hint_model()
    st = current_span()
    if st is not None and note:
        st.output = note

    result = await call(
        model_key,
        rules.hint_system_prompt(level, policy.hint_ladder.levels[level], seed, stricter),
        [{"role": "user", "content": rules.hint_user_prompt(public.title, public.statement, code, last_failure, level)}],
        actor="hint_coach",
        name="llm_hint",
        json_schema={"required": ["level", "hint"]},
        max_tokens=300,
    )
    data = result.data or {}
    try:
        reported_level = int(data.get("level", -1))
    except (TypeError, ValueError):
        reported_level = -1
    return {"level": reported_level, "hint": str(data.get("hint", ""))}
