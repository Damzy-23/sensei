"""Run every reference solution against its visible and hidden tests, in a subprocess with a timeout.

Exits non-zero and prints the failing problem and test if anything breaks. Run before every demo.
Usage: python scripts/validate_bank.py [path/to/problems.json]
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BANK = ROOT / "data" / "problems.json"
TIMEOUT_SECONDS = 10

REQUIRED_KEYS = {
    "id", "title", "difficulty", "pattern", "statement", "starter_code", "visible_tests",
    "hidden_tests", "reference_solution", "expected_complexity", "hint_seeds",
}

# Runs inside the subprocess: loads the solution from the given directory and checks each test.
RUNNER = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import solution
tests = json.load(open(sys.argv[2], encoding="utf-8"))
failures = []
for t in tests:
    got = eval(t["call"], vars(solution))
    if t.get("normalize") == "sorted":
        got = sorted(got)
    want = eval(t["expected"], vars(solution))
    if got != want:
        failures.append({"name": t["name"], "got": repr(got), "want": repr(want)})
print(json.dumps(failures))
sys.exit(1 if failures else 0)
'''


def check_structure(problem: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    missing = REQUIRED_KEYS - set(problem)
    if missing:
        problems.append(f"missing keys: {sorted(missing)}")
    seeds = problem.get("hint_seeds", {})
    if sorted(seeds) != ["1", "2", "3", "4", "5"]:
        problems.append("hint_seeds must have exactly levels 1 to 5")
    level5 = seeds.get("5", "")
    if level5 and len(level5.splitlines()) > 12:
        problems.append("hint level 5 must be at most 12 lines of pseudocode")
    if not problem.get("hidden_tests"):
        problems.append("no hidden tests")
    return problems


def run_problem(problem: dict[str, Any]) -> list[str]:
    errors = check_structure(problem)
    if errors:
        return errors
    tests = problem["visible_tests"] + problem["hidden_tests"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        (tmp_dir / "solution.py").write_text(problem["reference_solution"], encoding="utf-8")
        (tmp_dir / "tests.json").write_text(json.dumps(tests), encoding="utf-8")
        runner = tmp_dir / "runner.py"
        runner.write_text(RUNNER, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(runner), str(tmp_dir), str(tmp_dir / "tests.json")],
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return [f"reference solution timed out after {TIMEOUT_SECONDS}s"]
    if proc.returncode != 0:
        if proc.stdout.strip():
            failures = json.loads(proc.stdout.strip().splitlines()[-1])
            return [f"test '{f['name']}': got {f['got']}, want {f['want']}" for f in failures]
        return [f"runner error: {proc.stderr.strip()[-400:]}"]
    return []


def main(argv: list[str]) -> int:
    bank_path = Path(argv[1]) if len(argv) > 1 else DEFAULT_BANK
    problems = json.loads(bank_path.read_text(encoding="utf-8"))
    ids = [p.get("id") for p in problems]
    if len(set(ids)) != len(ids):
        print("FAIL: duplicate problem ids")
        return 1
    failed = 0
    for problem in problems:
        errors = run_problem(problem)
        status = "PASS" if not errors else "FAIL"
        print(f"{status}  {problem.get('id')}  ({len(problem.get('visible_tests', [])) + len(problem.get('hidden_tests', []))} tests)")
        for err in errors:
            print(f"      {err}")
        failed += bool(errors)
    if failed:
        print(f"\n{failed} problem(s) failed. The bank is not safe to demo.")
        return 1
    print(f"\nAll {len(problems)} problems pass their reference solutions.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
