"""Ordering contract for the regular-write independent acceptance session."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from kukai.ir.acceptance import derive_expectation
from kukai.ir.acceptance_evidence import AcceptanceReason
from kukai.ir.acceptance_journal import AcceptanceJournal
from kukai.ir.acceptance_live import observation_from_census
from kukai.ir.acceptance_probe import ACCEPTANCE_OBSERVATION_SCHEMA_VERSION
from kukai.ir.acceptance_runtime import (
    AcceptanceRuntimeError,
    prepare_acceptance,
)
from kukai.ir.compiler import plan_program
from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.outcome import (
    AcceptanceState,
    WitnessState,
    independently_assessed,
    write_committed,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge


RUN_ID = "c" * 32


def _document():
    return DocumentFingerprint.from_dict(
        GROUND_SNAPSHOT["__document_fingerprint"])


def _wall_plan():
    return plan_program({
        "ir_version": "1.0",
        "ops": [{
            "op": "create_wall",
            "id": "W1",
            "p0_mm": [0, 0],
            "p1_mm": [6000, 0],
            "level": {"by": "element_id", "value": 42},
        }],
    })


def _payload(plan, census, *, phase):
    expectation = derive_expectation(
        plan,
        level_names_by_id={
            str(row["id"]): row["name"]
            for row in GROUND_SNAPSHOT["levels"]
        },
    )
    scope = observation_from_census(
        expectation, _document(), census, run_id=RUN_ID, phase=phase)
    return {"result": {
        "schema_version": ACCEPTANCE_OBSERVATION_SCHEMA_VERSION,
        "run_id": RUN_ID,
        "phase": phase,
        "plan_digest": plan.plan_digest,
        "document_digest": _document().digest,
        "revit_version": "2026",
        "scope_census": scope.to_dict(),
        "mutations": None,
    }}


@pytest.mark.asyncio
async def test_pre_read_and_fsync_precede_write_authority(tmp_path: Path):
    plan = _wall_plan()
    calls = []

    async def reader(_code, phase, _timeout):
        calls.append(phase)
        if phase == "acceptance_before":
            return _payload(
                plan, {("OST_Walls", "Этаж 1"): 10}, phase="before")
        return _payload(
            plan, {("OST_Walls", "Этаж 1"): 11}, phase="after")

    with mock.patch(
            "kukai.ir.acceptance_runtime.new_acceptance_run_id",
            return_value=RUN_ID):
        session = await prepare_acceptance(
            plan, GROUND_SNAPSHOT, _document(), reader,
            revit_version="2026",
            timeout_ms=1000, evidence_root=tmp_path)

    assert calls == ["acceptance_before"]
    assert session.journal.path.exists()
    assert not session.journal.state.finalized
    assert session.registration.before is not None
    assert session.registration.expectation.rows[0].level == "Этаж 1"

    evidence = await session.assess_after(reader, timeout_ms=1000)
    assert calls == ["acceptance_before", "acceptance_after"]
    assert evidence.state is AcceptanceState.ACCEPTED
    outcome = independently_assessed(
        write_committed(witness=WitnessState.SATISFIED),
        session.outcome_state(evidence, WitnessState.SATISFIED),
    )
    session.finalize(outcome, evidence=evidence)
    reopened = AcceptanceJournal.open(session.journal.path)
    assert reopened.state.finalized
    assert session.evidence_wire(evidence)["journal"]["durable"] is True


@pytest.mark.asyncio
async def test_pre_read_failure_refuses_before_journal_or_write(tmp_path: Path):
    async def reader(_code, _phase, _timeout):
        return {"ok": False, "message": "bridge down"}

    with mock.patch(
            "kukai.ir.acceptance_runtime.new_acceptance_run_id",
            return_value=RUN_ID):
        with pytest.raises(AcceptanceRuntimeError) as caught:
            await prepare_acceptance(
                _wall_plan(), GROUND_SNAPSHOT, _document(), reader,
                revit_version="2026",
                timeout_ms=1000, evidence_root=tmp_path)
    assert caught.value.code == "KIR-A001"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_missing_durable_sink_refuses_before_write():
    plan = _wall_plan()
    calls = []

    async def reader(_code, _phase, _timeout):
        calls.append(_phase)
        return _payload(plan, {}, phase="before")

    with mock.patch(
            "kukai.ir.acceptance_runtime.new_acceptance_run_id",
            return_value=RUN_ID), mock.patch(
            "kukai.ir.acceptance_runtime.configured_evidence_root",
            return_value=None):
        with pytest.raises(AcceptanceRuntimeError) as caught:
            await prepare_acceptance(
                plan, GROUND_SNAPSHOT, _document(), reader,
                revit_version="2026", timeout_ms=1000)
    assert caught.value.code == "KIR-A005"
    assert calls == []


@pytest.mark.asyncio
async def test_reader_exception_is_a_named_pre_effect_failure(tmp_path: Path):
    async def reader(_code, _phase, _timeout):
        raise TimeoutError("private bridge detail")

    with mock.patch(
            "kukai.ir.acceptance_runtime.new_acceptance_run_id",
            return_value=RUN_ID):
        with pytest.raises(AcceptanceRuntimeError) as caught:
            await prepare_acceptance(
                _wall_plan(), GROUND_SNAPSHOT, _document(), reader,
                revit_version="2026", timeout_ms=1000,
                evidence_root=tmp_path)
    assert caught.value.code == "KIR-A001"
    assert caught.value.detail.endswith("TimeoutError")
    assert "private bridge detail" not in caught.value.detail


@pytest.mark.asyncio
async def test_post_reader_exception_becomes_inconclusive_evidence(
    tmp_path: Path,
):
    plan = _wall_plan()

    async def reader(_code, phase, _timeout):
        if phase == "acceptance_before":
            return _payload(plan, {}, phase="before")
        raise TimeoutError("bridge timeout")

    with mock.patch(
            "kukai.ir.acceptance_runtime.new_acceptance_run_id",
            return_value=RUN_ID):
        session = await prepare_acceptance(
            plan, GROUND_SNAPSHOT, _document(), reader,
            revit_version="2026", timeout_ms=1000,
            evidence_root=tmp_path)
    evidence = await session.assess_after(reader, timeout_ms=1000)
    assert evidence.state is AcceptanceState.INCONCLUSIVE
    assert evidence.reason is AcceptanceReason.POST_READ_UNAVAILABLE


@pytest.mark.asyncio
async def test_post_read_failure_is_explicitly_inconclusive(tmp_path: Path):
    plan = _wall_plan()

    async def reader(_code, phase, _timeout):
        if phase == "acceptance_before":
            return _payload(plan, {}, phase="before")
        return {"state": "timeout_unconfirmed"}

    with mock.patch(
            "kukai.ir.acceptance_runtime.new_acceptance_run_id",
            return_value=RUN_ID):
        session = await prepare_acceptance(
            plan, GROUND_SNAPSHOT, _document(), reader,
            revit_version="2026",
            timeout_ms=1000, evidence_root=tmp_path)
    evidence = await session.assess_after(reader, timeout_ms=1000)
    assert evidence.state is AcceptanceState.INCONCLUSIVE
    assert evidence.reason is AcceptanceReason.POST_READ_UNAVAILABLE


@pytest.mark.asyncio
async def test_exact_id_move_is_independently_measured(tmp_path: Path):
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [{
            "op": "move_elements",
            "id": "M1",
            "targets": [{"by": "element_id", "value": 100}],
            "delta_mm": [0, 0, 500],
        }],
    })
    calls = []
    bridge = PassingAcceptanceBridge(plan)
    bridge.snapshot = GROUND_SNAPSHOT

    async def reader(code, phase, _timeout):
        calls.append(phase)
        return bridge.dispatch(
            lambda _code, stage: (_ for _ in ()).throw(AssertionError(stage)),
            code,
            phase,
        )

    with mock.patch(
            "kukai.ir.acceptance_runtime.new_acceptance_run_id",
            return_value=RUN_ID):
        session = await prepare_acceptance(
            plan, GROUND_SNAPSHOT, _document(), reader,
            revit_version="2026",
            timeout_ms=1000, evidence_root=tmp_path)
    evidence = await session.assess_after(reader, timeout_ms=1000)
    assert calls == ["acceptance_before", "acceptance_after"]
    assert evidence.state is AcceptanceState.ACCEPTED
    assert evidence.reason is AcceptanceReason.MEASURED
    assert evidence.mutation_verdict is not None
    assert evidence.mutation_verdict.checked_claims == 1
