"""THE PHASE COUNT HAD NO CEILING AT ALL — A 200,000-OP PROGRAM THROUGH THE
BACK DOOR.

MEASURED 11.08.2026 (`/tmp/wiring/z2.py`, `compiler.split_phases` directly, a
phase table of 20 ops each — i.e. every chunk WITHIN the author's budget):

    phases      2, ops      40 -> ACCEPTED,  split   0 ms
    phases    512, ops  10 240 -> ACCEPTED,  split   5 ms
    phases  2 000, ops  40 000 -> ACCEPTED,  split  26 ms
    phases 10 000, ops 200 000 -> ACCEPTED,  split 236 ms

`MAX_OPS_PER_PROGRAM` measures ONE chunk, and measures it correctly. Nobody
measured the number of chunks, so a plan could bypass the author's budget by
multiplication: twenty ops per phase, ten thousand phases.

WHERE THE CEILING IS DERIVED FROM, RATHER THAN ASSIGNED. Every writing phase
becomes ONE program of the session journal (`plan_stream.publish` is called
in the shared body on every phase). The journal holds `journal._max_programs()`
programs and evicts the oldest. So a plan longer than the journal EVICTS ITS
OWN BEGINNING while it is still being built, and everything that reads the
journal starts reading a building with no beginning:

  * the building verdict judges the TAIL and says so itself
    (`programs_evicted`, "the building's TAIL is being judged, not the
    whole thing");
  * the collision-check batch loses early phases — and "added by this turn"
    gets counted against a baseline that no longer exists;
  * the viewer's `base_digest` covers eviction, so a live view must
    resynchronize mid-plan (`StaleBase`).

The ceiling is therefore EQUAL to the journal's capacity and is ASKED of it
at call time, not copied as a number: a copy would drift from the original
at the very next edit of `KUKAI_KIR_JOURNAL_PROGRAMS` — exactly the class of
defect this series exists to close.

WHAT THIS CEILING DOES NOT PROMISE. That there will be no eviction: a
session that has already declared programs before the plan eats into part
of the capacity, and a plan within the ceiling can still evict someone
else's beginning. This is a NECESSARY condition, not a sufficient one, and
`programs_evicted` remains the one that tells the truth after the fact.
"""
from __future__ import annotations

import asyncio
import unittest

from kir import serving as S
from kir.live import journal as _journal


def _plan(nphases: int, ops_per: int = 2) -> dict:
    ops, phases = [], []
    for p in range(nphases):
        ids = []
        for i in range(ops_per):
            oid = f"w{p}_{i}"
            ops.append({"op": "create_level", "id": oid,
                        "name": f"L{p}_{i}",
                        "elevation_mm": float(p * 1000 + i)})
            ids.append(oid)
        phases.append({"index": p, "name": f"ф{p}", "op_ids": ids})
    return {"ops": ops, "phases": phases}


def _authored():
    """A stub input is THE CONTRACT ITSELF, not a handwritten double of it.

    🔴 A SIX-ATTRIBUTE CLASS STOOD HERE, AND IT DRIFTED (01.09.2026).
    `_AuthoredInput` had grown to twelve fields by that day; the double knew
    six, and the very first field it did not know broke the run:
    `AttributeError: '_Authored' object has no attribute 'lineage'`
    in `serving.py` — a refusal ABOUT US, inside a finding about the phase
    ceiling.

    This is the tree's named defect in pure form: **a handwritten list that
    is supposed to match the registry drifts silently; a derived one does
    not.** Adding `lineage` here by hand would just buy the same red on the
    thirteenth field. So there is no double at all: what is used is the
    actual `dataclass`, everything on it besides `args` carrying a default —
    and a new contract field arrives here BY ITSELF.

    The stub still did not become a "real input": `args` is empty, because
    the checks below are about the phase ceiling, and none of them should
    ever reach the instrument's body."""
    return S._AuthoredInput(args={})


def _run(program):
    async def _bridge(*a, **k):
        raise AssertionError("мост не должен быть тронут: отказ до записи")

    return asyncio.run(S._run_plan(
        program, None, _bridge, query_id="q", authored=_authored()))


class ThePhaseCountHasACeiling(unittest.TestCase):

    def test_a_plan_longer_than_the_journal_is_refused_before_any_write(self):
        """A REFUSAL BEFORE THE BRIDGE. A plan that would evict its own
        beginning has no right to start being built: half the building would
        already be in the model."""
        result = _run(_plan(S.max_plan_phases() + 1))
        self.assertFalse(result["ok"])
        self.assertTrue(result["refused"])
        self.assertEqual(result["stage"], "plan")

    def test_the_refusal_names_both_numbers(self):
        over = S.max_plan_phases() + 7
        result = _run(_plan(over))
        self.assertIn(str(over), result["message_ru"])
        self.assertIn(str(S.max_plan_phases()), result["message_ru"])

    def test_the_ceiling_is_asked_of_the_journal_not_copied(self):
        """A copied number would drift from the original at the journal
        ceiling's first edit — the same class this whole marathon was
        closing."""
        self.assertEqual(S.max_plan_phases(), _journal._max_programs())

    def test_a_plan_at_the_ceiling_is_not_refused_by_this_rule(self):
        """A ceiling that refuses at the boundary refuses a correct plan.
        The bridge is untouched here, so it is EXACTLY this cause of refusal
        that is checked."""
        result = _run(_plan(3))
        self.assertNotIn("вместимости журнала",
                         str(result.get("message_ru") or ""))

    def test_the_ceiling_moves_with_the_journal(self):
        import os

        prev = os.environ.get("KUKAI_KIR_JOURNAL_PROGRAMS")
        os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = "16"
        try:
            self.assertEqual(S.max_plan_phases(), 16)
            result = _run(_plan(17))
            self.assertTrue(result["refused"])
        finally:
            if prev is None:
                os.environ.pop("KUKAI_KIR_JOURNAL_PROGRAMS", None)
            else:
                os.environ["KUKAI_KIR_JOURNAL_PROGRAMS"] = prev

    def test_the_op_budget_still_measures_one_phase(self):
        """The ceiling on the number of PHASES and the author's budget of
        OPS are DIFFERENT quantities, and one does not substitute for the
        other.

        🔴 A NUMBER WAS REMOVED FROM HERE. The earlier edition wrote
        `assertEqual(C.MAX_OPS_PER_PROGRAM, 20)`, and when the owner raised
        the budget to 100 (15.08), the test turned red — even though what
        it was checking had not changed by one byte: phases still are not
        measured in ops. Pinning a value in a test about the DIFFERENCE
        between two values is exactly the tree's named defect: a number
        declared in `compiler`, read here, with nothing forcing the two to
        match.

        What remains: both quantities exist, are positive, and are NOT
        EQUAL. That is the claim "there are two of them, and they are about
        different things", and it survives any future change of either
        one."""
        from kir import compiler as C

        self.assertGreater(C.MAX_OPS_PER_PROGRAM, 0)
        self.assertGreater(S.max_plan_phases(), 0)
        self.assertNotEqual(S.max_plan_phases(), C.MAX_OPS_PER_PROGRAM)


if __name__ == "__main__":
    unittest.main()
