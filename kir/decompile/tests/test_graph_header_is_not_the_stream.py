"""THE L0 HEADER AND THE ELEMENT STREAM ARE DIFFERENT SETS. Refuting tests.

🔴 THE PREMISE THIS FILE REMOVES. `building_graph` built three kinds of edges
from the HEADER (`header.levels`, `header.rooms`) and silently assumed that
every address named there is a node. The header carries a SUMMARY OF THE
DOCUMENT, the stream carries what actually got read; on a truncated or
partial read they diverge.

MEASUREMENT of 22.08.2026 — GRAPH RUN OVER THE WHOLE CORPUS (88
`backend/data/decompile` directories, 76 with `L0.jsonl`, machine-local):

    FIVE decompiles did not assemble into a graph AT ALL, all with one
    refusal — `ordinary graph edges require two assembled local nodes`:

    `k2_ar_rd_v1`         18 492 elements · header rooms 2 442, in stream 0
    `k2_ar_rd_v2`         same            · levels 59, in stream 0
    `k2_ar_rd_v3`         same
    `k2_ar_rd_v4`         18 489 elements · same
    `k4_geom_wave_15aug`     993 elements · rooms 1 150, in stream 0
    control `k2_ar_rd_v5` 55 293 elements · outside stream 0 — the graph DID
                          ASSEMBLE

Breakdown of the failure on `k2_ar_rd_v1` (by builder):

    `bounds_room`            14 334 edges with an EXTERNAL room + 2 962 with
                             two external ends
    `bounded_by_same_wall`      210 edges between two external rooms
    `level_above`                58 edges between two external levels

THE COST WAS THE WORST POSSIBLE: not "an edge with a named boundary" but the
FAILURE OF THE WHOLE GRAPH — our reading blindness, turned into the
impossibility of building the building's state. And it stood exactly in the
way of enabling `KUKAI_IR_BUILDING_GRAPH`: the census converged on 71 of 71
decompiles that construction reached, while the other five it did not reach
for a different reason, and without this file the flag would have been
enabled without noticing the difference.
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import (
    Modality,
    OutsideExtraction,
    Relation,
    graph_from_l0,
)

_SQUARE = [(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)]


def _element(element_id, category, **kw):
    row = {"element_id": element_id, "category": category, "type_id": "t",
           "type_name": "T", "level_id": None, "p0_mm": None, "p1_mm": None,
           "bbox_min_mm": None, "bbox_max_mm": None, "host_id": None,
           "params": {}}
    row.update(kw)
    return row


def _header(*, rooms=(), levels=()):
    return {"doc_name": "t", "levels": list(levels), "rooms": list(rooms),
            "grids": []}


class RoomsOfTheHeaderNeedNotBeNodes(unittest.TestCase):
    """The 14 334 + 2 962 + 210 edges of `k2_ar_rd_v1` lived exactly here."""

    def _rooms(self, *ids):
        return [{"id": rid, "level_id": "L1", "boundary_mm": _SQUARE,
                 "bounding_element_ids": ["W1"]} for rid in ids]

    def test_a_bounded_room_outside_the_stream_names_itself(self) -> None:
        """REFUTING CASE: before the fix, the WHOLE graph failed here."""
        graph = graph_from_l0(
            _header(rooms=self._rooms("R1")),
            [_element("W1", "OST_Walls")])
        edges = graph.relation_edges(Relation.BOUNDS_ROOM)
        self.assertEqual(len(edges), 1, "ребро исчезло — молчаливое выпадение")
        self.assertIs(edges[0].modality, Modality.UNRESOLVED_TARGET)
        self.assertEqual(edges[0].evidence["why"],
                         OutsideExtraction.ROOM_NOT_IN_SNAPSHOT.value)
        self.assertEqual(edges[0].src, "W1", "локальным концом обязан быть узел")

    def test_both_ends_outside_the_stream_do_not_refuse_the_graph(self) -> None:
        """2 962 edges of `k2_ar_rd_v1`: both the boundary element and the room
        are outside the stream.

        There is nothing to address such an edge with — the graph is a graph
        OVER ITS OWN NODES — but the whole construction must not be refused
        because of it.
        """
        graph = graph_from_l0(
            _header(rooms=self._rooms("R1")),
            [_element("X1", "OST_Furniture")])
        self.assertEqual(graph.relation_edges(Relation.BOUNDS_ROOM), ())
        self.assertEqual(len(graph), 1)

    def test_predicate_A_pair_outside_the_stream_is_addressed_by_the_opening(
            self) -> None:
        """210 edges of `k2_ar_rd_v1`: the predicate matched, the rooms are not
        in the stream.

        There is exactly one local end here — the opening itself; the edge is
        addressed by it, and both rooms ride along in the evidence.
        """
        graph = graph_from_l0(
            _header(rooms=self._rooms("R1", "R2")),
            [_element("W1", "OST_Walls"),
             _element("D1", "OST_Doors", host_id="W1")])
        edges = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.UNRESOLVED_TARGET)
        self.assertEqual(edges[0].src, "D1")
        self.assertEqual(edges[0].evidence["why"],
                         OutsideExtraction.ROOM_NOT_IN_SNAPSHOT.value)
        self.assertEqual(list(edges[0].evidence["room_ids"]), ["R1", "R2"])

    def test_the_proven_pair_is_UNCHANGED_when_both_rooms_are_nodes(self) -> None:
        """CONTROL IN THE REVERSE DIRECTION: without it the test cannot tell a
        fixed instrument from one that has stopped proving anything at all."""
        graph = graph_from_l0(
            _header(rooms=self._rooms("R1", "R2")),
            [_element("W1", "OST_Walls"),
             _element("D1", "OST_Doors", host_id="W1"),
             _element("R1", "OST_Rooms"), _element("R2", "OST_Rooms")])
        edges = graph.relation_edges(Relation.BOUNDED_BY_SAME_WALL)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN)
        self.assertEqual({edges[0].src, edges[0].dst}, {"R1", "R2"})
        bounds = graph.relation_edges(Relation.BOUNDS_ROOM)
        self.assertTrue(bounds)
        self.assertTrue(all(e.modality is Modality.PROVEN for e in bounds))


class LevelsOfTheHeaderNeedNotBeNodes(unittest.TestCase):
    """The 58 `level_above` edges in `k2_ar_rd_v1` had TWO external ends."""

    def _levels(self, *pairs):
        return [{"id": lid, "name": lid, "elevation_mm": z}
                for lid, z in pairs]

    def test_two_levels_outside_the_stream_do_not_refuse_the_graph(self) -> None:
        graph = graph_from_l0(
            _header(levels=self._levels(("L1", 0.0), ("L2", 3000.0))),
            [_element("W1", "OST_Walls")])
        self.assertEqual(graph.relation_edges(Relation.LEVEL_ABOVE), ())
        self.assertEqual(len(graph), 1)

    def test_one_level_outside_the_stream_is_named_not_dropped(self) -> None:
        graph = graph_from_l0(
            _header(levels=self._levels(("L1", 0.0), ("L2", 3000.0))),
            [_element("L1", "OST_Levels")])
        edges = graph.relation_edges(Relation.LEVEL_ABOVE)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.UNRESOLVED_TARGET)
        self.assertEqual(edges[0].src, "L1", "локальным концом обязан быть узел")
        self.assertEqual(edges[0].dst, "L2")
        self.assertEqual(edges[0].evidence["why"],
                         OutsideExtraction.LEVEL_NOT_IN_SNAPSHOT.value)
        # The direction of the relation is lost when the UPPER level turns
        # out to be external: `src` must be local. The evidence says which
        # one is higher.
        self.assertEqual(edges[0].evidence["upper"], "L2")

    def test_both_levels_present_still_prove_the_ordinary_edge(self) -> None:
        """CONTROL IN THE REVERSE DIRECTION."""
        graph = graph_from_l0(
            _header(levels=self._levels(("L1", 0.0), ("L2", 3000.0))),
            [_element("L1", "OST_Levels"), _element("L2", "OST_Levels")])
        edges = graph.relation_edges(Relation.LEVEL_ABOVE)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN)
        self.assertEqual((edges[0].src, edges[0].dst), ("L2", "L1"))
        self.assertEqual(edges[0].evidence["delta_mm"], 3000.0)


class TheWholeCorpusShapeIsReproduced(unittest.TestCase):
    """All three builders at once — exactly the shape of the five failed
    decompiles."""

    def test_a_header_only_document_builds_instead_of_refusing(self) -> None:
        rooms = [{"id": f"R{i}", "level_id": "L1", "boundary_mm": _SQUARE,
                  "bounding_element_ids": ["W1", "W2"]} for i in range(1, 4)]
        levels = [{"id": "L1", "name": "1", "elevation_mm": 0.0},
                  {"id": "L2", "name": "2", "elevation_mm": 3000.0}]
        graph = graph_from_l0(
            _header(rooms=rooms, levels=levels),
            [_element("W1", "OST_Walls"), _element("W2", "OST_Walls"),
             _element("D1", "OST_Doors", host_id="W1")])
        graph.census.assert_balanced()
        self.assertEqual(len(graph), 3)
        # Every edge that did come out carries a named reason.
        for edge in graph.edges:
            if edge.modality is Modality.UNRESOLVED_TARGET:
                self.assertIn(edge.evidence.get("why"),
                              {item.value for item in OutsideExtraction})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
