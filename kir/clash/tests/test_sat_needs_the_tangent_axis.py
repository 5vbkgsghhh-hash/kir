"""SAT IS A THEOREM ABOUT FULL-DIMENSIONAL POLYGONS, AND FOOTPRINTS CAN BE DEGENERATE.

`poly_poly_gap` declares: "SAT solves the QUESTION OF SIGN (separated or
not) — that is exactly what makes it a theorem." The theorem holds as long as
both polygons are FULL-DIMENSIONAL: they have enough edge normals for a
separating axis to be found. A degenerate footprint (a segment, a point) is
legitimate and is NOT discarded — `PrismSet` states this directly, because a
discarded piece SHRINKS the hull — but it only gives out half of the axes: the
perpendicular ones. The separating axis of two collinear segments lies ALONG
them, and it was not in the list.

Outcome: two segments on the same line with a 200 mm gap gave a SAT gap of
`0.0`, `poly_poly_gap` saw `best <= 0` and returned zero without reaching the
exact exhaustive search — which, when called, answers the correct 200.0. Next,
`relation_of(0)` gives `contact`, and CONTACT ends up in the report where there
is empty space.

🔴 WHAT WAS MEASURED ON THE CORPUS (30.08.2026, 68 decompiles, read-only), so
that the next reader does not mistake this file for a fix of a frequent case:
    collinear segment pairs from DIFFERENT bodies          2609
    of them separated along their own line                 779
    🔴 FALSE ZEROS of `poly_poly_gap`                       40   <- mechanism CAUGHT
    of them with Z-overlap (hypot does not cancel it)       14
    🔴 FALSE CONTACTS IN THE VERDICT                         0
The zero in the last line is explained, not left a mystery: for `PrismSet` the
signed distance is the MINIMUM over pairs of pieces, and in all fourteen cases
the minimum was set by a DIFFERENT pair with a genuine overlap of
−1100…−2350 mm. That is, the only thing blocking the false zero is a
neighboring piece that happened to be closer. This file fixes the MECHANISM,
not the caught incident.
"""

from __future__ import annotations

import unittest

from kir.clash import detect as D
from kir.clash import geom as G


