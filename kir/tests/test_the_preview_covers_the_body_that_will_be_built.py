"""THE FREE-FORM PREVIEW SHOWS WHAT WILL ACTUALLY BE BUILT.

Three defects of one seam (`course/rhino.py`). All three cost the same
thing: the author looks at the picture and makes a decision from it, while
something different travels into the model.

RT-01. The author's op carries `holes` (`_as_region` keeps them "WITHOUT
losing the holes"), while `_loft_mesh` did not know the word `hole` at
all — the cap was filled in solid.
RT-02. The cap was assembled as a FAN from vertex 0. A fan is correct
exactly for a convex ring; on a concave one it covers area OUTSIDE the
polygon.
RT-03. `move`/`rotate`/`mirror`/`scale`/`array` moved the carrier's mesh,
while `ops` relocated to the new carrier using THE SAME objects.

🔴 WHY AREA, NOT A LIST OF TRIANGLES. Nobody checks triangles by eye, and
an instrument comparing them to a recorded answer would go red on any
legal reordering. The area of the horizontal triangles is a quantity that
can be computed INDEPENDENTLY (the polygon area formula from
coordinates), and a mismatch with it is a fact about the body, not about
our code.
"""
from __future__ import annotations

import math
import unittest

from kir import dsl as D
from kir.course import rhino as R
from kir.diag import KirRefusal


# ── an independent count, NOT through the code being checked ───────────────

