"""CV studio: the tailor endpoint, run against a scripted model so no network is needed."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import db
from app.api import cv
from app.llm import gateway
from app.llm.gateway import LLMResult
from app.tracing import store

JOB = "Senior Backend Engineer. You will work in Python and SQL and run workloads on Kubernetes."
CV = "Alex Morgan\nSoftware Engineer, Northwind Labs, 2021 to present\nBuilt Python internal tools used by 40 engineers."
TAILORED = {
    "name": "Alex Morgan",
    "headline": "Software engineer, Python",
    "summary": "Software engineer at Northwind Labs building Python internal tools.",
    "skills": ["Python"],
    "experience": [
        {"role": "Software Engineer", "company": "Northwind Labs", "dates": "2021 to present",
         "bullets": ["Built Python internal tools used by 40 engineers."]}
    ],
    "education": [],
    "gaps": ["SQL", "Kubernetes"],
}


class ScriptedModel:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[tuple[str, str]] = []

    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
        self.calls.append((model, user))
        return LLMResult(self.text, model, 900, 300)


@pytest.fixture
def model(tmp_path, monkeypatch) -> ScriptedModel:
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "sensei.db"))
    db.reset_connection()
    scripted = ScriptedModel(json.dumps(TAILORED))
    gateway.set_client(scripted)
    yield scripted
    gateway.set_client(None)
    db.reset_connection()


@pytest.fixture
def client(model: ScriptedModel) -> TestClient:
    app = FastAPI()
    app.include_router(cv.router)
    return TestClient(app)


def _tailor(client: TestClient, job: str = JOB, cv_text: str = CV):
    return client.post("/cv/tailor", json={"job_description": job, "cv_text": cv_text})


def test_tailor_returns_the_cv_fields_and_a_trace_id(client: TestClient, model: ScriptedModel) -> None:
    r = _tailor(client)
    assert r.status_code == 200
    body = r.json()
    assert body["trace_id"].startswith("trc_")
    # Each role now also carries rule-based scores for its bullets; the tailored fields are unchanged.
    scores = [role.pop("bullet_scores") for role in body["experience"]]
    assert {k: body[k] for k in TAILORED} == TAILORED
    assert [len(per_role) for per_role in scores] == [len(role["bullets"]) for role in TAILORED["experience"]]
    assert body["gaps"] == ["SQL", "Kubernetes"]  # what the CV lacks is reported, not added
    assert "Kubernetes" not in body["skills"]
    assert JOB in model.calls[0][1] and CV in model.calls[0][1]  # the model saw both texts


def test_the_model_call_is_traced_with_model_and_cost(client: TestClient) -> None:
    events = store.load_trace(_tailor(client).json()["trace_id"])
    steps = [(e.actor, e.type, e.name) for e in events]
    assert ("cv_writer", "agent.start", "cv_writer") in steps
    call = next(e for e in events if e.type == "llm.call")
    assert call.name == "llm_tailor_cv" and call.actor == "cv_writer" and call.model == "claude-sonnet-5-5"
    assert call.tokens_in == 900 and call.tokens_out == 300
    assert call.cost_usd == pytest.approx((900 * 2 + 300 * 10) / 1_000_000)
    assert events[-1].type == "turn.end" and events[-1].status == "ok"


def test_model_output_that_is_not_json_gives_502(client: TestClient, model: ScriptedModel) -> None:
    model.text = "Here is the CV you asked for."
    r = _tailor(client)
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "JSON" in detail["detail"] and detail["trace_id"].startswith("trc_")
    assert store.load_trace(detail["trace_id"])[-1].status == "error"


def test_model_output_with_the_wrong_shape_gives_502(client: TestClient, model: ScriptedModel) -> None:
    model.text = json.dumps({**TAILORED, "skills": "Python"})
    r = _tailor(client)
    assert r.status_code == 502 and "'skills' must be a list" in r.json()["detail"]["detail"]


def test_a_cv_that_is_too_short_gives_422_and_calls_no_model(client: TestClient, model: ScriptedModel) -> None:
    assert _tailor(client, cv_text="Alex Morgan").status_code == 422
    blank = _tailor(client, cv_text="Alex" + " " * 80)  # long enough by length, almost no text
    assert blank.status_code == 422 and "at least 50 characters" in blank.json()["detail"]
    assert model.calls == []


def test_stub_mode_is_labelled_and_calls_no_model(client: TestClient, model: ScriptedModel, monkeypatch) -> None:
    monkeypatch.setenv("SENSEI_USE_STUBS", "1")
    body = _tailor(client).json()
    assert body["headline"] == "Sample output (stub mode)" and body["name"] == "Alex Morgan"
    assert body["experience"] == [] and model.calls == []
