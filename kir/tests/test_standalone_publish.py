"""First-send ordering over real local pipes/SQLite, with explicitly seeded receipts.

The reused server dispatches real Collector/Service code against API stubs. It
does NOT invoke generated Revit code, so a seeded receipt cannot prove native BIM.
"""
import json
from pathlib import Path
from uuid import uuid4

import pytest

from kir import standalone_publish as publishing
from kir.connector_result import assess_connector_context_response, assess_connector_write_response
from kir.revit_connector import ConnectorPreparationError, prepare_execution
from kir.revit_transport import ConnectorTransportError, exchange
from kir.saved_execution import SavedExecutionError, SavedExecutionRecord
from kir.tests.test_revit_transport import helper, native_server, wire


PROGRAM = {"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]}


def probe(record, client):
    request = record.credentials.context_request(request_id=str(uuid4()))
    response = exchange(record, wire(request), client_path=client, timeout_ms=10000)
    result = assess_connector_context_response(response, credentials=record.credentials, request_id=request["request_id"])
    assert result.read_complete
    return result.require_precondition(bind_view=True, bind_selection=True)


def kwargs(record, client, path, precondition):
    return dict(advertisement=record, client_path=client, archive_path=path,
                expected_document_key=precondition.document_key, operation_id=str(uuid4()),
                bind_view=True, bind_selection=True, timeout_ms=10000)


def sent(root):
    path = root / "requests"
    return path.read_text().splitlines() if path.exists() else []


@pytest.mark.parametrize("year", ["2023", "2026"])
def test_one_first_delivery_follows_durable_matching_archive_and_assesses_seeded_receipt(native_server, helper, tmp_path, monkeypatch, year):
    record, root = native_server(year)
    precondition = probe(record, helper)
    path = tmp_path / "operation.sqlite"
    options = kwargs(record, helper, path, precondition)
    actual = publishing.exchange
    boundaries = []

    def inspect_before_send(advertisement, request, **arguments):
        decoded = json.loads(request)
        boundaries.append(decoded["kind"])
        if decoded["kind"] == "execute":
            saved = SavedExecutionRecord.load(path)
            assert saved.binding_dict()["operation_id"] == options["operation_id"]
            assert saved.binding_dict()["source_sha256"] == decoded["source_sha256"]
            assert saved.to_dict()["source"] == decoded["source"]
            fresh = prepare_execution(PROGRAM, target=record.credentials.target,
                precondition=precondition, operation_id=options["operation_id"])
            saved.require_matches(fresh)
        return actual(advertisement, request, **arguments)
    monkeypatch.setattr(publishing, "exchange", inspect_before_send)
    result = publishing.publish_program(PROGRAM, **options)
    assert boundaries == ["context", "ping", "execute"]
    assert sent(root) == ["context", "context", "ping", "execute"]
    assert result.execution_contract_satisfied and not result.intent_verified
    assert result.result.outcome.acceptance.value == "not_run"
    assert result.record.digest == SavedExecutionRecord.load(path).digest
    assert record.credentials.token not in repr(result)
    assert result.record.to_dict()["claims"]["dispatch_state"] == "not_recorded"


def test_wrong_expected_document_refuses_before_compile_archive_or_execute(native_server, helper, tmp_path, monkeypatch):
    record, root = native_server()
    options = kwargs(record, helper, tmp_path / "operation.sqlite", probe(record, helper))
    options["expected_document_key"] = "different-opaque-document-not-a-title"
    def forbidden(*args, **kwargs):
        raise AssertionError("wrong document reached compilation")
    monkeypatch.setattr(publishing, "prepare_execution", forbidden)
    with pytest.raises(publishing.PublicationRefusal, match="unexpected_document"):
        publishing.publish_program(PROGRAM, **options)
    assert not options["archive_path"].exists()
    assert "execute" not in sent(root)


def test_existing_archive_is_not_a_replay_ticket(native_server, helper, tmp_path):
    record, root = native_server()
    options = kwargs(record, helper, tmp_path / "operation.sqlite", probe(record, helper))
    publishing.publish_program(PROGRAM, **options)
    before = options["archive_path"].read_bytes()
    with pytest.raises(SavedExecutionError, match="archive_exists"):
        publishing.publish_program(PROGRAM, **options)
    assert sent(root).count("execute") == 1
    assert options["archive_path"].read_bytes() == before


def test_existing_unrelated_file_is_not_overwritten_or_sent(native_server, helper, tmp_path):
    record, root = native_server()
    options = kwargs(record, helper, tmp_path / "keep.txt", probe(record, helper))
    options["archive_path"].write_bytes(b"user file")
    with pytest.raises(SavedExecutionError, match="archive_exists"):
        publishing.publish_program(PROGRAM, **options)
    assert "execute" not in sent(root)
    assert options["archive_path"].read_bytes() == b"user file"


def test_post_commit_archive_flush_failure_cannot_dispatch(native_server, helper, tmp_path, monkeypatch):
    import kir.saved_execution as archive
    record, root = native_server()
    options = kwargs(record, helper, tmp_path / "uncertain.sqlite", probe(record, helper))
    def fail_flush(path):
        raise OSError("injected post-commit flush failure")
    monkeypatch.setattr(archive, "_flush_created", fail_flush)
    with pytest.raises(SavedExecutionError, match="archive_durability_unconfirmed"):
        publishing.publish_program(PROGRAM, **options)
    assert options["archive_path"].exists()
    assert SavedExecutionRecord.load(options["archive_path"]).binding_dict()["operation_id"] == options["operation_id"]
    assert "execute" not in sent(root)


def test_returned_archive_must_match_fresh_compilation_before_delivery(native_server, helper, tmp_path, monkeypatch):
    record, root = native_server()
    precondition = probe(record, helper)
    options = kwargs(record, helper, tmp_path / "wrong.sqlite", precondition)
    actual = SavedExecutionRecord.create_new
    def wrong_archive(cls, path, prepared):
        different = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 5000}]},
            target=prepared.target, precondition=prepared.precondition, operation_id=prepared.operation_id)
        return actual(path, different)
    monkeypatch.setattr(SavedExecutionRecord, "create_new", classmethod(wrong_archive))
    with pytest.raises(SavedExecutionError, match="saved_execution_mismatch"):
        publishing.publish_program(PROGRAM, **options)
    assert options["archive_path"].exists()
    assert "execute" not in sent(root)


