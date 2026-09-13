"""Python journal-control contract; real local store, synthetic native replies."""
from copy import deepcopy
import json
import sys
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir import revit_transport as transport
from kir.level_resolution import (request_cancel_pending_level_update, qualify_level_not_started,
    LevelResolutionRefusal)
from kir.project_store import ProjectStore, RESOLUTION_STORE_SCHEMA, StoreCommitUnknown, StoreConflict
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.revit_level_update import prepare_level_update
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError, _capture
from kir.update_submission import bind_level_update_submission
from kir.tests.test_level_resolution import before_start_response
from kir.tests.test_project_realization_store import stored_case
from kir.tests.test_saved_level_update import advertisement_for
from kir.tests.test_update_submission_memory import record_values


def test_saved_cancel_request_has_exact_original_binding_but_no_source_or_execute_api():
    case, _, record = record_values()
    auth = case[0]["credentials"]
    before = record._raw
    with patch("kir.compiler.compile_program", side_effect=AssertionError("no compile")), \
         patch("kir.compiler.plan_program", side_effect=AssertionError("no plan")):
        request = record.cancel_before_start_request(auth, request_id=str(uuid4()))
    assert set(request) == {"protocol", "request_id", "target", "session_id", "token", "kind", "timeout_ms",
                            "operation_id", "source_sha256", "precondition"}
    assert request["kind"] == "cancel_before_start"
    for key, value in record.binding_dict().items(): assert request[key] == value
    assert record._raw == before and not hasattr(record, "execute_request")
    transport.validate_exchange_inputs(advertisement_for(case), json.dumps(request).encode(), client_path=sys.executable)
    foreign = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "foreign")
    with pytest.raises(SavedExecutionError, match="target_mismatch"):
        record.cancel_before_start_request(foreign, request_id=str(uuid4()))
    assert record.recovery_request(foreign, request_id=str(uuid4()))["kind"] == "recover_receipt"


@pytest.mark.parametrize("fault", ["source_null", "source", "recovery_null", "context", "missing_precondition",
    "precondition_key", "revision_bool", "bad_sha", "short_sha", "missing_operation", "wrong_target"])
def test_cancel_transport_rejects_wrong_field_shape_before_launch(fault):
    case, _, record = record_values()
    request = record.cancel_before_start_request(case[0]["credentials"], request_id=str(uuid4()))
    if fault == "source_null": request["source"] = None
    if fault == "source": request["source"] = "must not execute"
    if fault == "recovery_null": request["recovery_target"] = None
    if fault == "context": request["context"] = {}
    if fault == "missing_precondition": request.pop("precondition")
    if fault == "precondition_key": request["precondition"].pop("active_view_id")
    if fault == "revision_bool": request["precondition"]["revision"] = True
    if fault == "bad_sha": request["source_sha256"] = "x" * 64
    if fault == "short_sha": request["source_sha256"] = "a" * 63
    if fault == "missing_operation": request.pop("operation_id")
    if fault == "wrong_target": request["target"]["instance_id"] = str(uuid4())
    with patch.object(transport.subprocess, "Popen", side_effect=AssertionError("must not launch")):
        with pytest.raises(transport.ConnectorTransportError) as error:
            transport.exchange(advertisement_for(case), json.dumps(request).encode(), client_path=sys.executable)
    assert error.value.delivery == "not_attempted" and error.value.may_retry is False


def setup_pending(tmp_path):
    store, case, record, _, _, _ = stored_case(tmp_path / "project.sqlite", schema=RESOLUTION_STORE_SCHEMA)
    store.reserve_level_update(record, expected_checkpoint=None)
    stream = record.update_submission["original_publication"]["binding_digest"]
    return store, case, record, stream


def call_cancel(store, case, record, stream):
    return request_cancel_pending_level_update(store, stream_id=stream, expected_pending_archive=record.digest,
        advertisement=advertisement_for(case), client_path=sys.executable, request_id=str(uuid4()))


