"""Run the evaluation on the real models and write app/eval/report.json and app/eval/turns.jsonl.

    .venv/bin/python scripts/run_eval.py                 # every scenario
    .venv/bin/python scripts/run_eval.py --limit 2       # the first two, for a quick look
    .venv/bin/python scripts/run_eval.py --out /tmp/x    # write somewhere else

Needs ANTHROPIC_API_KEY (read from .env) and SENSEI_USE_STUBS=0. Uses a scratch SQLite file and
switches off every Firestore copy, so neither the local database nor the live data is touched.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Before the app is imported: a scratch database, and no copy of anything to Firestore.
os.environ["SENSEI_DB_PATH"] = str(Path(tempfile.mkdtemp(prefix="senior-eval-")) / "eval.db")
os.environ["SENSEI_LOG_FIRESTORE_DB"] = ""
os.environ["SENSEI_STATE_FIRESTORE_DB"] = ""
os.environ.pop("K_SERVICE", None)

from app.config import get_settings  # noqa: E402  (loads .env)
from app.eval import report, scenarios  # noqa: E402
from app.eval.runner import run_all  # noqa: E402
from app.llm.gateway import _route  # noqa: E402


def _commit() -> str:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()

    sha = git("rev-parse", "HEAD") or "unknown"
    return sha + ("-dirty" if git("status", "--porcelain", "--", "app", "config") else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, help="run only the first N scenarios")
    parser.add_argument("--concurrency", type=int, default=4, help="scenarios run at the same time (default 4)")
    parser.add_argument("--out", type=Path, help="folder for report.json and turns.jsonl (default app/eval/)")
    args = parser.parse_args()

    if get_settings().use_stubs:
        print("Refusing to run: SENSEI_USE_STUBS=1 serves fixed sample replies, so this would measure nothing.\n"
              "Set SENSEI_USE_STUBS=0 (and ANTHROPIC_API_KEY) to evaluate the real coach.", file=sys.stderr)
        return 2
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("Refusing to run: ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 2

    chosen = scenarios.all_scenarios()[: args.limit] if args.limit else scenarios.all_scenarios()
    turns = sum(len(s.messages) for s in chosen)
    print(f"{len(chosen)} scenarios, {turns} turns, {args.concurrency} at a time")
    done = []

    def progress(scenario, records) -> None:
        done.append(scenario)
        bad = [r for r in records if r.failed]
        print(f"  [{len(done):>3}/{len(chosen)}] {scenario.id:<58} {len(bad)} of {len(records)} turns flagged")

    records = asyncio.run(run_all(chosen, concurrency=args.concurrency, progress=progress))
    models = {task: _route(task)[1] for task in ("hint", "reasoning", "fast")}
    built = report.build(records, generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         commit=_commit(), models=models, scenarios_version=scenarios.VERSION,
                         scenario_count=len(chosen))
    report_path, turns_path = report.write(built, records, args.out)

    o = built["overall"]
    rc, jc, g = o["rule_checks"], o["judge_checks"], o["guards"]

    def show(r: dict) -> str:
        return f"{r['n']} of {r['of']}" + (f" ({r['rate']:.1%})" if r["rate"] is not None else "")

    print(f"\nturns: {o['turns']} ({o['turn_errors']} errors)")
    print(f"rule  too much code:               {show(rc['too_much_code'])}")
    print(f"rule  area named too early:        {show(rc['area_term_too_early'])}")
    print(f"rule  insight named too early:     {show(rc['insight_term_too_early'])}")
    print(f"judge full solution given:         {show(jc['gives_full_solution'])}")
    print(f"judge approach revealed too early: {show(jc['reveals_approach_too_early'])}")
    print(f"judge stayed within its level:     {show(jc['level_adherent'])}")
    print(f"judge unavailable:                 {jc['unavailable']}")
    print(f"guard turns with a blocked draft:  {show(g['turns_with_a_blocked_draft'])}; fallback sent {show(g['fallback_reply_sent'])}")
    print(f"latency p50 / p95:                 {built['latency_ms']['p50']} / {built['latency_ms']['p95']} ms")
    print(f"cost: turns ${built['cost_usd']['turns']}, judge ${built['cost_usd']['judge']}")
    print(f"failing turns listed: {len(built['failing_turns'])}\nwrote {report_path} and {turns_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
