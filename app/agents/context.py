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
    code_help: str = "none"  # "none" or "one_line": how much code this reply may contain

    def render(self) -> str:
        parts = [f"Problem: {self.problem_title} ({self.difficulty}, pattern: {self.pattern})"]
        if self.statement:
            parts.append(f"Statement: {self.statement}")
        if self.history:
            parts.append("Conversation so far:\n" + "\n".join(f"{actor}: {text}" for actor, text in self.history))
        parts.append(f"Student's current code:\n{self.student_code.strip() or '(nothing written yet)'}")
        parts.append(f"Consecutive failed test runs: {self.failed_runs}")
        parts.append(
            "Code allowed this turn: ONE line. Give it this turn."
            if self.code_help == "one_line" else "Code allowed this turn: none."
        )
        if self.countdown_seconds is not None:
            parts.append(f"Blitz mode. Seconds remaining: {self.countdown_seconds}")
        parts.append(f"Student's message: {self.student_message}")
        if self.reexplain:
            parts.append(
                "The student did not understand your last message. Say the same hint again in a different way: "
                "smaller words and an everyday comparison. Stay at the same hint level, and add nothing that level "
                "does not allow: no technique or data structure it has not yet named, and no walk through the steps."
            )
        if self.rewrite_note:
            parts.append(f"Your previous draft was rejected: {self.rewrite_note} Rewrite it in words only.")
        return "\n\n".join(parts)
