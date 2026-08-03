"""Independent exact-identity acceptance for in-place KIR writes."""
from __future__ import annotations

import copy
import hashlib
from dataclasses import replace

import pytest

from kukai.ir.acceptance import derive_expectation, expectation_categories
from kukai.ir.acceptance_evidence import (
    AcceptanceEvidence,
    AcceptanceEvidenceError,
    AcceptanceReason,
    AcceptanceRegistration,
    assess_acceptance,
)
from kukai.ir.acceptance_live import observation_from_census
from kukai.ir.acceptance_mutation import (
    MutationAcceptanceError,
    MutationKind,
    MutationMismatchCode,
    MutationObservation,
    MutationObservationRow,
    build_mutation_probe_cs,
    check_mutations,
    derive_mutation_expectation,
    mutation_precondition_errors,
    parse_mutation_observation,
)
from kukai.ir.acceptance_probe import (
    ACCEPTANCE_OBSERVATION_SCHEMA_VERSION,
    AcceptanceProbeError,
    build_acceptance_probe_cs,
    parse_acceptance_observation,
)
from kukai.ir.compiler import plan_program
from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.outcome import AcceptanceState
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


RUN_ID = "d" * 32
L1 = "Этаж 1"


def _document() -> DocumentFingerprint:
    return DocumentFingerprint.from_dict(
        GROUND_SNAPSHOT["__document_fingerprint"])


def _mutation_plan():
    return plan_program({
        "ir_version": "1.0",
        "allow_destructive": True,
        "ops": [
            {
                "op": "set_param", "id": "S1",
                "target": {"by": "element_id", "value": 101},
                "param": "Comments", "value": "accepted",
            },
            {
                "op": "move_elements", "id": "M1",
                "targets": [
                    {"by": "element_id", "value": 102},
                    {"by": "element_id", "value": 103},
                ],
                "delta_mm": [100, -200, 500],
            },
            {
                "op": "change_type", "id": "T1",
                "target": {"by": "element_id", "value": 104},
                "type": {"by": "element_id", "value": 900},
            },
            {
                "op": "delete", "id": "D1",
                "target": {"by": "element_id", "value": 105},
            },
        ],
    })


def _mutation_observation(expectation, *, phase="before"):
    rows = []
    for claim in expectation.claims:
        exists = not (phase == "after" and claim.kind is MutationKind.DELETE)
        unique_id = f"uid-{claim.target_id}" if exists else None
        version_guid = (
            hashlib.sha256(str(claim.target_id).encode("ascii")).hexdigest()[:32]
            if exists else None
        )
        location_kind = "not_requested" if exists else "missing"
        point = curve0 = curve1 = None
        type_id = None
        desired_type_exists = None
        desired_type_unique_id = None
        desired_type_version_guid = None
        matches = read_only = storage = string = integer = double = None
        if exists and claim.kind is MutationKind.MOVE:
            location_kind = "curve" if claim.target_id == 103 else "point"
            delta = claim.delta_mm if phase == "after" else (0.0, 0.0, 0.0)
            if location_kind == "point":
                point = tuple(1000.0 + index * 100.0 + delta[index]
                              for index in range(3))
            else:
                curve0 = tuple(1000.0 + index * 100.0 + delta[index]
                               for index in range(3))
                curve1 = tuple(4000.0 + index * 100.0 + delta[index]
                               for index in range(3))
        elif exists and claim.kind is MutationKind.CHANGE_TYPE:
            type_id = str(claim.type_id if phase == "after" else 800)
            desired_type_exists = True
            desired_type_unique_id = f"uid-{claim.type_id}"
            desired_type_version_guid = hashlib.sha256(
                str(claim.type_id).encode("ascii")).hexdigest()[:32]
        elif exists and claim.kind is MutationKind.SET_PARAMETER:
            matches = 1
            read_only = False
            storage = {
                "str": "String", "int": "Integer",
                "mm": "Double", "double": "Double",
            }[claim.value_kind]
            if claim.value_kind == "str":
                string = claim.expected_string if phase == "after" else "old"
            elif claim.value_kind == "int":
                integer = int(claim.expected_number if phase == "after" else 0)
            elif claim.value_kind == "mm":
                double = float(claim.expected_number) / 304.8 if phase == "after" else 0.0
            else:
                double = float(claim.expected_number) if phase == "after" else 0.0
        rows.append(MutationObservationRow(
            claim_key=claim.key,
            target_id=str(claim.target_id),
            exists=exists,
            unique_id=unique_id,
            version_guid=version_guid,
            desired_type_exists=desired_type_exists,
            desired_type_unique_id=desired_type_unique_id,
            desired_type_version_guid=desired_type_version_guid,
            type_id=type_id,
            location_kind=location_kind,
            point_mm=point,
            curve0_mm=curve0,
            curve1_mm=curve1,
            parameter_matches=matches,
            parameter_read_only=read_only,
            parameter_storage=storage,
            parameter_string=string,
            parameter_integer=integer,
            parameter_double=double,
        ))
    return MutationObservation(
        run_id=RUN_ID,
        phase=phase,
        expectation_digest=expectation.digest,
        document_digest=_document().digest,
        rows=tuple(rows),
    )


