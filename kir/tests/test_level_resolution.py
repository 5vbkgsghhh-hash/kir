"""Qualification of synthetic bound native not-started receipts; no dispatch."""
from copy import deepcopy
import json
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir.level_resolution import (QualifiedLevelNotStarted, LevelResolutionRefusal,
    qualify_level_not_started, validate_level_not_started_claims)
from kir.project import _hash
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.tests.test_update_submission_memory import record_values


def before_start_response(case, state="context_changed_before_start"):
    response = deepcopy(case[3])
    response["receipt"].update(state=state, started=False, may_retry=True,
        transaction_evidence="not_observed", changes=None, result_json=None,
        result_error=None, result_truncated=False, error="synthetic before-start refusal")
    return response


def resolution_case(state="context_changed_before_start"):
    case, _, record = record_values()
    response = before_start_response(case, state)
    resolved = qualify_level_not_started(record, json.dumps(response), credentials=case[0]["credentials"],
                                        request_id=response["request_id"])
    return case, record, response, resolved


@pytest.mark.parametrize("state", ["rejected_before_start", "context_changed_before_start", "cancelled_before_start"])
def test_only_qualified_before_start_evidence_is_available_for_store_resolution(state):
    case, record, response, resolved = resolution_case(state)
    data = resolved.to_dict()
    assert data["execution"] == record.binding_dict() and data["archive_digest"] == record.digest
    assert data["response"] == response and data["receipt_digest"] == _hash(response["receipt"])
    assert data["claims"] == {"scope": "bound_native_not_started", "checkpoint_advance": "none", "retry_permission": "none"}
    with patch("kir.compiler.compile_program", side_effect=AssertionError("no compile")), \
         patch("kir.compiler.plan_program", side_effect=AssertionError("no plan")), \
         patch("kir.revit_connector.prepare_execution", side_effect=AssertionError("no preparation")):
        assert validate_level_not_started_claims(data, record) is None
        assert qualify_level_not_started(record, json.dumps(response), credentials=case[0]["credentials"],
            request_id=response["request_id"]).digest == resolved.digest
    assert case[0]["credentials"].token not in json.dumps(data)
    assert not any(hasattr(resolved, name) for name in ("planned", "execute_request", "may_retry"))
    with pytest.raises(TypeError): QualifiedLevelNotStarted()
    data["response"]["receipt"]["state"] = "changed"
    assert resolved.to_dict()["response"] == response


@pytest.mark.parametrize("where,field,value", [
    ("receipt", "state", "running_unknown"), ("receipt", "state", "invocation_completed"),
    ("receipt", "state", "failed_after_start_unknown"), ("receipt", "started", True),
    ("receipt", "may_retry", False), ("receipt", "may_retry", 1),
    ("receipt", "changes", {"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False}),
    ("receipt", "transaction_evidence", "changes_not_observed"),
    ("receipt", "result_json", "{}"), ("receipt", "result_error", "unavailable"),
    ("receipt", "result_truncated", True), ("receipt", "semantic_evidence", "verified"),
    ("receipt", "operation_id", str(uuid4())), ("receipt", "source_sha256", "e" * 64),
    ("receipt", "document_key", "other-doc"), ("receipt", "precondition", None),
    ("route", "receipt", None), ("route", "ok", False), ("route", "status", "timeout"),
    ("route", "error", "timeout"), ("route", "session_id", str(uuid4())),
    ("route", "request_id", str(uuid4())),
])
def test_absence_unknown_partial_or_foreign_evidence_never_releases_pending(where, field, value):
    case, _, record = record_values()
    response = before_start_response(case)
    request_id = response["request_id"]
    (response["receipt"] if where == "receipt" else response)[field] = value
    with pytest.raises(LevelResolutionRefusal, match="bound_not_started_required"):
        qualify_level_not_started(record, json.dumps(response), credentials=case[0]["credentials"], request_id=request_id)


def test_recovery_route_is_distinct_from_original_operation_binding():
    case, _, record = record_values()
    response = before_start_response(case)
    other = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2023"), str(uuid4()), "synthetic-B")
    response.update(target=other.target.to_dict(), session_id=other.session_id)
    resolved = qualify_level_not_started(record, json.dumps(response), credentials=other,
        request_id=response["request_id"], recovery=True)
    assert resolved.to_dict()["execution"]["target"] == case[0]["credentials"].target.to_dict()
    assert resolved.to_dict()["response"]["target"] == other.target.to_dict()
    response["receipt"]["target"] = other.target.to_dict()
    with pytest.raises(LevelResolutionRefusal, match="bound_not_started_required"):
        qualify_level_not_started(record, json.dumps(response), credentials=other,
            request_id=response["request_id"], recovery=True)


@pytest.mark.parametrize("fault", ["digest", "archive", "project", "base", "proposed", "receipt_id",
    "started", "result", "changes", "new_checkpoint", "retry", "credentials", "protocol"])
def test_inert_validator_rejects_rehashed_cross_relation_and_authority_changes(fault):
    _, record, _, resolved = resolution_case()
    data = resolved.to_dict()
    if fault == "archive": data["archive_digest"] = "c" * 64
    if fault == "project": data["project_id"] = "foreign"
    if fault == "base": data["base_revision"] = "c" * 64
    if fault == "proposed": data["proposed_revision"] = "c" * 64
    if fault == "receipt_id": data["response"]["receipt"]["operation_id"] = str(uuid4())
    if fault == "started": data["response"]["receipt"]["started"] = True
    if fault == "result": data["response"]["receipt"]["result_json"] = "{}"
    if fault == "changes": data["response"]["receipt"]["changes"] = {}
    if fault == "new_checkpoint": data["claims"]["checkpoint_advance"] = "proposed_revision"
    if fault == "retry": data["claims"]["retry_permission"] = "safe"
    if fault == "credentials": data["response"]["token"] = "not-permitted"
    if fault == "protocol": data["response"]["protocol"] = "kir-revit-connector/3"
    data["receipt_digest"] = _hash(data["response"]["receipt"])
    data["resolution_digest"] = _hash({k: v for k, v in data.items() if k != "resolution_digest"})
    if fault == "digest": data["resolution_digest"] = "0" * 64
    with pytest.raises(LevelResolutionRefusal):
        validate_level_not_started_claims(data, record)
