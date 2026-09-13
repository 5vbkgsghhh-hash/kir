"""Real staged factories and SQLite edges; native receipts remain synthetic."""
from contextlib import contextmanager
from collections import Counter
from copy import copy, deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

from kir import project_create_store as creates
from kir.create_publication import (assess_create_identities, bind_create_receipt,
                                    retained_create_identity_claims, CreatePublicationError)
from kir.geometry_materialization import materialize_selection
from kir.project import ModuleInstance, output_id, _canonical, _hash, _object
from kir.project_selection import select_project_instances
from kir.project_submission import bind_selected_project_submission
from kir.project_store import ProjectStore, STAGED_CREATE_STORE_SCHEMA, StoreConflict, StoreCorrupt
from kir.revit_connector import (ContextPrecondition, prepare_execution, EXECUTION_ASSOCIATION_PREFIX,
                                 RuntimeTarget, SessionCredentials)
from kir.saved_execution import SavedExecutionRecord
from kir.staged_create_projection import prepare_staged_create, bind_staged_create_projection
from kir.staged_submission import bind_staged_project_submission
from kir.tests import test_staged_create_projection as stages
from kir.tests.test_revit_level_update import response_for
from kir.viewer.tests.test_live_scene_mesh import _VAULT


def staged_case(tmp_path, *, seed_input=True, seed_receipt=True, reused=False):
    root = stages.shared_project()
    source = root.revise(expected_revision=root.revision_id, instances=[*root.instances,
        ModuleInstance("preserved-concept", "m", {"body": {"op": "create_directshape",
            "category": "mass", "name": "Preserved concept", "mesh": _VAULT}},
            metadata={"role": "preserved_conceptual_source", "native_execution": "not_run"})])
    with pytest.MonkeyPatch.context() as patched:
        patched.setattr(stages, "shared_project", lambda **_kwargs: source)
        value = stages.case(original_reused=reused)
    projection = stages.project(value)
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    submission = bind_staged_project_submission(projection, prepared)
    child = SavedExecutionRecord.capture_project(prepared, submission)
    store = ProjectStore.create(tmp_path / "project.sqlite", root, schema=STAGED_CREATE_STORE_SCHEMA)
    store.commit(source, expected_revision=root.revision_id)
    if seed_input:
        store.reserve_create_publication(value["archive"], expected_revision=source.revision_id)
        if seed_receipt:
            store.record_create_receipt(value["bound"])
    return store, value, child, submission


def _expected(child):
    return sorted((child.digest, row["output_id"], row["original_archive_digest"], row["original_receipt_digest"])
                  for row in child.project_submission["projection"]["association_core"]["import_lineage"])


def _rows(path, table="create_imports"):
    assert table in ("create_imports", "create_inputs", "create_receipts", "create_scope_owners")
    with sqlite3.connect(path) as connection:
        return sorted(connection.execute("SELECT * FROM " + table).fetchall())


def reserve(store, child, submission):
    return store.reserve_create_publication(child, expected_revision=child.project_submission["project"]["revision_id"],
                                           submission=submission)


@pytest.mark.parametrize("reused", [False, True])
def test_staged_reservation_persists_exact_import_edges_and_only_owns_exports(tmp_path, reused):
    store, value, child, submission = staged_case(tmp_path, reused=reused)
    saved = reserve(store, child, submission)
    assert saved.inserted and not saved.may_retry
    assert _rows(store.path) == _expected(child)
    imported = {row[1] for row in _expected(child)}
    assert set(saved.output_ids).isdisjoint(imported) and len(saved.output_ids) == 1
    owners = _rows(store.path, "create_scope_owners")
    assert {row[4] for row in owners if row[5] == child.digest} == set(saved.output_ids)
    assert {row[4] for row in owners if row[5] == value["archive"].digest} >= imported
    excluded = output_id(value["project"].project_id, "preserved-concept", "body")
    assert excluded not in {row[4] for row in owners}
    assert store.head().instances[-1].key == "preserved-concept"
    reloaded = ProjectStore.open(store.path, readonly=False)
    assert reloaded.get_create_publication(child.digest).record._raw == child._raw
    assert not reloaded.reserve_create_publication(child, expected_revision=value["project"].revision_id).inserted
    assert _rows(store.path) == _expected(child)


@pytest.mark.parametrize("missing", ["input", "receipt"])
def test_missing_original_input_or_receipt_refuses_before_inserting_child(tmp_path, missing):
    store, _, child, submission = staged_case(tmp_path,
        seed_input=missing != "input", seed_receipt=False)
    tables = ("create_inputs", "create_scope_owners", "create_receipts", "create_imports")
    before = {name: _rows(store.path, name) for name in tables}
    with pytest.raises(StoreConflict):
        reserve(store, child, submission)
    assert {name: _rows(store.path, name) for name in tables} == before


