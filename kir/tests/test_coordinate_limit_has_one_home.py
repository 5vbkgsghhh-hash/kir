"""The coordinate limit is ONE quantity, and a refusal on it names a
NUMBER.

🔴 WHAT THIS FILE COST, FROM THE 25.08.2026 MEASUREMENT. Two defects, both
about the same thing.

FIRST: THREE CARRIERS, TWO VALUES.

    registry_base.COORD_LIMIT_MM        16,000,000
    authoring_validation._COORD_LIMIT_MM 16,000,000  (reads from the home
                                                        value since 25.08)
    curveops._COORD_MAX_MM              10,000,000
    mesh._COORD_MAX_MM                  10,000,000

A point at 12,000,000 mm is legal for a wall and illegal for a mesh. Both
smaller carriers derive their number from ONE source — "Revit claims it
works within 20 miles" — while the home value derives from "the working
coverage is ~16 km". Neither is measured, and so neither has authority
over the other.

`curveops` knew about the copy and said so out loud: «повторено значением
с явным указанием источника, потому что молча разойтись они не должны».
They drifted apart anyway.

SECOND: THE REFUSAL DOES NOT NAME THE LIMIT. A coordinate past the
boundary was being refused as "the wrong type":

    code     = KIR-T001
    expected = '[x,y] мм (числа)'
    got      = [99000000, 0]

The value is ALREADY a list of two numbers, meaning "convert to the form
above" is unexecutable by construction, and the number of the limit is
not named anywhere. The neighboring `relate.py` refuses the same quantity
correctly: `TYPE_BOUNDS` and a printed limit.

WHY THEY WERE UNIFIED ON THE LARGER VALUE. The home value was introduced
on 25.08 and declared the home; its value is WIDER, so no program
accepted today becomes rejected. Both numbers are derived, not measured —
so the dispute is settled by whatever does not break what already works.
When Revit's limit is MEASURED, ONE number will change.

A BOUNDARY, NAMED HONESTLY. The limit is also applied to the DIRECTION
field (`_pt_ok(dims=(3,))` on `dir_xyz`), where it is meaningless: for a
direction, only the ray matters, length does not. This is a separate
defect, NOT fixed here, and remains as a named one.
"""

from __future__ import annotations

import unittest

from kir import curveops, mesh
from kir import authoring_validation as av
from kir.compiler import compile_program
from kir.diag import TYPE_BOUNDS
from kir.registry_base import COORD_LIMIT_MM
from kir.tests.fixtures import GROUND_SNAPSHOT


class ПределОдин(unittest.TestCase):

    def test_все_носители_читают_дом(self):
        значения = {
            "registry_base.COORD_LIMIT_MM": COORD_LIMIT_MM,
            "authoring_validation._COORD_LIMIT_MM": av._COORD_LIMIT_MM,
            "curveops._COORD_MAX_MM": curveops._COORD_MAX_MM,
            "mesh._COORD_MAX_MM": mesh._COORD_MAX_MM,
        }
        разные = {и: з for и, з in значения.items() if з != COORD_LIMIT_MM}
        self.assertEqual(
            разные, {},
            f"у предела координаты несколько значений: {значения}. "
            f"Одна и та же точка законна у одного опа и незаконна у другого.")

    def test_КОНТРОЛЬ_дом_не_обнулился(self):
        """A match at zero would be green and meaningless."""
        self.assertGreater(COORD_LIMIT_MM, 1_000_000.0)


class ОтказНазываетПредел(unittest.TestCase):

    @staticmethod
    def _отказ(значение):
        программа = {"ir_version": "1.0", "ops": [{
            "op": "create_wall", "id": "w1", "p0_mm": [0, 0],
            "p1_mm": значение, "height_mm": 3000,
            "level": {"by": "name", "value": "Этаж 1"}}]}
        out = compile_program(программа, revit_version="2026",
                              snapshot=GROUND_SNAPSHOT)
        return out.diagnostics[0] if out.diagnostics else None

    def test_за_пределом_это_граница_а_не_тип(self):
        d = self._отказ([99_000_000, 0])
        self.assertIsNotNone(d, "координата за пределом принята")
        self.assertEqual(
            d.code, TYPE_BOUNDS,
            f"координата за пределом отказана как {d.code}: автору сказано "
            f"«не тот тип» про значение, которое УЖЕ нужного типа")

    def test_число_предела_напечатано(self):
        d = self._отказ([99_000_000, 0])
        весь = f"{d.message_ru or ''} {d.expected or ''}"
        self.assertIn(f"{COORD_LIMIT_MM:.0f}", весь,
                      f"предел не назван: {весь[:160]!r}")

    def test_КОНТРОЛЬ_не_тот_тип_остаётся_не_тем_типом(self):
        """The instrument must DISTINGUISH. A string instead of a point is
        a type error, and calling it a boundary violation would mean
        replacing one lie with another."""
        d = self._отказ("строка")
        self.assertIsNotNone(d)
        self.assertNotEqual(d.code, TYPE_BOUNDS)

    def test_КОНТРОЛЬ_точка_в_пределах_проезжает(self):
        d = self._отказ([4000, 0])
        self.assertIsNone(d, f"законная точка отказана: {d}")


if __name__ == "__main__":
    unittest.main()
