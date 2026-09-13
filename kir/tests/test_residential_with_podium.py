"""Real composed authoring/history/native geometry/scene/code-generation seam."""
from __future__ import annotations

import base64
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys

import pytest

from examples import residential_with_podium as example
from kir.geometry_materialization import materialize_project
from kir.occt_geometry import GeometryRefusal
from kir.project import NamedOutput, ProjectError, ProjectRevision, output_id, _canonical, _hash
from kir.project_diff import diff_projects
from kir.project_store import ProjectStore, StoreConflict, StoreExists
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
from kir.viewer.standalone import load_display_artifact
from kir.viewer.standalone_export import export_standalone_scene


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def composed():
    pytest.importorskip("OCP")
    return example.workflow()


def persist(path, composed, stage="refined"):
    revisions, bundle = composed
    store = ProjectStore.create(path, revisions[0])
    store.upgrade_schema("kir-project-store/2", expected_revision=revisions[0].revision_id)
    for index, revision in enumerate(revisions[1:example.STAGES.index(stage) + 1], 1):
        store.commit(revision, expected_revision=revision.parent_revision,
                     assets=[bundle] if index == 2 else [])
    return store


def fresh(code, *args):
    return subprocess.run([sys.executable, "-c", code, *map(str, args)], text=True,
                          capture_output=True, cwd=ROOT, timeout=45,
                          env=dict(os.environ, PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))


def decode_scene(blob):
    from kir.viewer.codec import SCENE_MAGIC
    start = len(SCENE_MAGIC) + 4
    length = struct.unpack_from("<I", blob, len(SCENE_MAGIC))[0]
    header = json.loads(blob[start:start + length])
    body = start + length
    streams = {row["name"]: blob[body + row["offset"]:body + row["offset"] + row["length"]]
               for row in header["buffers"]}
    return header, streams, streams["ids"].decode().splitlines()


def assert_podium_is_the_visible_derived_mesh(blob, program):
    header, streams, ids = decode_scene(blob)
    identifier = output_id(example.towers.PROJECT_ID, example.PODIUM_INSTANCE, example.PODIUM_OUTPUT)
    mesh = next(op["mesh"] for op in program["ops"] if op["id"] == identifier)
    position = ids.index("p1/" + identifier)
    assert streams["elem_kind"][position] == header["kinds"]["mesh"]
    slot = struct.unpack_from("<I", streams["elem_slot"], position * 4)[0]
    first_vertex, last_vertex = struct.unpack_from("<II", streams["mesh_vofs"], slot * 4)
    first_triangle, last_triangle = struct.unpack_from("<II", streams["mesh_ofs"], slot * 4)
    vertices = list(struct.iter_unpack("<3f", streams["mesh_vtx"][first_vertex * 12:last_vertex * 12]))
    vertices = [tuple(value + origin for value, origin in zip(point, header["origin_mm"], strict=True))
                for point in vertices]
    triangles = [tuple(index - first_vertex for index in triangle) for triangle in
                 struct.iter_unpack("<3I", streams["mesh_tri"][first_triangle * 12:last_triangle * 12])]
    assert len(vertices) == len(mesh["vertices_mm"])
    assert triangles == [tuple(row) for row in mesh["triangles"]]
    for shown, authored in zip(vertices, mesh["vertices_mm"], strict=True):
        assert shown == pytest.approx(authored, abs=.005, rel=0)  # declared scene f32 precision
    assert max(point[0] for point in vertices) == pytest.approx(67000., abs=.01, rel=0)
    assert min(point[2] for point in vertices) == pytest.approx(-3000.)
    assert max(point[2] for point in vertices) == pytest.approx(0., abs=1e-5)
    return header, ids


