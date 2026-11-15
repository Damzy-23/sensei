"""Score one CV bullet out of 10 from five checks. Each check says what it found.

The checks, and their points:
  action      2  starts with a strong action verb (0 for a weak opener such as "Responsible for")
  result      3  states a measurable result (1 for an outcome word with no number)
  relevance   3  uses terms the job asks for (2 for one term). Skipped when no job terms are given
  length      1  between 8 and 28 words
  specific    1  no filler words and no first person
A skipped check is left out of the maximum: a bullet scored without a job is out of 7, not
marked down for relevance nobody could measure.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

ACTION_VERBS = frozenset("""
accelerated achieved automated built consolidated created cut debugged decreased delivered deployed designed
developed drove eliminated engineered established expanded fixed grew implemented improved increased introduced
launched led maintained mentored migrated modernised modernized optimised optimized owned planned profiled
prototyped raised rebuilt redesigned reduced refactored released removed replaced resolved rewrote scaled secured
shipped simplified sped standardised standardized streamlined tested trained unified upgraded wrote ran
""".split())
WEAK_OPENERS = ("responsible for", "was responsible for", "were responsible for", "helped", "worked on", "assisted", "involved in", "tasked with",
                "duties included", "participated in", "was part of", "in charge of")
OUTCOME_WORDS = frozenset("reduced increased improved cut saved grew raised decreased eliminated accelerated doubled halved".split())
FILLER = frozenset("various several many stuff things etc numerous multiple".split())
FIRST_PERSON = frozenset({"i", "my", "me", "we", "our"})
MIN_WORDS, MAX_WORDS = 8, 28

# A number that measures something: 40%, 2M, 3x, $5k, 200ms, "2 million", "5 engineers".
_MEASURE = re.compile(
    r"(\d[\d,.]*\s?(%|x\b|k\b|m\b|bn\b|ms\b|s\b|gb\b|tb\b|percent|million|billion|thousand|users|requests|engineers|"
    r"services|teams|customers|hours|days|weeks|months)|[$£€]\s?\d)", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z][A-Za-z+#.\-]*")


@dataclass(frozen=True)
class Check:
    id: str
    label: str
    points: int
    max: int
    detail: str


@dataclass(frozen=True)
class BulletScore:
    text: str
    score: int
    max: int
    checks: list[Check] = field(default_factory=list)


def contains_term(text: str, term: str) -> bool:
    """Whole-term match, case-insensitive. "Go" must not match "Google"; "C++" and ".NET" must still match."""
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term.strip())}(?![A-Za-z0-9])", text, re.IGNORECASE) is not None


def _action(text: str, words: list[str]) -> Check:
    lowered = text.strip().lower()
    for opener in WEAK_OPENERS:
        if lowered.startswith(opener):
            return Check("action", "Action verb", 0, 2, f'Starts with "{opener}", which describes a duty, not something you did.')
    first = words[0].lower() if words else ""
    if first in ACTION_VERBS:
        return Check("action", "Action verb", 2, 2, f'Starts with "{words[0]}".')
    return Check("action", "Action verb", 1, 2, f'Starts with "{words[0] if words else ""}", not one of the strong action verbs.')


def _result(text: str, words: list[str]) -> Check:
    found = _MEASURE.search(text)
    if found:
        return Check("result", "Measurable result", 3, 3, f'Gives a number: "{found.group(0).strip()}".')
    outcome = next((w for w in words if w.lower() in OUTCOME_WORDS), None)
    if outcome:
        return Check("result", "Measurable result", 1, 3, f'Says "{outcome}" but gives no number for it.')
    return Check("result", "Measurable result", 0, 3, "States no result and no number.")


def _relevance(text: str, job_terms: list[str]) -> Check | None:
    if not job_terms:
        return None
    hits = [term for term in job_terms if contains_term(text, term)]
    points = 3 if len(hits) >= 2 else 2 if len(hits) == 1 else 0
    detail = f"Uses {', '.join(hits)} from the job." if hits else "Uses none of the terms the job asks for."
    return Check("relevance", "Relevant to the job", points, 3, detail)


def _length(words: list[str]) -> Check:
    count = len(words)
    ok = MIN_WORDS <= count <= MAX_WORDS
    where = "within" if ok else "under" if count < MIN_WORDS else "over"
    return Check("length", "Length", 1 if ok else 0, 1, f"{count} words, {where} the {MIN_WORDS} to {MAX_WORDS} range.")


def _specific(words: list[str]) -> Check:
    lowered = [w.lower() for w in words]
    filler = sorted({w for w in lowered if w in FILLER})
    person = sorted({w for w in lowered if w in FIRST_PERSON})
    if filler or person:
        found = ", ".join(f'"{w}"' for w in filler + person)
        return Check("specific", "Specific", 0, 1, f"Contains {found}.")
    return Check("specific", "Specific", 1, 1, "No filler words and no first person.")


def score_bullet(text: str, job_terms: list[str] | None = None) -> BulletScore:
    words = _WORD.findall(text)
    checks = [c for c in (_action(text, words), _result(text, words), _relevance(text, job_terms or []),
                          _length(words), _specific(words)) if c is not None]
    return BulletScore(text=text, score=sum(c.points for c in checks), max=sum(c.max for c in checks), checks=checks)
