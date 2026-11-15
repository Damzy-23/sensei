# Demo runbook

## Setup (once)

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # Windows
cp .env.example .env                                     # then fill in ANTHROPIC_API_KEY
python scripts/validate_bank.py                          # all 12 reference solutions must pass
python -m pytest                                         # 225 tests, no network
```

## Run the server

```bash
.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Open `http://127.0.0.1:8000/docs` to check the API is up.

## Rehearse the scripted student

With the server running:

```bash
.venv\Scripts\python scripts/simulate_student.py
```

It plays ten steps: two failing runs, hint requests, three injection attempts (the third escalates),
a mentor reply and resolve, and a final message. It prints each reply with its mode, hint level and
trace tree. Use `--record data/demo/recording.json` to save the run.

## Fallback recording

`data/demo/recording.json` is a complete run from the scripted model, for when the network or the
API key fails on stage. Its `note` field says it was recorded without a real model. The guards,
modes, escalation and traces are the real code; only the coach's wording is placeholder text.

To replace it with a real-model run, use a key and re-record:

```bash
.venv\Scripts\python scripts/simulate_student.py --record data/demo/recording.json
```

## Demo order (suggested)

1. Show `GET /problems` and a problem view: no solution or hidden tests in the response.
2. Send a message asking for the answer. The reply redirects and explains the ladder.
3. Show a hint being refused ("Not yet") before any failed run, then granted after one.
4. Send an injection attempt. The trace shows `regex_precheck` blocking it with the rule name.
5. Send three injections. The session escalates, and the mentor ticket appears.
6. Reply as the mentor. It appears in the student's chat as `actor=mentor`.
7. Open a trace in the agent inspector and point out the parent-child tree, decisions and costs.

## Known limits for the demo

- Test runs are trusted from the browser (hackathon scope).
- Model costs use placeholder prices in `config/prices.yaml`. Check them before quoting figures.
- Without `ANTHROPIC_API_KEY` the server still runs: classification falls back to regex rules,
  hints fall back to the canned text, and tickets get a default intervention. Each fallback is
  visible in the trace.
