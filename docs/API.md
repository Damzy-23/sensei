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
| `mode` | `learn`, `interview`, `blitz` |
| `hint_level` | integer `0`–`5` (0 = no hint yet) |
| `next_action` | `keep_coding`, `ask_for_hint`, `review_complexity`, `escalate` |
| `actor` (trace) | `client`, `guard`, `orchestrator`, `interviewer`, `hint_coach`, `evaluator`, `planner`, `mentor`, `escalation` |
| `type` (trace) | `turn.start`, `guard.input`, `mode.decision`, `agent.start`, `llm.call`, `tool.call`, `tool.result`, `guard.output`, `escalation.created`, `mentor.message`, `turn.end`, `eval.run`, `eval.pair` |
| `status` (trace) | `ok`, `blocked`, `error`, `retried` |
| chat `actor` | `student`, `coach`, `mentor` |
| ticket `status` | `open`, `resolved` |

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

## Quick test with curl

```bash
curl -s -X POST localhost:8000/sessions
curl -s localhost:8000/problems
curl -s localhost:8000/problems/two-sum
curl -N -X POST localhost:8000/sessions/ses_demo/message -H 'content-type: application/json' \
  -d '{"text":"stuck","problem_id":"two-sum","code":""}'
```
