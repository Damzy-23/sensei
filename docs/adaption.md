# Adaption: how the hint coach is trained

Written from the `adaption` Python SDK 0.19.0 (installed in `.venv`) and the public docs at
https://docs.adaptionlabs.ai. Re-check both before the demo, because the API may change.

## Setup

```bash
.venv\Scripts\python -m pip install -r requirements.txt   # includes adaption==0.19.0
```

Create an API key in Adaption under **Settings > API keys**, then put it in `.env`:

```
ADAPTION_API_KEY=pt_live_...
```

The SDK reads this variable itself. Never commit `.env`, and never paste the key into chat or code.

## What we train

The hint coach (`hint_tuned`) writes Socratic hints at five levels. Training rows come from
`scripts/make_hint_data.py`, which writes `data/adaption/train.jsonl`. Each row is one chat:
system prompt, user turn (the student's attempt), and the assistant hint. Held-out scenarios go to
`data/adaption/test.jsonl`, which the win-rate eval uses. Those scenarios are never uploaded.

`app/eval/adaption.py` turns each chat row into a `prompt` (system and user joined) and a
`completion` (the hint). It writes `data/adaption/upload.jsonl`.

## The pipeline

| Step | Command | SDK call | What it does |
|---|---|---|---|
| Upload | `python scripts/adaption_train.py upload` | `datasets.upload_file(path, processing_mode="raw", column_mapping={prompt, completion})` | Creates the dataset, uploads the file to a pre-signed URL, and completes the upload. Raw mode skips Adaption's document preprocessing, so no preprocessing credits are used and the rows are trained as written. |
| Ready | (same step) | `datasets.wait_for_completion` | Polls until the dataset is `succeeded`. Fails loudly otherwise. |
| Train | `python scripts/adaption_train.py train` | `autoscientist.create(dataset_id, data_format="instruction", column_mapping, idempotency_key)` then `autoscientist.wait_for_completion` | Starts an AutoScientist run. The idempotency key stops a retry from starting a second run. |
| Download | `python scripts/adaption_train.py download` | `autoscientist.download(experiment_id).write_to_file(...)` | Saves the trained model as `data/adaption/hint_coach_model.tar.gz`. |

`python scripts/adaption_train.py all` runs the three steps in order. Progress is written to
`data/adaption/run.json`, which holds the dataset id, run id, win rate, model path and leaderboard
status. The run record lets a later step resume without starting again.

## Not known from the docs

- **Leaderboard submission.** The SDK has no leaderboard call. `datasets.publish` targets Hugging
  Face or Kaggle, and it returns HTTP 501 (not implemented). Our record says
  `not submitted` until we know the process. Ask the organisers or Adaption support
  (https://docs.adaptionlabs.ai/resources/support/).
- **Serving the tuned model.** AutoScientist gives us a downloadable artifact. The docs don't say
  whether Adaption hosts it. To use it as `hint_tuned`, we must serve it on an OpenAI-compatible
  endpoint and set `HINT_TUNED_BASE_URL`, `HINT_TUNED_API_KEY` and `HINT_TUNED_MODEL`. The
  artifact format and how to serve it are unconfirmed.
- **Base model.** `autoscientist.list_models()` lists the options. We let the platform choose,
  until the hosting question is answered.

## Status

- Built: the conversion, upload, training, download and run record, with tests against a fake
  client (`tests/test_adaption.py`).
- Not run: no `ADAPTION_API_KEY` in this environment, and `data/adaption/train.jsonl` does not exist
  yet (it needs the Anthropic key). Nothing has been uploaded.
- Open: the leaderboard process and the hosting path above.
