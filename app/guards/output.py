"""Output guard logic. Pure functions except the judge prompt builder.

Checks on every coach reply:
  policy_check: length limit, the reply's level matches the unlocked level, not empty
  leak_check:   (a) code-block rules per level, (b) normalised similarity to the reference,
                (c) a model judge (run by the tool, see app/tools/guard.py)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

# Lines that read as code. Prose such as "For each number, ..." does not match.
_CODE_LINE = re.compile(
    r"^\s*("
    r"def\s+\w+\(.*\)\s*:?"
    r"|for\s+.+\s+in\s+.+:\s*$"
    r"|while\s+.+:\s*$"
    r"|if\s+.+:\s*$"
    r"|elif\s+.+:\s*$"
    r"|else:\s*$"
    r"|return\s+\S.*$"  # lowercase only: prose hints start with a capital
    r"|import\s+\S+"
    r"|from\s+\S+\s+import\s+\S+"
    r"|[A-Za-z_][\w\.\[\]]*\s*(=|\+=|-=|\*=)\s*\S"
    r"|[A-Za-z_][\w\.]*\(.*\)\s*$"
    r")"
)
_FENCED = re.compile(r"```[\w]*\n?(.*?)```", re.DOTALL)
_TOKEN = re.compile(r"[A-Za-z_]+|\d+|[^\sA-Za-z_\d]")


@dataclass(frozen=True)
class StaticCheck:
    ok: bool
    reason: str
    code_lines: int
    similarity: float


def code_lines(reply: str) -> list[str]:
    """Code-like lines, including the contents of fenced blocks."""
    fenced = [line for block in _FENCED.findall(reply) for line in block.splitlines() if line.strip()]
    outside = [line for line in _FENCED.sub("", reply).splitlines() if _CODE_LINE.match(line)]
    return fenced + outside


def normalise(code: str) -> list[str]:
    no_comments = re.sub(r"#.*", "", code)
    return _TOKEN.findall(no_comments.lower())


def coverage(reply_code: str, reference: str) -> float:
    """Fraction of the reference's tokens that appear, in order, in the reply's code."""
    ref = normalise(reference)
    if not ref:
        return 0.0
    rep = normalise(reply_code)
    if not rep:
        return 0.0
    matcher = SequenceMatcher(None, ref, rep, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / len(ref)


def static_checks(reply: str, level: int, reference: str, *, similarity_threshold: float, pseudocode_max_lines: int) -> StaticCheck:
    lines = code_lines(reply)
    sim = coverage("\n".join(lines), reference) if lines else 0.0
    if level < 5 and lines:
        return StaticCheck(False, f"code-like content at level {level} (code is allowed only at level 5)", len(lines), sim)
    if level >= 5 and len(lines) > pseudocode_max_lines:
        return StaticCheck(False, f"level 5 skeleton has {len(lines)} lines (max {pseudocode_max_lines})", len(lines), sim)
    if sim >= similarity_threshold:
        return StaticCheck(False, f"similarity {sim:.2f} to the reference is at or above {similarity_threshold:.2f}", len(lines), sim)
    return StaticCheck(True, "passed static checks", len(lines), sim)


def policy_verdict(candidate: dict[str, Any], expected_level: int, max_words: int) -> tuple[bool, str]:
    hint = str(candidate.get("hint", "")).strip()
    if not hint:
        return False, "empty hint"
    words = len(hint.split())
    if words > max_words:
        return False, f"hint is {words} words (max {max_words})"
    level = candidate.get("level")
    if level != expected_level:
        return False, f"reply is level {level}, unlocked level is {expected_level}"
    return True, "passed policy checks"


def judge_messages(reply: str, reference: str) -> list[dict[str, str]]:
    return [{
        "role": "user",
        "content": (
            "You are auditing a coding coach's hint. The reference solution is below.\n"
            f"<<<{reference}>>>\n\n"
            f"Hint to check:\n<<<{reply}>>>\n\n"
            "Does the hint reveal the complete working solution, or enough of it that the student could copy it? "
            "Reply with JSON only: {\"reveals_full_solution\": true or false}."
        ),
    }]


JUDGE_SCHEMA: dict[str, Any] = {"required": ["reveals_full_solution"]}


def parse_judge(data: dict[str, Any] | None) -> bool:
    """True means the hint leaks. Missing or malformed output counts as a leak (fail closed)."""
    if not data or not isinstance(data.get("reveals_full_solution"), bool):
        return True
    return data["reveals_full_solution"]
