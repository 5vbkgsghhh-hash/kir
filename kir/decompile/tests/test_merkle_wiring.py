"""The `merkle` wire into a live decompile: enabled — it computes, disabled — it does NOT.

The `merkle` layer sat on the shelf as 1312 lines and 41 tests, and all 41
checked WHAT it computes. Not one checked whether even a single live input
reaches it — so the shelf was invisible from inside the tests. This file
checks exactly the second thing, and only that.

The inertness law here is literal and checked byte for byte: with the flag
off, a run must lay down on disk THE SAME artifacts with the same bytes as
before this wave. Not "roughly the same" and not "the same plus an empty
merkle.json" — an empty report is already a claim about the building, and a
disabled capability has no right to claim anything.

The second law is that there is no silence. `ok:false` and an empty list of
repeats must look different, or a broken instrument becomes indistinguishable
from a building with no repeats.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest import mock

from kir.decompile import pipeline as pipe
from kir.decompile.merkle import merkle_enabled
from kir.decompile.merkle_report import (
    DIFF_SCHEMA,
    REPORT_SCHEMA,
    building_report,
    diff_report,
)
from kir.decompile.tests.test_pipeline import FakePipelineBridge

_FLAG = "KUKAI_IR_MERKLE"

#: Artifacts required to be deterministic.  `run.json`/`status.json`
#: carry stage timings and are excluded from the comparison by construction (I4).
_DETERMINISTIC = (
    "L0.jsonl", "tree.json", "named.json", "verify.json", "passport.json",
    "curve.index.json", "sketch.index.json", "curtain.index.json",
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _digests(directory: Path) -> dict[str, str]:
    out = {}
    for name in _DETERMINISTIC:
        path = directory / name
        if path.is_file():
            out[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def _decompile(tmp: str) -> Any:
    return _run(pipe.run_decompile(
        FakePipelineBridge(), out_dir=tmp, change_stamp="merkle-wiring-v1"))


class InertWhenOff(unittest.TestCase):
    def test_flag_is_off_by_default(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            self.assertFalse(merkle_enabled())

    def test_off_run_writes_no_merkle_artifact(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            with TemporaryDirectory() as tmp:
                result = _decompile(tmp)
                self.assertTrue(result.ok, msg=result.to_dict())
                self.assertFalse(
                    (Path(tmp) / "merkle.json").exists(),
                    "выключенный флаг оставил файл — отсутствующее обязано "
                    "отсутствовать, а не присутствовать пустым")
                status = json.loads(
                    (Path(tmp) / "status.json").read_text("utf-8"))
                self.assertNotIn(
                    "merkle", status.get("timing", {}).get("stage_ms", {}),
                    "выключенная стадия попала в часы — значит исполнялась")

    def test_switching_the_flag_moves_no_byte_of_the_old_artifacts(
            self) -> None:
        """The wave's main test: enabling it does NOT move a single prior artifact.

        The same bytes for `tree.json`/`passport.json`/`verify.json` under
        both flag positions is the only proof that the new layer rewrote
        nothing along the way. The building's hashes must also MATCH between
        runs: if `merkle` touched the tree, this check would fail first.
        """
        with TemporaryDirectory() as tmp_off, TemporaryDirectory() as tmp_on:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(_FLAG, None)
                self.assertTrue(_decompile(tmp_off).ok)
            with mock.patch.dict(os.environ, {_FLAG: "1"}):
                self.assertTrue(_decompile(tmp_on).ok)

            off, on = _digests(Path(tmp_off)), _digests(Path(tmp_on))
            self.assertTrue(off, "сравнивать нечего — прогон не дал артефактов")
            self.assertEqual(
                off, on,
                "включённый merkle сдвинул байты уже существовавшего "
                "артефакта — это не приложение к разбору, а изменение разбора")
            self.assertTrue((Path(tmp_on) / "merkle.json").is_file())


class ReportOnTheLiveRun(unittest.TestCase):
    def test_on_run_writes_a_readable_report(self) -> None:
        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            with TemporaryDirectory() as tmp:
                result = _decompile(tmp)
                self.assertTrue(result.ok, msg=result.to_dict())
                report = json.loads(
                    (Path(tmp) / "merkle.json").read_text("utf-8"))

        self.assertEqual(report["schema"], REPORT_SCHEMA)
        self.assertTrue(report["ok"], msg=report)
        self.assertEqual(len(report["root_hash"]), 64)
        self.assertGreater(report["nodes"], 0)
        self.assertGreaterEqual(report["nodes"], report["distinct_nodes"])
        self.assertEqual(report["repeats_total"], len(report["repeats"]))
        # The report must match what the layer gives directly for the same
        # tree: the wire has no right to paraphrase merkle in its own words.
        with TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop(_FLAG, None)
                _decompile(tmp)
            tree = json.loads((Path(tmp) / "tree.json").read_text("utf-8"))
        direct = building_report(tree, label=report["label"])
        self.assertEqual(direct["root_hash"], report["root_hash"])
        self.assertEqual(direct["nodes"], report["nodes"])

    def test_timing_records_the_stage_only_when_it_ran(self) -> None:
        with mock.patch.dict(os.environ, {_FLAG: "1"}):
            with TemporaryDirectory() as tmp:
                self.assertTrue(_decompile(tmp).ok)
                status = json.loads(
                    (Path(tmp) / "status.json").read_text("utf-8"))
        self.assertIn("merkle", status["timing"]["stage_ms"])


class NothingSilent(unittest.TestCase):
    """A refusal must differ from an empty result — otherwise it is invisible."""

    def test_a_malformed_tree_is_refused_by_name(self) -> None:
        report = building_report({"kind": "building"}, label="огрызок")
        self.assertFalse(report["ok"])
        self.assertEqual(report["schema"], REPORT_SCHEMA)
        self.assertIn("Merkle", report["error"]["type"])
        self.assertTrue(report["error"]["message"].strip())
        # This exact distinction is the point of the test: a refusal does
        # NOT look like "no repeats found".
        self.assertNotIn("repeats", report)

    def test_a_refused_diff_is_not_an_empty_diff(self) -> None:
        report = diff_report({"kind": "building"}, {"kind": "building"},
                             label_a="a", label_b="b")
        self.assertFalse(report["ok"])
        self.assertEqual(report["schema"], DIFF_SCHEMA)
        self.assertNotIn("entries", report)
        self.assertNotIn("identical", report)


class DiffOverPersistedTrees(unittest.TestCase):
    def _tree(self) -> dict[str, Any]:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FLAG, None)
            with TemporaryDirectory() as tmp:
                self.assertTrue(_decompile(tmp).ok)
                return json.loads(
                    (Path(tmp) / "tree.json").read_text("utf-8"))

    def test_a_building_against_itself_is_identical_not_merely_empty(
            self) -> None:
        tree = self._tree()
        report = diff_report(tree, tree, label_a="v1", label_b="v1")
        self.assertTrue(report["ok"])
        self.assertTrue(report["identical"])
        self.assertEqual(report["entries_total"], 0)
        self.assertEqual(report["counts"],
                         {"added": 0, "removed": 0, "changed": 0, "moved": 0})
        self.assertEqual(report["a"]["root_hash"], report["b"]["root_hash"])

    def test_a_removed_floor_shows_up_as_removed(self) -> None:
        """A refuting test: the diff must NAME what went missing.

        An empty diff between two knowingly different buildings is exactly
        the report this layer was wired in to make impossible.
        """
        tree = self._tree()
        if not tree["children"]:
            self.skipTest("мини-здание фикстуры без детей — нечего убирать")
        trimmed = dict(tree)
        trimmed["children"] = tree["children"][:-1]
        report = diff_report(tree, trimmed, label_a="полное",
                             label_b="урезанное")
        self.assertTrue(report["ok"])
        self.assertFalse(report["identical"])
        self.assertGreater(report["entries_total"], 0)
        self.assertGreater(report["counts"]["removed"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
