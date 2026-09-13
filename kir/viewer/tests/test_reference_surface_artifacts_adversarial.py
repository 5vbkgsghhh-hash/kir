"""Independent display/2 integrity controls; no browser, native model or sockets.

Valid fixtures derive actual reference surfaces. Resigned adversarial documents
exercise the inert loader, not a claim that hashing authenticates derivation.
"""
import base64
from copy import deepcopy
import hashlib
import json
import struct

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, _canonical, _hash, output_id
from kir.viewer import reference_surfaces
from kir.viewer.standalone import DisplayInputRefusal, load_display_artifact
from kir.viewer.standalone_export import export_standalone_scene


def resign(data, *, previews=True):
    if previews:
        for record in data.get("surfaces", []):
            preview = record["preview"]
            preview["preview_digest"] = _hash({key: value for key, value in preview.items() if key != "preview_digest"})
    data["artifact_digest"] = _hash({key: value for key, value in data.items() if key != "artifact_digest"})
    return _canonical(data).encode()


@pytest.fixture(scope="module")
def fixture():
    ref = lambda key: {"by": "ref", "value": output_id("surface-review", "i", key)}
    project = ProjectRevision("surface-review", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
        NamedOutput("low", {"op": "create_level", "elev_mm": 5000}),
        NamedOutput("high", {"op": "create_level", "elev_mm": 9200}),
        NamedOutput("wall", {"op": "create_wall", "level": ref("low"), "top_level": ref("high"),
            "height_mm": 2800, "base_offset_mm": -300, "top_offset_mm": -500,
            "p0_mm": [100000, -20000], "p1_mm": [105000, -17000]}),
        NamedOutput("floor", {"op": "create_floor_by_contour", "level": ref("low"), "height_offset_mm": -700,
            "contour": {"outer": {"shape": "poly", "points_mm": [[100000, -20000], [110000, -20000],
                [110000, -14000], [100000, -14000]]}, "holes": [{"shape": "poly", "points_mm": [
                    [101000, -19000], [102000, -19000], [102000, -18000], [101000, -18000]]}]}}),
        NamedOutput("late", {"op": "create_level", "elev_mm": 15000}),
    ])])
    materialization = materialize_project(project, {})
    artifact = export_standalone_scene(materialization, consumer_capabilities=[reference_surfaces.SURFACE_CAPABILITY])
    data = artifact.to_dict()
    assert {record["preview"]["surface_kind"] for record in data["surfaces"]} == {"wall_axis_surface", "floor_datum_surface"}
    assert data["surface_refusals"] == []
    assert load_display_artifact(artifact.dumps().encode()).transport["schema"] == "kir-standalone-transport/2"
    return materialization, artifact


def select(data, kind):
    return next(record["preview"] for record in data["surfaces"] if record["preview"]["surface_kind"] == kind)


def source_row(data, key):
    return next(row for row in data["source"]["operations"] if row["output_key"] == key)


def test_without_optin_preserves_old_shape_and_never_invokes_surface_derivation(fixture, monkeypatch):
    materialization, with_surfaces = fixture
    from kir.viewer import live_scene
    # The codec includes timing_ms. Hold THAT existing immutable result fixed
    # instead of accidentally demanding cross-run rebuild determinism.
    monkeypatch.setattr(live_scene, "scene_from_programs", lambda *_a, **_k: (with_surfaces.scene_bytes, {}))
    monkeypatch.setattr(reference_surfaces, "preview_reference_surfaces", lambda *a, **k: pytest.fail("surface derivation without opt-in"))
    old = export_standalone_scene(materialization)
    explicit_empty = export_standalone_scene(materialization, consumer_capabilities=[])
    assert old.dumps() == explicit_empty.dumps()
    assert old.scene_bytes == with_surfaces.scene_bytes
    assert old.to_dict()["schema"] == "kir-standalone-display/1"
    assert "surfaces" not in old.to_dict() and "surface_refusals" not in old.to_dict()
    loaded = load_display_artifact(old.dumps().encode())
    assert loaded.transport["schema"] == "kir-standalone-transport/1"
    assert "surface_payloads" not in loaded.transport


