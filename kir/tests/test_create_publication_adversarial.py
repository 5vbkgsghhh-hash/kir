"""Independent CREATE receipt/identity adversaries; all native facts are synthetic."""
from copy import copy, deepcopy
from dataclasses import replace
import json
import sqlite3
from uuid import uuid4

import pytest

from kir.bridge_result import WriteResultAssessment
from kir.contracts import ElementIdentityProof
from kir.create_publication import (CreatePublicationError, assess_create_identities, bind_create_receipt)
from kir.geometry_materialization import materialize_project
from kir.outcome import AcceptanceState, WitnessState, write_committed
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision, _canonical
from kir.project_store import CREATE_STORE_SCHEMA, ProjectStore, StoreConflict, StoreCorrupt, StoreCommitUnknown
from kir.project_submission import bind_project_submission
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution
from kir.saved_execution import SavedExecutionRecord, _capture


def make_case(tmp_path, *, with_type=False, stored=False):
    operations = {"first": {"op": "create_level", "elev_mm": 0},
                  "second": {"op": "create_level", "elev_mm": 3000}}
    if with_type:
        operations["type"] = {"op": "create_wall_type", "source_type": {"by": "element_id", "value": 100},
                              "new_name": "Explicit type", "layers": [{"width_mm": 250, "function": "Structure"}]}
    source = ProjectRevision("create-adversary", [ModuleDefinition("m")], [ModuleInstance("i", "m", operations)])
    materialized = materialize_project(source, {})
    credentials = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "synthetic-secret")
    prepared = prepare_execution(materialized.planned, target=credentials.target,
        precondition=ContextPrecondition("original-native-document", 8), operation_id=str(uuid4()))
    submission = bind_project_submission(source, materialized, prepared)
    record = SavedExecutionRecord._from_bytes(_capture(prepared, submission=submission))
    result = {"ok": True}
    for index, op in enumerate(prepared.planned.ops):
        result[op.op_id] = {"id": str(700 + index),
            "element_identity": ElementIdentityProof(700 + index, "uid-" + op.op_id, "a" * 32).to_dict(),
            "element_identity_status": "captured", "element_identity_reason": None}
        if op.op_name == "create_wall_type": result[op.op_id]["duplicated"] = True
    receipt = {**prepared.binding_dict(), "document_key": prepared.precondition.document_key,
        "state": "invocation_completed", "started": True, "may_retry": False,
        "transaction_evidence": "changes_observed", "semantic_evidence": "unverified",
        "result_json": json.dumps(result), "result_error": None, "result_truncated": False, "error": None,
        "changes": {"added": list(range(700, 700 + len(operations))), "modified": [], "deleted": [],
                    "transaction_names": ["KIR"], "truncated": False}, "timestamp_utc": "2026-09-06T14:00:00Z"}
    response = {"protocol": "kir-revit-connector/4", "target": credentials.target.to_dict(),
        "session_id": credentials.session_id, "request_id": str(uuid4()), "ok": True,
        "status": "receipt", "receipt": receipt, "context": None, "error": None}
    store = None
    if stored:
        store = ProjectStore.create(tmp_path / "project.sqlite", source, schema=CREATE_STORE_SCHEMA)
        store.reserve_create_publication(record, expected_revision=source.revision_id)
    return dict(source=source, prepared=prepared, record=record, credentials=credentials,
                result=result, response=response, store=store)


def bind(case, *, response=None, result=None, credentials=None, recovery=False):
    response = deepcopy(case["response"] if response is None else response)
    if result is not None: response["receipt"]["result_json"] = json.dumps(result)
    return bind_create_receipt(case["record"], json.dumps(response),
        credentials=credentials or case["credentials"], request_id=response["request_id"], recovery=recovery)


def report(case, bound):
    return assess_create_identities(case["source"], case["record"], bound).to_dict()


def test_public_derived_outcome_cannot_override_contradictory_raw_native_receipt(tmp_path):
    case = make_case(tmp_path)
    response = deepcopy(case["response"])
    response["receipt"]["started"] = False  # Contradicts invocation_completed.
    original = bind(case, response=response)
    assert original.assessment.outcome.execution.value == "unconfirmed"
    assert all(row["state"] == "unavailable" for row in report(case, original)["outputs"])
    forged = copy(original)
    assessment = replace(original.assessment,
        assessment=WriteResultAssessment(write_committed(witness=WitnessState.SATISFIED)))
    object.__setattr__(forged, "assessment", assessment)
    # Input, raw receipt, archive/receipt digests and all captures are untouched.
    try:
        checked = report(case, forged)
    except CreatePublicationError:
        return
    assert all(row["state"] == "unavailable" for row in checked["outputs"]), checked


