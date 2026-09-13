"""THE BUILDING GRAPH REACHES THE PIPELINE. Refuting tests.

🔴 WHAT IS CLOSED HERE. `building_graph.py` (2 029 lines: ten assembly
relations, four modalities, the census as a condition for construction, the
versioned artifact `building-graph/1`) had NEVER been called from prod, NOT
ONCE. The 22.08.2026 measurement by grepping the tree: the only call to
`graph_from_l0` outside tests is `tools/address_spine.py:172`; the
`graph_store` header admitted this verbatim — "not soldered into the live
pipeline". The building's state was produced by hand only.

THREE THINGS THESE TESTS HOLD:

 1. the flag's default is ENABLED (switched on 22.08 by the corpus
    measurement), while disabling it remains possible by an EXPLICIT WORD, and
    disabled means the old bytes — no artifact, no line in `timing`;
 2. when enabled — the artifact lies next to the decompile, is read by its own
    reader, and its census converges;
 3. sources that ARE ALREADY LYING NEARBY get read. `link` records of the same
    L0 and `join.index.json` of the same directory were not fed into the graph
    before this wave, and their kinds (`hosted_in_link`, `joined_to`,
    `joined_at_end`) silently stood at zero — indistinguishable from a fact
    about the building.
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kir.decompile import graph_store as gs
from kir.decompile.building_graph import (
    GRAPH_ARTIFACT_SCHEMA, GRAPH_ARTIFACT_SCHEMA_V1)
from kir.decompile import pipeline as pipe
from kir.decompile.building_graph import Relation
from kir.decompile.tests.test_pipeline import FakePipelineBridge

_FLAG = "KUKAI_IR_BUILDING_GRAPH"


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class _FlagCase(unittest.TestCase):

    def setUp(self) -> None:
        self._saved = os.environ.get(_FLAG)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(_FLAG, None)
        else:
            os.environ[_FLAG] = self._saved

    def _decompile(self, tmp: str):
        return _run(pipe.run_decompile(
            FakePipelineBridge(), out_dir=tmp,
            change_stamp="graph-pipeline-v1"))


class TheFlagIsATRISTATE(_FlagCase):
    """🔴 THE DEFAULT WAS FLIPPED ON 22.08.2026 — and it must be checkable.

    The owner named the condition for the switch: the census converges on the
    CORPUS, not on a single building. The 22.08 run over
    `backend/data/decompile`: 88 directories, 12 without `L0.jsonl`, the graph
    assembled on **76 of 76**, **0** failures, `assert_balanced()` holds on
    **76 of 76** (1 576 343 nodes, 1 843 930 edges). Before that day's fixes
    there were FIVE failures.

    Disabling it remained possible and became an EXPLICIT WORD.
    """

    def test_the_default_is_now_ON(self) -> None:
        from kir.decompile.building_graph import building_graph_enabled
        os.environ.pop(_FLAG, None)
        self.assertTrue(building_graph_enabled())

    def test_an_explicit_word_still_turns_it_OFF(self) -> None:
        from kir.decompile.building_graph import building_graph_enabled
        for word in ("0", "false", "no", "off", " OFF "):
            os.environ[_FLAG] = word
            self.assertFalse(building_graph_enabled(), msg=word)

    def test_a_typo_does_not_silently_disable(self) -> None:
        """CONTROL IN THE REVERSE DIRECTION: swapping the default for a typo
        is forbidden."""
        from kir.decompile.building_graph import building_graph_enabled
        for word in ("1", "on", "yes", "ложь", "ПРАВДА", ""):
            os.environ[_FLAG] = word
            self.assertTrue(building_graph_enabled(), msg=word)


class TheFlagDecidesAndNothingElse(_FlagCase):

    def test_flag_off_writes_no_artifact_at_all(self) -> None:
        os.environ[_FLAG] = "0"
        with TemporaryDirectory() as tmp:
            result = self._decompile(tmp)
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertFalse(gs.graph_path(tmp).exists())
            self.assertIsNone(gs.load_graph(tmp))
            self.assertNotIn("building_graph", result.stages)
            self.assertNotIn("building_graph", result.timing["stage_ms"])

    def test_flag_on_puts_the_artifact_next_to_the_decompile(self) -> None:
        os.environ.pop(_FLAG, None)  # the default is already ON — we are checking exactly that
        with TemporaryDirectory() as tmp:
            result = self._decompile(tmp)
            self.assertTrue(result.ok, msg=result.to_dict())
            path = gs.graph_path(tmp)
            self.assertTrue(path.is_file(), "артефакта графа нет на диске")
            self.assertIn("building_graph", result.stages)
            self.assertIn("building_graph", result.timing["stage_ms"])

    def test_the_written_artifact_reads_back_through_its_own_reader(self) -> None:
        """Round-trip run: the reader rejects foreign bytes and accepts its
        own."""
        os.environ.pop(_FLAG, None)  # the default is already ON — we are checking exactly that
        with TemporaryDirectory() as tmp:
            result = self._decompile(tmp)
            self.assertTrue(result.ok, msg=result.to_dict())
            graph = gs.load_graph(tmp)
            self.assertIsNotNone(graph)
            graph.census.assert_balanced()
            payload = json.loads(gs.graph_path(tmp).read_text("utf-8"))
            # 🔴 THE PIN WAS RE-HUNG ON 07.09.2026 FROM `building-graph/1` TO A
            # CONSTANT, AND THIS IS NOT A WEAKENING. The literal was guarding
            # TWO things at once: that the pipeline writes its own shape, and
            # that the shape is specifically the first one. The second half
            # was getting in the way of the first — under a legitimate
            # `/1` -> `/2` migration the pin would go red exactly where
            # everything worked correctly, and would demand fixing the literal
            # every time. Now the version is named by the producer, and the
            # guard checks what it was set up for: that the pipeline's
            # artifact is of ITS OWN version, not any readable one (`/1` is
            # also readable, but the pipeline is no longer entitled to write
            # it). Strictness went up: a fingerprint that `/1` never had at
            # all is added below.
            self.assertEqual(payload["schema"], GRAPH_ARTIFACT_SCHEMA)
            self.assertNotEqual(payload["schema"], GRAPH_ARTIFACT_SCHEMA_V1)
            # The observation fingerprint reaches disk THROUGH THE PIPELINE,
            # not only in the builder's memory: without this line `/2` would
            # be a shape with no content — exactly "written" instead of
            # "built in".
            self.assertEqual(payload["fingerprint_status"],
                             graph.fingerprint_status)
            self.assertEqual(
                payload["observation"],
                None if graph.observation is None else graph.observation.to_dict())
            # The artifact's census is a census of L0 LINES, not the number of
            # nodes "however many came out": silent dropping is forbidden by
            # law.
            self.assertEqual(
                payload["census"]["nodes"] + sum(
                    payload["census"]["refusals"].values()),
                payload["census"]["rows_seen"])

    def test_the_graph_addresses_the_same_elements_the_run_counted(self) -> None:
        os.environ.pop(_FLAG, None)  # the default is already ON — we are checking exactly that
        with TemporaryDirectory() as tmp:
            result = self._decompile(tmp)
            graph = gs.load_graph(tmp)
            self.assertEqual(graph.census.rows_seen, result.elements_total)


class SourcesLyingNextToTheRunAreRead(_FlagCase):
    """A zero for a kind whose source lies two steps away is our blindness."""

    def test_predicate_B_is_computed_so_its_zero_is_a_fact_about_the_building(
            self) -> None:
        os.environ.pop(_FLAG, None)  # the default is already ON — we are checking exactly that
        with TemporaryDirectory() as tmp:
            self._decompile(tmp)
            graph = gs.load_graph(tmp)
            self.assertNotIn("room_adjacency", graph.census.sources_absent)
            # `relation_count` REFUSES if the source was not supplied — so the
            # very fact that a number was obtained is itself proof it was
            # computed.
            graph.relation_count(Relation.OPENING_POINT_TOUCHES_ROOM)

    def test_the_join_index_on_disk_reaches_the_graph(self) -> None:
        os.environ.pop(_FLAG, None)  # the default is already ON — we are checking exactly that
        with TemporaryDirectory() as tmp:
            self._decompile(tmp)
            self.assertTrue((Path(tmp) / gs.JOIN_INDEX_NAME).is_file())
            graph = gs.load_graph(tmp)
            self.assertNotIn("joins", graph.census.sources_absent)
            graph.relation_count(Relation.JOINED_TO)

    def test_the_link_records_of_the_same_L0_reach_the_graph(self) -> None:
        """`link` records lay in the same file and were being discarded by the
        reader."""
        os.environ.pop(_FLAG, None)  # the default is already ON — we are checking exactly that
        with TemporaryDirectory() as tmp:
            self._decompile(tmp)
            _header, _rows, links = gs.read_l0_parts(tmp)
            self.assertTrue(links, "мини-разбор обязан нести запись link")
            graph = gs.load_graph(tmp)
            self.assertNotIn("link_ids", graph.census.sources_absent)
            graph.relation_count(Relation.HOSTED_IN_LINK)

    def test_the_run_leaves_NOTHING_unmeasured(self) -> None:
        """All three optional inputs are supplied — and this is CHECKED, not
        promised: `unmeasured_relations()` must be empty.

        The reverse side (the instrument can also NOT call something measured)
        is held by the synthetic cases below, where the input is explicitly
        removed.
        """
        os.environ.pop(_FLAG, None)  # the default is already ON — we are checking exactly that
        with TemporaryDirectory() as tmp:
            self._decompile(tmp)
            graph = gs.load_graph(tmp)
            self.assertEqual(graph.census.sources_absent, ())
            self.assertEqual(graph.unmeasured_relations(), ())


class TheReaderPicksUpLinkRecords(unittest.TestCase):
    """`read_l0_raw` took `document` and `element` and SILENTLY lost `link`."""

    def _write(self, path: Path, records: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def test_link_ids_come_out_of_the_same_file(self) -> None:
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            self._write(run / "L0.jsonl", [
                {"record": "header", "document": {"doc_name": "t"}},
                {"record": "link", "link": {"element_id": "LNK-1",
                                            "name": "K1.rvt", "loaded": True}},
                {"record": "link", "link": {"element_id": "LNK-2",
                                            "name": "K2.rvt", "loaded": True}},
                {"record": "element", "element": {
                    "element_id": "W1", "category": "OST_Walls"}},
            ])
            header, rows, links = gs.read_l0_parts(run)
            self.assertEqual(header["doc_name"], "t")
            self.assertEqual(len(rows), 1)
            self.assertEqual(links, ["LNK-1", "LNK-2"])

    def test_a_host_in_a_link_becomes_a_POSITIVE_fact_not_a_dangling_edge(
            self) -> None:
        """959 of 1 001 hosts of `snowdon_elec_v1` live exactly here."""
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            self._write(run / "L0.jsonl", [
                {"record": "header", "document": {"doc_name": "t"}},
                {"record": "link", "link": {"element_id": "LNK-1",
                                            "name": "K1.rvt", "loaded": True}},
                {"record": "element", "element": {
                    "element_id": "F1", "category": "OST_ElectricalFixtures",
                    "host_id": "LNK-1", "params": {}}},
            ])
            graph = gs.build_graph_for_run(run)
            self.assertNotIn("link_ids", graph.census.sources_absent)
            self.assertEqual(
                graph.relation_count(Relation.HOSTED_IN_LINK), 1)
            self.assertEqual(graph.relation_count(Relation.HOSTED_IN), 0)

    def test_the_caller_can_still_override_what_was_read(self) -> None:
        """An explicit argument from the caller outranks what was read from
        disk."""
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            self._write(run / "L0.jsonl", [
                {"record": "header", "document": {"doc_name": "t"}},
                {"record": "link", "link": {"element_id": "LNK-1",
                                            "name": "K1.rvt"}},
                {"record": "element", "element": {
                    "element_id": "F1", "category": "OST_ElectricalFixtures",
                    "host_id": "LNK-1", "params": {}}},
            ])
            graph = gs.build_graph_for_run(run, link_ids=())
            # 🔴 THE OUTCOME WAS RE-TARGETED (F-056), THE TEST'S INTENT IS
            # INTACT. An explicit argument still outranks what was read from
            # disk — but an explicitly supplied EMPTY value is now a MEASURED
            # zero: the caller said "there are no relations", not "don't ask".
            # The previous expectation was cancelling the middle outcome of
            # the `relation_count` law exactly where it is needed.
            self.assertNotIn("link_ids", graph.census.sources_absent)
            self.assertEqual(graph.relation_count(Relation.HOSTED_IN_LINK), 0)
            self.assertEqual(graph.relation_count(Relation.HOSTED_IN), 1)

    def test_reading_side_indexes_can_be_switched_off_wholesale(self) -> None:
        with TemporaryDirectory() as tmp:
            run = Path(tmp)
            self._write(run / "L0.jsonl", [
                {"record": "header", "document": {"doc_name": "t"}},
                {"record": "link", "link": {"element_id": "LNK-1"}},
                {"record": "element", "element": {
                    "element_id": "W1", "category": "OST_Walls", "params": {}}},
            ])
            graph = gs.build_graph_for_run(run, read_side_indexes=False)
            self.assertIn("link_ids", graph.census.sources_absent)
            self.assertIn("joins", graph.census.sources_absent)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
