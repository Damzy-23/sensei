"""Output guard: stop a reply that gives the student more code than they have earned.

Rule-based on purpose: it is free, instant, and its reason is the rule that fired.
Most replies may contain no code at all. Once the student has earned it (see
rules.code_help), a reply may contain exactly one line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.tracing.context import span

_CODE_LINE = re.compile(
    r"^\s*(def \w+\(|class \w+|for .+ in .+:|while .+:|if .+:\s*$|elif .+:|else:\s*$|return\b|import \w+|"
    r"[A-Za-z_]\w*(\[[^\]]*\])?\s*(=|\+=|-=)\s*\S+)"
)
_LOOKS_LIKE_A_STATEMENT = re.compile(r"[=()\[\]:]")
# Prose sometimes matches the pattern above ("if you return early:"). One such line is let through.
MAX_PROSE_LIKE_LINES = 1


@dataclass(frozen=True)
class LeakDecision:
    leaked: bool
    rule: str
    reason: str
    code_lines: int = 0  # lines of code given on purpose: fenced, or alone in backticks


def _statements(line: str) -> int:
    return max(1, len([part for part in line.split(";") if part.strip()]))


def _count(reply: str) -> tuple[int, int, bool]:
    """Return (lines given as code, prose lines that look like code, whether a fence was used)."""
    given = prose_like = 0
    fenced = in_fence = False
    for raw in reply.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            fenced = True
            rest = line.strip("`").strip()
            # A whole one-line block on a single line: ```seen[n] = i```
            if in_fence is False and line.endswith("```") and len(line) > 6 and rest and not rest.isalpha():
                given += _statements(rest)
            else:
                in_fence = not in_fence
            continue
        if in_fence:
            if line:
                given += _statements(line)
            continue
        if len(line) > 2 and line.startswith("`") and line.endswith("`") and line.count("`") == 2:
            inner = line[1:-1]
            if _CODE_LINE.match(inner) or _LOOKS_LIKE_A_STATEMENT.search(inner):
                given += _statements(inner)
                continue
        if _CODE_LINE.match(raw):
            prose_like += 1
    return given, prose_like, fenced


def decide(reply: str, allowed_code_lines: int = 0) -> LeakDecision:
    """The rule itself, without a trace span. `check` wraps it for a reply to the student."""
    given, prose_like, fenced = _count(reply)
    if allowed_code_lines == 0:
        if fenced:
            return LeakDecision(True, "leak.code_fence", "rule leak.code_fence: reply contains a code block", given)
        if given:
            return LeakDecision(True, "leak.code_line", "rule leak.code_line: reply gives a line of code before it is earned", given)
    elif given > allowed_code_lines:
        return LeakDecision(
            True, "leak.too_many_lines",
            f"rule leak.too_many_lines: reply gives {given} lines of code and {allowed_code_lines} is allowed", given,
        )
    if prose_like > MAX_PROSE_LIKE_LINES:
        return LeakDecision(True, "leak.code_lines", f"rule leak.code_lines: {prose_like} lines of the reply are code", given)
    if given:
        return LeakDecision(False, "leak.earned_line", f"rule leak.earned_line: {given} line of code, earned by trying", given)
    return LeakDecision(False, "leak.none", "rule leak.none: no code in the reply", 0)


# Code inside a sentence: anything in backticks, an assignment or equality test on a name, a call
# (but not O(n), nor a plural like "number(s)"), a subscript on a name.
_CODE_IN_TEXT = re.compile(
    r"`"
    r"|\b[A-Za-z_]\w*(\[[^\]]*\])?\s*(\+=|-=|\*=|==|!=|=)\s*\S"
    r"|\b(?!O\()[A-Za-z_][\w.]*\((?!s\))"
    r"|\b[A-Za-z_]\w*\[[^\]]*\]"
)


def is_code(text: str) -> bool:
    """True when a short text (a label, a caption, one step) holds any code at all.

    Stricter than `decide` on purpose. A reply of several sentences may hold one code-like
    line, and one line of code when the rules allow it. A drawing may hold none, ever: that
    line belongs in the reply, where it is counted, not on the glass.
    """
    return bool(_CODE_IN_TEXT.search(text)) or any(_CODE_LINE.match(line) for line in text.splitlines())


def prose_only(reply: str) -> str:
    """The reply with its code taken out: fenced blocks, and every line `decide` counts as code.

    For a reader that must not repeat the code, such as the illustrator.
    """
    kept: list[str] = []
    in_fence = False
    for raw in reply.splitlines():
        given, prose_like, fence = _count(raw)
        if fence:
            # A block that opens and closes on one line gives its code there; any other fence line opens or closes one.
            in_fence = in_fence if given else not in_fence
        elif not (in_fence or given or prose_like):
            kept.append(raw)
    return "\n".join(kept).strip()


def check(reply: str, allowed_code_lines: int = 0) -> LeakDecision:
    with span("guard", "guard.output", "leak_check", reply) as st:
        decision = decide(reply, allowed_code_lines)
        st.decision = "blocked" if decision.leaked else "pass"
        st.reason = decision.reason
        st.status = "blocked" if decision.leaked else "ok"
        return decision


def keep_safe_notes(signals: list[dict]) -> list[dict]:
    """Drop any panel note that contains code: the candidate reads these mid-interview."""
    with span("guard", "guard.output", "panel_note_check", f"{len(signals)} notes") as st:
        safe = [s for s in signals if not decide(s["note"]).leaked]
        dropped = len(signals) - len(safe)
        st.decision = "blocked" if dropped else "pass"
        st.reason = (
            f"rule panel.code_in_note: dropped {dropped} of {len(signals)} notes"
            if dropped else "rule panel.clean: no code in the notes"
        )
        st.status = "blocked" if dropped else "ok"
        return safe
