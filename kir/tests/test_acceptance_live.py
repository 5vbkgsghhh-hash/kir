"""Live L2 boundary and immutable independent-acceptance evidence."""
from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from kir.acceptance import (
    BlindOp,
    Expectation,
    MismatchCode,
    check_acceptance,
    derive_expectation,
)
from kir.acceptance_evidence import (
    AcceptanceEvidence,
    AcceptanceEvidenceError,
    AcceptanceReason,
    AcceptanceRegistration,
    assess_acceptance,
    incomplete_acceptance,
)
from kir.acceptance_live import (
    SCOPE_CENSUS_SCHEMA_VERSION,
    ScopeCensusError,
    ScopeCensusObservation,
    build_scope_census_cs,
    observation_from_census,
    parse_scope_census,
    scope_census_fragment,
)
from kir.acceptance_mutation import (
    MutationExpectation,
    derive_mutation_expectation,
)
from kir.compiler import plan_program
from kir.ground import ground_program
from kir.contracts import DocumentFingerprint
from kir.outcome import (
    AcceptanceState,
    WitnessState,
    independently_assessed,
    write_committed,
)
from kir.revit_read_helpers import ELEMENT_LEVEL_HELPERS_CS
from kir.tests.fixtures import GROUND_SNAPSHOT


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


def _observation(census, *, phase="before", scanned_total=None):
    return observation_from_census(
        _expectation(), _document(), census, run_id=RUN_ID, phase=phase,
        scanned_total=scanned_total)