def _polygon_area(points) -> float:
    """Area of a simple polygon from coordinates (the shoelace formula)."""
    total = 0.0
    for i in range(len(points)):
        x1, y1 = points[i][0], points[i][1]
        x2, y2 = points[(i + 1) % len(points)][0], points[(i + 1) % len(points)][1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _cap_area(mesh, z: float) -> float:
    """Area of the mesh's HORIZONTAL triangles at elevation `z`."""
    verts = mesh["vertices_mm"]
    total = 0.0
    for a, b, c in mesh["triangles"]:
        pa, pb, pc = verts[a], verts[b], verts[c]
        if max(abs(pa[2] - z), abs(pb[2] - z), abs(pc[2] - z)) > 1e-6:
            continue
        total += abs((pb[0] - pa[0]) * (pc[1] - pa[1])
                     - (pc[0] - pa[0]) * (pb[1] - pa[1])) / 2.0
    return total


def _cap_normal_z(mesh, z: float) -> float:
    """The sum of the z-components of the cap's normals: the sign tells which way it faces."""
    verts = mesh["vertices_mm"]
    total = 0.0
    for a, b, c in mesh["triangles"]:
        pa, pb, pc = verts[a], verts[b], verts[c]
        if max(abs(pa[2] - z), abs(pb[2] - z), abs(pc[2] - z)) > 1e-6:
            continue
        total += ((pb[0] - pa[0]) * (pc[1] - pa[1])
                  - (pb[1] - pa[1]) * (pc[0] - pa[0]))
    return total


_SQUARE = [[0, 0], [6000, 0], [6000, 6000], [0, 6000]]
#: «П»: a concave profile on which the fan covers ×1.30 of the area.
_P_SHAPE = [[0, 0], [6000, 0], [6000, 2000], [4000, 2000], [4000, 6000],
            [6000, 6000], [6000, 8000], [0, 8000]]
_BIG = [[0, 0], [10000, 0], [10000, 10000], [0, 10000]]
_HOLE = [[3000, 3000], [7000, 3000], [7000, 7000], [3000, 7000]]


def _region(outer, *holes) -> dict:
    body = {"outer": {"shape": "poly", "points_mm": [list(p) for p in outer]}}
    if holes:
        body["holes"] = [{"shape": "poly", "points_mm": [list(p) for p in h]}
                         for h in holes]
    return body


class _Fresh:
    """A separate program for each instrument: `loft` accumulates ops in the CURRENT one."""

    def __enter__(self):
        return D.program(intent="ворота предпросмотра")

    def __exit__(self, *exc):
        return False


# ═══════════════════════════════════════════════════════════════════════════
# RT-02. Concave profile
# ═══════════════════════════════════════════════════════════════════════════

class TheCapCoversTheProfileAndNothingElse(unittest.TestCase):

    def test_a_convex_profile_is_the_control_and_it_was_always_right(self):
        """CONTROL. On a convex shape the fan was already exact — the
        instrument measures something OTHER than itself.

        Without this line, "cap = area" could have turned out to be a
        property of the measurement itself: it must give the same truth
        where there was no defect.
        """
        with _Fresh():
            shape = R.loft([(_SQUARE, 0), (_SQUARE, 3000)], name="выпуклый")
        honest = _polygon_area(_SQUARE)
        self.assertEqual(honest, 36_000_000.0)
        self.assertAlmostEqual(_cap_area(shape["mesh"], 0.0), honest, places=3)
        self.assertAlmostEqual(_cap_area(shape["mesh"], 3000.0), honest,
                               places=3)

    def test_a_concave_profile_is_no_longer_covered_outside_itself(self):
        """POSITIVE. Measurement before the fix: 52,000,000 versus
        40,000,000 (×1.30).

        The fan from vertex 0 on the "П" shape covers the cutout — that
        is, the preview promised a slab where there is none.
        """
        with _Fresh():
            shape = R.loft([(_P_SHAPE, 0), (_P_SHAPE, 3000)], name="вогнутый")
        honest = _polygon_area(_P_SHAPE)
        self.assertEqual(honest, 40_000_000.0)
        self.assertAlmostEqual(_cap_area(shape["mesh"], 0.0), honest, places=3)
        self.assertAlmostEqual(_cap_area(shape["mesh"], 3000.0), honest,
                               places=3)

    def test_a_star_is_covered_exactly_too(self):
        """A stronger concavity: a ten-pointed star, ×1.82 on the fan.

        🔴 THE FIXTURE WAS CHOSEN BY MEASUREMENT, NOT BY EYE. The same
        star, started from a POINT, came out EXACT on the fan (×1.0000): a
        fan from a tip covers such a star completely, and the instrument
        would have been green on it BEFORE the fix — that is, it would
        have passed. Starting from a NOTCH gives 53,430,678 against an
        honest 29,389,263.
        """
        star = []
        for i in range(10):
            radius = 2000.0 if i % 2 == 0 else 5000.0      # NOTCH first
            angle = math.pi / 2 + i * math.pi / 5
            star.append([radius * math.cos(angle), radius * math.sin(angle)])
        with _Fresh():
            shape = R.loft([(star, 0), (star, 3000)], name="звезда")
        self.assertAlmostEqual(_cap_area(shape["mesh"], 0.0),
                               _polygon_area(star), places=3)

    def test_the_caps_still_face_out(self):
        """BOTTOM FACES DOWN, TOP FACES UP — the fan's previous behavior.

        Both orientations of the author's ring must give the same thing:
        the sign of the area is the only fact about the winding that we
        actually have.
        """
        for name, ring in (("CCW", _P_SHAPE), ("CW", _P_SHAPE[::-1])):
            with self.subTest(ring=name):
                with _Fresh():
                    shape = R.loft([(ring, 0), (ring, 3000)], name="крышки")
                self.assertLess(_cap_normal_z(shape["mesh"], 0.0), 0.0)
                self.assertGreater(_cap_normal_z(shape["mesh"], 3000.0), 0.0)


# ═══════════════════════════════════════════════════════════════════════════
# RT-01. Openings
# ═══════════════════════════════════════════════════════════════════════════

class ThePreviewKeepsTheHolesTheProgramCarries(unittest.TestCase):

    def test_the_op_carries_the_hole_and_now_so_does_the_mesh(self):
        """POSITIVE. Measurement: cap 100,000,000 versus an honest
        84,000,000.

        The first thing checked is that the hole ACTUALLY REACHED the
        operation at all: otherwise the instrument would be measuring the
        absence of a hole on the way in, not the fill on the way out.
        """
        with _Fresh() as program:
            shape = R.loft([(_region(_BIG, _HOLE), 0),
                            (_region(_BIG, _HOLE), 5000)], name="с проёмом")
        node = program.ops[-1]
        self.assertEqual(node["op"], "create_solid_blend")
        self.assertEqual(len(node["profile"]["holes"]), 1)
        honest = _polygon_area(_BIG) - _polygon_area(_HOLE)
        self.assertEqual(honest, 84_000_000.0)
        self.assertAlmostEqual(_cap_area(shape["mesh"], 0.0), honest, places=3)
        self.assertAlmostEqual(_cap_area(shape["mesh"], 5000.0), honest,
                               places=3)

    def test_a_profile_without_holes_is_the_control(self):
        """FAIL CONTROL. The same outer contour WITHOUT an opening is
        covered whole.

        Otherwise "84,000,000" could turn out to be a consequence of the
        cap simply no longer being built at all.
        """
        with _Fresh():
            shape = R.loft([(_BIG, 0), (_BIG, 5000)], name="без проёма")
        self.assertAlmostEqual(_cap_area(shape["mesh"], 0.0),
                               _polygon_area(_BIG), places=3)

    def test_the_shaft_has_walls_so_a_section_can_see_it(self):
        """THE OPENING'S WALLS EXIST, AND `section()` CHECKS THIS.

        `section` assembles rings from segments; an opening without walls
        would not give a single segment and would vanish a second time —
        this time in the floor plan.
        """
        with _Fresh():
            shape = R.loft([(_region(_BIG, _HOLE), 0),
                            (_region(_BIG, _HOLE), 5000)], name="шахта")
        plan = R.section(shape, 2500)
        self.assertEqual(len(plan.get("holes") or []), 1, plan)
        self.assertAlmostEqual(_polygon_area(plan["outer"]["points_mm"]),
                               _polygon_area(_BIG), places=3)
        self.assertAlmostEqual(
            _polygon_area(plan["holes"][0]["points_mm"]),
            _polygon_area(_HOLE), places=3)

    def test_three_holes_at_once(self):
        holes = [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]],
                 [[4000, 4000], [6000, 4000], [6000, 6000], [4000, 6000]],
                 [[8000, 8000], [9000, 8000], [9000, 9000], [8000, 9000]]]
        with _Fresh():
            shape = R.loft([(_region(_BIG, *holes), 0),
                            (_region(_BIG, *holes), 4000)], name="три проёма")
        honest = _polygon_area(_BIG) - sum(_polygon_area(h) for h in holes)
        self.assertAlmostEqual(_cap_area(shape["mesh"], 0.0), honest, places=3)

    def test_a_hole_in_a_concave_profile(self):
        """Both defects at once: a concave contour AND an opening."""
        hole = [[500, 500], [2500, 500], [2500, 2500], [500, 2500]]
        with _Fresh():
            shape = R.loft([(_region(_P_SHAPE, hole), 0),
                            (_region(_P_SHAPE, hole), 3000)], name="оба")
        honest = _polygon_area(_P_SHAPE) - _polygon_area(hole)
        self.assertAlmostEqual(_cap_area(shape["mesh"], 0.0), honest, places=3)

    def test_sections_whose_holes_disagree_get_no_mesh_and_a_named_reason(self):
        """THE SAME LAW AS FOR A DIFFERENT POINT COUNT ON THE OUTSIDE.

        The correspondence of an opening's vertices between sections is
        Revit's own choice; inventing it would mean describing a body we
        never built. And silently closing the opening is exactly the lie
        the openings were brought in here to remove.
        """
        with _Fresh():
            shape = R.loft([(_region(_BIG, _HOLE), 0), (_BIG, 5000)],
                           name="проёмы разошлись")
        self.assertIsNone(shape["mesh"])
        self.assertIn("проёмы", shape["mesh_absent_reason"])
        self.assertTrue(shape["ops"], "операции строиться обязаны")
        with self.assertRaises(KirRefusal) as caught:
            R.faces(shape)
        self.assertIn("проёмы", str(caught.exception))

    def test_the_reconstructed_shape_keeps_the_hole_too(self):
        """`_shape_from_op` assembles the mesh with the SAME `_loft_mesh` —
        so with the opening too. Two walks would have diverged silently."""
        with _Fresh() as program:
            R.loft([(_region(_BIG, _HOLE), 0), (_region(_BIG, _HOLE), 5000)],
                   name="обратно")
        again = R._shape_from_op(program.ops[-1])
        self.assertIsNotNone(again)
        self.assertAlmostEqual(_cap_area(again["mesh"], 0.0),
                               _polygon_area(_BIG) - _polygon_area(_HOLE),
                               places=3)


