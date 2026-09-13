"""Room-point capture arrived — the lift did not pick it up.

Throughout the project's entire history (55 saved decompiles, 4 buildings), EVERY
room had `p0_mm` as null: the same API member that killed group reading also cost
the point for every room. This was fixed on 30.07, and the tower gave rooms
with a point for the first time.

The lift did not notice. `_lift_room` explicitly passed `source_location_mm=None`,
with the comment "L0 1.0 stores only boundaries, not Room.Location" —
true at the time of writing and outdated the day capture moved on. The seam
between capture and the lift rested on a COMMENT, not on a contract, and
so it diverged silently.

The cost is not cosmetic. For a non-convex room — L-shaped, a corridor,
a room with a cutout — a center computed from the contour can lie OUTSIDE the
room itself. A rebuilt room would then land in a neighboring room or fail to
be created at all. On the tower this produced 2153 discrepancies out of 2153 lifted
rooms, with deviations of up to 5339 mm.

The tests hold BOTH sides of the rule, because "just trust capture" is
also a defect: a captured point can turn out to be outside the contour (a room
was re-surveyed, the boundaries shifted), and then the only honest answer is
a deterministic fallback, not a broken program.
"""
from __future__ import annotations

import math
import unittest

from kir.decompile.lift import lift_document
from kir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
    RoomInfo,
)

_LEVEL = LevelInfo(id="100", name="Этаж 1", elevation_mm=0.0)
_PROJ = ProjectInfo(name="Проект", address="адрес", building_type_hint=None)

#: An L-shaped room. The bounding-box center (5000, 5000) lies IN THE CUTOUT, that is,
#: outside; any "center" derived from the bounding box points to the wrong place.
_L_SHAPE = (
    (0.0, 0.0), (10000.0, 0.0), (10000.0, 3000.0),
    (3000.0, 3000.0), (3000.0, 10000.0), (0.0, 10000.0),
)

#: The point Revit actually holds for this room: inside the lower
#: shelf, far from any derived center.
_CAPTURED = [8000.0, 1500.0, 0.0]


def _room(**kw) -> RoomInfo:
    base = dict(
        id="8001", name="Комн 101", level_id="100", level_name="Этаж 1",
        area_m2=51.0, boundary_mm=_L_SHAPE, boundary_loops_mm=(_L_SHAPE,),
        bounding_element_ids=())
    base.update(kw)
    return RoomInfo(**base)


def _room_element(p0: list[float] | None) -> L0Element:
    return L0Element(
        element_id="8001", category="OST_Rooms", category_ru="Помещения",
        type_id="7001", type_name="Помещение", level_id="100", level_name="Этаж 1",
        geom_kind=GeometryKind.POINT if p0 else GeometryKind.BBOX_ONLY,
        p0_mm=p0, p1_mm=None, rotation_deg=None,
        bbox_min_mm=[0.0, 0.0, 0.0], bbox_max_mm=[10000.0, 10000.0, 3000.0],
        host_id=None, params={})


def _document(p0: list[float] | None) -> L0Document:
    return L0Document(
        doc_name="проба", revit_version="2023", units="mm",
        change_stamp="room-point-test", levels=(_LEVEL,), grids=(),
        rooms=(_room(),), project_info=_PROJ,
        elements=(_room_element(p0),))


def _lift_xy(p0: list[float] | None) -> tuple[float, float]:
    ops = [n for n in lift_document(_document(p0))
           if n["kind"] == "op" and n["op_name"] == "create_room"]
    assert len(ops) == 1, f"ожидался ровно один create_room, получено {ops!r}"
    xy = ops[0]["params"]["xy"]
    return (float(xy[0]), float(xy[1]))


class RoomSourcePointTests(unittest.TestCase):

    def test_a_captured_room_point_is_used_verbatim(self) -> None:
        """REFUTING TEST: the point from the model must make it to the operation.

        Before the fix, the lift computed its own point and never looked at the
        captured one, so here there stood a discrepancy of thousands of millimeters — exactly what
        the verifier reported 2153 times in a row and that nobody read, because
        everyone was looking at coverage.
        """
        xy = _lift_xy(_CAPTURED)
        self.assertAlmostEqual(xy[0], _CAPTURED[0], delta=0.5)
        self.assertAlmostEqual(xy[1], _CAPTURED[1], delta=0.5)

    def test_without_a_captured_point_the_fallback_stays_inside(self) -> None:
        """The old behavior remains LEGITIMATE where there is no point.

        Snapshots captured before 30.07 carry no point, and their lift must still work
        as before — but the derived point must lie INSIDE the room, not
        in the cutout of an L-shaped contour.
        """
        x, y = _lift_xy(None)
        self.assertFalse(
            3000.0 < x and 3000.0 < y,
            f"выведенная точка ({x}, {y}) попала в вырез, то есть вне помещения")

    def test_a_captured_point_outside_the_room_is_not_trusted(self) -> None:
        """The flip side: capture can lie too.

        If the point is outside the contour (the boundaries were re-surveyed, the snapshot aged),
        the honest answer is a deterministic fallback, not a program
        that creates the room in the neighboring room.
        """
        x, y = _lift_xy([9000.0, 9000.0, 0.0])      # in the cutout, outside
        self.assertFalse(
            math.isclose(x, 9000.0, abs_tol=1.0)
            and math.isclose(y, 9000.0, abs_tol=1.0),
            "точка вне помещения принята как есть — подъём доверяет захвату "
            "слепо, и пересобранное помещение уедет в чужое пространство")

    def test_the_point_that_lands_in_the_op_also_lands_in_the_anchor(self) -> None:
        """The anchor and the parameter must say the same thing.

        The verifier compares predicted points against the ones read, and the
        prediction is taken from `xy` if it exists, and from `anchor_mm` otherwise.
        Let the two diverge, and the verdict would start depending on which branch
        the reader picked, not on what was built.
        """
        node = [n for n in lift_document(_document(_CAPTURED))
                if n["kind"] == "op" and n["op_name"] == "create_room"][0]
        xy = node["params"]["xy"]
        anchor = node["anchor_mm"]
        self.assertAlmostEqual(float(anchor[0]), float(xy[0]), delta=0.5)
        self.assertAlmostEqual(float(anchor[1]), float(xy[1]), delta=0.5)


if __name__ == "__main__":
    unittest.main()
