"""Store/5 migration and transaction-local helpers; no agent/native execution."""
from copy import deepcopy
import json
import sqlite3

import pytest

from kir import project_store as storage
from kir import project_realization_store as ledger
from kir.project_store import (ProjectStore, TASK_STORE_SCHEMA, STORE_SCHEMA, GEOMETRY_STORE_SCHEMA,
    REALIZATION_STORE_SCHEMA, RESOLUTION_STORE_SCHEMA, StoreConflict, StoreCorrupt,
    StoreReadOnly, ProjectStoreError, _commit_revision, _read_history, _read_state)
from kir.tests.test_project_store import root, changed
from kir.tests.test_project_realization_store import stored_case
from kir.tests.test_project_level_resolution_store import not_started, fresh_record


def table_rows(path, names):
    with sqlite3.connect(path) as connection:
        return {name: connection.execute('SELECT * FROM "' + name + '"').fetchall() for name in names}


@pytest.mark.parametrize("schema", [STORE_SCHEMA, GEOMETRY_STORE_SCHEMA, REALIZATION_STORE_SCHEMA, RESOLUTION_STORE_SCHEMA])
def test_explicit_upgrade5_preserves_history_native_payloads_and_store_identity(tmp_path, schema):
    from kir.project_tasks import TASK_TABLES

    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=schema)
    names = ["revisions"]
    if schema != STORE_SCHEMA: names.append("geometry_assets")
    if schema in (REALIZATION_STORE_SCHEMA, RESOLUTION_STORE_SCHEMA):
        names.extend(ledger.realization_tables(schema))
        store.reserve_level_update(record, expected_checkpoint=None)
    if schema == RESOLUTION_STORE_SCHEMA:
        evidence = not_started(case, record)
        store.commit_level_not_started(evidence, expected_checkpoint=None, expected_pending_archive=record.digest)
    before = table_rows(store.path, names)
    head, store_id = store.head().revision_id, store.store_id
    reader = ProjectStore.open(store.path)
    with pytest.raises(StoreReadOnly): reader.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=head)
    with pytest.raises(StoreConflict): store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision="f" * 64)
    assert store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=head)
    assert not store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=head)
    assert reader.schema == TASK_STORE_SCHEMA and reader.store_id == store_id
    assert store.head().revision_id == head
    assert table_rows(store.path, names) == before
    assert all(rows == [] for rows in table_rows(store.path, TASK_TABLES).values())
    assert tuple(item.dumps() for item in store.history()) == tuple(row[-1] for row in before["revisions"])
    with store._transaction(write=True) as (connection, state):
        assert state.schema == TASK_STORE_SCHEMA
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        sql = connection.execute("SELECT sql FROM sqlite_schema WHERE name='level_update_archives'").fetchone()[0]
        assert storage._normalized_sql(sql) == storage._normalized_sql(ledger.realization_tables(RESOLUTION_STORE_SCHEMA)["level_update_archives"])
    if schema == REALIZATION_STORE_SCHEMA:
        assert store.level_baseline(record.update_submission["original_publication"]["binding_digest"]).pending_archive_digest == record.digest
    if schema == RESOLUTION_STORE_SCHEMA:
        assert store.get_level_resolution_for_archive(record.digest) == evidence.to_dict()
        assert store.status()["native"]["streams"][0]["not_started_at_checkpoint"] == 1


