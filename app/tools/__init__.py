"""Tool modules. Importing this package registers every tool with REGISTRY.

Inventory (actor.name): client.run_tests; guard.{classify_input, regex_precheck,
leak_check, policy_check}; orchestrator.{read_state, write_state, select_mode,
route_agent, create_escalation}; interviewer.{get_problem, llm_followup, record_answer};
hint_coach.{get_hint_level, unlock_hint, llm_hint}; evaluator.{read_run_result,
analyze_complexity, static_check}; planner.{get_mastery, update_mastery,
query_problem_bank, select_next_problem}; escalation.{create_ticket, notify_mentor,
relay_mentor_message}.
"""

from app.tools import (  # noqa: F401  (import for registration side effect)
    client,
    escalation,
    evaluator,
    guard,
    hint_coach,
    interviewer,
    orchestrator,
    planner,
)
