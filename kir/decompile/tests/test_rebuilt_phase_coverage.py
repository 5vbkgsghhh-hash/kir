"""The REBUILT phase: plan coverage counts BOTH known outcomes.

MEASUREMENT 28.07, rebuild #4 (artifact v9, journal
``a5_runs/64058c8994184790.state.jsonl``): the cycle passed — 15 programs, 14
committed (1236 elements), one isolated one rejected by a receipt — but the
run died RIGHT AFTER the cycle:

    A5JournalError('rebuild receipts do not cover the complete plan')

``comparison_performed`` never happened. The reason: the third layer — the journal's
phase machine — was never told about the new outcome. The plan-completeness check
counted ONLY commit receipts as coverage, and the refusal was recorded in a homemade
dict that the receipt reader silently skipped.

The law being pinned here:

* a commit and a refusal cover the program EQUALLY — both are a KNOWN outcome;
* the unknown (``timeout_unconfirmed``) covers nothing: its effect
  never finishes at all, and the transition to REBUILT must fail, as it did;
* strictness is preserved: every program in the plan has exactly one outcome, no
  extra receipts.

A foreign or reordered receipt is caught EARLIER — by the plan-prefix rule
in ``prepare_rebuild_plan`` (the epoch resets, its receipts drop out of the
count). This rule existed before this wave and was not changed; what is checked here
is exactly what changed.
"""
from __future__ import annotations

import glob
import hashlib
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from kir import serving
from kir.a5_recovery import (
    A5Journal, A5JournalError, A5Phase, _validate_transition_proof)
from kir.contracts import CommitReceipt, RunId

RUN_ID = RunId("0123456789abcdef")
REVISION = "rev-after-chunk-2"
PROGRAM_A = "a" * 64
PROGRAM_B = "b" * 64
BRIDGE_DETAIL = (
    'transaction commit status: RolledBack | Revit: Error: Не удалось '
    'сформировать тип "ATR_Панель витража с решеткой : Интегрированная '
    'Вентиляционная решетка". [элементы: 11409473, 11409491]')


def _commit(program_id: str, ids: tuple[str, ...],
            revision: str | None = REVISION) -> CommitReceipt:
    return CommitReceipt(
        run_id=RUN_ID, operation="rebuild", element_ids=ids,
        bridge_error=False, commit_confirmed=True, commit_status="Committed",
        program_id=program_id, document_revision=revision)


def _refusal(
    program_id: str,
    *,
    revision: str | None = None,
) -> CommitReceipt:
    return CommitReceipt(
        run_id=RUN_ID, operation="rebuild", element_ids=(),
        bridge_error=True, commit_confirmed=False, commit_status="RolledBack",
        program_id=program_id, document_revision=revision)


def _proof(receipts, created, revision=REVISION, with_program_ids=True):
    proof = {
        "commit_receipts": [receipt.to_dict() for receipt in receipts],
        "created_ids": list(created),
        "document_revision": revision,
    }
    if with_program_ids:
        proof["program_ids"] = [receipt.program_id for receipt in receipts]
    return proof


