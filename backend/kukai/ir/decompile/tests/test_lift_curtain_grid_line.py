"""Раскладка сетки витража — недостающее звено генератора.

ЗАМЕР НОЧИ 28.07 (``kir-night/artifacts/child_closure_20260728.json``):
замыкание детей 417/1556 = 27%, и у ВСЕХ пересобранных носителей НОЛЬ
внутренних U/V линий при БАЙТ-ИДЕНТИЧНЫХ типах. Диагноз оттуда прямой:
раскладка сетки — авторское состояние, которого ``create_wall`` не несёт, и
без него у витража не воспроизводится ни одна ячейка, ни один импост и ни
одна панель — вся семья детей носителя.

ПРЕД-СОСТОЯНИЕ (v13, схема индекса /4): у 70 носителей есть линии — 122
штуки, у всех прочитана прямая кривая с концами в мм, — и НИ ОДНОЙ операции
на них. Линии нет и в L0: её категорию коллектор не собирает вовсе (замер:
122 линии индекса, 0 среди 3153 элементов L0). Поэтому узел не поднимается
с элемента, а СИНТЕЗИРУЕТСЯ из бокового индекса и ссылается на носителя.

ЧЕСТНОСТЬ. Линия становится операцией ТОЛЬКО когда доказано, что тип
носителя не делает её сам: раскладка типа (шесть параметров
``SPACING_LAYOUT_*``) читается схемой /5 и сравнивается с нулём — ЧИСЛОМ, а
не толкованием имени. Тип делит сетку сам ⇒ операции нет: удвоенная линия
хуже отсутствующей. Раскладка не прочитана ⇒ тоже нет, и причина названа.

СТРОКИ ВЗЯТЫ ЖИВЫЕ: носитель ``8145922`` и его линия ``8145929`` с
концами из ``data/decompile/sob62_fas_r23_v13/curtain.index.json``;
раскладка типа дописана здесь и помечена как дописанная (живого извлечения
схемой /5 ещё не было).
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kukai.ir.decompile.curtain_extract import (
    CURTAIN_INDEX_SCHEMA_VERSION,
    CURTAIN_INDEX_SCHEMA_VERSION_MULLION,
    GRID_LAYOUT_NONE,
    CurtainWallRecord,
    GridLayout,
    GridLayoutState,
    GridLineState,
)
from kukai.ir.decompile.l1_schema import AtomReason, stable_l1_id
from kukai.ir.decompile.lift import lift_document_detailed
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)


HOST_ID = "8145922"
LINE_ID = "8145929"
P0 = [6890.514473904456, 28537.503893960205, 4924.999999999713]
P1 = [8545.171981203326, 29107.24816426004, 4924.999999999713]
#: Середина живой линии — точка, через которую её ставит AddGridLine.
MID = [round((a + b) / 2.0, 6) for a, b in zip(P0, P1)]


def _line_row(line_id: str = LINE_ID, *,
              curve_state: str = "line") -> dict[str, Any]:
    straight = curve_state == "line"
    return {
        "line_id": line_id,
        "curve_state": curve_state,
        "p0_mm": P0 if straight else None,
        "p1_mm": P1 if straight else None,
        "existing_segment_count": 1,
        "skipped_segment_count": 0,
        "locked": False,
    }


def _layout(**values: int) -> dict[str, Any]:
    return {
        "slots": dict(values),
        "state": (GridLayoutState.OK.value if values
                  else GridLayoutState.NONE.value),
    }


def _index(
    *,
    u_lines: list[dict[str, Any]] | None = None,
    v_lines: list[dict[str, Any]] | None = None,
    grid_layout: dict[str, Any] | None = None,
    schema_version: str = CURTAIN_INDEX_SCHEMA_VERSION,
    host_id: str = HOST_ID,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "curtain_available": True,
        "host_kind": "wall",
        "default_panel_type_id": "7469627",
        "default_panel_type_name": "НР_ВТ_Стеклопакет_30мм",
        "default_panel_state": "ok",
        "default_panel_source": "AUTO_PANEL_WALL",
        "auto_mullion_types": {"slots": {}, "state": "not_captured"},
        "u_grid_lines": [] if u_lines is None else u_lines,
        "v_grid_lines": [] if v_lines is None else v_lines,
        "panels": [],
        "mullions": [],
    }
    if grid_layout is not None:
        row["grid_layout"] = grid_layout
    return {
        "schema_version": schema_version,
        "curtain_index": {host_id: row},
        "failures": [],
    }


def _line_element(element_id: str, ordinal: int = 1) -> dict[str, Any]:
    """Строка L0 линии разрезки — как её отдаёт экстрактор после починки.

    Категория взята из ПЕРЕПИСИ ЖИВОЙ МОДЕЛИ v14: ``OST_CurtainGridsWall``,
    122 элемента — ровно столько, сколько линий в curtain-индексе того же
    прогона. Ни типа, ни точки размещения у линии нет, и строка это честно
    показывает: узел строится не из неё, а из бокового индекса.
    """

    return {
        "element_id": element_id,
        "category": "OST_CurtainGridsWall",
        "category_ru": "Схемы разрезки витражей",
        "type_id": "0",
        "type_name": "",
        "level_id": None,
        "level_name": None,
        # Геометрия строки L0 роли не играет: узел строится из бокового
        # индекса, а не из неё. Форма взята как у соседей по витражу в
        # живом L0 v14 (импост — point с координатами).
        "geom_kind": "bbox_only",
        "p0_mm": None,
        "p1_mm": None,
        "rotation_deg": None,
        "bbox_min_mm": P0,
        "bbox_max_mm": P1,
        "host_id": HOST_ID,
        "params": {},
        "design_option": None,
        "phase_created": None,
        "workset": None,
    }


def _document(line_ids: tuple[str, ...] = (LINE_ID,)) -> L0Document:
    """Носитель и его линии — обе стороны в L0, как после починки чтения."""

    wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
    wall["element_id"] = HOST_ID
    wall["type_name"] = "НР_ВТ_(250х50)_Без нарезки_Теплый"
    elements = [wall] + [
        _line_element(line_id, ordinal)
        for ordinal, line_id in enumerate(line_ids, start=1)]
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-grid-line-v1"
    row["elements"] = elements
    row["category_status"] = []
    return L0Document.from_dict(row)


def _document_without_the_line() -> L0Document:
    """Линия есть в индексе, но НЕ прочитана — пред-состояние v14."""

    wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
    wall["element_id"] = HOST_ID
    wall["type_name"] = "НР_ВТ_(250х50)_Без нарезки_Теплый"
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-grid-line-unread"
    row["elements"] = [wall]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lines(result) -> list[dict[str, Any]]:
    return [node for node in result.nodes
            if node.get("op_name") == "create_curtain_grid_line"]


class GridLineVerdict(unittest.TestCase):
    """Вердикт считается по числам раскладки, без всякого лифта."""

    @staticmethod
    def _record(layout: GridLayout) -> CurtainWallRecord:
        return CurtainWallRecord.from_dict(HOST_ID, {
            "curtain_available": True,
            "host_kind": "wall",
            "default_panel_type_id": None,
            "default_panel_type_name": None,
            "default_panel_state": "not_captured",
            "default_panel_source": None,
            "auto_mullion_types": {"slots": {}, "state": "not_captured"},
            "grid_layout": layout.to_dict(),
            "u_grid_lines": [_line_row()],
            "v_grid_lines": [],
            "panels": [],
            "mullions": [],
        })

    def test_layout_zero_means_the_line_is_authored(self) -> None:
        record = self._record(GridLayout.from_wire(
            _layout(vert=GRID_LAYOUT_NONE, horiz=GRID_LAYOUT_NONE), "l"))
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.MANUAL)

    def test_a_dividing_type_makes_the_line_its_own(self) -> None:
        record = self._record(GridLayout.from_wire(_layout(vert=2), "l"))
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.TYPE_DRIVEN)

    def test_a_type_without_layout_parameters_divides_nothing(self) -> None:
        """``none`` — прочитанный факт: параметров раскладки у типа нет."""

        record = self._record(GridLayout.from_wire(_layout(), "l"))
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.MANUAL)

    def test_unreadable_layout_is_not_a_guess(self) -> None:
        record = self._record(GridLayout.from_wire(
            {"slots": {}, "state": GridLayoutState.UNREADABLE.value}, "l"))
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.UNREADABLE)

    def test_schema_before_five_says_not_captured(self) -> None:
        record = self._record(GridLayout.not_captured())
        self.assertEqual(
            record.grid_line_state(record.u_grid_lines[0]),
            GridLineState.NOT_CAPTURED)


class GridLineLift(unittest.TestCase):
    def test_v4_row_yields_no_operation_and_says_why(self) -> None:
        """ПРЕД-СОСТОЯНИЕ: 122 линии v13 — и ни одной операции."""

        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                u_lines=[_line_row()],
                schema_version=CURTAIN_INDEX_SCHEMA_VERSION_MULLION))
        self.assertEqual(_lines(result), [])
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(len(skipped), 1)
        self.assertIn("раскладки типа не читала", skipped[0].detail)

    def test_authored_line_becomes_an_operation_on_the_host(self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE,
                                    horiz=GRID_LAYOUT_NONE)))
        lines = _lines(result)
        self.assertEqual(len(lines), 1)
        line = lines[0]
        self.assertEqual(line["params"]["direction"], "u")
        self.assertEqual(line["params"]["position_mm"], MID)
        self.assertEqual(line["source_element_id"], LINE_ID)
        host = [n for n in result.nodes
                if n["source_element_id"] == HOST_ID][0]
        self.assertEqual(line["params"]["host"], {"ref": host["_id"]})

    def test_direction_comes_from_the_axis_the_index_put_it_on(self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                v_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        self.assertEqual(_lines(result)[0]["params"]["direction"], "v")

    def test_a_dividing_type_emits_nothing_and_names_the_reason(self) -> None:
        """Удвоенная линия хуже отсутствующей — оп не эмитируется."""

        result = lift_document_detailed(
            _document(),
            curtain_index=_index(u_lines=[_line_row()],
                                 grid_layout=_layout(vert=2)))
        self.assertEqual(_lines(result), [])
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0].reason, AtomReason.GENERATOR_CHILD)
        self.assertIn("делит сетку сам", skipped[0].detail)

    def test_a_curve_that_is_not_a_line_refuses_instead_of_guessing(
            self) -> None:
        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                u_lines=[_line_row(curve_state="curved_unsupported")],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        self.assertEqual(_lines(result), [])
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(
            skipped[0].reason, AtomReason.CURVE_KIND_UNSUPPORTED)

    def test_two_lines_make_two_operations_and_no_duplicates(self) -> None:
        """Мультимножество: сколько линий в индексе, столько и операций."""

        result = lift_document_detailed(
            _document(("8145929", "8145930", "8145931")),
            curtain_index=_index(
                u_lines=[_line_row("8145929"), _line_row("8145930")],
                v_lines=[_line_row("8145931")],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        lines = _lines(result)
        self.assertEqual(len(lines), 3)
        sources = [node["source_element_id"] for node in result.nodes]
        self.assertEqual(len(sources), len(set(sources)))
        node_ids = [node["_id"] for node in result.nodes]
        self.assertEqual(len(node_ids), len(set(node_ids)))

    def test_a_line_that_L0_did_deliver_is_not_synthesised_twice(
            self) -> None:
        """Переизвлечение может отдать линию элементом — узел всё равно один.

        Если бы синтез не смотрел на L0, тот же id пришёл бы дважды, и
        пересборка построила бы линию дважды.
        """

        document = _document()
        wall = make_element("OST_Walls", int(HOST_ID), ordinal=0)
        wall["element_id"] = HOST_ID
        wall["type_name"] = "НР_ВТ_(250х50)_Без нарезки_Теплый"
        line = make_element("OST_GenericModel", int(LINE_ID), ordinal=1)
        line["element_id"] = LINE_ID
        line["host_id"] = HOST_ID
        # Какой именно категорией переизвлечение отдаст линию, знает живой
        # Revit; тест держит ровно то, что от него зависит: id УЖЕ В L0 —
        # значит синтез обязан промолчать, иначе линия построится дважды.
        row = copy.deepcopy(project1_metadata())
        row["change_stamp"] = "curtain-grid-line-relift"
        row["elements"] = [wall, line]
        row["category_status"] = []
        document = L0Document.from_dict(row)
        result = lift_document_detailed(
            document,
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        sources = [node["source_element_id"] for node in result.nodes]
        self.assertEqual(sources.count(LINE_ID), 1)
        self.assertEqual(len(sources), len(set(sources)))

    def test_a_line_absent_from_L0_makes_no_node_and_says_why(self) -> None:
        """ПРЕД-СОСТОЯНИЕ: живой прогон v14 остановился ровно здесь.

        Первая редакция волны синтезировала узел линии из бокового индекса,
        не глядя на L0, и фолд отверг это законом переписи:
        ``FoldError('L0/L1 source mismatch: missing=0, invented=122')``
        (``sob62_fas_r23_v14/run.json``; извлечение при этом прошло целиком —
        5096 элементов, перепись сошлась). Закон прав: узел без источника в
        L0 — изобретённый элемент. Теперь операции нет, а причина названа.
        """

        result = lift_document_detailed(
            _document_without_the_line(),
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE)))
        self.assertEqual(_lines(result), [])
        sources = {node["source_element_id"] for node in result.nodes}
        self.assertNotIn(LINE_ID, sources)
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(len(skipped), 1)
        self.assertIn("нет среди прочитанных элементов", skipped[0].detail)

    def test_the_fold_law_itself_rejects_an_invented_source(self) -> None:
        """Тот самый закон, что спас прогон, — под тестом.

        Ослаблять его нельзя: он единственный отличает «прочитали и
        подняли» от «сочинили элемент, которого чтение не видело».
        """

        from kukai.ir.decompile.fold import FoldError, fold_l1

        document = _document_without_the_line()
        nodes = list(lift_document_detailed(
            document,
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE))).nodes)
        host = [n for n in nodes if n["source_element_id"] == HOST_ID][0]
        invented = {
            "kind": "op",
            "op_name": "create_curtain_grid_line",
            "_id": stable_l1_id("op", LINE_ID),
            "type_name": "",
            "params": {"host": {"ref": host["_id"]}, "direction": "u",
                       "position_mm": MID},
            "source_element_id": LINE_ID,
            "level_name": host.get("level_name"),
            "anchor_mm": MID,
        }
        with self.assertRaises(FoldError) as caught:
            fold_l1(nodes + [invented], document)
        self.assertIn("invented=1", str(caught.exception))

    def test_the_position_travels_with_the_delta_copy(self) -> None:
        """ПРЕД-СОСТОЯНИЕ: живой прогон №9 (v15) умер ровно здесь.

        ``position_mm`` не значился в общей координатной таблице
        (``fold._COORDINATE_FIELDS``), и Δ-перенос двигал СТЕНУ, но не точку
        её линии разрезки. Замер по артефактам прогона: стена в программе
        уехала на ``p0_mm=[637652.0, 15682.0]``, а позиция линии осталась
        ``[7717.8, 28822.4, 4925.0]`` — координаты ОРИГИНАЛА. Коммит
        откатился с посланной Revit ошибкой «Не удалось создать импост
        витража. Та часть схемы разрезки витража, на которой он был
        размещён, больше не существует».

        Тот же урок был получен 21.07 на «xyz» у place_family: мебель
        строилась по оригинальным координатам ВНУТРИ здания. Одно поле в
        общей таблице чинит обоих потребителей — перенос и канон.
        """

        from kukai.ir.decompile.materialize import leaves_to_program

        leaves = [n for n in lift_document_detailed(
            _document(), curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE))).nodes
            if n.get("kind") == "op"]
        delta = (300000.0, 0.0, 0.0)
        programs = leaves_to_program(leaves, offset_mm=delta).programs
        lines = [op for prog in programs for op in prog["ops"]
                 if op["op"] == "create_curtain_grid_line"]
        self.assertEqual(len(lines), 1)
        moved = lines[0]["position_mm"]
        self.assertAlmostEqual(moved[0], MID[0] + delta[0], delta=1.0)
        self.assertAlmostEqual(moved[1], MID[1], delta=1.0)
        self.assertAlmostEqual(moved[2], MID[2], delta=1.0)
        walls = [op for prog in programs for op in prog["ops"]
                 if op["op"] == "create_wall"]
        self.assertTrue(walls, "носитель обязан быть в программе")
        # Линия и её стена обязаны уехать НА ОДНУ И ТУ ЖЕ величину:
        # разъехаться им нельзя ни при каком сдвиге.
        plain = leaves_to_program(leaves).programs
        plain_wall = [op for prog in plain for op in prog["ops"]
                      if op["op"] == "create_wall"][0]
        self.assertAlmostEqual(
            moved[0] - MID[0],
            walls[0]["p0_mm"][0] - plain_wall["p0_mm"][0], delta=1.0)

    def test_the_canon_is_translation_invariant_for_the_line(self) -> None:
        """Иначе лист линии не совпал бы с оригиналом НИКОГДА.

        Сравнение идемпотентности сверяет канонические хеши оригинала и
        пересобранной копии, а копия стоит со сдвигом. Поле, которого нет в
        координатной таблице, канон не локализует — и хеши расходятся даже
        при идеально построенной линии.
        """

        from kukai.ir.decompile.component import _translate_leaf
        from kukai.ir.decompile.fold import FidelityCanon

        nodes = list(lift_document_detailed(
            _document(), curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE))).nodes)
        delta = (300000.0, 0.0, 0.0)
        # Копия строится СДВИНУТОЙ ЦЕЛИКОМ — и линия в ней стоит на
        # position+delta. Двигаем лист руками, а не общей таблицей: иначе
        # тест сравнивал бы таблицу с самой собой и не поймал бы ровно ту
        # дыру, из-за которой упал прогон №9.
        moved = []
        for node in nodes:
            shifted = _translate_leaf(node, delta)
            if shifted.get("op_name") == "create_curtain_grid_line":
                params = dict(shifted["params"])
                params["position_mm"] = [
                    node["params"]["position_mm"][i] + delta[i]
                    for i in range(3)]
                shifted = {**shifted, "params": params}
            moved.append(shifted)
        origin = (0.0, 0.0, 0.0)
        here = FidelityCanon.hash_sequence(nodes, origin)
        there = FidelityCanon.hash_sequence(moved, delta)
        index_of_line = [i for i, node in enumerate(nodes)
                         if node.get("op_name") == "create_curtain_grid_line"]
        self.assertEqual(len(index_of_line), 1)
        i = index_of_line[0]
        self.assertEqual(here[i], there[i])

    def test_a_host_that_did_not_lift_refuses_instead_of_dangling(
            self) -> None:
        """Ссылка на неподнятого носителя была бы висячей ссылкой L1."""

        result = lift_document_detailed(
            _document(),
            curtain_index=_index(
                u_lines=[_line_row()],
                grid_layout=_layout(vert=GRID_LAYOUT_NONE),
                host_id="404404"))
        self.assertEqual(_lines(result), [])
        skipped = [d for d in result.diagnostics
                   if d.source_element_id == LINE_ID]
        self.assertEqual(skipped[0].reason, AtomReason.MISSING_REFERENCE)


if __name__ == "__main__":
    unittest.main()
