"""The reverse path for a ceiling and a railing (wave/arch, 2026-07-29).

WHAT IS PROVEN HERE AND WHAT IS NOT — stated plainly, so the report cannot
be read as better than it is.

PROVEN OFFLINE: a ceiling with a profile in the side sketch index lifts into
``create_ceiling`` with its level, type, and offset; a ceiling without a
profile, and a railing, give a TYPED atom reason naming the missing fact.

NOT PROVEN, AND HONESTLY NAMED AS UNPROVEN: not a single ceiling and not a
single railing of a REAL building lifts today — because the snapshot has no
geometry for them. Measurement on 13A-RD-AR-K2_v33 (55 293 elements):

    OST_Ceilings        81 pcs.  geom_kind=bbox_only  params={}  no profile
    OST_StairsRailing  203 pcs.  bbox_only 31 / point 172, host_id=null,
                                not a single row in sketch.index.json,
                                nor in curve.index.json

That is, the gates on the operations are green, but there is NOTHING to
lift: this is not fixed by the lift, but by the EXTRACTION side (the
extractor captures neither the ceiling's profile nor the railing's
path/position), and the wave had no live Revit available for this step. The
profiles below are synthetic, and are named as synthetic.
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

CEILING_ID = "9100001"
RAILING_ID = "9100002"

#: A SYNTHETIC profile (in the K2 snapshot ceilings have no profile at all)
#: — the row's shape is copied from real sketch.index.json rows.
SYNTHETIC_CEILING_PROFILE: dict[str, Any] = {
    "profile_available": True,
    "exterior_loop": [
        [0.0, 0.0],
        [6000.0, 0.0],
        [6000.0, 4000.0],
        [0.0, 4000.0],
    ],
    "curve_kinds": [["line", "line", "line", "line"]],
    "arc_midpoints": [[None, None, None, None]],
    "holes": [],
}


def _document(category: str, element_id: str, *,
              offset: float | None = None,
              host_id: str | None = None) -> L0Document:
    element = make_element(category, 4100, ordinal=0)
    element["element_id"] = element_id
    element["params"] = dict(element.get("params") or {})
    if offset is not None:
        element["params"]["CEILING_HEIGHTABOVELEVEL_PARAM"] = offset
    if host_id is not None:
        element["host_id"] = host_id
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "arch-v1"
    row["elements"] = [element]
    row["category_status"] = []
    return L0Document.from_dict(row)


def _lift(category: str, element_id: str, profile=None, **kw):
    result = lift_document_detailed(
        _document(category, element_id, **kw),
        {element_id: copy.deepcopy(profile)} if profile else {})
    return {node["source_element_id"]: node
            for node in result.nodes}[element_id]


class ACeilingWithAProfileLifts(unittest.TestCase):

    def test_it_becomes_create_ceiling(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE)
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_ceiling")

    def test_the_outline_survives_the_round_trip(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE)
        self.assertEqual(len(node["params"]["outline"]), 4)
        self.assertEqual(node["params"]["holes"], [])

    def test_it_carries_its_own_level_and_type(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE)
        self.assertIn("level", node["params"])
        self.assertIn("type", node["params"])

    def test_the_height_offset_travels(self) -> None:
        """The offset is read from the ceiling's OWN parameter. A foreign
        name (FLOOR_HEIGHTABOVELEVEL_PARAM) would silently return zero — the
        very same "0 instead of absence" that has already cost this house
        96% of its groups."""
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE,
                     offset=-250.0)
        self.assertEqual(node["params"]["height_offset_mm"], -250.0)

    def test_an_absent_offset_stays_absent(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID, SYNTHETIC_CEILING_PROFILE)
        self.assertNotIn("height_offset_mm", node["params"])

    def test_a_floor_parameter_is_not_read_by_mistake(self) -> None:
        document = _document("OST_Ceilings", CEILING_ID)
        document.elements[0].params["FLOOR_HEIGHTABOVELEVEL_PARAM"] = -900.0
        result = lift_document_detailed(
            document, {CEILING_ID: copy.deepcopy(SYNTHETIC_CEILING_PROFILE)})
        node = result.nodes[0]
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertNotIn("height_offset_mm", node["params"])


class WithoutEvidenceTheReasonIsExact(unittest.TestCase):
    """Before this wave, the reason was the same for all these elements:
    "the operation does not exist." That was true, and then stopped being
    true — and the reason that decides what to build next has no right to
    lag behind reality."""

    def test_a_ceiling_without_a_profile_names_the_missing_profile(self) -> None:
        node = _lift("OST_Ceilings", CEILING_ID)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.MISSING_GEOMETRY.value)

    def test_a_hosted_railing_names_the_missing_position(self) -> None:
        """The host is known, the position is not. Substituting Treads "by
        default" means silently placing the railing on the wrong side of
        the flight."""
        node = _lift("OST_StairsRailing", RAILING_ID, host_id="777")
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.MISSING_PARAMETER.value)

    def test_a_bare_railing_names_the_missing_geometry(self) -> None:
        node = _lift("OST_StairsRailing", RAILING_ID)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.MISSING_GEOMETRY.value)

    def test_neither_is_reported_as_a_missing_operation_any_more(self) -> None:
        for category, kw in (("OST_Ceilings", {}),
                             ("OST_StairsRailing", {}),
                             ("OST_StairsRailing", {"host_id": "777"})):
            with self.subTest(category=category, kw=tuple(kw)):
                node = _lift(category, RAILING_ID, **kw)
                self.assertNotEqual(node["reason"]["code"],
                                    AtomReason.REGISTRY_OP_GAP.value)
                self.assertNotEqual(node["reason"]["code"],
                                    AtomReason.NO_LIFTER.value)


if __name__ == "__main__":
    unittest.main()
