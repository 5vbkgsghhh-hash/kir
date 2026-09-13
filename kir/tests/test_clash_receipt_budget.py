"""THE BUDGET OF THE RECEIPT'S NON-REMOVABLE PART — A NAMED NUMBER WITH A LOCK.

WHAT THIS FIXES (measured 11.08.2026, `snowdon_plumb_v4`, a live rebuild).
The receipt consists of two parts, and they compete for one ceiling:

  * NON-REMOVABLE — "here is what I did NOT look at": so many bodies, so
    many without a body and why, what the check does not see at all, what
    its scope is;
  * FINDINGS — "here is what I found".

The first part grew all week, and grew SILENTLY:

    was, when the ceiling was first chosen (the `_TEXT_CAP` header)  1 043 chars.
    is now                                                           1 600 chars.  (+53%)
    of which this wave series added                                   586 chars.
        WHAT THIS CHECK DOES NOT SEE AT ALL                            298
        ADDED BY THIS BATCH                                            185
        OF WHICH BY REASON                                             103

The consequence was measured: at a ceiling of 2 700, findings were left with
1 100 chars., i.e. 3.3 judgments out of the promised five, and the report
printed «список суждений обрезан» (the list of judgments is truncated). This
is the SAME failure that the `_TEXT_CAP` header already declared fixed once:
"at the previous 1 100 the findings list was truncated down to ZERO rows —
the receipt said 'there is a dispute' and showed not a single one".

THE LAW LOCKED DOWN HERE: when HONESTY text crowds out findings, honesty
starts costing TRUTH. So the non-removable part gets a named budget instead
of growing by whatever happens: the next honest line MUST FORCE a decision —
compress, drop another line, or bring a measurement to justify raising the
ceiling — instead of silently eating another judgment.

THE CEILING IS NOT RAISED HERE. Not because it cannot be, but because we
have no measurement of what the model actually pays for these characters;
raising it is only defensible together with one.
"""
from __future__ import annotations

import os
import unittest

from kir import clash_bundle as CB


class _Flag:
    def __enter__(self):
        self._prev = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()
        return self

    def __exit__(self, *exc):
        if self._prev is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()
        return False


