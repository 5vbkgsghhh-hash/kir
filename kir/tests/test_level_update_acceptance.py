"""Pure post-update field/manifest assessment, with synthetic native evidence.

The archive fixture uses the actual codec in memory, not a filesystem stand-in
claimed as durable storage. No geometry/native execution or file creation.
"""
from copy import deepcopy
from pathlib import PurePosixPath
from unittest.mock import patch
from uuid import uuid4
import json

import pytest

from kir.level_update_acceptance import assess_level_update, _fields
from kir.revit_connector import ContextPrecondition, prepare_execution
from kir.revit_level_update import LevelUpdateRefusal, prepare_level_update
from kir.revit_observation import prepare_element_observation, parse_element_observation
from kir.revit_observation import ObservationRefusal
from kir.saved_execution import SavedExecutionRecord, _capture
from kir.tests.test_revit_level_update import make_case, bind, observation, plan, response_for
from kir.tests.test_revit_observation import unavailable


def memory_case():
    records = {}
    def create(path, prepared, submission):
        record = SavedExecutionRecord._from_bytes(_capture(prepared, submission=submission))
        records[str(path)] = record
        return record
    with patch.object(SavedExecutionRecord, "create_project_new", side_effect=create), \
         patch.object(SavedExecutionRecord, "load", side_effect=lambda path: records[str(path)]):
        source = make_case(PurePosixPath("/not-created"))
    original = bind(source)
    before = observation(source, original)
    update = plan(source, original, before)
    prepared = prepare_level_update(update, operation_id=str(uuid4()))
    op = prepared.planned.to_ops()[0]
    receipt = response_for(prepared, source["credentials"], {"ok": True, op["id"]: {
        "id": str(op["target"]["value"]), "param": op["param"], "value": "localized display is not parsed"}},
        changes={"added": [], "modified": [op["target"]["value"]], "deleted": [],
                 "transaction_names": ["synthetic setter"], "truncated": False})
    rows = before.rows
    target_uid = update.to_dict()["target_identity"]["unique_id"]
    level = rows[target_uid]["level"]
    level.update(project_elevation_mm=3800.0, reported_elevation_mm=3800.0)
    level["elevation_parameter"]["value_internal_feet"] = 3800.0 / 304.8
    return source, update, prepared, receipt, rows


def assess(case, *, mutate_rows=None, mutate_receipt=None, revision=10, document="native-doc", prepared_override=None):
    source, update, prepared, receipt, rows = case
    rows, receipt = deepcopy(rows), deepcopy(receipt)
    if mutate_rows:
        mutate_rows(rows)
    if mutate_receipt:
        mutate_receipt(receipt)
    query = prepare_element_observation(list(rows), target=update.target,
        precondition=ContextPrecondition(document, revision), operation_id=str(uuid4()))
    payload = {op.op_id: rows[op.to_dict()["unique_id"]] for op in query.planned.ops}
    response = response_for(query, source["credentials"], payload, changes={"added": [], "modified": [], "deleted": [],
        "transaction_names": [], "truncated": False})
    after = parse_element_observation(query, json.dumps(response), credentials=source["credentials"],
                                      request_id=response["request_id"])
    return assess_level_update(update, prepared_override or prepared, json.dumps(receipt),
        credentials=source["credentials"], request_id=receipt["request_id"], after=after)


def test_matching_field_and_manifest_scope_is_not_geometry_or_engineering_acceptance():
    result = assess(memory_case())
    assert result.scope_satisfied and result.target_satisfied
    report = result.to_dict()
    assert report["execution"]["execution"] == "committed"
    assert report["not_evaluated"] == ["dependent_geometry", "protected_geometry", "engineering"]
    assert report["may_retry"] is False


@pytest.mark.parametrize("field", ["project_elevation_mm", "reported_elevation_mm", "parameter"])
def test_wrong_after_value_does_not_relabel_commit_as_rollback(field):
    case = memory_case()
    uid = case[1].to_dict()["target_identity"]["unique_id"]
    def corrupt(rows):
        level = rows[uid]["level"]
        if field == "parameter": level["elevation_parameter"]["value_internal_feet"] = 3000 / 304.8
        else: level[field] = 3000
    result = assess(case, mutate_rows=corrupt)
    assert not result.scope_satisfied and not result.target_satisfied
    assert result.to_dict()["checks"]["target_elevation"]["status"] == "violated"
    assert result.to_dict()["execution"]["execution"] == "committed"


