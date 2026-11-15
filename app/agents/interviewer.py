"""Interviewer: runs interview and blitz mode. Role: app/prompts/interviewer.md."""

from __future__ import annotations

from app.agents.context import AgentContext
from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

NAME = "interviewer"


async def respond(ctx: AgentContext) -> str:
    with span(NAME, "agent.start", NAME, ctx.student_message) as st:
        reply = await gateway.complete(
            "reasoning", system=load(NAME), user=ctx.render(), actor=NAME, name="llm_interview"
        )
        st.output = reply
        return reply.strip()
