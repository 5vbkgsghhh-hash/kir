"""wave/opening (2026-08-03): create_opening — an opening AS A SEPARATE ELEMENT.

TRIGGERED BY A MEASUREMENT, NOT AN IDEA. A survey of eight real buildings
found EXACTLY ONE silent loss across the whole pipeline, and this is it. An
opening in Revit is made by TWO different mechanisms:

  * an internal sketch loop in the host — WE KNOW HOW TO DO THIS (60
    `create_floor` calls with non-empty `holes` across three buildings);
  * a SEPARATE `Opening` element — this existed in no view at all: a grep
    across every `.py`/`.cs` gives zero mentions of `OST_ShaftOpening`,
    `OST_SWallRectOpening`, `OST_FloorOpening`, `OST_RoofOpening`, `Opening`,
    `NewOpening`.

Census: 35 elements across 3 of 6 buildings — OST_FloorOpening 10,
OST_ShaftOpening 9, OST_SWallRectOpening 9, OST_RoofOpening 7.

WHY THIS IS THE WORST CLASS OF DEFECT, NOT "one more uncovered category".
The element is not extracted ⇒ it produces NO atom ⇒ it is absent from the
cause map. Meanwhile the HOST gets raised by an ordinary
`create_floor`/`create_wall` and reassembled as SOLID. Acceptance would not
catch this: `acceptance.py` states outright that it DOES NOT LOOK AT
GEOMETRY AT ALL. That is, from the outside, a quietly wrong result is
indistinguishable from success — exactly the shape of error this whole
compiler exists to forbid.

THE DISPROVING TEST COMES FIRST. The classes below first pin down the
ABSENCE (the registry does not know the operation, reading does not know the
categories), and only then require presence — so that "we fixed it" is a
verifiable claim, not a story.

API MEASUREMENT (trap index `data/api_traps/revit_api_traps.sqlite`, tables
`member`/`prose`, plus a check against the reference XML of six packages):

    Creation.Document.NewOpening(Element, CurveArray, eRefFace)     6/6
    Creation.Document.NewOpening(Element, CurveArray, bool)         6/6
    Creation.Document.NewOpening(Level, Level, CurveArray)          6/6
    Creation.Document.NewOpening(Wall, XYZ, XYZ)                    6/6
    Opening.Host / .BoundaryRect / .IsRectBoundary / .BoundaryCurves 6/6
    Opening.SketchId                                          2022-2026 (5/6)

A spec remark, taken verbatim: "Slanted stacked walls do not support
rectangular openings" — meaning a Revit failure on a slanted/multi-layer
wall is a LEGITIMATE outcome, not our defect; it must arrive loudly.
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_opening_queue.jsonl"))

from kir import contour as contour_mod                        # noqa: E402
from kir import spec                                          # noqa: E402
from kir.compiler import compile_program                      # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT    # noqa: E402

HOST = {"by": "element_id", "value": 8145901}

#: A 2x2 m rectangle — an area well above the degenerate `pts` threshold.
SQUARE = [[1000, 1000], [3000, 1000], [3000, 3000], [1000, 3000]]

#: The same rectangle, said in the sketch's language.
SQUARE_REGION = {"outer": {"shape": "rect", "origin": [1000, 1000],
                           "size_mm": [2000, 2000]}}

#: And the same one with ONE rounded side — exactly what a polyline cannot
#: say at all: under `outline` an arc becomes a chord, i.e. a DIFFERENT opening.
ARC_REGION = {"outer": {"shape": "poly", "points_mm": SQUARE,
                        "arcs": [{"edge": 1, "bulge": 0.4}]}}


def _prog(ops, intent="opening-test", **kw):
    out = {"ir_version": "1.0", "intent": intent, "ops": ops}
    out.update(kw)
    return out


def _wall_rect(oid="O1", **kw):
    op = {"op": "create_opening", "id": oid, "variety": "wall_rect",
          "host": dict(HOST),
          "p0_mm": [1000.0, 0.0, 900.0], "p1_mm": [2500.0, 0.0, 2400.0]}
    op.update(kw)
    return op


def _host_face(oid="O1", **kw):
    op = {"op": "create_opening", "id": oid, "variety": "host_face",
          "host": dict(HOST), "outline": SQUARE, "cut": "vertical"}
    op.update(kw)
    return op


def _sketch(oid="O1", contour=None, **kw):
    """An opening as the SECOND entry point of the form: a sketch instead of
    a polyline.

    A separate constructor, not `_host_face(contour=...)`, and this is not a
    style choice: `_host_face` has the polyline hard-wired, and having both
    fields at once is a typed refusal, KIR-P007. A fixture supplying both
    fields would be testing the refusal while believing it tests
    construction."""
    op = {"op": "create_opening", "id": oid, "variety": "host_face",
          "host": dict(HOST),
          "contour": SQUARE_REGION if contour is None else contour,
          "cut": "vertical"}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


def _messages(out):
    return " ".join(d.message_ru or "" for d in out.diagnostics)


# ── 1. DISPROOF: the loss WAS silent ─────────────────────────────────────

class TheLossWasSilent(unittest.TestCase):
    """The shape of the defect, pinned down by measurement — so the fix is
    verifiable, not declarative.

    These assertions FAILED before the wave and must hold after it."""

    def test_the_op_exists_at_all(self):
        self.assertIn(
            "create_opening", spec.OPS,
            "проём отдельным элементом не выражался НИ ОДНОЙ операцией "
            "реестра — 35 элементов на 3 зданиях уходили в никуда")

    def test_a_solid_host_is_no_longer_the_only_expressible_answer(self):
        """Before the wave, the only expression of an opening was a loop in
        the host's sketch (`create_floor.holes`). An opening in an EXISTING
        floor that the program did not create had no means of expression at
        all."""
        out = compile_program(_prog([_host_face()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("NewOpening", out.csharp)

    def test_the_reading_side_names_the_opening_categories(self):
        """Reading must KNOW these categories by name: silence is worse than
        a refusal.

        What is checked is not "there is a riser" but "there is a typed
        answer": a category must either have a raise candidate or stand in
        the refusal map with a named operation."""
        from kir.decompile.lift import (
            _CANDIDATES, _OPS_WITHOUT_L0_INPUTS)
        known = set(_CANDIDATES) | set(_OPS_WITHOUT_L0_INPUTS)
        for category in ("OST_SWallRectOpening", "OST_FloorOpening",
                         "OST_RoofOpening"):
            with self.subTest(category=category):
                self.assertIn(
                    category, known,
                    "категория проёма обязана давать ЧЕСТНЫЙ АТОМ с "
                    "типизированной причиной, а не исчезать")


# ── 2. Registry ───────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_it_is_a_writer_of_the_authoring_family(self):
        op = spec.OPS["create_opening"]
        self.assertTrue(op.writes_model)
        self.assertEqual(op.family, "authoring")

    def test_it_grounds_nothing(self):
        """The opening HAS NO kind: not one of the four `NewOpening`
        overloads accepts one. So there should be no pool either: a pool for
        an operation that does not use it would be a promise with no
        bearer."""
        self.assertEqual(spec.OPS["create_opening"].grounded, ())

    def test_the_variety_enum_is_closed_to_what_is_witnessed(self):
        variety = next(p for p in spec.OPS["create_opening"].params
                       if p.name == "variety")
        self.assertEqual(set(variety.choices), {"wall_rect", "host_face"})
        self.assertTrue(variety.required)

    def test_the_discriminator_is_named_variety_not_kind(self):
        """The registry holds the word "kind" for the dictionary of Revit
        object kinds (SPEC 12.8), and `test_invariants` checks this BY THE
        FIELD'S NAME."""
        names = {p.name for p in spec.OPS["create_opening"].params}
        self.assertIn("variety", names)
        self.assertNotIn("kind", names)

    def test_the_promised_tolerance_lives_in_the_registry(self):
        self.assertIn("bbox_mm", spec.OPS["create_opening"].tolerances)