@pytest.mark.parametrize("fault", ["stale_hash", "missing_op", "wrong_kind", "later_level", "duplicate", "reverse"])
def test_resigning_does_not_hide_invalid_level_dependency_links(fixture, fault):
    data = fixture[1].to_dict()
    preview = select(data, "wall_axis_surface")
    dependencies = preview["source"]["dependencies"]
    if fault == "stale_hash":
        dependencies[0]["operation_sha256"] = "f" * 64
    elif fault == "missing_op":
        dependencies[0]["op_id"] = "f" * 64
    elif fault in {"wrong_kind", "later_level"}:
        row = source_row(data, "floor" if fault == "wrong_kind" else "late")
        dependencies[0] = {"op_id": row["op_id"], "operation_sha256": row["operation_sha256"]}
    elif fault == "duplicate":
        dependencies[1] = deepcopy(dependencies[0])
    else:
        dependencies.reverse()
    with pytest.raises(DisplayInputRefusal, match="dependency identity/digest/order"):
        load_display_artifact(resign(data))


@pytest.mark.parametrize("fault", ["operation", "operation_hash", "whole_plan", "version", "units", "space", "claims"])
def test_resigned_surface_source_policy_and_claims_cannot_be_rebound(fixture, fault):
    data = fixture[1].to_dict()
    preview = select(data, "floor_datum_surface")
    if fault == "operation":
        preview["source"]["op_id"] = source_row(data, "wall")["op_id"]
    elif fault == "operation_hash":
        preview["source"]["operation_sha256"] = source_row(data, "wall")["operation_sha256"]
    elif fault == "whole_plan":
        preview["source"]["compiler_plan_digest"] = "f" * 64
    elif fault == "version":
        preview["source"]["ir_version"] = "unsupported"
    elif fault == "units":
        preview["units"] = "m"
    elif fault == "space":
        preview["mesh_space"] = "scene_relative"
    else:
        preview["claims"]["native_equivalence"] = "verified"
    with pytest.raises(DisplayInputRefusal):
        load_display_artifact(resign(data))


@pytest.mark.parametrize("fault", ["missing", "duplicate", "result_and_refusal"])
def test_every_direct_subject_has_exactly_one_surface_outcome(fixture, fault):
    data = fixture[1].to_dict()
    record = next(row for row in data["surfaces"] if row["preview"]["surface_kind"] == "floor_datum_surface")
    if fault == "missing":
        data["surfaces"].remove(record)
    elif fault == "duplicate":
        data["surfaces"].append(deepcopy(record))
    else:
        data["surface_refusals"].append({"display_id": record["display_id"], "code": "refused", "detail": "contradiction"})
    with pytest.raises(DisplayInputRefusal):
        load_display_artifact(resign(data))


@pytest.mark.parametrize("fault", ["missing_capability", "unknown_capability", "missing_requirement", "old_schema"])
def test_display2_never_silently_downgrades_its_capability_contract(fixture, fault):
    data = fixture[1].to_dict()
    if fault == "missing_capability":
        data["consumer_contract"]["declared_capabilities"] = []
    elif fault == "unknown_capability":
        data["consumer_contract"]["declared_capabilities"].append("invented_surface_capability")
    elif fault == "missing_requirement":
        data["consumer_contract"]["required_proxy_capabilities"] = []
    else:
        data["schema"] = "kir-standalone-display/1"
    with pytest.raises(DisplayInputRefusal):
        load_display_artifact(resign(data))


@pytest.mark.parametrize("fault", ["index_bool", "index_float", "index_range", "index_duplicate", "vertex_bool", "vertex_string", "empty"])
def test_surface_mesh_shape_and_scalar_types_are_not_guessed(fixture, fault):
    data = fixture[1].to_dict()
    mesh = select(data, "floor_datum_surface")["mesh"]
    if fault == "index_bool":
        assert mesh["triangles"][0][0] == 0
        mesh["triangles"][0][0] = False  # Still a distinct valid index numerically; type must refuse it.
    elif fault == "index_float":
        mesh["triangles"][0][0] = 0.0
    elif fault == "index_range":
        mesh["triangles"][0][0] = len(mesh["vertices_mm"])
    elif fault == "index_duplicate":
        mesh["triangles"][0] = [0, 0, 1]
    elif fault == "vertex_bool":
        mesh["vertices_mm"][0][0] = True
    elif fault == "vertex_string":
        mesh["vertices_mm"][0][0] = "1000"
    else:
        mesh["triangles"] = []
    with pytest.raises(DisplayInputRefusal):
        load_display_artifact(resign(data))


