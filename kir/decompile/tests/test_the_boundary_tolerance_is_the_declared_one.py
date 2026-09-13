"""THE BOUNDARY TOLERANCE EQUALS THE DECLARED ONE AT ANY LENGTH (F-073).

`_point_on_segment` was computing a cross product — a quantity in MM² —
and comparing it DIRECTLY against `CANON_MM`, a quantity in MM. `cross`
equals "distance along the normal × the segment's length," so the actual
tolerance came out as `CANON_MM / length` and SHRANK with the boundary's
length:

    segment    100 mm -> tolerance 0.01000 mm
    segment   1000 mm -> tolerance 0.00100 mm
    segment  10000 mm -> tolerance 0.00010 mm
    segment 100000 mm -> tolerance 0.00001 mm

🔴 On a wall 100 m long, the tolerance came out as 10 NANOMETERS — the
"point on a segment" check was degenerating into exact equality. At no
point in the range did the tolerance equal the declared one, and a point
lying on a long boundary within the canon was recognized as not lying on
it, IN SILENCE. The predicate decides room membership and group
boundaries.

🔴 ONE LENGTH PROVES NOTHING, AND THIS IS THE MAIN POINT OF THIS FILE. The
defect was not "the threshold is wrong," but "the threshold DEPENDS ON
THE LENGTH." A check on one length would go green even on a fitted
constant; here the tolerance is measured by binary search across FOUR
lengths spanning three orders of magnitude, and must come out as ONE AND
THE SAME number.

A COST MEASUREMENT ON LIVE BUILDINGS (read-only): on `bench_A` and
`sob62_r23_v6`, 746,482 "point/edge" pairs and ZERO changed decisions.
The fix is correct in direction and inert on these buildings.

Run:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_the_boundary_tolerance_is_the_declared_one.py -q
"""
from __future__ import annotations

import unittest

from kir.decompile.fold import _point_on_segment
from kir.decompile.schema import CANON_MM

#: Three orders of magnitude of length. Fewer than two, and the check is
#: not about DEPENDENCE.
_LENGTHS = (100.0, 1000.0, 10000.0, 100000.0)


def _measured_tolerance(length: float) -> float:
    """The actual tolerance along the normal — by binary search, not by reading the code."""
    low, high = 0.0, 500.0
    for _ in range(60):
        mid = (low + high) / 2.0
        if _point_on_segment((length / 2.0, mid), (0.0, 0.0), (length, 0.0)):
            low = mid
        else:
            high = mid
    return low


class TheToleranceDoesNotDependOnLength(unittest.TestCase):

    def test_every_length_measures_the_declared_tolerance(self):
        for length in _LENGTHS:
            with self.subTest(отрезок=length):
                self.assertAlmostEqual(
                    _measured_tolerance(length), CANON_MM, places=6,
                    msg=("допуск не равен объявленному: предикат снова "
                         "сравнивает мм² с мм"))

    def test_the_four_lengths_agree_with_each_other(self):
        """A separate check of DEPENDENCE: a fitted constant will not pass it.

        Each length's equality to the canon could rest on the luck of
        rounding; the lengths' equality to EACH OTHER is a direct
        assertion that "the tolerance does not depend on length" —
        exactly the property that was missing.
        """
        measured = [_measured_tolerance(length) for length in _LENGTHS]
        self.assertAlmostEqual(max(measured), min(measured), places=6,
                               msg=f"допуск гуляет с длиной: {measured}")

    def test_the_case_from_the_registry(self):
        """A point 0.5 mm from a 10 m edge — with a declared tolerance of 1 mm."""
        self.assertTrue(
            _point_on_segment((5000.0, 0.5), (0.0, 0.0), (10000.0, 0.0)))


class TheToleranceStillEnds(unittest.TestCase):
    """🔴 THE SECOND OUTCOME. Without it, the fix is indistinguishable from "accept everything"."""

    def test_a_point_beyond_the_canon_is_still_off_the_segment(self):
        for length in _LENGTHS:
            with self.subTest(отрезок=length):
                self.assertFalse(
                    _point_on_segment((length / 2.0, CANON_MM * 5.0),
                                      (0.0, 0.0), (length, 0.0)))

    def test_a_point_past_the_ends_is_still_off_the_segment(self):
        self.assertFalse(
            _point_on_segment((-50.0, 0.0), (0.0, 0.0), (100.0, 0.0)))
        self.assertFalse(
            _point_on_segment((150.0, 0.0), (0.0, 0.0), (100.0, 0.0)))


class TheDegenerateSegmentIsUnchanged(unittest.TestCase):
    """A degenerate segment is LEGAL, and changing the answer for it is
    not this class.

    Multiplication (`abs(cross) > CANON_MM * length`) was chosen over
    division for exactly this reason: at `length == 0` it gives `0 > 0`,
    i.e. EXACTLY the previous behavior, with not a single new decision.
    Division would have required a separate branch, and with it a new
    answer where no one asked for one to change.
    """

    def test_a_point_within_the_canon_is_on_a_degenerate_segment(self):
        self.assertTrue(
            _point_on_segment((0.5, 0.0), (0.0, 0.0), (0.0, 0.0)))

    def test_a_point_beyond_the_canon_is_not(self):
        self.assertFalse(
            _point_on_segment((5.0, 0.0), (0.0, 0.0), (0.0, 0.0)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
