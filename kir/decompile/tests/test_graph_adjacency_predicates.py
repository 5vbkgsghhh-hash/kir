"""TWO ROOM-ADJACENCY PREDICATES CARRIED ONE NAME — refuting tests.

`fold._semantic_fold` and `design_check._openings` are both called
"room adjacency." Measurement 08-10 (instrument — a raw decompile of
`L0.jsonl`, corpus `backend/backend/data/decompile`, machine-local)
shows these are TWO DIFFERENT PREDICATES:

| building | doors | A edges | B edges | shared | JACCARD | A only | B only |
|---|---|---|---|---|---|---|---|
| `демо`                        | 5,941 | 1,035 | 3,272 | 963 | **0.288** | 72 | 2,309 |
| `13A-RD-AR-K2_v33`            | 2,096 |   975 | 1,438 | 950 | **0.649** | 25 |   488 |
| `Snowdon …Architectural`      |   143 |    22 |    23 |  11 | **0.324** | 11 |    12 |
| `SOB6.2…AR_R23`               |   153 |    40 |   117 |  35 | **0.287** |  5 |    82 |

Jaccard ranges 0.287…0.649 and diverges in BOTH directions — neither
predicate is a coarsening of the other.

TWO DEFECTS, found along the way, are reproduced here VERBATIM:

**(1) `fold` silently discards everything except "exactly two rooms."**
The distribution of the number of rooms bounded by a door's host,
`демо-v3`: `{0: 2816, 1: 154, 2: 1036, 3: 966, 4: 648, 5: 50, 6: 76,
7: 25, 8: 55, 9: 113, 30: 1, 34: 1}`. 1,036 of 5,941 doors get an edge
— **17.4%**; 4,905 fall out with no named reason.

**(2) `design_check` truncates to two rooms BY ALPHABETICAL ORDER of the
room identifier.** `near = sorted(touching(...))`, then
`from_room_id=near[0]`, `to_room_id=near[1]`. Measured: **66 doors** of
`демо-v3` and **34 doors** of `k2_ar_rd_v7` touch three or more rooms.
The point is not the count, but that a building's adjacency depends on
the STRING ORDER of identifiers: renumber the rooms — and the building
"changes" without having changed.
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import (
    GraphBuildError,
    Modality,
    Relation,
    graph_from_l0,
)
from kir.decompile.graph_adjacency import (
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
    """A = `bounded_by_same_wall`: a fact about Revit's DECLARATION, not about geometry."""

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
        """A REFUTING CASE: `fold` is silent here. 966 doors of
        `демо-v3` fall exactly here, and another 648 into the "four" branch."""
        graph = self._graph(["R1", "R2", "R3"])
        edges = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertEqual(len(edges), 1, "ребро исчезло — молчаливое выпадение")
        self.assertIs(edges[0].modality, Modality.REFUTED)
        self.assertTrue(edges[0].refuted_by)
        self.assertEqual(edges[0].evidence["rooms_bounded_by_host"], 3)

    def test_ZERO_rooms_is_also_named(self) -> None:
        """2,816 doors of `демо-v3` — the host bounds NOT A SINGLE room."""
        graph = self._graph([])
        edges = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.REFUTED)
        self.assertEqual(edges[0].evidence["rooms_bounded_by_host"], 0)

    def test_refutation_counts_are_reportable(self) -> None:
        graph = self._graph(["R1", "R2", "R3"])
        self.assertEqual(sum(graph.refuted_by_counts().values()), 1)


class PredicateBDoesNotTruncateByAlphabet(unittest.TestCase):
    """B = `opening_point_touches_room`: a fact about MEASURED geometry."""

    def _fixture(self, n_rooms):
        """n rooms whose polygons converge at the door's point (0,0)."""
        quads = [
            _SQUARE,                       # x,y >= 0
            _shift(_SQUARE, -1000.0, 0.0),  # x <= 0
            _shift(_SQUARE, -1000.0, -1000.0),
            _shift(_SQUARE, 0.0, -1000.0),
        ][:n_rooms]
        # The names are deliberately such that alphabetical order does NOT match geometry.
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
        """A REFUTING CASE, verbatim: `design_check` would return
        `from_room_id='Aкомната'`, `to_room_id='Bкомната'` — a pair
        chosen by STRING SORTING, discarding the rest. 66 doors of
        `демо-v3` and 34 doors of `k2_ar_rd_v7` fall into this branch."""
        header, elements, names = self._fixture(4)
        edges, census = opening_point_touches_room_edges(header, elements)
        proven = [e for e in edges if e.modality is Modality.PROVEN]
        # C(4,2) = 6 pairs, none discarded.
        self.assertEqual(len(proven), 6)
        self.assertEqual(census.touch_degree, {4: 1})
        self.assertEqual(census.truncated_by_design_check, 1)
        # A check that the alphabetical pair is not privileged.
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
        """1,305 doors of `демо-v3` (22.0%) have neither a point nor a
        bounding box. In `design_check` they silently drop out of adjacency."""
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


