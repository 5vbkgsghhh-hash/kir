"""A category owning a lifter must not make that lifter's refusal terminal.

``_lift_one`` picks the lifter by CATEGORY alone.  When the specialised lifter
then refuses because the element is not the SHAPE that op expects, the element
became an atom and the generic ``place_family`` path was never tried — it was
reachable only for categories missing from ``_CANDIDATES`` entirely.

Measured on SOB6.2_UPO_L_DOO_AR_R23: 275 OST_StructuralFraming elements, 270 of
them unhosted ``OneLevelBased`` FamilyInstances with a LocationPoint and a full
row in the placement side index — exactly what ``place_family`` expresses.  All
275 were atoms ("OST_StructuralFraming requires curve geometry"), 57% of every
atom in that building, because ``_lift_beam`` owns the category and wants a
curve.  Nothing was missing but the fall-through.

The fall-through is deliberately narrow.  Only a SHAPE refusal defers; a refusal
about a VALUE or a broken REFERENCE must stay terminal, because ``place_family``
would answer it by dropping the very facts the specialised op exists to keep
(a door's host, a beam's endpoints).  Silently downgrading an element to a
generic placement is worse than an honest atom.
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

_PLACEMENT = {
    "placement_type": "OneLevelBased",
    "placement_available": True,
    "point_mm": [1000.0, 2000.0, 3510.0],
    "family_name": "UPO_Каркас Несущий_Перемычка металлическая_сборная",
    "host_id": None,
    "host_class": None,
    "group_id": None,
    "in_place": False,
    "mirrored": False,
    "hand_flipped": False,
    "facing_flipped": False,
    "hand_orientation": [0.0, 1.0, 0.0],
    "facing_orientation": [-1.0, 0.0, 0.0],
    "rotation_deg": 90.0,
    "super_component_id": None,
    "symbol_id": "60",
    "type_name": "Тип_без опорных уголков 1050",
}


def _framing(eid="500"):
    """Point-placed structural framing — the real SOB6.2 shape."""
    return L0Element(
        element_id=eid, category="OST_StructuralFraming",
        category_ru="Каркас несущий",
        type_id="60", type_name="Тип_без опорных уголков 1050",
        level_id="10", level_name="L1",
        geom_kind=GeometryKind.POINT,
        p0_mm=(1000.0, 2000.0, 3510.0), p1_mm=None, rotation_deg=90.0,
        bbox_min_mm=None, bbox_max_mm=None, host_id=None, params={})


def _doc(*elements):
    return L0Document(
        doc_name="fallback", revit_version="2023", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "L1", 1800.0),), grids=(), rooms=(),
        project_info=ProjectInfo(), elements=elements)


class ShapeRefusalFallsThrough(unittest.TestCase):
    def _node(self, doc, source_id, index=None):
        nodes = lift_document(doc, None, index)
        return {n["source_element_id"]: n for n in nodes}[source_id]

    def test_point_placed_framing_becomes_place_family(self):
        node = self._node(_doc(_framing()), "500", {"500": dict(_PLACEMENT)})
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "place_family")

    def test_without_a_placement_row_it_stays_an_atom(self):
        # Fail-closed: no side-index row, nothing to fall through to.  The
        # ORIGINAL refusal is what gets reported, not the fallback's.
        node = self._node(_doc(_framing()), "500", {"999": dict(_PLACEMENT)})
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "missing_geometry")
        self.assertIn("requires curve geometry", node["reason"]["detail"])

    def test_without_any_index_it_stays_an_atom(self):
        node = self._node(_doc(_framing()), "500")
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "missing_geometry")

    def test_curve_framing_still_lifts_as_a_beam(self):
        # The fall-through must not shadow the specialised op when it applies.
        beam = L0Element(
            element_id="501", category="OST_StructuralFraming",
            category_ru="Каркас несущий", type_id="60", type_name="Б200",
            level_id="10", level_name="L1", geom_kind=GeometryKind.CURVE,
            p0_mm=(0.0, 0.0, 1800.0), p1_mm=(4000.0, 0.0, 1800.0),
            rotation_deg=None, bbox_min_mm=None, bbox_max_mm=None,
            host_id=None, params={})
        node = self._node(_doc(beam), "501", {"501": dict(_PLACEMENT)})
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "create_beam")

    def test_a_generated_child_is_reported_as_one(self):
        # 237 of SOB6.2's 275 framing instances are nested shared families: a
        # parent already creates them, so lifting them individually would
        # duplicate geometry.  The fallback's refusal is a fact about the
        # ELEMENT, not about place_family's limits, so it must outrank the
        # owning lifter's "requires curve geometry" — otherwise the next reader
        # goes hunting for a curve lifter that must never be written.
        row = dict(_PLACEMENT, super_component_id="777")
        node = self._node(_doc(_framing()), "500", {"500": row})
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "generator_child")
        self.assertIn("777", node["reason"]["detail"])

    def test_a_value_refusal_does_not_fall_through(self):
        # A door whose sill is beyond the forward bound must NOT quietly become
        # a hostless place_family: that answers a value problem by discarding
        # the host relationship.  The honest atom is the correct outcome.
        wall = L0Element(
            element_id="100", category="OST_Walls", category_ru="Стены",
            type_id="7", type_name="W200", level_id="10", level_name="L1",
            geom_kind=GeometryKind.CURVE,
            p0_mm=(0.0, 0.0, 1800.0), p1_mm=(6000.0, 0.0, 1800.0),
            rotation_deg=None, bbox_min_mm=(0.0, -100.0, 1800.0),
            bbox_max_mm=(6000.0, 100.0, 5000.0), host_id=None,
            params={"WALL_USER_HEIGHT_PARAM": 3200.0})
        door = L0Element(
            element_id="200", category="OST_Doors", category_ru="Двери",
            type_id="9", type_name="Д1", level_id="10", level_name="L1",
            geom_kind=GeometryKind.POINT,
            p0_mm=(2000.0, 0.0, 1800.0 + 200_000.0), p1_mm=None,
            rotation_deg=0.0, bbox_min_mm=None, bbox_max_mm=None,
            host_id="100", params={})
        node = self._node(_doc(wall, door), "200", {"200": dict(_PLACEMENT)})
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"], "invalid_forward_value")


if __name__ == "__main__":
    unittest.main()
