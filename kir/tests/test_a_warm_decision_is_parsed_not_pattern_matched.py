"""THE DECISION TO WARM UP IS MADE BY PARSING, NOT BY A LIST OF CALL FORMS.

Audit finding `F-359` (29.08.2026), `kir/course/language.warm_for_source`.

The "дом" and "квартира" lessons read the PARSE CORPUS, and the sandbox child,
after isolation, sits in an empty root — meaning the text must be captured
BEFORE isolation. The decision "capture or not" was made by A LIST OF FOUR
EXACT SUBSTRINGS:

    _WARM_LESSONS = ('course("дом")', "course('дом')",
                     'course("квартира")', "course('квартира')")

Measured against EIGHT legal recordings of the same call: THREE got warmed
up. Missed were: a space before the parenthesis, the topic passed through a
variable, a call split across two lines, a keyword argument, a function
alias. The author would get «УРОК «ДОМ» НЕДОСТУПЕН: корпуса разборов нет на
этой машине» while the corpus was INSTALLED — the refusal was blaming the
MACHINE for our own grammar.

🔴 A FIFTH LINE IN THE LIST WOULD NOT HAVE HELPED: next would come a sixth.
The owner's word from 28.08: a dictionary is not a mechanism, you cannot
enumerate every form, and trying to produces garbage in the code. The list
was REMOVED, not extended.

In its place, ONE checkable property: the topic is known only if it is
WRITTEN AS A LITERAL. Everything else — a computed argument, broken source —
is IGNORANCE, and it SPEAKS UP in the receipt's `warmed` field, rather than
silently turning into "no warming needed."

A SECOND CARRIER OF THE SAME KNOWLEDGE WAS ALSO REMOVED. The topics
requiring warm-up were named TWICE — by a loop in `building.prime()` and by
a list in `language` — and the second one also knew the call's grammar,
which it should not have to know. Now there is one authority:
`building.PRIMABLE_TOPICS`.

WHY THE CHEAP SUBSTRING FILTER STAYS, AND WHY THIS IS LEGAL: the author MUST
write the name `course` in order to call the function. It can fire one extra
time (the cost is one AST parse) and cannot fail to fire — unlike the
removed dictionary, where the substring was also checking the ARGUMENT. For
the same reason, the neighboring `_WARM_BY_NAME` is left untouched: there
the substring checks ONLY the function's name.

A NAMED LIMIT: an alias (`c = course; c("дом")`) is not resolved by parsing
— that would require data-flow analysis, i.e., a decision about the
language, not a bug fix. There is no warm-up there (it costs 10.1 s and
would be paid for by every comment containing the word `course`), but there
is no silence either: the receipt carries `НЕ ПРОГРЕТ:` with a reason and a
next move.
"""
from __future__ import annotations

import unittest

from kir.course.building import PRIMABLE_TOPICS
from kir.course.language import _course_topics, warm_for_source


def _decides(src: str) -> bool:
    """WHETHER WARMING ACTUALLY HAPPENED is observed through
    `warm_for_source`.

    🔴 THE FIRST DRAFT WAS ASKING `_course_topics`, AND THE CONTROL CAUGHT
    IT. A helper is not the decision: a mutation that made `warm_for_source`
    return a dict of forms, and a mutation of "warm up on any occurrence of
    the word course," BOTH left the check green, because it was looking at a
    layer below the actual decision. An instrument aimed at the wrong layer
    guards nothing.

    Now the seam itself is observed: `prime()` is replaced with a spy, and
    what is checked is the FACT of the call — what the author pays 10.1 s
    for.
    """
    import kir.course.building as _b
    calls: list[int] = []
    real = _b.prime
    _b.prime = lambda: (calls.append(1), real())[1] if False else (
        calls.append(1) or ())
    try:
        warm_for_source(src)
    finally:
        _b.prime = real
    return bool(calls)


class ПрогревРешаетсяРазбором(unittest.TestCase):

    def test_every_legal_way_to_ask_the_lesson_gets_it_primed(self) -> None:
        """🔴 THE SUBJECT. The cases are chosen BY PYTHON'S LEGALITY, not for
        convenience: each one calls the same topic, and the list of forms is
        deliberately incomplete — that's the whole point."""
        for src in ('course("дом")', "course('дом')", 'course ("дом")',
                    'topic = "дом"\ncourse(topic)', 'course(\n  "дом"\n)',
                    'course(topic="дом")', 'course("квартира")',
                    'print(course("дом"))'):
            with self.subTest(src=src):
                self.assertTrue(_decides(src), src)

    def test_a_topic_that_needs_no_corpus_is_not_primed(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it the check would be "always warm
        up," trading ten seconds of every author's time for lessons they
        never asked for (measured 22.08: lesson() 10.1 s, lesson_flat() 1.9
        s)."""
        for src in ('course("витраж")', 'course()',
                    'create_wall(p0_mm=[0,0], p1_mm=[1,0], level="Э1")'):
            with self.subTest(src=src):
                self.assertFalse(_decides(src), src)

    def test_a_computed_topic_says_it_was_primed_blind(self) -> None:
        """Ignorance must SPEAK UP, not turn into "not needed"."""
        _asked, blind, _seen = _course_topics('topic = "дом"\ncourse(topic)')
        self.assertTrue(blind)
        self.assertTrue(_decides('topic = "дом"\ncourse(topic)'))
        self.assertIn("ПРОГРЕТ ВСЛЕПУЮ",
                      " ".join(warm_for_source('topic = "дом"\ncourse(topic)')))
        _a, none, _s = _course_topics('course("дом")')
        self.assertEqual(none, "", "литерал не смеет считаться незнанием")

    def test_an_alias_is_a_named_limit_not_a_silence(self) -> None:
        """A NAMED LIMIT. An alias is not resolved — but it does not stay silent either."""
        _a, _b, seen = _course_topics('c = course\nc("дом")')
        self.assertFalse(seen)
        self.assertIn("НЕ ПРОГРЕТ", " ".join(warm_for_source('c = course\nc("дом")')))
        # And where the call IS parsed successfully, this line must not
        # appear — otherwise it would become noise on every run.
        self.assertNotIn("НЕ ПРОГРЕТ", " ".join(warm_for_source('course("дом")')))

    def test_a_broken_source_is_blind_not_silent(self) -> None:
        _asked, blind, _seen = _course_topics('course("дом"')
        self.assertEqual(blind, "исходник не разобран")

    def test_the_topics_have_one_carrier(self) -> None:
        """🔴 THE SECOND CARRIER IS REMOVED. Warm-up topics are declared
        ONCE, and `prime()` iterates over THEM, not over its own list."""
        import kir.course.language as lang
        self.assertFalse(hasattr(lang, "_WARM_LESSONS"),
                         "список форм вызова обязан быть УДАЛЁН, а не дополнен")
        self.assertEqual(set(PRIMABLE_TOPICS), {"дом", "квартира"})

    def test_the_neighbouring_substring_gate_is_untouched(self) -> None:
        """`_WARM_BY_NAME` could NOT be edited: there the substring checks
        only the NAME the author must write; narrowing it down to parsing
        would introduce under-warming where none exists today."""
        import kir.course.language as lang
        self.assertTrue(lang._WARM_BY_NAME)
        self.assertIn("region", lang._WARM_BY_NAME)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
