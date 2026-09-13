"""WHY AN ELEMENT WAS LEFT WITHOUT A BODY — FIVE DIFFERENT FACTS, NOT ONE
LIST.

MEASUREMENT OF 11.08.2026, a live reassembly through
`materialize.leaves_to_program` (`/tmp/wiring/m_blind.py`,
`/tmp/wiring/m_cover.py`):

    sob62_r23_v5      902 elements, WITHOUT a type-body snapshot: 3, WITH a snapshot: 18
    snowdon_plumb_v4  16 257 elements, WITHOUT a snapshot: 905, WITH a snapshot: 16 247

That is, coverage on the reassembly door is decided NOT by the wiring, but
by whether an open-model snapshot reaches the check. It does reach it:
`remember_sections` stands in the SHARED body of both doors (`serving.py`,
under `_program_writes`), and `clash_only` reads `entry.sections`. The
earlier report "the audit sees a third of a percent of the building" was a
measurement of MY OWN TEST BENCH, which had seeded the journal by hand and
without sections.

The remaining blindness after the snapshot breaks down into five DIFFERENT
facts, and they are fixed in five different places. As long as they lie in
one flat list of causes, the reader cannot tell "we did not ask" apart
from "there is no one to ask."
"""
from __future__ import annotations

import pathlib
import re
import unittest

from kir import clash_bundle as CB


class EveryBlindnessReasonIsClassified(unittest.TestCase):
    """A LOCK AGAINST SILENCE, the same technique as the category table:
    there is no default. A new cause added to the module and not assigned
    to any class must be NOTICED by the test, rather than travel into the
    report unnamed."""

    SOURCE = pathlib.Path(CB.__file__)

    def _literals(self):
        text = self.SOURCE.read_text(encoding="utf-8")
        found = set()
        for m in re.finditer(r'blame\("([a-z0-9_]+)"\)', text):
            found.add(m.group(1))
        for m in re.finditer(r'return \(?"([a-z0-9_]+)"', text):
            name = m.group(1)
            if name and not name.startswith("kir"):
                found.add(name)
        for m in re.finditer(r'^\s+return \("([a-z0-9_]+)" if', text, re.M):
            found.add(m.group(1))
        return {f for f in found
                if f not in ("none", "ok", "bbox", "read", "absent", "prism")}

    def test_no_reason_is_left_unclassified(self):
        unknown = sorted(r for r in self._literals() if not CB.blind_class(r))
        self.assertEqual(unknown, [], f"причины без класса: {unknown}")

    def test_the_class_list_is_closed(self):
        """A class with no human-readable name looks like technical
        clutter in the report and reads as "unclear" — that is, as the
        absence of an answer."""
        self.assertEqual(
            set(CB.BLIND_CLASSES.values())
            | {name for _, name in CB._BLIND_SUFFIX}
            | {"never_a_body"},
            set(CB.BLIND_CLASS_RU))

    def test_dynamic_reasons_are_classified_by_suffix(self):
        """`f"{name}_geometry_not_expressed"` is assembled from the
        operation's name, and they cannot be listed by name: the registry
        keeps growing."""
        self.assertEqual(CB.blind_class("create_door_geometry_not_expressed"),
                         "op_expresses_no_body")
        self.assertEqual(CB.blind_class("create_window_geometry_not_expressed"),
                         "op_expresses_no_body")
        self.assertEqual(
            CB.blind_class("route_duct_system_graph_has_no_readable_segment"),
            "not_declared_by_program")

    def test_an_invented_reason_is_not_silently_accepted(self):
        self.assertEqual(CB.blind_class("совершенно_новая_причина"), "")


