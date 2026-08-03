from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, Iterable

from kukai.ir.decompile.fold import TreeNode, fold_document, iter_l1_leaves
from kukai.ir.decompile.lift import lift_document
from kukai.ir.decompile.schema import L0Document, L0Element
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)
from kukai.ir.decompile.verify import (
    VERIFY_TOL_MM,
    VerifyResult,
    verify,
    verify_document,
)


def _document(
    elements: list[dict[str, Any]],
    *,
    name: str = "verify-synthetic",
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


def _well_formed_document() -> L0Document:
    wall = make_element("OST_Walls", 20_001, ordinal=0)
    column = make_element("OST_StructuralColumns", 20_002, ordinal=0)
    floor = make_element("OST_Floors", 20_003, ordinal=0)
    return _document([wall, column, floor], name="well-formed")


def _walk(node: TreeNode) -> Iterable[TreeNode]:
    yield node
    for child in node["children"]:
        yield from _walk(child)


def _tree_node_count(node: TreeNode) -> int:
    return sum(1 for _candidate in _walk(node))


def _drop_first_leaf(node: TreeNode) -> bool:
    if node["members"]:
        node["members"].pop(0)
        return True
    for index, child in enumerate(node["children"]):
        if child["payload"] is not None and not child["children"]:
            del node["children"][index]
            return True
        if _drop_first_leaf(child):
            return True
    return False


def seeded_verify_payload() -> str:
    """Subprocess entry used to prove hash-seed-independent result bytes."""

    document = _well_formed_document()
    nodes = lift_document(document)
    tree = fold_document(document, nodes)
    return json.dumps(
        verify_document(document, tree, nodes).to_dict(),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


class VerifyPipelineTests(unittest.TestCase):
    def test_l0_lift_fold_verify_has_exact_ops_and_approximate_atoms(
            self) -> None:
        document = _well_formed_document()
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        original_tree = copy.deepcopy(tree)

        result = verify_document(document, tree, nodes)

        self.assertTrue(result.reversible)
        self.assertEqual(tree, original_tree)
        self.assertEqual(result.summary.total_leaves, 3)
        self.assertEqual(result.summary.op_count, 2)
        self.assertEqual(result.summary.atom_count, 1)
        self.assertEqual(result.summary.exact, 2)
        self.assertEqual(result.summary.approximate, 1)
        self.assertEqual(result.summary.failed, 0)
        self.assertEqual(result.summary.failed_count, 0)
        self.assertAlmostEqual(result.summary.exact_pct, 200.0 / 3.0)
        self.assertAlmostEqual(
            result.summary.approximate_pct, 100.0 / 3.0)
        self.assertAlmostEqual(result.summary.lift_coverage, 200.0 / 3.0)
        self.assertEqual(result.summary.point_geometry_passthrough_pct, 100.0)
        self.assertEqual(
            result.summary.compression_ratio,
            _tree_node_count(tree) / 3.0,
        )
        by_source = {
            verdict.source_element_id: verdict for verdict in result.verdicts
        }
        self.assertEqual(by_source["20001"].status, "exact")
        self.assertEqual(by_source["20002"].status, "exact")
        self.assertEqual(by_source["20003"].status, "approximate")

        direct = verify(
            nodes,
            tree,
            {element.element_id: element for element in document.elements},
        )
        self.assertEqual(result, direct)

    def test_result_dataclasses_are_frozen_and_have_json_boundary(self) -> None:
        document = _well_formed_document()
        nodes = lift_document(document)
        tree = fold_document(document, nodes)
        result = verify_document(document, tree, nodes)

        payload = result.to_dict()
        encoded = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True)

        self.assertIsInstance(result, VerifyResult)
        self.assertIn('"point_geometry_passthrough_pct": 100.0', encoded)
        self.assertIsInstance(payload["verdicts"], list)
        with self.assertRaises(FrozenInstanceError):
            result.reversible = False  # type: ignore[misc]
        with self.assertRaises(FrozenInstanceError):
            result.summary.failed_count = 99  # type: ignore[misc]

    def test_empty_document_metrics_are_finite_and_zero(self) -> None:
        document = _document([], name="empty")
        tree = fold_document(document, ())

        result = verify_document(document, tree, ())

        self.assertTrue(result.reversible)
        self.assertEqual(result.verdicts, ())
        self.assertEqual(result.summary.to_dict(), {
            "total_leaves": 0,
            "op_count": 0,
            "atom_count": 0,
            "exact": 0,
            "approximate": 0,
            "failed": 0,
            "exact_pct": 0.0,
            "approximate_pct": 0.0,
            "failed_count": 0,
            "lift_coverage": 0.0,
            "point_geometry_passthrough_pct": 0.0,
            "compression_ratio": 0.0,
        })


class ReversibilityTests(unittest.TestCase):
    def test_dropped_fold_leaf_is_detected_before_geometry_verdicts(self) -> None:
        document = _well_formed_document()
        nodes = lift_document(document)
        corrupted_tree = copy.deepcopy(fold_document(document, nodes))
        self.assertTrue(_drop_first_leaf(corrupted_tree))

        result = verify_document(document, corrupted_tree, nodes)

        self.assertFalse(result.reversible)
        self.assertIn("missing _id", result.reversibility_detail)
        self.assertEqual(result.summary.total_leaves, len(nodes) - 1)
        self.assertEqual(len(result.verdicts), len(nodes) - 1)

    def test_same_ids_with_mutated_payload_are_not_reversible(self) -> None:
        document = _well_formed_document()
        nodes = lift_document(document)
        corrupted_tree = copy.deepcopy(fold_document(document, nodes))
        mutated = next(iter(iter_l1_leaves(corrupted_tree)))
        mutated["type_name"] += " — corrupted"

        result = verify_document(document, corrupted_tree, nodes)

        self.assertFalse(result.reversible)
        self.assertIn("payload mismatch", result.reversibility_detail)
        self.assertEqual(result.summary.total_leaves, len(nodes))

    def test_generated_fold_expansions_preserve_l1_multisets(self) -> None:
        randomizer = random.Random(20260718)
        categories = (
            "OST_Walls",
            "OST_StructuralColumns",
            "OST_Furniture",
            "OST_Floors",
        )
        for case_index in range(20):
            rows: list[dict[str, Any]] = []
            for element_index in range(randomizer.randint(1, 60)):
                category = randomizer.choice(categories)
                row = make_element(
                    category,
                    100_000 + case_index * 100 + element_index,
                    ordinal=0,
                )
                x = float(randomizer.randint(-20, 20) * 1_000)
                y = float(randomizer.randint(-20, 20) * 1_000)
                if row["geom_kind"] == "curve":
                    row["p0_mm"] = [x, y, 0.0]
                    row["p1_mm"] = [x + 2_000.0, y, 0.0]
                elif row["geom_kind"] == "point":
                    row["p0_mm"] = [x, y, 0.0]
                    row["rotation_deg"] = 0.0
                row["bbox_min_mm"] = [x - 100.0, y - 100.0, 0.0]
                row["bbox_max_mm"] = [x + 2_100.0, y + 100.0, 3_000.0]
                rows.append(row)
            document = _document(rows, name=f"property-{case_index}")
            nodes = lift_document(document)
            tree = fold_document(document, nodes)

            result = verify_document(document, tree, nodes)

            self.assertTrue(result.reversible, result.reversibility_detail)
            self.assertEqual(result.summary.total_leaves, len(nodes))
            self.assertEqual(result.summary.failed_count, 0)


class GeometryVerdictTests(unittest.TestCase):
    def test_injected_lift_deviation_over_tolerance_is_one_real_failure(
            self) -> None:
        document = _document([
            make_element("OST_Walls", 30_001, ordinal=0),
        ], name="injected-lift-bug")
        nodes = list(copy.deepcopy(lift_document(document)))
        self.assertEqual(nodes[0]["kind"], "op")
        nodes[0]["params"]["p0_mm"][0] += VERIFY_TOL_MM + 15.0
        tree = fold_document(document, nodes)

        result = verify_document(document, tree, nodes)

        self.assertTrue(result.reversible)
        self.assertEqual(result.summary.failed, 1)
        self.assertEqual(result.summary.failed_count, 1)
        self.assertEqual(result.summary.exact, 0)
        self.assertEqual(result.verdicts[0].status, "failed")
        self.assertEqual(
            result.verdicts[0].max_deviation_mm,
            VERIFY_TOL_MM + 15.0,
        )
        self.assertIn("25.000 mm", result.verdicts[0].detail)

    def test_tolerance_boundary_and_common_dimensions_are_exact(self) -> None:
        document = _document([
            make_element("OST_Walls", 30_002, ordinal=0),
        ], name="tolerance-boundary")
        nodes = list(copy.deepcopy(lift_document(document)))
        nodes[0]["params"]["p0_mm"][0] += VERIFY_TOL_MM
        # Wall params are 2D while frozen L0 endpoints are 3D.  The contract
        # compares their two common dimensions.
        tree = fold_document(document, nodes)

        result = verify_document(document, tree, nodes)

        self.assertEqual(result.verdicts[0].status, "exact")
        self.assertEqual(result.verdicts[0].max_deviation_mm, VERIFY_TOL_MM)
        self.assertEqual(result.summary.failed_count, 0)

    def test_atom_bbox_only_op_and_host_relative_without_anchor_fail_closed(
            self) -> None:
        atom_document = _document([
            make_element("OST_Floors", 31_001, ordinal=0),
        ], name="atom")
        atom_nodes = lift_document(atom_document)
        atom_result = verify_document(
            atom_document,
            fold_document(atom_document, atom_nodes),
            atom_nodes,
        )
        self.assertEqual(atom_nodes[0]["kind"], "atom")
        self.assertEqual(atom_result.verdicts[0].status, "approximate")

        level_document = _document([
            make_element("OST_Levels", 100, ordinal=0),
        ], name="bbox-level-op")
        level_nodes = lift_document(level_document)
        level_result = verify_document(
            level_document,
            fold_document(level_document, level_nodes),
            level_nodes,
        )
        self.assertEqual(level_nodes[0]["kind"], "op")
        self.assertEqual(level_result.verdicts[0].status, "approximate")
        self.assertIn("bbox-only", level_result.verdicts[0].detail)

        wall = make_element("OST_Walls", 9001, ordinal=0)
        door = make_element("OST_Doors", 31_002, ordinal=0)
        hosted_document = _document([wall, door], name="host-relative")
        hosted_nodes = list(copy.deepcopy(lift_document(hosted_document)))
        door_node = next(
            node for node in hosted_nodes
            if node["source_element_id"] == "31002"
        )
        self.assertEqual(door_node["kind"], "op")
        door_node["anchor_mm"] = None
        hosted_tree = fold_document(hosted_document, hosted_nodes)

        hosted_result = verify_document(
            hosted_document, hosted_tree, hosted_nodes)
        hosted_by_source = {
            verdict.source_element_id: verdict
            for verdict in hosted_result.verdicts
        }
        self.assertEqual(hosted_by_source["9001"].status, "exact")
        self.assertEqual(hosted_by_source["31002"].status, "approximate")
        self.assertEqual(hosted_result.summary.failed_count, 0)

    def test_missing_l0_is_approximate_and_point_count_mismatch_fails(
            self) -> None:
        document = _document([
            make_element("OST_Walls", 32_001, ordinal=0),
        ], name="actual-geometry-cases")
        nodes = lift_document(document)
        tree = fold_document(document, nodes)

        missing = verify(nodes, tree, {})
        self.assertEqual(missing.verdicts[0].status, "approximate")
        self.assertEqual(missing.summary.failed_count, 0)

        point_row = make_element("OST_StructuralColumns", 32_001, ordinal=0)
        point_source = L0Element.from_dict(point_row)
        mismatched = verify(nodes, tree, {"32001": point_source})
        self.assertEqual(mismatched.verdicts[0].status, "failed")
        self.assertIn("point-count mismatch", mismatched.verdicts[0].detail)


class DeterminismTests(unittest.TestCase):
    def test_same_inputs_produce_identical_frozen_result(self) -> None:
        document = _well_formed_document()
        nodes = lift_document(document)
        tree = fold_document(document, nodes)

        first = verify_document(document, tree, nodes)
        second = verify_document(document, tree, nodes)

        self.assertEqual(first, second)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_output_bytes_are_stable_across_python_hash_seeds(self) -> None:
        backend_root = Path(__file__).resolve().parents[4]
        code = (
            "from kukai.ir.decompile.tests.test_verify import "
            "seeded_verify_payload;print(seeded_verify_payload())"
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
