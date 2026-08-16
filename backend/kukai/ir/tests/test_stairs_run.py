"""ВТОРОЙ МАРШ УЖЕ СТОЯЩЕЙ ЛЕСТНИЦЫ — что этот файл стережёт.

ЧИСЛО, РАДИ КОТОРОГО ВОЛНА (дом владельца `LEN_AR_ME_R24`):

    всего лестниц 19 · выразимо до волны 2 (10.5 %) · маршей на лестницу
    1м:2 · 2м:4 · 3м:2 · 4м:10 · 5м:1 — МОДА ЧЕТЫРЕ МАРША

`create_stairs` строит лестницу и РОВНО ОДИН марш; площадка садится на уже
стоящую лестницу; второго марша не было вовсе. Марш+площадка выразимы, а
марш+площадка+марш — нет: дыра в ЯЗЫКЕ, державшая жилой дом невыразимым на
89.5 %.

🔴 ЖИВЬЁМ НИ ОДНОГО ПРОГОНА, И ЭТО НАЗВАНО, А НЕ УМОЛЧАНО. 15.08 `create_stairs`
на настоящем доме заблокировала поток Ревита модальным окном, которое некому
нажать. Здесь доказывается КОМПИЛЯЦИЯ (ворота 6/6) и ФОРМА эмиссии, а не
постройка. Строка в `tool_doc.UNPROVEN` несёт ту же причину.
"""

from __future__ import annotations

import unittest

from kukai.ir import spec
from kukai.ir.compiler import compile_program
from kukai.ir.tests import fixtures

OP = "create_stairs_run"
STAIRS = {"by": "element_id", "value": 4242}


def _op(**over):
    op = {"op": OP, "id": "RN1", "stairs": STAIRS,
          "p0_mm": [0.0, 0.0], "p1_mm": [3000.0, 0.0],
          "base_elevation_mm": 1800.0}
    op.update(over)
    return op


def _prog(*ops):
    return {"ir_version": "1.0", "ops": list(ops)}


def _emit(ver="2023", **over):
    out = compile_program(_prog(_op(**over)), revit_version=ver)
    assert out.ok, [d.message_ru for d in (out.diagnostics or [])]
    return out.csharp


