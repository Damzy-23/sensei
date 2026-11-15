# Senior API

Base URL (dev): `http://localhost:8000`. All bodies are JSON. CORS is open for development.
With `SENSEI_USE_STUBS=1` (the default) responses are **stub data**. With `SENSEI_USE_STUBS=0` the
session, trace, track and mentor endpoints run the real orchestrator; `/eval/results` is still a stub.
Shapes are the same in both modes and will not change without a note here.

Interactive docs once the server runs: `http://localhost:8000/docs`.

Run: `uvicorn app.main:app --reload --port 8000`

---

## Conventions

- Errors: `404 {"detail": "..."}` for unknown ids; `422` for invalid bodies (FastAPI standard).
- Ids: `ses_*` sessions, `trc_*` traces, `tkt_*` tickets, `msg_*` chat messages, `evt_*` events.
- Timestamps: ISO 8601 UTC strings.
- **Never returned by any endpoint:** reference solutions, hidden tests, or the internal prompts.

## Enums

| Field | Values |
|---|---|
| `difficulty` | `easy`, `medium`, `hard` |
| `mode` | `learn`, `interview`, `blitz`, `call` |
| `hint_level` | integer `0`–`5` (0 = no hint yet) |
| `next_action` | `keep_coding`, `ask_for_hint`, `review_complexity`, `escalate` |
| `actor` (trace) | `client`, `guard`, `orchestrator`, `interviewer`, `hint_coach`, `evaluator`, `planner`, `mentor`, `escalation` |
| `type` (trace) | `turn.start`, `guard.input`, `mode.decision`, `agent.start`, `llm.call`, `tool.call`, `tool.result`, `guard.output`, `escalation.created`, `mentor.message`, `turn.end`, `eval.run`, `eval.pair` |
| `status` (trace) | `ok`, `blocked`, `error`, `retried` |
| chat `actor` | `student`, `coach`, `mentor` |
| ticket `status` | `open`, `resolved` |

---

## Who can see what

Nobody has to sign in. Every request is answered for a viewer: a guest, or a signed-in user.

| Viewer | Sees and can act on |
|---|---|
| Anyone, guest or signed in | The sessions their own browser started: those sessions' activity and mentor tickets |
| A mentor | Every session |

- **A session id is the key to a session.** It is unguessable (`ses_` + 12 hex digits). The browser
  remembers the ids of the sessions it starts (the newest 30, in `localStorage`) and sends them with
  every request in the header `X-Senior-Sessions: ses_3f9a1c0d2e4b,ses_77aa01bc93de`. Ids that are
  not well formed are ignored, and at most 30 are read.
- **A mentor** is a signed-in user whose verified email is listed in `SENSEI_MENTOR_EMAILS`. The
  sign-in is a Firebase ID token in `Authorization: Bearer <token>` (or `?token=` for EventSource),
  and it can only be checked when `SENSEI_AUTH_PROJECT` names the Firebase project. A token that
  does not verify answers `401`. No token is a guest, never an error.
- **Scoped routes:** `GET /logs` and everything under `/mentor/tickets`. A ticket of a session the
  viewer does not hold answers `404`, the same as a ticket that does not exist.
- **Routes keyed by an unguessable id are not scoped:** `/sessions/{session_id}/...` and
  `/traces/{trace_id}` answer whoever knows the id. No scoped route returns another session's
  session id, trace id or ticket id.

| Setting | Meaning |
|---|---|
| `SENSEI_SCOPE_DATA=1` | Switches the rules above on. Unset, every caller sees every session, as before: fine on your own machine, not on a public server. |
| `SENSEI_MENTOR_EMAILS` | The mentors' emails, comma separated. Case does not matter. Empty means there are no mentors. |
| `SENSEI_AUTH_PROJECT` | The Firebase project whose tokens are accepted. With scoping off it also makes every call need a sign-in, as before. |

---

## Sessions

### `POST /sessions` → 201
Optional body: `{ "mode": "learn" }` (`learn` by default, or `interview`, `blitz`). The mode decides
which agent answers: the hint coach in `learn`, the interviewer in `interview` and `blitz`.
```json
{ "session_id": "ses_3f9a1c0d2e4b" }
```

### `POST /sessions/{session_id}/message` → SSE stream
Request:
```json
{
  "text": "I'm stuck on how to find the pair",
  "problem_id": "two-sum",
  "code": "def two_sum(nums, target):\n    pass\n"
}
```

Response is `text/event-stream`. Two kinds of event:

