"""Store/4 SQL migration and resolution; synthetic native receipts, scoped files only."""
from copy import deepcopy
import json
import os
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

from kir import project_store as storage
from kir import project_realization_store as ledger
from kir.project import _canonical
from kir.project_store import (ProjectStore, STORE_SCHEMA, GEOMETRY_STORE_SCHEMA, REALIZATION_STORE_SCHEMA,
    RESOLUTION_STORE_SCHEMA, StoreConflict, StoreCorrupt, StoreReadOnly, StoreNotFound,
    StoreCommitUnknown, StoreUpgradeRequired, ProjectStoreError)
from kir.level_resolution import qualify_level_not_started
from kir.revit_level_update import prepare_level_update
from kir.saved_execution import SavedExecutionRecord, _capture
from kir.update_submission import bind_level_update_submission
from kir.tests.test_project_realization_store import stored_case, second_archive, FaultConnection


def not_started(case, record):
    response = deepcopy(case[3])
    response["request_id"] = str(uuid4())
    response["receipt"].update(record.binding_dict())
    response["receipt"].update(state="context_changed_before_start", started=False, may_retry=True,
        changes=None, transaction_evidence="not_observed", result_json=None, result_error=None,
        result_truncated=False, error="synthetic context change")
    return qualify_level_not_started(record, json.dumps(response), credentials=case[0]["credentials"],
                                     request_id=response["request_id"])


def rows(path, table):
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT * FROM " + table).fetchall()


def fresh_record(update):
    prepared = prepare_level_update(update, operation_id=str(uuid4()))
    return SavedExecutionRecord._from_bytes(_capture(prepared,
        level_update=bind_level_update_submission(update, prepared)))


@pytest.mark.parametrize("schema", [STORE_SCHEMA, GEOMETRY_STORE_SCHEMA, REALIZATION_STORE_SCHEMA])
def test_explicit_upgrade4_preserves_all_old_rows_and_enforces_foreign_keys(tmp_path, schema):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite", schema=schema)
    if schema == REALIZATION_STORE_SCHEMA:
        store.reserve_level_update(record, expected_checkpoint=None)
    tables = ["revisions", "project_store"]
    if schema != STORE_SCHEMA: tables.append("geometry_assets")
    if schema == REALIZATION_STORE_SCHEMA: tables.extend(ledger.REALIZATION_TABLES)
    before = {name: rows(store.path, name) for name in tables}
    identity, head = store.store_id, store.head().revision_id
    readonly = ProjectStore.open(store.path)
    with pytest.raises(StoreReadOnly): readonly.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=head)
    with pytest.raises(StoreConflict): store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision="f" * 64)
    assert store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=head)
    assert not store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=head)
    assert readonly.schema == RESOLUTION_STORE_SCHEMA and readonly.store_id == identity
    for table, data in before.items():
        if table != "project_store": assert rows(store.path, table) == data
    assert rows(store.path, "level_resolutions") == []
    with store._transaction(write=True) as (connection, _):
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute("INSERT INTO level_resolutions VALUES (?, ?, ?, NULL, '{}')", ("a" * 64, "b" * 64, "c" * 64))
    assert store.head().revision_id == head and store.history()
    if schema == REALIZATION_STORE_SCHEMA:
        assert store.get_level_update_archive(record.digest)._raw == record._raw
        assert store.level_baseline(qualified.to_dict()["original_binding_digest"]).pending_archive_digest == record.digest


def test_unupgraded3_stays_exact_and_cannot_resolve(tmp_path):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    qualified = not_started(case, record)
    before = store.path.read_bytes()
    with pytest.raises(StoreUpgradeRequired):
        store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    with pytest.raises(StoreUpgradeRequired): store.get_level_resolution_for_archive(record.digest)
    assert store.schema == REALIZATION_STORE_SCHEMA and store.path.read_bytes() == before
    with sqlite3.connect(store.path) as connection:
        actual = connection.execute("SELECT sql FROM sqlite_schema WHERE name='level_update_archives'").fetchone()[0]
    assert actual == ledger.REALIZATION_TABLES["level_update_archives"]


