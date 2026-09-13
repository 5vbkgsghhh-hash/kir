"""wave/sweep (2026-08-09): create_wall_sweep / create_slab_edge.

WHY THIS WAVE. The family of hosted sweep profiles had NEVER ONCE been
surveyed: a registry census found not a single operation creating
`WallSweep`, `SlabEdge`, `Fascia`, or `Gutter`. Cornices, string courses,
rustication, and drip edges along a slab edge — a whole class of facade and
roof trim — were expressed by nothing at all.

The structure mirrors test_site.py (RegistryShape / Ground / Negative /
Witness / NamedWeakerGuarantee / CommitGateInvariants) — the same graph of
invariants.

EVERY API MEMBER WAS MEASURED BY COMPILATION ON :52412 (09.08.2026, six
reference builds), not taken from memory and not from
`data/revit_api_db.json` (that database is provably incomplete and does not
know `NewSlabEdge` at all). The full table is in the header of ops_sweep.py.
Repeated here are only the findings that the code below checks:

  * THIS WAVE HAS NO VERSION AXIS AT ALL, and this is a measurement, not
    luck: every member that names both emitters compiles 6/6, so all six
    versions get THE EXACT SAME C#. The `VersionAxis` test below checks
    exactly this — the absence of divergence, not its presence;
  * `WallSweepInfo.IsVertical` is a READ-ONLY property (CS0200 on all six).
    The only orientation channel is the constructor argument, so
    `orientation` is mandatory and has NO default;
  * `WallSweep` is NOT a `HostedSweep` (CS0030), but `SlabEdge` is. Their
    witnesses are therefore of different strength, and `NamedWeakerGuarantee`
    below keeps that difference declared rather than implied;
  * `SlabEdge.SlabEdgeType`, `GetTypeId()`, and the base `Length` /
    `get_ReferenceCurve(Reference)` — all 6/6. THE WAVE'S MAIN MEASUREMENT:
    a previous inspection found `SlabEdge` had no getter at all beyond
    `AddSegment`, and by that finding the operation should have been
    rejected. It is wrong — there are four readable kinds, and the last of
    them is good enough to be a real witness.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_sweep_queue.jsonl"))

from kir import spec                                        # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.ops_sweep import (                                 # noqa: E402
    SWEEP_ORIENTATIONS, SLAB_EDGE_SIDES, WALL_SWEEP_NON_FIXED_ID,
)
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

HOST_ID = {"by": "element_id", "value": 7777}
OPS = ("create_wall_sweep", "create_slab_edge")


def _prog(ops, intent="sweep-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _sweep(oid="S1", orientation="horizontal", **kw):
    op = {"op": "create_wall_sweep", "id": oid, "host": HOST_ID,
          "orientation": orientation}
    op.update(kw)
    return op


def _edge(oid="E1", side="top", **kw):
    op = {"op": "create_slab_edge", "id": oid, "host": HOST_ID, "side": side}
    op.update(kw)
    return op


def _emit(ops, ver="2026"):
    out = compile_program(_prog(ops), revit_version=ver, snapshot=SNAPSHOT,
                          bulk=True)
    return out


class RegistryShape(unittest.TestCase):
    def test_both_ops_are_registered_writing_creates(self):
        for name in OPS:
            with self.subTest(op=name):
                op = spec.OPS[name]
                self.assertTrue(op.writes_model)
                self.assertEqual(op.family, "authoring")
                self.assertEqual(op.effect.value, "create")

    def test_each_op_grounds_its_own_pool(self):
        """TWO POOLS, NOT ONE, and this is not pedantry: `NewSlabEdge`
        accepts ONLY a `SlabEdgeType`, while the wall sweep type is not a
        class at all but an element of one of two categories. Grounding a
        cornice in the pool of edge profiles would mean handing the emitter
        an id that the call is guaranteed to reject."""
        got = {name: dict((p, pool) for p, pool, _r in spec.OPS[name].grounded)
               for name in OPS}
        self.assertEqual(got["create_wall_sweep"]["type"], "wall_sweep_types")
        self.assertEqual(got["create_slab_edge"]["type"], "slab_edge_types")

    def test_neither_op_declares_a_tolerance(self):
        """NOT A SINGLE TOLERANCE — A CONSEQUENCE, NOT A GAP.

        All witnesses of both operations are EXACT: id membership in a set,
        id equality, boolean equality, equality of two counters. There is no
        number for either of them that it would make sense to compare with a
        tolerance: for the wall sweep, because position determines the type
        (see NamedWeakerGuarantee); for the edge sweep, because Revit miters
        the profile length by an unmeasured amount, and it travels into the
        RECEIPT as an observation, not into the verdict.

        The lock is needed because the reverse change — adding a number
        here — looks like an improvement, while in fact it is exactly the
        "bound authored by reasoning" that this house names as its own class
        of defect.
        """
        for name in OPS:
            with self.subTest(op=name):
                self.assertEqual(spec.OPS[name].tolerances, {})
                self.assertNotIn("±", spec.OPS[name].post)

    def test_orientation_and_side_are_closed_and_have_no_default(self):
        o = {p.name: p for p in spec.OPS["create_wall_sweep"].params}
        self.assertEqual(o["orientation"].choices, SWEEP_ORIENTATIONS)
        self.assertTrue(o["orientation"].required)
        self.assertIsNone(o["orientation"].default)
        s = {p.name: p for p in spec.OPS["create_slab_edge"].params}
        self.assertEqual(s["side"].choices, SLAB_EDGE_SIDES)
        self.assertTrue(s["side"].required)
        self.assertIsNone(s["side"].default)

    def test_wall_sweep_claims_no_geometry_capability(self):
        """The ("create", "geometry") cell for the wall sweep would be
        OVER-PROMISING by exactly the amount of the named weaker guarantee;
        for the edge sweep it is earned, because we choose the perimeter."""
        self.assertNotIn(("create", "geometry"),
                         spec.OPS["create_wall_sweep"].capability)
        self.assertIn(("create", "geometry"),
                      spec.OPS["create_slab_edge"].capability)


class NamedWeakerGuarantee(unittest.TestCase):
    """THE MOST IMPORTANT CLASS IN THIS FILE.

    Autodesk's remark, verbatim across all six RevitAPI.xml: "The wall
    sweep's profile and type are taken from the wall sweep type properties.
    The values set in the WallSweepInfo are ignored." From it follow THREE
    obligations of this wave, and each is checked here, because each is
    easy to lose to a change that looks like an improvement.
    """

    def test_the_op_exposes_no_geometric_field_at_all(self):
        """Fields the operation MUST NOT HAVE. Adding any of them would mean
        accepting from the author a value that the API is documented to
        ignore — that is, building a silently-wrong result by construction.
        """
        names = {p.name for p in spec.OPS["create_wall_sweep"].params}
        for forbidden in ("distance_mm", "offset_mm", "wall_offset_mm",
                          "elevation_mm", "angle_deg", "profile"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, names)

    def test_the_limit_is_stated_verbatim_in_post(self):
        """The constraint is NAMED, not implied: the verbatim quote sits in
        `post`, that is, in the same text read both by the translation
        certificate and by a human."""
        post = spec.OPS["create_wall_sweep"].post
        self.assertIn("NAMED WEAKER GUARANTEE", post)
        self.assertIn("The values set in the WallSweepInfo are ignored", post)

    def test_the_clause_is_registered_as_non_witnessable(self):
        """AND MOST IMPORTANTLY — it is registered EXPLICITLY, and did not
        slip past the audit on some accidental shared word.
        `audit_registry_coverage()` requires that every `post` clause carry
        an obligation; an unassertable one must carry a waiver with a
        reason."""
        from kir.translation_cert import _NON_WITNESSABLE_CLAUSES
        markers = _NON_WITNESSABLE_CLAUSES["create_wall_sweep"]
        self.assertEqual(len(markers), 1)
        marker, why = markers[0]
        self.assertIn(marker, spec.OPS["create_wall_sweep"].post.lower())
        self.assertIn("witness", why)

    def test_the_registry_audit_is_clean(self):
        from kir.translation_cert import audit_registry_coverage
        self.assertEqual(audit_registry_coverage(), ())


class VersionAxis(unittest.TestCase):
    def test_six_versions_receive_the_same_csharp(self):
        """THERE IS NO VERSION AXIS — AND THIS IS AN ASSERTION, NOT A DEFAULT.

        Every API member naming both emitters is measured 6/6, so there
        must be no divergence ANYWHERE except the ElementId literal (it has
        its own version idiom, shared across the whole house — and in these
        programs it is small, so it too does not diverge). The test catches
        a future change that quietly introduces a version branch where the
        API does not require one: "a refusal the API does not require is as
        much a lie as silence where one is needed".
        """
        for ops in ([_sweep()], [_edge()]):
            texts = {}
            for ver in spec.REVIT_VERSIONS:
                out = _emit(ops, ver)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
                texts[ver] = out.csharp
            with self.subTest(op=ops[0]["op"]):
                self.assertEqual(len(set(texts.values())), 1,
                                 "версионная ветка появилась там, где API её "
                                 "не требует")


class Ground(unittest.TestCase):
    def test_omitted_type_resolves_to_the_sole_entry(self):
        out = _emit([_sweep()])
        self.assertTrue(out.ok)
        self.assertIn("new ElementId(1800)", out.csharp)
        out = _emit([_edge()])
        self.assertTrue(out.ok)
        self.assertIn("new ElementId(1801)", out.csharp)

    def test_ambiguous_pool_refuses_instead_of_picking(self):
        """The second type in the pool is a typed question, not a choice made
        for the author. A live measurement on 02.08 named the cost of that
        choice: the C# arm silently took 1 door type out of 62 and built it."""
        snap = dict(SNAPSHOT)
        snap["wall_sweep_types"] = [{"id": 1800, "name": "Карниз 200x100"},
                                    {"id": 1802, "name": "Карниз 300x150"}]
        out = compile_program(_prog([_sweep()]), snapshot=snap, bulk=True)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G102", [d.code for d in out.diagnostics])

    def test_named_type_is_resolved_by_name(self):
        out = _emit([_sweep(type={"by": "name", "value": "Карниз 200x100"})])
        self.assertTrue(out.ok)
        self.assertIn("new ElementId(1800)", out.csharp)