def test_response_loss_keeps_original_archive_and_does_not_retry(native_server, helper, tmp_path, monkeypatch):
    record, root = native_server()
    precondition = probe(record, helper)
    options = kwargs(record, helper, tmp_path / "lost.sqlite", precondition)
    actual = publishing.exchange
    def lose_after_exchange(advertisement, request, **arguments):
        result = actual(advertisement, request, **arguments)
        if json.loads(request)["kind"] == "execute":
            raise ConnectorTransportError("injected_response_loss", "response", delivery="unknown")
        return result
    monkeypatch.setattr(publishing, "exchange", lose_after_exchange)
    with pytest.raises(ConnectorTransportError) as caught:
        publishing.publish_program(PROGRAM, **options)
    assert caught.value.delivery == "unknown" and caught.value.may_retry is False
    assert sent(root).count("execute") == 1
    # Reopening does not compile or produce a write method. Explicitly query
    # the original operation's receipt, not publish again with a fresh UUID.
    saved = SavedExecutionRecord.load(options["archive_path"])
    assert not hasattr(saved, "execute_request") and not hasattr(saved, "to_prepared")
    request_id = str(uuid4())
    request = saved.receipt_request(record.credentials, request_id=request_id)
    response = actual(record, wire(request), client_path=helper, timeout_ms=10000)
    fresh = prepare_execution(PROGRAM, target=record.credentials.target,
                              precondition=precondition, operation_id=options["operation_id"])
    saved.require_matches(fresh)
    result = assess_connector_write_response(fresh, response, credentials=record.credentials, request_id=request_id)
    assert result.ok and result.outcome.acceptance.value == "not_run"
    assert sent(root).count("execute") == 1 and sent(root)[-1] == "receipt"


