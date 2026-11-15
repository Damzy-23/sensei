"""Caller: the interviewer for a live phone interview. Role: app/prompts/caller.md.

Its replies are written to be spoken, so the same turn loop can sit behind a
voice line: the telephony layer sends what the candidate said and speaks the reply.
"""

from __future__ import annotations

from app.agents.context import AgentContext
from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

NAME = "caller"


async def respond(ctx: AgentContext) -> str:
    with span(NAME, "agent.start", NAME, ctx.student_message) as st:
        reply = await gateway.complete("reasoning", system=load(NAME), user=ctx.render(), actor=NAME, name="llm_call")
        st.output = reply
        return reply.strip()
