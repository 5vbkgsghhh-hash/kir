"""Explicit /2 surfaces preserve authoring, legacy bytes and dependency identity."""
import pytest

from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, _hash, output_id
from kir.project_store import ProjectStore
from kir.viewer import standalone_export as exporter, standalone as reader
from kir.viewer.reference_surfaces import SURFACE_CAPABILITY


@pytest.fixture
def materialized():
    oid = lambda key: output_id("reference-demo", "i", key)
    level = lambda key: {"by": "ref", "value": oid(key)}
    outputs = {
        "low": {"op": "create_level", "elev_mm": -1200., "name": "Low"},
        "high": {"op": "create_level", "elev_mm": 3400., "name": "High"},
        "wall": {"op": "create_wall", "p0_mm": [100000., -50000.], "p1_mm": [106000., -50000.],
                 "level": level("low"), "base_offset_mm": 100., "top_level": level("high"),
                 "top_offset_mm": -300., "height_mm": 800.},
        "floor": {"op": "create_floor_by_contour", "level": level("high"), "height_offset_mm": -400.,
                  "contour": {"outer": {"shape": "poly", "points_mm": [
                      [100000., -50000.], [106000., -50000.], [106000., -44000.], [100000., -44000.]]},
                      "holes": [{"shape": "poly", "points_mm": [
                          [102000., -48000.], [104000., -48000.], [104000., -46000.], [102000., -46000.]]}]}},
    }
    project = ProjectRevision("reference-demo", [ModuleDefinition("m")], [ModuleInstance("i", "m", outputs)])
    return materialize_project(project, {})


def test_explicit_capability_preserves_legacy_export_and_source_bytes(materialized, monkeypatch):
    program = materialized.to_program()
    original = materialized.project.dumps()
    legacy = exporter.export_standalone_scene(materialized)
    # Existing codec timing_ms differs between independent scene builds. Hold
    # the upstream snapshot fixed to test the /1 opt-in compatibility law.
    import kir.viewer.live_scene
    monkeypatch.setattr(kir.viewer.live_scene, "scene_from_programs", lambda *a, **k: (legacy.scene_bytes, {}))
    def forbidden(*args, **kwargs):
        pytest.fail("legacy export evaluated a surface")
    import kir.viewer.reference_surfaces as surfaces
    with monkeypatch.context() as m:
        m.setattr(surfaces, "preview_reference_surfaces", forbidden)
        assert exporter.export_standalone_scene(materialized).dumps() == legacy.dumps()
    modern = exporter.export_standalone_scene(materialized, consumer_capabilities=[SURFACE_CAPABILITY])
    data = modern.to_dict()
    assert data["schema"] == exporter.DISPLAY_SCHEMA_V2 and modern.scene_bytes == legacy.scene_bytes
    assert data["source"]["program_sha256"] == _hash(program)
    assert materialized.to_program() == program and materialized.project.dumps() == original
    assert len(data["surfaces"]) == 2 and not data["surface_refusals"]
    source = {row["output_key"]: row for row in data["source"]["operations"]}
    assert source["wall"]["display_status"] == "base_scene_record"
    assert source["floor"]["display_status"] == "authored_surface_record"
    assert {row["output_key"] for row in data["omissions"]} == {"low", "high"}
    previews = {row["preview"]["surface_kind"]: row["preview"] for row in data["surfaces"]}
    assert {point[2] for point in previews["wall_axis_surface"]["mesh"]["vertices_mm"]} == {-1100., 3100.}
    assert {point[2] for point in previews["floor_datum_surface"]["mesh"]["vertices_mm"]} == {3000.}
    assert all(row["preview"]["source"]["compiler_plan_digest"] == data["source"]["plan_digest"] for row in data["surfaces"])
    assert reader.load_display_artifact(legacy.dumps().encode()).transport["schema"] == reader.TRANSPORT_SCHEMA
    loaded = reader.load_display_artifact(modern.dumps().encode())
    assert loaded.transport["schema"] == reader.TRANSPORT_SCHEMA_V2
    assert len(loaded.transport["surface_payloads"]) == 2


def test_loading_and_store_status_never_rederive_reference_geometry(materialized, tmp_path, monkeypatch):
    artifact = exporter.export_standalone_scene(materialized, consumer_capabilities=[SURFACE_CAPABILITY])
    store = ProjectStore.create(tmp_path / "project.sqlite", materialized.project)
    raw = artifact.dumps().encode()
    before = store.path.read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("inert load/status ran a compiler or preview producer")
    import kir.compiler
    import kir.viewer.reference_surfaces
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    monkeypatch.setattr(kir.viewer.reference_surfaces, "preview_reference_surfaces", forbidden)
    loaded = reader.load_display_artifact(raw)
    status = reader._project_status(loaded, ProjectStore.open(store.path))
    assert status["state"] == "available" and status["source_binding"] == "matched_immutable_authoring_snapshot"
    assert store.path.read_bytes() == before and loaded.original_bytes == raw


def test_plan_drift_is_a_named_surface_refusal_not_a_stale_sheet(materialized, monkeypatch):
    import kir.viewer.reference_surfaces as surfaces
    original = surfaces.preview_reference_surfaces
    def stale(*args, **kwargs):
        result = original(*args, **kwargs)
        for preview in result["previews"]:
            preview["source"]["compiler_plan_digest"] = "f" * 64
            preview["preview_digest"] = _hash({k: v for k, v in preview.items() if k != "preview_digest"})
        return result
    monkeypatch.setattr(surfaces, "preview_reference_surfaces", stale)
    artifact = exporter.export_standalone_scene(materialized, consumer_capabilities=[SURFACE_CAPABILITY])
    data = artifact.to_dict()
    assert not data["surfaces"]
    assert {row["code"] for row in data["surface_refusals"]} == {"materialization_plan_mismatch"}
    assert len(data["surface_refusals"]) == 2
    assert reader.load_display_artifact(artifact.dumps().encode())


def test_named_unknown_level_keeps_omission_and_explicit_refusal(materialized):
    from dataclasses import replace
    project = materialized.project
    instance = project.instances[0]
    outputs = []
    for output in instance.outputs:
        if output.key == "floor":
            op = output.to_dict()["operation"]
            op["level"] = {"by": "name", "value": "High"}
            output = replace(output, operation=op)
        outputs.append(output)
    candidate = project.replace_instance(replace(instance, outputs=outputs), expected_revision=project.revision_id)
    artifact = exporter.export_standalone_scene(materialize_project(candidate, {}), consumer_capabilities=[SURFACE_CAPABILITY])
    data = artifact.to_dict()
    floor = next(row for row in data["source"]["operations"] if row["output_key"] == "floor")
    refusal = next(row for row in data["surface_refusals"] if row["display_id"] == floor["display_id"])
    assert refusal["code"] == "unresolved_level" and floor["display_status"] == "omitted"
    assert next(row for row in data["omissions"] if row["display_id"] == floor["display_id"])["code"] == refusal["code"]
    assert reader.load_display_artifact(artifact.dumps().encode())
