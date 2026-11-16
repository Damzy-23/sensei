"""Evaluation: the stored report of the last real run (GET /eval/report), and the placeholder
tuned-vs-base comparison (GET /eval/results) that is still stubbed."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from app import stubs
from app.eval.report import REPORT_PATH
from app.models import EvalResults

router = APIRouter(prefix="/eval", tags=["eval"])


class EvalReport(BaseModel):
    """What app.eval.report.build writes. See docs/EVALUATION.md for every field."""

    model_config = ConfigDict(extra="allow")

    generated_at: str
    commit: str
    scenarios_version: str
    models: dict[str, str]
    scenarios: int
    overall: dict[str, Any]
    by_family: dict[str, Any]
    by_hint_level_learn_mode: dict[str, Any]
    latency_ms: dict[str, Any]
    cost_usd: dict[str, Any]
    failing_turns: list[dict[str, Any]]
    limits: list[str]


@router.get("/results", response_model=EvalResults)
async def eval_results() -> EvalResults:
    return stubs.stub_eval_results()


@router.get("/report", response_model=EvalReport)
async def eval_report() -> EvalReport:
    """The last evaluation run on real models, as recorded. Never placeholder numbers."""
    if not REPORT_PATH.is_file():
        raise HTTPException(status_code=404, detail="No evaluation has been run yet: see docs/EVALUATION.md.")
    return EvalReport(**json.loads(REPORT_PATH.read_text()))
