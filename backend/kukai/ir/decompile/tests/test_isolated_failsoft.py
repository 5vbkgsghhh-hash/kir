"""Отказ ИЗОЛИРОВАННОЙ программы — квитанция, а не обвал прогона.

ЗАМЕР 28.07, живая пересборка №3 фасада SOB6.2 (артефакт v8, журнал
``a5_runs/f3aec7f67ce941ce.state.jsonl``):

* шесть больших чанков Committed — 242+228+234+250+250+22 = **1226
  элементов**; изоляция сработала, отложенный отказ до них не добрался;
* solo №1 (носитель 10006233, панель «Вентиляционная решетка») — Committed;
* solo №2 (носитель 10006947, панель «Интегрированная Вентиляционная
  решетка») — RolledBack с «Не удалось сформировать тип», и на этом
  оркестратор УБИЛ ВЕСЬ ПРОГОН: ``comparison_performed=false``, а уборка
  снесла 1099 уже построенных элементов.

Один носитель из 1200 стоил всей пересборки — при том что радиус его отказа
доказан ПОСТРОЕНИЕМ: изолированная программа содержит ровно одну хост-группу,
соседей в ней нет.

Карваут строго по этому множеству. Отказ ОБЫЧНОГО чанка остаётся фатальным:
там радиус равен всей программе, и «поедем дальше» означало бы молча потерять
до 250 опов.

Почему отказ вообще случается (эксперименты E6/E7 лида): Revit сегодня не
формирует эту решётку в 100-мм ячейке, а оригинал жив потому, что
существующие элементы не пере-формируются. Лифт ничего не потерял — мы честно
просим то, что в модели есть.
"""
from __future__ import annotations

import unittest
from typing import Any, Mapping

import kir_idempotence as K
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.tests.test_idempotence import (
    FakeModelBridge, _COPY_SAFETY, _document, _run)


ISOLATED_SOURCE = "9002"          # вторая стена — её и изолируем
BRIDGE_DETAIL = (
    'transaction commit status: RolledBack | Revit: Error: Не удалось '
    'сформировать тип "ATR_Панель витража с решеткой : Интегрированная '
    'Вентиляционная решетка". [элементы: 11401364, 11402544]')


class _RefusingBridge(FakeModelBridge):
    """Мост, который отвергает программы с заданными опами — как живой Revit."""

    def __init__(self, document, *, refuse_op_ids: set, **kwargs):
        super().__init__(document, **kwargs)
        self.refuse_op_ids = refuse_op_ids
        self.refused_programs = 0

    async def rebuild_runner(self, program: Mapping[str, Any]) -> dict:
        ids = {str(op.get("id")) for op in program.get("ops", [])}
        if ids & self.refuse_op_ids:
            self.refused_programs += 1
            self.rebuild_calls += 1
            return {"ok": False, "error": "rebuild_exec",
                    "message": BRIDGE_DETAIL}
        return await super().rebuild_runner(program)


def _report(*, isolate, refuse_source):
    doc = _document()
    leaves = list(lift_document(doc))
    bridge = _RefusingBridge(doc, refuse_op_ids={"e" + refuse_source})
    report = _run(K.run_idempotence(
        leaves, doc, doc_stamp="s", safety=_COPY_SAFETY,
        rebuild_runner=bridge.rebuild_runner,
        read_executor=bridge.read_executor,
        delete_runner=bridge.delete_runner,
        sweep_runner=bridge.sweep_runner, dry_run=False,
        isolate_source_ids=isolate))
    return report, bridge


