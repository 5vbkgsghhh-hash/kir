"""One read-only local status snapshot, not live BIM readiness or authority."""
import json
import multiprocessing
import sqlite3
from unittest.mock import patch

import pytest

from kir import __main__ as cli
from kir.project_store import ProjectStore, ProjectStoreError, StoreRecoveryRequired, STORE_SCHEMA, RESOLUTION_STORE_SCHEMA
from kir.tests.test_project_realization_store import stored_case
from kir.tests.test_project_level_resolution_store import not_started
from kir.tests.test_project_cli_lifecycle import _fresh
from kir.tests.test_update_submission_memory import record_values


def test_legacy_authoring_store_does_not_claim_native_publication_or_empty_catalog(tmp_path):
    store, _, _, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=STORE_SCHEMA)
    before = store.path.read_bytes()
    status = ProjectStore.open(store.path).status()
    assert status["schema"] == "kir-project-status/1" and status["read_only"] is True
    assert status["authoring"]["revision_id"] == store.head().revision_id
    assert not status["native"]["ledger_supported"] and not status["native"]["catalog_complete"]
    assert status["native"]["streams"] == [] and not status["native"]["live_model_observed"]
    assert status["native"]["whole_project_acceptance"] == "not_established"
    assert store.path.read_bytes() == before


def test_pending_is_not_running_and_checkpoint_is_not_whole_model_acceptance(tmp_path):
    store, case, record, _, qualified, target = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    status = store.status()
    row, = status["native"]["streams"]
    assert row["state"] == "pending" and row["accepted_scope_revision"] is None
    assert row["planning_base_revision"] == case[0]["project"].revision_id
    assert row["pending"] == {"archive_digest": record.digest, "operation_id": record.binding_dict()["operation_id"],
        "base_revision": case[0]["project"].revision_id, "proposed_revision": target.revision_id,
        "execution": "not_established_by_reservation"}
    assert not row["authoring_head_matches_planning_base"]
    store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    row, = store.status()["native"]["streams"]
    assert row["state"] == "checkpoint_recorded" and row["accepted_scope_revision"] == target.revision_id
    assert row["pending"] is None and row["authoring_head_matches_planning_base"]
    assert row["not_evaluated"] == ["dependent_geometry", "protected_geometry", "engineering"]


def test_not_started_keeps_authoring_ahead_without_inventing_an_accepted_revision(tmp_path):
    store, case, record, _, _, target = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    store.commit_level_not_started(not_started(case, record), expected_checkpoint=None, expected_pending_archive=record.digest)
    status = store.status()
    row, = status["native"]["streams"]
    assert row["state"] == "not_started_only" and row["not_started_at_checkpoint"] == 1
    assert row["accepted_scope_revision"] is None and row["checkpoint_digest"] is None
    assert status["authoring"]["revision_id"] == target.revision_id
    assert not row["authoring_head_matches_planning_base"]


def test_status_uses_one_read_transaction_and_never_compiles_or_queries_native(tmp_path, monkeypatch):
    store, _, record, _, _, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    from kir import project_store as storage
    original = storage._connect
    connections = []
    def connect(*args, **kwargs):
        connections.append(kwargs)
        return original(*args, **kwargs)
    monkeypatch.setattr(storage, "_connect", connect)
    before = store.path.read_bytes()
    with patch("kir.compiler.compile_program", side_effect=AssertionError("no compile")), \
         patch("kir.compiler.plan_program", side_effect=AssertionError("no plan")), \
         patch("kir.revit_transport.exchange", side_effect=AssertionError("no native call")):
        status = store.status()
    assert len(connections) == 1
    assert connections[0]["readonly"] is True
    assert status["snapshot_scope"] == "one_local_read_transaction"
    assert store.path.read_bytes() == before
    serialized = json.dumps(status)
    assert record.to_dict()["source"] not in serialized
    assert "before_observation" not in serialized and '"token"' not in serialized and '"result_json"' not in serialized


