"""Real SQLite CREATE input ownership; no native execution/receipt qualification."""
from dataclasses import FrozenInstanceError, replace
import json
import os
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest

from kir import project_store as storage
from kir import project_create_store as creates
from kir.geometry_materialization import materialize_project, materialize_selection
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, _canonical, _hash
from kir.project_merge import ProposalScope
from kir.project_selection import select_project_instances
from kir.project_submission import bind_project_submission, bind_selected_project_submission
from kir.project_store import (ProjectStore, CREATE_STORE_SCHEMA, TASK_STORE_SCHEMA,
    STORE_SCHEMA, GEOMETRY_STORE_SCHEMA, REALIZATION_STORE_SCHEMA, RESOLUTION_STORE_SCHEMA,
    StoreConflict, StoreCorrupt, StoreNotFound, StoreReadOnly, StoreUpgradeRequired, StoreCommitUnknown, ProjectStoreError)
from kir.revit_connector import RuntimeTarget, ContextPrecondition, prepare_execution
from kir.saved_execution import SavedExecutionRecord, _capture
from kir.tests.test_selected_project_submission import source_project, TARGET


def archive(project, *, roots=None, operation=None, target=TARGET, document="native-document", revision=7):
    if roots is None:
        materialized = materialize_project(project, {})
        binder = bind_project_submission
    else:
        choice = select_project_instances(project, instance_keys=roots)
        materialized = materialize_selection(project, choice, {})
        binder = bind_selected_project_submission
    prepared = prepare_execution(materialized.planned, target=target,
        precondition=ContextPrecondition(document, revision), operation_id=operation or str(uuid4()))
    binding = binder(project, materialized, prepared)
    return SavedExecutionRecord._from_bytes(_capture(prepared, submission=binding))


def case(tmp_path, *, roots=("section",), schema=CREATE_STORE_SCHEMA):
    source = source_project()
    store = ProjectStore.create(tmp_path / "project.sqlite", source, schema=schema)
    return store, source, archive(source, roots=roots)


def rows(path):
    with sqlite3.connect(path) as connection:
        return {name: connection.execute("SELECT * FROM " + name).fetchall() for name in creates.CREATE_TABLES}