# ── 3. Version axis: it does not exist, and this is measured ──────────────

class VersionAxis(unittest.TestCase):
    """All four `NewOpening` overloads live on 2021-2026 (6/6). The
    operation has no version axis; if one ever appears, this test will see
    it first."""

    def test_wall_rect_builds_on_all_six(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_wall_rect()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("NewOpening(", out.csharp)

    def test_host_face_builds_on_all_six(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_host_face()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("NewOpening(", out.csharp)


# ── 4. The witness checks the RESULT, not an echo of the call ───────────────

class TheWitnessReadsTheResult(unittest.TestCase):
    """"The opening exists, belongs to the requested host, its size
    matches" — and each of the three is read FROM THE BUILT ELEMENT."""

    def _cs(self, op, ver="2024"):
        out = compile_program(_prog([op]), revit_version=ver,
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_host_membership_is_read_from_the_created_opening(self):
        for name, op in (("wall_rect", _wall_rect()),
                         ("host_face", _host_face())):
            with self.subTest(variety=name):
                cs = self._cs(op)
                self.assertIn(".Host", cs)
                self.assertIn("__post.Add(", cs)

    def test_the_wall_rect_extent_is_read_from_boundary_rect(self):
        """The size of a rectangular opening is read from the OPENING
        ITSELF (Opening.BoundaryRect), not recomputed from our own
        arguments."""
        cs = self._cs(_wall_rect())
        self.assertIn("BoundaryRect", cs)
        self.assertIn("IsRectBoundary", cs)

    def test_the_host_face_extent_is_read_from_the_bounding_box(self):
        cs = self._cs(_host_face())
        self.assertIn("get_BoundingBox(null)", cs)

    def test_every_tolerance_comes_from_the_registry(self):
        """LAW OF PROVENANCE: the tolerance number reaches C# only as the
        `emit_model.Tolerance` object. Touch the registry, and the bytes
        must move."""
        from kir import spec as spec_mod
        tolerances = spec_mod.OPS["create_opening"].tolerances
        before = self._cs(_host_face())
        key = "bbox_mm"
        original = tolerances[key]
        tolerances[key] = original * 1000.0 + 7.77
        try:
            after = self._cs(_host_face())
        finally:
            tolerances[key] = original
        self.assertNotEqual(before, after,
                            "допуск объявлен, но эмиссия его не читает — "
                            "дефект create_type")

    def test_a_null_result_is_a_refusal_not_a_success(self):
        for name, op in (("wall_rect", _wall_rect()),
                         ("host_face", _host_face())):
            with self.subTest(variety=name):
                self.assertIn("== null", self._cs(op))

    def test_one_transaction_and_regenerate_before_the_verdict(self):
        for name, op in (("wall_rect", _wall_rect()),
                         ("host_face", _host_face())):
            with self.subTest(variety=name):
                cs = self._cs(op)
                self.assertEqual(cs.count("new Transaction("), 1)
                self.assertLess(cs.index("doc.Regenerate()"),
                                cs.index("__post.Add("))

    def test_the_creation_is_stamped(self):
        for name, op in (("wall_rect", _wall_rect()),
                         ("host_face", _host_face())):
            with self.subTest(variety=name):
                self.assertIn("__stamp", self._cs(op))


# ── 4b. Opening from a CONTOUR sketch (09.08.2026) ────────────────────────────────

class OpeningContour(unittest.TestCase):
    """`variety="host_face"` gained a SECOND profile entry point —
    `contour`.

    Why parallel rather than a replacement: straight points are what
    materialize speaks in, and they cannot be taken away from the reverse
    side even while it is still silent for an opening (`CAPTURE_GAP`). Why
    at all: a round cutout for a riser and a rounded edge of a polyline are
    inexpressible — it gives a DIFFERENT shape, not an approximation (in the
    refusal map that is 27 elements, "polygon ops cannot represent an arc
    profile").
    """

    def _cs(self, op, ver="2024"):
        out = compile_program(_prog([op]), revit_version=ver,
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_a_sketch_opening_builds_on_all_six(self):
        """THE SKETCH HAS NO VERSION AXIS, and this is MEASURED against
        reference assemblies, not memory: NewOpening(Element, CurveArray,
        bool), Arc.Create(XYZ,XYZ,XYZ), Line.CreateBound, CurveArray.Append,
        Curve.Evaluate, Curve.GetEndPoint, Curve.IsBound — all 6/6. A
        version-gated refusal that the API does not require would be a lie
        of the same kind as silence where a refusal is needed."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                cs = self._cs(_sketch(contour=ARC_REGION), ver)
                self.assertIn("NewOpening(", cs)
                self.assertIn("Arc.Create", cs)

    def test_the_straight_outline_could_not_say_this_at_all(self):
        """DISPROOF FIRST: before this wave there was NOTHING to express a
        rounded side of an opening with, and it was not "a polyline
        approximation".

        An author writing the same four points into `outline` would get
        FOUR segments and silence — that is, a different opening,
        indistinguishable from the outside from the one requested. Here this
        is pinned down as A FACT ABOUT EMISSION: the straight branch has no
        arc and never gets one."""
        straight = self._cs(_host_face(outline=SQUARE))
        self.assertNotIn("Arc.Create", straight)
        self.assertEqual(straight.count("__ca_O1.Append("), 4)
        curved = self._cs(_sketch(contour=ARC_REGION))
        self.assertIn("Arc.Create", curved)
        # And their sizes are DIFFERENT — that is, these are two different
        # shapes, not one with a tolerance: the arc's sagitta pushes the
        # boundary 400 mm past the vertices at a tolerance of 50 mm.
        edges = contour_mod.validate_region(
            ARC_REGION, [], "O1", "contour", [])["outer"]
        bulged = contour_mod.edges_bbox(edges)[2] - max(p[0] for p in SQUARE)
        self.assertGreater(bulged,
                           spec.OPS["create_opening"].tolerances["bbox_mm"])

    def test_an_arc_edge_becomes_an_arc_not_a_chord(self):
        """The trigger for the wave: under `outline` an arc collapses into a
        chord. An arc must reach C# as `Arc.Create` with THREE literal
        points — all the trigonometry is computed in Python at the ground
        stage."""
        cs = self._cs(_sketch(contour=ARC_REGION))
        self.assertEqual(cs.count("Arc.Create"), 1)
        self.assertEqual(cs.count("__ca_O1.Append(Line.CreateBound"), 3)

    def test_the_profile_still_sits_on_the_host_plane_not_at_zero(self):
        """The profile elevation comes from the HOST, not from zero.

        THE UNITS CHANGED AT THE 09.08.2026 MERGE, the invariant did not.
        Before it, the elevation traveled in INTERNAL units and the point
        was assembled as `new XYZ(U(x), U(y), __z_O1)`, bypassing `P`. Now
        both branches of this op sit on the shared edge assembler
        `contour._edge_curve_cs`, whose convention is ONE, millimeter-based,
        as in the whole language — so `MM(...)` stands at the source, and
        the point is again the ordinary `P(x, y, z)`.

        The assertion was kept TWO-SIDED on purpose: zero elevation is a
        quiet lie (the 17th floor's profile would not intersect the host),
        while `MM` without `U` or `U` without `MM` would give a miss of
        about 304.8 times, which compiles identically on all six versions
        and is visible only live.
        """
        cs = self._cs(_sketch())
        self.assertIn(
            "double __z_O1 = MM((__hbb_O1.Min.Z + __hbb_O1.Max.Z) / 2.0)", cs)
        self.assertIn("P(1000.0, 1000.0, __z_O1)", cs)
        self.assertNotIn("__ca_O1.Append(Line.CreateBound(new XYZ(", cs)
        self.assertNotIn("double __z_O1 = (__hbb_O1", cs)

    def test_the_witness_knows_where_the_arc_bulges(self):
        """THE WITNESS READS THE RESULT, AND IT MUST KNOW THE UPPER BOUND
        FROM THE ARC. An arc's extreme point is almost never a vertex: the
        sagitta reaches past the polyline's bounding box, and checking
        against vertices would mean blaming a correctly built opening for
        exactly the arc it was built to have."""
        edges = contour_mod.validate_region(
            ARC_REGION, [], "O1", "contour", [])["outer"]
        x0, y0, x1, y1 = contour_mod.edges_bbox(edges)
        self.assertGreater(x1, 3000.0)          # the arc reached PAST the vertices
        cs = self._cs(_sketch(contour=ARC_REGION))
        self.assertIn(f"__ox1_O1 > {round(x1, 1)} + ", cs)

    def test_the_lower_bound_is_the_vertices_because_they_are_read_exactly(self):
        """The LOWER bound of the strip is the VERTICES, and this is not
        caution but the limit of what the API promises: a curve's end,
        `GetEndPoint`, is returned exactly, while an arc's extremum is only
        obtained by finite sampling via `Evaluate`, whose density the
        documentation does not promise. Requiring `edges_bbox` from below
        would mean assigning a tolerance to sampling density — i.e.,
        inventing a number."""
        edges = contour_mod.validate_region(
            ARC_REGION, [], "O1", "contour", [])["outer"]
        vx1 = contour_mod.edges_vertex_bbox(edges)[2]
        ex1 = contour_mod.edges_bbox(edges)[2]
        self.assertLess(vx1, ex1)               # the strip is non-empty right here
        cs = self._cs(_sketch(contour=ARC_REGION))
        self.assertIn(f"__ox1_O1 < {round(vx1, 1)} - ", cs)

    def test_a_straight_sketch_collapses_the_band_into_equality(self):
        """For a profile WITHOUT ARCS both bounds of the strip coincide,
        meaning the contour branch is not "weaker" than the straight one —
        it generalizes it and matches it wherever the straight branch is
        right."""
        edges = contour_mod.validate_region(
            SQUARE_REGION, [], "O1", "contour", [])["outer"]
        self.assertEqual(contour_mod.edges_bbox(edges),
                         contour_mod.edges_vertex_bbox(edges))

    def test_the_boundary_is_sampled_only_when_there_is_an_arc(self):
        """The sample is emitted EXACTLY where it adds a fact. For straight
        segments the endpoints already are the extrema, extra points would
        say nothing — but would make the emission of two equivalent profiles
        diverge."""
        straight = self._cs(_sketch())
        curved = self._cs(_sketch(contour=ARC_REGION))
        self.assertNotIn("Evaluate", straight)
        self.assertIn("__c_O1.GetEndPoint(__k_O1)", straight)
        self.assertIn("__c_O1.Evaluate(__k_O1 / 8.0, true)", curved)
        self.assertIn("if (!__c_O1.IsBound) continue;", curved)

    def test_the_sampling_density_is_the_canon_one_not_a_new_number(self):
        """"How many points we sample an arc at" must have ONE answer for
        the whole compiler: the same number the canon uses to unroll an arc
        in its own static laws."""
        cs = self._cs(_sketch(contour=ARC_REGION))
        self.assertIn(f"__k_O1 <= {contour_mod.ARC_SAMPLES};", cs)

    def test_the_tolerance_is_the_registered_one_not_a_new_number(self):
        """A new number here would be a bound assigned by reasoning — the
        very class of defect this house was built to forbid. Both branches
        of the form read ONE key."""
        tol = spec.OPS["create_opening"].tolerances["bbox_mm"]
        self.assertIn(f"> {tol}", self._cs(_host_face()))
        self.assertIn(f"+ {tol}", self._cs(_sketch(contour=ARC_REGION)))

    def test_a_grid_anchored_profile_resolves_through_relate(self):
        """CONTOUR is a consumer of the RELATE address grammar, and the
        opening gets it together with the field, not as separate work."""
        cs = self._cs(_sketch(contour={"outer": {
            "shape": "rect",
            "origin": {"at_grid": ["1", "А"], "offset_mm": [200, 200]},
            "size_mm": [1800, 1600]}}))
        # The point construction changed at the 09.08 merge (see the
        # neighboring test about the host plane): the shared edge
        # assembler's convention is millimeters, so it is `P` again, not
        # `new XYZ(U(...), ...)`. The resolved address from the axes is not
        # affected — it was already in millimeters.
        self.assertIn("P(200.0, 200.0, __z_O1)", cs)

    def test_the_perpendicular_cut_keeps_only_the_lower_bound(self):
        """On a slope the plan of a perpendicular cut is LEGITIMATELY wider
        than the profile, so it has no upper bound — its absence is named,
        not forgotten."""
        cs = self._cs(_sketch(contour=ARC_REGION, cut="perpendicular"))
        self.assertIn("opening extents do not cover the contour (geometry)",
                      cs)
        self.assertNotIn("leave the contour band", cs)


class TheCutWitnessPromisesOnlyWhatItCanRead(unittest.TestCase):
    """WHAT THE CUT WITNESS CAN AND CANNOT DO — is named, not left unsaid.

    An opening is a VOID: it has no body, `get_BoundingBox` makes it no
    promise, so the witness here is WEAKER than for a ceiling or a slab,
    where the built element's own bounding box is checked. Promising more
    than the API delivers is exactly the defect that got correct beams
    rolled back."""

    def test_the_promise_names_both_shape_inputs(self):
        post = spec.OPS["create_opening"].post
        self.assertIn("with outline", post)
        self.assertIn("with contour", post)

    def test_the_promise_names_what_is_deliberately_unwitnessed(self):
        """The named remainder is part of the promise, not a footnote: the
        arc's sagitta inside the strip and the depth of the cut are checked
        by NOTHING."""
        post = spec.OPS["create_opening"].post
        self.assertIn("unwitnessed", post)
        self.assertIn("sagitta", post)
        self.assertIn("depth of the cut", post)

    def test_no_witness_claims_the_host_was_actually_cut(self):
        """"Material removed" is not claimed offline at all: confirming it
        is only possible from the host body's volume before and after, i.e.
        a live Revit. Here what is checked is that C# carries NO such
        promise."""
        out = compile_program(_prog([_sketch()]), revit_version="2024",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertNotIn("__el_O1.get_BoundingBox", out.csharp)
        self.assertNotIn("Volume", out.csharp)

    def test_the_certificate_proves_the_sketch_branch_on_all_six(self):
        from kir import ground as ground_mod
        from kir.compiler import _parse_and_check
        from kir.translation_cert import certify_op
        grounded = ground_mod.ground(
            _parse_and_check(_prog([_sketch(contour=ARC_REGION)])),
            SNAPSHOT)[0]
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                self.assertTrue(certify_op(grounded, ver).proven)

    def test_the_two_shape_inputs_carry_different_obligation_keys(self):
        """A conditional obligation is discharged precisely by the ABSENCE
        of its own witness, so a shared key on two mutually exclusive
        branches would declare the neighboring branch's witness "extra" on
        every program."""
        from kir.opening_emit import emit_opening
        straight = emit_opening(_host_face(), "2024", "kir:test")[2]
        sketch_op = _sketch()
        sketch_op["__region__"] = contour_mod.validate_region(
            SQUARE_REGION, [], "O1", "contour", [])
        sketch = emit_opening(sketch_op, "2024", "kir:test")[2]
        self.assertIn("bbox", [c.obligation_key for c in straight])
        self.assertIn("bbox_contour", [c.obligation_key for c in sketch])


class OpeningShapeIsSaidExactlyOnce(unittest.TestCase):
    """MUTUAL OBLIGATION, exactly like `place_family` (xyz vs p0_mm/p1_mm),
    but for an operation with a `variety` fork it is SPLIT, and this is a
    decision:

      * "both at once" is ALWAYS ambiguous -> the plan refuses (KIR-P007);
      * "neither one" is known only by the KIND: `wall_rect` has no shape
        field at all, it is given by two corners, so a shared refusal "no
        shape given" would blame a correct program. The lower half lives in
        the kind's own branch (KIR-P005).
    """

    def test_both_shapes_at_once_are_refused_naming_both_fields(self):
        out = compile_program(_prog([_host_face(contour=SQUARE_REGION)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        self.assertIn("outline", _messages(out))
        self.assertIn("contour", _messages(out))

    def test_no_shape_at_all_is_refused_naming_both_fields(self):
        op = _host_face()
        del op["outline"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))
        self.assertIn("outline", _messages(out))
        self.assertIn("contour", _messages(out))

    def test_the_wall_rect_variety_is_not_accused_of_a_missing_shape(self):
        """A DISPROVING TEST FOR THE GENERALIZED RULE: a rectangular opening
        in a wall has neither `outline` nor `contour`, and it is a CORRECT
        program. A rule of "exactly one of the two", written without regard
        for the kind fork, would have turned it away."""
        out = compile_program(_prog([_wall_rect()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])

    def test_a_sketch_is_refused_on_the_variety_that_cannot_use_it(self):
        """A sketch cannot be silently dropped: `NewOpening(Wall, XYZ, XYZ)`
        does not accept a profile at all, and accepting a field that no one
        looks at would mean building a rectangle where the author wrote an
        arc."""
        out = compile_program(_prog([_wall_rect(contour=SQUARE_REGION)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        self.assertIn("host_face", _messages(out))

    def test_a_broken_sketch_is_not_re_told_as_a_missing_shape(self):
        """A field already stated more specifically is not retold by a
        second, more general voice."""
        out = compile_program(
            _prog([_sketch(contour={"outer": {"shape": "rect",
                                              "origin": [0, 0],
                                              "size_mm": [1, 1]}})]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertNotIn("KIR-P005", _codes(out))

    def test_the_straight_outline_branch_is_untouched(self):
        """Byte stability of earlier programs: without `contour` the
        emission is the same polyline and the same endpoint walk as before
        (the real guard of this claim is
        golden/opening_host_face_*.golden.cs)."""
        out = compile_program(_prog([_host_face()]), revit_version="2024",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertNotIn("Arc.Create", out.csharp)
        self.assertNotIn("Evaluate", out.csharp)
        self.assertEqual(out.csharp.count("__ca_O1.Append(Line.CreateBound"), 4)


class AHoleInsideAnOpeningIsRefusedNotDropped(unittest.TestCase):
    """A sketch can have up to 8 loops, while an opening has EXACTLY ONE
    profile.

    `NewOpening(Element, CurveArray, bool)` accepts a single `CurveArray`
    ("Profile of the opening", singular), not a list of loops the way
    `Floor.Create`/`Ceiling.Create` do. Appending a second loop to the same
    array is a self-intersecting profile; silently dropping it is a loss of
    what was written."""

    HOLED = {"outer": {"shape": "rect", "origin": [1000, 1000],
                       "size_mm": [4000, 4000]},
             "holes": [{"shape": "rect", "origin": [2000, 2000],
                        "size_mm": [1000, 1000]}]}

    def test_it_is_a_typed_refusal(self):
        out = compile_program(_prog([_sketch(contour=self.HOLED)]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        from kir.diag import EMIT_CONTOUR_HOLES
        self.assertIn(EMIT_CONTOUR_HOLES, _codes(out))

    def test_the_reason_comes_from_the_one_table_not_retyped(self):
        """Three separately typed-out texts of one fact drift apart — this
        house already paid for exactly that with the category pairing on
        29.07."""
        from kir.ops_opening import CONTOUR_HOLES_NOT_EXPRESSIBLE
        out = compile_program(_prog([_sketch(contour=self.HOLED)]),
                              snapshot=SNAPSHOT)
        self.assertIn(CONTOUR_HOLES_NOT_EXPRESSIBLE, _messages(out))

    def test_it_is_not_confused_with_an_unsupported_variety(self):
        """"No such opening kind exists" and "the kind taken has no such
        shape" are different repairs, hence different codes."""
        from kir.diag import (
            EMIT_CONTOUR_HOLES, EMIT_UNSUPPORTED_ENUM)
        self.assertNotEqual(EMIT_CONTOUR_HOLES, EMIT_UNSUPPORTED_ENUM)

    def test_a_region_without_holes_is_untouched(self):
        out = compile_program(_prog([_sketch()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])


# ── 5. Refusals: named, not silent ───────────────────────────────────────

class NoSilentLoss(unittest.TestCase):

    def test_the_shaft_variety_is_refused_and_named(self):
        """A SHAFT IS NOT SUPPORTED, AND THIS IS A DECISION, NOT AN
        OVERSIGHT: a shaft's link to a PAIR OF LEVELS has nothing to read it
        from the built element (a shaft has no host, and the
        BuiltInParameter for the base/top constraint is undocumented in all
        six packages). No witness for "belongs to the requested one" is
        achievable, so the kind does not exist."""
        out = compile_program(_prog([_host_face(variety="shaft")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_the_reason_for_every_variety_left_out_is_written_down(self):
        from kir.ops_opening import VARIETIES_NOT_TAKEN
        self.assertEqual(set(VARIETIES_NOT_TAKEN), {"shaft", "framing"})
        for variety, entry in VARIETIES_NOT_TAKEN.items():
            with self.subTest(variety=variety):
                self.assertGreater(len(entry.reason), 60,
                                   "причина обязана быть причиной, а не меткой")

    def test_the_emitter_refusal_names_the_variety_and_its_reason(self):
        """"Unsupported" WITHOUT A REASON is indistinguishable from
        "forgotten".

        Belt over the emitter's suspenders is the one place where an
        unsupported kind is spoken aloud together with a reason. What is
        checked is that EXACTLY THE REASON FROM ONE TABLE is spoken, not a
        freshly retyped text: three different phrasings of one fact drift
        apart, and this house already paid for exactly that with the
        category pairing on 29.07."""
        from kir.diag import KirRefusal
        from kir.diag import EMIT_UNSUPPORTED_ENUM
        from kir.opening_emit import emit_opening
        from kir.ops_opening import VARIETIES_NOT_TAKEN
        for variety, entry in VARIETIES_NOT_TAKEN.items():
            why = entry.reason
            with self.subTest(variety=variety):
                with self.assertRaises(KirRefusal) as caught:
                    emit_opening({"op": "create_opening", "id": "O1",
                                  "variety": variety}, "2024", "kir:test")
                diag = caught.exception.diagnostics[0]
                self.assertEqual(diag.code, EMIT_UNSUPPORTED_ENUM)
                self.assertIn(variety, diag.message_ru)
                self.assertIn(why, diag.message_ru)
                self.assertEqual(diag.candidates, ["wall_rect", "host_face"])

    def test_an_unknown_variety_is_typed(self):
        out = compile_program(_prog([_host_face(variety="skylight")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_wall_rect_without_a_host_is_typed(self):
        op = _wall_rect()
        del op["host"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_wall_rect_without_corners_is_typed(self):
        op = _wall_rect()
        del op["p1_mm"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_host_face_without_an_outline_is_typed(self):
        op = _host_face()
        del op["outline"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_host_face_without_a_named_cut_is_typed(self):
        """`cut` HAS NO DEFAULT. A vertical and a perpendicular cut coincide
        only on a flat host; substituting one for the author would mean, on
        a slope, delivering a different opening while staying silent about
        it."""
        op = _host_face()
        del op["cut"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_the_corners_may_not_coincide(self):
        out = compile_program(
            _prog([_wall_rect(p1_mm=[1000.0, 0.0, 900.0])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)

    def test_the_wall_rect_corners_are_three_dimensional(self):
        """An opening in a wall is a rectangle IN THE WALL'S PLANE, and its
        height is Z. A two-dimensional point would silently drift to
        elevation 0."""
        out = compile_program(_prog([_wall_rect(p0_mm=[1000.0, 0.0])]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_a_degenerate_outline_is_refused(self):
        """🔴 THE FIXTURE IS DERIVED FROM THE THRESHOLD, NOT WRITTEN AS A
        NUMBER (21.08.2026).

        A 10x10 mm literal stood here. It was degenerate under the
        `MIN_RING_AREA_MM2` = 10,000 mm² threshold, and stopped being
        degenerate when the threshold was lowered to 100 on 21.08: 10x10 =
        EXACTLY 100 mm², and the comparison is strict (`area < threshold`),
        meaning the contour became LEGITIMATE. The test turned red not about
        the product, but because its own number had fallen behind the
        registry.

        The square's side is now computed FROM THE THRESHOLD and taken
        deliberately below it. This way the check survives every future
        move of the number and keeps measuring THE SAME THING: a degenerate
        contour is rejected.

        The second half is the CONTROL. A check that rejects everything is
        indistinguishable from "the op is broken": next to it stands a
        contour ABOVE the threshold, and it must pass.
        """
        from kir.geom import MIN_RING_AREA_MM2

        side_bad = (MIN_RING_AREA_MM2 ** 0.5) / 2.0      # area = threshold/4
        out = compile_program(
            _prog([_host_face(outline=[[0, 0], [side_bad, 0],
                                       [side_bad, side_bad], [0, side_bad]])]),
            snapshot=SNAPSHOT)
        self.assertFalse(out.ok, "контур площадью вчетверо ниже порога обязан "
                                 "быть отвергнут")

        side_ok = (MIN_RING_AREA_MM2 ** 0.5) * 4.0       # area = threshold*16
        control = compile_program(
            _prog([_host_face(outline=[[0, 0], [side_ok, 0],
                                       [side_ok, side_ok], [0, side_ok]])]),
            snapshot=SNAPSHOT)
        self.assertTrue(control.ok, _codes(control)[:3])

    def test_a_host_that_is_not_a_wall_is_refused_at_runtime_not_guessed(self):
        """`as Wall` plus a typed refusal: a foreign id must fail loudly,
        not build an opening "somewhere"."""
        out = compile_program(_prog([_wall_rect()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("as Wall", out.csharp)


# ── 6. Reference to this same program's own host ─────────────────────────────────

class HostMayBeEitherPinnedOrIntraProgram(unittest.TestCase):
    """An opening is cut both in an EXISTING host ("make an opening in this
    slab") and in one just built. Both paths must work — exactly like
    `create_railing`, whose owner can also be either foreign or its own."""

    def test_a_ref_to_a_wall_of_the_same_program(self):
        out = compile_program(_prog([
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "level": {"by": "element_id", "value": 42},
             "height_mm": 3000},
            _wall_rect(oid="O1", host={"by": "ref", "value": "W1"}),
        ]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])

    def test_a_ref_to_a_floor_of_the_same_program(self):
        out = compile_program(_prog([
            {"op": "create_floor", "id": "F1",
             "outline": [[0, 0], [8000, 0], [8000, 6000], [0, 6000]],
             "level": {"by": "element_id", "value": 42}},
            _host_face(oid="O1", host={"by": "ref", "value": "F1"}),
        ]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])

    def test_a_ref_to_something_that_was_never_created_is_refused(self):
        out = compile_program(_prog([
            _host_face(oid="O1", host={"by": "ref", "value": "NOPE"}),
        ]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", _codes(out))


# ── 7. Acceptance knows where the result will land ────────────────────────────

class AcceptanceKnowsTheCategory(unittest.TestCase):
    """An op with an UNKNOWN category strips acceptance's upper bounds
    ENTIRELY (acceptance.py). An opening must name its category, or a single
    new operation would weaken L2 for the whole program."""

    def test_the_wall_rect_category_is_exact(self):
        from kir.acceptance import _category_of_op
        self.assertEqual(_category_of_op(_wall_rect()),
                         ("OST_SWallRectOpening",))

    def test_the_host_face_category_is_a_named_sum_not_none(self):
        from kir.acceptance import _category_of_op
        categories = _category_of_op(_host_face())
        self.assertIsNotNone(
            categories,
            "неизвестная категория снимает верхние границы всей программы")
        self.assertEqual(set(categories),
                         {"OST_FloorOpening", "OST_RoofOpening",
                          "OST_CeilingOpening"})


# ── 8. The reverse path is declared ────────────────────────────────────────────

class TheReverseDirectionIsDeclared(unittest.TestCase):

    def test_the_manifest_covers_the_new_op(self):
        from kir.reverse_contract import REVERSE_CONTRACTS
        self.assertIn("create_opening", REVERSE_CONTRACTS)

    def test_it_does_not_promise_the_form_it_cannot_read(self):
        """🔴 A MODE NAME STOOD HERE, AND IT HAD ROTTED (04.09.2026).

        The test required `CAPTURE_GAP`, and that was true before `34d2121`:
        L0 1.0 carried neither `Opening.Host` nor the opening's boundary.
        Now the boundary is read (`IsRectBoundary`, and from it either
        `BoundaryRect` or `BoundaryCurves`), the mode became `DIRECT` — that
        is, the red brought a FIX, not a regression. A copy of the table on
        foreign ground goes stale before the table itself does; the manifest
        and the laws over it live in
        `kir/decompile/tests/test_reverse_contract.py`, and this is the same
        remedy the house prescribed itself on 11.08.2026: ASK THE AUTHORITY,
        rather than declaring what it holds.

        What stays true both before and after the fix: `Autodesk.Revit.DB.Opening`
        has SEVEN members across all six versions, and a cut direction is
        not among them — so an opening on a host face has no witness for it,
        `FORM_EXACT` is NEVER achievable, and what is lost must be named.
        The contract's constructor checks neither."""
        from kir.reverse_contract import REVERSE_CONTRACTS, ReverseGuarantee
        contract = REVERSE_CONTRACTS["create_opening"]
        self.assertIsNot(contract.guarantee, ReverseGuarantee.FORM_EXACT)
        self.assertTrue(contract.limitation)


# ── 9. Property ─────────────────────────────────────────────────────────────

class OpeningPBT(unittest.TestCase):

    def test_well_typed_wall_openings_always_compile(self):
        rng = random.Random(3082026)
        for i in range(40):
            x0 = rng.randrange(-40000, 40000)
            z0 = rng.randrange(0, 2500)
            op = _wall_rect(
                oid=f"O{i}",
                p0_mm=[float(x0), 0.0, float(z0)],
                p1_mm=[float(x0 + rng.randrange(600, 4000)), 0.0,
                       float(z0 + rng.randrange(600, 2500))])
            with self.subTest(i=i):
                out = compile_program(_prog([op]), revit_version="2021",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])

    def test_well_typed_host_face_openings_always_compile(self):
        rng = random.Random(3082027)
        for i in range(40):
            x0 = rng.randrange(-40000, 40000)
            y0 = rng.randrange(-40000, 40000)
            w = rng.randrange(500, 9000)
            h = rng.randrange(500, 9000)
            op = _host_face(
                oid=f"O{i}",
                outline=[[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]],
                cut=rng.choice(("vertical", "perpendicular")))
            with self.subTest(i=i):
                out = compile_program(_prog([op]), revit_version="2026",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])

    def test_well_typed_sketch_openings_always_compile(self):
        """The same law for the second form entry point: a well-typed sketch
        must always reach C#, arc edges included, on 2021 too — the sketch
        has no version axis."""
        rng = random.Random(9082028)
        for i in range(40):
            x0 = rng.randrange(-40000, 40000)
            y0 = rng.randrange(-40000, 40000)
            w = rng.randrange(500, 9000)
            h = rng.randrange(500, 9000)
            points = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
            region = {"outer": {"shape": "poly", "points_mm": points}}
            if rng.random() < 0.5:
                # An arc bulging OUTWARD along the short edge: an outward
                # sagitta cannot cross the opposite side, so the program
                # stays well-typed by construction.
                edge, bulge = (0, -0.3) if w <= h else (1, 0.3)
                region["outer"]["arcs"] = [{"edge": edge, "bulge": bulge}]
            op = _sketch(oid=f"O{i}", contour=region,
                         cut=rng.choice(("vertical", "perpendicular")))
            with self.subTest(i=i):
                out = compile_program(_prog([op]),
                                      revit_version=rng.choice(
                                          list(spec.REVIT_VERSIONS)),
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()
