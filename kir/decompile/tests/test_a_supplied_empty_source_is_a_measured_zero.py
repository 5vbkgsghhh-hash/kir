"""AN EXPLICITLY SUPPLIED EMPTY VALUE IS A MEASURED ZERO, NOT A REFUSAL
(F-056).

`relation_count` declares THREE outcomes, verbatim:

    edges exist                — a number;
    a source was supplied, no edges — ZERO, a fact about the BUILDING;
    no source was supplied     — a REFUSAL, a fact about OUR reading.

The middle outcome was UNREACHABLE for an empty collection:
`graph_from_l0` decided "was a source supplied" by a TRUTHINESS CHECK, and
an empty set is falsy. This canceled a third of the instrument's own law —
exactly where the law is needed. The author knew of this shape and closed
HALF of it: a comment above the line guarded against the lie "supplied"
on a non-empty GENERATOR, and left the lie "not supplied" for an empty
collection.

🔴 THE SECOND HALF OF THE FIX MATTERS MORE THAN THE FIRST, AND WITHOUT IT
THE FIRST IS HARMFUL. As soon as empty became "supplied,"
`build_graph_for_run` must stop supplying it from a TRUNCATED snapshot:
otherwise an honest refusal "not read" would instantly become the FALSE
FACT "the building has zero relations" — one wrong statement replaced by
another. So an empty list is supplied ONLY from a stream read IN FULL, and
"in full" is three independent conditions at once.

MEASUREMENT OF THE LIVE CORPUS 30.08.2026 (81 decompiles with L0,
read-only):

    WHOLE · 0 relations      16     <- will say an honest zero for the first time
    WHOLE · relations exist  61
    NOT WHOLE · relations exist 4  <- and NOT ONE "not whole · 0 relations"

The sets do not intersect, meaning today the gate takes nothing away. It
stands not for today's corpus but so the sets do not intersect tomorrow.

Run:
    /opt/kir-audit/suite-venv/venv/bin/python -m pytest \
        kir/decompile/tests/test_a_supplied_empty_source_is_a_measured_zero.py -q
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kir.decompile import graph_store as gs
from kir.decompile.building_graph import (
    GraphBuildError,
    Relation,
    graph_from_l0,
)

_HEADER = {"doc_name": "e"}

_H = {"record": "header", "document": {"doc_name": "t"}}
_W = {"record": "element",
      "element": {"element_id": "W1", "category": "OST_Walls", "params": {}}}
_LNK = {"record": "link", "link": {"element_id": "LNK-1", "name": "K1.rvt"}}


def _footer(*, link_count: int) -> dict:
    return {"record": "footer", "stream_complete": True, "element_count": 1,
            "link_count": link_count, "category_count": 1}


def _run(rows) -> Path:
    directory = Path(TemporaryDirectory().name)
    directory.mkdir(parents=True, exist_ok=True)
    gs.l0_path(directory).write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8")
    return directory


class TheThirdOutcomeStopsEatingTheSecond(unittest.TestCase):
    """The core: an empty SUPPLIED value and a NOT-SUPPLIED one stopped
    being one fact."""

    def test_an_explicit_empty_source_answers_zero(self):
        graph = graph_from_l0(_HEADER, [], link_ids=[], joins={})
        self.assertNotIn("link_ids", graph.census.sources_absent)
        self.assertNotIn("joins", graph.census.sources_absent)
        self.assertEqual(0, graph.relation_count(Relation.HOSTED_IN_LINK))
        self.assertEqual(0, graph.relation_count(Relation.JOINED_TO))

    def test_an_omitted_source_still_refuses(self):
        """A NEGATIVE CONTROL. Without it, a fix that "removes the refusal
        entirely" would pass."""
        graph = graph_from_l0(_HEADER, [])
        self.assertIn("link_ids", graph.census.sources_absent)
        self.assertIn("joins", graph.census.sources_absent)
        for relation in (Relation.HOSTED_IN_LINK, Relation.JOINED_TO):
            with self.subTest(relation=relation.value):
                with self.assertRaises(GraphBuildError) as caught:
                    graph.relation_count(relation)
                self.assertIn("НЕ ИЗМЕРЕН", str(caught.exception))

    def test_the_two_are_not_the_same_answer(self):
        supplied = graph_from_l0(_HEADER, [], link_ids=[], joins={})
        omitted = graph_from_l0(_HEADER, [])
        self.assertNotEqual(supplied.census.sources_absent,
                            omitted.census.sources_absent)

    def test_an_empty_generator_is_supplied_and_is_not_consumed_early(self):
        """The previous safeguard is PRESERVED and strengthened: the
        iterator is not touched at all."""
        graph = graph_from_l0(_HEADER, [], link_ids=(x for x in []))
        self.assertNotIn("link_ids", graph.census.sources_absent)
        self.assertEqual(0, graph.relation_count(Relation.HOSTED_IN_LINK))

    def test_room_adjacency_is_deliberately_untouched(self):
        """It is not a SOURCE but a REQUEST: `False` means "not counted"."""
        graph = graph_from_l0(_HEADER, [], link_ids=[], joins={},
                              room_adjacency=False)
        self.assertIn("room_adjacency", graph.census.sources_absent)


