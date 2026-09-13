"""READ BY THE SAME LAW BY WHICH IT WAS ACCEPTED (F-314 · F-324).

Both locks judged the PRESENCE of a decompile through `snapshot_file_exists`,
which DELIBERATELY answers `True` for `L0.jsonl.gz` — the cleaner compresses
cooled decompiles in place, and the store (0.5 GB per building) cools by
construction. But they opened the file with a bare `open`/`read_text`. The
instrument said "found" and a line later raised `FileNotFoundError`: a
legitimate archived decompile was UNCHECKABLE AT ALL.

A discrepancy between two laws about the SAME file is not "tracing trivia": a
lock that accepted the input and then failed to read it refuses for a reason
that does not exist in the building, and sends the author to fix the wrong
thing.

🔴 NEXT TO EVERY COMPRESSED RUN STANDS A RAW ONE, AND THE NUMBERS MUST MATCH.
Without this, a fix of "always open the .gz" is indistinguishable from a
correct one, and compression would stop being indifferent to the result —
exactly the property `snapshot_io` exists for.
"""

from __future__ import annotations

import gzip
import json
import pathlib
import tempfile
import unittest
from unittest import mock

from kir.clash.tools import bundle_containment_gate as BG
from kir.clash.tools import wall_prism_gate as WG


HEADER = {"record": "header",
          "document": {"levels": [{"id": "L1", "elevation_mm": 0.0}]}}
WALL = {"element_id": 3, "category": "OST_Walls", "level_id": "L1",
        "bbox_min_mm": [-5000, -5000, 0], "bbox_max_mm": [6000, 5000, 3000],
        "p0_mm": [0, 0, 0], "p1_mm": [1000, 0, 0],
        "params": {"WALL_ATTR_WIDTH_PARAM": 200.0,
                   "WALL_USER_HEIGHT_PARAM": 3000.0}}

L0_TEXT = (json.dumps(HEADER, ensure_ascii=False) + "\n"
           + json.dumps({"record": "element", "element": WALL},
                        ensure_ascii=False) + "\n")
CURVE_TEXT = json.dumps({"curve_index": {}}, ensure_ascii=False)


def _make(root: pathlib.Path, name: str, *, l0_gz: bool,
          curve_gz: bool | None) -> pathlib.Path:
    d = root / name
    d.mkdir(parents=True)
    if l0_gz:
        with gzip.open(d / "L0.jsonl.gz", "wt", encoding="utf-8") as handle:
            handle.write(L0_TEXT)
    else:
        (d / "L0.jsonl").write_text(L0_TEXT, encoding="utf-8")
    if curve_gz is True:
        (d / "curve.index.json.gz").write_bytes(
            gzip.compress(CURVE_TEXT.encode("utf-8")))
    elif curve_gz is False:
        (d / "curve.index.json").write_text(CURVE_TEXT, encoding="utf-8")
    return d


class ЗамокПризмыЧитаетСжатыйРазбор(unittest.TestCase):

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())
        patcher = mock.patch.object(WG, "ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _numbers(self, row: dict) -> tuple:
        return (row["target_population"]["walls_total"],
                row["target_population"]["ground_truth_walls_with_bbox"],
                row["judged"],
                row["non_containing_diagnosis"]["count"],
                row["gate_open"])

    def test_a_gz_only_run_is_analysed_and_agrees_with_the_raw_one(self):
        _make(self.root, "gz", l0_gz=True, curve_gz=True)
        _make(self.root, "raw", l0_gz=False, curve_gz=False)
        got, want = WG.analyse("gz"), WG.analyse("raw")
        self.assertNotIn("error", got)
        self.assertEqual(self._numbers(got), self._numbers(want))
        # 🔴 The numbers are not empty: two ZEROES matching proves nothing.
        self.assertEqual(self._numbers(want), (1, 1, 1, 1, False))

    def test_a_gz_side_index_is_read_too(self):
        """A SECOND place with the same discrepancy in the SAME instrument, and
        it does NOT follow from the first: L0 is raw, but the side index is
        compressed."""
        _make(self.root, "mixed", l0_gz=False, curve_gz=True)
        _make(self.root, "raw2", l0_gz=False, curve_gz=False)
        self.assertEqual(self._numbers(WG.analyse("mixed")),
                         self._numbers(WG.analyse("raw2")))

    def test_a_missing_run_is_still_named_as_missing(self):
        """🔴 THE SECOND OUTCOME. The fix does not turn `snapshot_file_exists`
        into "everything exists": there is no decompile — the instrument says
        so in words."""
        self.assertEqual(WG.analyse("нет-такого"),
                         {"run": "нет-такого", "error": "нет L0.jsonl"})


class ЗамокСодержанияЧитаетСжатыйРазбор(unittest.TestCase):

    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp())

    def test_a_gz_only_run_is_read_and_agrees_with_the_raw_one(self):
        gz = _make(self.root, "gz", l0_gz=True, curve_gz=None)
        raw = _make(self.root, "raw", l0_gz=False, curve_gz=None)
        # 🔴 NOT `(gz / "L0.jsonl").exists()`: a bare existence check of the
        # SNAPSHOT'S NAME is forbidden across the whole tree
        # (`test_snapshot_existence_is_asked`), and the ban is correct — that
        # check is exactly the original defect. The claim that the RAW file is
        # absent is made from the directory's CONTENTS, which also makes it
        # stricter.
        self.assertEqual(sorted(x.name for x in gz.iterdir()),
                         ["L0.jsonl.gz"])
        got, want = BG.read_l0(gz), BG.read_l0(raw)
        self.assertEqual(got, want)
        # The numbers are not empty.
        levels, elements = want
        self.assertEqual((len(levels), len(elements)), (1, 1))

    def test_resolution_and_reading_now_judge_by_the_same_law(self):
        """The heart of the finding: `_resolve` ACCEPTED a compressed run,
        while `read_l0` failed on it. Both laws must agree on the exact same
        input."""
        _make(self.root, "cold", l0_gz=True, curve_gz=None)
        with mock.patch.object(BG, "_roots", lambda: (self.root,)):
            resolved = BG._resolve("cold")
        self.assertEqual(resolved, self.root / "cold")
        levels, elements = BG.read_l0(resolved)
        self.assertEqual((len(levels), len(elements)), (1, 1))

    def test_a_run_that_is_absent_is_still_refused(self):
        """🔴 THE SECOND OUTCOME."""
        with mock.patch.object(BG, "_roots", lambda: (self.root,)):
            with self.assertRaises(SystemExit):
                BG._resolve("нет-такого")


if __name__ == "__main__":
    unittest.main()
