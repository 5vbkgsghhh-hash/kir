"""OFFSETTING AND THICKENING A CONTOUR — laws, refusals, and arithmetic.

WHY THIS FILE EXISTS. `curveops.offset`/`thicken` are value constructors
in the AUTHOR's Python, meaning code that calls not the compiler but the
model. They must be checked as language: not "the function returned a
dict," but "the area came out to THIS" and "on degeneration a named
refusal arrived, not some other shape."

🔴 THIS FILE HAS ALREADY PAID FOR TWO DEFECTS, BOTH ON THE VERY FIRST RUN
WITH NUMBERS:

* **an inversion was passing through.** The check stood on the SIGN of the
  winding (`shoelace * sign <= 0`), but a 5000×4000 square offset inward
  by 5000 PRESERVES the sign: both sides flipped direction, a double
  reflection. The result was 30.000 m² instead of the original 20.000, and
  the check was green. The fix is area monotonicity, pinned below from
  both sides;
* **a strip made from a SEGMENT was refused.** Parsing points always
  demanded three, because it was written for a ring — and it rejected
  exactly the case `thicken` was set up for ("a strip from a line").

Both were found not by reasoning but by a run with a NUMBER next to it:
5000×200 must give 1.000 m², and that is visible at a glance.
"""
from __future__ import annotations

import unittest

from kir import curveops as X
from kir.diag import KirRefusal

SQUARE = [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]
#: An L-shaped contour with a CONCAVE angle — where "shift each edge on
#: its own" gives the wrong vertex, while intersecting the shifted lines
#: gives the right one.
ELL = [[0, 0], [6000, 0], [6000, 2000], [2000, 2000], [2000, 5000], [0, 5000]]


def _area_m2(pts) -> float:
    s = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return abs(s / 2.0) / 1e6


class TheArithmeticIsExact(unittest.TestCase):
    """A number alongside it is the only thing that tells actual work
    apart from plausibility."""

    def test_outward_offset_grows_by_the_exact_amount(self) -> None:
        # 5000×4000 outward by 300 -> 5600×4600
        r = X.offset(SQUARE, 300)
        self.assertAlmostEqual(_area_m2(r["points_mm"]), 5.6 * 4.6, places=6)

    def test_inward_offset_shrinks_by_the_exact_amount(self) -> None:
        # -> 4400×3400
        r = X.offset(SQUARE, -300)
        self.assertAlmostEqual(_area_m2(r["points_mm"]), 4.4 * 3.4, places=6)

    def test_a_strip_from_a_single_segment(self) -> None:
        """THE MAIN case: a strip from a line. 5000 long × 200 wide."""
        r = X.thicken([[0, 0], [5000, 0]], 200)
        self.assertEqual(len(r["points_mm"]), 4)
        self.assertAlmostEqual(_area_m2(r["points_mm"]), 1.0, places=6)

    def test_the_result_is_a_poly_shape_ready_for_any_contour_op(self) -> None:
        """The point of the constructor is that the result gets fed onward."""
        for r in (X.offset(SQUARE, 300), X.thicken([[0, 0], [5000, 0]], 200)):
            self.assertEqual(r["shape"], "poly")
            self.assertEqual(set(r), {"shape", "points_mm"})


class TheVertexIsIntersectedNotShifted(unittest.TestCase):
    """At a concave angle, "shift each edge" gives the WRONG vertex.

    This is the constructor's entire value: shifting edges one by one by
    hand is exactly what gives the author a gap at a concave angle.
    """

    def test_a_concave_contour_keeps_its_vertex_count(self) -> None:
        self.assertAlmostEqual(_area_m2(ELL), 18.0, places=6)
        for d in (300, -300):
            with self.subTest(d=d):
                r = X.offset(ELL, d)
                self.assertEqual(len(r["points_mm"]), len(ELL))

    def test_inward_shrinks_and_outward_grows_on_a_concave_contour(self) -> None:
        self.assertLess(_area_m2(X.offset(ELL, -300)["points_mm"]), 18.0)
        self.assertGreater(_area_m2(X.offset(ELL, 300)["points_mm"]), 18.0)

    def test_the_direction_does_not_depend_on_the_order_of_points(self) -> None:
        """"Outward" is decided by the SIGN OF THE AREA, not by the order
        the author typed the points in.

        Otherwise the author would have to remember whether they wrote
        clockwise or counterclockwise — and the same `+300` would produce
        different shapes.
        """
        ccw = _area_m2(X.offset(SQUARE, 300)["points_mm"])
        cw = _area_m2(X.offset(list(reversed(SQUARE)), 300)["points_mm"])
        self.assertAlmostEqual(ccw, cw, places=6)


