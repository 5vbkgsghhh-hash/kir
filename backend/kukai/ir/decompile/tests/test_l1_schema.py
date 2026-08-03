from __future__ import annotations

import copy
import unittest

from kukai.ir.decompile.l1_schema import (
    L1SchemaError,
    is_valid_l1_node,
    validate_l1_node,
    validate_l1_nodes,
)
from kukai.ir.decompile.lift import lift_document, lift_element
from kukai.ir.decompile.schema import L0Document, L0Element
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element,
    project1_metadata,
)


def _document(elements: list[dict]) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "synthetic-l1-schema-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


class FrozenL1SchemaTests(unittest.TestCase):
    def test_lift_emits_the_frozen_op_and_atom_variants(self) -> None:
        wall = make_element("OST_Walls", 200_001, ordinal=0)
        furniture = make_element("OST_Furniture", 200_002, ordinal=0)

        op, atom = lift_document(_document([wall, furniture]))

        self.assertEqual(set(op), {
            "kind", "op_name", "_id", "type_name", "params",
            "source_element_id", "level_name", "anchor_mm",
        })
        self.assertEqual(set(atom), {
            "kind", "category", "category_ru", "type_name",
            "bbox_min_mm", "bbox_max_mm", "source_element_id",
            "level_name", "anchor_mm", "_id", "reason",
        })
        self.assertIs(validate_l1_node(op), op)
        self.assertIs(validate_l1_node(atom), atom)
        self.assertEqual(atom["reason"]["code"], "no_lifter")
        self.assertTrue(atom["reason"]["detail"])

    def test_nullable_anchor_and_bbox_are_valid_without_invented_origin(
            self) -> None:
        row = make_element("OST_Furniture", 200_003, ordinal=0)
        row.update({
            "geom_kind": "bbox_only",
            "p0_mm": None,
            "p1_mm": None,
            "rotation_deg": None,
            "bbox_min_mm": None,
            "bbox_max_mm": None,
        })

        atom = lift_element(L0Element.from_dict(row))

        self.assertIsNone(atom["anchor_mm"])
        self.assertIsNone(atom["bbox_min_mm"])
        self.assertTrue(is_valid_l1_node(atom))

    def test_provisional_wave_b_field_names_are_not_a_second_dialect(
            self) -> None:
        wall = lift_element(L0Element.from_dict(
            make_element("OST_Walls", 200_004, ordinal=0)))
        provisional = copy.deepcopy(wall)
        provisional["op"] = provisional.pop("op_name")
        provisional["id"] = provisional.pop("_id")

        with self.assertRaisesRegex(L1SchemaError, "_id"):
            validate_l1_node(provisional)

    def test_named_and_node_reference_shapes_are_strict(self) -> None:
        wall = lift_element(L0Element.from_dict(
            make_element("OST_Walls", 200_005, ordinal=0)))
        bad_named = copy.deepcopy(wall)
        bad_named["params"]["level"]["by"] = "id"

        with self.assertRaisesRegex(L1SchemaError, "literal 'name'"):
            validate_l1_node(bad_named)

        host = make_element("OST_Walls", 200_006, ordinal=0)
        door = make_element("OST_Doors", 200_007, ordinal=0)
        door["host_id"] = host["element_id"]
        door["p0_mm"] = [1_000.0, 0.0, 0.0]
        nodes = list(lift_document(_document([host, door])))
        nodes[1]["params"]["host"] = {"ref": "missing-node"}

        with self.assertRaisesRegex(L1SchemaError, "dangling"):
            validate_l1_nodes(nodes)

    def test_required_op_inputs_and_typed_atom_reason_are_enforced(self) -> None:
        wall = lift_element(L0Element.from_dict(
            make_element("OST_Walls", 200_008, ordinal=0)))
        missing = copy.deepcopy(wall)
        missing["params"].pop("p0_mm")
        with self.assertRaisesRegex(L1SchemaError, "required"):
            validate_l1_node(missing)

        furniture = lift_element(L0Element.from_dict(
            make_element("OST_Furniture", 200_009, ordinal=0)))
        unknown_reason = copy.deepcopy(furniture)
        unknown_reason["reason"]["code"] = "probably_furniture"
        with self.assertRaisesRegex(L1SchemaError, "known typed reason"):
            validate_l1_node(unknown_reason)


if __name__ == "__main__":
    unittest.main()
