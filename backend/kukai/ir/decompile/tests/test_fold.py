from __future__ import annotations

import copy
import math
import random
import unittest
from typing import Any, Iterable

from kukai.ir.decompile.fold import (
    FIDELITY_CANON_VERSION,
    TEMPLATE_CANON_VERSION,
    _MOP_RE,
    FidelityCanon,
    FoldError,
    TemplateCanon,
    TreeNode,
    _round_mm,
    assert_preservation,
    canon_hash,
    canon_op,
    fold_document,
    iter_l1_leaves,
    multiset_hash,
)
from kukai.ir.decompile.component import _translate_leaf
from kukai.ir.decompile.group_extract import GroupExtraction
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.schema import CANON_MM, L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)
from kukai.ir.contour import bulge_midpoint, radius_to_bulge


def _document(
    levels: list[tuple[str, str, float]],
    elements: list[dict[str, Any]],
    *,
    rooms: list[dict[str, Any]] | None = None,
    name: str = "fold-synthetic",
) -> L0Document:
    metadata = project1_metadata()
    metadata.update({
        "doc_name": name,
        "change_stamp": "synthetic-fold-v1",
        "levels": [
            {"id": level_id, "name": level_name, "elevation_mm": elevation}
            for level_id, level_name, elevation in levels
        ],
        "grids": [],
        "rooms": copy.deepcopy(rooms or []),
        "elements": copy.deepcopy(elements),
        "category_status": [],
        "links": [],
    })
    return L0Document.from_dict(metadata)


def _on_level(
    row: dict[str, Any],
    level: tuple[str, str, float],
) -> dict[str, Any]:
    level_id, level_name, _elevation = level
    row["level_id"] = level_id
    row["level_name"] = level_name
    return row


def _point_element(
    category: str,
    element_id: int,
    level: tuple[str, str, float],
    point: tuple[float, float, float],
    *,
    type_name: str | None = None,
) -> dict[str, Any]:
    row = _on_level(make_element(category, element_id, ordinal=0), level)
    row.update({
        "geom_kind": "point",
        "p0_mm": list(point),
        "p1_mm": None,
        "rotation_deg": 0.0,
        "bbox_min_mm": [point[0] - 100.0, point[1] - 100.0, point[2]],
        "bbox_max_mm": [point[0] + 100.0, point[1] + 100.0, point[2] + 300.0],
    })
    if type_name is not None:
        row["type_name"] = type_name
    return row


def _curve_element(
    category: str,
    element_id: int,
    level: tuple[str, str, float],
    p0: tuple[float, float, float],
    p1: tuple[float, float, float],
) -> dict[str, Any]:
    row = _on_level(make_element(category, element_id, ordinal=0), level)
    row.update({
        "geom_kind": "curve",
        "p0_mm": list(p0),
        "p1_mm": list(p1),
        "rotation_deg": None,
        "bbox_min_mm": [
            min(p0[0], p1[0]), min(p0[1], p1[1]), min(p0[2], p1[2]),
        ],
        "bbox_max_mm": [
            max(p0[0], p1[0]), max(p0[1], p1[1]),
            max(p0[2], p1[2]) + 2_800.0,
        ],
    })
    if category == "OST_Walls":
        row["params"] = {"WALL_USER_HEIGHT_PARAM": 2_800.0}
    return row


def _walk(node: TreeNode) -> Iterable[TreeNode]:
    yield node
    for child in node["children"]:
        yield from _walk(child)


def _kind(tree: TreeNode, kind: str) -> list[TreeNode]:
    return [node for node in _walk(tree) if node["kind"] == kind]


def _room(
    room_id: int,
    name: str,
    level: tuple[str, str, float],
    boundary: list[list[float]],
    boundary_ids: list[str],
) -> dict[str, Any]:
    width = max(point[0] for point in boundary) - min(
        point[0] for point in boundary)
    depth = max(point[1] for point in boundary) - min(
        point[1] for point in boundary)
    return {
        "id": str(room_id),
        "name": name,
        "level_id": level[0],
        "level_name": level[1],
        "area_m2": width * depth / 1_000_000.0,
        "boundary_mm": copy.deepcopy(boundary),
        "boundary_loops_mm": [copy.deepcopy(boundary)],
        "bounding_element_ids": boundary_ids,
    }


def _groups(*rows: tuple[str, str, list[str]]) -> GroupExtraction:
    return GroupExtraction.from_rows([
        {
            "element_id": instance_id,
            "group_type_id": type_id,
            "group_type_name": f"Group type {type_id}",
            "member_ids": members,
            "group_id_parent": None,
            "attached_detail_type_count": 0,
            "status": "ok",
        }
        for instance_id, type_id, members in rows
    ])


def _apartment_document(*, entrances: int) -> L0Document:
    level = ("10", "Level 1", 0.0)
    entry_walls = [
        _curve_element(
            "OST_Walls", 30_001 + index, level,
            (0.0, 0.0 + index * 200.0, 0.0),
            (0.0, 2_000.0 + index * 200.0, 0.0),
        )
        for index in range(entrances)
    ]
    internal_wall = _curve_element(
        "OST_Walls", 30_010, level,
        (0.0, 2_000.0, 0.0), (4_000.0, 2_000.0, 0.0))
    doors: list[dict[str, Any]] = []
    for index, wall in enumerate(entry_walls):
        door = _point_element(
            "OST_Doors", 30_100 + index, level,
            (0.0, 1_000.0 + index * 200.0, 0.0))
        door["host_id"] = wall["element_id"]
        doors.append(door)
    internal_door = _point_element(
        "OST_Doors", 30_110, level, (2_000.0, 2_000.0, 0.0))
    internal_door["host_id"] = internal_wall["element_id"]
    rooms = [
        _room(
            31_001, "Коридор", level,
            [[-2_000.0, 0.0], [0.0, 0.0],
             [0.0, 2_000.0], [-2_000.0, 2_000.0]],
            [wall["element_id"] for wall in entry_walls],
        ),
        _room(
            31_002, "Living", level,
            [[0.0, 0.0], [4_000.0, 0.0],
             [4_000.0, 2_000.0], [0.0, 2_000.0]],
            [wall["element_id"] for wall in entry_walls]
            + [internal_wall["element_id"]],
        ),
        _room(
            31_003, "Bedroom", level,
            [[0.0, 2_000.0], [4_000.0, 2_000.0],
             [4_000.0, 4_000.0], [0.0, 4_000.0]],
            [internal_wall["element_id"]],
        ),
    ]
    room_elements = [
        _on_level(make_element("OST_Rooms", int(room["id"]), ordinal=0), level)
        for room in rooms
    ]
    return _document(
        [level],
        entry_walls + [internal_wall] + doors + [internal_door] + room_elements,
        rooms=rooms,
        name=f"apartment-{entrances}-entries",
    )


class CanonicalizationTests(unittest.TestCase):
    def test_coordinates_localize_ids_strip_and_multiset_is_order_independent(
            self) -> None:
        levels = [("1", "L1", 0.0), ("2", "L2", 3_000.0)]
        rows = [
            _point_element(
                "OST_StructuralColumns", 10_001, levels[0],
                (2_000.4, 4_000.4, 0.4)),
            _point_element(
                "OST_StructuralColumns", 10_002, levels[1],
                (2_000.49, 4_000.49, 3_000.49)),
        ]
        document = _document(levels, rows)
        first, second = lift_document(document)

        self.assertEqual(
            canon_op(first, (0.0, 0.0, 0.0)),
            canon_op(second, (0.0, 0.0, 3_000.0)),
        )
        canonical = canon_op(first, (0.0, 0.0, 0.0))
        self.assertNotIn(first["_id"], canonical)
        self.assertNotIn(first["source_element_id"], canonical)
        self.assertEqual(
            multiset_hash([first, second], (0.0, 0.0, 0.0)),
            multiset_hash([second, first], (0.0, 0.0, 0.0)),
        )

    def test_recursive_canonical_hash_ignores_source_order(self) -> None:
        level = ("1", "L1", 0.0)
        rows = [
            _point_element(
                "OST_StructuralColumns", 10_010 + index, level,
                (float(index * 1_000), 0.0, 0.0))
            for index in range(4)
        ]
        document = _document([level], rows)
        nodes = lift_document(document)
        first = fold_document(document, nodes)
        second = fold_document(document, reversed(nodes))

        self.assertEqual(first, second)
        self.assertEqual(
            canon_hash(first, (0.0, 0.0, 0.0)),
            canon_hash(second, (0.0, 0.0, 0.0)),
        )


