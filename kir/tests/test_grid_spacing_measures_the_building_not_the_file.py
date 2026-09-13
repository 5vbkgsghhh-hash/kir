"""GRID SPACING MUST BE A PROPERTY OF THE BUILDING, NOT OF THE FILE'S
FORMATTING.

Audit findings `F-206` and `F-207` (29.08.2026),
`kir/course/building.grid_spacings`. Two independent troubles in ONE
function, both changing the number `RECORDED["grid_mm"]`, which the
MODEL reads from the "дом" lesson.

`F-206` — ENDPOINT ORDER. Grid bunches merge direction with its reversal
(`% 180`), while the signed offset was computed from the RAW `(dx, dy)`
and flipped sign on reversal. Two horizontal grids at y=3000 and
y=6000, the second one recorded right-to-left:

    NOW [9000.0]      AFTER [3000.0]        THREEFOLD

Endpoint order is set by the Revit parsing file, not by the author. So
the number was measuring the FILE'S FORMATTING, not the building.

`F-207` — THE 0°/180° BOUNDARY. `int(round((angle % 180) / 5))` gives
0..36, but bucket 36 and bucket 0 are ONE direction under TWO keys.
Grids at +0.1° and −0.1°, spaced 3000 mm apart:

    NOW []            AFTER [2999.995]

An empty list does not mean "there are no spacings" but "we did not
compute them", and from the outside the two are indistinguishable. A
slightly rotated grid is a common case: a document's true north almost
never coincides with the project's grid axes.

🔴 THEY DO NOT COVER FOR EACH OTHER'S FAULT, AND THIS IS VERIFIED BY
EXECUTION:

    F-206   closure fix only [9000.0]      canonicalization fix only [3000.0]
    F-207   closure fix only [2999.995]    canonicalization fix only []

So both fixes are in one commit (one function, adjacent lines), but
neither counts as proof of the other.

🔴 WHY THIS FILE EXISTS AT ALL. `grid_spacings()` went to the corpus,
and all six tests in `test_building_numbers_are_current.py` SKIP on a
machine with no parses. Meaning the number the model reads was guarded
by NOTHING here, and the second half of both findings was exactly
this. The body is split into "take the grids" and "compute the
spacing" (`grid_spacings_of`), and the checks below run on SYNTHETIC
data — they go red on any machine, with or without the corpus.

AN UNFIT CHECK, NAMED EXPLICITLY: `assertEqual(grid_spacings(), [...])`
on the live corpus. It is red or green depending on the state of
SOMEONE ELSE'S machine, and here it is simply skipped — meaning it
guards nothing.
"""
from __future__ import annotations

import math
import unittest

from kir.course import building as B


def _axis(deg: float, offset: float) -> dict:
    """A grid line at angle `deg`, offset by `offset` across itself."""
    r = math.radians(deg)
    return {"p0_mm": [0.0, offset],
            "p1_mm": [10000.0 * math.cos(r), offset + 10000.0 * math.sin(r)]}


