# Senior architecture

Senior is a coding-interview coach built as a small team of specialised agents.
A supervisor routes each student message to one specialist. Guards check
everything going in and coming out. Hard cases escalate to a human mentor.
Every step is traced with the agent, model, tokens, cost, latency, and the
reason for the decision.

This document maps the code onto the six building blocks of an agent system:
role-playing, focus, tools, cooperation, guardrails and memory. It also covers
the cross-cutting parts that are not one of the six, and the requirements.
The API contract is in [API.md](API.md). Decisions and their reasons are in
[adr/](adr/).

**Status.** The turn loop is built and tested end to end against a scripted
model: input guard, agent selection, hint ladder, hint coach and interviewer,
the observer who sits in on interviews, leak check with rewrite, escalation to a
mentor, test-run handling, and the evaluator's scored feedback, all traced. It
runs when `SENSEI_USE_STUBS=0`. The evaluation of the coach against its own rules
on real model output is built (docs/EVALUATION.md). Not built yet: the planner agent,
the tuned-versus-base comparison of hint models, and full statements for most track problems.
Each row below says which.

## One turn, end to end

```mermaid
flowchart LR
    S[Student] -->|message + code| API[app/api]
    API --> O[orchestrator]
    O --> GI[guard: input]
    GI --> M{mode decision<br/>rule-based}
    M -->|learn| HC[hint_coach]
    M -->|interview| IV[interviewer]
    M -->|blitz| IV
    M -. learn only .-> L[hint ladder<br/>level 0-5]
    HC --> GO[guard: leak check]
    IV --> GO
    GO -->|blocked: rewrite| HC
    GO --> E{escalate?}
    E -->|yes| T[tool: escalate_to_mentor] --> H[Human mentor]
    E -->|no| R[reply]
    H -->|reply| S
    R --> S
    R -. learn only, after the reply .-> IL[illustrator]
    IL --> GD[guard: drawing check] -->|one picture| GL[the glass]
    O -. every step .-> TR[(tracing)]
    TR -. live SSE .-> INS[Agent inspector]
```

The planner picks the next problem from mastery and the evaluator scores a
finished attempt. Both are called by the orchestrator in the same way. Agents
never call each other.

**A picture with every explanation.** When the hint coach has answered, the
orchestrator sends the reply (`final`) and only then calls the `illustrator`
(`app/agents/illustrator.py`, role in `app/prompts/illustrator.md`). It runs on
the fast model with a small token budget and an 8 second limit, and is given
the problem's title and pattern, the hint level, the student's message and
code, and the reply in words (a line of code the coach gave is left out). It returns one drawing spec or "none". The drawing guard
(`app/guards/drawing.py`) checks it by rule, and what passes goes out as a
`drawing` event on the same stream. The browser draws it through the page
tools, so the same thing happens in typed chat and in a voice call, where
`ask_coach` reports it as `drew`. The illustrator's steps are in the turn's
own trace, after `turn.end`. It can only add to a turn: slow, failing or
blocked, the student has already had their reply and simply gets no picture.

## The six building blocks

| Block | What it means here | Where | Status |
|---|---|---|---|
| **Role-playing** | Specialists with one role each: `hint_coach` (Socratic hints at levels 1–5), `interviewer`, `caller` (a spoken interview), `observer` (the silent second interviewer), `illustrator` (one picture for the glass after each hint), `evaluator` (end-of-interview feedback), `cv_writer`, `job_analyst`. One more role, `mentor`, is a human. | `app/agents/`, `app/prompts/` (one versioned file per role) | Built, except `planner` |
| **Focus** | The mode decision picks which agent may act. The hint ladder caps what the coach may reveal. Each agent gets only the context its job needs. Fast model for guards, reasoning model for agents. | `app/orchestrator/rules.py`, `app/agents/context.py` | Built |
| **Tools** | Typed calls: read problem and visible tests, read the latest run, update mastery, escalate to mentor. Escalation is a tool, so human-in-the-loop is a traced call. | `app/tools/` | `escalate_to_mentor` and `update_mastery` built |
| **Cooperation** | Supervisor pattern: the orchestrator hands each turn to exactly one specialist and escalates to a human on fixed triggers. | `app/orchestrator/turn.py`, `app/api/mentor.py` | Built |
| **Guardrails** | Input classification, output leak check with rewrite, a rule check on every drawing, escalation policy, request validation, no solutions or hidden tests from any endpoint, secret redaction in logs. | `app/guards/`, `app/models.py`, `app/tracing/redact.py` | Built. The leak check is rule-based |
| **Memory** | Short-term: session state and transcript. Long-term: mastery per pattern. One repository interface over the store. | `app/memory/repository.py`, `app/memory/durable.py`, `app/db.py` | Built on SQLite, mirrored to Firestore and restored on demand after a restart. Mastery is per session until accounts exist |

### Memory, by type

