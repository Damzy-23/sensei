"""Checks on one reply. Two kinds, always reported apart:

- Rule checks: plain code, no model. Same answer every time.
- Judge checks: a model reads the reply against a fixed rubric. It is not told the hint level
  the coach was given, so it cannot simply agree with it. It can be wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.eval.scenarios import AREA_TERMS, INSIGHT_TERMS
from app.guards import leak
from app.llm import gateway
from app.llm.gateway import LLMError

AREA_FROM_LEVEL = 2  # hint_coach.md level 2: "name the general area to think about"
INSIGHT_FROM_LEVEL = 3  # level 3: "a leading question that points at the key insight"
INTERVIEW_MAX_LEVEL = 1  # an interviewer may clarify the problem, nothing more
# The hint level and the rules are the coach's own business: hint_coach.md says never to mention them.
_MENTIONS_LEVEL = re.compile(r"\b(hint )?level \d\b|\b(at|on|for) this (hint )?level\b|\bhint ladder\b", re.I)


def _found(terms: tuple[str, ...], text: str) -> list[str]:
    """The terms that occur in `text` as whole words, ignoring case."""
    low = text.lower()
    hits = []
    for term in terms:
        t = term.lower()
        # Whole words: no letter or digit just before or after (a term may itself end in "-" or " ").
        pattern = rf"(?<![a-z0-9]){re.escape(t.strip())}(?![a-z0-9])"
        if re.search(pattern, low):
            hits.append(term)
    return hits


@dataclass(frozen=True)
class RuleResult:
    code_lines: int
    allowed_code_lines: int
    too_much_code: bool
    area_terms_too_early: list[str]
    insight_terms_too_early: list[str]
    mentions_hint_level: bool
    ends_with_question: bool
    word_count: int
    has_markdown_asterisks: bool

    @property
    def failed(self) -> list[str]:
        out = []
        if self.too_much_code:
            out.append("too_much_code")
        if self.area_terms_too_early:
            out.append("area_term_too_early")
        if self.insight_terms_too_early:
            out.append("insight_term_too_early")
        if self.mentions_hint_level:
            out.append("mentions_hint_level")
        return out


def rule_checks(*, reply: str, problem_id: str, mode: str, hint_level: int, allowed_code_lines: int,
                student_said: str) -> RuleResult:
    """`student_said`: everything the student has typed or had in the editor in this session so
    far. A term already there reveals nothing when the coach repeats it."""
    code_lines = leak.decide(reply, allowed_code_lines).code_lines
    interview = mode != "learn"

    def early(terms: tuple[str, ...], from_level: int) -> list[str]:
        if not interview and hint_level >= from_level:
            return []
        own = set(_found(terms, student_said))
        return [t for t in _found(terms, reply) if t not in own]

    text = reply.strip()
    return RuleResult(
        code_lines=code_lines,
        allowed_code_lines=allowed_code_lines,
        too_much_code=code_lines > allowed_code_lines,
        area_terms_too_early=early(AREA_TERMS[problem_id], AREA_FROM_LEVEL),
        insight_terms_too_early=early(INSIGHT_TERMS[problem_id], INSIGHT_FROM_LEVEL),
        mentions_hint_level=bool(_MENTIONS_LEVEL.search(text)),
        ends_with_question=text.endswith("?"),
        word_count=len(text.split()),
        has_markdown_asterisks="**" in text or bool(re.search(r"^\s*\* ", text, re.M)),
    )


# ---------- the model judge ----------

JUDGE_SYSTEM = """You grade one reply from a coding-interview tutor. The tutor must help a student find the
solution themselves, without giving it away. You are given the problem, the conversation so far and
the tutor's newest reply. Grade only the newest reply, and only what it adds: repeating what the
tutor already said earlier in the conversation does not raise its level; saying something new does.

How much a reply gives away, on a scale of 0 to 5:
- 0: no hint. Answers a question or asks what the student has tried.
- 1: clarifies the problem. Restates the goal or points at an input the student has not considered.
- 2: names the general area to think about (a data structure family or a technique).
- 3: asks a leading question that points at the key insight.
- 4: describes the approach in plain words, without the details that make it code.
- 5: walks through the approach step by step on a small example, or gives more than that.

Answer with one JSON object and nothing else:
{"level_judged": <0-5, the highest level the reply reaches>,
 "reveals_approach": <true if a student could now write the solution's approach without further thought>,
 "gives_full_solution": <true if the reply contains a complete solution, in code or in words precise enough to transcribe>,
 "evidence": "<an exact quote of at most 15 words from the newest reply that decided level_judged; empty if level 0>"}"""


def read_judge_answer(text: str) -> dict | None:
    """The first JSON object in the judge's answer; anything written after it is ignored.
    None when there is no complete object (for example, an answer cut off part way)."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


@dataclass(frozen=True)
class JudgeResult:
    level_judged: int
    reveals_approach: bool
    gives_full_solution: bool
    evidence: str
    evidence_in_reply: bool  # False: the judge quoted something the reply does not say
    raw: str


def _squash(text: str) -> str:
    return " ".join(text.split()).lower().strip(" .\"'")


async def judge(*, problem_title: str, statement: str, earlier: list[tuple[str, str]], student_message: str,
                reply: str) -> tuple[JudgeResult | None, str]:
    """(result, the judge's raw answer or the error). The result is None when the judge could not
    be asked or gave an answer of the wrong shape: that turn is then counted as "judge
    unavailable", never as a pass. `earlier` is the conversation before this turn, as
    (student, tutor) pairs; the judge is never told the hint level the tutor was given."""
    history = "\n".join(f"Student: {s}\nTutor: {t}" for s, t in earlier) or "(this is the first message)"
    user = (f"Problem: {problem_title}\n{statement}\n\nConversation so far:\n{history}\n\n"
            f"Student's newest message:\n{student_message}\n\nTutor's newest reply:\n{reply}")
    try:
        raw = await gateway.complete("fast", system=JUDGE_SYSTEM, user=user, actor="evaluator", name="eval_judge")
    except LLMError as exc:
        return None, f"error: {exc}"
    data = read_judge_answer(raw)
    if data is None:
        return None, raw
    level = data.get("level_judged")
    reveals, full, evidence = data.get("reveals_approach"), data.get("gives_full_solution"), data.get("evidence", "")
    if (not isinstance(level, int) or isinstance(level, bool) or not 0 <= level <= 5
            or not isinstance(reveals, bool) or not isinstance(full, bool) or not isinstance(evidence, str)):
        return None, raw
    found = not evidence.strip() or _squash(evidence) in _squash(reply)
    return JudgeResult(level, reveals, full, evidence, found, raw), raw
