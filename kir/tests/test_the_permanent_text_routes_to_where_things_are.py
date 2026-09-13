"""PERMANENT TEXT MUST SEND THE MODEL TO WHERE THE SUBJECT ACTUALLY LIES.

Audit findings `F-112` and `F-113` (29.08.2026), `kir/skill.py`. Both are
in text that travels to the model on EVERY turn of KIR mode, and both lie
about the COVERAGE of a neighboring channel: «это уже у тебя» ["you
already have this"] where it is not there at all.

`F-112` — §4 named three techniques by name and sent the reader to the
wrong place for them:

    • THE OTHER 10 TECHNIQUES (addressing within the program, type and
      family, macro limits, levels, host, coordinates) — course("приёмы")

Lifted by execution: «УРОВНИ И ОТМЕТКИ», «ХОСТ: ОКНА, ДВЕРИ, МАРКИ»,
«КООРДИНАТЫ И ЕДИНИЦЫ» — all three live in `course("место")`, sent there
by `_TECHNIQUES_PLACEMENT`. A model that needs a window's host calls
«приёмы», does not find it, and either spends a second turn or decides
the technique does not exist at all.

🔴 AND THE NUMBER WAS WRONG TOO, despite the package calling it
«вычисляемым и верным» ["computed and correct"]. `len(TECHNIQUES) -
len(kept)` = 10 summed BOTH topics, while `course("приёмы")` holds FIVE
(14 total − 4 permanent − 5 about placement). The computed number lied
just like the hand-typed list did — only more quietly.

`F-113` — `build_walkthrough_programs_text()` asserted unconditionally:

    Сами разборы (зачем каждый шаг) стоят в описании инструмента.

while `WALKTHROUGHS = 4` and `PERMANENT_WALKTHROUGHS = 1`. Three of the
four walkthroughs live in `course("случаи")`, and the sentence told the
model there was no need to go there. The cost is not lost text but a lost
CHAIN OF REASONING: the model gets the programs, but not «зачем каждый
шаг» ["why each step"] — and does not know it never got it.

🔴 THE NEIGHBORING GUARD WAS GREEN ABOUT THE SHAPE OF THE MISS.
`test_skill.test_the_moved_techniques_are_reachable_and_not_duplicated`
requires that the FULL NAME of a technique appear in exactly one of the
three texts. The false sentence used not the name but a lower-case
paraphrase («уровни, хост, координаты»), and the guard never saw it. The
same class as `F-341` and the subscript `offset` in `F-293`: the
instrument checks NAMES, and the miss was written in PROSE.

THIS IS WHY WHAT IS CHECKED HERE IS THE ROUTE, NOT THE TEXT: for every
technique — whether the topic named next to it is the right one; for a
claim about coverage — whether it actually depends on the coverage. The
lists of names in the permanent text were REMOVED, not corrected: they
were themselves the mechanism of the mismatch.
"""
from __future__ import annotations

import unittest

from kir import skill


