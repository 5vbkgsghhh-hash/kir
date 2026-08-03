from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from dataclasses import replace
from typing import Any

from kukai.ir.decompile.fold import TreeNode, fold_document, iter_l1_leaves
from kukai.ir.decompile.geom_extract import GeometryExtraction, extract_geometry
from kukai.ir.decompile.group_extract import GroupExtraction
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.name import name_document
from kukai.ir.decompile.passport import (
    PASSPORT_INJECT_TOKENS,
    Passport,
    PassportAssemblyError,
    PassportQueryRefusal,
    assemble_passport,
    build_passport,
    estimate_passport_tokens,
    is_passport_cache_hit,
    passport_bytes,
    passport_cache_key,
    passport_cache_status,
    passport_inject,
    query_passport,
)
from kukai.ir.decompile.recompile import recompile
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)
from kukai.ir.decompile.tests.test_geom_extract import (
    _element as _geometry_element,
    _part as _geometry_part,
    _payload as _geometry_payload,
    _triangle_mesh,
)
from kukai.ir.decompile.verify import verify_document


RECTANGLE = [
    [0.0, 0.0], [12_000.0, 0.0],
    [12_000.0, 8_000.0], [0.0, 8_000.0],
]


def _document(
    elements: list[dict[str, Any]],
    *,
    name: str = "passport-synthetic",
) -> L0Document:
    metadata = copy.deepcopy(project1_metadata())
    metadata.update({
        "doc_name": name,
        "change_stamp": f"{name}-v1",
        "levels": [metadata["levels"][0]],
        "grids": [],
        "rooms": [],
        "elements": copy.deepcopy(elements),
        "category_status": [],
        "links": [],
    })
    return L0Document.from_dict(metadata)


def _pipeline(
    document: L0Document,
    *,
    outline: Any = RECTANGLE,
) -> tuple[list[dict[str, Any]], TreeNode, dict[str, Any], Any, Passport]:
    nodes = list(lift_document(document))
    tree = fold_document(document, nodes)
    named = name_document(document, tree, outline)
    verified = verify_document(document, tree, nodes)
    passport = assemble_passport(document, tree, named, verified)
    return nodes, tree, named, verified, passport


def _walk(node: Any) -> list[Any]:
    return [node] + [
        descendant
        for child in node.get("children", [])
        for descendant in _walk(child)
    ]


def _multi_level_document(floors: int = 40) -> L0Document:
    metadata = copy.deepcopy(project1_metadata())
    levels: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []
    for index in range(floors):
        level_id = str(1000 + index)
        level_name = f"Уровень {index + 1:03d}"
        z = float(index * 3_000)
        levels.append({
            "id": level_id,
            "name": level_name,
            "elevation_mm": z,
        })
        wall = make_element("OST_Walls", 30_000 + index, ordinal=0)
        wall.update({
            "level_id": level_id,
            "level_name": level_name,
            "p0_mm": [0.0, 0.0, z],
            "p1_mm": [6_000.0, 0.0, z],
            "bbox_min_mm": [0.0, 0.0, z],
            "bbox_max_mm": [6_000.0, 300.0, z + 2_800.0],
        })
        elements.append(wall)
    metadata.update({
        "doc_name": "wide-top-tree",
        "change_stamp": "wide-top-tree-v1",
        "levels": levels,
        "grids": [],
        "rooms": [],
        "elements": elements,
        "category_status": [],
        "links": [],
    })
    return L0Document.from_dict(metadata)


def _grid_document() -> L0Document:
    elements: list[dict[str, Any]] = []
    for y_index in range(4):
        for x_index in range(4):
            element = make_element(
                "OST_StructuralColumns",
                40_000 + y_index * 4 + x_index,
                ordinal=0,
            )
            x = float(x_index * 1_000)
            y = float(y_index * 1_000)
            element.update({
                "p0_mm": [x, y, 0.0],
                "rotation_deg": 0.0,
                "bbox_min_mm": [x - 150.0, y - 150.0, 0.0],
                "bbox_max_mm": [x + 150.0, y + 150.0, 3_000.0],
            })
            elements.append(element)
    return _document(elements, name="grid-array")


