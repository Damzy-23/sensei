# Decisions

Defaults chosen while building the backend, and where the build departs from the spec. Each
entry says what was chosen and why. Change a value in `config/*.yaml` where one exists; otherwise
change the code and the test that pins it.

## Scope and trust

- **Browser test results are trusted** (hackathon scope). `POST /runs` takes pass and fail counts
  from the browser runner. The server does not re-run the student's code.
- **Reference solutions and hidden tests never leave the server.** Response models have no field
  for them, `app/bank.py` splits public and internal accessors, and tests check the API output
  for their text.
- **No accounts.** Mastery, sessions and tickets are per session, not per student.
- **No agent framework.** The orchestrator is a hand-written pipeline in `app/orchestrator/pipeline.py`.

## Problem bank

- **Hand-written, not generated.** `scripts/build_problems.py` writes `data/problems.json` from
  Python definitions. The reasoning model was not used, because no API key was available at build
  time. `scripts/validate_bank.py` runs each reference against all its tests in a subprocess with a
  10-second timeout, and fails loudly on any mismatch. It was checked against a planted wrong
  answer, which it caught.
- **12 problems**, two per pattern family where possible: two pointers, sliding window, hash map,
  stack, binary search, intervals, BFS/DFS, dynamic programming, heap.
- **Hint seeds are internal.** Level 5 is a pseudocode skeleton of at most 12 lines.

## Tracing

- **One event per span**, emitted when the span finishes. `turn()` emits `turn.start` on entry
  and `turn.end` on exit. The trace tree shows the last event per span, so a turn's root carries
  its final status and latency.
- **Actor list extended with `escalation`.** The spec lists the escalation tools under their own
  group, but the actor enum omitted it. Those tools log as `actor=escalation`.
- **`seq` is per trace**, not per session. Ordering across turns comes from `ts` and insertion
  order.
- **Guard and mode events require `decision` and `reason`** (`guard.input`, `guard.output`,
  `mode.decision`). Errors fill both automatically. A model call made inside a guard is an
  `llm.call` and needs neither.
- **Truncation to 500 characters** keeps the first 497 and appends `...`. Redaction runs first,
  so a secret cut in half cannot leak. Keys are redacted by pattern (`sk-ant-…`, `sk-…`, and
  `api_key`/`token`/`secret`/`password` assignments) and by the literal value of the env keys.
- **Cost from `config/prices.yaml`.** Its values are placeholders. Check them before quoting cost
  figures in the demo. An unknown model logs `cost_usd = null`.

## Model client

- **30 s timeout per attempt, two retries** with backoff, on timeouts, connection errors, 429 and
  5xx. Other 4xx errors are not retried.
- **One JSON repair attempt** when a schema is requested. The repair asks for JSON only.
- **Missing key or endpoint raises `LLMError`**, so callers degrade rather than crash.
- **Both providers are plain functions** in `PROVIDERS`, so tests substitute fakes without
  touching the network.

## Guards

- **Input classifier fails open; injection rules still block.** If the fast model is unavailable,
  `classify_input` uses the regex result alone and logs that it did. A regex injection hit blocks
  without any model call.
- **Frustration is flagged, not blocked.** It counts toward escalation (2 flags).
- **Answer requests and off-topic messages are redirected.** The redirect text explains the ladder.
  The hint is not refused outright.
- **Output checks run on every coach reply**: `policy_check` (60 words, non-empty, level matches
  the unlock), then `leak_check` (static rules, token coverage against the reference, then the
  judge). The first failure triggers one stricter regeneration. A second failure returns the
  canned hint for the level and logs the blocked original as a `canned_fallback` span.
- **Similarity is token coverage**, not a fuzzy ratio: the fraction of the reference's tokens that
  appear, in order, in the reply's code. The threshold is 0.80. Comments and whitespace are
  ignored.
- **The judge fails closed.** If the judge errors or returns unreadable output, the reply is
  blocked.
- **Code before level 5 is blocked.** At level 5, a skeleton longer than 12 lines is blocked.

## Hint ladder and modes

- **Unlock rule:** a level is granted only when asked AND (a failed run since the last unlock OR
  120 seconds since the last unlock, or since the problem started if there has been no unlock).
  Levels move one at a time and stop at 5.