def test_missing_stored_import_link_is_corruption_not_reconstructed_on_read(tmp_path):
    store, _, child, submission = staged_case(tmp_path)
    reserve(store, child, submission)
    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM create_imports WHERE archive_digest=?", (child.digest,))
    with pytest.raises(StoreCorrupt):
        ProjectStore.open(store.path).get_create_publication(child.digest)
    assert _rows(store.path) == []


@pytest.mark.parametrize("reused", [False, True])
def test_fresh_and_inert_identity_calculation_agree_without_rehydrating_authority(tmp_path, reused):
    _, value, _, _ = staged_case(tmp_path, reused=reused)
    fresh = assess_create_identities(value["project"], value["archive"], value["bound"])
    inert = retained_create_identity_claims(value["project"], value["archive"], value["bound"].to_dict())
    assert type(inert) is dict and inert == fresh.to_dict()
    assert inert["claims"]["dispatch_permission"] == "none"
    assert inert["claims"]["model_state"] == "not_fresh_observation"
    invalid = value["bound"].to_dict()
    invalid["native_receipt"]["result_json"] = "{}"
    with pytest.raises(CreatePublicationError):
        retained_create_identity_claims(value["project"], value["archive"], invalid)


def _foreign_original(store, value):
    source = value["project"]
    materialized = materialize_selection(source, select_project_instances(source, instance_keys=("A",)), {})
    prepared = prepare_execution(materialized.planned, target=value["credentials"].target,
        precondition=ContextPrecondition("another-document", 8), operation_id=str(uuid4()))
    record = SavedExecutionRecord.capture_project(prepared, bind_selected_project_submission(source, materialized, prepared))
    reply = response_for(prepared, value["credentials"], json.loads(value["response"]["receipt"]["result_json"]),
                         changes=value["response"]["receipt"]["changes"])
    bound = bind_create_receipt(record, json.dumps(reply), credentials=value["credentials"], request_id=reply["request_id"])
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    store.record_create_receipt(bound)
    return record, bound


@pytest.mark.parametrize("fault", ["extra_plain_link", "extra_child_link", "altered_output", "foreign_receipt",
    "foreign_original_and_receipt", "corrupt_receipt", "orphan_child", "missing_table"])
def test_import_index_and_actual_originals_are_checked_both_ways_on_read(tmp_path, fault):
    store, value, child, submission = staged_case(tmp_path)
    reserve(store, child, submission)
    foreign_record, foreign_bound = _foreign_original(store, value)
    edge = _expected(child)[0]
    with sqlite3.connect(store.path) as connection:
        if fault == "extra_plain_link":
            connection.execute("INSERT INTO create_imports VALUES (?,?,?,?)",
                (value["archive"].digest, edge[1], edge[2], edge[3]))
        elif fault == "extra_child_link":
            connection.execute("INSERT INTO create_imports VALUES (?,?,?,?)", (child.digest, "e" * 64, edge[2], edge[3]))
        elif fault == "altered_output":
            connection.execute("UPDATE create_imports SET output_id=? WHERE archive_digest=? AND output_id=?",
                               ("e" * 64, child.digest, edge[1]))
        elif fault == "foreign_receipt":
            connection.execute("UPDATE create_imports SET original_receipt_digest=? WHERE archive_digest=? AND output_id=?",
                               (foreign_bound.receipt_digest, child.digest, edge[1]))
        elif fault == "foreign_original_and_receipt":
            connection.execute("UPDATE create_imports SET original_archive_digest=?,original_receipt_digest=? WHERE archive_digest=? AND output_id=?",
                               (foreign_record.digest, foreign_bound.receipt_digest, child.digest, edge[1]))
        elif fault == "corrupt_receipt":
            receipt = value["bound"].to_dict()
            receipt["native_receipt"]["result_json"] = "{}"
            connection.execute("UPDATE create_receipts SET payload=? WHERE receipt_digest=?",
                               (_canonical(receipt), value["bound"].receipt_digest))
        elif fault == "orphan_child":
            connection.execute("UPDATE create_imports SET archive_digest=? WHERE archive_digest=?", ("e" * 64, child.digest))
        else:
            connection.execute("DROP TABLE create_imports")
    with pytest.raises(StoreCorrupt):
        ProjectStore.open(store.path).get_create_publication(child.digest)
    if fault != "missing_table":
        with pytest.raises(StoreCorrupt):
            ProjectStore.open(store.path).history()


