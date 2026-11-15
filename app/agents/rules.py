"""Pure rules shared by the agents and their tools: failure classification, mastery update,
pattern choice, static code checks and prompt builders. No I/O and no model calls.

Prompts never include the reference solution. The hint prompt includes the bank's hint seed
for the level as internal guidance; the output guard catches any copying.
"""

from __future__ import annotations

import ast
from typing import Any, Literal

FailureType = Literal["wrong_answer", "edge_case", "timeout", "runtime_error"]

_EDGE_WORDS = ("edge", "empty", "zero", "duplicate", "single", "large", "negative", "one ", "same")


def classify_failure(failures: list[dict[str, str]]) -> FailureType:
    """Classify the dominant failure of a run. Failure names and messages are the only inputs."""
    if not failures:
        return "wrong_answer"
    text = " ".join(f"{f.get('name', '')} {f.get('message', '')}" for f in failures).lower()
    if "timeout" in text or "timed out" in text or "time limit" in text:
        return "timeout"
    if "error" in text or "exception" in text or "traceback" in text:
        return "runtime_error"
    names = " ".join(f.get("name", "") for f in failures).lower()
    if any(word in names for word in _EDGE_WORDS):
        return "edge_case"
    return "wrong_answer"


FAILURE_FEEDBACK: dict[FailureType, str] = {
    "wrong_answer": "Some cases return the wrong answer. Trace one failing case by hand and compare each step with what you expected.",
    "edge_case": "The main path works but a boundary case fails. Check empty, single-element and repeated inputs.",
    "timeout": "The code is correct on small inputs but too slow on large ones. Count how many times each element is visited.",
    "runtime_error": "The code crashes on some input. Read the traceback line by line and check what value is None or out of range.",
}


# Mastery is stored on [0, 1]. Difficulty sets the expected-performance anchor.
DIFFICULTY_ANCHOR: dict[str, float] = {"easy": 0.4, "medium": 0.6, "hard": 0.8}
MASTERY_K = 0.2


def elo_update(score: float, outcome: float, difficulty: str) -> float:
    """Elo-style update. outcome is 1.0 for a solve, 0.0 for an abandon. Result stays in [0, 1]."""
    anchor = DIFFICULTY_ANCHOR.get(difficulty, DIFFICULTY_ANCHOR["medium"])
    expected = 1.0 / (1.0 + 10 ** ((anchor - score) / 0.4))
    updated = score + MASTERY_K * (outcome - expected)
    return round(min(1.0, max(0.0, updated)), 4)


def pick_pattern(mastery: dict[str, float], patterns: list[str]) -> str | None:
    """The weakest pattern (lowest mastery, unseen counts as 0). Ties keep bank order."""
    if not patterns:
        return None
    return min(patterns, key=lambda p: (mastery.get(p, 0.0), patterns.index(p)))


def target_difficulty(mastery_score: float) -> str:
    if mastery_score < 0.4:
        return "easy"
    if mastery_score < 0.7:
        return "medium"
    return "hard"


def static_issues(code: str) -> list[str]:
    """AST checks only. Nothing is executed."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"syntax error on line {exc.lineno}: {exc.msg}"]
    issues: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            returns = [n for n in ast.walk(node) if isinstance(n, ast.Return) and n.value is not None]
            if not returns:
                issues.append(f"function '{node.name}' never returns a value")
    return issues


# ---------- prompts ----------

COACH_SYSTEM = (
    "You are a Socratic coding-interview coach. Teach through questions and small nudges. "
    "Never write working code, never write a complete solution, and never name the final algorithm "
    "unless the level allows it. Keep the hint under 60 words. "
    "Reply with JSON only: {\"level\": <the level you were asked for>, \"hint\": \"<your hint>\"}."
)


def hint_system_prompt(level: int, level_instruction: str, seed: str, stricter: bool) -> str:
    text = (
        f"{COACH_SYSTEM}\n\nHint level {level}: {level_instruction}\n"
        f"Internal guidance for this level (paraphrase it, never quote it): {seed}"
    )
    if stricter:
        text += (
            "\nYour previous hint broke the rules. Use plain words only: no code, no pseudocode, "
            "no function definitions, and under 40 words."
        )
    return text


def hint_user_prompt(title: str, statement: str, code: str, last_failure: str, level: int) -> str:
    return (
        f"Problem: {title}\n{statement}\n\n"
        f"Student code (truncated):\n<<<{code[:2000]}>>>\n\n"
        f"Last failing test: {last_failure or 'none yet'}\n\n"
        f"Write the hint for level {level}."
    )


def followup_prompt(title: str, mode: str) -> str:
    focus = "time and space complexity" if mode == "interview" else "an edge case or a follow-up variation"
    return (
        f"The student just solved '{title}'. Ask one short interview follow-up about {focus}. "
        "Do not reveal the answer. Reply with JSON only: {\"question\": \"...\"}."
    )


def complexity_prompt(code: str, expected: str) -> str:
    return (
        "Analyse the time and space complexity of this Python solution. Do not rewrite or quote the code. "
        f"The expected complexity for this problem is {expected}. "
        "Reply with JSON only: {\"time\": \"O(...)\", \"space\": \"O(...)\", \"feedback\": \"one or two sentences\"}.\n\n"
        f"<<<{code[:2000]}>>>"
    )


def describe(obj: Any) -> str:
    return repr(obj)[:200]
