"""Actual optional OCCT execution; no Revit, network, service or production venv."""
from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from kir.occt_geometry import (GeometryBundle, GeometryRefusal, IDENTITY_FRAME,
                              MAX_BUNDLE_BYTES, capture_body)
from kir.project import (ModuleDefinition, ModuleInstance, ProjectRevision, RecipePin,
                         _hash)


ROOT = Path(__file__).resolve().parents[2]
PIN = RecipePin("def build(): return 'asserted result, not executed at load'", "a" * 64)


def native():
    return pytest.importorskip("OCP", reason="optional OCCT profile is not installed")


def capture(shape, **changes):
    options = dict(project_id="test", instance_key="body", output_key="shape",
                   recipe=PIN, parameters={"purpose": "analytic control"})
    options.update(changes)
    return capture_body(shape, **options)


@pytest.fixture(scope="module")
def box():
    native()
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    return capture(BRepPrimAPI_MakeBox(1000., 2000., 3000.).Shape())


@pytest.fixture(scope="module")
def podium():
    native()
    from examples.curved_podium import initial
    return initial()


def resign(data):
    data["bundle_sha256"] = _hash({k: v for k, v in data.items() if k != "bundle_sha256"})
    return json.dumps(data)


def fresh(code, source=""):
    return subprocess.run([sys.executable, "-c", code], input=source, text=True,
                          capture_output=True, cwd=ROOT, timeout=40,
                          env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))


def mesh_volume(mesh):
    # Divergence theorem on output triangles, independent of OCCT GProp.
    vertices = mesh["vertices_mm"]
    terms = []
    for i, j, k in mesh["triangles"]:
        a, b, c = vertices[i], vertices[j], vertices[k]
        terms.append((a[0]*(b[1]*c[2]-b[2]*c[1]) + a[1]*(b[2]*c[0]-b[0]*c[2])
                      + a[2]*(b[0]*c[1]-b[1]*c[0])) / 6)
    return math.fsum(terms)


def test_module_import_does_not_import_or_require_ocp():
    result = fresh("""
import importlib.abc, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('optional dependency imported eagerly')
sys.meta_path.insert(0, NoOcp())
import kir.occt_geometry
assert not any(name == 'OCP' or name.startswith('OCP.') for name in sys.modules)
print('inert')
""")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "inert"


def test_box_kernel_and_mesh_match_independent_analytic_quantities(box):
    expected_volume = 1000 * 2000 * 3000
    facts = box.measure()
    assert facts["volume_mm3"] == pytest.approx(expected_volume, rel=1e-12)
    assert facts["area_mm2"] == pytest.approx(2 * (1000*2000 + 1000*3000 + 2000*3000), rel=1e-12)
    assert facts["centroid_mm"] == pytest.approx([500, 1000, 1500])
    assert facts["bbox_min_mm"] == pytest.approx([0, 0, 0], abs=1e-6)
    assert facts["bbox_max_mm"] == pytest.approx([1000, 2000, 3000], abs=1e-6)
    assert mesh_volume(box.to_dict()["preview_mesh"]) == pytest.approx(expected_volume, rel=1e-12)
    assert facts["solid_count"] == 1 and facts["face_count"] == 6


def test_sphere_with_cylindrical_hole_matches_napkin_ring_volume():
    native()
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeCylinder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    radius, hole = 5000., 2000.
    cutter = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, -6000), gp_Dir(0, 0, 1)), hole, 12000).Shape()
    cut = BRepAlgoAPI_Cut(BRepPrimAPI_MakeSphere(radius).Shape(), cutter)
    assert cut.IsDone()
    bundle = capture(cut.Shape(), max_vertices=100_000, max_triangles=100_000)
    expected = 4 * math.pi / 3 * (radius * radius - hole * hole) ** 1.5
    assert bundle.measure()["volume_mm3"] == pytest.approx(expected, rel=1e-8)
    assert mesh_volume(bundle.to_dict()["preview_mesh"]) == pytest.approx(expected, rel=.01)