class AnIsolatedRefusalIsAReceipt(unittest.TestCase):
    def test_without_isolation_a_refusal_kills_the_run(self) -> None:
        """ПРЕД-СОСТОЯНИЕ прогона №3: один отказ — и сравнения нет вовсе."""

        report, _bridge = _report(isolate=None, refuse_source=ISOLATED_SOURCE)
        self.assertIsNotNone(report.error)
        self.assertEqual(report.error["code"], "rebuild_failed")
        self.assertIsNone(report.multiset_match)
        self.assertFalse(report.to_dict()["comparison_performed"])

    def test_an_isolated_refusal_keeps_the_run_alive(self) -> None:
        report, bridge = _report(
            isolate=[ISOLATED_SOURCE], refuse_source=ISOLATED_SOURCE)
        self.assertIsNone(report.error, msg=report.to_dict())
        self.assertTrue(report.to_dict()["comparison_performed"])
        self.assertIsNotNone(report.multiset_match)
        self.assertEqual(bridge.refused_programs, 1)
        self.assertEqual(len(report.isolated_failures), 1)

    def test_the_receipt_carries_the_source_and_the_verbatim_detail(
            self) -> None:
        report, _bridge = _report(
            isolate=[ISOLATED_SOURCE], refuse_source=ISOLATED_SOURCE)
        receipt = report.isolated_failures[0]
        self.assertEqual(receipt["kind"], "isolated_rebuild_refused")
        self.assertIn(ISOLATED_SOURCE, receipt["source_ids"])
        self.assertIn("e" + ISOLATED_SOURCE, receipt["op_ids"])
        self.assertEqual(receipt["bridge_detail"], BRIDGE_DETAIL,
                         "ответ моста ДОСЛОВНО — резать его значит гонять "
                         "Revit заново ради одной строки")
        self.assertIn("program_id", receipt)

    def test_the_receipt_reaches_the_report_dict(self) -> None:
        report, _bridge = _report(
            isolate=[ISOLATED_SOURCE], refuse_source=ISOLATED_SOURCE)
        data = report.to_dict()
        self.assertEqual(data["isolated_failed"], 1)
        self.assertEqual(data["isolated_failed_ops"], 1)
        self.assertTrue(any(
            item.get("kind") == "isolated_rebuild_refused"
            for item in data["discrepancies"]),
            "квитанция обязана быть в общем списке расхождений")
        self.assertEqual(
            data["comparable_coverage"]["isolated_refused_ops"], 1)
        self.assertIn("изолированных программ отвергнуты Revit",
                      data["comparable_coverage_summary"])

    def test_the_refused_ops_stay_in_the_denominator(self) -> None:
        """Непостроенное не имеет права поднимать процент."""

        report, _bridge = _report(
            isolate=[ISOLATED_SOURCE], refuse_source=ISOLATED_SOURCE)
        data = report.to_dict()
        self.assertEqual(data["non_datum_total"], report.non_datum_total)
        self.assertLess(report.total_matched, report.non_datum_total)
        self.assertIsNotNone(data["comparable_coverage_pct"])
        self.assertLess(data["comparable_coverage_pct"], 100.0)


class AnOrdinaryChunkRefusalStaysFatal(unittest.TestCase):
    def test_a_refusal_outside_the_isolated_set_is_still_fatal(self) -> None:
        """Закон не тупим: у обычного чанка радиус — вся программа."""

        report, _bridge = _report(isolate=[ISOLATED_SOURCE],
                                  refuse_source="9001")
        self.assertIsNotNone(report.error)
        self.assertEqual(report.error["code"], "rebuild_failed")
        self.assertIsNone(report.multiset_match)

    def test_an_empty_isolation_set_changes_nothing(self) -> None:
        report, _bridge = _report(isolate=[], refuse_source=ISOLATED_SOURCE)
        self.assertIsNotNone(report.error)
        self.assertEqual(report.error["code"], "rebuild_failed")


class TheIsolatedProgramMapIsBuiltFromComposition(unittest.TestCase):
    def test_a_program_is_isolated_by_its_ops_not_by_its_ordinal(self) -> None:
        materialized = [
            {"ops": [{"id": "e100"}, {"id": "e101"}]},
            {"ops": [{"id": "e9002"}]},
        ]
        planned = [{"program_id": "A"}, {"program_id": "B"}]
        receipts = K._isolated_programs(
            materialized, planned, frozenset({"9002"}))
        self.assertEqual(set(receipts), {"B"})
        self.assertEqual(receipts["B"]["source_ids"], ["9002"])
        self.assertEqual(receipts["B"]["ops"], 1)

    def test_no_isolation_means_no_receipts(self) -> None:
        self.assertEqual(
            K._isolated_programs([{"ops": [{"id": "e1"}]}],
                                 [{"program_id": "A"}], frozenset()), {})

    def test_the_hosted_children_travel_inside_the_receipt(self) -> None:
        """Изолируется ГРУППА: в квитанции — все опы, а не только хозяин."""

        materialized = [{"ops": [{"id": "e9002"}, {"id": "e9101"}]}]
        planned = [{"program_id": "A"}]
        receipts = K._isolated_programs(
            materialized, planned, frozenset({"9002"}))
        self.assertEqual(receipts["A"]["ops"], 2)
        self.assertEqual(receipts["A"]["op_ids"], ["e9002", "e9101"])


