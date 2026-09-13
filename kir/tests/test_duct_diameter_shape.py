"""An absent parameter and a mismatched value are DIFFERENT refusals.

A LIVE MEASUREMENT on 30.07 on the Snowdon Towers Sample Plumbing sample.
``create_duct`` with ``diameter_mm`` on the "Mitered Elbows / Tees" type built
the duct, the witness said «D1: diameter mismatch», and the transaction
rolled back. The rollback was HONEST, but the diagnosis was not: a
rectangular duct has no diameter parameter at all. A model reading
"mismatch" would go hunting for a number, when what needs fixing is the
intent: a rectangular cross-section has width and height, not a diameter.

Confirmed by refutation: the same op WITHOUT ``diameter_mm`` builds (id
1738961).

The cross-section's shape is not in the grounding pool, so there is nothing
to refuse on at compile time — the only place it is known is at execution.
So the test does not guard "the op refuses" but that the refusal
DISTINGUISHES the two cases: the parameter is absent, and the parameter is
present but has a different value.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT


def _duct(**extra) -> dict:
    op = {"op": "create_duct", "id": "D1",
          "p0_mm": [0, 0, 3000], "p1_mm": [8000, 0, 3000],
          "level": {"by": "element_id", "value": 42}}
    op.update(extra)
    return {"ir_version": "1.0", "ops": [op]}


def _route_duct(**extra) -> dict:
    op = {
        "op": "route_duct_system",
        "id": "RD",
        "nodes": [
            {"id": "a", "xyz_mm": [0, 0, 3000]},
            {"id": "b", "xyz_mm": [8000, 0, 3000]},
        ],
        "segments": [{"from": "a", "to": "b"}],
        "level": {"by": "element_id", "value": 42},
    }
    op.update(extra)
    return {"ir_version": "1.0", "ops": [op]}


class DiameterRefusalTests(unittest.TestCase):

    def _emit(self, program: dict) -> str:
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, getattr(out, "diagnostics", None))
        return out.csharp

    def test_absent_parameter_names_the_cross_section(self) -> None:
        """An absent parameter must say WHY it is absent."""
        code = self._emit(_duct(diameter_mm=200))
        self.assertIn("__dp == null", code)
        self.assertIn("сечение не круглое", code)
        self.assertIn("нет параметра диаметра", code)

    def test_a_wrong_value_stays_a_plain_mismatch(self) -> None:
        """A value mismatch is the old refusal, with no story about the cross-section."""
        code = self._emit(_duct(diameter_mm=200))
        tail = code.split("сечение не круглое")[1]
        self.assertIn("else if (Math.Abs(", tail)
        self.assertIn("diameter mismatch", tail)

    def test_the_two_cases_are_separate_branches(self) -> None:
        """One `if` for both cases is exactly the lost diagnosis."""
        code = self._emit(_duct(diameter_mm=200))
        self.assertNotIn("__dp == null || Math.Abs(", code)

    def test_without_a_diameter_no_check_is_emitted_at_all(self) -> None:
        """No diameter was asked for — nothing to check against: absence stays absence."""
        code = self._emit(_duct())
        self.assertNotIn("RBS_CURVE_DIAMETER_PARAM", code)


class RouteDiameterRefusalTests(DiameterRefusalTests):
    """The graph-shaped duct path must preserve the same diagnosis."""

    def test_absent_parameter_names_the_cross_section(self) -> None:
        code = self._emit(_route_duct(diameter_mm=200))
        self.assertIn("__dp == null", code)
        self.assertIn("сечение не круглое", code)
        self.assertIn("нет параметра диаметра", code)

    def test_a_wrong_value_stays_a_plain_mismatch(self) -> None:
        code = self._emit(_route_duct(diameter_mm=200))
        tail = code.split("сечение не круглое")[1]
        self.assertIn("else if (Math.Abs(", tail)
        self.assertIn("segment 0 diameter (semantic)", tail)

    def test_the_two_cases_are_separate_branches(self) -> None:
        code = self._emit(_route_duct(diameter_mm=200))
        self.assertNotIn("__dp == null || Math.Abs(", code)

    def test_without_a_diameter_no_check_is_emitted_at_all(self) -> None:
        code = self._emit(_route_duct())
        self.assertNotIn("RBS_CURVE_DIAMETER_PARAM", code)


if __name__ == "__main__":
    unittest.main()