def _registration(before=None, *, expectation=None):
    selected = expectation or _expectation()
    return AcceptanceRegistration(
        run_id=RUN_ID,
        plan_digest=_wall_plan().plan_digest,
        ground_digest=ground_program(
            _wall_plan(), GROUND_SNAPSHOT).ground_digest,
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


class TestTheScanCountsTheDocumentNotTheScope:
    """F-155: AN UNSOLICITED ELEMENT LEFT NO TRACE ANYWHERE.

    The live census's scope is derived from the EXPECTATION, and everything
    else is cut off three times over: in the C# itself, in the Python
    builder, and in the observation contract. `__kirAcceptanceTotal++` sat
    AFTER the `continue`, so a pipe created unintentionally, under an
    expectation of a single wall, disappeared from both the rows and the
    total. `Verdict.unexpected` — an instrument able to NAME the extra —
    stayed silent on the live path always: it was fed a census already
    filtered.

    🔴 THE CARDINALITY WITHOUT WHICH THESE CONTROLS ARE GREEN BY
    CONSTRUCTION (form 18). A single category is never "unsolicited": for
    the document count to be able to diverge from the scope count, there
    MUST be ≥ 2 categories and one of them MUST lie OUTSIDE the expected
    ones. The assertion `scanned_total >= total` is ALWAYS green, including
    when the counter has moved past the filter — so a strict "greater than"
    stands here at the entrance, where an element outside scope DOES exist.
    """

    def _wire(self, *, in_scope, outside):
        """The DEVICE's answer, decompiled by PROD CODE (`parse_scope_census`).

        The input is not assembled by hand from `ScopeCensusObservation`:
        the witness is supplied by the COLLECTOR, and it is the wire that
        must be checked, not the constructor.
        """
        payload = _observation({("OST_Walls", L1): in_scope}).to_dict()
        payload["scanned_total"] = in_scope + outside
        return parse_scope_census(
            payload, _expectation(), _document(), run_id=RUN_ID,
            phase="before")

    def test_an_element_outside_the_scope_is_counted_somewhere(self):
        observed = self._wire(in_scope=1, outside=1)
        assert observed.total == 1
        assert observed.scanned_total == 2
        assert observed.outside_scope == 1
        assert observed.scanned_total > observed.total

    def test_the_emitted_counter_stands_before_the_filter(self):
        """A GUARD OF THE GUARD ITSELF, AND IT READS THE C# TEXT.

        A counter that moved PAST the filter would silently become a second
        name for `total`: all the Python assertions would remain green, and
        the witness would be counting scope. That is why the ORDER in the
        emission is checked.
        """
        code = scope_census_fragment(
            _expectation(), _document(), run_id=RUN_ID, phase="before")
        assert code.index("__kirAcceptanceScanned++") < code.index(
            "!__kirAcceptanceWanted.Contains(__kirAcceptanceCategory)")
        assert code.index("__kirAcceptanceScanned++") < code.index(
            "__kirAcceptanceTotal++")
        assert '{"scanned_total", __kirAcceptanceScanned}' in code

    def test_a_reading_taken_before_this_wave_says_so_and_keeps_its_digest(self):
        """"NOT CAPTURED" AND "ZERO" MUST BE DISTINGUISHED (form 34).

        Evidence captured before this wave arrives WITHOUT the field. It
        MUST still decompile, answer `None` (not `0`), and keep its
        `observation_digest` byte-for-byte — otherwise the journal would
        stop being re-readable. The number below was captured at HEAD
        `d3a00ad`, BEFORE the fix.
        """
        old = _observation({("OST_Walls", L1): 7})
        assert old.scanned_total is None
        assert old.outside_scope is None
        assert "scanned_total" not in old.to_dict()
        assert old.observation_digest == (
            "25997d2b9d983a84a75c79b60b321641"
            "eeb2b9d312be00c919761535a2afc9bd")

        parsed = parse_scope_census(
            old.to_dict(), _expectation(), _document(), run_id=RUN_ID,
            phase="before")
        assert parsed == old

    def test_any_other_extra_field_is_still_refused(self):
        """The optionality of ONE field is not an opening of the wire."""
        payload = _observation({("OST_Walls", L1): 7}).to_dict()
        payload["scanned_extra"] = 1
        with pytest.raises(ScopeCensusError, match="fields differ"):
            parse_scope_census(payload, _expectation(), _document(),
                               run_id=RUN_ID, phase="before")

    def test_a_scan_below_the_scope_is_refused(self):
        """The document count cannot be SMALLER than the scope count — this is not a number."""
        payload = _observation({("OST_Walls", L1): 7}).to_dict()
        payload["scanned_total"] = 6
        with pytest.raises(ScopeCensusError, match="below the in-scope total"):
            parse_scope_census(payload, _expectation(), _document(),
                               run_id=RUN_ID, phase="before")

    def test_the_growth_outside_the_scope_reaches_the_evidence(self):
        """THE WITNESS MUST REACH THE READER, otherwise the fix dies silently.

        The reader here is `AcceptanceEvidence.to_dict()`, that is exactly
        what `acceptance_journal` puts into the durable evidence.
        """
        before = _observation({("OST_Walls", L1): 10}, scanned_total=100)
        after = _observation({("OST_Walls", L1): 11}, phase="after",
                             scanned_total=104)
        evidence = assess_acceptance(_registration(before), after, None)

        # outside scope was 90, became 93 -> three elements nobody asked for
        assert evidence.outside_scope_delta == 3
        assert evidence.to_dict()["outside_scope_delta"] == 3

    def test_the_delta_is_a_note_and_never_a_refusal(self):
        """AND WHAT THIS FIX DOES NOT DO — IS STATED BY A NUMBER, NOT A PROMISE.

        Revit produces more derived elements than authored ones, so a
        refusal here would fail every honest construction. The evidence's
        state does not move from growth outside scope — and this is an
        assertion, not an intention.
        """
        quiet = assess_acceptance(
            _registration(_observation({("OST_Walls", L1): 10},
                                       scanned_total=100)),
            _observation({("OST_Walls", L1): 11}, phase="after",
                         scanned_total=101),
            None)
        noisy = assess_acceptance(
            _registration(_observation({("OST_Walls", L1): 10},
                                       scanned_total=100)),
            _observation({("OST_Walls", L1): 11}, phase="after",
                         scanned_total=901),
            None)
        assert quiet.outside_scope_delta == 0
        assert noisy.outside_scope_delta == 800
        assert quiet.state is noisy.state is AcceptanceState.ACCEPTED
        assert quiet.reason is noisy.reason is AcceptanceReason.MEASURED

    def test_evidence_without_the_witness_keeps_its_key_absent(self):
        """The key is ABSENT when not captured by both phases — `evidence_digest` does not move."""
        evidence = assess_acceptance(
            _registration(_observation({("OST_Walls", L1): 10})),
            _observation({("OST_Walls", L1): 11}, phase="after"),
            None)
        assert evidence.outside_scope_delta is None
        assert "outside_scope_delta" not in evidence.to_dict()

        half = assess_acceptance(
            _registration(_observation({("OST_Walls", L1): 10},
                                       scanned_total=100)),
            _observation({("OST_Walls", L1): 11}, phase="after"),
            None)
        assert half.outside_scope_delta is None
        assert "outside_scope_delta" not in half.to_dict()


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
        from kir.gate_runner import acceptance_gate_body

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

    def test_device_side_census_sorts_ordinally_not_by_culture(self):
        """`OrderBy` without a comparator is a CULTURE-based sort, and under
        ru-RU it does not match Python's ordinal sort in a single position.

        Measured live on 04.08 (the operator's device, `CurrentCulture=ru-RU`,
        the same level names as in «Проект1»)::

            culture=[Основание B.O.]   ordinal=[KIR_GAP_CEIL]   <<< mismatch
            culture=[Уровень 1]        ordinal=[KIR_GAP_CP]     <<< mismatch
            ...
            culture=[KIR_ST_TOP]       ordinal=[Фунд. стена T.O.]
            culture=[OST_Rooms]        ordinal=[OST_RoomSeparationLines]

        `ScopeCensusObservation` requires ORDINAL order
        (`tuple(sorted(set(rows)))` over python strings). So a census
        sorted by culture is rejected — and acceptance fails fail-closed
        either BEFORE the write (`KIR-A002`) or after it
        (`post_read_invalid`). This is exactly what happened on the live
        runs of 04.08, the moment a Cyrillic «Уровень 1» appeared next to
        the Latin `KIR_GAP_*`.

        That is why C# MUST sort EXPLICITLY, ordinally."""
        code = build_scope_census_cs(
            _expectation(), _document(), run_id=RUN_ID, phase="before")
        # Whitespace is collapsed: a line wrap must not hide the comparator
        # and must not break the check.
        flat = " ".join(code.split())
        sites = [flat[i:i + 140] for i in range(len(flat))
                 if flat.startswith("OrderBy(", i)]
        assert sites, "в переписи не осталось ни одной сортировки"
        bare = [s for s in sites if "StringComparer.Ordinal" not in s]
        assert bare == [], bare

    def test_culture_ordered_rows_are_refused(self):
        """The same defect from the data side: a census in ru-RU order
        (Cyrillic before Latin) MUST be rejected."""
        cyrillic, latin = "Уровень 1", "KIR_GAP_CEIL"
        assert sorted([cyrillic, latin]) == [latin, cyrillic]  # python: ordinal
        expectation = replace(
            _expectation(),
            rows=(replace(_expectation().rows[0], level=latin),
                  replace(_expectation().rows[0], level=cyrillic,
                          op_ids=("W2",))),
            op_count=2,
        )
        payload = observation_from_census(
            expectation, _document(),
            {("OST_Walls", latin): 1, ("OST_Walls", cyrillic): 4},
            run_id=RUN_ID, phase="before",
        ).to_dict()
        # ru-RU puts Cyrillic FIRST — exactly what the device returned.
        payload["rows"].sort(key=lambda r: (r["category"],
                                            r["level_name"] != cyrillic))
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
            ground_digest=ground_program(
                _wall_plan(), GROUND_SNAPSHOT).ground_digest,
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