class VerticalFoldTests(unittest.TestCase):
    def test_five_identical_floors_become_one_stack(self) -> None:
        levels = [
            (str(index + 1), f"L{index + 1}", float(index * 3_000))
            for index in range(5)
        ]
        rows = [
            _point_element(
                "OST_StructuralColumns", 11_000 + index, level,
                (2_000.0, 2_000.0, level[2]))
            for index, level in enumerate(levels)
        ]
        document = _document(levels, rows)
        nodes = lift_document(document)

        tree = fold_document(document, nodes)

        self.assertEqual(len(tree["children"]), 1)
        stack = tree["children"][0]
        self.assertEqual(stack["kind"], "stack")
        self.assertEqual(stack["macro"]["type"], "stack")
        self.assertEqual(len(stack["macro"]["levels"]), 5)
        self.assertEqual(stack["macro"]["dz_mm"], 3_000.0)
        self.assertEqual(len(stack["children"]), 5)
        assert_preservation(tree, nodes)

    def test_near_match_bootstraps_without_any_exact_floor_pair(self) -> None:
        levels = [
            (str(index + 1), f"L{index + 1}", float(index * 3_000))
            for index in range(3)
        ]
        rows: list[dict[str, Any]] = []
        next_id = 12_000
        for floor_index, level in enumerate(levels):
            for column_index in range(20):
                rows.append(_point_element(
                    "OST_StructuralColumns", next_id, level,
                    (float(column_index * 1_000), 0.0, level[2])))
                next_id += 1
            if floor_index:
                rows.append(_point_element(
                    "OST_StructuralColumns", next_id, level,
                    (50_000.0 + floor_index * 2_000.0, 7_000.0, level[2])))
                next_id += 1
        document = _document(levels, rows)
        nodes = lift_document(document)

        tree = fold_document(document, nodes)

        self.assertEqual(len(tree["children"]), 1)
        stack = tree["children"][0]
        self.assertEqual(stack["kind"], "stack")
        self.assertEqual(len(stack["macro"]["levels"]), 3)
        self.assertEqual(set(stack["macro"]["diffs"]), {"L2", "L3"})
        self.assertEqual(
            [len(diff["added"]) for diff in stack["macro"]["diffs"].values()],
            [1, 1],
        )
        assert_preservation(tree, nodes)

    def test_exact_repeat_at_irregular_elevations_uses_repeat_on_levels(
            self) -> None:
        levels = [("1", "L1", 0.0), ("2", "L2", 3_000.0),
                  ("3", "L3", 7_500.0)]
        rows = [
            _point_element(
                "OST_StructuralColumns", 12_500 + index, level,
                (0.0, 0.0, level[2]))
            for index, level in enumerate(levels)
        ]
        document = _document(levels, rows)

        stack = fold_document(document, lift_document(document))["children"][0]

        self.assertEqual(stack["macro"]["type"], "repeat_on_levels")
        self.assertNotIn("dz_mm", stack["macro"])


class HorizontalFoldTests(unittest.TestCase):
    def test_four_by_four_jittered_columns_form_relative_tolerance_grid(
            self) -> None:
        level = ("1", "L1", 0.0)
        xs = [0.0, 1_005.0, 1_995.0, 3_000.0]
        ys = [0.0, 1_200.0, 2_400.0, 3_600.0]
        rows = [
            _point_element(
                "OST_StructuralColumns", 13_000 + y_index * 4 + x_index,
                level, (x, y, 0.0))
            for y_index, y in enumerate(ys)
            for x_index, x in enumerate(xs)
        ]
        document = _document([level], rows)

        tree = fold_document(document, lift_document(document))

        grids = _kind(tree, "grid_array")
        self.assertEqual(len(grids), 1)
        self.assertEqual(grids[0]["macro"]["nx"], 4)
        self.assertEqual(grids[0]["macro"]["ny"], 4)
        self.assertEqual(grids[0]["macro"]["coverage"], 1.0)
        self.assertEqual(len(grids[0]["members"]), 16)

    def test_three_axis_aligned_ops_form_a_row(self) -> None:
        level = ("1", "L1", 0.0)
        rows = [
            _point_element(
                "OST_StructuralColumns", 13_100 + index, level,
                (float(index * 1_000), 100.0, 0.0))
            for index in range(3)
        ]
        document = _document([level], rows)

        tree = fold_document(document, lift_document(document))

        row_nodes = _kind(tree, "row")
        self.assertEqual(len(row_nodes), 1)
        self.assertEqual(row_nodes[0]["macro"]["n"], 3)
        self.assertEqual(row_nodes[0]["macro"]["axis"], "x")

    def test_group_boundaries_block_cross_group_rows_but_allow_inner_rows(
            self) -> None:
        level = ("1", "L1", 0.0)
        rows = [
            _point_element(
                "OST_StructuralColumns", 13_200 + index, level,
                (float(index * 1_000), 100.0, 0.0))
            for index in range(4)
        ]
        document = _document([level], rows)
        nodes = lift_document(document)
        split_groups = _groups(
            ("700", "800", ["13200", "13201"]),
            ("701", "800", ["13202", "13203"]),
        )

        legacy = fold_document(document, nodes)
        explicit_none = fold_document(document, nodes, group_index=None)
        guarded = fold_document(
            document, nodes, group_index=split_groups)

        self.assertEqual(legacy, explicit_none)
        self.assertEqual(len(_kind(legacy, "row")), 1)
        self.assertEqual(_kind(guarded, "row"), [])
        self.assertEqual(
            {leaf["source_element_id"] for leaf in iter_l1_leaves(guarded)},
            {"13200", "13201", "13202", "13203"},
        )

        inner_group = _groups(
            ("702", "801", ["13200", "13201", "13202"]),
        )
        inner_guarded = fold_document(
            document, nodes, group_index=inner_group)
        rows_inside = _kind(inner_guarded, "row")
        self.assertEqual(len(rows_inside), 1)
        self.assertEqual(
            {member["source_element_id"] for member in rows_inside[0]["members"]},
            {"13200", "13201", "13202"},
        )

    def test_grid_array_candidates_are_partitioned_by_group_instance(
            self) -> None:
        level = ("1", "L1", 0.0)
        rows = [
            _point_element(
                "OST_StructuralColumns",
                13_300 + y_index * 4 + x_index,
                level,
                (float(x_index * 1_000), float(y_index * 1_000), 0.0),
            )
            for y_index in range(4)
            for x_index in range(4)
        ]
        document = _document([level], rows)
        nodes = lift_document(document)
        checkerboard = ([], [])
        for y_index in range(4):
            for x_index in range(4):
                checkerboard[(x_index + y_index) % 2].append(
                    str(13_300 + y_index * 4 + x_index))
        groups = _groups(
            ("720", "820", checkerboard[0]),
            ("721", "820", checkerboard[1]),
        )

        unguarded = fold_document(document, nodes)
        guarded = fold_document(document, nodes, group_index=groups)

        self.assertEqual(len(_kind(unguarded, "grid_array")), 1)
        self.assertEqual(_kind(guarded, "grid_array"), [])
        self.assertEqual(len(list(iter_l1_leaves(guarded))), 16)


