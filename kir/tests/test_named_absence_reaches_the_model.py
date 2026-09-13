"""A NAMED ABSENCE MUST REACH THE READER, OR IT DOES NOT EXIST.

A named absence is worth exactly what distinguishes it from a weak witness:
it says "nobody looked here." If it lives only in the registry, then from the
outside an op with an unchecked shape is indistinguishable from a checked
one — that is, honesty gets built that nobody will ever read.

🔴 MEASURED 19.08.2026, BY RUNNING THE PROD PATH, NOT BY GREP (grep answers
"is the line there," the question asked is "does it happen"):

    create_site_subregion   unwitnessed_axes = {}                    ← CLEAN
    create_building_pad     unwitnessed_axes = {'semantic': [...]}

For the sub-region, the named absence of SHAPE is declared, yet the receipt
shows a fully checked op. Of 16 ops with named absences, EIGHT were lost
entirely, and the table had exactly ONE consumer — the static
`audit_registry_coverage`. There was not a single live reader.

THE CAUSE IS DIFFERENT GRANULARITY. `unwitnessed_axes` judges by AXIS, the
named absence lives at the CLAUSE. An op with a dimensional obligation and a
named unverifiable shape INSIDE that same axis is indistinguishable, to the
axis instrument, from one fully checked.
"""
from __future__ import annotations

import unittest

from kir import serving, spec
from kir import translation_cert as tc


class TheTristateIsNotCollapsed(unittest.TestCase):
    """THREE OUTCOMES, AND COLLAPSING THEM BRINGS BACK THE SAME DISEASE.

    "Checked" · "not checked, and this is NAMED" · "nothing to judge by" —
    three different facts, each demanding its own action. One code for two
    outcomes is our named defect; here it would walk under the name of
    honesty.
    """

    def test_nothing_to_judge_is_not_all_clear(self):
        self.assertIsNone(tc.named_absences([]),
                          "пустая программа — «судить нечем», а не «чисто»")
        self.assertIsNone(tc.named_absences(None))

    def test_all_clear_is_an_assertion_not_a_silence(self):
        self.assertEqual(tc.named_absences(["create_wall"]), {},
                         "все опы проверены по таблице — это УТВЕРЖДЕНИЕ")

    def test_a_named_absence_carries_its_reason(self):
        got = tc.named_absences(["create_wall", "create_site_subregion"])
        self.assertIn("create_site_subregion", got)
        clause, why = got["create_site_subregion"][0]
        self.assertIn("boundary vertex multiset", clause)
        self.assertTrue(why.strip(), "отсутствие без причины — не названное")


class ItAnswersADifferentQuestionThanTheAxes(unittest.TestCase):
    """TWO INSTRUMENTS, TWO QUESTIONS — AND NEITHER REPLACES THE OTHER.

    These are not two ways of saying the same thing: if one replaced the
    other, the correct fix would have been editing `unwitnessed_axes`, not
    adding a new field.
    """

    def test_the_axes_instrument_is_BLIND_to_a_named_absence(self):
        """🔴 THE CONTROL THE WHOLE FILE EXISTS FOR, AND IT MUST BE ABLE TO
        FAIL.

        `create_site_subregion` carries a named absence of shape while being
        read by the axis instrument as FULLY checked. Should the axis
        instrument start seeing it, this test will turn red — and that will
        be the correct red: it will say the new field is no longer needed.
        """
        witness = serving._witness_for_success(
            "authoring", {}, ["create_site_subregion"])
        self.assertEqual(witness.get("unwitnessed_axes"), {},
                         "осевой прибор объявляет оп чистым…")
        self.assertIn("create_site_subregion",
                      tc.named_absences(["create_site_subregion"]),
                      "…а названное отсутствие у него ЕСТЬ")

    def test_an_axis_gap_and_a_clause_gap_are_different_ops(self):
        """For `create_level`, WHOLE axes are empty; for the sub-region, a
        clause inside an axis is.

        🔴 THE EXAMPLE CHANGED ON 22.08.2026, THE LAW DID NOT. `set_param`
        used to stand here: it was a clean case of "empty axes and no named
        absence." The consequence-circle wave gave it an absence ("the
        target's category is unknown to the compiler, no general neighbor
        reader exists"), and the example stopped being clean — the test
        turned red CORRECTLY.

        `create_level` was taken instead: `semantic` and `topology` are
        empty, there is no named absence. There are 29 such ops today, so the
        law does not rest on a single sample.
        """
        axes = serving._witness_for_success("authoring", {}, ["create_level"])
        self.assertTrue(axes.get("unwitnessed_axes"),
                        "пустые оси ловит осевой прибор")
        self.assertEqual(tc.named_absences(["create_level"]), {},
                         "…и названного отсутствия у него нет")

    def test_set_param_now_has_BOTH_and_that_is_the_point(self):
        """And `set_param` became the case where BOTH instruments agree.

        The axes are empty (there are no obligations on them) AND a named
        absence exists (neighbors are not read, and it says why). The two
        instruments answer different questions about the same op, and both
        must speak.
        """
        axes = serving._witness_for_success("authoring", {}, ["set_param"])
        self.assertTrue(axes.get("unwitnessed_axes"))
        self.assertIn("set_param", tc.named_absences(["set_param"]))


