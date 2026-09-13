"""THE "HOW DESIGN WORKS" DOCUMENT MUST BE A MEASUREMENT, NOT A RECORD OF A MEASUREMENT.

Audit finding `F-179` (29.08.2026), `kir/course/design.py`. Until that day
the module had NOT A SINGLE TEST OF ITS OWN — and that is half the finding.

🔴 THE FIRST HALF: `available()` asked for ONE FILE OUT OF FIVE KINDS.

    return all(_json(run, "group.index.json") is not None for run in MEASURED_RUNS)

The document consumes five kinds of source — L0, family placement, curtain
wall, profile, tags — yet the presence of `group.index.json` was declared
proof that everything was present. With a live group index and every other
artifact torn down, the document printed WHOLE AND CONFIDENT.

🔴 THE SECOND HALF, WORSE THAN THE FIRST: `build_design_document()`
recomputed NOTHING. The numbers were taken from `RECORDED` — constants
captured on the day they were recorded. Rule 1 of the course states
plainly: "EVERY NUMBER IS RECOMPUTED… a stale measurement in a textbook is
indistinguishable from a fabrication." Verified by execution:
`"recompute" in inspect.getsource(build_design_document)` -> False.

🔴 THE THIRD THING, FOUND WHILE FIXING IT: the `RECORDED` docstring points
to a guard called `test_design_numbers_are_current`, WHICH DOES NOT EXIST
(`grep` over the tree: the only occurrence is this very reference). A
reference to a nonexistent ratchet is worse than none at all: it answers the
question "is this guarded?" with "yes." The guard is set up below.

WHY THE AVAILABILITY SIGNAL IS LENGTH, NOT TRUTH. The obvious
`if not m.recompute()` would count a LEGITIMATE ZERO as a missing source —
exactly the substitution the whole bundle (`F-247`) was written against. A
legitimate zero does exist here: `range_name` is recorded as `(2.2, 0.0)`.
The measurement showed that recomputing against a missing source returns a
SHORT list (`[]`), not a list of zeros.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from kir.course import design


class ОдинФайлНеДоказательствоКорпуса(unittest.TestCase):

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved = design.DECOMPILE_ROOT
        design.DECOMPILE_ROOT = self._tmp.name
        self.addCleanup(setattr, design, "DECOMPILE_ROOT", self._saved)

    def _only_group_index(self) -> None:
        """Exactly the finding's case: the group index EXISTS, nothing else does."""
        for run in design.MEASURED_RUNS:
            d = os.path.join(self._tmp.name, run)
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "group.index.json"), "w",
                      encoding="utf-8") as fh:
                json.dump({"group_index": {"definitions": {}}}, fh)

    def test_the_old_probe_would_have_said_yes_on_this_corpus(self) -> None:
        """🔴 THE FINDING'S SUBJECT, REPRODUCED. The old signal is true on
        this corpus — meaning the document would have printed in full."""
        self._only_group_index()
        old_probe = all(design._json(run, "group.index.json") is not None
                        for run in design.MEASURED_RUNS)
        self.assertTrue(old_probe, "случай находки не воспроизведён")

    def test_one_present_index_is_not_proof_of_the_whole_corpus(self) -> None:
        """While the new signal on the same corpus is false, and the
        document refuses WITH A NAMED CAUSE, rather than printing numbers
        from memory."""
        self._only_group_index()
        self.assertFalse(design.available())
        self.assertIn("НЕДОСТУПЕН", design.build_design_document())

    def test_an_empty_corpus_still_refuses(self) -> None:
        """THE GREEN OUTCOME that must survive: an empty corpus refused
        before the fix, and must refuse after it too."""
        self.assertFalse(design.available())
        self.assertIn("НЕДОСТУПЕН", design.build_design_document())


