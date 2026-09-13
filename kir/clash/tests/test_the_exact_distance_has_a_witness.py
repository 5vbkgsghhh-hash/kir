"""THE EXACT DISTANCE ENUMERATION STOOD WITHOUT A SINGLE WITNESS.

A class bought on F-136: a value can be WRONG, and nobody notices, because
above it stands an aggregator whose answer is set by a DIFFERENT summand.
There, the shield was a neighboring piece, `PrismSet`. Here it is a
neighboring ESTIMATE: SAT gives a lower bound, and it COINCIDES with the
truth every time the bodies are separated along an axis. It coincides — and
by doing so it hides `_convex_poly_distance`.

🔴 THE MEASUREMENT THIS FILE EXISTS FOR (2026-08-30). Each narrow-phase
function was broken one at a time (`-> 0.0`), and what was measured was
whether the CORPUS would notice it, and whether the SUITES would notice it.
The denominator is only pairs with a POSITIVE answer: on a pair whose answer
is already non-positive, corrupting it to zero changes nothing by law, not
by a shield.

    term                       calls    corpus did NOT notice   red tests
    _convex_poly_distance     10 371         85.4 %               0
    _seg_seg_distance_2d     164 070         85.4 %               0
    _seg_polygon_distance     13 680         67.1 %               6
    _prism_pair_sd             3 187         65.5 %              41
    poly_poly_gap              3 187         73.2 %              47
    _poly_sat_gap               8 133        60.3 %              50

The zero in the third column is not a typo. Before commit `a3f5828`,
corrupting `_convex_poly_distance` or `_seg_seg_distance_2d` to ZERO left the
entire `clash` group green: 458 passed, and the only red one was the one
already standing in BASELINE §2.1 #1. Two functions, one of which is called
164 070 times on the corpus sample, had NOT A SINGLE guard; they were held up
only by an accidentally matching SAT.

WHAT THIS FILE GUARDS. Pairs where SAT is STRICTLY LESS than the truth —
only on those does exact enumeration decide anything. The cases were picked
by ENUMERATING SHAPES, not invented: five out of twenty trials were enough
for the gap to exceed a millimeter.
"""

from __future__ import annotations

import math
import unittest

from kir.clash import geom as G


SQUARE = ((0., 0.), (10., 0.), (10., 10.), (0., 10.))


def _rotated(poly, angle, dx, dy):
    c, s = math.cos(angle), math.sin(angle)
    return tuple((x * c - y * s + dx, x * s + y * c + dy) for x, y in poly)


#: (name · rotation of the second shape · offset · SAT · truth). The numbers
#: were captured by execution, not computed by hand.
UNDERESTIMATED = (
    ("по диагонали, без поворота", 0.0, 40., 40., 30.000, 42.426),
    ("по диагонали, ближе", 0.0, 25., 25., 15.000, 21.213),
    ("поворот 30°", math.pi / 6, 40., 40., 40.981, 42.426),
    ("поворот 45°, наискось", math.pi / 4, 50., 15., 32.929, 35.072),
    ("поворот 60°, наискось", math.pi / 3, 50., 15., 31.340, 32.896),
)


class ТочныйПереборЕдинственныйСвидетельИстины(unittest.TestCase):

    def test_the_sat_is_only_a_lower_bound_here(self):
        """First it is proven that the case IS ON TOPIC: SAT must be
        STRICTLY less than the truth, otherwise the check below is green by
        construction and guards nothing."""
        for name, angle, dx, dy, sat, exact in UNDERESTIMATED:
            with self.subTest(name=name):
                b = _rotated(SQUARE, angle, dx, dy)
                self.assertAlmostEqual(G._poly_sat_gap(SQUARE, b), sat,
                                       places=3)
                self.assertGreater(exact - sat, 1.0,
                                   "разрыв меньше миллиметра — случай не о том")

    def test_the_answer_is_the_exact_distance_not_the_bound(self):
        """🔴 THE HEART OF THE FILE. Break `_convex_poly_distance` — and the
        answer drops to the SAT estimate. Before this file, that drop did
        not turn NOT A SINGLE test red."""
        for name, angle, dx, dy, sat, exact in UNDERESTIMATED:
            with self.subTest(name=name):
                b = _rotated(SQUARE, angle, dx, dy)
                self.assertAlmostEqual(G.poly_poly_gap(SQUARE, b), exact,
                                       places=3)

    def test_the_same_holds_through_the_whole_path(self):
        """THE WHOLE PATH, not a helper: footprints -> prisms -> signed
        distance. Checking `poly_poly_gap` alone would prove that the
        function is capable, not that the correct number reaches the
        verdict."""
        b = _rotated(SQUARE, 0.0, 40., 40.)
        pa = G.Prism(SQUARE, 0., 100.)
        pb = G.Prism(b, 0., 100.)
        self.assertAlmostEqual(G.signed_distance(pa, pb), 42.426, places=3)

    def test_a_pair_separated_along_an_axis_still_agrees(self):
        """🔴 THE SECOND OUTCOME. Where SAT IS EXACT, the answer must stay
        the same: the file guards exact enumeration, it does not require it
        to always be the decider. Without this pair, a fix of "always call
        the enumeration and ignore SAT" would have passed the checks
        above."""
        b = tuple((x + 40., y) for x, y in SQUARE)
        self.assertAlmostEqual(G._poly_sat_gap(SQUARE, b), 30.0, places=6)
        self.assertAlmostEqual(G.poly_poly_gap(SQUARE, b), 30.0, places=6)

    def test_a_segment_against_a_polygon_keeps_its_exact_distance(self):
        """`_seg_polygon_distance` — the same row: shielded 67.1 % of the
        time and turns six tests red, all six about something ELSE
        (capsules, golden, section). Its NUMBER had no direct witness."""
        segment = ((0., 0., 0.), (0., 0., 10.))
        prism = G.Prism(_rotated(SQUARE, math.pi / 4, 40., 40.), 0., 10.)
        got = G.signed_distance(G.Capsule(segment, 1.0), prism)
        self.assertGreater(got, 0.0)
        self.assertAlmostEqual(
            got, G.signed_distance(G.Capsule(segment, 0.0), prism) - 1.0,
            places=6, msg="радиус капсулы обязан вычитаться ровно один раз")


if __name__ == "__main__":
    unittest.main()
