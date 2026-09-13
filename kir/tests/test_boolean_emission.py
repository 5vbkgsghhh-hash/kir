"""EMISSION OF THE BOOLEAN — the one thing the law never had: it was a
pure function.

`test_boolean_witness_law.py` checks the LAW (`witness_verdict`,
`degenerate_reason`) — pure functions over four numbers. It knows not a
single line of C# and should not. This file checks something DIFFERENT,
exactly what sits between the law and Revit: that emission actually
calls the boolean, actually builds the intersection at EVERY step, and
actually refuses BEFORE the effect.

🔴 WHY THEY ARE SEPARATE. A law proven on numbers, paired with an
emission that never collects those numbers, produces a GREEN over empty
ground: what gets checked never runs. This is exactly how it was found
on 20.08 that `create_directshape` with the MESH sub-language had been
shipping since 29.07 and had never once been called — the capability sat
unused for a month, because nobody looked at the gap between "built" and
"called."
"""
from __future__ import annotations

import unittest

from kir import boolean_emit
from kir.compiler import compile_program
from kir.ops_boolean import (BOOLEAN_DISJOINT, BOOLEAN_NESTED,
                                  BOOLEAN_PARTS_MAX, BOOLEAN_PARTS_MIN,
                                  PART_SHAPES, validate_parts)

_RECT = {"outer": {"shape": "rect", "origin": [0, 0], "size_mm": [4000, 4000]}}
_SPHERE = {"shape": "sphere", "center_mm": [2000, 2000, 4000],
           "radius_mm": 2400.0}
_CYL = {"shape": "cylinder", "center_mm": [1000, 1000, 1500],
        "radius_mm": 900.0, "height_mm": 3000.0}
_BOX = {"shape": "box", "center_mm": [3000, 3000, 3000],
        "size_mm": [2000, 2000, 2000]}


def _program(operation: str = "difference", parts=None, oid: str = "B1") -> dict:
    return {"ir_version": "1.0", "ops": [{
        "op": "create_solid_boolean", "id": oid, "operation": operation,
        "profile": _RECT, "height_mm": 4000.0,
        "parts": list(parts if parts is not None else [_SPHERE]),
        "category": "generic_model", "name": "проба"}]}


def _cs(operation: str = "difference", parts=None) -> str:
    out = compile_program(_program(operation, parts), revit_version="2026")
    if not out.ok:
        raise AssertionError("программа отвергнута: "
                             + "; ".join(str(d.message_ru) for d in out.diagnostics))
    return out.csharp


class TheOperationActuallyReachesRevit(unittest.TestCase):
    """The op calls the BOOLEAN, rather than building something similar
    off to the side."""

    def test_each_operation_emits_its_own_member(self) -> None:
        for name, member in (("union", "Union"), ("difference", "Difference"),
                             ("intersect", "Intersect")):
            with self.subTest(name):
                cs = _cs(name)
                self.assertIn(
                    f"BooleanOperationsUtils.ExecuteBooleanOperation("
                    f"__acc_B1, __prt_B1_0, BooleanOperationsType.{member})", cs)

    def test_the_NON_modifying_overload_is_used(self) -> None:
        """🔴 `...ModifyingOriginalSolid` IS FORBIDDEN, and this is an
        api_traps measurement.

        The modifying variants carry a throw condition the plain one
        does not: "Thrown when the original solid object is the geometry
        of the Revit model." We build our own bodies, so hitting it
        formally is hard — but there is no reason to choose an overload
        with one extra throw condition, and a silent drift toward it
        must be caught.
        """
        cs = _cs()
        self.assertNotIn("ModifyingOriginalSolid", cs)


