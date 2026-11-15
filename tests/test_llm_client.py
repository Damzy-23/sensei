"""Phase 3 LLM client tests with fake providers. No network calls."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from app.llm import client
from app.llm.client import LLMError, LLMJSONError, ProviderReply, call
from app.llm.models import ModelNotConfigured, resolve
from app.tracing import store
from app.tracing.context import turn


@pytest.fixture(autouse=True)
def fast_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(client, "BACKOFF_BASE_SECONDS", 0.0)
    yield


def _fake(replies: list[object]) -> tuple[list[int], object]:
    """Provider that returns queued replies; an Exception instance is raised instead."""
    calls: list[int] = []

    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        calls.append(1)
        item = replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item  # type: ignore[return-value]

    return calls, provider


def _run(model_key: str = "fast", **kwargs):  # noqa: ANN003
    import asyncio

    async def go():
        return await call(model_key, "system", [{"role": "user", "content": "hi"}], actor="guard", name="classify_input", **kwargs)

    return asyncio.run(go())


def test_successful_call_is_one_traced_span(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, provider = _fake([ProviderReply("hello", 100, 20)])
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    with turn("ses_llm1") as tctx:
        result = _run()
    assert result.text == "hello"
    assert result.attempts == 1
    ev = next(e for e in store.load_trace(tctx.trace_id) if e.name == "classify_input" and e.type == "llm.call")
    assert ev.model == "claude-haiku-5-5"
    assert ev.tokens_in == 100 and ev.tokens_out == 20
    assert ev.status == "ok"
    assert ev.cost_usd is not None and ev.cost_usd > 0


def test_transient_error_is_retried_and_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://example.test")
    status_err = httpx.HTTPStatusError("busy", request=request, response=httpx.Response(429, request=request))
    calls, provider = _fake([status_err, ProviderReply("ok after retry", 10, 5)])
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    with turn("ses_llm2") as tctx:
        result = _run()
    assert result.text == "ok after retry"
    assert result.attempts == 2
    ev = next(e for e in store.load_trace(tctx.trace_id) if e.type == "llm.call")
    assert ev.status == "retried"


def test_gives_up_after_three_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://example.test")
    err = httpx.TimeoutException("slow", request=request)
    calls, provider = _fake([err, err, err])
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    with turn("ses_llm3") as tctx:
        with pytest.raises(LLMError):
            _run()
    assert len(calls) == 3
    ev = next(e for e in store.load_trace(tctx.trace_id) if e.type == "llm.call")
    assert ev.status == "error"


def test_client_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://example.test")
    bad = httpx.HTTPStatusError("bad request", request=request, response=httpx.Response(400, request=request))
    calls, provider = _fake([bad])
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    with pytest.raises(LLMError):
        _run()
    assert len(calls) == 1


def test_json_repair_runs_once_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls, provider = _fake([ProviderReply("not json at all", 5, 5), ProviderReply('{"category": "ok"}', 5, 5)])
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    result = _run(json_schema={"required": ["category"]})
    assert result.data == {"category": "ok"}
    assert result.repaired is True
    assert len(calls) == 2


def test_json_fenced_reply_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _, provider = _fake([ProviderReply('```json\n{"category": "ok"}\n```', 5, 5)])
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    result = _run(json_schema={"required": ["category"]})
    assert result.data == {"category": "ok"}
    assert result.repaired is False


def test_invalid_json_after_repair_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _, provider = _fake([ProviderReply("nope", 1, 1), ProviderReply("still nope", 1, 1)])
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    with pytest.raises(LLMJSONError):
        _run(json_schema={"required": ["category"]})


def test_missing_key_is_reported_without_calling_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls, provider = _fake([ProviderReply("unused", 1, 1)])
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    with pytest.raises(LLMError, match="not configured"):
        _run()
    assert calls == []


def test_model_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_MODEL_FAST", "my-fast-model")
    assert resolve("fast").model == "my-fast-model"
    monkeypatch.delenv("ANTHROPIC_MODEL_FAST")
    assert resolve("fast").model == "claude-haiku-5-5"


def test_hint_tuned_needs_all_three_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("HINT_TUNED_BASE_URL", "HINT_TUNED_API_KEY", "HINT_TUNED_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ModelNotConfigured):
        resolve("hint_tuned")
    monkeypatch.setenv("HINT_TUNED_BASE_URL", "https://tuned.example/v1/")
    monkeypatch.setenv("HINT_TUNED_API_KEY", "k")
    monkeypatch.setenv("HINT_TUNED_MODEL", "hint-7b")
    target = resolve("hint_tuned")
    assert target.base_url == "https://tuned.example/v1"
    assert target.provider == "openai_compatible"


def test_timeout_is_thirty_seconds() -> None:
    assert client.TIMEOUT_SECONDS == 30.0
    assert client.MAX_RETRIES == 2


def test_llm_error_is_surfaced_as_llm_error_type() -> None:
    assert issubclass(LLMJSONError, LLMError)
