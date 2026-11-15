"""Generate the hint-coach training set and the held-out test scenarios.

Needs ANTHROPIC_API_KEY (the reasoning model writes attempts, target hints and judgements).
Writes data/adaption/train.jsonl and data/adaption/test.jsonl.

Usage: python scripts/make_hint_data.py [--problems id1,id2,...]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import bank  # noqa: E402
from app.eval import hint_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--problems", default="", help="comma-separated problem ids (default: whole bank)")
    args = parser.parse_args()
    ids = [p for p in args.problems.split(",") if p] or [p.id for p in bank.list_problems()]

    train, held_out = asyncio.run(hint_data.build_real(ids))
    hint_data.write_outputs(train, held_out)
    print(f"training rows: {len(train)} (target 400+)")
    print(f"held-out scenarios: {len(held_out)} from {sorted(hint_data.HOLDOUT_PROBLEMS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