class TheAuxiliaryBodyIsBuiltByADifferentCall(unittest.TestCase):
    """🔴 THE LAW THE ENTIRE WITNESS RESTS ON, AND IT WAS VIOLATED.

    The identity needs FOUR volumes, two of which come from DIFFERENT
    kernel calls. The first draft of the emission built the helper
    intersection body independently of the operation — and for
    `intersect` it compared `Intersect(A,B)` against `Intersect(A,B)`. A
    deterministic function always equals itself: the witness existed,
    printed in the certificate, and COULD NOT FAIL.

    Hence the law: the helper enum member must DIFFER from the
    operation's own member. Below this is checked on all three, not just
    the one where the bug was found.
    """

    AUX = {"union": "Intersect", "difference": "Intersect",
           "intersect": "Union"}

    def test_the_auxiliary_member_differs_from_the_operation(self) -> None:
        for name, aux in self.AUX.items():
            with self.subTest(name):
                cs = _cs(name)
                self.assertIn(f"Solid __bau_B1_0 = BooleanOperationsUtils"
                              f".ExecuteBooleanOperation(__acc_B1, __prt_B1_0, "
                              f"BooleanOperationsType.{aux})", cs)
                self.assertNotEqual(
                    aux, {"union": "Union", "difference": "Difference",
                          "intersect": "Intersect"}[name],
                    "вспомогательное тело строится тем же вызовом, что и "
                    "результат — тождество не сможет провалиться")

    def test_every_step_builds_its_own_auxiliary(self) -> None:
        cs = _cs("difference", [_SPHERE, _CYL, _BOX])
        for i in range(3):
            self.assertIn(f"Solid __bau_B1_{i} = BooleanOperationsUtils"
                          f".ExecuteBooleanOperation(__acc_B1, __prt_B1_{i}, "
                          f"BooleanOperationsType.Intersect)", cs)

    def test_the_auxiliary_precedes_the_operation_where_it_can(self) -> None:
        """The order carries weight: the precondition must refuse
        BEFORE the effect.

        For `union`/`difference` the helper body is the intersection,
        and it is built FIRST. For `intersect` the intersection's volume
        IS the result's volume, so the precondition physically cannot
        stand before it; but the refusal still comes before the effect —
        the `Solid` lives in memory, and the element is created further
        down the stream.
        """
        for name in ("union", "difference"):
            with self.subTest(name):
                cs = _cs(name, [_SPHERE, _CYL])
                for i in range(2):
                    self.assertLess(cs.index(f"Solid __bau_B1_{i} ="),
                                    cs.index(f"Solid __brs_B1_{i} ="))
        cs = _cs("intersect")
        self.assertLess(cs.index("Math.Min(__bva_B1[0]"),
                        cs.index("DirectShape.CreateElement"),
                        "предусловие обязано стоять до создания ЭЛЕМЕНТА")

    def test_all_four_volumes_come_from_revit(self) -> None:
        """Not a single number of OUR OWN: all four quantities are read
        off Revit bodies."""
        cs = _cs()
        for expr in ("__acc_B1.Volume", "__prt_B1_0.Volume",
                     "__bau_B1_0 == null ? 0.0 : __bau_B1_0.Volume",
                     "__brs_B1_0.Volume"):
            self.assertIn(expr, cs)


class TheDegeneracyRefusalHappensBeforeAnyEffect(unittest.TestCase):
    """Degeneracy is a refusal FROM THE OP, not a witness failure: the
    fixes are different."""

    def test_both_codes_are_emitted_with_their_own_text(self) -> None:
        cs = _cs()
        self.assertIn(BOOLEAN_DISJOINT, cs)
        self.assertIn(BOOLEAN_NESTED, cs)

    def test_the_guards_stand_before_the_boolean_call(self) -> None:
        cs = _cs()
        self.assertLess(cs.index(BOOLEAN_DISJOINT),
                        cs.index("BooleanOperationsType.Difference"))
        self.assertLess(cs.index(BOOLEAN_NESTED),
                        cs.index("BooleanOperationsType.Difference"))
        # And for all three — before the ELEMENT is created, which is
        # the actual effect.
        for name in ("union", "difference", "intersect"):
            with self.subTest(name):
                c = _cs(name)
                self.assertLess(c.index(BOOLEAN_DISJOINT),
                                c.index("DirectShape.CreateElement"))

    def test_the_nested_guard_compares_against_the_SMALLER_body(self) -> None:
        """`Math.Min`, not "against the base": either of the two can be
        the one nested inside."""
        self.assertIn("Math.Min(__bva_B1[0], __bvb_B1[0])", _cs())

    def test_the_vacuity_guard_compares_tolerance_to_the_intersection(self) -> None:
        """A tolerance no smaller than the intersection is a check that
        cannot fail."""
        self.assertIn("if (__bdl_B1[0] >= __bvi_B1[0])", _cs())


