"""Play the scripted student through the API and print the trace tree.

Usage:
  python scripts/simulate_student.py                       # against http://127.0.0.1:8000
  python scripts/simulate_student.py --base-url http://localhost:8000
  python scripts/simulate_student.py --record data/demo/recording.json

Start the server first: uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.demo.simulate import run  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--record", type=Path, default=None, help="write the run to this JSON file")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        run(client, record_path=args.record, verbose=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
