"""Win-rate eval with fake generators and judges: randomised order, leak handling, scoring,
aggregation, honest rendering, and the eval.pair spans."""

from __future__ import annotations

import asyncio
import json

from app import bank
from app.eval import winrate
from app.eval.hint_data import Scenario
from app.tracing import store

SCENARIO = Scenario(id="two-sum-L2-a0", problem_id="two-sum", level=2, code="def two_sum(n, t): pass",
                    last_failure="duplicates: wrong")


def _scenarios(n: int) -> list[Scenario]:
    return [Scenario(id=f"s{i}", problem_id="two-sum", level=2, code="x", last_failure="f") for i in range(n)]


def _gen(base: str, tuned: str):
    async def gen(scenario, model_key):  # noqa: ANN001
        return base if model_key == "hint_base" else tuned
    return gen


async def _no_leak(hint, level, reference):  # noqa: ANN001
    return False


def _judge_fixed(winner: str):
    seen_orders: list[str] = []

    async def judge(scenario, hint_a, hint_b):  # noqa: ANN001
        seen_orders.append(hint_a)
        perfect = {"correct_level": 1, "socratic": 1, "helpful": 1, "brevity": 1}
        return {"winner": winner, "A": perfect, "B": {"correct_level": 0, "socratic": 0, "helpful": 0, "brevity": 0}}

    judge.seen = seen_orders  # type: ignore[attr-defined]
    return judge


def test_tuned_wins_when_judge_picks_the_tuned_hint_regardless_of_order() -> None:
    # Judge always says "A". With a random swap, A is sometimes tuned and sometimes base, so the
    # winner must follow the mapping, not the label.
    judge = _judge_fixed("A")
    pairs = asyncio.run(winrate.run_pairs(_scenarios(20), gen=_gen("BASE", "TUNED"), judge=judge,
                                          leak=_no_leak, seed=3))
    assert {p.winner for p in pairs} == {"tuned", "base"}
    for p in pairs:
        expected = "tuned" if p.tuned_hint == judge.seen[pairs.index(p)] else "base"
        assert p.winner == expected


def test_order_is_randomised_but_reproducible() -> None:
    judge_a = _judge_fixed("tie")
    judge_b = _judge_fixed("tie")
    asyncio.run(winrate.run_pairs(_scenarios(12), gen=_gen("B", "T"), judge=judge_a, leak=_no_leak, seed=11))
    asyncio.run(winrate.run_pairs(_scenarios(12), gen=_gen("B", "T"), judge=judge_b, leak=_no_leak, seed=11))
    assert judge_a.seen == judge_b.seen
    assert len(set(judge_a.seen)) == 2  # both orders occur


def test_leaked_tuned_hint_loses_without_judging() -> None:
    async def leak_tuned(hint, level, reference):  # noqa: ANN001
        return hint == "TUNED"

    judge = _judge_fixed("tuned")
    pairs = asyncio.run(winrate.run_pairs(_scenarios(3), gen=_gen("BASE", "TUNED"), judge=judge,
                                          leak=leak_tuned, seed=1))
    assert all(p.winner == "base" for p in pairs)
    assert all(p.leaked["tuned"] and not p.leaked["base"] for p in pairs)
    assert judge.seen == []  # leaks never reach the judge


def test_both_leaking_is_a_tie() -> None:
    async def leak_all(hint, level, reference):  # noqa: ANN001
        return True

    pairs = asyncio.run(winrate.run_pairs(_scenarios(2), gen=_gen("x", "y"), judge=_judge_fixed("A"),
                                          leak=leak_all, seed=0))
    assert all(p.winner == "tie" for p in pairs)


