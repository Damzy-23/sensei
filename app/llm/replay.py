"""DEMO_MODE response cache.

With DEMO_MODE=1, every successful model call is cached on disk (data/demo/llm_cache.json), keyed
by the model key, system prompt and messages. If a later call fails (network down, timeout,
missing key), the cached reply for the same request is replayed instead. The replay is logged
to the console and recorded in the trace, so it is never silent.

Requests that were never cached still fail, as they would without DEMO_MODE.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

from app.config import ROOT

CACHE_PATH = ROOT / "data" / "demo" / "llm_cache.json"
log = logging.getLogger("sensei.demo")
_lock = threading.Lock()


def cache_key(model_key: str, system: str, messages: list[dict[str, str]]) -> str:
    raw = json.dumps({"model": model_key, "system": system, "messages": messages}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("DEMO_MODE cache at %s is unreadable; ignoring it", path)
        return {}


def get(model_key: str, system: str, messages: list[dict[str, str]], path: Path | None = None) -> dict[str, Any] | None:
    return _load(path or CACHE_PATH).get(cache_key(model_key, system, messages))


def put(model_key: str, system: str, messages: list[dict[str, str]], entry: dict[str, Any],
        path: Path | None = None) -> None:
    path = path or CACHE_PATH
    with _lock:
        data = _load(path)
        data[cache_key(model_key, system, messages)] = entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
