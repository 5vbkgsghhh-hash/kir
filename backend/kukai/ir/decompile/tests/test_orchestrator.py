from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from kukai.ir.decompile import (
    DecompileResult,
    Passport,
    decompile,
    query_passport,
)
from kukai.ir.decompile.fold import iter_l1_leaves
from kukai.ir.decompile.geom_extract import GeometryExtraction, extract_geometry
from kukai.ir.decompile.group_extract import (
    GROUP_INDEX_SCHEMA_VERSION,
    GroupExtraction,
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


REPO_ROOT = next(
    ancestor
    for ancestor in Path(__file__).resolve().parents
    if (ancestor / "backend" / "pyproject.toml").is_file()
    and (ancestor / "backend" / "kukai" / "ir").is_dir()
)
BACKEND_ROOT = (REPO_ROOT / "backend").resolve()
# Preserve a virtual-environment launcher instead of resolving its symlink to
# the base interpreter, which may not have this repository's dependencies.
PYTHON_EXECUTABLE = Path(sys.executable).absolute()

OUTLINE = [
    [0, 0], [12_000, 0], [12_000, 8_000], [0, 8_000],
]


def _document(
    elements: list[dict[str, Any]],
    *,
    name: str = "orchestrator-synthetic",
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


def _profile_entry() -> dict[str, Any]:
    return {
        "profile_available": True,
        "exterior_loop": copy.deepcopy(OUTLINE),
        "holes": [],
        "curve_kinds": [["line"] * len(OUTLINE)],
        "arc_midpoints": [[None] * len(OUTLINE)],
    }


def _building() -> tuple[L0Document, dict[str, dict[str, Any]]]:
    rows = [
        make_element("OST_Walls", 20_001, ordinal=0),
        make_element("OST_Floors", 20_002, ordinal=0),
        make_element("OST_Roofs", 20_003, ordinal=0),
        make_element("OST_Furniture", 20_004, ordinal=0),
    ]
    return _document(rows), {
        "20002": _profile_entry(),
        "20003": _profile_entry(),
    }


def _geometry_extraction() -> GeometryExtraction:
    return extract_geometry(_geometry_payload([
        _geometry_element(
            "20001", "OST_Walls", [_geometry_part(_triangle_mesh())]),
        _geometry_element(
            "20004", "OST_Furniture", [], status="empty"),
    ]))


def _family_index_for(
    document: L0Document,
    element_id: str = "20004",
) -> dict[str, dict[str, Any]]:
    element = next(
        item for item in document.elements if item.element_id == element_id)
    return {
        element_id: {
            "symbol_id": element.type_id,
            "type_name": element.type_name,
            "family_name": "Synthetic universal family",
            "placement_type": "OneLevelBased",
            "in_place": False,
            "mirrored": True,
            "hand_flipped": False,
            "facing_flipped": True,
            "super_component_id": None,
            "group_id": "70000",
            "host_id": None,
            "host_class": None,
            "hand_orientation": [1.0, 0.0, 0.0],
            "facing_orientation": [0.0, 1.0, 0.0],
            "placement_available": True,
            "point_mm": list(element.p0_mm or ()),
            "rotation_deg": float(element.rotation_deg or 0.0),
        },
    }


def _group_extraction() -> GroupExtraction:
    return GroupExtraction.from_rows([{
        "element_id": "70000",
        "group_type_id": "71000",
        "group_type_name": "Synthetic group",
        "member_ids": ["20004"],
        "group_id_parent": None,
        "attached_detail_type_count": 0,
        "origin_ft": [0.0, 0.0, 0.0],
        "status": "ok",
    }])


def _walk(node: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


def _canonical_result() -> str:
    document, profile_index = _building()
    result = decompile(
        document,
        geometry_index=_geometry_extraction(),
        profile_index=profile_index,
        family_placement_index=_family_index_for(document),
        group_index=_group_extraction(),
    )
    return json.dumps(
        result.to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


class OfflineOrchestratorTests(unittest.TestCase):
    def test_family_and_group_indexes_flow_through_without_overclaim(self) -> None:
        document, _ = _building()
        placement_index = _family_index_for(document)
        groups = _group_extraction()

        result = decompile(
            document,
            family_placement_index=placement_index,
            group_index=groups,
        )

        family_node = next(
            node for node in result.l1_nodes
            if node["source_element_id"] == "20004")
        self.assertEqual(family_node["op_name"], "place_family")
        self.assertEqual(
            family_node["params"]["symbol"]["family_name"],
            "Synthetic universal family",
        )
        fidelity = next(
            item for item in result.verify_result.fidelity_verdicts
            if item.source_element_id == "20004")
        self.assertEqual(fidelity.verdict.value, "approximate")
        reason_values = {reason.value for reason in fidelity.reasons}
        self.assertIn("instance_params_incomplete", reason_values)
        self.assertIn("dependency_unresolved", reason_values)
        self.assertNotIn("placement_kind_unknown", reason_values)
        self.assertNotIn("flip_state_unknown", reason_values)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.family_placement_index, placement_index)
        self.assertEqual(
            result.group_index,
            groups.to_dict(),
        )
        self.assertEqual(
            result.to_dict()["group_index"]["schema_version"],
            GROUP_INDEX_SCHEMA_VERSION,
        )
        self.assertEqual(
            result.passport["relations"]["group_membership"]["20004"],
            {
                "group_instance_id": "70000",
                "group_type_id": "71000",
                "ordinal": 0,
            },
        )
        group_type = result.passport[
            "definitions"]["group_types"]["71000"]
        self.assertEqual(group_type["name"], "Synthetic group")
        self.assertEqual(group_type["instance_count"], 1)
        self.assertFalse(group_type["has_composition_mismatch"])
        projection = query_passport(
            result.passport,
            result.passport["tree"]["node_id"],
            projection="groups",
        )
        instance = query_passport(
            result.passport,
            projection["children"][0]["node_id"],
            projection="groups",
        )["children"][0]
        member_page = query_passport(
            result.passport,
            instance["node_id"],
            projection="groups",
        )
        self.assertEqual(member_page["members_page"]["total"], 1)
        self.assertEqual(
            member_page["members"][0]["source_element_id"], "20004")
        self.assertEqual(
            Counter(
                leaf["source_element_id"]
                for leaf in iter_l1_leaves(result.passport["tree"])
            ),
            Counter(element.element_id for element in document.elements),
        )

    def test_profile_backed_building_reaches_a_navigable_passport(self) -> None:
        document, profile_index = _building()
        geometry_index = {
            "20004": {"tier": "A", "geo_hash": None, "transform": None},
        }

        result = decompile(
            document,
            geometry_index=geometry_index,
            profile_index=profile_index,
        )

        self.assertIsInstance(result, DecompileResult)
        self.assertIsInstance(result.passport, Passport)
        self.assertEqual(result.passport["change_stamp"], document.change_stamp)
        by_source = {
            node["source_element_id"]: node for node in result.l1_nodes
        }
        self.assertEqual(by_source["20002"]["op_name"], "create_floor")
        self.assertEqual(by_source["20003"]["op_name"], "create_roof")
        self.assertEqual(by_source["20004"]["kind"], "atom")
        served_ops = {
            node["op_name"]
            for node in iter_l1_leaves(result.passport["tree"])
            if node["kind"] == "op"
        }
        self.assertIn("create_floor", served_ops)
        self.assertIn("create_roof", served_ops)
        self.assertTrue(result.verify_result.reversible)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.metrics["failed_count"], 0)
        self.assertEqual(result.metrics["total_leaves"], 4)
        self.assertEqual(result.metrics["lift_coverage"], 75.0)
        self.assertGreater(result.metrics["compression_ratio"], 0.0)
        self.assertGreater(result.metrics["point_geometry_passthrough_pct"], 0.0)
        self.assertLessEqual(result.metrics["point_geometry_passthrough_pct"], 100.0)
        self.assertEqual(
            result.passport["verify_summary"]["failed_count"],
            result.failed_count,
        )
        self.assertIn("Прямоугольное здание", result.passport["gestalt"])
        self.assertEqual(result.passport["footprint"]["shape"], "rectangle")
        root_view = query_passport(
            result.passport, result.passport["tree"]["node_id"])
        self.assertEqual(root_view["kind"], "building")
        self.assertTrue(root_view["children"])

        # An index-only legacy input has no store definition to join. It stays
        # available on the result, but the Passport honestly omits geometry.
        self.assertNotIn("geometry", result.passport)
        # The result owns a snapshot, not caller data.
        geometry_index["20004"]["tier"] = "corrupted"
        self.assertEqual(result.geometry_index["20004"]["tier"], "A")
        self.assertEqual(
            result.to_dict()["geometry_index"],
            {"20004": {
                "tier": "A", "geo_hash": None, "transform": None,
            }},
        )
        with self.assertRaisesRegex(ValueError, "ids absent from L0"):
            decompile(document, geometry_index={
                "foreign": {
                    "tier": "A", "geo_hash": None, "transform": None,
                },
            })

    def test_complete_geometry_flows_into_passport_and_recompile(self) -> None:
        document, profile_index = _building()
        geometry = _geometry_extraction()

        result = decompile(
            document,
            geometry_index=geometry,
            profile_index=profile_index,
        )

        self.assertIn("geometry", result.passport)
        section = result.passport["geometry"]
        self.assertEqual(section["geometry_index"], geometry.geometry_index)
        self.assertEqual(result.geometry_index, geometry.geometry_index)
        geo_hash = section["geometry_index"]["20001"]["geo_hash"]
        self.assertIn(geo_hash, section["geometry_store"])

        wall_leaf = next(
            node for node in _walk(result.passport["tree"])
            if (node.get("payload") or {}).get(
                "source_element_id") == "20001"
        )
        wall_view = query_passport(result.passport, wall_leaf["node_id"])
        self.assertEqual(wall_view["geometry_ref"]["tier"], "Gm")
        self.assertEqual(wall_view["geometry_ref"]["geo_hash"], geo_hash)
        self.assertEqual(
            wall_view["geometry_ref"]["definition"],
            section["geometry_store"][geo_hash],
        )

        tier_a_leaf = next(
            node for node in _walk(result.passport["tree"])
            if (node.get("payload") or {}).get(
                "source_element_id") == "20004"
        )
        tier_a_view = query_passport(
            result.passport, tier_a_leaf["node_id"])
        self.assertNotIn("geometry_ref", tier_a_view)

        emitted = recompile(section["nodes"])
        self.assertEqual(emitted.direct_shape_count, 1)
        self.assertIn("DirectShape.CreateElement", emitted.csharp)
        self.assertEqual(result.failed_count, 0)
        by_source = {
            node["source_element_id"]: node for node in result.l1_nodes
        }
        self.assertEqual(by_source["20002"]["op_name"], "create_floor")
        self.assertEqual(by_source["20003"]["op_name"], "create_roof")

        # The persisted GeometryExtraction mapping is equally accepted.
        restored = decompile(
            document,
            geometry_index=geometry.to_dict(),
            profile_index=profile_index,
        )
        self.assertEqual(
            restored.passport["geometry"], result.passport["geometry"])

    def test_omitted_indexes_preserve_the_previous_atom_fallback(self) -> None:
        document, _profile_index = _building()

        result = decompile(document)

        by_source = {
            node["source_element_id"]: node for node in result.l1_nodes
        }
        self.assertEqual(by_source["20001"]["op_name"], "create_wall")
        self.assertEqual(by_source["20002"]["kind"], "atom")
        self.assertEqual(by_source["20003"]["kind"], "atom")
        self.assertEqual(by_source["20004"]["kind"], "atom")
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(result.metrics["op_count"], 1)
        self.assertEqual(result.metrics["atom_count"], 3)
        self.assertEqual(result.passport["stats"]["elements_total"], 4)
        self.assertIsNone(result.geometry_index)
        self.assertNotIn("family_placement_index", result.to_dict())
        self.assertNotIn("group_index", result.to_dict())
        self.assertNotIn("relations", result.passport)
        self.assertNotIn("definitions", result.passport)
        root_view = query_passport(
            result.passport, result.passport["tree"]["node_id"])
        self.assertEqual(
            root_view["node_id"], result.passport["tree"]["node_id"])

    def test_rooms_less_heavy_atom_model_is_compact_and_navigable(self) -> None:
        rows: list[dict[str, Any]] = []
        for index in range(180):
            element = make_element(
                "OST_Furniture", 60_000 + index, ordinal=0)
            x = float((index * 7_919) % 4_900)
            y = float((index * 3_571 + index * index) % 4_900)
            element.update({
                "p0_mm": [x, y, 0.0],
                "bbox_min_mm": [x - 100.0, y - 100.0, 0.0],
                "bbox_max_mm": [x + 100.0, y + 100.0, 1_000.0],
            })
            rows.append(element)
        document = _document(rows, name="rooms-less-heavy-atoms")

        result = decompile(document)

        tree_nodes = list(_walk(result.passport["tree"]))
        self.assertEqual(result.metrics["total_leaves"], 180)
        self.assertEqual(result.metrics["atom_count"], 180)
        self.assertEqual(result.metrics["lift_coverage"], 0.0)
        self.assertEqual(result.failed_count, 0)
        self.assertLess(len(tree_nodes), 20)
        self.assertLess(result.metrics["compression_ratio"], 0.1)
        cluster = next(
            node for node in tree_nodes if node["kind"] == "atom_cluster")
        self.assertEqual(cluster["macro"]["count"], 180)
        cluster_view = query_passport(result.passport, cluster["node_id"])
        self.assertEqual(cluster_view["member_count"], 180)
        self.assertEqual(cluster_view["expansion"]["type"], "atom_cluster")
        self.assertTrue(result.passport["gestalt"])

    def test_every_pipeline_surface_preserves_the_l0_leaf_multiset(self) -> None:
        randomizer = random.Random(20260718)
        categories = (
            "OST_Walls",
            "OST_Floors",
            "OST_Roofs",
            "OST_StructuralColumns",
            "OST_Furniture",
        )
        for case_index in range(12):
            rows: list[dict[str, Any]] = []
            profile_index: dict[str, dict[str, Any]] = {}
            for item_index in range(randomizer.randint(1, 45)):
                category = randomizer.choice(categories)
                element_id = 100_000 + case_index * 100 + item_index
                row = make_element(category, element_id, ordinal=0)
                rows.append(row)
                if category in {"OST_Floors", "OST_Roofs"}:
                    profile_index[str(element_id)] = _profile_entry()
            document = _document(rows, name=f"preservation-{case_index}")

            result = decompile(
                document,
                profile_index=profile_index if case_index % 2 == 0 else None,
            )

            expected = Counter(
                element.element_id for element in document.elements)
            lifted = Counter(
                node["source_element_id"] for node in result.l1_nodes)
            folded = Counter(
                node["source_element_id"]
                for node in iter_l1_leaves(result.tree)
            )
            served = Counter(
                node["source_element_id"]
                for node in iter_l1_leaves(result.passport["tree"])
            )
            self.assertEqual(lifted, expected)
            self.assertEqual(folded, expected)
            self.assertEqual(served, expected)
            self.assertTrue(result.verify_result.reversible)
            self.assertEqual(result.metrics["total_leaves"], len(rows))
            self.assertEqual(
                result.passport["stats"]["elements_total"], len(rows))

    def test_result_is_deterministic_under_two_pythonhashseed_values(
            self) -> None:
        document, profile_index = _building()
        self.assertEqual(
            decompile(document, profile_index=profile_index),
            decompile(document, profile_index=profile_index),
        )
        script = (
            "from kukai.ir.decompile.tests.test_orchestrator import "
            "_canonical_result; print(_canonical_result())"
        )
        outputs = []
        for seed in ("7", "991"):
            environment = dict(os.environ)
            environment["PYTHONHASHSEED"] = seed
            environment["PYTHONPATH"] = str(BACKEND_ROOT)
            completed = subprocess.run(
                [str(PYTHON_EXECUTABLE), "-c", script],
                cwd=BACKEND_ROOT,
                env=environment,
                text=True,
                capture_output=True,
                timeout=30,
                check=True,
            )
            outputs.append(completed.stdout)
        self.assertEqual(outputs[0], outputs[1])
        payload = json.loads(outputs[0])
        self.assertEqual(payload["failed_count"], 0)
        self.assertEqual(
            payload["passport"]["footprint"]["shape"], "rectangle")
        self.assertIn("geometry_store", payload["passport"]["geometry"])


class OrchestratorCurtainIndexTests(unittest.TestCase):
    """Хвост волны панелей (aaa44b45, 28.07): ``decompile()`` threads
    ``profile_index``/``family_placement_index`` into ``lift_document`` but
    has no ``curtain_index`` parameter at all — a caller holding a curtain
    index (e.g. a persisted ``curtain.index.json``) has no way to pass it
    through the offline orchestrator, and the panel stays an atom."""

    _HOST_ID = "30001"
    _CELL_ID = "30002"
    _GLAZING_TYPE_ID = "40001"
    _DEFAULT_TYPE_ID = "40000"

    def _curtain_index(self) -> dict[str, Any]:
        return {
            "schema_version": "2",
            "curtain_index": {
                self._HOST_ID: {
                    "curtain_available": True,
                    "host_kind": "wall",
                    "default_panel_type_id": self._DEFAULT_TYPE_ID,
                    "default_panel_type_name": "Системная панель по умолчанию",
                    "u_grid_lines": [],
                    "v_grid_lines": [],
                    "panels": [{
                        "panel_id": self._CELL_ID,
                        "is_family_instance": True,
                        "family_name": "Системная панель",
                        "type_name": "Стеклопакет 30мм",
                        "type_id": self._GLAZING_TYPE_ID,
                        "host_panel_id": None,
                        "host_panel_type_id": None,
                        "host_panel_type_name": None,
                        "u_index": 2,
                        "v_index": 1,
                        "address_state": "ok",
                        "is_door": False,
                    }],
                    "mullions": [],
                },
            },
            "failures": [],
        }

    def _build_document(self) -> L0Document:
        wall = {
            "element_id": self._HOST_ID, "category": "OST_Walls",
            "category_ru": "Стены", "type_id": "50001",
            "type_name": "Витраж НР_ВТ", "level_id": "100",
            "level_name": "Этаж 1", "geom_kind": "curve",
            "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [6000.0, 0.0, 0.0],
            "rotation_deg": None, "bbox_min_mm": None, "bbox_max_mm": None,
            "host_id": None, "params": {"WALL_USER_HEIGHT_PARAM": 2800.0},
        }
        cell = {
            "element_id": self._CELL_ID, "category": "OST_CurtainWallPanels",
            "category_ru": "Панели витража", "type_id": self._GLAZING_TYPE_ID,
            "type_name": "Стеклопакет 30мм", "level_id": None,
            "level_name": None, "geom_kind": "bbox_only",
            "p0_mm": None, "p1_mm": None, "rotation_deg": None,
            "bbox_min_mm": None, "bbox_max_mm": None,
            "host_id": self._HOST_ID, "params": {},
        }
        return _document([wall, cell], name="orchestrator-curtain")

    def test_curtain_index_reaches_the_lift(self) -> None:
        result = decompile(
            self._build_document(), curtain_index=self._curtain_index())
        cell_node = next(
            node for node in result.l1_nodes
            if node["source_element_id"] == self._CELL_ID)
        self.assertEqual(
            cell_node["kind"], "op",
            "panel stayed an atom — decompile() drops curtain_index: "
            f"{cell_node}")
        self.assertEqual(cell_node["op_name"], "set_curtain_panel")


if __name__ == "__main__":
    unittest.main()
