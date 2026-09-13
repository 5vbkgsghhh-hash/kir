"""G02: publication derives one geometry from its selected BRep owner."""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from kir.geometry_materialization import (GeometryMaterialization, materialize_project,
                                         validate_geometry_bindings)
from kir.occt_geometry import GeometryBundle, GeometryRefusal, IDENTITY_FRAME, capture_body
from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance, NamedOutput,
                         PROJECT_SCHEMA_V2, ProjectRevision, RecipePin, _hash)


PIN = RecipePin("explicit analytic box fixture; source is declared, not executed on load", "a" * 64)
ROOT = Path(__file__).resolve().parents[2]


def capture(width=1000, *, parameters=None, **changes):
    pytest.importorskip("OCP")
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    options = dict(project_id="p", instance_key="body", output_key="solid", recipe=PIN,
                   parameters={"width_mm": width} if parameters is None else parameters)
    options.update(changes)
    return capture_body(BRepPrimAPI_MakeBox(width, 2000, 3000).Shape(), **options)


def project_for(bundle):
    manifest = bundle.to_dict()["manifest"]
    binding = manifest["binding"]
    instance = ModuleInstance(binding["instance_key"], "m", [NamedOutput(
        binding["output_key"], {"op": "create_directshape", "category": "mass", "name": "Authored body"},
        BodyRepresentation(bundle.digest, bundle.body_digest))], manifest["parameters"])
    return ProjectRevision(binding["project_id"], [ModuleDefinition(
        "m", "sealed_evaluation", RecipePin.from_dict(manifest["recipe"]))], [instance], schema=PROJECT_SCHEMA_V2)


def resized_claim(data):
    data["bundle_sha256"] = _hash({key: value for key, value in data.items() if key != "bundle_sha256"})
    return GeometryBundle(data)


@pytest.fixture(scope="module")
def box():
    return capture()


@pytest.fixture(scope="module")
def mixed(box):
    larger = capture(2000)
    data = larger.to_dict()
    data["preview_mesh"] = box.to_dict()["preview_mesh"]
    data["manifest"]["preview"]["sha256"] = _hash(data["preview_mesh"])
    data["manifest"]["measurements"]["volume_mm3"] = 1.0  # another stale/asserted derivative
    return resized_claim(data)


def fresh(code, value):
    return subprocess.run([sys.executable, "-c", code], input=json.dumps(value),
                          text=True, capture_output=True, cwd=ROOT, timeout=40,
                          env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))


def test_load_binding_validation_and_diff_are_inert_in_a_process_without_ocp(box):
    result = fresh("""
import importlib.abc, json, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('inert loading entered native backend')
sys.meta_path.insert(0, NoOcp())
from kir.geometry_materialization import validate_geometry_bindings
from kir.occt_geometry import GeometryBundle
from kir.project import ProjectRevision
from kir.project_diff import diff_projects
source = json.load(sys.stdin)
project = ProjectRevision.from_dict(source['project'])
bundle = GeometryBundle(source['bundle'])
validate_geometry_bindings(project, {bundle.digest: bundle})
assert len(diff_projects(project, project).unchanged) == 1
assert not any(name == 'OCP' or name.startswith('OCP.') for name in sys.modules)
print('inert')
""", {"project": project_for(box).to_dict(), "bundle": box.to_dict()})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "inert"


def test_body_not_cached_mesh_is_the_publication_geometry_owner(mixed):
    project = project_for(mixed)
    original = project.dumps(), mixed.dumps()
    assert max(point[0] for point in mixed.fallback_op(name="cached")["mesh"]["vertices_mm"]) == 1000
    materialized = materialize_project(project, {mixed.digest: mixed})
    operation = materialized.to_program()["ops"][0]
    assert max(point[0] for point in operation["mesh"]["vertices_mm"]) == pytest.approx(2000)
    assert operation["name"] == "Authored body" and operation["category"] == "mass"
    assert operation["id"] == mixed.op_id
    source = materialized.sources[0]
    assert source["source_bundle_sha256"] == mixed.digest
    assert source["source_body_sha256"] == mixed.body_digest
    assert source["measurements"]["volume_mm3"] == pytest.approx(12e9, rel=1e-12)
    assert source["measurements_space"] == "body_local" and source["mesh_space"] == "project"
    assert source["stored_preview_bytes_equal"] is False
    assert source["mesh_sha256"] == _hash(operation["mesh"])
    assert (project.dumps(), mixed.dumps()) == original


def test_rederive_keeps_exact_source_bytes_address_frame_and_provenance(mixed):
    data = mixed.to_dict()
    derived = mixed.rederive_preview().to_dict()
    assert derived["brep_base64"] == data["brep_base64"]
    for field in ("binding", "recipe", "parameters", "source_lineage", "units", "frame", "backend", "brep"):
        assert derived["manifest"][field] == data["manifest"][field]
    assert derived["bundle_sha256"] != data["bundle_sha256"]
    assert max(p[0] for p in derived["preview_mesh"]["vertices_mm"]) == 2000


