"""HTTP layer. Routes only: validate the request, call the layer below, shape the response.

No business rules live here. A route that needs to decide something calls the
orchestrator (or, in Phase 1, the stubs) and returns what it is given.
"""
