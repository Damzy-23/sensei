"""Config files parse and agree with the code and with .env.example. Every endpoint in
docs/API.md is registered on the app."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from app.config import ROOT
from app.llm.models import _registry
from app.main import app
from app.policy import load_policy
from app.tracing.prices import _table

API_DOC = ROOT / "docs" / "API.md"


def test_policy_loads_and_matches_spec_numbers() -> None:
    p = load_policy()
    assert p.hint_ladder.max_level == 5
    assert p.hint_ladder.reply_max_words == 60
    assert p.hint_ladder.min_wait_seconds == 120
    assert p.guard.violation_escalation_count == 3
    assert p.guard.frustration_escalation_count == 2
    assert p.escalation.stuck_hint_level == 5


def test_model_registry_has_the_four_spec_keys() -> None:
    assert set(_registry()) == {"reasoning", "fast", "hint_base", "hint_tuned"}


def test_prices_cover_the_default_models() -> None:
    prices = _table()
    assert {"claude-sonnet-5-5", "claude-haiku-5-5"} <= set(prices)


def test_env_example_lists_every_setting_the_code_reads() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    documented = set(re.findall(r"^([A-Z_]+)=", example, flags=re.M))
    read_by_code = {
        "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL_REASONING", "ANTHROPIC_MODEL_FAST",
        "HINT_MODEL", "HINT_TUNED_BASE_URL", "HINT_TUNED_API_KEY", "HINT_TUNED_MODEL",
        "SENSEI_DB_PATH", "SENSEI_USE_STUBS", "DEMO_MODE",
    }
    assert read_by_code <= documented


def test_no_secret_values_in_env_example() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if line.startswith(("ANTHROPIC_API_KEY=", "HINT_TUNED_API_KEY=")):
            assert line.split("=", 1)[1] == "", "keys must be blank in .env.example"


def test_models_yaml_declares_every_key_it_needs() -> None:
    data = yaml.safe_load((ROOT / "config" / "models.yaml").read_text(encoding="utf-8"))
    assert data["hint_tuned"]["provider"] == "openai_compatible"
    assert data["reasoning"]["model_default"] == "claude-sonnet-5-5"
    assert data["fast"]["model_default"] == "claude-haiku-5-5"


def test_every_endpoint_in_api_doc_is_served() -> None:
    doc = API_DOC.read_text(encoding="utf-8")
    documented = set(re.findall(r"^### `(GET|POST) (/[^`]*)`", doc, flags=re.M))
    served = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    for method, path in documented:
        normalised = re.sub(r"\{[^}]+\}", "{x}", path)
        assert any(m == method and re.sub(r"\{[^}]+\}", "{x}", p) == normalised for m, p in served), f"{method} {path}"


def test_openapi_schema_builds() -> None:
    assert TestClient(app).get("/openapi.json").status_code == 200