def test_internal_failure_marker_cannot_qualify_a_stale_identity_capture(tmp_path):
    case = make_case(tmp_path)
    result = deepcopy(case["result"])
    first = case["prepared"].planned.ops[0].op_id
    result[first]["internal"] = True
    data = report(case, bind(case, result=result))
    assert data["outputs"][0]["state"] == "unavailable", data
    assert data["outputs"][1]["state"] == "created_here", data


@pytest.mark.parametrize("fault", ["witness", "acceptance"])
def test_derived_witness_or_acceptance_cannot_override_raw_facts(tmp_path, fault):
    case = make_case(tmp_path)
    result = deepcopy(case["result"])
    if fault == "witness": result["postcondition_violations"] = ["controlled geometric drift"]
    original = bind(case, result=result)
    expected = original.assessment.outcome.to_dict()
    altered = (replace(original.assessment.assessment.outcome, witness=WitnessState.SATISFIED)
               if fault == "witness" else
               replace(original.assessment.assessment.outcome, acceptance=AcceptanceState.ACCEPTED))
    forged = copy(original)
    object.__setattr__(forged, "assessment", replace(original.assessment, assessment=WriteResultAssessment(altered)))
    try:
        observed = report(case, forged)
    except CreatePublicationError:
        return
    assert observed["outcome"] == expected, observed


def owners(store):
    with sqlite3.connect(store.path) as connection:
        return connection.execute("SELECT * FROM create_scope_owners ORDER BY output_id").fetchall()


def progress(case, number, *, padding=""):
    response = deepcopy(case["response"])
    response.update(ok=False, status="running_unknown", error="still running")
    response["receipt"].update(state="running_unknown", result_json=None, error="pending " + padding,
        transaction_evidence="not_observed", changes=None, timestamp_utc=f"2026-09-06T14:{number:02d}:00Z")
    return bind(case, response=response)


def test_orphaned_receipt_index_cannot_make_a_recorded_terminal_disappear(tmp_path):
    case = make_case(tmp_path, stored=True)
    store = case["store"]
    receipt = bind(case)
    store.record_create_receipt(receipt)
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE create_receipts SET archive_digest=?", ("f" * 64,))
    with pytest.raises(StoreCorrupt):
        store.get_create_receipts(case["record"].digest)


def test_misattributed_receipt_index_cannot_hide_terminal_behind_another_existing_input(tmp_path):
    case = make_case(tmp_path, stored=True)
    store = case["store"]
    first = bind(case)
    store.record_create_receipt(first)
    materialized = materialize_project(case["source"], {})
    prepared = prepare_execution(materialized.planned, target=case["prepared"].target,
        precondition=ContextPrecondition("another-native-document", 8), operation_id=str(uuid4()))
    submission = bind_project_submission(case["source"], materialized, prepared)
    second = SavedExecutionRecord._from_bytes(_capture(prepared, submission=submission))
    store.reserve_create_publication(second, expected_revision=case["source"].revision_id)
    with sqlite3.connect(store.path) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("UPDATE create_receipts SET archive_digest=? WHERE receipt_digest=?",
                           (second.digest, first.receipt_digest))
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    # The indexed target exists, but the payload still belongs to the first
    # archive. Reading A must detect corruption, not report no native receipt.
    with pytest.raises(StoreCorrupt):
        store.get_create_receipts(case["record"].digest)


