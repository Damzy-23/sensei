"""Upload the hint-coach training set to Adaption, train it, and download the model.

Needs ADAPTION_API_KEY (in the environment or .env). Never paste the key into code or chat.

Usage:
  python scripts/adaption_train.py upload          # build upload.jsonl, upload, wait for ready
  python scripts/adaption_train.py train           # start AutoScientist on the last dataset, wait
  python scripts/adaption_train.py download        # save the trained model artifact
  python scripts/adaption_train.py all             # all three in order

Run scripts/make_hint_data.py first: it writes data/adaption/train.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from app.eval import adaption  # noqa: E402
from app.eval.hint_data import DATA_DIR  # noqa: E402


def _client():  # noqa: ANN202
    load_dotenv(ROOT / ".env")
    if not os.environ.get("ADAPTION_API_KEY"):
        sys.exit("ADAPTION_API_KEY is not set. Add it to .env (see .env.example). Do not paste it into chat.")
    from adaption import Adaption  # imported late so --help works without the SDK

    return Adaption()


def _load_record() -> adaption.RunRecord:
    if adaption.RUN_RECORD_PATH.exists():
        return adaption.RunRecord(**json.loads(adaption.RUN_RECORD_PATH.read_text(encoding="utf-8")))
    return adaption.RunRecord()


def cmd_upload(client, record: adaption.RunRecord) -> None:  # noqa: ANN001
    train_path = DATA_DIR / "train.jsonl"
    if not train_path.exists():
        sys.exit(f"{train_path} is missing. Run scripts/make_hint_data.py first.")
    train = [json.loads(line) for line in train_path.read_text(encoding="utf-8").splitlines() if line]
    rows = adaption.write_upload_file(train)
    print(f"upload file: {adaption.UPLOAD_PATH} ({rows} rows)")
    record.dataset_id = adaption.upload(client)
    record.dataset_rows = rows
    print(f"dataset: {record.dataset_id}")
    status = adaption.wait_for_dataset(client, record.dataset_id)
    print(f"dataset ready: {status.status}, row_count={status.row_count}")
    record.dataset_rows = status.row_count or rows
    adaption.save_record(record)


def cmd_train(client, record: adaption.RunRecord) -> None:  # noqa: ANN001
    if not record.dataset_id:
        sys.exit("No dataset yet. Run the upload step first.")
    run = adaption.start_training(client, record.dataset_id, idempotency_key=str(uuid.uuid4()))
    record.experiment_id = run.id
    record.model = run.model
    print(f"run: {run.id} on {run.model}, status {run.status}")
    adaption.save_record(record)
    done = adaption.wait_for_training(client, run.id)
    record.status = done.status
    record.best_win_rate = done.best_win_rate
    print(f"run finished: {done.status}, best win rate {done.best_win_rate}")
    adaption.save_record(record)


def cmd_download(client, record: adaption.RunRecord) -> None:  # noqa: ANN001
    if not record.experiment_id:
        sys.exit("No training run yet. Run the train step first.")
    path = adaption.download_model(client, record.experiment_id)
    record.model_path = str(path)
    print(f"model saved: {path}")
    adaption.save_record(record)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["upload", "train", "download", "all"])
    args = parser.parse_args()
    client = _client()
    record = _load_record()
    steps = {"upload": [cmd_upload], "train": [cmd_train], "download": [cmd_download],
             "all": [cmd_upload, cmd_train, cmd_download]}[args.step]
    for step in steps:
        step(client, record)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
