"""Ограждение: захват был, провода не было (03.08.2026).

СТОРОНА ИЗВЛЕЧЕНИЯ ЗАКРЫЛА ЭТОТ ВОПРОС 29.07. ``RailingPathRecord`` снимает
``Railing.GetPath()``, ``HasHost``/``HostId`` и базовый уровень, стадия
``sketch`` кормится обеими категориями ограждений, и захват едет в проде.

ЛИФТ ЕГО НЕ ЧИТАЛ. ``_Context`` знал ``stairs_run_path_index`` и не знал
``railing_path_index``; ``_lift_railing`` решал по ``element.host_id`` — по
строке L0 — при том, что готовые пути лежали в ``sketch.index.json`` того же
разбора. Замер по k2_ar_rd_v9 (13A-RD-AR-K2_v33, 115 880 элементов): 31 строка
захвата, из них 28 свободных ограждений с путём, базовым уровнем и плоскостью
РОВНО на отметке уровня; все 31 прямые.

Тесты ниже написаны ДО правки и падали на ней красным.

ГРАНИЦА, КОТОРУЮ ЭТОТ ФАЙЛ ЗАЩИЩАЕТ ОТДЕЛЬНО: разбор, снятый ДО стадии
захвата, обязан дать ПРЕЖНИЙ отказ ДОСЛОВНО. Иначе «починка» переписала бы
историю всех слепков на диске, и сравнить сегодняшний компилятор со вчерашним
стало бы нечем.
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

RAILING_ID = "9200001"

#: Форма строки списана с настоящего ``railing_path_index`` k2_ar_rd_v9.
FREE_RAILING_ROW: dict[str, Any] = {
    "path_available": True,
    "points_mm": [[14880.0, 24575.0], [10920.0, 24575.0]],
    "curve_kinds": ["line"],
    "arc_midpoints_mm": [None],
    "plane_z_mm": 0.0,
    "has_host": False,
    "host_id": None,
    "base_level_id": "100",
}


def _document(*, level_id: str = "100") -> L0Document:
    element = make_element("OST_StairsRailing", 4200, ordinal=0)
    element["element_id"] = RAILING_ID
    element["level_id"] = level_id
    element["level_name"] = "Этаж 1"
    element["host_id"] = None
    payload = copy.deepcopy(project1_metadata())
    payload["change_stamp"] = "railing-v1"
    payload["elements"] = [element]
    payload["category_status"] = []
    return L0Document.from_dict(payload)


def _sketch_index(railing_row: dict[str, Any] | None) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": "sketch-extract/1",
        "profile_index": {},
        "stairs_run_path_index": {},
        "failures": [],
    }
    if railing_row is not None:
        envelope["railing_path_index"] = {RAILING_ID: railing_row}
    return envelope


def _node(document: L0Document, sketch: dict[str, Any] | None):
    result = lift_document_detailed(document, sketch, None)
    nodes = [n for n in result.nodes if n["source_element_id"] == RAILING_ID]
    assert len(nodes) == 1, nodes
    return nodes[0]


def _row(**overrides: Any) -> dict[str, Any]:
    row = copy.deepcopy(FREE_RAILING_ROW)
    row.update(overrides)
    return row


class AFreeRailingWithAPathBecomesAnOp(unittest.TestCase):
    def test_path_variety_carries_path_level_and_type(self) -> None:
        node = _node(_document(), _sketch_index(FREE_RAILING_ROW))
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_railing")
        params = node["params"]
        self.assertEqual(params["variety"], "path")
        self.assertEqual(
            params["path"], [[14880.0, 24575.0], [10920.0, 24575.0]])
        self.assertEqual(params["level"]["_id"], "100")
        self.assertIn("type", params)

    def test_the_op_validates_against_the_registry(self) -> None:
        """Форма пути — ТА, которую принимает прямой ход, а не похожая."""
        from kukai.ir.authoring_validation import validate

        node = _node(_document(), _sketch_index(FREE_RAILING_ROW))
        op = {"op": "create_railing", "id": "R1", **{
            k: v for k, v in node["params"].items() if k != "level"}}
        op["level"] = {"by": "name", "value": "Этаж 1"}
        op["type"] = {"by": "name", "value": op["type"]["value"]}
        diagnostics: list[Any] = []
        validate(op, "create_railing", 0, "R1", diagnostics)
        self.assertEqual(
            [d.code for d in diagnostics], [],
            [d.as_dict() for d in diagnostics])


class BordersThatDoNotMove(unittest.TestCase):
    def test_a_hosted_railing_stays_an_atom(self) -> None:
        """Позиции установки в API нет ни на одной версии — переложить
        лестничное ограждение в variety=path значило бы потерять хозяина."""
        node = _node(_document(), _sketch_index(
            _row(has_host=True, host_id="777", base_level_id=None)))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.MISSING_PARAMETER.value)
        self.assertIn("RailingPlacementPosition", node["reason"]["detail"])

    def test_an_unknown_host_state_stays_an_atom(self) -> None:
        """``has_host is None`` — «прочитать не удалось». Запись заведена
        трёхзначной ровно затем, чтобы это НЕ читалось как «хозяина нет»:
        свободное ограждение из неизвестности теряет хозяина так же молча,
        как и явная подмена."""
        node = _node(_document(), _sketch_index(_row(has_host=None)))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.MISSING_METADATA.value)

    def test_an_arc_in_the_path_stays_an_atom(self) -> None:
        node = _node(_document(), _sketch_index(_row(
            points_mm=[[0.0, 0.0], [1000.0, 0.0]],
            curve_kinds=["arc"],
            arc_midpoints_mm=[[500.0, 100.0]])))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.CURVE_KIND_UNSUPPORTED.value)

    def test_a_path_plane_off_its_base_level_stays_an_atom(self) -> None:
        """У create_railing нет параметра смещения: ограждение приехало бы
        обратно на другой отметке молча."""
        node = _node(_document(), _sketch_index(_row(plane_z_mm=1500.0)))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("offset", node["reason"]["detail"])

    def test_an_unreadable_path_stays_an_atom(self) -> None:
        node = _node(_document(), _sketch_index(_row(
            path_available=False, points_mm=[], curve_kinds=[],
            arc_midpoints_mm=[], plane_z_mm=None)))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.MISSING_GEOMETRY.value)


class ASnapshotTakenBeforeTheStageKeepsItsFormerAnswer(unittest.TestCase):
    """Правило дома. Проверяется ДОСЛОВНО, а не по коду причины."""

    HOSTLESS = ("frozen L0 has no railing path and no host id "
                "(ограждение в слепке — только габарит)")
    HOSTED = ("frozen L0 carries no RailingPlacementPosition for a hosted "
              "railing (host is known, placement side is not)")

    def test_no_index_at_all_keeps_the_hostless_refusal_verbatim(self) -> None:
        node = _node(_document(), None)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["detail"], self.HOSTLESS)

    def test_index_without_the_railing_key_keeps_it_verbatim(self) -> None:
        """Именно эта форма лежит на диске у sob62/демо/sklnk: конверт есть,
        ключа ``railing_path_index`` в нём нет."""
        node = _node(_document(), _sketch_index(None))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["detail"], self.HOSTLESS)

    def test_a_hosted_railing_without_the_stage_keeps_its_refusal(self) -> None:
        document = _document()
        object.__setattr__(document.elements[0], "host_id", "9001")
        node = _node(document, _sketch_index(None))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["detail"], self.HOSTED)


if __name__ == "__main__":
    unittest.main()
