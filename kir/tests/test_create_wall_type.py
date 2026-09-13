"""`create_wall_type` — a wall type with a SPECIFIED LAYER MAKEUP.

WHY THE OP EXISTS, IN NUMBERS. The author's K3 apartment, sent into a
clean «Проект1» on 23.08.2026: 29 operations, 9 would have made it
through, 20 blocked — and TWELVE of those are ALL the apartment's walls
that have no type at their destination (0 out of 185).

WHY A LAYER MAKEUP, NOT A SINGLE THICKNESS. Measurement on K1: of 44 wall
types, 40 carry a composition, 18 of them COMPOUND (>1 layer) = 41%. A
type created from a single thickness would give the right name and the
right volume with the wrong layer makeup, and there would be NOTHING to
catch it with: the `create_wall` witness stays silent about the type,
`verify.json` does not read layers, and the clash shell takes
`WallType.Width` — which stays CORRECT even after the substitution.
"""
from __future__ import annotations

import unittest

from kir import authoring, ground as ground_mod, spec
from kir.compiler import _parse_and_check
from kir.diag import KirRefusal
from kir.registry_base import (
    WALL_LAYER_FUNCTIONS, WALL_LAYER_MAX_MM, WALL_LAYERS_MAX,
)
from kir.tests.fixtures import GROUND_SNAPSHOT

_SRC = {"by": "element_id", "value": 4001}


def _prog(layers, name="КИР_Пробный", with_wall=False, host_kind=None):
    ops = [{"op": "create_wall_type", "id": "WT1", "source_type": _SRC,
            "new_name": name, "layers": layers}]
    if host_kind is not None:
        ops[0]["host_kind"] = host_kind
    if with_wall:
        ops.append({"op": "create_wall", "id": "W1",
                    "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
                    "level": {"by": "element_id", "value": 42},
                    "type": {"by": "ref", "value": "WT1"}})
    return {"ir_version": "1.0", "ops": ops}


def _emit(layers, **kw):
    plan = _parse_and_check(_prog(layers, **kw))
    return authoring.emit_program(
        ground_mod.ground(plan, GROUND_SNAPSHOT), "2024")


class Registry(unittest.TestCase):
    def test_op_is_its_own_not_an_extension_of_create_type(self):
        """THE RESULT IS DIFFERENT — and that is an argument, not a taste.

        `create_type` returns a `FamilySymbol`; a wall type IS NOT one, and
        its emitter casts `as FamilySymbol`. Merging them would mean giving
        one name two ontologies — exactly the sickness counted on 23.08: of
        the 51 parameter names shared by two or more ops, 25 disagree.
        """
        wt = spec.OPS["create_wall_type"]
        ct = spec.OPS["create_type"]
        self.assertNotEqual(wt.result.reference_kind, ct.result.reference_kind)
        self.assertEqual(wt.result.reference_kind.value, "wall_type")

    def test_tolerance_is_declared_where_the_witness_claims_it(self):
        """`tol_key` must be the truth — the `create_type` defect ("a
        reference into the void") was fixed for exactly this."""
        self.assertIn("layer_mm", spec.OPS["create_wall_type"].tolerances)

    def test_wall_accepts_a_reference_to_a_type_made_here(self):
        """Without this the op is useless: grounding resolves catalog names
        against a snapshot taken BEFORE the run, and a type created within
        this same program is not in it."""
        p = next(p for p in spec.OPS["create_wall"].params if p.name == "type")
        self.assertEqual([k.value for k in p.ref_kinds], ["wall_type"])


