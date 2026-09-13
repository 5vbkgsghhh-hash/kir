"""The "unfolding → L1" contract: what the materializer fixes ON ITS OWN,
and what the unfolding pass must handle.

WHY. The director's decision on 08-12: the intent-unfolding pass targets
L1, and then chunking, ref-closure, and topological sort "come for free"
from `materialize`. "For free" is a HYPOTHESIS until the list of laws is
named and it is shown, for each one, whether it is fixed or skipped. Below
is a measurement, not a reading of docstrings: an L1 that VIOLATES a law
is built, and the outcome is observed.

    law D5 / obligation              who holds it        how it was checked
    ------------------------------  -----------------  --------------------------
    (d) order, Kahn's topo sort      FREE                the level fed LAST —
                                                          emitted FIRST
    (a) ref atomicity                FREE                a host and its dependent
                                                          are always in one program
    (c) chunk size                   FREE, BUT SEE THE   1000 walls on an EXISTING
                                      CEILING BELOW       level → 4 programs×250
    dangling reference               SCHEMA, LOUD        `dangling L1 node
                                                          reference` BEFORE materialize
    duplicate address                SCHEMA, LOUD        `duplicate source ids`
    provenance of `_id`               SCHEMA, LOUD        `op _id is not
                                                          deterministic for its source`
    type/symbol without ElementId     THE UNFOLDING       the one and only hole, O12

**THE MAIN FINDING, AND IT CONTRADICTS THE PREMISE "CHUNKING IS FREE": A
DATUM CREATED BY THE SAME PROGRAM GLUES THE WHOLE BUILDING INTO ONE
INDIVISIBLE UNIT.** Measured 2026-08-12, a sharp boundary:

    the level is CREATED right here:  300 ops → 1 program [300]
                                       301 ops → MaterializeError REFUSAL
        "host-atomic group exceeds compiler bulk limit: 301 > 300
         (host source S-LEVEL)"

    the level ALREADY EXISTS in the document: 1000 walls → 4 programs [250,250,250,250]

    two created levels × 200 walls (402 ops) → 2 programs [201, 201]

The cause is law D5a itself, and it works correctly: the indivisible unit
is the CONNECTED COMPONENT of the entire reference graph. Every wall
references the level ⇒ the building is ONE component ⇒ it must fit inside
`MAX_BULK_OPS`. The reverse pass never saw this, because there datums are
EXTERNAL: `_translate_reference` translates an existing level into
`by=element_id`, and that, as the `_build_host_groups` docstring states,
CREATES NO EDGE. The small components of the reverse pass are a property
of the building already being built, not a property of chunking.

**A CONSEQUENCE STATED AS A NUMBER, AND IT IS ABOUT THE MISSION.** A
building authored from scratch fits no more than **300 ops per created
datum** (299 + the datum itself). A tower of ~30,000 ops, authored from
scratch, requires ≥100 created levels — or the datums must already exist
in the document. Splitting by datum works (two levels gave two programs),
so the ceiling is not absolute but "per component."

**THIS IS NOT A HOLE IN CORRECTNESS BUT A CEILING ON CAPABILITY, AND THE
DIFFERENCE MATTERS.** The refusal is LOUD, typed, and names the offending
datum by name. There is no silent wrongness here; there is a named
boundary that must be known BEFORE anyone starts building on the decision
"the unfolding pass targets L1."

**AND THE CURE IS ALREADY IN PLACE — THIS MATTERS MORE THAN THE ILLNESS
ITSELF.** The same input, the same level, the same references, the
difference in one flag:

    include_datums=True   (the level IS CREATED)   → REFUSAL 401 > 300
    include_datums=False  (the level IS PINNED)     → 2 programs [250, 150]
                                                       level: {"by": "element_id",
                                                               "value": 778899}

A reference by `element_id` creates NO edge, the component falls apart,
and law D5a is untouched to the letter. The mechanism works on every
reverse run. **There is exactly one hole, and it is narrow: today
"external" and "created by us" are MUTUALLY EXCLUSIVE** — a datum becomes
external precisely by NOT BEING CREATED. For the ceiling to disappear, a
datum is needed that is both created AND whose ElementId is known by the
time the next chunk grounds — that is, an ADDRESS THAT OUTLIVES THE
PROGRAM.

And a mode for exactly this is already named: **`mode="fresh_document"` —
hook B4, named in three places in the code, refuses, and there is exactly
one test for the refusal.** This is a NAMED hole, not an unknown; there is
no need to design "a building together with its document" all over again.

THE KIND OF THIS LIST: **CLOSED, BUT NOT COMPLETE.** The laws checked are
the ones named in the `materialize` docstring (D5 a/c/d) plus three schema
obligations. The laws "rooms trail at the end" and "a solo staircase" are
NOT checked here — they need an L1 with rooms and staircases, and their
absence from the table means "unknown," not "free."
"""
from __future__ import annotations