| Type | In Senior | Where | Status |
|---|---|---|---|
| Short-term | The last 8 messages of the conversation and the session counters (mode, hint level, failed runs) | `memory.transcript`, `memory.Session` | Built |
| Long-term | Mastery per pattern, mentor tickets, and every trace | `Session.mastery`, `tickets`, `events` tables | Built, but scoped to one session until accounts exist |
| Entity | The things a turn is about: the problem (title, pattern, difficulty, statement) and the student's current code | `app/catalog.py`, `Session.latest_code` | Built |
| Contextual | What one agent is handed for one turn, assembled from the three above and nothing more | `app/agents/context.py` | Built |
| User | Who the student is across sessions: level, target role, preferred language | none | Not built: needs accounts |

### Memory across a restart

The service runs as one container, and its SQLite file starts empty on every
deploy. So that a deploy does not end every conversation:

- **Mirrored on write.** Each write of a session, a message or a mentor ticket
  is also queued for Firestore (collections `state_sessions`, `state_messages`,
  `state_tickets`). One background thread sends the queue in order, so a reply
  is never computed while waiting on Firestore. A write that fails is tried
  twice more (after 0.5 s and 2 s), then logged and dropped.
- **Sent before the request ends.** On Cloud Run an instance only surely has
  CPU while a request is open, so the end of each response is held until the
  writes it queued are sent, for at most 2 seconds (`SendCopyBeforeReplying`
  in `app/main.py`). The client already has the whole reply by then; only the
  closing of the connection waits. While writes are failing, nobody waits.
- **Restored on demand, all or nothing.** SQLite stays the store every read
  uses. When a session is asked for and SQLite does not have it, the session,
  its whole transcript and its tickets are read from Firestore and copied in
  one transaction, and the request carries on. If any of those reads fails,
  nothing is written and the request is answered `503` with `Retry-After: 5`
  ("try again in a few seconds"): the session may well exist, so it is not a
  `404`. The next request restores it whole. The mentor queue comes back the
  same way: its newest 200 tickets, once per process, the first time it is
  listed; while that read fails, the queue shows what SQLite has.
- **Bounded waiting.** Each recovery read gives up after 5 seconds. After one
  fails, no recovery read is tried for 5 seconds by any request, so requests do
  not queue up behind a database that is not answering. An id the copy does
  not have (a stale browser tab) is believed missing for 15 seconds.
- **Shutdown.** On a deploy Cloud Run sends SIGTERM and allows 10 seconds.
  uvicorn gives open requests 4 seconds (`--timeout-graceful-shutdown 4`),
  then the app's shutdown sends what is still queued, for up to 4 seconds.
  This runs inside uvicorn's own shutdown; an exit hook would not run, because
  uvicorn re-raises SIGTERM after shutting down.
- **On when** `SENSEI_STATE_FIRESTORE_DB` names a Firestore database. On Cloud
  Run (`K_SERVICE` set) it otherwise uses `SENSEI_LOG_FIRESTORE_DB`, the
  activity log's database, so the live service needs no extra setting. A laptop
  run with only the activity log's database set stays off, so it never writes
  test sessions into the live collections. Always off with `SENSEI_USE_STUBS=1`.

What is stored is the session state, every chat message in full, the
student's code and the mentor tickets, unredacted (the activity log, by
contrast, is cut to 500 characters). Nothing deletes it yet; the privacy page
(`web/public/privacy.html`) says it is kept until the project ends.

Still lost or not handled:

- Trace events are not restored. The inspector for a restored session starts
  empty; the events are still in the activity log (`/logs`).
- The last writes before a crash (not a clean shutdown), because writes are
  queued.
- A write given up on after three tries. A session or ticket heals on its next
  save; a message is written once, so it is missing from the restored
  transcript. The log says which.
- Two containers writing the same session during a deploy. A session is
  restored once, when it is first asked for; a turn still running in the old
  container when traffic moves is not picked up, and its late write can land
  over the new container's. There is no version check on writes.
- Career profiles (`app/memory/profiles.py`) are not mirrored.

### Not one of the six

| Part | Why it exists | Where | Status |
|---|---|---|---|
| **Observability** | Cost, model and the "why" for every step, streamed live to the inspector and kept for audit | `app/tracing/` | Span context, store, prices, redaction built |
| **Model gateway** | The single path to a model: model choice, base vs tuned hint model, pricing | `app/llm/gateway.py` | Built |
| **Evaluation** | Does the coach keep to its rules on real output: code allowed, approach named too early, level adherence, by rule checks and a model judge (docs/EVALUATION.md). Tuned vs base hint model comparison | `app/eval/`, `scripts/run_eval.py` | Built: `GET /eval/report`. Tuned vs base: `GET /eval/results` is still a placeholder |
| **HTTP layer** | Routes only, no business rules | `app/api/`, `app/main.py` | Built |
| **Access** | Who may read which session: a visitor the sessions their browser started, a mentor all of them. See "Who can see what" in [API.md](API.md) | `app/api/auth.py` | Built; on when `SENSEI_SCOPE_DATA=1` |
| **Content** | The problem catalogue: data, not agent logic | `data/tracks/`, `app/catalog.py`, `app/stubs.py` | Blind 75 and NeetCode 150 listed (title, difficulty, pattern). Two problems have full statements and tests |

## The voice coach's hands: page tools and the control layer