class TheToleranceIsDerivedFromRevitsOwnNumbers(unittest.TestCase):

    def test_delta_is_vertex_tolerance_plus_emission_quantum(self) -> None:
        from kir import contour as C
        cs = _cs()
        self.assertIn("__dtq_B1 = MM(doc.Application.VertexTolerance) + "
                      f"{C.EMIT_COORD_QUANTUM_MM!r}", cs)

    def test_the_step_tolerance_sums_FOUR_surface_areas(self) -> None:
        """The identity sums four MEASURED volumes — so the residual
        cannot be smaller than the sum of the four individual errors."""
        cs = _cs()
        for expr in ("__acc_B1.SurfaceArea", "__prt_B1_0.SurfaceArea",
                     "__bau_B1_0.SurfaceArea", "__brs_B1_0.SurfaceArea"):
            self.assertIn(expr, cs)


class TheTwoLawsAreSeparateWitnesses(unittest.TestCase):
    """The identity and the direction are DIFFERENT obligation keys.

    Under one shared key, removing either of the two assertions would go
    unnoticed by anyone: the key proves that a line exists, not WHAT it
    asserts.
    """

    def _keys(self, operation: str = "difference") -> list[str]:
        op = _program(operation)["ops"][0]
        op["__region__"] = compile_program(
            _program(operation), revit_version="2026").grounded_ops[0]["__region__"]
        _, _, checks, _ = boolean_emit.emit_solid_boolean(op, "2026", "st")
        return [c.obligation_key for c in checks]

    def test_identity_and_direction_have_distinct_keys(self) -> None:
        keys = self._keys()
        self.assertIn("boolean_identity", keys)
        self.assertIn("boolean_direction", keys)
        self.assertEqual(len(keys), len(set(keys)), "ключи обязательств повторились")


class TheEmittedLocalsAreExactlyTheOnesRead(unittest.TestCase):
    """CS0219: a declared and unread variable is a warning, and under a
    "warning = error" build, otherwise-correct emission would stop
    compiling.

    As a side effect, the `_NEEDS` table reads as a claim about the LAW
    itself: the intersection does not need the base's volume, and this
    is visible, not inferred."""

    def test_no_declared_local_goes_unread(self) -> None:
        import re
        for operation in ("union", "difference", "intersect"):
            with self.subTest(operation):
                cs = _cs(operation)
                for block in re.findall(r"for \(int __bi = 0.*?\n            \}",
                                        cs, re.S):
                    declared = set(re.findall(r"double (__\w+) = __bv", block))
                    for name in declared:
                        uses = len(re.findall(rf"(?<![\w]){re.escape(name)}(?![\w])",
                                              block))
                        self.assertGreater(
                            uses, 1,
                            f"{operation}: {name} объявлена и не прочитана "
                            f"(CS0219)")


class TheChainThreadsTheAccumulator(unittest.TestCase):

    def test_each_step_feeds_the_next(self) -> None:
        cs = _cs("difference", [_SPHERE, _CYL, _BOX])
        for i in range(3):
            self.assertIn(f"__acc_B1 = __brs_B1_{i};", cs)
        self.assertIn("__sol_B1 = __acc_B1;", cs)

    def test_arrays_are_sized_by_the_part_count(self) -> None:
        cs = _cs("difference", [_SPHERE, _CYL, _BOX])
        for arr in ("__bva", "__bvb", "__bvi", "__bvr", "__bvx", "__bdl"):
            self.assertIn(f"double[] {arr}_B1 = new double[3];", cs)


