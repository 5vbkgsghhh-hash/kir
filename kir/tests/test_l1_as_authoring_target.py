"""Is L1 viable as a TARGET FOR AUTHORING, not merely as a cast of
something existing.

WHY. The director's decision on 12.08: the intent-reversal aims at **L1**,
not at the program dialect — then chunking, ref-closure, and topological
sort come for free from `materialize` (paid for by 76 runs against real
buildings; grouping by `host` left 39 of 133 chunks refused on the
`k2_ar_rd_v8` tower), and a second reference walker never needs to exist
at all.

The decision rests on a premise that should have been checked FIRST: **L1
is the schema of the REVERSE move, its nodes descend from an existing
building.** If L1 requires origin from a document, it cannot be targeted.
The measurement below is the answer.

MEASURED 12.08.2026, and it is POSITIVE WITH ONE NAMED HOLE:

* synthetic origin IS ACCEPTED — `source_element_id` is checked as a
  non-empty unique string, NOT as a document element; `_id` is derived
  from it deterministically (`stable_l1_id`);
* a reference to an op in THIS SAME program works: the level is created
  right here, the wall references `{"ref": …}`, `leaves_to_program`
  translates it;
* **the sole gap is TYPE/SYMBOL.** `{"by": "name"|"family_type", "_id":
  …}` requires `_id` to parse as an integer ElementId, meaning the type
  must ALREADY EXIST in the document. The schema lets this through; the
  dialect translator tears: ``MaterializeError: L1 reference _id 'NEW'
  is not an integer ElementId``.

AND THERE IS NO WORKAROUND FOR THIS HOLE TODAY — both roads are closed,
measured against the registry:

    family_symbol PRODUCED BY  2 ops (create_type, load_family)
    family_symbol CONSUMED BY  0
    selector parameters 123, of which 69 accept no ref at all

That is, the program can create/load a type, and not a single op can
reference it: `create_wall.type`, `create_door.symbol`,
`create_floor.type` all have EMPTY ``ref_kinds``. The by-name road is
closed the same way: `ground.py` mentions neither `create_type` nor
`load_family` (23 `def`s in the file — a live grep), and grounding works
off a snapshot taken BEFORE execution.

THE CONSEQUENCE FOR THE MISSION, named as a number: authoring a building
into a document where its catalog doesn't exist yet does not run aground
on geometry or chunking, but on ONE link — there is no one to consume the
created symbol. This is exactly the shape of "built and not wired up,"
and it is measurable, not something to go by ear.

KIND OF LIST: **the registry is a DATED MEASUREMENT, not completeness.**
The test turns red once the hole is closed — and that is good news,
obliging an update to line O12 in `KIR_PLAN.md`, not a sign of breakage.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.decompile.l1_schema import (
    L1SchemaError, stable_l1_id, validate_l1_nodes)
from kir.decompile.materialize import MaterializeError, leaves_to_program

LEVEL_SRC = "SYNTH-LEVEL-1"
WALL_SRC = "SYNTH-WALL-1"
LEVEL_ID = stable_l1_id("op", LEVEL_SRC)


def _node(op_name, source_id, params, level_name=None):
    return {
        "kind": "op",
        "_id": stable_l1_id("op", source_id),
        "source_element_id": source_id,
        "level_name": level_name,
        "anchor_mm": None,
        "type_name": "—",
        "op_name": op_name,
        "params": params,
    }


def _level():
    return _node("create_level", LEVEL_SRC, {"name": "Этаж 1", "elev_mm": 0})


def _wall(type_selector):
    return _node("create_wall", WALL_SRC, {
        "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
        "level": {"ref": LEVEL_ID},
        "type": type_selector,
    }, level_name="Этаж 1")


class L1AcceptsABuildingThatDoesNotExistYet(unittest.TestCase):

    def test_synthetic_origin_is_accepted(self):
        """`source_element_id` is a unique string, NOT a document
        element."""
        nodes = validate_l1_nodes(
            [_level(), _wall({"by": "name", "value": "Стена 200",
                              "_id": "12345"})])
        self.assertEqual(len(nodes), 2)

    def test_the_probe_can_say_no(self):
        """FAIL control: an empty origin must turn red.

        Without it, the "accepted" above cannot be told apart from a
        check that is incapable of refusing anyone.
        """
        with self.assertRaises(L1SchemaError):
            validate_l1_nodes(
                [_node("create_level", "", {"name": "x", "elev_mm": 0})])

    def test_a_ref_to_an_op_of_the_same_program_survives_translation(self):
        """A level created by THIS SAME program is addressable."""
        nodes = validate_l1_nodes(
            [_level(), _wall({"by": "name", "value": "Стена 200",
                              "_id": "12345"})])
        result = leaves_to_program(nodes, include_datums=True)
        self.assertTrue(result.programs)


class TheOneBreakIsTheTypeThatDoesNotExistYet(unittest.TestCase):

    def test_schema_admits_it_but_translation_refuses(self):
        """The boundary lives in the dialect translator, not in the
        schema — this matters.

        The schema lets a type without an ElementId through; the refusal
        comes from `materialize`. So it is the reference dialect that
        needs fixing, not the validator.
        """
        nodes = validate_l1_nodes(
            [_level(), _wall({"by": "name", "value": "Стена, которой нет",
                              "_id": "NEW"})])
        with self.assertRaises(MaterializeError) as ctx:
            leaves_to_program(nodes, include_datums=True)
        self.assertIn("is not an integer ElementId", str(ctx.exception))

    def test_the_symbol_this_program_creates_is_now_consumable(self):
        """THE REGISTRY FIRED AND WAS EXECUTED ON 13.08.2026 — this is
        its second life.

        Before 13.08 this test required `consumers == []` and carried an
        order: "turns red once the hole is closed — that's good news and
        an order to update O12." The full suite on the merged line
        turned it red, the order was carried out, and the assertion was
        flipped, not removed: removing it would mean losing the one
        place where the language's edge is checked by a machine.

            measured 12.08   family_symbol produced by 2, consumed by 0
            measured 13.08   produced by 2, consumed by 7   (A8)

        The seven consumers are the `symbol` of `create_beam`,
        `create_beam_system`, `create_column`, `create_door`,
        `create_foundation`, `create_window`, `place_family`; all seven
        go through the ONE site `_symbol_res`.

        WHAT THIS TEST NOW GUARDS, and why both ends are mandatory:
        producers without consumers is an unclosed edge (what it used to
        be); consumers without producers is a mirror-image unclosed
        edge, and it looks like MORE completeness, because there are
        more rows in the registry. Type parameters
        (`FloorType`/`RoofType`) are deliberately NOT added here: their
        class doesn't produce a single op.
        """
        producers = [
            name for name, op in spec.OPS.items()
            if op.result.reference_kind is not None
            and op.result.reference_kind.value == "family_symbol"]
        consumers = sorted(
            f"{name}.{param.name}"
            for name, op in spec.OPS.items()
            for param in op.params
            if any(kind.value == "family_symbol" for kind in param.ref_kinds))
        self.assertGreaterEqual(
            len(producers), 1,
            "производителей family_symbol не осталось, а потребители есть — "
            "это ЗЕРКАЛЬНОЕ незамкнутое ребро, хуже исходного")
        self.assertTrue(
            consumers,
            "потребителей family_symbol снова ноль — ребро разомкнулось "
            "обратно; см. A8 и `_symbol_res`")
        # 🔴 THE EIGHTH CONSUMER, ADDED 21.08.2026, AND ADDED BY
        # MEASUREMENT. `create_adaptive_component.symbol` declares
        # `ref_kinds` `family_symbol` (checked against the registry, not
        # by name) and entered the language with the adaptive-components
        # wave, AFTER this list was pinned at seven on 13.08. The test
        # had been red ever since, saying exactly what it exists to say:
        # a list that is REMEMBERED had diverged from a registry that is
        # COMPUTED.
        #
        # The list is kept NAMED, not replaced with `len(consumers) >=
        # 7`: weakening it to a count would lose the second half of the
        # assertion — the NAMES. A consumer dropping out of the registry
        # would, under a count, be compensated by a new one and pass
        # silently.
        self.assertEqual(consumers, [
            "create_adaptive_component.symbol",
            "create_beam.symbol", "create_beam_system.symbol",
            "create_column.symbol", "create_door.symbol",
            "create_foundation.symbol", "create_window.symbol",
            "place_family.symbol"])


if __name__ == "__main__":
    unittest.main()