class TheBridgeDetailIsNotTruncated(unittest.TestCase):
    def test_the_serving_envelope_yields_the_revit_text_not_the_code(
            self) -> None:
        """У конверта serving `error` — это КОД, улика лежит в bridge_detail."""

        self.assertEqual(
            K._bridge_detail({"ok": False, "error": "rebuild_exec",
                              "bridge_detail": BRIDGE_DETAIL}),
            BRIDGE_DETAIL)

    def test_a_message_field_is_taken_verbatim(self) -> None:
        self.assertEqual(
            K._bridge_detail({"ok": False, "message": BRIDGE_DETAIL}),
            BRIDGE_DETAIL)

    def test_a_long_detail_survives_whole(self) -> None:
        long_detail = "x" * 5000
        self.assertEqual(
            len(K._bridge_detail({"message": long_detail})), 5000)

    def test_an_unknown_shape_still_says_something(self) -> None:
        self.assertIn("42", K._bridge_detail({"weird": 42}))


if __name__ == "__main__":
    unittest.main()


class ADefiniteRefusalClosesItsWriteAheadEffect(unittest.TestCase):
    """Определённый отказ — известный исход, а не «неизвестный эффект».

    Незакрытый эффект роняет СЛЕДУЮЩЕЕ чтение журнала («A5 phase cannot
    advance with pending effects»), то есть отказ одной программы отравлял
    бы прогон задним числом — ровно поперёк мягкому продолжению.
    Неизвестность (`timeout_unconfirmed`) по-прежнему остаётся висеть: там
    Revit мог зафиксировать, и сметать это молча нельзя.
    """

    def _drive(self, exec_result):
        import hashlib
        import tempfile
        from unittest import mock

        from kukai.ir import serving
        from kukai.ir.decompile.tests.test_serving_idempotence import (
            _ShimLLM, _never_bridge, _persist_decompile, _revision_after_chunk)

        fingerprint = serving.DocumentFingerprint(
            title="Проект — КОПИЯ A5", path_name="C:/copy.rvt",
            project_uid="uid-1")
        run_id = serving.RunId("0123456789abcdef")
        stamp_scope, stamp_prefix = serving._a5_stamp_scope("docA", run_id)
        lease = mock.Mock()
        lease.ensure_held = mock.AsyncMock()
        program = {
            "ir_version": "1.0", "program_id": "a" * 64,
            "ops": [{"op": "create_wall", "id": "W1",
                     "level": {"by": "element_id", "value": 100},
                     "type": {"by": "element_id", "value": 5001}}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            _persist_decompile(tmp)
            manifest = serving._load_a5_snapshot_manifest(
                tmp, doc_stamp="docA", document_fingerprint=fingerprint)
            journal = serving.A5Journal.create(
                tmp, run_id=run_id, prepared_proof={
                    "doc_stamp_sha256": hashlib.sha256(
                        b"docA").hexdigest(),
                    "request_digest": "b" * 64,
                    "stamp_prefix": stamp_prefix,
                    "document_fingerprint": fingerprint.to_dict(),
                })
            journal.transition(serving.A5Phase.SNAPSHOT_VERIFIED, {
                "snapshot_manifest": manifest.to_dict()})
            compiled = mock.Mock(ok=True, csharp="compiled-csharp",
                                 diagnostics=[])
            with (mock.patch("kukai.ir.compiler.compile_rebuild_chunk",
                             return_value=compiled),
                  mock.patch.object(
                      serving, "_run_declarative",
                      new=mock.AsyncMock(return_value=exec_result))):
                rebuild, *_rest = serving._a5_runners(
                    _ShimLLM(), _never_bridge, "2026",
                    stamp_scope=stamp_scope, stamp_prefix=stamp_prefix,
                    document_fingerprint=fingerprint, journal=journal,
                    lease=lease, revision_runner=_revision_after_chunk)
                result = _run(rebuild(program))
            return result, dict(journal.state.pending_effects)

    def test_an_explicit_rollback_leaves_no_pending_effect(self) -> None:
        result, pending = self._drive({
            "ok": False, "error": "stale_or_failed",
            "message": BRIDGE_DETAIL})
        self.assertFalse(result["ok"])
        self.assertEqual(result["bridge_detail"], BRIDGE_DETAIL)
        self.assertEqual(pending, {},
                         "определённый отказ обязан закрыть свой эффект")

    def test_an_unconfirmed_timeout_still_leaves_the_effect_pending(
            self) -> None:
        result, pending = self._drive({
            "ok": False, "state": "timeout_unconfirmed"})
        self.assertFalse(result["ok"])
        self.assertTrue(pending,
                        "неизвестный исход обязан остаться неизвестным")


class TheCleanupVerdictComesFromTheStampCensus(unittest.TestCase):
    """Каскадно удалённый элемент — не потеря уборки.

    ЗАМЕР 28.07 (прогон №4, артефакт v9): создано 1236, поштучных витнесов
    удаления 1224, недосчитано РОВНО 12 — все с одним ответом «элемент не
    найден (модель изменилась после grounding)». Ячейка витража уходит
    вместе со своим носителем, поэтому её id к своей очереди уже не
    существует. Уборка объявила себя неуспешной и вдобавок отбросила весь
    чанк целиком: 1108/1236.

    Финальная перепись штампа того же прогона (квитанция sweep:000000):
    ``found_count 0, remaining_count 0, witnesses_complete true`` — в модели
    не осталось ничего нашего. Перепись отвечает на настоящий вопрос
    уборки, поштучный проход — на более узкий.
    """

    def test_a_zero_census_is_readable(self) -> None:
        self.assertEqual(
            K._stamp_census({"ok": True, "result": {
                "witnesses_complete": True,
                "remaining": 0, "remaining_ids": []}}),
            {"remaining": 0, "remaining_ids": []})

    def test_a_non_empty_census_is_not_overridden(self) -> None:
        census = K._stamp_census({"ok": True, "result": {
            "witnesses_complete": True,
            "remaining": 2, "remaining_ids": ["11409473", "11409491"]}})
        self.assertEqual(census["remaining"], 2)

    def test_an_incomplete_census_is_no_evidence_at_all(self) -> None:
        for payload in (
            {"ok": True, "result": {"remaining": 0, "remaining_ids": []}},
            {"ok": True, "result": {"witnesses_complete": True,
                                    "remaining": 0}},
            {"ok": True, "result": {"witnesses_complete": True,
                                    "remaining": 1, "remaining_ids": []}},
            {"ok": False, "result": {"witnesses_complete": True,
                                     "remaining": 0, "remaining_ids": []}},
            {"ok": True},
        ):
            with self.subTest(payload=payload):
                self.assertIsNone(K._stamp_census(payload))

    def test_the_real_run_four_sweep_receipt_proves_a_clean_model(
            self) -> None:
        """Квитанция уборки прогона №4 — дословно с диска."""

        import glob
        import json as _json

        matches = glob.glob(
            "backend/data/decompile/sob62_fas_r23_v9/a5_runs/*.state.jsonl")
        if not matches:
            self.skipTest("журнал прогона №4 недоступен на этой машине")
        sweep = None
        for line in open(matches[0], encoding="utf-8"):
            row = _json.loads(line)
            if (row.get("event") == "effect_finished"
                    and str(row.get("effect_id", "")).startswith("sweep")):
                sweep = row["receipt"]
        self.assertIsNotNone(sweep, "финальной переписи в журнале нет")
        self.assertEqual(sweep["remaining_count"], 0)
        self.assertEqual(sweep["found_count"], 0)
        self.assertTrue(sweep["witnesses_complete"])
        self.assertTrue(sweep["confirmed"])
