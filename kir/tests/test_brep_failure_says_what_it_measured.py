"""A `BRepBuilder` REFUSAL IS OBLIGATED TO CARRY WHAT WAS MEASURED, AND THE NEXT MOVE.

WHY THIS FILE EXISTS. A live measurement on 2026-08-20 (Revit 2026): a facade
cut by Python into 48 independent NURBS patches produced 46 built ones and
TWO refusals of `Finish() -> Failure`. The refusal named only the outcome of
`Finish()`, even though two lines above the emission had already read
`IsResultAvailable()` and `RemovedSomeFaces()` — that is, it stayed silent
about values it was already holding. This is the tree's own named defect
("a message is obligated to print what was MEASURED"), and here it costs
more than usual: the cause of the refusal is NOT FOUND, and every unnamed
signal costs one more live attempt.

🔴 WHAT THE MEASUREMENT RULED OUT, SO THE NEXT PERSON DOES NOT LOOK THERE (seven hypotheses):

    position          the same panel at the coordinate origin fails the same way
    orientation       transposing the grid (flipping the normal) does not help
    flatness          the failing 21st and 32nd of 48 by deviation from planarity
    amplitude         a sweep: x1.0 refusal, x1.5 ok, x2.0 ok, x3.0 refusal, x4.0 ok
    curvature         a sign flip covers both refusals AND 29 more that built fine
    rounding          a 0.0040-0.0050 mm offset across ALL 48, 0.0047 for the failing ones
    regularity        |dS/du x dS/dv| for the failing ones is the LARGEST of the 48

The last two are ruled out by arithmetic in this same pass and by the
opposite sign: the failing patches are the MOST regular, and their rounding
is exactly average.

WHAT TO DO WHEN THE CAUSE IS FOUND: remove `test_the_cause_is_still_unnamed`
together with the words "NOT NAMED" in the refusal text. The test goes red
ON PURPOSE if the text is fixed but the hypothesis list is not: a refusal
that promises ignorance after the knowledge has arrived is a lie in the most
visible spot of the receipt.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program

_KN = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]


def _cs() -> str:
    pts = [[i * 1000.0, (i % 2) * 300.0 + (j % 3) * 120.0, j * 900.0]
           for i in range(4) for j in range(4)]
    out = compile_program({"ir_version": "1.0", "ops": [{
        "op": "create_surface", "id": "S1",
        "surface": {"degree_u": 3, "degree_v": 3, "count_u": 4, "count_v": 4,
                    "knots_u": _KN, "knots_v": _KN, "control_points_mm": pts},
        "category": "generic_model", "name": "проба"}]},
        revit_version="2026", snapshot={"levels": []})
    assert out.ok, [str(d.message_ru)[:200] for d in out.diagnostics]
    return out.csharp


def _refusal_line(cs: str) -> str:
    return next(l for l in cs.splitlines() if "BRepBuilder не собрал" in l)


class TheRefusalCarriesTheMeasurement(unittest.TestCase):

    def test_it_carries_result_availability(self) -> None:
        self.assertIn("результат доступен", _refusal_line(_cs()))

    def test_it_carries_whether_a_face_was_dropped(self) -> None:
        """`RemovedSomeFaces` distinguishes two DIFFERENT outcomes.

        "Did not build" and "built, but Revit dropped the one face" are
        different fixes, and the same text for both would mislead the reader.
        """
        self.assertIn("грань выброшена", _refusal_line(_cs()))

    def test_the_measured_values_are_EXPRESSIONS_not_literals(self) -> None:
        """CONTROL, WITHOUT WHICH THE FIRST TWO ARE WORTHLESS.

        The words "result available" could be printed as a constant, and the
        test above would pass without reading a single value. This checks
        that the VARIABLES read from Revit are what actually get substituted
        into the string.
        """
        line = _refusal_line(_cs())
        self.assertIn("__avail_S1 ?", line)
        self.assertIn("__removed_S1 ?", line)

    def test_it_names_the_next_move(self) -> None:
        """A refusal with no next move shifts the work onto the reader."""
        line = _refusal_line(_cs())
        self.assertIn("СЛЕДУЮЩИЙ ХОД", line)
        self.assertIn("отдельной программой", line)

    def test_it_is_NOT_the_bare_old_form(self) -> None:
        """Direct evidence of the fix: the old text stopped at the outcome of Finish()."""
        line = _refusal_line(_cs())
        bare = '"BRepBuilder не собрал оболочку: Finish() -> " + __outcome_S1)'
        self.assertNotIn(bare, line,
                         "отказ вернулся к форме, молчащей об измеренном")

    def test_the_cause_is_still_unnamed(self) -> None:
        """While the cause is not found — the refusal is obligated to say so OUT LOUD.

        Remove together with the words in the text once the cause is found. See the header.
        """
        self.assertIn("НЕ НАЗВАНА", _refusal_line(_cs()))


if __name__ == "__main__":
    unittest.main()
