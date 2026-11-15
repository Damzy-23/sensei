"""The output guard's counting: what is a line of code, and how many may pass."""

from __future__ import annotations

import pytest

from app.guards.leak import decide

ONE = "It records where you saw the number.\n`seen[n] = i`\nPut it inside the loop."


@pytest.mark.parametrize("reply, allowed, leaked, rule, lines", [
    ("Think about what you need to remember.", 0, False, "leak.none", 0),
    ("Think about what you need to remember.", 1, False, "leak.none", 0),
    (ONE, 0, True, "leak.code_line", 1),
    (ONE, 1, False, "leak.earned_line", 1),
    ("```python\nseen[n] = i\n```", 0, True, "leak.code_fence", 1),
    ("```python\nseen[n] = i\n```", 1, False, "leak.earned_line", 1),
    ("```python\nseen = {}\nseen[n] = i\n```", 1, True, "leak.too_many_lines", 2),
    ("`seen = {}`\n`seen[n] = i`", 1, True, "leak.too_many_lines", 2),
    ("`seen = {}; seen[n] = i`", 1, True, "leak.too_many_lines", 2),  # two statements on one line are two lines
    ("for i in range(n):\n    return i", 0, True, "leak.code_lines", 0),  # code without backticks is still code
    ("for i in range(n):\n    return i", 1, True, "leak.code_lines", 0),
])
def test_how_much_code_may_pass(reply: str, allowed: int, leaked: bool, rule: str, lines: int) -> None:
    result = decide(reply, allowed)
    assert (result.leaked, result.rule, result.code_lines) == (leaked, rule, lines)
    assert result.reason.startswith(f"rule {rule}")


def test_a_name_in_backticks_inside_a_sentence_is_not_a_line_of_code() -> None:
    assert decide("Look at how `nums` is used on your second line.").rule == "leak.none"
    assert decide("`nums`").rule == "leak.none"  # a bare name on its own line is not a statement


def test_one_prose_line_that_reads_like_code_is_let_through() -> None:
    assert decide("if you return early:\nyou skip the rest of the list.").leaked is False