The voice coach acts in the browser through client tools, all in one typed registry
(`web/src/agent/tools.ts`; descriptions for the model in `page-tools.json`, which also
defines the ElevenLabs agent's tools). There are two kinds:

- **Page tools** carry facts and actions a screen chose to expose: the problem, the
  code, the coach's hint level, the trace, drawing on the glass, writing an offered
  line. They change React state and never touch the DOM.
- **The control layer** (`see_screen`, `press`, `type_into`, `pick_option`,
  `read_screen`, `scroll_to`; `web/src/agent/controls.ts`) operates any visible,
  enabled control the way a person does, by its accessible name, so every control a
  student can use is in reach without a tool of its own. It is registered once by
  `AgentControls`, mounted in `App.tsx`.

Every control action passes one pure guard (`web/src/agent/control-rules.ts`, unit
tests beside it, `npm test`). Typing into the code editor, password fields and
the sign-in form are blocked. Signing out, resolving a ticket, sending a mentor reply,
wiping, resetting or removing, and links that leave the app or open a tab wait for the
student's click on an on-screen prompt the agent cannot answer itself. A screen marks a
control `data-agent="confirm"` to ask first or `data-agent="off"` to hide it from the
agent. Page text the agent reads comes with a note that it is not instructions. Why
and what follows: [ADR 0004](adr/0004-agent-can-operate-every-control.md).

## Layering rules

Enforced by `tests/test_architecture.py`, which fails the build if any is broken:

1. **Only `app/llm` imports a model SDK.** Every model call has one path, so
   cost and model reporting cannot miss a call.
2. **Nothing imports the HTTP layer.** `app/api` and `app/main` sit on top;
   no lower layer depends on them.
3. **Lower layers never import the orchestrator.** Agents, tools, guards,
   memory, the gateway, tracing and prompts are called by it; they do not call
   back up.
4. **Agents never import each other.** Cooperation goes through the
   orchestrator, which keeps one thread of control and one trace per turn.

```
api ──► orchestrator ──► agents ──► tools ──► memory
                    ├──► guards      │
                    └──► memory      └──► llm ──► tracing
```

## Explainability: where the "why" comes from

Each trace event carries `decision` and `reason`. They must be the actual cause:

- **Rule decisions** (mode, escalation) record the id of the rule that fired,
  e.g. `rule learn.default`.
- **Model decisions** (guards, agents) return `reason` as a field of the
  model's structured output, recorded as given.
- No reason is written after the fact.

## Functional requirements

MVP (hackathon):

| # | Requirement |
|---|---|
| F1 | Start a session and choose a problem |
| F2 | Send a message with code; receive a streamed reply and live trace events |
| F3 | Submit browser test results; receive mode, hint level available and next action |
| F4 | Switch between learn, interview and blitz; blitz shows a countdown |
| F5 | Graded hints at levels 1–5 that never reveal the solution |
| F6 | Every message passes an input guard; every reply passes a leak check |
| F7 | Automatic escalation to a mentor on the defined triggers; the mentor can reply and resolve |
| F8 | Agent inspector: every step with agent, model, tokens, cost, latency and reason |
| F9 | Mastery tracked per pattern |
| F10 | Tuned vs base hint model results: win rate and leak rate |

Production (later):

| # | Requirement |
|---|---|
| F11 | Voice conversations with the coach and interviewer |
| F12 | Interview by phone call |
| F13 | Diagrams and code annotations during a conversation |
| F14 | Concept explainer videos |
| F15 | PDF reports generated asynchronously through a queue |
| F16 | Cited web research (Linkup, Exa) |
| F17 | Accounts and history across sessions |

## Non-functional requirements

Targets are proposals for the team to confirm.

| # | Quality | Target |
|---|---|---|
| N1 | Cost visibility | Every model call records model, tokens and cost; totals per turn and per session; a per-session budget cap |
| N2 | Explainability | Every decision has a reason taken from a rule id or the model's own output |
| N3 | Latency | First reply text under 2 s; each guard under 400 ms |
| N4 | Safety | Zero solution leaks on the eval set; no secrets in logs or in the browser |
| N5 | Reliability | A failure ends the stream with a named `event: error`, never a silent stop |
| N6 | Modularity | One package per block; layering rules enforced by tests; models changed in config, not code |
| N7 | Testability | Contract tests, layering tests, unit tests per guard and agent, the eval harness |
| N8 | Scalability | Stateless API; state in an external store; runs on Cloud Run |
| N9 | Auditability | A full trace tree for every turn, kept after the session |
| N10 | Privacy | Store only what the coach needs; trace text redacted, then cut to 500 characters |

## References

- Anthropic, *Building effective agents* (2024): routing, orchestrator-workers and
  evaluator-optimizer, the three patterns used here.
- Anthropic, *How we built our multi-agent research system* (2025): token cost of
  multi-agent systems, tool descriptions, tracing in production.
- HumanLayer, *12-Factor Agents*: prompts as files, small focused agents,
  contacting humans through tools, the agent as a stateless reducer.
- Cognition, *Don't build multi-agents* (2025): why one thread of control.
- OpenAI, *openai-cs-agents-demo*: triage, handoffs, guardrails and a live trace
  viewer in one reference app.