**`event: trace`**: one per agent/tool/guard step, as it happens. `data` is a `TraceEvent`:
```
event: trace
data: {"event_id":"evt_0002","trace_id":"trc_stub_0001","span_id":"spn_guard","parent_span_id":"spn_root","session_id":"ses_demo_0001","seq":2,"ts":"2026-11-14T10:05:00.120+00:00","actor":"guard","type":"guard.input","name":"classify_input","status":"ok","decision":"ok","reason":"fast model: ok (0.94)","latency_ms":212.0,"model":"claude-haiku-5-5","tokens_in":180,"tokens_out":12,"cost_usd":0.00004,"input":"I'm stuck on how to find the pair","output":"{\"category\":\"ok\"}"}

```

**`event: final`**: exactly one, always last on success:
```
event: final
data: {"reply":"Good start. Try writing down what you need to know about each number as you scan the list.","mode":"learn","hint_level":1,"escalated":false,"trace_id":"trc_stub_0001"}

```

**`event: error`** (Phase 3+): `data: {"message": "...", "trace_id": "..."}`. Stream ends after it.

Each event is `event: <name>` line, `data: <json>` line, blank line.

### `POST /sessions/{session_id}/runs` → 200
Test results come from the browser runner (Pyodide). Trusted for the hackathon.
Request:
```json
{
  "problem_id": "two-sum",
  "code": "def two_sum(nums, target): ...",
  "passed": 1,
  "failed": 2,
  "total": 3,
  "failures": [{ "name": "duplicates", "message": "expected [0, 1], got None" }],
  "runtime_ms": 12
}
```
Response:
```json
{ "mode": "learn", "hint_level_available": 1, "next_action": "ask_for_hint" }
```
`hint_level_available` is the highest hint level the student may unlock next (`0` means none).

### `GET /sessions/{session_id}/state` → 200
```json
{
  "session_id": "ses_demo_0001",
  "problem_id": "two-sum",
  "mode": "learn",
  "hint_level": 1,
  "failed_runs": 2,
  "hints_used": 1,
  "time_on_problem": 420,
  "mastery": { "hash map": 0.42, "stack": 0.18 },
  "escalated": false,
  "countdown_seconds": null
}
```
- `failed_runs`: consecutive failed runs.
- `time_on_problem`: seconds on the current problem.
- `countdown_seconds`: only set in `blitz` mode. The frontend shows it.

### `GET /sessions/{session_id}/events` → SSE (agent inspector)
Live trace stream for the session. Same `event: trace` framing as above.
Phase 1 stub replays one turn, then sends:
```
event: end
data: {"reason": "stub replay complete"}

```
Phase 3+ keeps the connection open and sends `trace` events as they are written.

---

## Problems

### `GET /problems` → 200
```json
[
  { "id": "two-sum", "title": "Two Sum", "difficulty": "easy", "pattern": "hash map" },
  { "id": "valid-parentheses", "title": "Valid Parentheses", "difficulty": "easy", "pattern": "stack" }
]
```
Phase 3 will return 12 problems across two pointers, sliding window, hash map, stack, binary search, intervals, BFS/DFS, DP, and heap.

### `GET /problems/{problem_id}` → 200 | 404
```json
{
  "id": "two-sum",
  "title": "Two Sum",
  "difficulty": "easy",
  "pattern": "hash map",
  "statement": "Given a list of integers `nums` and an integer `target`, return the indices ...",
  "starter_code": "def two_sum(nums: list[int], target: int) -> list[int]:\n    # your code here\n    pass\n",
  "visible_tests": [
    { "name": "example 1", "input": "nums=[2,7,11,15], target=9", "expected": "[0, 1]" },
    { "name": "duplicates", "input": "nums=[3,3], target=6", "expected": "[0, 1]" }
  ]
}
```

---

## Interview panel

In `interview`, `blitz` and `call` modes two interviewers work on every turn: the lead
answers, and an observer notes what the candidate did. They run side by side, so the
second one adds no wait. The observer never speaks in the conversation.

### `GET /sessions/{session_id}/panel` → 200
```json
{
  "active": true,
  "notes": [
    { "dimension": "complexity", "rating": 1, "note": "You stated the cost before writing any code." }
  ],
  "scores": {
    "communication": { "score": null, "signals": 0 },
    "approach": { "score": null, "signals": 0 },
    "correctness": { "score": null, "signals": 0 },
    "complexity": { "score": 4.0, "signals": 1 }
  }
}
```
- `rating`: `1` a strength, `0` mixed, `-1` to work on.
- `score`: 1.0 to 4.0, computed as `2.5 + 1.5 × mean(rating)`. **`null` means not observed**, not zero.
- Notes are cleared when the session moves to a new problem. A note containing code is dropped.

