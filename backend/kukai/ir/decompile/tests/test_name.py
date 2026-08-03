from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from typing import Any

from kukai.ir.decompile.fold import TreeNode, fold_document
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.name import (
    ContourError,
    label_tree,
    name_document,
    shape_of,
)
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


RECTANGLE = [
    [0.0, 0.0], [12_000.0, 0.0],
    [12_000.0, 8_000.0], [0.0, 8_000.0],
]
L_OUTLINE = [
    [0.0, 0.0], [12_000.0, 0.0], [12_000.0, 4_000.0],
    [4_000.0, 4_000.0], [4_000.0, 10_000.0], [0.0, 10_000.0],
]
T_OUTLINE = [
    [0.0, 0.0], [12_000.0, 0.0], [12_000.0, 4_000.0],
    [7_000.0, 4_000.0], [7_000.0, 12_000.0],
    [5_000.0, 12_000.0], [5_000.0, 4_000.0], [0.0, 4_000.0],
]
U_OUTLINE = [
    [0.0, 0.0], [0.0, 12_000.0], [4_000.0, 12_000.0],
    [4_000.0, 5_000.0], [8_000.0, 5_000.0],
    [8_000.0, 12_000.0], [12_000.0, 12_000.0], [12_000.0, 0.0],
]


def _polygon_area_m2(points: list[list[float]]) -> float:
    area2 = sum(
        point[0] * points[(index + 1) % len(points)][1]
        - points[(index + 1) % len(points)][0] * point[1]
        for index, point in enumerate(points)
    )
    return abs(area2) / 2.0 / 1_000_000.0


def _l_building_document() -> L0Document:
    levels = [
        (str(100 + index), f"Этаж {index + 1}", float(index * 3_000))
        for index in range(5)
    ]
    rooms: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    for index, (level_id, level_name, elevation) in enumerate(levels):
        room_id = str(50_000 + index)
        rooms.append({
            "id": room_id,
            "name": "Гостиная",
            "level_id": level_id,
            "level_name": level_name,
            "area_m2": _polygon_area_m2(L_OUTLINE),
            "boundary_mm": copy.deepcopy(L_OUTLINE),
            "boundary_loops_mm": [copy.deepcopy(L_OUTLINE)],
            "bounding_element_ids": [],
        })
        room = make_element("OST_Rooms", int(room_id), ordinal=index)
        room.update({
            "level_id": level_id,
            "level_name": level_name,
            "bbox_min_mm": [0.0, 0.0, elevation],
            "bbox_max_mm": [12_000.0, 10_000.0, elevation + 2_800.0],
        })
        elements.append(room)

    # A deliberately tall bbox is not enough to call this atom roof pitched.
    roof = make_element("OST_Roofs", 59_000, ordinal=4)
    roof.update({
        "level_id": levels[-1][0],
        "level_name": levels[-1][1],
        "bbox_min_mm": [0.0, 0.0, 15_000.0],
        "bbox_max_mm": [12_000.0, 10_000.0, 17_000.0],
    })
    elements.append(roof)

    metadata = project1_metadata()
    metadata.update({
        "doc_name": "Г-образный жилой дом — synthetic",
        "change_stamp": "wave-d-l-building-v1",
        "levels": [
            {"id": level_id, "name": name, "elevation_mm": elevation}
            for level_id, name, elevation in levels
        ],
        "grids": [],
        "rooms": rooms,
        "elements": elements,
        "category_status": [],
        "links": [],
    })
    return L0Document.from_dict(metadata)


def _facts(area_m2: float | None = None) -> dict[str, Any]:
    return {
        "bbox_min_mm": None,
        "bbox_max_mm": None,
        "shape": None,
        "dims_mm": None,
        "area_m2": area_m2,
        "element_count": 0,
        "op_histogram": {},
    }


def _node(
    node_id: str,
    kind: str,
    *,
    label: str = "",
    children: list[TreeNode] | None = None,
    macro: dict[str, Any] | None = None,
    area_m2: float | None = None,
) -> TreeNode:
    return {
        "node_id": node_id,
        "kind": kind,
        "label": label,
        "children": children or [],
        "payload": None,
        "members": [],
        "macro": macro,
        "facts": _facts(area_m2),
        "verdict": None,
    }