def test_c0_resolution_retains_original_then_allows_only_new_explicit_operation(tmp_path):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    qualified = not_started(case, record)
    history = [revision.dumps() for revision in store.history()]
    assert store.get_level_resolution_for_archive(record.digest) is None
    result = store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    assert result.inserted and not result.may_retry and result.checkpoint_digest is None and result.pending_archive_digest is None
    baseline = store.level_baseline(qualified.to_dict()["original_binding_digest"])
    assert baseline.accepted is None and baseline.baseline_revision == case[0]["project"].revision_id
    assert store.get_level_resolution(qualified.digest) == qualified.to_dict()
    assert store.get_level_resolution_for_archive(record.digest) == qualified.to_dict()
    assert not store.reserve_level_update(record, expected_checkpoint=None).inserted
    new = fresh_record(case[1])
    assert store.reserve_level_update(new, expected_checkpoint=None).inserted
    repeated = store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    assert not repeated.inserted and repeated.pending_archive_digest == new.digest
    assert store.level_baseline(baseline.stream_id).pending_archive_digest == new.digest
    assert len(rows(store.path, "level_update_archives")) == 2 and len(rows(store.path, "level_resolutions")) == 1
    assert [revision.dumps() for revision in store.history()] == history


def test_c1_resolution_and_new_reservation_share_checkpoint_without_unique_constraint(tmp_path):
    store, case, record, after, settled, target = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    store.commit_level_settlement(settled, expected_checkpoint=None, expected_pending_archive=record.digest)
    pending, update = second_archive(store, after, settled, target)
    store.reserve_level_update(pending, expected_checkpoint=settled.digest)
    archived = rows(store.path, "level_update_archives")
    store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert rows(store.path, "level_update_archives") == archived
    qualified = not_started(case, pending)
    resolved = store.commit_level_not_started(qualified, expected_checkpoint=settled.digest, expected_pending_archive=pending.digest)
    assert resolved.checkpoint_digest == settled.digest and resolved.pending_archive_digest is None
    new = fresh_record(update)
    assert store.reserve_level_update(new, expected_checkpoint=settled.digest).inserted
    repeated = store.commit_level_not_started(qualified, expected_checkpoint=settled.digest, expected_pending_archive=pending.digest)
    assert not repeated.inserted and repeated.pending_archive_digest == new.digest
    assert repeated.checkpoint_digest == settled.digest
    assert store.history()


@pytest.mark.parametrize("prefix", [
    'CREATE TABLE "level_update_archives_next"', "INSERT INTO level_update_archives_next", "DROP TABLE level_update_archives",
    "ALTER TABLE level_update_archives_next", "CREATE TABLE level_resolutions", "CREATE INDEX level_archive_checkpoint",
    "CREATE INDEX level_resolution_checkpoint",
    "UPDATE project_store SET schema_version", "COMMIT",
])
def test_rebuild_migration_failure_restores3_or_reports_committed4(tmp_path, monkeypatch, prefix):
    store, _, record, _, qualified, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    before = {table: rows(store.path, table) for table in ("revisions", *ledger.REALIZATION_TABLES)}
    original = storage._connect
    connections = []
    with monkeypatch.context() as local:
        def connect(*args, **kwargs):
            connection = FaultConnection(original(*args, **kwargs), prefix, True)
            connections.append(connection)
            return connection
        local.setattr(storage, "_connect", connect)
        with pytest.raises(StoreCommitUnknown if prefix == "COMMIT" else ProjectStoreError):
            store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert any(connection.fired for connection in connections)
    assert store.schema == (RESOLUTION_STORE_SCHEMA if prefix == "COMMIT" else REALIZATION_STORE_SCHEMA)
    for table, data in before.items(): assert rows(store.path, table) == data
    assert store.level_baseline(qualified.to_dict()["original_binding_digest"]).pending_archive_digest == record.digest
    assert store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=store.head().revision_id) is (prefix != "COMMIT")
    assert store.history()


@pytest.mark.parametrize("prefix", ["INSERT INTO level_resolutions", "UPDATE level_streams SET pending_archive_digest=NULL", "COMMIT"])
def test_resolution_failure_retains_pending_or_supports_archive_ack_lookup(tmp_path, monkeypatch, prefix):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    qualified = not_started(case, record)
    connect = storage._connect
    with monkeypatch.context() as local:
        local.setattr(storage, "_connect", lambda *a, **kw: FaultConnection(connect(*a, **kw), prefix, True))
        with pytest.raises(StoreCommitUnknown if prefix == "COMMIT" else ProjectStoreError):
            store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    loaded = ProjectStore.open(store.path)
    found = loaded.get_level_resolution_for_archive(record.digest)
    assert (found == qualified.to_dict()) if prefix == "COMMIT" else found is None
    baseline = loaded.level_baseline(qualified.to_dict()["original_binding_digest"])
    assert baseline.pending_archive_digest == (None if prefix == "COMMIT" else record.digest)
    repeated = store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    assert repeated.inserted is (prefix != "COMMIT")


