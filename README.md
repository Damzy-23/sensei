# Senior

> Working name. The repository and the `SENSEI_*` settings keep the earlier name, Sensei, for now.

A coding-interview coach built as a small team of AI agents. Senior gives graded,
Socratic hints instead of answers, runs mock interviews, hands a stuck student to
a human mentor, and shows every step the agents took: which agent, which model,
how many tokens, what it cost, and why.

Built at the Imperial AI Hack, 14–15 November 2026.

## The problem

Students preparing for coding interviews either get no help or get the whole
answer. A tutor that explains too much teaches nothing, and an AI tutor is hard
to trust when nobody can see why it said what it said or what it cost.

## What it does

- **Learn mode.** A hint coach answers on a ladder from level 0 to 5. Each request
  for help moves one step up. No level ever contains code.
- **Interview and blitz modes.** An interviewer probes the approach and its cost
  without teaching. Blitz adds a 10-minute countdown.
- **Guardrails.** Every message is classified before an agent sees it. Every reply
  is checked for leaked code, and rewritten once if it fails.
- **Human in the loop.** Still stuck after the level 5 hint, three blocked messages,
  or two signs of frustration: a mentor gets a ticket with the transcript and code,
  and their reply lands in the student's chat.
- **Agent inspector.** Each turn is a trace tree streamed live: agent, action, model,
  tokens, cost in USD, latency, and the decision with its reason.
- **Tracks.** Blind 75 and NeetCode 150.

## How it works

One supervisor hands each turn to one specialist. The code is organised by the six
building blocks of an agent system (role-playing, focus, tools, cooperation,
guardrails, memory), and the layering between them is enforced by tests.

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): the design, a diagram of one turn, requirements, and what is built.
- [docs/API.md](docs/API.md): the HTTP contract.
- [docs/adr/](docs/adr/): three decisions and why we made them.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # add ANTHROPIC_API_KEY, set SENSEI_USE_STUBS=0
.venv/bin/uvicorn app.main:app --reload --port 8000
.venv/bin/python -m pytest -q
```

With `SENSEI_USE_STUBS=1` (the default) the API serves fixed sample data and needs no key.
Interactive API docs: http://localhost:8000/docs

## APIs, models and data

| | |
|---|---|
| Models | Claude Sonnet 5.5 (hint coach, interviewer) and Claude Haiku 5.5 (input guard), through the Anthropic API |
| Libraries | FastAPI, Pydantic, Uvicorn, httpx, PyYAML, the Anthropic Python SDK, pytest |
| Data | Problem lists: Blind 75 and NeetCode 150 (public lists; titles, difficulty and topic only) |

## Status

Built and tested: the turn loop for learn, interview and blitz modes, both guards,
escalation and the mentor queue, test-run handling with mastery, tracing with cost,
and the track catalogue.

Not built yet: the evaluator and planner agents, the tuned-versus-base hint model
evaluation (`/eval/results` returns placeholder data), a frontend, and full
statements and tests for most track problems (two have them).

## Live demo

https://senior-coach-1115-29b5.web.app (Firebase Hosting). Sign in with Google or email,
or continue as a guest.

During the hackathon the API behind it runs on a team laptop through a Cloudflare
tunnel, so the demo answers only while that laptop is online. Sign-in is checked in the
browser only: the API does not verify the Firebase token yet.