class TheRebuiltProofAcceptsBothKnownOutcomes(unittest.TestCase):
    def test_a_refusal_receipt_is_legal_evidence(self) -> None:
        """PRE-STATE: under the old law this failed with "unconfirmed receipt"."""

        _validate_transition_proof(
            A5Phase.REBUILT,
            _proof([_commit(PROGRAM_A, ("100", "101")), _refusal(PROGRAM_B)],
                   ["100", "101"]),
            run_id=RUN_ID)

    def test_a_plain_commit_only_proof_still_passes(self) -> None:
        _validate_transition_proof(
            A5Phase.REBUILT,
            _proof([_commit(PROGRAM_A, ("100",))], ["100"]),
            run_id=RUN_ID)

    def test_an_all_refused_proof_without_revision_witness_is_refused(self) -> None:
        """Closed rollbacks without a revision still do not form a snapshot proof."""

        with self.assertRaises(A5JournalError):
            _validate_transition_proof(
                A5Phase.REBUILT, _proof([_refusal(PROGRAM_A)], []),
                run_id=RUN_ID)

    def test_all_refused_is_a_closed_zero_coverage_execution(self) -> None:
        """Execution state does not depend on the presence of even one success."""

        _validate_transition_proof(
            A5Phase.REBUILT,
            _proof([_refusal(PROGRAM_A, revision=REVISION)], []),
            run_id=RUN_ID,
        )

    def test_an_undecided_receipt_is_still_refused(self) -> None:
        """The unknown differs from a refusal by the presence of witnesses."""

        murky = CommitReceipt(
            run_id=RUN_ID, operation="rebuild", element_ids=("100",),
            bridge_error=True, commit_confirmed=False,
            commit_status="Unknown", program_id=PROGRAM_B)
        self.assertFalse(murky.decided)
        with self.assertRaises(A5JournalError):
            _validate_transition_proof(
                A5Phase.REBUILT,
                _proof([_commit(PROGRAM_A, ("100",)), murky], ["100"]),
                run_id=RUN_ID)

    def test_the_final_revision_comes_from_the_last_receipt_that_has_one(
            self) -> None:
        """A refusal does not move the document — requiring a revision from it would be dishonest."""

        _validate_transition_proof(
            A5Phase.REBUILT,
            _proof([_commit(PROGRAM_A, ("100",)), _refusal(PROGRAM_B)],
                   ["100"]),
            run_id=RUN_ID)

    def test_a_wrong_final_revision_is_still_caught(self) -> None:
        with self.assertRaises(A5JournalError):
            _validate_transition_proof(
                A5Phase.REBUILT,
                _proof([_commit(PROGRAM_A, ("100",), revision="rev-old"),
                        _refusal(PROGRAM_B)],
                       ["100"], revision="rev-new"),
                run_id=RUN_ID)


class _Recovery:
    """A journal on disk + a recovery adapter, without the bridge."""

    def __init__(self, tmp: str):
        self.stamp_scope, self.stamp_prefix = serving._a5_stamp_scope(
            "docA", RUN_ID)
        self.journal = A5Journal.create(
            tmp, run_id=RUN_ID, prepared_proof={
                "doc_stamp_sha256": hashlib.sha256(b"docA").hexdigest(),
                "request_digest": "b" * 64,
                "stamp_prefix": self.stamp_prefix,
                "document_fingerprint": serving.DocumentFingerprint(
                    title="Проект — КОПИЯ A5", path_name="",
                    project_uid="uid-a5").to_dict(),
            })
        from kir.decompile.tests.test_serving_idempotence import (
            _persist_decompile)
        _persist_decompile(tmp)
        manifest = serving._load_a5_snapshot_manifest(
            tmp, doc_stamp="docA",
            document_fingerprint=serving.DocumentFingerprint(
                title="Проект — КОПИЯ A5", path_name="",
                project_uid="uid-a5"))
        self.journal.transition(A5Phase.SNAPSHOT_VERIFIED, {
            "snapshot_manifest": manifest.to_dict()})
        self.live_ids: list[str] = []

        async def _preview():
            # ONE builder for this wire shape (task #69, 31.07 postmortem):
            # this fixture used to hand-type the envelope, hardcoded the
            # schema-version literal, and — separately — dropped the v3
            # ``types_found*`` triple when that version shipped. Both are
            # the same disease (a fixture describing what the OTHER side
            # SHOULD produce instead of importing that contract), so both
            # are fixed the same way: build via ``serving.build_sweep_payload``,
            # which reads ``_A5_SWEEP_SCHEMA_VERSION`` live and always emits
            # every required field. This run builds only instances (no
            # ``create_type``), hence no ``types_found_ids``.
            ids = sorted(self.live_ids)
            return serving.build_sweep_payload(
                prefix=self.stamp_prefix, found_ids=ids, remaining_ids=ids,
                wrap_result=True)

        # The document revision is a state, not a constant: after a rebuild
        # it is one thing, after cleanup it must return to the snapshot one.
        self.snapshot_revision = manifest.revision_proof.fingerprint
        self.revision = REVISION

        async def _revision():
            return self.revision

        self.adapter = serving._A5Recovery(
            self.journal, mock.Mock(ensure_held=mock.AsyncMock()),
            stamp_prefix=self.stamp_prefix,
            preview_runner=_preview,
            sweep_runner=mock.AsyncMock(),
            revision_runner=_revision)

    def effect(self, effect_id: str, program_id: str, receipt=None) -> None:
        self.journal.start_effect(effect_id, {
            "kind": "rebuild", "program_id": program_id})
        if receipt is not None:
            self.journal.finish_effect(effect_id, receipt)