class Negative(unittest.TestCase):
    def test_orientation_is_mandatory(self):
        op = _sweep()
        del op["orientation"]
        out = _emit([op])
        self.assertFalse(out.ok)

    def test_side_is_mandatory(self):
        op = _edge()
        del op["side"]
        out = _emit([op])
        self.assertFalse(out.ok)

    def test_unknown_orientation_and_side_refuse(self):
        self.assertFalse(_emit([_sweep(orientation="diagonal")]).ok)
        self.assertFalse(_emit([_edge(side="north")]).ok)

    def test_host_is_mandatory(self):
        op = _sweep()
        del op["host"]
        self.assertFalse(_emit([op]).ok)
        op = _edge()
        del op["host"]
        self.assertFalse(_emit([op]).ok)

    def test_existing_host_by_element_id_is_legal(self):
        """The MAIN scenario for both operations: a cornice is hung on a wall
        that is ALREADY STANDING. Requiring `ref` would forbid the primary
        scenario — exactly the argument by which create_opening was entered
        into the same list."""
        self.assertTrue(_emit([_sweep()]).ok)
        self.assertTrue(_emit([_edge()]).ok)


class Emission(unittest.TestCase):
    def test_wall_sweep_derives_the_kind_from_the_type_category(self):
        """THE PROFILE KIND IS NOT ASKED OF THE AUTHOR. Asking would mean
        introducing a field that could CONTRADICT the type — and per
        Autodesk's remark the type would win, meaning the answer given to
        the author would silently differ."""
        cs = _emit([_sweep()]).csharp
        self.assertIn("BuiltInCategory.OST_Reveals", cs)
        self.assertIn("BuiltInCategory.OST_Cornices", cs)
        self.assertIn("WallSweepType.Reveal : WallSweepType.Sweep", cs)
        # Category comparison is via ToString(): the one ElementId idiom
        # alive on all six (`.IntegerValue` is dead on 2026, `.Value`
        # does not exist before 2024).
        self.assertNotIn(".IntegerValue", cs)

    def test_wall_sweep_sets_the_non_fixed_id_the_api_demands(self):
        """"The WallSweepInfo id must be set to -1 for a non-fixed wall
        sweep" — an ArgumentException condition, not advice."""
        cs = _emit([_sweep()]).csharp
        self.assertIn(f"__wi_S1.Id = {WALL_SWEEP_NON_FIXED_ID};", cs)

    def test_wall_sweep_preflights_wall_allows_wall_sweep(self):
        """A pre-check that Create ITSELF requires. Without it the refusal
        would arrive as a Revit exception and would be recorded by the
        pipeline as `internal` — "something broke on our end" instead of
        "this wall cannot host a profile"."""
        cs = _emit([_sweep()]).csharp
        self.assertIn("WallSweep.WallAllowsWallSweep(__ho_S1)", cs)
        self.assertLess(cs.index("WallAllowsWallSweep"),
                        cs.index("WallSweep.Create("),
                        "предпроверка обязана стоять ДО вызова")

    def test_orientation_reaches_the_constructor_and_the_witness(self):
        for orientation, literal in (("horizontal", "false"),
                                     ("vertical", "true")):
            with self.subTest(orientation=orientation):
                cs = _emit([_sweep(orientation=orientation)]).csharp
                self.assertIn(f"WallSweepType.Sweep, {literal})", cs)
                self.assertIn(f"__ri_S1.IsVertical != {literal}", cs)

    def test_slab_edge_side_selects_the_right_host_object_call(self):
        self.assertIn("HostObjectUtils.GetTopFaces(__ho_E1)",
                      _emit([_edge(side="top")]).csharp)
        self.assertIn("HostObjectUtils.GetBottomFaces(__ho_E1)",
                      _emit([_edge(side="bottom")]).csharp)

    def test_slab_edge_never_touches_the_instance_geometry_trap(self):
        """A TRAP ALREADY PAID FOR ONCE: `GetInstanceGeometry()` returns a
        COPY whose references Autodesk documents as "not suitable for
        creating new Revit elements referencing the original element". It
        compiles 6/6 and refuses LIVE, so a static lock here is cheaper than
        a second live run."""
        cs = _emit([_edge()]).csharp
        self.assertNotIn("GetInstanceGeometry", cs)

    def test_slab_edge_decides_by_cardinality_not_by_first_match(self):
        """BOTH stages are resolved by CARDINALITY, and both name a NUMBER.
        Cardinality does not depend on enumeration order, so the
        undocumented ordering of faces and edges has no effect on the result
        at all."""
        cs = _emit([_edge()]).csharp
        self.assertIn("if (__nf_E1 > 1)", cs)
        self.assertIn("__nf_E1.ToString()", cs)
        self.assertIn("if (__nl_E1 != 1)", cs)
        self.assertIn("__nl_E1.ToString()", cs)
        self.assertNotIn("FirstOrDefault", cs)

    def test_slab_edge_guards_the_documented_null_return(self):
        """`NewSlabEdge` is documented as RETURNING null on failure, not
        throwing. Without this check there would be a NullReferenceException
        recorded as `internal`."""
        cs = _emit([_edge()]).csharp
        i = cs.index("doc.Create.NewSlabEdge(")
        self.assertIn("if (__el_E1 == null)", cs[i:i + 400])


