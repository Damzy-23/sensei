"""Output guard enforcement for coach replies.

guard_reply(draft):
  1. draft a reply, run policy_check and leak_check
  2. if it fails, ask once more with a stricter instruction and check again
  3. if that fails too, return the canned hint for the level and log the blocked original

Every check is a traced tool. The fallback is logged as a guard.output span holding the
blocked original, the decision (fallback) and the reason.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.policy import load_policy
from app.tools.guard import leak_check, policy_check
from app.tracing.context import span

Draft = Callable[[bool], Awaitable[dict[str, Any]]]  # stricter? -> {"level": int, "hint": str}


@dataclass(frozen=True)
class GuardedReply:
    text: str
    level: int
    decision: Literal["pass", "regenerated", "fallback"]
    reason: str
    original: str | None  # the first blocked hint, only set on fallback


async def guard_reply(draft: Draft, *, level: int, reference: str) -> GuardedReply:
    policy = load_policy()
    first: dict[str, Any] | None = None
    last_reason = ""
    for attempt, stricter in enumerate((False, True)):
        candidate = await draft(stricter)
        first = first or candidate
        ok, reason = await _checks(candidate, level, reference)
        if ok:
            decision: Literal["pass", "regenerated"] = "pass" if attempt == 0 else "regenerated"
            return GuardedReply(text=str(candidate["hint"]), level=level, decision=decision,
                                reason=reason, original=None)
        last_reason = reason

    canned = policy.canned_hints[level]
    original = str(first["hint"]) if first else ""
    with span("guard", "guard.output", "canned_fallback", input_text=original) as st:
        st.decision = "fallback"
        st.reason = last_reason
        st.output = canned
    return GuardedReply(text=canned, level=level, decision="fallback", reason=last_reason, original=original)


async def _checks(candidate: dict[str, Any], level: int, reference: str) -> tuple[bool, str]:
    pc = policy_check(candidate, level)
    if pc["decision"] != "pass":
        return False, str(pc["reason"])
    lc = await leak_check(str(candidate.get("hint", "")), level, reference)
    if lc["decision"] != "pass":
        return False, str(lc["reason"])
    return True, "passed policy and leak checks"
