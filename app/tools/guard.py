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
from app.guards.output import (
    JUDGE_SCHEMA,
    judge_messages,
    parse_judge,
    policy_verdict,
    static_checks,
)
from app.llm.client import LLMError, call
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

    model_category = None
    model_conf = 0.0
    if regex_category != "injection":
        try:
            reply = await call("fast", "You classify coaching messages. Reply with JSON only.",
                               classify_messages(text), actor="guard", name="llm_classify",
                               json_schema=CLASSIFY_SCHEMA, max_tokens=60)
            model_category, model_conf = parse_classification(reply.data)
        except LLMError:
            # Classifier unavailable: rely on the regex rules alone, and say so in the trace.
            model_category, model_conf = None, 0.0

    # An injection found by regex_precheck is trusted without a second check. The rule name is
    # looked up from the text so the trace says which rule fired.
    regex_hit = regex_rules(text)
    if regex_category == "injection" and regex_hit is None:
        regex_hit = RegexHit("injection", "regex_precheck", text[:40])
    verdict = decide_input(regex_hit, model_category, model_conf, min_conf)
    if st is not None:
        st.decision = verdict.decision
        st.reason = verdict.reason
    return {"category": verdict.category, "decision": verdict.decision, "reason": verdict.reason}


@tool("guard", "leak_check", "guard.output")
async def leak_check(reply: str, level: int, reference_solution: str) -> dict[str, Any]:
    """Code-block rules per level, similarity to the reference, and a model judge (fail closed)."""
    st = current_span()
    policy = load_policy()
    static = static_checks(
        reply, level, reference_solution,
        similarity_threshold=policy.guard.similarity_threshold,
        pseudocode_max_lines=policy.hint_ladder.pseudocode_max_lines,
    )
    if not static.ok:
        result = {"decision": "block", "reason": static.reason, "checks": {"static": False, "similarity": static.similarity}}
    else:
        try:
            judged = await call("fast", "You audit coaching hints for leaked solutions. Reply with JSON only.",
                                judge_messages(reply, reference_solution), actor="guard", name="llm_judge",
                                json_schema=JUDGE_SCHEMA, max_tokens=60)
            leaks = parse_judge(judged.data)
            reason = "judge: reveals full solution" if leaks else "judge: no full solution revealed"
        except LLMError as exc:
            leaks = True
            reason = f"judge unavailable, failing closed: {exc}"
        if leaks:
            result = {"decision": "block", "reason": reason, "checks": {"static": True, "judge_leak": True}}
        else:
            result = {"decision": "pass", "reason": "static checks and judge passed",
                      "checks": {"static": True, "judge_leak": False, "similarity": static.similarity}}
    if st is not None:
        st.decision = result["decision"]
        st.reason = result["reason"]
    return result


@tool("guard", "policy_check", "guard.output")
def policy_check(reply: dict[str, Any], level: int) -> dict[str, Any]:
    """Length limit, non-empty hint, and that the reply's level matches the unlocked level."""
    st = current_span()
    ok, reason = policy_verdict(reply, level, load_policy().hint_ladder.reply_max_words)
    result = {"decision": "pass" if ok else "block", "reason": reason}
    if st is not None:
        st.decision = result["decision"]
        st.reason = result["reason"]
    return result
