"""Bullet scoring, job fit, drafts with blanks, and role research. The numbers are rule-based,
so these tests pin the rules and the evidence each score reports."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.agents.cv_writer import has_blank
from app.cv.fit import Requirement, job_fit
from app.cv.scoring import contains_term, score_bullet
from app.llm import gateway
from app.llm.gateway import LLMResult
from app.main import app

JOB = "Backend Engineer at Kora. You need Python, PostgreSQL and Kubernetes. Go is a nice to have. You will own on-call."
CV = ("Ada Okafor\nBackend Engineer, Kora, 2022-2025: built a card payment API in Python handling 2M requests a day; "
      "migrated MySQL to PostgreSQL; ran the on-call rota.\nBSc Computer Science, 2020.\nSkills: Python, PostgreSQL, Docker, Google Cloud.")


def _checks(text: str, terms: list[str] | None = None) -> dict[str, int]:
    return {c.id: c.points for c in score_bullet(text, terms).checks}


def test_a_strong_bullet_scores_full_marks_and_says_why() -> None:
    result = score_bullet("Reduced payment API latency by 40% by moving hot queries to PostgreSQL read replicas", ["PostgreSQL", "API"])
    assert (result.score, result.max) == (10, 10)
    details = {c.id: c.detail for c in result.checks}
    assert '"40%"' in details["result"] and "PostgreSQL" in details["relevance"] and '"Reduced"' in details["action"]


def test_a_weak_bullet_loses_points_for_named_reasons() -> None:
    result = score_bullet("Responsible for various backend things", ["Python"])
    assert _checks("Responsible for various backend things", ["Python"]) == {
        "action": 0, "result": 0, "relevance": 0, "length": 0, "specific": 0}
    assert result.score == 0 and result.max == 10
    assert "describes a duty" in result.checks[0].detail and '"various"' in result.checks[-1].detail


def test_an_outcome_word_without_a_number_earns_partial_credit() -> None:
    assert _checks("Improved the reliability of the nightly billing export job for finance")["result"] == 1


def test_without_job_terms_relevance_is_skipped_not_scored_as_zero() -> None:
    result = score_bullet("Built a payments API in Python serving 2M requests a day for merchants")
    assert "relevance" not in {c.id for c in result.checks}
    assert result.max == 7 and result.score == 7


def test_terms_match_whole_words_only() -> None:
    assert contains_term("Deployed to Google Cloud", "Go") is False
    assert contains_term("Wrote services in Go and C++", "Go") and contains_term("Wrote services in Go and C++", "C++")
    assert contains_term("Used postgresql daily", "PostgreSQL")


def test_fit_weights_must_haves_double_and_lists_the_evidence() -> None:
    reqs = [Requirement("Python", (), "must"), Requirement("Kubernetes", ("k8s",), "must"), Requirement("Go", (), "nice")]
    result = job_fit(reqs, CV)
    assert result.score == 40  # Python (2) of Python 2 + Kubernetes 2 + Go 1
    assert [r.term for r in result.matched] == ["Python"] and [r.term for r in result.missing] == ["Kubernetes", "Go"]
    assert job_fit(reqs, CV + " Ran k8s clusters.").score == 80  # an alias counts
    assert job_fit([], CV).score is None  # nothing to measure against is unknown, not zero


def test_a_draft_must_still_have_a_blank() -> None:
    assert has_blank("Deployed [which service] to Kubernetes")
    assert not has_blank("Deployed the payments service to Kubernetes")
    assert not has_blank("Deployed [] to Kubernetes")


class CvModel:
    def __init__(self) -> None:
        self.job = {"role_title": "Backend Engineer", "company": "Kora", "requirements": [
            {"term": "Python", "aliases": [], "importance": "must"},
            {"term": "Kubernetes", "aliases": ["k8s"], "importance": "must"},
            {"term": "Go", "aliases": [], "importance": "nice"},
            {"term": "Rust", "aliases": [], "importance": "must"},  # not in the job text: must be dropped
        ]}
        self.cv = {"name": "Ada Okafor", "headline": "Backend Engineer", "summary": "Builds payment APIs.",
                   "skills": ["Python", "PostgreSQL"], "education": ["BSc Computer Science, 2020"],
                   "experience": [{"role": "Backend Engineer", "company": "Kora", "dates": "2022-2025", "bullets": [
                       "Built a card payment API in Python handling 2M requests a day", "Responsible for the on-call rota"]}],
                   "gaps": ["Kubernetes"],
                   "suggested_lines": [
                       {"gap": "Kubernetes", "draft": "Deployed [which service] to Kubernetes, cutting [what] by [how much]", "question": "Have you run anything on Kubernetes?"},
                       {"gap": "Kubernetes", "draft": "Ran production Kubernetes clusters for the payments team", "question": "?"}]}
        self.job_reply: str | None = None

    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
        if "list what it asks a candidate to have" in system:
            return LLMResult(self.job_reply or json.dumps(self.job), model, 200, 80)
        return LLMResult(json.dumps(self.cv), model, 900, 400)


@pytest.fixture
def model(tmp_path, monkeypatch) -> CvModel:
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "sensei.db"))
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("LINKUP_API_KEY", raising=False)
    db.reset_connection()
    scripted = CvModel()
    gateway.set_client(scripted)
    yield scripted
    gateway.set_client(None)
    db.reset_connection()


@pytest.fixture
def client(model: CvModel) -> TestClient:
    return TestClient(app)


def test_tailor_returns_fit_bullet_scores_and_only_drafts_with_blanks(client: TestClient) -> None:
    body = client.post("/cv/tailor", json={"job_description": JOB, "cv_text": CV}).json()
    assert body["role_title"] == "Backend Engineer" and body["company"] == "Kora"
    assert body["job_terms"] == ["Python", "Kubernetes", "Go"]  # Rust was not in the job text
    assert body["fit"]["score"] == 40
    assert [r["term"] for r in body["fit"]["missing"]] == ["Kubernetes", "Go"]
    assert "original CV" in body["fit"]["note"]
    scores = body["experience"][0]["bullet_scores"]
    assert [s["score"] for s in scores] == [9, 1] and all(s["max"] == 10 for s in scores)
    assert [line["draft"] for line in body["suggested_lines"]] == ["Deployed [which service] to Kubernetes, cutting [what] by [how much]"]


def test_an_unreadable_job_costs_the_fit_score_not_the_cv(client: TestClient, model: CvModel) -> None:
    model.job_reply = "sorry, no"
    r = client.post("/cv/tailor", json={"job_description": JOB, "cv_text": CV})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Ada Okafor" and body["fit"]["score"] is None
    assert "could not be read" in body["fit"]["note"]
    assert body["experience"][0]["bullet_scores"][0]["max"] == 7  # no job terms: relevance skipped


def test_score_endpoint_scores_typed_lines_without_a_model(client: TestClient, model: CvModel) -> None:
    async def explode(**_: object) -> LLMResult:
        raise AssertionError("scoring must not call a model")

    model.complete = explode  # type: ignore[method-assign]
    r = client.post("/cv/score", json={"bullets": ["Cut deploy time by 60% with a Kubernetes rollout pipeline in Python"], "job_terms": ["Kubernetes", "Python"]})
    assert r.status_code == 200 and r.json()["scores"][0]["score"] == 10
    assert client.post("/cv/score", json={"bullets": []}).status_code == 422


def test_research_reports_each_search_that_is_not_set_up(client: TestClient) -> None:
    body = client.post("/cv/research", json={"role_title": "Backend Engineer", "company": "Kora"}).json()
    assert body["linkup"] == {"available": False, "reason": "Linkup is not set up on this server (LINKUP_API_KEY is missing).", "answer": "", "sources": []}
    assert body["exa"]["available"] is False and "EXA_API_KEY" in body["exa"]["reason"]
    assert body["trace_id"].startswith("trc_")


def test_research_in_stub_mode_returns_both_sample_searches(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("SENSEI_USE_STUBS", "1")
    body = client.post("/cv/research", json={"role_title": "Backend Engineer"}).json()
    assert body["linkup"]["available"] and len(body["linkup"]["sources"]) == 3
    assert body["exa"]["available"] and len(body["exa"]["sources"]) == 2


def test_fit_accepts_a_simple_plural_but_not_on_short_names() -> None:
    assert job_fit([Requirement("payment APIs", (), "must")], "Built a card payment API in Python").score == 100
    assert job_fit([Requirement("microservice", (), "must")], "Ran 12 microservices").score == 100
    assert job_fit([Requirement("Go", (), "must")], "The team gos fast").score == 0


def test_a_past_tense_duty_opener_is_still_a_weak_opener() -> None:
    assert _checks("Were responsible for the on-call rota across the payments team")["action"] == 0
