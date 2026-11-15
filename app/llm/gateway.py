"""The single path to a model. See app/llm/__init__.py and docs/adr/0002.

`complete()` picks the model for a task, makes the call, and records model,
tokens and latency on an `llm.call` span. Cost is derived from those by tracing.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.config import get_settings
from app.models import Actor
from app.tracing.context import span

Task = Literal["fast", "reasoning", "hint"]

DEFAULT_MODELS: dict[str, str] = {"fast": "claude-haiku-5-5", "reasoning": "claude-sonnet-5-5"}
MAX_TOKENS: dict[str, int] = {"fast": 1024, "reasoning": 4096, "hint": 4096}
# Thinking is always on for these models; effort is the only control over depth and speed.
EFFORT: dict[str, str] = {"fast": "low", "reasoning": "low", "hint": "low"}


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


@dataclass(frozen=True)
class LLMResult:
    text: str
    model: str
    tokens_in: int | None
    tokens_out: int | None


class LLMClient(Protocol):
    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult: ...


class AnthropicClient:
    """Claude through the official SDK. Credentials resolve from the environment."""

    def __init__(self) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.AsyncAnthropic()

    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
        try:
            response = await self._client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                output_config={"effort": effort},
                messages=[{"role": "user", "content": user}],
            )
        except self._anthropic.APIError as exc:
            raise LLMError(f"{type(exc).__name__}: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMError("model declined the request")
        text = "".join(block.text for block in response.content if block.type == "text")
        return LLMResult(text, response.model, response.usage.input_tokens, response.usage.output_tokens)


class TunedHintClient:
    """The fine-tuned hint model, served from an OpenAI-compatible endpoint (not Claude)."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
        import httpx

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                response = await http.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
                response.raise_for_status()
                body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"tuned hint model: {type(exc).__name__}: {exc}") from exc
        usage = body.get("usage") or {}
        return LLMResult(text, model, usage.get("prompt_tokens"), usage.get("completion_tokens"))


_clients: dict[str, LLMClient] = {}


def set_client(client: LLMClient | None, kind: str = "anthropic") -> None:
    """Replace a client. Tests use this to run without the network."""
    if client is None:
        _clients.pop(kind, None)
    else:
        _clients[kind] = client


def _route(task: Task) -> tuple[str, str]:
    """Return (client kind, model id) for a task."""
    if task == "hint" and get_settings().hint_model == "tuned":
        return "tuned", os.getenv("HINT_TUNED_MODEL", "hint-tuned")
    key = "fast" if task == "fast" else "reasoning"
    return "anthropic", os.getenv(f"ANTHROPIC_MODEL_{key.upper()}", DEFAULT_MODELS[key])


def _client(kind: str) -> LLMClient:
    if kind not in _clients:
        if kind == "tuned":
            _clients[kind] = TunedHintClient(os.environ["HINT_TUNED_BASE_URL"], os.getenv("HINT_TUNED_API_KEY", ""))
        else:
            _clients[kind] = AnthropicClient()
    return _clients[kind]


async def complete(
    task: Task, *, system: str, user: str, actor: Actor, name: str, max_tokens: int | None = None
) -> str:
    """Call the model for `task` and return its text. Traced as one `llm.call` span.

    `max_tokens` lowers the task's budget for a call whose answer is known to be small.
    """
    kind, model = _route(task)
    budget = min(max_tokens, MAX_TOKENS[task]) if max_tokens else MAX_TOKENS[task]
    with span(actor, "llm.call", name, user) as st:
        st.model = model
        result = await _client(kind).complete(
            model=model, system=system, user=user, max_tokens=budget, effort=EFFORT[task]
        )
        st.model, st.tokens_in, st.tokens_out = result.model, result.tokens_in, result.tokens_out
        st.output = result.text
        if not result.text.strip():
            raise LLMError("model returned no text")
        return result.text


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


async def complete_json(task: Task, *, system: str, user: str, actor: Actor, name: str) -> dict[str, Any]:
    """Like complete(), for a model asked to answer with one JSON object."""
    return parse_json(await complete(task, system=system, user=user, actor=actor, name=name), name)


def parse_json(text: str, name: str) -> dict[str, Any]:
    """Read the one JSON object a model was asked for. A code fence around it is allowed."""
    try:
        data = json.loads(_FENCE.sub("", text.strip()))
    except json.JSONDecodeError as exc:
        raise LLMError(f"{name}: model did not return JSON") from exc
    if not isinstance(data, dict):
        raise LLMError(f"{name}: expected a JSON object")
    return data
