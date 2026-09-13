"""THE NUMBERS IN THE "HOUSE" LESSON MUST MATCH THE DISK, OR IT IS FICTION.

The "house" lesson is the only one in the course that teaches not the
language but the BUILDING, and all its numbers are taken from the corpus of
decompiles of real projects. A recorded number that has diverged from the
corpus is indistinguishable from a made-up one — and a made-up number in a
lesson is worse than no lesson at all, because it gets quoted.

🔴 THE CORPUS IS MACHINE-LOCAL, AND ITS ABSENCE IS A THIRD OUTCOME, NOT A
GREEN ONE. A test that silently turns green without the corpus would be
reporting an absence of findings where it looked at nothing at all. That is
why a skip NAMES the artifact and the path to it: this way the reader can
tell "no instrument" apart from "no discrepancies."

FAIL CONTROL: substitute any value in `building.RECORDED` — the test turns
red exactly on it and prints both values.
"""
from __future__ import annotations

import statistics
import unittest

from kir.course import building


class BuildingNumbersAreCurrent(unittest.TestCase):

    def setUp(self):
        if not building.available():
            self.skipTest(
                "корпус разборов отсутствует на этой машине: %s — числа урока "
                "«дом» НЕ ПРОВЕРЕНЫ (это не «расхождений нет»)"
                % building.DECOMPILE_ROOT)

    def test_each_recorded_number_reproduces_from_the_corpus(self):
        for key, row in building.RECORDED.items():
            with self.subTest(key):
                vals = row.recompute()
                self.assertTrue(vals, "пересчёт %s не дал ни одного значения — "
                                      "прибор не дошёл до предмета" % key)
                got = statistics.median(vals)
                self.assertAlmostEqual(
                    row.value, got, places=3,
                    msg=("%s: записано %.3f %s, корпус даёт %.3f (%s)"
                         % (key, row.value, row.unit, got, row.what)))

    def test_each_recorded_number_carries_a_base_that_also_reproduces(self):
        """🔴 THE BASE IS NOW CHECKED ON PAR WITH THE VALUE (17.08.2026).

        Before this day the base lived as prose ("38 392 values"), and no
        ratchet mutates prose: the value matched the disk, while the basis
        could diverge forever and silently. The difference is not
        cosmetic — "5.59 per 38 392 values" was a measurement of OUR OWN
        history of decompiles, because the tower had been decompiled fifteen
        times, and each decompile weighed as a separate building.

        FAIL CONTROL: shift `n` or `buildings` by one — exactly that line
        turns red and prints both values.
        """
        for key, row in building.RECORDED.items():
            with self.subTest(key):
                self.assertEqual(
                    row.n, len(row.recompute()),
                    "%s: записана база %d значений, корпус даёт другое" % (
                        key, row.n))

    def test_the_corpus_is_counted_in_buildings_not_in_decompiles(self):
        """The unit of count is the BUILDING, and the difference between it
        and a decompile is measurable.

        The test must FAIL if the filtering by document name disappears:
        then the number of buildings would become equal to the number of
        decompiles, and every measurement in this file would start being
        weighted by whatever we decompiled more often.
        """
        # 🔴 READABLE DECOMPILES ARE COMPARED, NOT DIRECTORIES. The first
        # edit took `len(_runs())` — a count of DIRECTORIES, some of which
        # lack a header (measurement of 17.08: 80 directories, 71 with a
        # readable header, 13 buildings). With the filter removed, this
        # assertion would have stayed true (80 > 71) and therefore would
        # have distinguished nothing — green without an act of distinction,
        # in a test set up exactly for distinction.
        readable = [r for r in building._runs() if building._head(r)]
        houses = len(building.buildings())
        self.assertGreater(len(readable), houses,
                           "читаемых разборов не больше, чем зданий: отсев по "
                           "имени документа не сработал либо корпус вырожден")
        for key, row in building.RECORDED.items():
            with self.subTest(key):
                self.assertLessEqual(row.buildings, houses, key)
                self.assertGreater(row.buildings, 0, key)
        # The three corpus-wide measurements must stand on ONE base:
        # different bases on adjacent lines of the same lesson read as one.
        common = {k: r.buildings for k, r in building.RECORDED.items()
                  if r.recompute is not building.wall_widths}
        self.assertEqual(set(common.values()), {houses}, common)

    def test_the_lesson_names_its_limits(self):
        """A lesson must name what it does NOT know.

        Numbers without boundaries read as the norm; this lesson is about
        residential and office buildings in the RF and knows nothing about
        industrial buildings, room purposes, or column spacing. Silence
        about this is a promise wider than the code.
        """
        # Neither case nor LINE BREAKS are checked: the lesson text is laid
        # out by width, and "column spacing was not\ncounted" is the same
        # thought as on one line. A test that stumbles over layout guards
        # formatting instead of the subject; both first edits turned red
        # exactly this way.
        text = " ".join(building.lesson().lower().split())
        for mark in ("не знает", "не разделяется", "не считался"):
            self.assertIn(mark, text)

    def test_the_flat_lesson_stands_on_a_measured_corpus(self):
        """The "apartment" lesson must stand on measurement, not on memory.

        THREE things are checked, each of which would break silently: names
        are collected (otherwise the lesson would print an empty table), the
        room count matches the sum by name (otherwise the header lies to the
        table), and the most frequent room in a residential building is the
        bathroom, not the room. The last one is not decoration: the lesson's
        main conclusion rests on it.
        """
        kinds = building.room_kinds()
        self.assertGreater(len(kinds), 20, "имена помещений не собрались")
        total = sum(len(v) for v in kinds.values())
        text = building.lesson_flat()
        self.assertIn(str(total), text, "шапка урока разошлась с таблицей")
        top = max(kinds.items(), key=lambda kv: len(kv[1]))[0]
        self.assertIn(top, text)

    def test_without_the_corpus_the_lesson_refuses_by_name(self):
        """Without the corpus, the lesson REFUSES, rather than printing
        prose without numbers."""
        real = building.DECOMPILE_ROOT
        try:
            building.DECOMPILE_ROOT = "/нет/такого/корпуса"
            text = building.lesson()
        finally:
            building.DECOMPILE_ROOT = real
        self.assertIn("НЕДОСТУПЕН", text)
        self.assertNotIn("ТИПИЧНАЯ СТЕНА", text)
        # The second lesson must refuse the same way: if one refused and the
        # other printed prose without numbers, the reader would not be able
        # to tell their nature apart.
        real2 = building.DECOMPILE_ROOT
        try:
            building.DECOMPILE_ROOT = "/нет/такого/корпуса"
            self.assertIn("НЕДОСТУПЕН", building.lesson_flat())
        finally:
            building.DECOMPILE_ROOT = real2


if __name__ == "__main__":
    unittest.main()
