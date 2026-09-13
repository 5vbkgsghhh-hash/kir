"""Field-level observation parsing with explicit synthetic native receipts."""
from dataclasses import FrozenInstanceError
import json
from uuid import uuid4

import pytest

from kir.contracts import ElementIdentityProof
from kir.revit_connector import MAX_FRAME_BYTES, MAX_SOURCE_CHARS, SessionCredentials
from kir.element_query import ELEMENT_STATE_SCHEMA
from kir.revit_observation import (
    ElementObservation, MAX_OBSERVATION_ELEMENTS, ObservationRefusal,
    parse_element_observation, prepare_element_observation,
)
from kir.tests.test_connector_query_result import case as generic_case


def identity(element_id, uid):
    return {"element_identity": ElementIdentityProof(element_id, uid, "a" * 32).to_dict(),
            "element_identity_status": "captured", "element_identity_reason": None}


def unavailable():
    return {"element_identity": None, "element_identity_status": "unavailable",
            "element_identity_reason": "element_missing"}


def row(uid="level-uid", *, is_level=True):
    return {"schema_version": ELEMENT_STATE_SCHEMA, "requested_unique_id": uid,
        "status": "observed", "reason": None, "name": "Observed fixture", "category_id": -2000240,
        "is_level": is_level, "type_state": {"status": "observed", **identity(900, "type-uid")},
        "level_status": "observed" if is_level else "not_level", "level_reason": None,
        "level": {"project_elevation_mm": 3000.0, "reported_elevation_mm": 3000.0,
            "elevation_base": 0, "basis_parameter_id": -1007101,
            "elevation_parameter": {"builtin": "LEVEL_ELEV", "parameter_id": -1007102,
                "name": "Отметка", "storage_type": "Double", "is_read_only": False,
                "value_internal_feet": 3000 / 304.8, "name_match_count": 1,
                "name_resolves_builtin": True}} if is_level else None,
        **identity(700 if is_level else 701, uid)}


@pytest.fixture
def case():
    previous, credentials, response, _ = generic_case.__wrapped__()
    artifact = prepare_element_observation(["level-uid", "protected-uid"], target=previous.target,
        precondition=previous.precondition, operation_id=previous.operation_id)
    response["receipt"].update(artifact.binding_dict())
    rows = {"observe_0": row(), "observe_1": row("protected-uid", is_level=False)}

    def parse(values=None):
        response["receipt"]["result_json"] = json.dumps(rows if values is None else values)
        return parse_element_observation(artifact, json.dumps(response), credentials=credentials,
                                         request_id=response["request_id"])

    return artifact, response, rows, parse


def test_complete_observation_keeps_original_revision_and_detached_values(case):
    artifact, _, _, parse = case
    observed = parse()
    assert observed.target == artifact.target and observed.precondition is artifact.precondition
    assert observed.operation_id == artifact.operation_id and observed.source_sha256 == artifact.source_sha256
    assert observed.require_identity("level-uid").element_id == 700
    assert observed.require_level("level-uid")["level"]["project_elevation_mm"] == 3000
    detached = observed.rows
    detached["level-uid"]["level"]["project_elevation_mm"] = 0
    assert observed.require_level("level-uid")["level"]["project_elevation_mm"] == 3000
    with pytest.raises(FrozenInstanceError):
        observed.source_sha256 = "forged"
    with pytest.raises(TypeError):
        ElementObservation()


@pytest.mark.parametrize("missing", ["observe_0", "observe_1"])
def test_scope_omission_is_not_a_complete_observation(case, missing):
    _, _, rows, parse = case
    del rows[missing]
    with pytest.raises(ObservationRefusal):
        parse()


def test_extra_or_empty_results_cannot_claim_requested_scope(case):
    _, _, rows, parse = case
    with pytest.raises(ObservationRefusal):
        parse({})
    rows["unexpected"] = row("other")
    with pytest.raises(ObservationRefusal):
        parse()


@pytest.mark.parametrize("field", sorted(row()))
def test_missing_row_field_is_not_replaced_by_a_default(case, field):
    _, _, rows, parse = case
    del rows["observe_0"][field]
    with pytest.raises(ObservationRefusal):
        parse()