@pytest.mark.parametrize("state", ["cancelled", "committed", "started", "conflict", "lost"])
def test_one_cancel_exchange_only_resolves_bound_not_started(tmp_path, state):
    store, case, record, stream = setup_pending(tmp_path)
    calls = []
    def exchange(advertisement, raw, **kwargs):
        request = json.loads(raw)
        transport.validate_exchange_inputs(advertisement, raw, client_path=sys.executable)
        assert request["kind"] == "cancel_before_start" and request["operation_id"] == record.binding_dict()["operation_id"]
        calls.append(request)
        if state == "lost":
            raise transport.ConnectorTransportError("synthetic_loss", "response", delivery="unknown")
        response = deepcopy(case[3]) if state == "committed" else before_start_response(case, "cancelled_before_start")
        response["request_id"] = request["request_id"]
        if state == "started": response["receipt"].update(state="running_unknown", started=True, may_retry=False)
        if state == "conflict": response.update(ok=False, status="operation_conflict", error="synthetic conflict", receipt=None)
        return json.dumps(response).encode()
    with patch.object(transport, "exchange", side_effect=exchange):
        if state == "lost":
            with pytest.raises(transport.ConnectorTransportError): call_cancel(store, case, record, stream)
        else:
            result = call_cancel(store, case, record, stream)
            assert result.resolution_recorded is (state == "cancelled") and not result.may_retry
            assert case[0]["credentials"].token not in repr(result)
            if state == "committed": assert result.result.outcome.execution.value == "committed"
    assert len(calls) == 1
    assert store.level_baseline(stream).pending_archive_digest == (None if state == "cancelled" else record.digest)
    assert store.level_baseline(stream).checkpoint_digest is None


@pytest.mark.parametrize("actually_committed", [False, True])
def test_uncertain_storage_ack_uses_readback_never_repeats_native_or_storage_write(tmp_path, actually_committed):
    store, case, record, stream = setup_pending(tmp_path)
    actual = ProjectStore.commit_level_not_started
    writes, sends = [], []
    def uncertain(self, qualified, **kwargs):
        writes.append(qualified.digest)
        if actually_committed: actual(self, qualified, **kwargs)
        raise StoreCommitUnknown("synthetic lost storage acknowledgement")
    def exchange(advertisement, raw, **kwargs):
        request = json.loads(raw)
        sends.append(request["kind"])
        response = before_start_response(case, "cancelled_before_start")
        response["request_id"] = request["request_id"]
        return json.dumps(response).encode()
    with patch.object(ProjectStore, "commit_level_not_started", new=uncertain), \
         patch.object(transport, "exchange", side_effect=exchange):
        if actually_committed:
            result = call_cancel(store, case, record, stream)
            assert result.resolution_recorded and result.storage_acknowledgement == "read_back"
        else:
            with pytest.raises(StoreCommitUnknown): call_cancel(store, case, record, stream)
    assert len(writes) == 1 and sends == ["cancel_before_start"]
    assert store.level_baseline(stream).pending_archive_digest == (None if actually_committed else record.digest)


@pytest.mark.parametrize("same_receipt", [False, True])
def test_racing_resolution_ack_never_cancels_or_clears_new_pending(tmp_path, same_receipt):
    store, case, record, stream = setup_pending(tmp_path)
    new = prepare_level_update(case[1], operation_id=str(uuid4()))
    next_record = SavedExecutionRecord._from_bytes(_capture(new, level_update=bind_level_update_submission(case[1], new)))
    sends = []
    def exchange(advertisement, raw, **kwargs):
        request = json.loads(raw)
        sends.append(request)
        assert request["operation_id"] == record.binding_dict()["operation_id"]
        response = before_start_response(case, "cancelled_before_start")
        # Another controller sees the same native receipt through its own response ID.
        qualified = qualify_level_not_started(record, json.dumps(response), credentials=case[0]["credentials"],
            request_id=response["request_id"])
        store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
        store.reserve_level_update(next_record, expected_checkpoint=None)
        response["request_id"] = request["request_id"]
        if not same_receipt: response["receipt"]["error"] = "contradicting native receipt"
        return json.dumps(response).encode()
    with patch.object(transport, "exchange", side_effect=exchange):
        if same_receipt:
            result = call_cancel(store, case, record, stream)
            assert result.resolution_recorded and result.storage_acknowledgement == "read_back"
        else:
            with pytest.raises(StoreConflict): call_cancel(store, case, record, stream)
    assert len(sends) == 1 and store.level_baseline(stream).pending_archive_digest == next_record.digest
    with patch.object(transport, "exchange", side_effect=AssertionError("stale UI must not cancel another operation")):
        with pytest.raises(LevelResolutionRefusal, match="pending_level_update_changed"):
            call_cancel(store, case, record, stream)


def test_no_pending_does_not_send_journal_control(tmp_path):
    store, case, record, stream = setup_pending(tmp_path)
    response = before_start_response(case)
    qualified = qualify_level_not_started(record, json.dumps(response), credentials=case[0]["credentials"],
        request_id=response["request_id"])
    store.commit_level_not_started(qualified, expected_checkpoint=None, expected_pending_archive=record.digest)
    with patch.object(transport, "exchange", side_effect=AssertionError("no target operation")):
        with pytest.raises(LevelResolutionRefusal, match="no_pending_level_update"):
            call_cancel(store, case, record, stream)
