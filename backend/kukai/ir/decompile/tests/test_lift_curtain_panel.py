"""Панель витража = ЯЧЕЙКА сетки носителя (дизайн 2026-07-28).

ЗАМЕР ДО ПОЧИНКИ (28.07, фасадная модель SOB6.2_FAS_R23, 3130 элементов
прочитано): 734 панели витража, поднято НОЛЬ. Синтетическая ячейка с полной
строкой бокового индекса становилась атомом ``no_lifter`` — «category is
outside the exact Part 5 lifter table», то есть категории не было в таблице
лифтеров вообще.

Тесты ниже держат три вещи, каждая из которых ломалась бы молча:

* ячейка с ПОЛНЫМ адресом поднимается в ``set_curtain_panel``;
* ячейка, чей тип равен типу разрезки носителя, — ``generator_child``, а не
  лишняя операция (правило СТРУКТУРНОЕ: тип против типа, никаких списков
  знакомых имён — INVARIANT #1);
* индекс схемы /1 (адреса не captured) даёт ТИПИЗИРОВАННЫЙ атом, а не
  догадку про ячейку (0,0).
"""
from __future__ import annotations

import copy
import json
import pathlib
import unittest
from typing import Any

from kukai.ir.decompile.curtain_extract import (
    CURTAIN_INDEX_SCHEMA_VERSION,
    CURTAIN_INDEX_SCHEMA_VERSION_LEGACY,
    CellAddressState,
)
from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.lift import lift_document_detailed
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)


HOST_ID = "9001"
CELL_ID = "9002"
BODY_ID = "9003"
DEFAULT_TYPE_ID = "7000"
GLAZING_TYPE_ID = "7001"
WALL_BODY_TYPE_ID = "7002"


def _panel_row(
    panel_id: str = CELL_ID,
    *,
    type_id: str | None = GLAZING_TYPE_ID,
    type_name: str | None = "Стеклопакет 30мм",
    u_index: int | None = 0,
    v_index: int | None = 0,
    address_state: str = CellAddressState.OK.value,
    host_panel_id: str | None = None,
    host_panel_type_id: str | None = None,
    host_panel_type_name: str | None = None,
) -> dict[str, Any]:
    return {
        "panel_id": panel_id,
        "is_family_instance": True,
        "family_name": "Системная панель",
        "type_name": type_name,
        "type_id": type_id,
        "host_panel_id": host_panel_id,
        "host_panel_type_id": host_panel_type_id,
        "host_panel_type_name": host_panel_type_name,
        "u_index": u_index,
        "v_index": v_index,
        "address_state": address_state,
        "is_door": False,
    }


def _index(
    panels: list[dict[str, Any]],
    *,
    default_panel_type_id: str | None = DEFAULT_TYPE_ID,
    default_panel_state: str | None = None,
    default_panel_source: str | None = "AUTO_PANEL_WALL",
    host_id: str = HOST_ID,
) -> dict[str, Any]:
    if default_panel_state is None:
        default_panel_state = (
            "ok" if default_panel_type_id else "not_captured")
    return {
        "schema_version": CURTAIN_INDEX_SCHEMA_VERSION,
        "curtain_index": {
            host_id: {
                "curtain_available": True,
                "host_kind": "wall",
                "default_panel_type_id": default_panel_type_id,
                "default_panel_type_name": (
                    "Системная панель по умолчанию"
                    if default_panel_type_id else None),
                "default_panel_state": default_panel_state,
                "default_panel_source": default_panel_source,
                "u_grid_lines": [],
                "v_grid_lines": [],
                "panels": panels,
                "mullions": [],
            },
        },
        "failures": [],
    }


def _legacy_index(host_id: str = HOST_ID) -> dict[str, Any]:
    """Индекс схемы /1 — тот, что лежит в каждом разборе до этой волны."""

    return {
        "schema_version": CURTAIN_INDEX_SCHEMA_VERSION_LEGACY,
        "curtain_index": {
            host_id: {
                "curtain_available": True,
                "u_grid_lines": [],
                "v_grid_lines": [],
                "panels": [{
                    "panel_id": CELL_ID,
                    "is_family_instance": True,
                    "family_name": "Системная панель",
                    "type_name": "Стеклопакет 30мм",
                    "host_panel_id": None,
                    "is_door": False,
                }],
                "mullions": [],
            },
        },
        "failures": [],
    }


