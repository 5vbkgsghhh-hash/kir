"""U01 A: exported records and bytes, not browser rendering or native geometry."""
from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from examples import residential_project as towers
from kir import compile_program, sdk
from kir.clash_bundle import bundle_oid
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, _hash
from kir.viewer import live_scene
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY, preview_native_blend
from kir.viewer import standalone_export as export


CAPABILITIES = (REQUIRED_CONSUMER_CAPABILITY,)
ROOT = Path(__file__).resolve().parents[3]


def decode(blob):
    length = struct.unpack_from("<I", blob, 8)[0]
    header = json.loads(blob[12:12 + length])
    base = 12 + length
    buffers = {row["name"]: blob[base + row["offset"]:base + row["offset"] + row["length"]]
               for row in header["buffers"]}
    return header, buffers


def from_ops(*operations):
    outputs = [NamedOutput(f"out-{index}", {key: value for key, value in op.items() if key != "id"})
               for index, op in enumerate(operations)]
    project = ProjectRevision("export-control", [ModuleDefinition("m")], [ModuleInstance("i", "m", outputs)])
    return materialize_project(project, {})


@pytest.fixture(scope="module")
def concept():
    return materialize_project(towers.concept(), {})


@pytest.fixture(scope="module")
def residential():
    pytest.importorskip("OCP")
    from examples.residential_with_podium import workflow
    return workflow()


