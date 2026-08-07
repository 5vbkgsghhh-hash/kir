from __future__ import annotations

import ast
import os
from pathlib import Path
import subprocess
import sys

from kukai.ai_protocol.contracts import AVAILABLE_TOOL_NAMES
from kukai.ai_protocol.registry import CAPABILITY_REGISTRY


PROJECT_DIR = Path(__file__).resolve().parents[1]
AI_PROTOCOL_DIR = PROJECT_DIR.parent


def test_project_kernel_has_no_runtime_server_browser_revit_or_ir_imports() -> None:
    forbidden = (
        "fastapi",
        "kukai.bridge",
        "kukai.ir",
        "kukai.runtime",
        "kukai.server",
        "revit",
    )
    for path in sorted(PROJECT_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                imported.append(node.module or "")
        assert not {
            name
            for name in imported
            if any(name == item or name.startswith(item + ".")
                   for item in forbidden)
        }, path


def test_ap01_does_not_import_or_expose_project_kernel() -> None:
    before = CAPABILITY_REGISTRY.registry_digest
    parent_files = tuple(
        path for path in AI_PROTOCOL_DIR.glob("*.py") if path.is_file())
    for path in parent_files:
        assert "project_v0" not in path.read_text(encoding="utf-8")
    assert AVAILABLE_TOOL_NAMES == ("capabilities.get",)
    assert CAPABILITY_REGISTRY.registry_digest == before


def test_patch_result_and_state_digest_are_hash_seed_deterministic() -> None:
    script = r'''
from kukai.ai_protocol.project_v0 import (
    ProjectReadCommandV0, RootPutV0, SourcePatchCommandV0,
    create_project_state, project_read, source_patch,
)
from kukai.design_source import RootInstanceV0
from kukai.design_source.examples import make_tower_source
state = create_project_state(make_tower_source(n_floors=3))
read = project_read(state, ProjectReadCommandV0(
    project_id=state.project_id,
    revision_digest=state.head.revision_digest,
    scope="root_instance",
))
args = dict(read.state.head.root.arguments.items())
args["floor_width"] = 31000
root = RootInstanceV0(
    read.state.head.root.instance_id,
    read.state.head.root.module_id,
    args,
)
result = source_patch(read.state, SourcePatchCommandV0(
    project_id=read.state.project_id,
    base_revision_digest=read.state.head.revision_digest,
    patch_id="patch_seed",
    receipt_refs=(read.result.receipt.ref,),
    operations=(RootPutV0("root", root),),
))
print(result.result.transition_digest)
print(result.state.state_digest)
'''
    outputs = []
    backend_dir = str(PROJECT_DIR.parents[2])
    for seed in ("1", "777"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        environment["PYTHONPATH"] = backend_dir
        completed = subprocess.run(
            [sys.executable, "-c", script],
            check=True,
            capture_output=True,
            text=True,
            env=environment,
            cwd=backend_dir,
        )
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]