class ОпСобираетсяНаШестиВерсиях(unittest.TestCase):
    """Ветвления по версии у этого опа НЕТ — и это ЗАМЕР, а не надежда:
    `CreateStraightRun(Document, ElementId, Line, StairsRunJustification)`
    существует на всех шести с 2013 года (компиляция 15.08)."""

    def test_все_шесть_версий(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(ver=ver):
                out = compile_program(_prog(_op()), revit_version=ver)
                self.assertTrue(out.ok, [d.message_ru
                                         for d in (out.diagnostics or [])])

    def test_эмиссия_одинакова_на_всех_версиях(self):
        """Версионной ветки нет — значит и текст обязан совпасть.
        Расхождение здесь означало бы, что ветка появилась незамеченной."""
        texts = {ver: _emit(ver) for ver in spec.REVIT_VERSIONS}
        first = texts["2021"]
        for ver, text in texts.items():
            self.assertEqual(text, first, f"{ver}: эмиссия разошлась")


class ФабрикаИПривязка(unittest.TestCase):

    def test_зовётся_именно_CreateStraightRun(self):
        self.assertIn("StairsRun.CreateStraightRun(doc,", _emit())

    def test_привязка_уезжает_ИМЕНЕМ_ЧЛЕНА_а_не_числом(self):
        """Канон требует отдавать в C# имя члена enum: тогда авторитетом
        становятся сборки Revit, а опечатка не собирается вовсе."""
        for word, member in (("center", "Center"), ("left", "Left"),
                             ("right", "Right")):
            with self.subTest(word=word):
                cs = _emit(justification=word)
                self.assertIn(f"StairsRunJustification.{member}", cs)

    def test_умолчание_это_center(self):
        self.assertIn("StairsRunJustification.Center", _emit())


class ОбластьПравкиОткрываетсяНаСтоящейЛестнице(unittest.TestCase):
    """`InvalidOperationException` у `CreateStraightRun` дословно: «not in an
    active StairsEditScope». Значит область обязательна, и открывается она
    одноаргументным `Start(ElementId)` на УЖЕ СТОЯЩЕЙ лестнице."""

    def test_scope_открыт_и_закрыт(self):
        cs = _emit()
        self.assertIn("new StairsEditScope(doc,", cs)
        self.assertIn("__ess.Start(", cs)
        self.assertIn("__ess.Commit(new __KirStairsFailures())", cs)

    def test_отказ_снимает_ОБА_эффекта_доказанно(self):
        """Типизированный отказ после Start законен только если транзакция
        вернула RolledBack И scope после Cancel больше не активен."""
        cs = _emit()
        self.assertIn("__rollbackCancel_", cs)
        # Транзакция обязана вернуть RolledBack, И scope обязан перестать быть
        # активным. Возврат отказа при недоказанном снятии — это молчаливый
        # эффект под зелёным ответом, поэтому там бросается, а не отказывает.
        self.assertIn("__rollbackStatus_RN1 != TransactionStatus.RolledBack", cs)
        self.assertIn("return __cancel_RN1(__scope_RN1);", cs)
        for site in ("CreateStraightRun failed",
                     "CreateStraightRun returned null",
                     "postcondition failed"):
            with self.subTest(site=site):
                self.assertIn(f"{site} and rollback/cancel is unproven", cs)

    def test_предупреждения_снимаются_чтобы_не_всплыли_диалогом(self):
        """Модальное окно замораживает UI-поток Revit — тот самый инцидент,
        из-за которого живые прогоны этого пути и остановлены."""
        cs = _emit()
        self.assertIn("SetFailuresPreprocessor(new __KirStairsFailures())", cs)
        self.assertIn("SetForcedModalHandling(false)", cs)


class СвидетельЧитаетРЕЗУЛЬТАТ(unittest.TestCase):
    """Постусловие, подтверждающее лишь факт вызова, — именной дефект этого
    дерева. Здесь свидетель перечитывает построенный марш из документа."""

    def test_владелец_и_членство(self):
        cs = _emit()
        self.assertIn(".GetStairs()", cs)
        self.assertIn("GetStairsRuns()", cs)

    def test_ось_марша_сверяется_по_ОБОИМ_направлениям(self):
        """Revit волен вернуть путь развёрнутым; требовать нашего порядка
        значило бы отвергать верную постройку."""
        cs = _emit()
        self.assertIn("GetStairsPath()", cs)
        # Присутствия имён мало: они обязаны стоять в ОДНОЙ дизъюнкции, иначе
        # сверяется одно направление, а второе объявлено и не спрошено.
        self.assertIn("if (__fwd_RN1 || __rev_RN1) __pathHit_RN1 = true;", cs)
        for end, val in (("__ax_RN1", "0.0"), ("__zx_RN1", "3000.0")):
            with self.subTest(end=end):
                self.assertIn(f"Math.Abs({end} - {val})", cs)   # прямое
        self.assertIn("Math.Abs(__ax_RN1 - 3000.0)", cs)        # обратное

    def test_Z_НЕ_сравнивается_и_это_объявлено(self):
        """Z пути назначает Revit от базы лестницы. Подписать ось, которую не
        задавали, — ровно то, что запрещает test_witness_axis_honesty."""
        cs = _emit()
        self.assertIn("ось марша в плане не совпала", cs)
        self.assertNotIn("GetEndPoint(0).Z", cs)

    def test_свидетель_запускается_ДВАЖДЫ(self):
        """Внутри транзакции (нарушение откатывает всё) и ПОСЛЕ
        StairsEditScope.Commit на заново прочитанных объектах — старый
        managed wrapper не должен изображать живой результат."""
        cs = _emit()
        self.assertEqual(cs.count("__check_RN1("), 2)
        self.assertIn("doc.GetElement(__runId_RN1)", cs)

    def test_допуск_ВЫВОДИТСЯ_из_документа(self):
        """Реестровая константа здесь была бы границей, заведённой
        рассуждением; допуск — свойство живого документа."""
        cs = _emit()
        self.assertIn("MM(doc.Application.VertexTolerance)", cs)


class ОтметкаОтносительнаяИСеткаЖивая(unittest.TestCase):

    def test_Z_оси_берётся_от_базы_лестницы(self):
        cs = _emit()
        self.assertIn("__sbz_RN1", cs)
        self.assertIn("BaseElevation", cs)

    def test_кратность_подступенку_проверяется_ДО_эффекта(self):
        """Марш, начинающийся посреди подступенка, — не лестница. Шаг живой,
        поэтому отказ НАЗЫВАЕТ двух ближайших кандидатов, а не отсылает
        к документации."""
        cs = _emit()
        # Шаг обязан быть ПРОЧИТАН у лестницы, а не назван где-то рядом.
        self.assertIn("double __rh_RN1 = MM(__st_RN1.ActualRiserHeight);", cs)
        self.assertIn("double __elevQ_RN1 = 1800.0 / __rh_RN1;", cs)
        self.assertIn("Math.Abs(1800.0 - __elevNorm_RN1) > __dt_RN1", cs)
        self.assertIn("ближайшие кандидаты", cs)


class ОтказыТипизированы(unittest.TestCase):
    """КОНТРОЛЬ-FAIL: каждый неверный вход обязан дать НАЗВАННЫЙ код, а не
    тихую постройку и не внутреннюю ошибку."""

    def _codes(self, prog, **kw):
        out = compile_program(prog, revit_version="2023", **kw)
        self.assertFalse(out.ok)
        return {d.code for d in (out.diagnostics or [])}

    def test_сосед_в_программе_KIR_L002(self):
        wall = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
                "p1_mm": [1000, 0], "level": {"by": "name", "value": "L1"},
                "height_mm": 3000}
        self.assertIn("KIR-L002",
                      self._codes(_prog(_op(), wall), bulk=True))

    def test_ref_на_соседа_отказан(self):
        """Предшественника у соло-опа нет ПО ПОСТРОЕНИЮ, поэтому `ref`
        неразрешим, а не «опасен»."""
        self.assertTrue(
            self._codes(_prog(_op(stairs={"by": "ref", "value": "s1"}))))

    def test_чужая_привязка_KIR_T001(self):
        self.assertIn("KIR-T001",
                      self._codes(_prog(_op(justification="middle"))))

    def test_отметка_вне_границ_KIR_T002(self):
        self.assertIn("KIR-T002",
                      self._codes(_prog(_op(base_elevation_mm=-100.0))))
        self.assertIn("KIR-T002",
                      self._codes(_prog(_op(base_elevation_mm=9_999_999.0))))


