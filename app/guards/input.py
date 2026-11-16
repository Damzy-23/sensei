"""Input guard: classify every student message before any agent sees it."""

from __future__ import annotations

from dataclasses import dataclass

from app.guards import policy
from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

CATEGORIES = frozenset({"ok", "stuck", "confused", "solution_request", "frustrated", "off_topic", "injection"})


@dataclass(frozen=True)
class InputDecision:
    category: str
    reason: str

    @property
    def blocked(self) -> bool:
        return self.category in policy.BLOCKED_CATEGORIES


async def _ask_model(text: str) -> dict:
    data = await gateway.complete_json(
        "fast", system=load("input_guard"), user=text, actor="guard", name="llm_classify_input"
    )
    category = str(data.get("category", "")).strip()
    if category not in CATEGORIES:
        raise gateway.LLMError(f"input guard returned unknown category {category!r}")
    return data


async def classify(text: str) -> InputDecision:
    with span("guard", "guard.input", "classify_input", text) as st:
        # A model answer that is not JSON, or not one of the categories, is asked for once more.
        # If that fails too the message is treated as an ordinary one ("ok") rather than failing the
        # student's whole turn: every reply still goes through the leak check on its way out.
        try:
            data = await _ask_model(text)
        except gateway.LLMError:
            try:
                data = await _ask_model(text)
            except gateway.LLMError as exc:
                st.decision = "ok"
                st.reason = f"rule input.unclassified: the guard model failed twice ({exc}); treated as ok, the leak check still runs"
                st.status = "error"
                st.output = "ok"
                return InputDecision("ok", "the guard model could not classify this message")
        category = str(data.get("category", "")).strip()
        reason = str(data.get("reason") or "").strip() or "model gave no reason"
        confidence = data.get("confidence")
        decision = InputDecision(category, reason)
        st.decision = category
        st.reason = f"model: {reason}" + (f" ({confidence})" if isinstance(confidence, (int, float)) else "")
        st.status = "blocked" if decision.blocked else "ok"
        st.output = category
        return decision
