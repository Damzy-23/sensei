"""Adaption pipeline: upload the hint-coach training set, train it with AutoScientist, download the
result, and record each step.

Built against the `adaption` Python SDK (0.19.0). The SDK reads ADAPTION_API_KEY from the
environment. Every function takes the client as an argument, so tests pass a fake.

Steps (see docs/adaption.md):
  1. to_prompt_completion: chat rows become prompt/completion rows (what raw upload expects).
  2. upload: upload_file in raw mode with an explicit column mapping. No preprocessing credits.
  3. wait: poll until the dataset reports succeeded.
  4. train: AutoScientist run on that dataset, then poll until it finishes.
  5. download: save the trained model artifact (gzip) locally.

The leaderboard step is not here. The SDK has no leaderboard call, and datasets.publish returns
501 (not implemented). See docs/adaption.md.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.eval.hint_data import DATA_DIR

ADAPTION_DIR = DATA_DIR
UPLOAD_PATH = ADAPTION_DIR / "upload.jsonl"
RUN_RECORD_PATH = ADAPTION_DIR / "run.json"
MODEL_PATH = ADAPTION_DIR / "hint_coach_model.tar.gz"
COLUMNS = {"prompt": "prompt", "completion": "completion"}


def to_prompt_completion(train: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Turn chat rows (system, user, assistant) into prompt/completion rows.

    The system prompt and the user turn are joined into one prompt, so the model sees the same
    text it sees at inference time. The assistant turn is the completion.
    """
    rows: list[dict[str, str]] = []
    for row in train:
        msgs = {m["role"]: m["content"] for m in row["messages"]}
        prompt = f"{msgs['system']}\n\n{msgs['user']}"
        rows.append({"prompt": prompt, "completion": msgs["assistant"]})
    return rows


def write_upload_file(train: list[dict[str, Any]], path: Path = UPLOAD_PATH) -> int:
    rows = to_prompt_completion(train)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return len(rows)


@dataclass
class RunRecord:
    dataset_id: str | None = None
    dataset_rows: int | None = None
    experiment_id: str | None = None
    model: str | None = None
    status: str | None = None
    best_win_rate: float | None = None
    model_path: str | None = None
    leaderboard: str = "not submitted: no leaderboard call in the Adaption SDK 0.19.0"


def save_record(record: RunRecord, path: Path = RUN_RECORD_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(record), indent=2), encoding="utf-8")


def upload(client: Any, path: Path = UPLOAD_PATH, name: str = "sensei-hint-coach") -> str:
    """Upload the prompt/completion file as a raw dataset. Returns the dataset id."""
    result = client.datasets.upload_file(
        path,
        name=name,
        processing_mode="raw",
        column_mapping=COLUMNS,
    )
    return result.dataset_id


def wait_for_dataset(client: Any, dataset_id: str, timeout: float = 3600.0) -> Any:
    """Poll until the dataset is ready. Raises if it failed."""
    status = client.datasets.wait_for_completion(dataset_id, timeout=timeout)
    if status.status != "succeeded":
        raise RuntimeError(f"Adaption dataset {dataset_id} ended as {status.status}: {status.error_data}")
    return status


def start_training(client: Any, dataset_id: str, idempotency_key: str,
                   model: str | None = None) -> Any:
    """Start an AutoScientist run. The idempotency key stops a retry starting a second run."""
    kwargs: dict[str, Any] = {
        "dataset_id": dataset_id,
        "data_format": "instruction",
        "column_mapping": COLUMNS,
        "training_method": "instruction",
        "idempotency_key": idempotency_key,
    }
    if model:
        kwargs["model"] = model
    return client.autoscientist.create(**kwargs)


def wait_for_training(client: Any, experiment_id: str, timeout: float = 14400.0) -> Any:
    run = client.autoscientist.wait_for_completion(experiment_id, timeout=timeout)
    if run.status != "succeeded":
        raise RuntimeError(f"AutoScientist run {experiment_id} ended as {run.status}: {run.error}")
    return run


def download_model(client: Any, experiment_id: str, path: Path = MODEL_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    response = client.autoscientist.download(experiment_id)
    response.write_to_file(path)
    return path
