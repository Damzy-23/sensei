"""Routing and escalation rules. Each returns the id of the rule that fired, which the
trace records as the reason. See docs/adr/0003.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.guards import policy
from app.memory.repository import Session
from app.models import NextAction


@dataclass(frozen=True)
class Decision:
    value: str
    rule: str
    detail: str

    @property
    def reason(self) -> str:
        return f"rule {self.rule}: {self.detail}"


def select_agent(session: Session) -> Decision:
    """Focus: which specialist may act this turn."""
    if session.mode == "interview":
        return Decision("interviewer", "mode.interview", "session is in interview mode")
    if session.mode == "blitz":
        return Decision("interviewer", "mode.blitz", "session is in blitz mode, timed")
    if session.mode == "call":
        return Decision("caller", "mode.call", "session is a live phone interview")
    return Decision("hint_coach", "mode.learn", "session is in learn mode")


def next_hint_level(session: Session, category: str) -> Decision:
    """The hint ladder: one step up per request for help, never past the top."""
    if category == "confused":
        return Decision(str(session.hint_level), "hint.reexplain", "student did not understand: same level, explained another way")
    if category not in policy.HINT_CATEGORIES:
        return Decision(str(session.hint_level), "hint.hold", f"message is '{category}', not a request for help")
    if session.hint_level >= policy.MAX_HINT_LEVEL:
        return Decision(str(policy.MAX_HINT_LEVEL), "hint.max", "already at the top of the ladder")
    return Decision(str(session.hint_level + 1), "hint.step", f"student asked for help at level {session.hint_level}")


def code_help(session: Session, category: str = "ok") -> Decision:
    """How much code the coach may give this turn: "none" or "one_line".

    One line at a time, never the solution. A student who asks for a line gets one. A student
    who has not asked is offered one only after a few tries. Never in an interview, and never
    past a small total per problem.
    """
    if session.mode != "learn":
        return Decision("none", "code.not_in_interview", "no code is given in an interview")
    if session.code_lines_given >= policy.CODE_LINES_PER_PROBLEM:
        return Decision("none", "code.limit", f"{session.code_lines_given} lines already given on this problem")
    if category == "solution_request":
        return Decision("one_line", "code.asked", "the student asked for code: one line, not the solution")
    # A try is anything the student has put in on this problem: a message or a failed run.
    tries = session.student_turns + session.failed_runs
    if tries >= policy.CODE_HELP_AFTER_TRIES:
        return Decision(
            "one_line", "code.earned",
            f"{session.student_turns} messages and {session.failed_runs} failed runs on this problem",
        )
    return Decision("none", "code.not_yet", f"{tries} of {policy.CODE_HELP_AFTER_TRIES} tries so far")


def should_escalate(session: Session, category: str) -> Decision | None:
    """Human-in-the-loop triggers. None when no rule fires or a mentor is already involved."""
    if session.escalated:
        return None
    if session.guard_violations >= policy.ESCALATE_AFTER_GUARD_VIOLATIONS:
        return Decision("escalate", "escalate.guard_violations", f"{session.guard_violations} blocked messages")
    if session.frustration_flags >= policy.ESCALATE_AFTER_FRUSTRATION_FLAGS:
        return Decision("escalate", "escalate.frustration", f"frustration flagged {session.frustration_flags} times")
    if (
        session.mode == "learn"
        and session.hint_level >= policy.MAX_HINT_LEVEL
        and category in policy.HINT_CATEGORIES
        and session.hints_used > policy.MAX_HINT_LEVEL
    ):
        return Decision("escalate", "escalate.max_hint", "still stuck after the level 5 hint")
    return None


def hint_level_available(session: Session) -> int:
    """Highest hint level the student may unlock next (0 = none)."""
    if session.mode != "learn" or session.failed_runs == 0:
        return 0
    return min(policy.MAX_HINT_LEVEL, session.hint_level + 1)


def next_action(session: Session, solved: bool) -> tuple[NextAction, Decision]:
    if session.escalated:
        return "escalate", Decision("escalate", "next.escalated", "a mentor has the session")
    if solved:
        return "review_complexity", Decision("review_complexity", "next.solved", "all tests pass")
    if session.failed_runs >= 2:
        return "ask_for_hint", Decision("ask_for_hint", "next.repeated_failure", f"{session.failed_runs} failed runs in a row")
    return "keep_coding", Decision("keep_coding", "next.keep_coding", "first failed run")
