"""AN OPEN FLOOR PLAN CONNECTS; A SHARED WALL DOES NOT.

THE MEASUREMENT THAT BOUGHT THIS FILE (18.08.2026, the owner's tower
`13a-rd-ar-k2_v33_kuklev.d.s`, parsed in `backend/data/decompile/`).

The apartment inference was built ONLY from doors, and there is no
door between a living room and a kitchen alcove — the layout is open,
and the spaces are divided by a SEPARATION LINE
(`OST_RoomSeparationLines`). The witness sat in the parser
(`RoomInfo.bounding_element_ids`, 2,958 references to separators out
of 17,296 boundary ones) and broke off on the way into `SpatialModel`.

Numbers through the real pipeline, predicate `apartments_are_dwellings`
("kitchen OR bathroom," `engine.py:342`), BOTH positions of
`KUKAI_CHECKER_V2`:

    v2=1   apartments 995 -> 808   non-dwellings 621 -> 429
    v2=0   apartments 1612 -> 1301 non-dwellings 1612 -> 645
    kindergarten `sob62_r23_v5`: separators 0 — a DEGENERATE control,
                            no effect and none possible, and this is a
                            property of the BUILDING

🔴 WHAT THIS FILE GUARDS ABOVE ALL — IS NOT THE BENEFIT, BUT THE HARM.
The first edition joined by CLIQUE every space that named one
separator. On the tower **34 separators border more than two
spaces**, and the clique produced **19 "apartments" with two or more
kitchens** — two apartments merged into one. A false merge is worse
than an undercount: it doesn't understate a number, it LIES ABOUT THE
DWELLING'S COMPOSITION, and composition is exactly the subject of
HAB002/003/004. With **0** false merges on the whole SEGMENT.

The `_SEPARATOR_TOUCH_MM` threshold was not tuned to the result: 603
pairs at tolerances of 10, 50, 200, and 600 mm — the split is
structural, not threshold-dependent.

Run:
    venv/bin/python -m pytest kir/tests/test_separator_edges.py -q
"""
from __future__ import annotations

import unittest

from kir.checker.graph import build_graph, _separator_pairs
from kir.checker.spatial_model import (
    Level, Room, RoomFunction, SpatialModel,
)


def _room(rid: str, boundary, *, function=RoomFunction.ЖИЛАЯ, seps=()) -> Room:
    return Room(id=rid, name=rid, level_id="L1", function=function,
                area_m2=10.0, height_mm=2700.0, boundary=list(boundary),
                separator_ids=tuple(seps))


def _model(*rooms: Room) -> SpatialModel:
    return SpatialModel(
        building_id="b", levels=[Level(id="L1", name="L1", elevation_mm=0.0,
                                       index=0)],
        rooms=list(rooms), doors=[], windows=[], stairs=[], walls=[])


#: Two rectangles sharing the WHOLE segment x=1000 from y=0 to y=3000.
_LEFT = [(0.0, 0.0), (1000.0, 0.0), (1000.0, 3000.0), (0.0, 3000.0)]
_RIGHT = [(1000.0, 0.0), (2000.0, 0.0), (2000.0, 3000.0), (1000.0, 3000.0)]
#: A third one — on the same line x=1000, but HIGHER: it shares no
#: length with the first two.
_FAR = [(1000.0, 9000.0), (2000.0, 9000.0), (2000.0, 12000.0),
        (1000.0, 12000.0)]


class AnOpenPlanIsConnected(unittest.TestCase):

    def test_two_rooms_sharing_a_separator_and_a_segment_are_joined(self):
        m = _model(_room("a", _LEFT, seps=("s1",)),
                   _room("b", _RIGHT, function=RoomFunction.КУХНЯ,
                         seps=("s1",)))
        g = build_graph(m)
        self.assertTrue(g.has_edge("a", "b"),
                        "кухня-ниша за линией разделения осталась отрезанной")
        self.assertEqual(g["a"]["b"]["kind"], "separator",
                         "род ребра обязан отличаться от дверного: они доказаны "
                         "РАЗНЫМИ свидетелями, и слить их значит потерять "
                         "различие навсегда")


class AShredIdIsNotAWitness(unittest.TestCase):
    """🔴 A control aimed exactly at the defect that produced 19 false
    merges."""

    def test_a_third_room_on_the_same_separator_is_NOT_joined(self):
        m = _model(_room("a", _LEFT, seps=("s1",)),
                   _room("b", _RIGHT, seps=("s1",)),
                   _room("far", _FAR, seps=("s1",)))
        pairs = {(x, y) for x, y, _ in _separator_pairs(m)}
        self.assertIn(("a", "b"), pairs)
        self.assertNotIn(("a", "far"), pairs,
                         "общий id разделителя принят за свидетель — это КЛИКА, "
                         "и на башне она слила по две квартиры в 19 случаях")
        self.assertNotIn(("b", "far"), pairs)

    def test_rooms_sharing_only_a_wall_are_not_joined(self):
        """The same geometry, but no separator — a shared WALL does
        not connect."""
        m = _model(_room("a", _LEFT), _room("b", _RIGHT))
        g = build_graph(m)
        self.assertEqual(_separator_pairs(m), [])
        self.assertFalse(g.has_edge("a", "b"),
                         "помещения соединены через общую стену — так "
                         "склеиваются СОСЕДНИЕ КВАРТИРЫ")

    def test_a_touching_corner_is_not_a_shared_segment(self):
        """Touching at a point is not an opening: zero length does
        not connect."""
        corner = [(1000.0, 3000.0), (2000.0, 3000.0), (2000.0, 6000.0),
                  (1000.0, 6000.0)]
        m = _model(_room("a", _LEFT, seps=("s1",)),
                   _room("c", corner, seps=("s1",)))
        self.assertEqual(_separator_pairs(m), [],
                         "общий УГОЛ засчитан как общий отрезок")


class TheFieldCarriesMeaningNotRawIds(unittest.TestCase):

    def test_empty_separator_ids_leave_the_graph_exactly_as_before(self):
        """The PROGRAM path gives no field at all — the behavior must
        not shift."""
        m = _model(_room("a", _LEFT), _room("b", _RIGHT))
        self.assertEqual(build_graph(m).number_of_edges(), 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