class ЗакрытияПоРееструЗаговорили(unittest.TestCase):
    """Оп, добавленный в реестр и не внесённый в закрытия, — тихая дыра.
    Здесь проверяется, что каждое закрытие его ЗНАЕТ."""

    def test_соло_оп_объявлен(self):
        self.assertIn(OP, spec.SOLO_OPS)

    def test_у_соло_опа_есть_свой_шаблон_программы(self):
        from kukai.ir import authoring
        self.assertIn(OP, authoring._SOLO_PROGRAMS)
        # Ключи таблицы обязаны совпадать с `spec.SOLO_OPS` — иначе оп молча
        # уехал бы в чужой шаблон и получил бы чужую эмиссию, а не отказ.
        self.assertEqual(set(authoring._SOLO_PROGRAMS), set(spec.SOLO_OPS))

    def test_контракт_понижения_полон(self):
        from kukai.ir import op_contract
        self.assertTrue(op_contract.contract_for(OP))

    def test_обратный_контракт_назван(self):
        from kukai.ir import reverse_contract
        self.assertIn(OP, reverse_contract.REVERSE_CONTRACTS)

    def test_категория_объявлена_СЛЕПОЙ_а_не_угадана(self):
        """Ошибка слепоты обратима (теряется верхняя граница), ошибка
        заполнения — нет: она отклоняет ЧЕСТНУЮ постройку. Категория марша
        живым Revit не замерена, поэтому строки в таблице нет."""
        from kukai.ir import acceptance
        self.assertIn(OP, acceptance._OPS_BLIND)
        self.assertIsNone(spec.OP_RESULT_CATEGORIES.get(OP))

    def test_клеш_знает_что_оболочки_нет(self):
        from kukai.ir import clash_bundle
        self.assertIn(OP, clash_bundle.OP_NO_BODY)

    def test_живая_недоказанность_НАЗВАНА(self):
        """Молчание читается как «проверено». Оп без живого свидетельства
        обязан стоять в UNPROVEN — вместе с причиной."""
        from kukai.ir import tool_doc
        self.assertIn(OP, tool_doc.UNPROVEN)


