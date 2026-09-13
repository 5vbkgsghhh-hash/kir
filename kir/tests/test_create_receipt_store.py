"""Bound receipt retention in real SQLite; synthetic native response only."""
from copy import deepcopy
import json
import sqlite3
from uuid import uuid4

import pytest

from kir.create_publication import bind_create_receipt, BoundCreateReceipt, CreatePublicationError
from kir.project_store import ProjectStore, StoreConflict, StoreCorrupt, ProjectStoreError
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.tests.test_project_create_store import case as reserved_case, archive


@pytest.fixture
def case(tmp_path):
    store, source, record = reserved_case(tmp_path)
    store.reserve_create_publication(record, expected_revision=source.revision_id)
    binding = record.to_dict()["binding"]
    credentials = SessionCredentials(RuntimeTarget(**binding["target"]), str(uuid4()), "private-test-token")
    outputs = record.project_submission["outputs"]
    result = {"ok": True, **{row["output_id"]: {"id": str(700 + i)} for i, row in enumerate(outputs)}}
    receipt = {**binding, "document_key": binding["precondition"]["document_key"],
               "state": "invocation_completed", "started": True, "may_retry": False,
               "transaction_evidence": "changes_observed", "semantic_evidence": "unverified",
               "result_json": json.dumps(result), "result_truncated": False, "result_error": None,
               "error": None, "changes": {"added": list(range(700, 700 + len(outputs))), "modified": [],
                   "deleted": [], "transaction_names": ["KIR"], "truncated": False}, "timestamp_utc": "2026-09-06T12:00:00Z"}
    response = {"protocol": "kir-revit-connector/4", "request_id": str(uuid4()), "target": credentials.target.to_dict(),
                "session_id": credentials.session_id, "ok": True, "status": "receipt", "error": None,
                "context": None, "receipt": receipt}
    return store, source, record, credentials, response


def bind(case, response=None, *, credentials=None, recovery=False):
    _, _, record, original_credentials, original_response = case
    response = original_response if response is None else response
    return bind_create_receipt(record, json.dumps(response), credentials=credentials or original_credentials,
                               request_id=response["request_id"], recovery=recovery)


def test_store_reload_keeps_receipt_without_moving_head_or_releasing_scope(case):
    store, source, record, _, _ = case
    receipt = bind(case)
    result = store.record_create_receipt(receipt)
    assert result.inserted and result.terminal_receipt_digest == receipt.receipt_digest and not result.may_retry
    assert not store.record_create_receipt(receipt).inserted
    loaded = ProjectStore.open(store.path).get_create_receipts(record.digest).to_dict()
    assert loaded["receipts"] == [receipt.to_dict()]
    assert loaded["claims"]["dispatch_permission"] == "none"
    assert store.head().revision_id == source.revision_id
    with pytest.raises(StoreConflict, match="output scope"):
        store.reserve_create_publication(archive(source, roots=("section",)), expected_revision=source.revision_id)
    with pytest.raises(TypeError):
        BoundCreateReceipt()
    with pytest.raises(ProjectStoreError, match="bound CREATE receipt"):
        store.record_create_receipt(receipt.to_dict())


def test_recovery_route_and_request_do_not_create_a_different_original_receipt(case):
    store, _, record, _, response = case
    original = bind(case)
    store.record_create_receipt(original)
    other = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "recovery-token")
    moved = deepcopy(response)
    moved.update(target=other.target.to_dict(), session_id=other.session_id, request_id=str(uuid4()))
    recovered = bind(case, moved, credentials=other, recovery=True)
    assert recovered.receipt_digest == original.receipt_digest
    assert recovered.to_dict() == original.to_dict()
    assert not store.record_create_receipt(recovered).inserted
    assert len(store.get_create_receipts(record.digest).to_dict()["receipts"]) == 1


@pytest.mark.parametrize("mode", ["partial", "result_truncated", "failed_after_change"])
def test_partial_or_unavailable_result_is_retained_without_full_success(case, mode):
    store, _, record, _, response = case
    altered = deepcopy(response)
    if mode == "partial":
        result = json.loads(altered["receipt"]["result_json"])
        result[record.project_submission["outputs"][-1]["output_id"]] = {"refused": "controlled failure"}
        altered["receipt"]["result_json"] = json.dumps(result)
    elif mode == "result_truncated":
        altered["receipt"].update(result_truncated=True, result_json=None)
    else:
        altered["receipt"].update(state="failed_after_observed_change", error="controlled failure", result_json=None)
    receipt = bind(case, altered)
    assert not receipt.assessment.ok
    saved = store.record_create_receipt(receipt)
    assert saved.inserted and saved.terminal_receipt_digest == receipt.receipt_digest
    assert store.get_create_receipts(record.digest).to_dict()["receipts"][0] == receipt.to_dict()


