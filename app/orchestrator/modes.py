"""Mode selection. Pure code, no LLM. Every choice names the signals it read and the rule that fired.

Priority (from the spec):
  1. any mode -> learn  if consecutive failed runs >= threshold, or hint level >= threshold
  2. learn    -> interview if the problem was solved with <= N hints AND pattern mastery >= M
  3. interview -> blitz  after K solves in a row under the time target
  4. otherwise stay in the current mode
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.policy import ModePolicy

Mode = Literal["learn", "interview", "blitz"]


@dataclass(frozen=True)
class ModeSignals:
    current_mode: Mode
    consecutive_failed_runs: int
    hint_level: int
    last_solved: bool
    hints_on_solve: int
    pattern_mastery: float
    solved_streak_under_target: int


@dataclass(frozen=True)
class ModeChoice:
    mode: Mode
    rule: str
    reason: str
    signals: dict[str, float | int | bool | str]


def select_mode(sig: ModeSignals, policy: ModePolicy) -> ModeChoice:
    signals: dict[str, float | int | bool | str] = {
        "current_mode": sig.current_mode,
        "consecutive_failed_runs": sig.consecutive_failed_runs,
        "hint_level": sig.hint_level,
        "last_solved": sig.last_solved,
        "hints_on_solve": sig.hints_on_solve,
        "pattern_mastery": sig.pattern_mastery,
        "solved_streak_under_target": sig.solved_streak_under_target,
    }

    if sig.consecutive_failed_runs >= policy.learn_consecutive_failed_runs:
        return ModeChoice(
            "learn", "learn.failed_runs",
            f"{sig.consecutive_failed_runs} consecutive failed runs (threshold {policy.learn_consecutive_failed_runs})",
            signals,
        )
    if sig.hint_level >= policy.learn_hint_level:
        return ModeChoice(
            "learn", "learn.hint_level",
            f"hint level {sig.hint_level} (threshold {policy.learn_hint_level})",
            signals,
        )
    if sig.current_mode == "learn":
        if (
            sig.last_solved
            and sig.hints_on_solve <= policy.interview_max_hints_on_solve
            and sig.pattern_mastery >= policy.interview_min_mastery
        ):
            return ModeChoice(
                "interview", "interview.solved_fast",
                f"solved with {sig.hints_on_solve} hint(s), mastery {sig.pattern_mastery:.2f} >= {policy.interview_min_mastery}",
                signals,
            )
    if sig.current_mode == "interview":
        if sig.solved_streak_under_target >= policy.blitz_solves_in_row:
            return ModeChoice(
                "blitz", "blitz.streak",
                f"{sig.solved_streak_under_target} solves in a row under the time target",
                signals,
            )
    return ModeChoice(
        sig.current_mode, f"stay.{sig.current_mode}",
        "no mode rule fired",
        signals,
    )