def test_new5_has_all_tables_and_cannot_implicitly_downgrade(tmp_path):
    from kir.project_tasks import TASK_TABLES

    project = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", project, schema=TASK_STORE_SCHEMA)
    assert store.schema == TASK_STORE_SCHEMA and store.history() == (project,)
    with sqlite3.connect(store.path) as connection:
        actual = {name for name, in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert actual == {"revisions", "project_store", "geometry_assets", *ledger.realization_tables(TASK_STORE_SCHEMA), *TASK_TABLES}
    for older in (GEOMETRY_STORE_SCHEMA, REALIZATION_STORE_SCHEMA, RESOLUTION_STORE_SCHEMA):
        with pytest.raises(StoreConflict): store.upgrade_schema(older, expected_revision=project.revision_id)


def test_schema5_missing_task_table_is_not_accepted_as_an_empty_task_catalog(tmp_path):
    from kir.project_tasks import TASK_TABLES

    store = ProjectStore.create(tmp_path / "project.sqlite", root(), schema=TASK_STORE_SCHEMA)
    name = next(iter(TASK_TABLES))
    with sqlite3.connect(store.path) as connection:
        connection.execute('DROP TABLE "' + name + '"')
    with pytest.raises(StoreCorrupt): ProjectStore.open(store.path)


def test_failed_upgrade5_rolls_back_all_new_schema_changes(tmp_path, monkeypatch):
    from kir import project_tasks

    store = ProjectStore.create(tmp_path / "project.sqlite", root(), schema=REALIZATION_STORE_SCHEMA)
    before = table_rows(store.path, ("revisions", "project_store", *ledger.REALIZATION_TABLES))
    with monkeypatch.context() as scoped:
        scoped.setattr(project_tasks, "TASK_TABLES", {**project_tasks.TASK_TABLES, "broken": "INVALID SQL"})
        with pytest.raises(ProjectStoreError):
            store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert store.schema == REALIZATION_STORE_SCHEMA
    assert table_rows(store.path, before) == before
    assert store.history()


def test_transaction_local_append_never_commits_and_rolls_back_with_its_caller(tmp_path):
    project = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", project)
    candidate = changed(project)
    with pytest.raises(RuntimeError, match="caller failed"):
        with store._transaction(write=True) as (connection, state):
            result = _commit_revision(connection, state, candidate, expected_revision=project.revision_id)
            assert result.inserted and connection.in_transaction
            assert _read_history(connection, _read_state(connection)) == (project, candidate)
            raise RuntimeError("caller failed")
    assert store.head() == project and store.history() == (project,)
    with store._transaction(write=True) as (connection, state):
        assert _commit_revision(connection, state, candidate, expected_revision=project.revision_id).inserted
        assert connection.in_transaction
    assert store.head() == candidate
    newer = changed(candidate, "newer")
    store.commit(newer, expected_revision=candidate.revision_id)
    with store._transaction(write=True) as (connection, state):
        retry = _commit_revision(connection, state, candidate, expected_revision=project.revision_id)
        assert not retry.inserted and retry.head_revision == newer.revision_id
    assert store.head() == newer


def test_transaction_local_helpers_reject_autocommit_connections(tmp_path):
    project = root()
    store = ProjectStore.create(tmp_path / "project.sqlite", project)
    connection = storage._connect(store.path, readonly=False, timeout=1)
    try:
        state = _read_state(connection)
        with pytest.raises(ProjectStoreError, match="existing transaction"):
            _commit_revision(connection, state, changed(project), expected_revision=project.revision_id)
        with pytest.raises(ProjectStoreError, match="existing transaction"):
            _read_history(connection, state)
    finally:
        connection.close()
    assert store.head() == project


def test_task_audit_extends_shared_asset_cache_before_orphan_check(tmp_path, monkeypatch):
    from kir import project_tasks

    store = ProjectStore.create(tmp_path / "project.sqlite", root(), schema=TASK_STORE_SCHEMA)
    trace = []
    actual = project_tasks.audit_tasks
    def tracked(connection, state, *, asset_cache):
        assert connection.in_transaction and type(asset_cache) is dict
        trace.append("task audit")
        return actual(connection, state, asset_cache=asset_cache)
    monkeypatch.setattr(project_tasks, "audit_tasks", tracked)
    with store._transaction() as (connection, state):
        connection.set_trace_callback(trace.append)
        _read_history(connection, state)
    assert trace.index("task audit") < next(index for index, sql in enumerate(trace) if sql == "SELECT digest FROM geometry_assets")


def test_schema5_preserves_resolution4_and_new_reservation_semantics(tmp_path):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=TASK_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    resolved = not_started(case, record)
    result = store.commit_level_not_started(resolved, expected_checkpoint=None, expected_pending_archive=record.digest)
    assert result.inserted and not result.may_retry
    stream = resolved.to_dict()["original_binding_digest"]
    assert store.level_baseline(stream).pending_archive_digest is None
    fresh = fresh_record(case[1])
    assert store.reserve_level_update(fresh, expected_checkpoint=None).inserted
    replay = store.commit_level_not_started(resolved, expected_checkpoint=None, expected_pending_archive=record.digest)
    assert not replay.inserted and replay.pending_archive_digest == fresh.digest
    assert store.get_level_resolution(resolved.digest) == resolved.to_dict()
    assert store.history()


@pytest.mark.parametrize("terminal", [True, False])
def test_public_cancel_door_keeps_resolution4_scope_on_schema5(tmp_path, monkeypatch, terminal):
    from kir import revit_transport
    from kir.tests.test_pending_level_cancellation import call_cancel
    from kir.tests.test_level_resolution import before_start_response

    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=TASK_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    stream = record.update_submission["original_publication"]["binding_digest"]
    calls = []
    def exchange(_advertisement, raw, **kwargs):
        request = json.loads(raw)
        calls.append(request["kind"])
        response = before_start_response(case, "cancelled_before_start") if terminal else deepcopy(case[3])
        response["request_id"] = request["request_id"]
        if not terminal:
            response["receipt"].update(state="running_unknown", started=True, may_retry=False)
        return json.dumps(response).encode()
    monkeypatch.setattr(revit_transport, "exchange", exchange)
    result = call_cancel(store, case, record, stream)
    assert calls == ["cancel_before_start"] and result.resolution_recorded is terminal
    assert result.may_retry is False
    assert store.level_baseline(stream).pending_archive_digest == (None if terminal else record.digest)
    assert store.history()