@pytest.mark.parametrize("number", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_json_is_rejected_before_digest_checks(fixture, number):
    data = fixture[1].to_dict()
    select(data, "wall_axis_surface")["mesh"]["vertices_mm"][0][0] = number
    with pytest.raises(DisplayInputRefusal, match="nonfinite"):
        load_display_artifact(json.dumps(data, allow_nan=True).encode())


def test_surface_overlay_cannot_hide_a_known_body_after_full_scene_resigning(fixture):
    data = fixture[1].to_dict()
    row = next(row for row in data["scene"]["records"] if row["display_id"] == source_row(data, "wall")["display_id"])
    assert row["fidelity"] == "no_body"
    raw = bytearray(base64.b64decode(data["scene"]["base64"]))
    header_length = struct.unpack_from("<I", raw, 8)[0]
    header = json.loads(raw[12:12 + header_length])
    span = next(item for item in header["buffers"] if item["name"] == "elem_fidelity")
    raw[12 + header_length + span["offset"] + row["scene_element_index"]] = 2
    row.update(fidelity="box_only", fidelity_code=2)
    data["scene"].update(base64=base64.b64encode(raw).decode(), sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(DisplayInputRefusal, match="cannot replace a known body"):
        load_display_artifact(resign(data))


@pytest.mark.parametrize("stale", ["preview", "artifact"])
def test_mesh_changes_require_both_integrity_layers(fixture, stale):
    data = fixture[1].to_dict()
    preview = select(data, "floor_datum_surface")
    preview["mesh"]["vertices_mm"][0][2] += 1
    if stale == "preview":
        raw = resign(data, previews=False)
    else:
        preview["preview_digest"] = _hash({key: value for key, value in preview.items() if key != "preview_digest"})
        raw = _canonical(data).encode()
    with pytest.raises(DisplayInputRefusal, match="digest differs"):
        load_display_artifact(raw)


def test_floor_has_only_one_level_dependency_even_when_second_link_is_otherwise_valid(fixture):
    data = fixture[1].to_dict()
    preview = select(data, "floor_datum_surface")
    high = source_row(data, "high")
    preview["source"]["dependencies"].append({"op_id": high["op_id"], "operation_sha256": high["operation_sha256"]})
    with pytest.raises(DisplayInputRefusal):
        load_display_artifact(resign(data))


def test_inert_loader_does_not_recompute_floor_region_from_source_hashes(fixture):
    data = fixture[1].to_dict()
    preview = select(data, "floor_datum_surface")
    original = preview["mesh"]
    actual_triangles = [Polygon([original["vertices_mm"][i][:2] for i in triangle]) for triangle in original["triangles"]]
    actual_region = unary_union(actual_triangles)
    hole = Polygon([[101000, -19000], [102000, -19000], [102000, -18000], [101000, -18000]])
    assert actual_region.intersection(hole).area == 0
    # Consistently resigned, finite but false mesh: fills the hole. The inert
    # format does not retain/replay a full source program; do not call loading
    # proof of geometric derivation or native equivalence.
    preview["mesh"] = {"vertices_mm": [[100000, -20000, 4300], [110000, -20000, 4300],
        [110000, -14000, 4300], [100000, -14000, 4300]], "triangles": [[0, 1, 2], [0, 2, 3]]}
    loaded = load_display_artifact(resign(data))
    assert loaded.transport["validation"] == "inert_bytes_schema_addresses_not_native_execution"
    assert loaded.data["claims"]["digest_scope"] == "byte_integrity_not_rebuild_determinism_or_execution_proof"
    filled = Polygon([point[:2] for point in preview["mesh"]["vertices_mm"]])
    assert filled.intersection(hole).area == 1_000_000


def test_loaded_surface_payload_is_detached_from_the_input_artifact(fixture):
    data = fixture[1].to_dict()
    loaded = load_display_artifact(resign(data))
    original = loaded.transport["surface_payloads"][0]["sha256"]
    data["surfaces"][0]["preview"]["mesh"]["vertices_mm"].clear()
    assert loaded.transport["surface_payloads"][0]["sha256"] == original
    with pytest.raises(TypeError):
        loaded.data["surfaces"][0]["preview"]["mesh"]["vertices_mm"][0][0] = 0
