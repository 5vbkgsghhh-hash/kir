"""THE PASSPORT ROW COVERS EVERY RECEIPT — F-178 · F-177.

**F-178.** `receipts_summary_ru` was reading `side_cuts_total` and
`side_determinations_total` and NOT reading
`side_failures_unclassified`, which `summarize_side_failures` carefully
counts one line above — with the direct argument that "silence about
this is not allowed, this is exactly the hole the dictionary was set up
to close." Executed before the fix:

    summary: side_failures_total=14343, side_cuts_total=0,
             side_failures_unclassified={'неизвестная_причина': 14343}
    passport row: "no cuts"

🔴 "NO CUTS" WITH 14,343 UNCLASSIFIED RECEIPTS. And this is exactly the
quantity the module itself names as the reason for setting up the
breakdown: by that single number, 14,343, the stage would be judged the
most FAILED of all. The number came back with the opposite sign — by
it, the stage would be judged the CLEANEST of all, i.e. the lie went in
the reassuring direction, the worse of the two.

**F-177.** `reconcile_side_stage` was making an early return
`if not wanted: return` BEFORE building `seen`, so the guard "the
response carries unrequested ids" was UNREACHABLE on an empty request.
An empty request is not a contrivance: a stage with nothing to ask is
called with an empty list, and foreign rows in the response mean the
bridge was reading a DIFFERENT document — a trouble that cost 1,837
foreign receipts on 30.07.

🔴 THE RATCHET HERE IS A SUM, NOT A SHAPE. "Was the word 'class'
printed" — a check of SHAPE: any edit of the text will satisfy it,
including one that prints zero, and it is defeated by rewriting the
line. "Does what was printed add up to the whole" — a check of a
PROPERTY: as long as the breakdown does not cover
`side_failures_total`, the row must turn red, and the next kind of
receipt will not disappear the same way this one did.

Run:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_the_receipt_line_covers_every_receipt.py -q
"""
from __future__ import annotations

import re
import unittest

from kir.decompile.side_contract import (
    SideStageContractError,
    receipts_summary_ru,
    reconcile_side_stage,
)


def _summary(**over) -> dict:
    base = {
        "side_failures_total": 0,
        "side_cuts_total": 0, "side_cuts_by_reason": {},
        "side_determinations_total": 0, "side_determinations_by_reason": {},
        "side_failures_untyped": 0,
    }
    base.update(over)
    return base


def _numbers_printed(line: str) -> int:
    """The sum of ALL the row's total numbers — from its own text, not
    from the summary.

    Only total numbers are counted (following "receipts",
    "determinations", "NO CLASS", "NO TYPE"), not the breakdown by
    reason: otherwise every number would enter twice.
    """
    head = re.match(r"^(\d+)", line)
    total = int(head.group(1)) if head else 0
    for tag in ("определений", "БЕЗ КЛАССА", "БЕЗ ТИПА"):
        found = re.search(tag + r":?\s*(\d+)", line)
        if found:
            total += int(found.group(1))
    return total


class TheLineAccountsForTheWhole(unittest.TestCase):
    """A property, not a shape: what is printed must add up to the whole."""

    CASES = {
        "только без класса (случай 14 343)": _summary(
            side_failures_total=14343,
            side_failures_unclassified={"неизвестная_причина": 14343}),
        "только срезы": _summary(
            side_failures_total=19, side_cuts_total=19,
            side_cuts_by_reason={"cut": 19}),
        "срезы и определения": _summary(
            side_failures_total=19 + 14324, side_cuts_total=19,
            side_cuts_by_reason={"cut": 19},
            side_determinations_total=14324,
            side_determinations_by_reason={"not_curtain": 14324}),
        "все четыре рода сразу": _summary(
            side_failures_total=19 + 100 + 7 + 3, side_cuts_total=19,
            side_cuts_by_reason={"cut": 19},
            side_determinations_total=100,
            side_determinations_by_reason={"not_curtain": 100},
            side_failures_unclassified={"неизвестная": 7},
            side_failures_untyped=3),
        "ни одной квитанции": _summary(),
    }

    def test_every_receipt_reaches_the_line(self):
        for name, summary in self.CASES.items():
            with self.subTest(случай=name):
                line = receipts_summary_ru(summary)
                self.assertEqual(
                    _numbers_printed(line), summary["side_failures_total"],
                    f"строка не покрывает целое: {line!r}")

    def test_the_unclassified_case_no_longer_says_there_are_none(self):
        line = receipts_summary_ru(self.CASES["только без класса (случай 14 343)"])
        self.assertIn("14343", line)
        self.assertIn("неизвестная_причина", line,
                      "число без причины нельзя заказать в работу")

    def test_a_clean_extraction_still_says_there_are_none(self):
        """🔴 THE SECOND OUTCOME: the fix does not turn the row into an eternal complaint."""
        self.assertEqual(receipts_summary_ru(_summary()), "срезов нет")

    def test_the_classified_half_is_rendered_exactly_as_before(self):
        """The existing render must work exactly as before — down to the character."""
        self.assertEqual(
            receipts_summary_ru(self.CASES["только срезы"]),
            "19 (по причинам: cut 19)")


class TheGuardOfForeignIdsIsReachable(unittest.TestCase):
    """F-177: an empty request is not "nothing to check," but "we did not ask"."""

    def test_an_empty_request_still_refuses_foreign_ids(self):
        with self.assertRaises(SideStageContractError) as caught:
            reconcile_side_stage("curtain", requested=[],
                                 accounted=["чужой-1", "чужой-2"])
        self.assertIn("незапрошенных", str(caught.exception))

    def test_a_non_empty_request_refuses_them_as_before(self):
        """🔴 CONTROL: the existing guard does not move."""
        with self.assertRaises(SideStageContractError):
            reconcile_side_stage("curtain", requested=["a"],
                                 accounted=["a", "чужой"])

    def test_an_empty_request_with_an_empty_answer_is_silent(self):
        """🔴 THE SECOND OUTCOME: the guard does not fire on a legal empty exchange."""
        reconcile_side_stage("curtain", requested=[], accounted=[])

    def test_a_missing_id_is_still_refused(self):
        with self.assertRaises(SideStageContractError) as caught:
            reconcile_side_stage("curtain", requested=["a", "b"],
                                 accounted=["a"])
        self.assertIn("без строки и без квитанции", str(caught.exception))

    def test_a_foreign_id_is_named_before_a_missing_one(self):
        """A foreign document cancels the meaning of the question "what is missing"."""
        with self.assertRaises(SideStageContractError) as caught:
            reconcile_side_stage("curtain", requested=["a", "b"],
                                 accounted=["чужой"])
        self.assertIn("незапрошенных", str(caught.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
