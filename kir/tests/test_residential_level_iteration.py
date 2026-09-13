"""Real residential recipes/OCCT/SQLite; native receipts and queries are synthetic.

Only the delivery exchange is patched by the shared dispatch fixture. This is
not a live Revit test or proof of dependent/protected geometry preservation.
"""
import json

import pytest

from examples import residential_project as towers
from examples import residential_refinement as refinement
from examples import residential_with_podium as composed
from kir.level_settlement import qualify_level_settlement
from kir.project import PROJECT_SCHEMA_V2, _canonical
from kir.project_handoff import handoff_instance_to_explicit
from kir.project_refinement import refinement_view
from kir.project_store import ProjectStore, REALIZATION_STORE_SCHEMA
from kir.revit_level_update import plan_level_elevation_update
from kir.tests.test_level_update_iteration import dispatch, observe_rows, shifted_rows
from kir.tests.test_revit_level_update import make_case, bind, observation, proposed


def test_saved_residential_level_3600_3800_4200_keeps_original_lineage_and_assets(tmp_path):
    pytest.importorskip("OCP")
    target = ("tower-a", "storey-02-level")
    protected = (("tower-b", "concept-volume"), ("tower-c", "concept-volume"),
                 (composed.PODIUM_INSTANCE, composed.PODIUM_OUTPUT))
    root = towers.concept()
    store = ProjectStore.create(tmp_path / "residential.sqlite", root)
    assert store.upgrade_schema(REALIZATION_STORE_SCHEMA, expected_revision=root.revision_id)
    upgraded = root.upgrade_schema(PROJECT_SCHEMA_V2, expected_revision=root.revision_id)
    store.commit(upgraded, expected_revision=root.revision_id)
    podium, bundle = composed.add_podium(upgraded)
    bundle_bytes = bundle.dumps().encode("utf-8")
    store.commit(podium, expected_revision=upgraded.revision_id, assets=[bundle])
    sealed = refinement.develop_section(podium)
    store.commit(sealed, expected_revision=podium.revision_id)
    r0 = handoff_instance_to_explicit(sealed, "tower-a", new_module_key="tower-a-explicit",
                                     expected_revision=sealed.revision_id)
    store.commit(r0, expected_revision=sealed.revision_id)
    source = make_case(tmp_path, project=store.head(), bundles={bundle.digest: store.get_asset(bundle.digest)},
                       required=(target, *protected))
    origin = bind(source)
    original = origin.to_dict()
    assert {row["source_op"] for row in origin.rows} == {"create_level", "create_solid_blend", "create_directshape"}
    podium_binding = next(row for row in source["record"].project_submission["outputs"]
                          if row["instance_key"] == composed.PODIUM_INSTANCE)
    assert podium_binding["body"]["descriptor"]["bundle_sha256"] == bundle.digest
    assert podium_binding["body"]["descriptor"]["body_sha256"] == bundle.body_digest
    # 24 -> 25: the concept volume stays in the head as a separate instance
    # (2026-09-07), and its op now enters the project's materialization. The
    # section still has 23 ops, same as before.
    assert len(source["materialized"].planned.ops) == 25
    before = observation(source, origin, target_address=target)
    r1 = proposed(r0, target=target, value=3800.0)
    store.commit(r1, expected_revision=r0.revision_id)
    first = plan_level_elevation_update(r0, r1, publication=origin, observation=before,
                                       target=target, protected_outputs=protected)
    assert first.to_dict()["old_elev_mm"] == 3600.0
    assert len(first.to_dict()["affected_output_ids"]) == 6
    attempt1, response1 = dispatch(store, first, source["credentials"], tmp_path / "update-3800.sqlite")
    assert store.level_baseline(origin.digest).pending_archive_digest == attempt1.record.digest
    r2 = proposed(r1, target=target, value=4200.0)
    store.commit(r2, expected_revision=r1.revision_id)  # authored head may lead the accepted scope
    uid = first.to_dict()["target_identity"]["unique_id"]
    after1 = observe_rows(source["credentials"], shifted_rows(before.rows, uid, 3800.0), 10)
    qualified1 = qualify_level_settlement(attempt1.record, json.dumps(response1), after=after1,
        credentials=source["credentials"], request_id=response1["request_id"])
    accepted1 = store.commit_level_settlement(qualified1, expected_checkpoint=None,
                                              expected_pending_archive=attempt1.record.digest)
    assert accepted1.inserted and store.head().revision_id == r2.revision_id

    store = ProjectStore.open(store.path, readonly=False)
    baseline = store.level_baseline(origin.digest)
    assert baseline.baseline_revision == r1.revision_id and baseline.pending_archive_digest is None
    assert baseline.original == original
    current = observe_rows(source["credentials"], baseline.accepted["after"]["rows"], 10)
    second = plan_level_elevation_update(store.get(r1.revision_id), store.head(), baseline=baseline,
                                        observation=current, target=target, protected_outputs=protected)
    assert second.publication is None and second.baseline is baseline
    assert second.original_binding == original
    assert second.to_dict()["old_elev_mm"] == 3800.0 and second.to_dict()["new_elev_mm"] == 4200.0
    assert len(second.planned.to_ops()) == 1 and second.planned.to_ops()[0]["op"] == "set_param"
    attempt2, response2 = dispatch(store, second, source["credentials"], tmp_path / "update-4200.sqlite")
    assert attempt2.record.update_submission["schema"] == "kir-submitted-level-update/2"
    assert attempt2.record.update_submission["baseline_ref"]["checkpoint_digest"] == baseline.checkpoint_digest
    after2 = observe_rows(source["credentials"], shifted_rows(current.rows, uid, 4200.0), 11)
    qualified2 = qualify_level_settlement(attempt2.record, json.dumps(response2), after=after2,
        credentials=source["credentials"], request_id=response2["request_id"])
    accepted2 = store.commit_level_settlement(qualified2, expected_checkpoint=baseline.checkpoint_digest,
                                              expected_pending_archive=attempt2.record.digest)
    assert accepted2.inserted

    final = ProjectStore.open(store.path)
    checkpoint = final.level_baseline(origin.digest)
    assert final.schema == REALIZATION_STORE_SCHEMA
    assert checkpoint.baseline_revision == r2.revision_id and checkpoint.pending_archive_digest is None
    assert checkpoint.original == original and checkpoint.original["project"]["revision_id"] == r0.revision_id
    assert checkpoint.checkpoint_digest != baseline.checkpoint_digest
    assert checkpoint.accepted["after"]["rows"][uid]["level"]["project_elevation_mm"] == 4200.0
    assert checkpoint.accepted["assessment"]["not_evaluated"] == ["dependent_geometry", "protected_geometry", "engineering"]
    expected_history = (root, upgraded, podium, sealed, r0, r1, r2)
    assert tuple(item.dumps() for item in final.history()) == tuple(item.dumps() for item in expected_history)
    assert final.get_asset(bundle.digest).dumps().encode("utf-8") == bundle_bytes
    for revision in (r0, r1, r2):
        for key in ("tower-b", "tower-c", composed.PODIUM_INSTANCE):
            old = next(item for item in sealed.instances if item.key == key)
            new = next(item for item in revision.instances if item.key == key)
            assert _canonical(new.to_dict()) == _canonical(old.to_dict())
        assert _canonical([m.to_dict() for m in revision.modules]) == _canonical([m.to_dict() for m in r0.modules])
        assert refinement_view(revision, "tower-a", source=podium)["binding_status"] == "exact_supplied_source"
    for attempt in (attempt1, attempt2):
        assert attempt.record.update_submission["original_publication"] == original
        assert final.get_level_update_archive(attempt.record.digest)._raw == attempt.record._raw
    assert final.get_level_settlement(qualified1.digest) == qualified1.to_dict()
    assert final.get_level_settlement(qualified2.digest) == qualified2.to_dict()