class SemanticFoldTests(unittest.TestCase):
    def test_two_rooms_behind_exactly_one_mop_door_form_apartment(self) -> None:
        document = _apartment_document(entrances=1)
        nodes = lift_document(document)

        tree = fold_document(document, nodes)

        apartments = _kind(tree, "apartment")
        self.assertEqual(len(apartments), 1)
        room_labels = {
            node["label"] for node in _walk(apartments[0])
            if node["kind"] == "room"
        }
        self.assertEqual(room_labels, {"Living", "Bedroom"})
        self.assertEqual(len(_kind(tree, "mop")), 1)
        assert_preservation(tree, nodes)

    def test_two_mop_entrance_doors_do_not_group_apartment(self) -> None:
        document = _apartment_document(entrances=2)

        tree = fold_document(document, lift_document(document))

        self.assertEqual(_kind(tree, "apartment"), [])
        loose_rooms = {
            node["label"] for node in _kind(tree, "room")
        }
        self.assertTrue({"Living", "Bedroom"} <= loose_rooms)

    def test_stair_presence_promotes_mop_component_to_core(self) -> None:
        document = _apartment_document(entrances=1)
        level = ("10", "Level 1", 0.0)
        stair = _on_level(make_element("OST_Stairs", 31_500, ordinal=0), level)
        stair["bbox_min_mm"] = [-1_500.0, 500.0, 0.0]
        stair["bbox_max_mm"] = [-500.0, 1_500.0, 3_000.0]
        document = _document(
            [level],
            [element.to_dict() for element in document.elements] + [stair],
            rooms=[room.to_dict() for room in document.rooms],
        )

        tree = fold_document(document, lift_document(document))

        self.assertEqual(len(_kind(tree, "core")), 1)
        self.assertEqual(_kind(tree, "mop"), [])

    def test_mop_classifier_is_multilingual(self) -> None:
        # English/international MOP terms must match, same as the Russian
        # ones — decompile must not be Russian-only (universality invariant).
        mop_names = (
            "Corridor", "corridor 3", "Stairwell", "Stair Hall",
            "Lobby", "Main Lobby", "Elevator Lobby", "Lift Hall",
            "Vestibule", "Foyer", "Entrance Hall", "Utility Room",
            "Mechanical Room", "Electrical Closet", "Riser Shaft",
        )
        for name in mop_names:
            self.assertTrue(
                _MOP_RE.search(name), f"expected MOP match for {name!r}")

        non_mop_names = (
            "Apartment 12", "Living Room", "Living", "Bedroom",
            "Kitchen", "Master Bedroom", "Dining Room",
        )
        for name in non_mop_names:
            self.assertFalse(
                _MOP_RE.search(name), f"unexpected MOP match for {name!r}")

    def test_apartment_grouping_works_with_english_room_names(self) -> None:
        level = ("10", "Level 1", 0.0)
        entry_wall = _curve_element(
            "OST_Walls", 32_001, level,
            (0.0, 0.0, 0.0), (0.0, 2_000.0, 0.0))
        internal_wall = _curve_element(
            "OST_Walls", 32_010, level,
            (0.0, 2_000.0, 0.0), (4_000.0, 2_000.0, 0.0))
        entry_door = _point_element(
            "OST_Doors", 32_100, level, (0.0, 1_000.0, 0.0))
        entry_door["host_id"] = entry_wall["element_id"]
        internal_door = _point_element(
            "OST_Doors", 32_110, level, (2_000.0, 2_000.0, 0.0))
        internal_door["host_id"] = internal_wall["element_id"]
        rooms = [
            _room(
                33_001, "Corridor", level,
                [[-2_000.0, 0.0], [0.0, 0.0],
                 [0.0, 2_000.0], [-2_000.0, 2_000.0]],
                [entry_wall["element_id"]],
            ),
            _room(
                33_002, "Living Room", level,
                [[0.0, 0.0], [4_000.0, 0.0],
                 [4_000.0, 2_000.0], [0.0, 2_000.0]],
                [entry_wall["element_id"], internal_wall["element_id"]],
            ),
            _room(
                33_003, "Bedroom", level,
                [[0.0, 2_000.0], [4_000.0, 2_000.0],
                 [4_000.0, 4_000.0], [0.0, 4_000.0]],
                [internal_wall["element_id"]],
            ),
        ]
        room_elements = [
            _on_level(make_element("OST_Rooms", int(room["id"]), ordinal=0), level)
            for room in rooms
        ]
        document = _document(
            [level],
            [entry_wall, internal_wall, entry_door, internal_door]
            + room_elements,
            rooms=rooms,
            name="apartment-english-1-entry",
        )
        nodes = lift_document(document)

        tree = fold_document(document, nodes)

        apartments = _kind(tree, "apartment")
        self.assertEqual(len(apartments), 1)
        room_labels = {
            node["label"] for node in _walk(apartments[0])
            if node["kind"] == "room"
        }
        self.assertEqual(room_labels, {"Living Room", "Bedroom"})
        self.assertEqual(len(_kind(tree, "mop")), 1)
        assert_preservation(tree, nodes)


class DegenerateAndAtomScaleTests(unittest.TestCase):
    def test_rooms_empty_model_is_valid_and_zoned_by_discipline(self) -> None:
        level = ("1", "L1", 0.0)
        rows = [
            _curve_element(
                "OST_PipeCurves", 14_000, level,
                (100.0, 100.0, 0.0), (2_000.0, 100.0, 0.0)),
            _point_element(
                "OST_Furniture", 14_001, level, (500.0, 500.0, 0.0)),
        ]
        document = _document([level], rows, rooms=[])

        tree = fold_document(document, lift_document(document))

        zones = _kind(tree, "zone")
        self.assertTrue(zones)
        disciplines = {
            node["macro"]["discipline"]
            for node in _kind(tree, "group")
            if node["macro"] and node["macro"].get("type") == "discipline"
        }
        # 28.07: раздел читается из таблицы экстрактора, а не из
        # своего словаря fold.py. Мебель там стоит архитектурной —
        # прежнее «unknown» было не свойством документа, а дырой в
        # словаре, который знал 17 категорий из 47.
        self.assertEqual(disciplines, {"plumbing", "architectural"})

    def test_large_atom_population_becomes_one_compact_cluster(self) -> None:
        level = ("1", "L1", 0.0)
        rows = [
            _point_element(
                "OST_Furniture", 14_100 + index, level,
                (float((index * 613) % 4_000),
                 float((index * 997) % 4_000), 0.0))
            for index in range(200)
        ]
        document = _document([level], rows)
        nodes = lift_document(document)

        tree = fold_document(document, nodes)

        clusters = _kind(tree, "atom_cluster")
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["macro"]["count"], 200)
        self.assertEqual(len(clusters[0]["members"]), 200)
        self.assertLess(len(list(_walk(tree))), 10)
        self.assertEqual(len(list(iter_l1_leaves(tree))), 200)

    def test_atom_clusters_never_cross_group_instance_boundaries(self) -> None:
        level = ("1", "L1", 0.0)
        rows = [
            _point_element(
                "OST_Furniture", 14_400 + index, level,
                (float(index * 137), float(index * 211), 0.0))
            for index in range(6)
        ]
        document = _document([level], rows)
        nodes = lift_document(document)
        groups = _groups(
            ("710", "810", ["14400", "14401", "14402"]),
            ("711", "810", ["14403", "14404", "14405"]),
        )

        unguarded = fold_document(document, nodes)
        guarded = fold_document(document, nodes, group_index=groups)

        self.assertEqual(len(_kind(unguarded, "atom_cluster")), 1)
        self.assertEqual(_kind(guarded, "atom_cluster"), [])
        self.assertEqual(len(list(iter_l1_leaves(guarded))), 6)

    def test_small_atom_groups_are_capped_then_summarized(self) -> None:
        level = ("1", "L1", 0.0)
        rows = [
            _point_element(
                "OST_Furniture", 14_500 + index, level,
                (float(index * 100), float((index % 3) * 100), 0.0),
                type_name=f"unique-{index}")
            for index in range(45)
        ]
        document = _document([level], rows)

        tree = fold_document(document, lift_document(document))

        self.assertEqual(len(_kind(tree, "atom")), 20)
        summaries = _kind(tree, "atom_summary")
        self.assertEqual(len(summaries), 1)
        self.assertEqual(sum(node["macro"]["count"] for node in summaries), 25)
        self.assertEqual(summaries[0]["macro"]["type_name"], "<mixed>")
        self.assertEqual(summaries[0]["macro"]["type_kinds_omitted"], 5)
        self.assertEqual(len(list(iter_l1_leaves(tree))), 45)