def _replace_row(observation, claim_key, **changes):
    rows = tuple(
        replace(row, **changes) if row.claim_key == claim_key else row
        for row in observation.rows
    )
    return replace(observation, rows=rows)


def test_exact_mutations_are_derived_without_receipt_locators():
    expectation = derive_mutation_expectation(_mutation_plan())
    assert [claim.kind for claim in expectation.claims] == [
        MutationKind.DELETE,
        MutationKind.MOVE,
        MutationKind.MOVE,
        MutationKind.SET_PARAMETER,
        MutationKind.CHANGE_TYPE,
    ]
    assert expectation.blind_ops == ()
    assert all(claim.target_id in {101, 102, 103, 104, 105}
               for claim in expectation.claims)


def test_final_state_collapses_repeated_parameter_and_move_operations():
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [
            {"op": "set_param", "id": "S1",
             "target": {"by": "element_id", "value": 101},
             "param": "Comments", "value": "first"},
            {"op": "set_param", "id": "S2",
             "target": {"by": "element_id", "value": 101},
             "param": "Comments", "value": "last"},
            {"op": "move_elements", "id": "M1",
             "targets": [{"by": "element_id", "value": 102},
                         {"by": "element_id", "value": 102}],
             "delta_mm": [10, 20, 30]},
            {"op": "move_elements", "id": "M2",
             "targets": [{"by": "element_id", "value": 102}],
             "delta_mm": [-5, 0, 5]},
        ],
    })
    expectation = derive_mutation_expectation(plan)
    param = next(c for c in expectation.claims
                 if c.kind is MutationKind.SET_PARAMETER)
    move = next(c for c in expectation.claims
                if c.kind is MutationKind.MOVE)
    assert param.expected_string == "last"
    assert param.op_ids == ("S1", "S2")
    assert move.delta_mm == (5.0, 20.0, 35.0)
    assert move.op_ids == ("M1", "M2")


def test_reference_addressed_mutations_are_explicitly_blind():
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [
            {"op": "create_level", "id": "L", "elev_mm": 3000,
             "name": "New"},
            {"op": "set_param", "id": "S",
             "target": {"by": "ref", "value": "L"},
             "param": "Comments", "value": "new"},
        ],
    })
    expectation = derive_mutation_expectation(plan)
    assert expectation.claims == ()
    assert [item.op_name for item in expectation.blind_ops] == ["set_param"]


def test_matching_parameter_move_type_and_delete_are_accepted():
    expectation = derive_mutation_expectation(_mutation_plan())
    before = _mutation_observation(expectation, phase="before")
    after = _mutation_observation(expectation, phase="after")
    assert mutation_precondition_errors(expectation, before) == ()
    verdict = check_mutations(expectation, before, after)
    assert verdict.accepted
    assert verdict.checked_claims == 5
    assert verdict.mismatches == ()


@pytest.mark.parametrize(("claim_prefix", "changes", "code"), [
    ("param:", {"parameter_string": "wrong"},
     MutationMismatchCode.PARAMETER_MISMATCH),
    ("move:102", {"point_mm": (1100.0, 900.0, 1601.1)},
     MutationMismatchCode.LOCATION_MISMATCH),
    ("type:", {"type_id": "901"}, MutationMismatchCode.TYPE_MISMATCH),
    ("delete:", {"exists": True, "unique_id": "uid-105",
                 "version_guid": hashlib.sha256(b"105").hexdigest()[:32],
                 "location_kind": "not_requested"},
     MutationMismatchCode.DELETE_FAILED),
])
def test_negative_mutation_controls_reject(claim_prefix, changes, code):
    expectation = derive_mutation_expectation(_mutation_plan())
    before = _mutation_observation(expectation, phase="before")
    after = _mutation_observation(expectation, phase="after")
    key = next(claim.key for claim in expectation.claims
               if claim.key.startswith(claim_prefix))
    broken = _replace_row(after, key, **changes)
    verdict = check_mutations(expectation, before, broken)
    assert not verdict.accepted
    assert code in {item.code for item in verdict.mismatches}


def test_location_without_point_or_curve_is_named_inconclusive():
    expectation = derive_mutation_expectation(_mutation_plan())
    before = _mutation_observation(expectation, phase="before")
    after = _mutation_observation(expectation, phase="after")
    key = next(claim.key for claim in expectation.claims
               if claim.key == "move:102")
    before = _replace_row(
        before, key, location_kind="unsupported", point_mm=None)
    after = _replace_row(
        after, key, location_kind="unsupported", point_mm=None)
    verdict = check_mutations(expectation, before, after)
    assert not verdict.accepted
    assert key in verdict.inconclusive_claims
    assert verdict.mismatches == ()