def _room_document() -> L0Document:
    metadata = copy.deepcopy(project1_metadata())
    wall = make_element("OST_Walls", 50_001, ordinal=0)
    wall.update({
        "p0_mm": [1_000.0, 1_000.0, 0.0],
        "p1_mm": [5_000.0, 1_000.0, 0.0],
        "bbox_min_mm": [1_000.0, 900.0, 0.0],
        "bbox_max_mm": [5_000.0, 1_100.0, 2_800.0],
    })
    room = {
        "id": "room-1",
        "name": "Кабинет",
        "level_id": "100",
        "level_name": "Этаж 1",
        "area_m2": 100.0,
        "boundary_mm": copy.deepcopy(RECTANGLE),
        "boundary_loops_mm": [copy.deepcopy(RECTANGLE)],
        "bounding_element_ids": [],
    }
    metadata.update({
        "doc_name": "room-navigation",
        "change_stamp": "room-navigation-v1",
        "levels": [metadata["levels"][0]],
        "grids": [],
        "rooms": [room],
        "elements": [wall],
        "category_status": [],
        "links": [],
    })
    return L0Document.from_dict(metadata)


def _heavy_atom_document(count: int = 600) -> L0Document:
    elements: list[dict[str, Any]] = []
    for index in range(count):
        element = make_element(
            "OST_Furniture", 60_000 + index, ordinal=1)
        # All points occupy one 5 m atom cell, but deliberately do not form a
        # Cartesian grid that could hide the atom-cluster navigation path.
        x = float((index * 7919) % 4_900)
        y = float((index * 3571 + index * index) % 4_900)
        element.update({
            "level_id": "100",
            "level_name": "Этаж 1",
            "p0_mm": [x, y, 0.0],
            "bbox_min_mm": [x - 100.0, y - 100.0, 0.0],
            "bbox_max_mm": [x + 100.0, y + 100.0, 1_000.0],
        })
        elements.append(element)
    return _document(elements, name="heavy-atoms")


def seeded_passport_payload() -> str:
    """Subprocess entry proving hash-seed-independent Passport bytes."""

    *_parts, passport = _pipeline(_grid_document())
    return passport_bytes(passport).decode("utf-8")


def _geometry_extraction() -> GeometryExtraction:
    return extract_geometry(_geometry_payload([
        _geometry_element(
            "20001", "OST_Walls", [_geometry_part(_triangle_mesh())]),
        _geometry_element(
            "20004", "OST_Furniture", [], status="empty"),
    ]))


def _group_extraction() -> GroupExtraction:
    return GroupExtraction.from_rows([
        {
            "element_id": "700",
            "group_type_id": "800",
            "group_type_name": "Typical floor",
            "member_ids": ["21001", "21002", "999999"],
            "group_id_parent": None,
            "attached_detail_type_count": 0,
            "status": "ok",
        },
        {
            "element_id": "701",
            "group_type_id": "800",
            "group_type_name": "Typical floor",
            "member_ids": ["21003", "21004"],
            "group_id_parent": None,
            "attached_detail_type_count": 0,
            "status": "ok",
        },
    ])


def seeded_geometry_passport_payload() -> str:
    document = _document([
        make_element("OST_Walls", 20_001, ordinal=0),
        make_element("OST_Furniture", 20_004, ordinal=0),
    ], name="geometry-determinism")
    nodes = lift_document(document)
    tree = fold_document(document, nodes)
    passport = build_passport(
        document,
        tree,
        name_document(document, tree, RECTANGLE),
        verify_document(document, tree, nodes),
        geometry=_geometry_extraction(),
    )
    return passport_bytes(passport).decode("utf-8")


