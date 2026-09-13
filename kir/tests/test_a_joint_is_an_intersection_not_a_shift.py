"""A JOINT IS THE INTERSECTION OF TWO OFFSET LINES, AND THIS LAW IS ONE PER MODULE.

Audit findings `F-290` and `F-291` (29.08.2026), `kir/curveops.py`.

`F-290`. `thicken` promises "a strip of CONSTANT width around a polyline,"
but at a break it took the normal of the CHORD `prev -> next` and pushed
the vertex out by `half`. The chord is not parallel to either of the two
segments, so the vertex ended up at a distance of `half*cos(θ/2)` from each
of them:

    thicken([[0,0],[1000,0],[1000,1000]], 100)
      joint -> [1035.355, -35.355]     35.355 mm from both of its own segments
      that is, the strip "of width 100" was 70.71 wide at every break

🔴 NOT A SINGLE ACTIVE SHAPE LAW CAUGHT THIS, and that is the main point.
The vertex count is correct, the area is positive and plausible, there is
no self-intersection, `abs(_shoelace) >= 1.0` holds. There were no WIDTH
checks on the strip anywhere except the straight segment, where there is no
break by construction. The defect lived exactly in the gap between "the
straight case is checked" and "the curved case is checked by area."

The correct joint had already been written in THIS SAME file twenty lines
above — `offset` intersects offset lines. That is, the joint law had TWO
CARRIERS, and they drifted apart; it is fixed the same way as `F-190` — the
carrier is made into one (`_join`), and BOTH call it. Writing the correct
formula a second time would mean leaving in place the very mechanism that
gave birth to the defect.

`F-291`. `offset` did not check the INPUT for degeneracy, and three
consequences folded into one — an input that ought to receive a named
refusal instead became authored geometry:

    offset([[0,0],[10000,0],[5000,0.1]], 100)
      input 0.0005 m²  ->  output 2002 m², a vertex at -10 000 000 mm

Orientation is read off the SIGN of the area, and a degenerate line has no
sign: `_shoelace` gives 0.0, and "clockwise" is assigned to a shape that
has no winding at all. Law 8 (area monotonicity) is blind BY CONSTRUCTION
when `area_src == 0`: any positive result is greater than zero. And the
self-intersection detector looked only at the OUTPUT, so the figure-eight
slipped through with mutually cancelling area lobes.

WHY THE MEASURE IS "TO BOTH OF ITS OWN LINES," NOT "TO THE POLYLINE." The
obvious-seeming measure "the strip's point is at distance half from the
polyline" is green on the straight case and TURNS RED AFTER THE CORRECT
FIX: the miter's outer joint must sit at `half/cos(θ/2)` = 70.71 from the
polyline, and that is correct. It was written first and removed by the run.
The sound measure is the distance to the LINE of its own segment: that is
precisely the definition of a joint.

FAIL CONTROL was executed for each end separately; the laws have both
outcomes, and they have a green outcome on the UNFIXED tree too.
"""
from __future__ import annotations

import math
import unittest

from kir import curveops as X
from kir.diag import KirRefusal

#: Reference cases on which the output must not shift by a single bit.
ELL = [[0, 0], [6000, 0], [6000, 2000], [2000, 2000], [2000, 5000], [0, 5000]]
SQUARE = [[0, 0], [5000, 0], [5000, 4000], [0, 4000]]


