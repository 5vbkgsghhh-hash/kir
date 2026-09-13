"""AN UNCOMPUTED VALUE IS PRINTED AS `null` WITH A WORD, NOT AS A NUMBER.

Found by a live run of a twisted form on 20.08.2026 (Revit 2026, a blend from a square
into a rotated square). The receipt returned:

    volume_mm3_expected      0
    volume_mm3_measured      103 455 659 089
    volume_tolerance_mm3     0

This reads as "we expected zero volume, we got a mountain" — that is, as the crudest
kind of construction error. In reality the volume simply WAS NOT COMPUTED: Revit itself
chooses the side wall's shape between the profiles, it is undocumented, and cannot be predicted.
This is a named absence, not an expectation.

WHY THIS IS WORSE THAN A MISSING KEY. Zero is a legitimate value for a volume, so
the reader cannot tell "it wasn't computed" apart from "it was computed and came out zero". With no
key, a question has been asked; with a key that lies, the question is closed with the wrong answer. In our
house this form is recorded as a named one ("zero of an uncomputed value") and has been bought
today for the third time: in the live-loop instrument (`_first(...) or got` was substituting a
"0 elements" counter for the entire answer) and here.

A NEIGHBORING FORM, CLOSED BY THE SAME RULE: a sentinel number. For a surface,
uncompared control points were being printed as `-304.8` — this is `-1.0` in
internal feet, run through the conversion to millimeters. A plausible-looking
number is more dangerous than a zero: nobody argues with it.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program

_SNAP = {"levels": [{"id": 355, "name": "Уровень 1", "elevation_mm": 0.0}]}


def _blend_cs() -> str:
    base = [[0, 0], [4000, 0], [4000, 4000], [0, 4000]]
    top = [[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]]
    out = compile_program({"ir_version": "1.0", "ops": [{
        "op": "create_solid_blend", "id": "B1",
        "profile": {"outer": {"shape": "poly", "points_mm": base}},
        "profile_top": {"outer": {"shape": "poly", "points_mm": top}},
        "height_mm": 6000.0, "category": "generic_model",
        "name": "контроль",
    }]}, revit_version="2026", snapshot=_SNAP)
    assert out.ok, [str(d.message_ru)[:200] for d in out.diagnostics]
    return out.csharp


class TheReceiptNeverInventsANumber(unittest.TestCase):

    def test_the_unpredictable_volume_is_null(self) -> None:
        cs = _blend_cs()
        self.assertIn('__rb["volume_mm3_expected"] = null;', cs,
                      "непредсказуемый объём напечатан числом")

    def test_the_null_comes_with_a_reason_in_words(self) -> None:
        """`null` without a reason is the second half of the same defect.

        The reader learns "it wasn't computed" and does not learn WHY, that is, cannot
        decide whether this is a defect or simply how Revit works.
        """
        cs = _blend_cs()
        self.assertIn('__rb["volume_expectation_ru"]', cs)
        self.assertIn("боковины", cs)

    def test_a_tolerance_for_an_unclaimed_value_is_NOT_printed(self) -> None:
        """A tolerance next to an unknown expectation is decoration, and it lies.

        `volume_tolerance_mm3: 0` next to "it wasn't computed" reads as "it was compared with a
        zero tolerance", that is, as the strictest possible check.
        """
        self.assertNotIn('__rb["volume_tolerance_mm3"]', _blend_cs())

    def test_the_measured_volume_IS_still_printed(self) -> None:
        """A NARROWNESS CONTROL: the fix must not take away what was MEASURED.

        Removing an unverifiable expectation is no reason to stay silent about the fact: the live number
        is exactly what a law of the side wall will one day be derived from.
        """
        self.assertIn('__rb["volume_mm3_measured"]', _blend_cs())

    def test_a_solid_with_a_KNOWN_volume_still_claims_it(self) -> None:
        """A SECOND NARROWNESS CONTROL: extrusion predicts volume exactly.

        Without it, the fix could have removed the expectation from ALL bodies at once, and this
        would have passed every check above.
        """
        out = compile_program({"ir_version": "1.0", "ops": [{
            "op": "create_solid_extrusion", "id": "E1",
            "profile": {"outer": {"shape": "poly",
                                  "points_mm": [[0, 0], [3000, 0],
                                                [3000, 3000], [0, 3000]]}},
            "height_mm": 2000.0, "category": "generic_model",
            "name": "контроль",
        }]}, revit_version="2026", snapshot=_SNAP)
        self.assertTrue(out.ok, [str(d.message_ru)[:200] for d in out.diagnostics])
        self.assertIn('__rb["volume_mm3_expected"] = ', out.csharp)
        self.assertNotIn('__rb["volume_mm3_expected"] = null;', out.csharp)


if __name__ == "__main__":
    unittest.main()
