"""Early input checks avoid archives/pending; they do not probe a connection."""
from dataclasses import replace
import json
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir import standalone_publish as publisher
from kir.revit_transport import validate_exchange_inputs, exchange, ConnectorTransportError
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_project_realization_store import stored_case
from kir.tests.test_saved_level_update import advertisement_for
from kir.tests.test_level_update_acceptance import memory_case
from kir.tests.test_revit_transport import ready_response, helper


@pytest.mark.parametrize("fault", ["missing", "relative", "directory", "none", "expired"])
def test_bad_update_inputs_cannot_create_archive_or_reserve_pending(tmp_path, fault):
    store, case, _, _, _, _ = stored_case(tmp_path / "project.sqlite")
    advertisement = advertisement_for(case)
    client = sys.executable
    if fault == "missing": client = tmp_path / "missing-client"
    if fault == "relative": client = "relative-client"
    if fault == "directory": client = tmp_path
    if fault == "none": client = None
    if fault == "expired": advertisement = replace(advertisement, _expiry_ticks=0)
    before = store.path.read_bytes()
    archive_path = tmp_path / "must-not-be-created.sqlite"
    with patch.object(SavedExecutionRecord, "create_update_new", side_effect=AssertionError("archive reached")), \
         patch.object(publisher, "exchange", side_effect=AssertionError("delivery reached")):
        with pytest.raises(ConnectorTransportError) as caught:
            publisher.publish_level_update(case[1], advertisement=advertisement, client_path=client,
                archive_path=archive_path, operation_id=str(uuid4()), project_store=store)
    assert caught.value.code == ("advertisement_expired" if fault == "expired" else "client_unavailable")
    assert caught.value.delivery == "not_attempted" and not caught.value.may_retry
    assert not archive_path.exists() and store.path.read_bytes() == before
    assert case[0]["credentials"].token not in str(caught.value)


def test_disabling_early_gate_demonstrates_the_previously_orphaned_pending(tmp_path):
    store, case, _, _, _, _ = stored_case(tmp_path / "project.sqlite")
    path = tmp_path / "counterfactual.sqlite"
    # Mutation control: bypass the publisher's early validation and probe. The real exchange
    # still refuses the missing client, but now storage was already changed.
    with patch.object(publisher, "validate_exchange_inputs", return_value=None), \
         patch.object(publisher, "_probe_connection", return_value=None), \
         patch("kir.revit_transport.subprocess.Popen", side_effect=AssertionError("must never launch")):
        with pytest.raises(ConnectorTransportError, match="client_unavailable"):
            publisher.publish_level_update(case[1], advertisement=advertisement_for(case),
                client_path=tmp_path / "missing-client", archive_path=path,
                operation_id=str(uuid4()), project_store=store)
    record = SavedExecutionRecord.load(path)
    baseline = store.level_baseline(case[1].original_binding["binding_digest"])
    assert baseline.pending_archive_digest == record.digest


def test_preflight_is_read_only_and_pass_does_not_establish_connectivity():
    case = memory_case()
    advertisement = advertisement_for(case)  # pipe deliberately does not exist
    request = case[2].execute_request(case[0]["credentials"], request_id=str(uuid4()))
    with patch("kir.revit_transport.subprocess.Popen", side_effect=AssertionError("no launch/probe")):
        path = validate_exchange_inputs(advertisement, json.dumps(request).encode(), client_path=sys.executable)
    assert path == Path(sys.executable)


@pytest.mark.parametrize("fault", ["expired", "changed_request", "missing_client"])
def test_exchange_revalidates_after_an_earlier_successful_preflight(fault, tmp_path):
    case = memory_case()
    advertisement = advertisement_for(case)
    request = case[2].execute_request(case[0]["credentials"], request_id=str(uuid4()))
    validate_exchange_inputs(advertisement, json.dumps(request).encode(), client_path=sys.executable)
    client = sys.executable
    if fault == "expired": advertisement = replace(advertisement, _expiry_ticks=0)
    if fault == "changed_request": request["source_sha256"] = "a" * 64
    if fault == "missing_client": client = tmp_path / "missing-now"
    with patch("kir.revit_transport.subprocess.Popen", side_effect=AssertionError("must revalidate before launch")):
        with pytest.raises(ConnectorTransportError) as caught:
            exchange(advertisement, json.dumps(request).encode(), client_path=client)
    assert caught.value.delivery == "not_attempted" and not caught.value.may_retry


