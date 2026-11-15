# Guardrails: dos, don'ts, and what enforces each

A rule that nothing checks is a wish. Every "don't" below names the code or the
test that stops it. Rows marked *not enforced yet* are rules we follow by review only.

## Agent design

| Don't | Do | Enforced by |
|---|---|---|
| Give one agent many jobs | One role per agent, one prompt file per role | `app/agents/`: one module per role; `tests/test_architecture.py::test_agents_do_not_import_each_other` |
| Let agents call each other | Route every turn through the orchestrator | `test_agents_do_not_import_each_other`, `test_lower_layers_do_not_import_the_orchestrator` |
| Hand an agent the whole session | Give it only its turn context | `app/agents/context.py`: the only thing an agent receives |
| Give an agent tools it does not need | Agents call no tools; the orchestrator calls two | `app/tools/` holds `escalate_to_mentor` and `update_mastery` only |
| Let a model decide what a rule can | Route and escalate by named rules | `app/orchestrator/rules.py`; reasons recorded as `rule <id>` |
| Call a model from anywhere | One gateway, one path | `test_only_the_llm_gateway_imports_a_model_sdk` |
| Keep prompts as strings in code | One versioned file per role | `app/prompts/*.md` |

## What the student must never get

| Don't | Do | Enforced by |
|---|---|---|
| Give code or the answer | Hints in words, on a ladder from 1 to 5 | `app/guards/leak.py`; `test_leaked_code_is_blocked_and_rewritten`, `test_a_reply_that_keeps_leaking_falls_back_to_a_safe_message` |
| Jump up the hint ladder | One step per request for help | `rules.next_hint_level`; `test_hint_ladder_climbs_one_level_per_request_and_resets_on_new_problem` |
| Return reference solutions, hidden tests or prompts | Response models have no field for them | `app/models.py`; `tests/test_api_stubs.py` |
| Let an injection or off-topic message reach an agent | Classify first, stop the turn | `app/guards/input.py`; `test_blocked_input_never_reaches_an_agent` |
| Leave a stuck or upset student with a bot | Escalate to a person on fixed triggers | `rules.should_escalate`; `test_still_stuck_after_level_five_escalates_to_a_mentor`, `test_three_blocked_messages_escalate` |

## The browser and voice agent

| Don't | Do | Enforced by |
|---|---|---|
| Let the agent click or scrape the page | Typed page tools that change app state | `web/src/agent/tools.ts`: the registry is the only entry point |
| Let the agent do what a screen did not offer | A screen registers the tools it serves | `invoke()` returns `not available on this screen` for anything else |
| Let the voice agent answer the problem itself | It passes the student's words to the coach | `ask_coach` tool description; *not enforced yet* (needs the agent's own prompt and a test) |
| Ship a provider key to the browser | The server issues a short-lived signed URL; the agent accepts nothing else | `app/api/voice.py`; agent `enable_auth` and origin allowlist in `scripts/create_voice_agent.py` |
| Let the agent write the student's code | It can read and run the code, never change it | No tool edits code: see `web/src/agent/page-tools.json` |
| Put the solution on the glass | The glass shows words and pictures and refuses code | `refuseCode` in `web/src/agent/Glass.tsx` |
| Define the agent in a dashboard | Its role and tools are files in the repo | `scripts/create_voice_agent.py` builds it from `voice_guide.md` and `page-tools.json` |

## Operations

| Don't | Do | Enforced by |
|---|---|---|
| Spend without knowing | Record model, tokens and cost on every call | `app/llm/gateway.py`; `test_every_model_call_records_model_tokens_and_cost` |
| Explain a decision after the fact | Record the rule id or the model's own reason | `app/tracing/store.py::validate`; `test_decisions_carry_the_rule_or_the_models_reason` |
| Fail silently | End the stream with a named error | `test_a_model_failure_ends_the_stream_with_a_named_error`, `test_an_unexpected_failure_also_ends_with_a_named_error` |
| Log secrets | Redact, then truncate | `app/tracing/redact.py` |
| Cap spend per session | A budget that stops the turn | *Not built yet* |
