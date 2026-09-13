"""create_filled_region — a 2D fill by contour, living ON THE VIEW (09.08.2026).

The first operation where TWO sub-languages meet: CONTOUR gives the shape,
docspace gives the space. The file holds exactly the laws that this seam
lets you break silently, and not a single "the op exists".

WHAT IS PROVEN HERE:
  * the contour lands in the VIEW'S PLANE, not the model's XY (otherwise
    Revit rejects the loop on any section — while on a plan it would accept
    it silently, and the defect would only show up on a live model with a
    non-orthogonal basis);
  * the forward and inverse passes are IDENTICAL, not merely similar — one
    formula for both;
  * the witness reads the RESULT (`GetBoundaries()`), not an echo of the
    argument;
  * an address taken from the grid axes inside the contour is a typed
    REFUSAL, not "it will line up on the plans";
  * the tolerance is DERIVED from `contour._EDGE_TOL`, not assigned.

WHAT THIS FILE CANNOT PROVE AND DOES NOT PRETEND TO: there is no live Revit
here. Exactly what `GetBoundaries()` returns for a built fill — whether the
loops match in number, whether Revit keeps an arc an arc, whether it does
not shift the ring's starting point — that is a live measurement. Offline,
the witness's FORM is proven, and the fact that it looks outward.

RECORDED REFUSALS (the last class of tests): the elevation spot mark and
volumetric text. Both are measured by compilation and both are REFUSED; the
test exists so that the reason does not rot silently along with the prose
that explains it.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_fr_queue.jsonl"))

from kir import contour, docspace, spec                    # noqa: E402
from kir.compiler import compile_program                   # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

VERSIONS = ("2021", "2022", "2023", "2024", "2025", "2026")
IN_VIEW = {"by": "element_id", "value": 900}          # id-pinned: no pool of views
RECT = {"outer": {"shape": "rect", "origin": [500, 500], "size_mm": [3000, 1200]}}


def _fr(oid="F1", **kw):
    op = {"op": "create_filled_region", "id": oid, "in_view": IN_VIEW,
          "contour": RECT}
    op.update(kw)
    return op


def _prog(ops, intent="filled-region-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _emit(ops, ver="2026"):
    out = compile_program(_prog(ops), revit_version=ver, snapshot=SNAPSHOT)
    assert out.ok, [f"{d.code}: {d.message_ru}" for d in out.diagnostics]
    return out.csharp


class ItCompilesOnEveryShippedVersion(unittest.TestCase):
    """The version axis for the fill is FLAT, and this is a measurement, not
    a hope: `FilledRegion.Create(Document, ElementId, ElementId,
    IList<CurveLoop>)`, `GetBoundaries()`, `IsValidFilledRegionTypeId` and
    `ElementTypeGroup.FilledRegionType` compile on 2021-2026 against the
    reference assemblies. So the emitter has NO version branch at all — and
    this test must fail if one appears."""

    def test_same_emission_shape_on_all_six(self):
        for ver in VERSIONS:
            with self.subTest(ver=ver):
                cs = _emit([_fr()], ver)
                self.assertIn("FilledRegion.Create(doc, __frt_F1.Id, "
                              "__vw_F1.Id, __loops_F1)", cs)
                self.assertIn("FilledRegion.IsValidFilledRegionTypeId", cs)
                self.assertIn("__el_F1.GetBoundaries()", cs)

    def test_no_version_branch_hides_in_the_emission(self):
        """The texts of the six versions differ by EXACTLY the ElementId
        literal, if they differ at all. A version branch added without a
        measurement will be caught here."""
        bodies = {ver: _emit([_fr(type={"by": "element_id", "value": 1800})],
                             ver)
                  for ver in VERSIONS}
        stripped = {ver: cs.replace("new ElementId(1800)", "<ID>")
                        .replace("new ElementId((long)1800)", "<ID>")
                        .replace("new ElementId(900)", "<VIEW>")
                        .replace("new ElementId((long)900)", "<VIEW>")
                    for ver, cs in bodies.items()}
            # The program's stamp depends on its digest, not on the version.
        self.assertEqual(len(set(stripped.values())), 1,
                         "эмиссия разошлась по версиям — где замер?")


class ContourLandsInViewSpaceNotModelXY(unittest.TestCase):
    """THE MOST IMPORTANT LAW OF THIS OP.

    `FilledRegion.Create` requires a loop in a plane parallel to the view's
    OWN sketch plane (RevitAPI.xml). The ready-made `contour.emit_loop_cs`
    assembles the loop at z=0 in world XY — true on a plan and rejected on a
    section. A defect of this kind is invisible offline and invisible on
    plans, which is why the law is pinned here structurally."""

    def test_every_loop_point_goes_through_the_view_basis(self):
        cs = _emit([_fr()])
        loop_lines = [ln for ln in cs.splitlines() if ".Append(" in ln]
        self.assertTrue(loop_lines, "петля не собрана вовсе")
        for ln in loop_lines:
            self.assertIn("__vp_F1(", ln,
                          "точка петли не прошла через базис вида")
            self.assertNotIn("P(", ln.replace("__vp_F1(", ""),
                             "точка петли построена в мировых XY — на разрезе "
                             "Revit отвергнет петлю целиком")

    def test_the_point_function_is_the_family_forward_map(self):
        """The point function is NOT a second formula — it is the same one.
        Otherwise the fill and the text on the same view would end up in
        different places."""
        cs = _emit([_fr()])
        one_point = docspace.emit_view2d_to_xyz_cs("__vw_F1", 500.0, 500.0)
        # From the expression of one point we strip its literals — what
        # remains is the skeleton, which must stand word for word in the
        # body of the local function.
        skeleton = one_point.replace("U(500.0)", "U(__u)", 1) \
                            .replace("U(500.0)", "U(__v)", 1)
        self.assertIn(skeleton, cs)
        self.assertIn("XYZ __vp_F1(double __u, double __v) =>", cs)

    def test_forward_and_inverse_are_one_law(self):
        """Identity, not resemblance: the inverse pass takes the SAME
        Right/Up in the SAME order as the forward one, and both sides are
        born from one module."""
        cs = _emit([_fr()])
        fwd = docspace.emit_view2d_to_xyz_cs("__vw_F1", 0.0, 0.0)
        self.assertLess(fwd.index("RightDirection"), fwd.index("UpDirection"))
        inv = docspace.emit_xyz_to_view2d_cs(
            "__vw_F1", "__frCv_F1.GetEndPoint(0)", "__frRa_F1",
            "__frAu_F1", "__frAv_F1")
        self.assertLess(inv.index("RightDirection"), inv.index("UpDirection"))
        # The indentation is set by the program assembler, so LINES are
        # compared, not the whole block: the inverse pass must stand in the
        # emission verbatim.
        emitted = {ln.strip() for ln in cs.splitlines()}
        for line in inv.strip().splitlines():
            self.assertIn(line.strip(), emitted)
        # The inverse pass reads the CREATED element, not the call's argument.
        self.assertIn("__frCv_F1.GetEndPoint(0) - __vw_F1.Origin", cs)


class TheWitnessReadsTheResult(unittest.TestCase):
    """The witness must re-read the built boundary, not merely confirm that
    the call took place."""

    def test_boundary_is_reread_and_matched_edge_for_edge(self):
        cs = _emit([_fr()])
        post = cs[cs.index("// post F1"):cs.index("// witness F1")]
        self.assertIn("__el_F1.GetBoundaries()", post)
        self.assertIn("__frCv_F1.GetEndPoint(0)", post)
        self.assertIn("__frCv_F1.GetEndPoint(1)", post)
        # The edge's midpoint is the only thing that distinguishes an arc
        # from its chord.
        self.assertIn("__frCv_F1.Evaluate(0.5, true)", post)
        self.assertIn("__post.Add", post)

    def test_loop_and_curve_counts_are_gated(self):
        """A hole adds a loop and edges: the numbers in the witness must
        travel together with the contour, otherwise they are decoration,
        not evidence."""
        with_hole = dict(RECT)
        with_hole = {"outer": RECT["outer"],
                     "holes": [{"shape": "rect", "origin": [1000, 700],
                                "size_mm": [500, 400]}]}
        plain = _emit([_fr()])
        holed = _emit([_fr(contour=with_hole)])
        self.assertIn("__frLoops_F1 != 1 || __frCurves_F1 != 4", plain)
        self.assertIn("__frLoops_F1 != 2 || __frCurves_F1 != 8", holed)
        self.assertIn("new int[4]", plain)
        self.assertIn("new int[8]", holed)

    def test_every_authored_edge_must_be_matched_exactly_once(self):
        """"At least one found" catches only a half-swapped contour. Here a
        bijection is required: every authored edge exactly once, and not a
        single extra curve."""
        cs = _emit([_fr()])
        self.assertIn("if (__frHit_F1[__frJ_F1] != 1) __frExact_F1 = false;", cs)
        self.assertIn("if (!__frOne_F1) __frStray_F1 = true;", cs)

    def test_arc_midpoint_travels_into_the_witness(self):
        """An arc and its chord have THE SAME endpoints. Without the
        midpoint, the witness would mistake a built chord for the ordered
        arc."""
        arc = {"outer": {"shape": "poly",
                         "points_mm": [[0, 0], [4000, 0], [4000, 2500],
                                       [0, 2500]],
                         "arcs": [{"edge": 1, "bulge": 0.4}]}}
        cs = _emit([_fr(contour=arc)])
        mid = contour.bulge_midpoint([4000.0, 0.0], [4000.0, 2500.0], 0.4)
        self.assertIn(f"Arc.Create(__vp_F1(4000.0, 0.0), "
                      f"__vp_F1(4000.0, 2500.0), "
                      f"__vp_F1({round(mid[0], 2)}, {round(mid[1], 2)}))", cs)
        # THE SAME midpoint must lie in the array against which the read
        # curve is compared — otherwise the witness would be checking a
        # different arc.
        self.assertIn(f"double[] __fum_F1 = new double[] {{ 2000.0, "
                      f"{round(mid[0], 2)},", cs)

    def test_type_is_reread_from_the_built_element(self):
        cs = _emit([_fr(type={"by": "name", "value": "Бетон"})])
        self.assertIn("__el_F1.GetTypeId().ToString() != __frt_F1.Id.ToString()",
                      cs)

    def test_is_masking_is_recorded_never_asserted(self):
        """Whether it "is a fill or a mask" is decided by the TYPE, and
        which of the project's types are masking ones is not visible from
        the program. The fact rides into the receipt; refusing on it would
        mean refusing on a guess."""
        cs = _emit([_fr()])
        post = cs[cs.index("// post F1"):cs.index("// witness F1")]
        witness = cs[cs.index("// witness F1"):]
        self.assertNotIn("IsMasking", post)
        self.assertIn('__rb["is_masking"] = __el_F1.IsMasking', witness)


class SpaceConfusionIsRefusedNotTolerated(unittest.TestCase):
    """The contour points are [u,v] OF THE VIEW'S SPACE. The grid axis lives
    in the model: on a plan with a world basis these numbers would coincide,
    on a section they would mean a different place. Exactly the class that
    docspace makes inexpressible."""

    def test_grid_anchor_inside_the_contour_is_a_typed_refusal(self):
        addressed = {"outer": {"shape": "rect",
                               "origin": {"at_grid": ["А", "1"]},
                               "size_mm": [3000, 1200]}}
        out = compile_program(_prog([_fr(contour=addressed)]),
                              revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        text = " ".join(d.message_ru or "" for d in out.diagnostics)
        self.assertIn("at_grid", text)
        self.assertIn("ПРОСТРАНСТВЕ ВИДА", text)

    def test_a_plain_contour_is_not_refused(self):
        """A refusal the API does not require is as much a lie as silence."""
        out = compile_program(_prog([_fr()]), revit_version="2026",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok,
                        [d.message_ru for d in out.diagnostics])

    def test_a_coordinate_outside_the_working_extent_is_refused(self):
        """CONTOUR itself has no coordinate limit at all; the limit taken is
        the same one as for the `at` of the spot mark and the text —
        because it is the same space."""
        huge = {"outer": {"shape": "rect",
                          "origin": [docspace._SHEET_LIMIT_MM * 2, 0],
                          "size_mm": [3000, 1200]}}
        out = compile_program(_prog([_fr(contour=huge)]),
                              revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_in_view_by_ref_is_refused_like_the_rest_of_the_family(self):
        out = compile_program(
            _prog([{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                    "p1_mm": [6000, 0],
                    "level": {"by": "name", "value": "Этаж 1"}},
                   _fr(in_view={"by": "ref", "value": "W1"})]),
            revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("in_view", " ".join(d.field_name or ""
                                          for d in out.diagnostics))


class TheToleranceIsDerivedNotInvented(unittest.TestCase):
    """1.0 mm is CONTOUR's OWN resolution for points
    (`contour._EDGE_TOL`): an edge shorter than it the sub-language
    statically rejects as zero-length, meaning two points closer than a
    millimeter are, for this language, ONE point. The witness has no right
    to distinguish what the language cannot distinguish."""

    def test_boundary_tolerance_equals_the_contour_edge_tolerance(self):
        self.assertEqual(
            spec.OPS["create_filled_region"].tolerances["boundary_mm"],
            contour._EDGE_TOL)

    def test_the_number_actually_reaches_the_emission(self):
        self.assertIn("<= 1.0", _emit([_fr()]))


class GroundingFollowsTheExistingPattern(unittest.TestCase):
    def test_named_type_resolves_through_the_new_pool(self):
        cs = _emit([_fr(type={"by": "name", "value": "Грунт"})])
        self.assertIn("new ElementId(1801)", cs)

    def test_omitted_type_uses_the_document_default(self):
        """For the fill, a document-level default EXISTS (measured: 6/6).
        The general "single item in the pool" rule would be the worst
        choice here — a real project has dozens of fill types."""
        cs = _emit([_fr()])
        self.assertIn("doc.GetDefaultElementTypeId("
                      "ElementTypeGroup.FilledRegionType)", cs)
        self.assertNotIn("new ElementId(1800)", cs)

    def test_the_pool_is_askable_before_the_program(self):
        self.assertIn("filled_region_types",
                      spec.OPS["query_types"].params[0].choices)

    def test_an_unknown_type_name_refuses_with_candidates(self):
        out = compile_program(
            _prog([_fr(type={"by": "name", "value": "Нет такого"})]),
            revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(any(d.candidates for d in out.diagnostics))


class RecordedRefusalsStayRecorded(unittest.TestCase):
    """REFUSALS WITH A NAMED REASON, measured on 09.08 against six reference
    assemblies. The test is not about taste but about keeping the reason
    from disappearing along with the prose: without it, the next wave would
    propose them again and spend a day on a repeat measurement."""

    def test_no_elevation_marker_op_exists_and_the_reason_is_written_down(self):
        self.assertNotIn("create_elevation_marker", spec.OPS)
        self.assertNotIn("create_elevation_view", spec.OPS)
        from kir import ops_annotation
        doc = ops_annotation.__doc__ or ""
        # The reason, not the fact: an empty marker draws nothing, and its
        # views require ReferenceKind.VIEW — a change to the LANGUAGE, not
        # to the operation.
        self.assertIn("CurrentViewCount", doc)
        self.assertIn("ReferenceKind.VIEW", doc)
        # And the correct sibling name: `CreateElevationView` does not exist.
        self.assertIn("CreateElevation(Document", doc)
        self.assertIn("CreateElevationView", doc)

    def test_no_model_text_op_exists_and_the_reason_is_written_down(self):
        self.assertNotIn("create_model_text", spec.OPS)
        from kir import ops_annotation
        doc = ops_annotation.__doc__ or ""
        self.assertIn("NewModelText", doc)
        self.assertIn("FamilyItemFactory", doc)
        self.assertIn("CS1061", doc)


class ExistingEmissionDidNotMove(unittest.TestCase):
    """The inverse formula moved into docspace FROM the spot mark and the
    text — byte for byte. The reference assemblies already prove this;
    here is a direct check that the helper produces exactly the lines that
    used to stand hand-written in the emitters."""

    def test_the_helper_reproduces_the_hand_written_tag_bytes(self):
        self.assertEqual(
            docspace.emit_xyz_to_view2d_cs(
                "__vw_T1", "__el_T1.TagHeadPosition", "__rel_T1",
                "__ou_T1", "__ow_T1", indent=" " * 8),
            "        var __rel_T1 = __el_T1.TagHeadPosition - __vw_T1.Origin;\n"
            "        double __ou_T1 = MM(__rel_T1.DotProduct(__vw_T1.RightDirection));\n"
            "        double __ow_T1 = MM(__rel_T1.DotProduct(__vw_T1.UpDirection));\n")

    def test_the_model_space_loop_builder_is_unchanged(self):
        """`emit_loop_cs` gained an optional point formatter. Without it,
        the bytes must stay unchanged — otherwise every contour-based floor
        would shift."""
        edges = [([0.0, 0.0], [1000.0, 0.0], 0.0),
                 ([1000.0, 0.0], [0.0, 0.0], 0.5)]
        self.assertEqual(
            contour.emit_loop_cs(edges, "__ol"),
            "CurveLoop __ol = new CurveLoop();\n"
            "__ol.Append(Line.CreateBound(P(0.0, 0.0, 0), P(1000.0, 0.0, 0)));\n"
            "__ol.Append(Arc.Create(P(1000.0, 0.0, 0), P(0.0, 0.0, 0), "
            f"P({round(contour.bulge_midpoint([1000.0, 0.0], [0.0, 0.0], 0.5)[0], 2)}, "
            f"{round(contour.bulge_midpoint([1000.0, 0.0], [0.0, 0.0], 0.5)[1], 2)}, 0)));")


if __name__ == "__main__":
    unittest.main()


class TheRefusalNamesEveryOutOfBoundsPoint(unittest.TestCase):
    """The boundary refusal hands back ALL the points, not just the first
    (13.08.2026).

    Here stood `raise KirRefusal(bound_diags[:1])` — the ONLY slice among
    76 `raise KirRefusal` sites across the whole tree; the other 75 hand
    back the list in full.

    WHY IT WAS WORSE THAN AN ORDINARY TRUNCATION. The remedy for this class
    was written on 12.08 (`23be2d1f`) and sits ON THE CONSUMER SIDE: the
    receipt shows 8 and names `diagnostics_total` when there were more. The
    slice sat ON THE PRODUCER SIDE — the consumer received one out of one,
    and correctly kept quiet about the rest. A truncation that fools its
    own remedy costs more than a truncation with no remedy at all.

    The cost in turns: a coordinate blowout is almost always systemic (the
    wrong coordinate system), meaning it fails ALL vertices at once. The
    model was fixing them one at a time.
    """

    #: knowingly beyond docspace — the numbers are taken from the limit
    #: itself, not assigned here, otherwise the test would survive a change
    #: to the boundary
    FAR = 10 ** 9

    def _far_rect(self):
        """THE RECTANGLE is one AUTHORED point, and this is its limit.

        The first edition of this test submitted `shape: "poly"` with
        `pts` — CONTOUR HAS NO such shape, and the op was rejected by the
        schema (`KIR-T001: неизвестные поля формы`) BEFORE the boundary
        loop. The test was red, but the subject was untouched: the probe
        was looking at the wrong input.

        🔴 THE FIX OF THAT FIX LOST THE SUBJECT A SECOND TIME (26.08.2026).
        The shape was replaced with `rect`, the schema let it through — and
        the test became red FOREVER, because a rectangle has ONE point:
        `origin`. The other three corners are DERIVED, are not authored,
        and by construction are not named in the refusal. Demanding "more
        than one named point" from such an input is impossible by any
        means.

        So the rectangle stays, but it checks ITS OWN thing: one authored
        point — exactly one refusal. Plurality is checked by the ring.
        """
        f = self.FAR
        return {"outer": {"shape": "rect", "origin": [f, f],
                          "size_mm": [3000, 1200]}}

    def _far_poly(self, n=4):
        """A RING of `n` AUTHORED points, with all `n` beyond the coverage
        limit."""
        f = self.FAR
        return {"outer": {"shape": "poly",
                          "points_mm": [[f + i * 1000, f] for i in range(n)]}}

    def _bounds_diags(self, contour):
        out = compile_program(_prog([_fr(contour=contour)]),
                              revit_version="2026", snapshot=SNAPSHOT)
        self.assertFalse(out.ok, "программа с вылетевшим контуром прошла")
        return [d for d in out.diagnostics
                if d.field_name and d.field_name.startswith("contour")]

    def test_all_offending_points_are_reported_not_the_first(self):
        """FOUR unfit points — FOUR named, not just the first.

        WHAT THIS BOUGHT: before 26.08, the ring-parsing loop returned
        `None` on the first unresolvable point, and the rest were never
        asked about at all. The author was fixing them one at a time — four
        rounds instead of one.
        """
        bound = self._bounds_diags(self._far_poly(4))
        named = {d.field_name for d in bound}
        self.assertEqual(
            len(named), 4,
            "отказ назвал %d точку(и) из четырёх вылетевших — модель будет "
            "чинить их по одной за ход, не зная, что их больше: %s"
            % (len(named), sorted(named)))

    def test_one_authored_point_yields_exactly_one_refusal(self):
        """AN UPPER-BOUND CONTROL: a rectangle has one point, one refusal.

        Without it, "name them all" would slide into "name the derived
        corners too", meaning the refusal would blame numbers the author
        never wrote.
        """
        bound = self._bounds_diags(self._far_rect())
        self.assertEqual([d.field_name for d in bound],
                         ["contour.outer.origin"], [d.field_name for d in bound])

    def test_a_ring_of_many_bad_points_is_capped_and_the_rest_is_NAMED(self):
        """THE LIST IS CAPPED, AND THE REMAINDER IS NAMED BY A NUMBER.

        The second half of the same fix: on a UNITS error, ALL points are
        unfit at once, and lifting the cap would have traded a silent loss
        for a refusal carrying sixty-four diagnostics. A truncation that
        stays silent about itself is the same defect as a loss: the reader
        cannot tell it apart from "that's all there was".
        """
        from kir.contour import _BAD_POINTS_SHOWN
        n = _BAD_POINTS_SHOWN + 8
        bound = self._bounds_diags(self._far_poly(n))
        per_point = [d for d in bound
                     if d.field_name.endswith("]")]
        self.assertEqual(len(per_point), _BAD_POINTS_SHOWN, len(per_point))
        rest = [d for d in bound if d not in per_point]
        self.assertEqual(len(rest), 1, [d.field_name for d in rest])
        self.assertEqual(rest[0].got, n,
                         "остаток обязан считаться ПОЛНЫМ числом негодных, "
                         "иначе приписка врёт тому, кто по ней чинит")

    def test_a_contour_inside_the_limit_yields_no_bounds_diagnostics(self):
        """PASS CONTROL: a valid contour gives NOT A SINGLE boundary
        refusal.

        Without it, the first test is green on an instrument that always
        refuses.
        """
        f = self.FAR
        # a rectangle entirely within bounds — the control must give ZERO
        one_bad = {"outer": {"shape": "rect", "origin": [500, 500],
                             "size_mm": [3000, 1200]}}
        out = compile_program(_prog([_fr(contour=one_bad)]),
                              revit_version="2026", snapshot=SNAPSHOT)
        bound = [d for d in out.diagnostics
                 if d.field_name and d.field_name.startswith("contour")]
        self.assertEqual(
            [], bound,
            f"годный контур дал отказы по границам: {bound}")