def _alter_retained_import(child, submission, change):
    """Coherently rehashed adversarial claims, NOT a new factory qualification.

    The copied carrier checks that SQL ownership cannot be bypassed merely by
    possessing a Python object's type. No native request is made with it.
    """
    data = child.to_dict()
    submitted = data["project_submission"]
    core = submitted["projection"]["association_core"]
    change(core["import_lineage"][0])
    association = _hash(core)
    submitted["projection"]["association_digest"] = association
    data["source"] = EXECUTION_ASSOCIATION_PREFIX + association + "\n" + data["source"].split("\n", 1)[1]
    data["source_byte_length"] = len(data["source"].encode("utf-8"))
    data["source_utf16_units"] = len(data["source"].encode("utf-16-le")) // 2
    data["binding"]["source_sha256"] = hashlib.sha256(data["source"].encode("utf-8")).hexdigest()
    submitted["execution"] = deepcopy(data["binding"])
    submitted["submission_digest"] = _hash({key: item for key, item in submitted.items() if key != "submission_digest"})
    data["record_digest"] = _hash({key: item for key, item in data.items() if key != "record_digest"})
    retained = SavedExecutionRecord._from_bytes(_canonical(data).encode("utf-8"))
    carrier = copy(submission)
    object.__setattr__(carrier, "_payload", _object({key: item for key, item in submitted.items() if key != "submission_digest"}, "adversarial"))
    object.__setattr__(carrier, "digest", submitted["submission_digest"])
    return retained, carrier


@pytest.mark.parametrize("fault", ["revision", "legacy_receipt_digest", "assessment", "proof", "state", "precondition", "foreign_namespace"])
def test_self_consistent_claims_cannot_replace_stored_original_facts(tmp_path, fault):
    store, value, child, submission = staged_case(tmp_path)
    foreign_record, foreign_bound = _foreign_original(store, value)
    def change(row):
        if fault == "revision": row["original_project_revision"] = "a" * 64
        elif fault == "legacy_receipt_digest": row["original_receipt_digest"] = _hash(value["bound"].receipt)
        elif fault == "assessment": row["original_identity_assessment_digest"] = "a" * 64
        elif fault == "proof": row["original_identity"]["element_id"] += 100
        elif fault == "state": row["original_identity_state"] = "reused_existing"
        elif fault == "precondition": row["original_precondition"]["revision"] -= 1
        else:
            row.update(original_archive_digest=foreign_record.digest, original_receipt_digest=foreign_bound.receipt_digest)
    changed, carrier = _alter_retained_import(child, submission, change)
    before = {name: _rows(store.path, name) for name in ("create_inputs", "create_scope_owners", "create_imports")}
    with pytest.raises(StoreConflict):
        reserve(store, changed, carrier)
    assert {name: _rows(store.path, name) for name in before} == before


def test_released_original_refuses_even_when_caller_kept_an_old_binding(tmp_path):
    store, value, child, submission = staged_case(tmp_path, seed_receipt=False)
    response = deepcopy(value["response"])
    response["receipt"].update(state="cancelled_before_start", started=False, may_retry=True,
        transaction_evidence="not_observed", changes=None, result_json=None,
        result_error=None, result_truncated=False, error="synthetic cancellation")
    no_start = bind_create_receipt(value["archive"], json.dumps(response), credentials=value["credentials"], request_id=response["request_id"])
    store.release_create_not_started(no_start, expected_archive_digest=value["archive"].digest)
    with pytest.raises(StoreConflict, match="released"):
        reserve(store, child, submission)
    assert _rows(store.path) == []


def test_child_input_owners_and_import_links_rollback_in_one_sql_transaction(tmp_path, monkeypatch):
    store, _, child, submission = staged_case(tmp_path)
    tables = ("create_inputs", "create_scope_owners", "create_imports")
    before = {name: _rows(store.path, name) for name in tables}
    actual, observed = ProjectStore._transaction, []
    @contextmanager
    def fail_after_all_inserts(self, *, write=False, migration=False):
        with actual(self, write=write, migration=migration) as pair:
            yield pair
            if write:
                connection, _ = pair
                assert connection.execute("SELECT count(*) FROM create_inputs WHERE archive_digest=?", (child.digest,)).fetchone()[0] == 1
                assert connection.execute("SELECT count(*) FROM create_scope_owners WHERE archive_digest=?", (child.digest,)).fetchone()[0] == 1
                assert sorted(connection.execute("SELECT * FROM create_imports WHERE archive_digest=?", (child.digest,))) == _expected(child)
                observed.append("all staged rows present before rollback")
                raise RuntimeError("controlled precommit failure")
    with monkeypatch.context() as patched:
        patched.setattr(ProjectStore, "_transaction", fail_after_all_inserts)
        with pytest.raises(RuntimeError, match="controlled precommit"):
            reserve(store, child, submission)
    assert observed and {name: _rows(store.path, name) for name in tables} == before
    assert reserve(store, child, submission).inserted


