"""Building block: Role-playing (the role definitions themselves).

One versioned Markdown file per agent and guard, loaded at runtime. Prompts are
files in the repository rather than strings in code, so a change to a role shows
up in review and can be tied to an eval run.

Prompts are never returned by any endpoint.
"""
