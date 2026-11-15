"""CV writer: tailors a candidate's CV to a job description. Role: app/prompts/cv_writer.md.

It may only rearrange and reword what the CV already says. What the job asks for and
the CV lacks comes back as `gaps`, never as invented experience.
"""

from __future__ import annotations

from typing import Any

from app.llm import gateway
from app.prompts.loader import load
from app.tracing.context import span

NAME = "cv_writer"

_TEXT_FIELDS = ("name", "headline", "summary")
_LIST_FIELDS = ("skills", "education", "gaps")
_ROLE_FIELDS = ("role", "company", "dates")


def _strings(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise gateway.LLMError(f"cv_writer: '{field}' must be a list of strings")
    return [item.strip() for item in value if item.strip()]


def _validate(data: dict[str, Any]) -> dict[str, Any]:
    """Check the model's answer has the agreed shape. Raises LLMError naming what is wrong."""
    missing = [key for key in (*_TEXT_FIELDS, *_LIST_FIELDS, "experience") if key not in data]
    if missing:
        raise gateway.LLMError(f"cv_writer: answer is missing {', '.join(missing)}")
    out: dict[str, Any] = {}
    for key in _TEXT_FIELDS:
        if not isinstance(data[key], str):
            raise gateway.LLMError(f"cv_writer: '{key}' must be text")
        out[key] = data[key].strip()
    for key in _LIST_FIELDS:
        out[key] = _strings(data[key], key)
    if not isinstance(data["experience"], list):
        raise gateway.LLMError("cv_writer: 'experience' must be a list")
    out["experience"] = []
    for index, job in enumerate(data["experience"]):
        if not isinstance(job, dict) or any(not isinstance(job.get(key), str) for key in _ROLE_FIELDS):
            raise gateway.LLMError(f"cv_writer: experience[{index}] needs text for role, company and dates")
        out["experience"].append(
            {
                **{key: job[key].strip() for key in _ROLE_FIELDS},
                "bullets": _strings(job.get("bullets"), f"experience[{index}].bullets"),
            }
        )
    return out


async def tailor(job_description: str, cv_text: str) -> dict[str, Any]:
    with span(NAME, "agent.start", NAME, job_description) as st:
        user = f"Job description:\n{job_description.strip()}\n\nCandidate's CV:\n{cv_text.strip()}"
        data = await gateway.complete_json(
            "reasoning", system=load(NAME), user=user, actor=NAME, name="llm_tailor_cv"
        )
        result = _validate(data)
        st.output = f"{len(result['experience'])} roles, {len(result['skills'])} skills, {len(result['gaps'])} gaps"
        return result
