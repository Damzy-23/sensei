"""Job analyst: lists what a job description asks for. Role: app/prompts/job_analyst.md.

A requirement the model returns is kept only if its term really appears in the job text,
so the fit score can never be computed against a requirement the job did not state.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.cv.fit import Requirement
from app.cv.scoring import contains_term
from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

NAME = "job_analyst"
MAX_REQUIREMENTS = 18


@dataclass(frozen=True)
class JobAnalysis:
    role_title: str
    company: str
    requirements: list[Requirement]


async def analyse(job_description: str) -> JobAnalysis:
    with span(NAME, "agent.start", NAME, job_description) as st:
        data = await gateway.complete_json("fast", system=load(NAME), user=job_description.strip(), actor=NAME, name="llm_read_job")
        raw = data.get("requirements")
        if not isinstance(raw, list):
            raise gateway.LLMError("job_analyst: 'requirements' must be a list")
        requirements: list[Requirement] = []
        seen: set[str] = set()
        dropped = 0
        for item in raw:
            if not isinstance(item, dict):
                continue
            term = str(item.get("term") or "").strip()
            if not term or term.lower() in seen:
                continue
            if not contains_term(job_description, term):
                dropped += 1  # not in the job text: the model added it
                continue
            aliases = tuple(str(a).strip() for a in (item.get("aliases") or []) if str(a).strip())[:3]
            importance = "nice" if item.get("importance") == "nice" else "must"
            requirements.append(Requirement(term, aliases, importance))
            seen.add(term.lower())
            if len(requirements) == MAX_REQUIREMENTS:
                break
        st.output = f"{len(requirements)} requirements kept, {dropped} dropped as not in the job text"
        return JobAnalysis(str(data.get("role_title") or "").strip(), str(data.get("company") or "").strip(), requirements)
