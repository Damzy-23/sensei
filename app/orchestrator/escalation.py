"""Escalation triggers. Pure code. Returns the reason, or None when the session should continue.

Triggers (from the spec):
  - hint level 5 reached and still failing
  - 3 guard violations (injection blocks)
  - frustration flagged twice
"""

from __future__ import annotations

from dataclasses import dataclass

from app import state
from app.policy import EscalationPolicy, GuardPolicy, load_policy


@dataclass(frozen=True)
class EscalationInputs:
    hint_level: int
    consecutive_failed_runs: int
    guard_violations: int
    frustration_flags: int


def escalation_reason(
    inp: EscalationInputs,
    escalation: EscalationPolicy,
    guard: GuardPolicy,
) -> str | None:
    if inp.hint_level >= escalation.stuck_hint_level and inp.consecutive_failed_runs >= 1:
        return (
            f"stuck: hint level {inp.hint_level} reached and {inp.consecutive_failed_runs} "
            "run(s) still failing"
        )
    if inp.guard_violations >= guard.violation_escalation_count:
        return f"{inp.guard_violations} guard violations (threshold {guard.violation_escalation_count})"
    if inp.frustration_flags >= guard.frustration_escalation_count:
        return f"frustration flagged {inp.frustration_flags} times (threshold {guard.frustration_escalation_count})"
    return None


def escalation_for_session(session_id: str) -> str | None:
    """Apply the triggers to the stored counts. The orchestrator calls this after every turn."""
    record = state.get_session(session_id)
    if record is None:
        return None
    policy = load_policy()
    return escalation_reason(
        EscalationInputs(
            hint_level=record.hint_level,
            consecutive_failed_runs=record.failed_runs,
            guard_violations=record.guard_violations,
            frustration_flags=record.frustration_flags,
        ),
        policy.escalation,
        policy.guard,
    )