def test_malformed_execution_response_stays_unconfirmed_without_second_delivery(native_server, helper, tmp_path, monkeypatch):
    record, root = native_server()
    options = kwargs(record, helper, tmp_path / "invalid-reply.sqlite", probe(record, helper))
    actual = publishing.exchange
    def corrupt_response(advertisement, request, **arguments):
        response = actual(advertisement, request, **arguments)
        return b'{"ok":true}' if json.loads(request)["kind"] == "execute" else response
    monkeypatch.setattr(publishing, "exchange", corrupt_response)
    result = publishing.publish_program(PROGRAM, **options)
    assert not result.execution_contract_satisfied and not result.intent_verified
    assert result.result.outcome.execution.value == "unconfirmed"
    assert result.result.outcome.retry_safety.value == "verify_first"
    assert sent(root).count("execute") == 1 and options["archive_path"].exists()


def test_invalid_program_refuses_before_archive_or_execute(native_server, helper, tmp_path):
    record, root = native_server()
    options = kwargs(record, helper, tmp_path / "bad-program.sqlite", probe(record, helper))
    with pytest.raises(ConnectorPreparationError, match="compile_refused"):
        publishing.publish_program({"ops": [{"op": "unrecognized_operation", "id": "bad"}]}, **options)
    assert not options["archive_path"].exists() and "execute" not in sent(root)


def test_query_program_is_not_sent_through_write_publication(native_server, helper, tmp_path):
    record, root = native_server()
    options = kwargs(record, helper, tmp_path / "query.sqlite", probe(record, helper))
    with pytest.raises(publishing.PublicationRefusal, match="write_program_required"):
        publishing.publish_program({"ops": [{"op": "query_list", "id": "Q", "kind": "wall"}]}, **options)
    assert not options["archive_path"].exists() and "execute" not in sent(root)


@pytest.mark.parametrize("case", ["no_document", "incomplete", "foreign", "malformed"])
def test_unusable_context_never_reaches_compilation_or_archive(native_server, helper, tmp_path, monkeypatch, case):
    record, root = native_server()
    options = kwargs(record, helper, tmp_path / "no-context.sqlite", probe(record, helper))
    actual = publishing.exchange
    def unusable_context(advertisement, request, **arguments):
        assert json.loads(request)["kind"] == "context"
        response = json.loads(actual(advertisement, request, **arguments))
        if case == "malformed":
            return b'{"ok":true}'
        if case == "incomplete":
            response["context"]["complete"] = False
        elif case == "foreign":
            response["target"]["instance_id"] = str(uuid4())
        else:
            response["context"].update(has_document=False, document_key="", document_title="",
                revision=0, active_view_id=0, selection_digest="", selection_count=0,
                is_family_document=False, is_read_only=False, is_modifiable=False)
        return wire(response)
    def forbidden(*args, **kwargs):
        raise AssertionError("unusable context reached compilation")
    monkeypatch.setattr(publishing, "exchange", unusable_context)
    monkeypatch.setattr(publishing, "prepare_execution", forbidden)
    with pytest.raises(publishing.PublicationRefusal, match="context_unavailable"):
        publishing.publish_program(PROGRAM, **options)
    assert not options["archive_path"].exists() and "execute" not in sent(root)


@pytest.mark.parametrize("field,value", [("bind_view", 1), ("bind_selection", None),
    ("bulk", "false"), ("timeout_ms", True), ("operation_id", "not-a-uuid"), ("expected_document_key", "")])
def test_invalid_explicit_inputs_fail_before_transport(monkeypatch, field, value):
    from kir.tests.test_revit_transport import advertisement
    record = advertisement()
    options = dict(advertisement=record, client_path=Path("/unused"), archive_path=Path("/unused"),
        expected_document_key="opaque", operation_id=str(uuid4()), bind_view=True, bind_selection=True)
    options[field] = value
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid input reached transport")
    monkeypatch.setattr(publishing, "exchange", forbidden)
    with pytest.raises((publishing.PublicationRefusal, ConnectorPreparationError)):
        publishing.publish_program(PROGRAM, **options)
