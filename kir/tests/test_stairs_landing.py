"""A STAIR LANDING BY SKETCH: laws, each of which is falsifiable.

WHAT KIND OF GAP THIS IS. Until 10.08.2026 the compiler could handle exactly
ONE run per staircase, i.e. a staircase with a single run; an intermediate
landing — the thing without which no real multi-story building can be
built — had NOTHING in the language TO SAY IT WITH. A census of
capabilities found the entire landing family had never once been
considered.

FIVE LAWS THIS FILE HOLDS:

  1. THE SOLO-OP LAW IS NOT WEAKENED, BUT GENERALIZED. A landing needs THE
     SAME edit scope as a run (RevitAPI.xml: "not in an active
     StairsEditScope"), so it is itself a solo op — and the price of a
     landing is a SEPARATE PROGRAM, not a relaxation of the rule. This file
     also guards against a regression that was already written into the
     first edition: the refusal named `create_stairs` as a LITERAL, i.e. it
     was blaming someone else's operation.
  2. THE SKETCH IS A CONTOUR, AND THERE IS NO SECOND WAY. The profile takes
     the same `region` kind as a floor-by-contour, a fill region, and a
     beam system; a hole is a typed refusal, because there is no second
     loop in the signature.
  3. THE TOLERANCE IS DERIVED, NOT ASSIGNED. The geometric tolerance is the
     document's own `VertexTolerance` plus a quantum from our own
     emission. The riser height sets a GRID of admissible elevations, not
     a wide tolerance: a deviation of one riser must fail the witness.
  4. THE WITNESS READS THE RESULT AND SIGNS OFF ONLY ON THE AXIS IT READ.
     The boundary is checked against the PLAN; the Z of the curves that
     are read is set by Revit itself ("projected on the stairs base
     level"), and we are not entitled to sign off on it.
  5. THE WITNESS MUST BE ABLE TO FAIL. The oracle is mutation: cutting out
     any emitted `__post.Add` must make the certificate's `proven` fail.
     Plus a runtime ban on vacuousness: a tolerance that eats up half of
     the shortest edge is a named refusal, not a signature.

Run: venv/bin/python3.12 -m pytest kir/tests/test_stairs_landing.py -q
"""
from __future__ import annotations

import os
import re
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_landing_queue.jsonl"))

from kir import authoring, contour as C, spec  # noqa: E402
from kir import reverse_contract as RC  # noqa: E402
from kir import translation_cert as TC  # noqa: E402
from kir import diag as D  # noqa: E402
from kir import stairs_landing_emit as SLE  # noqa: E402
from kir.acceptance import _OP_CATEGORIES, _OP_DERIVED  # noqa: E402
from kir.compiler import compile_program, plan_program  # noqa: E402
from kir.contracts import ElementIdentityProof  # noqa: E402
from kir.diag import KirRefusal  # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
OP = "create_stairs_landing"
STAIRS = {"by": "element_id", "value": 4242}
RECT = {"outer": {"shape": "rect", "origin": [5000.0, 0.0],
                  "size_mm": [2400.0, 1200.0]}}


def _op(**extra) -> dict:
    op = {"op": OP, "id": "LG1", "stairs": STAIRS, "contour": RECT,
          "elevation_mm": 1500.0}
    op.update(extra)
    return op


def _prog(*ops, intent: str = "площадка") -> dict:
    return {"ir_version": "1.0", "intent": intent, "ops": list(ops)}


def _compile(program: dict, ver: str = "2023", **kw):
    return compile_program(program, snapshot=SNAPSHOT, revit_version=ver,
                           bulk=True, **kw)


def _codes(out) -> list[str]:
    return [d.code for d in out.diagnostics]


def _cs(ver: str = "2023", **extra) -> str:
    out = _compile(_prog(_op(**extra)), ver)
    assert out.ok, _codes(out)
    return out.csharp


# ══════════════════════════════ 1. SOLO OP: THE LAW GENERALIZED, NOT WEAKENED

