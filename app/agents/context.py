"""What an agent is given for one turn: only what its job needs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentContext:
    problem_title: str
    pattern: str
    difficulty: str
    statement: str | None
    student_message: str
    student_code: str
    history: list[tuple[str, str]]  # (actor, text), oldest first
    hint_level: int = 0
    failed_runs: int = 0
    countdown_seconds: int | None = None
    rewrite_note: str | None = None  # set when the output guard blocked the previous draft
    reexplain: bool = False  # the student did not understand the last reply

    def render(self) -> str:
        parts = [f"Problem: {self.problem_title} ({self.difficulty}, pattern: {self.pattern})"]
        if self.statement:
            parts.append(f"Statement: {self.statement}")
        if self.history:
            parts.append("Conversation so far:\n" + "\n".join(f"{actor}: {text}" for actor, text in self.history))
        parts.append(f"Student's current code:\n{self.student_code.strip() or '(nothing written yet)'}")
        parts.append(f"Consecutive failed test runs: {self.failed_runs}")
        if self.countdown_seconds is not None:
            parts.append(f"Blitz mode. Seconds remaining: {self.countdown_seconds}")
        parts.append(f"Student's message: {self.student_message}")
        if self.reexplain:
            parts.append(
                "The student did not understand your last message. Explain the same idea again in a different "
                "way: smaller words and one small concrete example, in words. Stay at the same hint level."
            )
        if self.rewrite_note:
            parts.append(f"Your previous draft was rejected: {self.rewrite_note} Rewrite it in words only.")
        return "\n\n".join(parts)