class PassportAssemblyTests(unittest.TestCase):
    def test_l0_lift_fold_name_verify_serve_joins_a_frozen_passport(
            self) -> None:
        document = _document([
            make_element("OST_Walls", 20_001, ordinal=0),
            make_element("OST_StructuralColumns", 20_002, ordinal=0),
            make_element("OST_Floors", 20_003, ordinal=0),
        ])
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        named = name_document(document, tree, RECTANGLE)
        verified = verify_document(document, tree, nodes)
        original_tree = copy.deepcopy(tree)
        original_named = copy.deepcopy(named)
        original_verified = verified.to_dict()

        passport = assemble_passport(document, tree, named, verified)

        self.assertIsInstance(passport, Passport)
        self.assertEqual(tree, original_tree)
        self.assertEqual(named, original_named)
        self.assertEqual(verified.to_dict(), original_verified)
        self.assertEqual(passport["doc_name"], document.doc_name)
        self.assertEqual(passport["change_stamp"], document.change_stamp)
        self.assertIn("Прямоугольное здание", passport["gestalt"])
        self.assertEqual(passport["footprint"]["shape"], "rectangle")
        self.assertEqual(passport["stats"]["elements_total"], 3)
        self.assertEqual(passport["stats"]["ops_lifted"], 2)
        self.assertEqual(passport["stats"]["atoms"], 1)
        self.assertEqual(passport["verify_summary"]["failed_count"], 0)
        self.assertEqual(passport["verify_summary"]["verdicts_joined"], 3)
        self.assertEqual(passport["tree"]["verdict"]["status"], "approximate")

        encoded = json.dumps(
            passport, ensure_ascii=False, allow_nan=False, sort_keys=True)
        self.assertIn('"gestalt"', encoded)
        self.assertEqual(passport_bytes(passport), passport.to_bytes())
        mutable = passport.to_dict()
        mutable["tree"]["label"] = "detached"
        self.assertNotEqual(passport["tree"]["label"], "detached")
        with self.assertRaises(TypeError):
            passport["doc_name"] = "changed"
        with self.assertRaises(TypeError):
            passport["tree"]["children"].append({})

    def test_geometry_none_is_byte_identical_to_the_legacy_passport(self) -> None:
        document = _document([
            make_element("OST_Walls", 20_001, ordinal=0),
        ], name="no-geometry-backward-compat")
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        named = name_document(document, tree, RECTANGLE)
        verified = verify_document(document, tree, nodes)

        legacy = build_passport(document, tree, named, verified)
        explicit_none = build_passport(
            document, tree, named, verified, geometry=None)

        self.assertEqual(passport_bytes(explicit_none), passport_bytes(legacy))
        self.assertEqual(explicit_none, legacy)
        self.assertNotIn("geometry", legacy)

    def test_group_none_is_byte_identical_to_the_legacy_passport(self) -> None:
        document = _document([
            make_element("OST_Walls", 20_011, ordinal=0),
        ], name="no-groups-backward-compat")
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        named = name_document(document, tree, RECTANGLE)
        verified = verify_document(document, tree, nodes)

        legacy = build_passport(document, tree, named, verified)
        explicit_none = build_passport(
            document, tree, named, verified, group_index=None)

        self.assertEqual(passport_bytes(explicit_none), passport_bytes(legacy))
        self.assertNotIn("relations", legacy)
        self.assertNotIn("definitions", legacy)
        with self.assertRaises(PassportQueryRefusal):
            query_passport(
                legacy,
                legacy["tree"]["node_id"],
                projection="groups",
            )

    def test_group_relations_definitions_and_virtual_projection_are_honest(
            self) -> None:
        document = _document([
            make_element("OST_Walls", 21_001, ordinal=0),
            make_element("OST_StructuralColumns", 21_002, ordinal=0),
            make_element("OST_Furniture", 21_003, ordinal=0),
            make_element("OST_Furniture", 21_004, ordinal=0),
            make_element("OST_Furniture", 21_005, ordinal=0),
        ], name="group-relations")
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        named = name_document(document, tree, RECTANGLE)
        verified = verify_document(document, tree, nodes)
        plain = build_passport(document, tree, named, verified)

        passport = build_passport(
            document,
            tree,
            named,
            verified,
            group_index=_group_extraction(),
        )

        # Membership is a side relation; the canonical tree is not reparented
        # and no synthetic group-instance leaf is invented.
        self.assertEqual(passport["tree"], plain["tree"])
        self.assertEqual(len(list(iter_l1_leaves(passport["tree"]))), 5)
        membership = passport["relations"]["group_membership"]
        self.assertEqual(set(membership), {
            "21001", "21002", "21003", "21004",
        })
        self.assertEqual(membership["21001"], {
            "group_instance_id": "700",
            "group_type_id": "800",
            "ordinal": 0,
        })
        self.assertNotIn("ordinal", membership["21003"])
        self.assertNotIn("21005", membership)
        unmatched = passport["relations"]["group_membership_unmatched"]
        self.assertEqual(unmatched["total"], 1)
        self.assertEqual(unmatched["absent_from_l0_count"], 1)
        self.assertEqual(unmatched["ambiguous_group_claim_count"], 0)
        self.assertEqual(unmatched["matched_leaf_count"], 4)

        definition = passport["definitions"]["group_types"]["800"]
        self.assertEqual(definition["name"], "Typical floor")
        self.assertEqual(definition["reference_instance_id"], "700")
        self.assertEqual(definition["slot_count"], 3)
        self.assertEqual(definition["instance_count"], 2)
        self.assertTrue(definition["has_composition_mismatch"])
        self.assertEqual(definition["mismatch_instance_count"], 1)
        self.assertEqual(
            definition["slot_comparison_basis"],
            "ordered_cardinality_only",
        )

        root_view = query_passport(
            passport,
            passport["tree"]["node_id"],
            projection="groups",
        )
        self.assertEqual(root_view["node_id"], "groups")
        self.assertEqual(root_view["children_page"]["total"], 1)
        type_view = query_passport(
            passport,
            root_view["children"][0]["node_id"],
            projection="groups",
            limit=1,
        )
        self.assertEqual(type_view["children_page"]["total"], 2)
        self.assertEqual(type_view["children_page"]["more"], "+1 more")
        instance_view = query_passport(
            passport,
            type_view["children"][0]["node_id"],
            projection="groups",
            limit=1,
        )
        self.assertEqual(instance_view["group_instance_id"], "700")
        self.assertEqual(instance_view["members_page"]["total"], 2)
        self.assertEqual(instance_view["members_page"]["more"], "+1 more")
        self.assertEqual(
            instance_view["members"][0]["source_element_id"], "21001")
        self.assertEqual(
            instance_view["members"][0]["membership"]["ordinal"], 0)

        mismatch_view = query_passport(
            passport,
            "group-instance:701",
            projection="groups",
        )
        self.assertEqual(mismatch_view["members_page"]["total"], 2)
        self.assertTrue(all(
            "ordinal" not in member["membership"]
            for member in mismatch_view["members"]
        ))
        restored = json.loads(passport_bytes(passport))
        self.assertEqual(
            query_passport(
                restored, "group-instance:701", projection="groups"),
            mismatch_view,
        )

    def test_geometry_bundle_joins_queries_and_feeds_recompile(self) -> None:
        document = _document([
            make_element("OST_Walls", 20_001, ordinal=0),
            make_element("OST_Furniture", 20_004, ordinal=0),
        ], name="geometry-passport")
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        named = name_document(document, tree, RECTANGLE)
        verified = verify_document(document, tree, nodes)
        geometry = _geometry_extraction()

        passport = build_passport(
            document, tree, named, verified, geometry=geometry)

        self.assertEqual(set(passport["geometry"]), {
            "geometry_index", "geometry_store", "nodes",
        })
        index = passport["geometry"]["geometry_index"]
        store = passport["geometry"]["geometry_store"]
        self.assertEqual(index["20001"]["tier"], "Gm")
        self.assertEqual(index["20004"], {
            "tier": "A", "geo_hash": None, "transform": None,
        })
        geo_hash = index["20001"]["geo_hash"]
        self.assertIn(geo_hash, store)
        self.assertEqual(store[geo_hash]["tier"], "Gm")
        with self.assertRaises(TypeError):
            store[geo_hash] = {}

        wall_leaf = next(
            candidate for candidate in _walk(passport["tree"])
            if (candidate.get("payload") or {}).get(
                "source_element_id") == "20001"
        )
        wall_view = query_passport(passport, wall_leaf["node_id"])
        self.assertEqual(wall_view["geometry_ref"]["tier"], "Gm")
        self.assertEqual(wall_view["geometry_ref"]["geo_hash"], geo_hash)
        self.assertEqual(
            wall_view["geometry_ref"]["definition"], store[geo_hash])

        tier_a_leaf = next(
            candidate for candidate in _walk(passport["tree"])
            if (candidate.get("payload") or {}).get(
                "source_element_id") == "20004"
        )
        tier_a_view = query_passport(passport, tier_a_leaf["node_id"])
        self.assertNotIn("geometry_ref", tier_a_view)

        emitted = recompile(passport["geometry"]["nodes"])
        self.assertEqual(emitted.direct_shape_count, 1)
        self.assertIn("DirectShape.CreateElement", emitted.csharp)
        self.assertIn("TessellatedShapeBuilder", emitted.csharp)

        # The persisted GeometryExtraction dict is the second public input
        # dialect and produces the exact same frozen geometry section.
        from_mapping = build_passport(
            document,
            tree,
            named,
            verified,
            geometry=geometry.to_dict(),
        )
        self.assertEqual(from_mapping["geometry"], passport["geometry"])
        restored = json.loads(passport_bytes(passport))
        self.assertEqual(
            query_passport(restored, wall_leaf["node_id"])["geometry_ref"],
            wall_view["geometry_ref"],
        )

    def test_directshape_pseudo_category_joins_its_real_geometry_category(
            self) -> None:
        """L0 class identity must not overwrite the node's OST_* identity."""

        document = _document([
            make_element("DirectShape", 20_005, ordinal=0),
        ], name="directshape-geometry-passport")
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        named = name_document(document, tree, RECTANGLE)
        verified = verify_document(document, tree, nodes)
        geometry = extract_geometry(_geometry_payload([
            _geometry_element(
                "20005", "OST_GenericModel",
                [_geometry_part(_triangle_mesh())]),
        ]))

        passport = build_passport(
            document, tree, named, verified, geometry=geometry.to_dict())

        self.assertEqual(
            passport["geometry"]["nodes"][0]["category"],
            "OST_GenericModel",
        )
        self.assertEqual(
            passport["geometry"]["geometry_index"]["20005"]["tier"],
            "Gm",
        )

    def test_missing_verify_fact_is_explicitly_unknown(self) -> None:
        document = _document([
            make_element("OST_Walls", 21_001, ordinal=0),
        ], name="missing-verdict")
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        named = name_document(document, tree, RECTANGLE)
        verified = verify_document(document, tree, nodes)
        incomplete = replace(verified, verdicts=())

        passport = assemble_passport(document, tree, named, incomplete)
        leaf = next(
            node for node in _walk(passport["tree"])
            if node["kind"] == "op"
        )

        self.assertEqual(passport["verify_summary"]["unknown_verdicts"], 1)
        self.assertEqual(passport["tree"]["verdict"]["status"], "unknown")
        self.assertEqual(leaf["verdict"]["status"], "unknown")

    def test_missing_name_facts_are_unknown_never_fabricated(self) -> None:
        document = _document([], name="missing-name-facts")
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        incomplete_name = name_document(document, tree, None)
        incomplete_name.pop("gestalt")
        incomplete_name.pop("shape")

        passport = assemble_passport(
            document,
            tree,
            incomplete_name,
            verify_document(document, tree, nodes),
        )

        self.assertEqual(passport["gestalt"], "unknown")
        self.assertEqual(passport["footprint"]["shape"], "unknown")
        self.assertEqual(passport["stats"]["footprint_shape"], "unknown")
        self.assertEqual(passport["stats"]["footprint_dims_mm"], "unknown")

    def test_failed_verify_verdict_is_not_softened_during_join(self) -> None:
        document = _document([
            make_element("OST_Walls", 21_002, ordinal=0),
        ], name="failed-verdict")
        nodes = list(copy.deepcopy(lift_document(document)))
        nodes[0]["params"]["p0_mm"][0] += 100.0
        tree = fold_document(document, nodes)

        passport = assemble_passport(
            document,
            tree,
            name_document(document, tree, RECTANGLE),
            verify_document(document, tree, nodes),
        )
        leaf = next(
            node for node in _walk(passport["tree"])
            if node["kind"] == "op"
        )

        self.assertEqual(passport["verify_summary"]["failed_count"], 1)
        self.assertEqual(passport["tree"]["verdict"]["status"], "failed")
        self.assertEqual(leaf["verdict"]["status"], "failed")

    def test_mismatched_name_tree_and_foreign_verdict_fail_closed(self) -> None:
        left = _document([
            make_element("OST_Walls", 22_001, ordinal=0),
        ], name="left")
        right = _document([
            make_element("OST_Walls", 22_002, ordinal=0),
        ], name="right")
        left_nodes = lift_document(left)
        left_tree = fold_document(left, left_nodes)
        right_nodes = lift_document(right)
        right_tree = fold_document(right, right_nodes)

        with self.assertRaisesRegex(PassportAssemblyError, "NAME tree"):
            assemble_passport(
                left,
                left_tree,
                name_document(right, right_tree, RECTANGLE),
                verify_document(left, left_tree, left_nodes),
            )

        with self.assertRaisesRegex(PassportAssemblyError, "another tree"):
            assemble_passport(
                left,
                left_tree,
                name_document(left, left_tree, RECTANGLE),
                verify_document(right, right_tree, right_nodes),
            )