def test_readonly_missing_and_wrong_input_never_clear_pending(tmp_path):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    qualified = not_started(case, record)
    readonly = ProjectStore.open(store.path)
    before = store.path.read_bytes()
    with pytest.raises(StoreReadOnly): readonly.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    for bad in (qualified.to_dict(), record, None):
        with pytest.raises(ProjectStoreError): store.commit_level_not_started(bad, expected_checkpoint=None, expected_pending_archive=record.digest)
    with pytest.raises(StoreConflict): store.commit_level_not_started(qualified, expected_checkpoint="f" * 64, expected_pending_archive=record.digest)
    with pytest.raises(StoreConflict): store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive="f" * 64)
    with pytest.raises(StoreNotFound): readonly.get_level_resolution_for_archive("f" * 64)
    with pytest.raises(StoreNotFound): readonly.get_level_resolution(qualified.digest)
    assert readonly.get_level_resolution_for_archive(record.digest) is None
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("sql", ["UPDATE level_resolutions SET payload='{}'", "DELETE FROM level_resolutions",
    "UPDATE level_resolutions SET stream_id='foreign'", "UPDATE level_streams SET pending_archive_digest=(SELECT digest FROM level_update_archives LIMIT 1)"])
def test_corrupt_resolution_or_terminal_pointer_never_permits_new_reservation(tmp_path, sql):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    qualified = not_started(case, record)
    store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    new = fresh_record(case[1])
    with sqlite3.connect(store.path) as connection: connection.execute(sql)
    before = store.path.read_bytes()
    with pytest.raises(StoreCorrupt): store.level_baseline(qualified.to_dict()["original_binding_digest"])
    with pytest.raises(StoreCorrupt): store.reserve_level_update(new, expected_checkpoint=None)
    with pytest.raises(StoreCorrupt): store.history()
    assert store.path.read_bytes() == before


def test_double_terminal_is_detected_by_hot_read_and_each_evidence_reader(tmp_path):
    store, case, record, _, settled, _ = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    qualified = not_started(case, record)
    store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    data = settled.to_dict()
    with sqlite3.connect(store.path) as connection:
        connection.execute("INSERT INTO level_settlements VALUES (?, ?, ?, NULL, 0, ?, ?, ?)",
            (settled.digest, data["original_binding_digest"], record.digest, data["base_revision"], data["proposed_revision"], _canonical(data)))
    with pytest.raises(StoreCorrupt): store.level_baseline(data["original_binding_digest"])
    with pytest.raises(StoreCorrupt): store.get_level_resolution(qualified.digest)
    with pytest.raises(StoreCorrupt): store.get_level_settlement(settled.digest)
    with pytest.raises(StoreCorrupt): store.history()


def test_resolution_reopens_by_archive_in_new_process_without_fresh_objects(tmp_path):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    qualified = not_started(case, record)
    store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    script = '''
import json,sys
from unittest.mock import patch
from kir.project_store import ProjectStore
with patch('kir.compiler.plan_program',side_effect=AssertionError('no plan')),patch('kir.level_resolution.qualify_level_not_started',side_effect=AssertionError('no fresh qualification')):
    result=ProjectStore.open(sys.argv[1]).get_level_resolution_for_archive(sys.argv[2])
    assert type(result) is dict
    print(json.dumps(result))
'''
    child = subprocess.run([sys.executable, "-B", "-c", script, str(store.path), record.digest],
        capture_output=True, text=True, timeout=30, check=True, env=os.environ.copy())
    assert json.loads(child.stdout) == qualified.to_dict()


@pytest.mark.parametrize("mutation", ["stream_id='foreign'", "expected_checkpoint=NULL"])
def test_misattributed_resolution_cannot_hide_unresolved_archive_at_c1(tmp_path, mutation):
    store, case, first, after, settled, target = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(first, expected_checkpoint=None)
    store.commit_level_settlement(settled, expected_checkpoint=None, expected_pending_archive=first.digest)
    pending, update = second_archive(store, after, settled, target)
    store.reserve_level_update(pending, expected_checkpoint=settled.digest)
    qualified = not_started(case, pending)
    store.commit_level_not_started(qualified, expected_checkpoint=settled.digest, expected_pending_archive=pending.digest)
    new = fresh_record(update)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE level_resolutions SET " + mutation)
    with pytest.raises(StoreCorrupt): store.level_baseline(settled.to_dict()["original_binding_digest"])
    with pytest.raises(StoreCorrupt): store.reserve_level_update(new, expected_checkpoint=settled.digest)


