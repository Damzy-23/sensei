"""ElevenLabs: signed URLs for browser voice sessions, and speech for short narration.

Narration is cached by voice and text, and rate limited, because the route that serves it is
open to guests: without those two, anyone could spend the account's character quota.
"""

from __future__ import annotations

import os
import time
from collections import OrderedDict, deque

import httpx

API = "https://api.elevenlabs.io/v1/convai"
TTS_API = "https://api.elevenlabs.io/v1/text-to-speech"
TTS_MODEL = "eleven_flash_v2_5"  # the low-latency model: narration should start quickly
MAX_TTS_CHARS = 600
TTS_CALLS_PER_MINUTE = 120  # across all callers of this process
CACHE_ENTRIES = 128


class VoiceNotConfigured(RuntimeError):
    """ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID is missing."""


class VoiceError(RuntimeError):
    """The provider refused or could not be reached."""


class VoiceBusy(RuntimeError):
    """Too many narration requests in the last minute."""


def _settings() -> tuple[str, str]:
    key, agent = os.getenv("ELEVENLABS_API_KEY", "").strip(), os.getenv("ELEVENLABS_AGENT_ID", "").strip()
    if not key or not agent:
        raise VoiceNotConfigured("voice is not configured on this server")
    return key, agent


async def signed_url() -> tuple[str, str]:
    """Return (signed_url, agent_id). The URL is single-use and expires within minutes."""
    key, agent = _settings()
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            response = await http.get(
                f"{API}/conversation/get-signed-url", params={"agent_id": agent}, headers={"xi-api-key": key}
            )
            response.raise_for_status()
            return response.json()["signed_url"], agent
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        raise VoiceError(f"could not start a voice session: {type(exc).__name__}") from exc


_cache: OrderedDict[tuple[str, str], bytes] = OrderedDict()
_recent_calls: deque[float] = deque()


def reset_narration_state() -> None:
    """Forget cached audio and recent calls. For tests."""
    _cache.clear()
    _recent_calls.clear()


async def _post_tts(key: str, voice_id: str, text: str) -> bytes:
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(
            f"{TTS_API}/{voice_id}", params={"output_format": "mp3_44100_64"},
            headers={"xi-api-key": key}, json={"text": text, "model_id": TTS_MODEL},
        )
        response.raise_for_status()
        return response.content


async def speak(text: str, voice_id: str) -> tuple[bytes, bool]:
    """Return (mp3 bytes, served_from_cache) for `text` in the given voice."""
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise VoiceNotConfigured("voice is not configured on this server")
    cached = _cache.get((voice_id, text))
    if cached is not None:
        _cache.move_to_end((voice_id, text))
        return cached, True

    now = time.monotonic()
    while _recent_calls and now - _recent_calls[0] > 60:
        _recent_calls.popleft()
    if len(_recent_calls) >= TTS_CALLS_PER_MINUTE:
        raise VoiceBusy("too many narration requests in the last minute")
    _recent_calls.append(now)

    try:
        audio = await _post_tts(key, voice_id, text)
    except httpx.HTTPError as exc:
        raise VoiceError(f"could not create narration: {type(exc).__name__}") from exc
    if not audio:
        raise VoiceError("could not create narration: the provider returned no audio")
    _cache[(voice_id, text)] = audio
    while len(_cache) > CACHE_ENTRIES:
        _cache.popitem(last=False)
    return audio, False