class PreservationPropertyTests(unittest.TestCase):
    def test_seeded_mixed_models_never_lose_or_invent_a_leaf(self) -> None:
        randomizer = random.Random(0xF01D)
        categories = (
            "OST_StructuralColumns", "OST_PipeCurves",
            "OST_CableTray", "OST_Furniture", "OST_GenericModel",
        )
        for case_index in range(20):
            level_count = randomizer.randint(1, 5)
            levels = [
                (str(index + 1), f"L{index + 1}", float(index * 3_000))
                for index in range(level_count)
            ]
            rows: list[dict[str, Any]] = []
            for element_index in range(randomizer.randint(1, 80)):
                level = randomizer.choice(levels)
                category = randomizer.choice(categories)
                x = float(randomizer.randint(-20_000, 20_000))
                y = float(randomizer.randint(-20_000, 20_000))
                element_id = 100_000 + case_index * 1_000 + element_index
                if category in ("OST_PipeCurves", "OST_CableTray"):
                    row = _curve_element(
                        category, element_id, level,
                        (x, y, level[2]), (x + 1_000.0, y, level[2]))
                else:
                    row = _point_element(
                        category, element_id, level, (x, y, level[2]))
                rows.append(row)
            document = _document(levels, rows, name=f"property-{case_index}")
            nodes = lift_document(document)

            tree = fold_document(document, nodes)

            self.assertEqual(
                [node["_id"] for node in sorted(
                    iter_l1_leaves(tree), key=lambda item: item["_id"])],
                [node["_id"] for node in sorted(
                    nodes, key=lambda item: item["_id"])],
            )
            self.assertEqual(
                tree["node_id"],
                fold_document(document, reversed(nodes))["node_id"],
            )

    def test_l0_l1_mismatch_refuses_instead_of_silently_folding(self) -> None:
        level = ("1", "L1", 0.0)
        document = _document([level], [
            _point_element(
                "OST_StructuralColumns", 160_000, level, (0.0, 0.0, 0.0)),
        ])
        nodes = lift_document(document)

        with self.assertRaisesRegex(FoldError, "source mismatch"):
            fold_document(document, ())
        assert_preservation(fold_document(document, nodes), nodes)

    def test_missing_level_elevation_refuses_instead_of_guessing_z(self) -> None:
        metadata_level = ("1", "L1", 0.0)
        element_level = ("2", "orphan-level", 3_000.0)
        document = _document([metadata_level], [
            _point_element(
                "OST_StructuralColumns", 160_100, element_level,
                (0.0, 0.0, 3_000.0)),
        ])

        with self.assertRaisesRegex(FoldError, "no matching L0 elevation"):
            fold_document(document, lift_document(document))