class DegeneracyIsRefusedNotSilentlyReshaped(unittest.TestCase):
    """A silent substitution of shape is indistinguishable from success on
    the outside."""

    def _refusal(self, fn) -> str:
        with self.assertRaises(KirRefusal) as ctx:
            fn()
        diags = ctx.exception.diagnostics
        self.assertTrue(diags, "отказ обязан нести причину")
        return diags[0].message_ru

    def test_a_collapsed_edge_names_its_index(self) -> None:
        msg = self._refusal(lambda: X.offset(SQUARE, -2000))
        self.assertIn("схлопнуло ребро", msg)
        self.assertIn("Следующий ход", msg)

    def test_eversion_is_caught_by_area_not_by_winding(self) -> None:
        """🔴 A REGRESSION THAT ALREADY HAPPENED ONCE.

        The winding sign does not work here: both sides change direction,
        the reflection is doubled, the orientation survives. The first
        edition let this through and handed back 30.000 m² instead of
        20.000.
        """
        for d in (-5000, -9999):
            with self.subTest(d=d):
                msg = self._refusal(lambda: X.offset(SQUARE, d))
                self.assertIn("не уменьшило площадь", msg)

    def test_a_strip_that_folds_over_itself_refuses(self) -> None:
        msg = self._refusal(lambda: X.thicken([[0, 0], [300, 0], [300, 300]], 4000))
        self.assertIn("самопересекается", msg)

    def test_an_arc_refuses_rather_than_becoming_a_chord(self) -> None:
        """A chord and an arc share THE SAME endpoints — a substitution
        would be invisible."""
        msg = self._refusal(lambda: X.offset(
            {"shape": "poly", "points_mm": SQUARE,
             "arcs": [{"edge": 0, "bulge": 0.3}]}, 300))
        self.assertIn("дуги", msg)
        self.assertIn("Следующий ход", msg)

    def test_a_spline_refuses_by_the_same_law(self) -> None:
        """A second carrier of the same class — to be searched for within
        the same pass."""
        msg = self._refusal(lambda: X.offset(
            {"shape": "poly", "points_mm": SQUARE,
             "splines": [{"edge": 0, "via_mm": [[2500, 500]]}]}, 300))
        self.assertIn("сплайны", msg)

    def test_a_distance_below_the_tolerance_refuses(self) -> None:
        msg = self._refusal(lambda: X.offset(SQUARE, 0.5))
        self.assertIn("ShortCurveTolerance", msg)

    def test_a_non_poly_shape_refuses_with_the_reason(self) -> None:
        msg = self._refusal(lambda: X.offset(
            {"shape": "rect", "origin": [0, 0], "size_mm": [1000, 1000]}, 300))
        self.assertTrue(msg)

    def test_a_ring_needs_three_points_and_a_path_needs_two(self) -> None:
        """Two DIFFERENT minimums, and merging them was the defect."""
        self.assertIn("нужно от 3", self._refusal(
            lambda: X.offset([[0, 0], [1000, 0]], 300)))
        self.assertIn("нужно от 2", self._refusal(
            lambda: X.thicken([[0, 0]], 200)))


class NothingIsSilentlyRepaired(unittest.TestCase):
    """The standard of honesty is `mesh.py`: not one silent fix-up of the input."""

    def test_a_zero_length_edge_refuses_instead_of_being_skipped(self) -> None:
        with self.assertRaises(KirRefusal):
            X.offset([[0, 0], [0.2, 0], [5000, 0], [5000, 4000], [0, 4000]], 300)

    def test_a_coordinate_outside_the_workspace_refuses(self) -> None:
        with self.assertRaises(KirRefusal):
            X.offset([[0, 0], [5000, 0], [5000, 99_000_000]], 300)

    def test_an_unknown_field_refuses_rather_than_being_ignored(self) -> None:
        with self.assertRaises(KirRefusal):
            X.offset({"shape": "poly", "points_mm": SQUARE, "radius": 3}, 300)


class TheModuleKnowsWhatItIsNot(unittest.TestCase):
    """A capability whose cost isn't named reads as complete."""

    def test_the_header_names_what_revit_does_better(self) -> None:
        doc = X.__doc__ or ""
        for word in ("collapse", "the arc", "THE COST"):
            self.assertIn(word, doc)

    def test_the_header_says_the_result_carries_no_bim_meaning(self) -> None:
        for boundary in ("SHAPE, not an element", "no type", "no material", "no specification"):
            self.assertIn(boundary, X.__doc__ or "")


if __name__ == "__main__":
    unittest.main()