class TheSoloLawIsGeneralNotOneName(unittest.TestCase):

    def test_the_landing_is_declared_solo_in_the_registry(self) -> None:
        self.assertIn(OP, spec.SOLO_OPS)

    def test_a_neighbour_is_refused_at_PLAN_not_only_at_emit(self) -> None:
        """Live Revit is not needed for this rule: it is about the SHAPE of
        the program, and must be visible in the sandbox, not on the
        device."""
        with self.assertRaises(KirRefusal) as got:
            plan_program(_prog(
                _op(),
                {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                 "p1_mm": [6000, 0], "height_mm": 3000}))
        self.assertIn("KIR-L002", [d.code for d in got.exception.diagnostics])

    def test_the_refusal_names_the_op_that_is_actually_solo(self) -> None:
        """A REGRESSION FROM THE FIRST EDITION. The refusal text in
        `emit_program` named `create_stairs` as a literal; with a second
        solo op it would be blaming someone else's operation — an
        instrument that lies on exactly the new half of the range."""
        out = _compile(_prog(
            _op(),
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000}))
        self.assertFalse(out.ok)
        text = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn(OP, text)

    def test_the_dsl_hint_offers_a_move_this_slot_actually_has(self) -> None:
        """MEASUREMENT 04.08 introduced this helper precisely because a
        CORRECT refusal can lead into a pit. The advice "match BY NAME" is
        right for a run's level (`sel`), but `stairs` has kind `target_w`,
        which has no `name` field and cannot have one — the old text would
        send the author into a second refusal in a row."""
        from kir import dsl

        p = {q.name: q for q in spec.OPS[OP].params}["stairs"]
        stairs_spec = spec.OPS["create_stairs"]
        handle = dsl.Handle(id="S1", op="create_stairs", spec_=stairs_spec)
        move = dsl._by_name_next_move(spec.OPS[OP], p, handle)
        self.assertIn("element_id", move)
        self.assertNotIn('stairs="Этаж 1"', move)
        # ...and the old advice remains verbatim wherever it is correct.
        lvl = {q.name: q for q in stairs_spec.params}["base_level"]
        self.assertIn('base_level="Этаж 1"',
                      dsl._by_name_next_move(stairs_spec, lvl, handle))

    def test_every_solo_op_has_its_own_whole_program_template(self) -> None:
        """A mismatch between the table and the registry would mean a new
        solo op SILENTLY ends up in someone else's template and receives
        someone else's emission."""
        self.assertEqual(set(authoring._SOLO_PROGRAMS), set(spec.SOLO_OPS))

    def test_the_certificate_reads_the_same_table(self) -> None:
        self.assertEqual(set(TC._EXTRA_CERTIFIABLE), set(spec.SOLO_OPS))

    def test_an_intra_program_ref_is_refused_at_parse(self) -> None:
        """A solo op has no predecessor at all, so `by: ref` is
        unresolvable BY CONSTRUCTION — and the refusal must arrive at
        parsing."""
        out = _compile(_prog(_op(stairs={"by": "ref", "value": "S1"})))
        self.assertFalse(out.ok)
        text = " ".join(d.message_ru for d in out.diagnostics)
        self.assertIn("ref", text)


# ══════════════════════════════ 2. THE SKETCH IS A CONTOUR

class TheSketchIsContourAndOnlyContour(unittest.TestCase):

    def test_the_profile_param_is_of_kind_region(self) -> None:
        kinds = {p.name: p.kind for p in spec.OPS[OP].params}
        self.assertEqual(kinds["contour"], "region")

    def test_holes_are_a_typed_refusal_not_a_silent_drop(self) -> None:
        """A silent drop would build a SOLID landing where one with a
        cutout was requested."""
        holed = {"outer": RECT["outer"],
                 "holes": [{"shape": "rect", "origin": [5600.0, 300.0],
                            "size_mm": [600.0, 600.0]}]}
        out = _compile(_prog(_op(contour=holed)))
        self.assertFalse(out.ok)
        self.assertIn(D.EMIT_CONTOUR_HOLES, _codes(out))

    def test_an_arc_edge_lowers_to_three_literal_points(self) -> None:
        """Canon CONTOUR, item 1: all the trigonometry happens at COMPILE
        TIME, what goes out is three literal points per arc."""
        arced = {"outer": {"shape": "poly",
                           "points_mm": [[5000.0, 0.0], [7400.0, 0.0],
                                         [7400.0, 1200.0], [5000.0, 1200.0]],
                           "arcs": [{"edge": 1, "bulge": 0.3}]}}
        cs = _cs(contour=arced)
        self.assertIn("Arc.Create(", cs)
        loop = cs.split("CurveLoop __ol_LG1", 1)[1].split(
            "CreateSketchedLanding", 1)[0]
        self.assertNotIn("Math.", loop)

    def test_the_loop_sits_on_the_stairs_base_elevation_not_zero(self) -> None:
        """A loop left at world zero under a staircase at +3.000 either
        gets rejected or builds the landing in the wrong place — the same
        seam as with the beam system."""
        cs = _cs()
        self.assertIn("double __sbz_LG1 = MM(__st_LG1.BaseElevation);", cs)
        loop = cs.split("CurveLoop __ol_LG1")[1].split("try")[0]
        self.assertIn("__sbz_LG1", loop)
        self.assertNotIn(", 0)", loop)


