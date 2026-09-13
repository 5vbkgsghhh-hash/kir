"""Real local SQLite CAS; synthetic native evidence, no Revit/.NET/files outside basetemp."""
from copy import deepcopy
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir import project_store as storage
from kir.project_store import (ProjectStore, STORE_SCHEMA, GEOMETRY_STORE_SCHEMA, REALIZATION_STORE_SCHEMA,
    ProjectStoreError, StoreConflict, StoreCorrupt, StoreNotFound, StoreReadOnly, StoreUpgradeRequired, StoreCommitUnknown)
from kir.project_realization_store import RecordedLevelBaseline
from kir.level_settlement import qualify_level_settlement
from kir.revit_level_update import prepare_level_update, plan_level_elevation_update
from kir.saved_execution import SavedExecutionRecord, _capture
from kir.update_submission import bind_level_update_submission
from kir.tests.test_level_settlement import qualified_case
from kir.tests.test_revit_level_update import initial, proposed, response_for, TARGET_ADDRESS, PROTECTED, bind, observation, plan


def stored_case(path, *, schema=REALIZATION_STORE_SCHEMA, include_proposal=True):
    case, record, after, qualified = qualified_case()
    source = case[0]["project"]
    root = initial(explicit=False)
    assert source.parent_revision == root.revision_id
    store = ProjectStore.create(path, root, schema=schema)
    store.commit(source, expected_revision=root.revision_id)
    target = proposed(source)
    assert target.revision_id == record.update_submission["update"]["proposed_revision"]
    if include_proposal:
        store.commit(target, expected_revision=source.revision_id)
    return store, case, record, after, qualified, target


def count_rows(path):
    with sqlite3.connect(path) as connection:
        return {name: connection.execute("SELECT count(*) FROM " + name).fetchone()[0]
            for name in ("revisions", "geometry_assets", "level_streams", "level_update_archives", "level_settlements", "level_scope_owners")}


def test_reserve_settle_preserves_later_author_head_and_exact_input(tmp_path):
    store, case, record, after, qualified, target = stored_case(tmp_path / "project.sqlite")
    later = target.revise(expected_revision=target.revision_id, metadata={"later_authoring": True})
    store.commit(later, expected_revision=target.revision_id)
    before = [project.dumps() for project in store.history()]
    stream = qualified.to_dict()["original_binding_digest"]
    with patch("kir.compiler.compile_program", side_effect=AssertionError("no compile")), \
         patch("kir.compiler.plan_program", side_effect=AssertionError("no plan")):
        reserved = store.reserve_level_update(record, expected_checkpoint=None)
        assert reserved.inserted and reserved.pending_archive_digest == record.digest and not reserved.may_retry
        baseline = store.level_baseline(stream)
        assert type(baseline) is RecordedLevelBaseline
        assert baseline.checkpoint_digest is None and baseline.baseline_revision == case[0]["project"].revision_id
        assert baseline.store_id == store.store_id and baseline.project_id == store.project_id
        assert baseline.pending_archive_digest == record.digest
        assert not any(hasattr(baseline, name) for name in ("planned", "execute_request", "require_identity"))
        retained = store.get_level_update_archive(record.digest)
        assert retained._raw == record._raw and not hasattr(retained, "execute_request")
        repeated = store.reserve_level_update(record, expected_checkpoint=None)
        assert not repeated.inserted and repeated.pending_archive_digest == record.digest
        committed = store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
        assert committed.inserted and committed.checkpoint_digest == qualified.digest
        assert committed.pending_archive_digest is None and not committed.may_retry
        assert store.get_level_settlement(qualified.digest) == qualified.to_dict()
        baseline = store.level_baseline(stream)
        assert baseline.baseline_revision == target.revision_id and baseline.accepted == qualified.to_dict()
        again = store.reserve_level_update(record, expected_checkpoint=None)
        assert not again.inserted and again.checkpoint_digest == qualified.digest and again.pending_archive_digest is None
        settled_again = store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
        assert not settled_again.inserted and settled_again.checkpoint_digest == qualified.digest
        assert [project.dumps() for project in store.history()] == before
        assert store.head().revision_id == later.revision_id
    assert count_rows(store.path)["level_update_archives"] == count_rows(store.path)["level_settlements"] == 1
    original = baseline.original
    original["outputs"].clear()
    accepted = baseline.accepted
    accepted["after"]["rows"].clear()
    assert baseline.original["outputs"] and baseline.accepted["after"]["rows"]


