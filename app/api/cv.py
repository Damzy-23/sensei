"""CV studio routes: tailor a CV to a job, score it, and research the role. The PDF is made in the browser.

Numbers on this page are computed, not written by a model: bullet scores and the job-fit
score come from fixed rules in app/cv/, and every score carries what earned it.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.agents import cv_writer, job_analyst
from app.config import get_settings
from app.cv import fit as fit_rules
from app.cv import scoring
from app.llm.gateway import LLMError
from app.tools import exa, linkup
from app.tracing.context import turn

router = APIRouter(prefix="/cv", tags=["cv"])

MIN_JOB_CHARS = 20
MIN_CV_CHARS = 50
MAX_BULLETS = 60


class TailorIn(BaseModel):
    job_description: str = Field(min_length=MIN_JOB_CHARS, max_length=8000)
    cv_text: str = Field(min_length=MIN_CV_CHARS, max_length=12000)


class CheckOut(BaseModel):
    id: str
    label: str
    points: int
    max: int
    detail: str


class BulletScoreOut(BaseModel):
    text: str
    score: int
    max: int = Field(description="10 with job terms, 7 without: relevance cannot be measured without a job.")
    checks: list[CheckOut]


class Role(BaseModel):
    role: str
    company: str
    dates: str
    bullets: list[str]
    bullet_scores: list[BulletScoreOut] = []


class RequirementOut(BaseModel):
    term: str
    importance: str


class FitOut(BaseModel):
    score: int | None = Field(description="Percent of the job's requirements the original CV shows. Null when they could not be read.")
    matched: list[RequirementOut] = []
    missing: list[RequirementOut] = []
    note: str = Field(description="How the score was reached, or why there is none.")


class SuggestedLine(BaseModel):
    gap: str
    draft: str = Field(description="A bullet with [blanks] only the candidate can fill. Never part of the CV until they do.")
    question: str


class TailorOut(BaseModel):
    name: str
    headline: str
    summary: str
    skills: list[str]
    experience: list[Role]
    education: list[str]
    gaps: list[str]
    suggested_lines: list[SuggestedLine] = []
    fit: FitOut
    job_terms: list[str] = []
    role_title: str = ""
    company: str = ""
    trace_id: str


class ScoreIn(BaseModel):
    bullets: list[str] = Field(min_length=1, max_length=MAX_BULLETS)
    job_terms: list[str] = Field(default=[], max_length=40)


class ScoreOut(BaseModel):
    scores: list[BulletScoreOut]


class ResearchIn(BaseModel):
    role_title: str = Field(min_length=2, max_length=120)
    company: str = Field(default="", max_length=120)


class SourceOut(BaseModel):
    title: str
    url: str
    excerpt: str


class SearchOut(BaseModel):
    available: bool = Field(description="False when this search did not run. `reason` says why.")
    reason: str = ""
    answer: str = ""
    sources: list[SourceOut] = []


class ResearchOut(BaseModel):
    linkup: SearchOut
    exa: SearchOut
    trace_id: str


def _require_content(text: str, minimum: int, label: str) -> None:
    """Length limits count spaces; this rejects text that is mostly whitespace."""
    if len("".join(text.split())) < minimum:
        raise HTTPException(status_code=422, detail=f"{label} needs at least {minimum} characters of text.")


def _score(text: str, job_terms: list[str]) -> BulletScoreOut:
    result = scoring.score_bullet(text, job_terms)
    return BulletScoreOut(text=result.text, score=result.score, max=result.max, checks=[CheckOut(**c.__dict__) for c in result.checks])


def _fit(analysis: job_analyst.JobAnalysis | None, cv_text: str, failure: str | None) -> FitOut:
    if analysis is None:
        return FitOut(score=None, note=f"No score: the job's requirements could not be read ({failure}).")
    result = fit_rules.job_fit(analysis.requirements, cv_text)
    if result.score is None:
        return FitOut(score=None, note="No score: no concrete requirements were found in the job description.")
    as_out = lambda items: [RequirementOut(term=r.term, importance=r.importance) for r in items]  # noqa: E731
    return FitOut(
        score=result.score, matched=as_out(result.matched), missing=as_out(result.missing),
        note=f"Your CV shows {len(result.matched)} of the {len(analysis.requirements)} things the job asks for. "
             "Must-haves count double. Measured on your original CV, so rewording cannot raise it.",
    )


def _stub(body: TailorIn, trace_id: str) -> TailorOut:
    first_line = next((line.strip() for line in body.cv_text.splitlines() if line.strip()), "")
    return TailorOut(
        name=first_line[:80], headline="Sample output (stub mode)",
        summary="The API is serving sample data, so no model read your CV. Set SENSEI_USE_STUBS=0 to tailor it.",
        skills=[], experience=[], education=[], gaps=[],
        fit=FitOut(score=None, note="No score in stub mode: no model read the job."), trace_id=trace_id,
    )


async def _read_job(job_description: str) -> tuple[job_analyst.JobAnalysis | None, str | None]:
    """The job reader's failure costs the fit score, never the tailored CV."""
    try:
        return await job_analyst.analyse(job_description), None
    except LLMError as exc:
        return None, str(exc)