# ══════════════════════════════ 3. THE TOLERANCE IS DERIVED, NOT ASSIGNED

class EveryToleranceIsDerivedFromRevitsOwnNumbers(unittest.TestCase):

    def test_the_registry_declares_no_tolerance_at_all(self) -> None:
        """Both tolerances depend on the LIVE model and therefore cannot be
        registry constants by construction."""
        self.assertEqual(spec.OPS[OP].tolerances, {})

    def test_the_boundary_tolerance_is_vertex_tolerance_plus_the_quantum(self) -> None:
        cs = _cs()
        self.assertIn(
            f"double __dt_LG1 = MM(doc.Application.VertexTolerance) + "
            f"{C.EMIT_COORD_QUANTUM_MM!r};", cs)

    def test_no_bare_literal_stands_in_the_boundary_comparison(self) -> None:
        """A bare literal in a comparison is exactly the third of
        boundaries that `bounds_audit` cannot find by searching for
        constants."""
        block = _cs().split("foreach (Curve __bc_LG1")[1].split(
            "if (!__bRead_LG1)")[0]
        for cmp_line in re.findall(r"Math\.Abs\([^)]*\)\s*<=\s*([^\s&|);]+)",
                                   block):
            self.assertEqual(cmp_line, "__dt_LG1")
        self.assertTrue(
            re.search(r"Math\.Abs\([^)]*\)\s*<=\s*__dt_LG1", block))

    def test_elevation_is_normalized_before_the_call_and_witnessed_strictly(self) -> None:
        """We do not guess at the hidden side of Revit's rounding: the
        author must name a value that is already a multiple, the factory
        receives a computed multiple, and the witness uses a small
        geometric tolerance."""
        cs = _cs()
        self.assertIn("double __rh_LG1 = MM(__st_LG1.ActualRiserHeight);", cs)
        self.assertIn("double __elevNorm_LG1 = __elevK_LG1 * __rh_LG1;", cs)
        self.assertIn("Math.Abs(1500.0 - __elevNorm_LG1) > __dt_LG1", cs)
        self.assertIn("U(__elevNorm_LG1)", cs)
        self.assertIn(
            "Math.Abs(__gotE_LG1 - __elevNorm_LG1) > __dt_LG1", cs)
        self.assertNotIn("> __rh_LG1 + __dt_LG1", cs)

    def test_a_plus_or_minus_one_riser_mutation_fails_the_witness(self) -> None:
        """A mutation oracle for an old defect: the previous tolerance of a
        whole riser was accepting both of these wrong results."""
        expected, riser, tolerance = 1500.0, 175.0, 0.02
        self.assertLess(tolerance, riser)
        for built in (expected - riser, expected + riser):
            with self.subTest(built=built):
                self.assertGreater(abs(built - expected), tolerance)
        self.assertIn(
            "Math.Abs(__gotE_LG1 - __elevNorm_LG1) > __dt_LG1", _cs())

    def test_non_multiple_refusal_names_both_adjacent_candidates(self) -> None:
        cs = _cs()
        self.assertIn("__elevLower_LG1", cs)
        self.assertIn("__elevUpper_LG1", cs)
        self.assertIn("ближайшие кандидаты", cs)

    def test_the_registry_upper_bound_is_autodesks_own_number(self) -> None:
        """"no more than 30000 feet in absolute value" is an external
        number; ours is only the unit conversion applied to it."""
        p = {q.name: q for q in spec.OPS[OP].params}["elevation_mm"]
        self.assertEqual(p.max_val, 30_000 * 304.8)

    def test_the_exact_lower_bound_is_a_runtime_refusal_naming_the_number(self) -> None:
        """The registry bound (0) is WEAK on purpose: the exact one ("half
        of the riser height") is known only by the live staircase. The weak
        bound rejects no legitimate value at all; the exact one is set by
        the runtime, and it NAMES the measured number rather than pointing
        to documentation."""
        p = {q.name: q for q in spec.OPS[OP].params}["elevation_mm"]
        self.assertEqual(p.min_val, 0.0)
        cs = _cs()
        self.assertIn("if (1500.0 < __rh_LG1 / 2.0)", cs)
        self.assertIn("Math.Round(__rh_LG1 / 2.0, 1)", cs)


