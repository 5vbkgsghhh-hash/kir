"""THE EXAMPLE WE SHOW THE MODEL IS CHECKED AGAINST THE COMPILER.

WHY THIS FILE. In the tool's persistent description (28,218 characters
before this wave), the word `track` appeared ONCE as prose and NOT ONCE as
JSON: the section on repetition talked about the payoff and never showed
the shape. For an LLM, a worked-out example is denser than a paragraph, so
an example was added — and along with it an obligation prose does not have.

**NOBODY MUTATES PROSE.** Canon form 9: a promise in the text is broader
than the behavior in the code, and no run goes red because a paragraph
lied. An example is prose that LOOKS like code, and is therefore more
dangerous than ordinary prose: the model will copy it verbatim. The only
way to keep it from rotting is to check it against the very compiler that
will accept or reject it.

WHAT IS PINNED DOWN:
  * the shown program COMPILES and unfolds into the declared number of
    operations (an example that does not compile teaches the wrong thing
    with the same density with which a correct one teaches the right
    thing);
  * the shown REFUSAL is verbatim what the compiler produces today, not a
    recollection from memory;
  * both reach the description that actually goes out to the model.

BOUNDARY. The file checks the PLAN (`compiler.plan_program`) — the stage
where both macro expansion and track coverage live. It does not check
grounding, emission, or Revit's behavior: the shown program has a
by-name level selector, and in a live document it may fail to resolve.
That is exactly the example's subject — the notational form of repetition,
not readiness to be built in a specific model.
"""

from __future__ import annotations

import copy
import unittest

from kir import compiler, skill, tool_doc

EXPECTED_OPS = 6


def _plan(program: dict):
    return compiler.plan_program(copy.deepcopy(program))


class TheShownProgramCompiles(unittest.TestCase):

    def test_it_expands_to_the_declared_number_of_ops(self) -> None:
        planned = _plan(skill.REPEAT_BY_TRACK)
        self.assertEqual(len(planned.ops), EXPECTED_OPS)

    def test_the_description_says_the_same_number(self) -> None:
        """The number in the prose and the number from the compiler are one
        and the same quantity.

        This is exactly the defect this house has been catching for two
        days running: a value is declared in one place and read in
        another, and nothing forces them to agree.
        """
        self.assertIn(f"Разворачивается в {EXPECTED_OPS} операций",
                      tool_doc.build_tool_description())

    def test_the_program_reaches_the_description_verbatim(self) -> None:
        text = tool_doc.build_tool_description().replace(" ", "")
        self.assertIn('"op":"series"', text)
        self.assertIn('"$x@next"', text)


class TheShownRefusalIsTheRealOne(unittest.TestCase):
    """The refusal in the description is a snapshot of the compiler, not a
    paraphrase."""

    @staticmethod
    def _shorten_track() -> dict:
        """The same program with the track set to 5 instead of 6 — the only
        change."""
        broken = copy.deepcopy(skill.REPEAT_BY_TRACK)
        broken["ops"][0]["track"]["x"] = [[0, 0], [5, 12000]]
        return broken

    def test_the_quoted_text_is_what_the_compiler_says_today(self) -> None:
        with self.assertRaises(Exception) as caught:
            _plan(self._shorten_track())
        diags = getattr(caught.exception, "diagnostics", None) or ()
        self.assertTrue(diags, "отказ без диагностик — сверять нечего")
        d = diags[0]
        quoted = skill.REPEAT_REFUSAL_RU[0]
        self.assertIn(d.code, quoted)
        self.assertIn(d.message_ru, quoted,
                      "текст отказа в описании разошёлся с компилятором")

    def test_the_refusal_reaches_the_description(self) -> None:
        text = tool_doc.build_tool_description()
        self.assertIn("KIR-M001", text)
        self.assertIn("ПОЧИНКА — ОДИН УЗЕЛ", text)


class TheCheckCanFail(unittest.TestCase):
    """A FAIL control: without it the green above reports nothing.

    Canon form 8. What is checked is not "something failed" but that
    EXACTLY WHAT these tests promise to catch fails: a broken example and
    a diverged refusal.
    """

    def test_a_broken_example_would_be_caught(self) -> None:
        broken = copy.deepcopy(skill.REPEAT_BY_TRACK)
        broken["ops"][0]["track"]["x"] = [[0, 0], [5, 12000]]
        with self.assertRaises(Exception):
            _plan(broken)

    def test_a_drifted_refusal_text_would_be_caught(self) -> None:
        with self.assertRaises(Exception) as caught:
            _plan(TheShownRefusalIsTheRealOne._shorten_track())
        real = (getattr(caught.exception, "diagnostics", None) or ())[0]
        self.assertNotIn(real.message_ru, "KIR-M001 | поле x | подсаженный "
                                          "пересказ отказа по памяти")

    def test_the_op_count_assertion_is_not_vacuous(self) -> None:
        """The cardinality is named: at count=1, the expansion is
        indistinguishable from a non-repeat."""
        self.assertGreaterEqual(EXPECTED_OPS, 2)
        one = copy.deepcopy(skill.REPEAT_BY_TRACK)
        one["ops"][0]["count"] = 2
        one["ops"][0]["track"] = {"x": [[0, 0], [2, 4000]],
                                  "h": [[0, 3300], [2, 3000]]}
        self.assertEqual(len(_plan(one).ops), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