class PassportCacheTests(unittest.TestCase):
    def test_cache_key_and_hit_stale_decision_are_inert(self) -> None:
        document = _document([], name="cache")
        *_pipeline_parts, passport = _pipeline(document)

        self.assertEqual(passport_cache_key(passport), "cache-v1")
        self.assertEqual(passport_cache_status(passport, "cache-v1"), "hit")
        self.assertEqual(passport_cache_status(passport, "cache-v2"), "stale")
        self.assertTrue(is_passport_cache_hit(passport, "cache-v1"))
        self.assertFalse(is_passport_cache_hit(passport, "cache-v2"))


class ProgressiveDeliveryTests(unittest.TestCase):
    def test_inject_is_bounded_top_tree_and_truncates_breadth_first_honestly(
            self) -> None:
        document = _multi_level_document(80)
        *_parts, passport = _pipeline(document)

        injected = passport_inject(passport)
        payload = json.loads(injected)

        self.assertLessEqual(
            estimate_passport_tokens(injected), PASSPORT_INJECT_TOKENS)
        self.assertEqual(payload["gestalt"], passport["gestalt"])
        self.assertEqual(payload["stats"], passport["stats"])
        self.assertIn("tree", payload)
        self.assertRegex(payload["more"], r"^\+\d+ more$")
        visible_stack = payload["tree"]["children"][0]
        self.assertEqual(visible_stack["kind"], "stack")
        self.assertTrue(visible_stack["children"])
        self.assertTrue(all(
            child["kind"] == "floor"
            for child in visible_stack["children"]
        ))
        self.assertNotIn('"payload"', injected)
        self.assertNotIn('"members"', injected)
        self.assertNotIn('"params"', injected)
        self.assertIn("query_passport(node_id)", payload["navigation"])

        # The exact same cache value produces exactly the same context bytes.
        self.assertEqual(injected, passport_inject(passport))

    def test_query_returns_exact_children_and_is_read_only(self) -> None:
        *_parts, passport = _pipeline(_grid_document())
        root = passport["tree"]

        view = query_passport(passport, root["node_id"])

        self.assertEqual(
            [child["node_id"] for child in view["children"]],
            [child["node_id"] for child in root["children"]],
        )
        self.assertEqual(view["children_page"]["total"], len(root["children"]))
        with self.assertRaises(TypeError):
            view["children"].append({})

        # The same navigator consumes the ordinary dict produced by a JSON
        # cache read; no in-memory Passport-only index is required.
        restored = json.loads(passport_bytes(passport))
        self.assertEqual(
            query_passport(restored, root["node_id"]),
            view,
        )

    def test_stack_expands_to_levels_and_grid_array_to_actual_positions(
            self) -> None:
        *_parts, stacked = _pipeline(_multi_level_document(5))
        stack = next(
            node for node in _walk(stacked["tree"])
            if node["kind"] == "stack"
        )

        stack_view = query_passport(stacked, stack["node_id"])

        self.assertEqual(stack_view["expansion"]["type"], "stack")
        self.assertEqual(len(stack_view["expansion"]["levels"]), 5)
        self.assertEqual(
            [level["node_id"] for level in stack_view["expansion"]["levels"]],
            [child["node_id"] for child in stack["children"]],
        )
        paged_stack = query_passport(
            stacked, stack["node_id"], limit=2)
        self.assertEqual(paged_stack["macro"]["level_count"], 5)
        self.assertNotIn("levels", paged_stack["macro"])
        self.assertEqual(len(paged_stack["expansion"]["levels"]), 2)
        self.assertEqual(paged_stack["expansion"]["page"]["more"], "+3 more")

        *_grid_parts, gridded = _pipeline(_grid_document())
        grid = next(
            node for node in _walk(gridded["tree"])
            if node["kind"] == "grid_array"
        )
        grid_view = query_passport(gridded, grid["node_id"])
        positions = grid_view["expansion"]["positions"]

        self.assertEqual(grid_view["expansion"]["type"], "grid_array")
        self.assertEqual(grid_view["expansion"]["page"]["total"], 16)
        self.assertEqual(len(positions), 16)
        self.assertEqual(
            {tuple(position["anchor_mm"][:2]) for position in positions},
            {(float(x * 1_000), float(y * 1_000))
             for x in range(4) for y in range(4)},
        )
        self.assertTrue(all(
            position["verdict"]["status"] == "exact"
            for position in positions
        ))

    def test_room_query_shows_operations_without_live_model_access(self) -> None:
        *_parts, passport = _pipeline(_room_document(), outline=RECTANGLE)
        room = next(
            node for node in _walk(passport["tree"])
            if node["kind"] == "room"
        )

        view = query_passport(passport, room["node_id"])

        self.assertEqual(view["expansion"]["type"], "room")
        self.assertEqual(view["expansion"]["page"]["total"], 1)
        operation = view["expansion"]["operations"][0]
        self.assertEqual(operation["payload"]["op_name"], "create_wall")
        self.assertEqual(operation["verdict"]["status"], "exact")

    def test_heavy_atom_tree_stays_compact_and_members_are_paged(self) -> None:
        document = _heavy_atom_document()
        *_parts, passport = _pipeline(document)
        visible_nodes = _walk(passport["tree"])
        cluster = next(
            node for node in visible_nodes
            if node["kind"] == "atom_cluster"
        )

        injected = passport_inject(passport)
        view = query_passport(passport, cluster["node_id"], limit=25)

        self.assertLess(len(visible_nodes), 20)
        self.assertLessEqual(
            estimate_passport_tokens(injected), PASSPORT_INJECT_TOKENS)
        self.assertEqual(view["member_count"], 600)
        self.assertEqual(view["expansion"]["page"]["returned"], 25)
        self.assertEqual(view["expansion"]["page"]["total"], 600)
        self.assertEqual(view["expansion"]["page"]["more"], "+575 more")
        self.assertEqual(len(view["expansion"]["members"]), 25)
        second = query_passport(
            passport, cluster["node_id"], offset=25, limit=25)
        self.assertEqual(second["expansion"]["page"]["offset"], 25)
        self.assertNotEqual(
            view["expansion"]["members"][0]["l1_node_id"],
            second["expansion"]["members"][0]["l1_node_id"],
        )

    def test_unknown_node_is_a_typed_refusal_never_an_empty_view(self) -> None:
        *_parts, passport = _pipeline(_document([], name="unknown-node"))

        with self.assertRaises(PassportQueryRefusal) as caught:
            query_passport(passport, "does-not-exist")

        self.assertEqual(caught.exception.code, "KIR-S001")
        refusal = caught.exception.to_dict()
        self.assertFalse(refusal["ok"])
        self.assertEqual(refusal["diagnostics"][0]["code"], "KIR-S001")
        self.assertEqual(
            refusal["diagnostics"][0]["got"], "does-not-exist")