import unittest

from kir.decompile.l1_schema import (
    L1SchemaError, stable_l1_id, validate_l1_nodes)
from kir.decompile.materialize import (
    MAX_BULK_OPS, MaterializeError, leaves_to_program)

LEVEL_SRC = "S-LEVEL"
LEVEL_ID = stable_l1_id("op", LEVEL_SRC)
#: A level already standing in the document: a selector with an integer
#: ElementId. Such a reference is translated to `by=element_id` and
#: creates NO edge in the graph.
EXISTING_LEVEL = {"by": "name", "value": "Этаж 1", "_id": "987654"}


def _node(op_name, source_id, params, level_name=None):
    return {
        "kind": "op", "_id": stable_l1_id("op", source_id),
        "source_element_id": source_id, "level_name": level_name,
        "anchor_mm": None, "type_name": "—",
        "op_name": op_name, "params": params,
    }


def _level(source_id=LEVEL_SRC, name="Этаж 1", elev_mm=0):
    return _node("create_level", source_id, {"name": name, "elev_mm": elev_mm})


def _wall(index, level_selector):
    return _node("create_wall", f"S-WALL-{index}", {
        "p0_mm": [index * 5000, 0], "p1_mm": [index * 5000 + 4000, 0],
        "height_mm": 3000, "level": level_selector,
        "type": {"by": "name", "value": "Стена 200", "_id": "12345"},
    }, level_name="Этаж 1")


def _door(index, host_src):
    return _node("create_door", f"S-DOOR-{index}", {
        "host": {"ref": stable_l1_id("op", host_src)},
        "offset_mm": 2000,
        "symbol": {"by": "name", "value": "Дверь 900", "_id": "22222"},
    }, level_name="Этаж 1")


def _materialize(leaves):
    return leaves_to_program(validate_l1_nodes(leaves), include_datums=True)


def _sizes(result):
    return [len(program["ops"]) for program in result.programs]


def _placement(result):
    return {op["id"]: index
            for index, program in enumerate(result.programs)
            for op in program["ops"]}


class TheseLawsComeFree(unittest.TestCase):
    """The unfolding pass may feed L1 in any order and not think about
    them."""

    def test_order_is_repaired_by_the_toposort(self):
        """Law (d): the level is fed last — emitted first."""
        result = _materialize([_wall(1, {"ref": LEVEL_ID}),
                               _wall(2, {"ref": LEVEL_ID}),
                               _level()])
        order = [op["id"] for program in result.programs
                 for op in program["ops"]]
        self.assertEqual(order[0], "e" + LEVEL_SRC,
                         "порядок сохранён как подан — топосорт не сработал")

    def test_a_host_and_its_dependent_never_split(self):
        """Law (a): a door and its wall stay in one program even across a
        batch boundary."""
        leaves = ([_wall(i, EXISTING_LEVEL) for i in range(400)]
                  + [_door(0, "S-WALL-399")])
        where = _placement(_materialize(leaves))
        self.assertIn("eS-DOOR-0", where, "дверь не эмитирована вовсе")
        self.assertEqual(
            where["eS-DOOR-0"], where["eS-WALL-399"],
            "хозяин и зависимый разъехались по программам — KIR-L003")

    def test_chunking_is_free_when_the_datum_is_external(self):
        """Law (c): 1000 walls on an EXISTING level split on their own."""
        result = _materialize([_wall(i, EXISTING_LEVEL) for i in range(1000)])
        sizes = _sizes(result)
        self.assertGreater(len(sizes), 1, "не разделилось вовсе")
        self.assertLessEqual(max(sizes), MAX_BULK_OPS)