def test_first_reservation_retains_exact_input_and_all_selected_dependency_outputs(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    before = source.dumps()
    with monkeypatch.context() as no_execution:
        import kir.compiler
        no_execution.setattr(kir.compiler, "plan_program", lambda *_a, **_kw: pytest.fail("reservation replanned"))
        no_execution.setattr(kir.compiler, "compile_program", lambda *_a, **_kw: pytest.fail("reservation compiled"))
        first = store.reserve_create_publication(record, expected_revision=source.revision_id)
        assert first.inserted and not first.may_retry
        assert first.archive_digest == record.digest
        assert first.output_ids == tuple(row["output_id"] for row in record.project_submission["outputs"])
        assert len(first.output_ids) == 2  # Includes the cross-instance level dependency.
        with pytest.raises(FrozenInstanceError): first.inserted = False
        loaded = store.get_create_publication(record.digest)
        assert loaded.record._raw == record._raw
        assert loaded.state == "reserved" and not loaded.may_retry
        assert loaded.store_id == store.store_id and loaded.project_id == source.project_id
        assert loaded.output_ids == first.output_ids and loaded.source_revision == source.revision_id
        assert not any(hasattr(loaded, method) for method in ("execute_request", "planned", "require_identity"))
        detached = loaded.to_dict()
        detached["input"]["source"] = "changed caller copy"
        assert loaded.record.to_dict()["source"] == record.to_dict()["source"]
    assert store.head().dumps() == before and store.history() == (source,)
    assert len(rows(store.path)["create_inputs"]) == 1
    assert len(rows(store.path)["create_scope_owners"]) == 2
    assert rows(store.path)["create_receipts"] == []


def test_exact_replay_and_historical_read_ignore_registry_evolution_and_later_head(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    later = source.revise(expected_revision=source.revision_id, metadata={"draft": "later"})
    store.commit(later, expected_revision=source.revision_id)
    import kir.bridge_result
    import kir.project_submission
    actual_validate = kir.project_submission.validate_submission_source
    policies = []
    def retained_only(project, submission, *, selection_policy="current"):
        policies.append(selection_policy)
        assert selection_policy == "retained"
        return actual_validate(project, submission, selection_policy=selection_policy)
    monkeypatch.setattr(kir.project_submission, "validate_submission_source", retained_only)
    monkeypatch.setattr(kir.bridge_result, "saved_create_result_contract",
                        lambda *_: pytest.fail("historical lookup consulted current registry admission"))
    readonly = ProjectStore.open(store.path)
    assert readonly.get_create_publication(record.digest).record._raw == record._raw
    replay = store.reserve_create_publication(record, expected_revision=source.revision_id)
    assert not replay.inserted and not replay.may_retry and policies
    assert store.head().revision_id == later.revision_id
    with pytest.raises(StoreConflict):
        store.reserve_create_publication(record, expected_revision=later.revision_id)


def test_known_operation_lookup_after_reopen_is_inert_and_does_not_need_current_head(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    later = source.revise(expected_revision=source.revision_id, metadata={"later": True})
    store.commit(later, expected_revision=source.revision_id)
    import kir.compiler
    monkeypatch.setattr(kir.compiler, "plan_program", lambda *_a, **_kw: pytest.fail("lookup replanned"))
    reopened = ProjectStore.open(store.path)
    before = store.path.read_bytes()
    binding = record.binding_dict()
    found = reopened.find_create_publication(journal_id=binding["target"]["journal_id"],
                                             operation_id=binding["operation_id"])
    assert found.record._raw == record._raw and found.archive_digest == record.digest
    assert found.source_revision == source.revision_id and not found.may_retry
    assert reopened.head().revision_id == later.revision_id
    assert store.path.read_bytes() == before
    with pytest.raises(StoreNotFound):
        reopened.find_create_publication(journal_id=str(uuid4()), operation_id=binding["operation_id"])
    with pytest.raises(StoreNotFound):
        reopened.find_create_publication(journal_id=binding["target"]["journal_id"], operation_id=str(uuid4()))
    with pytest.raises(ProjectStoreError):
        reopened.find_create_publication(journal_id="bad", operation_id=binding["operation_id"])


@pytest.mark.parametrize("roots", [None, ("section",), ("datums",), ("section", "unselected")])
def test_second_uuid_subset_or_superset_cannot_republish_owned_outputs(tmp_path, roots):
    store, source, first = case(tmp_path)
    store.reserve_create_publication(first, expected_revision=source.revision_id)
    before = rows(store.path)
    other = archive(source, roots=roots)
    with pytest.raises(StoreConflict, match="output scope"):
        store.reserve_create_publication(other, expected_revision=source.revision_id)
    assert rows(store.path) == before


@pytest.mark.parametrize("axis", ["context_revision", "authored_revision"])
def test_context_or_authoring_revision_does_not_release_output_ownership(tmp_path, axis):
    store, source, first = case(tmp_path)
    store.reserve_create_publication(first, expected_revision=source.revision_id)
    if axis == "authored_revision":
        later = source.revise(expected_revision=source.revision_id, metadata={"new": True})
        store.commit(later, expected_revision=source.revision_id)
        source = later
    other = archive(source, roots=("section",), revision=99)
    with pytest.raises(StoreConflict, match="output scope"):
        store.reserve_create_publication(other, expected_revision=source.revision_id)


@pytest.mark.parametrize("axis", ["document", "journal", "instance", "year", "disjoint_outputs"])
def test_distinct_native_namespace_or_disjoint_outputs_are_separate_reservations(tmp_path, axis):
    store, source, first = case(tmp_path)
    store.reserve_create_publication(first, expected_revision=source.revision_id)
    options = {"roots": ("section",)}
    if axis == "document": options["document"] = "another-document"
    elif axis == "journal": options["target"] = replace(TARGET, journal_id=str(uuid4()))
    elif axis == "instance": options["target"] = replace(TARGET, instance_id=str(uuid4()))
    elif axis == "year": options["target"] = replace(TARGET, revit_version="2023")
    else: options["roots"] = ("unselected",)
    other = archive(source, **options)
    assert store.reserve_create_publication(other, expected_revision=source.revision_id).inserted
    assert len(rows(store.path)["create_inputs"]) == 2


def test_same_native_operation_uuid_conflicts_even_across_document_and_subset(tmp_path):
    store, source, first = case(tmp_path)
    store.reserve_create_publication(first, expected_revision=source.revision_id)
    other = archive(source, roots=("unselected",), document="different", operation=first.binding_dict()["operation_id"])
    with pytest.raises(StoreConflict, match="operation identity"):
        store.reserve_create_publication(other, expected_revision=source.revision_id)


def test_wrong_or_unstored_source_and_stale_first_head_refuse_without_rows(tmp_path):
    store, source, record = case(tmp_path)
    with pytest.raises(StoreConflict):
        store.reserve_create_publication(record, expected_revision="f" * 64)
    missing = source.revise(expected_revision=source.revision_id, metadata={"not": "stored"})
    missing_record = archive(missing, roots=("section",))
    with pytest.raises(StoreConflict):
        store.reserve_create_publication(missing_record, expected_revision=missing.revision_id)
    store.commit(missing, expected_revision=source.revision_id)
    with pytest.raises(StoreConflict, match="current authored head"):
        store.reserve_create_publication(record, expected_revision=source.revision_id)
    assert all(not value for value in rows(store.path).values())


@pytest.mark.parametrize("fault", ["missing_owner", "extra_owner", "wrong_owner", "orphan_owner", "metadata", "payload"])
def test_corrupt_ownership_catalog_is_not_interpreted_as_free_scope(tmp_path, fault):
    store, source, first = case(tmp_path)
    store.reserve_create_publication(first, expected_revision=source.revision_id)
    with sqlite3.connect(store.path) as connection:
        if fault == "missing_owner":
            connection.execute("DELETE FROM create_scope_owners WHERE output_id=?", (first.project_submission["outputs"][0]["output_id"],))
        elif fault == "extra_owner":
            old = connection.execute("SELECT * FROM create_scope_owners LIMIT 1").fetchone()
            connection.execute("INSERT INTO create_scope_owners VALUES (?,?,?,?,?,?)", (*old[:4], "f" * 64, old[5]))
        elif fault == "wrong_owner":
            connection.execute("UPDATE create_scope_owners SET document_key='foreign-document'")
        elif fault == "orphan_owner":
            connection.execute("DELETE FROM create_inputs")  # This test-only connection has FK enforcement off.
        elif fault == "metadata":
            connection.execute("UPDATE create_inputs SET operation_id=?", (str(uuid4()),))
        else:
            connection.execute("UPDATE create_inputs SET payload='{}'")
    before = rows(store.path)
    for operation in (lambda: store.get_create_publication(first.digest),
                      lambda: store.reserve_create_publication(archive(source, roots=("unselected",)), expected_revision=source.revision_id),
                      store.history):
        with pytest.raises(StoreCorrupt): operation()
    assert rows(store.path) == before


def test_payload_budget_is_checked_before_decoding_the_blob(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    monkeypatch.setattr(creates, "MAX_RECORD_BYTES", 16)
    monkeypatch.setattr(SavedExecutionRecord, "_from_bytes", lambda *_: pytest.fail("oversized input was decoded"))
    with pytest.raises(StoreCorrupt, match="bounded archive size"):
        store.get_create_publication(record.digest)


@pytest.mark.parametrize("old_schema", [STORE_SCHEMA, GEOMETRY_STORE_SCHEMA, REALIZATION_STORE_SCHEMA, RESOLUTION_STORE_SCHEMA, TASK_STORE_SCHEMA])
def test_explicit_upgrade6_preserves_old_payloads_and_task_native_tables(tmp_path, old_schema):
    store, source, record = case(tmp_path, schema=old_schema)
    candidate = source.revise(expected_revision=source.revision_id, metadata={"draft": 2})
    store.commit(candidate, expected_revision=source.revision_id)
    with sqlite3.connect(store.path) as connection:
        old_tables = [name for name, in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")]
        before = {name: connection.execute("SELECT * FROM " + name).fetchall() for name in old_tables if name != "project_store"}
    with pytest.raises(StoreUpgradeRequired):
        store.reserve_create_publication(record, expected_revision=source.revision_id)
    reader = ProjectStore.open(store.path)
    with pytest.raises(StoreReadOnly): reader.upgrade_schema(CREATE_STORE_SCHEMA, expected_revision=candidate.revision_id)
    assert store.upgrade_schema(CREATE_STORE_SCHEMA, expected_revision=candidate.revision_id)
    assert not store.upgrade_schema(CREATE_STORE_SCHEMA, expected_revision=candidate.revision_id)
    assert reader.schema == CREATE_STORE_SCHEMA and reader.store_id == store.store_id
    assert [value.dumps() for value in store.history()] == [source.dumps(), candidate.dumps()]
    with sqlite3.connect(store.path) as connection:
        assert {name: connection.execute("SELECT * FROM " + name).fetchall() for name in before} == before
    assert all(not value for value in rows(store.path).values())
    with pytest.raises(StoreConflict): store.upgrade_schema(TASK_STORE_SCHEMA, expected_revision=candidate.revision_id)


def test_schema6_keeps_existing_task_and_level_semantics_and_payloads(tmp_path):
    from kir.tests.test_project_realization_store import stored_case
    from kir.project_tasks import create_task, checkpoint_task, read_task
    store, _, level_record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=TASK_STORE_SCHEMA)
    reserved = store.reserve_level_update(level_record, expected_checkpoint=None)
    task = create_task(store, task_id="task", base_revision=store.head().revision_id, actor="worker", objective="Retain grant",
                       scope=ProposalScope(instances=("section",)))["task"]
    with sqlite3.connect(store.path) as connection:
        before = {name: connection.execute("SELECT * FROM " + name).fetchall() for name in ("level_update_archives", "level_streams", "level_scope_owners", "task_events", "task_heads")}
    store.upgrade_schema(CREATE_STORE_SCHEMA, expected_revision=store.head().revision_id)
    assert store.level_baseline(reserved.stream_id).pending_archive_digest == level_record.digest
    assert store.get_level_update_archive(level_record.digest)._raw == level_record._raw
    assert read_task(store, "task") == task
    with sqlite3.connect(store.path) as connection:
        assert {name: connection.execute("SELECT * FROM " + name).fetchall() for name in before} == before
    checkpoint_task(store, "task", request_id="checkpoint", expected_version=task["version"], generation=0, actor="worker", notes={"stage": 1})
    assert store.history()


@pytest.mark.parametrize("first", ["create", "level"])
def test_cross_method_native_uuid_exclusion_works_both_directions(tmp_path, first):
    from kir.tests.test_project_realization_store import stored_case
    store, _, level_record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=CREATE_STORE_SCHEMA)
    binding = level_record.binding_dict()
    create_record = archive(store.head(), operation=binding["operation_id"], target=RuntimeTarget(**binding["target"]),
                            document=binding["precondition"]["document_key"])
    reserve_create = lambda: store.reserve_create_publication(create_record, expected_revision=store.head().revision_id)
    reserve_level = lambda: store.reserve_level_update(level_record, expected_checkpoint=None)
    (reserve_create if first == "create" else reserve_level)()
    with pytest.raises(StoreConflict, match="operation identity"):
        (reserve_level if first == "create" else reserve_create)()
    assert len(rows(store.path)["create_inputs"]) == (1 if first == "create" else 0)


def test_read_uses_readonly_connection_and_never_recovers_or_writes(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    before, actual, modes = store.path.read_bytes(), storage._connect, []
    def observed(path, **options):
        modes.append(options["readonly"])
        return actual(path, **options)
    monkeypatch.setattr(storage, "_connect", observed)
    assert store.get_create_publication(record.digest).archive_digest == record.digest
    assert modes == [True] and store.path.read_bytes() == before
    with pytest.raises(StoreReadOnly):
        ProjectStore.open(store.path).reserve_create_publication(record, expected_revision=source.revision_id)
    with pytest.raises(StoreNotFound): store.get_create_publication("f" * 64)


def test_lost_commit_ack_retains_ownership_and_exact_replay_never_grants_retry(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    actual = storage._commit
    def lost(connection):
        actual(connection)
        raise StoreCommitUnknown("controlled acknowledgement loss")
    with monkeypatch.context() as fault:
        fault.setattr(storage, "_commit", lost)
        with pytest.raises(StoreCommitUnknown):
            store.reserve_create_publication(record, expected_revision=source.revision_id)
    replay = store.reserve_create_publication(record, expected_revision=source.revision_id)
    assert not replay.inserted and not replay.may_retry
    assert store.get_create_publication(record.digest).record._raw == record._raw


def test_failed_owner_insertion_rolls_back_input_atomically(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    actual = storage._connect
    class Connection:
        def __init__(self, connection): self.connection = connection
        def __getattr__(self, name): return getattr(self.connection, name)
        def executemany(self, sql, values):
            if sql.startswith("INSERT INTO create_scope_owners"):
                raise RuntimeError("controlled failure after input insert")
            return self.connection.executemany(sql, values)
    with monkeypatch.context() as fault:
        fault.setattr(storage, "_connect", lambda *args, **kwargs: Connection(actual(*args, **kwargs)))
        with pytest.raises(RuntimeError): store.reserve_create_publication(record, expected_revision=source.revision_id)
    assert all(not value for value in rows(store.path).values())


def test_two_real_processes_compete_for_one_output_scope(tmp_path):
    store, source, first = case(tmp_path)
    second = archive(source, roots=("section",))
    script = """
import json,sys
from kir.project_store import ProjectStore,StoreConflict
from kir.saved_execution import SavedExecutionRecord
s=ProjectStore.open(sys.argv[1],readonly=False)
r=SavedExecutionRecord._from_bytes(sys.stdin.buffer.read())
try:
    value=s.reserve_create_publication(r,expected_revision=r.project_submission['project']['revision_id'])
    print(json.dumps({'inserted':value.inserted,'retry':value.may_retry}))
except StoreConflict:
    print(json.dumps({'conflict':True}))
"""
    children = [subprocess.Popen([sys.executable, "-c", script, str(store.path)], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")) for _ in range(2)]
    for child, record in zip(children, (first, second), strict=True):
        child.stdin.write(record._raw)
        child.stdin.close()
        child.stdin = None
    results = []
    for child in children:
        stdout, stderr = child.communicate(timeout=30)
        assert child.returncode == 0, stderr.decode()
        results.append(json.loads(stdout))
    assert sum(result.get("inserted", False) for result in results) == 1
    assert sum(result.get("conflict", False) for result in results) == 1
    assert len(rows(store.path)["create_inputs"]) == 1 and len(rows(store.path)["create_scope_owners"]) == 2


def test_new_archive_profile_admission_is_not_bypassed(tmp_path, monkeypatch):
    store, source, record = case(tmp_path)
    import kir.bridge_result
    def refused(record): raise ValueError("controlled unsupported current CREATE contract")
    monkeypatch.setattr(kir.bridge_result, "saved_create_result_contract", refused)
    with pytest.raises(StoreConflict, match="current flat CREATE"):
        store.reserve_create_publication(record, expected_revision=source.revision_id)
    assert all(not value for value in rows(store.path).values())


def test_rehashed_archive_claims_are_compared_with_actual_stored_source(tmp_path):
    store, source, record = case(tmp_path)
    data = record.to_dict()
    submitted = data["project_submission"]
    submitted["instances"][0]["instance_snapshot_digest"] = "f" * 64
    submitted["submission_digest"] = _hash({key: value for key, value in submitted.items() if key != "submission_digest"})
    data["record_digest"] = _hash({key: value for key, value in data.items() if key != "record_digest"})
    forged = SavedExecutionRecord._from_bytes(_canonical(data).encode())
    with pytest.raises(StoreConflict, match="actual stored source"):
        store.reserve_create_publication(forged, expected_revision=source.revision_id)
    assert all(not value for value in rows(store.path).values())


@pytest.mark.parametrize("kind", ["macro", "mutation", "query", "group"])
def test_actual_nonflat_or_noncreate_project_archives_do_not_reserve(tmp_path, kind):
    if kind == "macro":
        operation = {"op": "stack", "levels": 2, "h_mm": 3000, "floor": [
            {"op": "create_wall", "id": "wall", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]}
    elif kind == "mutation":
        operation = {"op": "set_param", "target": {"by": "element_id", "value": 100}, "param": "Comments", "value": "note"}
    elif kind == "query":
        operation = {"op": "query_count", "kind": "wall"}
    else:
        operation = {"op": "create_group", "name": "Group", "members": [
            {"op": "create_wall", "id": "wall", "p0_mm": [0, 0], "p1_mm": [5000, 0],
             "level": {"by": "element_id", "value": 42}}], "placements": [[0, 0, 0]]}
    source = ProjectRevision("nonflat", [ModuleDefinition("m")], [ModuleInstance("i", "m", {"output": operation})])
    record = archive(source)
    store = ProjectStore.create(tmp_path / "project.sqlite", source, schema=CREATE_STORE_SCHEMA)
    with pytest.raises(StoreConflict, match="current flat CREATE"):
        store.reserve_create_publication(record, expected_revision=source.revision_id)
    assert all(not value for value in rows(store.path).values())


def test_nonproject_saved_archive_and_missing_schema_tables_refuse(tmp_path):
    store, source, record = case(tmp_path)
    data = record.to_dict()
    data["schema"] = "kir-saved-execution/1"
    data.pop("project_submission")
    from kir.saved_execution import _CLAIMS
    data["claims"] = dict(_CLAIMS)
    data["record_digest"] = _hash({key: value for key, value in data.items() if key != "record_digest"})
    ordinary = SavedExecutionRecord._from_bytes(_canonical(data).encode())
    with pytest.raises(ProjectStoreError):
        store.reserve_create_publication(ordinary, expected_revision=source.revision_id)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE create_receipts")
    with pytest.raises(StoreCorrupt): ProjectStore.open(store.path)


@pytest.mark.parametrize("when", ["after_input_before_owners", "after_commit"])
def test_real_process_crash_never_leaves_a_partially_owned_scope(tmp_path, when):
    store, source, record = case(tmp_path)
    script = """
import os,sys
from kir import project_store as storage
from kir.saved_execution import SavedExecutionRecord
s=storage.ProjectStore.open(sys.argv[1],readonly=False)
r=SavedExecutionRecord._from_bytes(sys.stdin.buffer.read())
if sys.argv[2]=='after_commit':
    original=storage._commit
    def stopped(c):
        original(c)
        os._exit(72)
    storage._commit=stopped
else:
    original=storage._connect
    class Connection:
        def __init__(self,c): self.c=c
        def __getattr__(self,key): return getattr(self.c,key)
        def executemany(self,sql,values):
            if sql.startswith('INSERT INTO create_scope_owners'): os._exit(71)
            return self.c.executemany(sql,values)
    storage._connect=lambda *a,**k:Connection(original(*a,**k))
s.reserve_create_publication(r,expected_revision=r.project_submission['project']['revision_id'])
"""
    stopped = subprocess.run([sys.executable, "-c", script, str(store.path), when], input=record._raw,
        capture_output=True, timeout=30, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert stopped.returncode == (71 if when == "after_input_before_owners" else 72), stopped.stderr.decode()
    # Explicit writable open owns recovery if SQLite left a rollback journal.
    recovered = ProjectStore.open(store.path, readonly=False)
    if when == "after_input_before_owners":
        assert all(not value for value in rows(store.path).values())
        with pytest.raises(StoreNotFound): recovered.get_create_publication(record.digest)
    else:
        assert recovered.get_create_publication(record.digest).record._raw == record._raw
        replay = recovered.reserve_create_publication(record, expected_revision=source.revision_id)
        assert not replay.inserted and not replay.may_retry
    assert recovered.head().revision_id == source.revision_id
