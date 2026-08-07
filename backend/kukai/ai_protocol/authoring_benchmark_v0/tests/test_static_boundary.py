from __future__ import annotations

import ast
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
PRODUCTION = tuple(
    path for path in PACKAGE.glob("*.py") if path.name != "__init__.py"
)


def _imports(path: Path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def test_no_network_revit_runtime_or_process_dependencies() -> None:
    forbidden = (
        "requests", "httpx", "socket", "urllib", "subprocess", "threading",
        "clr", "Autodesk", "revit", "runtime", "compiler",
    )
    for path in PRODUCTION:
        imports = tuple(_imports(path))
        assert not any(
            name == item or name.startswith(item + ".")
            for name in imports for item in forbidden
        ), (path, imports)


def test_project_loop_imports_only_public_nested_wire_host() -> None:
    for filename in ("harness.py", "verifier.py"):
        imports = tuple(_imports(PACKAGE / filename))
        project_imports = tuple(
            name for name in imports if "ai_protocol.project_v0" in name)
        assert project_imports == ("kukai.ai_protocol.project_v0.wire_v0",)
    source = (PACKAGE / "harness.py").read_text()
    tree = ast.parse(source)
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "state"
        for node in ast.walk(tree)
    )
    assert "handle_wire_request" in source
    assert "state_digest" in source


def test_no_private_ap02_or_registration_symbols() -> None:
    source = "\n".join(path.read_text() for path in PRODUCTION)
    for forbidden in (
        "project_v0.state", "project_v0.session", "wire_v0.session",
        "create_project_state", "source_patch(", "register_tool",
        "runtime.register", "AI_BENCHMARK_PASS\"",
    ):
        assert forbidden not in source