def _document(*, with_body: bool = False) -> L0Document:
    wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
    wall["element_id"] = HOST_ID
    wall["type_name"] = "Витраж НР_ВТ"
    cell = make_element("OST_CurtainWallPanels", int(CELL_ID), ordinal=1)
    cell["element_id"] = CELL_ID
    cell["host_id"] = HOST_ID
    cell["geom_kind"] = "bbox_only"
    cell["p0_mm"] = cell["p1_mm"] = None
    cell["bbox_min_mm"] = cell["bbox_max_mm"] = None
    cell["type_id"] = GLAZING_TYPE_ID
    cell["type_name"] = "Стеклопакет 30мм"
    elements = [wall, cell]
    if with_body:
        body = make_element("OST_CurtainWallPanels", int(BODY_ID), ordinal=2)
        body["element_id"] = BODY_ID
        body["geom_kind"] = "curve"
        body["p0_mm"] = [0.0, 0.0, 0.0]
        body["p1_mm"] = [1500.0, 0.0, 0.0]
        body["host_id"] = None
        body["type_id"] = WALL_BODY_TYPE_ID
        body["type_name"] = "НР_ВТ_Сэндвич панель_30мм"
        elements.append(body)
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-cell-v1"
    row["elements"] = elements
    row["category_status"] = []
    return L0Document.from_dict(row)


def _document_body_only() -> L0Document:
    """Документ, где у ячейки есть ТОЛЬКО занятая панель.

    Ровно так выглядит переизвлечение пересобранной модели: замер
    ``sob62_fas_r23_v12/idempotence_debug.json`` — 20 переизвлечённых
    панелей витража, из них с ключом индекса (``panel_id``, занявший)
    совпало 0, а с ``host_panel_id`` (занятая) — все 20.
    """

    wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
    wall["element_id"] = HOST_ID
    wall["type_name"] = "Витраж НР_ВТ"
    body = make_element("OST_CurtainWallPanels", int(BODY_ID), ordinal=1)
    body["element_id"] = BODY_ID
    body["host_id"] = HOST_ID
    body["geom_kind"] = "bbox_only"
    body["p0_mm"] = body["p1_mm"] = None
    body["bbox_min_mm"] = body["bbox_max_mm"] = None
    body["type_id"] = WALL_BODY_TYPE_ID
    body["type_name"] = "НР_ВТ_Сэндвич панель_30мм"
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-cell-relift"
    row["elements"] = [wall, body]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _occupied_panels() -> list[dict[str, Any]]:
    """Занятая ячейка: занявший 9002 + занятая панель 9003."""

    return [_panel_row(
        type_id="7099", type_name="Системная панель: Стена",
        host_panel_id=BODY_ID, host_panel_type_id=WALL_BODY_TYPE_ID,
        host_panel_type_name="НР_ВТ_Сэндвич панель_30мм")]


def _by_source(result) -> dict[str, dict[str, Any]]:
    return {node["source_element_id"]: node for node in result.nodes}


