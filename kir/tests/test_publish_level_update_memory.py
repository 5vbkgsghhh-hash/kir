"""Actual dispatcher order with in-memory archive/transport seams, not live I/O."""
from dataclasses import replace
import json
import sys
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir import standalone_publish as publisher
from kir.revit_discovery import load_discovery
from kir.revit_transport import ConnectorTransportError
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError, _capture
from kir.tests.test_level_update_acceptance import memory_case
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_revit_transport import ready_response


def run(*, fault=None):
    case = memory_case()
    source, update = case[:2]
    credentials = source["credentials"]
    declaration = {"protocol": "kir-revit-connector/4", "target": credentials.target.to_dict(),
        "session_id": credentials.session_id, "token": credentials.token, "pipe_name": "synthetic-not-connected",
        "process_id": 123, "expires_utc": "2099-01-01T00:00:00.0000000Z"}
    advertisement = load_discovery(json.dumps(declaration).encode())
    if fault == "target":
        declaration["target"]["instance_id"] = str(uuid4())
        advertisement = load_discovery(json.dumps(declaration).encode())
    events, retained = [], {}
    def archive(path, prepared, submission):
        events.append("archive")
        if fault == "exists": raise SavedExecutionError("archive_exists", "synthetic existing path")
        if fault == "flush": raise SavedExecutionError("archive_durability_unconfirmed", "synthetic flush failure")
        record = SavedExecutionRecord._from_bytes(_capture(prepared, level_update=submission))
        retained.update(record=record, prepared=prepared)
        return record
    def exchange(advertisement, raw, **kwargs):
        request = json.loads(raw)
        events.append(request["kind"])
        if request["kind"] == "ping":
            assert events == ["ping"] and not retained
            return json.dumps(ready_response(request)).encode()
        assert events == ["ping", "archive", "execute"]  # no context refresh or premature mutation
        record, prepared = retained["record"], retained["prepared"]
        assert request["source"] == record.to_dict()["source"]
        assert request["precondition"] == update.precondition.to_dict()
        assert prepared.expected_identities == update.expected_identities
        if fault == "lost_reply": raise ConnectorTransportError("synthetic_loss", "response", delivery="unknown")
        operation = prepared.planned.to_ops()[0]
        value = {"ok": True, operation["id"]: {"id": str(operation["target"]["value"]), "param": operation["param"]}}
        response = response_for(prepared, credentials, value, changes={"added": [], "modified": [901], "deleted": [],
            "transaction_names": ["synthetic setter"], "truncated": False})
        response["request_id"] = request["request_id"]
        if fault == "binding": response["receipt"]["source_sha256"] = "f" * 64
        return json.dumps(response).encode()
    with patch.object(SavedExecutionRecord, "create_update_new", side_effect=archive), \
         patch.object(publisher, "exchange", side_effect=exchange):
        try:
            attempt = publisher.publish_level_update(update, advertisement=advertisement, client_path=sys.executable,
                archive_path="/not-created", operation_id=str(uuid4()))
        except (publisher.PublicationRefusal, SavedExecutionError, ConnectorTransportError) as error:
            return error, events, retained
    return attempt, events, retained


def test_update_is_archived_and_checked_before_one_delivery_without_context_refresh():
    result, events, retained = run()
    assert events == ["ping", "archive", "execute"] and result.execution_contract_satisfied
    assert not result.intent_verified and result.prepared is retained["prepared"]
    assert result.record.update_submission is not None


@pytest.mark.parametrize("fault,events", [("target", []), ("exists", ["ping", "archive"]), ("flush", ["ping", "archive"])])
def test_failed_prerequisites_do_not_dispatch(fault, events):
    error, actual, _ = run(fault=fault)
    assert isinstance(error, Exception) and actual == events


def test_lost_reply_keeps_original_archive_and_does_not_retry():
    error, events, retained = run(fault="lost_reply")
    assert isinstance(error, ConnectorTransportError) and error.may_retry is False
    assert events == ["ping", "archive", "execute"] and retained["record"].update_submission


def test_foreign_receipt_cannot_make_update_successful():
    result, events, _ = run(fault="binding")
    assert events == ["ping", "archive", "execute"] and not result.execution_contract_satisfied
    assert result.result.outcome.execution.value == "unconfirmed"
