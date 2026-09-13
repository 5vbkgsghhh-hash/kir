"""«NO INDEX» AND «MEASURED ZERO» ARE DIFFERENT FACTS ABOUT THE BUILDING.

An audit finding, `F-247` (29.08.2026). `corpus.group_index`/`curtain_index`
return empty on a missing file — and this answer must not be dropped: the
lesson MUST be assembled even over an incomplete decompile. But the empty
result was travelling into the course's numbers as ZERO, and was
indistinguishable from a REAL zero:

    group_definitions("здание_без_индекса")  ->  0.0
    group_definitions("здание_с_пустым")     ->  0.0

🔴 THE COST IS HIGHER THAN USUAL RIGHT HERE. The MODEL reads the course's
numbers and reads them as measurements of real buildings. A recorded zero
where there was no index teaches it that groups and curtain walls are not
used — and `create_group` is exactly the named principal unused multiplier
of the language.

🔴 THE COMPANION WAS WRITTEN AND FIT FOR USE — NOBODY EVER CALLED IT.
`corpus.index_absent_reason` had distinguished these three outcomes from
the very start. It was not in `__all__`, no KIR module called it, and the
course's guard called it ONLY inside `if drift` — that is, exactly where a
discrepancy had already been found. A measurement RECORDED as zero and
RECOMPUTED as zero from an ABSENT index gives no discrepancy: the guard was
green BY CONSTRUCTION, and "closed by the companion" was a lie not about
the companion, but about whether it is reachable to call at all.

WHY THE CURE IS A VALUE, NOT A SECOND CALL. A cause that has to be asked
for separately gets forgotten — has already been forgotten, and that is
exactly the finding. `SideIndex` is a `dict` subclass: it IS EQUAL to `{}`,
is falsy in a condition, goes into `len`, `.get`, `json.dumps`, and into a
loop, so not a single reader today (including OUTSIDE of KIR) sees the
difference; the cause travels TOGETHER WITH the value.

WHY THE LIST OF INDEXES IS NOT COMPILED BY HAND. `SIDE_INDEXES` is filled
in by the readers THEMSELVES. Enumerating them a second place would mean
setting up a pair that will drift apart — the same class of defect as
`F-190`.

FAIL CONTROL performed: removing `absent_reason` flags the first two
cases red; removing the reader's registration flags the third; a
legitimate empty index remains green across all editions.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest


def _building(root: str, name: str, *, with_indexes: bool) -> str:
    d = os.path.join(root, name)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "L0.jsonl"), "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"record": "element", "element": {
            "element_id": "1", "category": "Стены", "type_id": "T1"}}) + "\n")
    if with_indexes:
        # EMPTY, BUT PRESENT — a legitimate zero that MUST survive.
        for fname, key in (("group.index.json", "group_index"),
                           ("curtain.index.json", "curtain_index")):
            with open(os.path.join(d, fname), "w", encoding="utf-8") as fh:
                json.dump({key: {}}, fh)
    return name


class ОтсутствующийИндексНеИзмеренныйНоль(unittest.TestCase):

    def setUp(self) -> None:
        from kir.course import corpus
        self.corpus = corpus
        self._root = tempfile.TemporaryDirectory()
        self.addCleanup(self._root.cleanup)
        self._saved = corpus.DECOMPILE_ROOT
        corpus.DECOMPILE_ROOT = self._root.name
        self.addCleanup(setattr, corpus, "DECOMPILE_ROOT", self._saved)
        self.missing = _building(self._root.name, "без_индекса",
                                 with_indexes=False)
        self.empty = _building(self._root.name, "пустой_индекс",
                               with_indexes=True)

    def test_the_number_alone_cannot_tell_them_apart(self) -> None:
        """THE FINDING'S SUBJECT, BY NUMBER. Both buildings give 0.0 — and the
        fix does NOT change this: the number MUST remain the number,
        otherwise everything that reads it breaks. What changes is that
        there is now an answer to "why" standing next to it."""
        self.assertEqual(self.corpus.group_definitions(self.missing), 0.0)
        self.assertEqual(self.corpus.group_definitions(self.empty), 0.0)

    def test_the_value_carries_the_reason_it_is_empty(self) -> None:
        gone = self.corpus.group_index(self.missing)
        real = self.corpus.group_index(self.empty)
        self.assertEqual(gone, {})
        self.assertEqual(real, {})
        self.assertIsNotNone(gone.absent_reason)
        self.assertIn("group.index.json", gone.absent_reason)
        # 🔴 THE GREEN OUTCOME. Without it the check would be "empty is
        # always suspicious" and would forbid a LEGITIMATE zero — the
        # second mistake instead of the first.
        self.assertIsNone(real.absent_reason)

    def test_the_curtain_half_behaves_the_same(self) -> None:
        self.assertIsNotNone(
            self.corpus.curtain_index(self.missing).absent_reason)
        self.assertIsNone(self.corpus.curtain_index(self.empty).absent_reason)

    def test_the_absence_list_comes_from_the_readers_not_from_a_hand_list(self) -> None:
        """BOTH OUTCOMES + THE DENOMINATOR CONTROL. An empty `SIDE_INDEXES`
        would make `side_index_absences` green about nothing at all."""
        self.assertEqual(set(self.corpus.SIDE_INDEXES),
                         {"group.index.json", "curtain.index.json"})
        for filename, reader in self.corpus.SIDE_INDEXES.items():
            with self.subTest(filename=filename):
                self.assertIs(reader, getattr(
                    self.corpus, filename.split(".")[0] + "_index"))
        self.assertEqual(len(self.corpus.side_index_absences(self.missing)),
                         len(self.corpus.SIDE_INDEXES))
        self.assertEqual(self.corpus.side_index_absences(self.empty), [])

    def test_a_building_absent_from_the_machine_says_so_differently(self) -> None:
        """THE THIRD OUTCOME. "There is no decompile on the machine" is a
        fact about the MACHINE, and it must not be merged with "the index
        was not captured": the next moves differ."""
        why = self.corpus.index_absent_reason("нет_такого_здания",
                                              "group.index.json")
        self.assertIsNotNone(why)
        self.assertIn("машине", why)
        self.assertNotIn("стадия не снималась", why)

    def test_an_outside_reader_sees_no_change_at_all(self) -> None:
        """AN ADDITIVE FIX. `group_definitions` and its neighbors are read
        OUTSIDE KIR (`tools/design/examples/method_baseline.py`), and
        `SideIndex` MUST be indistinguishable from `dict` in everything a
        dict is used for."""
        gone = self.corpus.group_index(self.missing)
        self.assertIsInstance(gone, dict)
        self.assertFalse(gone)
        self.assertEqual(len(gone), 0)
        self.assertEqual(list(gone), [])
        self.assertIsNone(gone.get("definitions"))
        self.assertEqual(json.dumps(gone), "{}")
        self.assertEqual(dict(gone), {})

    def test_the_satellite_is_reachable_from_outside_the_module(self) -> None:
        """HALF OF THE DEFECT WAS IN REACHABILITY: the companion existed and
        was not in `__all__`, so there was nothing with which to check
        "closed by the companion"."""
        for name in ("index_absent_reason", "side_index_absences",
                     "SideIndex", "SIDE_INDEXES"):
            with self.subTest(name=name):
                self.assertIn(name, self.corpus.__all__)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
