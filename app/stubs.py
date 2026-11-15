"""Stub data for endpoints that later phases replace. Phase 7 replaces the eval results.

Everything else is served from the database and the problem bank.
"""

from __future__ import annotations

from app.models import EvalExample, EvalModelStats, EvalResults


def stub_eval_results() -> EvalResults:
    return EvalResults(
        status="stub",
        generated_at=None,
        held_out_problems=["sliding-window-max", "dijkstra-grid", "coin-change"],
        base=EvalModelStats(model_key="hint_base", win_rate=0.5, n=0, leak_rate=0.0,
                            criteria={"correct_level": 0.0, "socratic": 0.0, "helpful": 0.0, "brevity": 0.0}),
        tuned=EvalModelStats(model_key="hint_tuned", win_rate=0.5, n=0, leak_rate=0.0,
                             criteria={"correct_level": 0.0, "socratic": 0.0, "helpful": 0.0, "brevity": 0.0}),
        examples=[
            EvalExample(scenario_id="stub-1", problem_id="two-sum", hint_level=2,
                        base_hint="(stub) Name the pattern family you would use here.",
                        tuned_hint="(stub) Think about what you can store as you scan.",
                        winner="tie"),
        ],
    )
