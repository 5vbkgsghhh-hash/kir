"""Real portable transport + SQLite; server receipts are explicitly seeded.

Generated Revit code is NOT invoked by this server. The tests establish input,
send, receipt and restart ordering, not native creation or BIM correctness.
"""
import json
import sqlite3
from uuid import uuid4

import pytest

from kir import standalone_publish as publishing
from kir.geometry_materialization import materialize_selection
from kir.project_selection import select_project_instances
from kir.project_store import ProjectStore, CREATE_STORE_SCHEMA, StoreConflict
from kir.revit_transport import ConnectorTransportError
from kir.tests.test_revit_transport import helper, native_server
from kir.tests.test_standalone_publish import probe, sent
from kir.tests.test_selected_project_submission import source_project


def setup(native_server, helper, tmp_path, *, partial=False):
    advertisement, root = native_server("2023")
    condition = probe(advertisement, helper)
    source = source_project()
    store = ProjectStore.create(tmp_path / "stored.sqlite", source, schema=CREATE_STORE_SCHEMA)
    materialized = materialize_selection(source, select_project_instances(source, instance_keys=("section",)), {})
    result = {"ok": True, **{op.op_id: {"id": str(700 + index)} for index, op in enumerate(materialized.planned.ops)}}
    if partial:
        result[materialized.planned.ops[-1].op_id] = {"refused": "seeded failure, not native execution"}
    (root / "seed-result.json").write_text(json.dumps(result), encoding="utf-8")
    options = dict(expected_revision=source.revision_id, advertisement=advertisement, client_path=helper,
                   expected_document_key=condition.document_key, operation_id=str(uuid4()),
                   bind_view=True, bind_selection=True, timeout_ms=10000)
    return store, materialized, advertisement, root, options


def input_digest(store, operation_id):
    with sqlite3.connect(store.path) as connection:
        return connection.execute("SELECT archive_digest FROM create_inputs WHERE operation_id=?", (operation_id,)).fetchone()[0]


def test_stored_selected_input_precedes_one_real_send_and_retained_receipt(native_server, helper, tmp_path, monkeypatch):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    actual = publishing.exchange
    boundaries = []
    def checked_send(advertisement, request, **kwargs):
        message = json.loads(request)
        boundaries.append(message["kind"])
        if message["kind"] == "execute":
            captured = ProjectStore.open(store.path).get_create_publication(input_digest(store, options["operation_id"]))
            assert captured.record.to_dict()["source"] == message["source"]
            assert captured.record.binding_dict()["source_sha256"] == message["source_sha256"]
            assert len(captured.output_ids) == 2
            assert captured.record.project_submission["project"]["revision_id"] == materialized.project.revision_id
        return actual(advertisement, request, **kwargs)
    monkeypatch.setattr(publishing, "exchange", checked_send)
    attempt = publishing.publish_stored_project(store, materialized, **options)
    assert boundaries == ["context", "ping", "execute"] and sent(root).count("execute") == 1
    assert attempt.execution_contract_satisfied and not attempt.intent_verified
    assert attempt.retained_receipt_digest
    retained = store.get_create_receipts(attempt.record.digest).to_dict()
    assert retained["terminal_receipt_digest"] == attempt.retained_receipt_digest
    assert len(retained["receipts"]) == 1
    assert len(list(tmp_path.glob("*.sqlite"))) == 1  # No independent source archive file.
    assert advertisement.credentials.token not in json.dumps(retained)
    assert store.head().revision_id == materialized.project.revision_id


def test_lost_response_reopens_and_recovers_without_second_create(native_server, helper, tmp_path, monkeypatch):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    actual = publishing.exchange
    def lose_response(advertisement, request, **kwargs):
        response = actual(advertisement, request, **kwargs)
        if json.loads(request)["kind"] == "execute":
            raise ConnectorTransportError("controlled_lost_response", "response", delivery="unknown")
        return response
    monkeypatch.setattr(publishing, "exchange", lose_response)
    with pytest.raises(ConnectorTransportError):
        publishing.publish_stored_project(store, materialized, **options)
    digest = input_digest(store, options["operation_id"])
    assert store.get_create_receipts(digest).to_dict()["receipts"] == []
    reopened = ProjectStore.open(store.path, readonly=False)
    monkeypatch.setattr(publishing, "exchange", actual)
    monkeypatch.setattr(publishing, "prepare_execution", lambda *_a, **_kw: pytest.fail("recovery recompiled"))
    recovered = publishing.recover_stored_create(reopened, digest, advertisement=advertisement,
                                                  client_path=helper, timeout_ms=10000)
    assert recovered.execution_contract_satisfied and recovered.prepared is None
    assert recovered.retained_receipt_digest and sent(root).count("execute") == 1
    assert sent(root)[-1] == "receipt"


def test_partial_receipt_keeps_successful_rows_and_prevents_fresh_uuid_republish(native_server, helper, tmp_path):
    store, materialized, _, root, options = setup(native_server, helper, tmp_path, partial=True)
    attempt = publishing.publish_stored_project(store, materialized, **options)
    assert not attempt.execution_contract_satisfied and attempt.result.outcome.committed
    assert attempt.retained_receipt_digest
    result = json.loads(store.get_create_receipts(attempt.record.digest).to_dict()["receipts"][0]["native_receipt"]["result_json"])
    assert result[materialized.planned.ops[0].op_id]["id"] == "700"
    assert "refused" in result[materialized.planned.ops[-1].op_id]
    with pytest.raises(StoreConflict, match="output scope"):
        publishing.publish_stored_project(store, materialized, **{**options, "operation_id": str(uuid4())})
    assert sent(root).count("execute") == 1


