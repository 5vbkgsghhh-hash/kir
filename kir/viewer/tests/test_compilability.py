"""The compilability indicator. What is checked first is ITS OWN HONESTY.

A lamp that does not know it never looked is the same defect as "the
witness signs an unread axis", the one that made 10.08 redo six checks, only
sized to the whole product. So the tests below hold not "green is green" but
"gray does not pass itself off as green" and "the blind-spot list cannot be
removed".
"""

import unittest

from kir.viewer import compilability as C


#: How many walls go in one row before the row wraps to the right.
#:
#: 🔴 THE LAYOUT WAS CHANGED FROM A LINE TO A GRID ON 28.08.2026, AND THIS
#: IS A RIG FIX, NOT A WEAKENING OF THE ASSERTION. Walls used to run in a
#: single line, `y = i * 1000`, and at the authored budget of 100 000, the
#: sixteen-thousandth one went past the scene's limit (16 000 000 mm): the
#: check "exactly the budget PASSES" got `KIR-T002: coordinate past the
#: scene limit` and declared it a budget failure.
#:
#: The same class of defect that already cost this file two red days on
#: 20.08: the rig carried a value pinned to the PREVIOUS cap
#: (20 -> 1000 -> 100 000), and it broke from someone else's decision,
#: saying nothing about its own subject. A grid does not depend on the cap:
#: no matter how much it grows, the walls stay inside the scene.
_ROW = 15_000


