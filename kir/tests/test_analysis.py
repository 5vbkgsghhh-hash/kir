"""The loads-and-egress-routes wave: what must not be broken silently.

Every class here stands against a SPECIFIC quiet-wrong outcome, rather
than against "it might break someday":

* `LoadsExistOnlyWhereTheApiHasThem` — the version axis. A free load
  exists in 2021-2023 and was removed by Autodesk from the API in 2024; if
  someone one day "fixes" the refusal by passing `InvalidElementId`, the
  test MUST fail, because this argument's behavior has never once been
  measured.
* `WitnessReadsTheResult` — the witness reads a PROPERTY OF THE BUILT
  ELEMENT. Checking "the setter ran" is a recurring defect of this
  package, and it passes any ordinary test.
* `OrientationIsPinned` — without a pinned frame of reference, the force
  vector's three numbers mean nothing definite, and a force witness would
  not notice a swapped frame at all.
* `LoadCaseIsMandatory` — a load that landed in the default case looks,
  from outside, indistinguishable from work actually done.
* `BoundaryConditionsAreDeliberatelyAbsent` — a decision, not an
  oversight; exactly the same lock as `create_wire`'s in the MEP wave.
* `ForceToleranceIsDerived` — the tolerance number MUST FOLLOW FROM a
  declared boundary, rather than being typed in by hand.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_analysis_queue.jsonl"))

from kir import spec                                      # noqa: E402
from kir.analysis_emit import (                           # noqa: E402
    ANALYSIS_ZERO_LOAD, _FREE_LOAD_LAST_VER, _plane_normal,
)
from kir.compiler import compile_program                  # noqa: E402
from kir.diag import PARSE_MISSING_FIELD                 # noqa: E402
from kir.reverse_contract import REVERSE_CONTRACTS, ReverseMode  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT            # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
CASE_NAME = {"by": "name", "value": "ДЛ1 Собственный вес"}
CASE_ID = {"by": "element_id", "value": 1500}

POINT_LOAD = {"op": "create_point_load", "id": "PL1", "xyz": [1000, 2000, 3000],
              "fz_n": -10000.0, "mx_nm": 250.0, "load_case": CASE_NAME}
LINE_LOAD = {"op": "create_line_load", "id": "LL1", "p0_mm": [0, 0, 3000],
             "p1_mm": [6000, 0, 3000], "fz_n_per_m": -5000.0,
             "load_case": CASE_ID}
AREA_LOAD = {"op": "create_area_load", "id": "AL1",
             "outline": [[0, 0], [6000, 0], [6000, 4000], [0, 4000]],
             "elev_mm": 3000, "fz_n_per_m2": -3000.0, "load_case": CASE_ID}
PATH = {"op": "create_path_of_travel", "id": "PT1",
        "in_view": {"by": "element_id", "value": 900},
        "p0_mm": [0, 0], "p1_mm": [12000, 5000]}

LOAD_OPS = (POINT_LOAD, LINE_LOAD, AREA_LOAD)


def _compile(op: dict, ver: str = "2023", **extra):
    program = {"ir_version": "1.0", "ops": [op]}
    program.update(extra)
    return compile_program(program, revit_version=ver, snapshot=GROUND_SNAPSHOT)


def _codes(out) -> set:
    return {d.code for d in out.diagnostics}


class LoadsExistOnlyWhereTheApiHasThem(unittest.TestCase):
    """A measurement, not a convention: overloads without a carrier give
    CS1503/CS1501 on 2024-2026 against the reference assemblies, so a
    refusal there is the CORRECT answer."""

    def test_free_loads_emit_up_to_2023_and_refuse_after(self) -> None:
        for op in LOAD_OPS:
            for ver in VERSIONS:
                with self.subTest(op=op["op"], ver=ver):
                    out = _compile(op, ver)
                    if ver <= _FREE_LOAD_LAST_VER:
                        self.assertTrue(out.ok, _codes(out))
                    else:
                        self.assertFalse(out.ok)
                        self.assertEqual(_codes(out), {"KIR-E003"})

    def test_the_refusal_names_the_measurement_and_the_reason(self) -> None:
        """A refusal without a cause sends the repair to the wrong place.
        Here the cause MUST name BOTH the version, AND why InvalidElementId
        will not do."""
        out = _compile(POINT_LOAD, "2026")
        text = " ".join(d.message_ru for d in out.diagnostics)
        for probe in ("2026", "2024", "hostElemId", "InvalidElementId",
                      "аналитического"):
            self.assertIn(probe, text, probe)

    def test_path_of_travel_is_the_one_op_alive_on_all_six(self) -> None:
        for ver in VERSIONS:
            with self.subTest(ver=ver):
                self.assertTrue(_compile(PATH, ver).ok)


class WitnessReadsTheResult(unittest.TestCase):
    """A postcondition confirming merely that the call took place passes
    any test and proves nothing. Here what is checked is that the post
    block carries a READ of a property of the built element."""

    #: (op, program, the lines that MUST stand in the post block).
    EXPECTED = (
        ("create_point_load", POINT_LOAD, (
            "__el_PL1.Point", "__el_PL1.ForceVector", "__el_PL1.MomentVector",
            "__el_PL1.OrientTo", "__el_PL1.LoadCaseId", "__el_PL1.GetTypeId()")),
        ("create_line_load", LINE_LOAD, (
            "__el_LL1.StartPoint", "__el_LL1.EndPoint",
            "__el_LL1.ForceVector1", "__el_LL1.IsUniform",
            "__el_LL1.OrientTo", "__el_LL1.LoadCaseId")),
        ("create_area_load", AREA_LOAD, (
            "__el_AL1.GetLoops()", "__el_AL1.ForceVector1",
            "__el_AL1.OrientTo", "__el_AL1.LoadCaseId")),
        ("create_path_of_travel", PATH, (
            "__el_PT1.PathStart", "__el_PT1.PathEnd",
            "__el_PT1.GetCurves()", "__el_PT1.OwnerViewId")),
    )

    def _post_block(self, op: dict) -> str:
        out = _compile(op, "2023")
        self.assertTrue(out.ok, _codes(out))
        marker = f"// post {op['id']}"
        start = out.csharp.index(marker)
        end = out.csharp.index("// witness", start)
        return out.csharp[start:end]

    def test_every_obligation_reads_a_property_of_the_built_element(self) -> None:
        for name, op, probes in self.EXPECTED:
            block = self._post_block(op)
            for probe in probes:
                with self.subTest(op=name, probe=probe):
                    self.assertIn(probe, block)

    def test_geometry_is_compared_against_revits_own_tolerance(self) -> None:
        """Not a single hand-typed number: the comparison is against
        `doc.Application.VertexTolerance` — the same technique as
        `create_dimension`."""
        for _name, op, _probes in self.EXPECTED:
            with self.subTest(op=op["op"]):
                self.assertIn("doc.Application.VertexTolerance",
                              self._post_block(op))

    def test_the_route_length_is_an_inequality_not_an_equality(self) -> None:
        """Revit computes the route's shape. Only what does not depend on
        its calculation can be asserted: the route is non-empty and no
        shorter than a straight line."""
        block = self._post_block(PATH)
        self.assertIn("__cvs_PT1.Count < 1", block)
        # The straight line between (0,0) and (12000,5000) is exactly
        # 13000 mm, and this is the ONLY number the route assertion has the
        # right to name: it is computed from the requested points, not from
        # Revit's output.
        self.assertIn("__len_PT1 < U(13000.0)", block)
        self.assertNotIn("__len_PT1 ==", block)

    def test_path_z_is_excluded_by_construction_not_by_prose(self) -> None:
        """The API drops the Z of the given points ("set to the view's
        level elevation"). The fact is written into the KIND of the
        parameter, not into a comment."""
        kinds = {p.name: p.kind for p in spec.OPS["create_path_of_travel"].params}
        self.assertEqual(kinds["p0_mm"], "pt_xy")
        self.assertEqual(kinds["p1_mm"], "pt_xy")


class OrientationIsPinned(unittest.TestCase):
    """`ForceVector` is documented as "oriented according to OrientTo
    setting". Without a pinned frame of reference, a force witness would
    read the same triple of numbers in a different system and notice
    nothing."""

    def test_orient_is_set_before_the_vector_is_written(self) -> None:
        for op, prop in ((POINT_LOAD, "ForceVector"),
                         (LINE_LOAD, "ForceVector1"),
                         (AREA_LOAD, "ForceVector1")):
            with self.subTest(op=op["op"]):
                out = _compile(op, "2023")
                cs = out.csharp
                orient = cs.index(f"__el_{op['id']}.OrientTo = ")
                write = cs.index(f"__el_{op['id']}.{prop} = ")
                self.assertLess(orient, write,
                                "система отсчёта обязана быть пришпилена ДО "
                                "записи вектора, иначе проверка ловила бы "
                                "собственный пересчёт Revit")

    def test_an_unpermitted_orientation_is_a_typed_runtime_refusal(self) -> None:
        out = _compile(POINT_LOAD, "2023")
        self.assertIn("IsOrientToPermitted", out.csharp)


class LoadCaseIsMandatory(unittest.TestCase):
    """A load that landed in the default case stands there and looks
    correct, yet participates in the wrong load combinations. From outside
    this is indistinguishable from success."""

    def test_every_load_declares_load_case_required(self) -> None:
        for name in ("create_point_load", "create_line_load", "create_area_load"):
            grounded = dict((p, r) for p, _pool, r in spec.OPS[name].grounded)
            with self.subTest(op=name):
                self.assertTrue(grounded["load_case"])

    def test_a_missing_load_case_is_a_typed_refusal(self) -> None:
        for op in LOAD_OPS:
            bare = {k: v for k, v in op.items() if k != "load_case"}
            with self.subTest(op=op["op"]):
                out = _compile(bare, "2023")
                self.assertFalse(out.ok)
                # Required selectors are a parse/schema invariant: an absent
                # field is rejected before grounding gets a selector to read.
                self.assertEqual(_codes(out), {PARSE_MISSING_FIELD})
                self.assertEqual(
                    {d.field_name for d in out.diagnostics}, {"load_case"})

    def test_an_ambiguous_case_name_refuses_with_candidates(self) -> None:
        """Two cases with one name are normal for a structural project. The
        refusal MUST carry the candidates, otherwise the author has nowhere
        to take the next move from."""
        snap = dict(GROUND_SNAPSHOT)
        snap["load_cases"] = [{"id": 1500, "name": "Снег"},
                              {"id": 1501, "name": "Снег"}]
        prog = {"ir_version": "1.0",
                "ops": [dict(POINT_LOAD, load_case={"by": "name", "value": "Снег"})]}
        out = compile_program(prog, revit_version="2023", snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", _codes(out))
        self.assertTrue(any(d.candidates for d in out.diagnostics))


class ZeroLoadIsRefusedBeforeTheTransaction(unittest.TestCase):
    """Autodesk documents `ArgumentsInconsistentException` for a zero load.
    A runtime exception inside a transaction reads as OUR defect; this is
    the author's error, and it must be named as exactly that."""

    def test_all_zero_components_refuse_typed(self) -> None:
        bare = {"op": "create_point_load", "id": "Z", "xyz": [0, 0, 0],
                "load_case": CASE_ID}
        out = _compile(bare, "2023")
        self.assertFalse(out.ok)
        self.assertEqual(_codes(out), {ANALYSIS_ZERO_LOAD})

    def test_one_nonzero_component_is_enough(self) -> None:
        ok = {"op": "create_point_load", "id": "Z", "xyz": [0, 0, 0],
              "mz_nm": 10.0, "load_case": CASE_ID}
        self.assertTrue(_compile(ok, "2023").ok)


class WorkPlaneIsAuthoredNotInherited(unittest.TestCase):
    """`null` instead of a plane would hand the load's marker over to the
    ACTIVE VIEW, that is, to an input that is not in the program and that,
    on the user's machine, is unknown to us."""

    def test_the_emitter_builds_its_own_sketch_plane(self) -> None:
        for op in (POINT_LOAD, LINE_LOAD):
            with self.subTest(op=op["op"]):
                cs = _compile(op, "2023").csharp
                self.assertIn("SketchPlane.Create(doc, "
                              "Plane.CreateByNormalAndOrigin", cs)

    def test_a_sloped_line_load_gets_a_vertical_plane_through_its_segment(self) -> None:
        """A horizontal plane does not contain a sloped segment, and Revit
        would reject the call inside the transaction. The normal is
        computed in Python."""
        self.assertEqual(_plane_normal((0, 0, 0), (1000, 0, 0)), (0.0, 0.0, 1.0))
        nx, ny, nz = _plane_normal((0, 0, 0), (1000, 0, 500))
        self.assertEqual((round(nx, 9), round(ny, 9), nz), (0.0, -1.0, 0.0))
        # a strictly vertical segment: cross(d, Z) degenerates — the choice is named
        self.assertEqual(_plane_normal((0, 0, 0), (0, 0, 3000)), (1.0, 0.0, 0.0))

    def test_a_vertical_plane_actually_reaches_the_emission(self) -> None:
        sloped = dict(LINE_LOAD, id="LS", p1_mm=[6000, 2000, 4200])
        cs = _compile(sloped, "2023").csharp
        self.assertNotIn("Plane.CreateByNormalAndOrigin(XYZ.BasisZ", cs)
        self.assertIn("Plane.CreateByNormalAndOrigin(new XYZ(", cs)


class PathOfTravelRefusesWhatItCannotAddress(unittest.TestCase):
    def test_in_view_by_ref_is_refused_typed(self) -> None:
        """No KIR op creates a View, so `as View` by reference is a
        guaranteed CS0039, not a coincidence of the model (measured 28.07)."""
        out = _compile(dict(PATH, in_view={"by": "ref", "value": "W1"}), "2023")
        self.assertFalse(out.ok)

    def test_a_non_plan_view_is_guarded_at_runtime(self) -> None:
        cs = _compile(PATH, "2023").csharp
        self.assertIn("ViewType.FloorPlan", cs)
        self.assertIn("IsTemplate", cs)

    def test_a_non_success_status_refuses_before_postconditions(self) -> None:
        """`ResultAffectedByCrop` would return an ELEMENT with a route
        computed against the cropped view — it would still pass the length
        postcondition."""
        cs = _compile(PATH, "2023").csharp
        status = cs.index("PathOfTravelCalculationStatus.Success")
        post = cs.index("// post PT1")
        self.assertLess(status, post)


class BoundaryConditionsAreDeliberatelyAbsent(unittest.TestCase):
    """A DECISION, NOT AN OVERSIGHT — the same lock as `create_wire`'s.

    The three `New*BoundaryConditions` factories exist on all six versions
    and compile; there is still no operation. For the point kind, the sole
    overload takes a `Reference` to the END OF AN ANALYTICAL LINE — the
    frozen KIR reference dialect can name elements, and there is nothing at
    all with which to name that. For the line and area kinds, the host is
    addressable, but the whole point of a support is its six degrees of
    freedom, and there is NOTHING with which to read them back: `BoundaryConditions`
    has not one property about them, and `BOUNDARY_*_RESTRAINT_*` stores an
    integer whose correspondence to `TranslationRotationValue` Autodesk
    does not document.

    Only ONE live measurement can lift this refusal, not a rewording. The
    test stands here so that the next session does not silently ship a
    vacuous version.
    """

    def test_no_boundary_condition_op_exists(self) -> None:
        offenders = [n for n in spec.OPS if "boundary" in n]
        self.assertEqual(offenders, [])

    def test_the_reason_is_written_down_where_the_next_wave_will_look(self) -> None:
        from kir import ops_analysis
        doc = ops_analysis.__doc__ or ""
        for probe in ("NewPointBoundaryConditions", "NewLineBoundaryConditions",
                      "TranslationRotationValue", "BOUNDARY_RESTRAINT_",
                      "WHAT WOULD LIFT THE REFUSAL"):
            self.assertIn(probe, doc, probe)


class ForceToleranceIsDerived(unittest.TestCase):
    """A tolerance typed in by reasoning is this package's defective class
    (`create_door.sill_mm min_val=0`). Here the number MUST FOLLOW FROM the
    declared range boundary and binary floating-point arithmetic."""

    def test_the_number_follows_from_the_declared_bound(self) -> None:
        for name, key in (("create_point_load", "force_n"),
                          ("create_point_load", "moment_nm"),
                          ("create_line_load", "force_n_per_m"),
                          ("create_area_load", "force_n_per_m2")):
            op_spec = spec.OPS[name]
            bound = max(p.max_val for p in op_spec.params if p.kind == "num")
            # The relative error of the path `x -> x*k -> (x*k)/k` in
            # double does not exceed 3*2^-53, accounting for the
            # representation of x itself.
            worst = bound * 3 * 2.0 ** -53
            with self.subTest(op=name, key=key):
                value = op_spec.tolerances[key]
                self.assertGreater(value, worst, "допуск ниже шума арифметики")
                self.assertLess(value, worst * 1000,
                                "допуск на три порядка выше вывода — это уже "
                                "назначенное число, а не выведенное")

    def test_geometry_registers_no_number_at_all(self) -> None:
        """Geometry has no tolerance in the registry, and must not have
        one: the comparison is against Revit's own tolerance, read at
        check time."""
        for name in ("create_point_load", "create_line_load",
                     "create_area_load", "create_path_of_travel"):
            with self.subTest(op=name):
                keys = set(spec.OPS[name].tolerances)
                self.assertFalse({k for k in keys if k.endswith("_mm")})


class ReverseIsNamedNotAssumed(unittest.TestCase):
    """"The stage refused on the element" and "the stage said nothing
    about it" are different facts, and the silence has already cost this
    package one wrong diagnosis."""

    def test_each_one_declares_a_mode_that_matches_its_route(self) -> None:
        """🔴 REWRITTEN ON 04.09.2026: IT USED TO BE A LITERAL MODE PIN, NOW
        IT IS A LAW.

        This used to read `assertIs(contract.mode, CAPTURE_GAP)`, enumerated
        over four names — and that was true right up to the first CLOSING
        of a gap. `create_line_load` was closed that same day (the capture
        reads `LineLoad.StartPoint`/`EndPoint`/`ForceVector1`/`LoadCaseId`),
        the mode became `DIRECT`, and the pin turned red, HAVING FOUND NOT
        A SINGLE DEFECT.

        A pin like that does not guard, it taxes: every subsequent closure
        colors someone else's suite red, and the person fixing things
        starts reading red as noise. There are ten of these in `kir/tests`
        — this is the first one rewritten into a law.

        THE LAW CHECKED INSTEAD OF THE LIST: the mode MUST match the
        ROUTE. `DIRECT` without a lifter is a promise of a lift that does
        not exist; `CAPTURE_GAP` without a date is an archive, not a
        decision. Both outcomes are legitimate; what is illegitimate is
        their DIVERGENCE from the tree.

        🔴 WHAT GUARDS NOTHING HERE, AND THIS IS MEASURED BY AN ATTEMPT AT
        REFUTATION. Two clauses are unfalsifiable: `ReverseContract.
        __post_init__` ITSELF does not allow building a `DIRECT` without an
        entry point, or a `CAPTURE_GAP` without a date. Forging a contract
        so that they turn red is IMPOSSIBLE — the attempt fails at the
        constructor. They are left in as a readable assertion, but it is
        not this test that guards them.

        🔴 TWO CLAUSES WERE DISCARDED BECAUSE THEY ARE FALSE AS A LAW, AND
        THESE ARE NUMBERS. The first edition required (a) that the entry
        point lie in `_LIFTERS`, and (b) that at least one `_CANDIDATES`
        category lead into the op. Both were green ONLY on these four
        names, while across the whole manifest:

            entry point outside `_LIFTERS`   4 ops out of 33 (create_ceiling,
                                              create_curtain_grid_line,
                                              create_floor_by_contour,
                                              place_family)
            not one category on the route    5 ops out of 33 (the same
                                              four plus both stubs: for
                                              them the route is a BRANCH
                                              inside
                                              `_lift_pipe`/`_lift_duct` by
                                              `is_placeholder`, not a table
                                              row)

        That is, the law would have turned red on HONEST code nine times.
        This is exactly the kind of defect the canon calls "a guard written
        against a class fixes the SHAPE of the first instance": I had
        mistaken "the op is reachable" for "the op is in the table".

        THE LAW THAT REMAINED AND HOLDS TRUE FOR ALL 33: the entry point
        MUST be a real function of the `lift` module. Zero violations, an
        invented name does not pass — verified by substitution in both
        directions.
        """
        from kir.decompile import lift

        for name in ("create_point_load", "create_line_load",
                     "create_area_load", "create_path_of_travel"):
            contract = REVERSE_CONTRACTS[name]
            with self.subTest(op=name):
                self.assertTrue(contract.reason.strip())
                self.assertTrue(contract.limitation.strip())
                if contract.mode is ReverseMode.DIRECT:
                    self.assertTrue(
                        contract.entrypoints,
                        f"{name}: DIRECT обязан назвать точку входа")
                    for entry in contract.entrypoints:
                        self.assertTrue(
                            callable(getattr(lift, entry, None)),
                            f"{name}: точка входа {entry!r} не функция "
                            "модуля lift — манифест обещает подъём, "
                            "которого нет")
                elif contract.mode is ReverseMode.CAPTURE_GAP:
                    self.assertTrue(
                        contract.due,
                        f"{name}: пробел захвата без срока — это архив, а не "
                        "решение")
                # 🔴 THERE IS DELIBERATELY NO THIRD BRANCH, AND THIS IS THE
                # LAST REMNANT OF THE SAME AILMENT, REMOVED ON 04.09. This
                # used to read `assertIs(mode, CAPTURE_GAP)` — a closed list
                # of TWO modes for ops for which the registry's law holds
                # EIGHT. It would not have rotted from a gap being closed
                # (a closed op moves into the DIRECT branch), but it would
                # have turned red on a legitimate third: for a load,
                # `lifter_gap` is conceivable — when the reading already
                # exists but the lifter does not yet. Asserting the mode's
                # name means forbidding an honest state we did not
                # foresee; the assertions true for ANY mode (the cause and
                # the constraint are non-empty) stand above and are always
                # checked.


class PoolsAreAskableBeforeTheAttempt(unittest.TestCase):
    """In a structural project there are dozens of load cases; a blind
    name-based selector is a refusal that arrives one move too late."""

    def test_every_new_pool_is_in_the_query_types_enum(self) -> None:
        choices = set(next(p for p in spec.OPS["query_types"].params
                           if p.name == "pool").choices)
        for pool in ("load_cases", "point_load_types", "line_load_types",
                     "area_load_types"):
            with self.subTest(pool=pool):
                self.assertIn(pool, choices)

    def test_the_snapshot_collects_exactly_those_pools(self) -> None:
        from kir.open_model import GROUND_SNAPSHOT_CS, required_grounding_pools
        for pool in ("load_cases", "point_load_types", "line_load_types",
                     "area_load_types"):
            with self.subTest(pool=pool):
                self.assertIn(f'__AddPool("{pool}"', GROUND_SNAPSHOT_CS)
                self.assertIn(pool, required_grounding_pools())

    def test_load_natures_is_absent_on_purpose(self) -> None:
        """A pool without a selector would be the first exception to the
        rule "a pool exists for the sake of grounding"; there is no
        operation for creating a case in this wave, so there is no kind
        pool either."""
        from kir.open_model import required_grounding_pools
        self.assertNotIn("load_natures", required_grounding_pools())


if __name__ == "__main__":
    unittest.main()