@router.post("/tailor", response_model=TailorOut)
async def tailor(body: TailorIn) -> TailorOut:
    _require_content(body.job_description, MIN_JOB_CHARS, "The job description")
    _require_content(body.cv_text, MIN_CV_CHARS, "The CV")
    try:
        with turn("cv", name="cv_tailor") as trace:
            trace_id = trace.trace_id
            if get_settings().use_stubs:
                return _stub(body, trace_id)
            # The writer and the job reader work side by side: neither waits for the other.
            written, (analysis, failure) = await asyncio.gather(
                cv_writer.tailor(body.job_description, body.cv_text), _read_job(body.job_description)
            )
            terms = [r.term for r in analysis.requirements] if analysis else []
            for role in written["experience"]:
                role["bullet_scores"] = [_score(bullet, terms) for bullet in role["bullets"]]
            return TailorOut(
                **written, fit=_fit(analysis, body.cv_text, failure), job_terms=terms,
                role_title=analysis.role_title if analysis else "", company=analysis.company if analysis else "",
                trace_id=trace_id,
            )
    except LLMError as exc:
        raise HTTPException(status_code=502, detail={"detail": str(exc), "trace_id": trace_id}) from exc


@router.post("/score", response_model=ScoreOut)
async def score(body: ScoreIn) -> ScoreOut:
    """Score bullets by rule. No model is called, so this is instant and free: use it as the candidate types."""
    terms = [t.strip() for t in body.job_terms if t.strip()]
    return ScoreOut(scores=[_score(bullet, terms) for bullet in body.bullets])


async def _linkup(query: str) -> SearchOut:
    try:
        result = await linkup.search(query, actor="cv_writer")
    except linkup.LinkupError as exc:
        reason = "Linkup is not set up on this server (LINKUP_API_KEY is missing)." if "not set" in str(exc) else str(exc)
        return SearchOut(available=False, reason=reason)
    return SearchOut(available=True, answer=result.answer,
                     sources=[SourceOut(title=s.name, url=s.url, excerpt=s.snippet) for s in result.sources])


async def _exa(query: str) -> SearchOut:
    try:
        pages = await exa.search(query, actor="cv_writer")
    except (exa.ExaNotConfigured, exa.ExaError) as exc:
        return SearchOut(available=False, reason=str(exc))
    return SearchOut(available=True, sources=[SourceOut(title=p.title, url=p.url, excerpt=p.excerpt) for p in pages])


@router.post("/research", response_model=ResearchOut)
async def research(body: ResearchIn) -> ResearchOut:
    """Look the role up on the web: Linkup for a sourced answer, Exa for comparable postings.
    The two searches run side by side, and one failing does not hide the other."""
    role = body.role_title.strip()
    company = body.company.strip()
    at = f" at {company}" if company else ""
    with turn("cv", name="cv_research") as trace:
        answer, pages = await asyncio.gather(
            _linkup(f"What do interviewers and hiring managers look for in a {role}{at}? Skills, experience and interview process."),
            _exa(f"{role} job description{at}"),
        )
        return ResearchOut(linkup=answer, exa=pages, trace_id=trace.trace_id)