def _program(count, *, ok=True):
    return {"ir_version": "1.0", "ops": [
        {"op": "create_wall", "id": f"w{i}",
         "p0_mm": [(i // _ROW) * 6000, (i % _ROW) * 1000],
         "p1_mm": [(i // _ROW) * 6000 + 5000, (i % _ROW) * 1000],
         "height_mm": 3000,
         "level": ({"by": "name", "value": "L1"} if ok else "не селектор")}
        for i in range(count)]}


class TristateNeverCollapses(unittest.TestCase):

    def test_nothing_to_judge_is_unknown_and_not_ok(self):
        """An empty journal is NOT "the building compiles". Merging these
        two states means showing green where no one looked."""
        verdict = C.check_programs([])
        self.assertEqual(verdict.state, "unknown")
        self.assertTrue(verdict.reason)
        self.assertNotEqual(verdict.state, "ok")

    def test_unknown_says_so_in_russian_too(self):
        payload = C.check_programs([]).to_dict()
        self.assertIn("НЕ", payload["state_ru"])

    def test_a_valid_program_is_ok(self):
        self.assertEqual(C.check_programs([_program(3)]).state, "ok")

    def test_a_typed_failure_is_refused_and_names_its_code(self):
        """A refusal must name a reason: a silent rollback is
        indistinguishable from a breakage."""
        verdict = C.check_programs([_program(2, ok=False)])
        self.assertEqual(verdict.state, "refused")
        self.assertTrue(verdict.refusals[0]["text"])


class BudgetsAreTheOnesTheCompilerHolds(unittest.TestCase):

    def test_the_authored_budget_is_held_at_its_own_edge(self):
        """The authored budget measures a program WRITTEN BY the model:
        exactly the budget passes, budget plus one gets refused with
        `KIR-L001`.

        🔴 THE LITERAL WAS REMOVED 20.08.2026, AND THIS IS A FIX, NOT A
        WEAKENING. `assertEqual(MAX_OPS_PER_PROGRAM, 20)` used to stand
        here — A SECOND CARRIER of a value that lives in `compiler.py`. The
        caps were raised by the owner's decision on 18.08 (20 -> 1000), the
        test turned red with `20 != 1000` and **stood red for two days**,
        saying nothing about the subject it guards. The cost of red is not
        the defect it names, but the ones it hides while it stays red
        (shape 35).

        The assertion did not weaken here, it became MORE PRECISE: before,
        it checked "the budget equals twenty", now it checks "the boundary
        FIRES exactly where the compiler declared it". The first breaks
        from someone else's decision, the second only from a real defect.
        The registry's composition is guarded separately by the neighboring
        `test_budgets_are_published_not_reimplemented`.
        """
        from kir.compiler import MAX_OPS_PER_PROGRAM
        ok = C.check_programs([_program(MAX_OPS_PER_PROGRAM)])
        self.assertEqual(ok.state, "ok")
        over = C.check_programs([_program(MAX_OPS_PER_PROGRAM + 1)])
        self.assertEqual(over.state, "refused")
        self.assertIn("KIR-L001", over.refusals[0]["codes"])

    def test_bulk_budget_is_a_different_number_and_is_held(self):
        """The batch budget measures the MATERIALIZER CHUNK — a different
        budget for a different author. Mixing them would mean refusing an
        honest rebuild.

        THE DIFFERENCE OF THE TWO NUMBERS IS THE SUBJECT ITSELF, so it is
        asserted directly, and the value is not repeated: the entire value of
        the script and rebuild door lies in the MARGIN over the author's
        budget (form 32: the order "1000 everywhere" removed the boundary,
        not the invariant, and equalizing them would kill the capability
        rather than lift the constraint).
        """
        from kir.compiler import MAX_BULK_OPS, MAX_OPS_PER_PROGRAM
        self.assertGreater(MAX_BULK_OPS, MAX_OPS_PER_PROGRAM)
        over = C.check_programs([_program(MAX_BULK_OPS + 1)], bulk=True)
        self.assertEqual(over.state, "refused")
        self.assertIn("KIR-L001", over.refusals[0]["codes"])

    def test_budgets_are_published_not_reimplemented(self):
        """Numbers are taken FROM THE COMPILER. A local copy would silently drift."""
        from kir.compiler import (MAX_BULK_OPS, MAX_OPS_PER_PROGRAM,
                                       MAX_VALIDATED_OPS)
        budgets = C.check_programs([_program(1)]).budgets
        self.assertEqual(budgets["authored"], MAX_OPS_PER_PROGRAM)
        self.assertEqual(budgets["internal_bulk"], MAX_BULK_OPS)
        self.assertEqual(budgets["post_macro"], MAX_VALIDATED_OPS)


class BlindnessIsPartOfTheAnswer(unittest.TestCase):

    def test_blind_list_rides_on_every_verdict_including_the_green_one(self):
        """A green light must carry the list of what it did not look at —
        otherwise green reads as "everything was checked"."""
        for programs in ([], [_program(3)], [_program(2, ok=False)]):
            payload = C.check_programs(programs).to_dict()
            self.assertEqual(list(payload["blind"]), list(C.BLIND))
            self.assertTrue(payload["blind"])

    def test_roslyn_is_named_first_because_it_is_the_costliest_miss(self):
        self.assertIn("Roslyn", C.BLIND[0])

    def test_the_named_blind_spots_cover_the_gate_classes(self):
        """The blind-spot list is DATA, and it must cover the classes that
        the indicator physically cannot see."""
        blob = " ".join(C.BLIND)
        for token in ("Roslyn", "api_signatures", "bridge_reference_closure",
                      "приёмка", "клеши", "design_check", "бюджет"):
            self.assertIn(token, blob, token)

    def test_grounding_absence_is_stated_not_implied(self):
        """Without a document type snapshot the selectors are NOT checked.
        Showing this as "ok" would mean promising grounding that was never
        done."""
        verdict = C.check_programs([_program(3)])
        self.assertEqual(verdict.grounding, "not_checked")
        self.assertIn("НЕ ПРОВЕРЕНО", verdict.grounding_note)


class TheIndicatorNeverCostsTheTurn(unittest.TestCase):

    def test_it_does_not_raise_on_junk(self):
        """The indicator exists for the sake of the turn and has no right to drop it."""
        for junk in ([None], [42], ["строка"], [{"ops": "не список"}]):
            C.check_programs(junk)

    def test_missing_session_is_unknown_rather_than_an_exception(self):
        payload = C.check_session("нет-такого-устройства", "нет-документа")
        self.assertEqual(payload["state"], "unknown")
        self.assertTrue(payload["reason"])