def _dist_to_line(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return abs((p[0] - a[0]) * dy - (p[1] - a[1]) * dx) / math.hypot(dx, dy)


def _area_m2(ring) -> float:
    s, n = 0.0, len(ring)
    for i in range(n):
        s += ring[i][0] * ring[(i + 1) % n][1] - ring[(i + 1) % n][0] * ring[i][1]
    return abs(s / 2.0) / 1e6


def _refusal(fn) -> str:
    try:
        fn()
    except KirRefusal as exc:
        return exc.diagnostics[0].message_ru
    raise AssertionError("отказа не было — а он обязан быть")


class ПолосаШиринойW(unittest.TestCase):

    def test_every_joint_is_half_a_width_from_both_of_its_legs(self) -> None:
        """🔴 THE ONLY LAW THAT CATCHES F-290.

        The straight segment here is MANDATORY: it passes on the unfixed
        tree too, so the law does not "always go red" and was not tailored
        to the fix.
        """
        for path, w in (([[0, 0], [1000, 0], [1000, 1000]], 100),
                        ([[0, 0], [1000, 0], [1000, 1000],
                          [0, 1000], [0, 2000]], 100),
                        ([[0, 0], [5000, 0]], 200)):
            with self.subTest(path=path):
                ring = X.thicken(path, w)["points_mm"]
                n, half = len(path), w / 2.0
                self.assertEqual(len(ring), 2 * n)
                for i in range(n):
                    # ring = left + reversed(right): left[i] = ring[i],
                    # right[i] = ring[2n-1-i] — both sides of the same vertex.
                    legs = [(path[j], path[j + 1])
                            for j in (i - 1, i) if 0 <= j <= n - 2]
                    for p in (ring[i], ring[2 * n - 1 - i]):
                        for a, b in legs:
                            self.assertAlmostEqual(
                                _dist_to_line(p, a, b), half, places=6,
                                msg=f"вершина {i}, точка {p}, звено {a}->{b}")

    def test_the_mitre_tip_is_farther_from_the_polyline_and_that_is_correct(self) -> None:
        """🔴 THE OPPOSITE SIGN OF THE SAME MEASURE, and it explains why the
        measure was chosen to match the defect's subject, not for
        convenience. The outer joint of a right angle must sit at
        half/cos45° = 70.71 from the POLYLINE ITSELF: the measure
        "distance to the polyline equals half" would turn red here AFTER
        THE CORRECT FIX."""
        path = [[0, 0], [1000, 0], [1000, 1000]]
        tip = X.thicken(path, 100)["points_mm"][1]
        self.assertAlmostEqual(math.dist(tip, path[1]), 50 * math.sqrt(2),
                               places=6)

    def test_a_path_that_doubles_back_is_refused_by_direction_not_by_chord(self) -> None:
        """AN EXTENSION OF THE REFUSAL, NOT A NEW KIND. The previous
        version caught the return via the SHORT CHORD, that is, only with
        equal arms; `_join` looks at the segments' directions and catches
        it under any of them."""
        msg = _refusal(lambda: X.thicken([[0, 0], [1000, 0], [500, 0]], 10))
        self.assertIn("возвращается по себе", msg)
        self.assertIn("Следующий ход", msg)

    def test_a_straight_strip_did_not_move_a_bit(self) -> None:
        """THE MODULE'S MAIN CASE ("a strip from a line") must remain
        byte-for-byte the same: there are no breaks there."""
        self.assertEqual(X.thicken([[0, 0], [5000, 0]], 200)["points_mm"],
                         [[0.0, -100.0], [5000.0, -100.0],
                          [5000.0, 100.0], [0.0, 100.0]])


class КольцоОбязаноБытьКольцомАНеЧертой(unittest.TestCase):

    def test_a_ring_with_no_thickness_is_refused_not_offset(self) -> None:
        """Law 8 is blind ON A ZERO INPUT BY CONSTRUCTION, so a degenerate
        input must be rejected BEFORE it, not checked by it."""
        for ring in ([[0, 0], [1000, 0], [2000, 0]],          # degenerate line
                     [[0, 0], [10000, 0], [5000, 0.1]]):      # blade
            with self.subTest(ring=ring):
                msg = _refusal(lambda r=ring: X.offset(r, 100))
                self.assertIn("черта, а не контур", msg)
                self.assertIn("Следующий ход", msg)

    def test_the_threshold_is_a_length_not_an_area(self) -> None:
        """🔴 WHY "AREA > 0" IS UNFIT, BY THE NUMBER. The blade's area is
        500 mm², strictly positive — that is, an area threshold would let
        through an input that grows four million times over."""
        blade = [[0, 0], [10000, 0], [5000, 0.1]]
        self.assertGreater(_area_m2(blade), 0.0)
        self.assertIn("черта", _refusal(lambda: X.offset(blade, 100)))

    def test_a_self_intersecting_source_ring_is_refused(self) -> None:
        """A SECOND, INDEPENDENT OUTCOME. The figure-eight is deliberately
        taken with a NONZERO area: the first one written
        (`[[0,0],[1000,0],[0,1000],[1000,1000]]`) has an area of exactly 0
        and would go red BY THE FIRST law — the second would be
        green-and-unfit and would never give itself away."""
        eight = [[0, 0], [4000, 0], [0, 3000], [4000, 4000], [0, 5000]]
        self.assertAlmostEqual(_area_m2(eight), 10.0, places=6)
        msg = _refusal(lambda: X.offset(eight, 100))
        self.assertIn("самопересекается", msg)

    def test_a_legally_narrow_ring_still_offsets(self) -> None:
        """🔴 THE GREEN OUTCOME OF THE SAME LAW. A 10000x3 mm strip is
        narrow, but it is a valid contour: a thickness of 3 mm is greater
        than `_MIN_DISTANCE_MM`. Without this case the law would always go
        red and would guard nothing."""
        r = X.offset([[0, 0], [10000, 0], [10000, 3], [0, 3]], 100)
        self.assertAlmostEqual(_area_m2(r["points_mm"]), 2.0706, places=4)


class ОдинНосительЗаконаСтыка(unittest.TestCase):
    """As long as `_join` is not called by BOTH, there are still two carriers."""

    def test_offset_output_did_not_move_a_bit(self) -> None:
        """MOVING `offset` TO THE SHARED CARRIER IS INERT. The numbers were
        taken by execution BEFORE the fix and match byte-for-byte."""
        self.assertEqual(
            X.offset(ELL, 300)["points_mm"],
            [[-300.0, -300.0], [6300.0, -300.0], [6300.0, 2300.0],
             [2300.0, 2300.0], [2300.0, 5300.0], [-300.0, 5300.0]])
        self.assertEqual(
            X.offset(ELL, -300)["points_mm"],
            [[300.0, 300.0], [5700.0, 300.0], [5700.0, 1700.0],
             [1700.0, 1700.0], [1700.0, 4700.0], [300.0, 4700.0]])
        self.assertEqual(
            X.offset(SQUARE, 200)["points_mm"],
            [[-200.0, -200.0], [5200.0, -200.0], [5200.0, 4200.0],
             [-200.0, 4200.0]])

    def test_both_producers_go_through_the_same_joint(self) -> None:
        """STRUCTURALLY, NOT BY THE NUMBERS: we substitute the shared
        carrier and require that BOTH notice it. A check by result would
        not distinguish "calls the shared one" from "repeats the same
        formula locally"."""
        seen = []
        real = X._join

        def spy(*a, **kw):
            seen.append(a[4])          # field: "contour" or "path"
            return real(*a, **kw)

        X._join = spy
        try:
            X.offset(ELL, 300)
            X.thicken([[0, 0], [1000, 0], [1000, 1000]], 100)
        finally:
            X._join = real
        self.assertIn("contour", seen)
        self.assertIn("path", seen)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
