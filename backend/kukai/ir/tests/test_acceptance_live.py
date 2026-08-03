"""Live L2 boundary and immutable independent-acceptance evidence."""
from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from kukai.ir.acceptance import (
    BlindOp,
    Expectation,
    MismatchCode,
    check_acceptance,
    derive_expectation,
)
from kukai.ir.acceptance_evidence import (
    AcceptanceEvidence,
    AcceptanceEvidenceError,
    AcceptanceReason,
    AcceptanceRegistration,
    assess_acceptance,
    incomplete_acceptance,
)
from kukai.ir.acceptance_live import (
    SCOPE_CENSUS_SCHEMA_VERSION,
    ScopeCensusError,
    ScopeCensusObservation,
    build_scope_census_cs,
    observation_from_census,
    parse_scope_census,
)
from kukai.ir.acceptance_mutation import (
    MutationExpectation,
    derive_mutation_expectation,
)
from kukai.ir.compiler import plan_program
from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.outcome import (
    AcceptanceState,
    WitnessState,
    independently_assessed,
    write_committed,
)
from kukai.ir.revit_read_helpers import ELEMENT_LEVEL_HELPERS_CS
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


RUN_ID = "a" * 32
L1 = "Этаж 1"
L2 = "Этаж 2"


def _wall_plan():
    return plan_program({
        "ir_version": "1.0",
        "ops": [{
            "op": "create_wall",
            "id": "W1",
            "p0_mm": [0, 0],
            "p1_mm": [6000, 0],
            "level": {"by": "name", "value": L1},
        }],
    })


def _document() -> DocumentFingerprint:
    return DocumentFingerprint.from_dict(
        GROUND_SNAPSHOT["__document_fingerprint"])


def _expectation() -> Expectation:
    return derive_expectation(_wall_plan())


def _observation(census, *, phase="before"):
    return observation_from_census(
        _expectation(), _document(), census, run_id=RUN_ID, phase=phase)


def _registration(before=None, *, expectation=None):
    selected = expectation or _expectation()
    return AcceptanceRegistration(
        run_id=RUN_ID,
        plan_digest=_wall_plan().plan_digest,
        revit_version="2026",
        expectation=selected,
        mutation_expectation=derive_mutation_expectation(_wall_plan()),
        document=_document(),
        categories=tuple(sorted({
            category
            for row in selected.rows
            for category in row.categories
        })),
        before=before,
        mutation_before=None,
    )


class TestLiveCensusContract:
    def test_generated_read_uses_shared_level_authority_and_document_guard(self):
        code = build_scope_census_cs(
            _expectation(), _document(), run_id=RUN_ID, phase="before")
        assert ELEMENT_LEVEL_HELPERS_CS in code
        assert "OST_Walls" in code
        assert "WhereElementIsNotElementType" in code
        assert SCOPE_CENSUS_SCHEMA_VERSION in code
        assert RUN_ID in code
        assert _document().digest in code
        assert code.index("expected_fingerprint") < code.index(
            "FilteredElementCollector")

    def test_six_version_gate_includes_the_live_acceptance_body(self):
        from kukai.ir.gate_runner import acceptance_gate_body

        code = acceptance_gate_body()
        assert SCOPE_CENSUS_SCHEMA_VERSION in code
        assert "OST_Walls" in code
        assert "OST_PipeCurves" in code
        assert "expected_fingerprint" in code

    def test_round_trip_is_content_addressed_and_canonical(self):
        original = _observation({("OST_Walls", L1): 7})
        parsed = parse_scope_census(
            original.to_dict(), _expectation(), _document(), run_id=RUN_ID,
            phase="before")
        assert parsed == original
        assert parsed.census == {("OST_Walls", L1): 7}
        assert len(parsed.observation_digest) == 64

    @pytest.mark.parametrize("mutation", [
        lambda row: row.update(schema_version="kir-scope-census/999"),
        lambda row: row.update(run_id="b" * 32),
        lambda row: row.update(phase="after"),
        lambda row: row.update(expectation_digest="b" * 64),
        lambda row: row.update(document_digest="b" * 64),
        lambda row: row.update(categories=["OST_Floors"]),
        lambda row: row.update(total=8),
        lambda row: row.update(extra=True),
    ])
    def test_binding_or_wire_mutation_is_refused(self, mutation):
        payload = _observation({("OST_Walls", L1): 7}).to_dict()
        mutation(payload)
        with pytest.raises(ScopeCensusError):
            parse_scope_census(
                payload, _expectation(), _document(), run_id=RUN_ID,
                phase="before")

    def test_duplicate_cell_is_refused_even_when_counts_differ(self):
        payload = _observation({("OST_Walls", L1): 7}).to_dict()
        payload["rows"].append({
            "category": "OST_Walls", "level_name": L1, "count": 8,
        })
        payload["total"] = 15
        with pytest.raises(ScopeCensusError, match="duplicate"):
            parse_scope_census(
                payload, _expectation(), _document(), run_id=RUN_ID,
                phase="before")

    def test_rows_must_arrive_in_canonical_order(self):
        expectation = replace(
            _expectation(),
            rows=(_expectation().rows[0], replace(
                _expectation().rows[0], level=L2, op_ids=("W2",))),
            op_count=2,
        )
        payload = observation_from_census(
            expectation,
            _document(),
            {("OST_Walls", L1): 1, ("OST_Walls", L2): 1},
            run_id=RUN_ID,
            phase="before",
        ).to_dict()
        payload["rows"].reverse()
        with pytest.raises(ScopeCensusError, match="sorted"):
            parse_scope_census(
                payload, expectation, _document(), run_id=RUN_ID,
                phase="before")