class ThePrimitivesUseTheFactoryTheirShapeNeeds(unittest.TestCase):

    def test_sphere_is_a_revolve_and_touches_the_axis(self) -> None:
        cs = _cs("difference", [_SPHERE])
        self.assertIn("GeometryCreationUtilities.CreateRevolvedGeometry", cs)
        self.assertIn("XYZ.BasisX, XYZ.BasisZ", cs)   # profile in the XZ plane

    def test_cylinder_is_a_circle_of_TWO_arcs_extruded(self) -> None:
        """CurveLoop does not accept a closed curve as a single piece:
        the endpoints of a segment must differ. Two arcs of π each is
        the minimal honest split, not a sampling — Revit's arc is
        exact."""
        cs = _cs("difference", [_CYL])
        self.assertEqual(cs.count("Arc.Create(__pc_B1_0"), 2)
        self.assertIn("GeometryCreationUtilities.CreateExtrusionGeometry", cs)

    def test_box_is_four_bound_lines(self) -> None:
        cs = _cs("difference", [_BOX])
        self.assertEqual(cs.count("__plp_B1_0.Append(Line.CreateBound("), 4)


class ThePartTableIsClosed(unittest.TestCase):
    """An extra field is an ERROR, not ignorable noise: "gave
    radius_mm for a box" means the author was thinking of a different
    shape."""

    def _diags(self, parts) -> list:
        d: list = []
        validate_parts(parts, "B1", "parts", 0, d)
        return d

    def test_a_healthy_list_normalises(self) -> None:
        d: list = []
        out = validate_parts([dict(_SPHERE)], "B1", "parts", 0, d)
        self.assertEqual(d, [])
        self.assertEqual(out, [{"shape": "sphere",
                                "center_mm": [2000.0, 2000.0, 4000.0],
                                "radius_mm": 2400.0}])

    def test_an_unknown_shape_names_the_closed_table(self) -> None:
        d = self._diags([{"shape": "torus", "center_mm": [0, 0, 0],
                          "radius_mm": 500}])
        self.assertTrue(d)
        self.assertTrue(all(s in d[0].message_ru for s in PART_SHAPES))

    def test_an_extra_field_is_refused(self) -> None:
        bad = dict(_BOX, radius_mm=500.0)
        self.assertTrue(self._diags([bad]))

    def test_a_missing_field_is_refused(self) -> None:
        bad = {k: v for k, v in _CYL.items() if k != "height_mm"}
        self.assertTrue(self._diags([bad]))

    def test_too_few_and_too_many_parts_are_refused(self) -> None:
        self.assertTrue(self._diags([]))
        self.assertTrue(self._diags([dict(_SPHERE)] * BOOLEAN_PARTS_MAX))

    def test_the_bounds_come_from_ops_solid_not_from_here(self) -> None:
        """Two tables that must match drift apart silently."""
        from kir.ops_boolean import part_extent_bounds
        from kir.ops_solid import MAX_EXTENT_MM, MIN_EXTENT_MM
        self.assertEqual(part_extent_bounds(), (MIN_EXTENT_MM, MAX_EXTENT_MM))

    def test_a_size_out_of_bounds_is_refused(self) -> None:
        """🔴 THE BOUND IS TAKEN FROM `ops_solid`, NOT WRITTEN HERE AS A
        LITERAL.

        This used to say `size_mm=[1.0, ...]` — "1 mm is well below the
        minimum." On 21.08, `MIN_EXTENT_MM` was lowered from 100 to 1 by
        a live measurement, and the test TURNED RED, proving exactly
        what its neighbor
        `test_the_bounds_come_from_ops_solid_not_from_here` was written
        against: two numbers that must match drift apart silently. There
        is no literal here anymore.
        """
        from kir.ops_boolean import part_extent_bounds
        lo, hi = part_extent_bounds()
        self.assertTrue(self._diags([{"shape": "box", "center_mm": [0, 0, 0],
                                      "size_mm": [lo / 2.0, 1000.0, 1000.0]}]))
        self.assertTrue(self._diags([{"shape": "box", "center_mm": [0, 0, 0],
                                      "size_mm": [hi * 2.0, 1000.0, 1000.0]}]))