class TheFiveFactsAreNotOneFact(unittest.TestCase):
    """Five causes from DIFFERENT places are fixed differently, and the
    report must keep them apart. One row, "no body: 899," answers five
    questions at once and therefore answers none of them."""

    def _pack(self):
        return [{"ops": [
            # 1. the operation does not create a body at all
            {"op": "create_room", "id": "r1"},
            # 2. the operation does not express a body (geometry belongs
            # to the family)
            {"op": "create_door", "id": "d1"},
            # 3. the program did not declare a number
            {"op": "create_cable_tray", "id": "t1",
             "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0]},
            # 4. an open-model snapshot is needed
            {"op": "create_wall", "id": "w1",
             "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [4000.0, 0.0, 0.0],
             "height_mm": 3000.0},
        ]}]

    def test_each_fact_lands_in_its_own_class(self):
        geo = CB.bundle_elements(self._pack())
        classes = {CB.blind_class(r) for r in geo.no_geometry}
        self.assertIn("op_expresses_no_body", classes)
        self.assertIn("not_declared_by_program", classes)
        self.assertIn("needs_live_model", classes)
        # an operation without an element at all is counted SEPARATELY,
        # not through no_geometry
        self.assertIn("create_room", geo.no_body)
        self.assertNotIn("create_room", geo.no_geometry)

    def test_the_receipt_names_the_classes_not_only_the_count(self):
        block = CB._report(self._pack())
        self.assertIn("blind_by_class", block)
        self.assertTrue(block["blind_by_class"])
        text = block["message_ru"]
        for name in block["blind_by_class"]:
            self.assertIn(CB.BLIND_CLASS_RU[name].split(":")[0][:18], text)

    def test_a_hull_gate_refusal_is_not_our_gap(self):
        """A refusal from SOMEONE ELSE'S lock (`hulls`) and our own
        unfinished work are different things, and dumping them into one
        row means fixing the wrong place."""
        self.assertEqual(
            CB.blind_class("wall_prism_refused_by_containment_gate"),
            "refused_by_hull_gate")
        self.assertEqual(CB.blind_class("no_snapshot"), "needs_live_model")


class OneTableForOneRelation(unittest.TestCase):
    """`OP_CATEGORY` duplicated `spec.OP_RESULT_CATEGORIES`, and the two
    tables of one relation had ALREADY diverged — measurement of
    11.08.2026 (`/tmp/wiring/m_tables.py`, 29 rows versus 44):

      * `create_railing` — my row said `OST_StairsRailing`, the registry
        says `("OST_Railings", "OST_StairsRailing")`. A railing can also
        stand freely; my table named a category that Revit does not
        create in that case;
      * `create_face_wall` the registry knows (`OST_Walls`), and I did
        not know it AT ALL — a wall on a mass face did not enter the
        search with a single body;
      * `create_foundation` variety=slab: the registry honestly says
        `("OST_Floors", "OST_StructuralFoundation")` — the type decides,
        and the compiler does not see the type; my row silently picked
        one.

    THAT THIS IS NOT THE SAME RELATION was also measured, and that is why
    the table is not simply replaced. The registry answers "which
    categories does the op create IN REVIT" (for the census), while this
    module needs "which category to key the `hulls.KIND_TABLE` rule by."
    Hence `create_room` is present in the registry and not needed here,
    while the literal `"DirectShape"` is returned by the registry as a
    SECOND census key, and it is not a Revit category.
    """

    def test_the_local_table_is_gone(self):
        self.assertFalse(hasattr(CB, "OP_CATEGORY"),
                         "вторая таблица того же отношения жива")

    def test_the_registry_is_the_source(self):
        from kir import spec
        self.assertIs(CB._REGISTRY_CATEGORIES, spec.op_result_categories)

    def test_a_face_wall_now_gets_a_body(self):
        """A gain, not just cleanup: the registry knows an op that I did
        not know."""
        self.assertEqual(CB.category_of({"op": "create_face_wall"}),
                         "OST_Walls")

    def test_a_column_still_resolves_by_its_own_enum(self):
        self.assertEqual(
            CB.category_of({"op": "create_column", "category": "structural"}),
            "OST_StructuralColumns")
        self.assertEqual(
            CB.category_of({"op": "create_column",
                            "category": "architectural"}),
            "OST_Columns")

    def test_directshape_keeps_its_revit_category_not_the_census_key(self):
        for op in ("create_directshape", "create_solid_extrusion",
                   "create_solid_revolve"):
            self.assertEqual(
                CB.category_of({"op": op, "category": "furniture"}),
                "OST_Furniture", op)

    def test_an_op_the_registry_cannot_decide_is_named_not_guessed(self):
        """`create_foundation` variety=slab: whether this is a floor slab
        or a foundation slab is decided by the TYPE, which the compiler
        does not see. Silently picking one is a guess; so the choice is
        named and held by its own table."""
        self.assertIn("create_foundation", CB.REGISTRY_GAPS)
        self.assertEqual(CB.category_of({"op": "create_foundation",
                                         "variety": "slab"}),
                         "OST_StructuralFoundation")

    def test_ops_the_registry_does_not_carry_are_named_as_gaps(self):
        """A ROW THAT DID NOT WORK WAS REMOVED (measurement of
        11.08.2026).

        Two operations used to stand here. `create_curtain_grid_line`
        never passed this test: the final word in `category_of` belongs
        to `hulls.KIND_TABLE`, and its `OST_CurtainGridsWall` has
        `eligible=False`, so the answer was `None` while the
        `REGISTRY_GAPS` row was live. The table declared an answer the
        function never returned — the same kind as the removed
        `OP_CATEGORY`, only inside one file. The operation moved into
        `OP_NO_BODY` with a named reason, and the gap row was removed.
        """
        self.assertIn("create_wall_foundation", CB.REGISTRY_GAPS)
        self.assertIsNotNone(CB.category_of({"op": "create_wall_foundation"}))
        self.assertNotIn("create_curtain_grid_line", CB.REGISTRY_GAPS)
        self.assertIn("create_curtain_grid_line", CB.OP_NO_BODY)

    def test_room_and_text_still_produce_no_element(self):
        for op in ("create_room", "create_text", "place_family"):
            self.assertIsNone(CB.category_of({"op": op}), op)


if __name__ == "__main__":
    unittest.main()