def test_partial_reuse_and_failures_survive_receipt_storage_without_scope_release(tmp_path):
    case = make_case(tmp_path, with_type=True, stored=True)
    before_owners = owners(case["store"])
    first, second, type_id = [op.op_id for op in case["prepared"].planned.ops]
    result = deepcopy(case["result"])
    result[second] = {"refused": "failed operation", "refused_op_id": second}
    result[type_id]["duplicated"] = False
    response = deepcopy(case["response"])
    response["receipt"]["changes"]["added"] = [700]
    bound = bind(case, response=response, result=result)
    assert not bound.assessment.ok
    data = report(case, bound)
    assert [row["state"] for row in data["outputs"]] == ["created_here", "refused", "reused_existing"]
    assert data["outcome"]["execution"] == "committed"
    case["store"].record_create_receipt(bound)
    read = ProjectStore.open(case["store"].path).get_create_receipts(case["record"].digest)
    assert read.to_dict()["receipts"] == [bound.to_dict()]
    assert owners(case["store"]) == before_owners
    # A newly prepared UUID on the same revision still cannot repeat CREATE.
    prepared = prepare_execution(case["prepared"].planned, target=case["prepared"].target,
        precondition=case["prepared"].precondition, operation_id=str(uuid4()))
    materialized = materialize_project(case["source"], {})
    submission = bind_project_submission(case["source"], materialized, prepared)
    record = SavedExecutionRecord._from_bytes(_capture(prepared, submission=submission))
    with pytest.raises(StoreConflict, match="scope"):
        case["store"].reserve_create_publication(record, expected_revision=case["source"].revision_id)


@pytest.mark.parametrize("flag", [None, 0, 1, "false", [], {}])
def test_reused_type_flag_is_not_inferred_or_coerced(tmp_path, flag):
    case = make_case(tmp_path, with_type=True)
    result = deepcopy(case["result"])
    oid = case["prepared"].planned.ops[-1].op_id
    if flag is None: result[oid].pop("duplicated")
    else: result[oid]["duplicated"] = flag
    data = report(case, bind(case, result=result))
    assert data["outputs"][-1]["state"] == "unavailable"
    assert data["outputs"][-1]["element_identity"] is None
    assert data["outputs"][0]["state"] == "created_here"


@pytest.mark.parametrize("fault", ["primary_id", "uid", "extra_refused", "malformed_extra_uid"])
def test_conflicts_from_other_rows_remove_qualification_globally(tmp_path, fault):
    case = make_case(tmp_path)
    result = deepcopy(case["result"])
    a, b = [op.op_id for op in case["prepared"].planned.ops]
    if fault == "primary_id": result[b]["id"] = result[a]["id"]
    elif fault == "uid": result[b]["element_identity"]["unique_id"] = result[a]["element_identity"]["unique_id"]
    elif fault == "extra_refused": result["outside-plan"] = {"refused": "failed", "id": result[a]["id"]}
    else:
        result["outside-plan"] = deepcopy(result[a])
        result["outside-plan"]["element_identity"]["version_guid"] = "broken"
    data = report(case, bind(case, result=result))
    assert data["outputs"][0]["state"] == "conflict"
    assert data["outputs"][0]["element_identity"] is None


def test_recovery_route_changes_neither_raw_fact_identity_nor_terminal_head(tmp_path):
    case = make_case(tmp_path, stored=True)
    bound = bind(case)
    first = case["store"].record_create_receipt(bound)
    credentials = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "recovery-secret")
    response = deepcopy(case["response"])
    response.update(target=credentials.target.to_dict(), session_id=credentials.session_id, request_id=str(uuid4()))
    recovered = bind(case, response=response, credentials=credentials, recovery=True)
    assert recovered.receipt_digest == first.receipt_digest
    assert recovered.to_dict() == bound.to_dict()
    assert report(case, recovered)["assessment_digest"] == report(case, bound)["assessment_digest"]
    assert not case["store"].record_create_receipt(recovered).inserted
    source = case["source"]
    newer = source.revise(expected_revision=source.revision_id, metadata={"later": True})
    case["store"].commit(newer, expected_revision=source.revision_id)
    assert case["store"].get_create_publication(case["record"].digest).source_revision == source.revision_id
    assert case["store"].head().revision_id == newer.revision_id
    with pytest.raises(ValueError):
        assess_create_identities(newer, case["record"], recovered)


@pytest.mark.parametrize("fault", ["result_json", "truncated", "boolean_flag", "manifest", "state_type"])
def test_bound_invalid_native_payload_is_retained_but_no_identity_is_qualified(tmp_path, fault):
    case = make_case(tmp_path, stored=True)
    response = deepcopy(case["response"])
    if fault == "result_json": response["receipt"]["result_json"] = "{invalid"
    elif fault == "truncated": response["receipt"]["result_truncated"] = True
    elif fault == "boolean_flag": response["receipt"]["started"] = 1
    elif fault == "manifest": response["receipt"]["changes"] = {"truncated": False}
    else: response["receipt"]["state"] = []
    bound = bind(case, response=response)
    original_owners = owners(case["store"])
    case["store"].record_create_receipt(bound)
    assert case["store"].get_create_receipts(case["record"].digest).to_dict()["receipts"] == [bound.to_dict()]
    assert all(row["state"] == "unavailable" for row in report(case, bound)["outputs"])
    assert owners(case["store"]) == original_owners


