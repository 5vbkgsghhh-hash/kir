"""ДВА ПРЕДИКАТА СМЕЖНОСТИ КОМНАТ НОСИЛИ ОДНО ИМЯ — опровергающие тесты.

`fold._semantic_fold` и `design_check._openings` оба называются «смежность
комнат». Замер 10.08 (прибор — сырой разбор `L0.jsonl`, корпус
`backend/backend/data/decompile`, машинно-локальный) говорит, что это ДВА
РАЗНЫХ ПРЕДИКАТА:

| здание | дверей | A рёбер | B рёбер | общих | ЖАККАР | только A | только B |
|---|---|---|---|---|---|---|---|
| `демо`                        | 5 941 | 1 035 | 3 272 | 963 | **0.288** | 72 | 2 309 |
| `13A-RD-AR-K2_v33`            | 2 096 |   975 | 1 438 | 950 | **0.649** | 25 |   488 |
| `Snowdon …Architectural`      |   143 |    22 |    23 |  11 | **0.324** | 11 |    12 |
| `SOB6.2…AR_R23`               |   153 |    40 |   117 |  35 | **0.287** |  5 |    82 |

Жаккар гуляет 0.287…0.649 и расходится в ОБЕ стороны — ни один предикат не
является огрублением другого.

ДВА ДЕФЕКТА, найденные по дороге, воспроизведены здесь ДОСЛОВНО:

**(1) `fold` молча выбрасывает всё, кроме «ровно две комнаты».** Распределение
числа комнат, ограниченных хозяином двери, `демо-v3`:
`{0: 2816, 1: 154, 2: 1036, 3: 966, 4: 648, 5: 50, 6: 76, 7: 25, 8: 55,
9: 113, 30: 1, 34: 1}`. Ребро получают 1 036 дверей из 5 941 — **17.4 %**;
4 905 выпадают без названной причины.

**(2) `design_check` усекает до двух ПО АЛФАВИТУ идентификатора комнаты.**
`near = sorted(touching(...))`, затем `from_room_id=near[0]`,
`to_room_id=near[1]`. Замер: **66 дверей** `демо-v3` и **34 двери**
`k2_ar_rd_v7` касаются трёх и более комнат. Довод не в числе, а в том, что
смежность здания зависит от СТРОКОВОГО ПОРЯДКА идентификаторов: перенумеруй
комнаты — и здание «изменится», не изменившись.
"""
from __future__ import annotations

import unittest

from kukai.ir.decompile.building_graph import (
    Modality,
    Relation,
    graph_from_l0,
)
from kukai.ir.decompile.graph_adjacency import (
    REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO,
    REFUSAL_NO_POSITION,
    opening_point_touches_room_edges,
)

_SQUARE = [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)]


def _shift(poly, dx, dy):
    return [(x + dx, y + dy) for x, y in poly]


def _element(element_id, category, **kw):
    row = {"element_id": element_id, "category": category, "type_id": "t",
           "type_name": "T", "level_id": None, "p0_mm": None, "p1_mm": None,
           "bbox_min_mm": None, "bbox_max_mm": None, "host_id": None,
           "params": {}}
    row.update(kw)
    return row