class CurtainCellLift(unittest.TestCase):
    def test_addressed_cell_becomes_set_curtain_panel(self) -> None:
        result = lift_document_detailed(
            _document(), curtain_index=_index([_panel_row(u_index=2,
                                                          v_index=1)]))
        nodes = _by_source(result)
        cell = nodes[CELL_ID]
        self.assertEqual(cell["kind"], "op", cell.get("reason"))
        self.assertEqual(cell["op_name"], "set_curtain_panel")
        self.assertEqual(cell["params"]["u"], 2)
        self.assertEqual(cell["params"]["v"], 1)
        self.assertEqual(
            cell["params"]["panel_type"],
            {"by": "name", "value": "Стеклопакет 30мм",
             "_id": GLAZING_TYPE_ID})
        self.assertEqual(
            cell["params"]["host"], {"ref": nodes[HOST_ID]["_id"]})

    def test_type_equal_to_the_hosts_own_cut_is_generator_child(self) -> None:
        """СТРУКТУРНОЕ правило: тип против типа, а не список знакомых имён."""

        result = lift_document_detailed(
            _document(),
            curtain_index=_index([_panel_row(type_id=DEFAULT_TYPE_ID)]))
        cell = _by_source(result)[CELL_ID]
        self.assertEqual(cell["kind"], "atom")
        self.assertEqual(
            cell["reason"]["code"], AtomReason.GENERATOR_CHILD.value)

    def test_wall_filled_cell_carries_the_bodys_type_and_body_is_child(
            self) -> None:
        """Ячейка со стеной — ДВА элемента Revit; операция ровно одна."""

        panels = [_panel_row(
            type_id="7099", type_name="Системная панель: Стена",
            host_panel_id=BODY_ID, host_panel_type_id=WALL_BODY_TYPE_ID,
            host_panel_type_name="НР_ВТ_Сэндвич панель_30мм")]
        result = lift_document_detailed(
            _document(with_body=True), curtain_index=_index(panels))
        nodes = _by_source(result)
        cell = nodes[CELL_ID]
        self.assertEqual(cell["kind"], "op", cell.get("reason"))
        self.assertEqual(
            cell["params"]["panel_type"]["value"],
            "НР_ВТ_Сэндвич панель_30мм",
            "тип ячейки — тип ТЕЛА, а не системной обёртки")
        body = nodes[BODY_ID]
        self.assertEqual(body["kind"], "atom")
        self.assertEqual(
            body["reason"]["code"], AtomReason.GENERATOR_CHILD.value)

    def test_cell_is_found_by_the_occupied_panel_when_the_occupant_is_gone(
            self) -> None:
        """У ЗАНЯТОЙ ЯЧЕЙКИ ДВА ИМЕНИ — ре-лифт знает второе.

        ЗАМЕР ДО ПОЧИНКИ (v12, пересборка №6): индекс ключует ячейку по id
        занявшего, переизвлечение отдаёт id занятой панели; пересечения
        ключей НОЛЬ. Лифт получал None, уходил в общий путь размещения и
        давал 0 листьев ячеек там, где их ждали 20 — расхождение
        идемпотентности на ровном месте.
        """

        result = lift_document_detailed(
            _document_body_only(), curtain_index=_index(_occupied_panels()))
        nodes = _by_source(result)
        cell = nodes[BODY_ID]
        self.assertEqual(cell["kind"], "op", cell.get("reason"))
        self.assertEqual(cell["op_name"], "set_curtain_panel")
        self.assertEqual(cell["params"]["u"], 0)
        self.assertEqual(cell["params"]["v"], 0)
        self.assertEqual(
            cell["params"]["panel_type"]["value"],
            "НР_ВТ_Сэндвич панель_30мм")

    def test_two_names_of_one_cell_never_make_two_operations(self) -> None:
        """Мультимножество: обе стороны в документе — лист ровно один.

        В исходной модели присутствуют ОБЕ стороны у всех 372 занятых
        ячеек v12; если бы второе имя порождало свой лист, пересборка
        построила бы каждую такую ячейку дважды.
        """

        result = lift_document_detailed(
            _document(with_body=True), curtain_index=_index(
                _occupied_panels()))
        cells = [node for node in result.nodes
                 if node["kind"] == "op"
                 and node.get("op_name") == "set_curtain_panel"]
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0]["source_element_id"], CELL_ID)
        body = _by_source(result)[BODY_ID]
        self.assertEqual(body["kind"], "atom")
        self.assertEqual(
            body["reason"]["code"], AtomReason.GENERATOR_CHILD.value)
        sources = [node["source_element_id"] for node in result.nodes]
        self.assertEqual(len(sources), len(set(sources)))

    def test_one_cell_hashes_the_same_from_either_of_its_two_names(
            self) -> None:
        """Канон не должен зависеть от того, какой элемент попал в документ.

        ЗАМЕР (v12): у 20 ячеек, поднятых с двух сторон, ``params``
        совпадали побайтно, а канонический хеш — ни разу: расходился
        ``type_name`` листа («Стена» — имя системной обёртки занявшего —
        против имени типа, которым ячейка заполнена). Для сравнения
        идемпотентности это выглядело расхождением модели, которого нет.
        """

        from kukai.ir.decompile.fold import FidelityCanon

        origin = (0.0, 0.0, 0.0)
        panels = _occupied_panels()

        def _cell_hash(document) -> str:
            result = lift_document_detailed(
                document, curtain_index=_index(panels))
            hashes = FidelityCanon.hash_sequence(result.nodes, origin)
            cells = [
                digest for digest, node in zip(hashes, result.nodes)
                if node.get("op_name") == "set_curtain_panel"]
            self.assertEqual(len(cells), 1)
            return cells[0]

        self.assertEqual(
            _cell_hash(_document(with_body=True)),
            _cell_hash(_document_body_only()))

    def test_legacy_index_without_an_address_is_a_typed_atom(self) -> None:
        """Схема /1 адреса не несёт — и догадываться про (0,0) нельзя."""

        result = lift_document_detailed(
            _document(), curtain_index=_legacy_index())
        cell = _by_source(result)[CELL_ID]
        self.assertEqual(cell["kind"], "atom")
        self.assertEqual(
            cell["reason"]["code"], AtomReason.MISSING_METADATA.value)
        self.assertIn("not_captured", cell["reason"]["detail"])

    def test_unknown_host_default_type_refuses_instead_of_guessing(
            self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index([_panel_row()], default_panel_type_id=None))
        cell = _by_source(result)[CELL_ID]
        self.assertEqual(cell["kind"], "atom")
        self.assertEqual(
            cell["reason"]["code"], AtomReason.MISSING_METADATA.value)
        self.assertIn("not_captured", cell["reason"]["detail"])

    def test_a_host_that_cuts_no_panel_makes_every_cell_authored(self) -> None:
        """``none`` — это ПРОЧИТАННЫЙ факт, а не отсутствие факта.

        Носитель без автоматической панели не порождает ни одной ячейки,
        значит каждая занятая назначена автором. Отличать это состояние от
        «не смогли прочитать» и есть цена живого прогона v4.
        """

        result = lift_document_detailed(
            _document(),
            curtain_index=_index([_panel_row()], default_panel_type_id=None,
                                 default_panel_state="none"))
        cell = _by_source(result)[CELL_ID]
        self.assertEqual(cell["kind"], "op", cell.get("reason"))
        self.assertEqual(cell["op_name"], "set_curtain_panel")

    def test_unreadable_default_names_what_was_tried(self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                [_panel_row()], default_panel_type_id=None,
                default_panel_state="unreadable",
                default_panel_source="tried: AUTO_PANEL_WALL, AUTO_PANEL"))
        cell = _by_source(result)[CELL_ID]
        self.assertEqual(cell["kind"], "atom")
        self.assertEqual(
            cell["reason"]["code"], AtomReason.MISSING_METADATA.value)
        self.assertIn("unreadable", cell["reason"]["detail"])
        self.assertIn("AUTO_PANEL_WALL", cell["reason"]["detail"])

    def test_without_any_curtain_index_the_panel_stays_an_honest_atom(
            self) -> None:
        """Прежний путь сохранён дословно: нет индекса — нет и операции."""

        result = lift_document_detailed(_document())
        cell = _by_source(result)[CELL_ID]
        self.assertEqual(cell["kind"], "atom")
        self.assertNotEqual(cell.get("op_name"), "set_curtain_panel")

    def test_lifted_cell_compiles_to_a_program(self) -> None:
        """Оп обязан пройти разбор компилятора — иначе он невыразим."""

        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.decompile.materialize import leaves_to_program

        result = lift_document_detailed(
            _document(), curtain_index=_index([_panel_row()]))
        materialized = leaves_to_program(result.nodes)
        ops = [op for program in materialized.programs
               for op in program["ops"]]
        for program in materialized.programs:
            _parse_and_check(program)
        cell_ops = [op for op in ops if op["op"] == "set_curtain_panel"]
        self.assertEqual(len(cell_ops), 1)
        self.assertEqual(cell_ops[0]["u"], 0)
        self.assertEqual(cell_ops[0]["panel_type"],
                         {"by": "element_id", "value": int(GLAZING_TYPE_ID)})
        self.assertEqual(cell_ops[0]["host"]["by"], "ref")



