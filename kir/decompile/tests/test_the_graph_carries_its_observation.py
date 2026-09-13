"""The graph is dated BY ITSELF: `building-graph/2` and compatible
reading of `/1`.

Before 07.09.2026 the graph artifact carried neither a revision nor a
fingerprint, and the consumer had to accept the observation date as the
caller's own claim. Checked here: that the date is now MEASURED at
construction, survives disk storage and compression, and the old
artifact remains readable and honestly says it has no date.
"""
import gzip
import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from kir.decompile import graph_store as gs
from kir.decompile.building_graph import (
    FINGERPRINT_ABSENT,
    FINGERPRINT_DERIVED,
    GRAPH_ARTIFACT_SCHEMA,
    GRAPH_ARTIFACT_SCHEMA_V1,
    GraphBuildError,
    ObservationFingerprint,
    graph_from_dict,
    graph_from_l0,
)
from kir.decompile.capture_api import write_demo_capture
from kir.model.snapshot_io import digest_bytes


def _demo(directory: Path) -> Path:
    return write_demo_capture(directory / "run")


def _cool(run: Path) -> None:
    """Cool a run down exactly the way the snapshot janitor does."""
    with open(run / "L0.jsonl", "rb") as raw, gzip.open(run / "L0.jsonl.gz", "wb") as gz:
        shutil.copyfileobj(raw, gz)
    (run / "L0.jsonl").unlink()


class ОтпечатокВыводится(unittest.TestCase):
    def test_the_builder_measures_the_stamp_and_the_snapshot(self):
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            graph = gs.build_graph_for_run(run)
            self.assertEqual(graph.fingerprint_status, FINGERPRINT_DERIVED)
            self.assertEqual(graph.observation.change_stamp, "capture-api-demo")
            self.assertEqual(
                graph.observation.l0_sha256,
                digest_bytes((run / "L0.jsonl").read_bytes()))

    def test_the_streaming_digest_agrees_with_the_one_place_that_owns_it(self):
        """A second carrier of the algorithm is named — and must match the first."""
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            self.assertEqual(gs.l0_digest(run),
                             digest_bytes((run / "L0.jsonl").read_bytes()))

    def test_compression_does_not_move_the_fingerprint(self):
        """🔴 Had we hashed the FILE'S BYTES, the janitor would be
        changing the building's identity."""
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            hot = gs.build_graph_for_run(run).observation
            file_bytes_before = (run / "L0.jsonl").read_bytes()
            _cool(run)
            cold = gs.build_graph_for_run(run).observation
            self.assertEqual(hot, cold)
            # And a control: the file's bytes DID change in the process,
            # meaning the measurement tells "content" from "file" apart,
            # rather than matching by coincidence.
            self.assertNotEqual(digest_bytes((run / "L0.jsonl.gz").read_bytes()),
                                digest_bytes(file_bytes_before))

    def test_a_snapshot_without_a_change_stamp_is_undated_not_dated_blank(self):
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            rows = (run / "L0.jsonl").read_text(encoding="utf-8").splitlines()
            head = json.loads(rows[0])
            head["document"].pop("change_stamp")
            rows[0] = json.dumps(head, ensure_ascii=False)
            (run / "L0.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
            graph = gs.build_graph_for_run(run)
            self.assertIsNone(graph.observation)
            self.assertEqual(graph.fingerprint_status, FINGERPRINT_ABSENT)

    def test_an_explicit_fingerprint_still_wins_over_the_measured_one(self):
        """The same law as `link_ids`/`joins`: an explicit argument wins."""
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            mine = ObservationFingerprint("declared-stamp", "c" * 64)
            self.assertEqual(
                gs.build_graph_for_run(run, observation=mine).observation, mine)


class АртефактДержитОтпечаток(unittest.TestCase):
    def test_the_round_trip_carries_it_byte_for_byte(self):
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            graph = gs.build_graph_for_run(run)
            payload = graph.to_dict()
            self.assertEqual(payload["schema"], GRAPH_ARTIFACT_SCHEMA)
            self.assertEqual(payload["fingerprint_status"], FINGERPRINT_DERIVED)
            back = graph_from_dict(json.loads(json.dumps(payload)))
            self.assertEqual(back.observation, graph.observation)

    def test_the_artifact_survives_the_disk(self):
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            graph = gs.build_graph_for_run(run)
            gs.write_graph(run, graph)
            self.assertEqual(gs.load_graph(run).observation, graph.observation)


class СтарыйАртефактЧитаетсяИНеПолучаетДату(unittest.TestCase):
    """🔴 76 decompiles of the corpus sit in `/1`. Declaring them
    unreadable would mean losing the buildings' state for the sake of a
    key that was never in them to begin with."""

    def _v1(self, run: Path) -> dict:
        payload = gs.build_graph_for_run(run).to_dict()
        payload["schema"] = GRAPH_ARTIFACT_SCHEMA_V1
        payload.pop("observation")
        payload.pop("fingerprint_status")
        return payload

    def test_a_v1_artifact_reads_and_says_it_has_no_date(self):
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            graph = graph_from_dict(self._v1(run))
            self.assertIsNone(graph.observation)
            self.assertEqual(graph.fingerprint_status, FINGERPRINT_ABSENT)
            self.assertEqual(len(graph), 4)

    def test_a_v1_artifact_loads_from_disk_and_the_clash_query_survives_it(self):
        """A refusal here would fail not only the discrepancy report, but CLASH too."""
        from kir.decompile.graph_clash_query import graph_for_clash_query

        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            gs.graph_path(run).write_text(
                json.dumps(self._v1(run), ensure_ascii=False), encoding="utf-8")
            self.assertEqual(gs.load_graph(run).fingerprint_status, FINGERPRINT_ABSENT)
            self.assertEqual(len(graph_for_clash_query(run)), 4)

    def test_a_foreign_schema_still_refuses_loudly(self):
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            payload = {**self._v1(run), "schema": "building-graph/99"}
            with self.assertRaises(GraphBuildError):
                graph_from_dict(payload)

    def test_a_status_contradicting_its_own_payload_refuses(self):
        """"There is a date" with an empty fingerprint is a lie that cannot be read."""
        with TemporaryDirectory() as tmp:
            run = _demo(Path(tmp))
            payload = gs.build_graph_for_run(run).to_dict()
            payload["observation"] = None
            with self.assertRaises(GraphBuildError):
                graph_from_dict(payload)

    def test_a_blank_stamp_is_not_constructible(self):
        for stamp, digest in (("", "a" * 64), ("  ", "a" * 64),
                              ("s", "a" * 63), ("s", "A" * 64)):
            with self.subTest(stamp=stamp, digest=digest):
                with self.assertRaises(GraphBuildError):
                    ObservationFingerprint(stamp, digest)

    def test_a_graph_built_without_a_snapshot_is_undated(self):
        graph = graph_from_l0({"doc_name": "x"}, [])
        self.assertEqual(graph.fingerprint_status, FINGERPRINT_ABSENT)


if __name__ == "__main__":
    unittest.main()
