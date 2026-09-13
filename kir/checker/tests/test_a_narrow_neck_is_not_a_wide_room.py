"""A NARROW NECK DOES NOT MAKE A ROOM WIDE.

WHAT HAPPENED (29.08.2026, audit finding F-346, P0). `_min_width_mm`
declared: "the polygon of the true minimum width w erodes to nothing at exactly an offset of
w/2." This is true for CONVEX shapes and false for concave ones, and rooms are concave
all the time. For a dumbbell the neck disappears early, the LOBES remain, and the erosion
continues until the larger lobe disappears:

    a room made of two 4000 squares joined by a 500 mm neck
    -> width 3999.999999996 mm

that is, HAB021 certified an impassable passage as a room four
meters wide. What was measured was not the minimum cross-section but the diameter of the
largest inscribed circle — a quantity that coincides with it only in the convex case.

WHAT THIS FILE GUARDS: five shapes with a MANUALLY COMPUTED truth, including the
one where the measure STILL LIES. The last one stands here on purpose, expecting
a wrong number: a remainder recorded only in prose stops existing within a
week, while one recorded as a NUMBER turns red as soon as it is fixed, and
forces both the number and the statement to be updated.
"""
from __future__ import annotations

import unittest

from kir.checker.rules.dimensions import _min_width_mm

КВАДРАТ = [(0, 0), (4000, 0), (4000, 4000), (0, 4000)]
ПОЛОСА = [(0, 0), (8000, 0), (8000, 2000), (0, 2000)]
ГАНТЕЛЬ = [(0, 0), (4000, 0), (4000, 1750), (6000, 1750), (6000, 0),
           (10000, 0), (10000, 4000), (6000, 4000), (6000, 2250),
           (4000, 2250), (4000, 4000), (0, 4000)]
H_ФОРМА = [(0, 0), (2000, 0), (2000, 1600), (5000, 1600), (5000, 0),
           (7000, 0), (7000, 6000), (5000, 6000), (5000, 2400),
           (2000, 2400), (2000, 6000), (0, 6000)]
Г_ФОРМА = [(0, 0), (6000, 0), (6000, 2000), (2000, 2000), (2000, 6000),
           (0, 6000)]


class ANarrowNeckIsNotAWideRoom(unittest.TestCase):

    def test_a_convex_room_is_unchanged(self) -> None:
        """The fix has no right to shift the convex case: there, connectivity
        never sets in, and the answer must stay the same."""
        self.assertAlmostEqual(_min_width_mm(КВАДРАТ), 4000.0, delta=1.0)
        self.assertAlmostEqual(_min_width_mm(ПОЛОСА), 2000.0, delta=1.0)

    def test_the_dumbbell_neck_is_measured_not_the_lobe(self) -> None:
        """THE EXACT SAME DEFECT, a verbatim entry from the audit journal."""
        self.assertAlmostEqual(
            _min_width_mm(ГАНТЕЛЬ), 500.0, delta=1.0,
            msg="перешеек 500 мм подан как ширина доли — правило удостоверит "
                "непроходимый проход")

    def test_the_h_bar_is_measured_not_the_uprights(self) -> None:
        self.assertAlmostEqual(_min_width_mm(H_ФОРМА), 800.0, delta=1.0)

    def test_the_fat_corner_is_still_wrong_and_that_is_recorded(self) -> None:
        """🔴 A NAMED REMAINDER, NOT A FORGOTTEN CASE (audit registry `E-16`).

        For an L-shaped room with 2000 mm arms, the largest inscribed circle
        sits IN THE CORNER and has a diameter of 2343 mm: diagonally the shape is thicker than
        the arm. The erosion does not break here — the corner erodes last —
        and the measure overstates the arm's width by 17%.

        The test expects a WRONG number ON PURPOSE. When the measure becomes correct (that is
        a different wave — by the medial axis), it will turn red and force an update
        of both the number and the statement. A remainder recorded only in prose
        stops existing within a week.
        """
        self.assertAlmostEqual(
            _min_width_mm(Г_ФОРМА), 2343.1, delta=1.0,
            msg="если здесь стало 2000 — мера ПОЧИНЕНА до срединной оси: "
                "обнови этот тест, докстроку `_min_width_mm` и закрой E-16")

    def test_a_malformed_boundary_is_not_a_width_violation(self) -> None:
        self.assertIsNone(_min_width_mm([(0, 0), (1, 1)]))
        self.assertIsNone(_min_width_mm([(0, 0), (1, 0), (2, 0)]))


if __name__ == "__main__":
    unittest.main()
