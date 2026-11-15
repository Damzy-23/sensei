"""Evaluator: writes the end-of-interview feedback from the observer's notes. Role: app/prompts/evaluator.md."""

from __future__ import annotations

import json

from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

NAME = "evaluator"
LISTS = ("strengths", "work_on", "interviewers_look_for")


async def debrief(problem_title: str, pattern: str, notes: list[dict], scores: dict[str, float | None]) -> dict:
    with span(NAME, "agent.start", NAME, f"{len(notes)} notes") as st:
        user = json.dumps({
            "problem": problem_title,
            "problem_family": pattern,
            "scores_out_of_4": {k: ("not observed" if v is None else v) for k, v in scores.items()},
            "notes": notes,
        }, indent=1)
        data = await gateway.complete_json("reasoning", system=load(NAME), user=user, actor=NAME, name="llm_debrief")
        summary = str(data.get("summary") or "").strip()
        if not summary or any(not isinstance(data.get(key), list) for key in LISTS):
            raise gateway.LLMError("evaluator: reply is missing the summary or a list")
        out = {"summary": summary, **{key: [str(x).strip() for x in data[key] if str(x).strip()][:4] for key in LISTS}}
        st.output = summary
        return out