# ── Живая строка индекса: фасад SOB6.2, Revit 2023, разбор v4 (28.07) ────────
#
# Скопирована ДОСЛОВНО из backend/data/decompile/sob62_fas_r23_v4/
# curtain.index.json, носитель 8152799 — витраж с сеткой 2×2. Опущены только
# ``mullions`` (11 однотипных строк, лифт ячеек их не читает); всё остальное —
# байт в байт, что и проверяет ``LiveArtifactFixtureDoesNotDrift``.
#
# Ради чего фикстура ЖИВАЯ, а не синтетическая: синтетика этой волны была
# зелёной, пока живой прогон не показал, что тип разрезки носителя не
# читается вовсе. Синтетика проверяет то, что мы придумали; живая строка —
# то, что модель отдала на самом деле.
LIVE_V4_HOST_ID = "8152799"
LIVE_V4_HOST_ROW: dict[str, Any] = {
    "curtain_available": True,
    "default_panel_type_id": None,
    "default_panel_type_name": None,
    "host_kind": "wall",
    "panels": [
        {
            "address_state": "ok",
            "family_name": "Системная панель",
            "host_panel_id": "8152801",
            "host_panel_type_id": "7469627",
            "host_panel_type_name": "НР_ВТ_Стеклопакет_30мм",
            "is_door": False,
            "is_family_instance": True,
            "panel_id": "8152800",
            "type_id": "1715",
            "type_name": "Стена",
            "u_index": 0,
            "v_index": 0,
        },
        {
            "address_state": "ok",
            "family_name": "Системная панель",
            "host_panel_id": "8152819",
            "host_panel_type_id": "7469627",
            "host_panel_type_name": "НР_ВТ_Стеклопакет_30мм",
            "is_door": False,
            "is_family_instance": True,
            "panel_id": "8152812",
            "type_id": "1715",
            "type_name": "Стена",
            "u_index": 0,
            "v_index": 1,
        },
        {
            "address_state": "not_a_panel",
            "family_name": "ATR_Окно_Витражное",
            "host_panel_id": None,
            "host_panel_type_id": None,
            "host_panel_type_name": None,
            "is_door": False,
            "is_family_instance": True,
            "panel_id": "8152807",
            "type_id": "10617319",
            "type_name": (
                "ATR_Окно_Л_Витражное_Поворотно откидное_Без ограждения"),
            "u_index": None,
            "v_index": None,
        },
        {
            "address_state": "ok",
            "family_name": "Системная панель",
            "host_panel_id": None,
            "host_panel_type_id": None,
            "host_panel_type_name": None,
            "is_door": False,
            "is_family_instance": True,
            "panel_id": "8152813",
            "type_id": "273243",
            "type_name": "ПН_ВТ_Стеклопакет_ теплый_30 мм",
            "u_index": 1,
            "v_index": 1,
        },
    ],
    "u_grid_lines": [{
        "curve_state": "line",
        "existing_segment_count": 1,
        "line_id": "8152806",
        "locked": False,
        "p0_mm": [19234.895232480907, 33845.63573928605, 3389.99999999986],
        "p1_mm": [20795.00088221789, 34382.82319413963, 3389.99999999986],
        "skipped_segment_count": 1,
    }],
    "v_grid_lines": [{
        "curve_state": "line",
        "existing_segment_count": 2,
        "line_id": "8152811",
        "locked": False,
        "p0_mm": [19944.03416418041, 34089.811855128886, 2614.9999999998604],
        "p1_mm": [19944.03416418041, 34089.811855128886, 5449.999999999856],
        "skipped_segment_count": 0,
    }],
    "mullions": [],
}

