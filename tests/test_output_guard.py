"""Output guard: code rules per level, similarity, policy checks, the judge, and the
regenerate-then-fallback loop."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from app.guards import output as og
from app.guards.reply import guard_reply
from app.llm import client
from app.llm.client import ProviderReply
from app.policy import load_policy
from app.tools import guard as guard_tools
from app.tracing import store
from app.tracing.context import turn

REFERENCE = (
    "def two_sum(nums, target):\n"
    "    seen = {}\n"
    "    for i, n in enumerate(nums):\n"
    "        if target - n in seen:\n"
    "            return [seen[target - n], i]\n"
    "        seen[n] = i\n"
    "    return []\n"
)
PSEUDO = (
    "seen = {}  # value -> index\n"
    "for i, n in enumerate(nums):\n"
    "    if target - n in seen: return it\n"
    "    seen[n] = i\n"
)
PROSE = "For each number, ask what partner you would need, and remember what you have already seen."


@pytest.fixture(autouse=True)
def key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(client, "BACKOFF_BASE_SECONDS", 0.0)
    yield


def _policy():
    p = load_policy()
    return dict(similarity_threshold=p.guard.similarity_threshold, pseudocode_max_lines=p.hint_ladder.pseudocode_max_lines)


def test_prose_hint_at_level_two_passes_static_checks() -> None:
    r = og.static_checks(PROSE, 2, REFERENCE, **_policy())
    assert r.ok and r.code_lines == 0


def test_code_before_level_five_is_blocked() -> None:
    r = og.static_checks("```python\n" + REFERENCE + "```", 3, REFERENCE, **_policy())
    assert not r.ok
    assert "level 3" in r.reason


def test_pseudocode_allowed_at_level_five() -> None:
    lines = "\n".join(f"step_{i} = {i}" for i in range(10))
    r = og.static_checks(lines, 5, REFERENCE, **_policy())
    assert r.ok


def test_level_five_skeleton_longer_than_twelve_lines_is_blocked() -> None:
    lines = "\n".join(f"step_{i} = {i}" for i in range(13))
    r = og.static_checks(lines, 5, REFERENCE, **_policy())
    assert not r.ok
    assert "13 lines" in r.reason


def test_copy_of_reference_is_blocked_by_similarity() -> None:
    r = og.static_checks(REFERENCE, 5, REFERENCE, **_policy())
    assert not r.ok
    assert r.similarity >= 0.8


def test_similarity_ignores_comments_and_whitespace() -> None:
    reworded = REFERENCE.replace("seen = {}", "seen = {}  # the lookup table")
    assert og.coverage(reworded, REFERENCE) > 0.95


def test_policy_blocks_long_hint_and_level_mismatch() -> None:
    long_hint = {"level": 2, "hint": " ".join(["word"] * 61)}
    assert og.policy_verdict(long_hint, 2, 60)[0] is False
    mismatch = {"level": 3, "hint": "name the pattern"}
    ok, reason = og.policy_verdict(mismatch, 2, 60)
    assert ok is False and "level 3" in reason
    assert og.policy_verdict({"level": 2, "hint": "name the pattern family"}, 2, 60)[0] is True


def test_judge_fails_closed_on_malformed_output() -> None:
    assert og.parse_judge(None) is True
    assert og.parse_judge({"reveals_full_solution": "maybe"}) is True
    assert og.parse_judge({"reveals_full_solution": False}) is False


def test_leak_check_blocks_when_judge_says_leak(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        return ProviderReply('{"reveals_full_solution": true}', 10, 5)

    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    with turn("ses_og1") as tctx:
        result = asyncio.run(guard_tools.leak_check("Use a dictionary to store seen values.", 2, REFERENCE))
    assert result["decision"] == "block"
    assert "judge" in result["reason"]
    ev = next(e for e in store.load_trace(tctx.trace_id) if e.name == "leak_check")
    assert ev.decision == "block" and ev.reason


def test_leak_check_blocks_code_and_never_calls_judge(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        calls.append(1)
        return ProviderReply('{"reveals_full_solution": false}', 1, 1)

    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    result = asyncio.run(guard_tools.leak_check("```python\n" + REFERENCE + "```", 2, REFERENCE))
    assert result["decision"] == "block"
    assert calls == []


def test_leak_check_fails_closed_when_judge_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        return ProviderReply("not json", 1, 1)

    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    result = asyncio.run(guard_tools.leak_check("Think about a lookup table.", 2, REFERENCE))
    assert result["decision"] == "block"
    assert "failing closed" in result["reason"]


def test_canned_fallbacks_pass_every_static_check() -> None:
    policy = load_policy()
    for level, text in policy.canned_hints.items():
        assert og.static_checks(text, level, REFERENCE, **_policy()).ok, level
        assert og.policy_verdict({"level": level, "hint": text}, level, 60)[0], level


def test_guard_reply_passes_clean_first_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        return ProviderReply('{"reveals_full_solution": false}', 1, 1)

    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)

    async def draft(stricter: bool):
        return {"level": 2, "hint": "Name the pattern family you would reach for first."}

    result = asyncio.run(guard_reply(draft, level=2, reference=REFERENCE))
    assert result.decision == "pass"
    assert result.text.startswith("Name the pattern")


def test_guard_reply_regenerates_once_then_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        return ProviderReply('{"reveals_full_solution": false}', 1, 1)

    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    seen: list[bool] = []

    async def draft(stricter: bool):
        seen.append(stricter)
        if not stricter:
            return {"level": 2, "hint": "```python\n" + REFERENCE + "```"}
        return {"level": 2, "hint": "Name the pattern family you would reach for first."}

    with turn("ses_og2") as tctx:
        result = asyncio.run(guard_reply(draft, level=2, reference=REFERENCE))
    assert result.decision == "regenerated"
    assert seen == [False, True]
    assert any(e.name == "leak_check" and e.decision == "block" for e in store.load_trace(tctx.trace_id))


def test_guard_reply_falls_back_and_logs_original(monkeypatch: pytest.MonkeyPatch) -> None:
    async def provider(target, system, messages, max_tokens):  # noqa: ANN001
        return ProviderReply('{"reveals_full_solution": false}', 1, 1)

    monkeypatch.setitem(client.PROVIDERS, "anthropic", provider)
    leaky = "```python\n" + REFERENCE + "```"

    async def draft(stricter: bool):
        return {"level": 3, "hint": leaky}

    with turn("ses_og3") as tctx:
        result = asyncio.run(guard_reply(draft, level=3, reference=REFERENCE))
    policy = load_policy()
    assert result.decision == "fallback"
    assert result.text == policy.canned_hints[3]
    assert result.original == leaky
    fallback = next(e for e in store.load_trace(tctx.trace_id) if e.name == "canned_fallback")
    assert fallback.decision == "fallback"
    assert fallback.input is not None and "two_sum" in fallback.input