@pytest.mark.parametrize("path,value", [
    (("schema_version",), "kir-element-state/2"),
    (("requested_unique_id",), "another-uid"),
    (("element_identity", "unique_id"), "id-reused-by-another-element"),
    (("element_identity", "element_id"), True),
    (("element_identity", "element_id"), -1),
    (("element_identity", "version_guid"), "A" * 32),
    (("element_identity_status",), "unavailable"),
    (("is_level",), 1),
    (("category_id",), "-2000240"),
    (("level", "project_elevation_mm"), True),
    (("level", "project_elevation_mm"), float("nan")),
    (("level", "reported_elevation_mm"), "3000"),
    (("level", "elevation_base"), True),
    (("level", "basis_parameter_id"), 123),
    (("level", "elevation_parameter", "builtin"), "LEVEL_NAME"),
    (("level", "elevation_parameter", "storage_type"), "String"),
    (("level", "elevation_parameter", "value_internal_feet"), float("inf")),
    (("level", "elevation_parameter", "is_read_only"), 0),
    (("level", "elevation_parameter", "name"), ""),
    (("level", "elevation_parameter", "name_match_count"), 2),
])
def test_malformed_or_contradictory_observed_fields_refuse(case, path, value):
    _, _, rows, parse = case
    destination = rows["observe_0"]
    for key in path[:-1]:
        destination = destination[key]
    destination[path[-1]] = value
    with pytest.raises(ObservationRefusal):
        parse()


def test_not_found_is_an_explicit_row_but_cannot_supply_an_identity(case):
    _, _, rows, parse = case
    rows["observe_0"].update(status="not_found", name=None, category_id=None, is_level=None,
        type_state=None, level_status="not_evaluated", level=None, **unavailable())
    observed = parse()
    assert observed.rows["level-uid"]["status"] == "not_found"
    assert observed.require_identity("protected-uid").element_id == 701
    with pytest.raises(ObservationRefusal, match="element_identity_unavailable"):
        observed.require_identity("level-uid")
    with pytest.raises(ObservationRefusal, match="level_observation_unavailable"):
        observed.require_level("level-uid")


def test_missing_level_data_does_not_erase_known_identity_or_become_a_level_baseline(case):
    _, _, rows, parse = case
    rows["observe_0"].update(level_status="unavailable", level_reason="level_parameters_unavailable", level=None)
    observed = parse()
    assert observed.require_identity("level-uid").element_id == 700
    with pytest.raises(ObservationRefusal, match="level_observation_unavailable"):
        observed.require_level("level-uid")


def test_shared_basis_readonly_and_ambiguous_name_are_facts_not_update_permission(case):
    _, _, rows, parse = case
    level = rows["observe_0"]["level"]
    level.update(elevation_base=1, reported_elevation_mm=53000.0)
    level["elevation_parameter"].update(is_read_only=True, name_match_count=2, name_resolves_builtin=False)
    observed = parse().require_level("level-uid")
    assert observed["level"]["elevation_base"] == 1
    assert observed["level"]["project_elevation_mm"] == 3000
    assert observed["level"]["elevation_parameter"]["is_read_only"] is True


def test_changed_numeric_id_is_observed_by_same_uid_not_treated_as_original_id(case):
    _, _, rows, parse = case
    rows["observe_0"]["element_identity"]["element_id"] = 1700
    observed = parse()
    assert observed.require_identity("level-uid").element_id == 1700
    assert observed.require_identity("level-uid").unique_id == "level-uid"


def test_missing_type_identity_cannot_supply_level_update_dependency(case):
    _, _, rows, parse = case
    rows["observe_0"]["type_state"] = {"status": "unavailable", **unavailable()}
    # A malformed producer can still return a level payload. The consumer
    # explicitly needs the type dependency and refuses to use that payload.
    observed = parse()
    with pytest.raises(ObservationRefusal, match="level_observation_unavailable"):
        observed.require_level("level-uid")


@pytest.mark.parametrize("axis", ["element_id", "unique_id", "both"])
def test_level_cannot_be_its_own_type_dependency(case, axis):
    _, _, rows, parse = case
    level = rows["observe_0"]
    type_identity = level["type_state"]["element_identity"]
    for key in ("element_id", "unique_id") if axis == "both" else (axis,):
        type_identity[key] = level["element_identity"][key]
    with pytest.raises(ObservationRefusal, match="invalid_element_type_identity"):
        parse()


