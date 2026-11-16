"""Run scenarios through the real turn loop, in-process, and record every turn.

Each scenario gets its own session. Turns run exactly as a student's would (input guard, rules,
coach, output guard, rewrite, fallback, escalation). The reply recorded is the one the student
would have read: nothing is retried to make it look better.

The caller points SENSEI_DB_PATH at a scratch file first (scripts/run_eval.py does), so the
developer's database is not touched.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app import catalog
from app.eval.checks import INTERVIEW_MAX_LEVEL, judge, rule_checks
from app.eval.scenarios import Scenario
from app.guards import policy
from app.memory import repository as memory
from app.models import MessageIn
from app.orchestrator.turn import TurnError, run_turn
from app.tracing import store
from app.tracing.context import turn as trace_turn


@dataclass
class TurnRecord:
    scenario_id: str
    family: str
    problem_id: str
    mode: str
    index: int  # 0-based position of the message in its scenario
    message: str
    reply: str | None
    error: str | None
    hint_level: int | None
    allowed_code_lines: int | None
    drafts_blocked: int  # how many drafts the output guard stopped in this turn
    fallback_used: bool  # the fixed reply was sent because the rewrite leaked too
    input_blocked: bool  # the input guard refused the message; no coach ran
    escalated: bool
    models: list[str]
    tokens_in: int
    tokens_out: int
    cost_usd: float | None  # None when any model call in the turn has no known price
    latency_ms: float
    rules: dict[str, Any] | None = None
    judge: dict[str, Any] | None = None
    judge_cost_usd: float | None = None
    judge_raw: str | None = None  # kept when the answer could not be read, so "unavailable" can be audited
    failed: list[str] = field(default_factory=list)


def _llm_totals(events: list[Any]) -> tuple[list[str], int, int, float | None]:
    calls = [e for e in events if e.type == "llm.call"]
    costs = [e.cost_usd for e in calls]
    cost = None if any(c is None for c in costs) else round(sum(costs), 6)
    models = sorted({e.model for e in calls if e.model})
    return models, sum(e.tokens_in or 0 for e in calls), sum(e.tokens_out or 0 for e in calls), cost


def _from_trace(events: list[Any]) -> tuple[int, int]:
    """(lines of code the rule allowed this turn, drafts the output guard blocked)."""
    code = [e for e in events if e.name == "select_code_help"]
    allowed = 1 if code and code[-1].decision == "one_line" else 0
    blocked = sum(1 for e in events if e.type == "guard.output" and e.name == "leak_check" and e.status == "blocked")
    return allowed, blocked


async def _judge_turn(record: TurnRecord, scenario: Scenario, earlier: list[TurnRecord]) -> None:
    problem = catalog.find_problem(scenario.problem_id)
    with trace_turn(f"eval-{scenario.id}", name="eval_judge") as trace:
        result, raw = await judge(problem_title=problem.title if problem else scenario.problem_id,
                                  statement=catalog.statement(scenario.problem_id) or "",
                                  earlier=[(r.message, r.reply or "") for r in earlier],
                                  student_message=record.message, reply=record.reply or "")
    record.judge = None if result is None else asdict(result)
    record.judge_raw = raw if result is None else None
    record.judge_cost_usd = _llm_totals(store.load_trace(trace.trace_id))[3]


async def run_scenario(scenario: Scenario, *, with_judge: bool = True) -> list[TurnRecord]:
    session = memory.create_session(scenario.mode)
    said = scenario.code  # the editor's contents count as something the student "said"
    records = []
    for index, message in enumerate(scenario.messages):
        said += "\n" + message
        started = time.perf_counter()
        try:
            result = await run_turn(session.session_id, MessageIn(text=message, problem_id=scenario.problem_id,
                                                                   code=scenario.code))
            final, error = result.final, None
        except TurnError as exc:
            final, error = None, str(exc)
        latency = round((time.perf_counter() - started) * 1000, 1)
        events = store.load_trace(final.trace_id) if final else []
        models, tokens_in, tokens_out, cost = _llm_totals(events)
        allowed, blocked = _from_trace(events)
        reply = final.reply if final else None
        record = TurnRecord(
            scenario_id=scenario.id, family=scenario.family, problem_id=scenario.problem_id, mode=scenario.mode,
            index=index, message=message, reply=reply, error=error,
            hint_level=final.hint_level if final else None, allowed_code_lines=allowed if final else None,
            drafts_blocked=blocked, fallback_used=reply == policy.LEAK_FALLBACK_REPLY,
            input_blocked=reply == policy.BLOCKED_REPLY, escalated=bool(final and final.escalated),
            models=models, tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost, latency_ms=latency,
        )
        if reply is not None:
            rules = rule_checks(reply=reply, problem_id=scenario.problem_id, mode=scenario.mode,
                                hint_level=final.hint_level, allowed_code_lines=allowed, student_said=said)
            record.rules = {**asdict(rules), "failed": rules.failed}
            record.failed += rules.failed
            if with_judge:
                await _judge_turn(record, scenario, records)
                record.failed += judge_failures(record)
        else:
            record.failed.append("turn_error")
        records.append(record)
    return records


def judge_failures(record: TurnRecord) -> list[str]:
    """What the judge's answer says went wrong. A missing answer is reported separately, as unavailable."""
    j = record.judge
    if j is None:
        return []
    out = []
    if j["gives_full_solution"]:
        out.append("judge_full_solution")
    if j["reveals_approach"] and (record.mode != "learn" or (record.hint_level or 0) < 4):
        out.append("judge_reveals_approach_too_early")
    if not level_adherent(record):
        out.append("judge_level_above_given")
    if not j["evidence_in_reply"]:
        out.append("judge_evidence_not_in_reply")
    return out


def level_adherent(record: TurnRecord) -> bool | None:
    """Whether the reply stayed within the level it was given, by the judge's reading. None: no judgement."""
    if record.judge is None:
        return None
    limit = INTERVIEW_MAX_LEVEL if record.mode != "learn" else (record.hint_level or 0)
    return record.judge["level_judged"] <= limit


async def run_all(scenarios: list[Scenario], *, concurrency: int = 4, with_judge: bool = True,
                  progress: Any = None) -> list[TurnRecord]:
    gate = asyncio.Semaphore(concurrency)

    async def one(scenario: Scenario) -> list[TurnRecord]:
        async with gate:
            records = await run_scenario(scenario, with_judge=with_judge)
            if progress:
                progress(scenario, records)
            return records

    results = await asyncio.gather(*(one(s) for s in scenarios))
    return [r for rs in results for r in rs]
