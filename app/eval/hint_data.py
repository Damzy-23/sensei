"""Training and held-out data for the hint coach (the Adaption task).

For each problem: generate buggy or incomplete student attempts. For each attempt and each hint
level 1 to 5, write target hints with the strongest model. A hint is kept only if it passes
leak_check (the same guard the server uses), stays under 60 words, and passes a rubric judge
(right level, Socratic, helpful).

Three whole problems are held out. They never appear in training; their scenarios are the test
set for the win-rate eval.

The generator sees the reference solution, to write realistic mistakes and to judge. That
context never reaches the output files: rows hold only the prompt and the hint.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app import bank
from app.agents import rules
from app.llm.client import call
from app.policy import load_policy
from app.tools.guard import leak_check

HOLDOUT_PROBLEMS: tuple[str, ...] = ("container-most-water", "number-of-islands", "coin-change")
ATTEMPTS_PER_PROBLEM = 5
VARIANTS_PER_HINT = 2
MAX_WORDS = 60
LEVELS: tuple[int, ...] = (1, 2, 3, 4, 5)
DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "adaption"

ATTEMPT_SYSTEM = "You write realistic student mistakes for coding interviews. Reply with JSON only."
RUBRIC_SYSTEM = "You grade coaching hints against a rubric. Reply with JSON only."

AttemptFn = Callable[[str], Awaitable[list[dict[str, str]]]]
HintFn = Callable[[str, int, dict[str, str]], Awaitable[str]]
CheckFn = Callable[[str, int, str], Awaitable[bool]]
JudgeFn = Callable[[str, int, str, dict[str, str]], Awaitable[dict[str, bool]]]


@dataclass(frozen=True)
class Scenario:
    id: str
    problem_id: str
    level: int
    code: str
    last_failure: str


# ---------- prompts ----------


def attempt_messages(problem_id: str, count: int) -> list[dict[str, str]]:
    public = bank.get_public(problem_id)
    if public is None:
        raise KeyError(problem_id)
    reference = bank.get_reference(problem_id)
    return [{"role": "user", "content": (
        f"Problem: {public.title}\n{public.statement}\n\n"
        f"Reference solution (internal, never show a student): <<<{reference}>>>\n\n"
        f"Write {count} distinct buggy or incomplete attempts a real student might submit. "
        "Each attempt is a Python function with the same name, plus the failing test a student would see. "
        "Do not write a correct solution. Reply with JSON only: "
        "{\"attempts\": [{\"code\": \"...\", \"failure_name\": \"...\", \"failure_message\": \"...\"}]}."
    )}]


def rubric_messages(problem_id: str, level: int, hint: str, attempt: dict[str, str]) -> list[dict[str, str]]:
    public = bank.get_public(problem_id)
    if public is None:
        raise KeyError(problem_id)
    instruction = load_policy().hint_ladder.levels[level]
    return [{"role": "user", "content": (
        f"Problem: {public.title}.\n"
        f"Required hint level: {level} ({instruction}).\n"
        f"Student code: <<<{attempt.get('code', '')[:800]}>>>\n"
        f"Hint: <<<{hint}>>>\n\n"
        "Answer each as true or false: right_level (the hint is at exactly the required level and goes no further), "
        "socratic (it teaches with a question or nudge rather than telling the answer), "
        "helpful (it moves this student forward). "
        "Reply with JSON only: {\"right_level\": bool, \"socratic\": bool, \"helpful\": bool}."
    )}]


def _hint_prompts(problem_id: str, level: int, attempt: dict[str, str]) -> tuple[str, str]:
    public = bank.get_public(problem_id)
    if public is None:
        raise KeyError(problem_id)
    policy = load_policy()
    system = rules.hint_system_prompt(
        level, policy.hint_ladder.levels[level], bank.get_hint_seeds(problem_id)[level], False
    )
    user = rules.hint_user_prompt(
        public.title, public.statement, attempt.get("code", ""),
        f"{attempt.get('failure_name', '')}: {attempt.get('failure_message', '')}", level,
    )
    return system, user


# ---------- decisions ----------


def word_count(text: str) -> int:
    return len(text.split())


def passes_rubric(judgement: dict[str, bool] | None) -> bool:
    return bool(judgement) and all(judgement.get(k) is True for k in ("right_level", "socratic", "helpful"))


def scenario_for(problem_id: str, level: int, attempt: dict[str, str], index: int) -> Scenario:
    return Scenario(
        id=f"{problem_id}-L{level}-a{index}",
        problem_id=problem_id,
        level=level,
        code=attempt.get("code", ""),
        last_failure=f"{attempt.get('failure_name', '')}: {attempt.get('failure_message', '')}",
    )


def train_row(problem_id: str, level: int, attempt: dict[str, str], hint: str, index: int) -> dict[str, Any]:
    system, user = _hint_prompts(problem_id, level, attempt)
    return {
        "id": f"{problem_id}-L{level}-{index}",
        "problem_id": problem_id,
        "level": level,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
            {"role": "assistant", "content": hint},
        ],
    }


# ---------- the pipeline, with model functions injected ----------


async def build(
    problem_ids: list[str],
    *,
    attempt_fn: AttemptFn,
    hint_fn: HintFn,
    check_fn: CheckFn,
    judge_fn: JudgeFn,
) -> tuple[list[dict[str, Any]], list[Scenario]]:
    """Return (training rows, held-out scenarios). Held-out problems are never trained on."""
    train: list[dict[str, Any]] = []
    held_out: list[Scenario] = []
    for problem_id in problem_ids:
        attempts = (await attempt_fn(problem_id))[:ATTEMPTS_PER_PROBLEM]
        for a_index, attempt in enumerate(attempts):
            for level in LEVELS:
                if problem_id in HOLDOUT_PROBLEMS:
                    held_out.append(scenario_for(problem_id, level, attempt, a_index))
                    continue
                for variant in range(VARIANTS_PER_HINT):
                    hint = (await hint_fn(problem_id, level, attempt)).strip()
                    if not hint or word_count(hint) > MAX_WORDS:
                        continue
                    if not await check_fn(problem_id, level, hint):
                        continue
                    if not passes_rubric(await judge_fn(problem_id, level, hint, attempt)):
                        continue
                    train.append(train_row(problem_id, level, attempt, hint, a_index * 10 + variant))
    return train, held_out


# ---------- real model functions ----------


async def real_attempts(problem_id: str) -> list[dict[str, str]]:
    result = await call("reasoning", ATTEMPT_SYSTEM, attempt_messages(problem_id, ATTEMPTS_PER_PROBLEM + 1),
                        actor="evaluator", name="gen_attempts", json_schema={"required": ["attempts"]},
                        max_tokens=2000)
    return [a for a in (result.data or {}).get("attempts", []) if isinstance(a, dict) and a.get("code")]


async def real_hint(problem_id: str, level: int, attempt: dict[str, str]) -> str:
    system, user = _hint_prompts(problem_id, level, attempt)
    result = await call("reasoning", system, [{"role": "user", "content": user}],
                        actor="hint_coach", name="gen_target_hint", json_schema={"required": ["hint"]},
                        max_tokens=300)
    return str((result.data or {}).get("hint", ""))


async def real_check(problem_id: str, level: int, hint: str) -> bool:
    verdict = await leak_check(hint, level, bank.get_reference(problem_id))
    return verdict["decision"] == "pass"


async def real_judge(problem_id: str, level: int, hint: str, attempt: dict[str, str]) -> dict[str, bool]:
    result = await call("reasoning", RUBRIC_SYSTEM, rubric_messages(problem_id, level, hint, attempt),
                        actor="evaluator", name="rubric_judge",
                        json_schema={"required": ["right_level", "socratic", "helpful"]}, max_tokens=120)
    data = result.data or {}
    return {k: data.get(k) is True for k in ("right_level", "socratic", "helpful")}


async def build_real(problem_ids: list[str]) -> tuple[list[dict[str, Any]], list[Scenario]]:
    return await build(problem_ids, attempt_fn=real_attempts, hint_fn=real_hint,
                       check_fn=real_check, judge_fn=real_judge)


def write_outputs(train: list[dict[str, Any]], held_out: list[Scenario], out_dir: Path = DATA_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "train.jsonl").open("w", encoding="utf-8") as fh:
        for row in train:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out_dir / "test.jsonl").open("w", encoding="utf-8") as fh:
        for s in held_out:
            fh.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")


def load_scenarios(path: Path = DATA_DIR / "test.jsonl") -> list[Scenario]:
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing: run scripts/make_hint_data.py first")
    return [Scenario(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