def test_terminal_immutability_and_late_progress_do_not_downgrade_or_release_owners(tmp_path):
    case = make_case(tmp_path, stored=True)
    terminal = bind(case)
    case["store"].record_create_receipt(terminal)
    before_owners = owners(case["store"])
    late = case["store"].record_create_receipt(progress(case, 1))
    assert late.terminal_receipt_digest == terminal.receipt_digest
    different = deepcopy(case["response"])
    different["receipt"]["timestamp_utc"] = "2026-09-06T15:00:00Z"
    with pytest.raises(StoreConflict, match="terminal"):
        case["store"].record_create_receipt(bind(case, response=different))
    assert case["store"].get_create_receipts(case["record"].digest).terminal_receipt_digest == terminal.receipt_digest
    assert owners(case["store"]) == before_owners


def test_progress_count_exhaustion_keeps_space_for_terminal_and_exact_ack(tmp_path, monkeypatch):
    import kir.project_create_store as storage
    monkeypatch.setattr(storage, "MAX_CREATE_PROGRESS_RECEIPTS", 2)
    case = make_case(tmp_path, stored=True)
    a, b, c = progress(case, 1), progress(case, 2), progress(case, 3)
    case["store"].record_create_receipt(a)
    case["store"].record_create_receipt(b)
    with pytest.raises(StoreConflict, match="budget"):
        case["store"].record_create_receipt(c)
    terminal = bind(case)
    assert case["store"].record_create_receipt(terminal).inserted
    ack = case["store"].record_create_receipt(a)
    assert not ack.inserted and not ack.may_retry and ack.terminal_receipt_digest == terminal.receipt_digest
    assert len(case["store"].get_create_receipts(case["record"].digest).to_dict()["receipts"]) == 3


def test_progress_byte_exhaustion_reserves_a_full_terminal_payload(tmp_path, monkeypatch):
    import kir.project_create_store as storage
    case = make_case(tmp_path, stored=True)
    terminal = bind(case)
    limit = len(_canonical(terminal.to_dict()).encode()) + 8
    monkeypatch.setattr(storage, "MAX_CREATE_RECEIPT_BYTES", limit)
    base = progress(case, 1)
    base_size = len(_canonical(base.to_dict()).encode())
    padding = "x" * max(1, limit * 3 // 4 - base_size)
    a, b = progress(case, 1, padding=padding), progress(case, 2, padding=padding)
    assert len(_canonical(a.to_dict()).encode()) * 2 > limit
    case["store"].record_create_receipt(a)
    with pytest.raises(StoreConflict, match="budget"):
        case["store"].record_create_receipt(b)
    assert case["store"].record_create_receipt(terminal).inserted
    assert case["store"].get_create_receipts(case["record"].digest).terminal_receipt_digest == terminal.receipt_digest


def test_receipt_commit_lost_ack_is_readable_and_redelivery_never_releases_scope(tmp_path, monkeypatch):
    import kir.project_store as storage
    case = make_case(tmp_path, stored=True)
    bound = bind(case)
    original_owners = owners(case["store"])
    real_commit = storage._commit
    def lost(connection):
        real_commit(connection)
        raise StoreCommitUnknown("injected loss after the actual SQLite COMMIT")
    with monkeypatch.context() as failure:
        failure.setattr(storage, "_commit", lost)
        with pytest.raises(StoreCommitUnknown):
            case["store"].record_create_receipt(bound)
    readonly = ProjectStore.open(case["store"].path)
    observed = readonly.get_create_receipts(case["record"].digest)
    assert observed.terminal_receipt_digest == bound.receipt_digest
    assert observed.to_dict()["receipts"] == [bound.to_dict()]
    acknowledged = case["store"].record_create_receipt(bound)
    assert not acknowledged.inserted and not acknowledged.may_retry
    assert owners(case["store"]) == original_owners
