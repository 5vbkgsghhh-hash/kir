"""КЛАСС ХОЗЯИНА — ИЗМЕРЕННЫЙ ФАКТ, А НЕ СВОЙСТВО КАТЕГОРИИ.

План был положить «имеет ли категория физическую протяжённость» колонкой на
`CategorySpec` рядом с `discipline`. ЗАМЕР 11.08.2026 (сырой разбор корпуса
`backend/backend/data/decompile`, машинно-локальный) его отменяет по двум
независимым причинам.

**(1) `ReferencePlane` — не категория, а КЛАСС Revit.** В таблице экстрактора
77 строк, и ни `OST_CLines`, ни `OST_ReferencePlanes` среди них нет: опорные
плоскости не извлекаются вовсе (1 037 штук в цензе `snowdon_plumb_v5` против
0 в потоке). Колонка на `CategorySpec` не имела бы строки, в которую её писать.

**(2) У ВИСЯЧЕГО хозяина категория неизвестна в принципе** — строки с этим
адресом в снимке нет. Таблица, ключ которой категория, отвечает на вопрос,
который про висячую цель задать нечем.

**А ответ уже лежит на диске, поэлементно:** `host_class` в
`family_placement.index.json`, снятый чтением. Замер:

    `snowdon_plumb_v5`  Wall 2 647, Ceiling 100, **ReferencePlane 86**,
                        Level 25, FamilyInstance 2 — ровно те 86 висячих
    `sob62_r23_v5`      Wall 185, FamilyInstance 3, **RevitLinkInstance 1**
                        — ровно тот единственный висячий
    `демо-v3`           Wall 5 941
    `snowdon_elec_v1`   индекс есть, записей 20, с хозяином 0 — его 959
                        хозяев не экземпляры семейств, и это ЧЕСТНОЕ «индекс
                        молчит», а не «хозяина нет»

Прецедент `fold._discipline` при этом СОБЛЮДЁН: он запрещает ВТОРОЙ словарь об
одном понятии, а здесь второго не заводится — читается уже записанное.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.building_graph import (
    Modality,
    OutsideExtraction,
    graph_from_l0,
)

_HEADER = {"doc_name": "t", "levels": [], "rooms": [], "grids": []}


def _el(element_id, category, **kw):
    row = {"element_id": element_id, "category": category, "type_id": "t",
           "type_name": "T", "level_id": None, "host_id": None, "params": {}}
    row.update(kw)
    return row


class MeasuredHostClassDecides(unittest.TestCase):
    """Причина берётся из прочитанного класса, а не из списка от вызывающего."""

    def test_reference_plane_is_named_from_the_index(self) -> None:
        graph = graph_from_l0(
            _HEADER, [_el("W1", "OST_Windows", host_id="RP-9")],
            host_classes={"W1": "ReferencePlane"})
        edge = graph.unresolved_targets()[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value)
        self.assertEqual(edge.evidence["host_class"], "ReferencePlane")

    def test_link_class_is_named_from_the_index(self) -> None:
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="LNK-1")],
            host_classes={"F1": "RevitLinkInstance"})
        self.assertEqual(graph.unresolved_targets()[0].evidence["why"],
                         OutsideExtraction.RESOLVED_TO_LINK.value)

    def test_silent_index_stays_honestly_unknown(self) -> None:
        """`snowdon_elec_v1`: индекс есть, но про эти элементы молчит.
        Молчание индекса не есть факт о хозяине."""
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="X-1")],
            host_classes={"OTHER": "Wall"})
        edge = graph.unresolved_targets()[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value)
        self.assertIsNone(edge.evidence["host_class"])

    def test_measured_class_beats_the_caller_supplied_list(self) -> None:
        """Список остаётся запасным ходом, но ИЗМЕРЕННОЕ старше догадки."""
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="LNK-1")],
            host_classes={"F1": "RevitLinkInstance"},
            bodiless_target_ids=["LNK-1"])
        self.assertEqual(graph.unresolved_targets()[0].evidence["why"],
                         OutsideExtraction.RESOLVED_TO_LINK.value)

    def test_no_index_at_all_changes_nothing(self) -> None:
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="X-1")])
        self.assertIs(graph.unresolved_targets()[0].modality,
                      Modality.UNRESOLVED_TARGET)


class TheCategoryTableCannotAnswerThis(unittest.TestCase):
    """Опровергающий тест плана: строки для опорных плоскостей ПРОСТО НЕТ."""

    def test_reference_planes_are_absent_from_the_extraction_table(self) -> None:
        from kukai.ir.decompile.extract import _CATEGORY_SPECS
        names = {spec.name for spec in _CATEGORY_SPECS}
        self.assertNotIn("OST_CLines", names)
        self.assertNotIn("OST_ReferencePlanes", names)
        self.assertEqual(len(names), 77)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
