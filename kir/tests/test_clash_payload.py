"""THE PAYLOAD ALSO COSTS CONTEXT, YET ONLY THE TEXT WAS RATIONED.

MEASURED 11.08.2026 (`/tmp/wiring/m_payload.py`, a live rebuild via
`materialize.leaves_to_program`, serialization without spaces):

    snowdon_plumb_v4   BLOCK 9 931 chars;  message_ru 2 586 (26%),
                       findings 5 586 (56%)
    sob62_r23_v5       BLOCK 4 405 chars;  message_ru 1 362 (31%),
                       findings 1 120 (25%)

That is, the carefully rationed text of 2 700 characters was riding inside an
UNRATIONED payload twice its size. The budget was guarding the wrong
quantity — the same class of mistake as a ceiling measuring the wrong axis.

WHAT `findings` IS MADE OF (5 rows, snowdon):

    why          975  (195 per row)   <- ONE row per RULE
    text         865  (173 per row)
    action_ru    815  (163 per row)   <- ONE row per RUNG
    next_move    605  (121 per row)

`why` and `action_ru` are not finding content but CONSTANTS of their class,
duplicated across rows. Repetition measured: of the five `why` rows, only ONE
is distinct, and 772 of 975 characters are repeats. And that same text
already sits ONCE in the block — in `rules` (213 chars.).

And this is not a new rule but a BROKEN OLD ONE: `clash_judgement.Judged.why_ru`
states it verbatim for the text — "one rationale per rule, while a rule may
have eighty findings: printing it in every row means drowning the findings
in it too." The text followed this; the payload did not.

WHAT IS NOT DONE HERE. No ceiling is assigned to the payload. Nobody has
measured how much the model ACTUALLY pays for these characters, and assigning
a number instead of measuring is forbidden here in exactly the same way that
raising `_TEXT_CAP` was forbidden. What is locked down is the STRUCTURAL
invariant that needs no number: no finding row repeats what the block already
carries as a table.
"""
from __future__ import annotations

import json
import os
import unittest

from kir import clash_bundle as CB
from kir import clash_judgement as J


def _ducts(n, step=100.0):
    return [{"op": "create_duct", "id": f"d{i}", "diameter_mm": 400.0,
             "p0_mm": [i * step, 0.0, 0.0], "p1_mm": [i * step, 6000.0, 0.0]}
            for i in range(n)]


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


class NoRowRepeatsWhatTheBlockAlreadyCarries(unittest.TestCase):
    """A STRUCTURAL LOCK THAT NEEDS NO NUMBER."""

    def _block(self):
        with _Flag():
            return CB._report([{"ops": _ducts(6)}])

    def test_the_justification_is_not_copied_into_every_row(self):
        block = self._block()
        rows = block["findings"]
        self.assertGreater(len(rows), 1, "нужно несколько находок одного рода")
        for row in rows:
            self.assertNotIn(row["why"], block["rules"].values(),
                             "обоснование скопировано в строку целиком")

    def test_the_row_points_at_where_the_text_lives(self):
        """SILENT DISAPPEARANCE IS FORBIDDEN. The field stays in place and points
        the reader to where the text lives once — it does not vanish and
        does not become empty."""
        block = self._block()
        for row in block["findings"]:
            self.assertTrue(row["why"], row)
            self.assertIn(row["rule_id"], row["why"])
            self.assertIn("rules", row["why"])

    def test_the_action_of_a_rung_is_a_table_not_a_copy(self):
        block = self._block()
        self.assertIn("rung_actions", block)
        for row in block["findings"]:
            self.assertIn(row["rung"], block["rung_actions"])
            self.assertNotIn(row["action_ru"],
                             block["rung_actions"].values())
            self.assertTrue(row["action_ru"], row)

    def test_the_tables_carry_only_what_fired(self):
        """A table printing ALL rungs and ALL rules would bring back the same
        cost from the other side: `rules` is already built that way."""
        block = self._block()
        used = {row["rung"] for row in block["findings"]}
        self.assertTrue(set(block["rung_actions"]).issubset(
            {r.rung for r in J.judge([]).judged} | used | set(block["by_rung"])))

    def test_a_direct_caller_of_judge_still_gets_the_full_text(self):
        """`Judged.as_dict()` is the PUBLIC form of a pure function, and it must
        not be shortened: compression is the RECEIPT's concern, not the
        pair-judge's. A caller invoking `judge` directly must get the full
        rationale."""
        finding = {
            "finding_id": "a~b",
            "a": {"source_element_id": "a", "label": "duct",
                  "category": "OST_DuctCurves", "hull_source": "axis_section"},
            "b": {"source_element_id": "b", "label": "duct",
                  "category": "OST_DuctCurves", "hull_source": "axis_section"},
            "hull_relation": "overlap", "hull_grade": "conservative",
            "hull_overlap_depth_mm": 60.0, "ranking_tol_mm": 1.0,
            "pair_kind": "physical"}
        row = J.judge([finding]).judged[0].as_dict()
        self.assertGreater(len(row["why"]), 80)
        self.assertNotIn("rules", row["why"])