@pytest.mark.parametrize("fault", ["renamed", "missing", "unavailable", "manifest", "truncated", "remapped"])
def test_protected_scope_never_passes_from_missing_or_incomplete_evidence(fault):
    case = memory_case()
    target_uid = case[1].to_dict()["target_identity"]["unique_id"]
    protected_uid = next(uid for uid in case[4] if uid != target_uid)
    protected_id = case[4][protected_uid]["element_identity"]["element_id"]
    def change_rows(rows):
        row = rows[protected_uid]
        if fault == "renamed": row["name"] = "different"
        if fault in {"missing", "unavailable"}:
            row.update(status="not_found" if fault == "missing" else "unavailable",
                reason=None if fault == "missing" else "lookup_failed", name=None, category_id=None, is_level=None,
                type_state=None, level_status="not_evaluated", level_reason=None, level=None, **unavailable())
        if fault == "remapped": row["element_identity"]["element_id"] = 8001
    def change_receipt(response):
        if fault == "manifest": response["receipt"]["changes"]["modified"].append(protected_id)
        if fault == "truncated": response["receipt"]["changes"]["truncated"] = True
    result = assess(case, mutate_rows=change_rows, mutate_receipt=change_receipt)
    assert not result.scope_satisfied and result.target_satisfied
    assert result.to_dict()["execution"]["execution"] == "committed"


@pytest.mark.parametrize("revision,document", [(9, "native-doc"), (8, "native-doc"), (10, "foreign-doc")])
def test_wrong_after_revision_or_document_is_not_evaluated(revision, document):
    result = assess(memory_case(), revision=revision, document=document)
    assert not result.scope_satisfied
    assert result.to_dict()["checks"]["target_elevation"]["status"] == "not_evaluated"


def test_wrong_returned_target_and_unknown_execution_cannot_be_overruled_by_after_value():
    case = memory_case()
    def wrong_target(response):
        payload = json.loads(response["receipt"]["result_json"])
        payload["update_level_elevation"]["id"] = "999"
        response["receipt"]["result_json"] = json.dumps(payload)
    result = assess(case, mutate_receipt=wrong_target)
    assert not result.target_satisfied and result.to_dict()["execution"]["execution"] == "committed"
    def unknown(response): response["receipt"]["state"] = "running_unknown"
    result = assess(case, mutate_receipt=unknown)
    assert not result.scope_satisfied
    assert all(row["status"] == "not_evaluated" for row in result.to_dict()["checks"].values())


def test_preparation_without_guards_is_refused_before_interpreting_after_state():
    case = memory_case()
    update, original = case[1:3]
    unguarded = prepare_execution(update.planned, target=update.target, precondition=update.precondition,
                                  operation_id=original.operation_id)
    with pytest.raises(LevelUpdateRefusal, match="update_preparation_mismatch"):
        assess(case, prepared_override=unguarded)


def test_missing_before_level_fields_are_not_a_changed_field_baseline():
    from kir.tests.test_revit_observation import row
    before = row()
    before.update(level_status="unavailable", level_reason="level_parameters_unavailable", level=None)
    assert _fields(before) is None
    assert _fields(row()) is not None


def test_target_deletion_marker_contradicts_an_ordinary_successful_setter_result():
    case = memory_case()
    target_id = case[1].to_dict()["target_identity"]["element_id"]
    def deleted(response): response["receipt"]["changes"]["deleted"].append(target_id)
    result = assess(case, mutate_receipt=deleted)
    assert not result.target_satisfied and not result.scope_satisfied
    assert result.to_dict()["execution"]["execution"] == "committed"


def test_observed_level_cannot_satisfy_acceptance_while_claiming_no_type():
    case = memory_case()
    uid = case[1].to_dict()["target_identity"]["unique_id"]
    def no_type(rows): rows[uid]["type_state"] = {"status": "none", **unavailable()}
    with pytest.raises(ObservationRefusal, match="level_type_state_contradiction"):
        assess(case, mutate_rows=no_type)
