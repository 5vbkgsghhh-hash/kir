from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
import textwrap
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from kir import spec
from kir.decompile.extract import EXTRACT_CATEGORIES
from kir.decompile.lift import (
    AtomReason,
    LIFTER_TABLE,
    _OPS_WITHOUT_L0_INPUTS,
    is_valid_l1_node,
    lift_document,
    lift_document_detailed,
    lift_element,
    stable_l1_id,
)
from kir.decompile.l1_schema import validate_l1_node
from kir.decompile.curve_extract import (
    CURVE_INDEX_SCHEMA_VERSION,
    CurveExtraction,
    CurveKind,
    CurveRecord,
)
from kir.decompile.schema import L0Document, L0Element
from kir.decompile.sketch_extract import PROFILE_INDEX_SCHEMA_VERSION
from kir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_elements,
    project1_metadata,
)


# 🔴 27.08.2026: KIR LEFT THE PRODUCT TREE. The root was found as the ancestor
# that has `backend/` — i.e. the KUKAI tree; a standalone package has no such
# ancestor at all, and `next()` was raising `StopIteration` without a word
# about the reason. The root is needed here for exactly one thing: so the
# subprocess CAN IMPORT `kir`. So it is the directory CONTAINING the package,
# and it is taken from the package itself.
REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT          # the directory containing the `kir` package
PYTHON_EXECUTABLE = Path(sys.executable).resolve()


def _document(
    elements: list[dict[str, Any]],
    *,
    metadata: dict[str, Any] | None = None,
) -> L0Document:
    row = copy.deepcopy(metadata or project1_metadata())
    row["change_stamp"] = "synthetic-lift-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