def assert_standalone_composition(data, project, program):
    """Artifact/input contract; actual WebGL rendering is tested separately."""
    load_display_artifact(_canonical(data).encode())
    assert data["source"]["project_revision_id"] == project.revision_id
    assert data["source"]["program_sha256"] == _hash(program)
    assert data["consumer_contract"]["required_proxy_capabilities"] == [REQUIRED_CONSUMER_CAPABILITY]
    header, base_ids = assert_podium_is_the_visible_derived_mesh(base64.b64decode(data["scene"]["base64"]), program)
    proxies = {row["display_id"]: row["preview"] for row in data["proxies"]}
    operations = {op["id"]: op for op in program["ops"]}
    sources = {row["op_id"]: row for row in data["source"]["operations"]}
    expected_proxies = set()
    for instance in project.instances:
        if not (instance.key.startswith("tower-") and instance.parameters["representation"] == "concept"):
            continue
        identifier = output_id(project.project_id, instance.key, "concept-volume")
        expected_proxies.add("p1/" + identifier)
        operation = operations[identifier]
        assert operation == {**instance.outputs[0].to_dict()["operation"], "id": identifier}
        assert operation["op"] == "create_solid_blend" and "mesh" not in operation
        assert sources[identifier]["operation_sha256"] == _hash(operation)
        assert sources[identifier]["module_definition_digest"] == instance.module_digest
        proxy = proxies["p1/" + identifier]
        assert proxy["source"]["operation_sha256"] == _hash(operation)
        assert proxy["claims"]["native_equivalence"] == "unverified"
        assert proxy["claims"]["clash_eligibility"] == "none"
        vertices = proxy["mesh"]["vertices_mm"]
        low, high = vertices[:4], vertices[-4:]
        for profile, ring, z in (("profile", low, operation["base_z_mm"]),
                                  ("profile_top", high, operation["base_z_mm"] + operation["height_mm"])):
            for authored, shown in zip(operation[profile]["outer"]["points_mm"], ring, strict=True):
                assert shown == pytest.approx([*authored, z], abs=1e-6, rel=0)
        a = [low[1][axis] - low[0][axis] for axis in (0, 1)]
        b = [high[1][axis] - high[0][axis] for axis in (0, 1)]
        assert math.hypot(*b) / math.hypot(*a) == pytest.approx(.82)
        assert math.degrees(math.atan2(b[1], b[0]) - math.atan2(a[1], a[0])) == pytest.approx(
            instance.parameters["twist_deg"], abs=1e-6)
    assert set(proxies) == expected_proxies
    assert not expected_proxies.intersection(base_ids)  # Separate display policy, not disguised native geometry.
    assert {row["op"] for row in data["omissions"]} == (set() if len(expected_proxies) == 3
        else {"create_level", "create_floor_by_contour"})
    assert data["claims"]["browser_rendering"] == "not_observed"
    return header, set(base_ids) | expected_proxies


def test_history_keeps_original_root_upgrade_and_recipe_bytes_explicit(composed):
    revisions, bundle = composed
    root, upgraded, podium, refined, changed = revisions
    assert root.dumps() == example.towers.concept().dumps()
    assert [item.schema for item in revisions] == ["kir-authoring-project/1"] + ["kir-authoring-project/2"] * 4
    assert [item.parent_revision for item in revisions] == [None] + [item.revision_id for item in revisions[:-1]]
    assert [len(item.addressed_outputs()) for item in revisions] == [3, 3, 4, 24, 24]
    assert upgraded.to_program() == root.to_program()
    for revision in revisions:
        assert revision.modules[0].to_dict() == root.modules[0].to_dict()
    assert podium.instances[:3] == root.instances
    body = podium.geometry_references()[0][1]
    assert body.geometry.bundle_sha256 == bundle.digest
    assert "mesh" not in body.operation
    assert bundle.to_dict()["manifest"]["recipe"] == podium.modules[1].recipe.to_dict()


def test_section_edits_preserve_other_outputs_assets_ids_and_name_losses(composed):
    revisions, bundle = composed
    podium, refined, changed = revisions[2:]
    for revision in (refined, changed):
        assert [i.to_dict() for i in revision.instances[1:]] == [i.to_dict() for i in podium.instances[1:]]
        # 🔴 A LOOSE RECORD WAS REMOVED ON 2026-09-07, AND THE PIN WAS TURNED
        # TOWARD THIS. The generator used to place a four-field dict here: it
        # DECLARED kinship, but the typed view rejected it by name
        # (`legacy_unbound_refinement`) — no schema, no source, no members.
        # There were two carriers of one fact, a readable one and an
        # unreadable one, and it was the unreadable one that kept getting
        # lost — silently, on every repeated call of the generator. Now
        # kinship is written by exactly one place (`kir.project_refinement`),
        # and the raw generator does not declare it at all. The pin guards
        # exactly this: an empty spot instead of a falsehood, and the
        # preserved source address.
        assert "refinement" not in revision.instances[0].metadata, (
            "сырой генератор не вправе объявлять родство: источника он не знает")
        assert revision.instances[0].metadata["refines"], "адрес источника остаётся"
        assert revision.geometry_references()[0][1].geometry.bundle_sha256 == bundle.digest
    assert [row[2] for row in changed.addressed_outputs()] == [row[2] for row in refined.addressed_outputs()]
    diff = diff_projects(refined, changed)
    untouched = {identifier for instance, _, identifier in refined.addressed_outputs() if instance.key != "tower-a"}
    assert untouched <= set(diff.unchanged)
    assert not diff.added and not diff.removed
    before = {output.key: output.operation for output in refined.instances[0].outputs}
    after = {output.key: output.operation for output in changed.instances[0].outputs}
    assert before["storey-02-level"]["elev_mm"] == 3600
    assert after["storey-02-level"]["elev_mm"] == 4200
    assert after["storey-03-slab"]["contour"]["outer"]["points_mm"][1][0] == 12200


