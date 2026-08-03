"""Write-ahead, fsynced, tamper-evident acceptance journal."""
from __future__ import annotations

import json
import stat
from pathlib import Path
from unittest import mock

import pytest

from kukai.ir.acceptance import derive_expectation, expectation_categories
from kukai.ir.acceptance_evidence import (
    AcceptanceRegistration,
    assess_acceptance,
)
from kukai.ir.acceptance_journal import (
    ACCEPTANCE_EVIDENCE_DIR_ENV,
    AcceptanceJournal,
    AcceptanceJournalError,
    configured_evidence_root,
)
from kukai.ir.acceptance_live import observation_from_census
from kukai.ir.acceptance_mutation import derive_mutation_expectation
from kukai.ir.compiler import plan_program
from kukai.ir.contracts import DocumentFingerprint
from kukai.ir.outcome import (
    AcceptanceState,
    WitnessState,
    independently_assessed,
    write_committed,
)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


L1 = "Этаж 1"


def _parts(run_id: str = "a" * 32):
    plan = plan_program({
        "ir_version": "1.0",
        "ops": [{
            "op": "create_wall",
            "id": "W1",
            "p0_mm": [0, 0],
            "p1_mm": [6000, 0],
            "level": {"by": "name", "value": L1},
        }],
    })
    expectation = derive_expectation(plan)
    document = DocumentFingerprint.from_dict(
        GROUND_SNAPSHOT["__document_fingerprint"])
    before = observation_from_census(
        expectation, document, {("OST_Walls", L1): 10}, run_id=run_id,
        phase="before")
    registration = AcceptanceRegistration(
        run_id=run_id,
        plan_digest=plan.plan_digest,
        revit_version="2026",
        expectation=expectation,
        mutation_expectation=derive_mutation_expectation(plan),
        document=document,
        categories=expectation_categories(expectation),
        before=before,
        mutation_before=None,
    )
    after = observation_from_census(
        expectation, document, {("OST_Walls", L1): 11}, run_id=run_id,
        phase="after")
    evidence = assess_acceptance(registration, after, None)
    outcome = independently_assessed(
        write_committed(witness=WitnessState.SATISFIED),
        AcceptanceState.ACCEPTED,
    )
    return registration, evidence, outcome


def test_registration_is_fsynced_before_terminal_evidence(tmp_path: Path):
    registration, evidence, outcome = _parts()
    with mock.patch("kukai.ir.acceptance_journal.os.fsync",
                    wraps=__import__("os").fsync) as fsync:
        journal = AcceptanceJournal.create(tmp_path, registration)
        assert journal.path.read_text(encoding="utf-8").count("\n") == 1
        assert stat.S_IMODE(journal.path.stat().st_mode) == 0o600
        assert not journal.state.finalized
        journal.finalize(outcome, evidence=evidence)
    # file + directory for prepare, file for terminal
    assert fsync.call_count >= 3

    reopened = AcceptanceJournal.open(journal.path)
    assert reopened.state.finalized
    assert reopened.state.registration_digest == (
        registration.registration_digest)
    assert reopened.state.final_payload is not None
    assert reopened.state.final_payload["evidence_digest"] == (
        evidence.evidence_digest)


def test_second_terminal_record_is_forbidden(tmp_path: Path):
    registration, evidence, outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    journal.finalize(outcome, evidence=evidence)
    with pytest.raises(AcceptanceJournalError, match="already finalized"):
        journal.finalize(outcome, evidence=evidence)


def test_evidence_from_another_registration_is_forbidden(tmp_path: Path):
    registration, _evidence, outcome = _parts()
    _other_registration, other_evidence, _other_outcome = _parts("b" * 32)
    journal = AcceptanceJournal.create(tmp_path, registration)
    with pytest.raises(AcceptanceJournalError, match="another registration"):
        journal.finalize(outcome, evidence=other_evidence)


def test_modified_prepared_payload_breaks_checksum(tmp_path: Path):
    registration, _evidence, _outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    row = json.loads(journal.path.read_text(encoding="utf-8"))
    row["registration"]["plan_digest"] = "b" * 64
    journal.path.write_text(
        json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    with pytest.raises(AcceptanceJournalError, match="modified"):
        AcceptanceJournal.open(journal.path)


def test_torn_tail_is_not_silently_accepted(tmp_path: Path):
    registration, _evidence, _outcome = _parts()
    journal = AcceptanceJournal.create(tmp_path, registration)
    with journal.path.open("ab") as sink:
        sink.write(b'{"partial":')
    with pytest.raises(AcceptanceJournalError, match="torn tail"):
        AcceptanceJournal.open(journal.path)


def test_explicit_empty_configuration_disables_sink(monkeypatch):
    monkeypatch.setenv(ACCEPTANCE_EVIDENCE_DIR_ENV, "   ")
    assert configured_evidence_root() is None
    monkeypatch.setenv(ACCEPTANCE_EVIDENCE_DIR_ENV, "/tmp/kir-evidence-test")
    assert configured_evidence_root() == Path("/tmp/kir-evidence-test")


def test_evidence_root_belongs_to_the_installation_it_was_imported_from(
    monkeypatch, tmp_path: Path,
):
    """Any source checkout owns its evidence — not one absolute deployment.

    The previous form named ``/opt/kukai-rebuild1`` literally, so every neutral
    install refused each write with ``KIR-A005`` while only that box worked.
    """

    monkeypatch.delenv(ACCEPTANCE_EVIDENCE_DIR_ENV, raising=False)
    install = tmp_path / "some-other-install"
    (install / "backend" / "kukai").mkdir(parents=True)
    with mock.patch("kukai.ir.install_paths._INSTALL_ROOT", install):
        assert configured_evidence_root() == (
            install / "backend" / "data" / "evidence" / "kir_acceptance")


def test_a_packaged_import_owns_no_evidence_root(monkeypatch, tmp_path: Path):
    """No ``backend/kukai`` tree ⇒ no writable installation to claim.

    ``prepare_acceptance`` turns this into a pre-effect refusal; borrowing a
    neighbour's directory would be the one thing worse than refusing.
    """

    monkeypatch.delenv(ACCEPTANCE_EVIDENCE_DIR_ENV, raising=False)
    with mock.patch("kukai.ir.install_paths._INSTALL_ROOT", tmp_path):
        assert configured_evidence_root() is None