@pytest.mark.parametrize("fault", ["expired", "missing_client"])
def test_first_publication_rechecks_even_after_a_bound_context_was_returned(tmp_path, fault):
    case = memory_case()
    advertisement = advertisement_for(case)
    credentials = case[0]["credentials"]
    from kir.tests.test_connector_context import case as context_case
    # Synthetic first exchange: a bound context is not a substitute for the
    # current local session/path checks on the subsequent mutation request.
    def capture(advertisement, raw, **kwargs):
        request = json.loads(raw)
        _, _, response, _ = context_case.__wrapped__()
        response.update(target=credentials.target.to_dict(), session_id=credentials.session_id,
                        request_id=request["request_id"])
        response["context"]["document_key"] = "native-doc"
        return json.dumps(response).encode()
    with patch.object(publisher, "exchange", side_effect=capture), \
         patch.object(SavedExecutionRecord, "create_new", side_effect=AssertionError("archive reached")):
        if fault == "expired": advertisement = replace(advertisement, _expiry_ticks=0)
        with pytest.raises(ConnectorTransportError):
            publisher.publish_program({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
                advertisement=advertisement, client_path=sys.executable if fault == "expired" else tmp_path / "missing",
                archive_path=tmp_path / "must-not-exist.sqlite", expected_document_key="native-doc",
                operation_id=str(uuid4()), bind_view=False, bind_selection=False)


@pytest.mark.parametrize("fault", ["unready", "foreign_route", "unknown_reply", "missing_helper_reply"])
def test_unsuccessful_readiness_probe_leaves_no_archive_or_pending(tmp_path, fault):
    store, case, _, _, _, _ = stored_case(tmp_path / "project.sqlite")
    before = store.path.read_bytes()
    path = tmp_path / "must-not-be-created.sqlite"
    requests = []
    def probe(advertisement, raw, **kwargs):
        request = json.loads(raw)
        requests.append(request)
        assert request["kind"] == "ping" and not path.exists()
        response = ready_response(request)
        if fault == "unready": response.update(ok=False, status="disabled", error="synthetic refusal")
        if fault == "foreign_route": response["session_id"] = str(uuid4())
        if fault == "unknown_reply": return b"{}"
        if fault == "missing_helper_reply":
            raise ConnectorTransportError("synthetic_probe_loss", "response", delivery="unknown")
        return json.dumps(response).encode()
    with patch.object(publisher, "exchange", side_effect=probe), \
         patch.object(SavedExecutionRecord, "create_update_new", side_effect=AssertionError("archive reached")):
        with pytest.raises((publisher.PublicationRefusal, ConnectorTransportError)):
            publisher.publish_level_update(case[1], advertisement=advertisement_for(case), client_path=sys.executable,
                archive_path=path, operation_id=str(uuid4()), project_store=store)
    assert len(requests) == 1 and "operation_id" not in requests[0] and "source" not in requests[0]
    assert not path.exists() and store.path.read_bytes() == before


def test_real_helper_cannot_connect_and_no_archive_or_pending_is_created(tmp_path, helper):
    store, case, _, _, _, _ = stored_case(tmp_path / "project.sqlite")
    advertisement = advertisement_for(case)  # absent pipe, not a fake exchange
    before = store.path.read_bytes()
    path = tmp_path / "must-not-exist.sqlite"
    with pytest.raises(ConnectorTransportError):
        publisher.publish_level_update(case[1], advertisement=advertisement, client_path=helper,
            archive_path=path, operation_id=str(uuid4()), project_store=store, timeout_ms=1000)
    assert not path.exists() and store.path.read_bytes() == before
