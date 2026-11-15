"""Hint data pipeline with injected fake functions: filters, held-out split, output shape."""

from __future__ import annotations

import asyncio
import json

from app import bank
from app.eval import hint_data

TRAIN_PROBLEMS = ["two-sum", "valid-parentheses"]


def _attempt(name: str) -> dict[str, str]:
    return {"code": "def f(x):\n    return x", "failure_name": name, "failure_message": "wrong"}


async def _attempts(problem_id: str) -> list[dict[str, str]]:
    return [_attempt(f"case {i}") for i in range(5)]


async def _good_hint(problem_id: str, level: int, attempt: dict[str, str]) -> str:
    return f"Level {level}: what would you remember as you scan?"


async def _check_pass(problem_id: str, level: int, hint: str) -> bool:
    return True


async def _judge_pass(problem_id: str, level: int, hint: str, attempt: dict[str, str]) -> dict[str, bool]:
    return {"right_level": True, "socratic": True, "helpful": True}


def test_clean_run_produces_rows_for_every_level_and_attempt() -> None:
    train, held = asyncio.run(hint_data.build(
        TRAIN_PROBLEMS, attempt_fn=_attempts, hint_fn=_good_hint, check_fn=_check_pass, judge_fn=_judge_pass,
    ))
    expected = len(TRAIN_PROBLEMS) * 5 * 5 * hint_data.VARIANTS_PER_HINT
    assert len(train) == expected
    assert held == []


def test_leaking_hints_are_dropped() -> None:
    async def check_block(problem_id, level, hint):  # noqa: ANN001
        return False

    train, _ = asyncio.run(hint_data.build(
        ["two-sum"], attempt_fn=_attempts, hint_fn=_good_hint, check_fn=check_block, judge_fn=_judge_pass,
    ))
    assert train == []


def test_rubric_failures_are_dropped() -> None:
    async def judge_fail(problem_id, level, hint, attempt):  # noqa: ANN001
        return {"right_level": True, "socratic": False, "helpful": True}

    train, _ = asyncio.run(hint_data.build(
        ["two-sum"], attempt_fn=_attempts, hint_fn=_good_hint, check_fn=_check_pass, judge_fn=judge_fail,
    ))
    assert train == []


def test_hints_over_sixty_words_are_dropped() -> None:
    async def long_hint(problem_id, level, attempt):  # noqa: ANN001
        return " ".join(["word"] * 61)

    train, _ = asyncio.run(hint_data.build(
        ["two-sum"], attempt_fn=_attempts, hint_fn=long_hint, check_fn=_check_pass, judge_fn=_judge_pass,
    ))
    assert train == []


def test_held_out_problems_are_never_trained_on() -> None:
    problems = list(hint_data.HOLDOUT_PROBLEMS) + ["two-sum"]
    train, held = asyncio.run(hint_data.build(
        problems, attempt_fn=_attempts, hint_fn=_good_hint, check_fn=_check_pass, judge_fn=_judge_pass,
    ))
    assert {row["problem_id"] for row in train} == {"two-sum"}
    assert {s.problem_id for s in held} == set(hint_data.HOLDOUT_PROBLEMS)
    assert len(held) == len(hint_data.HOLDOUT_PROBLEMS) * 5 * 5


def test_training_rows_have_chat_shape_and_no_reference() -> None:
    train, _ = asyncio.run(hint_data.build(
        ["two-sum"], attempt_fn=_attempts, hint_fn=_good_hint, check_fn=_check_pass, judge_fn=_judge_pass,
    ))
    row = train[0]
    assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
    serialised = json.dumps(row)
    reference_first_line = bank.get_reference("two-sum").splitlines()[0]
    assert reference_first_line not in serialised


def test_holdout_list_is_three_distinct_problems() -> None:
    assert len(set(hint_data.HOLDOUT_PROBLEMS)) == 3
    ids = {p.id for p in bank.list_problems()}
    assert set(hint_data.HOLDOUT_PROBLEMS) <= ids


def test_write_and_load_round_trip(tmp_path) -> None:  # noqa: ANN001
    _, held = asyncio.run(hint_data.build(
        list(hint_data.HOLDOUT_PROBLEMS), attempt_fn=_attempts, hint_fn=_good_hint,
        check_fn=_check_pass, judge_fn=_judge_pass,
    ))
    hint_data.write_outputs([], held, out_dir=tmp_path)
    loaded = hint_data.load_scenarios(tmp_path / "test.jsonl")
    assert loaded == held