_LIVE_ARTIFACT = (
    pathlib.Path(__file__).resolve().parents[4]
    / "backend" / "data" / "decompile" / "sob62_fas_r23_v4"
    / "curtain.index.json")


def _live_index(**host_overrides: Any) -> dict[str, Any]:
    row = copy.deepcopy(LIVE_V4_HOST_ROW)
    row.update(host_overrides)
    return {
        "schema_version": "kir-decompile-curtain-index/2",
        "curtain_index": {LIVE_V4_HOST_ID: row},
        "failures": [],
    }


def _live_document() -> L0Document:
    """L0 с ЖИВЫМИ идентификаторами носителя, тел ячеек и оконной панели."""

    elements = []
    wall = make_element("OST_Walls", 1, ordinal=0)
    wall["element_id"] = LIVE_V4_HOST_ID
    wall["type_id"] = "7463740"
    wall["type_name"] = "НР_ВТ_(250х50)_Без нарезки_Теплый_Заполнение-Стемалит"
    elements.append(wall)
    for index, (panel_id, body_id) in enumerate(
            (("8152800", "8152801"), ("8152812", "8152819"),
             ("8152813", None)), start=1):
        cell = make_element("OST_CurtainWallPanels", 100 + index,
                            ordinal=index)
        cell["element_id"] = panel_id
        cell["host_id"] = LIVE_V4_HOST_ID
        cell["geom_kind"] = "bbox_only"
        cell["p0_mm"] = cell["p1_mm"] = None
        cell["bbox_min_mm"] = cell["bbox_max_mm"] = None
        elements.append(cell)
        if body_id is None:
            continue
        body = make_element("OST_CurtainWallPanels", 200 + index,
                            ordinal=index)
        body["element_id"] = body_id
        body["geom_kind"] = "curve"
        body["p0_mm"] = [0.0, 0.0, 0.0]
        body["p1_mm"] = [1500.0, 0.0, 0.0]
        body["host_id"] = None
        body["type_id"] = "7469627"
        body["type_name"] = "НР_ВТ_Стеклопакет_30мм"
        elements.append(body)
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "live-v4-row"
    row["elements"] = elements
    row["category_status"] = []
    return L0Document.from_dict(row)


