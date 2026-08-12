"""Контурный потолок обратным ходом (09.08.2026).

ФАКТ ДО ЭТОЙ ПРАВКИ. Утром 09.08 у ``create_ceiling`` появился ВТОРОЙ вход
формы — ``contour`` рода ``region`` (ops_arch.py), то есть весь язык эскиза
CONTOUR: дуги, до восьми отверстий, rect/l/poly. Прямое направление выросло,
обратное осталось на месте: ``_lift_ceiling`` звал только полигональный путь,
и потолок с закруглённым краем по-прежнему становился атомом
``unsupported_geometry`` — «оп не умеет эту форму», что перестало быть правдой
в то же утро.

ПОЧЕМУ ЭТО ЛИФТЕР, А НЕ РАЗРЫВ ЗАХВАТА (три состояния, между которыми решает
эта волна). Данные для контура УЖЕ ЛЕЖАТ в боковом индексе эскизов: категория
``OST_Ceilings`` стоит в ``_STAGE_CATEGORIES`` стадии ``sketch`` с 29.07, а
строка профиля несёт для каждой петли и род сегмента (``curve_kinds``), и
середину дуги (``arc_midpoints``) — ровно те три числа, из которых пол уже
собирает ``bulge``. Значит недоставало не поля в захвате и не операции в
реестре, а ветки в лифтере. Ровно тот единственный случай из трёх, когда
лифтер писать МОЖНО.

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ, А ЧТО НЕТ. Доказывается, что круг ЗАМЫКАЕТСЯ: узел,
который отдаёт лифт, компилятор принимает на 2022-2026 и отвергает
типизированным KIR-E003 на 2021 (у потолка там нет НИКАКОГО пути создания —
замерено компиляцией, см. ops_arch.py). НЕ доказывается, что потолок
пересобирается в живом Revit: наклон потолка захват по-прежнему не несёт (в
L0 его нет ни в каком виде), и наклонный потолок этот лифт вернёт плоским.
Эта граница названа в самом лифтере и в манифесте (``create_ceiling`` —
``BOUNDED``, а не ``FORM_EXACT``), и контур её не сдвигает ни на шаг: он про
ПЛАН, а уклон — про третью координату.
"""
from __future__ import annotations

import copy
import math
import unittest
from typing import Any

from kukai.ir.compiler import compile_program
from kukai.ir.contour import bulge_midpoint
from kukai.ir.decompile.l1_schema import AtomReason, validate_l1_node
from kukai.ir.decompile.lift import lift_document_detailed
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

#: Имена ИЗ СНИМКА ворот: круг проверяется до конца только тогда, когда
#: заземление находит и уровень, и тип. Иначе тест доказывал бы форму
#: региона, а не то, что программа компилируется.
SNAPSHOT_LEVEL = "Этаж 1"
SNAPSHOT_CEILING_TYPE = "Потолок подвесной 600x600"

SQUARE = [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0], [0.0, 4000.0]]

#: Закруглённый край: третье ребро квадрата — дуга с захваченной серединой.
ARC_MIDPOINT = [3000.0, 4600.0]


def _profile(
    outline: list[list[float]],
    *,
    curve_kinds: list[list[str]] | None = None,
    arc_midpoints: list[list[list[float] | None]] | None = None,
    holes: list[list[list[float]]] | None = None,
) -> dict[str, Any]:
    contours = [outline] + list(holes or [])
    return {
        "profile_available": True,
        "exterior_loop": copy.deepcopy(outline),
        "holes": copy.deepcopy(holes or []),
        "curve_kinds": copy.deepcopy(curve_kinds) if curve_kinds else [
            ["line"] * len(contour) for contour in contours],
        "arc_midpoints": copy.deepcopy(arc_midpoints) if arc_midpoints else [
            [None] * len(contour) for contour in contours],
    }


ARC_PROFILE = _profile(
    SQUARE,
    curve_kinds=[["line", "line", "arc", "line"]],
    arc_midpoints=[[None, None, ARC_MIDPOINT, None]])