- **Modes** (`config/policy.yaml`): Learn after 3 consecutive failed runs or hint level 3. Learn
  becomes Interview after a solve with at most 1 hint and mastery at least 0.6. Interview becomes
  Blitz after 3 solves in a row under 600 seconds. Blitz shows a 900-second countdown, which
  counts down from the problem start.
- **Each mode decision logs** the signals it read and the rule that fired.
- **Mastery** is stored on [0, 1] with an Elo-style update: `new = old + 0.2 × (outcome − expected)`,
  where expected uses an anchor of 0.4, 0.6 or 0.8 for easy, medium or hard. A solve gives 1.0 and
  an abandon 0.0. Abandons are not wired up yet.

## Escalation

- **Triggers:** still failing at hint level 5, 3 guard violations, or frustration flagged twice.
- **Resolving the last open ticket** clears the escalated flag and resets the violation and
  frustration counts. Otherwise the next message escalates again on the same counts. The scripted
  student found this bug.
- **Ticket intervention** comes from the reasoning model. If that fails, the ticket still opens
  with a default intervention, and the fallback is logged.
- **Mentor endpoints use the state repository directly** for reads, writes and resolve, and the
  `relay_mentor_message` tool for the reply. Mentor actions are not model calls or guard checks.

## Streaming and endpoints

- **`POST /message` streams live.** The trace events for the session are pushed as they happen,
  then `final`. The stream is session-scoped, so two turns in one session at once would interleave.
- **`GET /sessions/{id}/events`** replays stored events. `follow=true` (the default) then streams
  live. `follow=false` ends after the replay, which tests and the simulator use.
- **`POST /runs` opens its own trace** (`name=runs`), with `run_tests` logged as `source=client`.
- **`hint_level_available`** is the next level the student could unlock, or 0 if the run solved
  the problem.

## Eval and training data

- **Held-out problems:** `container-most-water` (two pointers), `number-of-islands` (BFS/DFS) and
  `coin-change` (dynamic programming). One from each of three different patterns.
- **Data target:** nine training problems × 5 attempts × 5 levels × 2 variants gives at most
  450 rows. The spec asked for 400+, which depends on how many hints pass the filters. The run
  reports the count.
- **Judging:** the A/B order is random, seeded by `--seed`, so a run can be reproduced. A leaked
  hint loses without being judged, and two leaks tie. Ties count as half a win.
- **Reporting:** the Markdown states plainly when the tuned model does not beat base.
- **`HINT_MODEL=tuned` falls back to base** if the tuned endpoint is not configured, and logs it.
  The eval never falls back. It fails loudly, so a result is never labelled tuned when it was not.

## Adaption

- **Built from the SDK, not run.** `docs/adaption.md` was written from the `adaption` SDK 0.19.0
  and the public docs, because the spec's file was missing. The pipeline is raw upload with an
  explicit prompt/completion mapping, then an AutoScientist run, then download. Tests use a fake
  client. Nothing has been uploaded: there is no `ADAPTION_API_KEY` in this environment yet.
- **No leaderboard step.** The SDK has no leaderboard call, and `datasets.publish` returns 501. The
  run record says `not submitted`. The organisers or Adaption support must confirm the process.
- **Hosting is open.** The downloaded artifact must be served on an OpenAI-compatible endpoint
  before it can be `hint_tuned`. The docs don't say how.

## Demo

- **`DEMO_MODE=1`** caches successful model replies on disk. A failed call with a cached request
  is replayed, logged to the console, and recorded as a `DEMO_MODE replay` span. An uncached
  request still fails.
- **`data/demo/recording.json` was recorded with a scripted model**, because no key was available.
  Its `note` field says so. The guards, modes, escalation and traces in it are the real code. The
  coach's wording is placeholder text. Re-record with a real key before the demo.
- **Problems that need a real model to judge** (hint quality, the leak judge, complexity analysis)
  are untested against live output. Their fake-model tests check the wiring and the fail-safe
  paths, not the content.

## Git

- **Four commits per phase**, authored only by the project owner, with no co-author trailers.
  Commits are local until pushing works: a credential prompt on this machine blocks `git push`.