class LayerValidation(unittest.TestCase):
    def test_layer_functions_are_revit_enum_not_our_shortlist(self):
        for fn in ("Structure", "Membrane", "StructuralDeck", "None"):
            self.assertIn(fn, WALL_LAYER_FUNCTIONS)

    def test_unknown_function_is_refused(self):
        with self.assertRaises(KirRefusal):
            _parse_and_check(_prog([{"width_mm": 80.0, "function": "Пирог"}]))

    def test_empty_material_name_is_refused_but_absent_key_is_legal(self):
        """THE ABSENCE of a key is a legitimate layer with no material
        (`InvalidElementId`). AN EMPTY string is "there is a name and it is
        empty" — a fabrication.
        """
        cs = _emit([{"width_mm": 80.0, "function": "Structure"}])
        self.assertIn("ElementId.InvalidElementId", cs)
        with self.assertRaises(KirRefusal):
            _parse_and_check(
                _prog([{"width_mm": 80.0, "function": "Structure",
                        "material": "   "}]))

    def test_zero_width_membrane_is_legal(self):
        """A membrane in Revit has zero thickness BY CONSTRUCTION; "strictly
        greater than zero" would reject a legitimate layer."""
        cs = _emit([{"width_mm": 0.0, "function": "Membrane"},
                    {"width_mm": 200.0, "function": "Structure"}])
        self.assertIn("MaterialFunctionAssignment.Membrane", cs)

    def test_bounds_are_behaviour_not_a_literal_comparison(self):
        """Ceilings are checked against the validator's BEHAVIOR at the
        boundary, not by comparing literal to literal — otherwise it is the
        same sickness, just wearing a test."""
        ok = [{"width_mm": 10.0, "function": "Substrate"}] * WALL_LAYERS_MAX
        _parse_and_check(_prog(ok))
        with self.assertRaises(KirRefusal):
            _parse_and_check(_prog(ok + [{"width_mm": 10.0,
                                          "function": "Substrate"}]))
        with self.assertRaises(KirRefusal):
            _parse_and_check(_prog([{"width_mm": WALL_LAYER_MAX_MM + 1.0,
                                     "function": "Substrate"}]))

    def test_extra_layer_key_is_refused_not_ignored(self):
        with self.assertRaises(KirRefusal):
            _parse_and_check(_prog([{"width_mm": 80.0, "function": "Structure",
                                     "цвет": "серый"}]))


