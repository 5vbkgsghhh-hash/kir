"""wave/room (2026-08-03): create_room_separator — a room separator.

WHY THIS WAVE. The offline suitability verdict is built and works, but on
a real building it STAYS SILENT: the program closes off only part of the
rooms with walls. Measurement on k2_ar_rd_v9 (independently reproduced by
the instrument, not recalled from memory):

    rooms total                                    2,442
    bounded ONLY by walls                            936
    among the bounding elements there is a separator 1,091
    walls + structural columns                       126
    no bounding element at all (not placed)          289

    OST_RoomSeparationLines in L0                  2,313
    of these bound EXACTLY TWO rooms                 749   ← ready-made graph edges
    bound one                                      1,358
    bound three                                       34
    bound none                                       172

That is, 1,091 rooms out of 2,442 cannot be closed off by ANY KIR program
as long as the separator is missing from the language, and 749 lines are
adjacency edges that `_semantic_fold` currently discards. There was no
operation; the lifter sent all 2,313 elements to atoms with the reason
`no_lifter` ("there is no operation at all").

THE API NAME IS VERIFIED BY THE TRAP INDEX AND BY COMPILATION, NOT BY
MEMORY (data/api_traps/revit_api_traps.sqlite, 35,516 members × 6
versions):

    Autodesk.Revit.Creation.Document.NewRoomBoundaryLines(
        SketchPlane, CurveArray, View) -> ModelCurveArray     2021-2026 (6/6)
    SketchPlane.Create(Document, ElementId)                   6/6
        summary: "Creates a sketch plane from a grid, reference plane,
                  or LEVEL" — that is, the plane is taken FROM THE LEVEL
                  ITSELF
    ViewPlan.GenLevel / IsTemplate / ViewType.FloorPlan       6/6
    Element.LevelId                                           6/6
    new ElementId(BuiltInCategory.…)                          6/6
    Category.BuiltInCategory                          ONLY 2023-2026 (4/6)
    ElementId.IntegerValue                            ABSENT in 2026 (5/6)

The last two lines are not a footnote but the reason for the witness's
form: the segment's category has to be checked via `Category.Id` and
`new ElementId(BIC)`, not via the convenient `Category.BuiltInCategory`
nor via `IntegerValue`.

The structure mirrors test_arch.py (Registry / VersionAxis / Geometry /
NoSilentLoss / CommitGateInvariants / PBT).
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_room_queue.jsonl"))

from kir import spec                                        # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.registry_base import IdentityCardinality           # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}

OP = "create_room_separator"


def _prog(ops, intent="room-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _sep(oid="S1", **kw):
    op = {"op": OP, "id": oid, "path": [[0, 0], [3000, 0]], "level": LVL}
    op.update(kw)
    return op


def _codes(out):
    return [d.code for d in out.diagnostics]


# ── registry ─────────────────────────────────────────────────────────────

class RegistryShape(unittest.TestCase):

    def test_the_op_is_registered(self):
        self.assertIn(OP, spec.OPS)

    def test_it_declares_itself_a_writer(self):
        self.assertTrue(spec.OPS[OP].writes_model)
        self.assertEqual(spec.OPS[OP].family, "authoring")

    def test_it_lives_in_its_own_registry_module(self):
        """Waves add ops IN PARALLEL, without touching someone else's
        ops_*.py.

        WHAT IS CHECKED IS THE INVARIANT, NOT AN INVENTORY. Here there
        used to be `assertEqual([op.name for op in ops_room.OPS], [OP])`,
        that is, a COPY of the module's contents, and it went stale on the
        day `create_space` (also spatial, also its own module)
        legitimately moved in next door. An inventory of someone else's
        module forbids a neighbor from existing — exactly what the wave
        model allows; the real requirement of the docstring is different:
        an op lives IN EXACTLY ONE `ops_*.py`. That is what we ask, of the
        registry itself.
        """
        from kir import ops_room
        owners = [m.__name__.rsplit(".", 1)[-1]
                  for m in spec._REGISTRY_MODULES
                  if any(op.name == OP for op in m.OPS)]
        self.assertEqual(owners, ["ops_room"],
                         "оп обязан жить ровно в одном ops_*.py")
        self.assertIn(OP, [op.name for op in ops_room.OPS])

    def test_the_result_carries_many_identities_not_one(self):
        """A polyline of n points creates n-1 ModelCurves. Declaring ONE
        identity would be a lie about everything except a straight
        segment — and would hide created elements the receipt never
        named."""
        result = spec.OPS[OP].result
        self.assertIs(result.identity_cardinality, IdentityCardinality.MANY)
        self.assertEqual(result.identity_field, "segment_ids")
        self.assertFalse(result.referenceable)

    def test_it_grounds_only_the_level(self):
        """`NewRoomBoundaryLines` HAS NO type/style argument, so the op
        has no `type` parameter: there is nothing to prime, and an
        invented pool would be a promise the API does not keep."""
        self.assertEqual(
            {p: pool for p, pool, _ in spec.OPS[OP].grounded},
            {"level": "levels"})
        self.assertNotIn("type", {p.name for p in spec.OPS[OP].params})

    def test_the_path_is_its_own_param_kind(self):
        """`path`, not `pts`: `pts` requires >=3 points and NONZERO AREA,
        that is, a ring by construction. A separator is most often a
        single segment between two walls (K2 measurement: 2,313 elements,
        EACH one a single segment), and under `pts` it would be rejected
        as a degenerate contour."""
        kinds = {p.name: p.kind for p in spec.OPS[OP].params}
        self.assertEqual(kinds["path"], "path")


# ── version axis ─────────────────────────────────────────────────────────

class VersionAxis(unittest.TestCase):

    def test_it_builds_on_all_six(self):
        """This op HAS NO version axis — measured 6/6 by the trap index
        and by compilation. If one ever appears, this test will be the
        first to see it."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                out = compile_program(_prog([_sep()]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])
                self.assertIn("NewRoomBoundaryLines(", out.csharp)

    def test_it_never_reads_a_member_absent_on_2026(self):
        """`ElementId.IntegerValue` was removed in 2026 (measured by
        compilation: CS1061), and `Category.BuiltInCategory` only
        appeared in 2023. Neither one should be in the emission on any
        version."""
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(version=ver):
                cs = compile_program(_prog([_sep()]), revit_version=ver,
                                     snapshot=SNAPSHOT).csharp
                self.assertNotIn("IntegerValue", cs)
                self.assertNotIn(".BuiltInCategory", cs)


