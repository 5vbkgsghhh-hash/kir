"""GUARD FOR THE SECOND SELECTION PATH — an index BY REQUEST, not by an open
window.

What is guarded here and what is NOT. The wave governs the SELECTION of the
target, not the output: the assembled index is the subject of
`test_building_index`, and duplicating its checks here would mean setting up
two places obliged to agree. What is checked here is precisely the seam:
request -> building -> the same `index_from_run`, and the three outcomes of
selection.

The L0 fixture is written by the prod reader in reverse — via
`L0JSONLReader`, which also parses it; the file's shape is not invented here
from memory.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest

from kir.building_index import BuildingIndexError, index_from_query


def _l0(doc_name: str, stamp: str, elements: int) -> str:
    """An L0 stream assembled from PROD TYPES, not by hand.

    🔴 THE FIRST DRAFT OF THIS HELPER WAS WRITTEN FROM MEMORY AND FAILED
    (`ExtractionProtocolError: header.document must be an object`) — form 27
    in pure form: a test that assembles its own input by hand guards the
    fixture, not the product. The header now comes from
    `L0Document.metadata_dict()`, the element lines from
    `L0Element.to_dict()`, and the tail carries `category_status` and a
    `footer` with counters that `L0JSONLReader._records()` RE-VERIFIES on
    every read. If the format drifts, it turns red here.
    """
    from kir.decompile.extract import EXTRACT_CATEGORIES
    from kir.decompile.schema import (L0_SCHEMA_VERSION, GeometryKind,
                                           L0Document, L0Element, ProjectInfo)

    # 🔴 THE CATEGORY TABLE IS ASKED FOR, NOT NAMED. The reader checks
    # `category_status` against `EXTRACT_CATEGORIES` POSITIONALLY and
    # requires their count to match an existing dialect generation; a single
    # "OST_Walls" line yields a "no such generation existed" refusal. Here
    # the table itself remains the authority, so the fixture survives its
    # growth.
    categories = tuple(EXTRACT_CATEGORIES)
    carrier = categories[0]
    document = L0Document(doc_name=doc_name, revit_version="2023", units="mm",
                          change_stamp=stamp, levels=(), grids=(), rooms=(),
                          project_info=ProjectInfo())

    def dump(row: dict) -> str:
        return json.dumps(row, ensure_ascii=False, separators=(",", ":"),
                          sort_keys=True)

    lines = [dump({"record": "header", "schema_version": L0_SCHEMA_VERSION,
                   "document": document.metadata_dict()})]
    for index in range(elements):
        element = L0Element(
            element_id=str(900_000 + index), category=carrier,
            category_ru="Стены", type_id="T1", type_name="Стена 200",
            level_id="L1", level_name="Уровень 1",
            geom_kind=GeometryKind.CURVE,
            p0_mm=(0.0, 0.0, 0.0), p1_mm=(1000.0 * (index + 1), 0.0, 0.0),
            rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=None, params={})
        lines.append(dump({"record": "element", "collector": carrier,
                           "element": element.to_dict()}))
    for category in categories:
        count = elements if category == carrier else 0
        lines.append(dump({"record": "category_status", "status": {
            "category": category, "state": "complete",
            "extracted_count": count, "expected_count": count,
            "error": None, "section_receipts": None}}))
    lines.append(dump({"record": "footer", "stream_complete": True,
                       "element_count": elements, "link_count": 0,
                       "category_count": len(categories)}))
    return "\n".join(lines) + "\n"


def _card(doc_name: str, stamp: str, elements: int) -> str:
    from kir.decompile.pipeline import _passport_markdown

    return _passport_markdown({
        "doc_name": doc_name, "revit_version": "2023", "change_stamp": stamp,
        "gestalt": "Здание, контур не определён, 3 этажа по 3,3 м. "
                   "Назначение: не определено. Типовой этаж: не определён.",
        "stats": {"elements_total": elements, "ops_lifted": 1, "atoms": 0,
                  "floors": 3, "rooms": 0, "apartments": 0},
        "verify_summary": {"failed_count": 0, "reversible": True},
    })


class TheChoiceReachesTheIndex(unittest.TestCase):

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for run, doc, count in (("dom_v1", "Дом", 2), ("dom_v2", "Дом", 4),
                                ("sklad_v1", "Склад", 3)):
            path = os.path.join(self.tmp, run)
            os.makedirs(path)
            with open(os.path.join(path, "passport.md"), "w",
                      encoding="utf-8") as handle:
                handle.write(_card(doc, run, count))
            with open(os.path.join(path, "L0.jsonl"), "w",
                      encoding="utf-8") as handle:
                handle.write(_l0(doc, run, count))
            with open(os.path.join(path, "status.json"), "w",
                      encoding="utf-8") as handle:
                json.dump({"stage": "done"}, handle)

    def test_one_match_builds_the_index_and_shows_the_choice(self) -> None:
        """One was found — the index travels together with the SELECTION
        THAT WAS SHOWN.

        A selection the caller cannot see is a `.FirstOrDefault()` with a
        good reputation; `ground.py` learned this lesson in full.
        """
        payload = index_from_query("Склад", root=self.tmp)
        self.assertEqual(payload["tier"], "full")
        self.assertEqual(payload["census"]["total"], 3)
        self.assertEqual(payload["source_run"], "sklad_v1")
        self.assertEqual(payload["doc_name"], "Склад")
        self.assertEqual(payload["query"], "Склад")
        self.assertTrue(payload["chosen_rule"])
        self.assertEqual(payload["runners_up"], [])

    def test_the_named_rule_picks_the_fuller_run_and_names_the_loser(self):
        payload = index_from_query("Дом", root=self.tmp)
        self.assertEqual(payload["source_run"], "dom_v2")
        self.assertEqual(payload["census"]["total"], 4)
        self.assertEqual(payload["runners_up"], ["dom_v1"])

    def test_several_matches_refuse_and_list_them(self) -> None:
        """Several found — a REFUSAL with a list, not a silent first pick."""
        with self.assertRaises(BuildingIndexError) as caught:
            index_from_query("Здание", root=self.tmp)
        text = str(caught.exception)
        self.assertIn("Дом", text)
        self.assertIn("Склад", text)

    def test_no_match_refuses_with_the_way_in(self) -> None:
        with self.assertRaises(BuildingIndexError) as caught:
            index_from_query("небоскрёб", root=self.tmp)
        self.assertIn("здания корпуса:", str(caught.exception))

    def test_absent_corpus_is_a_different_refusal_than_absent_building(self):
        """«No corpus» and «no such thing in the corpus» are DIFFERENT
        facts.

        The first is not about buildings at all, and conflating them would
        mean reporting an empty world where we simply looked in the wrong
        place.
        """
        with self.assertRaises(BuildingIndexError) as caught:
            index_from_query("Дом", root=os.path.join(self.tmp, "нет"))
        self.assertIn("каталог корпуса не собрался", str(caught.exception))
        self.assertNotIn("каталог корпуса не собрался",
                         str(self.assertRaises(
                             BuildingIndexError,
                             index_from_query, "небоскрёб", root=self.tmp)))

    def test_census_is_the_default_and_refusing_it_is_opt_in(self) -> None:
        """The ceiling: a census is the default, refusal is by explicit
        request.

        A TARGETED FAIL CONTROL: the ceiling is lowered to 200B, and this
        must change the outcome for EXACTLY this call. A census must not be
        silently swapped for a refusal — a census is an honest answer —
        which is why `allow_census=False` exists and must be explicit.
        """
        squeezed = index_from_query("Склад", root=self.tmp,
                                    ceiling_bytes=200)
        self.assertEqual(squeezed["tier"], "census")
        self.assertIn("не поместилось", squeezed["refused"])
        self.assertEqual(squeezed["elements"], [])
        # The same input, but the caller is not willing to wait -> a
        # refusal, not emptiness.
        with self.assertRaises(BuildingIndexError) as caught:
            index_from_query("Склад", root=self.tmp, ceiling_bytes=200,
                             allow_census=False)
        self.assertIn("не поместится", str(caught.exception))
        # And the control in the other direction: with the normal ceiling
        # there is NO refusal.
        self.assertEqual(
            index_from_query("Склад", root=self.tmp,
                             allow_census=False)["tier"], "full")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
