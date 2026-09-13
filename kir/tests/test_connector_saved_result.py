"""Read archived execution receipts without recreating compiler authority."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest

from kir import connector_result as results
from kir import revit_connector as native
from kir.geometry_materialization import materialize_project
from kir.project import ModuleDefinition, ModuleInstance, NamedOutput, ProjectRevision
from kir.project_submission import bind_project_submission
from kir.saved_execution import SavedExecutionRecord
from kir.tests.test_connector_result import case as fresh_case


@pytest.fixture(params=(1, 2))
def case(request, tmp_path):
    artifact, credentials, response, _ = fresh_case.__wrapped__()
    path = tmp_path / "source.sqlite"
    if request.param == 1:
        SavedExecutionRecord.create_new(path, artifact)
    else:
        project = ProjectRevision("saved-project", [ModuleDefinition("m")], [ModuleInstance("i", "m", [
            NamedOutput("level", {"op": "create_level", "elev_mm": 0})])])
        materialized = materialize_project(project, {})
        artifact = native.prepare_execution(materialized.planned, target=artifact.target,
            precondition=artifact.precondition, operation_id=artifact.operation_id)
        submission = bind_project_submission(project, materialized, artifact)
        SavedExecutionRecord.create_project_new(path, artifact, submission)
        response["receipt"].update(artifact.binding_dict())
    record = SavedExecutionRecord.load(path)
    request_id = response["request_id"]

    def assess(payload=None, *, auth=credentials, recovery=False):
        return results.assess_connector_saved_write_response(record,
            json.dumps(response if payload is None else payload), credentials=auth,
            request_id=request_id, recovery=recovery)

    return artifact, record, path, credentials, response, assess


def test_loaded_archive_result_requires_no_compiler_or_fresh_artifact(case, monkeypatch):
    import kir.compiler

    artifact, record, path, credentials, response, assess = case
    before = path.read_bytes()
    def forbidden(*args, **kwargs):
        pytest.fail("archived receipt validation invoked compiler/planner")
    monkeypatch.setattr(native, "compile_program", forbidden)
    monkeypatch.setattr(native, "prepare_execution", forbidden)
    monkeypatch.setattr(kir.compiler, "plan_program", forbidden)
    checked = assess()
    assert checked.result_available and checked.binding_matches
    assert checked.archive_digest == record.digest
    assert checked.receipt == response["receipt"]
    assert checked.result == json.loads(response["receipt"]["result_json"])
    assert path.read_bytes() == before
    assert not any(hasattr(checked, name) for name in ("ok", "outcome", "execute_request", "planned"))
    assert credentials.token not in repr(checked) and artifact.source not in repr(checked)
    with pytest.raises(native.ConnectorPreparationError, match="invalid_input"):
        results.assess_connector_write_response(record, json.dumps(response), credentials=credentials,
                                               request_id=response["request_id"])
    with pytest.raises(native.ConnectorPreparationError, match="invalid_input"):
        results.assess_connector_saved_write_response(artifact, json.dumps(response), credentials=credentials,
                                                      request_id=response["request_id"])


@pytest.mark.parametrize("payload", [{}, {"ok": False, "error": "postconditions_violated"},
                                     {"ok": True, "L": {"id": "700"}}])
def test_availability_is_not_commit_or_original_element_ownership(case, payload):
    _, _, _, _, response, assess = case
    response["receipt"]["result_json"] = json.dumps(payload)
    checked = assess()
    assert checked.result_available and checked.result == payload
    assert not hasattr(checked, "original_ownership_verified")


@pytest.mark.parametrize("where,field,value", [
    ("route", "protocol", "kir-revit-connector/3"),
    ("route", "request_id", str(uuid4())), ("route", "session_id", str(uuid4())),
    ("receipt", "operation_id", str(uuid4())), ("receipt", "source_sha256", "a" * 64),
    ("receipt", "document_key", "other-document"), ("receipt", "precondition", None),
    ("receipt", "target", None), ("receipt", "result_truncated", True),
    ("receipt", "result_error", "serialization failed"), ("receipt", "state", "running_unknown"),
])
def test_wrong_or_incomplete_receipt_never_supplies_archived_result(case, where, field, value):
    _, _, _, _, response, assess = case
    (response if where == "route" else response["receipt"])[field] = value
    checked = assess()
    assert not checked.result_available and checked.result is None


def test_rotated_session_and_foreign_recovery_keep_original_archive_binding(case):
    artifact, _, _, credentials, response, assess = case
    rotated = native.SessionCredentials(credentials.target, str(uuid4()), "new-session-token")
    response["session_id"] = rotated.session_id
    assert assess(auth=rotated).result_available
    foreign = native.SessionCredentials(native.RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "B-token")
    response["target"], response["session_id"] = foreign.target.to_dict(), foreign.session_id
    with pytest.raises(native.ConnectorPreparationError, match="target_mismatch"):
        assess(auth=foreign)
    historical = assess(auth=foreign, recovery=True)
    assert historical.result_available
    assert historical.receipt["target"] == artifact.target.to_dict()
    response["receipt"]["target"] = foreign.target.to_dict()
    assert not assess(auth=foreign, recovery=True).result_available


def test_lookup_absence_and_before_start_do_not_authorize_replay(case):
    _, _, _, _, response, assess = case
    absent = deepcopy(response)
    absent.update(ok=False, status="not_found", receipt=None, error=None)
    assert not assess(absent).result_available
    response["receipt"].update(state="context_changed_before_start", started=False, may_retry=True,
        changes=None, transaction_evidence="not_observed", result_json=None, error="changed")
    checked = assess()
    assert not checked.result_available and checked.diagnostic_code == "not_started"
    assert not hasattr(checked, "may_retry")


def test_detached_results_and_incomplete_change_manifest_are_retained_not_qualified(case):
    _, _, _, _, response, assess = case
    response["receipt"]["changes"]["truncated"] = True
    checked = assess()
    assert checked.result_available and checked.receipt["changes"]["truncated"]
    detached = checked.receipt
    detached["changes"]["truncated"] = False
    assert checked.receipt["changes"]["truncated"] is True
    decoded = checked.result
    decoded["ok"] = False
    assert checked.result["ok"] is True


def test_archived_query_cannot_be_reclassified_as_original_write(case, tmp_path):
    artifact, _, _, credentials, response, _ = case
    query = native.prepare_execution({"ops": [{"op": "query_inspect", "id": "Q",
        "target": {"by": "element_id", "value": 700}}]}, target=artifact.target,
        precondition=artifact.precondition, operation_id=artifact.operation_id)
    record = SavedExecutionRecord.create_new(tmp_path / "query.sqlite", query)
    response["receipt"].update(query.binding_dict())
    checked = results.assess_connector_saved_write_response(record, json.dumps(response),
        credentials=credentials, request_id=response["request_id"])
    assert not checked.result_available and checked.diagnostic_code == "write_plan_required"


def test_archived_result_is_publicly_exported():
    namespace = {}
    exec("from kir.connector_result import *", namespace)
    assert namespace["assess_connector_saved_write_response"] is results.assess_connector_saved_write_response
    assert namespace["ConnectorSavedResultAssessment"] is results.ConnectorSavedResultAssessment
