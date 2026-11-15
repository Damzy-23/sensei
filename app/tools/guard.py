"""guard actor. Input and output checks. Logic lives in app/guards/; these tools are the traced entry points."""

from __future__ import annotations

from typing import Any

from app.guards.input import (
    CLASSIFY_SCHEMA,
    RegexHit,
    classify_messages,
    decide_input,
    parse_classification,
    regex_rules,
)
from app.llm.client import call
from app.policy import load_policy
from app.tracing.context import current_span
from app.tracing.registry import tool


@tool("guard", "regex_precheck", "guard.input")
def regex_precheck(text: str) -> dict[str, Any]:
    """Rule-based check for injection and solution-reveal phrasing. Runs before the model."""
    hit = regex_rules(text)
    st = current_span()
    if hit is None:
        result = {"category": None, "rule": None, "decision": "pass", "reason": "no regex rule matched"}
    else:
        decision = "block" if hit.category == "injection" else "flag"
        result = {"category": hit.category, "rule": hit.rule, "decision": decision, "reason": f"regex rule {hit.rule}"}
    if st is not None:
        st.decision = result["decision"]
        st.reason = result["reason"]
    return result


@tool("guard", "classify_input", "guard.input")
async def classify_input(session_id: str, text: str, regex_category: str | None) -> dict[str, Any]:
    """Fast-model classifier. Skipped when the regex already found an injection."""
    st = current_span()
    min_conf = load_policy().guard.classify_min_confidence
    hit = regex_rules(text) if regex_category == "injection" else None

    model_category = None
    model_conf = 0.0
    if regex_category != "injection":
        reply = await call("fast", "You classify coaching messages. Reply with JSON only.",
                           classify_messages(text), actor="guard", name="llm_classify",
                           json_schema=CLASSIFY_SCHEMA, max_tokens=60)
        model_category, model_conf = parse_classification(reply.data)

    # The regex result arrives from regex_precheck. An injection from there is trusted as-is.
    if regex_category == "injection" and hit is None:
        regex_hit: RegexHit | None = RegexHit("injection", "regex_precheck", text[:40])
    else:
        regex_hit = hit
    verdict = decide_input(regex_hit, model_category, model_conf, min_conf)
    if st is not None:
        st.decision = verdict.decision
        st.reason = verdict.reason
    return {"category": verdict.category, "decision": verdict.decision, "reason": verdict.reason}


@tool("guard", "leak_check", "guard.output")
async def leak_check(reply: str, level: int, reference_solution: str) -> dict[str, Any]:
    """Code-block rules per level, similarity to the reference, and a model judge."""
    raise NotImplementedError("leak_check: built in Phase 4 (output guard)")


@tool("guard", "policy_check", "guard.output")
def policy_check(reply: str, level: int) -> dict[str, Any]:
    """Length limit and that the reply matches the unlocked hint level."""
    raise NotImplementedError("policy_check: built in Phase 4 (output guard)")