def test_conflicting_terminal_refuses_without_overwriting_first_receipt(case):
    store, _, record, _, response = case
    first = bind(case)
    store.record_create_receipt(first)
    changed = deepcopy(response)
    changed["receipt"]["timestamp_utc"] = "2026-09-06T13:00:00Z"
    with pytest.raises(StoreConflict, match="terminal receipt"):
        store.record_create_receipt(bind(case, changed))
    assert store.get_create_receipts(record.digest).to_dict()["receipts"] == [first.to_dict()]


def test_late_started_receipt_does_not_demote_terminal_or_release_owners(case):
    store, _, record, _, response = case
    complete = bind(case)
    store.record_create_receipt(complete)
    started = deepcopy(response)
    started.update(ok=False, status="running_unknown", error="pending")
    started["receipt"].update(state="running_unknown", result_json=None, error="pending", changes=None,
                              transaction_evidence="not_observed")
    progress = bind(case, started)
    assert progress.terminal_state is None
    result = store.record_create_receipt(progress)
    assert result.terminal_receipt_digest == complete.receipt_digest
    assert store.get_create_receipts(record.digest).terminal_receipt_digest == complete.receipt_digest


def test_missing_or_foreign_receipt_is_not_adopted(case):
    _, _, _, _, response = case
    for change in ("missing", "foreign"):
        changed = deepcopy(response)
        if change == "missing": changed.update(receipt=None, ok=False, status="not_found")
        else: changed["receipt"]["source_sha256"] = "a" * 64
        with pytest.raises(CreatePublicationError, match="unbound"):
            bind(case, changed)


def test_historical_read_does_not_run_current_qualification(case, monkeypatch):
    store, _, record, _, _ = case
    receipt = bind(case)
    store.record_create_receipt(receipt)
    import kir.bridge_result
    import kir.compiler
    monkeypatch.setattr(kir.bridge_result, "saved_create_result_contract", lambda *_: pytest.fail("historical admission"))
    monkeypatch.setattr(kir.compiler, "plan_program", lambda *_a, **_kw: pytest.fail("historical compilation"))
    assert store.get_create_receipts(record.digest).to_dict()["receipts"] == [receipt.to_dict()]


@pytest.mark.parametrize("change", ["index", "payload", "binding"])
def test_corrupt_receipt_never_becomes_a_successful_read(case, change):
    store, _, record, _, _ = case
    receipt = bind(case)
    store.record_create_receipt(receipt)
    with sqlite3.connect(store.path) as connection:
        if change == "index": connection.execute("UPDATE create_receipts SET receipt_digest=?", ("f" * 64,))
        elif change == "payload": connection.execute("UPDATE create_receipts SET payload='{}'")
        else:
            value = receipt.to_dict()
            value["native_receipt"]["document_key"] = "other"
            from kir.project import _canonical, _hash
            value["receipt_digest"] = _hash({"archive_digest": record.digest, "native_receipt": value["native_receipt"]})
            connection.execute("UPDATE create_receipts SET receipt_digest=?,payload=?", (value["receipt_digest"], _canonical(value)))
    with pytest.raises(StoreCorrupt):
        store.get_create_receipts(record.digest)


def test_history_audit_includes_retained_receipt_payloads(case):
    store, _, _, _, _ = case
    store.record_create_receipt(bind(case))
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE create_receipts SET payload='{}'")
    with pytest.raises(StoreCorrupt, match="receipt"):
        store.history()


def test_corrupted_progress_rows_cannot_consume_reserved_terminal_capacity(case, monkeypatch):
    from kir import project_create_store as ledger
    from kir.project import _canonical
    store, _, record, _, response = case
    payloads = []
    for second in (1, 2):
        progress = deepcopy(response)
        progress.update(ok=False, status="running_unknown", error="pending")
        progress["receipt"].update(state="running_unknown", result_json=None, error="pending", changes=None,
            transaction_evidence="not_observed", timestamp_utc=f"2026-09-06T12:00:0{second}Z")
        payloads.append(bind(case, progress).to_dict())
    budget = max(len(_canonical(row).encode()) for row in payloads) + 10
    monkeypatch.setattr(ledger, "MAX_CREATE_RECEIPT_BYTES", budget)
    with sqlite3.connect(store.path) as connection:
        for row in payloads:
            connection.execute("INSERT INTO create_receipts VALUES (?,?,?)",
                               (row["receipt_digest"], record.digest, _canonical(row)))
    with pytest.raises(StoreCorrupt, match="progress"):
        store.get_create_receipts(record.digest)