def test_prism_minus_cylinder_is_not_a_self_confirming_boolean_control():
    native()
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    cutter = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(2000, 2500, -100), gp_Dir(0, 0, 1)), 600, 6200).Shape()
    body = BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(4000, 5000, 6000).Shape(), cutter).Shape()
    assert capture(body).measure()["volume_mm3"] == pytest.approx(
        (4000 * 5000 - math.pi * 600**2) * 6000, rel=1e-10)


def test_bundle_roundtrip_is_immutable_and_does_not_execute_source(box):
    source = box.dumps()
    restored = GeometryBundle.loads(source)
    assert restored.dumps() == source
    assert restored.digest == box.digest
    external = restored.to_dict()
    external["preview_mesh"]["vertices_mm"][0][0] = 999
    assert restored.dumps() == source
    with pytest.raises(FrozenInstanceError):
        restored._data = {}
    with pytest.raises(TypeError):
        restored._data["manifest"]["units"] = "m"


def test_json_reload_is_inert_even_without_ocp(box):
    result = fresh("""
import importlib.abc, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('native parser entered by JSON load')
sys.meta_path.insert(0, NoOcp())
from kir.occt_geometry import GeometryBundle
bundle = GeometryBundle.loads(sys.stdin.read())
print(bundle.digest)
""", box.dumps())
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == box.digest


def test_actual_brep_reloads_and_remeasures_in_a_fresh_process(box):
    result = fresh("""
import json, sys
from kir.occt_geometry import GeometryBundle
bundle = GeometryBundle.loads(sys.stdin.read())
print(json.dumps(bundle.measure()))
""", box.dumps())
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["volume_mm3"] == pytest.approx(6e9, rel=1e-12)


@pytest.mark.parametrize("path,new", [
    (("manifest", "units"), "m"),
    (("manifest", "backend", "version"), "future"),
    (("manifest", "binding", "op_id"), "b" * 64),
    (("manifest", "brep", "size_bytes"), 1),
    (("manifest", "brep", "sha256"), "b" * 64),
    (("manifest", "preview", "sha256"), "b" * 64),
    (("manifest", "preview", "body_sha256"), "b" * 64),
    (("manifest", "preview", "measured_upper_bound_mm"), 20),
    (("manifest", "preview", "relative"), 0),
    (("manifest", "preview", "angular_deflection_rad"), 4),
    (("manifest", "recipe", "source"), "print('not original source')"),
    (("manifest", "measurements", "solid_count"), True),
    (("manifest", "measurements", "area_mm2"), -1),
    (("manifest", "source_lineage"), "source"),
    (("preview_mesh", "triangles"), [[True, 1, 2]]),
    (("preview_mesh", "triangles"), [[0, 1, 999999]]),
    (("brep_base64",), "not base64"),
])
def test_malformed_or_mismatched_contract_refuses_even_if_outer_hash_is_recomputed(box, path, new):
    data = box.to_dict()
    target = data
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = new
    with pytest.raises(GeometryRefusal):
        GeometryBundle.loads(resign(data))


def test_payload_edit_without_hash_update_is_refused(box):
    data = box.to_dict()
    data["manifest"]["parameters"]["purpose"] = "different"
    with pytest.raises(GeometryRefusal, match="integrity_mismatch"):
        GeometryBundle.loads(json.dumps(data))


@pytest.mark.parametrize("source", ["null", "[]", "{\"x\":1,\"x\":2}", "NaN", "Infinity", "{" * 1000,
                                      "{\"n\":" + "1" * 5000 + "}"])
def test_malformed_json_has_a_named_refusal(source):
    with pytest.raises(GeometryRefusal):
        GeometryBundle.loads(source)


def test_size_and_depth_are_bounded_before_native_execution(box):
    with pytest.raises(GeometryRefusal, match="budget_exceeded"):
        GeometryBundle.loads(" " * (MAX_BUNDLE_BYTES + 1))
    data = box.to_dict()
    value = {}
    for _ in range(40):
        value = {"nested": value}
    data["manifest"]["parameters"] = value
    with pytest.raises(GeometryRefusal, match="budget_exceeded"):
        GeometryBundle.loads(resign(data))


