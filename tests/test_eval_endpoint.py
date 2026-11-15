"""/eval/results serves the stub until a run writes real results, then serves the real file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import state
from app.eval import winrate
from app.main import app
from app.models import EvalModelStats, EvalResults


def _results() -> EvalResults:
    stats = EvalModelStats(model_key="hint_base", win_rate=0.4, n=10, leak_rate=0.0,
                           criteria={"correct_level": 0.5, "socratic": 0.9, "helpful": 0.7, "brevity": 0.8})
    tuned = stats.model_copy(update={"model_key": "hint_tuned", "win_rate": 0.6})
    return EvalResults(status="ready", generated_at="2026-11-15T00:00:00+00:00",
                       held_out_problems=["coin-change"], base=stats, tuned=tuned, examples=[])


@pytest.fixture
def results_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(winrate, "RESULTS_DIR", tmp_path)
    return tmp_path


def test_stub_is_served_when_no_results_file_exists(results_dir: Path) -> None:
    body = TestClient(app).get("/eval/results").json()
    assert body["status"] == "stub"


def test_real_results_are_served_once_written(results_dir: Path) -> None:
    (results_dir / "results.json").write_text(_results().model_dump_json(), encoding="utf-8")
    body = TestClient(app).get("/eval/results").json()
    assert body["status"] == "ready"
    assert body["tuned"]["win_rate"] == 0.6


def test_eval_run_is_recorded_in_the_database(results_dir: Path) -> None:
    run_id = state.record_eval_run("ready", _results().model_dump_json())
    assert run_id.startswith("evr_")
    from app.db import get_conn

    row = get_conn().execute("SELECT status, results_json FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "ready"
    assert json.loads(row["results_json"])["status"] == "ready"
