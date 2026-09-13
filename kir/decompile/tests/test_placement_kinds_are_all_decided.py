"""EVERY PLACEMENT KIND MUST BE RESOLVED, NOT SIMPLY ABSENT.

THE OCCASION — THE THIRD CASE OF ONE FAMILY IN ONE FILE. The lift gate held
a closed set of point-based placements, and twice it turned out to be narrower than
what the op already knew how to do:

  * `OneLevelBasedHosted` — "the op learned the host, but the lift gate was not widened,"
    2 053 elements on the `k2_ar_rd` tower;
  * `TwoLevelsBased` (12.08.2026) — the op carried `top_level`/`base_offset_mm`/
    `top_offset_mm`, the emitter wrote them, the witness read `FAMILY_TOP_LEVEL_PARAM`
    back, and the gate refused 4 658 elements. The comment right next to it at the same time
    ASSERTED that a two-level placement cannot be set by a point — while there were 5 337 lines with
    a point, a rotation, and both levels resolvable.

A relative in the compilation gate: the producer is unconditional, the consumer sits behind
a disabled flag. **The two sides of one fact evolve apart, and nothing
forces them to coincide** — as long as the exception is expressed by the ABSENCE of a line,
it requires a decision from no one.

WHAT THIS TEST DOES NOT REQUIRE. It does not require that every kind be lifted: for
`WorkPlaneBased` there is also a point (5 060 lines on the same tower), but the work
plane is a separate fact, and lifting by the point would silently lose it. Replacing
the list with the rule "there is a point ⇒ we lift" is forbidden for exactly this reason. What is required is
RESOLVEDNESS: point-based, view-dependent, or a named refusal with a reason and a deadline.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_placement_kinds.jsonl"))

from kir.decompile import lift  # noqa: E402
from kir.decompile.family_placement_extract import (  # noqa: E402
    FamilyPlacementType,
)


class EveryPlacementKindIsDecided(unittest.TestCase):

    def test_the_enum_is_reachable_before_any_zero_below(self):
        """Any zero below would be a lie if the enumeration is empty."""
        self.assertGreaterEqual(len(list(FamilyPlacementType)), 8)
        self.assertTrue(lift._POINT_PLACED_PLACEMENTS)
        self.assertTrue(len(lift.PLACEMENTS_NOT_POINT_PLACED))

    def test_no_placement_kind_is_silently_unhandled(self):
        """There is no third option — silence."""
        decided = (
            {p.value for p in lift._POINT_PLACED_PLACEMENTS}
            | {p.value for p in lift._VIEW_SPECIFIC_PLACEMENTS}
            | set(lift.PLACEMENTS_NOT_POINT_PLACED))
        silent = {p.value for p in FamilyPlacementType} - decided
        self.assertEqual(
            silent, set(),
            "роды размещения, о которых не сказано НИЧЕГО: "
            + ", ".join(sorted(silent))
            + ". Либо строка в _POINT_PLACED_PLACEMENTS (только вместе с "
              "замером, что все входы опа у них есть), либо запись в "
              "PLACEMENTS_NOT_POINT_PLACED с причиной и сроком")

    def test_a_kind_is_not_in_two_places_at_once(self):
        """Point-based AND a named refusal — that is two verdicts on one fact."""
        both = ({p.value for p in lift._POINT_PLACED_PLACEMENTS}
                & set(lift.PLACEMENTS_NOT_POINT_PLACED))
        self.assertEqual(both, set(),
                         "род и поднимается, и объявлен неподнимаемым: "
                         + ", ".join(sorted(both)))

    def test_the_ledger_speaks_only_about_kinds_that_exist(self):
        """A record about a kind that is not in the enumeration is forever green and forever
        useless — the same accounting gap, only reversed."""
        orphan = (set(lift.PLACEMENTS_NOT_POINT_PLACED)
                  - {p.value for p in FamilyPlacementType})
        self.assertEqual(orphan, set(),
                         "журнал говорит о несуществующих родах: "
                         + ", ".join(sorted(orphan)))

    def test_two_levels_based_is_point_placed_and_that_is_measured(self):
        """PINNED DELIBERATELY: the previous comment asserted the opposite.

        Without this line, the next person will narrow the set back down using the same
        reasoning — it sounds convincing right up until the measurement.
        """
        self.assertIn(FamilyPlacementType.TWO_LEVELS_BASED,
                      lift._POINT_PLACED_PLACEMENTS)

    def test_work_plane_based_is_excluded_ON_PURPOSE_and_says_why(self):
        """An exception expressed by absence requires a decision from no one."""
        self.assertNotIn(FamilyPlacementType.WORK_PLANE_BASED,
                         lift._POINT_PLACED_PLACEMENTS)
        reason = lift.PLACEMENTS_NOT_POINT_PLACED.reason(
            FamilyPlacementType.WORK_PLANE_BASED.value)
        self.assertIn("плоскост", reason)


if __name__ == "__main__":
    unittest.main()
