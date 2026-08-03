"""A column could only ever come out vertical.

``create_column`` took a single plan point, and the point overload of
``NewFamilyInstance`` builds a vertical column -- there is no argument that
could tilt it. Revit models a slanted column as a location CURVE from base to
top, so expressing one means switching overloads, not setting a parameter.

The extractor has read ``SLANTED_COLUMN_TYPE_PARAM`` all along: the reading
half was built and the writing half was not, which is the pattern the
2026-07-25 review found in ten subsystems.
"""

from __future__ import annotations

import unittest

from kukai.ir import spec
from kukai.ir.compiler import compile_program
from kukai.ir.diag import KirRefusal
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


def _column(**extra):
    op = {"op": "create_column", "id": "C1", "xy": [0, 0],
          "level": {"by": "name", "value": "Этаж 1"}}
    op.update(extra)
    return {"ir_version": "1.0", "intent": "test", "ops": [op]}


_TOP_LEVEL = {"by": "name", "value": "Этаж 2"}


class TheColumnOpCanExpressASlant(unittest.TestCase):
    def setUp(self):
        self.param = next((p for p in spec.OPS["create_column"].params
                           if p.name == "top_xy"), None)

    def test_create_column_has_a_top_xy(self):
        self.assertIsNotNone(
            self.param, "create_column cannot tilt: it takes one plan point")

    def test_it_is_a_plan_point_and_optional(self):
        self.assertEqual(self.param.kind, "pt_xy")
        self.assertFalse(self.param.required)
        self.assertIsNone(self.param.default)


class TheEmittedCode(unittest.TestCase):
    def _csharp(self, program):
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        return out.csharp

    def test_a_plain_column_still_uses_the_point_overload(self):
        # Byte-stability: every column authored before top_xy existed must
        # emit the identical C#.
        code = self._csharp(_column())

        self.assertIn("NewFamilyInstance(P(0, 0, 0)", code)
        self.assertNotIn("Line.CreateBound", code)

    def test_a_slanted_column_is_built_from_a_line(self):
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL))

        self.assertIn("Line.CreateBound", code)
        self.assertIn("NewFamilyInstance(__axis_C1", code)

    def test_the_line_spans_the_two_levels_own_elevations(self):
        # Level.Elevation is already in feet while the plan coords come from
        # P(), which converts mm. Mixing them up would put the column
        # somewhere plausible and wrong.
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL))

        self.assertIn("__lv_C1.Elevation", code)
        self.assertIn("__ctl_C1.Elevation", code)

    def test_offsets_move_the_ends_of_the_axis(self):
        code = self._csharp(_column(
            top_xy=[1000, 500], top_level=_TOP_LEVEL,
            base_offset_mm=300, top_offset_mm=-200))

        self.assertIn("__lv_C1.Elevation + U(300.0)", code)
        self.assertIn("__ctl_C1.Elevation + U(-200.0)", code)

    def test_the_top_level_parameter_is_neither_written_nor_demanded(self):
        # The curve already defines the top, so writing FAMILY_TOP_LEVEL_PARAM
        # would fight the geometry -- and DEMANDING it back in the witness
        # would roll every slanted column back for a parameter nobody set.
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL))

        self.assertNotIn("FAMILY_TOP_LEVEL_PARAM", code)
        self.assertNotIn("top constraint mismatch", code)

    def test_the_axis_ends_are_checked_against_the_level_elevations(self):
        # Without this the "slant" is only a plan claim: a column could span
        # the wrong storeys and still satisfy both plan ends.
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL))

        self.assertIn("ось колонны не по уровням (geometry)", code)

    def test_a_vertical_column_still_writes_its_top_constraint(self):
        code = self._csharp(_column(top_level=_TOP_LEVEL))

        self.assertIn("FAMILY_TOP_LEVEL_PARAM", code)


class TheWitness(unittest.TestCase):
    def _csharp(self, program):
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        return out.csharp

    def test_it_reads_the_curve_not_the_point(self):
        # A slanted column has no LocationPoint at all, so the inherited
        # check would have reported "нет LocationPoint" for every one.
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL))

        self.assertIn("Location as LocationCurve", code)

    def test_it_checks_both_ends_in_plan(self):
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL))

        self.assertIn("MM(__top.X) - 1000", code)
        self.assertIn("MM(__top.Y) - 500", code)

    def test_it_fails_a_column_that_came_out_vertical(self):
        # The lesson from the wall location line: a postcondition that only
        # checks the things it set can pass while the geometry is wrong. Here
        # the slant itself is the obligation.
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL))

        self.assertIn("колонна вышла вертикальной (geometry)", code)


class TheTopRequiresALevel(unittest.TestCase):
    def test_a_slant_without_a_top_level_is_refused(self):
        # Without it the upper end has no elevation, and inventing one would
        # place the column somewhere plausible and wrong.
        try:
            out = compile_program(_column(top_xy=[1000, 500]),
                                  snapshot=GROUND_SNAPSHOT)
            codes = [d.code for d in out.diagnostics]
            self.assertFalse(out.ok)
        except KirRefusal as refusal:
            codes = [d.code for d in refusal.diagnostics]

        self.assertIn("KIR-T002", codes)

    def test_a_plain_column_needs_no_top_level(self):
        out = compile_program(_column(), snapshot=GROUND_SNAPSHOT)

        self.assertTrue(out.ok, [d.code for d in out.diagnostics])


if __name__ == "__main__":
    unittest.main()


class TheRotationContinuationDoesNotDangle(unittest.TestCase):
    """The shape that shipped broken for three hours.

    The vertical column's location check is an ``else_block``, and the rotation
    obligation chains onto it as ``else { ... }``. A slanted column replaced
    that check with a self-contained guard, so the chain had nothing to attach
    to and the emitted C# carried a dangling ``else`` — CS8641 on all six Revit
    versions.

    The live run never saw it: the program authored by hand omitted
    rotation_deg and the block was not emitted at all. The LIFTED program
    states it, so every rebuilt slanted column would have failed to compile.
    Found by the offline compile gate on its first real use, and 1 428 passing
    tests had nothing to say about it.
    """

    def _csharp(self, program):
        out = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics])
        return out.csharp

    def test_a_slant_that_states_its_rotation_emits_no_rotation_block(self):
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL,
                                    rotation_deg=0.0))

        self.assertNotIn("__wantRot", code)

    def test_the_braces_before_every_else_still_balance(self):
        # A structural stand-in for the compiler: an `else` may only follow a
        # closed `if` body, never a bare `}` that ended an unrelated block.
        code = self._csharp(_column(top_xy=[1000, 500], top_level=_TOP_LEVEL,
                                    rotation_deg=45.0))
        lines = [l.strip() for l in code.splitlines()]

        for index, line in enumerate(lines):
            if line.startswith("else"):
                previous = lines[index - 1]
                with self.subTest(line=index):
                    self.assertFalse(
                        previous == "}" and lines[index - 2].startswith("__post"),
                        "an `else` follows a guard block that closed itself")

    def test_a_vertical_column_keeps_its_rotation_obligation(self):
        code = self._csharp(_column(rotation_deg=45.0, top_level=_TOP_LEVEL))

        self.assertIn("__wantRot", code)