class PredicateAIsNamedAndDoesNotDropSilently(unittest.TestCase):
    """A = `bounded_by_same_wall`: факт об ОБЪЯВЛЕНИИ Revit, не о геометрии."""

    def _graph(self, room_ids):
        rooms = [{"id": rid, "level_id": "L1", "bounding_element_ids": ["W1"],
                  "boundary_mm": _SQUARE} for rid in room_ids]
        return graph_from_l0(
            {"doc_name": "t", "levels": [], "rooms": rooms, "grids": []},
            [_element("W1", "OST_Walls"),
             _element("D1", "OST_Doors", host_id="W1")]
            + [_element(rid, "OST_Rooms") for rid in room_ids])

    def test_exactly_two_rooms_gives_a_proven_room_to_room_edge(self) -> None:
        graph = self._graph(["R1", "R2"])
        edges = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN)
        self.assertEqual({edges[0].src, edges[0].dst}, {"R1", "R2"})

    def test_THREE_rooms_is_a_NAMED_refutation_not_silence(self) -> None:
        """ОПРОВЕРГАЮЩИЙ СЛУЧАЙ: `fold` здесь молчит. 966 дверей `демо-v3`
        попадают ровно сюда, и ещё 648 — в ветку «четыре»."""
        graph = self._graph(["R1", "R2", "R3"])
        edges = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertEqual(len(edges), 1, "ребро исчезло — молчаливое выпадение")
        self.assertIs(edges[0].modality, Modality.REFUTED)
        self.assertTrue(edges[0].refuted_by)
        self.assertEqual(edges[0].evidence["rooms_bounded_by_host"], 3)

    def test_ZERO_rooms_is_also_named(self) -> None:
        """2 816 дверей `демо-v3` — хозяин не ограничивает НИ ОДНОЙ комнаты."""
        graph = self._graph([])
        edges = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.REFUTED)
        self.assertEqual(edges[0].evidence["rooms_bounded_by_host"], 0)

    def test_refutation_counts_are_reportable(self) -> None:
        graph = self._graph(["R1", "R2", "R3"])
        self.assertEqual(sum(graph.refuted_by_counts().values()), 1)


class PredicateBDoesNotTruncateByAlphabet(unittest.TestCase):
    """B = `opening_point_touches_room`: факт об ИЗМЕРЕННОЙ геометрии."""

    def _fixture(self, n_rooms):
        """n комнат, чьи полигоны сходятся у точки двери (0,0)."""
        quads = [
            _SQUARE,                       # x,y >= 0
            _shift(_SQUARE, -1000.0, 0.0),  # x <= 0
            _shift(_SQUARE, -1000.0, -1000.0),
            _shift(_SQUARE, 0.0, -1000.0),
        ][:n_rooms]
        # Имена нарочно таковы, что алфавит НЕ совпадает с геометрией.
        names = ["Zкомната", "Aкомната", "Mкомната", "Bкомната"][:n_rooms]
        rooms = [{"id": rid, "level_id": "L1", "boundary_mm": q,
                  "bounding_element_ids": ["W1"]}
                 for rid, q in zip(names, quads)]
        header = {"doc_name": "t", "levels": [], "rooms": rooms, "grids": []}
        elements = {
            "D1": _element("D1", "OST_Doors", host_id="W1", level_id="L1",
                           p0_mm=[0.0, 0.0, 0.0]),
            "W1": _element("W1", "OST_Walls", level_id="L1"),
        }
        return header, elements, names

    def test_two_touched_rooms_give_one_proven_edge(self) -> None:
        header, elements, _ = self._fixture(2)
        edges, census = opening_point_touches_room_edges(header, elements)
        proven = [e for e in edges if e.modality is Modality.PROVEN]
        self.assertEqual(len(proven), 1)
        census.assert_balanced()

    def test_FOUR_touched_rooms_emit_ALL_pairs_never_an_alphabetical_two(self):
        """ОПРОВЕРГАЮЩИЙ СЛУЧАЙ, дословно: `design_check` вернул бы
        `from_room_id='Aкомната'`, `to_room_id='Bкомната'` — пару, выбранную
        СОРТИРОВКОЙ СТРОК, и потерял бы остальные. 66 дверей `демо-v3` и
        34 двери `k2_ar_rd_v7` попадают в эту ветку."""
        header, elements, names = self._fixture(4)
        edges, census = opening_point_touches_room_edges(header, elements)
        proven = [e for e in edges if e.modality is Modality.PROVEN]
        # C(4,2) = 6 пар, ни одна не выброшена.
        self.assertEqual(len(proven), 6)
        self.assertEqual(census.touch_degree, {4: 1})
        self.assertEqual(census.truncated_by_design_check, 1)
        # Проверка, что алфавитная пара не привилегирована.
        pairs = {frozenset((e.src, e.dst)) for e in proven}
        self.assertIn(frozenset({"Zкомната", "Aкомната"}), pairs)
        for edge in proven:
            self.assertEqual(edge.evidence["rooms_touched"], 4)

    def test_fewer_than_two_is_a_NAMED_refutation(self) -> None:
        header, elements, _ = self._fixture(1)
        edges, _census = opening_point_touches_room_edges(header, elements)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.REFUTED)
        self.assertEqual(edges[0].refuted_by,
                         REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO)

    def test_opening_without_position_is_a_NAMED_refusal(self) -> None:
        """1 305 дверей `демо-v3` (22.0 %) не имеют ни точки, ни рамки.
        В `design_check` они выпадают из смежности молча."""
        header, elements, _ = self._fixture(2)
        elements["D1"]["p0_mm"] = None
        edges, census = opening_point_touches_room_edges(header, elements)
        self.assertEqual(edges, ())
        self.assertEqual(census.refusals, {REFUSAL_NO_POSITION: 1})
        census.assert_balanced()

    def test_bbox_centre_provenance_is_recorded_not_hidden(self) -> None:
        header, elements, _ = self._fixture(2)
        elements["D1"]["p0_mm"] = None
        elements["D1"]["bbox_min_mm"] = [-10.0, -10.0, 0.0]
        elements["D1"]["bbox_max_mm"] = [10.0, 10.0, 0.0]
        edges, _ = opening_point_touches_room_edges(header, elements)
        self.assertTrue(edges)
        self.assertEqual(edges[0].evidence["position_from"], "bbox_centre")

    def test_census_balances_on_every_branch(self) -> None:
        header, elements, _ = self._fixture(2)
        elements["D2"] = _element("D2", "OST_Doors", level_id=None,
                                  p0_mm=[0.0, 0.0, 0.0])
        _edges, census = opening_point_touches_room_edges(header, elements)
        census.assert_balanced()
        self.assertEqual(census.openings_seen, 2)


