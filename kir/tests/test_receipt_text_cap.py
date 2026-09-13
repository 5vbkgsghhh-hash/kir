"""A CEILING NAMED AFTER A FIELD, BUT MEASURING HALF OF IT.

REPRODUCED (measurement 11.08.2026, `/tmp/wiring/w2.py`, flag enabled):

    snowdon_plumb_v4  VERDICT  359 <=2600 | CLASHES 2504 <=2700
                      FIELD message_ru 2865  -> EXCEEDS the verdict ceiling
    sob62_r23_v5      VERDICT  353 | CLASHES 1362 | FIELD 1717  -> ok

`verdict._TEXT_CAP` is named "the RECEIPT text ceiling" and `_describe`
truncates against it — that is, ONLY the verdict half. Further on,
`_with_clash` appends the clash-check text into the SAME `message_ru`
field, which has its own ceiling of 2 700. A field named with a ceiling
of 2 600 can, in the worst case, carry 2 600 + 2 700 = 5 300.

THIS IS THE SAME SHAPE AS THE OTHER FOUR CASES OF THE MARATHON: a value
is declared in one place and read in another, and nothing forces them to
agree.
  * a ceiling named "number of BODIES" that was comparing the number of
    ELEMENTS;
  * a cache key with no `new_from`, then with none of the four ceilings;
  * `bundle_sha256`, which never contained the bundle's fingerprint;
  * and this one — a ceiling named after a field, measuring half of it.

WHAT IS NOT DONE HERE. No shared cutoff is introduced that would slice
into clash findings: that would bring back exactly what the budget wave
had fixed — honesty text crowding out the truth. The halves keep THEIR
OWN ceilings, and the sum gets a NAME and a lock, so the field is never
bigger than what it is named as.
"""
from __future__ import annotations

import os
import unittest

from kir import clash_bundle as CB
from kir.live import journal, verdict as V


def _ducts(n, step=45.0):
    return [{"op": "create_duct", "id": f"d{i}", "diameter_mm": 400.0,
             "p0_mm": [i * step, 0.0, 0.0], "p1_mm": [i * step, 6000.0, 0.0]}
            for i in range(n)]


class TheCapNamesTheHalfItMeasures(unittest.TestCase):

    KEY = ("test-receipt-text-cap", "")

    def setUp(self):
        journal.reset(self.KEY)
        self._prev = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        journal.reset(self.KEY)
        if self._prev is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def _judged(self, programs=6, per=30):
        for _ in range(programs):
            journal.append(self.KEY, {"ops": _ducts(per)}, source="chat")
        return V.judge(self.KEY, since_seq=programs - 1)

    def test_the_verdict_cap_is_named_for_the_verdict(self):
        """A name must name what is measured. `_TEXT_CAP` was measuring
        half of the field and was called the field's ceiling."""
        self.assertTrue(hasattr(V, "_VERDICT_TEXT_CAP"))
        self.assertFalse(hasattr(V, "_TEXT_CAP"),
                         "старое имя пережило переименование")

    def test_the_field_has_a_budget_of_its_own(self):
        """A field that carries two halves must have ITS OWN budget, and
        it must be derived from both, not just assigned."""
        self.assertEqual(V.RECEIPT_TEXT_BUDGET,
                         V._VERDICT_TEXT_CAP + CB._TEXT_CAP)

    def test_the_receipt_never_exceeds_the_budget_of_its_own_field(self):
        block = self._judged()
        self.assertLessEqual(len(block["message_ru"]), V.RECEIPT_TEXT_BUDGET)

    def test_each_half_still_keeps_its_own_ceiling(self):
        """The shared budget does not cancel the half-budgets: otherwise
        one half would eat the other, and that is exactly what the
        receipt's budget was curing."""
        block = self._judged()
        clash = (block.get("clash") or {}).get("message_ru", "")
        verdict_part = block["message_ru"][
            :len(block["message_ru"]) - len(clash)].rstrip()
        self.assertLessEqual(len(verdict_part), V._VERDICT_TEXT_CAP)
        self.assertLessEqual(len(clash), CB._TEXT_CAP)

    def test_the_sum_is_visible_and_not_only_asserted(self):
        """A value that nobody watches grows silently — the same
        argument as with `text_budget` in the clash block."""
        block = self._judged()
        self.assertIn("receipt_chars", block)
        self.assertEqual(block["receipt_chars"], len(block["message_ru"]))

    def test_without_clash_the_receipt_is_unchanged(self):
        """The fix has no right to touch a verdict with no clashes: a
        half with no other half stays exactly what it was."""
        os.environ.pop("KUKAI_IR_CLASH", None)
        CB._CACHE.clear()
        block = self._judged()
        self.assertNotIn("clash", block)
        self.assertLessEqual(len(block["message_ru"]), V._VERDICT_TEXT_CAP)


if __name__ == "__main__":
    unittest.main()
