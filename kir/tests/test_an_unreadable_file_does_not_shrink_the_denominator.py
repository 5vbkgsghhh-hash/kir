"""AN UNREADABLE FILE WAS SILENTLY SHRINKING THE DENOMINATOR (E-51, 30.08.2026).

`canon_state._oss_boundary` walked the tree carrying `except OSError:
continue`. A file that failed to open fell out of the walk without a
trace, and the canon's line

    id-like literals in NON-test code (shipping under Apache-2.0): 0

turned into a fact about WHAT COULD BE READ, while it was being read as a
fact about a LEAK. The rule applied here is already on record for
population enumeration: **"enumerate the population" is useless if the
traversal silently skips its members.**

🔴 THE SECOND TRAVERSAL FAILED IN THE OPPOSITE DIRECTION. Under `PKG` the
file was opened with a BARE `open`, unguarded: there, an unreadable file
would crash the BUILDING OF THE WHOLE CANON. One road, two ends — silence
and a crash; both are reduced to a single answer.

Today there are 0 unreadable files out of 1284, and so the skip is INERT.
The guard is deliberately set up on that zero: setting it up on the day
the number becomes nonzero would mean learning about it from someone else.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from kir.instruments import canon_state as C
from kir.tests.test_kir_canon_state_is_current import _sample_matching

#: 🔴 THE SAMPLE IS TAKEN FROM A CARRIER, NOT WRITTEN AS A LITERAL, FOR TWO REASONS.
#:
#: The first is general: two places that must match `DEVICE_RE` are our
#: own named defect, and a divergence would make the control green by
#: construction. A carrier already exists on the neighbor
#: (`_sample_matching`), and it is also the arbiter: it accepts only what
#: the regex has recognized.
#:
#: The second is measured right here. A literal in THIS file is counted by
#: THE CANON ITSELF: the line "the same in TESTS" went 2 -> 3 and named
#: this file, meaning the guard was moving the reading of the instrument it
#: is posted to watch. Verified by reconciling `build()` against the
#: subject taken from git.
_SAMPLE = _sample_matching(C.DEVICE_RE)


def _tree(root: str, *, unreadable_in_repo: bool = False,
          unreadable_in_pkg: bool = False) -> tuple[str, str]:
    """A synthetic tree. The unreadable one is a DANGLING SYMLINK with a filename.

    🔴 THE FIRST EDITION TOOK A DIRECTORY AND DID NOT WORK: `os.walk` puts
    directories into `dirs`, and the traversal only reads `names` — an
    "unreadable file" never even reached `open`, and the control would have
    been the eighth form (the mutation never actually took place). Caught
    by running it: `unreadable == []` where 1 was expected.

    A dangling symlink sits in `names` (for `scandir` it is not a
    directory) and yields `FileNotFoundError` — this is an `OSError` for
    both a regular user and root, so the check does not depend on who runs
    it. `chmod 000` does not give that independence: under root the file
    would open, and the control would be green for the WRONG reason.
    """
    pkg = os.path.join(root, "kir")
    os.mkdir(pkg)
    with open(os.path.join(pkg, "probe.py"), "w", encoding="utf-8") as fh:
        fh.write('DEVICE = "%s"\n' % _SAMPLE)
    if unreadable_in_repo:
        docs = os.path.join(root, "docs")
        os.mkdir(docs)
        os.symlink("НЕТ-ТАКОГО-ФАЙЛА", os.path.join(docs, "нечитаемый.md"))
    if unreadable_in_pkg:
        os.symlink("НЕТ-ТАКОГО-ФАЙЛА", os.path.join(pkg, "нечитаемый.py"))
    return root, pkg


class AWalkReportsWhatItCouldNotRead(unittest.TestCase):

    def _rows(self, root: str, pkg: str) -> tuple[list[str], dict]:
        saved = C.REPO, C.PKG
        try:
            C.REPO, C.PKG = root, pkg
            return C._oss_boundary(), C.oss_boundary_walk()
        finally:
            C.REPO, C.PKG = saved

    def test_the_live_walk_reaches_the_whole_tree(self):
        """The denominator is asked for AS A NUMBER, not assumed."""
        walk = C.oss_boundary_walk()
        self.assertGreaterEqual(
            walk["seen"], C._OSS_WALK_FLOOR,
            "обход увидел меньше файлов, чем порог: это ответ О ЗОНДЕ "
            "(сорванный корень, пустой фильтр), а не о дереве")
        self.assertEqual(walk["unreadable"], [],
                         "на живом дереве нечитаемых быть не должно")
        self.assertEqual(walk["read"], walk["seen"])

    def test_a_readable_tree_says_nothing_about_blindness(self):
        """The second outcome. A caveat that is ALWAYS present means nothing —

        and on top of that would be moving the canon's text just for the sake of silence.
        """
        with tempfile.TemporaryDirectory() as tmp:
            rows, walk = self._rows(*_tree(tmp))
        self.assertEqual(walk["unreadable"], [])
        self.assertNotIn("ПРОЧИТАНО", rows[0])
        self.assertIn("**1 в 1 файлах**", rows[0],
                      "подсадное нарушение обязано находиться, иначе обход "
                      "проверен на пустом входе")

    def test_an_unreadable_file_is_named_in_the_row_beside_the_zero(self):
        """THAT VERY SAME thing: a zero MUST say that it is about WHAT WAS READ."""
        with tempfile.TemporaryDirectory() as tmp:
            rows, walk = self._rows(*_tree(tmp, unreadable_in_repo=True))
        self.assertEqual(len(walk["unreadable"]), 1, walk["unreadable"])
        self.assertIn("нечитаемый.md", walk["unreadable"][0])
        self.assertIn("ПРОЧИТАНО", rows[0],
                      "оговорка обязана стоять В ТОЙ ЖЕ КЛЕТКЕ, где число: "
                      "примечание под таблицей читатель не увидит")
        self.assertIn("нечитаемый.md", rows[0],
                      "отказ обязан назвать ФАЙЛ, иначе следующий пойдёт "
                      "искать его сам")
        self.assertLess(walk["read"], walk["seen"])

    def test_the_second_walk_no_longer_drops_the_whole_canon(self):
        """The `PKG` traversal used a bare `open`: there, a skip was a CRASH.

        Checking both ends of the one road: the traversal MUST reach the
        end and name what was not traversed — in both directions.
        """
        with tempfile.TemporaryDirectory() as tmp:
            rows, walk = self._rows(*_tree(tmp, unreadable_in_pkg=True))
        self.assertTrue(rows, "обход упал вместо того, чтобы назвать отказ")
        self.assertTrue(any("нечитаемый.py" in b for b in walk["unreadable"]),
                        walk["unreadable"])
        self.assertIn("ПРОЧИТАНО", rows[0])

    def test_the_floor_is_below_the_live_denominator_and_not_pinned_to_it(self):
        """The threshold guards "there was no traversal", not the growth of the tree.

        A threshold set tight against today's number would turn red on
        every weeding-out of tests — and it would be removed within a week,
        guard and all.
        """
        self.assertLess(C._OSS_WALK_FLOOR, C.oss_boundary_walk()["seen"])


if __name__ == "__main__":
    unittest.main()