class Emission(unittest.TestCase):
    def test_structure_is_built_from_scratch_not_inherited(self):
        """`SetLayers` «completely resets», which is why a FACTORY is used:
        the source's layer makeup is not inherited by even one layer."""
        cs = _emit([{"width_mm": 80.0, "function": "Substrate"}])
        self.assertIn("CompoundStructure.CreateSimpleCompoundStructure", cs)
        self.assertIn("SetCompoundStructure", cs)

    def test_source_kind_is_checked_before_duplicate(self):
        """🔴 THE WHOLE CONDITION IS CHECKED, NOT WORD ORDER.

        The first edition of this test only checked that `WallKind.Basic`
        appears BEFORE `.Duplicate(` — and the mutation `if (false && ...)`
        sailed right through it: the text stayed in place, the check died.
        A guard that cannot be failed by a planted defect guards nothing.
        """
        cs = _emit([{"width_mm": 80.0, "function": "Substrate"}])
        self.assertIn("if (__src_WT1.Kind != WallKind.Basic)", cs)
        self.assertLess(cs.index("WallKind.Basic"), cs.index(".Duplicate("))

    def test_a_same_named_FOREIGN_type_is_NOT_adopted_and_rewritten(self):
        """🔴 A TYPE NAME IS NOT A DOCUMENT-GLOBAL IDENTITY, AND HERE THAT
        COST A SILENT CORRUPTION OF SOMEONE ELSE'S DOCUMENT.

        The repeat-run pre-search looked for a same-named type ONLY by
        Revit class and by name, and then UNCONDITIONALLY called
        `SetCompoundStructure`. Its neighbors already had the law in place:
        `create_type` checks the source's `Family.Id`, `load_family` checks
        the `.rfa` name, and this is pinned down by
        `test_families.py::test_named_type_presearch_is_scoped_to_expected_family`
        in exactly those words. It never reached `create_wall_type`.

        WHY THIS IS WORSE THAN FOR ITS NEIGHBORS. A `FamilySymbol`'s name is
        unique within its FAMILY, and `Duplicate` only throws within that
        family. For system types (`WallType`/`FloorType`/`RoofType`/
        `CeilingType`) the name is unique across the ENTIRE document class —
        meaning a same-named one will ALWAYS be found, including one the
        operator typed in by hand.

        THE COST, REPRODUCED: the name «Кирпич 250» exists in the
        `wall_types` pool of the very grounding snapshot the compiler is
        holding — and the program compiles with `ok=True` and zero
        diagnostics. The six witnesses cannot catch this BY CONSTRUCTION:
        they re-read the type by its OWN Id and check it against the
        REQUESTED one, and after the overwrite everything matches. The
        layer makeup changes for EVERY existing element of that type.
        Silently. Irreversibly.

        The original check required only a kir: prefix. It did not
        distinguish requests from different KIR programs. Now an exact
        marker is required, and reuse changes neither the composition nor
        the marker of an existing type.
        """
        cs = _emit([{"width_mm": 80.0, "function": "Substrate"}])

        # THE NEIGHBOR'S LAW, WORD FOR WORD THE SAME: a pre-search by name alone is forbidden.
        self.assertNotIn(
            "FirstOrDefault(__c => __c.Name ==", cs,
            "предпоиск по ОДНОМУ имени усыновляет чужой тип")

        # A shared kir: prefix is not ownership of this request. Exact marker
        # matching precedes read-only reuse; mutation is duplicate-only.
        self.assertIn("ALL_MODEL_TYPE_COMMENTS", cs)
        self.assertNotIn('StartsWith("kir:")', cs)
        self.assertIn('String.Equals(__owner_WT1, "kir:', cs)
        self.assertIn(':WT1", StringComparison.Ordinal)', cs)
        self.assertIn('if (__dupd_WT1) {\n        try', cs)

        # And a same-named FOREIGN one must give a NAMED refusal, not an overwrite.
        self.assertIn("Count > 1", cs)
        self.assertIn("не принадлежит этому точному запросу", cs)

    def test_ambiguous_material_name_refuses_never_picks_first(self):
        cs = _emit([{"width_mm": 80.0, "function": "Structure",
                     "material": "Бетон"}])
        self.assertIn("Count > 1", cs)
        self.assertIn("неоднозначно", cs)

    def test_no_preflight_validity_claim(self):
        """`CompoundStructure.IsValid` DOES NOT EXIST (0/6 across three
        signatures, an honest control). Emission must not call it."""
        cs = _emit([{"width_mm": 80.0, "function": "Structure"}])
        self.assertNotIn("IsValid", cs)
        self.assertIn("пирог отвергнут Ревитом", cs)

    def test_witness_reads_the_model_not_the_echo(self):
        """The cost of trusting an echo was paid for on 23.08: `load_family`
        was GREEN when families arrived under the names `kir_f1`…`kir_f6`."""
        cs = _emit([{"width_mm": 80.0, "function": "Structure"}])
        self.assertIn("doc.GetElement(__el_WT1.Id) as WallType", cs)
        self.assertIn("GetCompoundStructure()", cs)
        self.assertIn(".GetLayers()", cs)

    def test_witness_covers_width_function_material_and_total(self):
        cs = _emit([{"width_mm": 25.0, "function": "Finish1",
                     "material": "Бетон"},
                    {"width_mm": 55.0, "function": "Structure"}])
        self.assertIn("__exw", cs)
        self.assertIn("__exf", cs)
        self.assertIn("__exm", cs)
        self.assertIn("80.0", cs)          # sum of layers as the expectation for Width

    def test_wall_uses_the_created_type_without_a_stale_guard(self):
        """The element was created in this same transaction — a drift guard
        would be a lie."""
        cs = _emit([{"width_mm": 80.0, "function": "Structure"}],
                   with_wall=True)
        self.assertIn("WallType __wt_W1 = __el_WT1;", cs)


if __name__ == "__main__":
    unittest.main()


