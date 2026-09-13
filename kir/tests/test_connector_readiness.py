"""Bound ping readiness only; no native runtime/model or transport is invoked."""
from copy import deepcopy
import json
import traceback
from uuid import uuid4

import pytest

from kir import connector_result as results
from kir import revit_connector as native


DETAIL = "connector_not_ready: Connector readiness was not confirmed for the selected session."


@pytest.fixture
def case():
    credentials = native.SessionCredentials(native.RuntimeTarget(str(uuid4()), str(uuid4()), "2026"),
                                             str(uuid4()), "synthetic-private-readiness-token")
    request_id = str(uuid4())
    response = {"protocol": native.CONNECTOR_PROTOCOL, "request_id": request_id,
                "target": credentials.target.to_dict(), "session_id": credentials.session_id,
                "ok": True, "status": "ready", "error": None, "context": None, "receipt": None}
    return credentials, request_id, response


def require(case, response=None, **kwargs):
    credentials, request_id, positive = case
    arguments = {"credentials": credentials, "request_id": request_id}
    arguments.update(kwargs)
    return results.require_connector_ready_response(
        json.dumps(positive if response is None else response), **arguments)


def refuse(case, *, wire=None, response=None, **kwargs):
    credentials, request_id, positive = case
    arguments = {"credentials": credentials, "request_id": request_id}
    arguments.update(kwargs)
    with pytest.raises(native.ConnectorPreparationError) as caught:
        results.require_connector_ready_response(
            wire if wire is not None else json.dumps(positive if response is None else response), **arguments)
    assert caught.value.code == "connector_not_ready" and str(caught.value) == DETAIL
    assert not caught.value.diagnostics and caught.value.__cause__ is None
    assert credentials.token not in "".join(traceback.format_exception(caught.value))


def test_ping_is_only_standard_core_without_operation_or_document_inputs(case, monkeypatch):
    credentials, request_id, _ = case
    def forbidden(*args, **kwargs):
        pytest.fail("ping tried to prepare/compile model code")
    monkeypatch.setattr(native, "prepare_execution", forbidden)
    monkeypatch.setattr(native, "compile_program", forbidden)
    request = credentials.ping_request(request_id=request_id)
    assert request == {"protocol": native.CONNECTOR_PROTOCOL, "request_id": request_id,
        "target": credentials.target.to_dict(), "session_id": credentials.session_id,
        "token": credentials.token, "kind": "ping", "timeout_ms": 30000}
    assert credentials.ping_request(request_id=request_id, timeout_ms=1000)["timeout_ms"] == 1000
    assert credentials.context_request(request_id=request_id)["kind"] == "context"
    assert require(case) is None


@pytest.mark.parametrize("timeout", [None, True, 999, 300001, 1000.0])
def test_ping_keeps_existing_core_timeout_validation(case, timeout):
    with pytest.raises(native.ConnectorPreparationError, match="invalid_input"):
        case[0].ping_request(request_id=case[1], timeout_ms=timeout)


def test_ping_keeps_existing_request_uuid_and_frame_limits(case, monkeypatch):
    with pytest.raises(native.ConnectorPreparationError, match="invalid_input"):
        case[0].ping_request(request_id="not-a-uuid")
    monkeypatch.setattr(native, "MAX_FRAME_BYTES", 10)
    with pytest.raises(native.ConnectorPreparationError, match="frame_budget_exceeded"):
        case[0].ping_request(request_id=case[1])


@pytest.mark.parametrize("field,value", [
    ("protocol", "kir-revit-connector/3"), ("request_id", "another"), ("session_id", str(uuid4())),
    ("target", None), ("ok", False), ("ok", 1), ("ok", "true"),
    ("status", "disabled"), ("status", "receipt"), ("status", "context"),
    ("status", ["ready"]), ("error", "synthetic-private-readiness-token"), ("error", False),
    ("context", {}), ("context", False), ("receipt", {}), ("receipt", False),
    ("token", "synthetic-private-readiness-token"),
])
def test_nonready_or_extra_data_never_qualifies(case, field, value):
    response = deepcopy(case[2])
    response[field] = value
    refuse(case, response=response)


@pytest.mark.parametrize("field", ["protocol", "request_id", "target", "session_id", "ok", "status", "error", "context", "receipt"])
def test_missing_fields_are_not_filled_with_ready_defaults(case, field):
    response = deepcopy(case[2])
    del response[field]
    refuse(case, response=response)


@pytest.mark.parametrize("field,value", [
    ("journal_id", str(uuid4())), ("instance_id", str(uuid4())), ("revit_version", "2023"),
    ("journal_id", True), ("revit_version", None), ("token", "synthetic-private-readiness-token"),
])
def test_every_target_axis_and_unknown_target_field_is_checked(case, field, value):
    response = deepcopy(case[2])
    response["target"][field] = value
    refuse(case, response=response)


@pytest.mark.parametrize("wire", ["", "null", "[]", '"ready"', '{"ok":NaN}', '{"ok":1e999}',
                                 '{"value":"\\ud800"}', b"\xff"])
def test_invalid_json_has_only_the_safe_constant_diagnostic(case, wire):
    refuse(case, wire=wire)


def test_duplicates_depth_budget_and_nonwire_objects_are_refused(case, monkeypatch):
    encoded = json.dumps(case[2])
    refuse(case, wire=encoded[:-1] + ',"ok":true}')
    response = deepcopy(case[2])
    deep = {}
    response["context"] = deep
    for _ in range(70):
        deep["next"] = {}
        deep = deep["next"]
    refuse(case, response=response)
    refuse(case, wire={"not": "wire bytes"})
    monkeypatch.setattr(results, "MAX_FRAME_BYTES", len(encoded.encode()) - 1)
    refuse(case, wire=encoded)


def test_ready_bytes_are_accepted_but_wrong_caller_context_is_not(case):
    credentials, request_id, response = case
    assert results.require_connector_ready_response(json.dumps(response).encode(),
        credentials=credentials, request_id=request_id) is None
    refuse(case, credentials=None)
    refuse(case, request_id=credentials.token)


def test_readiness_function_is_public_without_a_new_authority_carrier():
    namespace = {}
    exec("from kir.connector_result import *", namespace)
    assert namespace["require_connector_ready_response"] is results.require_connector_ready_response
    assert not any("Readiness" in name for name in namespace)