def test_summary_counts_ties_as_half_and_reports_leak_rate() -> None:
    pairs = [
        winrate.PairResult("a", "two-sum", 2, "b", "t", "tuned", {"base": False, "tuned": False},
                           {"hint_base": {c: 0 for c in winrate.CRITERIA}, "hint_tuned": {c: 1 for c in winrate.CRITERIA}}),
        winrate.PairResult("b", "two-sum", 2, "b", "t", "tie", {"base": False, "tuned": True},
                           {"hint_base": {c: 0 for c in winrate.CRITERIA}, "hint_tuned": {c: 0 for c in winrate.CRITERIA}}),
        winrate.PairResult("c", "two-sum", 2, "b", "t", "base", {"base": False, "tuned": False},
                           {"hint_base": {c: 1 for c in winrate.CRITERIA}, "hint_tuned": {c: 0 for c in winrate.CRITERIA}}),
        winrate.PairResult("d", "two-sum", 2, "b", "t", "tuned", {"base": False, "tuned": False},
                           {"hint_base": {c: 0 for c in winrate.CRITERIA}, "hint_tuned": {c: 1 for c in winrate.CRITERIA}}),
    ]
    results = winrate.summarise(pairs, ["two-sum"])
    assert results.status == "ready"
    assert results.tuned.n == 4
    assert results.tuned.win_rate == round((2 + 0.5 * 1) / 4, 4)  # 0.625
    assert results.tuned.leak_rate == 0.25
    assert results.base.leak_rate == 0.0
    assert results.tuned.criteria["correct_level"] == 0.5


def test_markdown_states_when_tuned_loses() -> None:
    losing = [
        winrate.PairResult(f"s{i}", "two-sum", 2, "b", "t", "base", {"base": False, "tuned": False},
                           {"hint_base": {c: 1 for c in winrate.CRITERIA}, "hint_tuned": {c: 0 for c in winrate.CRITERIA}})
        for i in range(4)
    ]
    md = winrate.render_markdown(winrate.summarise(losing, ["two-sum"]))
    assert "did not beat" in md
    assert "win rate 0.0%" in md or "0.0%" in md
    assert "| hint_tuned |" in md
    assert "Three side-by-side examples" in md


def test_write_results_creates_json_and_markdown(tmp_path) -> None:  # noqa: ANN001
    pairs = asyncio.run(winrate.run_pairs(_scenarios(4), gen=_gen("base hint", "tuned hint"),
                                          judge=_judge_fixed("tie"), leak=_no_leak, seed=2))
    results = winrate.summarise(pairs, ["two-sum"])
    json_path, md_path = winrate.write_results(results, out_dir=tmp_path)
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded["status"] == "ready"
    assert set(loaded) >= {"base", "tuned", "examples", "held_out_problems"}
    assert len(loaded["examples"]) == 3
    assert md_path.read_text(encoding="utf-8").startswith("# Hint coach")


def test_each_judged_pair_is_logged_as_eval_pair_span() -> None:
    pairs = asyncio.run(winrate.run_pairs(_scenarios(2), gen=_gen("b", "t"), judge=_judge_fixed("tie"),
                                          leak=_no_leak, seed=0))
    assert len(pairs) == 2
    events = store.load_session_events("eval", limit=200)
    pair_events = [e for e in events if e.type == "eval.pair"]
    run_events = [e for e in events if e.type == "eval.run"]
    assert len(pair_events) == 2
    assert len(run_events) == 1
    assert all(e.actor == "evaluator" and e.output in {"base", "tuned", "tie"} for e in pair_events)


def test_held_out_scenarios_reference_real_problems() -> None:
    for p in ["container-most-water", "number-of-islands", "coin-change"]:
        assert bank.get_public(p) is not None


def test_leak_rate_uses_the_server_guard_rules() -> None:
    # A fenced solution at level 2 fails leak_check's static rule, so the eval treats it as a leak.
    from app.tools.guard import leak_check

    verdict = asyncio.run(leak_check("```python\ndef two_sum(a, b):\n    return []\n```", 2,
                                     bank.get_reference("two-sum")))
    assert verdict["decision"] == "block"