def _by_source(nodes: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {node["source_element_id"]: node for node in nodes}


def _profile_entry(
    outline: list[list[float | int]],
    *,
    holes: list[list[list[float | int]]] | None = None,
    curve_kinds: list[list[str]] | None = None,
    arc_midpoints: list[list[list[float | int] | None]] | None = None,
) -> dict[str, Any]:
    contours = [outline] + list(holes or [])
    return {
        "profile_available": True,
        "exterior_loop": copy.deepcopy(outline),
        "holes": copy.deepcopy(holes or []),
        "curve_kinds": copy.deepcopy(curve_kinds) if curve_kinds else [
            ["line"] * len(contour) for contour in contours
        ],
        "arc_midpoints": (
            copy.deepcopy(arc_midpoints) if arc_midpoints else [
                [None] * len(contour) for contour in contours
            ]
        ),
    }


def _slab_foundation(element_id: int) -> dict[str, Any]:
    row = make_element(
        "OST_StructuralFoundation", element_id, ordinal=0)
    row.update({
        "geom_kind": "bbox_only",
        "p0_mm": None,
        "p1_mm": None,
        "rotation_deg": None,
    })
    return row


def _stairs_side_index(
    element_id: str,
    path_row: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": PROFILE_INDEX_SCHEMA_VERSION,
        "profile_index": {
            element_id: {"profile_available": False},
        },
        "stairs_run_path_index": {
            element_id: {"run-1": copy.deepcopy(path_row)},
        },
        "failures": [],
    }


def _family_element_and_index(
    element_id: int = 14_001,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    element = make_element("OST_Furniture", element_id, ordinal=0)
    element.update({
        "type_id": "800",
        "type_name": "Стол 1200",
    })
    point = list(element["p0_mm"])
    return element, {
        str(element_id): {
            "symbol_id": "800",
            "type_name": "Стол 1200",
            "family_name": "Стол офисный",
            "placement_type": "OneLevelBased",
            "in_place": False,
            "mirrored": True,
            "hand_flipped": False,
            "facing_flipped": True,
            "super_component_id": None,
            "group_id": "900",
            "host_id": None,
            "host_class": None,
            "hand_orientation": [1.0, 0.0, 0.0],
            "facing_orientation": [0.0, 1.0, 0.0],
            "placement_available": True,
            "point_mm": point,
            "rotation_deg": 27.5,
        },
    }


class RegistryAndNodeContractTests(unittest.TestCase):
    def test_lift_authority_is_live_op_registry_not_query_kind_registry(
            self) -> None:
        # The exact NUMBER of kinds is irrelevant to this test's claim: it
        # would break under any legitimate growth of the table (27.07: 21 ->
        # 51, when structural/HVAC/plumbing/electrical were added to it). The
        # claim is about the AUTHORITY: the lifter refers to the OP registry,
        # and its node names live in their own namespace and are NOT required
        # to match the query kind names. "beam"/"foundation" are the lift's
        # node names; in the kind registry the same categories are named
        # differently (structural_framing, etc.), and this is exactly what
        # proves the tables are independent.
        self.assertNotIn("beam", spec.KINDS)
        self.assertNotIn("foundation", spec.KINDS)
        self.assertIn("create_beam", spec.OPS)
        self.assertIn("create_foundation", spec.OPS)
        self.assertIn("create_cable_tray", spec.OPS)
        self.assertIn("create_floor", spec.OPS)
        self.assertIn("create_roof", spec.OPS)
        self.assertIn("create_stairs", spec.OPS)
        self.assertEqual(
            LIFTER_TABLE["OST_StructuralFraming"],
            ("beam", "create_beam"),
        )
        self.assertEqual(
            LIFTER_TABLE["OST_StructuralFoundation"],
            ("foundation", "create_foundation"),
        )
        self.assertEqual(
            LIFTER_TABLE["OST_CableTray"],
            ("cable_tray", "create_cable_tray"),
        )
        self.assertEqual(
            LIFTER_TABLE["OST_Floors"],
            ("floor", "create_floor"),
        )
        self.assertEqual(
            LIFTER_TABLE["OST_Roofs"],
            ("roof", "create_roof"),
        )
        self.assertEqual(
            LIFTER_TABLE["OST_Stairs"],
            ("stair", "create_stairs"),
        )

    def test_ids_follow_kind_plus_source_sha1_and_are_idempotent(self) -> None:
        wall = L0Element.from_dict(make_element("OST_Walls", 9001, ordinal=0))
        first = lift_element(wall)
        second = lift_element(wall)
        self.assertEqual(first, second)
        self.assertEqual(first["_id"], stable_l1_id("op", "9001"))
        self.assertEqual(len(first["_id"]), 40)

        bad_row = make_element("OST_Walls", 9001, ordinal=0)
        bad_row["params"] = {}
        atom = lift_element(L0Element.from_dict(bad_row))
        self.assertEqual(atom["_id"], stable_l1_id("atom", "9001"))
        self.assertNotEqual(first["_id"], atom["_id"])
        self.assertEqual(
            atom["reason"]["code"], AtomReason.MISSING_PARAMETER.value)

    def test_nullable_wave_a_bbox_never_invents_an_anchor(self) -> None:
        row = make_element("OST_Furniture", 9100, ordinal=0)
        row.update({
            "geom_kind": "bbox_only",
            "p0_mm": None,
            "p1_mm": None,
            "rotation_deg": None,
            "bbox_min_mm": None,
            "bbox_max_mm": None,
        })
        node = lift_element(L0Element.from_dict(row))
        self.assertEqual(node["kind"], "atom")
        self.assertIsNone(node["bbox_min_mm"])
        self.assertIsNone(node["bbox_max_mm"])
        self.assertIsNone(node["anchor_mm"])
        self.assertTrue(is_valid_l1_node(node))


class DirectLifterTests(unittest.TestCase):
    def test_wall_uses_exact_curve_height_level_and_type(self) -> None:
        row = make_element("OST_Walls", 9200, ordinal=0)
        row["p0_mm"] = [100.0, 200.0, 0.0]
        row["p1_mm"] = [4_100.0, 3_200.0, 0.0]
        row["params"] = {"WALL_USER_HEIGHT_PARAM": 2_850.0}

        node = lift_element(L0Element.from_dict(row))

        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_wall")
        self.assertEqual(node["type_name"], "Стены — synthetic type")
        self.assertEqual(node["params"], {
            "p0_mm": [100.0, 200.0],
            "p1_mm": [4_100.0, 3_200.0],
            "level": {"by": "name", "value": "Этаж 1", "_id": "100"},
            "height_mm": 2_850.0,
            "type": {
                "by": "name",
                "value": "Стены — synthetic type",
                "_id": "50000",
            },
        })
        self.assertEqual(node["anchor_mm"], [2_100.0, 1_700.0, 0.0])
        self.assertTrue(is_valid_l1_node(node))

    def test_structural_and_architectural_columns_use_live_signature(self) -> None:
        structural = make_element(
            "OST_StructuralColumns", 9300, ordinal=0)
        architectural = make_element("OST_Columns", 9301, ordinal=0)
        document = _document([structural, architectural])

        nodes = lift_document(document)

        self.assertEqual(
            [node["kind"] for node in nodes],
            ["op", "op"],
        )
        self.assertEqual(nodes[0]["op_name"], "create_column")
        self.assertEqual(nodes[0]["params"]["category"], "structural")
        self.assertIn("symbol", nodes[0]["params"])
        self.assertEqual(nodes[0]["params"]["rotation_deg"], 0.0)
        self.assertEqual(nodes[1]["params"]["category"], "architectural")
        for node in nodes:
            self.assertLessEqual(
                set(node["params"]),
                {param.name for param in spec.OPS[node["op_name"]].params},
            )

    def test_rotated_column_lifts_with_measured_rotation(self) -> None:
        row = make_element("OST_StructuralColumns", 9302, ordinal=1)
        result = lift_document_detailed(_document([row]))

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.nodes[0]["kind"], "op")
        self.assertEqual(result.nodes[0]["op_name"], "create_column")
        self.assertEqual(result.nodes[0]["params"]["rotation_deg"], 15.0)
        self.assertEqual(validate_l1_node(result.nodes[0]), result.nodes[0])

    def test_pipe_and_circular_duct_use_3d_geometry_and_live_type_names(self) -> None:
        pipe = make_element("OST_PipeCurves", 9400, ordinal=0)
        duct = make_element("OST_DuctCurves", 9401, ordinal=0)
        duct["params"] = {"RBS_CURVE_DIAMETER_PARAM": 400.0}

        nodes = lift_document(_document([pipe, duct]))

        self.assertEqual(nodes[0]["op_name"], "create_pipe")
        self.assertEqual(nodes[0]["params"]["diameter_mm"], 100.0)
        self.assertIn("pipe_type", nodes[0]["params"])
        self.assertEqual(len(nodes[0]["params"]["p0_mm"]), 3)
        self.assertEqual(nodes[1]["op_name"], "create_duct")
        self.assertEqual(nodes[1]["params"]["diameter_mm"], 400.0)
        self.assertIn("duct_type", nodes[1]["params"])

    def test_rectangular_duct_is_atom_until_forward_signature_supports_it(
            self) -> None:
        row = make_element("OST_DuctCurves", 9402, ordinal=0)
        result = lift_document_detailed(_document([row]))

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertEqual(
            result.diagnostics[0].reason,
            AtomReason.MISSING_PARAMETER,
        )
        self.assertIn("RBS_CURVE_DIAMETER_PARAM", result.diagnostics[0].detail)


class MetadataLifterTests(unittest.TestCase):
    def test_level_grid_and_room_join_metadata_by_exact_element_id(self) -> None:
        level = make_element("OST_Levels", 100, ordinal=0)
        grid = make_element("OST_Grids", 7001, ordinal=0)
        room = make_element("OST_Rooms", 8001, ordinal=0)

        nodes = _by_source(lift_document(_document([room, grid, level])))

        self.assertEqual(nodes["100"]["op_name"], "create_level")
        self.assertEqual(nodes["100"]["params"], {
            "elev_mm": 0.0,
            "name": "Этаж 1",
        })
        self.assertEqual(nodes["7001"]["op_name"], "create_grid")
        self.assertEqual(nodes["7001"]["params"], {
            "p0_mm": [0.0, -1_000.0],
            "p1_mm": [0.0, 12_000.0],
            "name": "1",
        })
        self.assertEqual(nodes["8001"]["op_name"], "create_room")
        self.assertEqual(nodes["8001"]["params"]["xy"], [3_000.0, 2_000.0])
        self.assertEqual(nodes["8001"]["params"]["name"], "Комната 101")
        self.assertEqual(nodes["8001"]["anchor_mm"], [3_000.0, 2_000.0, 0.0])

    def test_metadata_record_does_not_add_an_l1_node_without_l0_element(
            self) -> None:
        wall = make_element("OST_Walls", 9500, ordinal=0)
        document = _document([wall])

        nodes = lift_document(document)

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0]["source_element_id"], "9500")

    def test_room_without_reliable_boundary_is_atom(self) -> None:
        metadata = project1_metadata()
        metadata["rooms"][0]["boundary_mm"] = []
        metadata["rooms"][0]["boundary_loops_mm"] = []
        room = make_element("OST_Rooms", 8001, ordinal=0)

        result = lift_document_detailed(
            _document([room], metadata=metadata))

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertEqual(
            result.diagnostics[0].reason,
            AtomReason.MISSING_GEOMETRY,
        )

    @staticmethod
    def _room_document(
        exterior: list[list[float]],
        holes: list[list[list[float]]] | None = None,
    ) -> L0Document:
        metadata = project1_metadata()
        metadata["rooms"][0]["boundary_mm"] = copy.deepcopy(exterior)
        metadata["rooms"][0]["boundary_loops_mm"] = [
            copy.deepcopy(exterior), *copy.deepcopy(holes or []),
        ]
        return _document(
            [make_element("OST_Rooms", 8001, ordinal=0)],
            metadata=metadata,
        )

    @staticmethod
    def _point_in_ring(
        point: list[float],
        ring: list[list[float]],
    ) -> bool:
        x, y = point
        inside = False
        previous = ring[-1]
        for current in ring:
            x0, y0 = previous
            x1, y1 = current
            if (y0 > y) != (y1 > y):
                crossing = (x1 - x0) * (y - y0) / (y1 - y0) + x0
                if x < crossing:
                    inside = not inside
            previous = current
        return inside

    @staticmethod
    def _boundary_clearance(
        point: list[float],
        rings: list[list[list[float]]],
    ) -> float:
        distances = []
        for ring in rings:
            for index, start in enumerate(ring):
                end = ring[(index + 1) % len(ring)]
                dx, dy = end[0] - start[0], end[1] - start[1]
                length2 = dx * dx + dy * dy
                projection = (
                    ((point[0] - start[0]) * dx
                     + (point[1] - start[1]) * dy) / length2
                )
                projection = min(1.0, max(0.0, projection))
                px = start[0] + projection * dx
                py = start[1] + projection * dy
                distances.append(math.hypot(point[0] - px, point[1] - py))
        return min(distances)

    def test_concave_room_uses_a_provably_interior_point(self) -> None:
        exterior = [
            [0.0, 0.0], [6_000.0, 0.0], [6_000.0, 1_000.0],
            [1_000.0, 1_000.0], [1_000.0, 6_000.0], [0.0, 6_000.0],
        ]

        node = lift_document(self._room_document(exterior))[0]

        self.assertEqual(node["kind"], "op")
        point = node["params"]["xy"]
        self.assertTrue(self._point_in_ring(point, exterior))
        self.assertGreaterEqual(
            self._boundary_clearance(point, [exterior]), 10.0)
        # The old area centroid lies outside this L-shaped room; the fallback
        # therefore proves this is not the former centroid-or-refuse path.
        self.assertLess(point[0], 1_000.0)
        self.assertLess(point[1], 1_000.0)

    def test_room_with_hole_selects_interior_outside_hole_with_margin(
            self) -> None:
        exterior = [
            [0.0, 0.0], [10_000.0, 0.0],
            [10_000.0, 10_000.0], [0.0, 10_000.0],
        ]
        hole = [
            [4_000.0, 4_000.0], [6_000.0, 4_000.0],
            [6_000.0, 6_000.0], [4_000.0, 6_000.0],
        ]

        node = lift_document(self._room_document(exterior, [hole]))[0]

        point = node["params"]["xy"]
        self.assertTrue(self._point_in_ring(point, exterior))
        self.assertFalse(self._point_in_ring(point, hole))
        self.assertGreaterEqual(
            self._boundary_clearance(point, [exterior, hole]), 10.0)

    def test_room_with_fewer_than_three_distinct_vertices_is_typed_atom(
            self) -> None:
        malformed = [
            [0.0, 0.0], [1_000.0, 0.0],
            [1_000.0, 0.0], [0.0, 0.0],
        ]

        result = lift_document_detailed(self._room_document(malformed))

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertEqual(
            result.diagnostics[0].reason, AtomReason.MISSING_GEOMETRY)
        self.assertIn("three distinct vertices", result.diagnostics[0].detail)

    def test_room_point_is_ring_order_independent(self) -> None:
        exterior = [
            [0.0, 0.0], [12_000.0, 0.0],
            [12_000.0, 10_000.0], [0.0, 10_000.0],
        ]
        holes = [
            [[2_000.0, 2_000.0], [4_000.0, 2_000.0],
             [4_000.0, 4_000.0], [2_000.0, 4_000.0]],
            [[8_000.0, 6_000.0], [10_000.0, 6_000.0],
             [10_000.0, 8_000.0], [8_000.0, 8_000.0]],
        ]
        shifted = exterior[2:] + exterior[:2]
        reversed_holes = [
            list(reversed(holes[1][1:] + holes[1][:1])),
            list(reversed(holes[0][2:] + holes[0][:2])),
        ]

        first = lift_document(self._room_document(exterior, holes))[0]
        second = lift_document(
            self._room_document(list(reversed(shifted)), reversed_holes))[0]

        self.assertEqual(first["params"]["xy"], second["params"]["xy"])

    def test_room_point_is_deterministic_under_two_hashseeds(self) -> None:
        script = textwrap.dedent(
            """
            import json
            from kir.decompile.lift import lift_document
            from kir.decompile.schema import L0Document
            from kir.decompile.tests.fixtures_decompile import (
                make_element, project1_metadata,
            )

            exterior = [[0.0, 0.0], [10000.0, 0.0],
                        [10000.0, 10000.0], [0.0, 10000.0]]
            hole = [[4000.0, 4000.0], [6000.0, 4000.0],
                    [6000.0, 6000.0], [4000.0, 6000.0]]
            row = project1_metadata()
            row["change_stamp"] = "room-hashseed"
            row["category_status"] = []
            row["elements"] = [make_element("OST_Rooms", 8001, ordinal=0)]
            row["rooms"][0]["boundary_mm"] = exterior
            row["rooms"][0]["boundary_loops_mm"] = [exterior, hole]
            point = lift_document(L0Document.from_dict(row))[0]["params"]["xy"]
            print(json.dumps(point, separators=(",", ":"), allow_nan=False))
            """
        )
        outputs = []
        for seed in ("17", "8128"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = str(BACKEND_ROOT)
            completed = subprocess.run(
                [str(PYTHON_EXECUTABLE), "-c", script],
                cwd=BACKEND_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])