class TheBillIsVisibleInEveryAnswer(unittest.TestCase):
    """Same as with text: a quantity nobody watches grows silently. The
    number rides along in the answer so drift is visible in PROD, not only
    in tests — a regex cannot catch up with reality, data can."""

    def test_the_payload_size_rides_in_the_block(self):
        with _Flag():
            block = CB._report([{"ops": _ducts(6)}])
        self.assertIn("payload_chars", block["text_budget"])
        self.assertGreater(block["text_budget"]["payload_chars"], 0)

    def test_the_number_counts_the_whole_block_including_itself(self):
        """A number that does not fully count itself is measuring its neighbor."""
        with _Flag():
            block = CB._report([{"ops": _ducts(6)}])
        actual = len(json.dumps(block, ensure_ascii=False,
                                separators=(",", ":"), default=str))
        reported = block["text_budget"]["payload_chars"]
        self.assertLessEqual(abs(actual - reported), 40,
                             f"замер {reported} против настоящих {actual}")

    def test_dedupe_actually_shrinks_the_bill(self):
        """Before/after measurement on the same batch: the saving must be a
        NUMBER, not an intention."""
        with _Flag():
            block = CB._report([{"ops": _ducts(6)}])
        rows = block["findings"]
        saved = sum(len(block["rules"].get(r["rule_id"], "")) - len(r["why"])
                    for r in rows)
        self.assertGreater(saved, 0, "дедупликация не сэкономила ничего")


class TheOldGuaranteesStillHold(unittest.TestCase):
    """Payload edits are not allowed to cost what already holds."""

    def test_flag_off_still_adds_nothing(self):
        prev = os.environ.pop("KUKAI_IR_CLASH", None)
        try:
            CB._CACHE.clear()
            self.assertIsNone(CB.bundle_clash_report([{"ops": _ducts(3)}]))
        finally:
            if prev is not None:
                os.environ["KUKAI_IR_CLASH"] = prev
            CB._CACHE.clear()

    def test_silence_and_clean_are_still_different(self):
        with _Flag():
            clean = CB._report([{"ops": [{"op": "create_room", "id": "r"}]}])
        self.assertEqual(clean["status"], "ok")
        self.assertEqual(clean["total_findings"], 0)
        self.assertIn("bodies", clean)

    def test_introduced_still_arrives_with_its_rule(self):
        with _Flag():
            block = CB._report([{"ops": _ducts(3)}, {"ops": _ducts(1, 250.0)}],
                               new_from=2)
        self.assertIn("introduced", block)
        self.assertIn("introduced_rule", block)



class TheRuleIsTheRuleAndNotItsDefence(unittest.TestCase):
    """`introduced_rule` was carrying the RULE TOGETHER WITH ITS DEFENSE — 362
    characters in EVERY answer, 4.2% of the block on `snowdon_plumb_v4` and
    8.4% on `sob62_r23_v5` (measured 11.08.2026).

    HOW THIS CASE DIFFERS FROM `why` AND `action_ru`, and why a pointer
    would be the WRONG solution here. Those repeated WITHIN a single
    answer — five rows of one value — and a pointer into the same answer's
    table removed the repeat without hiding anything. `introduced_rule`
    rides ONCE per answer; an outward pointer would remove not the repeat
    but the very visibility the field was created for — i.e. it would send
    the rule back into a comment, where the caller cannot see it.

    So what gets cut is not the field but its CONTENT: the reader needs the
    RULE in one phrase; the DEFENSE of the choice — why "at least one side"
    rather than "the new element merely discovered a pre-existing
    condition" — lives once and is referenced by name.
    """

    def _block(self):
        with _Flag():
            return CB._report([{"ops": _ducts(3)},
                               {"ops": _ducts(1, 250.0)}], new_from=2)

    def test_the_rule_still_states_itself_in_the_payload(self):
        rule = self._block()["introduced_rule"]
        self.assertIn("ХОТЯ БЫ ОДНА", rule)
        self.assertIn("внесённой", rule.lower())

    def test_the_rule_is_a_sentence_not_an_essay(self):
        rule = self._block()["introduced_rule"]
        self.assertLessEqual(
            len(rule), CB.INTRODUCED_RULE_CAP,
            f"правило {len(rule)} симв. при потолке {CB.INTRODUCED_RULE_CAP}: "
            f"это снова правило вместе с защитой")

    def test_the_defence_is_reachable_by_name_not_deleted(self):
        """The defense does not disappear: it is named and can be read. Otherwise
        the choice would again become invisible — `.FirstOrDefault()` with
        a better reputation, in other words."""
        rule = self._block()["introduced_rule"]
        self.assertIn("INTRODUCED_RULE_WHY", rule)
        self.assertTrue(CB.INTRODUCED_RULE_WHY)
        # CASE-INSENSITIVE, like the neighboring test one line above (`rule.lower()`).
        # 12.08 this test went red: the defense was rewritten to single out the reverse
        # reading in caps ("DISCOVERED"), and a check pinned to the WORDING,
        # reported the text's STRENGTHENING as its disappearance. An instrument pinned to
        # spelling does not distinguish strengthening from weakening — the first general form.
        # We check what the test promises by its name: the defense is NAMED and READABLE.
        self.assertIn("обнаружил", CB.INTRODUCED_RULE_WHY.lower())

    def test_the_addends_still_let_a_reader_count_otherwise(self):
        """Shortening the defense has no right to take away the MATERIAL: a
        reader who counts otherwise still sees both addends separately."""
        block = self._block()
        self.assertIn("both_new", block["by_origin"] | {"both_new": 0})
        self.assertEqual(
            block["introduced"],
            block["by_origin"].get("both_new", 0)
            + block["by_origin"].get("one_new", 0))

if __name__ == "__main__":
    unittest.main()