@pytest.mark.parametrize("schema", [STORE_SCHEMA, GEOMETRY_STORE_SCHEMA])
def test_explicit_upgrade_preserves_history_and_existing_readonly_handle(tmp_path, schema):
    store, _, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=schema)
    readonly = ProjectStore.open(store.path)
    before = [project.dumps() for project in store.history()]
    with pytest.raises(StoreUpgradeRequired): store.reserve_level_update(record, expected_checkpoint=None)
    with pytest.raises(StoreConflict): store.upgrade_schema(REALIZATION_STORE_SCHEMA, expected_revision="f" * 64)
    with pytest.raises(StoreReadOnly): readonly.upgrade_schema(REALIZATION_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert store.upgrade_schema(REALIZATION_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert not store.upgrade_schema(REALIZATION_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert readonly.schema == REALIZATION_STORE_SCHEMA
    assert [project.dumps() for project in readonly.history()] == before
    with pytest.raises(StoreConflict): store.upgrade_schema(GEOMETRY_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert store.reserve_level_update(record, expected_checkpoint=None).inserted


def test_missing_proposed_revision_cannot_leave_stream_or_pending(tmp_path):
    store, _, record, _, _, _ = stored_case(tmp_path / "project.sqlite", include_proposal=False)
    before = count_rows(store.path)
    with pytest.raises(StoreConflict, match="missing authored history"):
        store.reserve_level_update(record, expected_checkpoint=None)
    assert count_rows(store.path) == before


def test_another_pending_or_same_native_operation_never_replaces_first(tmp_path):
    store, case, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    prepared = prepare_level_update(case[1], operation_id=str(uuid4()))
    other = SavedExecutionRecord._from_bytes(_capture(prepared, level_update=bind_level_update_submission(case[1], prepared)))
    store.reserve_level_update(record, expected_checkpoint=None)
    with pytest.raises(StoreConflict, match="unresolved pending"):
        store.reserve_level_update(other, expected_checkpoint=None)
    with pytest.raises(StoreConflict):
        store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=other.digest)
    assert store.level_baseline(qualified.to_dict()["original_binding_digest"]).pending_archive_digest == record.digest
    assert count_rows(store.path)["level_update_archives"] == 1


def test_plain_reports_or_prepared_objects_cannot_settle(tmp_path):
    store, case, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    for unqualified in (qualified.to_dict(), record, case[2], None):
        with pytest.raises(ProjectStoreError, match="exact Qualified"):
            store.commit_level_settlement(unqualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    assert count_rows(store.path)["level_settlements"] == 0


def test_readonly_and_missing_paths_are_not_mutated(tmp_path):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    readonly = ProjectStore.open(store.path)
    before = store.path.read_bytes()
    with pytest.raises(StoreReadOnly): readonly.reserve_level_update(record, expected_checkpoint=None)
    with pytest.raises(StoreReadOnly):
        readonly.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    with pytest.raises(StoreNotFound): readonly.level_baseline(qualified.to_dict()["original_binding_digest"])
    with pytest.raises(StoreNotFound): readonly.get_level_update_archive(record.digest)
    with pytest.raises(StoreNotFound): readonly.get_level_settlement(qualified.digest)
    assert store.path.read_bytes() == before
    absent = tmp_path / "absent.sqlite"
    with pytest.raises(StoreNotFound): ProjectStore.open(absent)
    assert not absent.exists()


def test_unknown_execution_and_unqualified_after_leave_pending_indefinitely(tmp_path):
    store, case, record, after, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    response = deepcopy(case[3])
    response["receipt"]["state"] = "running_unknown"
    from kir.level_settlement import LevelSettlementRefusal
    with pytest.raises(LevelSettlementRefusal):
        qualify_level_settlement(record, json.dumps(response), after=after,
            credentials=case[0]["credentials"], request_id=response["request_id"])
    reopened = ProjectStore.open(store.path)
    assert reopened.level_baseline(qualified.to_dict()["original_binding_digest"]).pending_archive_digest == record.digest
    assert not hasattr(store, "abort_level_update")


def second_archive(store, after, qualified, target):
    baseline = store.level_baseline(qualified.to_dict()["original_binding_digest"])
    next_revision = proposed(target, value=4200.0)
    store.commit(next_revision, expected_revision=target.revision_id)
    update = plan_level_elevation_update(target, next_revision, baseline=baseline, observation=after,
        target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    prepared = prepare_level_update(update, operation_id=str(uuid4()))
    record = SavedExecutionRecord._from_bytes(_capture(prepared, level_update=bind_level_update_submission(update, prepared)))
    return record, update


def test_lost_pending_after_accepted_checkpoint_refuses_before_another_reservation(tmp_path):
    store, _, record, after, qualified, target = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    pending, update = second_archive(store, after, qualified, target)
    store.reserve_level_update(pending, expected_checkpoint=qualified.digest)
    other_prepared = prepare_level_update(update, operation_id=str(uuid4()))
    other = SavedExecutionRecord._from_bytes(_capture(other_prepared,
        level_update=bind_level_update_submission(update, other_prepared)))
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE level_streams SET pending_archive_digest=NULL")
    with pytest.raises(StoreCorrupt): store.level_baseline(qualified.to_dict()["original_binding_digest"])
    with pytest.raises(StoreCorrupt): store.reserve_level_update(other, expected_checkpoint=qualified.digest)
    assert count_rows(store.path)["level_update_archives"] == 2


@pytest.mark.parametrize("settled", [False, True])
def test_changed_original_binding_cannot_bypass_native_uid_scope(tmp_path, settled):
    store, case, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    if settled:
        store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    source = {**case[0], "response": deepcopy(case[0]["response"]), "result": deepcopy(case[0]["result"])}
    source["result"]["revit_warnings"] = ["alternate original receipt evidence"]
    original = bind(source)
    assert original.digest != qualified.to_dict()["original_binding_digest"]
    updated = plan(source, original, observation(source, original))
    prepared = prepare_level_update(updated, operation_id=str(uuid4()))
    other = SavedExecutionRecord._from_bytes(_capture(prepared, level_update=bind_level_update_submission(updated, prepared)))
    before = count_rows(store.path)
    with pytest.raises(StoreConflict, match="native UID scope"):
        store.reserve_level_update(other, expected_checkpoint=None)
    assert count_rows(store.path) == before


@pytest.mark.parametrize("fault", ["stale_revision", "protected_field"])
def test_imported_baseline_dto_cannot_override_actual_sql_checkpoint(tmp_path, fault):
    store, case, record, after, qualified, target = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    baseline = store.level_baseline(qualified.to_dict()["original_binding_digest"])
    accepted = baseline.accepted
    rows = after.rows
    if fault == "stale_revision":
        accepted["after"]["precondition"]["revision"] = 9
    else:
        uid = next(uid for uid in rows if uid != case[1].to_dict()["target_identity"]["unique_id"])
        rows[uid]["name"] = "changed protected field"
        accepted["after"]["rows"] = rows
    altered = replace(baseline, _accepted_json=json.dumps(accepted))
    from kir.tests.test_saved_level_update_acceptance import after_read
    observed, _, _ = after_read(case, rows=rows, revision=9 if fault == "stale_revision" else 10)
    next_revision = proposed(target, value=4200.0)
    store.commit(next_revision, expected_revision=target.revision_id)
    update = plan_level_elevation_update(target, next_revision, baseline=altered, observation=observed,
        target=TARGET_ADDRESS, protected_outputs=PROTECTED)
    prepared = prepare_level_update(update, operation_id=str(uuid4()))
    candidate = SavedExecutionRecord._from_bytes(_capture(prepared, level_update=bind_level_update_submission(update, prepared)))
    before = count_rows(store.path)
    with pytest.raises(StoreConflict, match="checkpoint"):
        store.reserve_level_update(candidate, expected_checkpoint=baseline.checkpoint_digest)
    assert count_rows(store.path) == before


class FaultConnection:
    def __init__(self, inner, prefix, after):
        self.inner, self.prefix, self.after, self.fired = inner, prefix, after, False
    def __getattr__(self, name): return getattr(self.inner, name)
    def execute(self, sql, *args):
        if not self.fired and sql.startswith(self.prefix):
            self.fired = True
            if self.after: self.inner.execute(sql, *args)
            raise sqlite3.OperationalError("injected transaction failure")
        return self.inner.execute(sql, *args)


@pytest.mark.parametrize("prefix,after", [
    ("INSERT INTO level_streams", True), ("INSERT INTO level_scope_owners", True),
    ("INSERT INTO level_update_archives", True), ("UPDATE level_streams SET pending", True), ("COMMIT", True),
])
def test_reservation_failure_is_atomic_or_named_commit_unknown(tmp_path, monkeypatch, prefix, after):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    original = storage._connect
    with monkeypatch.context() as local:
        local.setattr(storage, "_connect", lambda *a, **kw: FaultConnection(original(*a, **kw), prefix, after))
        with pytest.raises(StoreCommitUnknown if prefix == "COMMIT" else ProjectStoreError):
            store.reserve_level_update(record, expected_checkpoint=None)
    counts = count_rows(store.path)
    committed = prefix == "COMMIT"
    assert counts["level_streams"] == counts["level_update_archives"] == int(committed)
    assert counts["level_settlements"] == 0
    retry = store.reserve_level_update(record, expected_checkpoint=None)
    assert retry.inserted is not committed and not retry.may_retry
    assert store.level_baseline(qualified.to_dict()["original_binding_digest"]).pending_archive_digest == record.digest


@pytest.mark.parametrize("prefix", ["INSERT INTO level_settlements", "UPDATE level_streams SET checkpoint", "COMMIT"])
def test_settlement_failure_keeps_pending_or_reconciles_exact_committed_identity(tmp_path, monkeypatch, prefix):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    original = storage._connect
    with monkeypatch.context() as local:
        local.setattr(storage, "_connect", lambda *a, **kw: FaultConnection(original(*a, **kw), prefix, True))
        with pytest.raises(StoreCommitUnknown if prefix == "COMMIT" else ProjectStoreError):
            store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    baseline = store.level_baseline(qualified.to_dict()["original_binding_digest"])
    assert baseline.pending_archive_digest == (None if prefix == "COMMIT" else record.digest)
    replay = store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    assert replay.inserted is (prefix != "COMMIT")
    assert count_rows(store.path)["level_settlements"] == 1


@pytest.mark.parametrize("sql", [
    "UPDATE level_update_archives SET payload='{}'",
    "UPDATE level_update_archives SET proposed_revision=base_revision",
    "UPDATE level_streams SET original_payload='{}'",
    "UPDATE level_streams SET pending_archive_digest=NULL",
    "DELETE FROM level_scope_owners",
])
def test_corrupt_pending_records_are_neither_returned_nor_repaired(tmp_path, sql):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    with sqlite3.connect(store.path) as connection: connection.execute(sql)
    before = store.path.read_bytes()
    with pytest.raises(StoreCorrupt): store.level_baseline(qualified.to_dict()["original_binding_digest"])
    with pytest.raises(StoreCorrupt): store.reserve_level_update(record, expected_checkpoint=None)
    with pytest.raises(StoreCorrupt): store.history()
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("sql", [
    "UPDATE level_settlements SET payload='{}'", "UPDATE level_settlements SET sequence=4",
    "UPDATE level_streams SET checkpoint_digest=NULL",
])
def test_corrupt_settlement_or_rewound_checkpoint_is_not_qualified_history(tmp_path, sql):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    with sqlite3.connect(store.path) as connection: connection.execute(sql)
    with pytest.raises(StoreCorrupt): store.level_baseline(qualified.to_dict()["original_binding_digest"])
    with pytest.raises(StoreCorrupt): store.history()


def test_new_process_reopens_inert_baseline_without_compilation(tmp_path):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    store.commit_level_settlement(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    before = store.path.read_bytes()
    script = r'''
import json,sys
from unittest.mock import patch
from kir.project_store import ProjectStore
with patch('kir.compiler.compile_program',side_effect=AssertionError('no compile')), patch('kir.compiler.plan_program',side_effect=AssertionError('no plan')):
    baseline=ProjectStore.open(sys.argv[1]).level_baseline(sys.argv[2])
    assert not hasattr(baseline,'execute_request')
    print(json.dumps(baseline.to_dict()))
'''
    child = subprocess.run([sys.executable, "-B", "-c", script, str(store.path), qualified.to_dict()["original_binding_digest"]],
        capture_output=True, text=True, timeout=30, check=True, env=os.environ.copy())
    assert json.loads(child.stdout) == store.level_baseline(qualified.to_dict()["original_binding_digest"]).to_dict()
    assert store.path.read_bytes() == before


def test_two_processes_compete_for_one_pending_and_loser_leaves_no_archive(tmp_path):
    store, case, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    prepared = prepare_level_update(case[1], operation_id=str(uuid4()))
    other = SavedExecutionRecord._from_bytes(_capture(prepared, level_update=bind_level_update_submission(case[1], prepared)))
    script = r'''
import sys,json
from kir.project_store import ProjectStore,StoreConflict
from kir.saved_execution import SavedExecutionRecord
record=SavedExecutionRecord._from_bytes(sys.stdin.buffer.read())
try:
    result=ProjectStore.open(sys.argv[1],readonly=False).reserve_level_update(record,expected_checkpoint=None)
    print(json.dumps({'inserted':result.inserted,'digest':record.digest}))
except StoreConflict:
    print(json.dumps({'conflict':True,'digest':record.digest}))
'''
    processes = [subprocess.Popen([sys.executable, "-B", "-c", script, str(store.path)], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=os.environ.copy()) for _ in range(2)]
    for process, candidate in zip(processes, (record, other), strict=True):
        process.stdin.write(candidate._raw)
        process.stdin.close()
        process.stdin = None
    rows = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 0, stderr
        rows.append(json.loads(stdout))
    assert sum(row.get("inserted", False) for row in rows) == sum(row.get("conflict", False) for row in rows) == 1
    winner = next(row["digest"] for row in rows if row.get("inserted"))
    assert count_rows(store.path)["level_update_archives"] == 1
    assert store.level_baseline(qualified.to_dict()["original_binding_digest"]).pending_archive_digest == winner
    assert store.history()


@pytest.mark.parametrize("after_commit", [False, True])
def test_actual_child_exit_has_only_old_state_or_exact_durable_pending(tmp_path, after_commit):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    script = r'''
import os,sys
from kir import project_store as storage
from kir.saved_execution import SavedExecutionRecord
record=SavedExecutionRecord._from_bytes(sys.stdin.buffer.read())
connect=storage._connect
def small_cache(*a,**kw):
    connection=connect(*a,**kw)
    connection.execute('PRAGMA cache_size=1')
    connection.execute('PRAGMA cache_spill=ON')
    return connection
storage._connect=small_cache
commit=storage._commit
def interrupted(connection):
    if sys.argv[2]=='after': commit(connection)
    os._exit(72)
storage._commit=interrupted
storage.ProjectStore.open(sys.argv[1],readonly=False).reserve_level_update(record,expected_checkpoint=None)
'''
    child = subprocess.run([sys.executable, "-B", "-c", script, str(store.path), "after" if after_commit else "before"],
        input=record._raw, capture_output=True, timeout=30, env=os.environ.copy())
    assert child.returncode == 72, child.stderr
    # Explicit writable access is allowed to ask SQLite to recover its own
    # hot journal. Never delete the journal to force a seemingly clean state.
    recovered = ProjectStore.open(store.path, readonly=False)
    assert count_rows(store.path)["level_update_archives"] == int(after_commit)
    replay = recovered.reserve_level_update(record, expected_checkpoint=None)
    assert replay.inserted is not after_commit and not replay.may_retry
    assert recovered.level_baseline(qualified.to_dict()["original_binding_digest"]).pending_archive_digest == record.digest
    assert recovered.history()


@pytest.mark.parametrize("prefix", ["CREATE TABLE level_update_archives", "UPDATE project_store SET schema_version", "COMMIT"])
def test_multitable_upgrade_is_atomic_including_post_commit_ack_failure(tmp_path, monkeypatch, prefix):
    store, _, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=GEOMETRY_STORE_SCHEMA)
    before = [project.dumps() for project in store.history()]
    original = storage._connect
    with monkeypatch.context() as local:
        local.setattr(storage, "_connect", lambda *a, **kw: FaultConnection(original(*a, **kw), prefix, True))
        with pytest.raises(StoreCommitUnknown if prefix == "COMMIT" else ProjectStoreError):
            store.upgrade_schema(REALIZATION_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert store.schema == (REALIZATION_STORE_SCHEMA if prefix == "COMMIT" else GEOMETRY_STORE_SCHEMA)
    assert store.upgrade_schema(REALIZATION_STORE_SCHEMA, expected_revision=store.head().revision_id) is (prefix != "COMMIT")
    assert [project.dumps() for project in store.history()] == before
    assert store.reserve_level_update(record, expected_checkpoint=None).inserted


def test_sqlite_ledger_budget_precedes_python_payload_decode(tmp_path, monkeypatch):
    store, _, record, _, _, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    assert len(record._raw) > 4096
    from kir import project_realization_store as ledger
    monkeypatch.setattr(ledger, "MAX_RECORD_BYTES", 32)
    def forbidden(*args, **kwargs):
        raise AssertionError("oversize ledger row reached Python archive decoding")
    monkeypatch.setattr(SavedExecutionRecord, "_from_bytes", forbidden)
    with pytest.raises(StoreCorrupt, match="budget"):
        store.get_level_update_archive(record.digest)
