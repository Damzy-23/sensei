"""Resolve a model key from config/models.yaml into a concrete provider, model and credentials.

Environment is read at resolve time, so changing .env and restarting is enough.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import yaml

from app.config import ROOT

ModelKey = Literal["reasoning", "fast", "hint_base", "hint_tuned"]
Provider = Literal["anthropic", "openai_compatible"]


class ModelNotConfigured(RuntimeError):
    """A required env var (API key, base URL or model name) is missing."""


@dataclass(frozen=True)
class ModelTarget:
    key: str
    provider: Provider
    model: str
    base_url: str | None
    api_key: str | None


@lru_cache(maxsize=1)
def _registry() -> dict[str, dict[str, str]]:
    with (ROOT / "config" / "models.yaml").open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve(model_key: str) -> ModelTarget:
    entry = _registry().get(model_key)
    if entry is None:
        raise ModelNotConfigured(f"unknown model key: {model_key}")

    provider: Provider = entry["provider"]
    if provider == "anthropic":
        model = os.getenv(entry["model_env"], "").strip() or entry["model_default"]
        api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise ModelNotConfigured("ANTHROPIC_API_KEY is not set")
        return ModelTarget(key=model_key, provider=provider, model=model, base_url=None, api_key=api_key)

    base_url = os.getenv(entry["base_url_env"], "").strip()
    api_key = os.getenv(entry["api_key_env"], "").strip()
    model = os.getenv(entry["model_env"], "").strip()
    missing = [name for name, val in [(entry["base_url_env"], base_url), (entry["api_key_env"], api_key), (entry["model_env"], model)] if not val]
    if missing:
        raise ModelNotConfigured(f"{model_key} needs env: {', '.join(missing)}")
    return ModelTarget(key=model_key, provider=provider, model=model, base_url=base_url.rstrip("/"), api_key=api_key)