class Witness(unittest.TestCase):
    def test_wall_sweep_reads_the_result_not_the_call(self):
        cs = _emit([_sweep()]).csharp
        post = cs[cs.index("// post S1"):]
        for reader in ("__el_S1.GetHostIds()", "__el_S1.GetTypeId()",
                       "__el_S1.GetWallSweepInfo()"):
            with self.subTest(reader=reader):
                self.assertIn(reader, post)

    def test_slab_edge_witness_reads_the_built_sweeps_own_curves(self):
        """THE WAVE'S STRONGEST WITNESS: the BUILT profile is asked for the
        curve it routed along each reference we named. There is nothing the
        emitter can do to fake this — it passed the reference, and it was
        the element that returned the curve."""
        cs = _emit([_edge()]).csharp
        post = cs[cs.index("// post E1"):]
        self.assertIn("__el_E1.get_ReferenceCurve(__wr_E1)", post)
        self.assertIn("__bound_E1 != __named_E1", post)

    def test_every_verdict_signs_the_axis_it_reads(self):
        """The witness signs the grid it actually read. Here this is checked
        literally: the wall sweep has NOT ONE `(geometry)` verdict — it has
        nothing to read geometry with — while the edge sweep does."""
        sweep_post = _emit([_sweep()]).csharp
        sweep_post = sweep_post[sweep_post.index("// post S1"):]
        self.assertNotIn("(geometry)", sweep_post)
        self.assertIn("(topology)", sweep_post)
        self.assertIn("(semantic)", sweep_post)
        edge_post = _emit([_edge()]).csharp
        edge_post = edge_post[edge_post.index("// post E1"):]
        self.assertIn("(geometry)", edge_post)

    def test_a_failed_read_is_a_violation_not_silence(self):
        """"Could not read" has no right to look like "matched". Orientation
        is the only thing the author said about the wall sweep's shape, so
        an unreadable `GetWallSweepInfo()` must be a violation."""
        cs = _emit([_sweep()]).csharp
        self.assertIn("подтвердить ориентацию нечем", cs)

    def test_observations_ride_the_receipt_not_the_verdict(self):
        """The length of the built profile and the perimeter we supplied are
        BOTH in the receipt and NEITHER in the verdict: nobody has measured
        the amount of the miter cut, and checking them against an assigned
        tolerance would mean accusing a correctly built drip edge."""
        cs = _emit([_edge()]).csharp
        post_start = cs.index("// post E1")
        rb_start = cs.index("// witness E1")
        self.assertIn('__rb["perimeter_mm"]', cs[rb_start:])
        self.assertIn('__rb["sweep_length_mm"]', cs[rb_start:])
        self.assertNotIn("sweep_length_mm", cs[post_start:rb_start])