# ══════════════════════════════ 4. THE WITNESS READS THE RESULT AND THE SAME AXIS

class TheWitnessReadsTheResultAndSignsOnlyTheAxisItRead(unittest.TestCase):

    def test_the_boundary_is_re_read_from_the_built_landing(self) -> None:
        """Not from what we ourselves passed into the call: checking a call
        against itself is the definition of a witness that cannot fail."""
        cs = _cs()
        self.assertIn("__landing_LG1.GetFootprintBoundary()", cs)
        block = cs.split("foreach (Curve __bc_LG1")[1].split(
            "if (!__bRead_LG1)")[0]
        self.assertNotIn("__ol_LG1", block)

    def test_the_boundary_witness_compares_plan_only(self) -> None:
        """The Z of the curves that are read is set by Revit itself
        ("projected on the stairs base level"); signing off on an axis we
        did not set is exactly what test_witness_axis_honesty forbids."""
        block = _cs().split("foreach (Curve __bc_LG1")[1].split(
            "if (!__bRead_LG1)")[0]
        self.assertNotIn(".Z", block)
        self.assertIn(".X", block)
        self.assertIn(".Y", block)

    def test_each_authored_edge_must_be_matched_exactly_once(self) -> None:
        """A hit counter, not "something was found at all": without it,
        two curves that were read could both land on the same authored
        edge, leaving the second one unproven."""
        cs = _cs()
        self.assertIn("__bHit_LG1[__bk_LG1]++", cs)
        self.assertIn("if (__bHit_LG1[__bj_LG1] != 1) __bExact_LG1 = false;", cs)

    def test_the_arc_bulge_travels_with_its_midpoint(self) -> None:
        """By their endpoints alone, a straight line and an arc between the
        same endpoints are indistinguishable — the arc's sagitta would
        remain unproven."""
        cs = _cs()
        self.assertIn("__bxm_LG1", cs)
        self.assertIn("Evaluate(0.5, true)", cs)

    def test_the_sketched_factory_is_witnessed_as_sketched(self) -> None:
        """An automatic landing is a DIFFERENT element; `IsAutomaticLanding
        == true` would mean Revit built something other than what was
        asked for."""
        self.assertIn("__landing_LG1.IsAutomaticLanding", _cs())

    def test_ownership_is_witnessed_from_both_ends(self) -> None:
        cs = _cs()
        self.assertIn("__landing_LG1.GetStairs()", cs)
        self.assertIn("__stairs_LG1.GetStairsLandings()", cs)

    def test_requested_normalized_and_built_elevations_ride_the_receipt(self) -> None:
        cs = _cs()
        for key in ("elevation_requested_mm", "elevation_normalized_mm",
                    "elevation_built_mm", "elevation_lower_candidate_mm",
                    "elevation_upper_candidate_mm", "riser_height_mm",
                    "boundary_tolerance_mm"):
            self.assertIn(key, cs)


# ══════════════════════════════ 5. THE WITNESS MUST BE ABLE TO FAIL

