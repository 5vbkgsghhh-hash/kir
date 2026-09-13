"""The census distinguishes "no category" from "the question failed."

Before 12.08.2026, census §18.1 had
`try { __anyCat = __any.Category; } catch { }`, and an element whose
access THREW landed in the same `no_category` key as a genuinely
categoryless one. A refusal by the INSTRUMENT became a MEASUREMENT about
the model — canon shape 3.

The cost is measured, not assumed: on `k2_ar_rd_v7` the `no_category` key
carries **53,896 elements = 17.35% of the document**, and there is NO WAY
to break them down by kind from the artifacts — it is a single key. This
is the largest line of the unread in the project's main building.

A LOADED FIX, not a delivered one: the census is emitted C#, so across 77
saved runs it has NO EFFECT AT ALL — their artifacts were captured by the
old code. The effect will appear on the first live extraction. The test
checks the TEXT of the emission — the only thing checkable offline.
"""

import unittest

from kir.decompile.census import (
    CATEGORY_READ_FAILED_KEY,
    NO_CATEGORY_KEY,
)
from kir.decompile.extract import build_metadata_cs


class CensusCategoryFailureTest(unittest.TestCase):

    def _body(self) -> str:
        return build_metadata_cs()

    def test_both_keys_reach_the_emitted_census(self) -> None:
        """PASS control: the emission has BOTH keys, not just one."""
        body = self._body()
        self.assertIn(f'"{NO_CATEGORY_KEY}"', body)
        self.assertIn(f'"{CATEGORY_READ_FAILED_KEY}"', body)

    def test_the_catch_no_longer_swallows_silently(self) -> None:
        """FAIL control: bringing back a mute `catch { }` fails the test.

        The distinguishing assertion is specifically an EMPTY catch around
        the category access. Empty catches elsewhere in the census are
        legitimate (there a refusal does not stand in for a measurement),
        so the exact site is what gets checked.
        """
        body = self._body()
        self.assertIn("__anyCat = __any.Category;", body,
                      "площадка обращения к категории исчезла из эмиссии")
        self.assertNotIn("try { __anyCat = __any.Category; } catch { }", body,
                         "немой catch вернулся: отказ прибора снова станет "
                         "измерением о модели")

    def test_the_flag_is_raised_only_in_the_catch(self) -> None:
        """A run where nothing throws must behave exactly as before.

        The flag is set ONLY in the handler; if it turns up anywhere else,
        the key will start appearing on healthy runs and inflate the line
        this fix introduces for the sake of honesty.
        """
        body = self._body()
        self.assertIn("catch { __anyCatThrew = true; }", body)
        self.assertEqual(body.count("__anyCatThrew = true"), 1)

    def test_the_two_keys_are_different_predicates(self) -> None:
        """The keys must differ — otherwise the split is cosmetic."""
        self.assertNotEqual(NO_CATEGORY_KEY, CATEGORY_READ_FAILED_KEY)


if __name__ == "__main__":
    unittest.main()