def test_audit_cycle_and_failed_node_do_not_become_a_cached_success(tmp_path, monkeypatch):
    store, _, child, submission = staged_case(tmp_path)
    reserve(store, child, submission)
    with store._transaction() as (connection, state):
        audit = creates._import_audit()
        audit["active"].add(child.digest)
        with pytest.raises(StoreCorrupt, match="cyclic"):
            creates._read_input(connection, state, child.digest, audit=audit)
        audit["active"].clear()
        from kir import create_publication
        with monkeypatch.context() as patched:
            patched.setattr(create_publication, "retained_create_identity_claims", lambda *_a: (_ for _ in ()).throw(ValueError("unqualified")))
            with pytest.raises(StoreCorrupt, match="identity claims"):
                creates._read_input(connection, state, child.digest, audit=audit)
        assert child.digest not in audit["inputs"] and child.digest not in audit["verified"] and not audit["active"]
        assert creates._read_input(connection, state, child.digest, audit=audit).record.digest == child.digest
        assert child.digest in audit["inputs"]


def test_audit_memo_has_a_bounded_catalog_footprint():
    audit = creates._import_audit()
    for number in range(creates.MAX_STAGED_IMPORT_MEMO_ENTRIES + 10):
        creates._memo(audit, "inputs", number, str(number))
    assert len(audit["inputs"]) == creates.MAX_STAGED_IMPORT_MEMO_ENTRIES
    assert 0 not in audit["inputs"]


def test_iterative_walker_handles_a_deep_diamond_after_payload_eviction(monkeypatch):
    """Algorithm control, NOT a fabricated native/archive qualification.

    Real factory/SQL checks are exercised above. Here controlled readers expose
    a 2048-node DAG so Python recursion/memo behavior is tested independently.
    """
    from kir.staged_submission import STAGED_SUBMISSION_SCHEMA
    nodes = [f"{number:064x}" for number in range(2048)]
    graph = {node: tuple(dict.fromkeys(nodes[index - offset] for offset in (1, 2, index)
        if 0 < offset <= index)) for index, node in enumerate(nodes)}
    reads, checked = Counter(), Counter()
    def read(_connection, _state, digest):
        reads[digest] += 1
        return SimpleNamespace(record=SimpleNamespace(digest=digest, project_submission={
            "schema": STAGED_SUBMISSION_SCHEMA, "projection": {"association_core": {
                "import_lineage": [{"original_archive_digest": dependency} for dependency in graph[digest]]}}}))
    def check(connection, state, value, *, audit, **_kwargs):
        node = value.record.digest
        assert all(dependency in audit["verified"] for dependency in graph[node])
        for dependency in graph[node]:
            assert creates._read_input(connection, state, dependency, audit=audit).record.digest == dependency
        checked[node] += 1
    monkeypatch.setattr(creates, "_read_input_base", read)
    monkeypatch.setattr(creates, "_check_imports", check)
    audit = creates._import_audit()
    state = SimpleNamespace(schema=STAGED_CREATE_STORE_SCHEMA)
    assert creates._read_input(None, state, nodes[-1], audit=audit).record.digest == nodes[-1]
    assert set(audit["verified"]) == set(nodes) and not audit["active"]
    assert all(checked[node] == 1 for node in nodes)
    assert len(audit["inputs"]) <= creates.MAX_STAGED_IMPORT_MEMO_ENTRIES
    assert reads[nodes[0]] > 2  # Evicted payload reread, never requalified twice.
    graph[nodes[0]] = (nodes[-1],)
    with pytest.raises(StoreCorrupt, match="cyclic"):
        creates._read_input(None, state, nodes[-1], audit=creates._import_audit())


