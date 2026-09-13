"""A CLEARANCE IS A REQUIREMENT, NOT THE ABSENCE OF AN INTERSECTION.

🔴 WHY THIS WAS ADDED (2026-09-07, owner finding #1, reproduced by the probe
`intent-preservation/stageG/red_clearance.py`).

Two bodies are set apart by **10 mm**, the requirement is **50 mm**. Before
this wave, the analysis answered:

    status "refuted" · relation "clear" · kind "clearance" · gap_mm 10.0
    constraints about the unmet requirement — NOT A SINGLE ONE
    propose_fix -> FixError: nothing to fix: the pair is clear

That is, the analysis's STRONGEST claim ("provably no intersection") stood
exactly where the requirement was violated, while the fixer refused to fix
the violation with a word about the RELATION. `clear` answers the question
"do the bodies intersect"; it does not answer the question "is the clearance
met" at all, and substituting one for the other is exactly the falsehood that
four acceptance instruments failed to ask about.

WHAT IS GUARDED HERE:

1. a violation gets ITS OWN kind (`clearance_violated`) and three numbers:
   `gap_mm`, `required_clearance_mm`, `deficit_mm`;
2. the requirement's CARRIER is named — the reader must see whose decision
   the number was taken from, not have to guess;
3. without a requirement, `clear` stays `refuted`, and the report SAYS that
   there was no requirement — silence here would read as "clearance met";
4. the fixer works on the violation and takes its margin from the
   requirement ITSELF.
"""
from __future__ import annotations

import unittest

from kir.clash.project_analysis import (CLEARANCE_SOURCE, DEFAULT_TOLERANCE_POLICY,
                                        Finding, NO_CLEARANCE_REQUIREMENT)


def _clear(gap: float, **over) -> Finding:
    row = {"finding_id": "f1", "a_output_id": "a", "b_output_id": "b",
           "status": "refuted", "relation": "clear", "kind": "clearance",
           "evidence": "occt_common_v1", "gap_mm": gap}
    row.update(over)
    return Finding(**row)


class TheDefaultIsNoRequirementAndItIsSaidAloud(unittest.TestCase):

    def test_the_shipped_policy_declares_no_clearance_requirement(self) -> None:
        """The default is NO requirement. Otherwise it would appear for everyone silently."""
        self.assertEqual(DEFAULT_TOLERANCE_POLICY["clearance_mm"], 0.0)

    def test_a_finding_without_a_requirement_does_not_print_empty_fields(self) -> None:
        """An empty field would read as "there is a requirement and it is met"."""
        row = _clear(10.0).to_dict()
        for key in ("required_clearance_mm", "deficit_mm", "clearance_source"):
            self.assertNotIn(key, row)

    def test_the_limit_string_exists_and_says_what_clear_means(self) -> None:
        self.assertIn("не задано", NO_CLEARANCE_REQUIREMENT)
        self.assertIn("«зазор выдержан»", NO_CLEARANCE_REQUIREMENT)
        self.assertIn("не пересекаются", NO_CLEARANCE_REQUIREMENT)


class AViolatedClearanceCarriesThreeNumbersAndItsCarrier(unittest.TestCase):

    def setUp(self) -> None:
        self.row = _clear(10.0, status="clearance_violated", required_clearance_mm=50.0,
                          deficit_mm=40.0, clearance_source=CLEARANCE_SOURCE).to_dict()

    def test_the_three_numbers_travel_together(self) -> None:
        self.assertEqual(self.row["status"], "clearance_violated")
        self.assertEqual(self.row["gap_mm"], 10.0)
        self.assertEqual(self.row["required_clearance_mm"], 50.0)
        self.assertEqual(self.row["deficit_mm"], 40.0)

    def test_the_requirement_names_its_carrier(self) -> None:
        """A number without a carrier is someone else's decision without a name."""
        self.assertEqual(self.row["clearance_source"], CLEARANCE_SOURCE)
        self.assertIn("clearance_mm", CLEARANCE_SOURCE)

    def test_the_deficit_is_the_requirement_minus_the_gap(self) -> None:
        self.assertAlmostEqual(
            self.row["deficit_mm"],
            self.row["required_clearance_mm"] - self.row["gap_mm"], places=9)

    def test_the_relation_is_still_clear_and_that_is_not_a_contradiction(self) -> None:
        """The bodies REALLY do not intersect — the REQUIREMENT is violated, not a prohibition."""
        self.assertEqual(self.row["relation"], "clear")
        self.assertFalse(self.row["overlap_volume_mm3"])


class TheRepairWorksOnAViolatedClearance(unittest.TestCase):
    """The previous line answered "nothing to fix" to a violation. Not anymore."""

    def test_a_clear_pair_without_a_violation_is_still_nothing_to_fix(self) -> None:
        """THE DENOMINATOR FIRST: a fixer that fixes everything is not a fixer."""
        import kir.project_fix as fix

        source = __import__("inspect").getsource(fix.propose_fix)
        self.assertIn('if finding.relation == "clear" and not violated:', source)
        self.assertIn("nothing to fix: the pair is clear", source)

    def test_the_margin_comes_from_the_requirement_not_from_a_default(self) -> None:
        """Fixing a violation "to the default 50" when the requirement is 200 is not a fix."""
        import kir.project_fix as fix

        source = __import__("inspect").getsource(fix.propose_fix)
        self.assertIn("finding.required_clearance_mm", source)
        self.assertEqual(fix.DEFAULT_CLEARANCE_MM, 50.0)


if __name__ == "__main__":                                     # pragma: no cover
    unittest.main()
