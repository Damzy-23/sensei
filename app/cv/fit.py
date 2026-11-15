"""Job fit: how much of what the job asks for the candidate's own CV shows.

fit = weight of the requirements found in the CV / weight of all requirements, as a percent.
A "must" counts 2 and a "nice to have" counts 1. The CV text used is the candidate's
original, not the rewritten one, so rewording cannot raise the score.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.cv.scoring import contains_term

WEIGHTS = {"must": 2, "nice": 1}


def _forms(name: str) -> tuple[str, ...]:
    """A term and its simple singular or plural, so "payment APIs" is found in "payment API".
    Short names (Go, C, AWS) are left alone: dropping or adding an "s" there changes the word."""
    name = name.strip()
    if len(name) <= 3:
        return (name,)
    return (name, name[:-1]) if name.lower().endswith("s") else (name, name + "s")


@dataclass(frozen=True)
class Requirement:
    term: str
    aliases: tuple[str, ...]
    importance: str  # "must" | "nice"

    def found_in(self, text: str) -> bool:
        return any(contains_term(text, form) for name in (self.term, *self.aliases) for form in _forms(name))


@dataclass(frozen=True)
class Fit:
    score: int | None  # percent; None when no requirements could be read from the job
    matched: list[Requirement]
    missing: list[Requirement]


def job_fit(requirements: list[Requirement], cv_text: str) -> Fit:
    if not requirements:
        return Fit(None, [], [])
    matched = [r for r in requirements if r.found_in(cv_text)]
    missing = [r for r in requirements if not r.found_in(cv_text)]
    total = sum(WEIGHTS[r.importance] for r in requirements)
    return Fit(round(100 * sum(WEIGHTS[r.importance] for r in matched) / total), matched, missing)