### `POST /sessions/{session_id}/debrief` → 200 | 409 | 502
Ends the interview. The evaluator writes the feedback from the notes; the scores are the same
computed ones.
```json
{
  "summary": "You started well: ...",
  "strengths": ["..."], "work_on": ["..."], "interviewers_look_for": ["..."],
  "scores": { "approach": { "score": 1.0, "signals": 1 } },
  "notes_used": 4,
  "trace_id": "trc_..."
}
```
`409` when there are no notes yet. `502 {"detail": {"message", "trace_id"}}` when the model
fails or the feedback contained code and was withheld.

---

## Tracks

### `GET /tracks` → 200
```json
[
  { "id": "blind_75", "title": "Blind 75", "count": 75 },
  { "id": "neetcode_150", "title": "NeetCode 150", "count": 150 }
]
```

### `GET /tracks/{track_id}` → 200 | 404
The summary fields plus `problems`. `runnable` is true when the problem has a full statement,
starter code and visible tests (`GET /problems/{id}` works for it). Any track problem can be
used as `problem_id` in a session, runnable or not.
```json
{
  "id": "blind_75", "title": "Blind 75", "count": 75,
  "problems": [
    { "id": "two-sum", "title": "Two Sum", "difficulty": "easy", "pattern": "arrays", "runnable": true }
  ]
}
```

---

## Traces

### `GET /traces/{trace_id}` → 200 | 404
Full span tree for one student message. Use `roots[].children` to draw the tree. Each node's `event` is the span's start event.
```json
{
  "trace_id": "trc_stub_0001",
  "session_id": "ses_demo_0001",
  "roots": [
    {
      "event": { "event_id": "evt_0001", "span_id": "spn_root", "parent_span_id": null, "type": "turn.start", "name": "turn", "actor": "orchestrator", "status": "ok", "latency_ms": 1310.0, "...": "..." },
      "children": [
        { "event": { "span_id": "spn_guard", "type": "guard.input", "name": "classify_input", "actor": "guard", "decision": "ok", "reason": "fast model: ok (0.94)", "...": "..." }, "children": [] },
        { "event": { "span_id": "spn_mode", "type": "mode.decision", "name": "select_mode", "actor": "orchestrator", "decision": "learn", "reason": "rule learn.default: no solved runs yet", "...": "..." }, "children": [] },
        { "event": { "span_id": "spn_coach", "type": "agent.start", "name": "hint_coach", "actor": "hint_coach", "...": "..." },
          "children": [
            { "event": { "span_id": "spn_llm", "type": "llm.call", "name": "llm_hint", "model": "claude-sonnet-5-5", "tokens_in": 640, "tokens_out": 70, "cost_usd": 0.0029, "...": "..." }, "children": [] }
          ]
        },
        { "event": { "span_id": "spn_out", "type": "guard.output", "name": "leak_check", "decision": "pass", "...": "..." }, "children": [] }
      ]
    }
  ]
}
```

---

## Mentor

Tickets are created automatically when a session escalates (hint level 5 still failing, 3 guard violations, or frustration flagged twice).

