"""Обратный ход для потолка и ограждения (wave/arch, 2026-07-29).

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ И ЧТО НЕТ — прямо, чтобы отчёт нельзя было прочитать
лучше, чем он есть.

ДОКАЗАНО ОФЛАЙН: потолок с профилем в боковом индексе эскизов поднимается в
``create_ceiling`` со своим уровнем, типом и смещением; потолок без профиля и
ограждение дают ТИПИЗИРОВАННУЮ причину атома, называющую недостающий факт.

НЕ ДОКАЗАНО И ЧЕСТНО НАЗВАНО НЕДОКАЗАННЫМ: ни один потолок и ни одно
ограждение НАСТОЯЩЕГО здания сегодня не поднимается — потому что в слепке
для них нет геометрии. Замер по 13A-RD-AR-K2_v33 (55 293 элемента):

    OST_Ceilings        81 шт.  geom_kind=bbox_only  params={}  профиля нет
    OST_StairsRailing  203 шт.  bbox_only 31 / point 172, host_id=null,
                                ни одной строки ни в sketch.index.json,
                                ни в curve.index.json

То есть ворота у операций зелёные, а поднимать НЕЧЕГО: чинится это не
лифтом, а стороной ИЗВЛЕЧЕНИЯ (экстрактор не снимает ни профиль потолка, ни
путь/позицию ограждения), и живого Revit для этого шага у волны не было.
Профили ниже — синтетические, и названы синтетическими.
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.lift import lift_document_detailed
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)

CEILING_ID = "9100001"
RAILING_ID = "9100002"

#: СИНТЕТИЧЕСКИЙ профиль (в слепке K2 у потолков профиля нет вовсе) — форма
#: строки скопирована с настоящих строк sketch.index.json.
SYNTHETIC_CEILING_PROFILE: dict[str, Any] = {
    "profile_available": True,
    "exterior_loop": [
        [0.0, 0.0],
        [6000.0, 0.0],
        [6000.0, 4000.0],
        [0.0, 4000.0],
    ],
    "curve_kinds": [["line", "line", "line", "line"]],
    "arc_midpoints": [[None, None, None, None]],
    "holes": [],
}


def _document(category: str, element_id: str, *,
              offset: float | None = None,
              host_id: str | None = None) -> L0Document:
    element = make_element(category, 4100, ordinal=0)
    element["element_id"] = element_id
    element["params"] = dict(element.get("params") or {})
    if offset is not None:
        element["params"]["CEILING_HEIGHTABOVELEVEL_PARAM"] = offset
    if host_id is not None:
        element["host_id"] = host_id
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "arch-v1"
    row["elements"] = [element]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lift(category: str, element_id: str, profile=None, **kw):
    result = lift_document_detailed(
        _document(category, element_id, **kw),
        {element_id: copy.deepcopy(profile)} if profile else {})
    return {node["source_element_id"]: node
            for node in result.nodes}[element_id]


class ACeilingWithAProfileLifts(unittest.TestCase):

    def test_it_becomes_create_ceiling(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE)
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_ceiling")

    def test_the_outline_survives_the_round_trip(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE)
        self.assertEqual(len(node["params"]["outline"]), 4)
        self.assertEqual(node["params"]["holes"], [])

    def test_it_carries_its_own_level_and_type(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE)
        self.assertIn("level", node["params"])
        self.assertIn("type", node["params"])

    def test_the_height_offset_travels(self) -> None:
        """Смещение читается из СВОЕГО параметра потолка. Чужое имя
        (FLOOR_HEIGHTABOVELEVEL_PARAM) молча вернуло бы ноль — то самое
        «0 вместо отсутствия», которое в этом доме уже стоило 96% групп."""
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE,
                     offset=-250.0)
        self.assertEqual(node["params"]["height_offset_mm"], -250.0)

    def test_an_absent_offset_stays_absent(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE)
        self.assertNotIn("height_offset_mm", node["params"])

    def test_a_floor_parameter_is_not_read_by_mistake(self) -> None:
        document = _document("OST_Ceilings", CEILING_ID)
        document.elements[0].params["FLOOR_HEIGHTABOVELEVEL_PARAM"] = -900.0
        result = lift_document_detailed(
            document, {CEILING_ID: copy.deepcopy(SYNTHETIC_CEILING_PROFILE)})
        node = result.nodes[0]
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertNotIn("height_offset_mm", node["params"])


class WithoutEvidenceTheReasonIsExact(unittest.TestCase):
    """До этой волны причина у всех этих элементов была одна: «операции не
    существует». Она была правдой и перестала ей быть — а причина, по которой
    решают, что строить дальше, не имеет права отставать от реальности."""

    def test_a_ceiling_without_a_profile_names_the_missing_profile(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.MISSING_GEOMETRY.value)

    def test_a_hosted_railing_names_the_missing_position(self) -> None:
        """Хозяин известен, позиция — нет. Подставить Treads «по умолчанию»
        значит поставить ограждение не на ту сторону марша молча."""
        node = _lift("OST_StairsRailing", RAILING_ID, host_id="777")
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.MISSING_PARAMETER.value)

    def test_a_bare_railing_names_the_missing_geometry(self) -> None:
        node = _lift("OST_StairsRailing", RAILING_ID)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.MISSING_GEOMETRY.value)

    def test_neither_is_reported_as_a_missing_operation_any_more(self) -> None:
        for category, kw in (("OST_Ceilings", {}),
                             ("OST_StairsRailing", {}),
                             ("OST_StairsRailing", {"host_id": "777"})):
            with self.subTest(category=category, kw=tuple(kw)):
                node = _lift(category, RAILING_ID, **kw)
                self.assertNotEqual(node["reason"]["code"],
                                    AtomReason.REGISTRY_OP_GAP.value)
                self.assertNotEqual(node["reason"]["code"],
                                    AtomReason.NO_LIFTER.value)


if __name__ == "__main__":
    unittest.main()
