"""A RULE'S SILENCE MUST SURVIVE THE RECEIPT, NOT BE THE FIRST THING TRIMMED.

MEASUREMENT 20.08.2026, TOWER `13A-RD-AR-K2_v33` (2442 rooms, 15,323 walls,
`KUKAI_CHECKER_V2=1`), for whose sake this whole file was written::

    rules total 20 · SPOKE 9 · SILENT 11
    of the silent ones: 6 removed by the profile, 5 STARVED FOR INPUT
        HAB001 HAB010  no input «stair_landings_complete»
        HAB002         no input «apartments_are_dwellings»
        HAB011 HAB012  stairs exist, no measured geometry

    full brief verdict         2230 characters
    `_describe` requested      1600   ← LITERAL
    its own half's ceiling     2600   (`_VERDICT_TEXT_CAP`)
    trimmed to                 1602, lost 628

🔴 WHAT WAS ACTUALLY LOST — NOT THE FINDINGS. `render_verdict_brief` puts the «НЕ
ОЦЕНЕНО» block LAST, and the trim cuts the tail. This means **the louder a building's violations,
the more completely the account of what we did NOT look at disappears** — even though
the judge's own docstring demands that silence be printed LOUDER than the findings. On the tower
what survived was a single list of eleven codes; the REASONS for the five starved rules —
and their reason is exactly the address of the fix — did not arrive, not by a single letter.

And the ceiling was not small, it was NEVER ASKED FOR: 628 characters were being thrown away while
998 characters of its own budget went unused by anyone. Our named defect: the value
is declared in one place (2600, with a docstring about exactly this shape) and read
in another (1600) four hundred lines below.

TWO REMEDIES, AND THE SECOND DOES NOT REPLACE THE FIRST:

  * the budget is DERIVED from the ceiling minus the frame, not assigned as a literal;
  * the silence moves into the MACHINE field `rules_silent`. Prose is trimmable by
    construction — the field is not. This does not abolish the prose: there it exists for the human.

WHAT THIS FILE DOES NOT FIX, AND WHAT REMAINS A DEBT: the actual ORDER of lines inside
`design_check.render_verdict_brief` (silence last ⇒ eaten first).
That is someone else's territory, and it is cured there — by reserving budget for the silence block BEFORE
the finding examples spend it.

THE INPUT IS BUILT BY PROD CODE (form 27): the building is taken from the neighboring
`test_building_verdict_in_the_receipt.building()` — the very one the bundle
is checked with — and it is judged by the prod function `design_check.check_bundle`.
The decompile corpus is machine-local, so the tower does not appear here as a single
numeric assertion: it is the provenance of the measurement in this docstring, while the pins stand on
the mechanism.

Run: KUKAI_CHECKER_V2=1 venv/bin/python -m pytest \
        kir/tests/test_silence_survives_the_receipt.py -q
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KUKAI_CHECKER_V2", "1")
os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kir import design_check as dc                       # noqa: E402
from kir.checker.spatial_model import RuleStatus         # noqa: E402
from kir.tests.test_building_verdict_in_the_receipt import building  # noqa: E402
from kir.live import verdict as V                           # noqa: E402

#: The receipt's frame is the same shape that `_slice_head` assembles in prod.
#: Here it exists only so the preamble has some length; not a single assertion
#: in the file depends on its content.
HEAD = {"programs": 3, "ops": 30, "programs_evicted": 0,
        "built": 3, "dropped_from_pack": 0}


def _verdict(core: str = "Лестничная клетка"):
    return dc.check_bundle(building(core), building_id="проба")


class МолчаниеЕстьПолеАНеПроза(unittest.TestCase):

    def test_a_starved_rule_travels_with_its_reason(self):
        """A rule that stayed silent for a reason OTHER than removal travels by name and with a reason.

        The reason must EXIST: a rule that stays silent without a reason is indistinguishable from
        a rule that was simply forgotten and never called.
        """
        rows = V._silent_rules(_verdict())
        self.assertTrue(rows, "ни одного молчащего правила — предмет исчез")
        for row in rows:
            self.assertRegex(row["rule_id"], r"^HAB\d+$", row)
            self.assertTrue(row["reason"].strip(), row)
            self.assertNotEqual(row["reason"], "ПРИЧИНА НЕ НАЗВАНА", row)
            self.assertLessEqual(len(row["reason"]), V._SILENT_REASON_CAP, row)

    def test_suspended_is_a_different_fact_and_lives_in_a_different_field(self):
        """🔴 AN ACT OF DISTINCTION, NOT A RETELLING OF COVERAGE.

        A measurement on this same building: the core's room name changes the KIND of silence.
        For "Stairwell" — HAB001/HAB010 are EVALUATED (12 rules of 20);
        for "Storage room" — the same rules are REMOVED by the profile (10 of 20). The rules that
        starve for input are, in both cases, the SAME THREE.

        If the field simply retold "everything that is not evaluated", its composition
        would ride along with the removals — and the distinction between "the rule does not apply to
        this stage" and "the rule lacked input, and here is which one" would disappear.
        The first has nothing to fix; the second is the address of the work.

        🔴 WHY TWELVE, NOT THIRTEEN (29.08.2026). The numbers used to be 13/11,
        with TWO starving rules. `800394f` made HAB012 honest: the rule is no longer
        "evaluated" at ZERO compared flight pairs. The twelfth rule did not go
        anywhere — it MOVED from "judged" to "starving, and here is why", and
        the sum was preserved (12 + 5 removed + 3 starving = 20). That is why what is pinned
        here is the KIND of silence, not the count: the edit `13 -> 12` on its own would have been
        fitting the SHAPE to the number — exactly the move this whole file was written against.
        The order of the assertions below is also part of the instrument: if HAB012
        were returned to "evaluated at zero pairs", the assertion about the KIND
        of its silence must go red first, and only then the arithmetic.
        """
        stair, storage = _verdict("Лестничная клетка"), _verdict("Кладовая")

        # FIRST THE KIND OF SILENCE. The reason must EXIST and must be its OWN:
        # removal by the profile and starving for input are different facts, and a rule
        # that stayed silent for the second reason carries the address of the work, not "not applicable".
        for имя, вердикт in (("лестница", stair), ("кладовая", storage)):
            исход = {o.rule_id: o
                     for o in вердикт.report.coverage.outcomes}["HAB012"]
            self.assertEqual(исход.status, RuleStatus.NOT_EVALUATED, имя)
            self.assertTrue(исход.reason.strip(), имя)
            self.assertNotIn("suspended by stage profile", исход.reason, имя)
            self.assertNotIn("HAB012", вердикт.rules_suspended, имя)
            self.assertIn("HAB012",
                          {r["rule_id"] for r in V._silent_rules(вердикт)}, имя)

        # THEN THE COUNT, AND IT IS DERIVED, NOT PINNED. `rules_evaluated` is a second
        # carrier of the same fact as `outcomes`; if they diverge it must be
        # in red, not silently.
        for имя, вердикт in (("лестница", stair), ("кладовая", storage)):
            судило = sum(1 for o in вердикт.report.coverage.outcomes
                         if o.status is RuleStatus.EVALUATED)
            self.assertEqual(вердикт.rules_applied, судило, имя)
            голодает = {r["rule_id"] for r in V._silent_rules(вердикт)}
            self.assertEqual(вердикт.rules_applied
                             + len(вердикт.rules_suspended) + len(голодает),
                             вердикт.rules_total, имя)

        self.assertEqual(stair.rules_applied, 12, "материал уехал")
        self.assertEqual(storage.rules_applied, 10, "материал уехал")

        moved = set(storage.rules_suspended) - set(stair.rules_suspended)
        self.assertEqual(moved, {"HAB001", "HAB010"}, moved)

        starved_stair = {r["rule_id"] for r in V._silent_rules(stair)}
        starved_storage = {r["rule_id"] for r in V._silent_rules(storage)}
        self.assertEqual(starved_stair, starved_storage,
                         "состав голодающих поехал вслед за снятиями")
        self.assertFalse(starved_storage & set(storage.rules_suspended),
                         "снятое правило попало в поле голодающих")

    def test_the_receipt_carries_both_fields_apart(self):
        report = V._describe(_verdict(), HEAD, dc)
        self.assertIn("rules_silent", report)
        self.assertIn("rules_suspended", report)
        silent = {row["rule_id"] for row in report["rules_silent"]}
        self.assertFalse(silent & set(report["rules_suspended"]))
        # And the denominator adds up: judged + removed + starving == total.
        self.assertEqual(
            report["rules_evaluated"] + len(report["rules_suspended"])
            + len(silent), report["rules_total"])


class ОбрезНеИмеетВластиНадПолем(unittest.TestCase):
    """A FAIL CONTROL ON THE FILE'S MAIN ASSERTION.

    The assertion "the field survives the trim" is checked BY TRIMMING, not by faith
    in it: the brief verdict is replaced with text that is deliberately too long to fit, and
    the receipt must arrive trimmed — with the silence still in place.
    """

    def test_prose_is_cut_and_the_field_is_not(self):
        verdict = _verdict()
        expected = {row["rule_id"] for row in V._silent_rules(verdict)}
        with mock.patch.object(dc, "render_verdict_brief",
                               return_value="строка\n" * 4000):
            report = V._describe(verdict, HEAD, dc)
        self.assertIn("обрезано на", report["message_ru"])
        self.assertLessEqual(len(report["message_ru"]),
                             V._VERDICT_TEXT_CAP + 64)
        self.assertEqual({row["rule_id"] for row in report["rules_silent"]},
                         expected, "обрез съел поле — лекарство не работает")


class БюджетВыводитсяАНеНазначается(unittest.TestCase):

    def test_the_brief_is_given_the_budget_its_half_actually_has(self):
        """🔴 A PIN AGAINST THE RETURN OF THE LITERAL, AND IT CAN GO RED.

        This used to be `limit=1_600` against a half-ceiling of 2600. The pin catches
        EXACTLY this: the budget must be derived from the ceiling minus the frame —
        which means it is strictly greater than the old literal on any building whose
        frame is under a thousand characters.
        """
        verdict = _verdict()
        seen: dict = {}
        real = dc.render_verdict_brief

        def spy(report, *, limit):
            seen["limit"] = limit
            return real(report, limit=limit)

        with mock.patch.object(dc, "render_verdict_brief", side_effect=spy):
            V._describe(verdict, HEAD, dc)

        frame = len(V._preamble(HEAD)) + sum(
            len(line) + 1 for line in V._waiver_block(verdict, dc))
        self.assertEqual(seen["limit"],
                         V._VERDICT_TEXT_CAP - frame - 1
                         - V._CUT_SIGNATURE_RESERVE)
        self.assertGreater(seen["limit"], 1_600,
                           "бюджет снова не дотягивает до собственного потолка")

    def test_a_heavy_frame_cannot_starve_the_verdict_to_a_headline(self):
        """A floor on the budget: the frame has no right to eat the entire verdict.

        A control on a degenerate input — the frame is deliberately larger than the ceiling.
        Without the floor, `limit` would go to zero or negative, and the verdict
        would collapse into a header: "no violations shown" would become
        indistinguishable from "there are no violations".
        """
        verdict = _verdict()
        seen: dict = {}
        real = dc.render_verdict_brief

        def spy(report, *, limit):
            seen["limit"] = limit
            return real(report, limit=limit)

        with mock.patch.object(V, "_preamble", return_value="х" * 9_000), \
                mock.patch.object(dc, "render_verdict_brief", side_effect=spy):
            V._describe(verdict, HEAD, dc)
        self.assertEqual(seen["limit"], V._BRIEF_FLOOR)


if __name__ == "__main__":
    unittest.main()
