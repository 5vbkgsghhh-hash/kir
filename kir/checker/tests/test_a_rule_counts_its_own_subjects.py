"""A RULE COUNTS ITS OWN POPULATION, NOT SOMEONE ELSE'S.

WHAT HAPPENED (29.08.2026, audit finding F-134). Four consistency
rules iterate over DIFFERENT things — rooms, doors, unclassified ones, levels —
yet the engine wrote `n_subjects=len(model.rooms)` for all four. Live: a model of
seven rooms and ZERO doors printed

    HAB061 EVALUATED(n=7), 0 violations

that is, "doors reconciled and clean" where there were no doors at all. The number was
CORRECT — just about the wrong subject. An instrument that is truthful about a different
population is the most convincing form of lying: there is nothing to fault.

WHAT THIS GUARDS. Not "the counter is correct" — the test cannot know that —
but that the counters of DIFFERENT rules read DIFFERENT populations. Reverting to a common
denominator would make them equal again, and this is visible as a number.

🔴 SEPARATELY: EMPTINESS COMES IN TWO KINDS, AND `HAB062` IS THE SECOND KIND.
Zero unclassified rooms is a KNOWN CLEAN RESULT, not an absent
measurement. Counting the violations themselves as subjects would mean printing `NOT_EVALUATED`
exactly when the rule did its best work. So `HAB062`'s subject is
the classification outcome for EVERY decompiled room, and it is empty if and
only if none has been decompiled.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from kir.checker import engine
from kir.checker.rules import consistency
from kir.checker.spatial_model import Level, Room, RoomFunction, SpatialModel

#: 🔴 THE FLAG IS SET AS A SCOPE, NOT ON IMPORT, AND THIS WAS PAID FOR RIGHT HERE.
#: The first edition of this file did `os.environ.setdefault("KIR_CHECKER_V2",
#: "1")` at module level — and the environment edit happened AT COLLECTION time, that is, before
#: other people's tests. In that same run a neighbour failed:
#: `test_design_check.py::test_v1_path_is_refused_never_silently_downgraded`,
#: which checks the v1 path and saw v2 turned on. This test's own code accused
#: someone else's — the very shape of bug because of which this tree has already moved
#: environment edits to module scope and back.
#:
#: `checker_v2_enabled()` reads the environment LIVE (`flags.py:41`), so
#: a scoped context manager is enough and nothing is lost.
_V2 = mock.patch.dict(os.environ, {"KIR_CHECKER_V2": "1"})


def _model(n_rooms: int) -> SpatialModel:
    lvl = Level(id="L1", name="L1", elevation_mm=0, index=0)
    rooms = [
        Room(id=f"r{i}", name="жилая", level_id="L1",
             function=RoomFunction.ЖИЛАЯ, area_m2=16.0, height_mm=2700.0,
             boundary=[(i * 5000, 0), (i * 5000 + 4000, 0),
                       (i * 5000 + 4000, 4000), (i * 5000, 4000)])
        for i in range(n_rooms)
    ]
    return SpatialModel(building_id="b", levels=[lvl], rooms=rooms)


class ARuleCountsItsOwnSubjects(unittest.TestCase):

    def setUp(self) -> None:
        with _V2:
            self.report = engine.run(_model(7))
        self.by_id = {o.rule_id: o for o in self.report.coverage.outcomes}

    def test_every_consistency_rule_declares_its_population(self) -> None:
        """The field is mandatory by construction; here — that it is not a stub."""
        self.assertGreaterEqual(len(consistency.CONSISTENCY_REGISTRY), 4)
        for rule in consistency.CONSISTENCY_REGISTRY:
            with self.subTest(rule=rule.rule_id):
                self.assertTrue(callable(rule.subjects))
                self.assertGreaterEqual(
                    len(rule.vacuous_reason.strip()), 20,
                    f"{rule.rule_id}: причина пустоты не названа — «мы не "
                    f"спрашивали» и «спросили, ответило НЕТ» печатались бы "
                    f"одинаково")

    def test_a_doorless_model_does_not_claim_doors_were_reconciled(self) -> None:
        """THE EXACT SAME DEFECT. Seven rooms, zero doors."""
        hab061 = self.by_id["HAB061"]
        self.assertEqual(
            hab061.n_subjects, 0,
            "HAB061 отчитался числом КОМНАТ: «двери сверены» там, где дверей нет")
        self.assertEqual(hab061.status.value, "not_evaluated")
        self.assertTrue(hab061.reason.strip(), "пустота обязана назвать себя")

    def test_the_counters_do_not_all_read_one_population(self) -> None:
        """A reversion to a common denominator is visible as a number: they would become equal."""
        counts = {rid: self.by_id[rid].n_subjects
                  for rid in ("HAB060", "HAB061", "HAB062", "HAB063")}
        self.assertGreater(
            len(set(counts.values())), 1,
            f"все счётчики согласованности дали одно число {counts} — это "
            f"признак общего знаменателя, а совокупности у них разные")

    def test_zero_unclassified_is_a_clean_result_not_a_vacuum(self) -> None:
        """HAB062, with everything classified, must be EVALUATED, not "unknown"."""
        hab062 = self.by_id["HAB062"]
        self.assertEqual(hab062.status.value, "evaluated")
        self.assertEqual(hab062.n_subjects, 7)


class TheLawItselfCanFail(unittest.TestCase):
    """FAIL CONTROL: a common denominator must be caught."""

    def test_one_population_for_all_is_caught(self) -> None:
        same = {"HAB060": 7, "HAB061": 7, "HAB062": 7, "HAB063": 7}
        self.assertEqual(len(set(same.values())), 1,
                         "проба обязана нести ОДНО число на все правила")


if __name__ == "__main__":
    unittest.main()