def _label_tree_fixture() -> tuple[L0Document, TreeNode]:
    def apartment(suffix: str) -> TreeNode:
        return _node(
            f"apartment-{suffix}",
            "apartment",
            children=[
                _node(
                    f"living-{suffix}", "room",
                    label="Гостиная", area_m2=30.0),
                _node(
                    f"bedroom-{suffix}", "room",
                    label="Спальня", area_m2=24.0),
            ],
        )

    floor_two = _node(
        "floor-2",
        "floor",
        label="Этаж 2",
        children=[apartment("2"), _node("core-2", "core")],
        macro={"type": "floor", "level_name": "Этаж 2", "elevation_mm": 3_000.0},
    )
    floor_three = _node(
        "floor-3",
        "floor",
        label="Этаж 3",
        children=[apartment("3"), _node("core-3", "core")],
        macro={"type": "floor", "level_name": "Этаж 3", "elevation_mm": 6_000.0},
    )
    tree = _node(
        "building",
        "building",
        children=[_node(
            "stack-2-3",
            "stack",
            children=[floor_two, floor_three],
            macro={
                "type": "stack",
                "levels": ["Этаж 2", "Этаж 3"],
                "base_z_mm": 3_000.0,
                "dz_mm": 3_000.0,
                "template_node_id": "floor-2",
                "diffs": {},
            },
        )],
        macro={"type": "building"},
    )
    metadata = project1_metadata()
    metadata.update({
        "doc_name": "labels-synthetic",
        "change_stamp": "wave-d-labels-v1",
        "levels": [
            {"id": "2", "name": "Этаж 2", "elevation_mm": 3_000.0},
            {"id": "3", "name": "Этаж 3", "elevation_mm": 6_000.0},
        ],
        "grids": [],
        "rooms": [],
        "elements": [],
        "category_status": [],
        "links": [],
    })
    return L0Document.from_dict(metadata), tree


def _walk(node: TreeNode) -> list[TreeNode]:
    return [node] + [descendant for child in node["children"]
                     for descendant in _walk(child)]


