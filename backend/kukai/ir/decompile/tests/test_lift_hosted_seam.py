"""Audit F1: hosted window/door vertical anchor — sill from the HOST wall's
level (the emitter's placement basis), never from the hosted element's own
schedule level; door z preserved as an explicit sill."""
import math
import unittest

from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.schema import (
    GeometryKind,
    L0Document,
    L0Element,
    LevelInfo,
    ProjectInfo,
)


def _wall(eid="100", level_id="10", level_name="L1", height=6000.0):
    return L0Element(
        element_id=eid, category="OST_Walls", category_ru="Стены",
        type_id="7", type_name="W200", level_id=level_id, level_name=level_name,
        geom_kind=GeometryKind.CURVE,
        p0_mm=(0.0, 0.0, 0.0), p1_mm=(6000.0, 0.0, 0.0), rotation_deg=None,
        bbox_min_mm=(0.0, -100.0, 0.0), bbox_max_mm=(6000.0, 100.0, height),
        host_id=None, params={"WALL_USER_HEIGHT_PARAM": height})


def _hosted(eid, category, category_ru, type_name, z, *, level_id, level_name,
            host_id="100", x=2000.0):
    return L0Element(
        element_id=eid, category=category, category_ru=category_ru,
        type_id="8" if category == "OST_Windows" else "9",
        type_name=type_name, level_id=level_id, level_name=level_name,
        geom_kind=GeometryKind.POINT, p0_mm=(x, 0.0, z), p1_mm=None,
        rotation_deg=0.0, bbox_min_mm=None, bbox_max_mm=None,
        host_id=host_id, params={})


def _doc(*elements):
    return L0Document(
        doc_name="seam", revit_version="2024", units="mm", change_stamp="t",
        levels=(LevelInfo("10", "L1", 0.0), LevelInfo("20", "L2", 3000.0)),
        grids=(), rooms=(), project_info=ProjectInfo(), elements=elements)


class HostLevelSill(unittest.TestCase):
    def _lift_one(self, doc, source_id):
        nodes = lift_document(doc)
        return {n["source_element_id"]: n for n in nodes}[source_id]

    def test_window_sill_measured_from_host_wall_level(self):
        # Window on a multi-storey wall: own level L2@3000, insertion z=4500.
        # Faithful sill = z - HOST wall level (L1@0) = 4500, NOT 1500.
        win = _hosted("200", "OST_Windows", "Окна", "Win09", 4500.0,
                      level_id="20", level_name="L2")
        node = self._lift_one(_doc(_wall(), win), "200")
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["params"]["sill_mm"], 4500.0)

    def test_window_same_level_unchanged(self):
        win = _hosted("200", "OST_Windows", "Окна", "Win09", 900.0,
                      level_id="10", level_name="L1")
        node = self._lift_one(_doc(_wall(), win), "200")
        self.assertEqual(node["params"]["sill_mm"], 900.0)

    def test_door_z_preserved_as_sill(self):
        door = _hosted("300", "OST_Doors", "Двери", "D09", 3000.0,
                       level_id="20", level_name="L2", x=4000.0)
        node = self._lift_one(_doc(_wall(), door), "300")
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["params"]["sill_mm"], 3000.0)

    def test_door_at_host_level_keeps_historic_params(self):
        # z == host level elevation -> sill absent (canonical hashes stable).
        door = _hosted("300", "OST_Doors", "Двери", "D09", 0.0,
                       level_id="10", level_name="L1", x=4000.0)
        node = self._lift_one(_doc(_wall(), door), "300")
        self.assertEqual(node["kind"], "op")
        self.assertNotIn("sill_mm", node["params"])

    def test_subminimetre_negative_noise_clamped(self):
        win = _hosted("200", "OST_Windows", "Окна", "Win09", -0.5,
                      level_id="10", level_name="L1")
        node = self._lift_one(_doc(_wall(), win), "200")
        self.assertEqual(node["params"]["sill_mm"], 0.0)

    def test_genuinely_negative_sill_is_honest_atom(self):
        win = _hosted("200", "OST_Windows", "Окна", "Win09", -500.0,
                      level_id="10", level_name="L1")
        node = self._lift_one(_doc(_wall(), win), "200")
        self.assertEqual(node["kind"], "atom")


