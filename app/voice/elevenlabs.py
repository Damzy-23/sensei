"""ElevenLabs Agents: issue a short-lived signed URL for a browser voice session."""

from __future__ import annotations

import os

import httpx

API = "https://api.elevenlabs.io/v1/convai"


class VoiceNotConfigured(RuntimeError):
    """ELEVENLABS_API_KEY or ELEVENLABS_AGENT_ID is missing."""


class VoiceError(RuntimeError):
    """The provider refused or could not be reached."""


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
