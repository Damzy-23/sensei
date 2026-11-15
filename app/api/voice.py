"""Voice routes: start a browser voice session without exposing the provider key."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.voice import elevenlabs

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceSession(BaseModel):
    signed_url: str
    agent_id: str


@router.post("/session", response_model=VoiceSession)
async def start_voice_session() -> VoiceSession:
    try:
        url, agent = await elevenlabs.signed_url()
    except elevenlabs.VoiceNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except elevenlabs.VoiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return VoiceSession(signed_url=url, agent_id=agent)
