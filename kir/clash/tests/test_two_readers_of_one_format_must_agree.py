"""THE CLASH READER PROMISED PROVEN COMPLETENESS, AND ACCEPTED SIX KINDS OF CORRUPTION (F-115).

`read_decompile` declares in its header: "the stream must prove its own
completeness, and anything not included in it must be NAMED by a number"
(review #10). The promise was kept HALFWAY:

* all three footer checks stood under `isinstance(..., int)` — a missing or
  non-numeric promise was silently NOT checked;
* the order of records was not checked at all: a second header silently
  overwrote the first, records after the footer kept accumulating, and an
  unknown kind fell through past every branch.

The canonical `extract.L0JSONLReader` rejects all six by name. So the input
is already invalid BY THE FORMAT'S LAW, and a new refusal cannot fire on a
legitimate one.

🔴 THE MOST EXPENSIVE CASE — `element_count: "99"` with one element: the
footer's promise is KNOWINGLY wrong, the check exists precisely to catch it,
and it stayed silent only because the number arrived AS A STRING.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
import unittest

from kir.clash import snapshot as S


HEADER = {"record": "header", "schema_version": "1.0",
          "document": {"doc_name": "t", "revit_version": "2023",
                       "levels": [{"id": "1", "name": "L1",
                                   "elevation_mm": 0.0}]}}
ELEMENT = {"record": "element",
           "element": {"element_id": 101, "category": "OST_Walls",
                       "bbox_min_mm": [0, 0, 0],
                       "bbox_max_mm": [1000, 200, 3000]}}
FOOTER = {"record": "footer", "stream_complete": True, "element_count": 1,
          "category_count": 0, "link_count": 0}


class ПотокОбязанДоказатьСвоюПолноту(unittest.TestCase):

    def _run(self, rows: list[dict]) -> pathlib.Path:
        d = pathlib.Path(tempfile.mkdtemp()) / "run"
        d.mkdir(parents=True)
        (d / "L0.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
            encoding="utf-8")
        return d

    def test_a_whole_stream_is_still_read_exactly_as_before(self):
        """🔴 THE SECOND OUTCOME, and it is mandatory: without it, a fix of
        "always refuse" would pass all six checks below and would switch off
        reading decompiles entirely."""
        elements, _profiles, _curves, origin = S.read_decompile(
            self._run([HEADER, ELEMENT, FOOTER]))
        self.assertEqual(len(elements), 1)
        self.assertIs(origin["stream_complete"], True)
        self.assertEqual(origin["elements_in_l0"], 1)

    def test_a_footer_without_a_count_is_refused(self):
        rows = [HEADER, ELEMENT,
                {"record": "footer", "stream_complete": True,
                 "category_count": 0, "link_count": 0}]
        with self.assertRaises(S.SnapshotIntegrityError) as caught:
            S.read_decompile(self._run(rows))
        self.assertIn("element_count", str(caught.exception))

    def test_a_count_that_arrives_as_a_string_is_refused(self):
        for declared in ("1", "99"):
            with self.subTest(declared=declared):
                rows = [HEADER, ELEMENT, dict(FOOTER, element_count=declared)]
                with self.assertRaises(S.SnapshotIntegrityError) as caught:
                    S.read_decompile(self._run(rows))
                self.assertIn("не целое", str(caught.exception))

    def test_the_other_two_counts_are_checked_by_the_same_law(self):
        """Three numbers of one footer, and separately they do not substitute for each other."""
        for field in ("category_count", "link_count"):
            with self.subTest(field=field):
                footer = dict(FOOTER)
                del footer[field]
                with self.assertRaises(S.SnapshotIntegrityError) as caught:
                    S.read_decompile(self._run([HEADER, ELEMENT, footer]))
                self.assertIn(field, str(caught.exception))

    def test_a_record_after_the_footer_is_refused(self):
        rows = [HEADER, ELEMENT, FOOTER, ELEMENT,
                dict(FOOTER, element_count=2)]
        with self.assertRaises(S.SnapshotIntegrityError) as caught:
            S.read_decompile(self._run(rows))
        self.assertIn("ПОСЛЕ футера", str(caught.exception))

    def test_a_second_header_is_refused(self):
        """A second header SILENTLY OVERWROTE the first: the snapshot took its
        document from the last one and did not know which building it was
        talking about."""
        other = {"record": "header", "schema_version": "1.0",
                 "document": {"doc_name": "ДРУГОЙ", "revit_version": "2019"}}
        with self.assertRaises(S.SnapshotIntegrityError) as caught:
            S.read_decompile(self._run([HEADER, other, ELEMENT, FOOTER]))
        self.assertIn("ВТОРОЙ заголовок", str(caught.exception))

    def test_an_unknown_record_kind_is_refused(self):
        rows = [HEADER, ELEMENT, {"record": "НОВЫЙ-РОД", "payload": {}},
                FOOTER]
        with self.assertRaises(S.SnapshotIntegrityError) as caught:
            S.read_decompile(self._run(rows))
        self.assertIn("неизвестный род записи", str(caught.exception))


class ЭтотЧитательЧитаетПОДМНОЖЕСТВО(unittest.TestCase):
    """🔴 A RATCHET ON THE DECISION, NOT ON THE CODE (F-115).

    The package called the "ask the authority" shape preferred: prove
    completeness by calling `L0JSONLReader.validate()`, so the format would
    have ONE reader. Measurement showed that this is a refusal on a
    LEGITIMATE input: the canonical reader requires a COMPLETE document
    header (`revit_version`, `units`, `levels`, `grids`, `rooms`,
    `project_info`), which the clash reader never needed — it reads a
    SUBSET. Put in place experimentally, that shape turned 10 checks red on
    legitimate tree fixtures.

    The test guards the DECISION: as long as this claim holds, the "ask the
    authority" shape remains a refusal on a legitimate input. If it stops
    holding — the headers have converged — the decision can be revisited
    with a number in hand, not from memory.
    """

    def test_the_canonical_reader_refuses_a_header_this_reader_accepts(self):
        from kir.decompile.extract import (
            ExtractionProtocolError, L0JSONLReader)
        d = pathlib.Path(tempfile.mkdtemp()) / "run"
        d.mkdir(parents=True)
        (d / "L0.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n"
                    for r in (HEADER, ELEMENT, FOOTER)), encoding="utf-8")
        elements, _p, _c, origin = S.read_decompile(d)
        self.assertEqual(len(elements), 1)
        self.assertIs(origin["stream_complete"], True)
        with self.assertRaises(ExtractionProtocolError) as caught:
            L0JSONLReader(d / "L0.jsonl").validate()
        self.assertIn("document is missing required fields",
                      str(caught.exception))


if __name__ == "__main__":
    unittest.main()
