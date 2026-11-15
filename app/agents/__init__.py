"""Building block: Role-playing and Focus.

One module per specialist: interviewer, hint_coach, evaluator, planner. Each one
declares its role (a prompt file in app/prompts/), the tools it may use, and the
model key it runs on. It receives only the context its job needs.

Rules:
- An agent never imports another agent. Cooperation goes through app.orchestrator.
- An agent never calls a model SDK. Every model call goes through app.llm.
- An agent returns a result to the orchestrator; it does not write the reply to
  the student itself.
"""
