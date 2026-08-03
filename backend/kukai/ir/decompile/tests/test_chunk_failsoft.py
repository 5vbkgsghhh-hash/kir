# -*- coding: utf-8 -*-
"""Чанковый fail-soft: упавший чанк даёт квитанцию, а не убивает прогон.

Фикстура — пересборка №10 (v16), журнал
``a5_runs/eeff119bd2c34344.state.jsonl``: 28 чанков в плане, 10 отработало,
9 ``Committed`` (2009 элементов), девятый ``RolledBack``, сравнения не было
вовсе, уборка снесла всё построенное.

ПОРЯДОК ТЕСТОВ ЗНАЧИМ. Первые два (``test_01`` / ``test_02``) обязаны быть
ЗЕЛЁНЫМИ И ДО ПРАВКИ: они доказывают, что контракт квитанции и фазовая машина
УЖЕ умеют отказ, и что менять надо ровно одно место — ``raise`` в
``run_idempotence``. Если они краснеют, правка ушла не туда: кто-то полез в
контракты вместо оркестратора.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kukai.ir.a5_recovery import (
    A5JournalError, A5Phase, _validate_transition_proof)
from kukai.ir.contracts import CommitReceipt, RunId

import kir_idempotence as KI


# Квитанция девятого чанка ДОСЛОВНО из живого журнала №10 (v16).
CHUNK9_RECEIPT = {
    "bridge_detail": (
        "transaction commit status: RolledBack | Revit: Error: Не удалось "
        "создать импост витража. Та часть схемы разрезки витража, на которой "
        "он был размещен, больше не существует. [элементы: 11464715] ; Error: "
        "Один или более опорных объектов для выделенного элемента стали "
        "некорректными. [элементы: 11464715]"),
    "bridge_error": True,
    "commit_confirmed": False,
    "commit_status": "RolledBack",
    "element_count": 0,
    "element_ids": [],
    "operation": "rebuild",
    "outcome": "refused_without_commit",
    "program_id": "9643a4773131a339d15f575acb7e0e6e899a04ccb0b5453bfd21f33dcd483737",
    "run_id": "eeff119bd2c34344",
    "schema_version": "a5-commit-receipt/2",
}
RUN_ID = RunId("eeff119bd2c34344")
LIVE_JOURNAL = (pathlib.Path(__file__).resolve().parents[4]
                / "backend" / "data" / "decompile" / "sob62_fas_r23_v16"
                / "a5_runs" / "eeff119bd2c34344.state.jsonl")


_REVISION = "35358:fe1a7154d53dfb6e:9253e8976748904d"


def _valid_rebuilt_proof() -> dict:
    """Доказательство фазы Rebuilt: 9 подтверждённых чанков + 1 отказ."""
    receipts = [
        _confirmed(f"{index:064x}", (str(11457708 + index),), _REVISION)
        for index in range(9)
    ]
    receipts.append(CommitReceipt.from_dict(CHUNK9_RECEIPT))
    return {
        "commit_receipts": [r.to_dict() for r in receipts],
        "program_ids": [r.program_id for r in receipts],
        "created_ids": sorted({i for r in receipts for i in r.element_ids}),
        "document_revision": _REVISION,
    }


def _confirmed(program_id: str, ids: tuple[str, ...], revision: str | None):
    return CommitReceipt(
        run_id=RUN_ID, operation="rebuild", element_ids=ids,
        bridge_error=False, commit_confirmed=True, commit_status="Committed",
        program_id=program_id, document_revision=revision)


class ContractsAlreadyReady(unittest.TestCase):
    """ЗЕЛЁНЫЕ ДО ПРАВКИ — доказательство, что менять надо одно место."""

    def test_01_refusal_receipt_is_decided(self):
        """Живая квитанция отказа — `refused_without_commit` и `decided`."""
        receipt = CommitReceipt.from_dict(CHUNK9_RECEIPT)
        self.assertTrue(receipt.refused_without_commit)
        self.assertTrue(receipt.decided)
        self.assertFalse(receipt.confirmed)
        self.assertEqual(receipt.element_ids, ())

    def test_02_rebuilt_proof_accepts_a_refused_chunk(self):
        """Proof фазы Rebuilt валиден при 9 подтверждённых + 1 отказе."""
        _validate_transition_proof(
            A5Phase.REBUILT, _valid_rebuilt_proof(), run_id=RUN_ID)


class ChunkFailSoft(unittest.TestCase):

    def test_03_denominator_is_untouched(self):
        """Опы отказавшего чанка ОСТАЮТСЯ в знаменателе."""
        report = KI.IdempotenceReport(
            doc_stamp="s", delta_mm=(0.0, 0.0, 0.0), multiset_match=True,
            expected_hash="a", actual_hash="a", total_expected=2732,
            total_matched=2482, raw_exact_pct=90.8, adjusted_exact_pct=90.8,
            per_kind=(), discrepancies=(), datums_skipped=86,
            created_ids=(), cleanup_ok=True, cleanup_detail="",
            atoms_excluded=2469, non_datum_total=5201, dry_run=False,
            chunk_failures=({"kind": "chunk_rebuild_refused",
                             "program_id": "x", "chunk_index": 9,
                             "ops": 250, "op_ids": [],
                             "bridge_detail": "…"},),
        )
        out = report.to_dict()
        self.assertEqual(out["total_expected"], 2732)
        self.assertEqual(out["non_datum_total"], 5201)
        self.assertEqual(out["chunk_failed"], 1)
        self.assertEqual(out["chunk_failed_ops"], 250)
        self.assertEqual(
            out["comparable_coverage"]["chunk_refused_ops"], 250)
        # Отказ виден в общем списке расхождений, а не только в своём углу.
        self.assertTrue(any(row.get("kind") == "chunk_rebuild_refused"
                            for row in out["discrepancies"]))
        self.assertIn("чанков отвергнуты Revit",
                      out["comparable_coverage_summary"])

    def test_04_timeout_stays_fatal(self):
        """Неизвестность НЕ является отказом: fail-soft её не глотает."""
        self.assertFalse(KI._refused_without_commit(
            {"ok": False, "error": "rebuild_exec",
             "bridge_detail": "timeout_unconfirmed"}))
        self.assertFalse(KI._refused_without_commit(
            {"ok": False, "error": "timeout_unconfirmed"}))
        self.assertFalse(KI._refused_without_commit({"ok": False}))
        self.assertFalse(KI._refused_without_commit(None))
        # И ровно один конверт признаётся известным отказом.
        self.assertTrue(KI._refused_without_commit(
            {"ok": False, "error": "rebuild_exec",
             "outcome": "refused_without_commit",
             "bridge_detail": CHUNK9_RECEIPT["bridge_detail"]}))

    def test_05a_refusal_without_revision_cannot_prove_rebuilt(self):
        """Отказ решает эффект, но без revision ещё не доказывает snapshot."""
        proof = {
            "commit_receipts": [
                CommitReceipt.from_dict(CHUNK9_RECEIPT).to_dict()],
            "program_ids": [CHUNK9_RECEIPT["program_id"]],
            "created_ids": [],
            "document_revision": "r",
        }
        with self.assertRaises(A5JournalError):
            _validate_transition_proof(A5Phase.REBUILT, proof, run_id=RUN_ID)

    def test_05b_unfinished_effect_blocks_the_phase(self):
        """Незакрытый write-ahead эффект НЕ пускает фазу вперёд.

        Ровно та мина из 568349f6: отказ, чей эффект не закрыт квитанцией,
        травит журнал задним числом («A5 phase cannot advance with pending
        effects»). Fail-soft обязан оставить её на месте — иначе неизвестность
        начнёт притворяться отказом.

        Доказательства фаз берутся ДОСЛОВНО из живого журнала №10: сочинять
        SnapshotManifest вручную значило бы проверять свою же выдумку.
        """
        if not LIVE_JOURNAL.is_file():
            self.skipTest(f"нет живого журнала: {LIVE_JOURNAL}")
        from kukai.ir.a5_recovery import A5Journal
        proofs = {}
        for line in LIVE_JOURNAL.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("event") == "transition":
                proofs[row["phase"]] = row["proof"]
            if len(proofs) == 2:
                break
        self.assertEqual(set(proofs), {"Prepared", "SnapshotVerified"})
        with tempfile.TemporaryDirectory() as tmp:
            journal = A5Journal.create(
                tmp, run_id=RUN_ID, prepared_proof=proofs["Prepared"])
            journal.transition(
                A5Phase.SNAPSHOT_VERIFIED, proofs["SnapshotVerified"])
            journal.start_effect("rebuild:000000", {
                "kind": "rebuild", "program_id": "b" * 64})
            reopened = pathlib.Path(tmp) / "a5_runs" / f"{RUN_ID.value}.state.jsonl"
            # Proof ВАЛИДНЫЙ (тот же, что принят в test_02) — упереться
            # обязаны именно в незакрытый эффект, а не в форму доказательства.
            with self.assertRaises(Exception) as caught:
                A5Journal.open(reopened).transition(
                    A5Phase.REBUILT, _valid_rebuilt_proof())
            self.assertIn("pending effects", str(caught.exception))

    def test_06_threshold_reads_both_measures(self):
        """Порог берёт максимум из двух долей — по чанкам и по опам."""
        self.assertEqual(KI.MAX_REFUSED_CHUNK_SHARE, 0.25)
        # План v16: 11 больших (10×250 + 215) + 17 solo по одному опу.
        plan = ([{"ops": [{}] * 250} for _ in range(10)]
                + [{"ops": [{}] * 215}]
                + [{"ops": [{}]} for _ in range(17)])
        self.assertEqual(len(plan), 28)
        self.assertEqual(sum(len(p["ops"]) for p in plan), 2732)

        # ЖИВОЙ СЛУЧАЙ: один большой чанк из 28. Прогон обязан доехать.
        chunk_share, op_share, exceeded = KI.refusal_shares(
            [{"ops": 250}], plan)
        self.assertFalse(exceeded)
        self.assertAlmostEqual(op_share, 250 / 2732, places=6)

        # Три больших чанка: по чанкам 10.7% (прошло бы), по опам 27.5% —
        # ловит именно измерение по опам.
        chunk_share, op_share, exceeded = KI.refusal_shares(
            [{"ops": 250}] * 3, plan)
        self.assertLessEqual(chunk_share, KI.MAX_REFUSED_CHUNK_SHARE)
        self.assertGreater(op_share, KI.MAX_REFUSED_CHUNK_SHARE)
        self.assertTrue(exceeded)

        # Восемь solo по одному опу: по опам 0.29% (прошло бы), по чанкам
        # 28.6% — ловит измерение по чанкам.
        chunk_share, op_share, exceeded = KI.refusal_shares(
            [{"ops": 1}] * 8, plan)
        self.assertGreater(chunk_share, KI.MAX_REFUSED_CHUNK_SHARE)
        self.assertLessEqual(op_share, KI.MAX_REFUSED_CHUNK_SHARE)
        self.assertTrue(exceeded)

    def test_07_materializer_stays_host_atomic(self):
        """ТРИПВАЙР: ни одна ref-ссылка не пересекает границу чанка.

        Замер 29.07 на плане v16: 275 ссылок, 0 через границу. Каскад
        «осиротевших» опов не пишется именно потому, что осиротеть нечему;
        если материализатор начнёт резать хост-группу, падать должно ЗДЕСЬ,
        а не на живом Revit через сорок минут.
        """
        plan = [
            {"program_id": "a" * 64, "ops": [
                {"op": "create_wall", "id": "w1"},
                {"op": "create_curtain_grid_line", "id": "g1",
                 "host": {"by": "ref", "value": "w1"}}]},
            {"program_id": "b" * 64, "ops": [
                {"op": "create_wall", "id": "w2"},
                {"op": "set_curtain_panel", "id": "p2",
                 "host": {"by": "ref", "value": "w2"}}]},
        ]
        self.assertEqual(_cross_chunk_refs(plan), [])
        broken = [
            plan[0],
            {"program_id": "c" * 64, "ops": [
                {"op": "create_curtain_grid_line", "id": "g9",
                 "host": {"by": "ref", "value": "w1"}}]},
        ]
        self.assertEqual(_cross_chunk_refs(broken), [("g9", "w1")])

    def test_08_live_journal_replays_as_valid_rebuilt(self):
        """Живой журнал №10: 9 подтверждённых + 1 отказ = валидный Rebuilt."""
        if not LIVE_JOURNAL.is_file():
            self.skipTest(f"нет живого журнала: {LIVE_JOURNAL}")
        receipts, created = [], set()
        revision = None
        for line in LIVE_JOURNAL.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row.get("event") != "effect_finished":
                continue
            raw = row.get("receipt") or {}
            if raw.get("operation") != "rebuild":
                continue
            receipt = CommitReceipt.from_dict(raw)
            receipts.append(receipt)
            created.update(receipt.element_ids)
            if receipt.document_revision:
                revision = receipt.document_revision
        self.assertEqual(len(receipts), 10)
        self.assertEqual(sum(r.confirmed for r in receipts), 9)
        self.assertEqual(sum(r.refused_without_commit for r in receipts), 1)
        self.assertTrue(all(r.decided for r in receipts))
        self.assertEqual(len(created), 2009)
        _validate_transition_proof(A5Phase.REBUILT, {
            "commit_receipts": [r.to_dict() for r in receipts],
            "program_ids": [r.program_id for r in receipts],
            "created_ids": sorted(created),
            "document_revision": revision,
        }, run_id=RUN_ID)


def _cross_chunk_refs(plan):
    """(op_id, ref) для каждой ссылки, чей носитель лежит в ДРУГОМ чанке."""
    owner = {}
    for index, program in enumerate(plan):
        for op in program.get("ops") or ():
            if op.get("id"):
                owner[op["id"]] = index
    out = []
    for index, program in enumerate(plan):
        for op in program.get("ops") or ():
            for ref in _refs(op):
                if owner.get(ref) != index:
                    out.append((op.get("id"), ref))
    return out


def _refs(node):
    if isinstance(node, dict):
        if node.get("by") == "ref":
            yield node.get("value")
        for value in node.values():
            yield from _refs(value)
    elif isinstance(node, list):
        for item in node:
            yield from _refs(item)


if __name__ == "__main__":
    unittest.main()


# ─── задача №25: отказ ОТДЕЛЬНОГО опа внутри ЗАКОММИЧЕННОГО чанка ───────────

class OpRefusalsInsideACommittedChunk(unittest.TestCase):
    """Прогон №11: чанк «Committed», а 37 опов внутри него отказали молча."""

    def _report(self, *, refuse_op_ids=(), unaccounted=False):
        import kir_idempotence as K
        from kukai.ir.decompile.lift import lift_document
        from kukai.ir.decompile.tests.test_idempotence import (
            FakeModelBridge, _COPY_SAFETY, _document, _run)

        reason = ("линия разрезки не принимает штамп прогона (A5 stamp write "
                  "failed: A5 stamp parameter missing) — созданный, но "
                  "непомеченный элемент сломал бы сверку пересборки")

        class Bridge(FakeModelBridge):
            async def rebuild_runner(self, program):
                envelope = await super().rebuild_runner(program)
                hit = [op for op in program.get("ops", [])
                       if str(op.get("id")) in refuse_op_ids]
                if not hit:
                    return envelope
                if unaccounted:
                    # Чанк закоммичен, но исходы не сходятся: опы просто
                    # исчезли из выдачи — ровно класс «молча не создано».
                    for op in hit:
                        envelope["result"].pop(str(op["id"]), None)
                    return {"ok": False, "error": "ops_unaccounted",
                            "bridge_detail": "учтено меньше, чем опов",
                            "ops_total": len(program.get("ops") or ()),
                            "ops_unaccounted": len(hit)}
                for op in hit:
                    envelope["result"].pop(str(op["id"]), None)
                envelope["op_refusals"] = [{
                    "op_id": str(op["id"]), "op_name": op.get("op"),
                    "intent": op.get("host"), "reason": reason} for op in hit]
                return envelope

        doc = _document()
        bridge = Bridge(doc)
        return K, _run(K.run_idempotence(
            list(lift_document(doc)), doc, doc_stamp="s",
            safety=_COPY_SAFETY, rebuild_runner=bridge.rebuild_runner,
            read_executor=bridge.read_executor,
            delete_runner=bridge.delete_runner,
            sweep_runner=bridge.sweep_runner, dry_run=False)), reason

    def test_09_refusals_are_reported_without_moving_the_denominator(self):
        """Отказ виден в отчёте и в discrepancies; знаменатель НЕ трогается."""
        _K, plain, _ = self._report()
        _K, report, reason = self._report(refuse_op_ids={"e9002"})
        out, base = report.to_dict(), plain.to_dict()

        self.assertIsNone(report.error, msg=out)
        self.assertTrue(out["comparison_performed"], "прогон обязан доехать")
        self.assertEqual(out["op_refused"], 1)
        self.assertEqual(out["comparable_coverage"]["op_refused_ops"], 1)
        # ЗНАМЕНАТЕЛЬ НЕПОДВИЖЕН: оп был обещан и не построен.
        for key in ("total_expected", "non_datum_total", "atoms_excluded"):
            self.assertEqual(out[key], base[key], key)
        self.assertLess(out["total_matched"], base["total_matched"])
        # Причина ДОСЛОВНО и в общем списке расхождений.
        row = next(r for r in out["discrepancies"]
                   if r.get("kind") == "op_refused_in_commit")
        self.assertEqual(row["reason"], reason)
        self.assertEqual(row["op_id"], "e9002")
        self.assertIn("program_id", row)
        self.assertIn("опов отвергнуты ВНУТРИ закоммиченных чанков",
                      out["comparable_coverage_summary"])

    def test_10_an_op_without_an_outcome_kills_the_run(self):
        """ОП БЕЗ ИСХОДА — неизвестность: fail-soft её НЕ глотает.

        Смерть обязана быть ТИПИЗИРОВАННОЙ (`ops_unaccounted`), а не
        «internal»: последнее означало бы, что наружу вылетело голое
        исключение контракта, то есть молчаливый обрыв вместо решения.
        Журнальный след неизвестности тот же, что у `timeout_unconfirmed` —
        serving возвращает этот конверт ДО `finish_effect`, поэтому
        write-ahead эффект остаётся висеть (см. test_05b: незакрытый эффект
        не пускает фазу вперёд).
        """
        K, report, _ = self._report(refuse_op_ids={"e9002"}, unaccounted=True)
        self.assertIsNotNone(report.error)
        self.assertEqual(report.error["code"], "ops_unaccounted")
        self.assertFalse(report.to_dict()["comparison_performed"])
        # И конверт неизвестности НЕ является решённым отказом — иначе
        # чанковый fail-soft поехал бы дальше поверх неизвестного состояния.
        self.assertFalse(K._refused_without_commit(
            {"ok": False, "error": "ops_unaccounted"}))
