"""Update association/Archive3 codec only; no files, durable writes, or Revit."""
from copy import deepcopy
import hashlib
from uuid import uuid4
from unittest.mock import patch

import pytest

from kir.project import _canonical, _hash
from kir.revit_connector import prepare_execution
from kir.saved_execution import SavedExecutionRecord, SavedExecutionError, _capture
from kir.update_submission import bind_level_update_submission, UpdateSubmissionError
from kir.tests.test_level_update_acceptance import memory_case
from kir.tests.test_revit_connector_preparation import prepare as original_fixture


def record_values():
    case = memory_case()
    update, prepared = case[1:3]
    submission = bind_level_update_submission(update, prepared)
    return case, submission, SavedExecutionRecord._from_bytes(_capture(prepared, level_update=submission))


def resign(data):
    original = data["update_submission"]["original_publication"]
    original["binding_digest"] = _hash({k: v for k, v in original.items() if k != "binding_digest"})
    data["update_submission"]["update"]["original_binding_digest"] = original["binding_digest"]
    submission = data["update_submission"]
    submission["submission_digest"] = _hash({k: v for k, v in submission.items() if k != "submission_digest"})
    data["record_digest"] = _hash({k: v for k, v in data.items() if k != "record_digest"})
    return _canonical(data).encode()


def test_archive3_keeps_baseline_and_guards_but_cannot_execute_or_recreate_plan():
    case, submission, record = record_values()
    update, prepared = case[1:3]
    assert record.to_dict()["schema"] == "kir-saved-execution/3"
    assert record.project_submission is None
    assert record.update_submission == submission.to_dict()
    assert record.update_submission["before_observation"]["rows"] == update.before_observation.rows
    assert record.update_submission["expected_identities"] == [proof.to_dict() for proof in prepared.expected_identities]
    with patch("kir.compiler.compile_program", side_effect=AssertionError("no recompile")), \
         patch("kir.compiler.plan_program", side_effect=AssertionError("no replan")):
        loaded = SavedExecutionRecord._from_bytes(record._raw)
    assert loaded.binding_dict() == prepared.binding_dict()
    assert not any(hasattr(loaded, name) for name in ("execute_request", "planned", "to_prepared"))
    loaded.require_matches(prepared, level_update=submission)
    with pytest.raises(SavedExecutionError, match="fresh_update_submission_required"):
        loaded.require_matches(prepared)
    request = loaded.receipt_request(case[0]["credentials"], request_id=str(uuid4()))
    assert request["operation_id"] == prepared.operation_id and "source" not in request
    detached = loaded.update_submission
    detached["expected_identities"].clear()
    assert loaded.update_submission["expected_identities"]


def test_missing_guards_or_changed_precondition_cannot_bind_to_fresh_update():
    case = memory_case()
    update, prepared = case[1:3]
    unguarded = prepare_execution(update.planned, target=update.target, precondition=update.precondition,
                                  operation_id=prepared.operation_id)
    with pytest.raises(UpdateSubmissionError):
        bind_level_update_submission(update, unguarded)


@pytest.mark.parametrize("fault", ["drop_guard", "uid", "drop_row", "revision", "new_value", "original_revision",
    "overclaim", "original_overclaim", "token", "scope", "parameter", "before_shape", "address"])
def test_rehashed_cross_relation_corruption_is_not_accepted(fault):
    _, _, record = record_values()
    data = deepcopy(record.to_dict())
    submission = data["update_submission"]
    before = submission["before_observation"]
    report = submission["update"]
    uid = report["target_identity"]["unique_id"]
    if fault == "drop_guard": submission["expected_identities"].pop()
    if fault == "uid": before["rows"][uid]["element_identity"]["unique_id"] = "another"
    if fault == "drop_row": before["rows"].pop(uid)
    if fault == "revision": before["precondition"]["revision"] += 1
    if fault == "new_value": report["new_elev_mm"] = 9000
    if fault == "original_revision": submission["original_publication"]["project"]["revision_id"] = "f" * 64
    if fault == "overclaim": report["claims"]["native_execution"] = "verified"
    if fault == "original_overclaim": submission["original_publication"]["claims"]["global_ownership"] = "verified"
    if fault == "token": submission["original_publication"]["execution"]["token"] = "must-not-be-retained"
    if fault == "scope": report["protected_output_ids"] = []
    if fault == "parameter": before["rows"][uid]["level"]["elevation_parameter"]["name"] = "different"
    if fault == "before_shape":
        before["precondition"].pop("active_view_id")
        report["observation"]["precondition"].pop("active_view_id")
    if fault == "address": submission["original_publication"]["outputs"][0]["output_key"] = "another-output"
    with pytest.raises(SavedExecutionError):
        SavedExecutionRecord._from_bytes(resign(data))


def test_archive1_bytes_remain_identical_and_cannot_claim_an_unrecorded_update():
    assert hashlib.sha256(_capture(original_fixture())).hexdigest() == "26344194ae90e87be276649e4f9d21c0929fa5a35dfee90742d5023add809f14"
    case, submission, _ = record_values()
    ordinary = SavedExecutionRecord._from_bytes(_capture(case[2]))
    assert ordinary.update_submission is None
    with pytest.raises(SavedExecutionError, match="submission_not_archived"):
        ordinary.require_matches(case[2], level_update=submission)


@pytest.mark.parametrize("field,value", [("target", 901.0), ("target", True), ("id", None), ("id", ""),
                                       ("id", " "), ("value", True), ("value", "3800")])
def test_rehashed_mutation_scalar_types_cannot_use_python_numeric_equality(field, value):
    _, _, record = record_values()
    data = record.to_dict()
    payload = data["plan_evidence"]["ops"][0]["payload"]
    if field == "target": payload["target"]["value"] = value
    elif field == "id": payload["id"] = value
    else: payload["value"]["v"] = value
    plan = data["plan_evidence"]
    plan["plan_digest"] = _hash({k: v for k, v in plan.items() if k != "plan_digest"})
    data["grounded_evidence"] = None
    submission = data["update_submission"]
    submission["plan_digest"] = submission["update"]["mutation_plan_digest"] = plan["plan_digest"]
    with pytest.raises(SavedExecutionError):
        SavedExecutionRecord._from_bytes(resign(data))


@pytest.mark.parametrize("fault", ["nonlevel_target", "float_guard", "float_target_identity"])
def test_retained_target_kind_and_identity_types_match_the_fresh_profile(fault):
    _, _, record = record_values()
    data = record.to_dict()
    submitted = data["update_submission"]
    if fault == "nonlevel_target":
        selected = submitted["update"]["target_output_id"]
        row = next(row for row in submitted["original_publication"]["outputs"] if row["output_id"] == selected)
        row["source_op"] = "create_directshape"
    elif fault == "float_guard":
        submitted["expected_identities"][0]["element_id"] = float(submitted["expected_identities"][0]["element_id"])
    else:
        submitted["update"]["target_identity"]["element_id"] = float(submitted["update"]["target_identity"]["element_id"])
    with pytest.raises(SavedExecutionError):
        SavedExecutionRecord._from_bytes(resign(data))