class HostKind(unittest.TestCase):
    """THE HOST TYPE KIND (24.08.2026) — the op stopped being only about walls.

    WHY, IN NUMBERS. Moving the K3 building into a clean «Проект1»,
    measured 24.08: 0 of 82 floors built, 0 of 36 roofs, 0 of 18 ceilings —
    even though the operations EXIST and sit in the programs (`create_floor`
    46, `create_roof` 27, `create_ceiling` 1). Each one addresses its type
    BY NAME, and grounding resolves names against a snapshot taken BEFORE
    the run: a type created by this same program is not in it BY
    CONSTRUCTION.

    WHY A PARAMETER, NOT THREE OPS. The constructor and the witness are the
    same across all four classes: `Duplicate` / `GetCompoundStructure` /
    `SetCompoundStructure` — 6/6 on real 2021-2026 builds, against two
    negative controls at 0/6.

    A LIVE RUN ON 24.08.2026, «Проект2», Revit 2026 — built and re-read:
      КИР_Перекрытие_320мм  2 layers, width 320  -> floor   286978
      КИР_Кровля_350мм      2 layers, width 350  -> roof    287018
      КИР_Потолок_70мм      1 layer,  width 70  -> ceiling 287067
    """

    def test_the_default_keeps_every_program_ever_written(self):
        """An omitted `host_kind` must give the SAME BYTES as before it
        existed: the op has a golden sample, and an "improved" letter would
        break emission parity."""
        layers = [{"width_mm": 80, "function": "Substrate"}]
        self.assertEqual(_emit(layers), _emit(layers, host_kind="wall"))

    def test_the_kind_decides_the_reference_kind(self):
        """One kind for four classes would give up exactly the guarantee
        the language exists for: `create_floor.type` would accept a roof
        type statically, and the refusal would come only from Revit."""
        wt = spec.OPS["create_wall_type"]
        for kind, expected in (("wall", "wall_type"), ("floor", "floor_type"),
                               ("roof", "roof_type"), ("ceiling", "ceiling_type")):
            with self.subTest(kind=kind):
                got = wt.result_for({"host_kind": kind}).reference_kind
                self.assertEqual(got.value, expected)
        self.assertEqual(wt.result_for({}).reference_kind.value, "wall_type")

    def test_the_source_is_grounded_in_the_pool_of_its_own_kind(self):
        """`Duplicate` is an INSTANCE method: a roof type is only born from
        a roof type. Searching for a floor type's name among wall types
        would mean refusing with "not found" — a refusal naming the wrong
        cause."""
        wt = spec.OPS["create_wall_type"]
        for kind, pool in (("wall", "wall_types"), ("floor", "floor_types"),
                           ("roof", "roof_types"), ("ceiling", "ceiling_types")):
            with self.subTest(kind=kind):
                got = dict((p, q) for p, q, _r in
                           wt.grounded_for({"host_kind": kind}))
                self.assertEqual(got["source_type"], pool)

    def test_one_authority_for_the_revit_class(self):
        """The keys of `HOST_TYPE_CLASS` ARE the parameter's `choices`. A
        kind set up in one place and forgotten in another must go red, not
        silently build the wrong class."""
        param = next(p for p in spec.OPS["create_wall_type"].params
                     if p.name == "host_kind")
        from kir.registry_base import HOST_TYPE_CLASS
        self.assertEqual(sorted(HOST_TYPE_CLASS), sorted(param.choices))

    def test_a_type_of_the_wrong_kind_is_refused_at_compile_time(self):
        """A NEGATIVE NARROWNESS CONTROL. In C# the substitution would give
        `null` and a refusal AT RUNTIME; here it must die AT COMPILE TIME."""
        layers = [{"width_mm": 80, "function": "Substrate"}]
        floor = {"op": "create_floor", "id": "F1",
                 "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
                 "level": {"by": "element_id", "value": 42},
                 "type": {"by": "ref", "value": "T1"}}
        wall = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                "p1_mm": [6000, 0], "height_mm": 3000,
                "level": {"by": "element_id", "value": 42},
                "type": {"by": "ref", "value": "T1"}}

        def prog(host_kind, consumer):
            head = {"op": "create_wall_type", "id": "T1", "source_type": _SRC,
                    "new_name": "X", "layers": layers}
            if host_kind:
                head["host_kind"] = host_kind
            return {"ir_version": "1.0", "ops": [head, consumer]}

        for host_kind, consumer, what in (
                (None, floor, "перекрытие берёт тип стены"),
                ("floor", wall, "стена берёт тип перекрытия"),
                ("roof", floor, "перекрытие берёт тип кровли")):
            with self.subTest(what=what):
                with self.assertRaises(KirRefusal) as caught:
                    _parse_and_check(prog(host_kind, consumer))
                self.assertEqual(caught.exception.diagnostics[0].code, "KIR-L004")
        # AND JUST AS IMPORTANT: the legitimate case must pass, otherwise
        # "always refuses" would also be a green test.
        for host_kind, consumer in ((None, wall), ("floor", floor)):
            with self.subTest(legal=host_kind or "wall"):
                _parse_and_check(prog(host_kind, consumer))

    def test_the_endcap_comes_from_the_source_not_from_a_literal(self):
        """A MEASUREMENT OF LIVE REVIT, not theory:
        `CreateSimpleCompoundStructure` assembles a layer makeup with a
        WALL end cap, and `FloorType.SetCompoundStructure` rejects it
        verbatim — «Input compound structure has wrong EndCap condition
        for this element type». Compilation stayed silent about it (6/6),
        which is exactly the gap between "compiles" and "executes."

        The value is NOT CHOSEN BY US: `EndCapCondition` has four members
        (all 6/6), and a literal here would be declaring our own knowledge
        of which end cap is legitimate for each kind. It is taken from the
        source whose layer makeup Revit accepted.
        """
        layers = [{"width_mm": 80, "function": "Substrate"}]
        wall_cs = _emit(layers)
        self.assertNotIn("EndCap", wall_cs)
        for kind in ("floor", "roof", "ceiling"):
            with self.subTest(kind=kind):
                cs = _emit(layers, host_kind=kind)
                self.assertIn(
                    "__cs_WT1.EndCap = __src_WT1.GetCompoundStructure().EndCap;",
                    cs)

    def test_the_preflight_reads_what_the_class_actually_carries(self):
        """`Kind` exists ONLY on `WallType` (6/6 against 0/6 for the other
        three). Writing "source kind Basic" where the property does not
        exist would mean promising a check the class doesn't carry. Their
        preflight is the presence of a layer makeup on the source."""
        layers = [{"width_mm": 80, "function": "Substrate"}]
        wall_cs = _emit(layers)
        self.assertIn("WallKind.Basic", wall_cs)
        for kind in ("floor", "roof", "ceiling"):
            with self.subTest(kind=kind):
                cs = _emit(layers, host_kind=kind)
                self.assertNotIn("WallKind.Basic", cs)
                self.assertIn("GetCompoundStructure() == null", cs)

    def test_the_total_width_is_read_where_the_class_keeps_it(self):
        """The other three classes have NO `Width` (0/6) — the sum lives on
        the layer makeup itself, `CompoundStructure.GetWidth()` (6/6)."""
        layers = [{"width_mm": 80, "function": "Substrate"}]
        self.assertIn("MM(__vt_WT1.Width)", _emit(layers))
        for kind in ("floor", "roof", "ceiling"):
            with self.subTest(kind=kind):
                cs = _emit(layers, host_kind=kind)
                self.assertNotIn("MM(__vt_WT1.Width)", cs)
                self.assertIn("MM(__vcs_WT1.GetWidth())", cs)

    def test_the_empty_pool_refusal_names_the_exact_call(self):
        """A REFUSAL THAT COSTS AN EXTRA ROUND IS ALSO A DEFECT.

        The `floor_types` pool is empty in a clean document, and before
        24.08 the refusal said "no KIR operation creates this kind." Now a
        producer exists, but THE OP'S NAME ALONE IS NOT ENOUGH:
        `create_wall_type` without `host_kind` gives a WALL type, and a
        model that read only the name would get a KIR-L004 on the next
        turn. So the refusal must also name the parameter value.
        """
        from kir.ground import _empty_pool_next_move
        for op_name, value in (("create_floor", "floor"), ("create_roof", "roof"),
                               ("create_ceiling", "ceiling"), ("create_wall", "wall")):
            with self.subTest(op=op_name):
                move = _empty_pool_next_move(op_name, "type")
                self.assertIn("create_wall_type", move)
                self.assertIn(f"host_kind={value!r}", move)
        # A NEGATIVE CONTROL: a railing type has no producer, and
        # inventing a move there is forbidden.
        self.assertIn("Ни одна операция KIR не создаёт этот род",
                      _empty_pool_next_move("create_railing", "type"))
