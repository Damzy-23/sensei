"""Agent tools with a fake provider: hint model selection, follow-up, complexity, static checks,
run classification, mastery persistence and next-problem selection."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from app import state
from app.llm import client
from app.llm.client import ProviderReply
from app.models import RunIn
from app.tools import evaluator, hint_coach, interviewer, planner
from app.tracing import store
from app.tracing.context import turn


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(client, "BACKOFF_BASE_SECONDS", 0.0)
    yield


def _reply(text: str):
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        provider.calls.append(target.model)
        return ProviderReply(text, 10, 5)

    provider.calls = []
    return provider


def test_llm_hint_returns_model_level_and_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _reply('{"level": 2, "hint": "Name the pattern family for lookups."}')
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    out = asyncio.run(hint_coach.llm_hint("ses_t", "two-sum", 2, "pass", "none"))
    assert out == {"level": 2, "hint": "Name the pattern family for lookups."}
    assert provider.calls == ["claude-sonnet-5-5"]


def test_hint_model_falls_back_to_base_when_tuned_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HINT_MODEL", "tuned")
    for var in ("HINT_TUNED_BASE_URL", "HINT_TUNED_API_KEY", "HINT_TUNED_MODEL"):
        monkeypatch.delenv(var, raising=False)
    provider = _reply('{"level": 1, "hint": "Restate the task."}')
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    with turn("ses_t2") as tctx:
        asyncio.run(hint_coach.llm_hint("ses_t2", "two-sum", 1, "", "none"))
    assert provider.calls == ["claude-sonnet-5-5"]
    ev = next(e for e in store.load_trace(tctx.trace_id) if e.name == "llm_hint" and e.type == "llm.call")
    assert ev.model == "claude-sonnet-5-5"


def test_hint_model_uses_tuned_endpoint_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HINT_MODEL", "tuned")
    monkeypatch.setenv("HINT_TUNED_BASE_URL", "https://tuned.example/v1")
    monkeypatch.setenv("HINT_TUNED_API_KEY", "k")
    monkeypatch.setenv("HINT_TUNED_MODEL", "hint-7b")
    seen: list[str] = []

    async def tuned(target, system, messages, max_tokens):  # noqa: ANN001
        seen.append(target.model)
        return ProviderReply('{"level": 1, "hint": "Restate the task."}', 10, 5)

    monkeypatch.setitem(client.PROVIDERS, "openai_compatible", tuned)
    asyncio.run(hint_coach.llm_hint("ses_t3", "two-sum", 1, "", "none"))
    assert seen == ["hint-7b"]


def test_followup_question_comes_from_the_fast_model(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _reply('{"question": "What is the time complexity of your approach?"}')
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    q = asyncio.run(interviewer.llm_followup("ses_i", "two-sum", "interview"))
    assert q.endswith("?")
    assert provider.calls == ["claude-haiku-5-5"]


def test_record_answer_stores_student_message() -> None:
    sid = state.create_session()
    interviewer.record_answer(sid, "What is the complexity?", "O(n) time")
    msgs = state.list_messages(sid)
    assert msgs[-1].actor == "student" and msgs[-1].text == "O(n) time"


def test_read_run_result_classifies_failure() -> None:
    sid = state.create_session()
    assert evaluator.read_run_result(sid) == {"found": False}
    state.add_run(sid, "two-sum", RunIn(
        problem_id="two-sum", code="pass", passed=2, failed=1, total=3,
        failures=[{"name": "large", "message": "timed out"}], runtime_ms=9999,
    ))
    result = evaluator.read_run_result(sid)
    assert result["found"] is True
    assert result["solved"] is False
    assert result["failure_type"] == "timeout"


def test_read_run_result_marks_solved_runs() -> None:
    sid = state.create_session()
    state.add_run(sid, "two-sum", RunIn(problem_id="two-sum", code="ok", passed=3, failed=0, total=3, runtime_ms=4))
    result = evaluator.read_run_result(sid)
    assert result["solved"] is True
    assert result["failure_type"] is None


def test_static_check_uses_ast_only() -> None:
    assert evaluator.static_check("def f(x):\n    return x\n") == {"ok": True, "issues": []}
    bad = evaluator.static_check("def f(x):\n    x + 1\n")
    assert bad["ok"] is False and bad["issues"]


def test_analyze_complexity_parses_model_output(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _reply('{"time": "O(n)", "space": "O(n)", "feedback": "One pass with a lookup table."}')
    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    out = asyncio.run(evaluator.analyze_complexity("def f(x):\n    return x\n", "O(n) time, O(n) space"))
    assert out["time"] == "O(n)" and out["space"] == "O(n)"
    assert provider.calls == ["claude-sonnet-5-5"]


def test_mastery_persists_across_updates() -> None:
    sid = state.create_session()
    first = planner.update_mastery(sid, "stack", 1.0, "easy")
    second = planner.update_mastery(sid, "stack", 1.0, "easy")
    assert second > first > 0
    assert planner.get_mastery(sid)["stack"] == second


def test_next_problem_targets_weakest_pattern() -> None:
    sid = state.create_session()
    for pattern in ["hash map", "stack", "heap", "two pointers", "sliding window", "binary search",
                    "intervals", "BFS/DFS", "dynamic programming"]:
        state.set_mastery(sid, pattern, 0.9)
    state.set_mastery(sid, "heap", 0.05)
    pid = planner.select_next_problem(sid)
    assert pid == "kth-largest"  # the only heap problem, and mastery 0.05 is an easy band
