"""Фаза REBUILT: покрытие плана считает ОБА известных исхода.

ЗАМЕР 28.07, пересборка №4 (артефакт v9, журнал
``a5_runs/64058c8994184790.state.jsonl``): цикл прошёл — 15 программ, 14
закоммичено (1236 элементов), одна изолированная отвергнута квитанцией, — а
прогон умер УЖЕ ПОСЛЕ цикла:

    A5JournalError('rebuild receipts do not cover the complete plan')

``comparison_performed`` так и не случился. Причина: третьему слою — фазовой
машине журнала — про новый исход не рассказали. Проверка полноты плана
считала покрытием ТОЛЬКО коммит-квитанции, а отказ был записан самодельным
словарём, который читатель квитанций пропускал молча.

Закон, который здесь пинуется:

* коммит и отказ покрывают программу ОДИНАКОВО — оба суть ИЗВЕСТНЫЙ исход;
* неизвестность (``timeout_unconfirmed``) не покрывает ничего: её эффект
  вообще не финишируется, и переход к REBUILT обязан падать, как падал;
* строгость сохранена: у каждой программы плана ровно один исход, лишних
  квитанций нет.

Чужая или переставленная квитанция ловится РАНЬШЕ — правилом префикса плана
в ``prepare_rebuild_plan`` (эпоха сбрасывается, её квитанции выходят из
счёта). Это правило существовало до этой волны и не менялось; здесь
проверяется ровно то, что изменилось.
"""
from __future__ import annotations

import glob
import hashlib
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from kukai.ir import serving
from kukai.ir.a5_recovery import (
    A5Journal, A5JournalError, A5Phase, _validate_transition_proof)
from kukai.ir.contracts import CommitReceipt, RunId

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
        """ПРЕД-СОСТОЯНИЕ: на старом законе это падало «unconfirmed receipt»."""

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
        """Закрытые rollback без revision всё ещё не образуют snapshot proof."""

        with self.assertRaises(A5JournalError):
            _validate_transition_proof(
                A5Phase.REBUILT, _proof([_refusal(PROGRAM_A)], []),
                run_id=RUN_ID)

    def test_all_refused_is_a_closed_zero_coverage_execution(self) -> None:
        """Execution state не зависит от наличия хотя бы одного success."""

        _validate_transition_proof(
            A5Phase.REBUILT,
            _proof([_refusal(PROGRAM_A, revision=REVISION)], []),
            run_id=RUN_ID,
        )

    def test_an_undecided_receipt_is_still_refused(self) -> None:
        """Неизвестность отличается от отказа наличием витнесов."""

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
        """Отказ документ не двигает — требовать от него ревизию нечестно."""

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
    """Журнал на диске + адаптер восстановления, без моста."""

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
        from kukai.ir.decompile.tests.test_serving_idempotence import (
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

        # Ревизия документа — состояние, а не константа: после пересборки
        # она одна, после уборки обязана вернуться к снимочной.
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
        """timeout_unconfirmed: эффект не закрыт — дыра в покрытии."""

        with tempfile.TemporaryDirectory() as tmp:
            box = _Recovery(tmp)
            box.effect("rebuild:000000", PROGRAM_A,
                       _commit(PROGRAM_A, ("100",)).to_dict())
            box.effect("rebuild:000001", PROGRAM_B)      # без квитанции
            _run(box.adapter.prepare_rebuild_plan([PROGRAM_A, PROGRAM_B]))
            with self.assertRaises(A5JournalError) as caught:
                _run(box.adapter.after_rebuilt(["100"]))
            self.assertIn("complete plan", str(caught.exception))

    def test_created_ids_are_witnessed_only_by_commits(self) -> None:
        """Отказ витнесов не несёт — и не имеет права их «покрывать»."""

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
    """Журнал прогона №4 писался переходной формой — он обязан читаться."""

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
        """Живой журнал №4: 15 программ, 14 коммитов + 1 отказ = покрытие."""

        matches = glob.glob(
            "backend/data/decompile/sob62_fas_r23_v9/a5_runs/*.state.jsonl")
        if not matches:
            self.skipTest("журнал прогона №4 недоступен на этой машине")
        with tempfile.TemporaryDirectory() as tmp:
            copy = pathlib.Path(tmp) / pathlib.Path(matches[0]).name
            shutil.copy(matches[0], copy)
            journal = A5Journal.open(copy)          # replay зелёный
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
    """Весь низ машины против прогона-с-отказами и каскадом.

    ЗАМЕР 28.07: №4 умер на покрытии плана (починено), №5 — на RECONCILED
    («run-prefix reconciliation disagrees with commit receipts»). Дальше по
    машине те же предположения «квитанция = коммит» и «удаление = витнес»
    стоят ещё в трёх местах: CLEANUP_PREVIEWED сверяет перепись с
    created_ids, COMPLETED требует, чтобы витнесы удаления ПОКРЫВАЛИ каждый
    созданный id, и replay сверяет фазы между собой.

    Здесь весь путь проходится целиком: REBUILT → RECONCILED → COMPARED →
    CLEANUP_PREVIEWED → COMPLETED, с одним отказом изолированной программы и
    с элементом, исчезнувшим каскадом до уборки.
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

            # КАСКАД: "101" исчез вместе со своим хозяином — витнеса удаления
            # у него нет, и в переписи его тоже нет.
            box.effect("delete:000000", PROGRAM_A, CommitReceipt(
                run_id=RUN_ID, operation="delete", element_ids=("100",),
                bridge_error=False, commit_confirmed=True,
                commit_status="Committed").to_dict())
            box.live_ids = []
            box.revision = box.snapshot_revision   # уборка вернула документ
            _run(box.adapter.after_cleanup(
                created, retain=False, cleanup_ok=True,
                cleanup_detail="deleted 1/2; каскад"))
            self.assertIs(box.journal.state.phase, A5Phase.COMPLETED)

    def test_a_surviving_created_element_still_fails_cleanup(self) -> None:
        """Строгость не потеряна: выживший созданный элемент — провал."""

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
            box.live_ids = ["101"]          # выжил
            with self.assertRaises(A5JournalError):
                _run(box.adapter.after_cleanup(
                    created, retain=False, cleanup_ok=True,
                    cleanup_detail="deleted 1/2"))

    def test_the_completed_journal_replays_from_zero(self) -> None:
        """Итоговый журнал обязан перечитываться целиком — иначе следующий
        прогон на этом штампе не стартует."""

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
            reopened = A5Journal.open(box.journal.path)     # replay с нуля
            self.assertIs(reopened.state.phase, A5Phase.COMPLETED)
            self.assertFalse(reopened.state.pending_effects)