class НастоящаяЛестницаВыразима(unittest.TestCase):
    """Ворота волны: Г- и П-образная лестницы собираются целиком.
    П-образная — МОДА настоящего дома (10 лестниц из 19 четырёхмаршевые)."""

    SNAP = fixtures.GROUND_SNAPSHOT

    def _levels(self):
        return [r.get("name") for r in self.SNAP.get("levels", [])][:2]

    def _stairs(self):
        base, top = self._levels()
        return _prog({"op": "create_stairs", "id": "S1",
                      "base_level": {"by": "name", "value": base},
                      "top_level": {"by": "name", "value": top},
                      "p0_mm": [0, 0], "p1_mm": [3000, 0], "width_mm": 1200})

    def _landing(self, k):
        return _prog({"op": "create_stairs_landing", "id": f"LG{k+1}",
                      "stairs": STAIRS,
                      "contour": {"outer": {"shape": "rect",
                                            "origin": [3000.0, 1300.0 * k],
                                            "size_mm": [1200.0, 1200.0]}},
                      "elevation_mm": 1800.0 * (k + 1)})

    def _run(self, k):
        return _prog(_op(id=f"RN{k+1}",
                         p0_mm=[0.0, 1300.0 * k], p1_mm=[3000.0, 1300.0 * k],
                         base_elevation_mm=1800.0 * (k + 1)))

    def _all_compile(self, pack):
        for prog in pack:
            out = compile_program(prog, revit_version="2023",
                                  snapshot=self.SNAP)
            self.assertTrue(out.ok, [d.message_ru
                                     for d in (out.diagnostics or [])])
        return len(pack)

    def test_Г_образная_марш_площадка_марш(self):
        pack = [self._stairs(), self._landing(0), self._run(0)]
        self.assertEqual(self._all_compile(pack), 3)

    def test_П_образная_четыре_марша_три_площадки(self):
        pack = [self._stairs()]
        for k in range(3):
            pack += [self._landing(k), self._run(k)]
        self.assertEqual(self._all_compile(pack), 7)

    def test_каждое_звено_ОТДЕЛЬНАЯ_программа_и_это_закон_Revit(self):
        """Две области правки одновременно Revit не открывает, поэтому
        соседство двух лестничных опов невыразимо ПО REVIT, а не по вкусу."""
        out = compile_program(
            _prog(_op(id="RN1"), _op(id="RN2")),
            revit_version="2023", bulk=True)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L002", {d.code for d in (out.diagnostics or [])})


if __name__ == "__main__":
    unittest.main()
