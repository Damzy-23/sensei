"""Evaluation results: tuned vs base hint model (win rate, leak rate)."""

from __future__ import annotations

from fastapi import APIRouter

from app import stubs
from app.models import EvalResults

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/results", response_model=EvalResults)
async def eval_results() -> EvalResults:
    return stubs.stub_eval_results()