class ЧислоИзмеряетЗданиеАНеЗаписьФайла(unittest.TestCase):

    def test_the_spacing_does_not_depend_on_the_order_of_the_endpoints(self) -> None:
        """🔴 THE SUBJECT OF F-206. There is one property: THE SAME
        ANSWER on two recordings of one building. Different answers
        would mean the number measures the file's formatting."""
        same = [{"p0_mm": [0, 3000], "p1_mm": [1000, 3000]},
                {"p0_mm": [0, 6000], "p1_mm": [1000, 6000]}]
        flipped = [{"p0_mm": [0, 3000], "p1_mm": [1000, 3000]},
                   {"p0_mm": [1000, 6000], "p1_mm": [0, 6000]}]
        self.assertEqual(B.grid_spacings_of(same), B.grid_spacings_of(flipped))
        # A GREEN OUTCOME that must survive: the same endpoint order
        # gives 3000 both BEFORE the fix and after. Without it, the
        # check would amount to "the function always lies" and would
        # pass on any pair of identical answers, even two empty lists.
        self.assertEqual(B.grid_spacings_of(same), [3000.0])

    def test_the_canonisation_covers_vertical_axes_too(self) -> None:
        """The rule for picking a representative must be COMPLETE: for a
        vertical, `dx == 0`, and without the second half of the
        condition it would stay dependent on endpoint order."""
        up = [{"p0_mm": [3000, 0], "p1_mm": [3000, 1000]},
              {"p0_mm": [6000, 0], "p1_mm": [6000, 1000]}]
        down = [{"p0_mm": [3000, 0], "p1_mm": [3000, 1000]},
                {"p0_mm": [6000, 1000], "p1_mm": [6000, 0]}]
        self.assertEqual(B.grid_spacings_of(up), B.grid_spacings_of(down))
        self.assertEqual(B.grid_spacings_of(up), [3000.0])

    def test_the_side_of_the_axis_survives_the_canonisation(self) -> None:
        """🔴 WHY NOT `abs()` THE OFFSET, WITH A NUMBER. Two grids on
        OPPOSITE sides of the origin: with `abs` their offsets would
        coincide and the spacing between them would become zero,
        meaning it would drop out of the sample. Canonicalizing the sign
        of the DIRECTION preserves the side."""
        both_sides = [{"p0_mm": [0, -3000], "p1_mm": [1000, -3000]},
                      {"p0_mm": [0, 3000], "p1_mm": [1000, 3000]}]
        self.assertEqual(B.grid_spacings_of(both_sides), [6000.0])

    def test_axes_across_the_zero_boundary_land_in_one_beam(self) -> None:
        """🔴 THE SUBJECT OF F-207. 179.9° and 0.1° are one direction."""
        near_zero = B.grid_spacings_of([_axis(0.1, 3000), _axis(-0.1, 6000)])
        self.assertEqual(len(near_zero), 1)
        self.assertAlmostEqual(near_zero[0], 3000.0, delta=1.0)
        # A GREEN OUTCOME that already works TODAY: the same pair, the
        # same tolerance, but not on the boundary. Without it, the
        # check would not tell "the boundary was fixed" apart from
        # "everything got merged into one bunch".
        away = B.grid_spacings_of([_axis(10.1, 3000), _axis(9.9, 6000)])
        self.assertEqual(len(away), 1)

    def test_a_perpendicular_axis_is_still_a_different_beam(self) -> None:
        """A GREEN OUTCOME of the opposite sign: the closure fix must
        not merge 0° and 90°. Without it, the "fix" could turn out to be
        a loss of bunches."""
        self.assertEqual(
            B.grid_spacings_of([_axis(0, 3000), _axis(90, 6000)]), [])

    def test_the_number_of_beams_is_derived_from_their_width(self) -> None:
        """🔴 36 IS NOT A VALUE BUT 180/5. The link had been lost: 5
        stood in the code, 36 stood nowhere. A `36` literal would have
        left it unnamed, and it would have drifted apart at the very
        first change to the bunch width."""
        self.assertEqual(B._BEAM_COUNT, int(180.0 / B._BEAM_STEP_DEG))

    def test_the_corpus_reader_is_the_same_law_as_the_pure_one(self) -> None:
        """The split must not introduce a SECOND carrier of the law:
        `grid_spacings()` must be exactly the sum of `grid_spacings_of`
        over the buildings."""
        docs = [("a", {"grids": [{"p0_mm": [0, 3000], "p1_mm": [1000, 3000]},
                                 {"p0_mm": [1000, 6000], "p1_mm": [0, 6000]}]}),
                ("b", {"grids": [_axis(0.1, 0), _axis(-0.1, 4000)]})]
        real = B.buildings
        B.buildings = lambda: docs
        try:
            got = B.grid_spacings()
        finally:
            B.buildings = real
        expected = [x for _k, d in docs for x in B.grid_spacings_of(d["grids"])]
        self.assertEqual(got, expected)
        self.assertEqual(len(got), 2)   # a control on the denominator


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
