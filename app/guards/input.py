"""Input guard: classify every student message before any agent sees it."""

from __future__ import annotations

from dataclasses import dataclass

from app.guards import policy
from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

CATEGORIES = frozenset({"ok", "stuck", "solution_request", "frustrated", "off_topic", "injection"})


@dataclass(frozen=True)
class InputDecision:
    category: str
    reason: str

    @property
    def blocked(self) -> bool:
        return self.category in policy.BLOCKED_CATEGORIES


async def classify(text: str) -> InputDecision:
    with span("guard", "guard.input", "classify_input", text) as st:
        data = await gateway.complete_json(
            "fast", system=load("input_guard"), user=text, actor="guard", name="llm_classify_input"
        )
        category = str(data.get("category", "")).strip()
        if category not in CATEGORIES:
            raise gateway.LLMError(f"input guard returned unknown category {category!r}")
        reason = str(data.get("reason") or "").strip() or "model gave no reason"
        confidence = data.get("confidence")
        decision = InputDecision(category, reason)
        st.decision = category
        st.reason = f"model: {reason}" + (f" ({confidence})" if isinstance(confidence, (int, float)) else "")
        st.status = "blocked" if decision.blocked else "ok"
        st.output = category
        return decision
