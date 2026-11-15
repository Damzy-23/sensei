"""CV studio route: tailor a CV to a job description. The PDF is made in the browser."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents import cv_writer
from app.config import get_settings
from app.llm.gateway import LLMError
from app.tracing.context import turn

router = APIRouter(prefix="/cv", tags=["cv"])

MIN_JOB_CHARS = 20
MIN_CV_CHARS = 50


class TailorIn(BaseModel):
    job_description: str = Field(min_length=MIN_JOB_CHARS, max_length=8000)
    cv_text: str = Field(min_length=MIN_CV_CHARS, max_length=12000)


class Role(BaseModel):
    role: str
    company: str
    dates: str
    bullets: list[str]


class TailorOut(BaseModel):
    name: str
    headline: str
    summary: str
    skills: list[str]
    experience: list[Role]
    education: list[str]
    gaps: list[str]
    trace_id: str


def _require_content(text: str, minimum: int, label: str) -> None:
    """Length limits count spaces; this rejects text that is mostly whitespace."""
    if len("".join(text.split())) < minimum:
        raise HTTPException(status_code=422, detail=f"{label} needs at least {minimum} characters of text.")


def _stub(body: TailorIn, trace_id: str) -> TailorOut:
    first_line = next((line.strip() for line in body.cv_text.splitlines() if line.strip()), "")
    return TailorOut(
        name=first_line[:80], headline="Sample output (stub mode)",
        summary="The API is serving sample data, so no model read your CV. Set SENSEI_USE_STUBS=0 to tailor it.",
        skills=[], experience=[], education=[], gaps=[], trace_id=trace_id,
    )


@router.post("/tailor", response_model=TailorOut)
async def tailor(body: TailorIn) -> TailorOut:
    _require_content(body.job_description, MIN_JOB_CHARS, "The job description")
    _require_content(body.cv_text, MIN_CV_CHARS, "The CV")
    try:
        with turn("cv", name="cv_tailor") as trace:
            trace_id = trace.trace_id
            if get_settings().use_stubs:
                return _stub(body, trace_id)
            return TailorOut(**await cv_writer.tailor(body.job_description, body.cv_text), trace_id=trace_id)
    except LLMError as exc:
        raise HTTPException(status_code=502, detail={"detail": str(exc), "trace_id": trace_id}) from exc
