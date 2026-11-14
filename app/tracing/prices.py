"""Cost per call from config/prices.yaml (USD per 1M tokens)."""

from __future__ import annotations

from functools import lru_cache

import yaml

from app.config import ROOT


@lru_cache(maxsize=1)
def _table() -> dict[str, dict[str, float]]:
    with (ROOT / "config" / "prices.yaml").open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {str(k): {"input": float(v["input"]), "output": float(v["output"])} for k, v in data.items()}


def cost_usd(model: str | None, tokens_in: int | None, tokens_out: int | None) -> float | None:
    """Return the call cost, or None when the model is unknown or no tokens were recorded."""
    if model is None or (tokens_in is None and tokens_out is None):
        return None
    price = _table().get(model)
    if price is None:
        return None
    total = (tokens_in or 0) * price["input"] + (tokens_out or 0) * price["output"]
    return round(total / 1_000_000, 8)