def test_missing_or_read_only_target_is_a_pre_effect_failure():
    expectation = derive_mutation_expectation(_mutation_plan())
    before = _mutation_observation(expectation, phase="before")
    param_key = next(c.key for c in expectation.claims
                     if c.kind is MutationKind.SET_PARAMETER)
    broken = _replace_row(before, param_key, parameter_read_only=True)
    assert "read-only" in mutation_precondition_errors(expectation, broken)[0]


def test_missing_or_changed_desired_type_is_not_accepted():
    expectation = derive_mutation_expectation(_mutation_plan())
    before = _mutation_observation(expectation, phase="before")
    after = _mutation_observation(expectation, phase="after")
    key = next(c.key for c in expectation.claims
               if c.kind is MutationKind.CHANGE_TYPE)

    missing = _replace_row(
        before,
        key,
        desired_type_exists=False,
        desired_type_unique_id=None,
        desired_type_version_guid=None,
    )
    assert "desired type does not exist" in mutation_precondition_errors(
        expectation, missing)[0]

    changed = _replace_row(
        after,
        key,
        desired_type_version_guid="f" * 32,
    )
    verdict = check_mutations(expectation, before, changed)
    assert not verdict.accepted
    assert MutationMismatchCode.DEPENDENCY_CHANGED in {
        mismatch.code for mismatch in verdict.mismatches
    }


def test_legal_change_type_replacement_is_one_named_inconclusive_claim():
    expectation = derive_mutation_expectation(_mutation_plan())
    before = _mutation_observation(expectation, phase="before")
    after = _mutation_observation(expectation, phase="after")
    key = next(c.key for c in expectation.claims
               if c.kind is MutationKind.CHANGE_TYPE)
    replaced = _replace_row(after, key, unique_id="replacement-uid-104")

    verdict = check_mutations(expectation, before, replaced)

    assert not verdict.accepted
    assert verdict.mismatches == ()
    assert verdict.inconclusive_claims == (key,)


def test_empty_string_uses_the_same_null_as_empty_semantics_as_emitter():
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [{
            "op": "set_param", "id": "S",
            "target": {"by": "element_id", "value": 101},
            "param": "Comments", "value": "",
        }],
    })
    expectation = derive_mutation_expectation(plan)
    before = _mutation_observation(expectation, phase="before")
    after = _mutation_observation(expectation, phase="after")
    assert check_mutations(expectation, before, after).accepted
    code = build_mutation_probe_cs(
        expectation, _document(), run_id=RUN_ID,
        phase="after", revit_version="2026")
    assert 'AsString() ?? ""' in code


def test_generated_probe_is_document_phase_and_version_bound():
    expectation = derive_mutation_expectation(_mutation_plan())
    code = build_mutation_probe_cs(
        expectation,
        _document(),
        run_id=RUN_ID,
        phase="before",
        revit_version="2026",
    )
    assert "expected_fingerprint" in code
    assert '"phase", "before"' in code
    assert 'new ElementId(101)' in code
    assert expectation.digest in code

    from kukai.ir.gate_runner import mutation_acceptance_gate_body
    gate = mutation_acceptance_gate_body("2026")
    assert ACCEPTANCE_OBSERVATION_SCHEMA_VERSION in gate
    assert "LocationCurve" in gate
    assert "GetParameters" in gate


def test_long_element_id_uses_only_the_supported_revit_dialect():
    long_id = 3_000_000_000
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [{
            "op": "move_elements", "id": "M",
            "targets": [{"by": "element_id", "value": long_id}],
            "delta_mm": [1, 0, 0],
        }],
    })
    expectation = derive_mutation_expectation(plan)
    code = build_mutation_probe_cs(
        expectation, _document(), run_id=RUN_ID,
        phase="before", revit_version="2024")
    assert "new ElementId(3000000000L)" in code
    with pytest.raises(ValueError, match="32-bit"):
        build_mutation_probe_cs(
            expectation, _document(), run_id=RUN_ID,
            phase="before", revit_version="2023")


@pytest.mark.parametrize("mutate", [
    lambda row: row.update(run_id="e" * 32),
    lambda row: row.update(phase="after"),
    lambda row: row.update(expectation_digest="e" * 64),
    lambda row: row.update(extra=True),
    lambda row: row["rows"].reverse(),
    lambda row: row["rows"][0].update(target_id="999"),
])
def test_mutation_wire_is_closed_and_bound(mutate):
    expectation = derive_mutation_expectation(_mutation_plan())
    payload = _mutation_observation(
        expectation, phase="before").to_dict()
    mutate(payload)
    with pytest.raises(MutationAcceptanceError):
        parse_mutation_observation(
            payload, expectation, _document(), run_id=RUN_ID, phase="before")


