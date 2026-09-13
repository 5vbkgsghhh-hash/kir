"""ONE ARC, TWO RECORDS — THERE WERE TWO VERDICTS.

🔴 WHY (2026-08-25, audit finding, reproduced by a run).

The authored `bulge` is checked against bounds: `MIN_ARC_BULGE <= |b| <=
MAX_ARC_BULGE`, otherwise a typed refusal. The `{edge, radius_mm, dir}` form
bypassed this check ENTIRELY: `radius_mm` has no upper bound at all, and the
`radius_to_bulge` result was never checked against anything.

Measurement on a 1000 mm chord:

```
radius_mm 1.0e+04 -> bulge 2.5e-02   accepted (and correct)
radius_mm 2.5e+09 -> bulge 1.0e-07   ACCEPTED, yet MIN_ARC_BULGE = 1e-6
radius_mm 1.0e+18 -> bulge 2.5e-16   ACCEPTED
```

An author who wrote `bulge: 1e-7` BY HAND got a refusal. The SAME arc, named
by radius, went through.

**The cost is not elegance.** With `_EMIT_DECIMALS = 2` three points of such
an "arc" become COLLINEAR, and `Arc.Create` throws `ArgumentException` — the
refusal comes from Revit and points at the WRONG thing: the author goes off
to look for trouble in the model, but the trouble is in the number we
accepted.
"""
from __future__ import annotations

import unittest

from kir import contour

ХОРДА = ((0.0, 0.0), (1000.0, 0.0))


def _дуга(radius: float):
    diags: list = []
    b = contour.radius_to_bulge(ХОРДА[0], ХОРДА[1], radius, True,
                                "O1", "arcs[0]", diags)
    return b, diags


class РАДИУСВСТРЕЧАЕТТУЖЕГРАНИЦУ(unittest.TestCase):

    def test_слишком_плоская_дуга_ОТКАЗАНА(self):
        """🔴 RED before the fix: all three were accepted."""
        for radius in (2.5e9, 2.5e13, 1e18):
            with self.subTest(radius=radius):
                b, diags = _дуга(radius)
                self.assertIsNone(b)
                self.assertEqual(len(diags), 1)

    def test_отказ_называет_РАДИУС_а_не_bulge(self):
        """The author wrote a radius — fix it for the radius."""
        _, diags = _дуга(2.5e9)
        текст = str(diags[0].message_ru)
        self.assertIn("радиус", текст)
        self.assertIn("хорде", текст)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", текст)
        self.assertIn("ПРЯМОЙ", текст,
                      "отказ обязан сказать, ЧЕМ это кончится в Ревите")

    def test_КОНТРОЛЬ_PASS_нормальные_дуги_проходят(self):
        """Without it, the refusal above would just mean "arcs were banned"."""
        for radius in (600.0, 1e4):
            with self.subTest(radius=radius):
                b, diags = _дуга(radius)
                self.assertEqual(diags, [])
                self.assertIsNotNone(b)
                self.assertGreaterEqual(abs(b), contour.MIN_ARC_BULGE)

    def test_радиус_меньше_полухорды_по_прежнему_ОТКАЗАН(self):
        """A fix has no right to eat a check that used to work."""
        b, diags = _дуга(400.0)
        self.assertIsNone(b)
        self.assertIn("хорды", str(diags[0].message_ru))


class ОБЕЗАПИСИСУДЯТСЯОДНИМЗАКОНОМ(unittest.TestCase):

    def test_граница_у_радиуса_ТА_ЖЕ_что_у_bulge(self):
        """MUTATION: move the bound — the radius's answer must follow it."""
        from unittest import mock
        b, diags = _дуга(2.5e9)
        self.assertIsNone(b, "на реестровой границе — отказ")
        with mock.patch.object(contour, "MIN_ARC_BULGE", 1e-9):
            b2, diags2 = _дуга(2.5e9)
        self.assertIsNotNone(b2, "правило обязано ЧИТАТЬ границу, а не помнить")
        self.assertEqual(diags2, [])


if __name__ == "__main__":
    unittest.main()