class HostedReferenceTests(unittest.TestCase):
    @staticmethod
    def _hosted_rows() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        wall = make_element("OST_Walls", 9001, ordinal=0)
        wall["p0_mm"] = [100.0, 200.0, 0.0]
        wall["p1_mm"] = [4_100.0, 3_200.0, 0.0]

        door = make_element("OST_Doors", 9600, ordinal=0)
        door["host_id"] = "9001"
        # wall direction is [0.8, 0.6], so this is exactly 2,500 mm along.
        door["p0_mm"] = [2_100.0, 1_700.0, 0.0]

        window = make_element("OST_Windows", 9601, ordinal=0)
        window["host_id"] = "9001"
        # Exactly 3,750 mm along, 900 mm above level elevation.
        window["p0_mm"] = [3_100.0, 2_450.0, 900.0]
        return wall, door, window

    def test_projection_and_sill_are_exact_and_input_order_independent(
            self) -> None:
        wall, door, window = self._hosted_rows()
        document = _document([door, window, wall])

        nodes = _by_source(lift_document(document))

        wall_node = nodes["9001"]
        self.assertEqual(nodes["9600"]["op_name"], "create_door")
        self.assertEqual(nodes["9600"]["params"]["offset_mm"], 2_500.0)
        self.assertEqual(
            nodes["9600"]["params"]["host"],
            {"ref": wall_node["_id"]},
        )
        self.assertEqual(nodes["9601"]["op_name"], "create_window")
        self.assertEqual(nodes["9601"]["params"]["offset_mm"], 3_750.0)
        self.assertEqual(nodes["9601"]["params"]["sill_mm"], 900.0)
        self.assertEqual(
            nodes["9601"]["params"]["host"],
            {"ref": wall_node["_id"]},
        )

    def test_hosted_op_consistently_references_an_atom_wall(self) -> None:
        wall, door, _window = self._hosted_rows()
        wall["params"] = {}  # wall cannot regenerate, but its curve is truthful.

        nodes = _by_source(lift_document(_document([door, wall])))

        self.assertEqual(nodes["9001"]["kind"], "atom")
        self.assertEqual(nodes["9600"]["kind"], "op")
        self.assertEqual(
            nodes["9600"]["params"]["host"],
            {"ref": nodes["9001"]["_id"]},
        )

    def test_missing_host_or_out_of_segment_projection_atomizes(self) -> None:
        wall, door, _window = self._hosted_rows()
        missing = copy.deepcopy(door)
        missing["element_id"] = "9602"
        missing["host_id"] = "does-not-exist"
        outside = copy.deepcopy(door)
        outside["element_id"] = "9603"
        outside["p0_mm"] = [8_100.0, 6_200.0, 0.0]

        result = lift_document_detailed(
            _document([missing, outside, wall]))
        nodes = _by_source(result.nodes)
        diagnostics = {
            item.source_element_id: item for item in result.diagnostics}

        self.assertEqual(nodes["9602"]["kind"], "atom")
        self.assertEqual(
            diagnostics["9602"].reason,
            AtomReason.MISSING_REFERENCE,
        )
        self.assertEqual(nodes["9603"]["kind"], "atom")
        self.assertEqual(
            diagnostics["9603"].reason,
            AtomReason.INVALID_VALUE,
        )


