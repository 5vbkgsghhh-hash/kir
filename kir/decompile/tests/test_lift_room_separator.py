"""wave/room — the reverse path for the room separator.

WRITTEN AND RUN BEFORE THE LIFTER (package discipline: refuting test
first). Before the fix, every test in this file failed the same way: the
``OST_RoomSeparationLines`` category was absent from the lifters table,
and every element of it became a ``no_lifter`` atom with the wording
"category is outside the exact Part 5 lifter table." The wording was
HONEST: the operation did not exist.

THE MEASUREMENT THIS FILE FOLLOWS FROM (k2_ar_rd_v9, taken by the L0
instrument): 2 313 separators, of which 2 299 are straight and 14 are
arced; 2 309 have their elevation exactly at the level, 4 are 30 mm
lower. After the wave, the same decompile yields 2 296 ops and 17 atoms
with TWO named reasons instead of one nameless one.

THIS FILE PINS DOWN THE BOUNDARIES SPECIFICALLY, not just the success: an
atom with an exact reason is just as mandatory here as a lifted
operation. An arc straightened into a chord, and a separator that came
back 30 mm lower, would both pass verify (endpoints are compared) and
look like a success — exactly the Goodhart move the lift refuses instead
of "building approximately," in order to forbid it.
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

CATEGORY = "OST_RoomSeparationLines"


def _document(elements: list[dict[str, Any]]) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "synthetic-room-separator-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


def _only(result):
    return result.nodes[0]


class LifterReadsBackOrNamesWhy(unittest.TestCase):

    def test_the_category_is_in_the_lifter_table(self):
        self.assertIn(CATEGORY, LIFTER_TABLE)
        self.assertEqual(LIFTER_TABLE[CATEGORY][1], "create_room_separator")

    def test_a_straight_separator_lifts_to_a_two_point_path(self):
        row = make_element(CATEGORY, 7101, ordinal=0)
        result = lift_document_detailed(_document([row]))

        self.assertEqual(result.diagnostics, ())
        node = _only(result)
        self.assertEqual(node["kind"], "op")
        self.assertEqual(node["op_name"], "create_room_separator")
        self.assertEqual(node["params"]["path"],
                         [[row["p0_mm"][0], row["p0_mm"][1]],
                          [row["p1_mm"][0], row["p1_mm"][1]]])
        self.assertEqual(node["params"]["level"]["value"], row["level_name"])
        self.assertTrue(validate_l1_node(node))

    def test_one_source_element_becomes_exactly_one_node(self):
        """Adjacent lines are NOT stitched into one polyline: L0 has no
        shared identity that would prove their kinship — only a
        coincidence of coordinates, and that is a guess."""
        rows = [make_element(CATEGORY, 7200 + i, ordinal=i) for i in range(5)]
        result = lift_document_detailed(_document(rows))

        self.assertEqual(len(result.nodes), 5)
        for node in result.nodes:
            self.assertEqual(node["kind"], "op")
            self.assertEqual(len(node["params"]["path"]), 2)

    def test_the_op_carries_no_type_because_the_api_has_none(self):
        """NewRoomBoundaryLines has no type argument, and for all 2 313
        separators of K2 the ``type_id``/``type_name`` are empty. Lifting
        a "type" would mean inventing it."""
        row = make_element(CATEGORY, 7301, ordinal=1)
        node = _only(lift_document_detailed(_document([row])))
        self.assertNotIn("type", node["params"])

    # ── boundaries, named out loud ───────────────────────────────────────────

    def test_an_arc_separator_is_a_typed_atom_never_a_chord(self):
        row = make_element(CATEGORY, 7401, ordinal=2)
        row["curve_kind"] = "arc"
        result = lift_document_detailed(_document([row]))

        node = _only(result)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.CURVE_KIND_UNSUPPORTED.value)
        self.assertIn("create_room_separator", node["reason"]["detail"])

    def test_a_separator_off_its_level_plane_is_a_typed_atom(self):
        """There is no offset in either the operation or the API: the
        sketch plane is built from the level itself. Returning such a
        separator to "approximately there" is a silent loss, and on a
        59-story tower nobody would notice it."""
        row = make_element(CATEGORY, 7501, ordinal=3)
        row["p0_mm"] = [row["p0_mm"][0], row["p0_mm"][1], row["p0_mm"][2] - 30]
        row["p1_mm"] = [row["p1_mm"][0], row["p1_mm"][1], row["p1_mm"][2] - 30]
        result = lift_document_detailed(_document([row]))

        node = _only(result)
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.UNSUPPORTED_SIGNATURE.value)
        self.assertIn("offset", node["reason"]["detail"])

    def test_a_separator_crossing_the_level_plane_is_refused_too(self):
        """One end at the level, the other not — that is not "almost
        flat," it is a segment the sketch plane does not express at
        all."""
        row = make_element(CATEGORY, 7601, ordinal=4)
        row["p1_mm"] = [row["p1_mm"][0], row["p1_mm"][1],
                        row["p1_mm"][2] + 500]
        node = _only(lift_document_detailed(_document([row])))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.UNSUPPORTED_SIGNATURE.value)

    def test_a_separator_without_a_level_is_a_typed_atom(self):
        row = make_element(CATEGORY, 7701, ordinal=5)
        row["level_id"] = None
        row["level_name"] = None
        node = _only(lift_document_detailed(_document([row])))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.MISSING_REFERENCE.value)

    def test_a_degenerate_separator_is_refused_before_the_compiler_does(self):
        """The 1 mm threshold is the same as for the `path` kind on the
        forward path: handing over an honest atom is better than a
        program the compiler will reject anyway."""
        row = make_element(CATEGORY, 7801, ordinal=6)
        row["p1_mm"] = list(row["p0_mm"])
        node = _only(lift_document_detailed(_document([row])))
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(node["reason"]["code"],
                         AtomReason.INVALID_VALUE.value)


class ForwardBackwardAgree(unittest.TestCase):
    """A lifted operation must compile through the forward path —
    otherwise the lift produces pretty nodes the language does not
    accept."""

    def test_the_lifted_node_compiles_forward(self):
        from kir.compiler import compile_program
        from kir.tests.fixtures import GROUND_SNAPSHOT

        row = make_element(CATEGORY, 7901, ordinal=0)
        node = _only(lift_document_detailed(_document([row])))
        op = {"op": node["op_name"], "id": "RS1",
              "path": node["params"]["path"],
              # the level of the decompile fixture and the level of the
              # forward-path fixture are different registries, so the
              # selector is pinned by the snapshot's id
              "level": {"by": "element_id", "value": 42}}
        out = compile_program(
            {"ir_version": "1.0", "intent": "поднятый разделитель",
             "ops": [op]}, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.code for d in out.diagnostics][:3])
        self.assertIn("NewRoomBoundaryLines(", out.csharp)


if __name__ == "__main__":
    unittest.main()
