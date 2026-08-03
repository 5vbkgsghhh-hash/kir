"""wave/shape — обратный ход DirectShape.

НАПИСАН И ЗАПУЩЕН ДО ЛИФТЕРА (дисциплина пакета: сначала опровергающий тест).
До правки все тесты этого файла падали: категория "DirectShape" отсутствовала
в таблице лифтеров, и элемент становился атомом NO_LIFTER с формулировкой
«category is outside the exact Part 5 lifter table».

ГЛАВНОЕ, ЧТО ЭТОТ ФАЙЛ ФИКСИРУЕТ. С появлением операции прежняя формулировка
стала НЕВЕРНОЙ: лифтер есть. Неверно другое — в L0 нет мешей. Замер по коду
извлечения: GeometryKind закрыт тремя значениями (curve/point/bbox_only), а
geometry_store.py пишет только bbox/кривую/точку; ни вершин, ни треугольников
в L0 нет ни одного байта, и это Волна G (KIR_DECOMPILE_SPEC.md §0.6),
не построенная. Сверх того, у DirectShape НЕ СОХРАНЯЕТСЯ даже собственная
категория: коллектор кладёт в поле category литерал "DirectShape"
(extract.py:1296), потому что BuiltInCategory для него не определяется классом.

Поэтому честных исходов ровно два, и оба здесь проверены:

  * срез с мешем есть  -> полноценный create_directshape;
  * среза нет          -> атом с ТОЧНОЙ причиной (MISSING_GEOMETRY), которая
                          называет, чего именно не хватает.

Подставить вместо отсутствующего меша габаритную коробку было бы ровно тем
Гудхартом, который в этом доме уже оплачен: «построил что-то другое» снаружи
неотличимо от успеха, а плоский потолок вместо наклонного — не приближение,
а неправда.
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


def _document(elements: list[dict[str, Any]]) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "synthetic-directshape-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


def _tetra() -> dict:
    return {
        "mesh_available": True,
        "vertices_mm": [[0, 0, 0], [3000, 0, 0], [1500, 2600, 0],
                        [1500, 900, 2400]],
        "triangles": [[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]],
        "category": "generic_model",
        "name": "тетраэдр",
    }


class LifterReadsBackOrNamesWhy(unittest.TestCase):

    def test_directshape_is_in_the_lifter_table(self):
        self.assertIn("DirectShape", LIFTER_TABLE)

    def test_mesh_slice_lifts_to_a_full_op(self):
        row = make_element("DirectShape", 7001, ordinal=0)
        result = lift_document_detailed(
            _document([row]), profile_index={"7001": _tetra()})

        self.assertEqual(result.diagnostics, ())
        node = result.nodes[0]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_directshape")
        self.assertEqual(node["params"]["category"], "generic_model")
        self.assertEqual(node["params"]["name"], "тетраэдр")
        self.assertEqual(node["params"]["mesh"]["triangles"],
                         _tetra()["triangles"])
        self.assertEqual(validate_l1_node(node), node)

    def test_without_a_mesh_slice_the_atom_names_the_real_reason(self):
        """Не «лифтера нет» — лифтер есть. Нет МЕША в L0, и атом обязан
        сказать именно это."""
        row = make_element("DirectShape", 7002, ordinal=1)
        result = lift_document_detailed(_document([row]))

        node = result.nodes[0]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(len(result.diagnostics), 1)
        diag = result.diagnostics[0]
        self.assertIs(diag.reason, AtomReason.MISSING_GEOMETRY)
        self.assertNotIn("outside the exact Part 5 lifter table", diag.detail)
        self.assertIn("меш", diag.detail.lower())

    def test_a_slice_that_breaks_the_mesh_laws_becomes_an_atom(self):
        """Инвариант направления: лифтер НИКОГДА не отдаёт программу, которую
        компилятор потом отвергнет. Те же законы, тот же validate_mesh."""
        broken = _tetra()
        broken["triangles"] = [[0, 1, 99]]          # индекс вне диапазона
        row = make_element("DirectShape", 7003, ordinal=2)
        result = lift_document_detailed(
            _document([row]), profile_index={"7003": broken})

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertIs(result.diagnostics[0].reason,
                      AtomReason.UNSUPPORTED_GEOMETRY)

    def test_slice_without_a_category_refuses_instead_of_guessing(self):
        """generic_model «по умолчанию» — молчаливая подмена категории."""
        slice_ = _tetra()
        del slice_["category"]
        row = make_element("DirectShape", 7004, ordinal=3)
        result = lift_document_detailed(
            _document([row]), profile_index={"7004": slice_})

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertIs(result.diagnostics[0].reason,
                      AtomReason.MISSING_METADATA)

    def test_lifted_op_recompiles(self):
        """Замыкание круга: то, что лифтер отдал, компилятор принимает."""
        from kukai.ir.compiler import compile_program

        row = make_element("DirectShape", 7005, ordinal=4)
        result = lift_document_detailed(
            _document([row]), profile_index={"7005": _tetra()})
        params = dict(result.nodes[0]["params"])
        program = {"ir_version": "1.0", "intent": "relift",
                   "ops": [dict(params, op="create_directshape", id="D1")]}
        out = compile_program(program, revit_version="2023",
                              snapshot={"levels": []})
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])


if __name__ == "__main__":
    unittest.main()
