"""Voice routes: start a browser voice session, and narrate short text, without exposing the provider key."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.voice import elevenlabs, personas

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


class NarrationIn(BaseModel):
    text: str = Field(min_length=1, max_length=elevenlabs.MAX_TTS_CHARS)
    persona: Literal["drill", "mentor", "peer"] = personas.DEFAULT  # type: ignore[assignment]


@router.post("/tts", response_class=Response, responses={200: {"content": {"audio/mpeg": {}}}})
async def narrate(body: NarrationIn) -> Response:
    """Speak a short piece of text in a coach's voice. Returns MP3 audio.

    Used by the explainer, so its narration sounds like the coach the student chose.
    Repeats of the same text are served from a cache and are not billed again.
    """
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="There is no text to speak.")
    if get_settings().use_stubs:
        raise HTTPException(status_code=503, detail="Narration needs the real voice service: set SENSEI_USE_STUBS=0.")
    try:
        audio, cached = await elevenlabs.speak(text, personas.VOICES[body.persona])
    except elevenlabs.VoiceNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except elevenlabs.VoiceBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except elevenlabs.VoiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/mpeg",
                    headers={"cache-control": "private, max-age=3600", "x-narration": "cached" if cached else "fresh"})
