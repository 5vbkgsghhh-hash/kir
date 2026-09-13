"""ROOM GEOMETRY THAT FAILED TO BUILD IS NOT A FACT ABOUT NON-ADJACENCY (F-319).

CAUSE. A room whose polygon fails to build dropped out of the index
SILENTLY, and a self-intersecting one was silently fixed by `buffer(0)`,
keeping ONLY the single largest part. When, as a result, an opening
touched fewer than two rooms, a POSITIVE `REFUTED` statement was issued —
"these rooms are not adjacent" — even though what the predicate lacked
was not non-adjacency but GEOMETRY. The census, meanwhile, RECONCILED
fine: it counted openings and asked nothing about rooms.

🔴 THE FINDINGS LOG DEMANDED THE WRONG THING, AND THIS IS SETTLED BY
MEASUREMENT, NOT BY READING. The log described the case "butterfly ->
`buffer(0)` -> one petal survives." A measurement on the live corpus:
6,406 dropped rooms, and ALL 6,406 (100%) have an EMPTY `boundary_mm`. So
the first kind here is `boundary_mm_is_empty`, named separately from
"fewer than three points" (of which the corpus has 0).

🔴 BUT "ZERO BUTTERFLIES" IS ALSO A NUMBER ABOUT A DIFFERENT SUBJECT, and
this too is checked by execution. The previous measurement counted DROPPED
rooms (`poly is None`), while a fixed room does NOT drop out: it stays in
the index, altered. On `mnvnk_atr_pd_b14_k3` there are 4 of them — 2 fixed
and 2 truncated — against 391 dropped. The instrument could not see them
BY CONSTRUCTION. So both kinds are guarded here: the defect in an altered
room is more dangerous — it answers, and answers wrongly.

WHAT IS GUARDED: not "always POSSIBLE." The edge is weakened EXACTLY
WHERE the level had a room that failed to build or was altered; on a clean
level `REFUTED` stays `REFUTED`, and proven adjacency stays `PROVEN`.
Without this second half, the fix is indistinguishable from "give up on
every opening."

MEASUREMENT AFTER THE FIX on real buildings (read-only):
    bench_A         144 rooms, 5 without a contour -> refuted 3 · possible 5 · proven 118
    sob62_r23_v6    120 rooms, 13 without a contour -> refuted 14 · possible 21 · proven 117
The share of weakened edges among non-positive ones is 5/8 and 21/35, i.e.
62% and 60%, against a corpus-wide estimate of 62.3%.

Run:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_a_missing_room_is_not_a_proven_non_adjacency.py -q
"""
from __future__ import annotations

import unittest

from kir.decompile.building_graph import GraphBuildError, Modality
from kir.decompile.graph_adjacency import (
    REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO,
    ROOM_GEOMETRY_NO_BOUNDARY,
    ROOM_GEOMETRY_OK,
    ROOM_GEOMETRY_REPAIRED,
    ROOM_GEOMETRY_TOO_FEW_POINTS,
    AdjacencyCensus,
    _polygon,
    opening_point_touches_room_edges,
)

_A = [[0, 0], [4000, 0], [4000, 4000], [0, 4000]]
_B_OK = [[4000, 0], [8000, 0], [8000, 4000], [4000, 4000]]
#: A butterfly: the petal at the door is small, the fix keeps the far
#: part.
_B_BOW = [[4000, 0], [20000, 8000], [20000, 0], [4000, 2000]]

#: The door sits ON THE SHARED EDGE of rooms A and B.
_DOOR = {"door1": {"category": "OST_Doors", "level_id": "L1",
                   "p0_mm": [4000.0, 1000.0, 0.0]}}


def _header(b_boundary):
    return {"rooms": [{"id": "A", "level_id": "L1", "boundary_mm": _A},
                      {"id": "B", "level_id": "L1",
                       "boundary_mm": b_boundary}]}


class TheMeasuredMechanismIsCovered(unittest.TestCase):
    """An empty `boundary_mm` — 100% of the corpus's dropped rooms."""

    def test_an_empty_boundary_weakens_the_claim_and_names_the_room(self):
        edges, census = opening_point_touches_room_edges(_header([]), _DOOR)
        self.assertEqual(len(edges), 1)
        edge = edges[0]
        self.assertIs(
            edge.modality, Modality.POSSIBLE,
            "«не смежны» выпущено там, где комнаты просто не было")
        self.assertIsNone(edge.refuted_by)
        # `GraphEdge` freezes the evidence: lists arrive as tuples.
        self.assertEqual(
            list(edge.evidence["rooms_with_unfaithful_geometry"]), ["B"])
        self.assertEqual(dict(edge.evidence["room_geometry"]),
                         {"B": ROOM_GEOMETRY_NO_BOUNDARY})
        self.assertEqual(census.rooms_seen, 2)
        self.assertEqual(dict(census.room_geometry),
                         {"B": ROOM_GEOMETRY_NO_BOUNDARY})
        self.assertEqual(census.rooms_faithful, 1)
        census.assert_balanced()

    def test_an_empty_boundary_is_named_apart_from_a_short_one(self):
        """"No contour" and "too few points" are different facts about
        different troubles."""
        self.assertEqual(_polygon([])[1], ROOM_GEOMETRY_NO_BOUNDARY)
        self.assertEqual(_polygon(None)[1], ROOM_GEOMETRY_NO_BOUNDARY)
        self.assertEqual(_polygon([[0, 0], [1, 1]])[1],
                         ROOM_GEOMETRY_TOO_FEW_POINTS)