def test_default_capability_omits_blends_by_address_without_even_running_proxy_producer(concept, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("preview requires explicit opt-in")
    monkeypatch.setattr(export, "preview_native_blend", forbidden)
    result = export.export_standalone_scene(concept)
    data = result.to_dict()
    assert data["proxies"] == [] and data["scene"]["records"] == []
    assert len(data["omissions"]) == 3
    assert {row["code"] for row in data["omissions"]} == {"capability_required"}
    assert {row["op_id"] for row in data["omissions"]} == {op["id"] for op in concept.to_program()["ops"]}
    assert all(row["required_capability"] == REQUIRED_CONSUMER_CAPABILITY for row in data["omissions"])
    assert data["consumer_contract"]["required_proxy_capabilities"] == []


def test_original_binary_scene_is_kept_byte_for_byte_and_never_injected_with_proxy_meshes(concept, monkeypatch):
    captured = []
    actual = live_scene.scene_from_programs
    def recording(programs, **kwargs):
        result = actual(programs, **kwargs)
        captured.append((programs, kwargs, result[0]))
        return result
    monkeypatch.setattr(live_scene, "scene_from_programs", recording)
    before = concept.project.dumps(), concept.to_dict()
    result = export.export_standalone_scene(concept, consumer_capabilities=CAPABILITIES)
    data = result.to_dict()
    assert len(captured) == 1 and captured[0][1] == {}  # no live session/snapshot authority
    assert captured[0][0] == [concept.to_program()]
    assert result.scene_bytes == captured[0][2] == base64.b64decode(data["scene"]["base64"], validate=True)
    assert decode(result.scene_bytes)[0]["counts"]["mesh"] == 0
    assert len(data["proxies"]) == 3 and data["omissions"] == []
    assert (concept.project.dumps(), concept.to_dict()) == before
    assert all(op["op"] == "create_solid_blend" and "mesh" not in op for op in captured[0][0][0]["ops"])


def test_proxy_source_rings_and_plan_hashes_are_bound_to_the_original_named_outputs(concept):
    data = export.export_standalone_scene(concept, consumer_capabilities=CAPABILITIES).to_dict()
    source = data["source"]
    assert source["project_revision_id"] == concept.project.revision_id
    assert source["plan_digest"] == concept.planned.plan_digest
    assert source["materialization_digest"] == concept.to_dict()["materialization_digest"]
    assert source["program_sha256"] == _hash(concept.to_program())
    for row, proxy, op in zip(source["operations"], data["proxies"], concept.to_program()["ops"], strict=True):
        assert row["operation_sha256"] == _hash(op)
        assert proxy["display_id"] == row["display_id"] == bundle_oid(1, op["id"])
        assert proxy["preview"] == preview_native_blend(op).to_dict()
        assert proxy["preview"]["source"]["op_id"] == row["op_id"] == op["id"]
        assert proxy["preview"]["claims"]["native_equivalence"] == "unverified"
        assert proxy["preview"]["claims"]["containment"] == "not_claimed"
        assert proxy["preview"]["claims"]["clash_eligibility"] == "none"
        assert row["display_status"] == "approximate_proxy_record"
    assert data["claims"]["browser_rendering"] == "not_observed"


def test_immutable_artifact_hashes_and_detached_serialization(concept):
    result = export.export_standalone_scene(concept, consumer_capabilities=CAPABILITIES)
    data = json.loads(result.dumps())
    assert data["artifact_digest"] == result.digest == _hash({key: value for key, value in data.items() if key != "artifact_digest"})
    assert data["scene"]["sha256"] == hashlib.sha256(result.scene_bytes).hexdigest()
    assert data["scene"]["size_bytes"] == len(result.scene_bytes)
    with pytest.raises(FrozenInstanceError):
        result.scene_bytes = b"changed"
    with pytest.raises(TypeError):
        result._descriptor["source"]["operations"][0]["op"] = "create_directshape"
    data["proxies"][0]["preview"]["mesh"]["vertices_mm"][0][0] += 90000
    assert data != result.to_dict()
    assert not hasattr(result, "loads") and not hasattr(result, "to_program")
    with pytest.raises(TypeError, match="export_standalone_scene"):
        export.StandaloneDisplayArtifact()


@pytest.mark.parametrize("value", [None, {}, [], "store.sqlite"])
def test_export_requires_explicit_materialization_not_implicit_native_resolution(value):
    with pytest.raises(export.StandaloneExportRefusal, match="explicit_materialization_required"):
        export.export_standalone_scene(value)


@pytest.mark.parametrize("capabilities,code", [(None, "invalid_capabilities"), (True, "invalid_capabilities"),
    (REQUIRED_CONSUMER_CAPABILITY, "invalid_capabilities"), ({REQUIRED_CONSUMER_CAPABILITY: True}, "invalid_capabilities"),
    ([True], "invalid_capabilities"), (["display_approximate_profile_proxy/2"], "unsupported_capability")])
def test_malformed_or_unknown_capability_does_not_accidentally_opt_in(concept, capabilities, code):
    with pytest.raises(export.StandaloneExportRefusal, match=code):
        export.export_standalone_scene(concept, consumer_capabilities=capabilities)


def test_legitimate_native_blend_outside_display_subset_is_named_omission_not_a_replacement():
    op = towers.concept().to_program()["ops"][0]
    op["profile_top"] = {"outer": {"shape": "poly", "points_mm": [[0, 0], [12000, 0], [12000, 5000], [0, 5000]]}}
    result = from_ops(op)
    prior = result.to_dict()
    artifact = export.export_standalone_scene(result, consumer_capabilities=CAPABILITIES).to_dict()
    assert artifact["proxies"] == []
    assert artifact["omissions"][0]["code"] == "unsupported_similarity"
    assert artifact["omissions"][0]["op_id"] == result.to_program()["ops"][0]["id"]
    for version in ("2023", "2026"):
        compiled = compile_program(result.planned, revit_version=version)
        assert compiled.ok and "CreateBlendGeometry" in compiled.csharp
    assert result.to_dict() == prior


def test_one_unsupported_profile_does_not_remove_an_independent_supported_proxy():
    unsupported, supported = towers.concept().to_program()["ops"][:2]
    unsupported["profile_top"] = {"outer": {"shape": "poly", "points_mm": [[0, 0], [12000, 0], [12000, 5000], [0, 5000]]}}
    result = from_ops(unsupported, supported)
    artifact = export.export_standalone_scene(result, consumer_capabilities=CAPABILITIES).to_dict()
    operations = result.to_program()["ops"]
    assert [row["op_id"] for row in artifact["omissions"]] == [operations[0]["id"]]
    assert [row["preview"]["source"]["op_id"] for row in artifact["proxies"]] == [operations[1]["id"]]
    assert [row["display_status"] for row in artifact["source"]["operations"]] == ["omitted", "approximate_proxy_record"]


def test_existing_codec_prism_is_not_silently_left_out_of_the_consumer_contract():
    # This actual legal operation differs from current example's by_contour
    # floors. Without a type snapshot it is a NO_BODY plan proxy, not a slab.
    result = from_ops(sdk.create_floor(outline=[[0, 0], [3000, 0], [3000, 2000], [0, 2000]],
                                      level={"by": "name", "value": "L1"}))
    artifact = export.export_standalone_scene(result).to_dict()
    assert artifact["scene"]["counts"]["prism"] == 1
    assert artifact["consumer_contract"]["required_scene_kinds"] == ["prism"]
    row = artifact["scene"]["records"][0]
    assert row["kind"] == "prism" and row["fidelity"] == "no_body"


@pytest.mark.parametrize("index,proxies", [(2, 3), (3, 2), (4, 2)])
def test_real_residential_records_preserve_podium_geometry_ghost_fidelity_and_addressed_floor_omissions(residential, index, proxies):
    revisions, bundle = residential
    result = materialize_project(revisions[index], {bundle.digest: bundle})
    prior = result.project.dumps(), bundle.dumps(), result.to_program()
    artifact = export.export_standalone_scene(result, consumer_capabilities=CAPABILITIES)
    data = artifact.to_dict()
    assert len(data["proxies"]) == proxies and data["unattributed_scene_ids"] == []
    assert data["source"]["body_sources"] == result.to_dict()["sources"]
    assert data["scene"]["counts"] == {"box": 0 if index == 2 else 3, "capsule": 0 if index == 2 else 12,
        "prism": 0, "mesh": 1, "mesh_triangles": 584, "mesh_vertices": 594}
    header, buffers = decode(artifact.scene_bytes)
    mesh_rows = [row for row in data["scene"]["records"] if row["kind"] == "mesh"]
    assert len(mesh_rows) == 1 and mesh_rows[0]["display_id"] == bundle_oid(1, bundle.op_id)
    assert mesh_rows[0]["fidelity"] == "exact"  # supplied triangles only, NOT exact/native BIM
    authored = next(op["mesh"] for op in result.to_program()["ops"] if op["id"] == bundle.op_id)
    actual_vertices = list(struct.iter_unpack("<3f", buffers["mesh_vtx"]))
    assert len(actual_vertices) == len(authored["vertices_mm"])
    for actual, expected in zip(actual_vertices, authored["vertices_mm"], strict=True):
        assert [actual[i] + header["origin_mm"][i] for i in range(3)] == pytest.approx(expected, abs=.005, rel=0)
    assert list(struct.iter_unpack("<3I", buffers["mesh_tri"])) == [tuple(tri) for tri in authored["triangles"]]
    assert all(row["fidelity"] == "no_body" for row in data["scene"]["records"] if row["kind"] != "mesh")
    if index > 2:
        assert len(data["omissions"]) == 6
        assert sorted(row["op"] for row in data["omissions"]) == ["create_floor_by_contour"] * 3 + ["create_level"] * 3
        assert {row["code"] for row in data["omissions"]} == {"no_direct_scene_record"}
    assert (result.project.dumps(), bundle.dumps(), result.to_program()) == prior


def test_fresh_process_store_reopen_edit_materialize_export_keeps_real_remaining_rings_and_native_codegen(residential, tmp_path):
    from kir.project_store import ProjectStore
    revisions, bundle = residential
    path = tmp_path / "standalone-history.sqlite"
    store = ProjectStore.create(path, revisions[0])
    store.upgrade_schema("kir-project-store/2", expected_revision=revisions[0].revision_id)
    for index, revision in enumerate(revisions[1:], 1):
        store.commit(revision, expected_revision=revision.parent_revision, assets=[bundle] if index == 2 else [])
    child = subprocess.run([sys.executable, "-c", """
import json, sys
from examples.residential_with_podium import continue_section, materialize_saved
from kir.project_store import ProjectStore
from kir.viewer.standalone_export import export_standalone_scene
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
from kir import compile_program
store = ProjectStore.open(sys.argv[1], readonly=False)
previous = store.head()
updated = continue_section(store, expected_revision=previous.revision_id, height_mm=4500, setback_mm=1200)
result = materialize_saved(store)
artifact = export_standalone_scene(result, consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY])
for version in ('2023', '2026'):
    compiled = compile_program(result.planned, revit_version=version)
    assert compiled.ok
    assert 'CreateBlendGeometry' in compiled.csharp and '(ICollection<VertexPair>)null' in compiled.csharp
assert result.project.revision_id == updated.revision_id
print(artifact.dumps())
""", str(path)], text=True, capture_output=True, cwd=ROOT, timeout=40,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    data = json.loads(child.stdout)
    reopened = ProjectStore.open(path, readonly=True)
    head = reopened.head()
    assert data["source"]["project_revision_id"] == head.revision_id
    assert data["source"]["parent_revision_id"] == revisions[-1].revision_id
    assert head.instances[0].parameters["storey_height_mm"] == 4500
    assert head.instances[0].parameters["terrace_setback_mm"] == 1200
    assert reopened.get_asset(bundle.digest).dumps() == bundle.dumps()
    assert head.instances[1:] == revisions[-1].instances[1:]
    assert len(data["proxies"]) == 2
    original_ops = towers.concept().to_program()["ops"]
    for record, original in zip(data["proxies"], original_ops[1:], strict=True):
        # Actual upper and lower authored rings, not just unchanged IDs.
        mesh = record["preview"]["mesh"]["vertices_mm"]
        assert mesh[:4] == [[*xy, 0.] for xy in original["profile"]["outer"]["points_mm"]]
        assert mesh[-4:] == [[*xy, original["height_mm"]] for xy in original["profile_top"]["outer"]["points_mm"]]
        assert record["preview"]["source"]["operation_sha256"] == _hash(original)
    header, buffers = decode(base64.b64decode(data["scene"]["base64"], validate=True))
    assert header["counts"]["mesh"] == 1 and bundle_oid(1, bundle.op_id) in buffers["ids"].decode().splitlines()
    assert data["source"]["body_sources"][0]["source_bundle_sha256"] == bundle.digest
    assert data["source"]["body_sources"][0]["source_body_sha256"] == bundle.body_digest
    assert data["consumer_contract"]["required_scene_kinds"] == ["box", "capsule", "mesh"]
    # This proves an exporter/user data path only. No browser or Revit ran.
    assert data["claims"]["browser_rendering"] == "not_observed"


def test_export_reuses_explicit_materialization_without_reading_native_body_again(residential, monkeypatch):
    from kir.occt_geometry import GeometryBundle
    revisions, bundle = residential
    result = materialize_project(revisions[-1], {bundle.digest: bundle})
    def forbidden(*args, **kwargs):
        raise AssertionError("export is not another native execution stage")
    for method in ("read_body", "rederive_preview", "measure"):
        monkeypatch.setattr(GeometryBundle, method, forbidden)
    artifact = export.export_standalone_scene(result, consumer_capabilities=CAPABILITIES)
    assert len(artifact.to_dict()["proxies"]) == 2


@pytest.mark.parametrize("budget", ["MAX_SCENE_BYTES", "MAX_ARTIFACT_BYTES"])
def test_output_budget_refusal_leaves_materialization_and_previous_artifact_unchanged(concept, monkeypatch, budget):
    previous = export.export_standalone_scene(concept, consumer_capabilities=CAPABILITIES)
    saved = previous.dumps(), concept.to_dict()
    monkeypatch.setattr(export, budget, 1)
    with pytest.raises(export.StandaloneExportRefusal, match="display_budget_exceeded"):
        export.export_standalone_scene(concept, consumer_capabilities=CAPABILITIES)
    assert (previous.dumps(), concept.to_dict()) == saved


def test_fresh_process_without_ocp_can_export_an_explicit_ordinary_materialization():
    child = subprocess.run([sys.executable, "-c", """
import importlib.abc, json, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('standalone export entered native backend')
sys.meta_path.insert(0, NoOcp())
from examples.residential_project import concept
from kir.geometry_materialization import materialize_project
from kir.viewer.standalone_export import export_standalone_scene
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
r = materialize_project(concept(), {})
a = export_standalone_scene(r, consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY])
assert len(a.to_dict()['proxies']) == 3
assert not any(name == 'OCP' or name.startswith('OCP.') for name in sys.modules)
print(a.digest)
"""], text=True, capture_output=True, cwd=ROOT, timeout=30,
        env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    assert len(child.stdout.strip()) == 64