class CommitGateInvariants(unittest.TestCase):
    def test_per_op_isolation_uses_the_op_local_refusal(self):
        """A refusal inside the wrapped create must be OP-LOCAL: otherwise
        one op's refusal would roll back neighbors that were already
        committed."""
        from kir.emit_utils import program_refusal_tokens
        for ops in ([_sweep()], [_edge()]):
            out = compile_program(_prog(ops), snapshot=SNAPSHOT, bulk=True,
                                  isolation="per_op")
            self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
            create = out.csharp
            with self.subTest(op=ops[0]["op"]):
                self.assertIn("__OpRefuse(", create)
                self.assertNotIn("__t.RollBack(); return __Refuse(",
                                 create[create.index("// create_"):
                                        create.index("// post")])

    def test_both_ops_stamp_the_element_they_created(self):
        for ops, var in (([_sweep()], "__el_S1"), ([_edge()], "__el_E1")):
            with self.subTest(op=ops[0]["op"]):
                cs = _emit(ops).csharp
                self.assertIn(
                    f"{var}.get_Parameter(BuiltInParameter."
                    f"ALL_MODEL_INSTANCE_COMMENTS)", cs)

    def test_variables_read_after_the_post_block_are_declared_outside_it(self):
        """A REGRESSION CAUGHT BY THE GATE ON 09.08.

        `__hs_`/`__named_`/`__bound_` were declared in the witness's READER,
        but are read by the RECEIPT — that is, in the next scope. The
        postcondition block carries its own braces, so the name died at the
        closing one, and all six versions in both isolations answered
        CS0103 (48 live Roslyn cells, 48 refusals). The test keeps the
        declarations outside the block.
        """
        for ops, names in (([_sweep()], ("__hs_S1",)),
                           ([_edge()], ("__named_E1", "__bound_E1"))):
            cs = _emit(ops).csharp
            head = cs[:cs.index("// create_")]
            for name in names:
                with self.subTest(var=name):
                    self.assertIn(f"{name} = ", head,
                                  "переменная, которую читает квитанция, "
                                  "обязана быть объявлена в decl")


if __name__ == "__main__":
    unittest.main()
