"""Read-only joins of a saved display file to one Store snapshot.

🔴 13.09.2026. These checks used to reach the join through the loopback
inspector's `/project-status.json`, and one of them drove the browser panel
through a Node DOM stub. The window was removed by the owner's word; the join
it called was NOT — it is what tells a reader whether a saved scene still
describes the project it names. The server-only assertions (allowlist, 404/405,
Host check, the panel) went with the window; every claim about the JOIN is kept
and now calls `_project_status` directly.

This is not a browser/WebGL test or live native-model observation.
"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kir.geometry_materialization import materialize_project
from kir.project import BodyRepresentation, ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision, _hash
from kir.project_store import ProjectStore
from kir.viewer import standalone
from kir.viewer.standalone_export import export_standalone_scene


ROOT = Path(__file__).resolve().parents[3]


def display(project):
    return export_standalone_scene(materialize_project(project, {})).dumps().encode()


@pytest.fixture
def case(tmp_path):
    project = ProjectRevision("status-project", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
        NamedOutput("L1", {"op": "create_level", "elev_mm": 0, "name": "First"}),
        NamedOutput("L2", {"op": "create_level", "elev_mm": 3000, "name": "Second"}),
    ])])
    store = ProjectStore.create(tmp_path / "project.sqlite", project)
    raw = display(project)
    for name in ("index.html", "app.js", "app.css"):
        (tmp_path / name).write_text("static snapshot", encoding="utf-8")
    return project, store, raw, tmp_path


def status_for(raw, store=None):
    """The join itself, with no transport around it."""
    return standalone._project_status(standalone.load_display_artifact(raw), store)


def resign(data):
    # Keep internal display omission declarations consistent so the adversarial
    # difference reaches the STORE join, not only the existing artifact loader.
    by_id = {row["display_id"]: row for row in data["source"]["operations"]}
    for omission in data["omissions"]:
        omission.update(by_id[omission["display_id"]])
    data["artifact_digest"] = _hash({k: v for k, v in data.items() if k != "artifact_digest"})
    return json.dumps(data).encode()


def test_one_mutable_snapshot_and_frozen_scene_survive_authoring_advance(case, monkeypatch):
    project, writer, raw, root = case
    reader = ProjectStore.open(writer.path)
    original = ProjectStore.status
    reads = []
    def counted(self, **kwargs):
        reads.append(kwargs)
        return original(self, **kwargs)
    monkeypatch.setattr(ProjectStore, "status", counted)
    def forbidden(*args, **kwargs):
        pytest.fail("serving status ran head/per-stream/materialization/compiler work")
    monkeypatch.setattr(ProjectStore, "head", forbidden)
    monkeypatch.setattr(ProjectStore, "level_baseline", forbidden)
    import kir.compiler
    import kir.geometry_materialization
    monkeypatch.setattr(kir.compiler, "compile_program", forbidden)
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    monkeypatch.setattr(kir.geometry_materialization, "materialize_project", forbidden)
    before = writer.path.read_bytes()
    first = status_for(raw, reader)
    assert first["state"] == "available" and first["status"]["authoring"]["revision_id"] == project.revision_id
    assert first["source_binding"] == "matched_immutable_authoring_snapshot"
    assert first["status"]["native"]["live_model_observed"] is False
    assert writer.path.read_bytes() == before and reads == [{"limit": 20}]
    child = project.revise(expected_revision=project.revision_id, metadata={"new": "draft"})
    writer.commit(child, expected_revision=project.revision_id)
    second = status_for(raw, reader)
    assert reads == [{"limit": 20}, {"limit": 20}]
    assert second["displayed_revision_id"] == project.revision_id
    assert second["status"]["authoring"]["revision_id"] == child.revision_id


def test_an_absent_store_is_named_not_looked_up(case):
    _, _, raw, _ = case
    value = status_for(raw)
    assert value["state"] == "not_attached" and value["status"] is None
    assert value["source_binding"] == "not_checked" and value["diagnostic"] is None


@pytest.mark.parametrize("fault", ["revision", "parent", "order", "authored_digest", "module_digest", "operation_digest"])
def test_rehashed_display_claims_must_match_the_real_saved_revision(case, monkeypatch, fault):
    _, writer, raw, root = case
    data = json.loads(raw)
    if fault == "revision": data["source"]["project_revision_id"] = "f" * 64
    elif fault == "parent": data["source"]["parent_revision_id"] = "f" * 64
    elif fault == "order": data["source"]["operations"].reverse()
    else:
        key = {"authored_digest": "authored_output_sha256", "module_digest": "module_definition_digest", "operation_digest": "operation_sha256"}[fault]
        data["source"]["operations"][0][key] = "f" * 64
    changed = resign(data)
    value = status_for(changed, ProjectStore.open(writer.path))
    assert value["state"] == "unavailable" and value["status"] is None


def test_foreign_project_and_replaced_store_never_attach_status_to_scene(case, monkeypatch):
    project, writer, raw, root = case
    other = ProjectRevision("other", project.modules, project.instances)
    foreign = ProjectStore.create(root / "foreign.sqlite", other)
    assert status_for(raw, ProjectStore.open(foreign.path))["diagnostic"] == "display_store_mismatch"
    # ONE handle across the swap, exactly as the server held one: the point is a
    # reader that outlives the file it opened, not a fresh open afterwards.
    reader = ProjectStore.open(writer.path)
    before = status_for(raw, reader)
    assert before["state"] == "available"
    replacement = ProjectStore.create(root / "replacement.sqlite", project)
    writer.path.rename(root / "original-store-retained.sqlite")
    replacement.path.rename(writer.path)  # only test-owned files; both databases retained
    after = status_for(raw, reader)
    assert after["state"] == "unavailable" and after["status"] is None


def test_a_writable_handle_is_refused_by_the_join_itself(case):
    # 🔴 The guard used to stand in `make_server`; with the window gone it stands
    # where it belongs — a display join never takes a writable handle.
    _, writer, raw, _ = case
    with pytest.raises(standalone.DisplayInputRefusal, match="readonly_store_required"):
        status_for(raw, writer)


def test_body_reference_comparison_is_inert_not_geometry_verification():
    # Pure join control: the stored revision is a real typed value, the accessor
    # is a test double. No BRep is fabricated or parsed to test digest equality.
    reference = BodyRepresentation("a" * 64, "b" * 64)
    project = ProjectRevision("body", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
        NamedOutput("body", {"op": "create_directshape", "category": "mass"}, reference)])], schema="kir-authoring-project/2")
    instance, output, oid = project.addressed_outputs()[0]
    row = {"op_id": oid, "display_id": "p1/" + oid, "instance_key": "i", "module_key": "m", "output_key": "body",
        "module_definition_digest": instance.module_digest, "op": "create_directshape",
        "authored_output_sha256": _hash(output.to_dict()), "geometry_reference": reference.to_dict()}
    source = {"project_id": "body", "project_revision_id": project.revision_id, "project_schema": project.schema,
        "parent_revision_id": None, "ir_version": project.ir_version, "operations": [row]}
    snapshot = {"schema": "kir-project-status/1", "store_id": "c" * 32, "project_id": "body",
        "snapshot_scope": "one_local_read_transaction", "read_only": True,
        "native": {"live_model_observed": False, "whole_project_acceptance": "not_established", "streams": []}}
    reader = SimpleNamespace(store_id="c" * 32, project_id="body", status=lambda **_: snapshot, get=lambda _: project)
    validated = SimpleNamespace(data={"source": source}, transport={"artifact_sha256": "d" * 64})
    assert standalone._project_status(validated, reader)["state"] == "available"
    row["geometry_reference"] = BodyRepresentation("e" * 64, "b" * 64).to_dict()
    assert standalone._project_status(validated, reader)["diagnostic"] == "display_store_mismatch"


def test_real_scoped_checkpoint_and_pending_remain_distinct_from_display(case):
    from kir.tests.test_level_update_iteration import first_round, observe_rows
    from kir.revit_level_update import plan_level_elevation_update, prepare_level_update
    from kir.tests.test_revit_level_update import TARGET_ADDRESS, PROTECTED
    from kir.update_submission import bind_level_update_submission
    from kir.saved_execution import SavedExecutionRecord
    from uuid import uuid4

    _, _, _, root = case
    scenario = root / "scope"
    scenario.mkdir()
    source, writer, origin, r1, r2, _ = first_round(scenario)
    baseline = writer.level_baseline(origin.digest)
    observed = observe_rows(source["credentials"], baseline.accepted["after"]["rows"], 10)
    update = plan_level_elevation_update(r1, r2, baseline=baseline, observation=observed,
                                        target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    prepared = prepare_level_update(update, operation_id=str(uuid4()))
    record = SavedExecutionRecord.create_update_new(scenario / "pending.sqlite", prepared,
                                                    bind_level_update_submission(update, prepared))
    writer.reserve_level_update(record, expected_checkpoint=baseline.checkpoint_digest)
    raw = display(r1)
    value = status_for(raw, ProjectStore.open(writer.path))
    assert value["state"] == "available" and value["displayed_revision_id"] == r1.revision_id
    assert value["status"]["authoring"]["revision_id"] == r2.revision_id
    scope, = value["status"]["native"]["streams"]
    assert scope["accepted_scope_revision"] == r1.revision_id
    assert scope["pending"]["proposed_revision"] == r2.revision_id
    assert scope["pending"]["execution"] == "not_established_by_reservation"
    assert scope["not_evaluated"] == ["dependent_geometry", "protected_geometry", "engineering"]


#: 🔴 The panel control that stood here drove `frontend/standalone/src/main.js`
#: through a Node DOM stub: it checked that the window never interpolated HTML
#: and cleared a stale badge. Both the panel and that file were removed with the
#: browser window (13.09.2026); the claims above are about the JOIN, which stayed.