# ── geometry: a polyline, not a ring ────────────────────────────────────

class PathIsNotARing(unittest.TestCase):

    def test_two_points_are_one_segment(self):
        out = compile_program(_prog([_sep()]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Line.CreateBound"), 1)

    def test_three_points_are_two_segments_not_three(self):
        """A closing segment is not implied: a line that isn't in the
        source would slice off a piece of the room that no one asked
        for."""
        out = compile_program(
            _prog([_sep(path=[[0, 0], [3000, 0], [3000, 3000]])]),
            snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Line.CreateBound"), 2)

    def test_a_closed_ring_is_expressible_by_repeating_the_first_point(self):
        """A room closed off by separators ALONE is expressed as a
        polyline whose last point coincides with the first: 5 points → 4
        segments."""
        ring = [[0, 0], [3000, 0], [3000, 3000], [0, 3000], [0, 0]]
        out = compile_program(_prog([_sep(path=ring)]), snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertEqual(out.csharp.count("Line.CreateBound"), 4)

    def test_a_single_point_is_refused(self):
        out = compile_program(_prog([_sep(path=[[0, 0]])]), snapshot=SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", _codes(out))

    def test_a_zero_length_segment_is_refused(self):
        """The 1 mm threshold is common to the `path` kind: Revit does
        not build such a curve (`ArgumentsInconsistentException` "curve
        length is too small", trap index)."""
        out = compile_program(_prog([_sep(path=[[0, 0], [0, 0.5]])]),
                              snapshot=SNAPSHOT)
        self.assertFalse(out.ok)


# ── the plane is taken from the level, not computed by us ──────────────

class PlaneComesFromTheLevel(unittest.TestCase):

    def test_the_sketch_plane_is_built_from_the_level_itself(self):
        """`SketchPlane.Create(doc, ElementId)` is documented as "a plane
        from a grid, a reference plane, OR A LEVEL" (summary in the trap
        index). Computing the elevation ourselves would mean setting up a
        second judge of where the level actually is."""
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertIn("SketchPlane.Create(doc, __lv_S1.Id)", cs)
        self.assertNotIn("Plane.CreateByNormalAndOrigin", cs)

    def test_the_curve_elevation_is_read_live_from_the_level(self):
        """The curve's elevation is `MM(__lv.Elevation)`, read AT
        RUNTIME: the compiler does not know the elevation of a level
        addressed by name or reference, and substituting our own number
        would mean building the separator in the wrong place."""
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertIn("MM(__lv_S1.Elevation)", cs)


# ── plan view: the choice is NAMED, not made silently ───────────────────

class ViewChoiceIsNamed(unittest.TestCase):

    def test_the_view_is_derived_from_the_level_not_from_the_active_view(self):
        """`doc.ActiveView` is exactly the silent choice that NAMED
        DEFAULT was written to forbid: the result would depend on what
        the user happens to be looking at."""
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertNotIn("ActiveView", cs)
        self.assertIn("GenLevel", cs)
        self.assertIn("ViewType.FloorPlan", cs)

    def test_a_template_view_is_never_chosen(self):
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertIn("IsTemplate", cs)

    def test_the_absence_of_a_plan_view_is_a_refusal_not_a_guess(self):
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        self.assertIn("stale_or_failed", cs)

    def test_the_chosen_view_reaches_the_receipt(self):
        """A default is NAMED exactly when it is visible from the
        outside."""
        cs = compile_program(_prog([_sep()]), snapshot=SNAPSHOT).csharp
        for key in ('"view_id"', '"view_name"', '"view_candidates"'):
            with self.subTest(key=key):
                self.assertIn(key, cs)


# ── witnesses ────────────────────────────────────────────────────────────

class WitnessesCoverThePromise(unittest.TestCase):

    def _cs(self):
        out = compile_program(_prog([_sep(path=[[0, 0], [3000, 0],
                                               [3000, 3000]])]),
                              snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_the_number_of_created_segments_is_witnessed(self):
        """A polyline of 3 points must produce EXACTLY 2 curves. Fewer is
        a loss, more is garbage; both look like success from the
        outside."""
        self.assertIn("__segs_S1.Count != 2", self._cs())

    def test_the_category_of_every_segment_is_witnessed(self):
        """This is the heart of the op: to prove that we built a
        SEPARATOR, not an ordinary model line. A line "in the same
        place" bounds nothing and is indistinguishable from the
        outside."""
        cs = self._cs()
        self.assertIn("OST_RoomSeparationLines", cs)

    def test_the_level_of_every_segment_is_witnessed(self):
        self.assertIn("LevelId", self._cs())

    def test_the_endpoints_are_witnessed_against_the_path(self):
        self.assertIn("GetEndPoint(", self._cs())

    def test_every_promise_clause_has_a_witness(self):
        """The translation certificate splits `post` on the semicolon and
        requires a witness for EVERY piece."""
        from kir.translation_cert import audit_registry_coverage
        problems = [p for p in audit_registry_coverage() if OP in p]
        self.assertEqual(problems, [])

    def test_the_tolerance_comes_from_the_registry(self):
        """LAW OF PROVENANCE: the tolerance number reaches the C# only as
        an object minted by the registry. Touch the number in the
        registry — the bytes must move."""
        self.assertIn("endpoint_mm", spec.OPS[OP].tolerances)
        cs = self._cs()
        self.assertIn(str(spec.OPS[OP].tolerances["endpoint_mm"]), cs)


# ── execution invariants ────────────────────────────────────────────────

class CommitGateInvariants(unittest.TestCase):

    def _csharp(self, op, ver="2024"):
        out = compile_program(_prog([op]), revit_version=ver, snapshot=SNAPSHOT)
        self.assertTrue(out.ok, _codes(out)[:3])
        return out.csharp

    def test_one_transaction(self):
        self.assertEqual(self._csharp(_sep()).count("new Transaction("), 1)

    def test_regenerate_precedes_postconditions(self):
        cs = self._csharp(_sep())
        self.assertIn("doc.Regenerate()", cs)
        self.assertLess(cs.index("doc.Regenerate()"), cs.index("__post.Add("))

    def test_every_creation_is_stamped(self):
        self.assertIn("__stamp", self._csharp(_sep()))

    def test_a_null_result_is_a_refusal_not_a_success(self):
        self.assertIn("== null", self._csharp(_sep()))

    def test_it_survives_per_op_isolation(self):
        """Variables the postcondition block reads must be declared in
        the OUTER scope: with `isolation="per_op"`, `create` and `post`
        end up in different scopes (a live pitfall from the fencing wave,
        CS0103)."""
        from kir.compiler import compile_program as cp
        out = cp(_prog([_sep()]), snapshot=SNAPSHOT, isolation="per_op")
        self.assertTrue(out.ok, _codes(out)[:3])
        self.assertIn("SubTransaction", out.csharp)


# ── rollback ─────────────────────────────────────────────────────────────

class ReverseContract(unittest.TestCase):

    def test_the_manifest_declares_a_direct_inverse(self):
        from kir.reverse_contract import REVERSE_CONTRACTS, ReverseMode
        contract = REVERSE_CONTRACTS[OP]
        self.assertIs(contract.mode, ReverseMode.DIRECT)
        self.assertIn("_lift_room_separator", contract.entrypoints)

    def test_the_category_is_in_the_lifter_table(self):
        from kir.decompile.lift import LIFTER_TABLE
        self.assertEqual(LIFTER_TABLE["OST_RoomSeparationLines"][1], OP)


# ── acceptance ───────────────────────────────────────────────────────────

class AcceptanceKnowsTheOp(unittest.TestCase):

    def test_the_expected_count_is_segments_not_one(self):
        """Acceptance must expect n-1 elements, not one: otherwise a
        program that built 1 line instead of 4 would pass it."""
        from kir.acceptance import derive_expectation
        expectation = derive_expectation(_prog([
            _sep(path=[[0, 0], [3000, 0], [3000, 3000], [0, 3000]])]))
        rows = [r for r in expectation.rows
                if "OST_RoomSeparationLines" in r.categories]
        self.assertEqual([r.count for r in rows], [3])

    def test_the_op_is_not_blind(self):
        from kir.acceptance import derive_expectation
        expectation = derive_expectation(_prog([_sep()]))
        self.assertEqual(expectation.blind_ops, ())


# ── property ─────────────────────────────────────────────────────────────

class RoomPBT(unittest.TestCase):

    def test_well_typed_separators_always_compile_on_every_version(self):
        rng = random.Random(3082026)
        for i in range(40):
            n = rng.randrange(2, 12)
            path = []
            x, y = rng.randrange(-20000, 20000), rng.randrange(-20000, 20000)
            for _ in range(n):
                path.append([x, y])
                if rng.random() < 0.5:
                    x += rng.choice([-1, 1]) * rng.randrange(500, 5000)
                else:
                    y += rng.choice([-1, 1]) * rng.randrange(500, 5000)
            ver = rng.choice(spec.REVIT_VERSIONS)
            with self.subTest(i=i, version=ver):
                out = compile_program(_prog([_sep(oid=f"S{i}", path=path)]),
                                      revit_version=ver, snapshot=SNAPSHOT)
                self.assertTrue(out.ok, _codes(out)[:3])


if __name__ == "__main__":
    unittest.main()
