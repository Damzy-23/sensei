"""Observer: the second interviewer. Silent; notes one exchange at a time. Role: app/prompts/observer.md."""

from __future__ import annotations

from app.agents.context import AgentContext
from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

NAME = "observer"
DIMENSIONS = ("communication", "approach", "correctness", "complexity")
MAX_SIGNALS = 2


async def observe(ctx: AgentContext) -> list[dict]:
    """Return up to two signals for this exchange: {"dimension", "rating", "note"}."""
    with span(NAME, "agent.start", NAME, ctx.student_message) as st:
        data = await gateway.complete_json("fast", system=load(NAME), user=ctx.render(), actor=NAME, name="llm_observe")
        raw = data.get("signals")
        if not isinstance(raw, list):
            raise gateway.LLMError("observer: 'signals' must be a list")
        signals = []
        for item in raw[:MAX_SIGNALS]:
            if not isinstance(item, dict):
                continue
            dimension, rating, note = item.get("dimension"), item.get("rating"), str(item.get("note") or "").strip()
            if dimension in DIMENSIONS and rating in (-1, 0, 1) and note:
                signals.append({"dimension": dimension, "rating": rating, "note": note})
        st.output = f"{len(signals)} signals"
        return signals