class TheLiveV4RowIsDiagnosedNotGuessed(unittest.TestCase):
    """Что ИМЕННО живой разбор v4 говорит про свои 311 ячеек."""

    def test_v4_as_it_stands_lifts_nothing_and_says_why(self) -> None:
        """ОПРОВЕРГАЮЩИЙ ЗАМЕР: адрес доехал, тип разрезки — нет.

        Ровно этот исход дал живой прогон: все ячейки — атомы, и причина
        обязана указывать на НЕПРОЧИТАННОЕ состояние, а не на выдуманное
        «панель штатная».
        """

        result = lift_document_detailed(
            _live_document(), curtain_index=_live_index())
        nodes = _by_source(result)
        for panel_id in ("8152800", "8152812", "8152813"):
            with self.subTest(panel=panel_id):
                node = nodes[panel_id]
                self.assertEqual(node["kind"], "atom")
                self.assertEqual(
                    node["reason"]["code"],
                    AtomReason.MISSING_METADATA.value)
                self.assertIn("not_captured", node["reason"]["detail"])
        ops = [n for n in result.nodes
               if n.get("op_name") == "set_curtain_panel"]
        self.assertEqual(ops, [])

    def test_the_same_live_row_lifts_once_the_default_is_read(self) -> None:
        """Починка звена — и те же три ячейки становятся операциями."""

        index = _live_index(
            default_panel_type_id="273243",
            default_panel_type_name="ПН_ВТ_Стеклопакет_ теплый_30 мм",
            default_panel_state="ok",
            default_panel_source="AUTO_PANEL_WALL")
        index["schema_version"] = "kir-decompile-curtain-index/3"
        result = lift_document_detailed(_live_document(), curtain_index=index)
        nodes = _by_source(result)
        # Две ячейки заполнены СТЕНОЙ — их тип берётся у тела, он отличается
        # от типа разрезки, значит это назначения автора.
        for panel_id, u, v in (("8152800", 0, 0), ("8152812", 0, 1)):
            with self.subTest(panel=panel_id):
                node = nodes[panel_id]
                self.assertEqual(node["kind"], "op", node.get("reason"))
                self.assertEqual(node["op_name"], "set_curtain_panel")
                self.assertEqual(node["params"]["u"], u)
                self.assertEqual(node["params"]["v"], v)
                self.assertEqual(
                    node["params"]["panel_type"]["value"],
                    "НР_ВТ_Стеклопакет_30мм")
        # Третья ячейка держит РОВНО тип разрезки — она порождаемая.
        standard = nodes["8152813"]
        self.assertEqual(standard["kind"], "atom")
        self.assertEqual(
            standard["reason"]["code"], AtomReason.GENERATOR_CHILD.value)
        # Тела ячеек — тоже порождаемые, отдельной операции у них нет.
        for body_id in ("8152801", "8152819"):
            with self.subTest(body=body_id):
                self.assertEqual(
                    nodes[body_id]["reason"]["code"],
                    AtomReason.GENERATOR_CHILD.value)

    def test_a_host_with_no_automatic_panel_authors_every_live_cell(
            self) -> None:
        index = _live_index(default_panel_state="none",
                            default_panel_source="AUTO_PANEL_WALL")
        index["schema_version"] = "kir-decompile-curtain-index/3"
        result = lift_document_detailed(_live_document(), curtain_index=index)
        ops = [n for n in result.nodes
               if n.get("op_name") == "set_curtain_panel"]
        self.assertEqual(len(ops), 3)

    def test_the_window_cell_stays_honestly_unaddressed(self) -> None:
        """Витражное окно — не ``Panel``; ``GetRefGridLines`` для него нет.

        Живой замер v4: 50 таких ячеек. Адрес им придумывать нечем, и
        строка индекса говорит это прямо (``not_a_panel``), а не молчит.
        """

        from kukai.ir.decompile.curtain_extract import (
            CellAddressState, CurtainWallRecord)

        record = CurtainWallRecord.from_dict(
            LIVE_V4_HOST_ID, LIVE_V4_HOST_ROW)
        window = next(p for p in record.panels if p.panel_id == "8152807")
        self.assertIs(window.address_state, CellAddressState.NOT_A_PANEL)
        self.assertIsNone(window.u_index)