def seeded_name_payload() -> str:
    """Subprocess entry used to prove hash-seed-independent bytes."""

    document = _l_building_document()
    tree = fold_document(document, lift_document(document))
    result = name_document(document, tree, L_OUTLINE)
    return json.dumps(
        result,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class ShapeClassificationTests(unittest.TestCase):
    def test_rectangle_and_near_collinear_vertex(self) -> None:
        with_extra_vertex = [
            [0.0, 0.0], [6_000.0, 10.0], [12_000.0, 0.0],
            [12_000.0, 8_000.0], [0.0, 8_000.0], [0.0, 0.0],
        ]

        result = shape_of(with_extra_vertex)

        self.assertEqual(result["shape"], "rectangle")
        self.assertEqual(result["corners"], 4)
        self.assertEqual(result["dims_mm"], [12_000.0, 8_000.0])
        self.assertTrue(result["convex"])

    def test_non_right_quadrilateral_is_never_called_rectangle(self) -> None:
        trapezoid = [
            [0.0, 0.0], [12_000.0, 0.0],
            [10_000.0, 8_000.0], [0.0, 8_000.0],
        ]

        result = shape_of(trapezoid)

        self.assertEqual(result["shape"], "complex")
        self.assertNotEqual(result["description"], "complex")
        self.assertIn("4 угла", result["description"])

    def test_l_t_and_u_topologies(self) -> None:
        self.assertEqual(shape_of(L_OUTLINE)["shape"], "L")
        self.assertEqual(shape_of(T_OUTLINE)["shape"], "T")
        self.assertEqual(shape_of(U_OUTLINE)["shape"], "U")

    def test_unrecognized_complex_shape_keeps_rich_facts(self) -> None:
        contour = [
            [0.0, 0.0], [10_000.0, 0.0], [12_000.0, 4_000.0],
            [6_000.0, 10_000.0], [0.0, 6_000.0],
        ]

        result = shape_of(contour)

        self.assertEqual(result["shape"], "complex")
        self.assertEqual(result["corners"], 5)
        self.assertEqual(result["aspect"], 1.2)
        self.assertTrue(result["convex"])
        self.assertIsInstance(result["area_m2"], float)
        self.assertIn("сложный контур", result["description"])

    def test_typed_arc_flags_curvilinear_and_blocks_rectangle(self) -> None:
        contour = {
            "outer": {
                "segments": [
                    {"kind": "line", "p0_mm": [0.0, 0.0],
                     "p1_mm": [12_000.0, 0.0]},
                    {"kind": "arc", "p0_mm": [12_000.0, 0.0],
                     "p1_mm": [12_000.0, 8_000.0]},
                    {"kind": "line", "p0_mm": [12_000.0, 8_000.0],
                     "p1_mm": [0.0, 8_000.0]},
                    {"kind": "line", "p0_mm": [0.0, 8_000.0],
                     "p1_mm": [0.0, 0.0]},
                ],
            },
        }

        result = shape_of(contour)

        self.assertEqual(result["shape"], "complex")
        self.assertTrue(result["curvilinear_perimeter"])
        self.assertFalse(result["convex"])
        self.assertIsNone(result["dims_mm"])
        self.assertIsNone(result["area_m2"])
        self.assertIn("криволинейный периметр", result["description"])

    def test_inner_loop_is_courtyard_and_blocks_rectangle(self) -> None:
        courtyard = [
            [3_000.0, 2_000.0], [9_000.0, 2_000.0],
            [9_000.0, 6_000.0], [3_000.0, 6_000.0],
        ]

        result = shape_of({"outer": RECTANGLE, "holes": [courtyard]})

        self.assertEqual(result["shape"], "complex")
        self.assertTrue(result["courtyard"])
        self.assertFalse(result["convex"])
        self.assertAlmostEqual(result["area_m2"], 72.0)
        self.assertIn("с внутренним двором", result["description"])

    def test_degenerate_is_unknown_and_malformed_explicit_data_refuses(self) -> None:
        self.assertEqual(shape_of([])["shape"], "unknown")
        with self.assertRaises(ContourError):
            shape_of([[0.0, 0.0], [float("nan"), 1.0], [2.0, 0.0]])


class NameIntegrationTests(unittest.TestCase):
    def test_l_shaped_five_storey_fixture_renders_required_gestalt(self) -> None:
        document = _l_building_document()
        folded = fold_document(document, lift_document(document))
        original = copy.deepcopy(folded)

        result = name_document(document, folded, L_OUTLINE)

        self.assertEqual(result["shape"]["shape"], "L")
        self.assertIn("Г-образное здание", result["gestalt"])
        self.assertIn("5 этажей", result["gestalt"])
        self.assertIn("по 3 м", result["gestalt"])
        self.assertIn("Назначение: жилой дом", result["gestalt"])
        self.assertIn("кровля не определена", result["gestalt"])
        self.assertNotIn("прямоуголь", result["gestalt"].casefold())
        self.assertEqual(result["tree"]["facts"]["shape"], "L")
        self.assertEqual(folded, original, "NAME must not mutate FOLD's L3 tree")

    def test_missing_frozen_profile_stays_unknown_not_bbox_rectangle(self) -> None:
        document = _l_building_document()
        folded = fold_document(document, lift_document(document))

        result = name_document(document, folded)

        self.assertEqual(result["shape"]["shape"], "unknown")
        self.assertIn("контур не определён", result["gestalt"])
        self.assertIsNone(result["tree"]["facts"]["shape"])

    def test_fact_template_node_labels(self) -> None:
        document, tree = _label_tree_fixture()

        named = label_tree(tree, document)
        labels = {node["node_id"]: node["label"] for node in _walk(named)}

        self.assertEqual(
            labels["floor-2"], "Этаж 2 (типовой, =2-3)")
        self.assertEqual(
            labels["apartment-2"], "Квартира 2-комн. 54 м²")
        self.assertEqual(labels["core-2"], "Лестнично-лифтовой узел")
        self.assertEqual(labels["living-2"], "Гостиная")
        apartment = next(
            node for node in _walk(named) if node["node_id"] == "apartment-2")
        self.assertEqual(apartment["facts"]["area_m2"], 54.0)

    def test_typical_floor_summary_uses_geometry_room_counts_and_areas(self) -> None:
        document, tree = _label_tree_fixture()

        result = name_document(document, tree, RECTANGLE)

        self.assertIn(
            "Типовой этаж: 1 кв. (2-комн. 54 м²), 1 ЛК.",
            result["gestalt"],
        )

    def test_purpose_thresholds_use_all_non_mop_room_names(self) -> None:
        base_document, tree = _label_tree_fixture()
        cases = {
            "residential": (
                ["Гостиная", "Спальня", "Кухня", "Офис"],
                "Назначение: жилой дом.",
            ),
            "office": (
                ["Офис", "Кабинет", "Переговорная", "Спальня"],
                "Назначение: офис.",
            ),
            "mixed": (
                ["Гостиная", "Спальня", "Офис", "Кабинет"],
                "Назначение: многофункциональное.",
            ),
            "unknown_dominates": (
                ["Спальня", "Склад 1", "Склад 2", "Склад 3"],
                "Назначение: не определено.",
            ),
        }
        for case_name, (names, expected) in cases.items():
            with self.subTest(case_name):
                payload = base_document.to_dict()
                payload["rooms"] = [{
                    "id": str(70_000 + index),
                    "name": name,
                    "level_id": "2",
                    "level_name": "Этаж 2",
                    "area_m2": 0.0,
                    "boundary_mm": [],
                    "boundary_loops_mm": [],
                    "bounding_element_ids": [],
                } for index, name in enumerate(names)]
                document = L0Document.from_dict(payload)

                result = name_document(document, tree, RECTANGLE)

                self.assertIn(expected, result["gestalt"])

    def test_llm_callback_is_never_called_when_flag_is_off(self) -> None:
        document = _l_building_document()
        folded = fold_document(document, lift_document(document))
        calls: list[tuple[Any, ...]] = []

        def forbidden(*args: Any) -> str:
            calls.append(args)
            raise AssertionError("LLM decorator must not run")

        first = name_document(
            document,
            folded,
            L_OUTLINE,
            llm_labeler=forbidden,
        )
        second = name_document(
            document,
            folded,
            L_OUTLINE,
            use_llm_labels=False,
            llm_labeler=forbidden,
        )

        self.assertEqual(calls, [])
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
        )

    def test_output_bytes_are_stable_across_python_hash_seeds(self) -> None:
        backend_root = Path(__file__).resolve().parents[4]
        code = (
            "from kukai.ir.decompile.tests.test_name import seeded_name_payload;"
            "print(seeded_name_payload())"
        )
        outputs = []
        for seed in ("1", "8675309"):
            environment = os.environ.copy()
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONPATH"] = str(backend_root)
            outputs.append(subprocess.check_output(
                [sys.executable, "-c", code],
                env=environment,
            ))

        self.assertEqual(outputs[0], outputs[1])


if __name__ == "__main__":
    unittest.main()