def _run(coro):
    import asyncio
    return asyncio.run(coro)


class TheCompletePlanCountsRefusalsAsCoverage(unittest.TestCase):
    def test_a_commit_plus_a_refusal_covers_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            box = _Recovery(tmp)
            box.effect("rebuild:000000", PROGRAM_A,
                       _commit(PROGRAM_A, ("100", "101")).to_dict())
            box.effect("rebuild:000001", PROGRAM_B, {
                **_refusal(PROGRAM_B).to_dict(),
                "outcome": "refused_without_commit",
                "bridge_detail": BRIDGE_DETAIL})
            box.live_ids = ["100", "101"]
            _run(box.adapter.prepare_rebuild_plan([PROGRAM_A, PROGRAM_B]))
            _run(box.adapter.after_rebuilt(["100", "101"]))
            self.assertIn(box.journal.state.phase,
                          (A5Phase.REBUILT, A5Phase.RECONCILED))
            proof = box.journal.state.proofs[A5Phase.REBUILT]
            self.assertEqual(proof["program_ids"], [PROGRAM_A, PROGRAM_B])
            self.assertEqual(len(proof["commit_receipts"]), 2)

    def test_an_unfinished_effect_still_blocks_the_phase(self) -> None:
        """timeout_unconfirmed: the effect is not closed — a hole in coverage."""

        with tempfile.TemporaryDirectory() as tmp:
            box = _Recovery(tmp)
            box.effect("rebuild:000000", PROGRAM_A,
                       _commit(PROGRAM_A, ("100",)).to_dict())
            box.effect("rebuild:000001", PROGRAM_B)      # without a receipt
            _run(box.adapter.prepare_rebuild_plan([PROGRAM_A, PROGRAM_B]))
            with self.assertRaises(A5JournalError) as caught:
                _run(box.adapter.after_rebuilt(["100"]))
            self.assertIn("complete plan", str(caught.exception))

    def test_created_ids_are_witnessed_only_by_commits(self) -> None:
        """A refusal carries no witnesses — and has no right to "cover" them."""

        with tempfile.TemporaryDirectory() as tmp:
            box = _Recovery(tmp)
            box.effect("rebuild:000000", PROGRAM_A,
                       _commit(PROGRAM_A, ("100",)).to_dict())
            box.effect("rebuild:000001", PROGRAM_B,
                       _refusal(PROGRAM_B).to_dict())
            _run(box.adapter.prepare_rebuild_plan([PROGRAM_A, PROGRAM_B]))
            with self.assertRaises(A5JournalError) as caught:
                _run(box.adapter.after_rebuilt(["100", "999"]))
            self.assertIn("disagree with durable commit receipts",
                          str(caught.exception))


