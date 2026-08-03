"""A door below its host wall's level is real, not an error.

Measured on SOB6.2_UPO_L_DOO_AR_R23 (Revit 2023, 151 doors): 140 doors carry a
NEGATIVE sill and 131 of them sit at exactly -100 mm.  The mechanism is ordinary
Russian practice — the wall's own ``WALL_BASE_OFFSET`` is -150, so the wall body
starts below its level, and a door set at the finished floor lands below that
level while remaining entirely inside the wall.

``_host_level_sill`` used to state the opposite ("a genuinely negative sill is
impossible for a hosted instance") and ``create_door.sill_mm`` carried
``min_val=0`` to enforce it, which turned 92.7% of that building's doors into
atoms.  The bound rejected reality, not a defect.
"""
import unittest

from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


def _wall(eid="100", *, base_offset=-150.0, height=3450.0):
    return L0Element(
        element_id=eid, category="OST_Walls", category_ru="Стены",
        type_id="7", type_name="ВН_Газобетон D600_200мм",
        level_id="10", level_name="L1",
        geom_kind=GeometryKind.CURVE,
        p0_mm=(0.0, 0.0, 0.0), p1_mm=(6000.0, 0.0, 0.0), rotation_deg=None,
        bbox_min_mm=(0.0, -100.0, base_offset),
        bbox_max_mm=(6000.0, 100.0, height),
        host_id=None,
        params={"WALL_USER_HEIGHT_PARAM": height,
                "WALL_BASE_OFFSET": base_offset})


def _door(eid="200", *, z):
    return L0Element(
        element_id=eid, category="OST_Doors", category_ru="Двери",
        type_id="9", type_name="ДВо_П_1570х2100(h)",
        level_id="10", level_name="L1",
        geom_kind=GeometryKind.POINT, p0_mm=(2000.0, 0.0, z), p1_mm=None,
        rotation_deg=0.0, bbox_min_mm=None, bbox_max_mm=None,
        host_id="100", params={})


def _doc(*elements):
    return L0Document(
        doc_name="sill", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "L1", 0.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=elements)


class DoorBelowHostLevel(unittest.TestCase):
    def _node(self, doc, source_id):
        return {n["source_element_id"]: n
                for n in lift_document(doc)}[source_id]

    def test_door_at_finished_floor_lifts_with_a_negative_sill(self):
        # The dominant real case: 131 of 151 doors in SOB6.2 sit here.
        node = self._node(_doc(_wall(), _door(z=-100.0)), "200")
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_door")
        self.assertEqual(node["params"]["sill_mm"], -100.0)

    def test_deeper_negative_sill_still_lifts(self):
        # Also measured: -600 mm on one door.  Nothing about the sign is special.
        node = self._node(_doc(_wall(), _door(z=-600.0)), "200")
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["params"]["sill_mm"], -600.0)

    def test_submillimetre_negative_noise_still_clamps_to_absent(self):
        # Unchanged: -0.4 mm is float noise, not an anchor.  It clamps to 0 and
        # then falls under the 1 mm omission threshold, so no sill is written —
        # this is what keeps every pre-existing door program byte-stable.
        node = self._node(_doc(_wall(), _door(z=-0.4)), "200")
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertNotIn("sill_mm", node["params"])

    def test_positive_sill_unchanged(self):
        node = self._node(_doc(_wall(), _door(z=750.0)), "200")
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["params"]["sill_mm"], 750.0)


if __name__ == "__main__":
    unittest.main()
