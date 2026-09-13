"""Independent geometry controls; actual OCCT, no Revit execution.

The bundle is an inert assertion carrier. These tests distinguish measured
native geometry from saved claims and preserve placement across recipe edits.
"""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from kir.occt_geometry import GeometryBundle, GeometryRefusal, capture_body
from kir.project import RecipePin, _hash


def _capture(shape, **changes):
    options = dict(project_id="adversarial", instance_key="body", output_key="solid",
                   recipe=RecipePin("pass", "a" * 64), parameters={})
    options.update(changes)
    return capture_body(shape, **options)


def test_parameter_only_podium_edit_does_not_reset_a_valid_placement():
    pytest.importorskip("OCP")
    from examples.curved_podium import initial, change, recipe_pin, _instance

    project, original = initial()
    frame = (0., -1., 0., 100000., 1., 0., 0., -50000.,
             0., 0., 1., 2000., 0., 0., 0., 1.)
    data = original.to_dict()["manifest"]
    placed = capture_body(
        original.read_body(), **{key: data["binding"][key]
                               for key in ("project_id", "instance_key", "output_key")},
        recipe=recipe_pin(), parameters=data["parameters"], frame=frame)
    project = project.replace_instance(_instance(placed), expected_revision=project.revision_id)
    before = project.dumps(), placed.dumps()
    updated_project, updated = change(project, placed, atrium_radius_mm=3500.)
    assert updated.to_dict()["manifest"]["frame"] == list(frame)
    assert updated.op_id == placed.op_id
    assert updated_project.parent_revision == project.revision_id
    assert updated.to_dict()["manifest"]["source_lineage"] == [placed.digest]
    assert (project.dumps(), placed.dumps()) == before


def test_saved_measurements_are_not_used_as_recomputed_native_facts():
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox

    bundle = _capture(BRepPrimAPI_MakeBox(1000., 2000., 3000.).Shape())
    data = bundle.to_dict()
    data["manifest"]["measurements"]["volume_mm3"] = 1.
    data["bundle_sha256"] = _hash({k: v for k, v in data.items() if k != "bundle_sha256"})
    asserted = GeometryBundle(data)
    assert asserted.to_dict()["manifest"]["measurements"]["volume_mm3"] == 1.
    assert asserted.measure()["volume_mm3"] == pytest.approx(6e9, rel=1e-12)


def test_an_open_shell_wrapped_in_a_solid_type_is_not_an_accepted_body():
    pytest.importorskip("OCP")
    from OCP.BRep import BRep_Builder
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Shell, TopoDS_Solid

    source = BRepPrimAPI_MakeBox(1000., 2000., 3000.).Shape()
    explorer = TopExp_Explorer(source, TopAbs_FACE)
    explorer.Next()  # Omit one whole face, not just one triangle.
    builder, shell, solid = BRep_Builder(), TopoDS_Shell(), TopoDS_Solid()
    builder.MakeShell(shell)
    while explorer.More():
        builder.Add(shell, explorer.Current())
        explorer.Next()
    builder.MakeSolid(solid)
    builder.Add(solid, shell)
    with pytest.raises(GeometryRefusal, match="invalid_body"):
        _capture(solid)


def test_current_source_change_refuses_before_invoking_native_generation(monkeypatch):
    pytest.importorskip("OCP")
    from examples import curved_podium

    project, bundle = curved_podium.initial()
    before = project.dumps(), bundle.dumps()
    changed_pin = replace(curved_podium.recipe_pin(), source="pass  # changed recipe")
    monkeypatch.setattr(curved_podium, "recipe_pin", lambda: changed_pin)
    def must_not_generate(_parameters):
        raise AssertionError("source mismatch must be refused before generation")
    monkeypatch.setattr(curved_podium, "build_body", must_not_generate)
    with pytest.raises(GeometryRefusal, match="recipe_changed"):
        curved_podium.change(project, bundle, atrium_radius_mm=3500.)
    assert (project.dumps(), bundle.dumps()) == before


def test_persisted_project_and_body_can_be_explicitly_edited_in_a_fresh_process():
    pytest.importorskip("OCP")
    from examples.curved_podium import initial

    project, bundle = initial()
    root = Path(__file__).resolve().parents[2]
    code = """
import json, sys
from examples.curved_podium import change
from kir.occt_geometry import GeometryBundle
from kir.project import ProjectRevision
artifact = json.load(sys.stdin)
project = ProjectRevision.from_dict(artifact['project'])
bundle = GeometryBundle(artifact['bundle'])
updated_project, updated = change(project, bundle, atrium_radius_mm=3500.)
print(json.dumps({'parent': updated_project.parent_revision,
                  'body': updated.body_digest, 'op_id': updated.op_id,
                  'lineage': updated.to_dict()['manifest']['source_lineage'],
                  'planned_ops': len(updated_project.plan().to_ops())}))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        input=json.dumps({"project": project.to_dict(), "bundle": bundle.to_dict()}),
        text=True, capture_output=True, cwd=root, timeout=40,
        env=dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1"))
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["parent"] == project.revision_id
    assert observed["body"] != bundle.body_digest
    assert observed["op_id"] == bundle.op_id
    assert observed["lineage"] == [bundle.digest]
    assert observed["planned_ops"] == 1