class AWitnessThatCannotFailIsWorseThanNone(unittest.TestCase):

    def test_a_tolerance_that_could_swallow_an_edge_is_a_refusal(self) -> None:
        """'A tolerance >= the quantity' is exactly the definition of
        vacuousness; here it is guarded by a NAMED refusal, not a
        signature."""
        cs = _cs()
        self.assertIn("if (2.0 * __dt_LG1 >= 1200.0)", cs)

    def test_the_vacuity_guard_uses_this_contours_own_shortest_edge(self) -> None:
        narrow = {"outer": {"shape": "rect", "origin": [5000.0, 0.0],
                            "size_mm": [2400.0, 300.0]}}
        self.assertIn("if (2.0 * __dt_LG1 >= 300.0)", _cs(contour=narrow))

    def test_the_certificate_finds_no_dead_verdict(self) -> None:
        for ver in VERSIONS:
            with self.subTest(version=ver):
                cert = TC.certify_op(_grounded(ver), ver)
                self.assertTrue(cert.proven)
                self.assertEqual(cert.vacuous, ())

    #: The marker for each obligation -> the verdict that rests on it.
    #: The pair is EXPLICIT and is held here, not derived: see the second
    #: test below.
    _WITNESS_PAIRS = (
        (".GetStairs()", "площадка принадлежит не той лестнице (topology)"),
        ("GetStairsLandings", "площадки нет в GetStairsLandings своей "
                              "лестницы (topology)"),
        ("IsAutomaticLanding", "построена автоматическая площадка вместо "
                               "эскизной (semantic)"),
        ("GetFootprintBoundary", "граница площадки не совпала с заданным "
                                 "контуром в плане (geometry)"),
        ("BaseElevation", "отметка площадки не равна нормализованному "
                          "кратному подступенка (geometry)"),
    )

    def test_excising_a_witness_flips_the_certificate(self) -> None:
        """A FALSIFIABILITY ORACLE, in the shape of a mutation (discipline
        C5 of this repository): cutting out a genuine witness MUST make
        `proven` fail. For an op with its OWN program template, the ENTIRE
        witness block is cut out — both the read and the verdict —
        because that is exactly what a careless edit looks like; a witness
        the certificate does not check is a signature under something
        unread."""
        real = authoring._SOLO_PROGRAMS[OP]
        survivors = []
        for marker, verdict in self._WITNESS_PAIRS:
            def excised(o, v, intent="", *, _m=marker, _t=verdict, **kw):
                program = real(o, v, intent, **kw)
                return (program.replace(_m, "__CUT__")
                               .replace(f'__post.Add("LG1: {_t}");', "{ }"))
            authoring._SOLO_PROGRAMS[OP] = excised
            try:
                still = TC.certify_op(_grounded("2023"), "2023").proven
            finally:
                authoring._SOLO_PROGRAMS[OP] = real
            if still:
                survivors.append(marker)
        self.assertEqual(
            [], survivors,
            "\nсвидетели, чьё удаление оставляет сертификат PROVEN:\n  "
            + "\n  ".join(survivors))

    def test_a_verdict_deleted_alone_is_caught_HERE_because_the_cert_cannot(self) -> None:
        """MEASUREMENT 10.08.2026, AND THIS IS A GENUINE INSTRUMENT
        LIMITATION, NOT NITPICKING.

        An op with its own program template takes the STRING-LEVEL path of
        the certificate, where the obligation is discharged by a MARKER —
        a structural C# substring (`GetFootprintBoundary`, `BaseElevation`,
        …). The marker lives in the READ. So deleting just `__post.Add`
        alone leaves the marker in place, and `certify_op` still says
        PROVEN — verified by cutting out all five verdicts one at a time:
        the certificate did not fail on a SINGLE one.

        This is not a defect of this wave — `create_stairs` takes the same
        path — but it cannot be passed over in silence: "the key proves
        the string EXISTS, not that it can FIRE" is written into the canon
        on vacuousness, and here is the same gap one level up. As long as
        the model-level path (`WitnessCheck`) is unavailable for
        whole-program templates, it is THIS test that holds the pair
        "marker + its verdict", and it is the only thing standing between
        a deleted verdict and a green gate."""
        real = authoring._SOLO_PROGRAMS[OP]
        program = real(_grounded("2023"), "2023")
        for marker, verdict in self._WITNESS_PAIRS:
            with self.subTest(marker=marker):
                self.assertIn(marker, program)
                self.assertIn(f'__post.Add("LG1: {verdict}");', program)
        # And the other side of the same pair: the instrument really is
        # blind, which is why the oracle above cuts out the whole block.
        # If the certificate ever learns to catch a lone verdict, THIS
        # line will fail and call for the oracle to be simplified — a
        # ratchet in both directions.
        marker, verdict = self._WITNESS_PAIRS[0]

        def verdict_only(o, v, intent="", **kw):
            return real(o, v, intent, **kw).replace(
                f'__post.Add("LG1: {verdict}");', "{ }")
        authoring._SOLO_PROGRAMS[OP] = verdict_only
        try:
            still = TC.certify_op(_grounded("2023"), "2023").proven
        finally:
            authoring._SOLO_PROGRAMS[OP] = real
        self.assertTrue(
            still,
            "сертификат СТАЛ ловить одинокий вердикт — упростите оракул "
            "мутации выше до вырезания одного `__post.Add`")