class AnUnreadSnapshotNeverSaysZero(unittest.TestCase):
    """🔴 THE LEAD'S CENTRAL CONDITION: "not read" != "zero relations"."""

    def test_a_whole_snapshot_with_no_links_says_an_honest_zero(self):
        graph = gs.build_graph_for_run(_run([_H, _W, _footer(link_count=0)]))
        self.assertNotIn("link_ids", graph.census.sources_absent)
        self.assertEqual(0, graph.relation_count(Relation.HOSTED_IN_LINK))

    def test_a_snapshot_without_a_footer_keeps_the_refusal(self):
        graph = gs.build_graph_for_run(_run([_H, _W]))
        self.assertIn("link_ids", graph.census.sources_absent)
        with self.assertRaises(GraphBuildError):
            graph.relation_count(Relation.HOSTED_IN_LINK)

    def test_a_damaged_row_also_keeps_the_refusal(self):
        directory = _run([_H, _W, _footer(link_count=0)])
        path = gs.l0_path(directory)
        path.write_text(path.read_text(encoding="utf-8")
                        + '{"record": "element", "element": {\n',
                        encoding="utf-8")
        graph = gs.build_graph_for_run(directory)
        self.assertIn("link_ids", graph.census.sources_absent)

    def test_a_footer_that_declares_other_links_keeps_the_refusal(self):
        """A second witness: the footer's count must agree with what was
        read."""
        graph = gs.build_graph_for_run(_run([_H, _W, _footer(link_count=3)]))
        self.assertIn("link_ids", graph.census.sources_absent)

    def test_a_read_link_is_supplied_even_from_a_torn_snapshot(self):
        """A `link` record that was read stays read — whether or not the
        stream was read to the end."""
        graph = gs.build_graph_for_run(_run([_H, _LNK, _W]))
        self.assertNotIn("link_ids", graph.census.sources_absent)
        self.assertEqual(0, graph.relation_count(Relation.HOSTED_IN_LINK))


class TheReaderTellsTheTruthAboutItself(unittest.TestCase):
    """`L0Parts.whole` — three conditions, and none is derived from the
    other two."""

    def test_a_whole_stream_is_whole(self):
        parts = gs.read_l0_parts_detailed(_run([_H, _W, _footer(link_count=0)]))
        self.assertTrue(parts.whole)
        self.assertTrue(parts.committed)
        self.assertEqual(parts.unreadable, 0)
        self.assertEqual(parts.footer_link_count, 0)

    def test_each_condition_alone_makes_it_not_whole(self):
        no_footer = gs.read_l0_parts_detailed(_run([_H, _W]))
        self.assertFalse(no_footer.whole)
        self.assertFalse(no_footer.committed)

        mismatch = gs.read_l0_parts_detailed(
            _run([_H, _W, _footer(link_count=3)]))
        self.assertTrue(mismatch.committed)
        self.assertEqual(mismatch.unreadable, 0)
        self.assertFalse(mismatch.whole, "счёт футера не сверен")

    def test_the_older_shapes_still_unpack(self):
        """D3: not one previous caller is broken."""
        directory = _run([_H, _LNK, _W, _footer(link_count=1)])
        header, rows, links = gs.read_l0_parts(directory)
        self.assertEqual(links, ["LNK-1"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(header["doc_name"], "t")
        header2, rows2, links2, unreadable = gs.read_l0_parts_counted(directory)
        self.assertEqual((header2, rows2, links2), (header, rows, links))
        self.assertEqual(unreadable, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