class CanonIdentityIsDefiningDOF(unittest.TestCase):
    """Canon-рефайнмент (live A5 evidence 2026-07-21): идентичность OP-листа =
    определяющие DOF (op_name+type_name+params); anchor_mm — деривированная
    величина из сырой Revit-геометрии с float-шумом (10/40 живых стен «мимо»
    канона на 0.5мм anchor-дрейфа при точных p0/p1) и в идентичность op НЕ
    входит.  АТОМ params не имеет — его anchor остаётся идентичностью."""

    _ORIGIN = (0.0, 0.0, 0.0)

    @staticmethod
    def _wall(node_id: str, x: float, level: str = "Этаж 1"):
        return {
            "kind": "op", "op_name": "create_wall", "_id": node_id,
            "type_name": "ЖБ(200)", "source_element_id": node_id,
            "level_name": level,
            "params": {
                "p0_mm": [x, 0.0], "p1_mm": [x + 6000.0, 0.0],
                "height_mm": 3000.0,
                "level": {"by": "name", "value": level},
            },
            "anchor_mm": [x + 3000.0, 0.0, 0.0],
        }

    @staticmethod
    def _door(node_id: str, host_id: str):
        return {
            "kind": "op", "op_name": "create_door", "_id": node_id,
            "type_name": "Дверь", "source_element_id": node_id,
            "level_name": "Этаж 1",
            "params": {
                "host": {"ref": host_id}, "offset_mm": 1000.0,
                "sill_mm": 0.0,
                "type": {"by": "name", "value": "Дверь"},
            },
            "anchor_mm": [1000.0, 0.0, 0.0],
        }

    def test_canon_contract_versions_are_explicit(self) -> None:
        # Страж намеренно прибит: смена канона обязана быть решением, а не
        # побочным эффектом.  /2 → /3 (2026-07-26) — дименсиональные сетки:
        # оси дуги и радианы перестали округляться по миллиметровой сетке
        # (две разные дуговые стены давали ОДИН канон), безразмерные скаляры
        # тоже; и сама версия вошла в canon_hash, чтобы следующая такая смена
        # не переопределяла молча смысл уже сохранённых хешей.
        # /3 → /4 (2026-07-28) — раздел зонной группы: раскладка
        # берёт его из таблицы экстрактора вместо собственного
        # словаря на 17 категорий, лексикон сменился целиком
        # («architecture»→«architectural», «coordination»→«shared»),
        # а macro discipline-группы входит в канон поддерева — то
        # есть у тех же элементов меняются и раскладка, и tree-хеш.
        self.assertEqual(TEMPLATE_CANON_VERSION, "template-canon/4")
        # fidelity /1 → /2 (2026-07-28, contour floor canon): v12 rebuild #7
        # measured extra_rebuilt (source_element_id 11438487) vs expected
        # (9981227) diverging on the SAME logical floor — contour rings
        # (create_floor_by_contour's params.contour.{outer,holes}) now get
        # cyclic-start+winding canon (ContourFloorCanonTests) and bulge is
        # quantized on a grid tied to CANON_MM/chord instead of the generic
        # 1e-9 dimensionless-scalar grid, which never absorbed round-trip
        # noise. See ContourFloorCanonTests for the live falsifying case.
        # fidelity /2 → /3 (2026-07-29, codex-review tasks/b8f3v4r97.output
        # seams #5/#6/#8 on the SAME /2 canon): #5 — the /2 bulge grid
        # (safety*2*CANON_MM/chord) falsely converged bulge=0.09951 and
        # 0.10049 on a 4000mm chord despite a 1.96mm real midpoint drift
        # (>CANON_MM); replaced with the arc's physical mid-sweep point
        # (contour.bulge_midpoint) on the SAME CANON_MM grid as every vertex
        # — no separate bulge dial at all. #6 — radius_mm/dir arcs fell out
        # of /2 entirely (raw, unnormalized ring); both arc forms now lower
        # through one shared function (_effective_bulge calling
        # contour.radius_to_bulge) before canonicalizing, so an authored
        # radius arc and its bulge equivalent hash identically. #8 (canon
        # half only; lift.py's own <1mm discard is out of this wave's
        # boundary) — height_offset_mm absent now canonicalizes identically
        # to explicit 0.0 on create_floor/create_floor_by_contour
        # (_FIDELITY_ABSENT_DEFAULTS).
        #
        # fidelity-canon/4 (2026-07-29, пересборка №11): дуговые стены. A —
        # ветвь 2π снимается на уровне ДУГИ парным сдвигом углов
        # (_canonical_arc_branch): atan2 обратного чтения отдаёт (-pi, pi],
        # декомпиляция хранила соседнюю ветвь — та же дуга, другой хеш (4 из
        # 5 живых расхождений v18). B — концы дуговой стены канонизируются ИЗ
        # её же дуги (_fidelity_arc_endpoints_from_arc): хранимые p0/p1
        # расходились с дугой того же листа на 0.37-0.94 мм и переходили
        # сетку CANON_MM (2 из 5). Ни один допуск не расширен.
        self.assertEqual(FIDELITY_CANON_VERSION, "fidelity-canon/4")

    def test_template_slots_survive_but_fidelity_detects_wrong_host(self) -> None:
        wall_a = self._wall("wall-a", 0.0)
        wall_b = self._wall("wall-b", 20_000.0)
        expected = [wall_a, wall_b, self._door("door", "wall-a")]
        wrong = copy.deepcopy(expected)
        wrong[2]["params"]["host"]["ref"] = "wall-b"

        # Host wildcarding is intentional for reusable templates.
        self.assertEqual(
            TemplateCanon.multiset_hash(expected, self._ORIGIN),
            TemplateCanon.multiset_hash(wrong, self._ORIGIN))
        # A5 fidelity is graph-aware and therefore rejects the wrong wall.
        self.assertNotEqual(
            FidelityCanon.multiset_hash(expected, self._ORIGIN),
            FidelityCanon.multiset_hash(wrong, self._ORIGIN))

    def test_fidelity_keeps_level_while_template_wildcards_it(self) -> None:
        first = self._wall("wall", 0.0, "Этаж 1")
        other_level = copy.deepcopy(first)
        other_level["level_name"] = "Этаж 2"
        other_level["params"]["level"]["value"] = "Этаж 2"

        self.assertEqual(
            TemplateCanon.hash(first, self._ORIGIN),
            TemplateCanon.hash(other_level, self._ORIGIN))
        self.assertNotEqual(
            FidelityCanon.hash(first, self._ORIGIN),
            FidelityCanon.hash(other_level, self._ORIGIN))

    def test_fidelity_uses_typed_angle_and_radial_grids(self) -> None:
        base = self._wall("wall", 0.0)
        base["params"]["rotation_deg"] = 10.04
        base["params"]["radius_mm"] = 99.6
        changed_angle = copy.deepcopy(base)
        changed_angle["params"]["rotation_deg"] = 10.16
        changed_radius = copy.deepcopy(base)
        changed_radius["params"]["radius_mm"] = 100.4

        # The historical template grid is deliberately unchanged (1-unit
        # broad equivalence); FidelityCanon is no coarser than witnesses.
        self.assertEqual(
            TemplateCanon.hash(base, self._ORIGIN),
            TemplateCanon.hash(changed_angle, self._ORIGIN))
        self.assertEqual(
            TemplateCanon.hash(base, self._ORIGIN),
            TemplateCanon.hash(changed_radius, self._ORIGIN))
        self.assertNotEqual(
            FidelityCanon.hash(base, self._ORIGIN),
            FidelityCanon.hash(changed_angle, self._ORIGIN))
        self.assertNotEqual(
            FidelityCanon.hash(base, self._ORIGIN),
            FidelityCanon.hash(changed_radius, self._ORIGIN))

    def test_arc_center_translates_and_both_canons_localize_it(self) -> None:
        arc_wall = self._wall("arc-wall", 0.0)
        arc_wall["params"]["arc"] = {
            "curve_type": "Arc", "center_mm": [3000.0, 1000.0, 0.0],
            "radius_mm": 3162.5, "x_axis": [1.0, 0.0, 0.0],
            "y_axis": [0.0, 1.0, 0.0], "start_angle_rad": 0.1,
            "end_angle_rad": 2.1,
        }
        delta = (200_000.0, 500.0, 0.0)
        moved = _translate_leaf(arc_wall, delta)

        self.assertEqual(
            moved["params"]["arc"]["center_mm"],
            [203_000.0, 1500.0, 0.0])
        self.assertEqual(
            TemplateCanon.hash(arc_wall, self._ORIGIN),
            TemplateCanon.hash(moved, delta))
        self.assertEqual(
            FidelityCanon.hash(arc_wall, self._ORIGIN),
            FidelityCanon.hash(moved, delta))

    def test_op_canon_ignores_anchor_drift(self) -> None:
        op = {
            "kind": "op", "op_name": "create_wall", "_id": "op:1",
            "type_name": "ЖБ(200)", "source_element_id": "1",
            "level_name": "Этаж 1",
            "params": {"p0_mm": [0.0, 0.0], "p1_mm": [6000.0, 0.0],
                       "height_mm": 3000.0,
                       "level": {"by": "name", "value": "Этаж 1"}},
            "anchor_mm": [240213.0, 0.0, 0.0],
        }
        drifted = copy.deepcopy(op)
        # The LIVE pair (демо-v2, src=22272772): raw-geometry anchor 240213.0
        # vs true-midpoint 240212.5 — banker's rounding puts them in DIFFERENT
        # CANON_MM cells (240213 vs 240212), so pre-fix these two canons differ.
        drifted["anchor_mm"] = [240212.5, 0.0, 0.0]
        self.assertEqual(
            canon_hash(op, self._ORIGIN), canon_hash(drifted, self._ORIGIN))
        # Defining DOF still differentiates: a moved endpoint is a new wall.
        moved = copy.deepcopy(op)
        moved["params"]["p1_mm"] = [6100.0, 0.0]
        self.assertNotEqual(
            canon_hash(op, self._ORIGIN), canon_hash(moved, self._ORIGIN))

    def test_ring_canon_is_cyclic_invariant(self) -> None:
        # Canon-рефайнмент №2 (live floor evidence 2026-07-21): Revit
        # пересобирает скетч и отдаёт петлю со СВОЕЙ стартовой вершины —
        # ротация/направление кольца и порядок holes-колец Revit-инцидентны,
        # не определяющие DOF.
        base = {
            "kind": "op", "op_name": "create_floor", "_id": "op:9",
            "type_name": "Плита", "source_element_id": "9",
            "level_name": "Этаж 1",
            "params": {
                "outline": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 4000.0],
                            [0.0, 4000.0]],
                "holes": [[[1000.0, 1000.0], [2000.0, 1000.0],
                           [2000.0, 2000.0], [1000.0, 2000.0]],
                          [[3000.0, 1000.0], [4000.0, 1000.0],
                           [4000.0, 2000.0], [3000.0, 2000.0]]],
                "level": {"by": "name", "value": "Этаж 1"}},
            "anchor_mm": [3000.0, 2000.0, 0.0],
        }
        rotated = copy.deepcopy(base)
        # та же геометрия: outline повёрнут на 2 вершины И развёрнут,
        # holes переставлены и повёрнуты
        o = base["params"]["outline"]
        rotated["params"]["outline"] = list(reversed(o[2:] + o[:2]))
        h0, h1 = base["params"]["holes"]
        rotated["params"]["holes"] = [h1[1:] + h1[:1], h0[3:] + h0[:3]]
        self.assertEqual(
            canon_hash(base, self._ORIGIN), canon_hash(rotated, self._ORIGIN))
        # определяющее различие ловится: сдвинутая вершина = другой пол
        moved = copy.deepcopy(base)
        moved["params"]["outline"][1] = [6100.0, 0.0]
        self.assertNotEqual(
            canon_hash(base, self._ORIGIN), canon_hash(moved, self._ORIGIN))

    def test_atom_canon_keeps_anchor(self) -> None:
        atom = {
            "kind": "atom", "op_name": None, "_id": "atom:1",
            "type_name": "Перила", "source_element_id": "1",
            "level_name": "Этаж 1", "params": None,
            "anchor_mm": [0.0, 0.0, 0.0],
            "reason": {"code": "unsupported_signature"},
        }
        far = copy.deepcopy(atom)
        far["anchor_mm"] = [5000.0, 0.0, 0.0]
        self.assertNotEqual(
            canon_hash(atom, self._ORIGIN), canon_hash(far, self._ORIGIN))

    def test_rotation_canon_is_periodic(self) -> None:
        # Canon-рефайнмент №3 (live antresol furniture 2026-07-21): flip-
        # композиция (hand-флип + пре-ротация) оставляет инстанс на 360° там,
        # где лифт оригинала дал 0° — геометрически то же место, но сырой канон
        # считал 360.0 ≠ 0.0 (3 из 5 «промахов» мебели = именно 360-wrap).
        op = {
            "kind": "op", "op_name": "place_family", "_id": "op:pf",
            "type_name": "Шкаф", "source_element_id": "7",
            "level_name": "Этаж 59",
            "params": {"xyz": [1000.0, 2000.0, 0.0], "rotation_deg": 0.0,
                       "mirrored": True, "hand_flipped": True,
                       "facing_flipped": False,
                       "level": {"by": "name", "value": "Этаж 59"}},
            "anchor_mm": [1000.0, 2000.0, 0.0],
        }
        full_turn = copy.deepcopy(op)
        full_turn["params"]["rotation_deg"] = 360.0
        self.assertEqual(
            canon_hash(op, self._ORIGIN),
            canon_hash(full_turn, self._ORIGIN))
        # float-край: 359.9997° тоже сворачивается в 0°
        near = copy.deepcopy(op)
        near["params"]["rotation_deg"] = 359.9997
        self.assertEqual(
            canon_hash(op, self._ORIGIN), canon_hash(near, self._ORIGIN))
        # определяющее различие держится: 90° ≠ 0°
        quarter = copy.deepcopy(op)
        quarter["params"]["rotation_deg"] = 90.0
        self.assertNotEqual(
            canon_hash(op, self._ORIGIN), canon_hash(quarter, self._ORIGIN))


