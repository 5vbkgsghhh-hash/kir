"""A CENSUS OF FOLD ADJACENCY — 82.6% OF DOORS FELL OUT SILENTLY.

`fold._semantic_fold` builds an adjacency edge ONLY when a door's host
bounds EXACTLY TWO rooms, and for any other count it does nothing and
says nothing. Yet the predicate was called "room adjacency."

MEASUREMENT 2026-08-10 (raw decompile of `L0.jsonl`, corpus
`backend/backend/data/decompile`, machine-local) — the number of rooms
bounded by a door's host:

    `demo-v3`      5,941 doors: {0: 2816, 1: 154, 2: 1036, 3: 966, 4: 648,
                   5: 50, 6: 76, 7: 25, 8: 55, 9: 113, 30: 1, 34: 1}
                   -> 1,036 doors get an edge, 17.4%
    `k2_ar_rd_v7`  2,096 doors: {0: 66, 1: 449, 2: 1054, 3: 326, 4: 125,
                   5: 25, 8: 8, 9: 1} -> 50.3%
    `sob62_r23_v5`   153 doors: {0: 15, 1: 79, 2: 47, 3: 12}

WHY THE OUTCOME IS GIVEN AS A CENSUS, NOT ANOTHER EDGE. The fold's shape
enters the digest: `merkle._build_merkle_node` computes a node's hash as
`_hash_parts(content_json, edges)`, where `edges` are the hashes of the
CHILDREN. A different arrangement of rooms into containers would shift
the hash of every node above the leaves and would devalue the saved
indices — dedup (×9.96 on Snowdon Plumbing) and diff pruning (33,617
subtrees on the `k2_ar_rd_v7`->`v8` pair). `BuildingState`, however,
would NOT be affected: it is a multiset of LEAF `canon_op`s, and the
leaves are held by `assert_preservation`, so journal reproduction
(18/18, 5/5, 3/3, 2/2) and `merge3` are insensitive to the shape of the
containers.

That is why the census counts what the fold stayed silent about, and
does NOT touch the tree, while the typed refuting edge lives in
`building_graph`.
"""
from __future__ import annotations

import unittest

from kir.decompile.fold import (
    FoldError,
    RoomAdjacencyCensus,
    room_adjacency_census,
)
from kir.decompile.schema import GeometryKind, L0Element, RoomInfo


def _door(source_id, host_id):
    return {"kind": "op", "_id": f"op:{source_id}",
            "source_element_id": source_id, "level_name": None,
            "anchor_mm": None, "op": "create_door", "params": {}}


def _element(element_id, category, host_id=None):
    return L0Element(
        element_id=element_id, category=category, category_ru="",
        type_id="t", type_name="T", level_id=None, level_name=None,
        # THE GEOMETRY KIND WAS DECLARED AS ONE THING AND CARRIED
        # ANOTHER. Here it was `POINT` with `p0_mm=None`, i.e. "a point
        # without a point"; the schema does not allow this (`point
        # geometry requires only p0_mm`) and six census tests failed at
        # the constructor, never reaching a single assertion — meaning
        # the file reported six times about something other than what
        # it checks. The test does not care about geometry — it is
        # about adjacency and the census — and the schema calls exactly
        # this shape `BBOX_ONLY`: all three point and curve fields are
        # empty. Declare what we carry.
        # AND THE SECOND HALF, WITHOUT WHICH THE FIRST READS AS A
        # RELAXATION: `POINT` without `p0_mm` is an INVALID L0 row, and
        # the production schema must keep rejecting it. It was the
        # fixture that was being fixed, not the rule.
        # (Two sessions arrived at this fix independently and wrote it
        # identically; both halves of the comment were reconciled on merge.)
        geom_kind=GeometryKind.BBOX_ONLY, p0_mm=None, p1_mm=None,
        rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
        host_id=host_id)


