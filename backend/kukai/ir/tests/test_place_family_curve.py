"""`place_family` по КРИВОЙ: семейства, которые ставятся не в точку.

ЗАМЕР 27.07 (тренировочная модель ЭОМ, SKLNK, Revit 2026). После починки
порядка отказов в лифте честное покрытие ЭОМ — 67.70%, и ВЕСЬ остаток дыры
это 79 элементов с одной причиной: `FamilyPlacementType.CurveBased`.

Что они такое, проверено в живой модели: огнезащитные кожухи кабельных
лотков («Техстронг_ОЗК : 4 стороны»), категория «Обобщенные модели», каждый
на хосте-лотке. У ВСЕХ 79 есть `LocationCurve`, и все кривые — прямые
отрезки. Пример:
    1268396 | Line [155643,-5766,565] -> [155643,-5766,4910] | хост 1221482

То есть Revit хранит их геометрию и отдаёт её; невыразимой она была только у
нас. Точечный `place_family` их не берёт по существу, а не по недосмотру:
у экземпляра нет `LocationPoint` вообще.

Почему это общий оп, а не частный случай ЭОМ: кривая — один из десяти видов
размещения семейства, и большинство категорий Revit суть экземпляры
семейств. Оп, умеющий и точку, и кривую, покрывает категории тысячами, а не
поштучно. Раздел тут только повод: тот же `CurveBased` встречается в КР
(связи), ОВ (опоры воздуховодов) и АР (карнизы, поручни).

Договор параметров повторяет уже существующий в реестре: кривая — это пара
`p0_mm`/`p1_mm`, ровно как у `create_beam`, `create_pipe`,
`create_cable_tray`. Второго способа записать отрезок в этом реестре быть не
должно.
"""
import copy
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_pfcurve.jsonl"))

from kukai.ir import spec
from kukai.ir.compiler import compile_program
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

_POINT = {
    "ir_version": "1.0", "intent": "семейство в точку", "ops": [
        {"op": "place_family", "id": "F1", "xyz": [1000, 2000, 0],
         "level": {"by": "element_id", "value": 42}}]}

# Хост у кривого варианта обязателен — ЗАМЕРЕНО, а не выбрано: перегрузка
# с уровнем проецирует кривую на плоскость уровня и схлопывает вертикальный
# отрезок в точку, верная перегрузка идёт по ссылке на грань хоста.
# Поэтому программа держит лоток и кожух на нём — так же, как стена и дверь.
_CURVE = {
    "ir_version": "1.0", "intent": "семейство по кривой на хосте", "ops": [
        {"op": "create_cable_tray", "id": "T1",
         "p0_mm": [155643, -5766, 565], "p1_mm": [155643, -5766, 4910],
         "level": {"by": "element_id", "value": 42}},
        {"op": "place_family", "id": "F1",
         "p0_mm": [155643, -5766, 565], "p1_mm": [155643, -5766, 4910],
         "host": {"by": "ref", "value": "T1"}}]}


class PlaceFamilyCurve(unittest.TestCase):
    def test_curve_without_a_host_is_refused(self):
        """Кривая без хоста — отказ, а не подстановка уровня.

        Замер 27.07: перегрузка с уровнем проецирует отрезок на плоскость
        уровня; вертикальная кривая схлопывается в точку, а уровень Revit
        вдобавок игнорирует (LevelId остаётся -1). Подставить уровень «чтобы
        вызов состоялся» значило бы выдать поломанную геометрию за успех.
        """
        no_host = copy.deepcopy(_CURVE)
        no_host["ops"][1].pop("host")
        out = compile_program(no_host, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("host", str([d.as_dict() for d in out.diagnostics]))

    def test_registry_expresses_a_curve_the_same_way_as_every_other_op(self):
        params = {p.name: p for p in spec.OPS["place_family"].params}
        for name in ("p0_mm", "p1_mm"):
            self.assertIn(name, params, f"{name} нет у place_family")
            self.assertEqual(params[name].kind, "pt_xyz")
        # точка перестала быть обязательной — иначе кривую не выразить
        self.assertFalse(params["xyz"].required)

    def test_curve_variant_compiles_and_uses_the_curve_overload(self):
        out = compile_program(copy.deepcopy(_CURVE), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        cs = out.csharp
        self.assertIn("Line.CreateBound", cs)
        self.assertIn("new Reference(__pfh_F1)", cs)
        # свидетель обязан читать РЕЗУЛЬТАТ, а у кривого экземпляра результат
        # это LocationCurve, а не LocationPoint
        self.assertIn("LocationCurve", cs)
        self.assertIn("host mismatch (topology)", cs)
        self.assertIn("endpoints mismatch (geometry)", cs)

    def test_point_and_curve_are_mutually_exclusive(self):
        both = copy.deepcopy(_CURVE)
        both["ops"][1]["xyz"] = [0, 0, 0]
        out = compile_program(both, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok, "точка и кривая вместе неоднозначны")

        neither = copy.deepcopy(_POINT)
        neither["ops"][0].pop("xyz")
        out2 = compile_program(neither, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out2.ok, "без точки и без кривой ставить нечего")

    def test_half_a_curve_is_refused_not_guessed(self):
        half = copy.deepcopy(_CURVE)
        half["ops"][1].pop("p1_mm")
        out = compile_program(half, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok, "одна точка кривой — не кривая")

    def test_point_emission_is_byte_stable(self):
        """Точечный путь не смеет сдвинуться ни на байт.

        Кривая — ДОБАВЛЕННАЯ ветвь, а не переписанный оп: 18 700 экземпляров
        демо и 327 из прогона A5 поставлены точечным путём, и их байты
        заморожены корпусом паритета.
        """
        out = compile_program(copy.deepcopy(_POINT), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertNotIn("Line.CreateBound", out.csharp)
        self.assertIn("NewFamilyInstance(__pfp_F1", out.csharp)


if __name__ == "__main__":
    unittest.main()