class TheAlteredRoomIsCoveredToo(unittest.TestCase):
    """A fixed room does NOT drop out — and is therefore more dangerous
    than a dropped one."""

    def test_a_repaired_boundary_also_weakens_the_claim(self):
        edges, census = opening_point_touches_room_edges(
            _header(_B_BOW), _DOOR)
        self.assertIs(edges[0].modality, Modality.POSSIBLE)
        self.assertEqual(dict(census.room_geometry),
                         {"B": ROOM_GEOMETRY_REPAIRED})

    def test_a_repaired_room_still_yields_a_polygon(self):
        """Exactly why the previous measurement did not see it: it did not
        "drop out"."""
        poly, state = _polygon(_B_BOW)
        self.assertIsNotNone(poly, "починенная комната обязана остаться")
        self.assertNotEqual(state, ROOM_GEOMETRY_OK)


class TheClaimIsNotWeakenedEverywhere(unittest.TestCase):
    """🔴 THE SECOND OUTCOME. Otherwise the fix is indistinguishable from
    "give up on everything"."""

    def test_a_clean_level_keeps_its_proven_adjacency(self):
        edges, census = opening_point_touches_room_edges(
            _header(_B_OK), _DOOR)
        self.assertEqual(len(edges), 1)
        self.assertIs(edges[0].modality, Modality.PROVEN)
        self.assertEqual(dict(census.room_geometry), {})

    def test_a_clean_level_still_refutes_when_one_room_is_touched(self):
        header = {"rooms": [{"id": "A", "level_id": "L1",
                             "boundary_mm": _A}]}
        edges, census = opening_point_touches_room_edges(header, _DOOR)
        self.assertEqual(len(edges), 1)
        self.assertIs(
            edges[0].modality, Modality.REFUTED,
            "на чистом уровне опровержение ЗАРАБОТАНО и обязано остаться")
        self.assertEqual(edges[0].refuted_by,
                         REFUTED_OPENING_TOUCHES_FEWER_THAN_TWO)
        self.assertNotIn("rooms_with_unfaithful_geometry",
                         edges[0].evidence)
        self.assertEqual(dict(census.room_geometry), {})

    def test_a_dirty_level_does_not_taint_a_clean_neighbour(self):
        """It is the LEVEL that is contaminated, not the building: the
        neighboring floor is left untouched."""
        header = {"rooms": [
            {"id": "A", "level_id": "L1", "boundary_mm": _A},
            {"id": "B", "level_id": "L1", "boundary_mm": []},
            {"id": "C", "level_id": "L2", "boundary_mm": _A},
        ]}
        doors = {
            "door1": {"category": "OST_Doors", "level_id": "L1",
                      "p0_mm": [4000.0, 1000.0, 0.0]},
            "door2": {"category": "OST_Doors", "level_id": "L2",
                      "p0_mm": [4000.0, 1000.0, 0.0]},
        }
        edges, _census = opening_point_touches_room_edges(header, doors)
        by_door = {e.src: e for e in edges}
        self.assertIs(by_door["door1"].modality, Modality.POSSIBLE)
        self.assertIs(by_door["door2"].modality, Modality.REFUTED)


class TheRoomCensusHasItsOwnLaw(unittest.TestCase):
    """A law that reconciles on one subject stays confidently silent about
    the other."""

    def test_a_balanced_room_census_passes(self):
        AdjacencyCensus(openings_seen=1, openings_evaluated=1, refusals={},
                        touch_degree={1: 1}, rooms_seen=2,
                        room_geometry={"B": ROOM_GEOMETRY_NO_BOUNDARY}
                        ).assert_balanced()

    def test_more_broken_rooms_than_rooms_is_refused(self):
        with self.assertRaises(GraphBuildError):
            AdjacencyCensus(
                openings_seen=1, openings_evaluated=1, refusals={},
                touch_degree={1: 1}, rooms_seen=1,
                room_geometry={"B": ROOM_GEOMETRY_NO_BOUNDARY,
                               "C": ROOM_GEOMETRY_NO_BOUNDARY}
            ).assert_balanced()

    def test_the_opening_law_still_holds_on_its_own(self):
        with self.assertRaises(GraphBuildError):
            AdjacencyCensus(openings_seen=5, openings_evaluated=1,
                            refusals={}, touch_degree={1: 1}).assert_balanced()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