class ProfileIndexLifterTests(unittest.TestCase):
    OUTLINE = [
        [0, 0], [6_000, 0], [6_000, 4_000], [0, 4_000],
    ]
    COURTYARD = [
        [2_000, 1_000], [4_000, 1_000],
        [4_000, 3_000], [2_000, 3_000],
    ]

    def test_floor_lifts_exact_outline_hole_level_and_type(self) -> None:
        row = make_element("OST_Floors", 9700, ordinal=0)
        profile_index = {
            "9700": _profile_entry(
                self.OUTLINE,
                holes=[self.COURTYARD],
            ),
        }

        result = lift_document_detailed(
            _document([row]),
            profile_index=profile_index,
        )

        self.assertEqual(result.diagnostics, ())
        node = result.nodes[0]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_floor")
        self.assertEqual(node["params"], {
            "outline": [[float(value) for value in point]
                        for point in self.OUTLINE],
            "holes": [[
                [float(value) for value in point]
                for point in self.COURTYARD
            ]],
            "level": {"by": "name", "value": "Этаж 1", "_id": "100"},
            "type": {
                "by": "name",
                "value": "Перекрытия — synthetic type",
                "_id": "50001",
            },
        })
        self.assertEqual(validate_l1_node(node), node)

    def test_roof_lifts_through_optional_lift_element_index(self) -> None:
        row = make_element("OST_Roofs", 9701, ordinal=0)
        element = L0Element.from_dict(row)

        node = lift_element(
            element,
            profile_index={"9701": _profile_entry(self.OUTLINE)},
        )

        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_roof")
        self.assertEqual(
            node["params"]["outline"],
            [[float(value) for value in point] for point in self.OUTLINE],
        )
        self.assertNotIn("holes", node["params"])
        self.assertEqual(node["params"]["level"]["_id"], "100")
        self.assertEqual(node["params"]["type"]["_id"], "50002")
        self.assertEqual(validate_l1_node(node), node)

    def test_slab_foundation_lifts_exact_profile_holes_level_and_type(
            self) -> None:
        row = _slab_foundation(9713)
        profile_index = {
            "9713": _profile_entry(
                self.OUTLINE,
                holes=[self.COURTYARD],
            ),
        }

        result = lift_document_detailed(
            _document([row]),
            profile_index=profile_index,
        )

        self.assertEqual(result.diagnostics, ())
        node = result.nodes[0]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_foundation")
        self.assertEqual(node["params"], {
            "variety": "slab",
            "outline": [[float(value) for value in point]
                        for point in self.OUTLINE],
            "holes": [[
                [float(value) for value in point]
                for point in self.COURTYARD
            ]],
            "type": {
                "by": "name",
                "value": "Фундаменты несущих конструкций — synthetic type",
                "_id": "50006",
            },
            "level": {"by": "name", "value": "Этаж 1", "_id": "100"},
        })
        self.assertNotIn("xy", node["params"])
        self.assertNotIn("symbol", node["params"])
        self.assertEqual(validate_l1_node(node), node)

    def test_slab_foundation_without_usable_profile_fails_closed(self) -> None:
        rows = [
            _slab_foundation(9714),
            _slab_foundation(9715),
            _slab_foundation(9716),
            _slab_foundation(9719),
        ]
        arc_profile = _profile_entry(
            self.OUTLINE,
            curve_kinds=[["line", "arc", "line", "line"]],
            arc_midpoints=[[None, [7_000, 2_000], None, None]],
        )
        profile_index = {
            "9715": {"profile_available": False},
            "9716": arc_profile,
            "9719": _profile_entry(
                self.OUTLINE,
                holes=[[
                    [200 + index * 500, 200],
                    [500 + index * 500, 200],
                    [500 + index * 500, 500],
                    [200 + index * 500, 500],
                ] for index in range(9)],
            ),
        }

        result = lift_document_detailed(
            _document(rows),
            profile_index=profile_index,
        )

        self.assertTrue(all(node["kind"] == "atom" for node in result.nodes))
        self.assertEqual(
            [item.reason for item in result.diagnostics],
            [
                AtomReason.MISSING_GEOMETRY,
                AtomReason.MISSING_GEOMETRY,
                AtomReason.UNSUPPORTED_GEOMETRY,
                AtomReason.UNSUPPORTED_SIGNATURE,
            ],
        )
        self.assertEqual(
            result.nodes[0]["reason"]["detail"],
            "foundation slab needs a Sketch profile; only point footing is invertible",
        )
        self.assertTrue(all("params" not in node for node in result.nodes))

    def test_slab_foundation_holes_refuse_the_2021_forward_path(self) -> None:
        metadata = project1_metadata()
        metadata["revit_version"] = "2021"
        row = _slab_foundation(9720)

        result = lift_document_detailed(
            _document([row], metadata=metadata),
            profile_index={
                "9720": _profile_entry(
                    self.OUTLINE,
                    holes=[self.COURTYARD],
                ),
            },
        )

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertEqual(
            result.diagnostics[0].reason,
            AtomReason.UNSUPPORTED_SIGNATURE,
        )
        self.assertIn("2022+", result.diagnostics[0].detail)

    def test_profile_does_not_reclassify_point_or_curve_foundations(
            self) -> None:
        point = make_element(
            "OST_StructuralFoundation", 9717, ordinal=0)
        curve = make_element(
            "OST_StructuralFoundation", 9718, ordinal=0)
        curve.update({
            "geom_kind": "curve",
            "p0_mm": [0.0, 0.0, 0.0],
            "p1_mm": [6_000.0, 0.0, 0.0],
            "rotation_deg": None,
        })
        profile_index = {
            "9717": _profile_entry(self.OUTLINE),
            "9718": _profile_entry(self.OUTLINE),
        }

        result = lift_document_detailed(
            _document([point, curve]),
            profile_index=profile_index,
        )

        self.assertEqual(result.nodes[0]["op_name"], "create_foundation")
        self.assertEqual(result.nodes[0]["params"]["variety"], "isolated")
        self.assertIn("xy", result.nodes[0]["params"])
        self.assertNotIn("outline", result.nodes[0]["params"])
        self.assertEqual(result.nodes[1]["kind"], "atom")
        self.assertEqual(
            result.diagnostics[0].reason,
            AtomReason.MISSING_GEOMETRY,
        )

    def test_arc_profiles_and_roof_holes_fail_closed(self) -> None:
        rows = [
            make_element("OST_Floors", 9702, ordinal=0),
            make_element("OST_Roofs", 9703, ordinal=0),
            make_element("OST_Roofs", 9704, ordinal=0),
        ]
        arc_profile = _profile_entry(
            self.OUTLINE,
            curve_kinds=[["line", "arc", "line", "line"]],
            arc_midpoints=[[None, [7_000, 2_000], None, None]],
        )
        profile_index = {
            "9702": copy.deepcopy(arc_profile),
            "9703": copy.deepcopy(arc_profile),
            "9704": _profile_entry(
                self.OUTLINE,
                holes=[self.COURTYARD],
            ),
        }

        result = lift_document_detailed(
            _document(rows),
            profile_index=profile_index,
        )

        # 28.07: for a FLOOR, an arc profile stopped being a dead end — it is
        # now taken by `create_floor_by_contour` (the op existed from the
        # start, but was never mentioned in the decompile). A ROOF has no
        # contour op, so its arc remains a genuine atom, and so does an
        # opening in a roof.
        by_source = {node["source_element_id"]: node for node in result.nodes}
        floor = by_source["9702"]
        self.assertEqual(floor["kind"], "op", floor.get("reason"))
        self.assertEqual(floor["op_name"], "create_floor_by_contour")
        self.assertEqual(
            floor["params"]["contour"]["outer"]["arcs"][0]["edge"], 1)

        for element_id in ("9703", "9704"):
            with self.subTest(element=element_id):
                self.assertEqual(by_source[element_id]["kind"], "atom")
                self.assertNotIn("params", by_source[element_id])
        self.assertEqual(
            [item.reason for item in result.diagnostics],
            [
                AtomReason.UNSUPPORTED_GEOMETRY,
                AtomReason.UNSUPPORTED_SIGNATURE,
            ],
        )
        # The midpoint of an arc has no right to become the element's
        # "anchor" — it is a point of the profile's GEOMETRY, not of
        # position.
        self.assertNotIn(
            [7_000.0, 2_000.0],
            [node.get("anchor_mm") for node in result.nodes],
        )

    def _wall_with_top(self, *, base_offset, top_offset, eid=9310):
        row = make_element("OST_Walls", eid, ordinal=0)   # level "Floor 1" @ 0
        row["params"] = {
            "WALL_USER_HEIGHT_PARAM": 3615.0,
            "WALL_BASE_OFFSET": base_offset,
            "WALL_HEIGHT_TYPE": "100",        # the same level as the base
            "WALL_TOP_OFFSET": top_offset,
        }
        return row

    def test_top_attachment_below_the_base_is_not_lifted(self) -> None:
        """Found by rebuilding a real building on 27.07: a chunk of 250 ops
        was rolling back entirely with «Верх стены находится ниже, чем
        подошва стены».

        In SOB6.2 there are TWO such walls out of 693: base +2185 with top
        −300 (both bindings point to the same level). The hypothesis
        "binding to its own level = height is unconstrained" is REFUTED by
        measurement: of 94 such walls only 2 are impossible, the other 92
        are legitimate. So the rule is purely geometric — we lift the top
        binding only if the top is strictly above the base; otherwise the
        measured height remains, which is what the wall actually has."""
        result = lift_document_detailed(
            _document([self._wall_with_top(base_offset=2185.0, top_offset=-300.0)]))
        node = result.nodes[0]
        self.assertEqual(node["op_name"], "create_wall")
        self.assertNotIn("top_level", node["params"])
        self.assertNotIn("top_offset_mm", node["params"])
        self.assertEqual(node["params"]["height_mm"], 3615.0)
        self.assertEqual(validate_l1_node(node), node)

    def test_a_valid_top_attachment_on_the_same_level_is_kept(self) -> None:
        """92 of 94 walls in the same building are bound to their own level
        and are entirely legitimate — the rule must not lose them."""
        result = lift_document_detailed(
            _document([self._wall_with_top(base_offset=-150.0, top_offset=3000.0)]))
        params = result.nodes[0]["params"]
        self.assertEqual(params["top_level"],
                         {"by": "name", "value": "Этаж 1", "_id": "100"})
        self.assertEqual(params["top_offset_mm"], 3000.0)

    def test_top_attachment_to_a_higher_level_is_untouched(self) -> None:
        """A genuine inter-floor binding (123 walls in the same
        building)."""
        row = make_element("OST_Walls", 9311, ordinal=0)
        row["params"] = {
            "WALL_USER_HEIGHT_PARAM": 3400.0,
            "WALL_BASE_OFFSET": -100.0,
            "WALL_HEIGHT_TYPE": "101",        # "Floor 2" @ 3000
            "WALL_TOP_OFFSET": -300.0,
        }
        params = lift_document_detailed(_document([row])).nodes[0]["params"]
        self.assertEqual(params["top_level"]["_id"], "101")
        self.assertEqual(params["top_offset_mm"], -300.0)

    def test_stairs_lifts_one_exact_straight_run_and_both_levels(self) -> None:
        row = make_element("OST_Stairs", 9705, ordinal=0)
        side_index = _stairs_side_index("9705", {
            "path_available": True,
            "points_mm": [[0, 0], [2_500, 0], [5_000, 0]],
            "curve_kinds": ["line", "line"],
            "arc_midpoints_mm": [None, None],
        })

        result = lift_document_detailed(
            _document([row]),
            profile_index=side_index,
        )

        self.assertEqual(result.diagnostics, ())
        node = result.nodes[0]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_stairs")
        self.assertEqual(node["params"], {
            "p0_mm": [0.0, 0.0],
            "p1_mm": [5_000.0, 0.0],
            "base_level": {
                "by": "name", "value": "Этаж 1", "_id": "100",
            },
            "top_level": {
                "by": "name", "value": "Этаж 2", "_id": "101",
            },
        })
        self.assertNotIn("width_mm", node["params"])
        self.assertEqual(validate_l1_node(node), node)

    def test_stairs_without_available_run_path_remains_atom(self) -> None:
        row = make_element("OST_Stairs", 9706, ordinal=0)
        side_index = _stairs_side_index(
            "9706", {"path_available": False})

        result = lift_document_detailed(
            _document([row]),
            profile_index=side_index,
        )

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertEqual(
            result.nodes[0]["reason"],
            {
                "code": AtomReason.MISSING_GEOMETRY.value,
                "detail": "frozen L0 has no reliable stair-run geometry",
            },
        )
        self.assertEqual(
            result.diagnostics[0].reason,
            AtomReason.MISSING_GEOMETRY,
        )

    def test_profile_lifting_is_deterministic_under_two_hashseeds(self) -> None:
        profile_index = {
            "profile_index": {
                "9710": _profile_entry(
                    self.OUTLINE,
                    holes=[self.COURTYARD],
                ),
                "9711": _profile_entry(self.OUTLINE),
                "9712": {"profile_available": False},
                "9713": _profile_entry(self.OUTLINE),
            },
            "stairs_run_path_index": {
                "9712": {"run-1": {
                    "path_available": True,
                    "points_mm": [[0, 0], [5_000, 0]],
                    "curve_kinds": ["line"],
                    "arc_midpoints_mm": [None],
                }},
            },
        }
        script = textwrap.dedent(
            f"""
            import json
            from kir.decompile.lift import lift_document
            from kir.decompile.schema import L0Document
            from kir.decompile.tests.fixtures_decompile import (
                make_element, project1_metadata,
            )

            row = project1_metadata()
            row["change_stamp"] = "hashseed-lift"
            row["category_status"] = []
            row["elements"] = [
                make_element("OST_Floors", 9710, ordinal=0),
                make_element("OST_Roofs", 9711, ordinal=0),
                make_element("OST_Stairs", 9712, ordinal=0),
            ]
            foundation = make_element(
                "OST_StructuralFoundation", 9713, ordinal=0)
            foundation.update({{
                "geom_kind": "bbox_only",
                "p0_mm": None,
                "p1_mm": None,
                "rotation_deg": None,
            }})
            row["elements"].append(foundation)
            document = L0Document.from_dict(row)
            profile_index = {profile_index!r}
            print(json.dumps(
                lift_document(document, profile_index),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ))
            """
        )
        outputs = []
        for seed in ("7", "991"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = str(BACKEND_ROOT)
            completed = subprocess.run(
                [str(PYTHON_EXECUTABLE), "-c", script],
                cwd=BACKEND_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(
            [node["op_name"] for node in json.loads(outputs[0])],
            [
                "create_floor", "create_roof", "create_stairs",
                "create_foundation",
            ],
        )


class UniversalFamilyFallbackTests(unittest.TestCase):
    def test_unowned_family_instance_lifts_with_full_selector_and_state(
            self) -> None:
        element, placement_index = _family_element_and_index()

        node = lift_document(
            _document([element]),
            family_placement_index=placement_index,
        )[0]

        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "place_family")
        self.assertEqual(node["params"]["xyz"], placement_index["14001"]["point_mm"])
        self.assertEqual(node["params"]["rotation_deg"], 27.5)
        self.assertTrue(node["params"]["mirrored"])
        self.assertFalse(node["params"]["hand_flipped"])
        self.assertTrue(node["params"]["facing_flipped"])
        self.assertEqual(node["params"]["symbol"], {
            "by": "family_type",
            "category": "OST_Furniture",
            "family_name": "Стол офисный",
            "type_name": "Стол 1200",
            "_id": "800",
        })
        self.assertEqual(node["params"]["level"]["_id"], element["level_id"])
        validate_l1_node(node)

    def test_no_side_index_preserves_the_pre_r1_atom_exactly(self) -> None:
        element, _ = _family_element_and_index()
        document = _document([element])

        without_argument = lift_document(document)[0]
        with_empty_index = lift_document(
            document, family_placement_index={})[0]

        self.assertEqual(without_argument, with_empty_index)
        self.assertEqual(without_argument["kind"], "atom")
        self.assertEqual(
            without_argument["reason"]["code"], AtomReason.NO_LIFTER.value)

    def test_curve_based_instance_lifts_to_place_family_with_a_curve(
            self) -> None:
        """A CurveBased instance with a readable straight line gets lifted,
        rather than staying an atom.

        MEASUREMENT of 27.07 (the electrical training model, SKLNK R2026):
        after fixing the refusal order, honest coverage is 67.70%, and the
        WHOLE remainder of the hole is 79 elements, all
        `FamilyPlacementType.CurveBased`. In the live model all 79 have a
        `LocationCurve`, and all the curves are straight. Instance 1268396 is
        «Техстронг_ОЗК : 4 стороны», a generic model, host 1221482 (a cable
        tray), Line [155643,-5766,565] -> [155643,-5766,4910].

        The host is not an obstacle here, and this is a MEASURED decision,
        not a relaxation: the `NewFamilyInstance` overload with a host curve
        does NOT accept one — Revit does the binding itself. So the host is
        not imposed, but is read back in the witness; refusing because of it
        would mean losing the element for the sake of a field the call does
        not even have.
        """
        from kir.decompile.curtain_extract import CurveState

        # The host must be IN THE DOCUMENT and lift earlier — exactly like a
        # wall under a door. Without it there is nothing to place the casing
        # on, and the lift must say so, rather than invent a location.
        tray = make_element("OST_CableTray", 1_221_482, ordinal=0)
        element, placement_index = _family_element_and_index(16_800)
        placement_index["16800"].update({
            "placement_type": "CurveBased",
            "host_id": "1221482", "host_class": "CableTray",
            "point_mm": None, "rotation_deg": None,
            "curve_state": CurveState.LINE.value,
            "curve_p0_mm": [155643.0, -5766.0, 565.0],
            "curve_p1_mm": [155643.0, -5766.0, 4910.0],
        })
        result = lift_document_detailed(
            _document([tray, element]), family_placement_index=placement_index)
        result = type(result)(
            nodes=[n for n in result.nodes
                   if n.get("source_element_id") == "16800"],
            diagnostics=result.diagnostics)

        node = result.nodes[0]
        self.assertEqual(node["kind"], "op", node.get("reason"))
        self.assertEqual(node["op_name"], "place_family")
        self.assertEqual(node["params"]["p0_mm"], [155643.0, -5766.0, 565.0])
        self.assertEqual(node["params"]["p1_mm"], [155643.0, -5766.0, 4910.0])
        # a point must not exist for the curved variant — otherwise the
        # compiler will refuse it as an ambiguity (KIR-P007)
        self.assertNotIn("xyz", node["params"])
        # the curved variant HAS NO level (measurement: LevelId = -1 for all
        # 79)
        self.assertNotIn("level", node["params"])
        self.assertIn("host", node["params"])

    def test_curve_that_could_not_be_read_stays_an_honest_atom(self) -> None:
        """`curved_unsupported` is a refusal, not "a curve by default".

        The marker is set BEFORE the read attempt, so it means exactly one
        thing: capturing a straight line failed. Lifting such an instance by
        nonexistent endpoints would mean inventing geometry.
        """
        from kir.decompile.curtain_extract import CurveState

        element, placement_index = _family_element_and_index(16_801)
        placement_index["16801"].update({
            "placement_type": "CurveBased",
            "placement_available": False,
            "point_mm": None, "rotation_deg": None,
            "curve_state": CurveState.CURVED_UNSUPPORTED.value,
            "curve_p0_mm": None, "curve_p1_mm": None,
        })
        result = lift_document_detailed(
            _document([element]), family_placement_index=placement_index)
        self.assertEqual(result.nodes[0]["kind"], "atom")

    def test_generator_child_wins_over_every_other_refusal(self) -> None:
        """A generated child is a child, whatever its placement.

        MEASUREMENT of 27.07 (the electrical training model, SKLNK R2026):
        1738 family instances, of which 1659 nested and only 79
        freestanding. The lifter reported "395 refusals: place_family
        supports only unhosted OneLevelBased" — because the placement-kind
        check stood FIRST, and 316 nested instances with CurveBased placement
        got its label instead of `generator_child`.

        The cost of the error is not cosmetic: `generator_child` IS
        SUBTRACTED from honest coverage (the parent creates the child itself,
        it is not a separate hole), while `unsupported_signature` is not.
        Because of the check order, the electrical model's honest coverage
        was showing as 30.37% instead of 67.70%.

        The order of checks is a boundary just like a numeric limit, and it
        must equally not be set by reasoning: a refusal's reason must be the
        MOST CORRECT of the applicable ones, not the first one in the
        function's text.
        """
        for change in (
                {"placement_type": "CurveBased"},
                {"placement_type": "WorkPlaneBased"},
                {"placement_type": "TwoLevelsBased"},
                {"in_place": True},
                {"host_id": "wall-1", "host_class": "Wall"},
                {"placement_available": False, "point_mm": None,
                 "rotation_deg": None},
        ):
            with self.subTest(change=change):
                element, placement_index = _family_element_and_index(15_500)
                placement_index["15500"].update(change)
                placement_index["15500"]["super_component_id"] = "parent-9"
                result = lift_document_detailed(
                    _document([element]),
                    family_placement_index=placement_index,
                )
                self.assertEqual(
                    result.nodes[0]["reason"]["code"],
                    AtomReason.GENERATOR_CHILD.value,
                    f"{change}: вложенность обязана перебивать прочие отказы")

    def test_every_placement_refusal_is_typed_and_preserves_the_leaf(
            self) -> None:
        mutations = [
            ({"placement_type": "WorkPlaneBased"},
             AtomReason.UNSUPPORTED_SIGNATURE),
            ({"in_place": True}, AtomReason.UNSUPPORTED_SIGNATURE),
            ({"super_component_id": "parent-1"}, AtomReason.GENERATOR_CHILD),
            # Anchoring is NO LONGER a refusal (28.07): the op places
            # anchored families with the host overload. Exactly one refusal
            # remains, and it is honest — the host was not lifted, there is
            # nothing to place on: `wall-1` is absent from this document.
            ({"host_id": "wall-1", "host_class": "Wall"},
             AtomReason.MISSING_REFERENCE),
            ({"placement_available": False, "point_mm": None,
              "rotation_deg": None}, AtomReason.MISSING_GEOMETRY),
        ]
        for index, (change, reason) in enumerate(mutations):
            with self.subTest(change=change):
                element, placement_index = _family_element_and_index(
                    14_100 + index)
                placement_index[str(14_100 + index)].update(change)
                result = lift_document_detailed(
                    _document([element]),
                    family_placement_index=placement_index,
                )
                self.assertEqual(len(result.nodes), 1)
                self.assertEqual(result.nodes[0]["kind"], "atom")
                self.assertEqual(
                    result.nodes[0]["reason"]["code"], reason.value)
                self.assertEqual(result.diagnostics[0].reason, reason)

    def test_nested_shared_child_is_generated_accounted_in_verify(self) -> None:
        from kir.decompile.verify import verify_document
        from kir.decompile.fold import fold_document

        element, placement_index = _family_element_and_index()
        placement_index["14001"]["super_component_id"] = "parent-1"
        document = _document([element])
        nodes = lift_document(
            document, family_placement_index=placement_index)
        tree = fold_document(document, nodes)

        result = verify_document(document, tree, nodes)

        self.assertEqual(
            result.fidelity_verdicts[0].verdict.value, "generated_accounted")
        self.assertIn(
            "generator_child",
            [reason.value for reason in result.fidelity_verdicts[0].reasons],
        )

    def test_candidate_owned_category_is_never_intercepted(self) -> None:
        column = make_element("OST_StructuralColumns", 14_200, ordinal=0)
        family_element, placement_index = _family_element_and_index(14_200)
        placement_index["14200"]["symbol_id"] = column["type_id"]
        placement_index["14200"]["type_name"] = column["type_name"]
        # The index row is deliberately otherwise usable, but _CANDIDATES
        # remains authoritative for this category.
        del family_element

        node = lift_document(
            _document([column]),
            family_placement_index=placement_index,
        )[0]

        self.assertEqual(node["op_name"], "create_column")

    def test_family_lift_is_deterministic_across_hash_seeds(self) -> None:
        element, placement_index = _family_element_and_index()
        document_row = _document([element]).to_dict()
        script = textwrap.dedent(
            f"""
            import json
            from kir.decompile.lift import lift_document
            from kir.decompile.schema import L0Document
            document = L0Document.from_dict({document_row!r})
            index = {placement_index!r}
            print(json.dumps(
                lift_document(document, family_placement_index=index),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ))
            """
        )
        outputs = []
        for seed in ("19", "887"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            env["PYTHONPATH"] = str(BACKEND_ROOT)
            completed = subprocess.run(
                [str(PYTHON_EXECUTABLE), "-c", script],
                cwd=BACKEND_ROOT,
                env=env,
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(json.loads(outputs[0])[0]["op_name"], "place_family")


class HonestAtomAndTotalityTests(unittest.TestCase):
    def test_no_bbox_profile_approximation_for_floor_roof_or_stairs(self) -> None:
        rows = [
            make_element("OST_Floors", 9700, ordinal=0),
            make_element("OST_Roofs", 9701, ordinal=0),
            make_element("OST_Stairs", 9702, ordinal=0),
        ]
        # Even a plausible-looking arbitrary params key lacks frozen-schema
        # provenance and must not become a floor contour.
        rows[0]["params"]["profile_loops_mm"] = [[
            [0.0, 0.0], [5_000.0, 0.0],
            [5_000.0, 5_000.0], [0.0, 5_000.0],
        ]]

        document = _document(rows)
        result = lift_document_detailed(document)
        with_empty_index = lift_document_detailed(document, profile_index={})

        self.assertEqual(with_empty_index, result)
        self.assertTrue(all(node["kind"] == "atom" for node in result.nodes))
        self.assertTrue(all(
            item.reason is AtomReason.MISSING_GEOMETRY
            for item in result.diagnostics
        ))
        for node in result.nodes:
            self.assertIn("bbox_min_mm", node)
            self.assertNotIn("params", node)

    def test_beam_foundation_and_cable_tray_lift_under_ops_authority(
            self) -> None:
        rows = [
            make_element("OST_StructuralFraming", 9800, ordinal=0),
            make_element("OST_StructuralFoundation", 9801, ordinal=0),
            make_element("OST_CableTray", 9802, ordinal=0),
        ]

        result = lift_document_detailed(_document(rows))

        self.assertEqual(
            [node["op_name"] for node in result.nodes],
            ["create_beam", "create_foundation", "create_cable_tray"],
        )
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.nodes[1]["params"]["variety"], "isolated")
        self.assertIn("symbol", result.nodes[0]["params"])
        self.assertIn("symbol", result.nodes[1]["params"])
        self.assertIn("tray_type", result.nodes[2]["params"])
        self.assertNotIn("width_mm", result.nodes[2]["params"])
        self.assertNotIn("height_mm", result.nodes[2]["params"])

    def test_a_cable_tray_lifts_the_instance_section_when_present(self) -> None:
        row = make_element("OST_CableTray", 9805, ordinal=0)
        row["params"] = {
            "RBS_CABLETRAY_WIDTH_PARAM": 300.0,
            "RBS_CABLETRAY_HEIGHT_PARAM": 100.0,
        }

        result = lift_document_detailed(_document([row]))

        self.assertEqual(result.nodes[0]["op_name"], "create_cable_tray")
        self.assertEqual(result.nodes[0]["params"]["width_mm"], 300.0)
        self.assertEqual(result.nodes[0]["params"]["height_mm"], 100.0)

    def test_half_a_tray_section_lifts_as_half_not_as_an_atom(self) -> None:
        row = make_element("OST_CableTray", 9806, ordinal=0)
        row["params"] = {"RBS_CABLETRAY_WIDTH_PARAM": 300.0}

        result = lift_document_detailed(_document([row]))

        self.assertEqual(result.nodes[0]["op_name"], "create_cable_tray")
        self.assertEqual(result.nodes[0]["params"]["width_mm"], 300.0)
        self.assertNotIn("height_mm", result.nodes[0]["params"])

    def test_rotated_foundation_remains_an_honest_atom(self) -> None:
        row = make_element(
            "OST_StructuralFoundation", 9803, ordinal=1)

        result = lift_document_detailed(_document([row]))

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertEqual(
            result.nodes[0]["reason"]["code"],
            AtomReason.UNSUPPORTED_SIGNATURE.value,
        )

    def test_every_category_outside_table_is_an_atom(self) -> None:
        outside = [
            category for category in EXTRACT_CATEGORIES
            if category not in LIFTER_TABLE
        ]
        rows = [
            make_element(category, 99_000 + index, ordinal=0)
            for index, category in enumerate(outside)
        ]

        result = lift_document_detailed(_document(rows))

        self.assertEqual(len(result.nodes), len(outside))
        self.assertTrue(all(node["kind"] == "atom" for node in result.nodes))
        # TOTALITY has not changed: an element outside the lifter table must
        # still become an ATOM, not disappear. What changed is something
        # else — "outside the table" stopped being ONE reason.
        #
        # Since the wave of 29.07 there are TWO such reasons, and exactly one
        # question separates them: does an operation exist for the category.
        # No operation — `no_lifter`, and this is true (lines, spot
        # elevations, slopes, generic annotations). An operation exists, but
        # the reading does not carry its required inputs —
        # `source_contract_gap`: dimensions, tags and notes, whose
        # create_dimension / create_tag / create_text have been in the
        # registry since 28.07.
        #
        # Checking a single bare code here would mean demanding the WORST
        # diagnosis from the lift: "there is no operation" about an
        # operation that has, in fact, been written. So what is checked is
        # the RULE, not a constant — and this incidentally also catches a
        # discrepancy between the annotation table and the reading table.
        by_source = {
            element.element_id: element for element in _document(rows).elements}
        for item in result.diagnostics:
            category = by_source[item.source_element_id].category
            expected = (
                AtomReason.SOURCE_CONTRACT_GAP
                if category in _OPS_WITHOUT_L0_INPUTS
                else AtomReason.NO_LIFTER
            )
            with self.subTest(category=category):
                self.assertIs(item.reason, expected)

    def test_property_every_l0_element_yields_one_valid_stable_node(self) -> None:
        by_category = project1_elements(total=350)
        rows = [
            row
            for category in EXTRACT_CATEGORIES
            for row in by_category[category]
        ]
        document = _document(rows)

        first = lift_document(document)
        second = lift_document(document)

        self.assertEqual(len(first), len(document.elements))
        self.assertEqual(first, second)
        self.assertTrue(all(is_valid_l1_node(node) for node in first))
        self.assertEqual(
            [node["source_element_id"] for node in first],
            [element.element_id for element in document.elements],
        )
        self.assertEqual(
            len({node["source_element_id"] for node in first}),
            len(document.elements),
        )

        reversed_document = replace(
            document, elements=tuple(reversed(document.elements)))
        reversed_nodes = lift_document(reversed_document)
        self.assertEqual(
            {node["source_element_id"]: node["_id"] for node in first},
            {node["source_element_id"]: node["_id"] for node in reversed_nodes},
        )

    def test_malformed_nested_params_never_panic_or_drop_valid_l0(self) -> None:
        elements: list[L0Element] = []
        for index, category in enumerate(EXTRACT_CATEGORIES):
            row = make_element(category, 120_000 + index, ordinal=0)
            row["params"] = {
                "WALL_USER_HEIGHT_PARAM": object(),
                "RBS_PIPE_DIAMETER_PARAM": float("nan"),
                "RBS_CURVE_DIAMETER_PARAM": float("inf"),
            }
            elements.append(L0Element.from_dict(row))
        document = replace(
            _document([]),
            elements=tuple(elements),
        )

        nodes = lift_document(document)

        self.assertEqual(len(nodes), len(elements))
        self.assertTrue(all(is_valid_l1_node(node) for node in nodes))
        self.assertEqual(
            {node["source_element_id"] for node in nodes},
            {element.element_id for element in elements},
        )


class WallCurveArcLift(unittest.TestCase):
    """Curve-IR (P4-B): a wall lifts curved when — and only when — the canon
    location-curve side index (curve_extract.CurveExtraction) says so."""

    # A quarter fillet (r=325) whose plan endpoints are (325,0) and (0,325).
    # The canon curve-index row nests the six ArcCurve fields under "arc" and
    # carries the plane normal (x_axis × y_axis) — this is the exact shape the
    # live LOT31 curve_index.json emits for its 2371 arc walls.
    _ARC_ROW = {
        "curve_kind": "arc", "category": "OST_Walls",
        "p0_mm": [325.0, 0.0, 0.0], "p1_mm": [0.0, 325.0, 0.0],
        "arc": {
            "center_mm": [0.0, 0.0, 0.0], "radius_mm": 325.0,
            "x_axis": [1.0, 0.0, 0.0], "y_axis": [0.0, 1.0, 0.0],
            "start_angle_rad": 0.0, "end_angle_rad": math.pi / 2.0},
        "normal": [0.0, 0.0, 1.0],
    }

    def _wall(self, eid: int = 9200):
        # endpoints in the arc's plan plane (quarter fillet, r=325)
        row = make_element("OST_Walls", eid, ordinal=0)
        row["p0_mm"] = [325.0, 0.0, 0.0]
        row["p1_mm"] = [0.0, 325.0, 0.0]
        return L0Element.from_dict(row)

    def _extraction(self, eid: int, row: dict) -> CurveExtraction:
        # Build through the audited from_dict so tests exercise the real parser.
        return CurveExtraction.from_dict({
            "schema_version": CURVE_INDEX_SCHEMA_VERSION,
            "curve_index": {str(eid): row},
            "failures": [],
        })

    def _arc_extraction(self, eid: int = 9200):
        return self._extraction(eid, self._ARC_ROW)

    def test_no_side_index_lifts_straight_line(self):
        node = lift_element(self._wall())
        self.assertEqual(node["op_name"], "create_wall")
        self.assertNotIn("arc", node["params"])

    def test_arc_record_lifts_arc_param(self):
        node = lift_element(self._wall(), wall_curve_index=self._arc_extraction())
        self.assertIn("arc", node["params"])
        arc = node["params"]["arc"]
        self.assertEqual(arc["curve_type"], "Arc")
        self.assertEqual(arc["radius_mm"], 325.0)
        self.assertEqual(
            sorted(arc),
            ["center_mm", "curve_type", "end_angle_rad", "radius_mm",
             "start_angle_rad", "x_axis", "y_axis"])
        # The lifted op is a legal create_wall op (arc round-trips to emit).
        self.assertLessEqual(
            set(node["params"]),
            {param.name for param in spec.OPS["create_wall"].params})
        self.assertTrue(is_valid_l1_node(node))

    def test_persisted_envelope_is_accepted(self):
        node = lift_element(
            self._wall(),
            wall_curve_index=self._arc_extraction().to_dict())
        self.assertIn("arc", node["params"])

    def test_line_record_never_bends_the_wall(self):
        node = lift_element(self._wall(), wall_curve_index=self._extraction(
            9200, {"curve_kind": "line", "category": "OST_Walls",
                   "p0_mm": [325.0, 0.0, 0.0], "p1_mm": [0.0, 325.0, 0.0]}))
        self.assertNotIn("arc", node["params"])

    def test_spline_unsupported_stays_a_flat_wall(self):
        # An honest deferred spline is lifted as a straight wall — never an
        # invented arc, never a silently-tessellated fake.
        node = lift_element(self._wall(), wall_curve_index=self._extraction(
            9200, {"curve_kind": "spline_unsupported", "category": "OST_Walls",
                   "p0_mm": [325.0, 0.0, 0.0], "p1_mm": [0.0, 325.0, 0.0]}))
        self.assertEqual(node["op_name"], "create_wall")
        self.assertNotIn("arc", node["params"])

    def test_arc_record_class_used_directly(self):
        # CurveRecord is a real import (used as the canon record type) — a
        # smoke check that keeps the symbol honest and documents the shape.
        rec = CurveRecord.from_dict("9200", self._ARC_ROW)
        self.assertIs(rec.curve_kind, CurveKind.ARC)

    def test_mismatched_endpoints_refuse_the_arc(self):
        # A side entry whose arc endpoints do not match this wall's p0/p1 is a
        # stale/wrong record — it must never silently bend a different wall.
        row = make_element("OST_Walls", 9200, ordinal=0)
        row["p0_mm"] = [9999.0, 0.0, 0.0]
        row["p1_mm"] = [0.0, 325.0, 0.0]
        node = lift_element(
            L0Element.from_dict(row), wall_curve_index=self._arc_extraction())
        self.assertNotIn("arc", node["params"])

    def test_malformed_side_index_fails_closed(self):
        for bad in (123, "nope", {"records": "x"}):
            with self.subTest(bad=bad):
                node = lift_element(self._wall(), wall_curve_index=bad)
                self.assertNotIn("arc", node["params"])

    def test_absent_element_lifts_straight(self):
        # The wall is not in the side index at all -> straight line, no arc.
        node = lift_element(
            self._wall(eid=7777), wall_curve_index=self._arc_extraction(9200))
        self.assertNotIn("arc", node["params"])

    def test_arc_wall_round_trips_through_lift_and_document(self):
        # Full document path (order-independent lift) also carries the arc.
        document = _document([make_element("OST_Walls", 9200, ordinal=0)])
        # patch the element endpoints to the arc plan
        elements = [
            replace(el, p0_mm=(325.0, 0.0, 0.0), p1_mm=(0.0, 325.0, 0.0))
            for el in document.elements]
        document = replace(document, elements=tuple(elements))
        nodes = lift_document(document, wall_curve_index=self._arc_extraction())
        self.assertEqual(nodes[0]["op_name"], "create_wall")
        self.assertIn("arc", nodes[0]["params"])


if __name__ == "__main__":
    unittest.main()