class МаршрутНазванВерно(unittest.TestCase):
    """F-112."""

    def test_every_placement_technique_lives_where_it_is_sent(self) -> None:
        """🔴 THE SUBJECT. What is checked is the LAYOUT, not the wording:
        every "placement" technique must live under "placement" and not
        under "techniques"."""
        techniques = skill.build_techniques_text()
        placement = skill.build_placement_techniques_text()
        self.assertTrue(skill._TECHNIQUES_PLACEMENT)      # denominator control
        for title in sorted(skill._TECHNIQUES_PLACEMENT):
            with self.subTest(title=title):
                self.assertIn(title, placement)
                self.assertNotIn(title, techniques)

    def test_the_permanent_text_names_no_technique_of_the_other_topic(self) -> None:
        """The list of subjects next to `course("приёмы")` has been
        REMOVED. If someone brings it back, this test will not catch a
        paraphrase — but whoever brings it back will have to explain why
        the list exists again."""
        line = [l for l in skill.build_skill_text().splitlines()
                if 'course("приёмы")' in l]
        self.assertEqual(len(line), 1)
        for word in ("уровни", "хост", "координаты"):
            self.assertNotIn(word, line[0].lower(),
                             "предмет «места» назван рядом с темой «приёмы»")

    def test_the_count_matches_what_the_topic_actually_holds(self) -> None:
        """🔴 THE NUMBER IS COMPUTED FROM THE SAME TOPIC IT TALKS ABOUT. It
        stood at 10 when the true count was five — it summed both topics."""
        text = skill.build_skill_text()
        techniques = skill.build_techniques_text()
        really = sum(1 for s, _a in skill.TECHNIQUES if s in techniques)
        self.assertIn(f"ОСТАЛЬНЫЕ {really} ПРИЁМОВ", text)
        self.assertIn(f"ЕЩЁ {len(skill._TECHNIQUES_PLACEMENT)} О МЕСТЕ", text)

    def test_the_second_topic_is_still_named_with_a_subject_word(self) -> None:
        """🔴 THE GREEN OUTCOME. Removing ALL subject words would have been
        cheaper and worse: without a single one, the model would not
        understand why to call the second topic at all, and the cost of
        that is the same extra turn the fix exists to remove."""
        line = [l for l in skill.build_skill_text().splitlines()
                if 'course("место")' in l]
        self.assertEqual(len(line), 1)
        self.assertTrue(any(w in line[0].lower()
                            for w in ("уровень", "хост", "координат")))


class УтверждениеОбОхватеЗависитОтОхвата(unittest.TestCase):
    """F-113."""

    def test_the_programs_lesson_does_not_overclaim(self) -> None:
        """🔴 THE SUBJECT: the sentence must switch itself."""
        text = skill.build_walkthrough_programs_text()
        if len(skill.PERMANENT_WALKTHROUGHS) == len(skill.WALKTHROUGHS):
            self.assertIn("стоят в описании инструмента", text)
        else:
            self.assertNotIn(
                "Сами разборы (зачем каждый шаг) стоят в описании инструмента.",
                text)
            self.assertIn(f"{len(skill.PERMANENT_WALKTHROUGHS)} из "
                          f"{len(skill.WALKTHROUGHS)}", text)

    def test_the_topic_name_is_not_typed_a_second_time(self) -> None:
        """The topic's name is taken from the constant: typing it here by
        hand would have made this one more carrier — exactly the disease
        this whole class exists to cure."""
        self.assertIn(f'course("{skill.WALKTHROUGH_CASES_TOPIC}")',
                      skill.build_walkthrough_programs_text())

    def test_the_claim_flips_when_the_coverage_does(self) -> None:
        """🔴 BOTH OUTCOMES, EXECUTED. We substitute full coverage and
        require a DIFFERENT sentence — without this the check above is
        green on one state of the world and guards nothing."""
        saved = skill.PERMANENT_WALKTHROUGHS
        skill.PERMANENT_WALKTHROUGHS = frozenset(
            title for title, _s, _p in skill.WALKTHROUGHS)
        try:
            full = skill.build_walkthrough_programs_text()
        finally:
            skill.PERMANENT_WALKTHROUGHS = saved
        self.assertIn("стоят в описании инструмента", full)
        self.assertNotIn("из 4 разборов", full)
        # And back — under real coverage the sentence is honest again.
        self.assertIn("1 из 4", skill.build_walkthrough_programs_text())


class ПостоянныйТекстНеВыросВовсе(unittest.TestCase):

    def test_the_permanent_description_did_not_grow(self) -> None:
        """🔴 THE 30,000 CEILING STOOD AT 20 CHARACTERS. Both fixes REMOVE
        the list rather than append to it — the permanent text became 13
        characters SHORTER, and the margin grew from 20 to 33 (with the
        geometry-library flag)."""
        from kir.tool_doc import build_tool_description
        self.assertLess(len(build_tool_description()), 30_000 - 30,
                        "запас до потолка описания меньше 30 знаков")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
