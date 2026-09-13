"""No-start qualification is distinct from inert claims and scope release."""
from copy import copy, deepcopy
from dataclasses import replace
import json
from uuid import uuid4

import pytest

from kir.bridge_result import WriteResultAssessment
from kir.create_publication import (CreatePublicationError, require_create_not_started,
                                    validate_create_not_started_claims)
from kir.outcome import program_not_started
from kir.revit_connector import RuntimeTarget, SessionCredentials
from kir.tests.test_create_receipt_store import case, bind


def no_start(response, state="cancelled_before_start"):
    value = deepcopy(response)
    value["receipt"].update(state=state, started=False, may_retry=True,
        transaction_evidence="not_observed", changes=None, result_json=None,
        result_error=None, result_truncated=False, error="cancelled without invocation")
    return value


@pytest.mark.parametrize("state", ["cancelled_before_start", "context_changed_before_start", "rejected_before_start"])
def test_exact_native_no_start_qualifies_without_releasing_or_writing(case, state):
    store, _, record, _, response = case
    bound = bind(case, no_start(response, state))
    before = store.path.read_bytes()
    assert require_create_not_started(record, bound) is None
    assert validate_create_not_started_claims(record, bound.to_dict()) is None
    assert store.path.read_bytes() == before
    assert store.get_create_publication(record.digest).state == "reserved"
    assert store.get_create_receipts(record.digest).to_dict()["receipts"] == []


@pytest.mark.parametrize("field,value", [
    ("state", "running_unknown"), ("state", "invocation_completed"),
    ("state", "failed_after_start_unknown"), ("state", "operation_conflict"),
    ("started", True), ("started", 0), ("may_retry", False), ("may_retry", 1),
    ("changes", {"added": [], "modified": [], "deleted": [], "transaction_names": [], "truncated": False}),
    ("transaction_evidence", "changes_not_observed"), ("result_json", "{}"),
    ("result_error", "failed"), ("result_truncated", True),
    ("timestamp_utc", ""), ("semantic_evidence", "verified"),
])
def test_contradictory_or_unknown_receipt_cannot_release(case, field, value):
    _, _, record, _, response = case
    changed = no_start(response)
    changed["receipt"][field] = value
    bound = bind(case, changed)
    with pytest.raises(CreatePublicationError):
        require_create_not_started(record, bound)
    with pytest.raises(CreatePublicationError):
        validate_create_not_started_claims(record, bound.to_dict())


def test_inert_loaded_claims_never_become_fresh_no_start_evidence(case):
    _, _, record, _, response = case
    payload = json.loads(json.dumps(bind(case, no_start(response)).to_dict()))
    assert validate_create_not_started_claims(record, payload) is None
    with pytest.raises(CreatePublicationError):
        require_create_not_started(record, payload)


def test_forged_derived_no_start_cannot_overrule_native_creation(case):
    _, _, record, _, _ = case
    original = bind(case)
    forged = copy(original)
    object.__setattr__(forged, "assessment", replace(original.assessment,
        diagnostic_code="not_started", assessment=WriteResultAssessment(program_not_started())))
    assert forged.not_started  # This public convenience property is NOT authority.
    with pytest.raises(CreatePublicationError, match="create_assessment_mismatch"):
        require_create_not_started(record, forged)


def test_failed_original_outer_response_cannot_be_repaired_by_public_fields(case):
    _, _, record, _, response = case
    changed = no_start(response)
    changed.update(ok=False, status="journal_unavailable", error="failure")
    bound = bind(case, changed)
    claimed_outer = deepcopy(changed)
    claimed_outer.update(ok=True, status="receipt", error=None)
    forged = copy(bound)
    object.__setattr__(forged, "assessment", replace(bound.assessment,
        diagnostic_code="not_started", assessment=WriteResultAssessment(program_not_started()),
        raw_response=json.dumps(claimed_outer).encode()))
    with pytest.raises(CreatePublicationError, match="create_assessment_mismatch"):
        require_create_not_started(record, forged)


def test_no_start_does_not_require_current_compiler_registry_admission(case, monkeypatch):
    _, _, record, _, response = case
    bound = bind(case, no_start(response))
    import kir.bridge_result
    monkeypatch.setattr(kir.bridge_result, "saved_create_result_contract",
                        lambda *_: pytest.fail("no-start revalidated current CREATE profile"))
    assert require_create_not_started(record, bound) is None
    assert validate_create_not_started_claims(record, bound.to_dict()) is None


def test_recovery_runtime_changes_outer_route_not_original_no_start_binding(case):
    _, _, record, _, response = case
    other = SessionCredentials(RuntimeTarget(str(uuid4()), str(uuid4()), "2026"), str(uuid4()), "recovery-token")
    changed = no_start(response)
    changed.update(target=other.target.to_dict(), session_id=other.session_id, request_id=str(uuid4()))
    bound = bind(case, changed, credentials=other, recovery=True)
    assert require_create_not_started(record, bound) is None
    assert bound.to_dict()["native_receipt"]["target"] == record.binding_dict()["target"]
