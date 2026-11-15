"""DEMO_MODE: successful calls are cached, a failed call replays the cached reply, the replay is
logged and traced, and an uncached request still fails."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.llm import client, replay
from app.llm.client import LLMError, ProviderReply, call
from app.tracing import store
from app.tracing.context import turn

MESSAGES = [{"role": "user", "content": "Hint for two sum at level 1."}]
SYSTEM = "You are a Socratic coding-interview coach."


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(client, "BACKOFF_BASE_SECONDS", 0.0)
    cache = tmp_path / "llm_cache.json"
    monkeypatch.setattr(replay, "CACHE_PATH", cache)
    yield cache


def _ok(text: str):
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        return ProviderReply(text, 10, 5)

    return provider


def _down():
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        raise httpx.ConnectError("network is down")

    return provider


def _call(**kw):  # noqa: ANN003
    return asyncio.run(call("hint_base", SYSTEM, MESSAGES, actor="hint_coach", name="llm_hint", **kw))


def test_demo_mode_caches_a_successful_reply(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setitem(client.PROVIDERS, "anthropic", _ok('{"level": 1, "hint": "Restate the task."}'))
    _call()
    assert env.exists()
    entry = replay.get("hint_base", SYSTEM, MESSAGES, path=env)
    assert entry is not None and entry["text"] == '{"level": 1, "hint": "Restate the task."}'


def test_without_demo_mode_nothing_is_cached(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setitem(client.PROVIDERS, "anthropic", _ok('{"level": 1, "hint": "x"}'))
    _call()
    assert not env.exists()


def test_failed_call_replays_cached_reply_and_logs_it(monkeypatch: pytest.MonkeyPatch, env: Path, caplog) -> None:  # noqa: ANN001
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setitem(client.PROVIDERS, "anthropic", _ok('{"level": 1, "hint": "Restate the task."}'))
    _call()  # warm the cache while the network is up

    monkeypatch.setitem(client.PROVIDERS, "anthropic", _down())
    caplog.set_level(logging.WARNING, logger="sensei.demo")
    with turn("ses_demo1") as tctx:
        result = _call()

    assert result.text == '{"level": 1, "hint": "Restate the task."}'
    assert result.notes == ["replayed from DEMO_MODE cache"]
    assert any("DEMO_MODE" in rec.message for rec in caplog.records)
    replay_span = next(e for e in store.load_trace(tctx.trace_id)
                       if e.name == "llm_hint" and e.output and "DEMO_MODE replay" in e.output)
    assert replay_span.status == "retried"


def test_uncached_request_still_fails_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setitem(client.PROVIDERS, "anthropic", _down())
    with pytest.raises(LLMError):
        _call()


def test_failed_call_without_demo_mode_raises_even_if_cached(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setitem(client.PROVIDERS, "anthropic", _ok('{"level": 1, "hint": "x"}'))
    _call()
    monkeypatch.delenv("DEMO_MODE")
    monkeypatch.setitem(client.PROVIDERS, "anthropic", _down())
    with pytest.raises(LLMError):
        _call()


def test_missing_key_replays_in_demo_mode(monkeypatch: pytest.MonkeyPatch, env: Path) -> None:
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setitem(client.PROVIDERS, "anthropic", _ok('{"level": 1, "hint": "cached"}'))
    _call()
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    result = _call()
    assert result.text == '{"level": 1, "hint": "cached"}'