class TheReceiptCarriesTheRawFours(unittest.TestCase):
    """`Solid.Volume`'s own error on curved surfaces is documented
    nowhere, and for a boolean, curves appear starting with the very
    first sphere."""

    def test_every_step_reports_its_four_volumes_and_its_tolerance(self) -> None:
        cs = _cs("difference", [_SPHERE, _CYL])
        for i in range(2):
            for key in ("v_base_mm3", "v_part_mm3", "v_intersection_mm3",
                        "v_result_mm3", "v_auxiliary_mm3", "tolerance_mm3"):
                self.assertIn(f'__rb["step{i}_{key}"]', cs)

    def test_the_honest_label_is_written(self) -> None:
        cs = _cs()
        self.assertIn('__rb["bim_semantics"] = "none";', cs)
        self.assertIn('__rb["schedulable_as_building_element"] = false;', cs)


if __name__ == "__main__":
    unittest.main()


def _lowered(region):
    """The nested region — via the same pure function the compiler
    itself calls."""
    from kir import contour as C
    out = C.validate_region(region, None, "B1", "profile", [])
    assert out is not None
    return out


def _normalised(parts):
    from kir.ops_boolean import validate_parts as _vp
    out = _vp(list(parts), "B1", "parts", 0, [])
    assert out is not None
    return out


_PRISM = {"shape": "prism",
          "profile": {"outer": {"shape": "poly",
                                "points_mm": [[1000, 1000], [3000, 1000],
                                              [3000, 3000], [1000, 3000]]}},
          "height_mm": 2000.0, "base_z_mm": 500.0}
_PRISM_ON_A_WALL = {
    "shape": "prism",
    "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                          "size_mm": [1000, 1000]}},
    "height_mm": 1500.0,
    "plane": {"origin_mm": [1500.0, 0.0, 1000.0], "normal": [0.0, -1.0, 0.0],
              "x_dir": [1.0, 0.0, 0.0]}}