def test_native_podium_bounds_atrium_gap_and_section_shaft_are_geometrically_separate(composed):
    from OCP.BRepClass3d import BRepClass3d_SolidClassifier
    from OCP.gp import gp_Pnt
    from OCP.TopAbs import TopAbs_IN, TopAbs_ON, TopAbs_OUT

    revisions, bundle = composed
    facts = bundle.measure()
    assert facts["solid_count"] == 1 and facts["face_count"] == 7
    assert facts["bbox_min_mm"] == pytest.approx([-4000, -5000, -3000], abs=1e-5)
    assert facts["bbox_max_mm"] == pytest.approx([67000, 14000, 0], abs=1e-5)
    root = revisions[0]
    radius = bundle.to_dict()["manifest"]["parameters"]["atrium_radius_mm"]
    assert root.instances[0].parameters["width_mm"] < 19000 - radius < 19000 + radius < root.instances[1].parameters["x_mm"]
    assert all(output.operation["base_z_mm"] == 0 for item in root.instances for output in item.outputs)
    slab = next(output.operation for output in revisions[-1].instances[0].outputs if output.key == "storey-03-slab")
    shaft = slab["contour"]["holes"][0]["points_mm"]
    assert max(point[0] for point in shaft) < slab["contour"]["outer"]["points_mm"][1][0]
    assert max(point[0] for point in shaft) < 19000 - radius
    body = bundle.read_body()
    def state(point):
        return BRepClass3d_SolidClassifier(body, gp_Pnt(*point), .01).State()
    assert state((19000, 4500, -1500)) == TopAbs_OUT  # actual open atrium, not metadata
    assert state((19000 + radius + 100, 4500, -1500)) == TopAbs_IN
    for x in (7000, 31000, 55000):
        assert state((x, 4500, -1500)) == TopAbs_IN  # body beneath each tower
    assert state((7000, 4500, 0)) == TopAbs_ON
    assert state((7000, 4500, 1)) == TopAbs_OUT


@pytest.mark.parametrize("stage_index", [2, 3, 4])
def test_materialized_stages_show_podium_and_all_remaining_concept_towers(composed, stage_index):
    revisions, bundle = composed
    result = materialize_project(revisions[stage_index], {bundle.digest: bundle})
    program = result.to_program()
    before = result.project.dumps(), bundle.dumps(), _canonical(program)
    artifact = export_standalone_scene(result, consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY])
    header, ids = assert_standalone_composition(artifact.to_dict(), result.project, program)
    for item in result.project.instances:
        if item.key.startswith("tower-") and item.parameters["representation"] == "concept":
            assert "p1/" + output_id(result.project.project_id, item.key, "concept-volume") in ids
    assert header["counts"]["mesh"] == 1
    assert (result.project.dumps(), bundle.dumps(), _canonical(result.to_program())) == before
    report = example.publication_report(result)
    assert all(item["ok"] for item in report["compilation"])
    assert [item["revit_version"] for item in report["compilation"]] == ["2023", "2026"]
    assert all(item["live_execution"] == "not_run" for item in report["compilation"])