class PredicateBFitsInsideTheCoreGraph(unittest.TestCase):
    """🔴 PREDICATE B WAS BUILT OUTSIDE AND DID NOT FIT INTO THE CORE.

    The kind `OPENING_POINT_TOUCHES_ROOM` is declared in the core's
    `Relation`, is built by a separate module, and was NEVER produced
    by the core — before 2026-08-22 nothing called it except its own
    test. That is why it went unnoticed that its output does NOT FIT
    the core, for two laws at once:

     1. the kind is declared SYMMETRIC, meaning `GraphEdge.key` is a
        triple `(relation, min, max)`, which carries no opening. Two
        doors between the same two rooms gave two edges with ONE key,
        and `BuildingGraph` rejects that outright: "duplicate
        relation/src/dst edge truth is forbidden." The same failure on
        08-22 laid down end-join edges on MNVNK;
     2. the room is taken from the HEADER, while the nodes come from
        the STREAM, and on a truncated read these are different sets.
    """

    def _two_doors_between_two_rooms(self):
        rooms = [
            {"id": "R1", "level_id": "L1", "boundary_mm": _SQUARE,
             "bounding_element_ids": ["W1"]},
            {"id": "R2", "level_id": "L1",
             "boundary_mm": _shift(_SQUARE, -1000.0, 0.0),
             "bounding_element_ids": ["W1"]},
        ]
        header = {"doc_name": "t", "levels": [], "rooms": rooms, "grids": []}
        rows = [_element("W1", "OST_Walls", level_id="L1"),
                _element("D1", "OST_Doors", host_id="W1", level_id="L1",
                         p0_mm=[0.0, 0.0, 0.0]),
                _element("D2", "OST_Doors", host_id="W1", level_id="L1",
                         p0_mm=[0.0, 500.0, 0.0]),
                _element("R1", "OST_Rooms", level_id="L1"),
                _element("R2", "OST_Rooms", level_id="L1")]
        return header, rows

    def test_two_openings_on_one_pair_give_ONE_edge_and_keep_both(self) -> None:
        header, rows = self._two_doors_between_two_rooms()
        edges, _census = opening_point_touches_room_edges(
            header, {row["element_id"]: row for row in rows})
        proven = [e for e in edges if e.modality is Modality.PROVEN]
        self.assertEqual(len(proven), 1, "пара комнат обязана дать ОДНО ребро")
        self.assertEqual(list(proven[0].evidence["openings"]), ["D1", "D2"])
        self.assertEqual(proven[0].evidence["opening_count"], 2)

    def test_the_same_edges_now_assemble_into_a_BuildingGraph(self) -> None:
        """A REFUTING CASE: before the fix, the core failed here entirely."""
        header, rows = self._two_doors_between_two_rooms()
        graph = graph_from_l0(header, rows, room_adjacency=True)
        self.assertEqual(
            graph.relation_count(Relation.OPENING_POINT_TOUCHES_ROOM), 1)
        self.assertNotIn("room_adjacency", graph.census.sources_absent)

    def test_a_touched_room_outside_the_stream_is_named_not_fatal(self) -> None:
        header, rows = self._two_doors_between_two_rooms()
        rows = [row for row in rows if row["element_id"] != "R2"]
        graph = graph_from_l0(header, rows, room_adjacency=True)
        edges = graph.relation_edges(Relation.OPENING_POINT_TOUCHES_ROOM)
        unresolved = [e for e in edges
                      if e.modality is Modality.UNRESOLVED_TARGET]
        self.assertTrue(unresolved, "внешняя комната исчезла молча")
        self.assertEqual({e.dst for e in unresolved}, {"R2"})
        self.assertEqual({e.src for e in unresolved}, {"D1", "D2"})

    def test_without_the_flag_the_zero_is_NOT_a_fact_about_the_building(self):
        """A CONTROL IN THE OPPOSITE DIRECTION: it was not counted —
        and it is said that it was not counted."""
        header, rows = self._two_doors_between_two_rooms()
        graph = graph_from_l0(header, rows)
        self.assertIn("room_adjacency", graph.census.sources_absent)
        self.assertIn(Relation.OPENING_POINT_TOUCHES_ROOM,
                      graph.unmeasured_relations())
        with self.assertRaises(GraphBuildError):
            graph.relation_count(Relation.OPENING_POINT_TOUCHES_ROOM)


class TheTwoPredicatesAreDifferentRelations(unittest.TestCase):
    """One word for two predicates is a defect of the same class as a
    green witness over an unread grid."""

    def test_the_relations_do_not_share_a_name(self) -> None:
        self.assertNotEqual(Relation.BOUNDED_BY_SAME_WALL.value,
                            Relation.OPENING_POINT_TOUCHES_ROOM.value)

    def test_a_building_can_hold_both_and_they_may_disagree(self) -> None:
        """Measured: A-only 72 and B-only 2,309 on `демо-v3`; A-only
        11 and B-only 12 on `Snowdon Architectural`. The discrepancy
        runs in BOTH DIRECTIONS."""
        rooms = [
            {"id": "R1", "level_id": "L1", "boundary_mm": _SQUARE,
             "bounding_element_ids": ["W1"]},
            {"id": "R2", "level_id": "L1",
             "boundary_mm": _shift(_SQUARE, -1000.0, 0.0),
             "bounding_element_ids": ["W1"]},
            # A third room is bounded by the same host — A is refuted,
            # while B knows nothing about it: its polygon is far from
            # the door's point.
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