def test_authored_rigid_frame_is_applied_once_and_measurement_space_is_named(box):
    frame = (0., -1., 0., 100000., 1., 0., 0., -50000.,
             0., 0., 1., 1200., 0., 0., 0., 1.)
    moved = capture(frame=frame)
    materialized = materialize_project(project_for(moved), {moved.digest: moved})
    source = materialized.sources[0]
    assert source["frame"] == frame
    assert source["measurements"]["centroid_mm"] == pytest.approx([500, 1000, 1500])
    mesh = materialized.to_program()["ops"][0]["mesh"]
    assert [min(p[i] for p in mesh["vertices_mm"]) for i in range(3)] == pytest.approx([98000, -50000, 1200])
    assert [max(p[i] for p in mesh["vertices_mm"]) for i in range(3)] == pytest.approx([100000, -49000, 4200])


@pytest.mark.parametrize("case,code", [
    ("missing", "missing_asset"), ("wrong_type", "invalid_asset"),
    ("wrong_asset_key", "binding_mismatch"), ("wrong_body_digest", "binding_mismatch"),
    ("wrong_address", "binding_mismatch"), ("parameters", "parameters_mismatch"),
    ("recipe", "recipe_mismatch"),
])
def test_binding_refusals_happen_before_native_work_and_keep_previous_values(box, monkeypatch, case, code):
    project = project_for(box)
    assets = {box.digest: box}
    if case == "missing":
        assets = {}
    elif case == "wrong_type":
        assets = {box.digest: box.to_dict()}
    elif case in ("wrong_asset_key", "wrong_body_digest"):
        instance = project.instances[0]
        reference = BodyRepresentation("c" * 64, box.body_digest) if case == "wrong_asset_key" else BodyRepresentation(box.digest, "d" * 64)
        output = replace(instance.outputs[0], geometry=reference)
        project = project.replace_instance(replace(instance, outputs=[output]), expected_revision=project.revision_id)
        if case == "wrong_asset_key":
            assets = {"c" * 64: box}
    elif case == "wrong_address":
        project = replace(project, project_id="another")
    elif case == "parameters":
        project = project.replace_instance(replace(project.instances[0], parameters={"width_mm": 2000}), expected_revision=project.revision_id)
    else:
        definition = replace(project.modules[0], recipe=replace(PIN, source="changed source"))
        project = project.revise(expected_revision=project.revision_id, modules=[definition],
                                 instances=[replace(project.instances[0], module_digest=None)])
    def no_native(*_args, **_kwargs):
        raise AssertionError("binding must be validated before native work")
    monkeypatch.setattr(GeometryBundle, "rederive_preview", no_native)
    before = project.dumps(), box.dumps()
    with pytest.raises(GeometryRefusal) as refused:
        materialize_project(project, assets)
    assert refused.value.code == code
    assert (project.dumps(), box.dumps()) == before


@pytest.mark.parametrize("recorded,authored", [(1, True), (1, 1.0), (0.0, -0.0)])
def test_parameter_context_matching_does_not_coerce_scalar_types(recorded, authored):
    bundle = capture(parameters={"choice": recorded})
    project = project_for(bundle)
    project = project.replace_instance(replace(project.instances[0], parameters={"choice": authored}), expected_revision=project.revision_id)
    with pytest.raises(GeometryRefusal, match="parameters_mismatch"):
        validate_geometry_bindings(project, {bundle.digest: bundle})


def test_missing_module_recipe_does_not_claim_source_equivalence_or_erase_bundle_source(box):
    project = project_for(box)
    unknown = ModuleDefinition("m", "sealed_evaluation", None)
    project = project.revise(expected_revision=project.revision_id, modules=[unknown],
                             instances=[replace(project.instances[0], module_digest=None)])
    original = box.dumps()
    result = materialize_project(project, {box.digest: box})
    assert result.sources[0]["module_recipe_match"] == "not_claimed"
    assert box.dumps() == original


def test_all_referenced_assets_are_validated_before_any_is_materialized(box, monkeypatch):
    second = capture(instance_key="other")
    project = project_for(box)
    other = project_for(second).instances[0]
    project = project.with_instances([*project.instances, other], expected_revision=project.revision_id)
    def no_native(*_args, **_kwargs):
        raise AssertionError("missing later asset must refuse before native work")
    monkeypatch.setattr(GeometryBundle, "rederive_preview", no_native)
    with pytest.raises(GeometryRefusal, match="missing_asset"):
        materialize_project(project, {box.digest: box})