def test_two_independent_processes_deliver_same_resolution_once(tmp_path):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    qualified = not_started(case, record)
    credentials = case[0]["credentials"]
    payload = json.dumps({"record": record._raw.decode(), "response": qualified.to_dict()["response"],
        "target": credentials.target.to_dict(), "session_id": credentials.session_id, "token": credentials.token}).encode()
    script = r'''
import json,sys
from kir.project_store import ProjectStore
from kir.saved_execution import SavedExecutionRecord
from kir.level_resolution import qualify_level_not_started
from kir.revit_connector import RuntimeTarget,SessionCredentials
data=json.load(sys.stdin)
record=SavedExecutionRecord._from_bytes(data['record'].encode())
credentials=SessionCredentials(RuntimeTarget(**data['target']),data['session_id'],data['token'])
qualified=qualify_level_not_started(record,json.dumps(data['response']),credentials=credentials,request_id=data['response']['request_id'])
result=ProjectStore.open(sys.argv[1],readonly=False).commit_level_not_started(qualified,expected_checkpoint=None,expected_pending_archive=record.digest)
print(json.dumps({'inserted':result.inserted,'digest':result.resolution_digest}))
'''
    children = [subprocess.Popen([sys.executable, "-B", "-c", script, str(store.path)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=os.environ.copy()) for _ in range(2)]
    for child in children:
        child.stdin.write(payload)
        child.stdin.close()
        child.stdin = None
    results = []
    for child in children:
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 0, stderr
        results.append(json.loads(stdout))
    assert sorted(result["inserted"] for result in results) == [False, True]
    assert {result["digest"] for result in results} == {qualified.digest}
    assert len(rows(store.path, "level_resolutions")) == 1
    assert store.history()


def test_corrupted_migration_copy_is_detected_before_old_table_drop(tmp_path, monkeypatch):
    store, _, record, _, _, _ = stored_case(tmp_path / "project.sqlite")
    store.reserve_level_update(record, expected_checkpoint=None)
    before = rows(store.path, "level_update_archives")
    original = storage._connect
    class ChangedCopy:
        def __init__(self, connection): self.inner = connection
        def __getattr__(self, name): return getattr(self.inner, name)
        def execute(self, sql, *args):
            result = self.inner.execute(sql, *args)
            if sql.startswith("INSERT INTO level_update_archives_next"):
                self.inner.execute("UPDATE level_update_archives_next SET payload='changed'")
            if sql.startswith("DROP TABLE"):
                raise AssertionError("unverified migration copy reached DROP")
            return result
    with monkeypatch.context() as local:
        local.setattr(storage, "_connect", lambda *a, **kw: ChangedCopy(original(*a, **kw)))
        with pytest.raises(StoreCorrupt, match="changed archived bytes"):
            store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert store.schema == REALIZATION_STORE_SCHEMA and rows(store.path, "level_update_archives") == before


def test_rollback_ack_failure_is_not_masked_by_foreign_key_restoration(tmp_path, monkeypatch):
    store, _, _, _, _, _ = stored_case(tmp_path / "project.sqlite")
    connect = storage._connect
    class FailedCommitRollback:
        def __init__(self, connection): self.inner = connection
        def __getattr__(self, name): return getattr(self.inner, name)
        def execute(self, sql, *args):
            if sql in ("COMMIT", "ROLLBACK"):
                raise sqlite3.OperationalError("injected transaction acknowledgement failure")
            return self.inner.execute(sql, *args)
    with monkeypatch.context() as local:
        local.setattr(storage, "_connect", lambda *a, **kw: FailedCommitRollback(connect(*a, **kw)))
        with pytest.raises(StoreCommitUnknown):
            store.upgrade_schema(RESOLUTION_STORE_SCHEMA, expected_revision=store.head().revision_id)
    # Closing the actual SQLite connection rolls back this injected failure.
    # The API still must not have claimed a confirmed rollback to its caller.
    assert store.schema == REALIZATION_STORE_SCHEMA
    with store._transaction() as (connection, _):
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
