"""THE GOLDEN ROAD ACROSS THE THREE AXES: a real program -> the compiler ->
the verdict.

WHY THIS FILE EXISTS, AS OF THE 19.08.2026 MEASUREMENT. The owner declared
the BIM-Edit axes — geometry/meaning/topology, SEPARATELY — as the
criterion for going to production. A report on them has been built
(`design_check.axis_report`), and until today NOT A SINGLE end-to-end test
checked it: `test_three_axes_report.py` feeds it hand-made `_Row`,
`_Finding`, and `_Verdict` objects, assembled by hand inside the test
body. In other words, what was being checked was the report's
bookkeeping, not what it says about a real building.

🔴 THE MAIN ASSERTION OF THIS FILE IS NOT "THERE ARE NO FINDINGS" BUT
"SILENCE IS NAMED". A silent rule looks clean: it has not a single
finding, and in any summary it is indistinguishable from a rule that spoke
up and found nothing. Hence the canon's law — "the less we know about the
building, the cleaner it looks". That is why the test goes red when the
system DOES NOT KNOW, not only when it is wrong.

WHAT IS MEASURED AND PINNED HERE, BY NUMBER:

    building without a stair   judged 11 of 20, 0 violations, 9 silent
    building WITH a stair      judged 12 of 20, 0 violations, 8 silent

🔴 THESE NUMBERS CHANGED ON 22.08.2026, AND THE FILE'S FINDING FLIPPED. It
used to be 13 and 12, and the file recorded: "a richer building says LESS"
— the stair woke `HAB012` and muted `HAB001`/`HAB010`.

The reason for the change is a fix to the judge on that same day.
`stair_landings_complete` was a CONJUNCTION, vacuously true at zero
stairs: a set difference is empty when the left side is empty. On a real
building (MNVNK) this cost 23 BLOCKING findings of "a floor hangs with no
connection to the ground", and not one of them was a fact about the
building — there are 24 stairs there, and our own extraction discarded
all 24 of them. The precondition now requires that a stair EXIST, and a
building without a stair honestly mutes the same two rules AT ONCE,
rather than only after a stair is added.

Hence the new shape of the finding, and it is not weaker than the old
one: **11 -> 12, a richer building says MORE**, while the two
topological rules stay silent in BOTH cases and for DIFFERENT reasons —
"there isn't a single stair" versus "stairs exist, but the landings
aren't marked out". The file's law has not changed because of this: any
change in the makeup of who spoke up must be named, not slip past
silently. And it was named.

WHAT THIS FILE DOES NOT DO:

  * it does not go to Revit. `check_bundle` is a self-check
    (`ModelSource.PROGRAM`): what is judged is what the PROGRAM DECLARED,
    and the verdict carries this distinction within itself;
  * it does not require that there be no silent rules. Six of the eight
    are silent by a NAMED decision of the stage profile ("intent stage"),
    and turning that into red would mean demanding of the intent
    something that, by construction, it does not carry;
  * it does not judge the building. Zero violations here is a property
    of the exemplary building, not proof that the rules are strict:
    strictness is checked by the mutation tests.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_gold_path_queue.jsonl"))
os.environ.setdefault("KUKAI_CHECKER_V2", "1")

from kir import design_check as D  # noqa: E402

_L1 = {"by": "name", "value": "Этаж 1"}
_L2 = {"by": "name", "value": "Этаж 2"}
_WT = {"by": "name", "value": "Кирпич 250"}
_DOOR = {"by": "name", "value": "Одинарная-Щитовая"}
_WIN = {"by": "name", "value": "Фиксированное"}

#: A CLOSED list of silence reasons. No default: a reason this list does
#: not name fails the test, rather than joining some other bucket
#: silently. One word for three different troubles is not a measurement,
#: and this tree has already paid for that mistake once.
_SUSPENDED = "suspended by stage profile"
_MISSING_MARKERS = (
    "нет входа",                 # the input is declared and not supplied
    "no stair footprints",       # nothing to compare
    "no classified",             # no objects of the needed class
    "unknown ≠ pass",            # the object exists, the measure was not taken
    "degenerate model",          # a degenerate model
    # ── added on 20.08.2026 DELIBERATELY, as this list itself requires ──
    # The HAB011 reason stopped being a constant: it names WHAT was judged
    # against and what was missing (three values out of four are live —
    # 24 stairs out of 24, the flight width is missing). The old
    # `unknown ≠ pass` marker does not appear in the new text, and rightly
    # so: it claimed "not a single measure was taken", while now two out
    # of three have been. The KIND stays THE SAME though — the object
    # exists, the measure is incomplete.
    "нет вовсе",                 # not a single object exists (stairs, walls)
    "величина не прочитана",     # the object exists, NOTHING was taken
    "НЕ ХВАТИЛО",                # the object exists, PARTIALLY taken
    "выведенные связи",          # the object was replaced by our own inference
    # ── added on 29.08.2026 DELIBERATELY, as this list itself requires ──
    # The HAB012 reason stopped being about FOOTPRINTS and became about
    # PAIRS. The old `no stair footprints` marker claimed "there are no
    # footprints on the plan", and this was wrong about the subject: the
    # rule does not compare footprints, it compares PAIRS of adjacent
    # served levels, and it stays silent most often when the footprints
    # ARE THERE — when there is only one served level and no pair forms.
    #
    # Before the `800394f` fix, coverage was counting STAIRS, so one
    # stair printed as `EVALUATED(n=1), 0 нарушений` — "looked and it's
    # clean" at zero comparisons. The counter was switched to the same
    # iteration the rule itself walks; the text for emptiness changed
    # along with it.
    #
    # The KIND is THE SAME — there is no object to compare — but the
    # trouble is different, and merging them into the old marker would
    # mean sending the reader to look for footprints where what is
    # missing is a second stair.
    "сравнивать нечего и не с чем",   # not a single flight with a footprint exists
    "ни одной пары",                  # footprints exist, no level pair came out of them
)

#: 🔴 A THIRD KIND, WHICH DID NOT EXIST BEFORE THERE WAS CAPTURE
#: (20.08.2026). "We did not ask" and "we asked, and the building
#: answered NO" are not shades of one trouble but opposite statements: the
#: first is about us, the second is about the building. As long as
#: `WALL_STRUCTURAL_SIGNIFICANT` never arrived, the second case did not
#: exist and two buckets were enough. Now the parameter arrives for 7845
#: of 10 646 walls (all zero), and recording such silence under
#: `missing_input` would be exactly the "one word for three different
#: troubles" that this list was written against.
_BUILDING_FACT_MARKERS = (
    "ЗДАНИЕ ОТВЕТИЛО НЕТ",
    "смешанный вход",
)


def _classify(reason: str) -> str:
    """`suspended` | `missing_input` | `building_fact` — either a refusal
    with a reason."""
    if reason.startswith(_SUSPENDED):
        return "suspended"
    if any(marker in reason for marker in _BUILDING_FACT_MARKERS):
        return "building_fact"
    if any(marker in reason for marker in _MISSING_MARKERS):
        return "missing_input"
    raise AssertionError(
        f"молчание с НЕОПОЗНАННОЙ причиной: {reason!r}. Закрытый список причин "
        f"её не называет — добавь её туда ОСОЗНАННО или почини правило. "
        f"Молча присоединить её к чужому ведру нельзя: одно слово на разные "
        f"беды перестаёт быть замером")


def _wall(oid: str, p0, p1, *, top: bool = True) -> dict:
    wall = {"op": "create_wall", "id": oid, "p0_mm": p0, "p1_mm": p1,
            "level": _L1, "type": _WT, "height_mm": 3000}
    if top:
        # `top_level` here is NOT decoration: without it, a wall's top is
        # set by a number and stops following a level
        # (`ParamSpec.omission_transfers`), and the top-attachment
        # obligation is never checked at all. The exemplary building must
        # be exemplary in this respect too.
        wall["top_level"] = _L2
    return wall


def _body() -> dict:
    """The body: two levels, a closed box, a partition, two rooms."""
    return {"ir_version": "1.0", "intent": "золотая дорога — тело", "ops": [
        {"op": "create_level", "id": "lv1", "name": "Этаж 1", "elev_mm": 0},
        {"op": "create_level", "id": "lv2", "name": "Этаж 2", "elev_mm": 3000},
        _wall("wS", [0, 0], [8000, 0]),
        _wall("wE", [8000, 0], [8000, 6000]),
        _wall("wN", [8000, 6000], [0, 6000]),
        _wall("wW", [0, 6000], [0, 0]),
        _wall("wP", [4000, 0], [4000, 6000]),
        {"op": "create_floor", "id": "fl", "level": _L1,
         "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]},
        {"op": "create_door", "id": "d1", "offset_mm": 3000, "symbol": _DOOR,
         "host": {"by": "ref", "value": "wP"}},
        {"op": "create_door", "id": "d2", "offset_mm": 2000, "symbol": _DOOR,
         "host": {"by": "ref", "value": "wS"}},
        {"op": "create_window", "id": "g1", "offset_mm": 3000, "symbol": _WIN,
         "host": {"by": "ref", "value": "wW"}},
        {"op": "create_window", "id": "g2", "offset_mm": 3000, "symbol": _WIN,
         "host": {"by": "ref", "value": "wE"}},
        {"op": "create_room", "id": "r1", "xy": [2000, 3000], "level": _L1,
         "name": "Жилая комната", "number": "1"},
        {"op": "create_room", "id": "r2", "xy": [6000, 3000], "level": _L1,
         "name": "Кухня", "number": "2"},
    ]}


def _stairs() -> dict:
    """A stair is a SEPARATE link of the bundle, and that is a law, not a
    style choice.

    `create_stairs` owns its own transactions (`StairsEditScope`), so
    alongside walls in ONE program it is illegal (`KIR-L002`), while it is
    entirely legal as its own link. The unit of a building is the bundle.
    """
    return {"ir_version": "1.0", "intent": "золотая дорога — лестница", "ops": [
        {"op": "create_stairs", "id": "st1", "p0_mm": [1000, 1000],
         "p1_mm": [1000, 4000], "base_level": _L1, "top_level": _L2,
         "width_mm": 1200},
    ]}


class GoldPathAxes(unittest.TestCase):
    """A bundle of programs -> a verdict -> a three-axis report, without
    Revit."""

    def _report(self, bundle, building_id):
        verdict = D.check_bundle(bundle, building_id=building_id)
        self.assertIs(verdict.source, D.ModelSource.PROGRAM,
                      "вердикт обязан нести, что это САМОПРОВЕРКА, а не чтение")
        return verdict, D.axis_report(verdict)

    # -- the law this file was written for --------------------------------

    def test_every_silence_carries_a_named_reason(self):
        """Silence with no reason is worse than a finding: it is
        indistinguishable from cleanliness."""
        for label, bundle in (("тело", [_body()]),
                              ("тело+лестница", [_body(), _stairs()])):
            _verdict, rows = self._report(bundle, f"gold_{label}")
            silent = [(r.axis, rid, why) for r in rows for rid, why in r.silent]
            self.assertTrue(silent, "нечего проверять: молчащих правил ноль")
            for axis, rule_id, reason in silent:
                with self.subTest(where=label, axis=axis, rule=rule_id):
                    self.assertTrue(reason.strip(),
                                    f"{rule_id} молчит и НЕ ГОВОРИТ почему")
                    self.assertNotEqual(reason, "причина не названа",
                                        f"{rule_id}: заглушка вместо причины")
                    self.assertIn(_classify(reason),
                                  ("suspended", "missing_input", "building_fact"))

    def test_no_axis_is_judged_by_nobody(self):
        """An axis with not a single ruling rule is not "clean" — it is
        the absence of an answer.

        There, the report prints a dash, not 100%, and that is already
        pinned by its own test. What is pinned here is something else: on
        the EXEMPLARY building, there should be no such axis at all —
        otherwise the golden road is green by construction, because
        nobody asked anything.
        """
        for label, bundle in (("тело", [_body()]),
                              ("тело+лестница", [_body(), _stairs()])):
            _verdict, rows = self._report(bundle, f"gold_{label}")
            for row in rows:
                with self.subTest(where=label, axis=row.axis):
                    self.assertTrue(
                        row.judged,
                        f"ось {row.axis}: не судил НИКТО. Доли у такой оси нет "
                        f"вообще, и зелёный отчёт по ней ничего не значит")

    # -- pinned numbers -----------------------------------------------------

    def test_the_counts_are_pinned_so_a_rule_going_quiet_is_caught(self):
        """Measured on 19.08. A rule that FELL SILENT because of a fix
        must fail this test.

        The numbers are not "approximate": silence has no findings, so a
        rule falling silent will not show up in any violation counter —
        only here.
        """
        _v, rows = self._report([_body()], "gold_body")
        # 13 -> 11 and 7 -> 9 (22.08.2026): `stair_landings_complete`
        # stopped being vacuously true at zero stairs. The breakdown of
        # this change is in the header.
        self.assertEqual(sum(len(r.judged) for r in rows), 11)
        self.assertEqual(sum(len(r.violated) for r in rows), 0)
        self.assertEqual(sum(len(r.silent) for r in rows), 9)
        self.assertEqual(sum(r.total for r in rows), 20)

        _v2, rows2 = self._report([_body(), _stairs()], "gold_body_stairs")
        # 🔴 12 -> 11 and 8 -> 9 (29.08.2026), AND THIS IS NOT A REGRESSION
        # BUT A LIE LIFTED. The twelfth "ruling" rule was HAB012 at ZERO
        # compared pairs: coverage was counting stairs, and one stair gave
        # EVALUATED(n=1), 0 violations. After the counter fix (`800394f`)
        # it honestly stays silent with a named reason, and the count of
        # those who spoke up drops by one — exactly the one that, in
        # substance, was never really there.
        #
        # This test's trap does not depend on the change and still
        # stands: "it got quieter" reads as "it got cleaner". Here it got
        # quieter BECAUSE we stopped counting the undone, and the
        # breakdown must travel right alongside the number.
        self.assertEqual(sum(len(r.judged) for r in rows2), 11)
        self.assertEqual(sum(len(r.violated) for r in rows2), 0)
        self.assertEqual(sum(len(r.silent) for r in rows2), 9)

    def test_a_richer_building_changes_WHO_speaks_and_that_is_named(self):
        """🔴 THE 19.08 FINDING FLIPPED ON 22.08, AND THIS IS RECORDED, NOT
        ERASED.

        It used to be: a stair LOWERED the count of ruling rules, 13 -> 12,
        because `HAB001`/`HAB010` require `stair_landings_complete`, and a
        stair without landings has none. Now: 11 -> 12, a stair RAISES it.
        The reason is not the stair, but the fact that the precondition
        stopped being vacuously true at zero stairs (the breakdown is in
        the file's header, the cost was 23 false BLOCKING findings on
        MNVNK).

        The trap this test closes does not depend on the direction of the
        change: "it got quieter" reads as "it got cleaner". So what is
        checked is NOT THE DIRECTION but the law: every silence must be
        `missing_input` with a named input, and a change in who spoke up
        must be explainable, not silent.
        """
        _v1, rows1 = self._report([_body()], "gold_body")
        _v2, rows2 = self._report([_body(), _stairs()], "gold_body_stairs")
        before = {rid for r in rows1 for rid, _ in r.silent}
        after = {rid for r in rows2 for rid, _ in r.silent}
        # 🔴 THE EXPECTATION WAS FIXED ON 29.08.2026, AND IT HAD BEEN
        # STANDING ON THE RULE'S LIE.
        #
        # Here stood: `before - after == {"HAB012"}` — "a stair must wake
        # the flight-footprint comparison". This held, but not because the
        # comparison actually took place: coverage was counting STAIRS,
        # and ONE stair gave `EVALUATED(n=1)` at ZERO compared pairs. The
        # rule compares pairs of ADJACENT served levels, and one stair
        # serves one level, so no pair forms.
        #
        # In other words, the test was pinning exactly the lie this whole
        # file was written against: "looked and it's clean" instead of
        # "there was nothing to compare". The counter fix (`800394f`)
        # exposed this, and BOTH sides need fixing — adding the reason to
        # the closed list ABOVE and rewriting the expectation HERE.
        #
        # What is checked now is stronger than before: one stair does NOT
        # wake the rule, but it DOES CHANGE the reason for its silence.
        # The difference in reasons is itself the observable fact, and it
        # is exactly the one this file exists for. The positive side
        # ("two stairs on adjacent levels do wake the rule") is covered on
        # the judge's side: `checker/tests`, measured during the fix —
        # one stair gives `not_evaluated(0)`, two adjacent ones give
        # `evaluated(1)`.
        self.assertEqual(after - before, set(),
                         "новых молчащих быть не должно: те же правила "
                         "молчат и без лестницы")
        self.assertEqual(
            before - after, set(),
            "одна лестница НЕ обязана будить сравнение пар: обслуженный "
            "уровень один, пара не образуется. Если здесь снова появился "
            "HAB012 — счётчик покрытия вернулся к счёту ЛЕСТНИЦ вместо ПАР")

        # THE SAME CHECK AS BELOW FOR HAB001/HAB010, AND FOR THE SAME
        # REASON: one rule stays silent over DIFFERENT troubles, and the
        # difference decides what to fix.
        _why1 = {rid: why for r in rows1 for rid, why in r.silent}
        _why2 = {rid: why for r in rows2 for rid, why in r.silent}
        self.assertIn("HAB012", _why1)
        self.assertIn("HAB012", _why2)
        self.assertNotEqual(
            _why1["HAB012"], _why2["HAB012"],
            "без лестницы и с одной лестницей HAB012 молчит по РАЗНЫМ "
            "причинам; одинаковый текст означал бы, что беды слиты")
        self.assertIn("ни одной пары", _why2["HAB012"],
                      "с лестницей причина — не образовалась пара уровней")

        # 🔴 THE MAIN POINT: ONE AND THE SAME RULE STAYS SILENT FOR
        # DIFFERENT REASONS, and the difference decides what to fix.
        # Collapsing them into "no input" would mean sending the reader to
        # mark out landings where there isn't a stair at all.
        why1 = {rid: why for r in rows1 for rid, why in r.silent}
        why2 = {rid: why for r in rows2 for rid, why in r.silent}
        for rule_id in ("HAB001", "HAB010"):
            with self.subTest(rule=rule_id):
                self.assertEqual(_classify(why1[rule_id]), "missing_input")
                self.assertEqual(_classify(why2[rule_id]), "missing_input")
                self.assertIn("НЕТ НИ ОДНОЙ", why1[rule_id],
                              "без лестницы причина — её отсутствие")
                self.assertIn("разметк", why2[rule_id],
                              "с лестницей причина — неразмеченные площадки")
                self.assertNotEqual(why1[rule_id], why2[rule_id])

    # -- a building's door is A BUNDLE, and a lone program lies differently --

    def test_one_program_of_a_batch_judged_alone_reads_as_degenerate(self):
        """Measured 19.08 on a REAL program from the live benchmark.

        `check_ops` over one link of a multi-program building gave **0
        rules out of 20**, all twenty silent with the reason
        `degenerate model (no rooms)` — even though the link holds 20
        `create_room` operations and 56 walls. The statement is true (the
        levels were created by a DIFFERENT link, and without them not a
        single room can be assembled) and devastatingly misleading if
        read as a verdict on the building.

        The test pins BOTH facts at once: the single link is degenerate,
        the bundle is not. Without the second half, someone would "fix"
        the first one green.
        """
        alone = D.check_ops(_body(), building_id="одно звено")
        rows_alone = D.axis_report(alone)
        self.assertEqual(sum(len(r.judged) for r in rows_alone), 11,
                         "тело самодостаточно: оно САМО создаёт свои уровни")

        # And a link whose levels were created by another link is
        # degenerate — and says so.
        headless = {"ir_version": "1.0", "intent": "звено без уровней",
                    "ops": [op for op in _body()["ops"]
                            if op["op"] != "create_level"]}
        rows_headless = D.axis_report(
            D.check_ops(headless, building_id="звено без уровней"))
        self.assertEqual(sum(len(r.judged) for r in rows_headless), 0)
        for row in rows_headless:
            for _rid, why in row.silent:
                self.assertEqual(_classify(why), "missing_input")

        # The same trouble, cured by the bundle: the levels arrive via
        # their own link.
        datums = {"ir_version": "1.0", "intent": "звено отметок", "ops": [
            {"op": "create_level", "id": "lv1", "name": "Этаж 1", "elev_mm": 0},
            {"op": "create_level", "id": "lv2", "name": "Этаж 2",
             "elev_mm": 3000},
        ]}
        _v, rows_bundle = self._report([datums, headless], "пачка")
        self.assertGreater(sum(len(r.judged) for r in rows_bundle), 0,
                           "пачка обязана собрать то, что звено собрать не может")


if __name__ == "__main__":
    unittest.main()