def test_composite_probe_reads_scope_and_mutations_in_one_program():
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [
            {"op": "create_wall", "id": "W",
             "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": L1}},
            {"op": "move_elements", "id": "M",
             "targets": [{"by": "element_id", "value": 102}],
             "delta_mm": [0, 0, 500]},
        ],
    })
    scope = derive_expectation(plan)
    mutations = derive_mutation_expectation(plan)
    code = build_acceptance_probe_cs(
        plan_digest=plan.plan_digest,
        scope_expectation=scope,
        mutation_expectation=mutations,
        document=_document(),
        run_id=RUN_ID,
        phase="before",
        revit_version="2026",
    )
    assert code.count("expected_fingerprint") == 1
    assert "FilteredElementCollector" in code
    assert "LocationPoint" in code
    assert ACCEPTANCE_OBSERVATION_SCHEMA_VERSION in code

    scope_observation = observation_from_census(
        scope, _document(), {("OST_Walls", L1): 10},
        run_id=RUN_ID, phase="before")
    mutation_observation = _mutation_observation(
        mutations, phase="before")
    payload = {
        "schema_version": ACCEPTANCE_OBSERVATION_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "phase": "before",
        "plan_digest": plan.plan_digest,
        "document_digest": _document().digest,
        "revit_version": "2026",
        "scope_census": scope_observation.to_dict(),
        "mutations": mutation_observation.to_dict(),
    }
    parsed = parse_acceptance_observation(
        payload,
        plan_digest=plan.plan_digest,
        scope_expectation=scope,
        mutation_expectation=mutations,
        document=_document(),
        run_id=RUN_ID,
        phase="before",
        revit_version="2026",
    )
    assert parsed.scope_census == scope_observation
    assert parsed.mutations == mutation_observation
    widened = copy.deepcopy(payload)
    widened["extra"] = True
    with pytest.raises(AcceptanceProbeError):
        parse_acceptance_observation(
            widened,
            plan_digest=plan.plan_digest,
            scope_expectation=scope,
            mutation_expectation=mutations,
            document=_document(), run_id=RUN_ID, phase="before",
            revit_version="2026")


def test_mutation_evidence_is_replayed_and_cannot_be_forged():
    plan = _mutation_plan()
    scope = derive_expectation(plan)
    mutations = derive_mutation_expectation(plan)
    before = _mutation_observation(mutations, phase="before")
    registration = AcceptanceRegistration(
        run_id=RUN_ID,
        plan_digest=plan.plan_digest,
        revit_version="2026",
        expectation=scope,
        mutation_expectation=mutations,
        document=_document(),
        categories=(),
        before=None,
        mutation_before=before,
    )
    after = _mutation_observation(mutations, phase="after")
    evidence = assess_acceptance(registration, None, after)
    assert evidence.state is AcceptanceState.ACCEPTED
    assert evidence.mutation_verdict is not None

    bad_key = next(c.key for c in mutations.claims
                   if c.kind is MutationKind.SET_PARAMETER)
    broken = _replace_row(after, bad_key, parameter_string="wrong")
    with pytest.raises(AcceptanceEvidenceError, match="disagrees"):
        AcceptanceEvidence(
            registration=registration,
            state=AcceptanceState.ACCEPTED,
            reason=AcceptanceReason.MEASURED,
            mutation_after=broken,
            mutation_verdict=evidence.mutation_verdict,
        )


def test_mixed_create_delete_is_inconclusive_not_false_rejected_or_green():
    plan = plan_program({
        "ir_version": "1.0",
        "allow_destructive": True,
        "ops": [
            {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
             "p1_mm": [6000, 0],
             "level": {"by": "name", "value": L1}},
            {"op": "delete", "id": "D",
             "target": {"by": "element_id", "value": 105}},
        ],
    })
    scope = derive_expectation(plan)
    mutations = derive_mutation_expectation(plan)
    before = _mutation_observation(mutations, phase="before")
    registration = AcceptanceRegistration(
        run_id=RUN_ID,
        plan_digest=plan.plan_digest,
        revit_version="2026",
        expectation=scope,
        mutation_expectation=mutations,
        document=_document(),
        categories=expectation_categories(scope),
        before=None,
        mutation_before=before,
    )

    evidence = assess_acceptance(
        registration,
        None,
        _mutation_observation(mutations, phase="after"),
    )

    assert evidence.state is AcceptanceState.INCONCLUSIVE
    assert evidence.reason is AcceptanceReason.PARTIAL_BLIND_SCOPE
    assert evidence.mutation_verdict is not None
    assert evidence.mutation_verdict.accepted