def _worst_case_pack():
    """A batch that SQUEEZES every conditional row out of the receipt at once.

    The budget must be held to the WORST case, not a convenient one: the
    "no body" row appears only when there are bodyless ones, "wall joints"
    only when there is a wall hull, "nominal only" only when there is a pipe
    without a size table. A batch where none of them fires would be proving
    a budget that nobody pays.
    """
    ops = [
        # traces that DISPUTE: they produce findings and judgments with a move
        {"op": "create_duct", "id": "d1", "diameter_mm": 400.0,
         "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [0.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d2", "diameter_mm": 400.0,
         "p0_mm": [100.0, 0.0, 0.0], "p1_mm": [100.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d3", "diameter_mm": 400.0,
         "p0_mm": [200.0, 0.0, 0.0], "p1_mm": [200.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d4", "diameter_mm": 400.0,
         "p0_mm": [300.0, 0.0, 0.0], "p1_mm": [300.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d5", "diameter_mm": 400.0,
         "p0_mm": [400.0, 0.0, 0.0], "p1_mm": [400.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d6", "diameter_mm": 400.0,
         "p0_mm": [500.0, 0.0, 0.0], "p1_mm": [500.0, 6000.0, 0.0]},
        # a pipe with a nominal size and no size table -> "nominal only"
        {"op": "create_pipe", "id": "pp1", "diameter_mm": 100.0,
         "p0_mm": [0.0, 0.0, 500.0], "p1_mm": [3000.0, 0.0, 500.0]},
        # bodyless ones of DIFFERENT classes
        {"op": "create_room", "id": "r1"},
        {"op": "place_family", "id": "pf1"},
        {"op": "create_door", "id": "dr1"},
        {"op": "create_cable_tray", "id": "t1",
         "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0]},
        {"op": "create_wall", "id": "w1", "p0_mm": [0.0, 0.0, 0.0],
         "p1_mm": [4000.0, 0.0, 0.0], "height_mm": 3000.0},
        {"op": "create_stairs", "id": "s1"},
    ]
    return [{"ops": ops[:7]}, {"ops": ops[7:]}]


class TheFixedPartHasANamedBudget(unittest.TestCase):
    """A lock. If the non-removable part grows, THIS test fails — not the
    count of judgments shown."""

    def test_the_worst_case_fits_the_named_budget(self):
        with _Flag():
            block = CB._report(_worst_case_pack(), new_from=2)
        budget = block["text_budget"]
        self.assertLessEqual(
            budget["fixed"], CB.FIXED_TEXT_BUDGET,
            f"неснимаемая часть {budget['fixed']} > бюджета "
            f"{CB.FIXED_TEXT_BUDGET}: следующая честная строка съест суждение. "
            f"Решай — сжать, убрать другую строку, или принести замер под "
            f"поднятие потолка.")

    def test_the_budget_arithmetic_is_stated_and_true(self):
        """A number without arithmetic behind it is assigned, not measured. The
        budget must answer the question "how many judgments does it
        GUARANTEE"."""
        room = CB._TEXT_CAP - CB.FIXED_TEXT_BUDGET
        self.assertGreaterEqual(room, CB.GUARANTEED_FINDINGS * CB.COST_PER_FINDING)
        self.assertLessEqual(CB.GUARANTEED_FINDINGS, CB._TOP)

    def test_the_promise_of_the_text_and_of_the_payload_are_both_named(self):
        """`_TOP` promises five judgments IN THE DATA, while the text guarantees
        fewer — and before this wave the gap was silent. A silent mismatch
        between promise and delivery is exactly that defect."""
        self.assertGreater(CB._TOP, 0)
        self.assertGreater(CB.GUARANTEED_FINDINGS, 0)

    def test_the_budget_is_measured_on_the_worst_case_not_a_quiet_one(self):
        """The test batch must TRIGGER the conditional rows — otherwise the
        budget is proven on a receipt that nobody ever gets."""
        with _Flag():
            block = CB._report(_worst_case_pack(), new_from=2)
        text = block["message_ru"]
        for must in ("БЕЗ ТЕЛА", "ВНЕСЛА ЭТА ПАЧКА", "НЕ ВИДИТ",
                     "ТОЛЬКО НОМИНАЛ", "ВНЕ ПРОВЕРКИ"):
            self.assertIn(must, text, must)

    def test_at_least_the_guaranteed_number_of_findings_is_shown(self):
        """The point of the budget is not the number itself but that the
        findings arrive."""
        with _Flag():
            block = CB._report(_worst_case_pack(), new_from=2)
        shown = block["text_budget"]["shown"]
        self.assertGreaterEqual(
            shown, min(CB.GUARANTEED_FINDINGS, block["text_budget"]["of"]))

    def test_the_budget_rides_in_the_payload_so_it_can_be_watched(self):
        """A budget visible only to the test will start growing silently again
        between runs. It rides as a number in the answer."""
        with _Flag():
            block = CB._report(_worst_case_pack())
        for key in ("fixed", "cap", "room", "shown", "of"):
            self.assertIn(key, block["text_budget"])
        self.assertEqual(block["text_budget"]["cap"], CB._TEXT_CAP)
        self.assertEqual(
            block["text_budget"]["room"],
            max(0, CB._TEXT_CAP - block["text_budget"]["fixed"]))


class TheCapDocstringDescribesTodayNotYesterday(unittest.TestCase):
    """«1 043 + 5×330 ≈ 2 700» described a state that no longer exists:
    the non-removable part is 1 600, and 3.3 judgments fit. A number
    documenting a vanished state is exactly the defect being hunted."""

    def test_the_stale_arithmetic_is_gone(self):
        import inspect

        source = inspect.getsource(CB)
        head = source[source.index("_TEXT_CAP = "):]
        self.assertNotIn("1 043 + 5×330", head)

    def test_the_docstring_names_the_budget_constant(self):
        import inspect

        source = inspect.getsource(CB)
        anchor = source.index("#: The ceiling on the receipt's text.")
        window = source[anchor:anchor + 2_000]
        self.assertIn("FIXED_TEXT_BUDGET", window)


if __name__ == "__main__":
    unittest.main()


class TheNoticeCountsTheSameThingThePayloadDoes(unittest.TestCase):
    """The receipt must state the SAME number that rides in the answer.

    Measured 12.08.2026: with three findings shown, the text wrote
    «показано 6» (showing 6). `kept` accumulates ROWS, and each finding has
    two of them — `[СМОТРЕТЬ]` and `ХОД` — so the row count came out exactly
    double and was called a count of JUDGMENTS. The same class of bug as
    `_max_bodies` in the canon: declared "a ceiling on BODIES", read as
    `len(elements)`.

    Why this is a product defect and not a typo: the receipt's main reader
    is the model, and one that was told «показано шесть» (showing six) will
    not come back for the rest. A silently-wrong outcome is exactly where
    the invariant must speak loudest.
    """

    def test_the_truncation_notice_agrees_with_the_payload(self):
        import re
        with _Flag():
            block = CB._report(_worst_case_pack(), new_from=2)
        text = block["message_ru"]
        match = re.search(r"обрезан, показано (\d+)", text)
        if match is None:
            self.skipTest("на этой пачке список не обрезался — нечего сверять")
        self.assertEqual(
            int(match.group(1)), block["text_budget"]["shown"],
            "текст квитанции и её же payload называют РАЗНОЕ число показанных "
            "суждений; читатель верит тексту")


    def test_the_cost_of_a_finding_is_re_measured_not_recalled(self):
        """`COST_PER_FINDING` is a MEASUREMENT, and measurements go stale. Guard
        the input.

        The derivation of `FIXED_TEXT_BUDGET` computed correctly the whole
        time and faithfully propagated a stale number: the cost was measured
        on 09.08 (330), and the row was later lengthened by a grade, a
        tolerance and a section — 388. The formula was right, its input was
        not, and it was DELIVERY that failed because of it, not arithmetic.

        So the cost is taken from an actual render of the worst-case batch
        and checked against the recorded one. Stretch the judgment row and
        THIS line fails, number in hand, instead of "showing 3 instead of 4"
        two files away.
        """
        with _Flag():
            block = CB._report(_worst_case_pack(), new_from=2)
        lines = block["message_ru"].split("\n")
        costs, i = [], 0
        while i < len(lines):
            if lines[i].startswith("  ["):
                cost = len(lines[i]) + 1
                if i + 1 < len(lines) and lines[i + 1].lstrip().startswith("ХОД"):
                    cost += len(lines[i + 1]) + 1
                    i += 1
                costs.append(cost)
            i += 1
        self.assertTrue(costs, "худшая пачка не отрисовала ни одного суждения")
        self.assertLessEqual(
            max(costs), CB.COST_PER_FINDING,
            f"суждение подорожало: настоящая цена {max(costs)} против "
            f"записанной {CB.COST_PER_FINDING}. Перемерь и обнови константу "
            f"вместе с гарантией — иначе бюджет пообещает то, чего не доставит")