A mentor works the whole queue. Anyone else gets the tickets of their own sessions, and `404` for
any other ticket id (see [Who can see what](#who-can-see-what)).

### `GET /mentor/scope` → 200
Whose tickets this caller's queue holds: `"all"` for a mentor, or when scoping is off; otherwise `"own"`.
```json
{ "scope": "own" }
```

### `GET /mentor/tickets` → 200
```json
[
  { "id": "tkt_0001", "session_id": "ses_demo_0001", "problem_id": "two-sum", "status": "open", "stuck_reason": "Reached hint level 5 and 4 consecutive failed runs (timeout on large input).", "created_at": "2026-11-14T10:12:00+00:00" }
]
```

### `GET /mentor/tickets/{ticket_id}` → 200 | 404
Same fields as above, plus:
```json
{
  "transcript": [
    { "id": "msg_1", "session_id": "ses_demo_0001", "actor": "student", "text": "I'm stuck on two sum, my code times out", "ts": "2026-11-14T10:05:00+00:00", "trace_id": null },
    { "id": "msg_2", "session_id": "ses_demo_0001", "actor": "coach", "text": "What is the cost of checking every pair when nums is large?", "ts": "2026-11-14T10:05:03+00:00", "trace_id": null }
  ],
  "latest_code": "def two_sum(nums, target):\n    for i in range(len(nums)): ...",
  "suggested_intervention": "Student is using nested loops and hitting timeouts. Ask them to name the cost of the inner loop, then point at the complement lookup idea."
}
```

### `POST /mentor/tickets/{ticket_id}/reply` → 200 | 404
Request: `{ "text": "Look at the inner loop." }`
Response: the new chat message. It is also inserted into the student's chat with `actor: "mentor"`.
```json
{ "id": "msg_9f2e", "session_id": "ses_demo_0001", "actor": "mentor", "text": "Look at the inner loop.", "ts": "2026-11-14T10:20:00+00:00", "trace_id": null }
```

### `POST /mentor/tickets/{ticket_id}/resolve` → 200 | 404
Response: the ticket with `"status": "resolved"`. The session's `escalated` flag clears.

---

## Activity log

### `GET /logs` → 200
The agents' actions, newest first, with a summary per agent. Query: `actor`, `type` (a prefix such
as `llm`, `tool`, `guard`), `session_id` and `limit` (1 to 1000, default 300). The filters narrow
the list; `session_id` never widens what the caller may see.
```json
{
  "events": [ { "event_id": "evt_0005", "session_id": "ses_3f9a1c0d2e4b", "actor": "hint_coach", "type": "llm.call", "...": "..." } ],
  "summary": [
    { "actor": "hint_coach", "events": 2, "model_calls": 1, "tool_calls": 0, "blocked": 0, "errors": 0, "tokens_in": 640, "tokens_out": 70, "cost_usd": 0.0029 }
  ],
  "durable": false,
  "scope": "own",
  "totals_all": { "events": 4310, "model_calls": 1204, "tool_calls": 96, "cost_usd": 3.18 }
}
```
- `scope` is `"all"` for a mentor (or when scoping is off): `events` and `summary` cover every
  session. Otherwise it is `"own"`: they cover only the sessions the caller holds.
- `totals_all` always covers every session, so the screen can say how much the whole system has
  done. It holds these four numbers and nothing else: no text and no ids. It is `null` if the
  totals could not be read; the rest of the log is still returned.
- `durable` is true when the log is read from the Firestore archive.

---

## Eval

### `GET /eval/results` → 200
Phase 1 returns `"status": "stub"` with zero counts. Phase 7+ returns `"status": "ready"`.
```json
{
  "status": "stub",
  "generated_at": null,
  "held_out_problems": ["sliding-window-max", "dijkstra-grid", "coin-change"],
  "base":  { "model_key": "hint_base",  "win_rate": 0.5, "n": 0, "leak_rate": 0.0, "criteria": { "correct_level": 0.0, "socratic": 0.0, "helpful": 0.0, "brevity": 0.0 } },
  "tuned": { "model_key": "hint_tuned", "win_rate": 0.5, "n": 0, "leak_rate": 0.0, "criteria": { "correct_level": 0.0, "socratic": 0.0, "helpful": 0.0, "brevity": 0.0 } },
  "examples": [
    { "scenario_id": "stub-1", "problem_id": "two-sum", "hint_level": 2, "base_hint": "...", "tuned_hint": "...", "winner": "tie" }
  ]
}
```
`win_rate` is the tuned model's win rate against base when judged pairwise. Leakage is a hard fail, counted in `leak_rate`.

---

## Other routes

These exist and are tested, but are not written out in full here. Their exact request and
response shapes are in the interactive docs at `/docs` (generated from the code).

| Route | What it does |
|---|---|
| `GET /sessions/{session_id}/mentor-messages` | The mentor's replies for a session, so the student's chat can show them |
| `POST /voice/session` | A short-lived signed URL for a browser voice call. The provider key stays on the server |
| `POST /voice/tts` | Speaks up to 600 characters in a coach's voice (`persona`: `drill`, `mentor` or `peer`) and returns MP3. Cached and rate limited |
| `POST /cv/tailor` | Rewrites a CV for a job from the candidate's own facts; returns job fit, a score for every line, gaps and drafted lines |
| `POST /cv/score` | Scores CV lines by rule. No model is called |
| `POST /cv/research` | Looks a role up on the web through Linkup and Exa; each search reports whether it ran |
| `POST /profile`, `GET /profile/{id}`, `POST /profile/{id}/answer`, `POST /profile/{id}/recommend` | The career interview and role recommendations |
| `GET /logs` | The activity log: recent actions by every agent |

Trace events are written when a span finishes, so the root node of a trace tree carries the
`turn.end` event, with the turn's total latency. Actors also include `caller`, `observer`,
`job_analyst`, `cv_writer` and the career agent.

---

## Quick test with curl

```bash
curl -s -X POST localhost:8000/sessions
curl -s localhost:8000/problems
curl -s localhost:8000/problems/two-sum
curl -N -X POST localhost:8000/sessions/ses_demo/message -H 'content-type: application/json' \
  -d '{"text":"stuck","problem_id":"two-sum","code":""}'
```