class TheSchemaOwnsTheseLoudly(unittest.TestCase):
    """The unfolding pass owes this, but it cannot fail silently: the
    refusal arrives before emission."""

    def test_a_dangling_ref_is_refused_before_materialize(self):
        with self.assertRaises(L1SchemaError) as ctx:
            _materialize([_level(), _wall(1, {"ref": LEVEL_ID}),
                          _door(0, "S-WALL-КОТОРОЙ-НЕТ")])
        self.assertIn("dangling", str(ctx.exception))

    def test_a_duplicate_address_is_refused(self):
        with self.assertRaises(L1SchemaError):
            _materialize([_level(), _wall(1, {"ref": LEVEL_ID}),
                          _wall(1, {"ref": LEVEL_ID})])

    def test_an_id_not_derived_from_its_source_is_refused(self):
        forged = _wall(2, EXISTING_LEVEL)
        forged["_id"] = "не-тот-хеш"
        with self.assertRaises(L1SchemaError):
            _materialize([forged])


class ADatumCreatedInProgramIsACutVertex(unittest.TestCase):
    """The authoring ceiling: chunking is free ONLY with external datums.

    This is exactly where the cost of the decision "the unfolding pass
    targets L1" lives. The refusal is loud and names the datum — there is
    no silent wrongness, there is a named boundary.
    """

    def test_the_ceiling_is_exactly_the_compiler_bulk_limit(self):
        """300 ops on a created level go through, 301 is refused."""
        at_limit = [_level()] + [
            _wall(i, {"ref": LEVEL_ID}) for i in range(MAX_BULK_OPS - 1)]
        self.assertEqual(_sizes(_materialize(at_limit)), [MAX_BULK_OPS])

        over = at_limit + [_wall(MAX_BULK_OPS - 1, {"ref": LEVEL_ID})]
        with self.assertRaises(MaterializeError) as ctx:
            _materialize(over)
        message = str(ctx.exception)
        self.assertIn("exceeds compiler bulk limit", message)
        self.assertIn(LEVEL_SRC, message,
                      "отказ не называет виновный датум — граница безымянна")

    def test_the_same_ops_pass_when_the_datum_is_external(self):
        """Control: the same ops and the same count — but the datum is
        from the document.

        Without this pair, "301 refused" is indistinguishable from "301
        ops is simply not allowed," and the ceiling would read as a
        property of size, not of connectivity.
        """
        external = [_wall(i, EXISTING_LEVEL) for i in range(MAX_BULK_OPS)]
        sizes = _sizes(_materialize(external))
        self.assertEqual(sum(sizes), MAX_BULK_OPS)
        self.assertGreater(len(sizes), 1)

    def test_the_cure_already_exists_and_is_one_flag_away(self):
        """THE SAME input falls apart if the datum is pinned by ElementId.

        The most valuable thing in this file, because it names the CURE,
        not only the illness. 401 elements, the same level, the same
        references:

            include_datums=True   (the level IS CREATED)  -> REFUSAL 401 > 300
            include_datums=False  (the level IS PINNED)    -> 2 programs [250, 150]

        In the second case the reference is translated into
        ``{"by": "element_id", "value": 778899}`` — and such a reference
        creates NO edge in the graph, the component falls apart, and law
        D5a is untouched to the letter.

        So the mechanism that dissolves the component is ALREADY IN PLACE
        and works on every reverse run. There is exactly one hole, and it
        is narrow: today "external" and "created by us" are MUTUALLY
        EXCLUSIVE — a datum becomes external precisely by NOT BEING
        CREATED. For the ceiling to disappear, a datum is needed that is
        both created AND whose ElementId is known by the time the next
        chunk grounds.
        """
        numeric_src = "778899"          # a source like that of a real element
        numeric_id = stable_l1_id("op", numeric_src)
        leaves = [_level(numeric_src)] + [
            _wall(i, {"ref": numeric_id}) for i in range(MAX_BULK_OPS + 100)]

        with self.assertRaises(MaterializeError):
            leaves_to_program(validate_l1_nodes(leaves), include_datums=True)

        pinned = leaves_to_program(
            validate_l1_nodes(leaves), include_datums=False)
        self.assertGreater(len(pinned.programs), 1)
        self.assertEqual(
            pinned.programs[0]["ops"][0]["level"],
            {"by": "element_id", "value": int(numeric_src)},
            "ссылка не переведена в by=element_id — лекарство не то")

    def test_the_mode_the_mission_needs_is_built_and_its_border_is_named(self):
        """🔴 THE GUARD CORRECTLY WENT RED ON 2026-08-23: THE LAW HOLDS,
        THE MECHANISM CHANGED.

        `test_the_mode_the_mission_needs_is_named_and_refused` used to
        stand here and assert the opposite:

            with self.assertRaises(MaterializeError):
                leaves_to_program([], mode="fresh_document")

        The claim was true exactly as long as the mode did not exist, and
        it was set up NOT for the sake of refusing but so that "a building
        together with its document" would not be designed all over again.
        The mode has been built — meaning the record must say what is now
        true, not disappear: removing the guard would leave a hole where
        memory used to stand.

        WHAT IS PROTECTED NOW. Not "the mode exists," but the BOUNDARY
        beyond which it is still powerless — because powerlessness not
        named as a number reads as capability. A catalog reference is
        accepted by name only for the `sel` kind; the `target_w` kind (a
        view, a tag/text/dimension type) has no name at all. Measured
        08-23 on MNVNK K6: 2 761 operations drop out of 19 041, and it is
        EXACTLY three kinds — `create_tag` 1 285, `create_text` 809,
        `create_dimension` 667, each ENTIRELY. Not a single geometric
        operation drops out.
        """
        # Geometry TRAVELS, and travels by name.
        built = leaves_to_program(
            validate_l1_nodes([_wall(0, EXISTING_LEVEL)]),
            mode="fresh_document")
        self.assertEqual(
            built.programs[0]["ops"][0]["level"],
            {"by": "name", "value": "Этаж 1"},
            "каталожная ссылка обязана ехать ИМЕНЕМ, а не ElementId чужого "
            "документа")
        self.assertEqual(built.stats.as_dict()["document_bound_ops"], 0)

        # Annotation does NOT travel, and says so in a typed way.
        bound = leaves_to_program(
            validate_l1_nodes([_node("create_text", "S-TEXT-1", {
                "in_view": {"by": "name", "value": "План 1", "_id": "31337"},
                "at": [0, 0],
                "content": "примечание",
                "text_type": {"by": "name", "value": "3.5мм", "_id": "31338"},
            }, level_name="Этаж 1")]),
            mode="fresh_document")
        self.assertEqual(bound.programs, [])
        self.assertEqual(
            [skip.reason for skip in bound.skipped], ["document_bound:in_view"])

    def test_two_created_datums_split_the_building(self):
        """The ceiling is "per component," not absolute: 402 ops → two
        programs."""
        half = 200
        second = "S-LEVEL-2"
        leaves = [_level(), _level(second, "Этаж 2", 3000)]
        leaves += [_wall(i, {"ref": LEVEL_ID}) for i in range(half)]
        leaves += [_wall(1000 + i, {"ref": stable_l1_id("op", second)})
                   for i in range(half)]
        sizes = _sizes(_materialize(leaves))
        self.assertEqual(len(sizes), 2)
        self.assertLessEqual(max(sizes), MAX_BULK_OPS)


if __name__ == "__main__":
    unittest.main()
