"""THE CONSTRUCTION PLAN: THE RESUME POINTER JUMPED OVER A PHASE.

REPRODUCED (measured 11.08.2026, `/tmp/wiring/y1.py`, `_plan_receipt`
directly, three phases, the second one wrote and was NOT accepted):

    phase 1 did NOT write               -> resume_from=1  "stopped at phase #1 b"
    phase 1 WROTE, not ACCEPTED         -> resume_from=2  "stopped at phase #2 b"
                                                       ^^^^^^^^^^^^^^^^^^^
The phase that STOPPED the plan is the first one. The pointer says continue
from the SECOND, i.e. skip right over it. And the name in that same line
belongs to phase 1 (`steps[-1]`), while the number belongs to phase 2: the
line names "phase #2 b", where `b` is phase 1.

WHY IT HAPPENED THIS WAY — THE SAME SHAPE AS THE WHOLE SERIES. The
`_run_plan` loop stops on `ok`, while `resume` is computed from `committed`,
and nothing forces these two notions of "done" to coincide. `_plan_step`
SPLITS them apart on purpose and correctly (a write can be committed and NOT
accepted — a violated postcondition in `report` mode), but downstream one
substitutes for the other.

WHAT THIS COSTS. A phase that wrote into the model and was not accepted is
the one case where CONTINUE and REPEAT are equally wrong: repeating
duplicates what was already built, skipping leaves a violated postcondition
in the building and says nothing about it. This case needs the author's
DECISION, not a pointer, and a silent jump-over is the worst of the three
possible answers.

A SECOND FINDING FROM THE SAME RUN: on a refusal at the ZERO-th phase, the
receipt prints "phases 0..-1 already in the model" — a claim about a range
that does not exist.

A THIRD: phases the plan never reached are not named by number in the
report. `phases=3, steps=2` — the reader has to subtract it themselves, and
"never started" and "failed" have been different facts throughout this whole
marathon.
"""
from __future__ import annotations

import unittest

from kir import serving as S


def _step(index, name, ops, ok, committed):
    return {"index": index, "name": name, "ops": ops, "ok": ok,
            "committed": committed}


class ThePointerNeverSkipsTheFailedPhase(unittest.TestCase):

    def _receipt(self, steps, total, ok=False):
        return S._plan_receipt({"ok": ok, "message_ru": "x"},
                               list(steps), total)

    def test_a_phase_that_did_not_write_is_the_resume_point(self):
        block = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, False, False)],
            3)["plan"]
        self.assertEqual(block["resume_from"], 1)
        self.assertEqual(block["stopped_at"], 1)

    def test_a_phase_that_wrote_and_was_not_accepted_gets_no_pointer(self):
        """THE ONE CASE WHERE THE POINTER WOULD BE A LIE EITHER WAY.
        Repeating the phase duplicates what was built; skipping it leaves a
        violated postcondition in the building. It needs a DECISION, not a
        number."""
        block = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, False, True)],
            3)["plan"]
        self.assertEqual(block["stopped_at"], 1)
        self.assertNotIn("resume_from", block)
        self.assertEqual(block["needs_decision"], 1)

    def test_the_number_and_the_name_agree(self):
        """The line named "phase #2 b", where `b` is phase 1."""
        result = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, False, True)], 3)
        head = result["message_ru"].splitlines()[0]
        self.assertIn("№1", head)
        self.assertNotIn("№2", head)
        self.assertIn("b", head)

    def test_nothing_built_never_claims_a_range(self):
        """"phases 0..-1 already in the model" — a claim about a range that
        does not exist."""
        result = self._receipt([_step(0, "a", 2, False, False)], 3)
        self.assertNotIn("0..-1", result["message_ru"])
        self.assertEqual(result["plan"]["committed"], 0)

    def test_phases_never_started_are_counted_by_name(self):
        """"never started" and "failed" have been different facts
        throughout the whole marathon."""
        block = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, False, False)],
            5)["plan"]
        self.assertEqual(block["never_started"], 3)
        self.assertEqual(block["phases"], 5)
        self.assertEqual(len(block["steps"]), 2)

    def test_a_whole_plan_names_nothing_it_did_not_meet(self):
        """Labels that stand there always stop being read: a completed plan
        has neither a stopping point nor unrun ones."""
        block = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, True, True)],
            2, ok=True)["plan"]
        self.assertNotIn("resume_from", block)
        self.assertNotIn("stopped_at", block)
        self.assertNotIn("needs_decision", block)
        self.assertEqual(block["never_started"], 0)

    def test_the_counters_never_contradict_each_other(self):
        for steps, total in (
                ([_step(0, "a", 1, True, True)], 1),
                ([_step(0, "a", 1, False, False)], 4),
                ([_step(0, "a", 1, True, True), _step(1, "b", 1, False, True)], 2),
        ):
            block = self._receipt(steps, total)["plan"]
            self.assertEqual(
                block["never_started"], total - len(block["steps"]))
            self.assertLessEqual(block["committed"], len(block["steps"]))


if __name__ == "__main__":
    unittest.main()