class ContourFloorCanonTests(unittest.TestCase):
    """group_by-волна больше не актуальна здесь — это канон-волна 28.07:
    первый живой контурный пол (пересборка №7, v12,
    backend/data/decompile/sob62_fas_r23_v12/idempotence_debug.json)
    построился, но канон разошёлся — extra_rebuilt (source_element_id
    11438487) против ожидаемого (9981227), тот же лист.

    Замер: (1) КВАНТОВАНИЕ bulge — дименсиональный безразмерный скаляр
    сегодня округляется на сетке 1e-9 (``_FIDELITY_SCALAR_STEP``), а
    расхождение между «сырыми float лифта оригинала» и
    «округлённой-до-0.01мм геометрией после раунд-трипа через эмиссию»
    садится в 6-7-й знак bulge (~1.3e-6 на хорде ~3925мм) — грид на 3
    порядка точнее самого шума, никогда не сходится; (2) ПОВОРОТ ПЕТЛИ —
    ``_canonical_ring`` в этом файле уже умеет циклический
    старт+ориентацию, но контурные кольца лежат на уровень глубже, чем он
    ищет (``{"shape","points_mm","arcs"}``, а не голый список точек под
    ключом ``outline``/``holes`` напрямую) — для create_floor_by_contour
    он ни разу не срабатывает.

    Оба числа взяты ДОСЛОВНО из дампа (не придуманы)."""

    _ORIGIN = (0.0, 0.0, 0.0)

    # Дословно из idempotence_debug.json, лист source_element_id=9981227
    # (expected) / 11438487 (relifted, extra_rebuilt) — только геометрия и
    # определяющие DOF, без посторонних ключей L1Node не требует.
    _EXPECTED = {
        "kind": "op", "op_name": "create_floor_by_contour",
        "_id": "1cd6c39ca7ce906686b0840de61433508f574d7c",
        "type_name": "НР_Стальной лисn_Парапетная крышка_20мм",
        "source_element_id": "9981227",
        "level_name": "L_02.1Кровля ДОО_+10.460",
        "anchor_mm": [326624.0, 20678.0, 10780.0],
        "params": {
            "height_offset_mm": 1090.0,
            "level": {"_id": "7476592", "by": "name",
                     "value": "L_02.1Кровля ДОО_+10.460"},
            "type": {"_id": "9762703", "by": "name",
                    "value": "НР_Стальной лисn_Парапетная крышка_20мм"},
            "contour": {
                "outer": {
                    "shape": "poly",
                    "points_mm": [
                        [-1040.0000000005512, -630.0000000045203],
                        [21629.9999999992, -630.0000000066885],
                        [21630.00000000017, 9779.233715734683],
                        [54288.95502467433, 21024.613751911955],
                        [42186.60068860707, 41986.50635318629],
                        [1691.4489744590533, 28042.907413652592],
                        [-1039.999999998208, 24213.557182475626],
                    ],
                    "arcs": [{"bulge": 0.32010252369917475, "edge": 5}],
                },
                "holes": [{
                    "shape": "poly",
                    "points_mm": [
                        [-370.00000000048186, 39.99999999537959],
                        [-369.9999999898046, 24213.55718247556],
                        [1909.5796379443896, 27409.409968003652],
                        [41998.10222432238, 41212.99527047598],
                        [53417.916374770044, 21433.2969489025],
                        [20960.000000000597, 10257.140071225855],
                        [20959.999999999654, 39.99999999337618],
                    ],
                    "arcs": [{"bulge": -0.3201025237002575, "edge": 1}],
                }],
            },
        },
    }
    _RELIFTED = {
        "kind": "op", "op_name": "create_floor_by_contour",
        "_id": "50632af2a1ba238157e58a9c9c5ec6e870f9a9dc",
        "type_name": "НР_Стальной лисn_Парапетная крышка_20мм",
        "source_element_id": "11438487",
        "level_name": "L_02.1Кровля ДОО_+10.460",
        "anchor_mm": [26624.480000000003, 20678.255000000005,
                     10779.999999999853],
        "params": {
            "height_offset_mm": 1090.0,
            "level": {"by": "name", "value": "L_02.1Кровля ДОО_+10.460",
                     "_id": "7476592"},
            "type": {"by": "name",
                    "value": "НР_Стальной лисn_Парапетная крышка_20мм",
                    "_id": "9762703"},
            "contour": {
                "outer": {
                    "shape": "poly",
                    "points_mm": [
                        [-1040.0000000000018, -629.9999999999997],
                        [21630.0, -629.9999999999997],
                        [21630.0, 9779.23],
                        [54288.96000000001, 21024.61],
                        [42186.6, 41986.509999999995],
                        [1691.4499999999957, 28042.910000000003],
                        [-1040.0000000000018, 24213.56],
                    ],
                    "arcs": [{"edge": 5, "bulge": 0.3201017253539792}],
                },
                "holes": [{
                    "shape": "poly",
                    "points_mm": [
                        [-370.000000000002, 24213.56],
                        [1909.58, 27409.41],
                        [41998.100000000006, 41213.0],
                        [53417.92, 21433.3],
                        [20960.0, 10257.14],
                        [20960.0, 39.99999999999957],
                        [-369.9999999999982, 39.99999999999957],
                    ],
                    # ПОВОРОТ ПЕТЛИ живьём: та же дуга (та же хорда,
                    # тот же знак bulge, шум в 6-м знаке), но edge 1->0
                    # — relift читает петлю с ДРУГОГО первого узла.
                    "arcs": [{"edge": 0, "bulge": -0.3201012188462134}],
                }],
            },
        },
    }

    def test_v12_extra_rebuilt_sheet_converges_after_canon_fix(self) -> None:
        """Опровергающий тест: сегодняшний типизированный разъезд листа
        9981227 (expected) / 11438487 (relifted) — дословно те же числа,
        что в живом отказе пересборки №7. Канон обеих сторон обязан
        сойтись."""
        self.assertEqual(
            FidelityCanon.hash(self._EXPECTED, self._ORIGIN),
            FidelityCanon.hash(self._RELIFTED, self._ORIGIN),
            "живой лист 9981227/11438487 должен канонизироваться в один "
            "и тот же хеш — квантование bulge + поворот петли контура")

    def test_negative_control_genuinely_different_contour_still_diverges(
            self) -> None:
        """Отрицательный контроль: подвинуть реальную вершину дыры на
        50мм (заведомо больше любого допуска квантования) — канон обязан
        остаться РАЗНЫМ. Канон, который сходится всегда, не канон."""
        moved = copy.deepcopy(self._RELIFTED)
        pts = moved["params"]["contour"]["holes"][0]["points_mm"]
        pts[2] = [pts[2][0] + 50.0, pts[2][1]]
        self.assertNotEqual(
            FidelityCanon.hash(self._EXPECTED, self._ORIGIN),
            FidelityCanon.hash(moved, self._ORIGIN))

    def test_negative_control_genuinely_different_bulge_still_diverges(
            self) -> None:
        """Отрицательный контроль: тот же хорда, но заметно другая
        кривизна (bulge сдвинут на 0.05, на два порядка больше грида на
        этой хорде ~3925мм) — канон обязан остаться РАЗНЫМ."""
        moved = copy.deepcopy(self._RELIFTED)
        moved["params"]["contour"]["holes"][0]["arcs"][0]["bulge"] = -0.37
        self.assertNotEqual(
            FidelityCanon.hash(self._EXPECTED, self._ORIGIN),
            FidelityCanon.hash(moved, self._ORIGIN))

    def _ring_leaf(self, points_mm, arcs, node_id="r"):
        return {
            "kind": "op", "op_name": "create_floor_by_contour", "_id": node_id,
            "type_name": "T", "source_element_id": node_id,
            "level_name": "L1",
            "anchor_mm": [0.0, 0.0, 0.0],
            "params": {
                "level": {"by": "name", "value": "L1"},
                "type": {"by": "name", "value": "T"},
                "contour": {
                    "outer": {"shape": "poly", "points_mm": points_mm,
                             "arcs": arcs},
                    "holes": [],
                },
            },
        }

    def test_synthetic_square_rotation_invariant(self) -> None:
        """Clean synthetic case, easy to reason about: a plain square ring
        read back starting from a different vertex is the SAME ring."""
        square = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0]]
        rotated = square[2:] + square[:2]   # same loop, different start
        self.assertEqual(
            FidelityCanon.hash(self._ring_leaf(square, []), self._ORIGIN),
            FidelityCanon.hash(self._ring_leaf(rotated, []), self._ORIGIN))

    def test_synthetic_square_reversed_is_same_ring(self) -> None:
        square = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0]]
        reversed_ = list(reversed(square))
        self.assertEqual(
            FidelityCanon.hash(self._ring_leaf(square, []), self._ORIGIN),
            FidelityCanon.hash(self._ring_leaf(reversed_, []), self._ORIGIN))

    def test_synthetic_arc_edge_reindexes_under_rotation_and_reflection(
            self) -> None:
        """A ring with ONE arc, rotated AND reversed: the edge index must
        follow its own chord, and the bulge sign must flip under
        reflection (traversal direction reverses)."""
        pts = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0]]
        # edge 1 connects pts[1]->pts[2]
        base = self._ring_leaf(pts, [{"edge": 1, "bulge": 0.2}])

        rotated_pts = pts[1:] + pts[:1]   # old edge 1 -> new edge 0
        rotated = self._ring_leaf(rotated_pts, [{"edge": 0, "bulge": 0.2}])
        self.assertEqual(
            FidelityCanon.hash(base, self._ORIGIN),
            FidelityCanon.hash(rotated, self._ORIGIN))

        # Same physical loop, reversed traversal: pts[::-1] = [p3,p2,p1,p0];
        # the p1->p2 chord now sits at edge 1 (p2->p1), bulge sign flips.
        reversed_pts = pts[::-1]
        reversed_leaf = self._ring_leaf(
            reversed_pts, [{"edge": 1, "bulge": -0.2}])
        self.assertEqual(
            FidelityCanon.hash(base, self._ORIGIN),
            FidelityCanon.hash(reversed_leaf, self._ORIGIN))

        # But the WRONG sign on the reversed loop must NOT match — a
        # canon that ignores reflection sign is a silent-wrong canon.
        reversed_wrong_sign = self._ring_leaf(
            reversed_pts, [{"edge": 1, "bulge": 0.2}])
        self.assertNotEqual(
            FidelityCanon.hash(base, self._ORIGIN),
            FidelityCanon.hash(reversed_wrong_sign, self._ORIGIN))