# ═══════════════════════════════════════════════════════════════════════════
# RT-03. Shifting the carrier with live handles
# ═══════════════════════════════════════════════════════════════════════════

class MovingAPictureDoesNotMoveTheBuilding(unittest.TestCase):

    def test_moving_a_body_with_live_handles_is_a_named_refusal(self):
        """POSITIVE. Measurement before the fix: the mesh moved to
        x∈[100000, 106000], while the op IN THE PROGRAM stayed at
        x∈[0, 6000].

        There is nothing to move the ops themselves with: `loft` has
        already placed them in the current program, and `ops` holds
        ADDRESSES (`dsl.Handle`), not copies. The refusal names the
        correct form.
        """
        with _Fresh() as program:
            shape = R.loft([(_SQUARE, 0), (_SQUARE, 3000)], name="ехать")
            before = [p[0] for p in program.ops[-1]["profile"]["outer"]["points_mm"]]
            with self.assertRaises(KirRefusal) as caught:
                R.move(shape, 100_000, 0, 0)
            after = [p[0] for p in program.ops[-1]["profile"]["outer"]["points_mm"]]
        self.assertEqual(before, after, "отказ ПРАВИЛ программу")
        text = str(caught.exception)
        self.assertIn("живых ручек", text)
        self.assertIn("loft(", text)

    def test_every_transform_refuses_the_same_way(self):
        for name, call in (
                ("move", lambda s: R.move(s, 1000, 0, 0)),
                ("rotate", lambda s: R.rotate(s, 90)),
                ("mirror", lambda s: R.mirror(s, "x")),
                ("scale", lambda s: R.scale(s, 2)),
                ("array", lambda s: R.array(s, 3, step_mm=(1000, 0)))):
            with self.subTest(transform=name):
                with _Fresh():
                    shape = R.loft([(_SQUARE, 0), (_SQUARE, 3000)], name=name)
                    with self.assertRaises(KirRefusal):
                        call(shape)

    def test_the_profile_moves_and_that_is_the_named_way(self):
        """FAIL CONTROL. The correct form MUST work.

        A refusal with no working alternative is a ban, not a hint: move
        the PROFILE before the build, and then both the picture and the
        program move with it.
        """
        with _Fresh() as program:
            moved = R.move(_SQUARE, 100_000, 0, 0)
            shape = R.loft([(moved, 0), (moved, 3000)], name="верно")
            xs_op = [p[0] for p in program.ops[-1]["profile"]["outer"]["points_mm"]]
        xs_mesh = [v[0] for v in shape["mesh"]["vertices_mm"]]
        self.assertEqual((min(xs_op), max(xs_op)), (100_000.0, 106_000.0))
        self.assertEqual((min(xs_mesh), max(xs_mesh)), (100_000.0, 106_000.0))

    def test_a_bare_mesh_and_a_reconstructed_shape_still_move(self):
        """FAIL CONTROL #2. The refusal hits ONLY live handles.

        A bare mesh owns no handles; nor does a shape rebuilt from an
        operation (its `ops` is empty ON PURPOSE). Both must move exactly
        as before.
        """
        with _Fresh() as program:
            shape = R.loft([(_SQUARE, 0), (_SQUARE, 3000)], name="меш")
            node = program.ops[-1]
        bare = R.move(shape["mesh"], 0, 0, 500)
        self.assertIn("vertices_mm", bare)
        self.assertEqual(bare["vertices_mm"][0][2], 500.0)
        again = R._shape_from_op(node)
        self.assertEqual(again["ops"], [])
        shifted = R.move(again, 7000, 0, 0)
        self.assertEqual(min(v[0] for v in shifted["mesh"]["vertices_mm"]),
                         7000.0)

    def test_polys_and_regions_are_untouched_by_the_refusal(self):
        """The kinds that always moved still move byte-for-byte the same way."""
        poly = {"shape": "poly", "points_mm": [[0, 0], [100, 200]]}
        self.assertEqual(R.move(poly, 5, -5)["points_mm"],
                         [[5.0, -5.0], [105.0, 195.0]])
        region = _region(_BIG, _HOLE)
        moved = R.move(region, 1000, 0)
        self.assertEqual(moved["outer"]["points_mm"][0], [1000.0, 0.0])
        self.assertEqual(moved["holes"][0]["points_mm"][0], [4000.0, 3000.0])


if __name__ == "__main__":
    unittest.main()