# ══════════════════════════════ 6. THE WIRING: REVERSE PASS, ACCEPTANCE, UI REFUSAL

class TheOpIsWiredIntoEverySpineThatCounts(unittest.TestCase):

    def test_the_reverse_contract_is_a_dated_capture_gap(self) -> None:
        """A `capture_gap` without a date by which someone must answer is
        "someday", not a decision (`record_ratchet` would have refused the
        import)."""
        rc = RC.contract_for(OP) if hasattr(RC, "contract_for") \
            else RC._CONTRACTS[OP]
        self.assertIs(rc.mode, RC.ReverseMode.CAPTURE_GAP)
        self.assertIs(rc.guarantee, RC.ReverseGuarantee.NONE)
        self.assertTrue(rc.decided_on and rc.due)
        self.assertLess(rc.decided_on, rc.due)

    def test_the_census_counts_a_landing_not_a_stairs(self) -> None:
        """A second cell would mean "this program built a staircase", and
        an honest success would read as someone else's unordered create."""
        self.assertEqual(_OP_CATEGORIES[OP], ("OST_StairsLandings",))
        self.assertNotIn(OP, _OP_DERIVED)

    def test_the_modal_dialog_discipline_is_kept_on_both_points(self) -> None:
        """Incident 27.07: a modal dialog froze Revit's UI thread and
        killed the bridge across six calls in a row. The preprocessor must
        sit BOTH on the transaction AND on `StairsEditScope.Commit` — the
        warning can surface outside the transaction already."""
        cs = _cs()
        self.assertIn("__fho.SetFailuresPreprocessor(new __KirStairsFailures());",
                      cs)
        self.assertIn("__ess.Commit(new __KirStairsFailures());", cs)
        self.assertIn("__fa.DeleteWarning(__f);", cs)

    def test_the_edit_scope_is_opened_on_the_existing_stairs(self) -> None:
        """A MEASUREMENT, NOT A GUESS: the single-argument
        `Start(ElementId)` exists on all six versions, and it is exactly
        what makes the landing a separate program instead of the run's
        neighbor."""
        cs = _cs()
        self.assertIn("if (!__ess.IsPermitted)", cs)
        self.assertIn("__ess.Start(__stairsId_LG1);", cs)
        self.assertLess(cs.index("if (!__ess.IsPermitted)"),
                        cs.index("__ess.Start(__stairsId_LG1)"))
        self.assertIn(
            "__sid_LG1.ToString() != __stairsId_LG1.ToString()", cs)
        self.assertNotIn("StairsRun.Create", cs)

    def test_scope_permission_comes_from_the_scope_contract_not_the_stairs(self) -> None:
        cs = _cs()
        self.assertIn("__ess.IsPermitted", cs)
        self.assertNotIn("__st_LG1.IsInEditMode()", cs)

    def test_soft_refusals_after_start_require_proven_rollback_and_cancel(self) -> None:
        cs = _cs()
        self.assertIn(
            "__rollbackStatus_LG1 = __transaction_LG1.RollBack();", cs)
        self.assertIn(
            "__rollbackStatus_LG1 != TransactionStatus.RolledBack", cs)
        self.assertIn("__scope_LG1.Cancel();", cs)
        self.assertIn("return !__scope_LG1.IsActive;", cs)
        self.assertNotIn("__t.RollBack(); __ess.Cancel();", cs)
        after_start = cs.split("__sid_LG1 = __ess.Start", 1)[1]
        self.assertEqual(after_start.count("return __Refuse"), 2)
        for block in re.findall(
                r"if \(!__rollbackCancel_LG1\(__t, __ess\)\).*?"
                r"return __Refuse", after_start, flags=re.S):
            self.assertIn("throw new InvalidOperationException", block)
        self.assertEqual(len(re.findall(
            r"if \(!__rollbackCancel_LG1\(__t, __ess\)\).*?return __Refuse",
            after_start, flags=re.S)), 2)

    def test_final_witness_reloads_both_elements_after_scope_commit(self) -> None:
        cs = _cs()
        commit = cs.index("__ess.Commit(new __KirStairsFailures());")
        fresh_st = cs.index("doc.GetElement(__stairsId_LG1) as", commit)
        fresh_lg = cs.index("doc.GetElement(__landingId_LG1) as", commit)
        final_check = cs.index("__check_LG1(__freshLg_LG1, __freshSt_LG1)",
                               commit)
        self.assertLess(commit, fresh_st)
        self.assertLess(fresh_st, fresh_lg)
        self.assertLess(fresh_lg, final_check)
        self.assertIn('__results["postcondition_violations"]', cs)

    def test_a5_pre_and_transaction_identity_guards_have_distinct_symbols(self) -> None:
        """A5 checks identity before the scope and once again inside the
        transaction. C# does not allow a nested block to redeclare a local
        from the enclosing block; an identical prefix was making the
        guarded program CS0136 on 6/6."""
        proof = ElementIdentityProof(
            element_id=4242, unique_id="stairs-4242",
            version_guid="0" * 32)
        out = compile_program(
            _prog(_op()), snapshot=SNAPSHOT, revit_version="2023", bulk=True,
            expected_document={
                "title": "A5", "path_name": r"C:\models\a5.rvt",
                "project_uid": "project-a5"},
            expected_identities=(proof,))
        self.assertTrue(out.ok, _codes(out))
        self.assertIn("Element __kirBinding_0", out.csharp)
        self.assertIn("Element __kirLandingTxnBinding_0", out.csharp)
        self.assertIn(
            "if (!__rollbackCancel_LG1(__t, __ess))", out.csharp)

    def test_it_compiles_offline_on_all_six_versions(self) -> None:
        for ver in VERSIONS:
            with self.subTest(version=ver):
                out = _compile(_prog(_op()), ver)
                self.assertTrue(out.ok, _codes(out))
                self.assertIn("CreateSketchedLanding", out.csharp)

    def test_the_four_refused_factories_are_named_with_a_reason(self) -> None:
        """The census separately counts a "named without a reason" bucket;
        every line of the module docstring keeps it small."""
        doc = SLE.__doc__ or ""
        refusals = doc.split("REFUSED BY NAME", 1)
        self.assertEqual(len(refusals), 2, "секция отказов исчезла из шапки")
        section = refusals[1]
        for member in ("CreateAutomaticLanding",
                       "CreateSketchedLandingWithSlopeData",
                       "CreateSketchedRun",
                       "CreateSketchedRunWithSlopeData",
                       "SetSketchedLandingBoundaryAndPath"):
            with self.subTest(member=member):
                self.assertIn(member, section)
                # THE REASON, NOT JUST THE NAME: the census counts "named
                # without a reason" as a separate bucket, and overnight on
                # 09.08 it collapsed from 30 to 4 — every line here keeps
                # it small.
                after = section.split(member, 1)[1][:600]
                self.assertIn("REFUSED", after)
                self.assertRegex(after, r"(?s)REFUSED.{40,}")


def _grounded(ver: str) -> dict:
    out = _compile(_prog(_op()), ver)
    assert out.ok, _codes(out)
    return out.grounded_ops[0]


if __name__ == "__main__":
    unittest.main(verbosity=2)