class TheMeasuredGapIsPinned(unittest.TestCase):
    """THE MEASURED COUNT IS PINNED SO THE GAP CANNOT CLOSE SILENTLY.

    Not "roughly this many": if an entry leaves the table, or an op stops
    losing its absence, the test must say so, not stay silent.
    """

    def test_the_table_covers_ops_that_exist(self):
        unknown = [n for n in tc._NON_WITNESSABLE_CLAUSES if n not in spec.OPS]
        self.assertEqual(unknown, [],
                         "названное отсутствие у несуществующего опа — "
                         "запись, которую никто никогда не прочтёт")

    def test_every_entry_states_a_reason(self):
        for op, entries in tc._NON_WITNESSABLE_CLAUSES.items():
            for clause, why in entries:
                with self.subTest(op=op, clause=clause):
                    self.assertTrue(clause.strip())
                    self.assertTrue(
                        len(why.strip()) > 20,
                        "причина короче двадцати знаков не объясняет ничего")

    def test_the_ops_whose_absence_the_axes_instrument_LOSES(self):
        """By name, not by count: the list is the evidence, a bare number is
        not.

        These ops declare a named absence AND are read by the axis instrument
        as clean on every axis. Until the new field is in the receipt, from
        the outside they are indistinguishable from fully checked ops.
        """
        lost = []
        for op in sorted(tc._NON_WITNESSABLE_CLAUSES):
            spec_op = spec.OPS.get(op)
            if spec_op is None or not spec_op.writes_model:
                continue
            witness = serving._witness_for_success("authoring", {}, [op])
            if not witness.get("unwitnessed_axes"):
                lost.append(op)
        # Measured 19.08: EIGHT. The list is named so the movement is visible
        # BY NAME — "now seven" without a name does not say whether it got
        # better or an entry just vanished.
        #
        # 🔴 22.08.2026: NINE, `move_elements` was added, and the addition is
        # SUBSTANTIVE. A move now declares ALL THREE axes (the
        # consequence-circle wave added two topological obligations), so the
        # axis instrument reads it as fully checked — and for exactly that
        # reason it loses its named absence: rooms bordering the moved
        # element are not re-read, and walking them would cost 1 102 MNVNK
        # rooms ON EVERY op. This is exactly the different granularity the
        # file's header is about: closing an axis does not close a clause.
        self.assertEqual(
            lost,
            ["create_beam_system", "create_room", "create_site_subregion",
             "create_stairs", "create_stairs_landing", "create_truss",
             "move_elements", "route_duct_system", "route_pipe_system"],
            "состав потерянных изменился — назови, что произошло")


if __name__ == "__main__":
    unittest.main()