class TestAcceptanceEvidence:
    def test_exact_delta_is_accepted_and_replayable(self):
        before = _observation({("OST_Walls", L1): 10})
        registration = _registration(before)
        evidence = assess_acceptance(
            registration,
            _observation({("OST_Walls", L1): 11}, phase="after"),
            None,
        )
        assert evidence.state is AcceptanceState.ACCEPTED
        assert evidence.verdict is not None and evidence.verdict.accepted
        assert evidence.reason is AcceptanceReason.MEASURED
        assert len(evidence.evidence_digest) == 64
        assert evidence.to_dict()["registration_digest"] == (
            registration.registration_digest)

    @pytest.mark.parametrize(("after", "code"), [
        ({("OST_Walls", L1): 10}, MismatchCode.CATEGORY_SHORTFALL),
        ({("OST_Walls", L1): 12}, MismatchCode.CATEGORY_OVERSHOOT),
        ({("OST_Walls", L1): 10, ("OST_Walls", L2): 1},
         MismatchCode.LEVEL_SHORTFALL),
    ])
    def test_negative_controls_reject(self, after, code):
        registration = _registration(
            _observation({("OST_Walls", L1): 10}))
        evidence = assess_acceptance(
            registration, _observation(after, phase="after"), None)
        assert evidence.state is AcceptanceState.REJECTED
        assert evidence.verdict is not None
        assert code in {item.code for item in evidence.verdict.mismatches}

    def test_caller_cannot_forge_a_green_verdict(self):
        before = _observation({("OST_Walls", L1): 10})
        registration = _registration(before)
        rejected_after = _observation(
            {("OST_Walls", L1): 10}, phase="after")
        green = check_acceptance(
            _expectation(), before.census,
            _observation({("OST_Walls", L1): 11}, phase="after").census,
        )
        with pytest.raises(AcceptanceEvidenceError, match="disagrees"):
            AcceptanceEvidence(
                registration=registration,
                state=AcceptanceState.ACCEPTED,
                reason=AcceptanceReason.MEASURED,
                after=rejected_after,
                verdict=green,
            )

    def test_blind_mixed_program_is_measured_but_never_overclaimed(self):
        base = _expectation()
        partial = replace(
            base,
            blind_ops=(BlindOp(
                "F1", "place_family", "category comes from live symbol"),),
            upper_bounds_valid=False,
            op_count=2,
        )
        before = observation_from_census(
            partial, _document(), {}, run_id=RUN_ID, phase="before")
        registration = _registration(before, expectation=partial)
        after = observation_from_census(
            partial, _document(), {("OST_Walls", L1): 1}, run_id=RUN_ID,
            phase="after")
        evidence = assess_acceptance(registration, after, None)
        assert evidence.state is AcceptanceState.INCONCLUSIVE
        assert evidence.reason is AcceptanceReason.PARTIAL_BLIND_SCOPE
        assert evidence.verdict is not None and evidence.verdict.accepted

    def test_vacuous_program_has_named_inconclusive_evidence(self):
        vacuous = Expectation((), (), (), True, 1)
        registration = AcceptanceRegistration(
            run_id=RUN_ID,
            plan_digest=_wall_plan().plan_digest,
            revit_version="2026",
            expectation=vacuous,
            mutation_expectation=MutationExpectation((), ()),
            document=_document(),
            categories=(),
            before=None,
            mutation_before=None,
        )
        evidence = incomplete_acceptance(
            registration, AcceptanceReason.VACUOUS)
        assert evidence.state is AcceptanceState.INCONCLUSIVE
        assert evidence.verdict is None

    def test_outcome_transition_preserves_commit_and_witness_axes(self):
        committed = write_committed(witness=WitnessState.SATISFIED)
        assessed = independently_assessed(
            committed, AcceptanceState.ACCEPTED)
        assert assessed.committed
        assert assessed.witness is WitnessState.SATISFIED
        assert assessed.acceptance is AcceptanceState.ACCEPTED

        violated = write_committed(witness=WitnessState.VIOLATED)
        with pytest.raises(ValueError, match="cannot overrule"):
            independently_assessed(violated, AcceptanceState.ACCEPTED)