class LiveArtifactFixtureDoesNotDrift(unittest.TestCase):
    def test_embedded_row_matches_the_artifact_when_it_is_present(
            self) -> None:
        """Живая фикстура обязана оставаться живой.

        Артефакт в репозиторий не входит; когда он есть на машине —
        сверяемся с ним. Иначе «живая строка» через месяц станет такой же
        синтетикой, только с ореолом достоверности.
        """

        if not _LIVE_ARTIFACT.is_file():
            self.skipTest(f"нет артефакта {_LIVE_ARTIFACT}")
        actual = json.loads(_LIVE_ARTIFACT.read_text(encoding="utf-8"))
        row = actual["curtain_index"][LIVE_V4_HOST_ID]
        for key, expected in LIVE_V4_HOST_ROW.items():
            if key == "mullions":
                continue
            with self.subTest(field=key):
                self.assertEqual(row[key], expected)


if __name__ == "__main__":
    unittest.main()


class TheMullionBelongsToTheGridNotToPlaceFamily(unittest.TestCase):
    """Импост витража — элемент ЛИНИИ РАЗРЕЗКИ, а не экземпляр в точке.

    ЗАМЕР 28.07 (живой разбор v6, фасад SOB6.2): 956 импостов — 42% всех
    опов модели — поднимались в ``place_family`` с точкой и хостом-стеной.
    При пересборке витраж порождает СВОИ импосты по правилам типа, а наши
    956 легли бы поверх: число опов росло от нашего же дубля.

    ДОКАЗАТЕЛЬСТВО (RevitAPI.xml эталонного пакета, не вики): единственный
    конструктор — ``CurtainGridLine.AddMullions(Curve segment, MullionType,
    bool oneSegmentOnly)``, «add mullions on the specified segments of a
    grid»; у самого ``Mullion`` — ``LocationCurve``, а не точка. Экземпляром
    семейства импост не ставится, хотя классом и является FamilyInstance —
    из-за чего боковой индекс размещений честно отдаёт про него строку.

    Причина отказа — ДЫРА (``unsupported_forward_signature``), а не
    ``generator_child``: часть импостов порождается типом носителя (317 из
    956 на модели замера сидят на носителях БЕЗ линий разрезки, то есть это
    борта типа), а часть могла быть добавлена автором на сегмент. Разделить
    их можно только захватом параметров ``AUTO_MULLION_*`` у типа носителя;
    до тех пор честнее НЕ вычитать их из знаменателя, чем вычесть лишнее.
    """

    #: Импост 10006235 носителя 10006233 — строка ЖИВОГО разбора v6.
    LIVE_MULLION_ID = "10006235"
    LIVE_MULLION_HOST = "10006233"

    def _document(self) -> L0Document:
        wall = make_element("OST_Walls", 1, ordinal=0)
        wall["element_id"] = self.LIVE_MULLION_HOST
        wall["type_name"] = "НР_ВТ_(250х50)_Без нарезки_Заполнение_Вентрешетка"
        mullion = make_element("OST_CurtainWallMullions", 2, ordinal=1)
        mullion["element_id"] = self.LIVE_MULLION_ID
        mullion["host_id"] = self.LIVE_MULLION_HOST
        mullion["geom_kind"] = "point"
        mullion["p0_mm"] = [10820.47, 31038.21, 5450.0]
        mullion["rotation_deg"] = 193.40410108427128
        mullion["type_name"] = "20х70 мм_Смещение -75мм"
        mullion["type_id"] = "7924564"
        row = copy.deepcopy(project1_metadata())
        row["change_stamp"] = "live-v6-mullion"
        row["elements"] = [wall, mullion]
        row["category_status"] = []
        return L0Document.from_dict(row)

    def _index(self) -> dict[str, Any]:
        return {
            "schema_version": CURTAIN_INDEX_SCHEMA_VERSION,
            "curtain_index": {
                self.LIVE_MULLION_HOST: {
                    "curtain_available": True,
                    "host_kind": "wall",
                    "default_panel_type_id": "7924568",
                    "default_panel_type_name": "Вентиляционная решетка",
                    "default_panel_state": "ok",
                    "default_panel_source": "AUTO_PANEL_WALL",
                    "u_grid_lines": [], "v_grid_lines": [], "panels": [],
                    "mullions": [{
                        "mullion_id": self.LIVE_MULLION_ID,
                        "type_name": "20х70 мм_Смещение -75мм",
                        "curve_state": "curved_unsupported",
                        "p0_mm": None, "p1_mm": None,
                    }],
                },
            },
            "failures": [],
        }

    def _placements(self) -> dict[str, Any]:
        """Строка бокового индекса размещений — ровно как в живом v6."""

        return {
            self.LIVE_MULLION_ID: {
                "facing_flipped": False,
                "facing_orientation": [
                    0.32556815445711346, -0.9455185755993317, 0.0],
                "family_name": "Прямоугольный импост",
                "group_id": None,
                "hand_flipped": False,
                "hand_orientation": [0.0, 0.0, 1.0],
                "host_class": "Wall",
                "host_id": self.LIVE_MULLION_HOST,
                "in_place": False,
                "mirrored": False,
                "placement_available": True,
                "placement_type": "OneLevelBased",
                "point_mm": [
                    10820.472173785438, 31038.215288177897, 5449.999999999861],
                "rotation_deg": 193.40410108427128,
                "super_component_id": None,
                "symbol_id": "7924564",
                "type_name": "20х70 мм_Смещение -75мм",
            },
        }

    def test_without_the_curtain_index_the_mullion_becomes_place_family(
            self) -> None:
        """Пре-состояние, зафиксированное намеренно: вот что было до правила."""

        result = lift_document_detailed(
            self._document(), None, self._placements())
        node = _by_source(result)[self.LIVE_MULLION_ID]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "place_family")

    def test_a_mullion_named_by_its_grid_is_a_typed_hole(self) -> None:
        result = lift_document_detailed(
            self._document(), None, self._placements(),
            curtain_index=self._index())
        node = _by_source(result)[self.LIVE_MULLION_ID]
        self.assertEqual(node["kind"], "atom", node.get("op_name"))
        self.assertEqual(
            node["reason"]["code"], AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("AddMullions", node["reason"]["detail"])
        self.assertIn(self.LIVE_MULLION_HOST, node["reason"]["detail"])

    def test_the_hole_is_not_subtracted_from_honest_coverage(self) -> None:
        """generator_child вычитается из знаменателя, дыра — нет.

        Пометить импосты порождаемыми было бы приятнее (покрытие не упало
        бы), но неправдой: часть из них автор добавил сам, и воспроизвести
        их нам нечем.
        """

        result = lift_document_detailed(
            self._document(), None, self._placements(),
            curtain_index=self._index())
        node = _by_source(result)[self.LIVE_MULLION_ID]
        self.assertNotEqual(
            node["reason"]["code"], AtomReason.GENERATOR_CHILD.value)