def test_fresh_process_reopens_continues_then_materializes_scene_and_both_compilers(tmp_path, composed):
    path = tmp_path / "residential.sqlite"
    store = persist(path, composed)
    before = store.head()
    child = fresh("""
import base64, json, sys
from examples.residential_with_podium import continue_section, materialize_saved, publication_report
from kir.project_store import ProjectStore
from kir.viewer.blend_preview import REQUIRED_CONSUMER_CAPABILITY
from kir.viewer.standalone_export import export_standalone_scene
store = ProjectStore.open(sys.argv[1], readonly=False)
changed = continue_section(store, expected_revision=sys.argv[2])
result = materialize_saved(store)
artifact = export_standalone_scene(result, consumer_capabilities=[REQUIRED_CONSUMER_CAPABILITY])
print(json.dumps({'project': changed.to_dict(), 'program': result.to_program(),
                  'display': artifact.to_dict(), 'report': publication_report(result)}))
""", path, before.revision_id)
    assert child.returncode == 0, child.stderr
    data = json.loads(child.stdout)
    changed = ProjectRevision.from_dict(data["project"])
    assert changed.dumps() == composed[0][-1].dumps()
    assert store.head().dumps() == changed.dumps()
    assert store.get_asset(composed[1].digest).dumps() == composed[1].dumps()
    _, ids = assert_standalone_composition(data["display"], changed, data["program"])
    for key in ("tower-b", "tower-c"):
        assert "p1/" + output_id(changed.project_id, key, "concept-volume") in ids
    assert all(item["ok"] for item in data["report"]["compilation"])
    assert [p.dumps() for p in store.history()] == [p.dumps() for p in composed[0]]


def test_legacy_binary_alone_cannot_qualify_the_complete_composition(composed):
    from kir.viewer.live_scene import scene_from_programs
    revisions, bundle = composed
    result = materialize_project(revisions[-1], {bundle.digest: bundle})
    program = result.to_program()
    blob, _ = scene_from_programs([program])
    _, legacy_ids = assert_podium_is_the_visible_derived_mesh(blob, program)
    concept_ids = {"p1/" + output_id(result.project.project_id, key, "concept-volume")
                   for key in ("tower-b", "tower-c")}
    assert concept_ids.isdisjoint(legacy_ids)
    without_capability = export_standalone_scene(result).to_dict()
    other_header, other_streams, other_ids = decode_scene(base64.b64decode(without_capability["scene"]["base64"]))
    original_header, original_streams, _ = decode_scene(blob)
    # Separate codec builds include timing metadata; geometry/addresses stay identical.
    assert other_header["origin_mm"] == original_header["origin_mm"]
    assert other_streams == original_streams and other_ids == legacy_ids
    assert without_capability["proxies"] == []
    missing_concepts = {row["display_id"] for row in without_capability["omissions"]
                        if row["code"] == "capability_required"}
    assert missing_concepts == concept_ids
    assert all(row["op"] == "create_solid_blend" for row in without_capability["omissions"]
               if row["display_id"] in concept_ids)
    assert len([row for row in without_capability["omissions"]
                if row["op"] == "create_floor_by_contour" and row["code"] == "no_direct_scene_record"]) == 3


@pytest.mark.parametrize("field", ["source", "environment_digest"])
def test_changed_tower_recipe_refuses_continuation_without_head_or_asset_change(tmp_path, composed, field):
    store = persist(tmp_path / "pin.sqlite", composed)
    previous = store.head()
    module = previous.modules[0]
    value = module.recipe.source + "\n# saved different source" if field == "source" else "a" * 64
    changed_module = replace(module, recipe=replace(module.recipe, **{field: value}))
    mismatched = previous.revise(expected_revision=previous.revision_id,
        modules=[changed_module, previous.modules[1]],
        instances=[replace(item, module_digest=None) if item.module_key == module.key else item
                   for item in previous.instances])
    store.commit(mismatched, expected_revision=previous.revision_id)
    with pytest.raises(ProjectError, match="generator definition"):
        example.continue_section(store, expected_revision=mismatched.revision_id)
    assert store.head().dumps() == mismatched.dumps()
    assert store.get_asset(composed[1].digest).dumps() == composed[1].dumps()


