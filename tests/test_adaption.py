"""Adaption pipeline: row conversion, call arguments, and failure handling, with a fake client.

No network. The real SDK is checked by scripts/adaption_train.py, which needs ADAPTION_API_KEY.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.eval import adaption


def _chat_row(i: int) -> dict:
    return {
        "id": f"two-sum-L1-{i}",
        "messages": [
            {"role": "system", "content": "You are a Socratic coach."},
            {"role": "user", "content": f"Attempt {i}: wrong answer."},
            {"role": "assistant", "content": f"Hint {i}: restate the task."},
        ],
    }


class FakeDatasets:
    def __init__(self, final_status: str = "succeeded") -> None:
        self.final_status = final_status
        self.upload_calls: list[dict] = []

    def upload_file(self, path, **kwargs):  # noqa: ANN001, ANN003
        self.upload_calls.append({"path": Path(path), **kwargs})
        return SimpleNamespace(dataset_id="ds_1", status="awaiting_preprocessing")

    def wait_for_completion(self, dataset_id, timeout):  # noqa: ANN001
        return SimpleNamespace(status=self.final_status, row_count=2, error_data=None)


class FakeAutoscientist:
    def __init__(self, final_status: str = "succeeded") -> None:
        self.final_status = final_status
        self.create_calls: list[dict] = []

    def create(self, **kwargs):  # noqa: ANN003
        self.create_calls.append(kwargs)
        return SimpleNamespace(id="exp_1", model="base-x", status="pending", best_win_rate=None)

    def wait_for_completion(self, experiment_id, timeout):  # noqa: ANN001
        return SimpleNamespace(status=self.final_status, best_win_rate=0.7, error=None)


class FakeClient:
    def __init__(self, dataset_status: str = "succeeded", run_status: str = "succeeded") -> None:
        self.datasets = FakeDatasets(dataset_status)
        self.autoscientist = FakeAutoscientist(run_status)


def test_chat_rows_become_prompt_completion_pairs() -> None:
    rows = adaption.to_prompt_completion([_chat_row(1)])
    assert rows == [{
        "prompt": "You are a Socratic coach.\n\nAttempt 1: wrong answer.",
        "completion": "Hint 1: restate the task.",
    }]


def test_upload_file_is_written_as_jsonl(tmp_path: Path) -> None:
    out = tmp_path / "upload.jsonl"
    n = adaption.write_upload_file([_chat_row(1), _chat_row(2)], out)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert n == 2 and len(lines) == 2
    assert set(json.loads(lines[0])) == {"prompt", "completion"}


def test_upload_uses_raw_mode_with_explicit_columns() -> None:
    client = FakeClient()
    dataset_id = adaption.upload(client, path=Path("upload.jsonl"))
    assert dataset_id == "ds_1"
    call = client.datasets.upload_calls[0]
    assert call["processing_mode"] == "raw"
    assert call["column_mapping"] == {"prompt": "prompt", "completion": "completion"}


def test_training_run_passes_idempotency_key_and_instruction_format() -> None:
    client = FakeClient()
    run = adaption.start_training(client, "ds_1", idempotency_key="key-123")
    assert run.id == "exp_1"
    call = client.autoscientist.create_calls[0]
    assert call["dataset_id"] == "ds_1"
    assert call["idempotency_key"] == "key-123"
    assert call["data_format"] == "instruction"
    assert "model" not in call  # the platform picks the base model unless one is given


def test_failed_dataset_raises() -> None:
    with pytest.raises(RuntimeError, match="ended as failed"):
        adaption.wait_for_dataset(FakeClient(dataset_status="failed"), "ds_1")


def test_failed_training_run_raises() -> None:
    with pytest.raises(RuntimeError, match="ended as failed"):
        adaption.wait_for_training(FakeClient(run_status="failed"), "exp_1")


def test_run_record_states_leaderboard_is_not_submitted(tmp_path: Path) -> None:
    record = adaption.RunRecord(dataset_id="ds_1")
    adaption.save_record(record, tmp_path / "run.json")
    saved = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert saved["dataset_id"] == "ds_1"
    assert saved["leaderboard"].startswith("not submitted")
