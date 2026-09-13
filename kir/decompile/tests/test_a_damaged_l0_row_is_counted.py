"""A BROKEN SNAPSHOT ROW MUST BE COUNTED, NOT VANISH (F-057).

THE TRIGGER. `graph_store.read_l0_parts` was silently skipping an unreadable
row — `except ValueError: continue` and `not isinstance(record, Mapping):
continue`, both leaving not a single trace. A damaged or truncated snapshot
produced a SMALLER BUILDING, and it looked perfectly normal.

🔴 WHY THE CENSUS'S LAW DID NOT CATCH THIS, EVEN THOUGH IT IS EXACTLY ABOUT
THIS. `GraphCensus.assert_balanced` holds the equality "nodes + refusals =
rows". But `rows_seen` is counted from the rows that REACHED
`graph_from_l0`, and a broken row never reached it — it dropped out of
BOTH sides of the equality at once. The law added up, and it added up
ABOUT WHAT WAS LEFT. This is checked here by execution
(`TheLawCouldNotCatchItByItself`), not asserted in prose: a guard whose
blindness was never demonstrated will tomorrow be declared sufficient.

THE SHAPE OF THE FIX IS A NUMBER NEXT TO THE ANSWER, NOT A REFUSAL. A
snapshot's tail can be LEGITIMATELY cut short (a run interrupted, no
footer), and failing the whole corpus's reading over that would mean
trading one blindness for another. The same shape as
`GraphCensus.sources_absent` and `artifact_absent_note`.

MEASURED ON THE LIVE CORPUS 29.08.2026 (read-only): 81 L0 files,
**1 724 404 rows, 0 unreadable**. Today the fix is INERT — not one census
will move; it is not being added for that reason, but because there was
NOTHING AT ALL to check this with.

Run it:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_a_damaged_l0_row_is_counted.py -q
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kir.decompile import graph_store as gs
from kir.decompile.building_graph import (
    GraphBuildError,
    GraphCensus,
    NodeRefusal,
    graph_from_l0,
)

_HEADER = {"document": {"doc_name": "d", "levels": [], "grids": [],
                        "rooms": []}}


def _element(element_id: str) -> dict:
    return {"element": {"element_id": element_id, "category": "OST_Walls",
                        "category_ru": "Стены", "type_id": "7",
                        "type_name": "W200"}}


def _write_l0(directory: Path, *lines: str) -> Path:
    path = gs.l0_path(directory)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


#: 🔴 TWO CORRUPTIONS, NOT ONE, AND NOT FOR THE SAKE OF A NUMBER. The old
#: code was swallowing them with DIFFERENT branches (`except ValueError`
#: and `not isinstance(..., Mapping)`), and fixing one branch would have
#: left the other blind — exactly the case where a red for a known reason
#: hides a neighboring one.
_BROKEN_JSON = '{"element": {"element_id": "300",'
_VALID_JSON_NOT_AN_OBJECT = '["это законный JSON и не запись"]'


class TheDamagedRowReachesTheCensus(unittest.TestCase):
    """The behavioral half — on a REAL file, not on a faked input."""

    def test_a_clean_snapshot_names_no_unreadable_row(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            _write_l0(run, json.dumps(_HEADER, ensure_ascii=False),
                      json.dumps(_element("100"), ensure_ascii=False),
                      json.dumps(_element("101"), ensure_ascii=False))
            graph = gs.build_graph_for_run(run)
            self.assertEqual(graph.census.rows_seen, 2)
            self.assertEqual(graph.census.nodes, 2)
            self.assertNotIn(NodeRefusal.ROW_UNREADABLE.value,
                             graph.census.refusals)

    def test_both_kinds_of_damage_are_counted_and_named(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            _write_l0(run, json.dumps(_HEADER, ensure_ascii=False),
                      json.dumps(_element("100"), ensure_ascii=False),
                      _BROKEN_JSON,
                      json.dumps(_element("101"), ensure_ascii=False),
                      _VALID_JSON_NOT_AN_OBJECT)
            graph = gs.build_graph_for_run(run)
            self.assertEqual(
                graph.census.refusals.get(NodeRefusal.ROW_UNREADABLE.value), 2,
                "непрочитанная строка снова исчезла: здание уменьшилось молча")
            self.assertEqual(graph.census.nodes, 2)
            self.assertEqual(
                graph.census.rows_seen, 4,
                "битая строка обязана входить в `rows_seen`: она БЫЛА в снимке")
            # The law must add up WITH IT, not around it.
            graph.census.assert_balanced()

    def test_the_reader_reports_the_same_number_it_hid_before(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            _write_l0(run, json.dumps(_HEADER, ensure_ascii=False),
                      json.dumps(_element("100"), ensure_ascii=False),
                      _BROKEN_JSON, _VALID_JSON_NOT_AN_OBJECT)
            header, rows, links, unreadable = gs.read_l0_parts_counted(run)
            self.assertEqual(unreadable, 2)
            self.assertEqual(len(rows), 1)
            self.assertEqual(header["doc_name"], "d")
            self.assertEqual(links, [])


class TheOldShapeIsNotBroken(unittest.TestCase):
    """D3: the name is not renamed, the tuple is not extended — nothing to break."""

    def test_read_l0_parts_still_unpacks_into_three(self):
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            _write_l0(run, json.dumps(_HEADER, ensure_ascii=False),
                      json.dumps(_element("100"), ensure_ascii=False),
                      _BROKEN_JSON)
            header, rows, links = gs.read_l0_parts(run)
            self.assertEqual(len(rows), 1)
            self.assertEqual(links, [])
            self.assertEqual(header["doc_name"], "d")


class TheLawCouldNotCatchItByItself(unittest.TestCase):
    """🔴 DEMONSTRATING THE GUARD'S BLINDNESS, not telling a story about it.

    If the census's law caught a missing row by itself, this fix would be
    redundant. It does not catch it — and here is the execution that shows
    that.
    """

    def test_a_census_of_the_survivors_is_balanced_and_wrong(self):
        # Exactly what the old code built on a four-row snapshot, two of
        # which are broken: it saw two, and both became nodes.
        survivors = GraphCensus(rows_seen=2, nodes=2, refusals={})
        survivors.assert_balanced()  # does not raise — the law ADDED UP

    def test_the_same_census_with_the_row_counted_needs_a_named_reason(self):
        with self.assertRaises(GraphBuildError):
            # The row was put back into `rows_seen`, but the reason was not
            # named: the law must turn red. This is exactly what it could
            # not do before — the number never reached it.
            GraphCensus(rows_seen=4, nodes=2, refusals={}).assert_balanced()


class TheCountIsValidated(unittest.TestCase):
    """`unreadable_rows` is a number, and a bad number must be a refusal."""

    def test_a_negative_or_boolean_count_is_refused(self):
        for value in (-1, True, 1.5, "2"):
            with self.subTest(value=value):
                with self.assertRaises(GraphBuildError):
                    graph_from_l0({"doc_name": "d"}, iter(()),
                                  unreadable_rows=value)

    def test_zero_is_the_default_and_adds_nothing(self):
        graph = graph_from_l0({"doc_name": "d"}, iter(()))
        self.assertEqual(graph.census.rows_seen, 0)
        self.assertEqual(dict(graph.census.refusals), {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