def _room(room_id, bounds):
    return RoomInfo(id=room_id, name=room_id, level_id=None, level_name=None,
                    area_m2=1.0, boundary_mm=(), boundary_loops_mm=(),
                    bounding_element_ids=tuple(bounds))


class CensusCountsWhatFoldWasSilentAbout(unittest.TestCase):
    """Key 2 is the only one that yields an edge. All the others are a NAMED outcome."""

    def _census(self, degrees):
        """degrees: how many rooms each door's host bounds."""
        nodes, elements, rooms = [], {}, []
        for index, degree in enumerate(degrees):
            door_id, host_id = f"D{index}", f"W{index}"
            nodes.append(_door(door_id, host_id))
            elements[door_id] = _element(door_id, "OST_Doors", host_id)
            elements[host_id] = _element(host_id, "OST_Walls")
            for room_index in range(degree):
                rooms.append(_room(f"R{index}_{room_index}", [host_id]))
        return room_adjacency_census(nodes, rooms, elements)

    def test_exactly_two_is_the_only_edge_building_degree(self) -> None:
        census = self._census([2, 2, 3])
        self.assertEqual(census.edges_built, 2)
        self.assertEqual(census.refuted, 1)
        self.assertEqual(census.by_degree, {2: 2, 3: 1})

    def test_zero_bounded_rooms_is_counted_not_dropped(self) -> None:
        """2,816 doors of `demo-v3` fall exactly here."""
        census = self._census([0, 0, 2])
        self.assertEqual(census.by_degree[0], 2)
        self.assertEqual(census.refuted, 2)
        self.assertEqual(census.edges_built, 1)

    def test_high_degree_survives_as_a_number(self) -> None:
        """`demo-v3` has a host that bounds 34 rooms."""
        census = self._census([34])
        self.assertEqual(census.by_degree, {34: 1})
        self.assertEqual(census.edges_built, 0)

    def test_census_balances(self) -> None:
        census = self._census([0, 1, 2, 3, 4])
        census.assert_balanced()
        self.assertEqual(census.doors_seen, 5)
        self.assertEqual(census.doors_with_host, 5)

    def test_door_without_a_host_is_its_own_named_bucket(self) -> None:
        nodes = [_door("D1", None)]
        elements = {"D1": _element("D1", "OST_Doors", None)}
        census = room_adjacency_census(nodes, [], elements)
        self.assertEqual(census.doors_without_host, 1)
        self.assertEqual(census.doors_with_host, 0)
        census.assert_balanced()

    def test_non_doors_are_not_counted_at_all(self) -> None:
        nodes = [_door("W1", None)]
        elements = {"W1": _element("W1", "OST_Walls")}
        census = room_adjacency_census(nodes, [], elements)
        self.assertEqual(census.doors_seen, 0)


class UnbalancedCensusIsUnconstructible(unittest.TestCase):
    """A census that does not reconcile lies silently, just as the fold would."""

    def test_mismatched_totals_refuse(self) -> None:
        census = RoomAdjacencyCensus(doors_seen=10, doors_without_host=1,
                                     by_degree={2: 3})
        with self.assertRaises(FoldError):
            census.assert_balanced()


class TheRatioThisExistsToShow(unittest.TestCase):
    """The share for whose sake the census was written."""

    def test_demo_v3_shape_reproduces_the_measured_ratio(self) -> None:
        degrees = ([0] * 2816 + [1] * 154 + [2] * 1036 + [3] * 966
                   + [4] * 648 + [5] * 50 + [6] * 76 + [7] * 25 + [8] * 55
                   + [9] * 113 + [30] + [34])
        self.assertEqual(len(degrees), 5941)
        census = RoomAdjacencyCensus(
            doors_seen=5941, doors_without_host=0,
            by_degree={d: degrees.count(d) for d in set(degrees)})
        census.assert_balanced()
        self.assertEqual(census.edges_built, 1036)
        self.assertEqual(census.refuted, 4905)
        share = census.edges_built / census.doors_seen
        self.assertAlmostEqual(share, 0.1744, places=3)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
