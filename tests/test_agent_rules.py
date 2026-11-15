"""Pure agent rules: failure classification, mastery update, pattern choice, static checks,
and that prompts never carry the reference solution."""

from __future__ import annotations

import pytest

from app import bank
from app.agents import rules


@pytest.mark.parametrize("failures,expected", [
    ([], "wrong_answer"),
    ([{"name": "basic", "message": "expected [0, 1], got None"}], "wrong_answer"),
    ([{"name": "empty input", "message": "expected 0, got 1"}], "edge_case"),
    ([{"name": "large", "message": "timed out after 10s"}], "timeout"),
    ([{"name": "crash", "message": "IndexError: list index out of range"}], "runtime_error"),
])
def test_classify_failure(failures, expected) -> None:
    assert rules.classify_failure(failures) == expected


def test_elo_solve_raises_mastery_and_abandon_lowers_it() -> None:
    up = rules.elo_update(0.5, 1.0, "easy")
    down = rules.elo_update(0.5, 0.0, "easy")
    assert up > 0.5 > down


def test_elo_stays_within_bounds() -> None:
    assert rules.elo_update(1.0, 1.0, "easy") <= 1.0
    assert rules.elo_update(0.0, 0.0, "hard") >= 0.0


def test_harder_problem_gains_more_for_a_solve() -> None:
    easy_gain = rules.elo_update(0.5, 1.0, "easy") - 0.5
    hard_gain = rules.elo_update(0.5, 1.0, "hard") - 0.5
    assert hard_gain > easy_gain


def test_pick_pattern_chooses_weakest_then_bank_order() -> None:
    patterns = ["stack", "hash map", "heap"]
    assert rules.pick_pattern({"stack": 0.9, "hash map": 0.2}, patterns) == "heap"
    assert rules.pick_pattern({}, patterns) == "stack"
    assert rules.pick_pattern({}, []) is None


def test_target_difficulty_bands() -> None:
    assert rules.target_difficulty(0.1) == "easy"
    assert rules.target_difficulty(0.5) == "medium"
    assert rules.target_difficulty(0.9) == "hard"


def test_static_issues_detects_syntax_and_missing_return() -> None:
    assert rules.static_issues("def f(:\n    pass") != []
    assert any("never returns" in i for i in rules.static_issues("def f(x):\n    x + 1\n"))
    assert rules.static_issues("def f(x):\n    return x\n") == []


@pytest.mark.parametrize("problem_id", [p.id for p in bank.list_problems()])
def test_hint_prompts_never_contain_the_reference_solution(problem_id: str) -> None:
    reference = bank.get_reference(problem_id)
    public = bank.get_public(problem_id)
    assert public is not None
    for level in range(1, 6):
        system = rules.hint_system_prompt(level, "instruction", bank.get_hint_seeds(problem_id)[level], False)
        user = rules.hint_user_prompt(public.title, public.statement, "pass", "none", level)
        # Seeds are allowed in the system prompt; the reference function body is never included.
        first_line = reference.strip().splitlines()[0]
        assert first_line not in user
        assert reference.strip() not in system


def test_stricter_prompt_adds_restriction() -> None:
    assert "broke the rules" in rules.hint_system_prompt(2, "x", "seed", True)
    assert "broke the rules" not in rules.hint_system_prompt(2, "x", "seed", False)