class TheInterimRefusalShapeIsStillReadable(unittest.TestCase):
    """The journal of run #4 was written in the transitional form — it must still be readable."""

    INTERIM_ROW = {
        "outcome": "refused_without_commit",
        "program_id": "f" * 64,
        "bridge_detail": BRIDGE_DETAIL,
    }

    def test_the_interim_row_is_lifted_into_a_receipt(self) -> None:
        receipt = serving._receipt_from_journal(self.INTERIM_ROW, RUN_ID)
        self.assertIsNotNone(receipt)
        self.assertTrue(receipt.refused_without_commit)
        self.assertTrue(receipt.decided)
        self.assertFalse(receipt.confirmed)
        self.assertEqual(receipt.program_id, "f" * 64)

    def test_a_cleanup_receipt_is_not_mistaken_for_a_commit(self) -> None:
        self.assertIsNone(serving._receipt_from_journal(
            {"outcome": "reconciled_after_unknown_commit"}, RUN_ID))
        self.assertIsNone(serving._receipt_from_journal({}, RUN_ID))

    def test_the_real_run_four_journal_now_covers_its_plan(self) -> None:
        """Live journal #4: 15 programs, 14 commits + 1 refusal = coverage."""

        matches = glob.glob(
            "backend/data/decompile/sob62_fas_r23_v9/a5_runs/*.state.jsonl")
        if not matches:
            self.skipTest("журнал прогона №4 недоступен на этой машине")
        with tempfile.TemporaryDirectory() as tmp:
            copy = pathlib.Path(tmp) / pathlib.Path(matches[0]).name
            shutil.copy(matches[0], copy)
            journal = A5Journal.open(copy)          # replay green
            decided = confirmed = refused = 0
            for effect_id, raw in journal.state.effect_receipts.items():
                if not effect_id.startswith("rebuild"):
                    continue
                receipt = serving._receipt_from_journal(
                    raw, journal.state.run_id)
                self.assertIsNotNone(
                    receipt, f"{effect_id} перестал читаться как квитанция")
                decided += receipt.decided
                confirmed += receipt.confirmed
                refused += receipt.refused_without_commit
            self.assertEqual((decided, confirmed, refused), (15, 14, 1))


if __name__ == "__main__":
    unittest.main()