@pytest.mark.parametrize("frame", [
    (2., 0., 0., 0., *IDENTITY_FRAME[4:]),
    (-1., 0., 0., 0., *IDENTITY_FRAME[4:]),
    (*IDENTITY_FRAME[:12], 1., 0., 0., 1.),
    (True, *IDENTITY_FRAME[1:]),
    (float("nan"), *IDENTITY_FRAME[1:]),
])
def test_invalid_frame_is_not_silently_normalized(box, frame):
    with pytest.raises(GeometryRefusal):
        capture(box.read_body(), frame=frame)


def test_rigid_frame_is_applied_once_at_kir_fallback_not_to_local_brep(box):
    frame = (0., -1., 0., 1234., 1., 0., 0., -4567., 0., 0., 1., -1200., 0., 0., 0., 1.)
    moved = capture(box.read_body(), frame=frame)
    assert moved.measure()["centroid_mm"] == pytest.approx([500, 1000, 1500])
    op = moved.fallback_op(name="Rotated and moved box")
    for local, placed in zip(moved.to_dict()["preview_mesh"]["vertices_mm"], op["mesh"]["vertices_mm"]):
        assert placed == pytest.approx([1234-local[1], -4567+local[0], local[2]-1200])
    assert mesh_volume(op["mesh"]) == pytest.approx(6e9, rel=1e-12)


def test_failed_mesh_budget_does_not_modify_previous_bundle_or_input_body(podium):
    _, bundle = podium
    prior = bundle.dumps()
    body = bundle.read_body()
    with pytest.raises(GeometryRefusal, match="budget_exceeded"):
        capture(body, linear_deflection_mm=10, max_triangles=10)
    assert bundle.dumps() == prior
    replacement = capture(body)
    assert replacement.measure()["volume_mm3"] == pytest.approx(bundle.measure()["volume_mm3"], rel=1e-12)


def test_fine_preview_can_be_retained_but_is_not_silently_coarsened_for_revit(podium):
    _, bundle = podium
    fine = capture(bundle.read_body(), linear_deflection_mm=10,
                   max_vertices=100_000, max_triangles=100_000)
    assert len(fine.to_dict()["preview_mesh"]["triangles"]) > 4096
    original = fine.dumps()
    with pytest.raises(GeometryRefusal, match="kir_fallback_refused"):
        fine.fallback_op(name="Too dense for current KIR")
    assert fine.dumps() == original


def test_invalid_native_shape_refuses_without_masking_previous_result(box):
    from OCP.TopoDS import TopoDS_Shape
    original = box.dumps()
    with pytest.raises(GeometryRefusal, match="invalid_body"):
        capture(TopoDS_Shape())
    with pytest.raises(GeometryRefusal, match="invalid_body"):
        capture(None)
    assert box.dumps() == original


def test_single_solid_compound_is_allowed_but_stray_edges_are_not_counted_as_body(box):
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.TopoDS import TopoDS_Compound
    from OCP.gp import gp_Pnt
    compound, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, box.read_body())
    assert capture(compound).measure()["volume_mm3"] == pytest.approx(6e9)
    builder.Add(compound, BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(10000, 0, 0)).Edge())
    with pytest.raises(GeometryRefusal, match="unsupported_body"):
        capture(compound)


def test_modeling_and_meshing_tolerances_are_distinct_not_claimed_as_measured_bounds(box):
    manifest = box.to_dict()["manifest"]
    assert manifest["modeling_tolerance_mm"] == .01
    assert manifest["preview"]["linear_deflection_mm"] == 20
    assert manifest["preview"]["measured_upper_bound_mm"] is None
    assert manifest["semantics"] == "geometry_only"
    assert manifest["face_identity"] == "bundle_local"


def test_curved_podium_real_kernel_change_and_existing_compiler(podium):
    from examples.curved_podium import change
    from kir import compile_program
    from kir.project_diff import diff_projects
    first_project, first_bundle = podium
    project, bundle = change(ProjectRevision.loads(first_project.dumps()), GeometryBundle.loads(first_bundle.dumps()),
                             bulge_mm=2500., atrium_radius_mm=3500.)
    assert bundle.op_id == first_bundle.op_id
    assert bundle.body_digest != first_bundle.body_digest
    assert bundle.to_dict()["manifest"]["source_lineage"] == [first_bundle.digest]
    assert diff_projects(first_project, project).changed == (bundle.op_id,)
    for p, b in ((first_project, first_bundle), (project, bundle)):
        assert p.plan().to_ops()[0]["id"] == b.op_id
        assert b.measure()["solid_count"] == 1
        for version in ("2023", "2026"):
            result = compile_program(p.to_program(), revit_version=version)
            assert result.ok, [(d.code, d.message_ru) for d in result.diagnostics]
        assert mesh_volume(b.to_dict()["preview_mesh"]) == pytest.approx(b.measure()["volume_mm3"], rel=.01)


