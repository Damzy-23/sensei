"""Narration route: speaks short text in a coach's voice, caches repeats, and limits how much
a guest can spend. No test reaches the real voice service."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.voice import elevenlabs, personas

ROOT = Path(__file__).resolve().parent.parent


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = False

    async def __call__(self, key: str, voice_id: str, text: str) -> bytes:
        self.calls.append((voice_id, text))
        if self.fail:
            raise httpx.ConnectError("no route")
        return b"ID3-fake-mp3-" + text.encode()


@pytest.fixture
def provider(monkeypatch) -> FakeProvider:
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key-not-real")
    fake = FakeProvider()
    monkeypatch.setattr(elevenlabs, "_post_tts", fake)
    elevenlabs.reset_narration_state()
    yield fake
    elevenlabs.reset_narration_state()


@pytest.fixture
def client(provider: FakeProvider) -> TestClient:
    return TestClient(app)


def test_the_server_voices_match_the_personalities_the_browser_offers() -> None:
    frontend = json.loads((ROOT / "web/src/agent/personas.json").read_text())
    assert personas.VOICES == {name: persona["voice_id"] for name, persona in frontend.items()}
    assert personas.DEFAULT in personas.VOICES


def test_narration_is_spoken_in_the_chosen_coachs_voice(client: TestClient, provider: FakeProvider) -> None:
    r = client.post("/voice/tts", json={"text": "Start with one pointer at each end.", "persona": "drill"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert r.content == b"ID3-fake-mp3-Start with one pointer at each end."
    assert provider.calls == [(personas.VOICES["drill"], "Start with one pointer at each end.")]
    assert r.headers["x-narration"] == "fresh"


def test_the_default_voice_is_the_mentor(client: TestClient, provider: FakeProvider) -> None:
    client.post("/voice/tts", json={"text": "Hello."})
    assert provider.calls[0][0] == personas.VOICES["mentor"]


def test_a_repeat_is_served_from_the_cache_and_not_billed_again(client: TestClient, provider: FakeProvider) -> None:
    first = client.post("/voice/tts", json={"text": "Same line.", "persona": "peer"})
    again = client.post("/voice/tts", json={"text": "Same line.", "persona": "peer"})
    other_voice = client.post("/voice/tts", json={"text": "Same line.", "persona": "drill"})
    assert again.content == first.content and again.headers["x-narration"] == "cached"
    assert other_voice.headers["x-narration"] == "fresh"
    assert len(provider.calls) == 2  # one per voice, not one per request


def test_text_and_voice_are_bounded(client: TestClient, provider: FakeProvider) -> None:
    assert client.post("/voice/tts", json={"text": "x" * (elevenlabs.MAX_TTS_CHARS + 1)}).status_code == 422
    assert client.post("/voice/tts", json={"text": ""}).status_code == 422
    assert client.post("/voice/tts", json={"text": "   "}).status_code == 422
    assert client.post("/voice/tts", json={"text": "Hi.", "persona": "someone-elses-voice"}).status_code == 422
    assert provider.calls == []


def test_too_many_requests_in_a_minute_are_refused(client: TestClient, provider: FakeProvider, monkeypatch) -> None:
    monkeypatch.setattr(elevenlabs, "TTS_CALLS_PER_MINUTE", 2)
    codes = [client.post("/voice/tts", json={"text": f"Line {i}."}).status_code for i in range(3)]
    assert codes == [200, 200, 429]
    assert client.post("/voice/tts", json={"text": "Line 0."}).status_code == 200  # cached lines still play


def test_a_provider_failure_is_a_named_error_and_is_not_cached(client: TestClient, provider: FakeProvider) -> None:
    provider.fail = True
    r = client.post("/voice/tts", json={"text": "Will fail."})
    assert r.status_code == 502 and "could not create narration" in r.json()["detail"]
    provider.fail = False
    assert client.post("/voice/tts", json={"text": "Will fail."}).headers["x-narration"] == "fresh"


def test_without_a_key_the_route_says_voice_is_not_configured(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("ELEVENLABS_API_KEY", "")
    r = client.post("/voice/tts", json={"text": "Hello."})
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


def test_stub_mode_never_calls_the_voice_service(client: TestClient, provider: FakeProvider, monkeypatch) -> None:
    monkeypatch.setenv("SENSEI_USE_STUBS", "1")
    assert client.post("/voice/tts", json={"text": "Hello."}).status_code == 503
    assert provider.calls == []
