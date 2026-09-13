"""Bound query availability, explicitly not native field/readback acceptance."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from kir.connector_result import assess_connector_query_response, assess_connector_write_response
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials, prepare_execution


def test_public_query_contract_is_exported():
    namespace = {}
    exec("from kir.connector_result import *", namespace)
    assert namespace["assess_connector_query_response"] is assess_connector_query_response
    assert "ConnectorQueryAssessment" in namespace


@pytest.fixture
def case():
    target = RuntimeTarget(str(uuid4()), str(uuid4()), "2023")
    credentials = SessionCredentials(target, str(uuid4()), "not-in-result")
    prepared = prepare_execution({"ops": [{"op": "query_inspect", "id": "read",
        "target": {"by": "element_id", "value": 700}}]}, target=target,
        precondition=ContextPrecondition("original-document", 17), operation_id=str(uuid4()))
    receipt = {**prepared.binding_dict(), "document_key": "original-document",
        "state": "invocation_completed", "started": True, "may_retry": False,
        "transaction_evidence": "changes_not_observed", "semantic_evidence": "unverified",
        "result_json": json.dumps({"read": {"id": "700", "name": "Level"}}),
        "result_truncated": False, "result_error": None, "error": None,
        "changes": {"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False},
        "timestamp_utc": "2026-09-05T12:00:00.0000000Z"}
    response = {"protocol": "kir-revit-connector/4", "request_id": str(uuid4()),
        "target": target.to_dict(), "session_id": credentials.session_id,
        "ok": True, "status": "receipt", "error": None, "context": None, "receipt": receipt}
    request_id = response["request_id"]

    def assess(payload=None, *, wire=None, artifact=prepared):
        return assess_connector_query_response(artifact,
            wire if wire is not None else json.dumps(response if payload is None else payload),
            credentials=credentials, request_id=request_id)

    return prepared, credentials, response, assess


def test_query_payload_retains_observed_precondition_without_claiming_field_validation(case):
    artifact, credentials, response, assess = case
    result = assess()
    assert result.result_available and result.binding_matches
    assert result.precondition is artifact.precondition
    assert result.precondition.revision == 17
    assert result.result == {"read": {"id": "700", "name": "Level"}}
    assert result.receipt == response["receipt"]
    assert not hasattr(result, "ok") and not hasattr(result, "outcome")
    assert credentials.token not in repr(result)
    detached = result.result
    detached["read"]["id"] = "701"
    detached_receipt = result.receipt
    detached_receipt["precondition"]["revision"] = 99
    assert result.result["read"]["id"] == "700"
    assert result.receipt["precondition"]["revision"] == 17


@pytest.mark.parametrize("row", [{}, {"read": {"error": "not_found"}}, {"read": {"incomplete": True}}])
def test_available_payload_is_not_element_presence_or_schema_acceptance(case, row):
    _, _, response, assess = case
    response["receipt"]["result_json"] = json.dumps(row)
    result = assess()
    assert result.result_available
    assert result.result == row  # subsequent observation parser MUST validate it


@pytest.mark.parametrize("field,value", [("protocol", "kir-revit-connector/3"),
    ("request_id", str(uuid4())), ("session_id", str(uuid4())), ("target", None),
    ("ok", 1), ("status", "other"), ("error", "failure"), ("context", {})])
def test_wrong_route_cannot_supply_query_result(case, field, value):
    _, _, response, assess = case
    response[field] = value
    result = assess()
    assert not result.result_available and result.result is None and result.precondition is None


@pytest.mark.parametrize("field,value", [("operation_id", str(uuid4())), ("source_sha256", "f" * 64),
    ("document_key", "other-document"), ("target", None)])
def test_wrong_original_binding_cannot_supply_query_result(case, field, value):
    _, _, response, assess = case
    response["receipt"][field] = value
    result = assess()
    assert not result.result_available and not result.binding_matches


@pytest.mark.parametrize("value", [18, 17.0, True, None])
def test_newer_or_malformed_revision_cannot_relabel_original_observation(case, value):
    _, _, response, assess = case
    response["receipt"]["precondition"]["revision"] = value
    assert not assess().result_available


@pytest.mark.parametrize("field,value", [("added", [700]), ("modified", [700]), ("deleted", [700]),
    ("transaction_names", ["empty transaction"]), ("truncated", True)])
def test_any_change_or_incomplete_manifest_prevents_revision_bound_read(case, field, value):
    _, _, response, assess = case
    response["receipt"]["changes"][field] = value
    if field in ("added", "modified", "deleted"):
        response["receipt"]["transaction_evidence"] = "changes_observed"
    result = assess()
    assert result.binding_matches and not result.result_available
    assert result.diagnostic_code == "query_changes_unconfirmed"
    assert result.receipt["changes"][field] == value


@pytest.mark.parametrize("field,value", [("state", "running_unknown"), ("started", False),
    ("may_retry", True), ("result_truncated", True), ("result_error", "failed"),
    ("error", "failed"), ("semantic_evidence", "verified"), ("transaction_evidence", "not_observed"),
    ("changes", None), ("timestamp_utc", "")])
def test_incomplete_or_contradictory_receipt_does_not_supply_observation(case, field, value):
    _, _, response, assess = case
    response["receipt"][field] = value
    assert not assess().result_available


@pytest.mark.parametrize("wire", ['null', '[]', '"hello"', '{"x":1,"x":2}', '{"x":NaN}', '{"x":"\\ud800"}'])
def test_invalid_inner_query_json_is_not_an_observation(case, wire):
    _, _, response, assess = case
    response["receipt"]["result_json"] = wire
    assert not assess().result_available


def test_before_start_is_named_without_a_write_commit_or_read_result(case):
    _, _, response, assess = case
    response["receipt"].update(state="context_changed_before_start", started=False, may_retry=True,
        result_json=None, changes=None, transaction_evidence="not_observed", error="context changed")
    result = assess()
    assert result.binding_matches and result.diagnostic_code == "not_started"
    assert not result.result_available and result.precondition is None


def test_read_and_write_adapters_cannot_be_substituted(case):
    query, credentials, response, assess = case
    write = prepare_execution({"ops": [{"op": "create_level", "id": "L", "elev_mm": 0}]},
        target=query.target, precondition=query.precondition, operation_id=query.operation_id)
    assert assess(artifact=write).diagnostic_code == "query_plan_required"
    result = assess_connector_write_response(query, json.dumps(response), credentials=credentials,
                                             request_id=response["request_id"])
    assert not result.ok and result.diagnostic_code == "write_plan_required"


def test_unknown_fields_and_duplicate_outer_keys_are_refused(case):
    _, _, response, assess = case
    copy = deepcopy(response)
    copy["receipt"]["invented_freshness"] = True
    assert not assess(copy).result_available
    wire = json.dumps(response)
    assert not assess(wire=wire[:-1] + ',"receipt":null}').result_available
