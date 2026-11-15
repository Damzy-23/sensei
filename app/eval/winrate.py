"""Win-rate eval: hint_base vs hint_tuned on held-out scenarios.

For each scenario: generate one hint from each model, check both with leak_check, then have a
judge compare them with a fixed rubric. The A/B order is randomised per scenario (seeded, so a
run is reproducible). Leakage is a hard fail: a leaked hint loses to a clean one, and two leaks
tie at zero. Each judged pair is logged as an eval.pair span.

Scores are reported honestly. If the tuned model loses, the results say so.
"""

from __future__ import annotations

import json
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from app import bank
from app.agents import rules
from app.eval.hint_data import DATA_DIR, Scenario, load_scenarios
from app.llm.client import call
from app.models import EvalExample, EvalModelStats, EvalResults
from app.policy import load_policy
from app.tools.guard import leak_check
from app.tracing.context import span, turn

CRITERIA: tuple[str, ...] = ("correct_level", "socratic", "helpful", "brevity")
MODEL_KEYS: tuple[str, str] = ("hint_base", "hint_tuned")
RESULTS_DIR = Path(__file__).resolve().parents[2] / "data" / "eval"

GenFn = Callable[[Scenario, str], Awaitable[str]]
JudgeFn = Callable[[Scenario, str, str], Awaitable[dict[str, Any]]]
LeakFn = Callable[[str, int, str], Awaitable[bool]]

JUDGE_SYSTEM = "You judge two coaching hints for the same student, using a fixed rubric. Reply with JSON only."


@dataclass
class PairResult:
    scenario_id: str
    problem_id: str
    level: int
    base_hint: str
    tuned_hint: str
    winner: Literal["base", "tuned", "tie"]
    leaked: dict[str, bool]
    scores: dict[str, dict[str, int]] = field(default_factory=dict)


def judge_messages(scenario: Scenario, hint_a: str, hint_b: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": (
        f"Problem: {bank.get_public(scenario.problem_id).title}.\n"  # type: ignore[union-attr]
        f"Required hint level: {scenario.level}. Student code: <<<{scenario.code[:800]}>>>\n\n"
        f"Hint A: <<<{hint_a}>>>\nHint B: <<<{hint_b}>>>\n\n"
        "Score each hint 0 or 1 on: correct_level (at exactly the required level, no further), "
        "socratic (teaches by question or nudge, not by telling), helpful (moves this student forward), "
        "brevity (short and to the point, under 60 words). "
        "Then pick the winner: \"A\", \"B\", or \"tie\". "
        "Reply with JSON only: {\"winner\": \"A|B|tie\", \"A\": {\"correct_level\": 0|1, \"socratic\": 0|1, "
        "\"helpful\": 0|1, \"brevity\": 0|1}, \"B\": {...same keys...}}."
    )}]


def _clean_scores(raw: Any) -> dict[str, int]:
    raw = raw if isinstance(raw, dict) else {}
    return {c: 1 if raw.get(c) in (1, True) else 0 for c in CRITERIA}


async def run_pairs(
    scenarios: list[Scenario],
    *,
    gen: GenFn,
    judge: JudgeFn,
    leak: LeakFn,
    seed: int = 0,
    limit: int | None = None,
) -> list[PairResult]:
    rng = random.Random(seed)
    chosen = scenarios[:limit] if limit else scenarios
    pairs: list[PairResult] = []
    with turn("eval", name="winrate"):
        with span("evaluator", "eval.run", "winrate", input_text=f"scenarios={len(chosen)} seed={seed}"):
            for scenario in chosen:
                reference = bank.get_reference(scenario.problem_id)
                base = await gen(scenario, "hint_base")
                tuned = await gen(scenario, "hint_tuned")
                leaked = {
                    "base": await leak(base, scenario.level, reference),
                    "tuned": await leak(tuned, scenario.level, reference),
                }
                swap = rng.random() < 0.5
                hint_a, hint_b = (tuned, base) if swap else (base, tuned)

                with span("evaluator", "eval.pair", "judge_pair",
                          input_text=f"{scenario.id} A={'tuned' if swap else 'base'}") as st:
                    if leaked["base"] or leaked["tuned"]:
                        winner: Literal["base", "tuned", "tie"]
                        if leaked["base"] and leaked["tuned"]:
                            winner = "tie"
                        else:
                            winner = "tuned" if leaked["base"] else "base"
                        scores = {m: {c: 0 for c in CRITERIA} for m in MODEL_KEYS}
                    else:
                        verdict = await judge(scenario, hint_a, hint_b)
                        raw_winner = verdict.get("winner")
                        if raw_winner not in ("A", "B"):
                            raw_winner = "tie"  # an unreadable judgement counts as a tie
                        # Map the A/B labels back to models: A is tuned when swapped.
                        a_key, b_key = ("hint_tuned", "hint_base") if swap else ("hint_base", "hint_tuned")
                        scores = {
                            a_key: _clean_scores(verdict.get("A")),
                            b_key: _clean_scores(verdict.get("B")),
                        }
                        if raw_winner == "tie":
                            winner = "tie"
                        else:
                            winning_key = a_key if raw_winner == "A" else b_key
                            winner = "tuned" if winning_key == "hint_tuned" else "base"
                    st.output = winner

                pairs.append(PairResult(
                    scenario_id=scenario.id,
                    problem_id=scenario.problem_id,
                    level=scenario.level,
                    base_hint=base,
                    tuned_hint=tuned,
                    winner=winner,
                    leaked=leaked,
                    scores=scores,
                ))
    return pairs


