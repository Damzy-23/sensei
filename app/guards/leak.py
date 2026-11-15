"""Output guard: stop a reply that gives the student code.

Rule-based on purpose: it is free, instant, and its reason is the rule that
fired. Hints at every level are words only, so any code in a reply is a leak.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.tracing.context import span

_CODE_LINE = re.compile(
    r"^\s*(def \w+\(|class \w+|for .+ in .+:|while .+:|if .+:\s*$|elif .+:|else:\s*$|return\b|import \w+|"
    r"[A-Za-z_]\w*(\[[^\]]*\])?\s*(=|\+=|-=)\s*\S+)"
)
MAX_CODE_LINES = 1


@dataclass(frozen=True)
class LeakDecision:
    leaked: bool
    rule: str
    reason: str


def _decide(reply: str) -> LeakDecision:
    if "```" in reply:
        return LeakDecision(True, "leak.code_fence", "rule leak.code_fence: reply contains a code block")
    code_lines = [line for line in reply.splitlines() if _CODE_LINE.match(line)]
    if len(code_lines) > MAX_CODE_LINES:
        return LeakDecision(
            True, "leak.code_lines", f"rule leak.code_lines: {len(code_lines)} lines of the reply are code"
        )
    return LeakDecision(False, "leak.none", "rule leak.none: no code in the reply")


def check(reply: str) -> LeakDecision:
    with span("guard", "guard.output", "leak_check", reply) as st:
        decision = _decide(reply)
        st.decision = "blocked" if decision.leaked else "pass"
        st.reason = decision.reason
        st.status = "blocked" if decision.leaked else "ok"
        return decision
