"""Run the win-rate eval on the held-out scenarios and write data/eval/results.{json,md}.

Needs ANTHROPIC_API_KEY, and HINT_TUNED_* set for the tuned model. Run
scripts/make_hint_data.py first so data/adaption/test.jsonl exists.

Usage: python scripts/run_eval.py [--limit N] [--seed S]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import state  # noqa: E402
from app.eval import winrate  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="judge only the first N scenarios")
    parser.add_argument("--seed", type=int, default=0, help="seed for the A/B order")
    args = parser.parse_args()

    results = asyncio.run(winrate.run_real(limit=args.limit, seed=args.seed))
    state.record_eval_run("ready", results.model_dump_json())
    assert results.base and results.tuned
    print(f"pairs: {results.tuned.n}")
    print(f"base  win rate {results.base.win_rate:.1%}  leak rate {results.base.leak_rate:.1%}")
    print(f"tuned win rate {results.tuned.win_rate:.1%}  leak rate {results.tuned.leak_rate:.1%}")
    print(f"written to {winrate.RESULTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