def _document(*, offset: float | None = None,
              floor_offset: float | None = None) -> L0Document:
    ceiling = make_element("OST_Ceilings", 8801, ordinal=0)
    ceiling["element_id"] = "8801"
    ceiling["geom_kind"] = "bbox_only"
    ceiling["p0_mm"] = None
    ceiling["p1_mm"] = None
    ceiling["rotation_deg"] = None
    ceiling["type_id"] = "1200"
    ceiling["type_name"] = SNAPSHOT_CEILING_TYPE
    ceiling["params"] = dict(ceiling.get("params") or {})
    if offset is not None:
        ceiling["params"]["CEILING_HEIGHTABOVELEVEL_PARAM"] = offset
    if floor_offset is not None:
        ceiling["params"]["FLOOR_HEIGHTABOVELEVEL_PARAM"] = floor_offset
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "ceiling-contour-v1"
    row["elements"] = [ceiling]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lift(profile: dict[str, Any], **kwargs):
    result = lift_document_detailed(
        _document(**kwargs), {"8801": copy.deepcopy(profile)})
    return result.nodes[0], result.diagnostics


class AnArcCeilingStopsBeingAnAtom(unittest.TestCase):

    def test_it_lifts_as_create_ceiling_through_the_contour_input(self) -> None:
        node, diagnostics = _lift(ARC_PROFILE)
        self.assertEqual(diagnostics, ())
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_ceiling")
        self.assertIn("contour", node["params"])
        self.assertEqual(validate_l1_node(node), node)

    def test_the_flat_shape_fields_are_absent_because_both_is_a_refusal(self):
        """`outline`/`holes` рядом с `contour` — типизированный KIR-P007.

        Эмитировать оба значило бы отдать компилятору программу, которую он
        ОБЯЗАН отвергнуть, и записать её себе в покрытие.
        """

        node, _ = _lift(ARC_PROFILE)
        self.assertNotIn("outline", node["params"])
        self.assertNotIn("holes", node["params"])

    def test_the_bulge_reproduces_the_captured_midpoint(self) -> None:
        """Дуга записана ТОЧНО: обратный ход их же функцией даёт ту середину,
        которую снял экстрактор, а не «примерно ту же» кривую."""

        node, _ = _lift(ARC_PROFILE)
        outer = node["params"]["contour"]["outer"]
        self.assertEqual(outer["shape"], "poly")
        arcs = outer["arcs"]
        self.assertEqual(len(arcs), 1)
        edge = arcs[0]["edge"]
        points = outer["points_mm"]
        back = bulge_midpoint(
            points[edge], points[(edge + 1) % len(points)], arcs[0]["bulge"])
        self.assertLess(math.dist(back, ARC_MIDPOINT), 1e-6)

    def test_the_offset_comes_from_the_ceiling_parameter_only(self) -> None:
        """Имя параметра — часть тождества категории.

        Чужое имя здесь молча вернуло бы ноль, то есть положило бы потолок на
        плоскость уровня и назвало это успехом.
        """

        node, _ = _lift(ARC_PROFILE, offset=2700.0)
        self.assertEqual(node["params"]["height_offset_mm"], 2700.0)

        other, _ = _lift(ARC_PROFILE, floor_offset=2700.0)
        self.assertNotIn("height_offset_mm", other["params"])


class ThePolygonPathIsUnchanged(unittest.TestCase):
    """Контур берёт только НЕВЫРАЗИМОЕ. Всё остальное обязано не сдвинуться.

    Иначе круг разомкнулся бы на каждом потолке каждого уже разобранного
    здания, а «мы ничего не сломали» стало бы непроверяемым.
    """

    def test_a_polygon_ceiling_still_lifts_with_outline_and_holes(self) -> None:
        node, diagnostics = _lift(_profile(SQUARE), offset=2700.0)
        self.assertEqual(diagnostics, ())
        self.assertEqual(node["op_name"], "create_ceiling")
        self.assertEqual(node["params"]["outline"],
                         [[0.0, 0.0], [6000.0, 0.0],
                          [6000.0, 4000.0], [0.0, 4000.0]])
        self.assertEqual(node["params"]["holes"], [])
        self.assertNotIn("contour", node["params"])
        self.assertEqual(node["params"]["height_offset_mm"], 2700.0)


