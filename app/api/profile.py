"""Profile routes: the career agent's interview and its role recommendations."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.memory import profiles
from app.models import ProfileAnswerIn, ProfileDetail, ProfileResult, ProfileStartIn, ProfileTurn
from app.orchestrator import profile as flow

router = APIRouter(prefix="/profile", tags=["profile"])


def _require(profile_id: str) -> ProfileDetail:
    found = profiles.get(profile_id)
    if found is None:
        raise HTTPException(status_code=404, detail="profile not found")
    return found


@router.post("", status_code=201, response_model=ProfileTurn)
async def start(body: ProfileStartIn | None = None) -> ProfileTurn:
    return await flow.start(body.session_id if body else None)


@router.get("/{profile_id}", response_model=ProfileDetail)
def get_profile(profile_id: str) -> ProfileDetail:
    return _require(profile_id)


@router.post("/{profile_id}/answer", response_model=ProfileTurn)
async def answer(profile_id: str, body: ProfileAnswerIn, session_id: str | None = None) -> ProfileTurn:
    return await flow.answer(_require(profile_id), body.text, session_id)


@router.post("/{profile_id}/recommend", response_model=ProfileResult)
async def recommend(profile_id: str, session_id: str | None = None) -> ProfileResult:
    profile = _require(profile_id)
    if sum(1 for q in profile.qa if q.answer) < 3:
        raise HTTPException(status_code=409, detail="Answer at least three questions first.")
    try:
        return await flow.recommend(profile, session_id)
    except flow.ProfileError as exc:
        raise HTTPException(status_code=502, detail={"message": str(exc), "trace_id": exc.trace_id}) from exc
