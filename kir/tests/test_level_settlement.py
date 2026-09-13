"""Fresh settlement qualification and inert retained-data validation."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from kir.level_settlement import (QualifiedLevelSettlement, LevelSettlementRefusal,
    qualify_level_settlement, validate_level_settlement_claims)
from kir.project import _hash
from kir.tests.test_saved_level_update_acceptance import after_read
from kir.tests.test_update_submission_memory import record_values


def qualified_case():
    case, _, record = record_values()
    after, _, _ = after_read(case)
    qualified = qualify_level_settlement(record, json.dumps(case[3]), after=after,
        credentials=case[0]["credentials"], request_id=case[3]["request_id"])
    return case, record, after, qualified


def test_qualification_retains_exact_inputs_without_promoting_project_or_replaying_plan():
    case, record, after, qualified = qualified_case()
    data = qualified.to_dict()
    assert data["archive_digest"] == record.digest and qualified.record is record
    assert data["response"] == case[3] and data["after"]["rows"] == after.rows
    assert data["assessment"]["project_revision_promoted"] is False
    assert data["claims"]["scope"] == "observed_level_fields_only"
    assert data["claims"]["geometry"] == data["claims"]["engineering"] == "not_established"
    assert case[0]["credentials"].token not in json.dumps(data)
    with patch("kir.compiler.compile_program", side_effect=AssertionError("no compile")), \
         patch("kir.compiler.plan_program", side_effect=AssertionError("no plan")), \
         patch("kir.revit_connector.prepare_execution", side_effect=AssertionError("no preparation")):
        assert validate_level_settlement_claims(data, record) is None
        repeated = qualify_level_settlement(record, json.dumps(case[3]), after=after,
            credentials=case[0]["credentials"], request_id=case[3]["request_id"])
    assert repeated.digest == qualified.digest
    data["after"]["rows"].clear()
    assert qualified.to_dict()["after"]["rows"]
    with pytest.raises(TypeError):
        QualifiedLevelSettlement()
    assert not any(hasattr(qualified, name) for name in ("execute_request", "planned", "to_prepared"))


@pytest.mark.parametrize("fault", ["unknown", "wrong_elevation", "wrong_target_id", "protected_renamed",
    "protected_changes", "truncated_changes", "bad_row", "stale_read", "foreign_document"])
def test_partial_or_unknown_scope_never_creates_a_settlement(fault):
    case, _, record = record_values()
    response, rows = deepcopy(case[3]), deepcopy(case[4])
    target = case[1].to_dict()["target_identity"]["unique_id"]
    protected = next(uid for uid in rows if uid != target)
    if fault == "unknown": response["receipt"]["state"] = "running_unknown"
    if fault == "wrong_elevation": rows[target]["level"]["project_elevation_mm"] = 10
    if fault == "wrong_target_id": rows[target]["element_identity"]["element_id"] = 8001
    if fault == "protected_renamed": rows[protected]["name"] = "Changed"
    if fault == "protected_changes":
        response["receipt"]["changes"]["modified"].append(rows[protected]["element_identity"]["element_id"])
    if fault == "truncated_changes": response["receipt"]["changes"]["truncated"] = True
    if fault == "bad_row":
        result = json.loads(response["receipt"]["result_json"])
        result[case[2].planned.to_ops()[0]["id"]]["error"] = "failed"
        response["receipt"]["result_json"] = json.dumps(result)
    after, _, _ = after_read(case, rows=rows, revision=9 if fault == "stale_read" else 10,
        document="foreign" if fault == "foreign_document" else "native-doc")
    with pytest.raises(LevelSettlementRefusal, match="level_scope_not_satisfied"):
        qualify_level_settlement(record, json.dumps(response), after=after,
            credentials=case[0]["credentials"], request_id=response["request_id"])


@pytest.mark.parametrize("fault", ["digest", "archive", "original", "project", "base", "proposed", "scope",
    "after_revision", "after_target", "assessment", "execution", "report_after", "receipt", "credentials", "overclaim"])
def test_rehashed_retained_relationship_corruption_is_rejected(fault):
    _, record, _, qualified = qualified_case()
    data = qualified.to_dict()
    if fault in {"archive", "original", "base", "proposed"}:
        key = {"archive": "archive_digest", "original": "original_binding_digest", "base": "base_revision",
               "proposed": "proposed_revision"}[fault]
        data[key] = "f" * 64
    if fault == "project": data["project_id"] = "foreign"
    if fault == "scope": data["after"]["rows"].pop(next(iter(data["after"]["rows"])))
    if fault == "after_revision": data["after"]["precondition"]["revision"] = 1
    if fault == "after_target": data["after"]["target"]["revit_version"] = "2023"
    if fault == "assessment": data["assessment"]["checks"]["target_elevation"]["status"] = "violated"
    if fault == "execution": data["assessment"]["execution"]["execution"] = "unconfirmed"
    if fault == "report_after": data["assessment"]["after"]["operation_id"] = "different"
    if fault == "receipt": data["response"]["receipt"]["operation_id"] = "different"
    if fault == "credentials": data["response"]["token"] = "must-not-retain"
    if fault == "overclaim": data["claims"]["geometry"] = "verified"
    data["settlement_digest"] = _hash({k: v for k, v in data.items() if k != "settlement_digest"})
    if fault == "digest": data["settlement_digest"] = "0" * 64
    with pytest.raises(LevelSettlementRefusal):
        validate_level_settlement_claims(data, record=record)
