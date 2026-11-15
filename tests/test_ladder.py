"""Hint ladder gating and policy loading. Pure logic, no database or model."""

from __future__ import annotations

import pytest

from app.guards.ladder import decide_unlock
from app.policy import load_policy


@pytest.fixture
def ladder():
    return load_policy().hint_ladder


def test_policy_defines_five_levels_and_sixty_word_limit() -> None:
    policy = load_policy()
    assert sorted(policy.hint_ladder.levels) == [1, 2, 3, 4, 5]
    assert policy.hint_ladder.max_level == 5
    assert policy.hint_ladder.reply_max_words == 60
    assert policy.hint_ladder.pseudocode_max_lines == 12
    assert sorted(policy.canned_hints) == [1, 2, 3, 4, 5]


def test_no_unlock_without_a_request(ladder) -> None:
    d = decide_unlock(0, requested=False, failed_runs_since_unlock=5, seconds_since_last_unlock=999, ladder=ladder)
    assert d.granted is False
    assert d.level == 0
    assert "did not ask" in d.reason


def test_failed_run_since_last_unlock_grants_next_level(ladder) -> None:
    d = decide_unlock(1, requested=True, failed_runs_since_unlock=1, seconds_since_last_unlock=3, ladder=ladder)
    assert d.granted is True
    assert d.level == 2


def test_waiting_long_enough_grants_next_level(ladder) -> None:
    d = decide_unlock(1, requested=True, failed_runs_since_unlock=0,
                      seconds_since_last_unlock=ladder.min_wait_seconds, ladder=ladder)
    assert d.granted is True
    assert d.level == 2


def test_asking_too_soon_with_no_failed_run_is_denied(ladder) -> None:
    d = decide_unlock(1, requested=True, failed_runs_since_unlock=0,
                      seconds_since_last_unlock=ladder.min_wait_seconds - 1, ladder=ladder)
    assert d.granted is False
    assert d.level == 1


def test_unknown_elapsed_time_does_not_count_as_waited(ladder) -> None:
    d = decide_unlock(0, requested=True, failed_runs_since_unlock=0, seconds_since_last_unlock=None, ladder=ladder)
    assert d.granted is False


def test_levels_are_never_skipped(ladder) -> None:
    # Even with plenty of failures and wait, one request moves exactly one level.
    level = 0
    for _ in range(ladder.max_level + 3):
        d = decide_unlock(level, requested=True, failed_runs_since_unlock=10, seconds_since_last_unlock=10_000, ladder=ladder)
        assert d.level in {level, level + 1}
        level = d.level
    assert level == ladder.max_level


def test_no_unlock_past_the_last_level(ladder) -> None:
    d = decide_unlock(ladder.max_level, requested=True, failed_runs_since_unlock=9,
                      seconds_since_last_unlock=9999, ladder=ladder)
    assert d.granted is False
    assert d.level == ladder.max_level