class ПризнакРазличаетНольИОтсутствие(unittest.TestCase):
    """🔴 THE MAIN PROPERTY, and it is checked ON A LEGITIMATE ZERO."""

    @staticmethod
    def _measured(values, recompute):
        return design.Measured(values=values, unit="%", what="проба", docs=2,
                               verdict="проба", recompute=recompute)

    def _with(self, recorded: dict):
        saved = design.RECORDED
        design.RECORDED = recorded
        self.addCleanup(setattr, design, "RECORDED", saved)

    def test_a_legitimate_zero_is_available(self) -> None:
        """A metric HONESTLY recomputed into zeros is available. `if not
        m.recompute()` would declare it missing — and that would be the
        second bug in place of the first."""
        self._with({"z": self._measured((0.0, 0.0), lambda: [0.0, 0.0])})
        self.assertTrue(design.available())
        self.assertEqual(design._recompute_all(), {"z": [0.0, 0.0]})

    def test_a_short_list_is_a_missing_source(self) -> None:
        """A missing source gives a SHORT list — that is how every recompute
        of this module works (captured by execution: `[]` on an empty
        corpus)."""
        self._with({"z": self._measured((1.0, 2.0), lambda: [1.0])})
        self.assertFalse(design.available())
        self.assertIsNone(design._recompute_all())

    def test_a_raising_recompute_is_a_missing_source_too(self) -> None:
        def boom():
            raise OSError("носителя нет")
        self._with({"z": self._measured((1.0, 2.0), boom)})
        self.assertFalse(design.available())

    def test_the_expected_length_comes_from_the_metric_itself(self) -> None:
        """How many values there must be is declared by the METRIC ITSELF
        (`len(m.values)`). A second list alongside it would be a second
        carrier."""
        self._with({"one": self._measured((1.0,), lambda: [1.0]),
                    "two": self._measured((1.0, 2.0), lambda: [1.0, 2.0])})
        self.assertTrue(design.available())
        self._with({"one": self._measured((1.0,), lambda: [1.0, 2.0])})
        self.assertFalse(design.available(),
                         "лишнее значение — тоже расхождение с объявленным")


class ДокументПечатаетПересчётАНеЗапись(unittest.TestCase):

    def test_the_document_prints_the_recomputed_value(self) -> None:
        """🔴 THE SECOND HALF OF THE FINDING. We swap in a recompute that
        DIVERGES from the record, and require the document to show the
        RECOMPUTE."""
        saved = dict(design.RECORDED)
        self.addCleanup(setattr, design, "RECORDED", saved)
        fake = {k: design.Measured(
            values=m.values, unit=m.unit, what=m.what, docs=m.docs,
            verdict=m.verdict,
            recompute=(lambda mm=m: [round(v + 1.0, 1) for v in mm.values]))
            for k, m in saved.items()}
        design.RECORDED = fake
        doc = design.build_design_document()
        self.assertNotIn("НЕДОСТУПЕН", doc)
        self.assertIn("42.1 % и 83.6 %", doc,
                      "напечатана ЗАПИСЬ (41.1/82.6), а не пересчёт")
        self.assertNotIn("41.1 % и 82.6 %", doc)

    def test_the_record_stays_in_place_as_a_record(self) -> None:
        """`RECORDED[...].values` IS NOT DELETED: a mismatch between the
        record and the recompute is itself the finding, and there is
        nothing to guard it with if the record doesn't exist."""
        self.assertEqual(design.RECORDED["group_share"].values, (41.1, 82.6))


class ЗаписьСходитсяСПересчётом(unittest.TestCase):
    """🔴 THE GUARD THE `RECORDED` DOCSTRING POINTED TO, AND WHICH DID NOT EXIST.

    A reference to a nonexistent ratchet is worse than none at all: it
    answers "guarded" to a question nobody ever checked. It is set up here;
    without a corpus it IS SKIPPED WITH A NAMED CAUSE, rather than going
    green silently.
    """

    def test_each_recorded_number_reproduces_from_the_corpus(self) -> None:
        fresh = design._recompute_all()
        if fresh is None:
            self.skipTest(
                f"корпуса разборов нет на этой машине "
                f"({design.DECOMPILE_ROOT}) — запись сверить не с чем; это "
                f"факт о МАШИНЕ, а не о числах")
        drift = [f"{k}: записано {design.RECORDED[k].values}, пересчёт {v}"
                 for k, v in fresh.items()
                 if list(design.RECORDED[k].values) != list(v)]
        self.assertEqual(drift, [], "\n  ".join([""] + drift))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