class ThePrismPartIsTheFOURTHKindOfOperand(unittest.TestCase):
    """🔴 THE WAVE OF 21.08.2026. The earlier law read: "our boolean's
    operands are box/sphere/cylinder, an arbitrary profile cannot be
    said with them," and it cost 64 rejected shapes out of 283 when
    recipes were harvested from a real building.

    The argument behind it is TRUE and stands: a `Solid` in Revit is not
    an element, so the operand must be born and die inside the op, with
    nothing to reference in a neighboring op. The conclusion drawn from
    it is WRONG: a contour with EXPLICIT points is a VALUE, not a
    reference. It is checked entirely offline by the same pure
    `contour.validate_region` that checks the base, and it needs no
    grounding at all.
    """

    def test_a_prism_part_reaches_revit_as_an_extrusion_of_its_own_loops(self) -> None:
        cs = _cs("difference", [_PRISM])
        self.assertIn("Solid __prt_B1_0 = GeometryCreationUtilities"
                      ".CreateExtrusionGeometry(__lps_B1_p0, XYZ.BasisZ, "
                      "U(2000.0));", cs)
        self.assertIn("BooleanOperationsUtils.ExecuteBooleanOperation("
                      "__acc_B1, __prt_B1_0, BooleanOperationsType.Difference)",
                      cs)

    def test_two_prisms_do_not_share_one_loop_variable(self) -> None:
        """🔴 THE RING'S NAME CARRIES THE PART NUMBER, AND THIS IS NOT
        COSMETIC.

        `_loops_cs` prints `__ol_<s>`; without the part number, two
        prisms in one op would declare the SAME name twice — CS0128 at
        build time, and silently the FIRST ring for both, before that.
        """
        cs = _cs("difference", [_PRISM, _PRISM_ON_A_WALL])
        self.assertIn("__ol_B1_p0", cs)
        self.assertIn("__ol_B1_p1", cs)
        self.assertEqual(cs.count("CurveLoop __ol_B1_p0 = new CurveLoop();"), 1)
        self.assertEqual(cs.count("CurveLoop __ol_B1_p1 = new CurveLoop();"), 1)

    def test_a_prism_on_a_plane_extrudes_along_the_NORMAL_not_along_Z(self) -> None:
        """With `XYZ.BasisZ` the body would become a SKEWED prism, and
        on a wall's vertical face it would degenerate to ZERO. The same
        argument, verbatim, applies to the extrusion."""
        cs = _cs("difference", [_PRISM_ON_A_WALL])
        self.assertIn("CreateExtrusionGeometry(__lps_B1_p0, "
                      "new XYZ(0.0, -1.0, 0.0), U(1500.0));", cs)
        self.assertIn("__pf_tf_B1_p0.BasisZ = new XYZ(0.0, -1.0, 0.0);", cs)

    def test_the_witness_gained_NO_new_obligation(self) -> None:
        """🔴 THE WAVE'S MAIN CLAIM, AND IT IS CHECKED, NOT DECLARED.

        The boolean does not predict volume analytically: it compares
        FOUR numbers, all computed by Revit itself. The kind of part has
        nothing to change there — which means the list of obligation
        keys for a prism must match the list for a sphere DOWN TO THE
        CHARACTER.
        """
        # The obligation keys are read FROM THE EMITTER ITSELF, not
        # hunted for in the C# text: they are not in the text — they
        # travel into the certificate.
        from kir import boolean_emit as BE

        def keys(parts):
            op = dict(_program("difference", parts)["ops"][0])
            op["__region__"] = _lowered(op["profile"])
            op["parts"] = _normalised(parts)
            _decl, _create, checks, _rb = BE.emit_solid_boolean(op, "2026", "st")
            return sorted(check.obligation_key for check in checks)

        self.assertEqual(keys([_PRISM]), keys([_SPHERE]))
        self.assertEqual(keys([_PRISM]),
                         ["boolean_direction", "boolean_identity",
                          "solid_count"])

    def test_the_receipt_carries_the_prism_bbox_from_its_own_contour(self) -> None:
        cs = _cs("difference", [_PRISM])
        self.assertIn('__rb["step0_shape"] = "prism";', cs)
        self.assertIn("1000.0 1000.0 500.0 .. 3000.0 3000.0 2500.0", cs)

    def test_a_spline_in_a_part_is_refused_exactly_as_in_the_BASE(self) -> None:
        """A part that allowed a spline would be MORE PERMISSIVE than
        the base of the SAME op — one op with two different laws for
        one geometry."""
        curvy = {"shape": "prism", "height_mm": 1000.0,
                 "profile": {"outer": {
                     "shape": "poly",
                     "points_mm": [[1000, 1000], [3000, 1000], [3000, 3000],
                                   [1000, 3000]],
                     "splines": [{"edge": 0, "via_mm": [[2000, 1200]]}]}}}
        d: list = []
        self.assertIsNone(validate_parts([curvy], "B1", "parts", 0, d))
        self.assertTrue(d)
        self.assertIn("сплайн", d[0].message_ru)

    def test_plane_and_base_z_together_are_refused_in_a_PART_too(self) -> None:
        """The law is addressed to the KIND, not to the op's name: two
        ways of saying the same thing."""
        both = dict(_PRISM_ON_A_WALL, base_z_mm=100.0)
        d: list = []
        self.assertIsNone(validate_parts([both], "B1", "parts", 0, d))
        self.assertTrue(any("base_z_mm" in x.message_ru for x in d))

    def test_a_grid_anchor_in_a_part_contour_is_refused_by_CONTOUR_itself(self) -> None:
        """The part has no grounding by construction — so it has no
        axis pool either. The refusal comes from `contour`, not from
        our own copy of its rule."""
        gridded = {"shape": "prism", "height_mm": 1000.0,
                   "profile": {"outer": {"shape": "rect",
                                         "origin": {"at_grid": ["A", "1"]},
                                         "size_mm": [1000, 1000]}}}
        d: list = []
        self.assertIsNone(validate_parts([gridded], "B1", "parts", 0, d))
        self.assertTrue(d)

    def test_the_BASE_may_stand_on_a_plane_too(self) -> None:
        """The base and the part are ONE geometry. A plane check for one
        but not the other would mean two ways of saying the same
        prism."""
        program = _program("difference", [_SPHERE])
        program["ops"][0]["plane"] = {"origin_mm": [0.0, 0.0, 1000.0],
                                      "normal": [0.0, -1.0, 0.0],
                                      "x_dir": [1.0, 0.0, 0.0]}
        out = compile_program(program, revit_version="2026")
        self.assertTrue(out.ok, [str(d.message_ru) for d in out.diagnostics])
        self.assertIn("CreateExtrusionGeometry(__lps_B1, "
                      "new XYZ(0.0, -1.0, 0.0), U(4000.0));", out.csharp)

    def test_WITHOUT_a_plane_the_emission_is_byte_identical(self) -> None:
        """Absence stays absence: not a single extra transform, not a
        single changed literal — the parity ratchet's requirement."""
        cs = _cs("difference", [_SPHERE])
        self.assertIn("CreateExtrusionGeometry(__lps_B1, XYZ.BasisZ, "
                      "U(4000.0));", cs)
        self.assertNotIn("__pf_tf_B1 ", cs)


