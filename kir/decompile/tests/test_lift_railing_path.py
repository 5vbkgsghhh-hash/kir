"""Railing: capture existed, the wire did not (03.08.2026).

THE EXTRACTION SIDE CLOSED THIS QUESTION ON 29.07. ``RailingPathRecord``
captures ``Railing.GetPath()``, ``HasHost``/``HostId``, and the base
level, the ``sketch`` stage is fed both railing categories, and the
capture ships in prod.

THE LIFT DID NOT READ IT. ``_Context`` knew about
``stairs_run_path_index`` and did not know about ``railing_path_index``;
``_lift_railing`` decided from ``element.host_id`` — from the L0 row —
while ready-made paths sat in ``sketch.index.json`` of the same decompile.
Measurement on k2_ar_rd_v9 (13A-RD-AR-K2_v33, 115 880 elements): 31
capture rows, of which 28 are freestanding railings with a path, a base
level, and a plane EXACTLY at the level's elevation; all 31 are straight.

The tests below were written BEFORE the fix and failed red on it.

THE BOUNDARY THIS FILE GUARDS SEPARATELY: a decompile taken BEFORE the
capture stage must produce the SAME refusal VERBATIM. Otherwise the "fix"
would rewrite the history of every snapshot on disk, and there would be
nothing left to compare today's compiler against yesterday's.
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kir.decompile.l1_schema import AtomReason
from kir.decompile.lift import lift_document_detailed
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata)

RAILING_ID = "9200001"

#: The row's shape is copied from the real ``railing_path_index`` of
#: k2_ar_rd_v9.
FREE_RAILING_ROW: dict[str, Any] = {
    "path_available": True,
    "points_mm": [[14880.0, 24575.0], [10920.0, 24575.0]],
    "curve_kinds": ["line"],
    "arc_midpoints_mm": [None],
    "plane_z_mm": 0.0,
    "has_host": False,
    "host_id": None,
    "base_level_id": "100",
}


def _document(*, level_id: str = "100") -> L0Document:
    element = make_element("OST_StairsRailing", 4200, ordinal=0)
    element["element_id"] = RAILING_ID
    element["level_id"] = level_id
    element["level_name"] = "Этаж 1"
    element["host_id"] = None
    payload = copy.deepcopy(project1_metadata())
    payload["change_stamp"] = "railing-v1"
    payload["elements"] = [element]
    payload["category_status"] = []
    return L0Document.from_dict(payload)


def _sketch_index(railing_row: dict[str, Any] | None) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": "sketch-extract/1",
        "profile_index": {},
        "stairs_run_path_index": {},
        "failures": [],
    }
    if railing_row is not None:
        envelope["railing_path_index"] = {RAILING_ID: railing_row}
    return envelope


def _node(document: L0Document, sketch: dict[str, Any] | None):
    result = lift_document_detailed(document, sketch, None)
    nodes = [n for n in result.nodes if n["source_element_id"] == RAILING_ID]
    assert len(nodes) == 1, nodes
    return nodes[0]


def _row(**overrides: Any) -> dict[str, Any]:
    row = copy.deepcopy(FREE_RAILING_ROW)
    row.update(overrides)
    return row


class AFreeRailingWithAPathBecomesAnOp(unittest.TestCase):
    def test_path_variety_carries_path_level_and_type(self) -> None:
        node = _node(_document(), _sketch_index(FREE_RAILING_ROW))
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_railing")
        params = node["params"]
        self.assertEqual(params["variety"], "path")
        self.assertEqual(
            params["path"], [[14880.0, 24575.0], [10920.0, 24575.0]])
        self.assertEqual(params["level"]["_id"], "100")
        self.assertIn("type", params)

    def test_the_op_validates_against_the_registry(self) -> None:
        """The path shape is THE ONE the forward path accepts, not a
        similar one."""
        from kir.authoring_validation import validate

        node = _node(_document(), _sketch_index(FREE_RAILING_ROW))
        op = {"op": "create_railing", "id": "R1", **{
            k: v for k, v in node["params"].items() if k != "level"}}
        op["level"] = {"by": "name", "value": "Этаж 1"}
        op["type"] = {"by": "name", "value": op["type"]["value"]}
        diagnostics: list[Any] = []
        validate(op, "create_railing", 0, "R1", diagnostics)
        self.assertEqual(
            [d.code for d in diagnostics], [],
            [d.as_dict() for d in diagnostics])


class BordersThatDoNotMove(unittest.TestCase):
    def test_a_hosted_railing_stays_an_atom(self) -> None:
        """The placement position does not exist in the API on any
        version — moving a stair railing into variety=path would mean
        losing the host."""
        node = _node(_document(), _sketch_index(
            _row(has_host=True, host_id="777", base_level_id=None)))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.MISSING_PARAMETER.value)
        self.assertIn("RailingPlacementPosition", node["reason"]["detail"])

    def test_an_unknown_host_state_stays_an_atom(self) -> None:
        """``has_host is None`` means "could not be read." The record was
        made three-valued precisely so this does NOT read as "there is no
        host": a freestanding railing born out of the unknown loses its
        host just as silently as an explicit substitution would."""
        node = _node(_document(), _sketch_index(_row(has_host=None)))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.MISSING_METADATA.value)

    def test_an_arc_in_the_path_stays_an_atom(self) -> None:
        node = _node(_document(), _sketch_index(_row(
            points_mm=[[0.0, 0.0], [1000.0, 0.0]],
            curve_kinds=["arc"],
            arc_midpoints_mm=[[500.0, 100.0]])))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.CURVE_KIND_UNSUPPORTED.value)

    def test_a_path_plane_off_its_base_level_stays_an_atom(self) -> None:
        """create_railing has no offset parameter: the railing would come
        back at a different elevation silently."""
        node = _node(_document(), _sketch_index(_row(plane_z_mm=1500.0)))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("offset", node["reason"]["detail"])

    def test_an_unreadable_path_stays_an_atom(self) -> None:
        node = _node(_document(), _sketch_index(_row(
            path_available=False, points_mm=[], curve_kinds=[],
            arc_midpoints_mm=[], plane_z_mm=None)))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(
            node["reason"]["code"], AtomReason.MISSING_GEOMETRY.value)


class ASnapshotTakenBeforeTheStageKeepsItsFormerAnswer(unittest.TestCase):
    """A house rule. Checked VERBATIM, not by the reason code."""

    HOSTLESS = ("frozen L0 has no railing path and no host id "
                "(ограждение в слепке — только габарит)")
    HOSTED = ("frozen L0 carries no RailingPlacementPosition for a hosted "
              "railing (host is known, placement side is not)")

    def test_no_index_at_all_keeps_the_hostless_refusal_verbatim(self) -> None:
        node = _node(_document(), None)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["detail"], self.HOSTLESS)

    def test_index_without_the_railing_key_keeps_it_verbatim(self) -> None:
        """This exact shape is what lies on disk for sob62/demo/sklnk: the
        envelope exists, the ``railing_path_index`` key does not."""
        node = _node(_document(), _sketch_index(None))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["detail"], self.HOSTLESS)

    def test_a_hosted_railing_without_the_stage_keeps_its_refusal(self) -> None:
        document = _document()
        object.__setattr__(document.elements[0], "host_id", "9001")
        node = _node(document, _sketch_index(None))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["detail"], self.HOSTED)


if __name__ == "__main__":
    unittest.main()
