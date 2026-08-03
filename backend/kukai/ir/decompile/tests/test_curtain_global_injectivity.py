"""Глобальная инъективность panel_id ↔ host_panel_id (кодекс №4,
2026-07-29, tasks/b8f3v4r97.output сессии eeccfb91).

``CurtainWallRecord.__post_init__`` уже требует panel_id уникальным ВНУТРИ
одного носителя (``_require_unique``). Но panel_id и host_panel_id живут в
ОБЩЕМ, глобальном пространстве идентичности документа — а глобальная
сторона инъективности не проверялась вовсе: ``_curtain_side_index``
строила ``cells``/``bodies`` last-write, без единой проверки на коллизию
между носителями или между ролями panel_id/host_panel_id.

Опасность НЕ в том, что last-write создаёт дубликат листа (двух опов не
будет — тело перехватывается ``curtain_cell_bodies`` РАНЬШЕ, чем элемент
доходит до своей собственной проверки ``curtain_cells``, см. ``_lift_one``).
Опасность в ПОТЕРЕ: если body-id совпадает с НАСТОЯЩИМ panel_id чужой
ячейки, тот самый более ранний охранник тела перехватывает чужую легитимную
ячейку и навсегда прячет её собственную идентичность — она получает
generator_child, каким бы её реальный статус ни был.

Четыре адверсариальных формы (дословно кодекс): duplicate body, body =
чужой panel_id, self-alias, вложенный curtain-host. Все четыре обязаны
ИЗОЛИРОВАТЬ затронутые носители — их элементы падают в честный (не
curtain-специфичный) путь, а не портят граф молча.
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kukai.ir.decompile.curtain_extract import CURTAIN_INDEX_SCHEMA_VERSION
from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.lift import _curtain_side_index, lift_document_detailed
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)

GLAZING_TYPE_ID = "7001"
WALL_BODY_TYPE_ID = "7002"


def _panel_row(panel_id: str, *, host_panel_id: str | None = None,
               u_index: int = 0, v_index: int = 0) -> dict[str, Any]:
    return {
        "panel_id": panel_id,
        "is_family_instance": True,
        "family_name": "Системная панель",
        "type_name": "Стеклопакет 30мм",
        "type_id": GLAZING_TYPE_ID,
        "host_panel_id": host_panel_id,
        "host_panel_type_id": WALL_BODY_TYPE_ID if host_panel_id else None,
        "host_panel_type_name": (
            "НР_ВТ_Сэндвич панель_30мм" if host_panel_id else None),
        "u_index": u_index,
        "v_index": v_index,
        "address_state": "ok",
        "is_door": False,
    }


def _host_row(panels: list[dict[str, Any]], *,
              default_panel_type_id: str = "9999") -> dict[str, Any]:
    return {
        "curtain_available": True,
        "host_kind": "wall",
        "default_panel_type_id": default_panel_type_id,
        "default_panel_type_name": "Системная панель по умолчанию",
        "default_panel_state": "ok",
        "default_panel_source": "AUTO_PANEL_WALL",
        "u_grid_lines": [],
        "v_grid_lines": [],
        "panels": panels,
        "mullions": [],
    }


def _envelope(hosts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": CURTAIN_INDEX_SCHEMA_VERSION,
        "curtain_index": hosts,
        "failures": [],
    }


class DirectInjectivityChecks(unittest.TestCase):
    """Прямая проверка ``_curtain_side_index`` — быстрее и точнее, чем
    полный ``lift_document_detailed``, годится для перебора форм."""

    def test_clean_two_hosts_no_conflict(self) -> None:
        """Отрицательный контроль: два носителя, разные panel_id/
        host_panel_id — ничего не изолируется."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="B1")]),
            "H2": _host_row([_panel_row("P2", host_panel_id="B2")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertIn("P1", cells)
        self.assertIn("P2", cells)
        self.assertEqual(bodies.get("B1"), "P1")
        self.assertEqual(bodies.get("B2"), "P2")

    def test_duplicate_body_two_cells_claim_the_same_occupant(self) -> None:
        """Два РАЗНЫХ носителя, две ячейки заявляют ОДНОГО занявшего B1 —
        оба носителя изолируются целиком, ни одна из двух ячеек не
        участвует в cells/bodies по short-path."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="B1")]),
            "H2": _host_row([_panel_row("P2", host_panel_id="B1")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("P2", cells)
        self.assertNotIn("B1", bodies)

    def test_body_equals_a_foreign_real_panel_id(self) -> None:
        """H1's ячейка P1 занята B, но B — это НАСТОЯЩИЙ panel_id ячейки P2
        чужого носителя H2. Обе стороны изолируются: без этого ранний
        body-guard в _lift_one спрятал бы легитимную P2."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="P2")]),
            "H2": _host_row([_panel_row("P2")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("P2", cells, "чужая легитимная ячейка не должна пострадать МОЛЧА")
        self.assertNotIn("P2", bodies)

    def test_self_alias(self) -> None:
        """Ячейка P1, занятая «сама собой» (host_panel_id == panel_id) —
        физического смысла нет, носитель изолируется."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="P1")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("P1", bodies)

    def test_nested_curtain_host_as_body(self) -> None:
        """Занявший ячейки P1 носителя H1 — это САМ носитель H2 (его
        wall_id). Неопределённая территория — H1 изолируется, H2 как
        самостоятельный носитель не тронут."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="H2")]),
            "H2": _host_row([_panel_row("P2")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("H2", bodies)
        # H2 сам по себе остаётся ЧИСТЫМ носителем — его собственная
        # ячейка P2 не пострадала, изоляция не расползается за пределы
        # РЕАЛЬНО задействованных носителей.
        self.assertIn("P2", cells)

    def test_conflict_does_not_bleed_into_unrelated_hosts(self) -> None:
        """Третий, полностью посторонний носитель не изолируется от чужого
        конфликта — блокировка не глобальная паника, а точечная."""
        env = _envelope({
            "H1": _host_row([_panel_row("P1", host_panel_id="B1")]),
            "H2": _host_row([_panel_row("P2", host_panel_id="B1")]),
            "H3": _host_row([_panel_row("P3", host_panel_id="B3")]),
        })
        cells, bodies, _, _ = _curtain_side_index(env)
        self.assertNotIn("P1", cells)
        self.assertNotIn("P2", cells)
        self.assertIn("P3", cells)
        self.assertEqual(bodies.get("B3"), "P3")


def _wall(element_id: str, ordinal: int) -> dict[str, Any]:
    wall = make_element("OST_Walls", int(element_id), ordinal=ordinal)
    wall["element_id"] = element_id
    wall["type_name"] = "Витраж НР_ВТ"
    return wall


def _cell(element_id: str, host_id: str, ordinal: int) -> dict[str, Any]:
    cell = make_element("OST_CurtainWallPanels", int(element_id), ordinal=ordinal)
    cell["element_id"] = element_id
    cell["host_id"] = host_id
    cell["geom_kind"] = "bbox_only"
    cell["p0_mm"] = cell["p1_mm"] = None
    cell["bbox_min_mm"] = cell["bbox_max_mm"] = None
    cell["type_id"] = GLAZING_TYPE_ID
    cell["type_name"] = "Стеклопакет 30мм"
    return cell


def _body(element_id: str, ordinal: int) -> dict[str, Any]:
    body = make_element("OST_CurtainWallPanels", int(element_id), ordinal=ordinal)
    body["element_id"] = element_id
    body["host_id"] = None
    body["geom_kind"] = "curve"
    body["p0_mm"] = [0.0, 0.0, 0.0]
    body["p1_mm"] = [1500.0, 0.0, 0.0]
    body["type_id"] = WALL_BODY_TYPE_ID
    body["type_name"] = "НР_ВТ_Сэндвич панель_30мм"
    return body


def _lift(elements: list[dict[str, Any]], curtain_index: dict[str, Any]):
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "curtain-injectivity-v1"
    row["elements"] = elements
    row["category_status"] = []
    document = L0Document.from_dict(row)
    result = lift_document_detailed(document, curtain_index=curtain_index)
    return {node["source_element_id"]: node for node in result.nodes}


class EndToEndMultisetIsPreserved(unittest.TestCase):
    """Полный ``lift_document_detailed``: доказывает не только форму
    cells/bodies, но и РЕАЛЬНЫЙ исход — ровно один лист на элемент, ни
    одного потерянного, ни одной чужой ячейки, съеденной телом."""

    H1, P1, H2, P2, B1 = "9101", "9102", "9111", "9112", "9103"

    def test_duplicate_body_end_to_end_no_loss_no_double(self) -> None:
        """P1 (H1) и P2 (H2) оба заявляют B1 занявшим. Все три элемента
        обязаны получить РОВНО по одному листу — изоляция не роняет их
        из мультимножества, просто снимает short-path."""
        elements = [
            _wall(self.H1, 0), _cell(self.P1, self.H1, 1),
            _wall(self.H2, 2), _cell(self.P2, self.H2, 3),
            _body(self.B1, 4),
        ]
        curtain_index = _envelope({
            self.H1: _host_row([_panel_row(self.P1, host_panel_id=self.B1)]),
            self.H2: _host_row([_panel_row(self.P2, host_panel_id=self.B1)]),
        })
        nodes = _lift(elements, curtain_index)
        source_ids = list(nodes.keys())
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(
            set(source_ids), {self.H1, self.P1, self.H2, self.P2, self.B1})
        # B1 сам заявлен ДВУМЯ разными ячейками — ни одной из них нельзя
        # верить, поэтому B1 не должен быть тихо назначен generator_child
        # НИКАКОЙ из них: оба носителя изолированы, B1 идёт по общему пути
        # размещения как самостоятельный элемент.
        b1 = nodes[self.B1]
        self.assertFalse(
            b1["kind"] == "atom"
            and b1.get("reason", {}).get("code")
            == AtomReason.GENERATOR_CHILD.value,
            f"B1 must not be silently assigned as generator_child of "
            f"either conflicting claimant: {b1}")

    def test_body_equals_foreign_panel_keeps_the_foreign_cell_alive(
            self) -> None:
        """P2 (H2) — легитимная, адресованная ячейка. P1 (H1) объявляет её
        ID своим host_panel_id. БЕЗ фикса P2 стала бы недостижимой (ранний
        body-guard перехватил бы её как тело чужой ячейки P1). С фиксом —
        P2 остаётся РЕАЛЬНОЙ ячейкой (или честным атомом по своим
        причинам), но НЕ generator_child по чужой ссылке."""
        elements = [
            _wall(self.H1, 0), _cell(self.P1, self.H1, 1),
            _wall(self.H2, 2), _cell(self.P2, self.H2, 3),
        ]
        curtain_index = _envelope({
            self.H1: _host_row([_panel_row(self.P1, host_panel_id=self.P2)]),
            self.H2: _host_row([_panel_row(self.P2)]),
        })
        nodes = _lift(elements, curtain_index)
        source_ids = list(nodes.keys())
        self.assertEqual(len(source_ids), len(set(source_ids)))
        self.assertEqual(set(source_ids), {self.H1, self.P1, self.H2, self.P2})
        p2 = nodes[self.P2]
        self.assertFalse(
            p2["kind"] == "atom"
            and p2.get("reason", {}).get("code")
            == AtomReason.GENERATOR_CHILD.value,
            f"P2 must not be silently suppressed as somebody else's body: {p2}")


if __name__ == "__main__":
    unittest.main()
