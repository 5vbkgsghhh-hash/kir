"""ГРАНИЦА ИЗВЛЕЧЕНИЯ — ОДНО ПОНЯТИЕ, НО НЕ ОДИН КЛАСС.

Соблазн был назвать всё «цель вне извлечения» одним словом. ЗАМЕР 10.08.2026
(сырой разбор `L0.jsonl`, корпус `backend/backend/data/decompile`,
машинно-локальный) этого НЕ ПОДТВЕРДИЛ: висячий `host_id` и висячий
`bounds_room` суть РАЗНЫЕ популяции, и расходятся они на три порядка.

    `snowdon_elec_v1`   host 959 рёбер -> ВСЕГО 3 различных цели,
                        и все три суть записи `link` того же потока
    `snowdon_plumb_v5`  host  86 рёбер ->   4 цели; bounds_room 0
    `демо-v3`           host   0;  bounds_room 4 352 ребра -> 2 146 целей,
                        медиана 2 ребра на цель, записей `link` в потоке 0
    `sob62_r23_v5`      host   1;  bounds_room 340 -> 184 цели

Пересечение множеств целей: 0 на трёх зданиях, 1 на `sob62_r23_v5` — и та
единица есть запись `link`, несущая заодно 88 рёбер границы помещения.

Классы, которые обязаны остаться раздельными (числа команды клешей по всему
корпусу: 1 263 висячих ребра, из них 1 010 в связанный файл и 86 в
`ReferencePlane`, отнесённый `clash/hulls.KIND_TABLE` к `not_a_body`):

  * хозяин в СВЯЗАННОМ ФАЙЛЕ — дочитывается, если открыть связь;
  * хозяин НЕ МОЖЕТ ИМЕТЬ ТЕЛА ПО ПРИРОДЕ — дочитывать нечего никогда;
  * граница помещения вне извлечения — третий, самый массовый.

Разница ровно в том, ЧТО С НИМИ ДЕЛАТЬ, поэтому слить их обратно нельзя.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.building_graph import (
    Modality,
    OutsideExtraction,
    Relation,
    graph_from_l0,
)

_HEADER = {"doc_name": "t", "levels": [], "rooms": [], "grids": []}


def _el(element_id, category, **kw):
    row = {"element_id": element_id, "category": category, "type_id": "t",
           "type_name": "T", "level_id": None, "host_id": None, "params": {}}
    row.update(kw)
    return row


def _rooms(*pairs):
    return {"doc_name": "t", "levels": [], "grids": [],
            "rooms": [{"id": rid, "bounding_element_ids": list(bounds)}
                      for rid, bounds in pairs]}


class LinkIsAPositiveFactNotBlindness(unittest.TestCase):
    """959 рёбер `snowdon_elec_v1` называли НАШУ слепоту. L0 знал ответ."""

    def test_host_that_is_a_link_resolves_and_is_proven(self) -> None:
        graph = graph_from_l0(
            _HEADER,
            [_el("F1", "OST_ElectricalFixtures", host_id="LNK-1")],
            link_ids=["LNK-1"])
        edges = graph.relation_edges(Relation.HOSTED_IN_LINK)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN,
                      "связь названа неразрешённой целью — это наша слепота")
        self.assertEqual(edges[0].evidence["why"],
                         OutsideExtraction.RESOLVED_TO_LINK.value)
        self.assertEqual(graph.unresolved_targets(), ())

    def test_without_the_link_list_the_same_edge_stays_unresolved(self) -> None:
        """Отсутствие входа обязано читаться как «не спрашивали», а не как
        «связи нет»: разница в том, дочитывать ли."""
        graph = graph_from_l0(
            _HEADER, [_el("F1", "OST_ElectricalFixtures", host_id="LNK-1")])
        self.assertEqual(len(graph.unresolved_targets()), 1)
        self.assertEqual(graph.unresolved_targets()[0].evidence["why"],
                         OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value)


class BodilessHostIsItsOwnClass(unittest.TestCase):
    """86 из 1 263 висячих — `ReferencePlane`, телом не станет НИКОГДА."""

    def test_caller_supplied_bodiless_target_is_named_apart(self) -> None:
        graph = graph_from_l0(
            _HEADER, [_el("W1", "OST_Windows", host_id="RP-9")],
            bodiless_target_ids=["RP-9"])
        edge = graph.unresolved_targets()[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value)

    def test_the_graph_NEVER_guesses_this_class_from_L0(self) -> None:
        """Адреса такой цели в потоке нет вовсе, поэтому категорию сказать
        нечем. Класс приходит от вызывающего с таблицей родов — иначе это
        была бы догадка по категории, от которой весь модуль и уходит."""
        graph = graph_from_l0(
            _HEADER, [_el("W1", "OST_Windows", host_id="RP-9")])
        self.assertEqual(graph.unresolved_targets()[0].evidence["why"],
                         OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value)


class RoomBoundaryIsAThirdClass(unittest.TestCase):
    """4 352 ребра `демо-v3` против 0 висячих хозяев на том же здании."""

    def test_boundary_outside_extraction_has_its_own_name(self) -> None:
        graph = graph_from_l0(_rooms(("R1", ["W-MISSING"])),
                              [_el("R1", "OST_Rooms")])
        edges = graph.relation_edges(Relation.BOUNDS_ROOM)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.UNRESOLVED_TARGET)
        self.assertEqual(
            edges[0].evidence["why"],
            OutsideExtraction.BOUNDARY_ELEMENT_NOT_EXTRACTED.value)

    def test_a_link_bounding_a_room_is_named_as_a_link(self) -> None:
        """`sob62_r23_v5`: одна запись `link` несёт 88 рёбер границы."""
        graph = graph_from_l0(_rooms(("R1", ["LNK-1"])),
                              [_el("R1", "OST_Rooms")], link_ids=["LNK-1"])
        edge = graph.relation_edges(Relation.BOUNDS_ROOM)[0]
        self.assertEqual(edge.evidence["why"],
                         OutsideExtraction.RESOLVED_TO_LINK.value)

    def test_the_three_classes_do_not_share_a_name(self) -> None:
        values = {OutsideExtraction.RESOLVED_TO_LINK.value,
                  OutsideExtraction.HOST_CANNOT_HAVE_A_BODY.value,
                  OutsideExtraction.BOUNDARY_ELEMENT_NOT_EXTRACTED.value,
                  OutsideExtraction.TARGET_NOT_IN_SNAPSHOT.value}
        self.assertEqual(len(values), 4)


class EveryUnresolvedEdgeNamesItsReason(unittest.TestCase):
    """«Цель вне извлечения» без под-причины — снова одно слово на разные факты."""

    def test_no_unresolved_edge_is_left_without_a_why(self) -> None:
        graph = graph_from_l0(
            _rooms(("R1", ["W-MISSING"])),
            [_el("R1", "OST_Rooms"),
             _el("F1", "OST_ElectricalFixtures", host_id="X-1"),
             _el("F2", "OST_Windows", level_id="L-MISSING")])
        unresolved = graph.unresolved_targets()
        self.assertTrue(unresolved)
        for edge in unresolved:
            self.assertIn("why", edge.evidence, f"{edge.relation} без причины")
            self.assertIn(edge.evidence["why"],
                          {e.value for e in OutsideExtraction})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
