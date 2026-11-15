"""Typed view of config/policy.yaml. Loaded once; restart the server after editing."""

from __future__ import annotations

from functools import lru_cache

import yaml
from pydantic import BaseModel, Field

from app.config import ROOT


class HintLadderPolicy(BaseModel):
    max_level: int = Field(ge=1, le=5)
    min_wait_seconds: int = Field(ge=0)
    reply_max_words: int = Field(ge=1)
    pseudocode_max_lines: int = Field(ge=1)
    levels: dict[int, str]


class GuardPolicy(BaseModel):
    similarity_threshold: float = Field(ge=0, le=1)
    violation_escalation_count: int = Field(ge=1)
    frustration_escalation_count: int = Field(ge=1)
    classify_min_confidence: float = Field(ge=0, le=1)


class ModePolicy(BaseModel):
    learn_consecutive_failed_runs: int
    learn_hint_level: int
    interview_min_mastery: float
    interview_max_hints_on_solve: int
    blitz_solves_in_row: int
    blitz_time_target_seconds: int
    blitz_countdown_seconds: int


class EscalationPolicy(BaseModel):
    stuck_hint_level: int = Field(ge=1, le=5)


class Policy(BaseModel):
    hint_ladder: HintLadderPolicy
    guard: GuardPolicy
    canned_hints: dict[int, str]
    redirects: dict[str, str]
    modes: ModePolicy
    escalation: EscalationPolicy


@lru_cache(maxsize=1)
def load_policy() -> Policy:
    with (ROOT / "config" / "policy.yaml").open(encoding="utf-8") as fh:
        return Policy(**(yaml.safe_load(fh) or {}))
