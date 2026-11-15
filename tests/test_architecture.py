"""Architecture fitness tests: the layering rules in docs/ARCHITECTURE.md, enforced.

These read import statements with `ast`, so they check the code as written
without importing it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parent.parent / "app"

MODEL_SDKS = {"anthropic", "openai"}


def _modules(package: str | None = None) -> list[Path]:
    root = APP / package if package else APP
    return sorted(root.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found |= {f"{node.module}.{alias.name}" for alias in node.names}
    return found


def _package_of(path: Path) -> str:
    rel = path.relative_to(APP)
    return rel.parts[0] if len(rel.parts) > 1 else rel.stem


def test_there_are_modules_to_check() -> None:
    # Guards against the rest of this file passing because it found nothing.
    assert len(_modules()) >= 20


def test_only_the_llm_gateway_imports_a_model_sdk() -> None:
    offenders = [
        str(p.relative_to(APP))
        for p in _modules()
        if _package_of(p) != "llm"
        and any(name.split(".")[0] in MODEL_SDKS for name in _imports(p))
    ]
    assert offenders == [], f"model SDK imported outside app/llm: {offenders}"


def test_nothing_imports_the_http_layer() -> None:
    offenders = [
        str(p.relative_to(APP))
        for p in _modules()
        if _package_of(p) not in {"api", "main"}
        and any(name == "app.main" or name.startswith("app.api") for name in _imports(p))
    ]
    assert offenders == [], f"lower layer imports app.api or app.main: {offenders}"


@pytest.mark.parametrize("package", ["agents", "tools", "guards", "memory", "llm", "tracing", "prompts"])
def test_lower_layers_do_not_import_the_orchestrator(package: str) -> None:
    offenders = [
        str(p.relative_to(APP))
        for p in _modules(package)
        if any(name.startswith("app.orchestrator") for name in _imports(p))
    ]
    assert offenders == [], f"{package} imports the orchestrator: {offenders}"


def test_agents_do_not_import_each_other() -> None:
    offenders = []
    for path in _modules("agents"):
        own = f"app.agents.{path.stem}"
        for name in _imports(path):
            if name.startswith("app.agents.") and not name.startswith(own):
                offenders.append(f"{path.relative_to(APP)} -> {name}")
    assert offenders == [], f"agents must cooperate through the orchestrator: {offenders}"
