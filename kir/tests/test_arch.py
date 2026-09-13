"""wave/arch (2026-07-29): create_ceiling / create_railing.

WHY THIS WAVE. A full decompile of real working drawings
(13A-RD-AR-K2_v33, a 59-story tower, 55,293 elements) showed that part of
the model cannot be expressed by the compiler not because a lifter is
broken, but because THE OPERATION DOES NOT EXIST AT ALL: the registry has
32 writers, and among them were neither ceilings nor railings — content
present in EVERY architectural project. Cause 611 in the lift's cause map
(commit 9c63cc4e) names them by name: StairsRailing 203 and Ceilings 81 on
K2.

The structure mirrors test_struct.py 1:1 (Ground / VersionAxis / Negative
/ CommitGateInvariants / PBT) — the same invariant graph already proved
for create_beam/create_foundation.

THE VERSION AXIS IS MEASURED BY COMPILATION, NOT BY MEMORY (compare:
extract.py on `_CATEGORY_SPECS` — "RevitAPI.xml has no BuiltInCategory
members at all, so the only honest way to check is the compile service").
Measured on 29.07 across the six versions via :52412:

    Ceiling.Create(doc, IList<CurveLoop>, typeId, levelId)   2022-2026 (5/6)
        2021: CS0117 'Ceiling' does not contain a definition for 'Create'
    doc.Create.NewCeiling(...)                               NONE (0/6)
        CS1061 'Document' does not contain a definition for 'NewCeiling'
    Railing.Create(doc, CurveLoop, typeId, levelId)          2021-2026 (6/6)
    Railing.Create(doc, hostId, typeId, RailingPlacementPosition)  6/6
    RailingPlacementPosition.Treads / .Stringer              6/6
        .Left/.Right/.Landing/.Run/.None/.Center             NONE (0/6)
    ElementTypeGroup.CeilingType                             6/6
    ElementTypeGroup.RailingType                             NONE (0/6)
    BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM          6/6
    BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM         6/6

Two structural conclusions follow from this measurement, not one:

1. On 2021 the ceiling has NO creation path AT ALL — not "a different
   overload," but none whatsoever. So the only honest answer on 2021 is a
   typed KIR-E003 refusal, exactly as with create_floor and its openings.
2. Unlike a floor, a railing has NO default type in the document
   (ElementTypeGroup.RailingType does not exist on any version). So
   create_railing has NO RIGHT to substitute "a default": a missing type
   follows ground.py's general rule — the sole member of the pool, or a
   typed refusal. This is §18.1, "silent loss is forbidden," in practice.
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_arch_queue.jsonl"))

from kir import contour as contour_mod                  # noqa: E402
from kir import spec                                    # noqa: E402
from kir.compiler import compile_program                # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}

#: A 2.5×2.5 m rectangle — an area knowingly larger than the degenerate threshold.
SQUARE = [[0, 0], [2500, 0], [2500, 2500], [0, 2500]]

#: The same rectangle, said in the language of a sketch.
RECT_REGION = {"outer": {"shape": "rect", "origin": [0, 0],
                         "size_mm": [2500, 2500]}}


def _prog(ops, intent="arch-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _ceiling(oid="C1", **kw):
    op = {"op": "create_ceiling", "id": oid, "outline": SQUARE, "level": LVL}
    op.update(kw)
    return op


def _ceiling_sketch(oid="C1", contour=None, **kw):
    """A ceiling by a SECOND shape input: a sketch instead of a polyline.

    A separate constructor, not `_ceiling(contour=...)`, and this is not a
    matter of style: `_ceiling` has the polyline hard-wired in, and both
    inputs at once is a typed KIR-P007 refusal. A fixture supplying both
    fields would be testing the refusal while believing it tests the
    build."""
    op = {"op": "create_ceiling", "id": oid, "level": LVL,
          "contour": RECT_REGION if contour is None else contour}
    op.update(kw)
    return op


def _railing_path(oid="R1", **kw):
    op = {"op": "create_railing", "id": oid, "variety": "path",
          "path": [[0, 0], [3000, 0]], "level": LVL}
    op.update(kw)
    return op


def _railing_hosted(oid="R1", **kw):
    op = {"op": "create_railing", "id": oid, "variety": "hosted",
          "host": {"by": "element_id", "value": 777}, "position": "treads"}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


# ── registry ───────────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_both_ops_are_registered(self):
        self.assertIn("create_ceiling", spec.OPS)
        self.assertIn("create_railing", spec.OPS)

    def test_they_declare_themselves_as_writers(self):
        for name in ("create_ceiling", "create_railing"):
            with self.subTest(op=name):
                self.assertTrue(spec.OPS[name].writes_model)
                self.assertEqual(spec.OPS[name].family, "authoring")

    def test_the_type_pools_are_their_own(self):
        """A ceiling is NOT grounded against floor_types; a railing is
        grounded against its own pool. A foreign pool would give a
        plausible but wrong type: exactly the silent substitution §18.1
        forbids."""
        ceiling = {p: pool for p, pool, _ in spec.OPS["create_ceiling"].grounded}
        railing = {p: pool for p, pool, _ in spec.OPS["create_railing"].grounded}
        self.assertEqual(ceiling["type"], "ceiling_types")
        self.assertEqual(railing["type"], "railing_types")


# ── the version axis: ceiling ──────────────────────────────────────────────────

class CeilingVersionAxis(unittest.TestCase):

    def test_it_builds_on_2022_and_later(self):
        for ver in ("2022", "2023", "2024", "2025", "2026"):
            with self.subTest(version=ver):
                out = compile_program(_prog([_ceiling()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("Ceiling.Create(", out.csharp)

    def test_2021_is_a_typed_refusal_not_a_silent_substitute(self):
        """On 2021 the ceiling has NOT ONE creation path (measured:
        Ceiling.Create is absent, doc.Create.NewCeiling does not exist on
        any version). Silently building a floor in place of a ceiling
        would be the worst of all possible outcomes — "did something
        else" reads as success."""
        out = compile_program(_prog([_ceiling()]),
                              revit_version="2021", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-E003", _codes(out))

    def test_the_2021_refusal_says_why(self):
        out = compile_program(_prog([_ceiling()]),
                              revit_version="2021", snapshot=SNAPSHOT)
        message = " ".join(d.message_ru or "" for d in out.diagnostics)
        self.assertIn("2021", message)
        self.assertIn("Ceiling.Create", message)

    def test_2021_never_emits_a_floor_instead(self):
        out = compile_program(_prog([_ceiling()]),
                              revit_version="2021", snapshot=SNAPSHOT)
        self.assertNotIn("NewFloor", out.csharp or "")
        self.assertNotIn("Floor.Create", out.csharp or "")


# ── ceiling by a CONTOUR sketch (09.08.2026) ───────────────────────────────────

class CeilingContour(unittest.TestCase):
    """The ceiling gained a SECOND shape input — `contour` of kind `region`.

    Why parallel, not a replacement: the reverse pass (`_lift_ceiling` ->
    materialize) emits `outline`/`holes`, and a replacement would break
    the loop open on every ceiling of every decompiled building. Why at
    all: a polyline does not express an arc — it gives a DIFFERENT shape,
    not an approximation, that is, exactly the same class of defect as "a
    flat ceiling instead of a sloped one".
    """

    ARC_REGION = {"outer": {"shape": "poly",
                            "points_mm": [[0, 0], [6000, 0],
                                          [6000, 4000], [0, 4000]],
                            "arcs": [{"edge": 1, "bulge": 0.4}]}}

    def test_a_sketch_ceiling_builds_on_2022_and_later(self):
        for ver in ("2022", "2023", "2024", "2025", "2026"):
            with self.subTest(version=ver):
                out = compile_program(_prog([_ceiling_sketch()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("Ceiling.Create(doc, __loops_C1", out.csharp)
                self.assertEqual(out.csharp.count("new CurveLoop()"), 1)

    def test_an_arc_edge_becomes_an_arc_not_a_chord(self):
        """This is exactly the reason for the wave: under `outline` an arc
        collapses into a chord, that is, into a different shape. The arc
        MUST reach the C# as Arc.Create with THREE literal points — all
        the trigonometry stays in Python."""
        out = compile_program(_prog([_ceiling_sketch(contour=self.ARC_REGION)]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Arc.Create"), 1)
        self.assertEqual(out.csharp.count("__ol_C1.Append(Line.CreateBound"), 3)

    def test_the_bbox_witness_knows_where_the_arc_bulges(self):
        """THE WITNESS READS THE RESULT, AND MUST READ IT BY THE CORRECT NUMBER.

        For an arc, the extreme point is almost never a vertex: the bulge
        extends beyond the polyline's bounding box. Reconciling against
        vertices would accuse a correctly built ceiling on exactly the arc
        the sketch was taken for in the first place, so the number is
        taken from `contour.edges_bbox` (with the cardinal extremes
        included)."""
        region = compile_program(
            _prog([_ceiling_sketch(contour=self.ARC_REGION)]),
            revit_version="2024", snapshot=SNAPSHOT)
        self.assertTrue(region.ok, _codes(region)[:3])
        edges = contour_mod.validate_region(
            self.ARC_REGION, [], "C1", "contour", [])["outer"]
        x0, y0, x1, y1 = contour_mod.edges_bbox(edges)
        self.assertGreater(x1, 6000.0)          # the arc EXTENDED beyond the vertices
        self.assertIn(f"MM(__bb.Max.X) - {round(x1, 1)}", region.csharp)
        self.assertIn(f"MM(__bb.Min.X) - {round(x0, 1)}", region.csharp)

    def test_the_tolerance_is_the_registered_one_not_a_new_number(self):
        """A new number here would be a boundary assigned by reasoning —
        this house's defective class. Both branches read ONE registry key,
        and it is numerically the same as the contour slab's (the same
        witness over the same edges_bbox)."""
        tol = spec.OPS["create_ceiling"].tolerances["bbox_mm"]
        self.assertEqual(
            tol, spec.OPS["create_floor_by_contour"].tolerances["bbox_mm"])
        out = compile_program(_prog([_ceiling_sketch()]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertIn(f"> {tol}", out.csharp)

    def test_a_hole_in_the_region_reaches_the_loop_list(self):
        with_hole = {"outer": {"shape": "rect", "origin": [0, 0],
                               "size_mm": [6000, 4000]},
                     "holes": [{"shape": "rect", "origin": [1000, 1000],
                                "size_mm": [1000, 1000]}]}
        out = compile_program(_prog([_ceiling_sketch(contour=with_hole)]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("__loops_C1.Add(__hl_C1_0);", out.csharp)

    def test_a_grid_anchored_sketch_resolves_through_relate(self):
        """CONTOUR is a consumer of the RELATE addressing grammar, and the
        ceiling gets it along with the field, not as separate work."""
        out = compile_program(_prog([_ceiling_sketch(contour={"outer": {
            "shape": "rect", "origin": {"at_grid": ["1", "А"],
                                        "offset_mm": [200, 200]},
            "size_mm": [3800, 4300]}})]),
            revit_version="2024", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("P(200.0, 200.0, 0)", out.csharp)


class CeilingShapeIsSaidExactlyOnce(unittest.TestCase):
    """MUTUAL EXCLUSIVITY, exactly as with place_family (xyz vs p0_mm/p1_mm).

    "Both at once" and "neither" are equally ambiguous: in the first case
    it is unclear which of the two shape descriptions is true, in the
    second there is nothing to build. A schema cannot say this, so the
    rule lives in the compiler and MUST be a typed refusal, not a guess."""

    def test_both_shapes_at_once_are_refused_naming_both_fields(self):
        out = compile_program(
            _prog([_ceiling(contour=RECT_REGION)]),
            revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        message = " ".join(d.message_ru or "" for d in out.diagnostics)
        self.assertIn("outline", message)
        self.assertIn("contour", message)

    def test_no_shape_at_all_is_refused_naming_both_fields(self):
        op = _ceiling()
        del op["outline"]
        out = compile_program(_prog([op]), revit_version="2024",
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))
        message = " ".join(d.message_ru or "" for d in out.diagnostics)
        self.assertIn("outline", message)
        self.assertIn("contour", message)

    def test_flat_holes_beside_a_sketch_are_refused(self):
        """A sketch has its OWN holes (region.holes). Accepting a flat
        `holes` alongside it as well would mean taking one description of
        openings and silently discarding the other — a silent loss, §18.1."""
        out = compile_program(
            _prog([_ceiling_sketch(contour={"outer": {"shape": "rect",
                                                      "origin": [0, 0],
                                                      "size_mm": [9000, 9000]}},
                                   holes=[SQUARE])]),
            revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P007", _codes(out))

    def test_a_broken_outline_is_not_re_told_as_a_missing_shape(self):
        """A field that has already been described more specifically is
        not retold in a second, more generic voice: "a contour of 3..64
        points" is more useful than "there is no shape"."""
        out = compile_program(_prog([_ceiling(outline=[[0, 0], [1, 1]])]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertEqual(["KIR-T001"], _codes(out))

    def test_the_straight_outline_branch_is_untouched(self):
        """Byte-stability of prior programs: without `contour` the
        emission is the same polyline it always was (the reference is
        golden/arch_ceiling.golden.cs, which is itself the real guard of
        this assertion)."""
        out = compile_program(_prog([_ceiling()]), revit_version="2024",
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertNotIn("Arc.Create", out.csharp)
        self.assertEqual(out.csharp.count("__ol_C1.Append(Line.CreateBound"), 4)


class CeilingContourHasNoLegacyPathEither(unittest.TestCase):
    """THE SKETCH'S VERSION AXIS IS THE SAME AS THE POLYLINE'S, AND THIS
    HAS BEEN RE-VERIFIED.

    The temptation was symmetric: on 2021, `create_floor_by_contour` has a
    legacy path, `doc.Create.NewFloor(CurveArray, ...)`, and `contour.py`
    holds `emit_curvearray_cs` for it. For the ceiling there is NOWHERE to
    fall back to — reconciled against the 2021 reference assemblies
    (RevitAPI.xml: the type `Ceiling` exists, members matching
    `M:...Ceiling.*` number zero; the string `NewCeiling` is in no XML and
    in no RevitAPI.dll), — so the refusal stands BEFORE the shape is even
    parsed, and covers both branches alike."""

    def test_a_sketch_ceiling_on_2021_is_the_same_typed_refusal(self):
        out = compile_program(_prog([_ceiling_sketch()]),
                              revit_version="2021", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-E003", _codes(out))

    def test_the_2021_refusal_blames_the_version_not_the_holes(self):
        """For the floor slab, OPENINGS along the contour fail on 2021 (the
        slab itself is built via CurveArray). For the ceiling, openings are
        irrelevant: the operation itself does not exist, and this must be
        said outright, or the author will remove the opening and try again."""
        holed = {"outer": {"shape": "rect", "origin": [0, 0],
                           "size_mm": [6000, 4000]},
                 "holes": [{"shape": "rect", "origin": [1000, 1000],
                            "size_mm": [1000, 1000]}]}
        out = compile_program(_prog([_ceiling_sketch(contour=holed)]),
                              revit_version="2021", snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-E003", _codes(out))
        message = " ".join(d.message_ru or "" for d in out.diagnostics)
        self.assertIn("Ceiling.Create", message)
        self.assertIn("2021", message)
        self.assertNotIn("проём", message)
        self.assertNotIn("отверст", message)

    def test_2021_never_emits_a_curvearray_ceiling(self):
        out = compile_program(_prog([_ceiling_sketch()]),
                              revit_version="2021", snapshot=SNAPSHOT)
        self.assertNotIn("CurveArray", out.csharp or "")
        self.assertNotIn("NewCeiling", out.csharp or "")
        self.assertNotIn("NewFloor", out.csharp or "")


# ── version axis: railing ─────────────────────────────────────────────────

class RailingVersionAxis(unittest.TestCase):

    def test_the_path_variety_builds_on_all_six(self):
        """The railing HAS NO version axis — measured 6/6. If one ever
        appears, this test will see it first."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_railing_path()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("Railing.Create(", out.csharp)

    def test_the_hosted_variety_builds_on_all_six(self):
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_railing_hosted()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("RailingPlacementPosition.Treads", out.csharp)


# ── path geometry ───────────────────────────────────────────────────────────

class RailingPathIsNotARing(unittest.TestCase):
    """The railing's path is an OPEN polyline, not a closed contour.

    That is exactly why it has its own parameter kind `path`, rather than
    `pts`: `pts` requires >=3 points AND nonzero AREA (authoring.py, the
    "pts" branch), i.e. by construction it describes a ring. A straight
    railing along a stair flight — two points and zero area — would be
    rejected under `pts` as a «degenerate contour», while a closed railing
    under `pts` would come back into the model with an extra closing
    segment that is not in the source."""

    def test_two_points_are_a_legal_railing(self):
        out = compile_program(_prog([_railing_path()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])

    def test_a_single_point_is_refused(self):
        out = compile_program(_prog([_railing_path(path=[[0, 0]])]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_the_path_is_not_closed_behind_our_back(self):
        """Three points forming an L-shape: there must be TWO segments, not
        three."""
        out = compile_program(
            _prog([_railing_path(path=[[0, 0], [3000, 0], [3000, 3000]])]),
            snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Line.CreateBound"), 2)

    def test_a_zero_length_segment_is_refused(self):
        out = compile_program(
            _prog([_railing_path(path=[[0, 0], [0, 0]])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)


# ── refusal instead of silent substitution ─────────────────────────────────

class NoSilentLoss(unittest.TestCase):
    """§18.1. The past cost of this mistake is known: «0 degrees instead
    of no angle at all» cost 96% of the groups."""

    def test_a_missing_path_on_the_path_variety_is_typed(self):
        op = _railing_path()
        del op["path"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_a_missing_host_on_the_hosted_variety_is_typed(self):
        op = _railing_hosted()
        del op["host"]
        out = compile_program(_prog([op]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P005", _codes(out))

    def test_an_unknown_variety_is_typed(self):
        """KIR-T001: a value outside `choices` in this house is
        TYPE_BAD_TYPE (authoring.py, the "enum" branch), not a separate
        enum code."""
        out = compile_program(_prog([_railing_path(variety="ramp_side")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_an_unknown_position_is_typed(self):
        """«Left/Right» is the first thing a person will write from
        memory, and it doesn't exist in the API: RailingPlacementPosition.Left
        does not compile on any of the six versions. The closed list guards
        against exactly this kind of guess at the input."""
        out = compile_program(_prog([_railing_hosted(position="left")]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_an_ambiguous_railing_type_never_picks_the_first(self):
        """The railing has no default type in the document (measured:
        ElementTypeGroup.RailingType does not exist). Two types in the pool
        plus an omitted `type` must produce a question, not a choice made
        for the user."""
        snapshot = dict(SNAPSHOT)
        snapshot["railing_types"] = [{"id": 1200, "name": "Перила 900"},
                                     {"id": 1201, "name": "Перила 1200"}]
        out = compile_program(_prog([_railing_path()]), snapshot=snapshot)
        self.assertFalse(out.ok)

    def test_the_ceiling_height_offset_is_carried_when_given(self):
        out = compile_program(_prog([_ceiling(height_offset_mm=-250)]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("CEILING_HEIGHTABOVELEVEL_PARAM", out.csharp)

    def test_an_absent_ceiling_offset_stays_absent(self):
        """Absence of an offset is not zero. Byte stability: without the
        parameter there must be neither a setting nor a witness in C#."""
        out = compile_program(_prog([_ceiling()]),
                              revit_version="2024", snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertNotIn("CEILING_HEIGHTABOVELEVEL_PARAM", out.csharp)


# ── execution invariants ────────────────────────────────────────────────────

class CommitGateInvariants(unittest.TestCase):

    def _csharp(self, op, ver="2024"):
        out = compile_program(_prog([op]), revit_version=ver, snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_one_transaction_each(self):
        for name, op in (("ceiling", _ceiling()),
                         ("railing_path", _railing_path()),
                         ("railing_hosted", _railing_hosted())):
            with self.subTest(op=name):
                self.assertEqual(self._csharp(op).count("new Transaction("), 1)

    def test_regenerate_precedes_postconditions(self):
        for name, op in (("ceiling", _ceiling()),
                         ("railing_path", _railing_path())):
            with self.subTest(op=name):
                cs = self._csharp(op)
                self.assertIn("doc.Regenerate()", cs)
                self.assertLess(cs.index("doc.Regenerate()"),
                                cs.index("__post.Add("))

    def test_every_creation_is_stamped(self):
        for name, op in (("ceiling", _ceiling()),
                         ("railing_path", _railing_path()),
                         ("railing_hosted", _railing_hosted())):
            with self.subTest(op=name):
                self.assertIn("__stamp", self._csharp(op))

    def test_a_null_result_is_a_refusal_not_a_success(self):
        for name, op in (("ceiling", _ceiling()),
                         ("railing_path", _railing_path()),
                         ("railing_hosted", _railing_hosted())):
            with self.subTest(op=name):
                self.assertIn("== null", self._csharp(op))


# ── property ──────────────────────────────────────────────────────────────

class ArchPBT(unittest.TestCase):

    def test_well_typed_ceilings_always_compile_on_2026(self):
        rng = random.Random(29072026)
        for i in range(40):
            w = rng.randrange(1000, 20000)
            h = rng.randrange(1000, 20000)
            x0 = rng.randrange(-50000, 50000)
            y0 = rng.randrange(-50000, 50000)
            outline = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
            op = _ceiling(oid=f"C{i}", outline=outline)
            if rng.random() < 0.5:
                op["height_offset_mm"] = rng.randrange(-3000, 3000)
            with self.subTest(i=i):
                out = compile_program(_prog([op]), revit_version="2026",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])

    def test_well_typed_sketch_ceilings_always_compile_on_2026(self):
        """The same law for the form's second input: a well-typed sketch
        must always make it through to C#, including arc edges."""
        rng = random.Random(9082026)
        for i in range(40):
            w = rng.randrange(2000, 20000)
            h = rng.randrange(2000, 20000)
            x0 = rng.randrange(-50000, 50000)
            y0 = rng.randrange(-50000, 50000)
            points = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
            region = {"outer": {"shape": "poly", "points_mm": points}}
            if rng.random() < 0.5:
                # An outward arc on the short edge: the outward arrow
                # cannot cross the opposite side, so the program remains
                # well-typed by construction.
                edge, bulge = (0, -0.3) if w <= h else (1, 0.3)
                region["outer"]["arcs"] = [{"edge": edge, "bulge": bulge}]
            op = _ceiling_sketch(oid=f"C{i}", contour=region)
            if rng.random() < 0.5:
                op["height_offset_mm"] = rng.randrange(-3000, 3000)
            with self.subTest(i=i):
                out = compile_program(_prog([op]), revit_version="2026",
                                      snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])

    def test_well_typed_railings_always_compile_on_2021(self):
        rng = random.Random(29072027)
        for i in range(40):
            n = rng.randrange(2, 8)
            path = []
            x, y = rng.randrange(-20000, 20000), rng.randrange(-20000, 20000)
            for _ in range(n):
                path.append([x, y])
                x += rng.choice([-1, 1]) * rng.randrange(500, 5000)
                y += rng.choice([-1, 1]) * rng.randrange(500, 5000)
            with self.subTest(i=i):
                out = compile_program(_prog([_railing_path(oid=f"R{i}",
                                                           path=path)]),
                                      revit_version="2021", snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()
