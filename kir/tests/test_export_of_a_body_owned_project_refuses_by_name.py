"""AB-F3: `kir project export` on a body-owned project answers, never crashes.

Audit `.work/audit-fable-20260906/FINAL_AUDIT_RU.md` §4.2, line AB-F3:
"`kir project export` on a body-owned project — a Python traceback". Measured
again 13.09.2026 on the saved complex of `examples/final_result_walkthrough.py`
(5 bodies): rc 1 with an uncaught `GeometryResolutionRequired` traceback from
`kir/project.py:602`, because `to_program()` stood OUTSIDE the guard in
`cmd_project`. A body-owned project is a legitimate project STATE — a recipe
result with real OCCT bodies — not a broken file, so the door owes the reader a
named refusal and the next move.

The positive control is in the same file: a project WITHOUT bodies still
exports, so the refusal is about geometry ownership and not about export being
switched off.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from kir.project import (PROJECT_SCHEMA_V2, BodyRepresentation, ModuleDefinition,
                         ModuleInstance, NamedOutput, ProjectRevision)

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "b" * 64
OTHER = "c" * 64


def _export(path: Path):
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "kir", "project", "export", str(path)],
                          text=True, capture_output=True, cwd=ROOT, env=env, timeout=120)
    return done


def _plain_project():
    return ProjectRevision("ab-f3", [ModuleDefinition("m")], [ModuleInstance(
        "section-a", "m", {"level": {"op": "create_level", "name": "Base", "elev_mm": 0}})])


def _body_owned_project():
    """One output owned by a body: exactly what a recipe result looks like."""
    body = NamedOutput("shell", {"op": "create_directshape", "category": "mass",
                                 "name": "Башня: оболочка"},
                       BodyRepresentation(DIGEST, OTHER))
    # Bodies require the explicit /2 schema (`kir/project.py:455-457`): that
    # upgrade is the author's deliberate act, not a silent migration.
    return ProjectRevision("ab-f3-bodies", [ModuleDefinition("m")], [ModuleInstance(
        "tower-c", "m", (body,))], schema=PROJECT_SCHEMA_V2)


def test_a_body_owned_project_is_refused_by_name_and_not_by_traceback(tmp_path):
    path = tmp_path / "bodies.json"
    project = _body_owned_project()
    assert len(project.geometry_references()) == 1
    path.write_text(project.dumps(), encoding="utf-8")

    done = _export(path)
    assert done.returncode == 1, (done.stdout, done.stderr)
    assert "Traceback (most recent call last)" not in done.stderr, done.stderr
    assert "geometry_resolution_required" in done.stderr, done.stderr
    assert "tower-c/shell" in done.stderr, done.stderr
    # A REFUSAL NAMES THE NEXT MOVE: both the way forward and the way to look
    # at the project without exporting it at all.
    assert "materialize_project" in done.stderr, done.stderr
    assert "kir project inspect" in done.stderr, done.stderr
    # Nothing is printed on stdout: a refused export must not look like a
    # program to a shell redirect.
    assert done.stdout == "", done.stdout


def test_control_the_same_project_without_bodies_still_exports(tmp_path):
    path = tmp_path / "plain.json"
    path.write_text(_plain_project().dumps(), encoding="utf-8")
    done = _export(path)
    assert done.returncode == 0, done.stderr
    program = json.loads(done.stdout)
    assert [op["op"] for op in program["ops"]] == ["create_level"]


def test_control_inspect_reads_a_body_owned_project_without_refusing(tmp_path):
    """The next move the refusal names has to actually work."""
    path = tmp_path / "bodies.json"
    path.write_text(_body_owned_project().dumps(), encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-m", "kir", "project", "inspect", str(path)],
                          text=True, capture_output=True, cwd=ROOT, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    summary = json.loads(done.stdout)
    assert summary["instances"] == 1 and summary["outputs"] == 1
    assert summary["semantic_validation"] == "not_run"