def summarise(pairs: list[PairResult], held_out: list[str]) -> EvalResults:
    n = len(pairs)
    if n == 0:
        raise ValueError("no pairs to summarise")

    def stats(model: Literal["base", "tuned"]) -> EvalModelStats:
        key = f"hint_{model}"
        wins = sum(1 for p in pairs if p.winner == model)
        ties = sum(1 for p in pairs if p.winner == "tie")
        leaks = sum(1 for p in pairs if p.leaked[model])
        criteria = {
            c: round(sum(p.scores.get(key, {}).get(c, 0) for p in pairs) / n, 4) for c in CRITERIA
        }
        return EvalModelStats(
            model_key=key,  # type: ignore[arg-type]
            win_rate=round((wins + 0.5 * ties) / n, 4),
            n=n,
            leak_rate=round(leaks / n, 4),
            criteria=criteria,
        )

    examples = [
        EvalExample(
            scenario_id=p.scenario_id,
            problem_id=p.problem_id,
            hint_level=p.level,
            base_hint=p.base_hint,
            tuned_hint=p.tuned_hint,
            winner=p.winner,
        )
        for p in pairs[:3]
    ]
    return EvalResults(
        status="ready",
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        held_out_problems=held_out,
        base=stats("base"),
        tuned=stats("tuned"),
        examples=examples,
    )


def render_markdown(results: EvalResults) -> str:
    assert results.base and results.tuned
    base, tuned = results.base, results.tuned
    verdict = (
        f"The tuned model **won** more pairs than base (win rate {tuned.win_rate:.1%})."
        if tuned.win_rate > 0.5
        else f"The tuned model **did not beat** base: its win rate is {tuned.win_rate:.1%}, base {base.win_rate:.1%}."
        if tuned.win_rate < 0.5
        else f"The tuned model and base **tied** (win rate {tuned.win_rate:.1%} each)."
    )
    lines = [
        "# Hint coach: win rate, tuned vs base",
        "",
        f"Held-out problems: {', '.join(results.held_out_problems)}. Pairs judged: {tuned.n}. "
        f"Generated {results.generated_at}. Ties count as half a win.",
        "",
        verdict,
        "",
        "| Model | Win rate | Leak rate | Correct level | Socratic | Helpful | Brevity |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in (base, tuned):
        c = s.criteria
        lines.append(
            f"| {s.model_key} | {s.win_rate:.1%} | {s.leak_rate:.1%} | {c['correct_level']:.2f} | "
            f"{c['socratic']:.2f} | {c['helpful']:.2f} | {c['brevity']:.2f} |"
        )
    lines += ["", "## Three side-by-side examples", ""]
    for ex in results.examples:
        lines += [
            f"### {ex.scenario_id} (level {ex.hint_level}, winner: {ex.winner})",
            "",
            f"- **base:** {ex.base_hint}",
            f"- **tuned:** {ex.tuned_hint}",
            "",
        ]
    return "\n".join(lines)


def write_results(results: EvalResults, out_dir: Path = RESULTS_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    md_path = out_dir / "results.md"
    json_path.write_text(results.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(results), encoding="utf-8")
    return json_path, md_path


# ---------- real model functions ----------


async def real_gen(scenario: Scenario, model_key: str) -> str:
    public = bank.get_public(scenario.problem_id)
    if public is None:
        raise KeyError(scenario.problem_id)
    policy = load_policy()
    system = rules.hint_system_prompt(
        scenario.level, policy.hint_ladder.levels[scenario.level],
        bank.get_hint_seeds(scenario.problem_id)[scenario.level], False,
    )
    user = rules.hint_user_prompt(public.title, public.statement, scenario.code, scenario.last_failure, scenario.level)
    result = await call(model_key, system, [{"role": "user", "content": user}],
                        actor="hint_coach", name="eval_hint", json_schema={"required": ["hint"]}, max_tokens=300)
    return str((result.data or {}).get("hint", ""))


async def real_judge(scenario: Scenario, hint_a: str, hint_b: str) -> dict[str, Any]:
    result = await call("reasoning", JUDGE_SYSTEM, judge_messages(scenario, hint_a, hint_b),
                        actor="evaluator", name="judge_pair", json_schema={"required": ["winner"]}, max_tokens=300)
    return result.data or {}


async def real_leak(hint: str, level: int, reference: str) -> bool:
    verdict = await leak_check(hint, level, reference)
    return verdict["decision"] != "pass"


async def run_real(limit: int | None = None, seed: int = 0) -> EvalResults:
    scenarios = load_scenarios(DATA_DIR / "test.jsonl")
    pairs = await run_pairs(scenarios, gen=real_gen, judge=real_judge, leak=real_leak, seed=seed, limit=limit)
    held_out = sorted({s.problem_id for s in scenarios})
    results = summarise(pairs, held_out)
    write_results(results)
    return results


def load_results(path: Path = RESULTS_DIR / "results.json") -> EvalResults | None:
    if not path.exists():
        return None
    return EvalResults(**json.loads(path.read_text(encoding="utf-8")))
