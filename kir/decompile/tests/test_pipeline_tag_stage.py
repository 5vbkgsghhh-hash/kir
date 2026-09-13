"""The tags stage ACROSS THE WHOLE PIPELINE, not only piecewise.

The annotation wave of 30.07 passed all thirty of its tests, its C# ran
perfectly on the bridge — and the full run died after a minute and a half at the seam
(``side_stage_count_mismatch``). The defect was neither in the stage nor in the C#, but in
what none of the thirty tests touched: the WIRING.

Here it is exactly this that is checked: L0 -> id request -> bridge response ->
``tag.index.json`` -> lift -> ``create_tag``. And, at the same time, the one thing
this stage has beyond the others: its C# DEPENDS ON THE VERSION of the document
read, and the version becomes known only after reading.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from kir.decompile import pipeline as pipe
from kir.decompile.tag_extract import TAG_EXTRACT_SCHEMA_VERSION
from kir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)
from kir.decompile.tests.test_pipeline import FakePipelineBridge


#: The tags stage is paged and enumerates ids as ``new List<string> { ... }``
#: — the same way as annotation and systems, and NOT the way ``new string[] { ... }``
#: works for the first stages. Its own harvester stands here for exactly this reason: someone else's would return
#: an empty list, the fake bridge would honestly answer "not a single string," and §18.2
#: would fail the run — that is, the test would be measuring the shape of the literal, not the wiring.
def _requested_ids(code: str) -> list[str]:
    match = re.search(r"new List<string> \{([^}]*)\}", code)
    if match is None:
        return []
    return re.findall(r'"([^"]+)"', match.group(1))


WALL_ID = "1001"
TAG_ID = "5001"


def _elements() -> dict[str, list[dict[str, Any]]]:
    return {
        "OST_Walls": [
            make_element("OST_Walls", 1001, ordinal=0),
            make_element("OST_Walls", 1002, ordinal=1),
        ],
        "OST_WallTags": [make_element("OST_WallTags", 5001, ordinal=0)],
    }


def _metadata(revit_version: str = "2026") -> dict[str, Any]:
    meta = copy.deepcopy(project1_metadata())
    meta["doc_name"] = "pipeline-tag"
    meta["change_stamp"] = "pipeline-tag-v1"
    meta["revit_version"] = revit_version
    return meta


class TagBridge(FakePipelineBridge):
    """A fake bridge able to answer the tags stage.

    ``readable`` = False models an HONEST receipt: a tag on an element
    of a linked file. The run must stay alive, and the tag must remain an atom.
    """

    def __init__(self, *, revit_version: str = "2026",
                 readable: bool = True) -> None:
        super().__init__(elements=_elements(),
                         metadata=_metadata(revit_version))
        self.readable = readable
        self.tag_bodies: list[str] = []

    async def _dispatch(self, code: str, *, timeout_ms: int) -> dict[str, Any]:
        if TAG_EXTRACT_SCHEMA_VERSION in code:
            self.side_calls.append("tag")
            self.tag_bodies.append(code)
            requested = _requested_ids(code)
            if self.readable:
                rows = [{
                    "element_id": element_id,
                    "owner_view_id": "900",
                    "owner_view_name": "Уровень 1",
                    "at_view_ft": [10.0, -2.5],
                    "tagged_element_id": WALL_ID,
                    "tag_family": "independent",
                    # Without a leader: only this kind of tag is lifted today
                    # (for a tag WITH a leader, `at` means the end of the leader, while
                    # the stage reads the head — see _lift_tag).
                    "leader": False,
                    "orientation": "Horizontal",
                    "type_id": "77",
                    "type_name": "Марка стены",
                } for element_id in requested]
                failures: list[dict[str, Any]] = []
            else:
                rows = []
                failures = [{
                    "element_id": element_id,
                    "reason": "tag marks no element of this document",
                    "typed_reason": "tag_target_not_local",
                } for element_id in requested]
            return {"ok": True, "result": {
                "schema_version": TAG_EXTRACT_SCHEMA_VERSION,
                "elements": rows, "failures": failures}}
        return await super()._dispatch(code, timeout_ms=timeout_ms)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TagStageRunsEndToEnd(unittest.TestCase):

    def test_the_stage_is_asked_persisted_and_lifted(self) -> None:
        with TemporaryDirectory() as tmp:
            bridge = TagBridge()
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-tag-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            self.assertIn("tag", bridge.side_calls,
                          "конвейер не запросил стадию марок ни разу")
            index_path = Path(tmp) / "tag.index.json"
            self.assertTrue(index_path.is_file(), "индекс марок не сохранён")
            index = json.loads(index_path.read_text("utf-8"))
            self.assertIn(TAG_ID, index["tag_index"])
            self.assertEqual(
                index["tag_index"][TAG_ID]["tagged_element_id"], WALL_ID)

    def test_the_tag_becomes_an_op_only_when_the_stage_could_read_it(self) -> None:
        """The difference between "read" and "could not" must be VISIBLE in the numbers.

        The same document, the same lift, only the bridge's response differs —
        and the result differs by exactly one operation. Without this pair
        it is impossible to tell working wiring apart from wiring that silently
        hands back the previous answer (that very cache trap that cost three waves).
        """
        with TemporaryDirectory() as tmp:
            read = _run(pipe.run_decompile(
                TagBridge(readable=True), out_dir=tmp,
                change_stamp="pipeline-tag-v1"))
        with TemporaryDirectory() as tmp:
            refused = _run(pipe.run_decompile(
                TagBridge(readable=False), out_dir=tmp,
                change_stamp="pipeline-tag-v1"))
        self.assertTrue(read.ok, msg=read.to_dict())
        self.assertTrue(refused.ok, msg=refused.to_dict())
        self.assertEqual(read.ops_lifted, refused.ops_lifted + 1)
        self.assertEqual(read.atoms + 1, refused.atoms)

    def test_a_typed_receipt_keeps_the_run_alive_and_is_counted(self) -> None:
        """A receipt is a report, not the death of a run (§18.2)."""
        with TemporaryDirectory() as tmp:
            result = _run(pipe.run_decompile(
                TagBridge(readable=False), out_dir=tmp,
                change_stamp="pipeline-tag-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
            # The §18.2 aggregate lands in run.json FLAT, not as a separate
            # object: the keys unpack into the root (`**side_failures`).
            run = json.loads((Path(tmp) / "run.json").read_text("utf-8"))
            self.assertEqual(run.get("side_failures_by_stage", {}).get("tag"), 1)
            self.assertEqual(
                run.get("side_cuts_by_reason", {}).get("tag_target_not_local"),
                1)
            # A receipt must be a SLICE, not a "definition": our target
            # addresses its own document, and this constraint is ours.
            self.assertEqual(run.get("side_cuts_by_stage", {}).get("tag"), 1)
            self.assertEqual(run.get("side_failures_untyped"), 0)


class TheEmittedBodyFollowsTheDocumentsVersion(unittest.TestCase):
    """The 2022 seam must travel from the READ document, not from a default."""

    PROPERTY_CALL = "__tgInd.TaggedLocalElementId"
    METHOD_CALL = "__tgInd.GetTaggedLocalElements()"

    def _body(self, revit_version: str) -> str:
        with TemporaryDirectory() as tmp:
            bridge = TagBridge(revit_version=revit_version)
            result = _run(pipe.run_decompile(
                bridge, out_dir=tmp, change_stamp="pipeline-tag-v1"))
            self.assertTrue(result.ok, msg=result.to_dict())
        self.assertTrue(bridge.tag_bodies, "стадию марок ни разу не позвали")
        return bridge.tag_bodies[0]

    def test_a_2021_document_gets_the_2021_member(self) -> None:
        body = self._body("2021")
        self.assertIn(self.PROPERTY_CALL, body)
        self.assertNotIn(self.METHOD_CALL, body)

    def test_a_2026_document_gets_the_2022plus_member(self) -> None:
        body = self._body("2026")
        self.assertIn(self.METHOD_CALL, body)
        self.assertNotIn(self.PROPERTY_CALL, body)


if __name__ == "__main__":
    unittest.main()
