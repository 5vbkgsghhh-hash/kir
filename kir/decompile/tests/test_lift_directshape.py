"""wave/shape — the reverse path for DirectShape.

WRITTEN AND RUN BEFORE THE LIFTER (package discipline: refuting test
first). Before the fix, every test in this file failed: the
"DirectShape" category was absent from the lifters table, and the
element became a NO_LIFTER atom with the wording "category is outside
the exact Part 5 lifter table."

THE MAIN THING THIS FILE RECORDS. With the operation now in place, the
old wording became WRONG: a lifter exists. What is wrong is something
else — there are no meshes in L0. Measured from the extraction code:
GeometryKind is closed over three values (curve/point/bbox_only), and
geometry_store.py writes only bbox/curve/point; there is not a single
byte of vertices or triangles in L0, and that is Wave G
(KIR_DECOMPILE_SPEC.md §0.6), which has not been built. On top of that,
DirectShape does not even RETAIN its own category: the collector puts
the literal "DirectShape" into the category field (extract.py:1296),
because BuiltInCategory is not defined by its class.

So there are exactly two honest outcomes, and both are checked here:

  * a slice with a mesh exists  -> a full create_directshape;
  * no slice exists             -> an atom with the EXACT reason
                                   (MISSING_GEOMETRY), naming precisely
                                   what is missing.

Substituting a bounding box for the missing mesh would be exactly the
Goodhart move already paid for in this house: "built something else" is
indistinguishable from success on the outside, and a flat ceiling
instead of a sloped one is not an approximation, it is a falsehood.
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kir.decompile.lift import (
    AtomReason, LIFTER_TABLE, lift_document_detailed,
)
from kir.decompile.l1_schema import validate_l1_node
from kir.decompile.schema import L0Document
from kir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata,
)


def _document(elements: list[dict[str, Any]]) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "synthetic-directshape-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


def _tetra() -> dict:
    return {
        "mesh_available": True,
        "vertices_mm": [[0, 0, 0], [3000, 0, 0], [1500, 2600, 0],
                        [1500, 900, 2400]],
        "triangles": [[0, 1, 2], [0, 1, 3], [1, 2, 3], [0, 2, 3]],
        "category": "generic_model",
        "name": "тетраэдр",
    }


class LifterReadsBackOrNamesWhy(unittest.TestCase):

    def test_directshape_is_in_the_lifter_table(self):
        self.assertIn("DirectShape", LIFTER_TABLE)

    def test_mesh_slice_lifts_to_a_full_op(self):
        row = make_element("DirectShape", 7001, ordinal=0)
        result = lift_document_detailed(
            _document([row]), profile_index={"7001": _tetra()})

        self.assertEqual(result.diagnostics, ())
        node = result.nodes[0]
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_directshape")
        self.assertEqual(node["params"]["category"], "generic_model")
        self.assertEqual(node["params"]["name"], "тетраэдр")
        self.assertEqual(node["params"]["mesh"]["triangles"],
                         _tetra()["triangles"])
        self.assertEqual(validate_l1_node(node), node)

    def test_without_a_mesh_slice_the_atom_names_the_real_reason(self):
        """Not "there is no lifter" — a lifter exists. There is no MESH
        in L0, and the atom must say exactly that."""
        row = make_element("DirectShape", 7002, ordinal=1)
        result = lift_document_detailed(_document([row]))

        node = result.nodes[0]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(len(result.diagnostics), 1)
        diag = result.diagnostics[0]
        self.assertIs(diag.reason, AtomReason.MISSING_GEOMETRY)
        self.assertNotIn("outside the exact Part 5 lifter table", diag.detail)
        self.assertIn("меш", diag.detail.lower())

    def test_a_slice_that_breaks_the_mesh_laws_becomes_an_atom(self):
        """The direction invariant: a lifter NEVER hands over a program
        the compiler will later reject. The same laws, the same
        validate_mesh."""
        broken = _tetra()
        broken["triangles"] = [[0, 1, 99]]          # index out of range
        row = make_element("DirectShape", 7003, ordinal=2)
        result = lift_document_detailed(
            _document([row]), profile_index={"7003": broken})

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertIs(result.diagnostics[0].reason,
                      AtomReason.UNSUPPORTED_GEOMETRY)

    def test_slice_without_a_category_refuses_instead_of_guessing(self):
        """A "default" generic_model is a silent substitution of the
        category."""
        slice_ = _tetra()
        del slice_["category"]
        row = make_element("DirectShape", 7004, ordinal=3)
        result = lift_document_detailed(
            _document([row]), profile_index={"7004": slice_})

        self.assertEqual(result.nodes[0]["kind"], "atom")
        self.assertIs(result.diagnostics[0].reason,
                      AtomReason.MISSING_METADATA)

    def test_lifted_op_recompiles(self):
        """The loop closes: what the lifter hands over, the compiler
        accepts."""
        from kir.compiler import compile_program

        row = make_element("DirectShape", 7005, ordinal=4)
        result = lift_document_detailed(
            _document([row]), profile_index={"7005": _tetra()})
        params = dict(result.nodes[0]["params"])
        program = {"ir_version": "1.0", "intent": "relift",
                   "ops": [dict(params, op="create_directshape", id="D1")]}
        out = compile_program(program, revit_version="2023",
                              snapshot={"levels": []})
        self.assertTrue(out.ok, [d.message_ru for d in out.diagnostics])


if __name__ == "__main__":
    unittest.main()
