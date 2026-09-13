"""A WALL CROSSING A FACADE IS NOT PART OF IT (F-253).

🔴 THE WRONG THING WAS MEASURED. `_seg_ring_overlap` counted the wall's length INSIDE THE BUFFER
of the ring: `seg.intersection(ring.buffer(tol)).length`. The buffer is a two-dimensional STRIP
of width `2*tol`, so a wall crossing the facade at a RIGHT ANGLE picks up
exactly `2*tol = 600 mm` at `tol=300` and passes the threshold
`window_host_min_overlap_mm = 400`.

The threshold is SMALLER than double the tolerance — meaning ANY angle passed on length. The instrument
was blind to direction not by configuration but BY CONSTRUCTION, and raising the threshold does
not fix it: the question "at what angle is a wall still a host" would remain decided by a number
no one had measured.

THE DISCRIMINATOR IS IMPLEMENTED (reference fixture `make_good`, the bedroom's east facade replaced
by a perpendicular running through it):

    BEFORE  w_bed: verified        | room: (has_window=True,  2.5 m²)
    AFTER   w_bed: not_on_envelope | room: (has_window=False, 0.0 m²)

🔴 THE DISCRIMINATOR IS DIRECTION, AND IT NEEDS NOT A SINGLE NEW CONSTANT: both ends of a wall
must lie within `tol` of the edge's LINE. The distance is taken to the LINE, not
to the segment, so a wall TWICE AS LONG as the edge remains the host, while
a perpendicular is cut off on its own. The same technique already stands in `graph._share_a_segment`:
the instrument is new, the law is old.

🔴 WHAT THIS FILE HOLDS, AND WHAT IT DOES NOT. It holds a PROPERTY OF THE MEASURE on constructed
inputs. It does not claim the magnitude of harm on the corpus: my measurement with the real `derive`
before and after gave ZERO changed windows out of 14 700 across 31 buildings — the mechanism is real and
demonstrated, but does not fire once on the readable part of the corpus.
"""
from __future__ import annotations

import unittest

from shapely.geometry import LineString

from kir.checker.derive import _seg_ring_overlap

ДОПУСК = 300.0
ПОРОГ = 400.0


def _кольцо(*точки):
    return LineString(list(точки) + [точки[0]])


#: A square 10x10 m facade. The bottom edge runs from (0,0) to (10000,0).
ОБОЛОЧКА = _кольцо((0.0, 0.0), (10000.0, 0.0), (10000.0, 10000.0), (0.0, 10000.0))


class ПересекающаяСтенаНеХозяин(unittest.TestCase):

    def test_перпендикуляр_сквозь_фасад_НЕ_лежит_на_нём(self):
        """THE MAIN CASE. The old measure gave exactly 2*tol = 600 mm here and passed
        the 400 threshold; the new one must give zero."""
        стена = LineString([(5000.0, -500.0), (5000.0, 500.0)])
        self.assertEqual(_seg_ring_overlap(стена, [ОБОЛОЧКА], ДОПУСК), 0.0,
                         "перпендикуляр принят за часть фасада")

    def test_старая_мера_на_этом_же_входе_проходила_порог(self):
        """🔴 A MEASUREMENT INSIDE THE GUARD: showing that the case was chosen FOR THE SUBJECT,
        not for convenience. Without this, "the new one gives zero" would not prove that
        the old one gave the wrong thing."""
        стена = LineString([(5000.0, -500.0), (5000.0, 500.0)])
        старая = max(
            getattr(стена.intersection(r.buffer(ДОПУСК)), "length", 0.0)
            for r in [ОБОЛОЧКА])
        self.assertGreaterEqual(старая, ПОРОГ,
                                "случай выбран не тот: старая мера его и так "
                                "не пускала")
        self.assertAlmostEqual(старая, 2 * ДОПУСК, places=3)

    def test_ВТОРАЯ_ПОЛОВИНА_стена_НА_фасаде_остаётся_хозяином(self):
        """Without it the fix is indistinguishable from "no one is a host anymore"."""
        стена = LineString([(2000.0, 0.0), (6000.0, 0.0)])
        self.assertAlmostEqual(_seg_ring_overlap(стена, [ОБОЛОЧКА], ДОПУСК),
                               4000.0, places=3)

    def test_стена_ДЛИННЕЕ_ребра_проходит(self):
        """The distance is taken to the LINE, not the segment: a wall extending past
        the edge's ends remains collinear with it."""
        стена = LineString([(-5000.0, 0.0), (15000.0, 0.0)])
        # the overlap is clamped by the edge: the edge's full length, not the wall's length
        self.assertAlmostEqual(_seg_ring_overlap(стена, [ОБОЛОЧКА], ДОПУСК),
                               10000.0, places=3)

    def test_стена_в_пределах_допуска_но_под_углом_НЕ_хозяин(self):
        """Not only a right angle: a slant where ONE end is far from
        the line must also be cut off. Otherwise "collinearity" would be checked by the
        midpoint, not by both ends."""
        стена = LineString([(2000.0, 0.0), (6000.0, 800.0)])
        self.assertEqual(_seg_ring_overlap(стена, [ОБОЛОЧКА], ДОПУСК), 0.0)

    def test_наклон_В_ПРЕДЕЛАХ_допуска_остаётся_хозяином(self):
        """THE SECOND HALF of the previous case: the tolerance is not turned into zero. A wall with
        a 200 mm deviation at a 300 tolerance is still on the facade."""
        стена = LineString([(2000.0, 100.0), (6000.0, 200.0)])
        self.assertGreater(_seg_ring_overlap(стена, [ОБОЛОЧКА], ДОПУСК), ПОРОГ)

    def test_фасад_из_ДВУХ_коллинеарных_кусков_даёт_СУММУ(self):
        """Closing the envelope splits the facade into edges. A max instead of a sum
        would understate the overlap by half; this control did not exist in the tree."""
        кольцо = _кольцо((0.0, 0.0), (5000.0, 0.0), (10000.0, 0.0),
                         (10000.0, 10000.0), (0.0, 10000.0))
        стена = LineString([(1000.0, 0.0), (9000.0, 0.0)])
        self.assertAlmostEqual(_seg_ring_overlap(стена, [кольцо], ДОПУСК),
                               8000.0, places=3,
                               msg="перекрытие посчитано максимумом по рёбрам, "
                                   "а не суммой по стене")

    def test_вырожденная_стена_не_роняет_меру(self):
        стена = LineString([(1000.0, 0.0), (1000.0, 0.0)])
        self.assertEqual(_seg_ring_overlap(стена, [ОБОЛОЧКА], ДОПУСК), 0.0)


if __name__ == "__main__":
    unittest.main()
