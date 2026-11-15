"""Hint ladder gating. Pure functions: no I/O, no model calls.

Rules (from the spec):
  - Level N+1 is granted only if the student asked for a hint.
  - AND (at least one failed run since the last unlock OR min_wait_seconds have passed).
  - A level can never be skipped: a grant always moves exactly one level up.
  - Level max_level is the end of the ladder.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.policy import HintLadderPolicy


@dataclass(frozen=True)
class UnlockDecision:
    granted: bool
    level: int  # the level after this decision (unchanged if not granted)
    reason: str


def decide_unlock(
    current_level: int,
    *,
    requested: bool,
    failed_runs_since_unlock: int,
    seconds_since_last_unlock: float | None,
    ladder: HintLadderPolicy,
) -> UnlockDecision:
    if current_level >= ladder.max_level:
        return UnlockDecision(False, current_level, f"already at the last level ({ladder.max_level})")
    if not requested:
        return UnlockDecision(False, current_level, "student did not ask for a hint")

    next_level = current_level + 1
    if failed_runs_since_unlock >= 1:
        return UnlockDecision(True, next_level, f"unlocked level {next_level}: failed run since last unlock")
    if seconds_since_last_unlock is not None and seconds_since_last_unlock >= ladder.min_wait_seconds:
        return UnlockDecision(
            True,
            next_level,
            f"unlocked level {next_level}: waited {int(seconds_since_last_unlock)}s (min {ladder.min_wait_seconds}s)",
        )
    return UnlockDecision(False, current_level, "run the tests again or wait before the next hint")