class HostedEmitUsesSill(unittest.TestCase):
    def test_door_sill_lands_in_emitted_z(self):
        from kukai.ir import authoring, ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
        prog = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 6000,
             "level": {"by": "element_id", "value": 42}},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 1000,
             "sill_mm": 3000, "symbol": {"by": "element_id", "value": 777}},
        ]}
        grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
        cs = authoring.emit_program(grounded, "2024")
        self.assertIn("__hl_D1.Elevation + U(3000.0)", cs)

    def test_door_without_sill_is_byte_stable(self):
        from kukai.ir import authoring, ground as ground_mod
        from kukai.ir.compiler import _parse_and_check
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
        prog = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42}},
            {"op": "create_door", "id": "D1",
             "host": {"by": "ref", "value": "W1"}, "offset_mm": 1000,
             "symbol": {"by": "element_id", "value": 777}},
        ]}
        grounded = ground_mod.ground(_parse_and_check(prog), GROUND_SNAPSHOT)
        cs = authoring.emit_program(grounded, "2024")
        self.assertIn("__hl_D1.Elevation + U(0.0)", cs)


class HostedArcWallPlacement(unittest.TestCase):
    """F21: hosted offset is arc length, never projection on the chord."""

    _RADIUS = 8000.0
    _ARC = {
        "curve_type": "Arc",
        "center_mm": [0.0, 0.0, 0.0],
        "radius_mm": _RADIUS,
        "x_axis": [1.0, 0.0, 0.0],
        "y_axis": [0.0, 1.0, 0.0],
        "start_angle_rad": 0.0,
        "end_angle_rad": math.pi / 2.0,
    }

    def test_lift_and_emit_preserve_mid_arc_insertion(self):
        wall = _wall()
        wall = L0Element.from_dict({
            **wall.to_dict(),
            "p0_mm": [self._RADIUS, 0.0, 0.0],
            "p1_mm": [0.0, self._RADIUS, 0.0],
        })
        mid = self._RADIUS / math.sqrt(2.0)
        door = _hosted(
            "300", "OST_Doors", "Двери", "D09", 0.0,
            level_id="10", level_name="L1", x=mid)
        door = L0Element.from_dict({
            **door.to_dict(), "p0_mm": [mid, mid, 0.0],
        })
        curve_index = {"100": {
            "curve_kind": "arc",
            "arc": {key: value for key, value in self._ARC.items()
                    if key != "curve_type"},
        }}

        nodes = {node["source_element_id"]: node for node in lift_document(
            _doc(wall, door), wall_curve_index=curve_index)}
        expected_offset = self._RADIUS * math.pi / 4.0
        self.assertAlmostEqual(
            nodes["300"]["params"]["offset_mm"], expected_offset, places=6)

        from kukai.ir.compiler import compile_program
        from kukai.ir.tests.fixtures import GROUND_SNAPSHOT
        program = {
            "ir_version": "1.0",
            "ops": [
                {"op": "create_wall", "id": "W1",
                 "p0_mm": [self._RADIUS, 0.0],
                 "p1_mm": [0.0, self._RADIUS],
                 "height_mm": 3000.0,
                 "level": {"by": "element_id", "value": 42},
                 "arc": self._ARC},
                {"op": "create_door", "id": "D1",
                 "host": {"by": "ref", "value": "W1"},
                 "offset_mm": expected_offset,
                 "symbol": {"by": "element_id", "value": 777}},
            ],
        }
        compiled = compile_program(program, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(
            compiled.ok, [item.as_dict() for item in compiled.diagnostics])
        self.assertIn(
            f"new XYZ(U({round(mid, 1)}), U({round(mid, 1)}),",
            compiled.csharp)


if __name__ == "__main__":
    unittest.main()