class WhatContourStillCannotSayStaysATypedAtom(unittest.TestCase):

    def test_an_arc_without_a_captured_midpoint_stays_an_atom(self) -> None:
        """Без середины дуга невосстановима, и хорда — не приближение.

        Причина здесь `missing_geometry`, а не «контур не выражает»: строку с
        дугой без середины строгий разбор бокового индекса не принимает
        ВОВСЕ, то есть профиля у элемента нет. Ровно то же и тем же кодом
        отвечает пол (`test_lift_floor_contour`), и это не совпадение — разбор
        строки один на обе категории.
        """

        node, diagnostics = _lift(_profile(
            SQUARE,
            curve_kinds=[["line", "line", "arc", "line"]],
            arc_midpoints=[[None, None, None, None]]))
        self.assertEqual(node["kind"], "atom")
        self.assertIs(diagnostics[0].reason, AtomReason.MISSING_GEOMETRY)
        self.assertIn(
            "arc segment 2 requires an exact midpoint",
            node["reason"]["detail"])

    def test_more_than_eight_openings_are_refused_by_name(self) -> None:
        holes = [[[200.0 + i * 500, 200.0], [500.0 + i * 500, 200.0],
                  [500.0 + i * 500, 500.0], [200.0 + i * 500, 500.0]]
                 for i in range(9)]
        node, diagnostics = _lift(_profile(
            SQUARE,
            curve_kinds=[["line", "line", "arc", "line"]]
                        + [["line"] * 4] * 9,
            arc_midpoints=[[None, None, ARC_MIDPOINT, None]]
                          + [[None] * 4] * 9,
            holes=holes))
        self.assertEqual(node["kind"], "atom")
        self.assertIs(diagnostics[0].reason, AtomReason.UNSUPPORTED_SIGNATURE)
        self.assertIn("до 8 проёмов", node["reason"]["detail"])


class TheCircleActuallyCloses(unittest.TestCase):
    """Лифт, чей узел компилятор не принимает, — не покрытие, а отчёт о нём.

    Регион собирается ЛИФТОМ и отдаётся компилятору дословно; подменять его
    здесь написанным от руки эскизом значило бы проверить свою же догадку о
    том, что лифт эмитирует.
    """

    def _program(self, revit_version: str):
        node, _ = _lift(ARC_PROFILE, offset=2700.0)
        return compile_program(
            {"ir_version": "1.0", "intent": "потолок по эскизу", "ops": [{
                "op": "create_ceiling", "id": "CE1",
                "contour": node["params"]["contour"],
                "level": {"by": "name", "value": SNAPSHOT_LEVEL},
                "type": {"by": "name", "value": SNAPSHOT_CEILING_TYPE},
                "height_offset_mm": node["params"]["height_offset_mm"],
            }]},
            revit_version=revit_version, snapshot=GROUND_SNAPSHOT, bulk=True)

    def test_the_lifted_contour_compiles_on_every_version_that_has_ceilings(
            self) -> None:
        for version in ("2022", "2023", "2024", "2025", "2026"):
            with self.subTest(revit_version=version):
                out = self._program(version)
                self.assertTrue(
                    out.ok, [d.code for d in out.diagnostics])
                self.assertIn("Ceiling.Create", out.csharp)

    def test_2021_refuses_the_whole_operation_by_name(self) -> None:
        """У потолка на 2021 нет НИ ОДНОГО пути создания — ни нового, ни
        legacy. Отказ обязан быть типизированным и до разбора формы."""

        out = self._program("2021")
        self.assertFalse(out.ok)
        self.assertEqual([d.code for d in out.diagnostics], ["KIR-E003"])


if __name__ == "__main__":
    unittest.main()