class EveryPhaseBelowRebuiltSurvivesARunWithRefusals(unittest.TestCase):
    """The whole bottom of the machine against a run with refusals and a cascade.

    MEASUREMENT 28.07: #4 died on plan coverage (fixed), #5 — on RECONCILED
    ("run-prefix reconciliation disagrees with commit receipts"). Further down
    the machine the same assumptions "receipt = commit" and "deletion = witness"
    stand in three more places: CLEANUP_PREVIEWED checks the census against
    created_ids, COMPLETED requires that deletion witnesses COVER every
    created id, and replay checks the phases against each other.

    Here the whole path is walked in full: REBUILT → RECONCILED → COMPARED →
    CLEANUP_PREVIEWED → COMPLETED, with one refusal of an isolated program and
    with an element that disappeared in a cascade before cleanup.
    """

    METRICS = {
        "comparison_performed": True, "multiset_match": True,
        "total_expected": 2, "total_actual": 2, "total_matched": 2,
        "total_extra": 0,
    }

    def test_the_whole_tail_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            box = _Recovery(tmp)
            created = ["100", "101"]
            box.effect("rebuild:000000", PROGRAM_A,
                       _commit(PROGRAM_A, ("100", "101")).to_dict())
            box.effect("rebuild:000001", PROGRAM_B, {
                **_refusal(PROGRAM_B).to_dict(),
                "outcome": "refused_without_commit",
                "bridge_detail": BRIDGE_DETAIL})
            box.live_ids = list(created)
            _run(box.adapter.prepare_rebuild_plan([PROGRAM_A, PROGRAM_B]))
            _run(box.adapter.after_rebuilt(created))
            self.assertIs(box.journal.state.phase, A5Phase.RECONCILED)

            _run(box.adapter.after_compared({
                **self.METRICS, "per_kind": [], "discrepancies": [],
                "isolated_failed": 1, "isolated_failed_ops": 1,
            }))
            self.assertIs(box.journal.state.phase, A5Phase.COMPARED)

            _run(box.adapter.before_cleanup(created, retain=False))
            self.assertIs(box.journal.state.phase, A5Phase.CLEANUP_PREVIEWED)

            # CASCADE: "101" disappeared together with its host — it has no
            # deletion witness, and it is not in the census either.
            box.effect("delete:000000", PROGRAM_A, CommitReceipt(
                run_id=RUN_ID, operation="delete", element_ids=("100",),
                bridge_error=False, commit_confirmed=True,
                commit_status="Committed").to_dict())
            box.live_ids = []
            box.revision = box.snapshot_revision   # cleanup returned the document
            _run(box.adapter.after_cleanup(
                created, retain=False, cleanup_ok=True,
                cleanup_detail="deleted 1/2; каскад"))
            self.assertIs(box.journal.state.phase, A5Phase.COMPLETED)

    def test_a_surviving_created_element_still_fails_cleanup(self) -> None:
        """Strictness is not lost: a surviving created element is a failure."""

        with tempfile.TemporaryDirectory() as tmp:
            box = _Recovery(tmp)
            created = ["100", "101"]
            box.effect("rebuild:000000", PROGRAM_A,
                       _commit(PROGRAM_A, ("100", "101")).to_dict())
            box.live_ids = list(created)
            _run(box.adapter.prepare_rebuild_plan([PROGRAM_A]))
            _run(box.adapter.after_rebuilt(created))
            _run(box.adapter.after_compared({
                **self.METRICS, "per_kind": [], "discrepancies": []}))
            _run(box.adapter.before_cleanup(created, retain=False))
            box.effect("delete:000000", PROGRAM_A, CommitReceipt(
                run_id=RUN_ID, operation="delete", element_ids=("100",),
                bridge_error=False, commit_confirmed=True,
                commit_status="Committed").to_dict())
            box.live_ids = ["101"]          # survived
            with self.assertRaises(A5JournalError):
                _run(box.adapter.after_cleanup(
                    created, retain=False, cleanup_ok=True,
                    cleanup_detail="deleted 1/2"))

    def test_the_completed_journal_replays_from_zero(self) -> None:
        """The final journal must be re-readable in full — otherwise the next
        run on this stamp will not start."""

        with tempfile.TemporaryDirectory() as tmp:
            box = _Recovery(tmp)
            created = ["100", "101"]
            box.effect("rebuild:000000", PROGRAM_A,
                       _commit(PROGRAM_A, ("100", "101")).to_dict())
            box.effect("rebuild:000001", PROGRAM_B, {
                **_refusal(PROGRAM_B).to_dict(),
                "outcome": "refused_without_commit",
                "bridge_detail": BRIDGE_DETAIL})
            box.live_ids = list(created)
            _run(box.adapter.prepare_rebuild_plan([PROGRAM_A, PROGRAM_B]))
            _run(box.adapter.after_rebuilt(created))
            _run(box.adapter.after_compared({
                **self.METRICS, "per_kind": [], "discrepancies": []}))
            _run(box.adapter.before_cleanup(created, retain=False))
            box.effect("delete:000000", PROGRAM_A, CommitReceipt(
                run_id=RUN_ID, operation="delete", element_ids=("100", "101"),
                bridge_error=False, commit_confirmed=True,
                commit_status="Committed").to_dict())
            box.live_ids = []
            box.revision = box.snapshot_revision
            _run(box.adapter.after_cleanup(
                created, retain=False, cleanup_ok=True,
                cleanup_detail="deleted 2/2"))
            reopened = A5Journal.open(box.journal.path)     # replay from scratch
            self.assertIs(reopened.state.phase, A5Phase.COMPLETED)
            self.assertFalse(reopened.state.pending_effects)
