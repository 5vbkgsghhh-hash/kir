"""wave/room — обратный ход разделителя помещений.

НАПИСАН И ЗАПУЩЕН ДО ЛИФТЕРА (дисциплина пакета: сначала опровергающий тест).
До правки все тесты этого файла падали одинаково: категории
``OST_RoomSeparationLines`` не было в таблице лифтеров, и каждый её элемент
становился атомом ``no_lifter`` с формулировкой «category is outside the exact
Part 5 lifter table». Формулировка была ЧЕСТНОЙ: операции не существовало.

ЗАМЕР, ИЗ КОТОРОГО СЛЕДУЕТ ЭТОТ ФАЙЛ (k2_ar_rd_v9, снят прибором по L0):
2 313 разделителей, из них 2 299 прямых и 14 дуговых; у 2 309 отметка ровно
на уровне, у 4 — ниже на 30 мм. После волны тот же разбор даёт 2 296 опов и
17 атомов с ДВУМЯ названными причинами вместо одной безымянной.

ЭТОТ ФАЙЛ ФИКСИРУЕТ ИМЕННО ГРАНИЦЫ, а не только успех: атом с точной причиной
здесь так же обязателен, как поднятая операция. Дуга, спрямлённая хордой, и
разделитель, вернувшийся на 30 мм ниже, прошли бы verify (сравниваются концы)
и выглядели бы успехом — ровно тот Гудхарт, ради запрета которого лифт
отказывается вместо того, чтобы «примерно построить».
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kukai.ir.decompile.lift import (
    AtomReason, LIFTER_TABLE, lift_document_detailed,
)
from kukai.ir.decompile.l1_schema import validate_l1_node
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata,
)

CATEGORY = "OST_RoomSeparationLines"


def _document(elements: list[dict[str, Any]]) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "synthetic-room-separator-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


def _only(result):
    return result.nodes[0]


class LifterReadsBackOrNamesWhy(unittest.TestCase):

    def test_the_category_is_in_the_lifter_table(self):
        self.assertIn(CATEGORY, LIFTER_TABLE)
        self.assertEqual(LIFTER_TABLE[CATEGORY][1], "create_room_separator")

    def test_a_straight_separator_lifts_to_a_two_point_path(self):
        row = make_element(CATEGORY, 7101, ordinal=0)
        result = lift_document_detailed(_document([row]))

        self.assertEqual(result.diagnostics, ())
        node = _only(result)
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_room_separator")
        self.assertEqual(node["params"]["path"],
                         [[row["p0_mm"][0], row["p0_mm"][1]],
                          [row["p1_mm"][0], row["p1_mm"][1]]])
        self.assertEqual(node["params"]["level"]["value"], row["level_name"])
        self.assertTrue(validate_l1_node(node))

    def test_one_source_element_becomes_exactly_one_node(self):
        """Соседние линии НЕ сшиваются в одну ломаную: общей личности,
        которая доказывала бы их родство, в L0 нет — только совпадение
        координат, а это догадка."""
        rows = [make_element(CATEGORY, 7200 + i, ordinal=i) for i in range(5)]
        result = lift_document_detailed(_document(rows))

        self.assertEqual(len(result.nodes), 5)
        for node in result.nodes:
            self.assertEqual(node["kind"], "op")
            self.assertEqual(len(node["params"]["path"]), 2)

    def test_the_op_carries_no_type_because_the_api_has_none(self):
        """У NewRoomBoundaryLines нет аргумента типа, и у всех 2 313
        разделителей K2 ``type_id``/``type_name`` пусты. Поднять «тип» значило
        бы придумать его."""
        row = make_element(CATEGORY, 7301, ordinal=1)
        node = _only(lift_document_detailed(_document([row])))
        self.assertNotIn("type", node["params"])

    # ── границы, названные вслух ─────────────────────────────────────────────

    def test_an_arc_separator_is_a_typed_atom_never_a_chord(self):
        row = make_element(CATEGORY, 7401, ordinal=2)
        row["curve_kind"] = "arc"
        result = lift_document_detailed(_document([row]))

        node = _only(result)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.CURVE_KIND_UNSUPPORTED.value)
        self.assertIn("create_room_separator", node["reason"]["detail"])

    def test_a_separator_off_its_level_plane_is_a_typed_atom(self):
        """Смещения нет ни у операции, ни у API: плоскость эскиза строится из
        САМОГО уровня. Вернуть такой разделитель «примерно туда» — тихая
        потеря, и на башне в 59 этажей её никто бы не заметил."""
        row = make_element(CATEGORY, 7501, ordinal=3)
        row["p0_mm"] = [row["p0_mm"][0], row["p0_mm"][1], row["p0_mm"][2] - 30]
        row["p1_mm"] = [row["p1_mm"][0], row["p1_mm"][1], row["p1_mm"][2] - 30]
        result = lift_document_detailed(_document([row]))

        node = _only(result)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("offset", node["reason"]["detail"])

    def test_a_separator_crossing_the_level_plane_is_refused_too(self):
        """Один конец на уровне, другой нет — это не «почти плоско», это
        отрезок, которого плоскость эскиза не выражает вовсе."""
        row = make_element(CATEGORY, 7601, ordinal=4)
        row["p1_mm"] = [row["p1_mm"][0], row["p1_mm"][1],
                        row["p1_mm"][2] + 500]
        node = _only(lift_document_detailed(_document([row])))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.UNSUPPORTED_SIGNATURE.value)

    def test_a_separator_without_a_level_is_a_typed_atom(self):
        row = make_element(CATEGORY, 7701, ordinal=5)
        row["level_id"] = None
        row["level_name"] = None
        node = _only(lift_document_detailed(_document([row])))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.MISSING_REFERENCE.value)

    def test_a_degenerate_separator_is_refused_before_the_compiler_does(self):
        """Порог 1 мм — тот же, что у рода `path` на прямом ходу: отдать
        честный атом лучше, чем программу, которую компилятор всё равно
        отвергнет."""
        row = make_element(CATEGORY, 7801, ordinal=6)
        row["p1_mm"] = list(row["p0_mm"])
        node = _only(lift_document_detailed(_document([row])))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.INVALID_VALUE.value)


class ForwardBackwardAgree(unittest.TestCase):
    """Поднятая операция обязана компилироваться прямым ходом — иначе лифт
    производит красивые узлы, которых язык не принимает."""

    def test_the_lifted_node_compiles_forward(self):
        from kukai.ir.compiler import compile_program
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

        row = make_element(CATEGORY, 7901, ordinal=0)
        node = _only(lift_document_detailed(_document([row])))
        op = {"op": node["op_name"], "id": "RS1",
              "path": node["params"]["path"],
              # уровень фикстуры разбора и уровень фикстуры прямого хода —
              # разные каталоги, поэтому селектор пришпилен по id снимка
              "level": {"by": "element_id", "value": 42}}
        out = compile_program(
            {"ir_version": "1.0", "intent": "поднятый разделитель",
             "ops": [op]}, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics][:3])
        self.assertIn("NewRoomBoundaryLines(", out.csharp)


if __name__ == "__main__":
    unittest.main()
