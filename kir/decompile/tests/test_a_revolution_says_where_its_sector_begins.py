"""TWO DIFFERENT ROTATION SECTORS PRODUCED THE SAME PROGRAM BYTE-FOR-BYTE
(RH-02).

MEASUREMENT (04.09.2026), reproduced by this same file. Capture reads the
starting angle honestly: C# writes `start_angle_deg` as
`Math.Round(__rv.StartAngle * 180.0 / Math.PI, 6)`, decompile accepts it,
and the `FormRecipe.start_angle_deg` field is filled in. The lift took
from it ONE DIFFERENCE — `sweep = abs(end - start)` — and printed
`sweep_deg`. So:

    rotation   0° → 90°   ->  {"sweep_deg": 90.0, …}
    rotation  90° → 180°  ->  {"sweep_deg": 90.0, …}   BYTE-FOR-BYTE IDENTICAL

These are different sectors in different places. The solid arrived
ROTATED, and a volumetric check does not catch this at all: volume is
invariant under rotation — the same blindness that keeps an extrusion from
being flagged as multi-body ("the solid comes out plausible and in the
wrong place").

🔴 WHY A REFUSAL, AND NOT A NEW OPERATION FIELD. `create_solid_revolve` has
NO slot for a starting angle, and its absence from the registry is stated
in words: "The count is ALWAYS from the world's +X axis: there is no
starting angle as a parameter, and this is not a default but the absence
of a degree of freedom — the frame is one we set." The registry
(`kir/ops_solid.py`) lies OUTSIDE this fix and outside this file; inventing
a slot here would mean setting up a second bearer for the operation's law.
So the loss is NAMED: a sector that does not start from +X gets
`revolve_start_angle_not_expressible`, instead of silently sliding to
zero.

THE REFUSAL'S BOUNDARY IS MEASURED, NOT ASSIGNED: for a full turn the
sector's start is not observable (the solid does not depend on it), and it
still passes as before. Otherwise the refusal would have eaten legitimate
solids of revolution — the very two that had already been rejected once by
the false "sketch is not horizontal."
"""
from __future__ import annotations

import json
import unittest

from kir.decompile import family_recipe as FR


def _revolution(start: float | None, end: float | None) -> FR.FormRecipe:
    """A rectangular profile in the axis plane, the axis vertical at
    (0, 0)."""
    pts = [(1000.0, 0.0, 0.0), (2000.0, 0.0, 0.0),
           (2000.0, 0.0, 500.0), (1000.0, 0.0, 500.0)]
    loop = tuple(("line", pts[i], pts[(i + 1) % 4], None) for i in range(4))
    return FR.FormRecipe(
        form_id="F1", kind=FR.FormKind.REVOLUTION, is_solid=True,
        name="rev", plane_normal=(0.0, 1.0, 0.0), plane_z_mm=None,
        loops=(loop,),
        axis_start_mm=(0.0, 0.0, 0.0), axis_end_mm=(0.0, 0.0, 1000.0),
        start_angle_deg=start, end_angle_deg=end)


def _lift(start, end) -> FR.FormLift:
    return FR.form_to_op(_revolution(start, end),
                         category="OST_GenericModel", name="A")


class СекторНеПереезжаетКНулюМолча(unittest.TestCase):
    """The CAPABILITY axis: what the lift must now say about the sector's
    start."""

    def test_two_different_sectors_no_longer_produce_one_program(self):
        first, second = _lift(0.0, 90.0), _lift(90.0, 180.0)
        self.assertTrue(first.ops, "сектор от +X обязан подниматься как прежде")
        self.assertFalse(second.ops)
        self.assertNotEqual(json.dumps(first.ops, sort_keys=True),
                            json.dumps(second.ops, sort_keys=True))

    def test_the_refusal_names_its_own_repair(self):
        lift = _lift(90.0, 180.0)
        self.assertIs(lift.refusal.code,
                      FR.RecipeRefusal.REVOLVE_START_ANGLE_NOT_EXPRESSIBLE)
        self.assertIn("90.000", lift.refusal.detail)
        self.assertIn("180.000", lift.refusal.detail)

    def test_the_refusal_code_is_not_the_one_about_the_angle_being_too_big(self):
        """Two different remedies — two different codes.

        `revolve_angle_out_of_bounds` is fixed DIFFERENTLY (the sector
        does not fit within 1..360); merging them would mean giving one
        code to two different jobs.
        """
        self.assertNotEqual(
            FR.RecipeRefusal.REVOLVE_START_ANGLE_NOT_EXPRESSIBLE.value,
            FR.RecipeRefusal.SWEEP_ANGLE_OUT_OF_BOUNDS.value)


class ЧестныеВращенияНеПострадали(unittest.TestCase):
    """The CONTROL without which the previous class proves nothing.

    A refusal that always fires "fixes" things that were never broken.
    Listed here are all the shapes that MUST still come up as before.
    """

    def test_a_sector_from_the_world_x_axis_still_lifts(self):
        lift = _lift(0.0, 90.0)
        self.assertIsNone(lift.refusal)
        self.assertEqual(lift.op["sweep_deg"], 90.0)

    def test_a_full_turn_lifts_FROM_ANY_START(self):
        """For a full turn the start is not observable — and this is not a
        concession."""
        for start, end in ((0.0, 360.0), (90.0, 450.0), (-45.0, 315.0)):
            with self.subTest(start=start):
                lift = _lift(start, end)
                self.assertIsNone(lift.refusal, f"{start}° → {end}°")
                self.assertEqual(lift.op["sweep_deg"], 360.0)

    def test_a_start_written_as_a_full_turn_is_the_same_zero(self):
        lift = _lift(360.0, 450.0)
        self.assertIsNone(lift.refusal)
        self.assertEqual(lift.op["sweep_deg"], 90.0)

    def test_an_unread_angle_keeps_its_OWN_older_refusal(self):
        """"Angles not read" is not "start inexpressible": it is fixed by
        reading."""
        lift = _lift(None, 90.0)
        self.assertIs(lift.refusal.code, FR.RecipeRefusal.RECIPE_INCOMPLETE)


class КонтрольFail(unittest.TestCase):
    """FAIL control: bring back the previous law — the property must
    disappear.

    What is checked is the BEHAVIOR of the substituted law, not the
    source text: a test that reads text stays green because of a
    comment.
    """

    def test_taking_only_the_difference_makes_the_two_sectors_identical(self):
        def only_the_difference(form):
            """The previous lift, verbatim: one difference, the start
            discarded."""
            sweep = abs(form.end_angle_deg - form.start_angle_deg)
            return {"op": "create_solid_revolve", "id": form.form_id,
                    "axis_xy_mm": [form.axis_start_mm[0],
                                   form.axis_start_mm[1]],
                    "sweep_deg": round(sweep, 6)}

        then_first = only_the_difference(_revolution(0.0, 90.0))
        then_second = only_the_difference(_revolution(90.0, 180.0))
        self.assertEqual(json.dumps(then_first, sort_keys=True),
                         json.dumps(then_second, sort_keys=True),
                         "прежний закон давал ОДНУ программу на два сектора")
        now_first, now_second = _lift(0.0, 90.0), _lift(90.0, 180.0)
        self.assertNotEqual(bool(now_first.ops), bool(now_second.ops))


if __name__ == "__main__":
    unittest.main()
