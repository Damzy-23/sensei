"""Guard policy: the thresholds and fixed replies, in one place."""

from __future__ import annotations

# Input categories that stop the turn before any agent runs.
BLOCKED_CATEGORIES = frozenset({"off_topic", "injection"})
# Input categories that move the student one step up the hint ladder.
HINT_CATEGORIES = frozenset({"stuck", "solution_request"})

MAX_HINT_LEVEL = 5
ESCALATE_AFTER_GUARD_VIOLATIONS = 3
ESCALATE_AFTER_FRUSTRATION_FLAGS = 2
MAX_LEAK_RETRIES = 1

BLOCKED_REPLY = "Let's keep this on the problem in front of us. What part of it are you working on?"
LEAK_FALLBACK_REPLY = (
    "I started to give away too much there. Tell me what your current approach does "
    "on a small example, and we will find the gap together."
)
ESCALATED_NOTE = " I have also asked a mentor to take a look, so a person will reply here shortly."