class ВырожденнаяПодошваОтдавалаПоловинуОсей(unittest.TestCase):

    def test_collinear_segments_with_a_gap_are_separated(self):
        """The subject of the finding."""
        self.assertAlmostEqual(
            G.poly_poly_gap(((0., 0.), (100., 0.)), ((300., 0.), (400., 0.))),
            200.0, places=6)

    def test_the_prism_pair_is_no_longer_called_a_contact(self):
        """The same case ALONG THE WHOLE PATH: footprints -> prisms -> signed
        distance -> relation. Testing `poly_poly_gap` alone would prove that
        the helper is capable, not that the correct number reaches the
        verdict."""
        a = G.Prism(((0., 0.), (100., 0.)), 0., 1000.)
        b = G.Prism(((300., 0.), (400., 0.)), 0., 1000.)
        distance = G.signed_distance(a, b)
        self.assertAlmostEqual(distance, 200.0, places=6)
        self.assertEqual(D.relation_of(distance), "separated")

    def test_overlapping_collinear_segments_stay_at_zero(self):
        """🔴 THE SECOND OUTCOME, AND IT IS MORE VALUABLE THAN THE FIRST.
        Collinear segments that OVERLAP are required to give zero even after
        the fix: for zero-area figures the penetration depth is genuinely
        zero. Making them "separated" would create a MISSED clash — a defect
        worse than the original one."""
        self.assertAlmostEqual(
            G.poly_poly_gap(((0., 0.), (100., 0.)), ((50., 0.), (400., 0.))),
            0.0, places=6)

    def test_full_dimensional_answers_do_not_move(self):
        """🔴 THE SECOND OUTCOME. The fix touches exactly the case where SAT
        stops being a theorem, and touches none where it remains one. Without
        these four lines a fix that breaks the full-dimensional case would
        have passed the checks above."""
        square = ((0., 0.), (10., 0.), (10., 10.), (0., 10.))
        cases = (
            ("параллельные отрезки, 50 по Y",
             ((0., 0.), (100., 0.)), ((0., 50.), (100., 50.)), 50.0),
            ("два квадрата, разрыв 30",
             square, ((40., 0.), (50., 0.), (50., 10.), (40., 10.)), 30.0),
            ("два квадрата, перекрытие 4",
             square, ((6., 0.), (16., 0.), (16., 10.), (6., 10.)), -4.0),
            ("квадрат и точка внутри", square, ((5., 5.),), -5.0),
        )
        for name, a, b, want in cases:
            with self.subTest(name=name):
                self.assertAlmostEqual(G.poly_poly_gap(a, b), want, places=6)

    def test_the_axis_list_carries_both_normal_and_tangent(self):
        """Directly about the subject: every edge has TWO axes, and they are
        perpendicular. A check on the number of axes would catch a count;
        here what is checked is that the added axis is specifically the
        TANGENT one."""
        axes = G._poly_axes(((0., 0.), (100., 0.)))
        self.assertEqual(len(axes), 4)          # two winding directions × two axes
        for axis in axes:
            self.assertAlmostEqual(axis[0] ** 2 + axis[1] ** 2, 1.0, places=9)
        self.assertTrue(any(abs(x) > 0.99 for x, _ in axes),
                        "касательной оси (вдоль отрезка) нет: %r" % (axes,))
        self.assertTrue(any(abs(y) > 0.99 for _, y in axes),
                        "нормали (поперёк отрезка) нет: %r" % (axes,))

    def test_the_exact_sweep_still_earns_its_place(self):
        """🔴 THE BOUNDARY OF THE FIX FROM THE OTHER SIDE. The tangent axis
        fixes the SIGN, not the MAGNITUDE: for squares separated DIAGONALLY,
        SAT gives 30.0, while the true distance is 42.426 — it is delivered
        by the exact exhaustive search, and that search is required to stay.
        Without this pair, a control that "removes the exact exhaustive
        search" would be an IDENTITY: SAT computes all the other cases in the
        file exactly, and removing the exhaustive search would have passed
        unnoticed."""
        square = ((0., 0.), (10., 0.), (10., 10.), (0., 10.))
        diagonal = ((40., 40.), (50., 40.), (50., 50.), (40., 50.))
        self.assertAlmostEqual(G._poly_sat_gap(square, diagonal), 30.0,
                               places=6)
        self.assertAlmostEqual(G.poly_poly_gap(square, diagonal), 42.4264,
                               places=3)

    def test_the_sat_alone_already_knows_the_gap(self):
        """🔴 THE MISSING AXIS IS FIXED, NOT MASKED BY THE EXACT EXHAUSTIVE
        SEARCH. For collinear segments SAT is EXACT along the tangent axis,
        and `_poly_sat_gap` is required to give 200.0 ON ITS OWN, before
        `_convex_poly_distance` even runs. Without this check a fix that
        "always calls the exact exhaustive search" would pass all the
        others."""
        self.assertAlmostEqual(
            G._poly_sat_gap(((0., 0.), (100., 0.)), ((300., 0.), (400., 0.))),
            200.0, places=6)


class ЖИВАЯПАРАИЗКОРПУСА(unittest.TestCase):
    """🔴 THE SHAPE IS TAKEN FROM A REAL BUILDING, NOT INVENTED.

    `snowdon_plumb_v5`, elements 1501152 and 2115674 — both `OST_Floors`. Both
    footprints are degenerate into a segment and lie on the same vertical
    line x = −6054.725; the gap along it is 1819.275 mm. Before the fix
    `poly_poly_gap` answered −0.0000.

    The first point is duplicated — that is how the sweep delivers it, and it
    is left as is: a cleaned-up shape would be testing something other than
    what actually arrives.

    The verdict on the BODIES for this pair did not flip even before the fix
    (the bodies are separated along Z, `hypot` cancelled the false zero) —
    which is why what stands here is specifically the pair of FOOTPRINTS, and
    the claim is made about that, not about a finding in the report.
    """

    A = ((-6054.725, -8658.225), (-6054.725, -8658.225), (-6054.725, 971.55))
    B = ((-6054.725, 2790.825), (-6054.725, 2790.825), (-6054.725, 12725.4))

    def test_the_real_pair_is_separated_by_its_real_gap(self):
        self.assertAlmostEqual(G.poly_poly_gap(self.A, self.B),
                               1819.275, places=3)

    def test_the_same_pair_moved_to_touch_still_reads_zero(self):
        """The same live segment, shifted to TOUCH exactly: zero is required
        to stay zero. Without this pair the previous check would not
        distinguish the fix from a change that "always returns a positive
        number"."""
        touching = tuple((x, y - 1819.275) for x, y in self.B)
        self.assertAlmostEqual(G.poly_poly_gap(self.A, touching), 0.0,
                               places=6)


if __name__ == "__main__":
    unittest.main()