class TheTwoPredicatesAreDifferentRelations(unittest.TestCase):
    """Одно слово на два предиката — дефект того же класса, что зелёный
    свидетель по непрочитанной оси."""

    def test_the_relations_do_not_share_a_name(self) -> None:
        self.assertNotEqual(Relation.BOUNDED_BY_SAME_WALL.value,
                            Relation.OPENING_POINT_TOUCHES_ROOM.value)

    def test_a_building_can_hold_both_and_they_may_disagree(self) -> None:
        """Замерено: только-A 72 и только-B 2 309 на `демо-v3`; только-A 11 и
        только-B 12 на `Snowdon Architectural`. Расхождение ДВУСТОРОННЕЕ."""
        rooms = [
            {"id": "R1", "level_id": "L1", "boundary_mm": _SQUARE,
             "bounding_element_ids": ["W1"]},
            {"id": "R2", "level_id": "L1",
             "boundary_mm": _shift(_SQUARE, -1000.0, 0.0),
             "bounding_element_ids": ["W1"]},
            # Третья комната ограничена тем же хозяином — A опровергается,
            # а B про неё ничего не знает: её полигон далеко от точки двери.
            {"id": "R3", "level_id": "L1",
             "boundary_mm": _shift(_SQUARE, 50000.0, 50000.0),
             "bounding_element_ids": ["W1"]},
        ]
        header = {"doc_name": "t", "levels": [], "rooms": rooms, "grids": []}
        rows = [_element("W1", "OST_Walls", level_id="L1"),
                _element("D1", "OST_Doors", host_id="W1", level_id="L1",
                         p0_mm=[0.0, 0.0, 0.0])]
        rows += [_element(r["id"], "OST_Rooms", level_id="L1") for r in rooms]
        graph = graph_from_l0(header, rows)
        a_edges = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertTrue(all(e.modality is Modality.REFUTED for e in a_edges))

        elements = {row["element_id"]: row for row in rows}
        b_edges, _ = opening_point_touches_room_edges(header, elements)
        b_proven = [e for e in b_edges if e.modality is Modality.PROVEN]
        self.assertEqual(len(b_proven), 1)
        self.assertEqual({b_proven[0].src, b_proven[0].dst}, {"R1", "R2"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
