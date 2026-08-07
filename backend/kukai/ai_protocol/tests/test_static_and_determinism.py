from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys


BACKEND = Path(__file__).resolve().parents[3]
REPOSITORY = BACKEND.parent
PACKAGE = BACKEND / "kukai" / "ai_protocol"
PRODUCTION_FILES = tuple(sorted(
    path for path in PACKAGE.glob("*.py") if path.name != "tests"))
_AI_PROTOCOL_TARGET = ("kukai", "ai_protocol")
_REGISTRATION_CALLS = frozenset({
    "add_api_route",
    "add_route",
    "add_websocket_route",
    "include_router",
    "mount",
    "route",
    "websocket",
})


def _imports_ai_protocol(source: str, package: tuple[str, ...]) -> bool:
    tree = ast.parse(source)

    def is_target(parts: tuple[str, ...]) -> bool:
        return parts[:len(_AI_PROTOCOL_TARGET)] == _AI_PROTOCOL_TARGET

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                is_target(tuple(alias.name.split(".")))
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package) - (node.level - 1)
                base = package[:max(0, keep)]
            else:
                base = ()
            if node.module:
                base = (*base, *node.module.split("."))
            if is_target(base):
                return True
            if any(
                is_target((*base, *alias.name.split(".")))
                for alias in node.names
            ):
                return True
    return False


def _registers_ai_protocol(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function_name = (
            node.func.attr if isinstance(node.func, ast.Attribute) else None)
        if function_name not in _REGISTRATION_CALLS:
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id == "ai_protocol":
                return True
            if (
                isinstance(child, ast.Attribute)
                and child.attr == "ai_protocol"
            ):
                return True
            if (
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and "ai_protocol" in child.value
            ):
                return True
    return False


def _environment(seed: str = "1") -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONHASHSEED"] = seed
    environment["PYTHONPATH"] = str(BACKEND)
    return environment


def _run(script: str, *, seed: str = "1") -> str:
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPOSITORY,
        env=_environment(seed),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_cross_process_registry_schema_request_response_bytes_are_stable() -> None:
    script = r'''
import json
from kukai.ai_protocol.registry import CAPABILITY_REGISTRY
from kukai.ai_protocol.wire import decode_request, handle_request, encode_response

request = decode_request(
    b'{"protocol":"kir-ai/0","request_id":"request_1","tool":"capabilities.get","arguments":{}}'
)
response = handle_request(request)
print(json.dumps({
    "registry_digest": CAPABILITY_REGISTRY.registry_digest,
    "schema_digests": [item.schema_digest for item in CAPABILITY_REGISTRY.schemas],
    "request_digest": request.request_digest,
    "response_digest": response.response_digest,
    "response_bytes": encode_response(response).hex(),
}, sort_keys=True, separators=(",", ":")))
'''

    assert _run(script, seed="1") == _run(script, seed="99991")


def test_clean_import_loads_no_serving_modeling_or_revit_path() -> None:
    script = r'''
import sys
before = set(sys.modules)
import kukai.ai_protocol
loaded = set(sys.modules) - before
forbidden = (
    "kukai.api",
    "kukai.live",
    "kukai.ir",
    "kukai.llm",
    "kukai.modeling",
    "fastapi",
    "uvicorn",
    "litellm",
    "httpx",
    "requests",
    "socket",
    "subprocess",
)
bad = sorted(name for name in loaded if name.startswith(forbidden))
if bad:
    raise SystemExit("forbidden imports: " + repr(bad))
print("clean")
'''

    assert _run(script) == "clean"


def test_production_import_graph_is_closed_and_offline() -> None:
    allowed_absolute = {
        "__future__",
        "collections.abc",
        "dataclasses",
        "re",
        "typing",
        "kukai.design_source.canonical",
    }
    allowed_relative = {"contracts", "errors", "registry", "wire"}

    for path in PRODUCTION_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name in allowed_absolute, (path, alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level:
                    assert module in allowed_relative, (path, module)
                else:
                    assert module in allowed_absolute, (path, module)


def test_production_has_no_io_network_clock_process_or_dynamic_code_calls() -> None:
    forbidden_names = {
        "open",
        "exec",
        "eval",
        "compile",
        "__import__",
        "breakpoint",
    }
    forbidden_attributes = {
        "system",
        "popen",
        "run",
        "Popen",
        "socket",
        "urlopen",
        "request",
        "sleep",
        "now",
        "utcnow",
    }

    for path in PRODUCTION_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_names, (path, node.lineno)
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_attributes, (
                    path, node.lineno, node.func.attr)


def test_no_existing_production_module_imports_or_registers_ap01() -> None:
    offenders: list[Path] = []
    for path in (BACKEND / "kukai").rglob("*.py"):
        if PACKAGE in path.parents or "tests" in path.parts:
            continue
        relative = path.relative_to(BACKEND).with_suffix("")
        module_parts = relative.parts
        package_parts = module_parts[:-1]
        source = path.read_text(encoding="utf-8")
        if (
            _imports_ai_protocol(source, package_parts)
            or _registers_ai_protocol(source)
        ):
            offenders.append(path)

    assert offenders == []


def test_reverse_reachability_probe_detects_alias_relative_and_registration() -> None:
    assert _imports_ai_protocol(
        "import kukai.ai_protocol as protocol", ("kukai", "api"))
    assert _imports_ai_protocol(
        "from kukai import ai_protocol", ("kukai", "api"))
    assert _imports_ai_protocol(
        "from .. import ai_protocol", ("kukai", "api"))
    assert _registers_ai_protocol(
        "app.include_router(ai_protocol.router)")
    assert not _imports_ai_protocol(
        "from kukai import settings", ("kukai", "api"))


def test_no_forbidden_or_invented_surface_names_exist_in_production() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8") for path in PRODUCTION_FILES)

    for token in (
        "package.pin",
        "module.remove",
        "scene.read",
        "FastAPI",
        "APIRouter",
        "WebSocket",
        "Revit",
    ):
        assert token not in text
