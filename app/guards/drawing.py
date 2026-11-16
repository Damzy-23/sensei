"""Drawing guard: what the illustrator may put on the glass.

Rule-based, like the leak check: free, instant, and its reason is the rule that fired.
A drawing follows a reply that has already been sent, so there is no rewrite step: one
that breaks a rule is dropped and the student simply gets no picture.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, get_args

from app.guards import leak
from app.models import Drawing, DrawingKind
from app.tracing.context import span

KINDS: tuple[str, ...] = get_args(DrawingKind)
# The sizes the glass can show: web/src/agent/Glass.tsx.
MAX_VALUES = {"array": 16, "bars": 16, "tree": 31, "graph": 31, "steps": 6, "grid": 8}
UNIT = {"grid": "rows", "steps": "steps"}  # what one value is called; "values" for the rest
MAX_GRID_COLUMNS = 12
MAX_CAPTION = 160
MAX_TITLE = 60
MAX_STEP = 140  # characters in one step
MAX_LABEL = 16  # characters in one cell, node or pointer label
MAX_GRID_CELL = 3

_FORMATS = {
    "pointers": re.compile(r"\s*\d+\s*:[^,:]+(,\s*\d+\s*:[^,:]+)*"),
    "water": re.compile(r"\s*\d+\s*-\s*\d+\s*"),
    "highlight": re.compile(r"\s*\d+(\s*:\s*\d+)?\s*(,\s*\d+(\s*:\s*\d+)?\s*)*"),
    "edges": re.compile(r"\s*\d+\s*-\s*\d+\s*(,\s*\d+\s*-\s*\d+\s*)*"),
}
_EXAMPLES = {"pointers": "0:left,4:right", "water": "2-5", "highlight": "2,3 or 0:1", "edges": "0-1,1-2"}
_GRID_SPLIT = re.compile(r"[\s,]+")


@dataclass(frozen=True)
class DrawingDecision:
    drawing: Drawing | None  # None when blocked
    rule: str
    detail: str

    @property
    def reason(self) -> str:
        return f"rule {self.rule}: {self.detail}"


def _blocked(rule: str, detail: str) -> DrawingDecision:
    return DrawingDecision(None, rule, detail)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _mentions(text: str, pattern: str) -> bool:
    """True when the text names the pattern (case and plural insensitive), for example "hash map" or "two pointers"."""
    words = [w for w in re.split(r"[\s_-]+", pattern.lower()) if w]
    if not words:
        return False
    body = r"[\s_-]*".join(re.escape(w.rstrip("s")) + "s?" for w in words)
    return re.search(rf"\b{body}\b", text.lower()) is not None


def decide(raw: Any, hint_level: int | None = None, pattern: str = "") -> DrawingDecision:  # noqa: C901
    """The rules themselves, without a trace span. `check` wraps them for a drawing on its way out.

    With a hint level, a drawing may not show more than that rung of the ladder allows
    (app/prompts/hint_coach.md): below 2 it may not name the pattern; below 4 it shows the
    input only, so no two pointers, no water and no plan of more than two steps.
    """
    if not isinstance(raw, dict):
        return _blocked("drawing.shape", "the drawing is not a JSON object")
    kind = raw.get("kind")
    if kind not in KINDS:
        return _blocked("drawing.kind", f"kind must be one of {', '.join(KINDS)}")

    values = raw.get("values")
    if not isinstance(values, list) or not values:
        return _blocked("drawing.shape", "values must be a non-empty list")
    cells: list[str] = []
    for value in values:
        if value is None and kind == "tree":
            cells.append("null")  # a gap in level order
        elif isinstance(value, bool) or not isinstance(value, (str, int, float)):
            return _blocked("drawing.shape", "every value must be a string or a number")
        else:
            cells.append(str(value).strip())

    texts: dict[str, str] = {}
    for name in ("pointers", "water", "highlight", "edges", "title", "caption"):
        text = raw.get(name)
        if text is not None and not isinstance(text, str):
            return _blocked("drawing.shape", f"{name} must be a string")
        texts[name] = (text or "").strip()

    unit = UNIT.get(kind, "values")
    if len(cells) > MAX_VALUES[kind]:
        return _blocked("drawing.size", f"{kind} takes at most {MAX_VALUES[kind]} {unit}, got {len(cells)}")
    if kind == "grid":
        rows = [[c for c in _GRID_SPLIT.split(row) if c] for row in cells]
        if any(len(row) > MAX_GRID_COLUMNS for row in rows):
            return _blocked("drawing.size", f"a grid row takes at most {MAX_GRID_COLUMNS} cells")
        if any(len(c) > MAX_GRID_CELL for row in rows for c in row):
            return _blocked("drawing.size", f"a grid cell takes at most {MAX_GRID_CELL} characters")
    elif any(len(cell) > (MAX_STEP if kind == "steps" else MAX_LABEL) for cell in cells):
        longest = MAX_STEP if kind == "steps" else MAX_LABEL
        return _blocked("drawing.size", f"one of the {unit} is longer than {longest} characters")
    if len(texts["caption"]) > MAX_CAPTION:
        return _blocked("drawing.size", f"the caption takes at most {MAX_CAPTION} characters, got {len(texts['caption'])}")
    if len(texts["title"]) > MAX_TITLE:
        return _blocked("drawing.size", f"the title takes at most {MAX_TITLE} characters")
    if kind == "bars" and not all(_is_number(cell) for cell in cells):
        return _blocked("drawing.shape", "bars are heights: every value must be a number")

    for name, form in _FORMATS.items():
        if texts[name] and not form.fullmatch(texts[name]):
            return _blocked("drawing.format", f"{name} must look like {_EXAMPLES[name]}")
    labels = [part.split(":", 1)[1].strip() for part in texts["pointers"].split(",") if ":" in part]
    if any(len(label) > MAX_LABEL for label in labels):
        return _blocked("drawing.size", f"a pointer label takes at most {MAX_LABEL} characters")
    if len(labels) > max(2, len(cells)):
        return _blocked("drawing.size", f"at most {max(2, len(cells))} pointer labels on {len(cells)} {unit}")

    # The glass shows words and pictures. Code on it would walk around the coach's leak check.
    # Each piece is checked, and so are the pieces read together, so a line of code cannot be
    # split across cells or pointer labels.
    joined = [] if kind in ("steps", "grid") else [
        ("values", " ".join(cells)), ("values", "".join(cells)), ("pointers", " ".join(labels)), ("pointers", "".join(labels)),
    ]
    for where, text in [("values", c) for c in cells] + [("pointers", p) for p in labels] + joined + [
        ("title", texts["title"]), ("caption", texts["caption"]),
    ]:
        if leak.is_code(text):
            return _blocked("drawing.code", f"code in the {where}")

    # Not more than the hint level allows (mirrors the ladder in app/prompts/hint_coach.md).
    if hint_level is not None:
        words = [texts["title"], texts["caption"], *labels] + (cells if kind in ("steps", "array") else [])
        if hint_level < 2 and pattern and any(_mentions(t, pattern) for t in words):
            return _blocked("drawing.level", f"names the pattern ({pattern}) before hint level 2")
        # Below level 4 the picture is trimmed rather than dropped, so the student still gets one:
        # pointers and water stay only at the two ends (the starting state, not an answer), and a
        # plan keeps its first two steps (restating the goal), not the way to solve it.
        if hint_level < 4:
            trimmed = []
            if kind == "steps" and len(cells) > 2:
                cells = cells[:2]
                trimmed.append("plan cut to two steps")
            if kind == "bars":
                ends = {0, len(cells) - 1}
                pairs = [(int(p.split(":", 1)[0]), p.split(":", 1)[1].strip()) for p in texts["pointers"].split(",") if ":" in p]
                kept = [(i, name) for i, name in pairs if i in ends]
                if len(kept) != len(pairs):
                    texts["pointers"] = ",".join(f"{i}:{name}" for i, name in kept)
                    trimmed.append("pointers kept only at the ends")
                if texts["water"] and {int(x) for x in texts["water"].split("-")} != ends:
                    texts["water"] = ""
                    trimmed.append("water removed")
            if trimmed:
                return DrawingDecision(
                    Drawing(kind=kind, values=cells, **texts), "drawing.level_trimmed",
                    f"hint level {hint_level}: " + ", ".join(trimmed),
                )

    return DrawingDecision(
        Drawing(kind=kind, values=cells, **texts), "drawing.ok", f"{kind} with {len(cells)} {unit}, within the glass limits, no code"
    )


def check(raw: Any, hint_level: int | None = None, pattern: str = "") -> Drawing | None:
    """Return the drawing if it may go on the glass. A blocked one is on the trace with its rule."""
    shown = json.dumps(raw, ensure_ascii=False, default=str) if isinstance(raw, (dict, list)) else str(raw)
    with span("guard", "guard.output", "drawing_check", shown) as st:
        decision = decide(raw, hint_level, pattern)
        blocked = decision.drawing is None
        st.decision = "blocked" if blocked else "pass"
        st.reason = decision.reason
        st.status = "blocked" if blocked else "ok"
        return decision.drawing
