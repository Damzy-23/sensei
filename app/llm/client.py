"""The one place that calls a model. Every call is a span (llm.call) with model, tokens and cost.

call(model_key, system, messages, ...):
  - timeout 30 seconds per attempt
  - up to 2 retries (3 attempts total) on timeouts, connection errors, 429 and 5xx
  - if json_schema is given: parse the reply as JSON; if it fails, ask once for a repair
  - status is "retried" when any retry or repair happened

Providers are plain async functions in PROVIDERS, so tests can swap them for fakes.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.llm.models import ModelTarget, resolve
from app.models import Actor
from app.tracing.context import span

TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 2
BACKOFF_BASE_SECONDS = 0.5
REPAIR_ATTEMPTS = 1
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class LLMError(RuntimeError):
    """The model call failed and no retry or repair recovered it."""


class LLMJSONError(LLMError):
    """The reply was not valid JSON matching the schema, even after one repair."""


@dataclass
class ProviderReply:
    text: str
    tokens_in: int | None
    tokens_out: int | None


@dataclass
class LLMResult:
    text: str
    data: dict[str, Any] | None
    model: str
    tokens_in: int
    tokens_out: int
    attempts: int
    repaired: bool
    notes: list[str] = field(default_factory=list)


ProviderFn = Callable[[ModelTarget, str, list[dict[str, str]], int], Awaitable[ProviderReply]]


async def _anthropic(target: ModelTarget, system: str, messages: list[dict[str, str]], max_tokens: int) -> ProviderReply:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=target.api_key, timeout=TIMEOUT_SECONDS, max_retries=0)
    resp = await client.messages.create(
        model=target.model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,  # type: ignore[arg-type]
    )
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return ProviderReply(text=text, tokens_in=resp.usage.input_tokens, tokens_out=resp.usage.output_tokens)


async def _openai_compatible(target: ModelTarget, system: str, messages: list[dict[str, str]], max_tokens: int) -> ProviderReply:
    payload = {
        "model": target.model,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, *messages],
    }
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as http:
        resp = await http.post(
            f"{target.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {target.api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
    text = data["choices"][0]["message"]["content"] or ""
    usage = data.get("usage") or {}
    return ProviderReply(text=text, tokens_in=usage.get("prompt_tokens"), tokens_out=usage.get("completion_tokens"))


PROVIDERS: dict[str, ProviderFn] = {
    "anthropic": _anthropic,
    "openai_compatible": _openai_compatible,
}


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError, asyncio.TimeoutError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500
    return type(exc).__name__ in {"APIConnectionError", "APITimeoutError"}


def parse_json(text: str) -> dict[str, Any] | None:
    cleaned = _JSON_FENCE.sub("", text).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _check_required(data: dict[str, Any], json_schema: dict[str, Any] | None) -> bool:
    if not json_schema:
        return True
    return all(key in data for key in json_schema.get("required", []))


async def call(
    model_key: str,
    system: str,
    messages: list[dict[str, str]],
    *,
    actor: Actor,
    name: str,
    json_schema: dict[str, Any] | None = None,
    max_tokens: int = 800,
) -> LLMResult:
    """One traced model call. Raises LLMError (or LLMJSONError) when it cannot recover."""
    target = resolve(model_key)  # ModelNotConfigured if keys are missing: no span needed
    provider = PROVIDERS[target.provider]
    input_text = json.dumps(messages, ensure_ascii=False)

    with span(actor, "llm.call", name, input_text=input_text) as st:
        st.model = target.model
        tokens_in = 0
        tokens_out = 0
        attempts = 0
        repaired = False
        notes: list[str] = []
        last_error: BaseException | None = None
        reply: ProviderReply | None = None

        for attempt in range(MAX_RETRIES + 1):
            attempts += 1
            try:
                reply = await asyncio.wait_for(provider(target, system, messages, max_tokens), timeout=TIMEOUT_SECONDS + 1)
                break
            except Exception as exc:  # noqa: BLE001 - classified below
                last_error = exc
                if not _is_retryable(exc) or attempt == MAX_RETRIES:
                    break
                notes.append(f"retry after {type(exc).__name__}")
                await asyncio.sleep(BACKOFF_BASE_SECONDS * (2**attempt))

        if reply is None:
            st.status = "error"
            st.output = f"{type(last_error).__name__}: {last_error}"
            raise LLMError(f"{model_key} call failed after {attempts} attempt(s): {last_error}") from last_error

        tokens_in += reply.tokens_in or 0
        tokens_out += reply.tokens_out or 0
        text = reply.text
        data = parse_json(text) if json_schema is not None else None

        if json_schema is not None and (data is None or not _check_required(data, json_schema)):
            notes.append("json repair requested")
            repair_messages = [
                *messages,
                {"role": "assistant", "content": text},
                {"role": "user", "content": "Your reply was not valid JSON for the required schema. Return only the JSON object, with no prose."},
            ]
            for _ in range(REPAIR_ATTEMPTS):
                attempts += 1
                try:
                    reply = await asyncio.wait_for(provider(target, system, repair_messages, max_tokens), timeout=TIMEOUT_SECONDS + 1)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    break
                tokens_in += reply.tokens_in or 0
                tokens_out += reply.tokens_out or 0
                text = reply.text
                data = parse_json(text)
                repaired = True
                if data is not None and _check_required(data, json_schema):
                    break
            if data is None or not _check_required(data, json_schema):
                st.status = "error"
                st.output = text
                raise LLMJSONError(f"{model_key} returned invalid JSON after repair")

        st.tokens_in = tokens_in
        st.tokens_out = tokens_out
        st.output = text
        if attempts > 1:
            st.status = "retried"
    return LLMResult(
        text=text,
        data=data,
        model=target.model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        attempts=attempts,
        repaired=repaired,
        notes=notes,
    )