def test_podium_rebuild_source_binding_refuses_edited_parameter_only_snapshot(podium):
    from examples.curved_podium import change
    project, bundle = podium
    previous = project.instances[0]
    altered = project.replace_instance(replace(previous, parameters={**previous.parameters, "height_mm": 15000}),
                                        expected_revision=project.revision_id)
    with pytest.raises(GeometryRefusal, match="source_binding_mismatch"):
        change(altered, bundle, atrium_radius_mm=3500)


@pytest.mark.parametrize("changes", [{"height_mm": -1}, {"height_mm": True},
                                    {"bulge_mm": float("nan")}, {"new_parameter": 1},
                                    {"height_mm": 10**500}])
def test_refused_podium_parameter_edit_preserves_previous_artifact(podium, changes):
    from examples.curved_podium import change
    project, bundle = podium
    prior = project.dumps(), bundle.dumps()
    with pytest.raises(GeometryRefusal):
        change(project, bundle, **changes)
    assert (project.dumps(), bundle.dumps()) == prior


def test_actual_trimmed_podium_brep_reloads_in_fresh_process(podium):
    _, bundle = podium
    result = fresh("""
import json, sys
from kir.occt_geometry import GeometryBundle
bundle = GeometryBundle.loads(sys.stdin.read())
print(json.dumps(bundle.measure()))
""", bundle.dumps())
    assert result.returncode == 0, result.stderr
    facts = json.loads(result.stdout)
    assert facts["volume_mm3"] == pytest.approx(bundle.measure()["volume_mm3"], rel=1e-12)
    assert facts["solid_count"] == 1 and facts["face_count"] == 7


def test_podium_refuses_recipe_change_without_deleting_prior_state(podium):
    from examples.curved_podium import change
    project, bundle = podium
    old = project.modules[0]
    changed_pin = replace(old.recipe, source=old.recipe.source + "\n# changed")
    changed_module = ModuleDefinition(old.key, old.owner, changed_pin)
    changed_instance = replace(project.instances[0], module_digest=None)
    altered = project.revise(expected_revision=project.revision_id,
                              modules=[changed_module], instances=[changed_instance])
    with pytest.raises(GeometryRefusal, match="recipe_changed"):
        change(altered, bundle, atrium_radius_mm=3500)


def test_standalone_example_stdout_is_a_complete_project_and_bundle():
    native()
    result = subprocess.run([sys.executable, "examples/curved_podium.py"], cwd=ROOT,
                            capture_output=True, text=True, timeout=40,
                            env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert result.returncode == 0, result.stderr
    artifact = json.loads(result.stdout)
    project = ProjectRevision.from_dict(artifact["project"])
    bundle = GeometryBundle(artifact["geometry_bundle"])
    assert project.instances[0].metadata["geometry_bundle_sha256"] == bundle.digest
    assert project.to_program()["ops"][0]["id"] == bundle.op_id
    assert "brep_base64" not in project.dumps()


def test_saved_brep_is_not_parsed_by_json_load_even_with_invalid_native_content(box):
    data = box.to_dict()
    raw = b"\nCASCADE Topology V3, (c) Open Cascade\nnot a valid native body\n"
    data["brep_base64"] = base64.b64encode(raw).decode("ascii")
    data["manifest"]["brep"].update(size_bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    data["manifest"]["preview"]["body_sha256"] = hashlib.sha256(raw).hexdigest()
    bundle = GeometryBundle.loads(resign(data))
    # An inert, correctly bound envelope is not a successful native parse.
    with pytest.raises(GeometryRefusal):
        bundle.read_body()
