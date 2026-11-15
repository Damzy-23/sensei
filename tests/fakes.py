"""A scripted model for tests. It answers by the role in the system prompt, so no network is used.

Override any role by setting the attributes below. `calls` records which roles ran, in order.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import pytest

from app.llm import client
from app.llm.client import ProviderReply


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.category: str = "ok"
        self.category_confidence: float = 0.9
        self.leaks: bool = False
        self.hint_text: Callable[[int, bool], str] = lambda level, stricter: (
            "Name the pattern family you would reach for first." if not stricter
            else "Think about what you need to remember as you scan."
        )
        self.hint_level_override: int | None = None

    async def __call__(self, target, system, messages, max_tokens):  # noqa: ANN001
        if "audit coaching hints" in system:
            self.calls.append("judge")
            return self._reply({"reveals_full_solution": self.leaks})
        if "classify coaching" in system:
            self.calls.append("classify")
            return self._reply({"category": self.category, "confidence": self.category_confidence})
        if "Socratic" in system:
            level = int(re.search(r"Hint level (\d)", system).group(1))  # type: ignore[union-attr]
            stricter = "broke the rules" in system
            self.calls.append(f"hint{level}")
            reported = self.hint_level_override if self.hint_level_override is not None else level
            return self._reply({"level": reported, "hint": self.hint_text(level, stricter)})
        if "interviewer" in system:
            self.calls.append("followup")
            return self._reply({"question": "What is the time complexity of your approach?"})
        if "algorithms reviewer" in system:
            self.calls.append("complexity")
            return self._reply({"time": "O(n)", "space": "O(n)", "feedback": "One pass with a lookup table."})
        if "mentor" in system:
            self.calls.append("intervention")
            return self._reply({"intervention": "Ask the student what the inner loop costs."})
        self.calls.append("unknown")
        return self._reply({})

    @staticmethod
    def _reply(data: dict) -> ProviderReply:
        return ProviderReply(json.dumps(data), 10, 5)


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    monkeypatch.setattr(client, "BACKOFF_BASE_SECONDS", 0.0)
    model = FakeModel()
    monkeypatch.setitem(client.PROVIDERS, "anthropic", model)
    return model