def test_actual_historical_v4_original_supports_staged_child_and_new_process_read(tmp_path):
    from kir.tests.test_lineage_archive_compatibility import _fixtures, _bytes, _project
    from kir.tests.test_revit_observation import row as native_row, identity
    from kir.element_query import TYPE_DEFINITION_STATE_SCHEMA
    from kir.project_execution_partition import partition_project_execution
    old_project = _project()
    old_raw = _bytes(_fixtures()["archives"]["selected_project"])
    original = SavedExecutionRecord._from_bytes(old_raw)
    binding = original.binding_dict()
    creds = SessionCredentials(RuntimeTarget(**binding["target"]), str(uuid4()), "synthetic-not-sent")
    oid = original.project_submission["outputs"][0]["output_id"]
    payload = {"ok": True, oid: {"id": "700", **identity(700, "historical-level-uid")}}
    receipt = {**binding, "document_key": binding["precondition"]["document_key"],
        "state": "invocation_completed", "started": True, "may_retry": False,
        "transaction_evidence": "changes_observed", "semantic_evidence": "unverified",
        "result_json": json.dumps(payload), "result_truncated": False, "result_error": None, "error": None,
        "changes": {"added": [700], "modified": [], "deleted": [], "transaction_names": ["synthetic"], "truncated": False},
        "timestamp_utc": "2026-09-05T12:00:00Z"}
    request_id = str(uuid4())
    response = {"protocol": "kir-revit-connector/4", "request_id": request_id, "target": creds.target.to_dict(),
        "session_id": creds.session_id, "ok": True, "status": "receipt", "error": None, "context": None, "receipt": receipt}
    bound = bind_create_receipt(original, json.dumps(response), credentials=creds, request_id=request_id)
    source = old_project.revise(expected_revision=old_project.revision_id, instances=[*old_project.instances,
        ModuleInstance("B", "explicit", {"wall": {"op": "create_wall", "p0_mm": [0, 0], "p1_mm": [5000, 0],
            "height_mm": 3000, "level": {"by": "ref", "value": oid}}})])
    materialized = materialize_selection(source, select_project_instances(source, instance_keys=("B",)), {})
    partition = partition_project_execution(source, materialized, import_output_ids=(oid,))
    row = native_row("historical-level-uid")
    row.update(schema_version=TYPE_DEFINITION_STATE_SCHEMA, name="Base",
        type_definition={"status": "not_applicable", "reason": "unsupported_element_kind", "value": None})
    row["level"].update(project_elevation_mm=0.0, reported_elevation_mm=0.0)
    row["level"]["elevation_parameter"]["value_internal_feet"] = 0.0
    observed = stages.observe_rows({"historical-level-uid": row}, creds, document=binding["precondition"]["document_key"])
    projection = bind_staged_create_projection(partition, import_sources={oid: (old_project, original, bound)}, observation=observed)
    prepared = prepare_staged_create(projection, operation_id=str(uuid4()))
    submission = bind_staged_project_submission(projection, prepared)
    child = SavedExecutionRecord.capture_project(prepared, submission)
    store = ProjectStore.create(tmp_path / "history.sqlite", old_project, schema=STAGED_CREATE_STORE_SCHEMA)
    store.reserve_create_publication(original, expected_revision=old_project.revision_id)
    store.record_create_receipt(bound)
    store.commit(source, expected_revision=old_project.revision_id)
    assert reserve(store, child, submission).inserted
    assert store.get_create_publication(original.digest).record._raw == old_raw
    child_code = """
from contextlib import ExitStack
from unittest.mock import patch
import hashlib, json, os, sys
from kir.project_store import ProjectStore
def forbidden(*args, **kwargs):
    raise AssertionError('historical staged read re-prepared or rehydrated fresh authority')
with ExitStack() as stack:
    for name in ('kir.compiler.compile_program', 'kir.compiler.plan_program',
                 'kir.revit_connector.prepare_execution', 'kir.create_publication.bind_create_receipt'):
        stack.enter_context(patch(name, forbidden))
    store = ProjectStore.open(sys.argv[1])
    child = store.get_create_publication(sys.argv[2]).record
    old = store.get_create_publication(sys.argv[3]).record
    print(json.dumps({'pid': os.getpid(), 'child_sha': hashlib.sha256(child._raw).hexdigest(),
                      'old_sha': hashlib.sha256(old._raw).hexdigest(),
                      'imports': len(child.project_submission['projection']['association_core']['import_lineage'])}))
"""
    before = store.path.read_bytes()
    completed = subprocess.run([sys.executable, "-c", child_code, str(store.path), child.digest, original.digest],
        capture_output=True, text=True, timeout=30, cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert completed.returncode == 0, completed.stderr[-3000:]
    result = json.loads(completed.stdout)
    assert result["pid"] != os.getpid() and result["imports"] == 1
    assert result["child_sha"] == hashlib.sha256(child._raw).hexdigest()
    assert result["old_sha"] == hashlib.sha256(old_raw).hexdigest()
    assert store.path.read_bytes() == before
