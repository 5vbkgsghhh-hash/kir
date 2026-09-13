""""THERE IS A NAME IN THE CATALOG" AND "THERE IS A DECOMPILE" ARE DIFFERENT FACTS.

An audit finding, `F-204` (2026-08-29), `kir/course/building.available`.

It used to be `bool(_runs())`, i.e. `bool(os.listdir(...))`. A README, a
service file, or an empty subdirectory made the lesson "available," and it
printed its usual form for ZERO buildings; the honest refusal branch right
next to it («УРОК «ДОМ» НЕДОСТУПЕН») simply never fired. Two values of one
module contradicted each other in a single output:

    available(): True | buildings(): []

🔴 A CORRECTION TO THE JOURNAL, REVEALED BY EXECUTION, AND IT SHRINKS THE
FINDING. The journal assumes the reader will take zeros for measured values.
That is WRONG: the lesson names its own emptiness out loud and explicitly
forbids that reading — «· высота этажа: НИ ОДНОГО замера… Нули ниже означают
«не мерили», а не «ноль»». The defect exists, but it is elsewhere, and it is
visible in the same output: the line

    ЧИСЛА СНЯТЫ С НАСТОЯЩИХ ПРОЕКТОВ, НЕ ВСПОМНЕНЫ: по 0 ЗДАНИЯМ

asserts an ORIGIN, is self-contradictory, and is not covered by the
zero-banner. The cost: instead of ONE refusal line with a next move, the
reader gets a page where everything is correct except one sentence — and
spends a turn figuring that out.

THE CURE IS DERIVATION, NOT A LIST OF GARBAGE KINDS: their list is infinite.
What is asked is the one function that ALONE decides what a building is —
`buildings()` reads the header of every decompile and filters out garbage by
construction.

AN UNFIT ALTERNATIVE, NAMED EXPLICITLY: "print the zeros with a louder
banner." The banner already exists and already failed to work. Zeros dressed
with a warning still read as numbers; an absence does not read at all.
"""
from __future__ import annotations

import unittest

import kir.course.building as building


class ИмяВКорнеНеРазбор(unittest.TestCase):

    def setUp(self) -> None:
        self._saved = (building._runs, building._head, building._BUILDINGS_CACHE)
        self.addCleanup(self._restore)

    def _restore(self) -> None:
        building._runs, building._head, building._BUILDINGS_CACHE = self._saved

    def _corpus(self, runs, head) -> None:
        """🔴 THE CACHE IS RESET — THIS IS PART OF THE CHECK, NOT CLEANUP.
        `buildings()` keys `_BUILDINGS_CACHE` off the `_runs()` tuple; without
        the reset, the second case would read the first case's result and
        the test would go green on someone else's answer."""
        building._runs = lambda: runs
        building._head = head
        building._BUILDINGS_CACHE = None

    def test_a_readme_in_the_corpus_root_is_not_a_building(self) -> None:
        """🔴 THE SUBJECT OF THE FINDING."""
        self._corpus(["README.md"], lambda run: None)
        self.assertEqual(building.buildings(), [])
        self.assertFalse(building.available(),
                         "имя в каталоге объявлено разбором")
        self.assertIn("НЕДОСТУПЕН", building.lesson())

    def test_the_two_values_of_the_module_agree(self) -> None:
        """A property, not a single case: `available()` and `buildings()` are two
        values of ONE module, and they used to be printed side by side,
        contradicting each other. Checked together on three different corpora."""
        for runs, head in ((["README.md"], lambda r: None),
                           ([], lambda r: None),
                           (["real"], lambda r: {"doc_name": "Дом 1"}),
                           (["a", "b"], lambda r: {"doc_name": "Дом " + r})):
            with self.subTest(runs=runs):
                self._corpus(runs, head)
                self.assertEqual(building.available(),
                                 bool(building.buildings()))

    def test_a_real_run_is_still_available(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it, a fix of "always False" would pass
        everything else and take the whole lesson away."""
        self._corpus(["real"], lambda run: {"doc_name": "Дом 1"})
        self.assertTrue(building.available())
        self.assertEqual(len(building.buildings()), 1)
        self.assertNotIn("НЕДОСТУПЕН", building.lesson())

    def test_the_refusal_names_the_next_move(self) -> None:
        """A refusal is obligated to be ONE line with a move, not a page where
        everything is correct except one sentence."""
        self._corpus(["README.md"], lambda run: None)
        text = building.lesson()
        # The self-contradictory claim about ORIGIN («…НЕ ВСПОМНЕНЫ: по
        # 0 ЗДАНИЯМ») disappears; the phrase «сняты с настоящих проектов» remains —
        # but now inside the REFUSAL, where it explains the REASON for the
        # refusal instead of passing zeros off as a measurement. These are
        # different claims, and what must be checked is the one that lied.
        self.assertNotIn("ПО 0 ЗДАНИЯМ", text.upper())
        self.assertIn("НЕДОСТУПЕН", text)
        self.assertLess(len(text), 500,
                        "отказ обязан быть короткой строкой, а не страницей "
                        "урока, где верно всё, кроме одного предложения")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
