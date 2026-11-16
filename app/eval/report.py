"""Turn recorded turns into the report served by GET /eval/report.

Every rate is given with its numerator and denominator. A rate over zero turns is null, never 0
and never 1. Unknown cost stays null. A turn the judge could not grade is counted as
"unavailable", never as a pass. Every failing turn is listed in full.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

from app.eval.runner import TurnRecord, level_adherent

REPORT_PATH = Path(__file__).resolve().parent / "report.json"
TURNS_PATH = Path(__file__).resolve().parent / "turns.jsonl"

LIMITS = [
    "Small sample: one run of each scenario, no repeat runs, so no confidence interval. A rate of 0 of N "
    "means none was seen in N turns, not that it cannot happen.",
    "The scenarios and the term lists were written by the developers of the coach. A reply can give the "
    "approach away in words the lists do not contain.",
    "The judge is a model and can be wrong in either direction. Its answers are reported apart from the "
    "rule checks, with the quote it based its grade on; a quote that is not in the reply is flagged.",
    "The judge grades one reply at a time. A leak spread over several replies is not caught by either check.",
    "Messages are fixed and written in advance; a real student adapts to the replies.",
]


def rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"n": numerator, "of": denominator, "rate": round(numerator / denominator, 4) if denominator else None}


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(q) - 1], 1)


def _group(records: list[TurnRecord]) -> dict[str, Any]:
    graded = [r for r in records if r.reply is not None]
    judged = [r for r in graded if r.judge is not None]
    rules = [r.rules for r in graded]
    adherent = [level_adherent(r) for r in judged]
    return {
        "turns": len(records),
        "turn_errors": sum(1 for r in records if r.reply is None),
        "rule_checks": {
            "too_much_code": rate(sum(1 for x in rules if x["too_much_code"]), len(rules)),
            "area_term_too_early": rate(sum(1 for x in rules if x["area_terms_too_early"]), len(rules)),
            "insight_term_too_early": rate(sum(1 for x in rules if x["insight_terms_too_early"]), len(rules)),
            "lines_of_code_given": sum(x["code_lines"] for x in rules),
            "turns_where_a_line_was_allowed": sum(1 for x in rules if x["allowed_code_lines"]),
            "ends_with_question": rate(sum(1 for x in rules if x["ends_with_question"]), len(rules)),
            "markdown_asterisks": rate(sum(1 for x in rules if x["has_markdown_asterisks"]), len(rules)),
            "words_median": statistics.median([x["word_count"] for x in rules]) if rules else None,
        },
        "judge_checks": {
            "graded": len(judged),
            "unavailable": len(graded) - len(judged),
            "gives_full_solution": rate(sum(1 for r in judged if r.judge["gives_full_solution"]), len(judged)),
            "reveals_approach_too_early": rate(
                sum(1 for r in judged if "judge_reveals_approach_too_early" in r.failed), len(judged)),
            "level_adherent": rate(sum(1 for a in adherent if a), len(judged)),
            "evidence_not_in_reply": rate(sum(1 for r in judged if not r.judge["evidence_in_reply"]), len(judged)),
        },
        "guards": {
            "turns_with_a_blocked_draft": rate(sum(1 for r in graded if r.drafts_blocked), len(graded)),
            "drafts_blocked": sum(r.drafts_blocked for r in graded),
            "fallback_reply_sent": rate(sum(1 for r in graded if r.fallback_used), len(graded)),
            "message_refused_by_input_guard": rate(sum(1 for r in graded if r.input_blocked), len(graded)),
            "escalated_to_a_mentor": sum(1 for r in graded if r.escalated),
        },
    }


def build(records: list[TurnRecord], *, generated_at: str, commit: str, models: dict[str, str],
          scenarios_version: str, scenario_count: int) -> dict[str, Any]:
    latencies = [r.latency_ms for r in records if r.reply is not None]
    costs = [r.cost_usd for r in records]
    judge_costs = [r.judge_cost_usd for r in records if r.judge is not None]
    learn = [r for r in records if r.mode == "learn" and r.hint_level is not None]
    return {
        "generated_at": generated_at,
        "commit": commit,
        "scenarios_version": scenarios_version,
        "models": models,
        "scenarios": scenario_count,
        "overall": _group(records),
        "by_family": {f: _group([r for r in records if r.family == f]) for f in sorted({r.family for r in records})},
        "by_hint_level_learn_mode": {
            str(level): _group([r for r in learn if r.hint_level == level])
            for level in sorted({r.hint_level for r in learn})
        },
        "latency_ms": {"p50": _percentile(latencies, 50), "p95": _percentile(latencies, 95), "turns": len(latencies),
                       "note": "one whole turn, from the student's message to the final reply; the judge is not included"},
        "cost_usd": {
            "turns": None if any(c is None for c in costs) else round(sum(costs), 4),
            "turns_with_unknown_cost": sum(1 for c in costs if c is None),
            "judge": None if any(c is None for c in judge_costs) else round(sum(judge_costs), 4),
        },
        "failing_turns": [
            {"scenario_id": r.scenario_id, "index": r.index, "hint_level": r.hint_level, "message": r.message,
             "reply": r.reply, "error": r.error, "failed": r.failed,
             "judge_evidence": r.judge["evidence"] if r.judge else None,
             "terms": (r.rules or {}).get("area_terms_too_early", []) + (r.rules or {}).get("insight_terms_too_early", [])}
            for r in records if r.failed
        ],
        "limits": LIMITS,
    }


def write(report: dict[str, Any], records: list[TurnRecord], out_dir: Path | None = None) -> tuple[Path, Path]:
    report_path = (out_dir / REPORT_PATH.name) if out_dir else REPORT_PATH
    turns_path = (out_dir / TURNS_PATH.name) if out_dir else TURNS_PATH
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    with turns_path.open("w") as f:
        for r in records:
            f.write(json.dumps(r.__dict__) + "\n")
    return report_path, turns_path
