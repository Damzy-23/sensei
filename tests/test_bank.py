"""Phase 3 bank tests: validation, the public-view guarantee, and the DB-backed tools."""

from __future__ import annotations

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from app import bank, state
from app.config import ROOT
from app.main import app
from app.tools import orchestrator, planner
from app.tools import interviewer

REQUIRED_PATTERNS = {
    "two pointers", "sliding window", "hash map", "stack",
    "binary search", "intervals", "BFS/DFS", "dynamic programming", "heap",
}


def test_bank_has_fourteen_problems_covering_required_patterns() -> None:
    problems = bank.list_problems()
    assert len(problems) == 14
    assert {p.pattern for p in problems} >= REQUIRED_PATTERNS


def test_reference_solutions_pass_all_tests() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_bank.py")],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize("problem_id", [p.id for p in bank.list_problems()])
def test_hint_seeds_cover_levels_one_to_five(problem_id: str) -> None:
    seeds = bank.get_hint_seeds(problem_id)
    assert sorted(seeds) == [1, 2, 3, 4, 5]
    assert len(seeds[5].splitlines()) <= 12


@pytest.mark.parametrize("problem_id", [p.id for p in bank.list_problems()])
def test_public_view_has_no_solution_or_hidden_tests(problem_id: str) -> None:
    view = bank.get_public(problem_id)
    assert view is not None
    dumped = view.model_dump()
    assert {"reference_solution", "hidden_tests", "hint_seeds"}.isdisjoint(dumped)


@pytest.mark.parametrize("problem_id", [p.id for p in bank.list_problems()])
def test_api_response_contains_no_reference_or_hidden_test(problem_id: str) -> None:
    client = TestClient(app)
    text = client.get(f"/problems/{problem_id}").text
    assert bank.get_reference(problem_id).strip() not in text
    for hidden in bank.get_hidden_tests(problem_id):
        assert hidden["call"] not in text, f"hidden test leaked: {hidden['call']}"
    for level, seed in bank.get_hint_seeds(problem_id).items():
        assert seed not in text, f"hint seed level {level} leaked to the public view"


def test_list_endpoint_returns_fourteen_public_summaries() -> None:
    client = TestClient(app)
    body = client.get("/problems").json()
    assert len(body) == 14
    assert all(set(p) == {"id", "title", "difficulty", "pattern"} for p in body)


def test_query_filters_by_pattern_and_difficulty() -> None:
    stacks = planner.query_problem_bank("stack", None)
    assert [p["id"] for p in stacks] == ["valid-parentheses"]
    hard = planner.query_problem_bank(None, "hard")
    assert hard == []


def test_get_problem_tool_returns_public_view_only() -> None:
    view = interviewer.get_problem("two-sum")
    assert "reference_solution" not in view
    assert "hidden_tests" not in view
    with pytest.raises(KeyError):
        interviewer.get_problem("nope")


def test_read_and_write_state_tools_round_trip() -> None:
    sid = state.create_session()
    orchestrator.write_state(sid, {"hint_level": 2, "failed_runs": 3})
    current = orchestrator.read_state(sid)
    assert current["hint_level"] == 2
    assert current["failed_runs"] == 3
    with pytest.raises(KeyError):
        orchestrator.read_state("ses_missing")
