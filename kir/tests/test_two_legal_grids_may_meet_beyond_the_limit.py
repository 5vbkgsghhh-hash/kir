"""THE INTERSECTION OF TWO LEGAL GRIDS PRODUCED A POINT BEYOND THE COVERAGE LIMIT.

🔴 WHY (04.09.2026, audit finding FC-26, reproduced by a run).

`resolve_address` checks the ENTIRE input: the grid names were found, straight-line geometry
is present, the angle is not below `MIN_GRID_ANGLE_DEG`, `z_mm` is within coverage. The
ends of the grids themselves come from the model snapshot, meaning they are guaranteed to be within coverage. And
the checked input was enough to COMPUTE a value that nobody had
asked about: after `point = intersect(a0, a1, b0, b1)` there stood not a single check
on the coordinate limit.

MEASUREMENT BEFORE THE FIX:

    two grids at 1.1°, all four ends within ±16 000 000,
    parallel offset 400 000 mm -> x = −20 832 269 mm   ACCEPTED
    CONTROL offset 100 000 mm  -> x = −5 208 067 mm    accepted, legitimately

WHY THE ANGLE THRESHOLD DOES NOT AND SHOULD NOT CATCH THIS. `MIN_GRID_ANGLE_DEG = 1.0`
guards CONDITIONING: at 0.1° the error amplification is 573×, and the returned
point would be noise. The question here is a different one — RANGE: near-parallel grids
converge farther away the smaller the angle gets, and at a legitimate 1.1° they carry the point off
twenty kilometers. Two different questions, two different guards; one does not answer for
the other.

THE COST. The very same point, written as a LITERAL, is rejected statically
(`authoring_validation._COORD_LIMIT_MM`, also known as `registry_base.COORD_LIMIT_MM`).
Written as an address derived from grids — it went through. One value, two ways of writing it, two
verdicts — the named genus of this tree.
"""
from __future__ import annotations

import math
import unittest

from kir import registry_base, relate

ПРЕДЕЛ = registry_base.COORD_LIMIT_MM
УГОЛ = 1.1                                # above the 1.0° threshold, that is, LEGITIMATE


def _пара_осей(разнос_мм: float) -> list:
    """Two straight grids at `УГОЛ`, offset by `разнос_мм` vertically.

    All four ends deliberately lie INSIDE the coverage: the test's subject is the point,
    COMPUTED from legitimate input, not an input smuggled through the gate.
    """
    tg = math.tan(math.radians(УГОЛ))
    return [{"id": 1, "name": "A",
             "p0_mm": [-1_000_000.0, 0.0], "p1_mm": [1_000_000.0, 0.0]},
            {"id": 2, "name": "B",
             "p0_mm": [-1_000_000.0, разнос_мм - 1_000_000.0 * tg],
             "p1_mm": [1_000_000.0, разнос_мм + 1_000_000.0 * tg]}]


def _адрес(разнос_мм: float, **kw):
    diags: list = []
    точка = relate.resolve_address({"at_grid": ["A", "B"], **kw},
                                   _пара_осей(разнос_мм), "O1", "f", diags,
                                   dims=2,
                                   allow_world_offset="offset_mm" in kw)
    return точка, diags


class ЗАКОННЫЕОСИСХОДЯТСЯЗАПРЕДЕЛОМ(unittest.TestCase):

    def test_вход_законен_и_это_проверено(self):
        """The half without which the test would be proving the wrong thing.

        If the end of some grid itself lay beyond the limit, the refusal below
        would be explained by the input, and the finding would not be a finding.
        """
        for разнос in (400_000.0, 100_000.0):
            for row in _пара_осей(разнос):
                for точка in (row["p0_mm"], row["p1_mm"]):
                    for c in точка:
                        self.assertLessEqual(abs(c), ПРЕДЕЛ, row["name"])

    def test_угол_выше_порога_и_это_проверено(self):
        """The second half of the same thing: the refusal has no right to be about the angle."""
        (a0, a1), (b0, b1) = ((r["p0_mm"], r["p1_mm"])
                              for r in _пара_осей(400_000.0))
        угол = relate.line_angle_deg((a1[0] - a0[0], a1[1] - a0[1]),
                                     (b1[0] - b0[0], b1[1] - b0[1]))
        self.assertGreaterEqual(угол, relate.MIN_GRID_ANGLE_DEG)

    def test_точка_за_пределом_ОТКАЗАНА(self):
        """🔴 RED before the fix: [-20832269, 0] was returned with diags 0."""
        точка, diags = _адрес(400_000.0)
        self.assertIsNone(точка)
        self.assertEqual(len(diags), 1)
        self.assertIn("охвата модели", str(diags[0].message_ru))

    def test_КОНТРОЛЬ_FAIL_тот_же_вход_ближе_ПРОХОДИТ(self):
        """One changed condition — the offset four times smaller — and the verdict is different.

        Without this half, "refuse every intersection" would pass
        the previous test.
        """
        точка, diags = _адрес(100_000.0)
        self.assertEqual(diags, [])
        self.assertLess(abs(точка[0]), ПРЕДЕЛ)
        self.assertEqual(round(точка[0]), -5_208_067)

    def test_отказ_называет_ЧИСЛО_и_следующий_ход(self):
        """The way the neighboring refusals in the file do it."""
        _точка, diags = _адрес(400_000.0)
        текст = str(diags[0].message_ru)
        self.assertIn("-20832269", текст.replace(" ", ""),
                      "вычисленная точка обязана быть названа числом")
        self.assertIn("СЛЕДУЮЩИЙ ХОД", текст)
        self.assertEqual(diags[0].expected,
                         f"|координата| <= {ПРЕДЕЛ:.0f} мм")

    def test_мировой_отступ_меряется_ТОЙ_ЖЕ_проверкой(self):
        """The legacy form `offset_mm: [dx, dy]` moves an already-computed point.

        Checking before the offset would mean starting a second carrier of the law —
        or, worse, letting through a point that the offset carried outside. And it
        can: a world offset in the language is NOT bounded by anything except finiteness
        (`_is_pt`) — unlike a node offset, which has `MAX_OFFSET_MM`.
        """
        точка, diags = _адрес(100_000.0, offset_mm=[30_000_000.0, 0.0])
        self.assertIsNone(точка, "отступ вынес точку за предел")
        self.assertEqual(len(diags), 1)
        self.assertIn("охвата модели", str(diags[0].message_ru))
        # CONTROL: the same offset, but inward — is accepted
        точка, diags = _адрес(100_000.0, offset_mm=[1000.0, 0.0])
        self.assertEqual(diags, [])
        self.assertEqual(round(точка[0]), -5_207_067)

    def test_МУТАЦИЯ_правило_ЧИТАЕТ_предел_а_не_помнит(self):
        """The number lives in one house (`registry_base`), and this is checkable."""
        from unittest import mock
        точка, diags = _адрес(100_000.0)
        self.assertEqual(diags, [])
        self.assertGreater(abs(точка[0]), 1.0e6)
        with mock.patch.object(relate, "_COORD_LIMIT_MM", 1.0e6):
            точка, diags = _адрес(100_000.0)
            self.assertIsNone(точка)
            self.assertEqual(len(diags), 1)


if __name__ == "__main__":
    unittest.main()