def test_failed_body_creation_and_stale_edit_never_advance_previous_store(tmp_path, composed, monkeypatch):
    root, upgraded = composed[0][:2]
    store = ProjectStore.create(tmp_path / "previous.sqlite", root)
    store.upgrade_schema("kir-project-store/2", expected_revision=root.revision_id)
    store.commit(upgraded, expected_revision=root.revision_id)
    def fail(_parameters):
        raise GeometryRefusal("kernel_build_failed", "controlled native failure")
    monkeypatch.setattr(example, "build_podium_body", fail)
    with pytest.raises(GeometryRefusal, match="kernel_build_failed"):
        example.add_podium(store.head())
    assert store.head().dumps() == upgraded.dumps()
    assert len(store.history()) == 2
    with pytest.raises(StoreConflict):
        example.continue_section(store, expected_revision=root.revision_id)
    assert store.head().dumps() == upgraded.dumps()
    destination = tmp_path / "not_created.sqlite"
    with pytest.raises(GeometryRefusal):
        example.create_store(destination)
    assert not destination.exists()


@pytest.mark.parametrize("case", ["shifted_tower", "recipe", "refined_tower", "extra_output"])
def test_fixed_podium_recipe_refuses_changed_layout_before_native_build(composed, monkeypatch, case):
    project = composed[0][1]
    if case == "shifted_tower":
        tower = project.instances[2]
        moved = example.towers.instance(tower.key, dict(tower.parameters, x_mm=90000))
        project = project.replace_instance(moved, expected_revision=project.revision_id)
    elif case == "recipe":
        module = project.modules[0]
        project = project.revise(expected_revision=project.revision_id,
            modules=[replace(module, recipe=replace(module.recipe, source="another tower recipe"))],
            instances=[replace(item, module_digest=None) for item in project.instances])
    elif case == "refined_tower":
        project = example.towers.develop_section(project)
    else:
        tower = project.instances[2]
        modified = replace(tower, outputs=[*tower.outputs, NamedOutput("extra-level",
                            {"op": "create_level", "elev_mm": 0, "name": "Extra"})])
        project = project.replace_instance(modified, expected_revision=project.revision_id)
    before = project.dumps()
    calls = []
    def forbidden(_parameters):
        calls.append("native build")
        raise AssertionError("unsupported fixed layout must refuse before native work")
    monkeypatch.setattr(example, "build_podium_body", forbidden)
    with pytest.raises(GeometryRefusal, match="example_scope_mismatch"):
        example.add_podium(project)
    assert calls == [] and project.dumps() == before


def test_fixed_layout_allows_project_level_metadata_intent_and_parent_changes(composed):
    project = composed[0][1]
    revised = project.revise(expected_revision=project.revision_id, intent="Review the same geometry",
                             metadata={"review_note": "no geometry was changed"})
    with_podium, _ = example.add_podium(revised)
    assert with_podium.parent_revision == revised.revision_id
    assert with_podium.intent == revised.intent and with_podium.metadata == revised.metadata


def test_existing_file_is_not_adopted_or_overwritten(tmp_path, composed, monkeypatch):
    path = tmp_path / "existing.sqlite"
    store = persist(path, composed)
    before = path.read_bytes()
    monkeypatch.setattr(example, "workflow", lambda: composed)
    with pytest.raises(StoreExists):
        example.create_store(path)
    assert path.read_bytes() == before
    assert store.head().dumps() == composed[0][3].dumps()


def test_importing_the_composed_example_and_loading_its_history_need_no_ocp(tmp_path, composed):
    path = tmp_path / "inert.sqlite"
    store = persist(path, composed)
    child = fresh("""
import importlib.abc, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('inert example import/history entered native backend')
sys.meta_path.insert(0, NoOcp())
from examples import residential_with_podium
from kir.project_store import ProjectStore
store = ProjectStore.open(sys.argv[1])
assert len(store.history()) == 4
print(store.head().revision_id)
""", path)
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == store.head().revision_id


def test_cli_creates_an_explicit_history_and_reports_without_csharp(tmp_path):
    pytest.importorskip("OCP")
    path = tmp_path / "cli.sqlite"
    child = fresh("from examples.residential_with_podium import main; raise SystemExit(main())",
                  "--store", path, "--stage", "changed")
    assert child.returncode == 0, child.stderr
    report = json.loads(child.stdout)
    assert report["asset_durability"] == "sqlite_store"
    assert [item["stage"] for item in report["history"]] == list(example.STAGES)
    assert len(report["geometry_assets"]) == 1
    assert report["publication"]["scene"]["mesh_shown"] >= 1
    assert all(item["ok"] for item in report["publication"]["compilation"])
    assert not any("csharp" in item for item in report["publication"]["compilation"])
    assert ProjectStore.open(path).head().to_dict() == report["project"]