class Codex20260729BulgeMidpointCanon(unittest.TestCase):
    """Кодекс-ревью tasks/b8f3v4r97.output (сессия eeccfb91), швы №5/№6/№7 —
    все три на fidelity-canon/2 (contour ring canon), закрываются вместе
    fidelity-canon/3: канон дуги стал физическим mid-sweep, а не отдельно
    квантованным bulge, поэтому bulge- и radius-формы одной дуги сходятся
    ПО ПОСТРОЕНИЮ, а не второй нормализацией."""

    _ORIGIN = (0.0, 0.0, 0.0)

    @staticmethod
    def _ring_leaf(points_mm, arcs, node_id="r"):
        return {
            "kind": "op", "op_name": "create_floor_by_contour", "_id": node_id,
            "type_name": "T", "source_element_id": node_id, "level_name": "L1",
            "anchor_mm": [0.0, 0.0, 0.0],
            "params": {
                "level": {"by": "name", "value": "L1"},
                "type": {"by": "name", "value": "T"},
                "contour": {
                    "outer": {"shape": "poly", "points_mm": points_mm, "arcs": arcs},
                    "holes": [],
                },
            },
        }

    # ---- №5: bulge quantization was tied to chord, and falsely converged ----

    def test_codex5_reported_example_now_diverges(self) -> None:
        """Дословный пример ревью: хорда 4000мм, bulge=0.09951 и 0.10049 —
        /2 давал ОДИН hash, хотя середины дуг различаются на 1.96мм
        (> CANON_MM=1мм). /3 обязан их различать."""
        square = [[0.0, 0.0], [4000.0, 0.0], [4000.0, 4000.0], [0.0, 4000.0]]
        m1 = bulge_midpoint(square[0], square[1], 0.09951)
        m2 = bulge_midpoint(square[0], square[1], 0.10049)
        self.assertGreater(math.dist(m1, m2), CANON_MM)   # sanity on the claim itself
        h1 = FidelityCanon.hash(
            self._ring_leaf(square, [{"edge": 0, "bulge": 0.09951}]), self._ORIGIN)
        h2 = FidelityCanon.hash(
            self._ring_leaf(square, [{"edge": 0, "bulge": 0.10049}]), self._ORIGIN)
        self.assertNotEqual(h1, h2)

    def test_codex5_property_same_hash_implies_close_midpoints(self) -> None:
        """Property (кодекс формулировка): для ЛЮБЫХ двух дуг, сошедшихся в
        hash, mid-sweep точки обязаны быть БЛИЖЕ CANON_MM по каждой
        координате. Весь диапазон |b|<=1.5 и несколько длин хорд, включая
        >4км (нижний clamp /2 «раздувал допуск» именно там)."""
        rng = random.Random(20260729)
        chords_mm = [10.0, 100.0, 1000.0, 4000.0, 50_000.0, 4_500_000.0]
        checked_a_match = False
        for chord in chords_mm:
            square = [[0.0, 0.0], [chord, 0.0], [chord, chord], [0.0, chord]]
            for _ in range(60):
                b1 = rng.uniform(-1.5, 1.5)
                if abs(b1) < 1e-6:
                    continue
                b2 = b1 + rng.uniform(-1e-3, 1e-3) * max(1.0, abs(b1) * chord / 1000.0)
                if abs(b2) < 1e-6 or abs(b2) > 1.5:
                    continue
                h1 = FidelityCanon.hash(
                    self._ring_leaf(square, [{"edge": 0, "bulge": b1}]), self._ORIGIN)
                h2 = FidelityCanon.hash(
                    self._ring_leaf(square, [{"edge": 0, "bulge": b2}]), self._ORIGIN)
                if h1 != h2:
                    continue
                checked_a_match = True
                m1 = bulge_midpoint(square[0], square[1], b1)
                m2 = bulge_midpoint(square[0], square[1], b2)
                for i in (0, 1):
                    self.assertLess(
                        abs(m1[i] - m2[i]), CANON_MM,
                        f"chord={chord} b1={b1} b2={b2} coord {i}")
        self.assertTrue(checked_a_match, "property never exercised a real hash match")

    # ---- №6: radius_mm/dir fell out of canon entirely ----

    def test_codex6_radius_form_matches_equivalent_bulge_form(self) -> None:
        """radius=3000, chord=4000, ccw — equivalent bulge is the review's
        own number (0.38196601125…). Both forms of THE SAME arc must hash
        identically."""
        pts = [[0.0, 0.0], [4000.0, 0.0], [4000.0, 4000.0], [0.0, 4000.0]]
        b = radius_to_bulge(pts[0], pts[1], 3000.0, True, "x", "x", [])
        self.assertAlmostEqual(b, 0.38196601125010515, places=9)
        radius_leaf = self._ring_leaf(
            pts, [{"edge": 0, "radius_mm": 3000.0, "dir": "ccw"}])
        bulge_leaf = self._ring_leaf(pts, [{"edge": 0, "bulge": b}])
        self.assertEqual(
            FidelityCanon.hash(radius_leaf, self._ORIGIN),
            FidelityCanon.hash(bulge_leaf, self._ORIGIN))

    def test_codex6_radius_form_cw_matches_equivalent_bulge_form(self) -> None:
        pts = [[0.0, 0.0], [4000.0, 0.0], [4000.0, 4000.0], [0.0, 4000.0]]
        b = radius_to_bulge(pts[0], pts[1], 3000.0, False, "x", "x", [])
        self.assertLess(b, 0.0)
        radius_leaf = self._ring_leaf(
            pts, [{"edge": 0, "radius_mm": 3000.0, "dir": "cw"}])
        bulge_leaf = self._ring_leaf(pts, [{"edge": 0, "bulge": b}])
        self.assertEqual(
            FidelityCanon.hash(radius_leaf, self._ORIGIN),
            FidelityCanon.hash(bulge_leaf, self._ORIGIN))

    def test_codex6_radius_form_survives_rotation_and_reflection(self) -> None:
        """Не только «в лоб» — после диэдральной нормализации (кольцо,
        начатое с другой вершины) radius- и bulge-форма ОДНОЙ дуги обязаны
        остаться одним hash, реиндексация ребра общая для обеих форм."""
        pts = [[0.0, 0.0], [4000.0, 0.0], [4000.0, 4000.0], [0.0, 4000.0]]
        b = radius_to_bulge(pts[0], pts[1], 3000.0, True, "x", "x", [])
        rotated = pts[1:] + pts[:1]     # old edge 0 (pts[0]->pts[1]) -> new edge 3
        radius_leaf = self._ring_leaf(
            rotated, [{"edge": 3, "radius_mm": 3000.0, "dir": "ccw"}])
        bulge_leaf = self._ring_leaf(rotated, [{"edge": 3, "bulge": b}])
        self.assertEqual(
            FidelityCanon.hash(radius_leaf, self._ORIGIN),
            FidelityCanon.hash(bulge_leaf, self._ORIGIN))
        # and both still match the un-rotated bulge-form original
        original_bulge_leaf = self._ring_leaf(pts, [{"edge": 0, "bulge": b}])
        self.assertEqual(
            FidelityCanon.hash(radius_leaf, self._ORIGIN),
            FidelityCanon.hash(original_bulge_leaf, self._ORIGIN))

    def test_codex6_radius_shorter_than_half_chord_fails_open(self) -> None:
        """Геометрически невозможная radius-дуга (радиус < половины хорды)
        не должна ронять канон — тот же fail-open, что и у любой другой
        нераспознанной формы кольца (сырой ring, points_mm/arcs как есть)."""
        pts = [[0.0, 0.0], [4000.0, 0.0], [4000.0, 4000.0], [0.0, 4000.0]]
        leaf = self._ring_leaf(pts, [{"edge": 0, "radius_mm": 100.0, "dir": "ccw"}])
        h = FidelityCanon.hash(leaf, self._ORIGIN)   # must not raise
        self.assertTrue(h)

    # ---- №7: reflection sign, proven only for a minor arc (b=0.2) before ----

    def test_codex7_major_arc_reflection_sign_property(self) -> None:
        """1<|b|<=1.5, каждое ребро квадрата, оба знака: отражённая петля
        обязана сойтись с ПРАВИЛЬНЫМ знаком (-b) и разойтись с неизменённым
        (+b) — отрицательный контроль в том же цикле, не отдельно."""
        rng = random.Random(720260729)
        pts = [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0]]
        n = 4
        for edge in range(n):
            for _ in range(6):
                b = rng.uniform(1.0 + 1e-6, 1.5)
                if rng.random() < 0.5:
                    b = -b
                base = self._ring_leaf(pts, [{"edge": edge, "bulge": b}])
                reversed_pts = pts[::-1]
                new_edge = (n - 2 - edge) % n
                correct = self._ring_leaf(
                    reversed_pts, [{"edge": new_edge, "bulge": -b}])
                wrong = self._ring_leaf(
                    reversed_pts, [{"edge": new_edge, "bulge": b}])
                self.assertEqual(
                    FidelityCanon.hash(base, self._ORIGIN),
                    FidelityCanon.hash(correct, self._ORIGIN),
                    f"edge={edge} b={b}")
                self.assertNotEqual(
                    FidelityCanon.hash(base, self._ORIGIN),
                    FidelityCanon.hash(wrong, self._ORIGIN),
                    f"edge={edge} b={b}")


