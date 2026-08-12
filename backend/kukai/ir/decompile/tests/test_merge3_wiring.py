"""Провод `merge3`: страж между дельтой и документом, в который она ляжет.

Слой `merge3` пролежал на складе 420 строками и 20 тестами, и все 20
проверяли ЧТО он считает: T-MERGE, симметрию, типы конфликтов, мост по
source-id.  Ни один не проверял, доходит ли до него хоть один живой вход, —
поэтому склад и не был виден изнутри тестов.  Этот файл проверяет ровно
второе, и только его.

Место провода выбрано не по вкусу, а по НАЗВАННОЙ ДЫРЕ: дельта-пересборка
сама пишет о себе «дельта верна, только если в документе уже стоит здание
базы; проверить это офлайн компилятор не может».  Это единственная точка,
где живая пересборка способна дать МОЛЧАЛИВО НЕВЕРНЫЙ исход — построить
разницу поверх документа, который тем временем правил оператор, и ничего об
этом не сказать.  Свежий разбор того же документа делает условие
измеримым.

Четыре закона:

* **инертность** — без `current_doc_stamp` пересборка обязана дать ТЕ ЖЕ
  чанки и тот же отчёт, что и до этой волны, при любом положении флага;
* **конфликт — ОТКАЗ, а не предупреждение** — две правки одного и того же
  означают, что дельта сотрёт чужую работу; пережить это имеет право только
  тот, кто явно сказал `allow_conflicts`;
* **«проверено» пишется только там, где проверено** — совпало состояние
  документа с базой, и только тогда;
* **сравнение цели с собой запрещено** — оно всегда даёт «конфликтов нет»,
  и это ложное «проверено» хуже честного «не проверено».
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import tempfile
import unittest
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_merge3_wiring_queue.jsonl"))

from kukai.ir import serving  # noqa: E402
from kukai.ir.decompile.merge3 import merge_enabled  # noqa: E402
from kukai.ir.decompile.merge_guard import (  # noqa: E402
    GUARD_SCHEMA,
    VERDICT_CLEAN,
    VERDICT_CONFIRMED,
    VERDICT_CONFLICTING,
    guard_refusal,
    guard_report,
)
from kukai.ir.decompile.tests.test_merkle import _fold, _grid_building  # noqa: E402

_FLAG = "KUKAI_IR_MERGE3"
_REBUILD = "KUKAI_IR_REBUILD"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _ShimLLM:
    _revit_version = "2026"

    async def _repair_code(self, *a: Any, **k: Any) -> None:
        return None


async def _never_bridge(method: str, params: dict) -> dict:  # pragma: no cover
    raise AssertionError("мост не смеет вызываться в сухом прогоне")


# ───────────────────────────────────────────────────────────────────────────
# Сам страж: три исхода обязаны РАЗЛИЧАТЬСЯ
# ───────────────────────────────────────────────────────────────────────────


class GuardVerdicts(unittest.TestCase):
    def test_flag_is_off_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            self.assertFalse(merge_enabled())

    def test_an_untouched_document_confirms_the_precondition(self) -> None:
        base = _fold(_grid_building(floors=3))
        report = guard_report(
            base, _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=3, extra_furniture_on_floor=1)))
        self.assertTrue(report["ok"])
        self.assertEqual(report["verdict"], VERDICT_CONFIRMED)
        self.assertTrue(report["identical_to_base"])
        self.assertEqual(report["conflicts_total"], 0)

    def test_a_document_that_moved_without_arguing_is_not_confirmed(
            self) -> None:
        """`diverged_clean` — не «проверено». Условие базы НЕ выполнено."""

        report = guard_report(
            _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=3, extra_furniture_on_floor=1)),
            _fold(_grid_building(floors=3, stretch_wall_on_floor=2)))
        self.assertEqual(report["verdict"], VERDICT_CLEAN)
        self.assertFalse(report["identical_to_base"])
        self.assertEqual(report["conflicts_total"], 0)
        self.assertGreater(report["auto_merged"], 0)

    def test_two_edits_of_the_same_thing_are_named_conflicts(self) -> None:
        report = guard_report(
            _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=2)),
            _fold(_grid_building(floors=4)))
        self.assertEqual(report["verdict"], VERDICT_CONFLICTING)
        self.assertGreater(report["conflicts_total"], 0)
        self.assertTrue(report["conflicts"],
                        "конфликты посчитаны, но ни один не назван — по "
                        "отчёту нельзя понять, ЧТО именно сотрут")
        self.assertEqual(
            sum(report["conflicts_by_kind"].values()),
            report["conflicts_total"])

    def test_the_full_count_survives_the_sample_cut(self) -> None:
        """Обрезан СПИСОК, а не ЧИСЛО: обрезанное число лгало бы о здании."""

        report = guard_report(
            _fold(_grid_building(floors=3)),
            _fold(_grid_building(floors=2)),
            _fold(_grid_building(floors=4)))
        self.assertLessEqual(report["conflicts_shown"],
                             report["conflicts_total"])
        self.assertEqual(len(report["conflicts"]), report["conflicts_shown"])

    def test_a_refusal_is_not_a_clean_merge(self) -> None:
        report = guard_report({"kind": "building"}, {}, {})
        self.assertFalse(report["ok"])
        self.assertEqual(report["schema"], GUARD_SCHEMA)
        self.assertNotIn("verdict", report,
                         "сломанный страж выдал вердикт — «посчитать не "
                         "удалось» стало неотличимо от «конфликтов нет»")
        self.assertFalse(guard_refusal(ValueError("х"))["ok"])


# ───────────────────────────────────────────────────────────────────────────
# Живой вход: `handle_revit_rebuild` ← `api/admin_kir.py::rebuild`
# ───────────────────────────────────────────────────────────────────────────


class ServingWiring(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["KUKAI_KIR_DECOMPILE"] = "stage2"
        os.environ.pop("KUKAI_IR_ATOM_ESCROW", None)
        self._dev = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self._tmp = TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)

    def tearDown(self) -> None:
        self._dev.stop()
        self._tmp.cleanup()
        for flag in (_FLAG, _REBUILD, "KUKAI_KIR_DECOMPILE"):
            os.environ.pop(flag, None)

    def _persist(self, stamp: str, tree) -> None:
        directory = self.root / stamp
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tree.json").write_text(
            json.dumps(tree), encoding="utf-8")

    def _out_dir(self, stamp: str) -> str:
        return str(self.root / stamp)

    def _rebuild(self, args: dict) -> dict:
        with mock.patch.object(serving, "_decompile_out_dir", self._out_dir):
            return _run(serving.handle_revit_rebuild(
                {"dry_run": True, **args}, _ShimLLM(), _never_bridge))

    def _triple(self, *, ours_floors: int = 3, theirs_extra: bool = True,
                ours_extra: bool = False) -> None:
        self._persist("base", _fold(_grid_building(floors=3)))
        self._persist("now", _fold(_grid_building(
            floors=ours_floors,
            extra_furniture_on_floor=1 if ours_extra else None)))
        self._persist("target", _fold(_grid_building(
            floors=3,
            extra_furniture_on_floor=1 if theirs_extra else None,
            stretch_wall_on_floor=None if theirs_extra else 2)))

    # -- инертность ---------------------------------------------------------
    def test_without_the_current_stamp_nothing_changes(self) -> None:
        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1"}, clear=False):
            os.environ.pop(_FLAG, None)
            off = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            on = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        self.assertTrue(off["ok"], msg=off)
        self.assertTrue(on["ok"], msg=on)
        self.assertEqual(off["chunks_total"], on["chunks_total"])
        self.assertNotIn("merge_guard", off["delta"])
        self.assertNotIn("merge_guard", on["delta"],
                         "флаг включили — и страж заговорил сам, без "
                         "current_doc_stamp: это уже не приложение, а "
                         "изменение поведения пересборки")
        self.assertNotIn("precondition_verified", off["delta"])

    # -- отказы -------------------------------------------------------------
    def test_the_guard_with_the_flag_off_is_refused_by_name(self) -> None:
        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1"}, clear=False):
            os.environ.pop(_FLAG, None)
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "merge_guard_disabled")
        self.assertNotIn("chunks_total", result,
                         "отказ протащил за собой пересборку — просили "
                         "проверку, а построили бы вслепую")

    def test_a_current_stamp_without_a_base_is_meaningless(self) -> None:
        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild(
                {"doc_stamp": "target", "current_doc_stamp": "now"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "args")

    def test_comparing_the_target_with_itself_is_refused(self) -> None:
        """Ложное «проверено» хуже честного «не проверено»."""

        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "target"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "args")

    def test_a_missing_current_decompile_is_refused(self) -> None:
        self._triple()
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "нет-такого"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "no_current_decompile")

    # -- три исхода на живом входе -----------------------------------------
    def test_an_untouched_document_turns_the_precondition_into_a_measurement(
            self) -> None:
        """То, ради чего всё: обещание становится проверкой."""

        self._triple()
        self._persist("now", _fold(_grid_building(floors=3)))
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now"})
        self.assertTrue(result["ok"], msg=result)
        delta = result["delta"]
        self.assertTrue(delta["precondition_verified"])
        self.assertEqual(delta["merge_guard"]["verdict"], VERDICT_CONFIRMED)
        self.assertIn("проверено", delta["precondition_ru"])
        self.assertIn("chunks_total", result,
                      "проверка прошла, а пересборка всё равно отказана — "
                      "страж обязан пропускать то, что подтвердил")

    def test_a_clean_divergence_builds_but_does_not_claim_verification(
            self) -> None:
        self._triple(ours_extra=True, theirs_extra=False)
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now"})
        self.assertTrue(result["ok"], msg=result)
        delta = result["delta"]
        self.assertEqual(delta["merge_guard"]["verdict"], VERDICT_CLEAN)
        self.assertFalse(delta["precondition_verified"],
                         "документ ушёл от базы, а отчёт называет условие "
                         "проверенным — это ровно то враньё, ради которого "
                         "страж и заведён")
        self.assertIn("НЕ здание", delta["precondition_ru"])

    def test_conflicts_refuse_the_rebuild_instead_of_overwriting(self) -> None:
        """Опровергающий тест волны: без стража это тихая перезапись."""

        self._persist("base", _fold(_grid_building(floors=3)))
        self._persist("now", _fold(_grid_building(floors=2)))
        self._persist("target", _fold(_grid_building(floors=4)))
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            guarded = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now"})
            blind = self._rebuild(
                {"doc_stamp": "target", "base_doc_stamp": "base"})
        self.assertFalse(guarded["ok"])
        self.assertEqual(guarded["error"], "merge_conflicts")
        self.assertEqual(guarded["merge_guard"]["verdict"], VERDICT_CONFLICTING)
        self.assertNotIn("chunks_total", guarded)
        # А без стража — та же пересборка проходит и молчит. Это и есть
        # молчаливо неверный исход, который волна закрывает.
        self.assertTrue(blind["ok"], msg=blind)
        self.assertGreater(blind["chunks_total"], 0)
        self.assertNotIn("merge_guard", blind["delta"])

    def test_conflicts_may_be_accepted_but_never_hidden(self) -> None:
        self._persist("base", _fold(_grid_building(floors=3)))
        self._persist("now", _fold(_grid_building(floors=2)))
        self._persist("target", _fold(_grid_building(floors=4)))
        with mock.patch.dict(os.environ, {_REBUILD: "1", _FLAG: "1"}):
            result = self._rebuild({
                "doc_stamp": "target", "base_doc_stamp": "base",
                "current_doc_stamp": "now", "allow_conflicts": True})
        self.assertTrue(result["ok"], msg=result)
        guard = result["delta"]["merge_guard"]
        self.assertGreater(guard["conflicts_total"], 0,
                           "согласие стёрло конфликты из отчёта — согласие "
                           "касается решения, а не измерения")
        self.assertFalse(result["delta"]["precondition_verified"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
