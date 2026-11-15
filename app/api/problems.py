"""Problem catalogue routes. Never returns reference solutions or hidden tests."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import stubs
from app.models import Problem, ProblemDetail

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("", response_model=list[Problem])
async def list_problems() -> list[Problem]:
    return stubs.list_problems()


@router.get("/{problem_id}", response_model=ProblemDetail)
async def get_problem(problem_id: str) -> ProblemDetail:
    problem = stubs.get_problem(problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="problem not found")
    return problem
