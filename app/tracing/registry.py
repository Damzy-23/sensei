"""Tool registry and the @tool decorator.

Every function in app/tools/ is decorated with @tool(actor, name). The decorator
wraps the call in a span, so each tool and each model call is logged with the
name the frontend shows in the agent inspector. A test fails if a public function
in app/tools/ is missing from the registry.
"""

from __future__ import annotations

import functools
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from app.models import Actor, EventType
from app.tracing.context import span

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class ToolSpec:
    actor: Actor
    name: str
    event_type: EventType
    module: str
    qualname: str


class Registry:
    def __init__(self) -> None:
        self._specs: list[ToolSpec] = []

    def add(self, spec: ToolSpec) -> None:
        for existing in self._specs:
            if (existing.actor, existing.name) == (spec.actor, spec.name):
                raise ValueError(f"duplicate tool name: {spec.actor}.{spec.name}")
            if (existing.module, existing.qualname) == (spec.module, spec.qualname):
                raise ValueError(f"function registered twice: {spec.module}.{spec.qualname}")
        self._specs.append(spec)

    def all(self) -> list[ToolSpec]:
        return list(self._specs)

    def has_function(self, module: str, qualname: str) -> bool:
        return any(s.module == module and s.qualname == qualname for s in self._specs)

    def by_name(self, actor: str, name: str) -> ToolSpec | None:
        for s in self._specs:
            if s.actor == actor and s.name == name:
                return s
        return None


REGISTRY = Registry()


def _fmt(value: Any) -> str:
    if isinstance(value, str):
        return value
    if hasattr(value, "model_dump_json"):
        return value.model_dump_json()
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return repr(value)


def _fmt_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = [_fmt(a) for a in args] + [f"{k}={_fmt(v)}" for k, v in kwargs.items()]
    return ", ".join(parts)


def tool(actor: Actor, name: str, event_type: EventType = "tool.call") -> Callable[[F], F]:
    """Register a function as a traced tool. Works for sync and async functions."""

    def decorate(fn: F) -> F:
        REGISTRY.add(
            ToolSpec(
                actor=actor,
                name=name,
                event_type=event_type,
                module=fn.__module__,
                qualname=fn.__qualname__,
            )
        )

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with span(actor, event_type, name, input_text=_fmt_args(args, kwargs)) as st:
                    result = await fn(*args, **kwargs)
                    if st.output is None:
                        st.output = _fmt(result)
                return result

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            with span(actor, event_type, name, input_text=_fmt_args(args, kwargs)) as st:
                result = fn(*args, **kwargs)
                if st.output is None:
                    st.output = _fmt(result)
            return result

        return sync_wrapper  # type: ignore[return-value]

    return decorate