class PassportDeterminismTests(unittest.TestCase):
    def test_same_inputs_have_identical_passport_bytes(self) -> None:
        document = _grid_document()
        *first_parts, first = _pipeline(document)
        *second_parts, second = _pipeline(document)

        self.assertEqual(passport_bytes(first), passport_bytes(second))
        self.assertEqual(first, second)
        self.assertEqual(first_parts[1], second_parts[1])

    def test_output_bytes_are_stable_across_python_hash_seeds(self) -> None:
        backend_root = Path(__file__).resolve().parents[4]
        code = (
            "from kukai.ir.decompile.tests.test_passport import "
            "seeded_passport_payload;print(seeded_passport_payload())"
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

    def test_geometry_passport_is_stable_across_python_hash_seeds(self) -> None:
        backend_root = Path(__file__).resolve().parents[4]
        code = (
            "from kukai.ir.decompile.tests.test_passport import "
            "seeded_geometry_passport_payload;"
            "print(seeded_geometry_passport_payload())"
        )
        outputs = []
        for seed in ("7", "991"):
            environment = os.environ.copy()
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONPATH"] = str(backend_root)
            outputs.append(subprocess.check_output(
                [sys.executable, "-c", code],
                env=environment,
            ))

        self.assertEqual(outputs[0], outputs[1])
        self.assertIn(b'"geometry_store"', outputs[0])


if __name__ == "__main__":
    unittest.main()
