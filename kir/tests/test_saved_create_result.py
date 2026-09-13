"""Retained CREATE D1 shares native binding and the existing outcome algebra."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from kir.bridge_result import saved_create_result_contract, assess_saved_create_result
from kir.connector_result import assess_connector_saved_create_response, assess_connector_saved_write_response
from kir.outcome import ExecutionState, WitnessState
from kir.project import ModuleDefinition, ModuleInstance, ProjectRevision
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.tests.test_revit_level_update import make_case


def project(ops=None):
    return ProjectRevision("saved-create", [ModuleDefinition("m")], [ModuleInstance("section", "m", ops or {
        "first": {"op": "create_level", "elev_mm": 0},
        "second": {"op": "create_level", "elev_mm": 3000}})])


@pytest.fixture
def case(tmp_path):
    return make_case(tmp_path, project=project())


def assess(case, result=None, response=None, *, credentials=None, recovery=False):
    response = deepcopy(case["response"] if response is None else response)
    if result is not None:
        response["receipt"]["result_json"] = json.dumps(result)
    return assess_connector_saved_create_response(case["record"], json.dumps(response),
        credentials=credentials or case["credentials"], request_id=response["request_id"], recovery=recovery)


def test_complete_retained_result_without_compiling_or_replaying_source(case, monkeypatch):
    import kir.compiler
    import kir.revit_connector
    before = case["path"].read_bytes()
    def no_compile(*args, **kwargs):
        pytest.fail("retained result invoked compiler/planner")
    monkeypatch.setattr(kir.compiler, "plan_program", no_compile)
    monkeypatch.setattr(kir.compiler, "compile_program", no_compile)
    monkeypatch.setattr(kir.revit_connector, "prepare_execution", no_compile)
    result = assess(case)
    assert result.ok and result.binding_matches
    assert result.archive_digest == case["record"].digest
    assert result.outcome.execution is ExecutionState.COMMITTED
    assert result.outcome.witness is WitnessState.SATISFIED
    assert case["path"].read_bytes() == before


@pytest.mark.parametrize("mode", ["missing", "refused", "no_id", "violated"])
def test_committed_partial_result_is_retained_not_relabelled_rollback(case, mode):
    result = deepcopy(case["result"])
    last = case["prepared"].planned.ops[-1].op_id
    if mode == "missing": result.pop(last)
    if mode == "refused": result[last] = {"refused": "controlled operation failure"}
    if mode == "no_id": result[last] = {"name": "not an identity"}
    if mode == "violated": result["postcondition_violations"] = [last + ": controlled drift"]
    checked = assess(case, result)
    assert not checked.ok and checked.binding_matches
    assert checked.outcome.execution is ExecutionState.COMMITTED
    assert checked.outcome.witness is (WitnessState.VIOLATED if mode == "violated" else WitnessState.INCOMPLETE)
    assert json.loads(checked.receipt["result_json"]) == result


def test_availability_is_not_a_complete_create_result(case):
    response = deepcopy(case["response"])
    response["receipt"]["result_json"] = "{}"
    available = assess_connector_saved_write_response(case["record"], json.dumps(response),
        credentials=case["credentials"], request_id=response["request_id"])
    assert available.result_available
    checked = assess(case, response=response)
    assert not checked.ok and checked.outcome.execution is ExecutionState.UNCONFIRMED


def test_explicit_rollback_still_needs_consistent_native_change_manifest(case):
    response = deepcopy(case["response"])
    response["receipt"]["result_json"] = json.dumps({"commit_status": "RolledBack", "error": "controlled"})
    assert assess(case, response=response).diagnostic_code == "rollback_scope_unconfirmed"
    response["receipt"]["changes"].update(added=[], modified=[], deleted=[], transaction_names=[])
    response["receipt"]["transaction_evidence"] = "changes_not_observed"
    assert assess(case, response=response).outcome.execution is ExecutionState.ROLLED_BACK


def test_original_target_stays_bound_during_recovery_through_another_runtime(case):
    response = deepcopy(case["response"])
    other = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "other-token")
    response.update(target=other.target.to_dict(), session_id=other.session_id)
    checked = assess(case, response=response, credentials=other, recovery=True)
    assert checked.ok and checked.receipt["target"] == case["prepared"].target.to_dict()
    response["receipt"]["target"] = other.target.to_dict()
    assert not assess(case, response=response, credentials=other, recovery=True).binding_matches


@pytest.mark.parametrize("field,value", [("operation_id", str(uuid4())), ("source_sha256", "a" * 64),
                                         ("document_key", "other-document")])
def test_foreign_original_receipt_does_not_become_create_evidence(case, field, value):
    response = deepcopy(case["response"])
    response["receipt"][field] = value
    checked = assess(case, response=response)
    assert not checked.binding_matches and not checked.ok


@pytest.mark.parametrize("op", [
    {"op": "set_param", "target": {"by": "element_id", "value": 777}, "param": "Comments", "value": "changed"},
    {"op": "stack", "levels": 2, "floor": [{"op": "create_wall", "id": "W", "p0_mm": [0, 0], "p1_mm": [5000, 0]}]},
])
def test_mutation_or_macro_is_not_silently_relabelled_flat_create(tmp_path, op):
    data = make_case(tmp_path, project=project({"output": op}))
    with pytest.raises(ValueError, match="CREATE|unsupported"):
        saved_create_result_contract(data["record"])
    checked = assess_saved_create_result(data["result"], data["record"])
    assert checked.diagnostic["code"] == "unsupported_saved_create_profile"
    assert checked.outcome.execution is ExecutionState.UNCONFIRMED