class ThePrismPartSurvivesTheFOURPLACESAValueKindLivesIn(unittest.TestCase):
    """🔴 CANON 20.08: a value's kind lives in FOUR places —
    CANONICALIZATION, emission, the witness, the backward turn — and the
    first and the fourth are never recalled together. This is exactly
    how the spline lost its kind; `ref_dir`, declared as `pt_xyz`, ended
    up shifted like a point (`[-1,0,0]` -> `[-1001,-500,0]`). Here all
    four are named and three of them are checked, and the fourth is
    named a HOLE rather than passed over in silence.
    """

    def test_1_CANONICALISATION_the_part_is_plain_json_and_equal_to_itself(self) -> None:
        """A value must survive `json.dumps -> json.loads` UNCHANGED: a
        tuple travels out as an array and comes back as a LIST, meaning
        a plan read back from its signature would stop being equal to
        itself."""
        import json
        norm = _normalised([_PRISM, _PRISM_ON_A_WALL])
        self.assertEqual(json.loads(json.dumps(norm)), norm)
        # And the plan's signature must be STABLE: the same program,
        # compiled twice, gives the same C# down to the byte.
        self.assertEqual(_cs("difference", [_PRISM, _PRISM_ON_A_WALL]),
                         _cs("difference", [_PRISM, _PRISM_ON_A_WALL]))

    def test_4_REVERSE_the_kind_is_NOT_in_MM_KINDS_and_that_is_NAMED(self) -> None:
        """🔴 THE FOURTH PLACE IS A NAMED HOLE, NOT A SOLUTION.

        `program_source._round_mm` rounds every list of numbers inside a
        value of MILLIMETER kind to a whole millimeter, and `_shift`
        subtracts the local frame's origin from every list of length
        2-3. For a prism this would touch both the contour's points and
        the plane's DIRECTIONS (`normal`, `x_dir`) — exactly the pattern
        by which `ref_dir` turned into a point.

        Today `solid_parts` is NOT in `MM_KINDS`, so the backward turn
        does not touch the part AT ALL: coordinates are not rounded and
        do not move into the local frame. This is recorded HERE as a
        live assertion, not as prose in a comment, because adding the
        kind to `MM_KINDS` without sorting out `FREE_KEYS` would
        silently break the prism — and it will turn red right here.
        """
        from kir.decompile import program_source as ps
        self.assertNotIn("solid_parts", ps.MM_KINDS)
        self.assertNotIn("solid_parts", ps.DEG_KINDS)
        # And if the kind ever lands there — the plane's directions must
        # be in `FREE_KEYS`, or `_round_mm` will turn a normal of
        # [0.7071, 0.7071, 0] into the vector [1.0, 1.0, 0.0].
        self.assertIn("normal", ps.FREE_KEYS)
        self.assertIn("x_dir", ps.FREE_KEYS)