def test_bounded_paging_names_its_cross_call_snapshot_limit(tmp_path):
    store, _, first, _, _, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(first, expected_checkpoint=None)
    _, _, second = record_values()  # same authoring revision, distinct runtime/stream
    store.reserve_level_update(second, expected_checkpoint=None)
    all_rows = store.status()["native"]["streams"]
    page = store.status(limit=1)["native"]
    assert len(page["streams"]) == 1 and page["has_more"] and not page["catalog_complete"]
    next_page = store.status(limit=1, after_stream=page["next_cursor"])["native"]
    assert not next_page["has_more"] and not next_page["catalog_complete"]
    assert next_page["continuation_consistency"] == "new_read_snapshot_each_call"
    assert page["streams"] + next_page["streams"] == all_rows


def test_corrupt_scope_remains_visible_but_is_never_reported_as_empty_or_ready(tmp_path):
    store, _, first, _, _, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(first, expected_checkpoint=None)
    _, _, second = record_values()
    store.reserve_level_update(second, expected_checkpoint=None)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE level_update_archives SET payload='{}' WHERE digest=?", (first.digest,))
    before = store.path.read_bytes()
    status = store.status()
    assert status["native"]["catalog_complete"] and not status["native"]["returned_scopes_readable"]
    assert sorted(row["state"] for row in status["native"]["streams"]) == ["pending", "unavailable"]
    code, output, _ = _fresh(["project", "status", str(store.path)])
    assert code == cli.NOT_DONE and json.loads(output) == status
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": True}, {"limit": 101}, {"limit": 1.0},
                                    {"after_stream": "foreign"}, {"after_stream": 1}])
def test_invalid_budget_or_cursor_never_gets_a_successful_status(tmp_path, kwargs):
    store, _, _, _, _, _ = stored_case(tmp_path / "project.sqlite")
    with pytest.raises(ProjectStoreError): store.status(**kwargs)


def test_cli_status_reopens_without_mutation_and_missing_path_is_not_created(tmp_path):
    store, _, record, _, _, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    before = store.path.read_bytes()
    code, output, error = _fresh(["project", "status", str(store.path), "--limit", "1"])
    assert code == cli.ANSWERED, error
    assert json.loads(output) == store.status(limit=1)
    assert store.path.read_bytes() == before
    missing = tmp_path / "missing.sqlite"
    code, output, _ = _fresh(["project", "status", str(missing)])
    assert code == cli.NOT_DONE and not output and not missing.exists()


def test_status_bounds_intent_preview_without_changing_authored_text(tmp_path):
    store, _, _, _, _, _ = stored_case(tmp_path / "project.sqlite")
    head = store.head()
    long_intent = "Ж" * 2000
    next_revision = head.revise(expected_revision=head.revision_id, intent=long_intent)
    store.commit(next_revision, expected_revision=head.revision_id)
    assert store.status()["authoring"]["intent"] == long_intent[:1000]
    assert store.status()["authoring"]["intent_truncated"] is True
    assert store.head().intent == long_intent


@pytest.mark.parametrize("payload", ["[]", "null"])
def test_nonobject_checkpoint_reports_unavailable_scope_without_crashing(tmp_path, payload):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE level_settlements SET payload=?", (payload,))
    status = store.status()
    assert status["native"]["streams"][0]["state"] == "unavailable"
    assert not status["native"]["returned_scopes_readable"]


def test_missing_stream_owner_cannot_hide_an_unresolved_archive_as_empty_catalog(tmp_path):
    store, _, record, _, _, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM level_streams")
    status = store.status()
    assert status["native"]["streams"] == []
    assert not status["native"]["catalog_complete"] and not status["native"]["returned_scopes_readable"]
    assert status["native"]["catalog_diagnostic"] == "orphaned_scope_records"


def test_status_on_existing_writable_handle_does_not_recover_a_real_hot_journal(tmp_path):
    from kir.tests.test_project_store import root, changed, _crash_writer
    initial = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", initial)
    next_revision = changed(initial, metadata={"large_evaluation": "x" * 250000})
    process = multiprocessing.get_context("spawn").Process(
        target=_crash_writer, args=(str(store.path), next_revision.dumps(), "after_insert"))
    process.start()
    process.join(20)
    if process.is_alive():
        process.terminate()
        process.join(5)
    assert process.exitcode == 71
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    with pytest.raises(StoreRecoveryRequired): store.status()
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir()} == before
