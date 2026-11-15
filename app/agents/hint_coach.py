"""Hint coach: Socratic hints on a ladder from level 0 to 5. Role: app/prompts/hint_coach.md."""

from __future__ import annotations

from app.agents.context import AgentContext
from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

NAME = "hint_coach"


async def respond(ctx: AgentContext) -> str:
    with span(NAME, "agent.start", NAME, ctx.student_message) as st:
        user = f"Hint level for this reply: {ctx.hint_level}\n\n{ctx.render()}"
        reply = await gateway.complete("hint", system=load(NAME), user=user, actor=NAME, name="llm_hint")
        st.output = reply
        return reply.strip()
