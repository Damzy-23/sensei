"""Track routes: Blind 75 and NeetCode 150."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app import catalog
from app.models import Track, TrackSummary

router = APIRouter(prefix="/tracks", tags=["tracks"])


@router.get("", response_model=list[TrackSummary])
async def list_tracks() -> list[TrackSummary]:
    return catalog.list_tracks()


@router.get("/{track_id}", response_model=Track)
async def get_track(track_id: str) -> Track:
    track = catalog.get_track(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="track not found")
    return track