def test_ordinary_outputs_are_unchanged_and_can_materialize_without_ocp():
    result = fresh("""
import importlib.abc, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('ordinary project requires optional geometry backend')
sys.meta_path.insert(0, NoOcp())
from kir.geometry_materialization import materialize_project
from kir.project import ProjectRevision, ModuleInstance, ModuleDefinition
project = ProjectRevision('ordinary', [ModuleDefinition('m')], [ModuleInstance('i','m',
    {'level': {'op':'create_level','elev_mm':1200,'name':'L'}})])
result = materialize_project(project,{})
assert result.to_program() == project.to_program()
assert result.sources == ()
print('ordinary')
""", {})
    assert result.returncode == 0, result.stderr


def test_materialized_result_is_immutable_and_binds_mesh_program_and_plan(mixed):
    result = materialize_project(project_for(mixed), {mixed.digest: mixed})
    with pytest.raises(FrozenInstanceError):
        result.sources = ()
    with pytest.raises(TypeError):
        result.program["ops"][0]["mesh"]["vertices_mm"][0][0] = 0
    changed = result.to_program()
    changed["ops"][0]["mesh"]["vertices_mm"][0][0] += 1
    with pytest.raises(GeometryRefusal, match="invalid_materialization"):
        replace(result, program=changed)
    with pytest.raises(GeometryRefusal, match="invalid_materialization"):
        replace(result, sources=())
    stored = result.to_dict()
    assert stored["project_revision_id"] == result.project.revision_id
    assert stored["plan_digest"] == result.planned.plan_digest
    assert stored["recipe_execution"] == "not_run"
    assert stored["geometric_error_bound"] == "not_measured"
    assert not hasattr(GeometryMaterialization, "loads")


def test_dense_body_refuses_publication_without_changing_assets_or_project():
    pytest.importorskip("OCP")
    from examples.curved_podium import initial
    _, original = initial()
    data = original.to_dict()
    data["manifest"]["preview"]["linear_deflection_mm"] = 10
    fine_request_with_stale_preview = resized_claim(data)
    project = project_for(fine_request_with_stale_preview)
    before = project.dumps(), fine_request_with_stale_preview.dumps()
    with pytest.raises(GeometryRefusal, match="budget_exceeded"):
        materialize_project(project, {fine_request_with_stale_preview.digest: fine_request_with_stale_preview})
    assert (project.dumps(), fine_request_with_stale_preview.dumps()) == before


def test_persist_reload_materialize_scene_and_compiler_share_the_rederived_program(tmp_path, mixed):
    from kir import compile_program
    from kir.project_store import ProjectStore
    from kir.viewer.codec import SCENE_MAGIC
    from kir.viewer.live_scene import scene_from_programs
    project = project_for(mixed)
    store = ProjectStore.create(tmp_path / "geometry.sqlite", project,
                                schema="kir-project-store/2", assets=[mixed])
    reopened = ProjectStore.open(tmp_path / "geometry.sqlite")
    restored = reopened.head()
    asset = reopened.get_asset(mixed.digest)
    result = materialize_project(restored, {asset.digest: asset})
    program = result.to_program()
    scene, meta = scene_from_programs([program], origin_mm=(0, 0, 0))
    assert meta["source"] == "program" and meta["assertion"] == "self_reported"
    header_length = struct.unpack_from("<I", scene, len(SCENE_MAGIC))[0]
    header_start = len(SCENE_MAGIC) + 4
    header = json.loads(scene[header_start:header_start + header_length])
    body_start = header_start + header_length
    streams = {entry["name"]: scene[body_start + entry["offset"]:
                                    body_start + entry["offset"] + entry["length"]]
               for entry in header["buffers"]}
    mesh = program["ops"][0]["mesh"]
    assert meta["mesh_shown"] == 1
    assert header["elements"] == 1
    assert header["counts"] == {"mesh": 1, "box": 0, "capsule": 0, "prism": 0,
                                 "mesh_vertices": len(mesh["vertices_mm"]),
                                 "mesh_triangles": len(mesh["triangles"])}
    assert streams["ids"].decode("utf-8").splitlines() == ["p1/" + mixed.op_id]
    shown_vertices = list(struct.iter_unpack("<3f", streams["mesh_vtx"]))
    shown_triangles = list(struct.iter_unpack("<3I", streams["mesh_tri"]))
    assert shown_vertices == [tuple(point) for point in mesh["vertices_mm"]]
    assert shown_triangles == [tuple(triangle) for triangle in mesh["triangles"]]
    assert max(point[0] for point in shown_vertices) == 2000  # not the stale 1000 mm preview
    for version in ("2023", "2026"):
        compiled = compile_program(result.planned, revit_version=version)
        assert compiled.ok, [(d.code, d.message_ru) for d in compiled.diagnostics]
        assert compiled.planned.plan_digest == result.planned.plan_digest
    assert max(p[0] for p in program["ops"][0]["mesh"]["vertices_mm"]) == 2000
    assert store.head().dumps() == project.dumps()
