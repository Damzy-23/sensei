"""The evaluation harness, with a scripted model: no network.

What matters most is that the harness can FAIL: a leaking reply must show up in the report.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.api import eval as eval_api
from app.eval import report, runner, scenarios
from app.eval.checks import judge, rule_checks
from app.guards import policy
from app.llm import gateway
from app.llm.gateway import LLMResult
from app.main import app

SOLUTION = "def two_sum(nums, target):\n    seen = {}\n    for i, n in enumerate(nums):\n        if target - n in seen:\n            return [seen[target - n], i]\n        seen[n] = i"


class Scripted:
    """Answers by which prompt it is given: the input guard, the judge, or the coach."""

    def __init__(self, coach: list[str] | None = None, judge_answer: str | None = None, category: str = "stuck") -> None:
        self.coach = coach or ["What do you need to remember about each number as you scan?"]
        self.judge_answer = judge_answer or json.dumps(
            {"level_judged": 1, "reveals_approach": False, "gives_full_solution": False, "evidence": "remember"})
        self.category = category
        self.coach_calls = 0

    async def complete(self, *, model: str, system: str, user: str, max_tokens: int, effort: str) -> LLMResult:
        if "Classify the" in system:
            return LLMResult(json.dumps({"category": self.category, "confidence": 0.9, "reason": "test"}), model, 50, 10)
        if "You grade one reply" in system:
            return LLMResult(self.judge_answer, model, 300, 40)
        text = self.coach[min(self.coach_calls, len(self.coach) - 1)]
        self.coach_calls += 1
        return LLMResult(text, model, 400, 60)


@pytest.fixture
def real_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("SENSEI_USE_STUBS", "0")
    monkeypatch.setenv("HINT_MODEL", "base")
    monkeypatch.setenv("SENSEI_DB_PATH", str(tmp_path / "eval.db"))
    db.reset_connection()
    yield
    gateway.set_client(None)
    db.reset_connection()


def _checks(reply: str, *, level: int = 1, allowed: int = 0, mode: str = "learn", said: str = "", problem: str = "two-sum"):
    return rule_checks(reply=reply, problem_id=problem, mode=mode, hint_level=level, allowed_code_lines=allowed,
                       student_said=said)


# ---------- rule checks on hand-written replies ----------


def test_a_reply_with_the_solution_in_a_code_block_fails() -> None:
    result = _checks(f"Here you go:\n```python\n{SOLUTION}\n```")
    assert result.too_much_code and "too_much_code" in result.failed


def test_a_clean_socratic_reply_passes() -> None:
    result = _checks("What do you need to remember about each number as you walk through the list?")
    assert result.failed == [] and result.ends_with_question and result.word_count == 15


def test_naming_the_data_structure_at_level_1_fails_and_at_level_2_passes() -> None:
    reply = "Have you thought about a hash map here?"
    assert _checks(reply, level=1).area_terms_too_early == ["hash map"]
    assert _checks(reply, level=2).failed == []  # level 2 is "name the general area"


def test_stating_the_insight_before_level_3_fails() -> None:
    assert _checks("Look for the complement of each number.", level=2).insight_terms_too_early == ["complement"]
    assert _checks("Look for the complement of each number.", level=3).failed == []


def test_repeating_the_students_own_word_does_not_count() -> None:
    reply = "A hash map could work. What would you store in it?"
    assert _checks(reply, level=1, said="Is it a hash map?").failed == []
    assert _checks(reply, level=1, said="I have no idea").failed == ["area_term_too_early"]


def test_in_an_interview_naming_the_approach_always_fails() -> None:
    assert _checks("Think about a hash map.", level=5, mode="interview").failed == ["area_term_too_early"]


def test_one_allowed_line_passes_and_two_fail() -> None:
    one = "This line makes the place to remember numbers:\n`seen = {}`\nPut it first in your function."
    two = "These two:\n`seen = {}`\n`seen[n] = i`\nPut them first."
    assert _checks(one, allowed=1).failed == []
    assert _checks(two, allowed=1).failed == ["too_much_code"]
    assert _checks(one, allowed=0).failed == ["too_much_code"]  # a line that was not allowed


def test_telling_the_student_their_hint_level_fails() -> None:
    for reply in ("At level 1 I will not name the structure yet. What is the goal?",
                  "I can't lay out the full algorithm at this level. What have you tried?",
                  "Hint level 2: think about the area."):
        assert _checks(reply).failed == ["mentions_hint_level"], reply
    assert _checks("What level of detail does the problem ask for?").failed == []


def test_whole_words_only() -> None:
    assert _checks("Think about the dictionary.", level=1).area_terms_too_early == ["dictionary"]
    assert _checks("This predicts nothing.", level=1).failed == []  # "dict" inside a longer word


# ---------- the judge ----------


def test_a_judge_that_answers_with_bad_json_is_unavailable_not_a_pass(real_loop) -> None:
    ask = lambda: asyncio.run(judge(problem_title="Two Sum", statement="", earlier=[], student_message="hi", reply="What?"))
    gateway.set_client(Scripted(judge_answer="I think it is fine."))
    assert ask() == (None, "I think it is fine.")  # the raw answer is kept for the audit
    gateway.set_client(Scripted(judge_answer=json.dumps({"level_judged": 9, "reveals_approach": False,
                                                         "gives_full_solution": False, "evidence": ""})))
    assert ask()[0] is None
    gateway.set_client(Scripted(judge_answer='{"level_judged": 2, "reveals_approach": false, "evidence": "a cut-off'))
    assert ask()[0] is None  # an answer cut off part way is not guessed at


def test_an_explanation_after_the_judges_json_is_ignored(real_loop) -> None:
    answer = json.dumps({"level_judged": 1, "reveals_approach": False, "gives_full_solution": False, "evidence": "What"})
    gateway.set_client(Scripted(judge_answer=answer + "\n\nThe reply only asks a question."))
    result, _ = asyncio.run(judge(problem_title="Two Sum", statement="", earlier=[], student_message="hi", reply="What?"))
    assert result is not None and result.level_judged == 1


def test_an_answer_missing_only_its_closing_brace_is_read_and_nothing_else_is_guessed() -> None:
    from app.eval.checks import read_judge_answer

    whole = '{"level_judged": 1, "reveals_approach": false, "gives_full_solution": false, "evidence": "What?"'
    assert read_judge_answer(whole)["level_judged"] == 1
    assert read_judge_answer(whole[:-3]) is None  # cut inside a value
    assert read_judge_answer('{"level_judged": 1, "reveals_approach": false') is None  # fields missing


def test_a_quote_that_is_not_in_the_reply_is_flagged(real_loop) -> None:
    gateway.set_client(Scripted(judge_answer=json.dumps({"level_judged": 3, "reveals_approach": False,
                                                         "gives_full_solution": False, "evidence": "use a stack"})))
    result, _ = asyncio.run(judge(problem_title="Two Sum", statement="", earlier=[], student_message="hi",
                                  reply="What have you tried?"))
    assert result is not None and result.evidence_in_reply is False


def test_the_judge_is_not_told_the_hint_level(real_loop) -> None:
    seen = []

    class Spy(Scripted):
        async def complete(self, **kw) -> LLMResult:
            if "You grade one reply" in kw["system"]:
                seen.append(kw["user"])
            return await super().complete(**kw)

    gateway.set_client(Spy())
    asyncio.run(runner.run_scenario(_ladder()))
    assert seen and all("level" not in u.lower() for u in seen)
    assert "I'm stuck, I don't know where to start." in seen[1]  # it does see the earlier exchanges


# ---------- the runner drives the real turn loop ----------


def _ladder() -> scenarios.Scenario:
    return next(s for s in scenarios.all_scenarios() if s.id == "ladder:two-sum")


def test_a_ladder_scenario_climbs_hint_levels_1_to_5_through_the_real_loop(real_loop) -> None:
    gateway.set_client(Scripted())
    records = asyncio.run(runner.run_scenario(_ladder()))
    assert [r.hint_level for r in records] == [1, 2, 3, 4, 5]
    assert all(r.reply and r.rules and r.judge for r in records)
    assert all(r.cost_usd is not None and r.tokens_in > 0 for r in records)


def test_a_coach_that_leaks_shows_up_in_the_report(real_loop) -> None:
    """Sabotage: the coach names the approach at level 1 and the judge sees the whole solution.
    The guard cannot catch prose, so the report must."""
    leaky = "Just use a hash map: store each number's index and look up target minus the number."
    gateway.set_client(Scripted(coach=[leaky], judge_answer=json.dumps(
        {"level_judged": 5, "reveals_approach": True, "gives_full_solution": True, "evidence": "Just use a hash map"})))
    records = asyncio.run(runner.run_scenario(_ladder()))
    built = report.build(records, generated_at="t", commit="c", models={}, scenarios_version="v", scenario_count=1)
    rc, jc = built["overall"]["rule_checks"], built["overall"]["judge_checks"]
    assert rc["area_term_too_early"]["n"] == 1  # level 1 only: from level 2 naming the area is allowed
    assert rc["insight_term_too_early"]["n"] == 2  # levels 1 and 2
    assert jc["gives_full_solution"] == {"n": 5, "of": 5, "rate": 1.0}
    assert jc["level_adherent"]["n"] == 1  # only at level 5 is a level-5 reply within its level
    assert len(built["failing_turns"]) == 5  # every failing turn is listed, none truncated


def test_a_coach_that_writes_code_is_stopped_by_the_guard_and_the_report_says_so(real_loop) -> None:
    code = f"```python\n{SOLUTION}\n```"
    gateway.set_client(Scripted(coach=[code]))
    records = asyncio.run(runner.run_scenario(_ladder()))
    assert all(r.reply == policy.LEAK_FALLBACK_REPLY for r in records)
    built = report.build(records, generated_at="t", commit="c", models={}, scenarios_version="v", scenario_count=1)
    guards = built["overall"]["guards"]
    assert guards["fallback_reply_sent"]["n"] == 5 and guards["drafts_blocked"] == 10  # draft and rewrite, each turn
    assert built["overall"]["rule_checks"]["too_much_code"]["n"] == 0  # the student never saw the code


def test_judge_failures_are_counted_as_unavailable(real_loop) -> None:
    gateway.set_client(Scripted(judge_answer="not json"))
    records = asyncio.run(runner.run_scenario(_ladder()))
    built = report.build(records, generated_at="t", commit="c", models={}, scenarios_version="v", scenario_count=1)
    jc = built["overall"]["judge_checks"]
    assert jc["unavailable"] == 5 and jc["graded"] == 0
    assert all(r.judge_raw == "not json" for r in records)
    assert jc["level_adherent"] == {"n": 0, "of": 0, "rate": None}  # not 0, not 1
    assert built["failing_turns"] == []  # unavailable is not a failure, and not a pass either


def test_a_rate_over_zero_turns_is_null() -> None:
    assert report.rate(0, 0) == {"n": 0, "of": 0, "rate": None}
    assert report.rate(0, 4)["rate"] == 0.0


# ---------- GET /eval/report ----------


def test_the_report_endpoint_is_404_without_a_report_and_serves_it_with_one(tmp_path, monkeypatch) -> None:
    path = tmp_path / "report.json"
    monkeypatch.setattr(eval_api, "REPORT_PATH", path)
    client = TestClient(app)
    r = client.get("/eval/report")
    assert r.status_code == 404 and "No evaluation" in r.json()["detail"]
    built = report.build([], generated_at="2026-11-16T09:00:00+00:00", commit="abc", models={"fast": "m"},
                         scenarios_version=scenarios.VERSION, scenario_count=0)
    path.write_text(json.dumps(built))
    r = client.get("/eval/report")
    assert r.status_code == 200 and r.json()["commit"] == "abc" and r.json()["limits"]


def test_every_problem_has_term_lists_and_four_scenarios() -> None:
    all_ = scenarios.all_scenarios()
    assert len(all_) == 4 * len(scenarios.problem_ids())
    assert len({s.id for s in all_}) == len(all_)