def test_reservation_commit_ack_loss_never_reaches_execute(native_server, helper, tmp_path, monkeypatch):
    store, materialized, _, root, options = setup(native_server, helper, tmp_path)
    actual = ProjectStore.reserve_create_publication
    def lose_ack(self, record, **kwargs):
        actual(self, record, **kwargs)
        raise RuntimeError("controlled reservation ACK loss")
    monkeypatch.setattr(ProjectStore, "reserve_create_publication", lose_ack)
    with pytest.raises(RuntimeError, match="ACK loss"):
        publishing.publish_stored_project(store, materialized, **options)
    assert sent(root).count("execute") == 0
    digest = input_digest(store, options["operation_id"])
    assert ProjectStore.open(store.path).get_create_publication(digest).archive_digest == digest
    monkeypatch.setattr(ProjectStore, "reserve_create_publication", actual)
    with pytest.raises(publishing.PublicationRefusal, match="already_reserved"):
        publishing.publish_stored_project(store, materialized, **options)
    assert sent(root).count("execute") == 0


@pytest.mark.parametrize("committed", [False, True])
def test_receipt_storage_failure_recovers_without_second_create(
        native_server, helper, tmp_path, monkeypatch, committed):
    store, materialized, advertisement, root, options = setup(native_server, helper, tmp_path)
    actual = ProjectStore.record_create_receipt

    def lose_receipt_ack(self, evidence):
        if committed:
            actual(self, evidence)
        raise RuntimeError("controlled receipt storage failure")

    monkeypatch.setattr(ProjectStore, "record_create_receipt", lose_receipt_ack)
    with pytest.raises(RuntimeError, match="receipt storage failure"):
        publishing.publish_stored_project(store, materialized, **options)
    digest = input_digest(store, options["operation_id"])
    reopened = ProjectStore.open(store.path, readonly=False)
    before = reopened.get_create_receipts(digest).to_dict()
    assert len(before["receipts"]) == int(committed)
    assert sent(root).count("execute") == 1
    assert reopened.get_create_publication(digest).output_ids == tuple(
        op.op_id for op in materialized.planned.ops)

    monkeypatch.setattr(ProjectStore, "record_create_receipt", actual)
    monkeypatch.setattr(publishing, "prepare_execution",
                        lambda *_a, **_kw: pytest.fail("receipt recovery recompiled"))
    recovered = publishing.recover_stored_create(reopened, digest,
        advertisement=advertisement, client_path=helper, timeout_ms=10000)
    after = reopened.get_create_receipts(digest).to_dict()
    assert recovered.execution_contract_satisfied and recovered.prepared is None
    assert len(after["receipts"]) == 1
    assert after["terminal_receipt_digest"] == recovered.retained_receipt_digest
    if committed:
        assert before == after  # Lost local ACK does not duplicate native evidence.
    assert sent(root).count("execute") == 1 and sent(root)[-1] == "receipt"
    assert reopened.head().revision_id == materialized.project.revision_id


def test_source_mismatch_refuses_before_any_transport(native_server, helper, tmp_path, monkeypatch):
    store, materialized, _, root, options = setup(native_server, helper, tmp_path)
    before = sent(root)
    monkeypatch.setattr(publishing, "exchange", lambda *_a, **_kw: pytest.fail("wrong source reached transport"))
    with pytest.raises(publishing.PublicationRefusal, match="stored_source_mismatch"):
        publishing.publish_stored_project(store, materialized, **{**options, "expected_revision": "a" * 64})
    assert sent(root) == before


@pytest.mark.parametrize("isolation", ["atomic", "per_op"])
def test_explicit_isolation_reaches_exact_archived_source(native_server, helper, tmp_path, isolation):
    store, materialized, _, root, options = setup(native_server, helper, tmp_path)
    attempt = publishing.publish_stored_project(store, materialized, **options, isolation=isolation)
    source = store.get_create_publication(attempt.record.digest).record.to_dict()["source"]
    assert ("new SubTransaction(doc)" in source) is (isolation == "per_op")
    assert source == attempt.prepared.source
    assert attempt.record.to_dict()["plan_evidence"]["bulk"] is False
    assert sent(root).count("execute") == 1


@pytest.mark.parametrize("isolation", [None, True, "best_effort", []])
def test_invalid_isolation_never_reaches_transport(native_server, helper, tmp_path, monkeypatch, isolation):
    store, materialized, _, root, options = setup(native_server, helper, tmp_path)
    before = sent(root)
    monkeypatch.setattr(publishing, "exchange", lambda *_a, **_kw: pytest.fail("invalid isolation reached transport"))
    with pytest.raises(publishing.PublicationRefusal, match="invalid_isolation"):
        publishing.publish_stored_project(store, materialized, **options, isolation=isolation)
    assert sent(root) == before
