"""The tool description must not be able to lie about the registry.

Until 2026-07-27 the `revit_ir` description was a hand-written paragraph naming
"уровни/стены/окна/двери/перекрытия/колонны/помещения" — 7 of the 28 writing
ops. Nothing caught it, because prose has no ratchet: ops were added by six
separate waves and none of them touched the sentence. A model reading that text
could not know KIR authors beams, ducts, cable trays, groups, family types or
annotations at all.

These tests are that ratchet.
"""
from __future__ import annotations

import unittest

from kir import dsl, spec
from kir.registry_base import DISCIPLINES
from kir.tool_doc import (
    NOTES, OP_NOTES, UNPROVEN, build_tool_description)


class ToolDescriptionCoversRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.text = build_tool_description()

    def test_every_op_is_named(self):
        """Adding an op to the registry must not leave it undocumented."""
        missing = sorted(name for name in spec.OPS if name not in self.text)
        self.assertEqual(missing, [], f"опы отсутствуют в описании: {missing}")

    def test_writing_and_reading_counts_match_the_registry(self):
        writing = sum(1 for op in spec.OPS.values() if op.writes_model)
        reading = len(spec.OPS) - writing
        self.assertIn(f"ПИШУЩИЕ ({writing})", self.text)
        self.assertIn(f"ЧИТАЮЩИЕ ({reading})", self.text)

    def test_unproven_entries_name_real_ops(self):
        """A stale honesty note is worse than none — it sends the model away
        from an op that has since been fixed."""
        unknown = sorted(name for name in UNPROVEN if name not in spec.OPS)
        self.assertEqual(unknown, [], f"UNPROVEN называет несуществующие опы: {unknown}")
        for name in UNPROVEN:
            self.assertIn(name, self.text)

    def test_measured_idioms_are_present(self):
        """The idioms exist because the model failed without them; losing one
        silently re-opens the failure it closed."""
        self.assertGreaterEqual(len(NOTES), 10)
        for probe in (
            "толщина",          # a type, not an operation parameter
            "query_types",      # ask the catalog before the selector
            "create_stairs",    # the sole op of its own program
            "ПРОСТРАНСТВО ВИДА",   # annotations live in the 2D of the view
        ):
            self.assertIn(probe.lower(), self.text.lower(), probe)
        # `allow_destructive` MOVED, IT DID NOT DISAPPEAR (09.08). The probe stayed in
        # the test, but asks at a NEW address: the envelope requirement is needed by whoever
        # has already written `delete`, not by whoever is choosing the operation. Removing
        # the probe entirely would mean taking the ratchet off the measurement that
        # put it here in the first place.
        self.assertIn("allow_destructive",
                      dsl.OP_FUNCTIONS["delete"].__doc__ or "")

    def test_ref_rule_matches_the_compiler(self):
        """`ref` is legal for what the program itself creates (level/host/
        target/refs) and NOT for catalog selectors — proven live 2026-07-27
        (окно по ref на свою стену, set_param и create_tag по ref). An earlier
        draft said "только для level" and would have talked the model out of
        three shapes that work."""
        self.assertIn("host", self.text)
        self.assertIn("target", self.text)
        self.assertIn("`type`/`symbol` ref НЕ работает", self.text)

    def test_the_op_list_is_grouped_by_discipline_not_by_a_compiler_field(self):
        """The list of ops is read BY SECTION, because work is organized by section.

        Before 09.08, an internal registry field was printed here (`element`,
        `category/element: create_column, create_wall`, `element/mep_system`).
        Read through the author's own eyes, that list answered none of his
        questions: nothing in the text explained why `create_wall` was separated from
        `create_floor`. This test is not about beauty, but about whether a compiler-internal
        field is no longer leaking onto the surface.
        """
        for discipline, names in spec.ops_by_discipline(writes=True):
            self.assertIn(f"  {spec.DISCIPLINE_RU[discipline]}: "
                          + ", ".join(names), self.text)
        # The digest built from the registry does not print `capability` for ANY group.
        for kind, _names in spec.ops_by_object_kind(writes=True):
            self.assertNotIn(f"\n  {kind}: ", self.text)

    def test_every_discipline_label_is_the_one_dictionary(self):
        """The label is a TRANSLATION of the sections dictionary, not a second dictionary.

        If the keys drifted apart, the text would either grow a section the registry does not
        know about, or lose a section it does know about. Both cases are silent.
        """
        self.assertEqual(set(spec.DISCIPLINE_RU), set(DISCIPLINES))
        self.assertEqual(set(spec.DISCIPLINE_ORDER), set(DISCIPLINES))

    def test_the_discipline_of_every_op_is_derived_or_named_as_underived(self):
        """Every write op is either in a section, or in the list of the unlisted.

        There is no third option: an op missing from both would vanish from the roster entirely,
        and `shared` for an unlisted op is an outright lie (the dictionary says that
        `shared` means "belongs to everyone", not "unknown").
        """
        writing = {n for n, o in spec.OPS.items() if o.writes_model}
        placed = {n for _d, names in spec.ops_by_discipline(writes=True)
                  for n in names}
        undecided = {n for n, _why in spec.ops_without_discipline(writes=True)}
        self.assertEqual(placed | undecided, writing)
        self.assertEqual(placed & undecided, set())
        # EVERY unlisted op has a reason IN WORDS, not an empty string: a gap
        # in the accounting without a reason is indistinguishable from a forgotten op.
        for name, why in spec.ops_without_discipline(writes=True):
            self.assertTrue(why.strip(), name)

    def test_a_single_op_trap_lives_in_that_op_and_not_in_the_description(self):
        """DISPLACEMENT IS A MOVE, NOT A DELETION, and it is checked from both
        sides at once.

        A hint that names EXACTLY ONE op and is needed AFTER it has been chosen
        has no right to sit in permanently loaded text: the description
        is paid for on every turn, a docstring only on the turn where it was asked for. But
        "displaced" without the second half of the check is "deleted": knowledge
        counts as having arrived only if it is READABLE at the new address.
        """
        self.assertTrue(OP_NOTES)
        for op_name, notes in OP_NOTES.items():
            self.assertIn(op_name, spec.OPS, op_name)
            doc = dsl.OP_FUNCTIONS[op_name].__doc__ or ""
            for note in notes:
                self.assertIn(note, doc, f"{op_name}: не доехало в докстроку")
                self.assertNotIn(note, self.text,
                                 f"{op_name}: осталось и в описании — "
                                 f"платим дважды")

    def test_the_displaced_traps_have_a_named_address_in_the_description(self):
        """Knowledge with no path leading to it from the permanent text is dark.

        The same law of reachability as for the pointer to the course: a capability
        the model cannot learn about does not exist. So displacement
        is paid for with ONE line naming the door.
        """
        self.assertIn("spec(", self.text)

    def test_description_stays_small_next_to_the_schema(self):
        """The generated JSON Schema already costs ~23k tokens per turn. The
        prose is worth its place only while it stays a small fraction of that.

        The threshold was raised twice, both times DELIBERATELY, with arithmetic:
        8 000 -> 13 000 (30.07, `skill.py` moved in with judgments) -> 30 000 (30.07,
        the operator's decision: "a skill can be 10k tokens, that's not scary",
        the genre changed from a memo to a SHORT PREP COURSE).

        Measurement after the genre change (tiktoken o200k; tiktoken is deliberately NOT added
        to the test's dependencies, so the check runs on CHARACTERS, while the tokens
        remain the provenance):

            schema            22 927 tokens    89 018 characters
            prose (total)      8 929 tokens    26 786 characters
              of which course  7 140 tokens    20 708 characters
            whole batch        31 856 tokens

        Prose = 28.0% of the batch (8 929 / 31 856). It is paid for on EVERY request, while
        a saved round costs a whole batch plus deliberation (85% of turn time
        is the model's deliberation, measured 28.07). Break-even point: prose of volume P
        pays for itself if it saves one round every (batch / P) turns — right now
        31 856 / 8 929 = ONE ROUND OUT OF 3.6. This is a noticeably more demanding
        threshold than the memo had (1 out of 7.5), and it is deliberate: the course must change
        behavior appreciably, or it does not pay for itself.

        Why 30 000 characters. The ceiling declared by the operator is ~10 000
        tokens of prose; on this text, 3.00 characters per token was measured
        (26 786 / 8 929), so 30 000 characters ≈ 10 000 tokens. The threshold is
        expressed in characters precisely because the tokenizer is unavailable in the tests.

        Going forward the text must not grow, but displace itself: with prose exceeding
        a third of the batch, the savings would need to show up in almost every second turn already, and
        we have not measured that and cannot promise it.
        """
        # 🔴 THE CEILING WAS NOT RAISED, AND THIS IS THE DIRECTOR'S DECISION OF 15.08.2026.
        #
        # It was BREACHED by accumulation: eight capabilities arrived in the permanent
        # text in a single day, and the measurement gave 30 427 against a ceiling of 30 000. As the first
        # move I raised the ceiling to 30 600 with break-even arithmetic — and that
        # was the wrong move: the ceiling is paid for on EVERY call, and raising it
        # means offloading our own sloppiness onto the model's thinking budget.
        #
        # Instead of raising it — REDISTRIBUTION under the rule "the permanent text holds
        # only what, without it, the wrong form would get picked": six situational techniques
        # from §4 moved out into `course("приёмы")`, three that decide the form stayed.
        # Measurement: 30 427 -> 28 361 (-2 066), all eight capabilities are named,
        # the outcome control is green (14 facts out of 14).
        self.assertLess(len(self.text), 30_000,
                        "описание разрослось — режь, схема и так дорогая")

    def test_the_model_is_told_the_catalogue_is_already_in_hand(self):
        """🔴 THE GUARD WAS REWRITTEN ON 17.08.2026 PER THE OWNER'S CORRECTION.

        The previous edition was called "the cost of querying the catalog" and required that
        the permanent text say "asking costs A WHOLE TURN". The owner lifted
        this frame verbatim: "reconnaissance is normal, better to think ten times and
        act once", and ordered that 64.8% not be raised as a defect.

        THE NUMBERS STAYED TRUE, THE CONCLUSION WAS WRONG. 96.2% of calls to
        `query_types` are turns where nothing else is done; the mechanism has been measured:
        the answer is a LIST, and `_summarize_tool_result` beyond
        `KEEP_RECENT = 30` replaces every list with "collapsed". The model
        asks again not out of wastefulness, but because it FORGOT. Text that
        talks it out of asking treats the symptom and spoils behavior
        that the constitution counts as a virtue in it: "can check
        exhaustively".

        THAT IS WHY THE GUARD PINS DOWN A FACT, NOT A PERSUASION: the model must read
        that on the `program_py` path it ALREADY HAS the catalog and no trip is needed.
        It cannot obtain this on its own — it cannot see its own history.

        If this moves into a lesson read on demand, it will turn red here.
        """
        head = self.text
        # A FACT: the catalog is already in hand, and it is stated so that it can be acted on
        self.assertIn("model.types(", head)
        self.assertIn("program_py", head)
        self.assertTrue(
            "БЕЗ рейса" in head or "без рейса" in head,
            "не сказано главное: на этом пути каталог не требует хода")
        # 🔴 AND THE FLIP SIDE, WITHOUT WHICH THE CORRECTION WOULD ROLL BACK SILENTLY:
        # the dissuading wording has no right to come back.
        for withdrawn in ("ЦЕЛЫЙ ХОД", "целый ход", "ЦЕНА ФОРМЫ"):
            self.assertNotIn(
                withdrawn, head,
                "вернулась рамка «разведка дорога», снятая владельцем 17.08")



if __name__ == "__main__":
    unittest.main()