class Codex20260729HeightOffsetAbsentIsZero(unittest.TestCase):
    """Кодекс №8 (канон-половина — lift.py's <1мм discard остаётся у витража
    по границам волны): absent height_offset_mm обязан канонизироваться как
    explicit 0.0 на ОБЕИХ ветках пола."""

    _ORIGIN = (0.0, 0.0, 0.0)

    @staticmethod
    def _floor_leaf(height_offset, node_id="f"):
        params: dict[str, Any] = {
            "outline": [[0.0, 0.0], [1000.0, 0.0], [1000.0, 1000.0], [0.0, 1000.0]],
            "holes": [],
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "T"},
        }
        if height_offset is not None:
            params["height_offset_mm"] = height_offset
        return {
            "kind": "op", "op_name": "create_floor", "_id": node_id,
            "type_name": "T", "source_element_id": node_id, "level_name": "L1",
            "anchor_mm": [0.0, 0.0, 0.0], "params": params,
        }

    @staticmethod
    def _contour_floor_leaf(height_offset, node_id="fc"):
        params: dict[str, Any] = {
            "level": {"by": "name", "value": "L1"},
            "type": {"by": "name", "value": "T"},
            "contour": {
                "outer": {"shape": "poly",
                         "points_mm": [[0.0, 0.0], [1000.0, 0.0],
                                       [1000.0, 1000.0], [0.0, 1000.0]],
                         "arcs": []},
                "holes": [],
            },
        }
        if height_offset is not None:
            params["height_offset_mm"] = height_offset
        return {
            "kind": "op", "op_name": "create_floor_by_contour", "_id": node_id,
            "type_name": "T", "source_element_id": node_id, "level_name": "L1",
            "anchor_mm": [0.0, 0.0, 0.0], "params": params,
        }

    def test_absent_matches_explicit_zero_create_floor(self) -> None:
        self.assertEqual(
            FidelityCanon.hash(self._floor_leaf(None), self._ORIGIN),
            FidelityCanon.hash(self._floor_leaf(0.0), self._ORIGIN))

    def test_absent_matches_explicit_zero_create_floor_by_contour(self) -> None:
        self.assertEqual(
            FidelityCanon.hash(self._contour_floor_leaf(None), self._ORIGIN),
            FidelityCanon.hash(self._contour_floor_leaf(0.0), self._ORIGIN))

    def test_absent_still_differs_from_a_real_offset(self) -> None:
        """Not a blanket 'height_offset_mm is ignored' — a genuine 5mm
        offset must stay a genuine difference."""
        self.assertNotEqual(
            FidelityCanon.hash(self._floor_leaf(None), self._ORIGIN),
            FidelityCanon.hash(self._floor_leaf(5.0), self._ORIGIN))
        self.assertNotEqual(
            FidelityCanon.hash(self._contour_floor_leaf(None), self._ORIGIN),
            FidelityCanon.hash(self._contour_floor_leaf(5.0), self._ORIGIN))

    def test_roundtrip_minus_0999_to_0999_matches_round_mm_oracle(self) -> None:
        """Кодекс диапазон −0.999…0.999: любое явное значение канонизируется
        РОВНО как absent тогда и только тогда, когда _round_mm той же
        величины даёт 0.0 — то есть один и тот же грид для явного и
        отсутствующего, ни одно явное значение не проглатывается сверх
        этого общего правила."""
        absent_hash = FidelityCanon.hash(self._floor_leaf(None), self._ORIGIN)
        for v in (-0.999, -0.6, -0.4, 0.0, 0.4, 0.6, 0.999):
            with self.subTest(height_offset_mm=v):
                h = FidelityCanon.hash(self._floor_leaf(v), self._ORIGIN)
                self.assertEqual(h == absent_hash, _round_mm(v) == 0.0,
                                 f"height_offset_mm={v}: _round_mm->{_round_mm(v)}")


if __name__ == "__main__":
    unittest.main()