def test_two_observed_uids_cannot_share_one_current_numeric_id(case):
    _, _, rows, parse = case
    rows["observe_1"]["element_identity"]["element_id"] = 700
    with pytest.raises(ObservationRefusal, match="conflicting_element_identity"):
        parse()


@pytest.mark.parametrize("field,value", [("element_id", 901), ("unique_id", "another-type"),
                                        ("version_guid", "b" * 32)])
def test_shared_type_cannot_have_conflicting_observed_identities(case, field, value):
    _, _, rows, parse = case
    rows["observe_1"]["type_state"]["element_identity"][field] = value
    with pytest.raises(ObservationRefusal, match="conflicting_element_identity"):
        parse()


def test_identical_shared_type_is_legal_and_unavailable_raw_identity_does_not_poison_scope(case):
    _, _, rows, parse = case
    assert parse().require_level("level-uid")["type_state"]["element_identity"]["element_id"] == 900
    failed = rows["observe_0"]
    failed.update(status="unavailable", reason="identity_mismatch", name=None, category_id=None,
        is_level=None, type_state=None, level_status="not_evaluated", level=None)
    # A named unusable claim is preserved as failure, not indexed as authority.
    failed["element_identity"]["element_id"] = 701
    observed = parse()
    assert observed.rows["level-uid"]["reason"] == "identity_mismatch"
    assert observed.require_identity("protected-uid").element_id == 701


@pytest.mark.parametrize("axis", ["revision", "source", "changes", "truncated"])
def test_native_binding_and_readonly_scope_are_checked_before_field_acceptance(case, axis):
    _, response, _, parse = case
    if axis == "revision":
        response["receipt"]["precondition"]["revision"] += 1
    elif axis == "source":
        response["receipt"]["source_sha256"] = "b" * 64
    elif axis == "changes":
        response["receipt"]["changes"]["modified"] = [701]
        response["receipt"]["transaction_evidence"] = "changes_observed"
    else:
        response["receipt"]["changes"]["truncated"] = True
    with pytest.raises(ObservationRefusal, match="query_result_unavailable"):
        parse()


@pytest.mark.parametrize("scope", [None, "level-uid", b"uid", {}, [None], [True], [""], ["  "]])
def test_malformed_scope_cannot_be_prepared(case, scope):
    artifact, _, _, _ = case
    with pytest.raises(ObservationRefusal):
        prepare_element_observation(scope, target=artifact.target, precondition=artifact.precondition,
                                    operation_id=artifact.operation_id)


@pytest.mark.parametrize("scope,code", [([], "observation_scope_budget"),
    (["uid"] * 2, "duplicate_observation_identity"),
    ([f"uid-{index}" for index in range(MAX_OBSERVATION_ELEMENTS + 1)], "observation_scope_budget")])
def test_scope_budget_and_duplicates_refuse_explicitly(case, scope, code):
    artifact, _, _, _ = case
    with pytest.raises(ObservationRefusal, match=code):
        prepare_element_observation(scope, target=artifact.target, precondition=artifact.precondition,
                                    operation_id=artifact.operation_id)


def test_scope_is_detached_from_caller_and_maximum_batch_is_within_native_source_budget(case):
    artifact, _, _, _ = case
    scope = [f"{index:03d}-" + "😀" * 508 for index in range(MAX_OBSERVATION_ELEMENTS)]
    prepared = prepare_element_observation(scope, target=artifact.target, precondition=artifact.precondition,
                                           operation_id=artifact.operation_id)
    scope.clear()
    assert len(prepared.planned.to_ops()) == MAX_OBSERVATION_ELEMENTS
    assert prepared.precondition is artifact.precondition
    assert len(prepared.source.encode("utf-16-le")) // 2 <= MAX_SOURCE_CHARS
    credentials = SessionCredentials(artifact.target, str(uuid4()), "fixture-credential")
    request = prepared.execute_request(credentials, request_id=str(uuid4()))
    assert len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()) <= MAX_FRAME_BYTES


def test_unexpected_units_or_extra_claims_cannot_enter_level_observation(case):
    _, _, rows, parse = case
    rows["observe_0"]["level"]["units"] = "cm"
    with pytest.raises(ObservationRefusal):
        parse()
