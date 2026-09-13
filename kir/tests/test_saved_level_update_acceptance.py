"""Recovered Level update assessment; synthetic native receipts and after-reads."""
from copy import deepcopy
import json
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

import pytest

from kir.bridge_result import assess_write_result, expected_results
from kir.connector_result import (assess_connector_saved_level_update_response,
    assess_connector_saved_write_response, assess_connector_write_response)
from kir.level_update_acceptance import assess_level_update, assess_saved_level_update
from kir.project import _hash
from kir.revit_connector import ContextPrecondition, RuntimeTarget, SessionCredentials
from kir.revit_observation import prepare_element_observation, parse_element_observation
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_revit_level_update import response_for
from kir.tests.test_update_submission_memory import record_values, resign


def after_read(case, *, credentials=None, revision=10, document="native-doc", rows=None):
    credentials = credentials or case[0]["credentials"]
    rows = deepcopy(case[4] if rows is None else rows)
    query = prepare_element_observation(sorted(rows), target=credentials.target,
        precondition=ContextPrecondition(document, revision), operation_id=str(uuid4()))
    response = response_for(query, credentials,
        {op.op_id: rows[op.to_dict()["unique_id"]] for op in query.planned.ops},
        changes={"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False})
    parsed = parse_element_observation(query, json.dumps(response), credentials=credentials,
                                      request_id=response["request_id"])
    return parsed, query, response


def checked(record, case, response=None, **kwargs):
    response = case[3] if response is None else response
    return assess_connector_saved_level_update_response(record, json.dumps(response),
        credentials=case[0]["credentials"], request_id=response["request_id"], **kwargs)


def test_same_classifier_and_field_checks_with_explicit_retained_evidence_origin():
    case, _, record = record_values()
    after, _, _ = after_read(case)
    auth, request_id = case[0]["credentials"], case[3]["request_id"]
    fresh = assess_level_update(case[1], case[2], json.dumps(case[3]), credentials=auth,
                               request_id=request_id, after=after)
    with patch("kir.compiler.compile_program", side_effect=AssertionError("no compile")), \
         patch("kir.compiler.plan_program", side_effect=AssertionError("no plan")), \
         patch("kir.revit_connector.prepare_execution", side_effect=AssertionError("no preparation")):
        saved = assess_saved_level_update(record, json.dumps(case[3]), credentials=auth,
                                         request_id=request_id, after=after)
    assert saved.scope_satisfied and saved.target_satisfied
    report = saved.to_dict()
    assert report["checks"] == fresh.to_dict()["checks"]
    assert report["execution"] == fresh.to_dict()["execution"]
    assert report["schema"] == "kir-saved-level-update-acceptance/1"
    assert report["archive_digest"] == record.digest
    assert report["baseline_evidence"] == "retained_archive_claims"
    assert report["project_revision_promoted"] is False and report["may_retry"] is False
    assert report["not_evaluated"] == ["dependent_geometry", "protected_geometry", "engineering"]
    assert checked(record, case).archive_digest == record.digest
    assert not any(hasattr(record, name) for name in ("planned", "execute_request", "to_prepared"))
    with pytest.raises(ValueError):
        expected_results(record)
    assert not assess_write_result({"ok": True}, record).ok


@pytest.mark.parametrize("fault", ["empty", "missing_identity", "no_ok", "violation", "malformed_violation",
    "contradictory_status", "rollback", "rollback_changes", "rollback_truncated", "unknown", "missing_receipt",
    "foreign_source", "foreign_route", "truncated_result", "wrong_parameter", "wrong_element"])
def test_saved_and_fresh_native_d1_outcomes_match_including_rollback_scope(fault):
    case, _, record = record_values()
    response = deepcopy(case[3])
    receipt = response["receipt"]
    result = json.loads(receipt["result_json"])
    oid = case[2].planned.to_ops()[0]["id"]
    if fault == "empty": result = {}
    if fault == "missing_identity": result[oid].pop("id")
    if fault == "no_ok": result.pop("ok")
    if fault == "violation": result["postcondition_violations"] = ["wrong elevation"]
    if fault == "malformed_violation": result["postcondition_violations"] = [None]
    if fault == "contradictory_status": result["commit_status"] = "RolledBack"
    if fault.startswith("rollback"):
        result = {"ok": False, "commit_status": "RolledBack", "error": "synthetic failure"}
        if fault != "rollback_changes":
            receipt["changes"]["modified"] = []
            receipt["transaction_evidence"] = "changes_not_observed"
        if fault == "rollback_truncated": receipt["changes"]["truncated"] = True
    if fault == "unknown": receipt["state"] = "running_unknown"
    if fault == "missing_receipt": response["receipt"] = None
    if fault == "foreign_source": receipt["source_sha256"] = "a" * 64
    if fault == "foreign_route": response["session_id"] = str(uuid4())
    if fault == "truncated_result": receipt["result_truncated"] = True
    if fault == "wrong_parameter": result[oid]["param"] = "Other parameter"
    if fault == "wrong_element": result[oid]["id"] = "999"
    receipt["result_json"] = json.dumps(result)
    saved = checked(record, case, response)
    fresh = assess_connector_write_response(case[2], json.dumps(response), credentials=case[0]["credentials"],
                                           request_id=response["request_id"])
    assert saved.outcome == fresh.outcome and saved.ok == fresh.ok
    assert saved.diagnostic_code == fresh.diagnostic_code
    assert saved.archive_digest == record.digest and fresh.archive_digest is None
    after, _, _ = after_read(case)
    accepted = assess_saved_level_update(record, json.dumps(response), credentials=case[0]["credentials"],
        request_id=response["request_id"], after=after)
    assert not accepted.target_satisfied
    if fault in {"rollback_changes", "rollback_truncated"}:
        assert saved.diagnostic_code == "rollback_scope_unconfirmed"
    if fault in {"wrong_parameter", "wrong_element"}:
        assert saved.ok  # D1 identity presence alone is not intended-target acceptance.
        assert accepted.to_dict()["checks"]["execution_target"]["status"] == "violated"


def changed_profile(record, fault):
    data = record.to_dict()
    plan = data["plan_evidence"]
    op = plan["ops"][0]
    report = data["update_submission"]["update"]
    if fault == "ir": plan["ir_version"] = "historical-other-version"
    if fault == "result": op["result"]["identity_cardinality"] = "none"
    if fault == "family": op["family"] = "query"
    if fault == "effect": op["effect"] = "read"
    if fault == "contract": op["contract_digest"] = "b" * 64
    if fault == "nested": op["nested_contracts"] = [{}]
    if fault == "macro": op["provenance"]["macro_name"] = "unrecognized"
    if fault == "source_count": plan["source_op_count"] = 2
    if fault == "bulk": plan["bulk"] = True
    if fault == "destructive": plan["allow_destructive"] = True
    if fault == "setter_tolerance": report["setter_tolerance_mm"] = 1000
    if fault == "baseline_tolerance": report["baseline_tolerance_mm"] = 1000
    if fault == "reserved_id":
        op["payload"]["id"] = op["provenance"]["source_id"] = "ok"
    plan["plan_digest"] = _hash({k: v for k, v in plan.items() if k != "plan_digest"})
    data["grounded_evidence"] = None
    data["update_submission"]["plan_digest"] = report["mutation_plan_digest"] = plan["plan_digest"]
    return SavedExecutionRecord._from_bytes(resign(data))


@pytest.mark.parametrize("fault", ["ir", "result", "family", "effect", "contract", "nested", "macro",
    "source_count", "bulk", "destructive", "setter_tolerance", "baseline_tolerance", "reserved_id"])
def test_readable_rehashed_archive_is_not_automatically_a_supported_result_profile(fault):
    case, _, record = record_values()
    changed = changed_profile(record, fault)
    available = assess_connector_saved_write_response(changed, json.dumps(case[3]), credentials=case[0]["credentials"],
                                                     request_id=case[3]["request_id"])
    assert available.result_available  # old claims remain inspectable
    result = checked(changed, case)
    assert not result.ok and result.outcome.execution.value == "unconfirmed"
    assert result.diagnostic_code == "unsupported_saved_update_profile"
    after, _, _ = after_read(case)
    accepted = assess_saved_level_update(changed, json.dumps(case[3]), credentials=case[0]["credentials"],
        request_id=case[3]["request_id"], after=after)
    assert not accepted.scope_satisfied
    assert all(row["status"] == "not_evaluated" for row in accepted.to_dict()["checks"].values())


def test_recovery_route_does_not_rebind_after_observation_to_another_revit_process():
    case, _, record = record_values()
    other = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "synthetic-B")
    response = deepcopy(case[3])
    response.update(target=other.target.to_dict(), session_id=other.session_id)
    after, _, _ = after_read(case, credentials=other)
    recovered = assess_saved_level_update(record, json.dumps(response), credentials=other,
        request_id=response["request_id"], after=after, recovery=True)
    assert recovered.to_dict()["execution"]["execution"] == "committed"
    assert not recovered.scope_satisfied and not recovered.target_satisfied
    for key in ("target_elevation", "protected_fields", "protected_changes"):
        assert recovered.to_dict()["checks"][key]["reason"] == "after_scope_or_revision_mismatch"


def test_target_uid_with_remapped_numeric_address_does_not_prove_the_receipted_update():
    case, _, record = record_values()
    rows = deepcopy(case[4])
    uid = case[1].to_dict()["target_identity"]["unique_id"]
    rows[uid]["element_identity"]["element_id"] = 8001
    after, _, _ = after_read(case, rows=rows)
    kwargs = dict(credentials=case[0]["credentials"], request_id=case[3]["request_id"], after=after)
    fresh = assess_level_update(case[1], case[2], json.dumps(case[3]), **kwargs)
    saved = assess_saved_level_update(record, json.dumps(case[3]), **kwargs)
    assert not any(result.target_satisfied or result.scope_satisfied for result in (fresh, saved))
    for result in (fresh, saved):
        assert result.to_dict()["execution"]["execution"] == "committed"
        assert result.to_dict()["checks"]["target_elevation"] == {
            "status": "not_evaluated", "reason": "target_identity_address_changed"}


@pytest.mark.parametrize("field,value", [("error", "failed"), ("commit_status", "RolledBack"),
                                        ("ok", False), ("state", "running_unknown")])
def test_per_operation_failure_controls_cannot_hide_behind_a_correct_target(field, value):
    case, _, record = record_values()
    response = deepcopy(case[3])
    payload = json.loads(response["receipt"]["result_json"])
    payload[case[2].planned.to_ops()[0]["id"]][field] = value
    response["receipt"]["result_json"] = json.dumps(payload)
    after, _, _ = after_read(case)
    kwargs = dict(credentials=case[0]["credentials"], request_id=response["request_id"], after=after)
    fresh = assess_level_update(case[1], case[2], json.dumps(response), **kwargs)
    saved = assess_saved_level_update(record, json.dumps(response), **kwargs)
    assert not any(result.target_satisfied or result.scope_satisfied for result in (fresh, saved))
    for result in (fresh, saved):
        assert result.to_dict()["execution"]["execution"] == "committed"
        assert result.to_dict()["checks"]["execution_target"]["status"] == "violated"


def test_a_new_version_guid_after_a_legitimate_set_is_not_an_identity_mismatch():
    case, _, record = record_values()
    rows = deepcopy(case[4])
    uid = case[1].to_dict()["target_identity"]["unique_id"]
    rows[uid]["element_identity"]["version_guid"] = "e" * 32
    after, _, _ = after_read(case, rows=rows)
    result = assess_saved_level_update(record, json.dumps(case[3]), credentials=case[0]["credentials"],
        request_id=case[3]["request_id"], after=after)
    assert result.scope_satisfied


@pytest.mark.parametrize("fault", ["wrong_value", "protected_name", "protected_missing", "truncated_changes"])
def test_saved_scope_never_erases_bad_after_evidence(fault):
    case, _, record = record_values()
    uid = case[1].to_dict()["target_identity"]["unique_id"]
    rows, response = deepcopy(case[4]), deepcopy(case[3])
    protected = next(key for key in rows if key != uid)
    if fault == "wrong_value": rows[uid]["level"]["project_elevation_mm"] = 9999
    if fault == "protected_name": rows[protected]["name"] = "Changed"
    if fault == "protected_missing": rows.pop(protected)
    if fault == "truncated_changes": response["receipt"]["changes"]["truncated"] = True
    after, _, _ = after_read(case, rows=rows)
    result = assess_saved_level_update(record, json.dumps(response), credentials=case[0]["credentials"],
        request_id=response["request_id"], after=after)
    assert not result.scope_satisfied and result.to_dict()["execution"]["execution"] == "committed"


def test_real_archive_after_python_restart_is_assessed_without_recreating_write_plan(tmp_path):
    case, submission, _ = record_values()
    path = tmp_path / "recover.sqlite"
    record = SavedExecutionRecord.create_update_new(path, case[2], submission)
    _, query, response = after_read(case)
    auth = case[0]["credentials"]
    payload = {"credentials": {"target": auth.target.to_dict(), "session_id": auth.session_id, "token": auth.token},
        "execution_response": case[3], "query_response": response,
        "query_operation_id": query.operation_id, "query_precondition": query.precondition.to_dict()}
    script = r'''
import json, sys
from unittest.mock import patch
from kir.revit_connector import RuntimeTarget, SessionCredentials, ContextPrecondition
from kir.revit_observation import prepare_element_observation, parse_element_observation
from kir.saved_execution import SavedExecutionRecord
from kir.level_update_acceptance import assess_saved_level_update
payload = json.load(sys.stdin)
auth = payload["credentials"]
credentials = SessionCredentials(RuntimeTarget(**auth["target"]), auth["session_id"], auth["token"])
record = SavedExecutionRecord.load(sys.argv[1])
# A NEW query is legitimate; only the historical WRITE must never be rebuilt.
query = prepare_element_observation(sorted(record.update_submission["before_observation"]["rows"]),
    target=credentials.target, precondition=ContextPrecondition(**payload["query_precondition"]),
    operation_id=payload["query_operation_id"])
response = payload["query_response"]
after = parse_element_observation(query, json.dumps(response), credentials=credentials, request_id=response["request_id"])
with patch("kir.compiler.compile_program", side_effect=AssertionError("no compile")), \
     patch("kir.compiler.plan_program", side_effect=AssertionError("no plan")), \
     patch("kir.revit_connector.prepare_execution", side_effect=AssertionError("no preparation")):
    execution = payload["execution_response"]
    assessed = assess_saved_level_update(record, json.dumps(execution), credentials=credentials,
        request_id=execution["request_id"], after=after)
print(json.dumps(assessed.to_dict()))
'''
    before = path.read_bytes(), path.stat().st_mtime_ns
    child = subprocess.run([sys.executable, "-B", "-c", script, str(path)], input=json.dumps(payload),
                           capture_output=True, text=True, timeout=60)
    assert child.returncode == 0, child.stderr
    report = json.loads(child.stdout)
    assert report["archive_digest"] == record.digest
    assert all(row["status"] == "satisfied" for row in report["checks"].values())
    assert report["project_revision_promoted"] is False
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert {p.name for p in tmp_path.iterdir()} == {path.name}
