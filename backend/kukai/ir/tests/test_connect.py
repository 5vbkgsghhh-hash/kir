"""CONNECT gates: graph laws (typecheck), fitting inference by degree AND
local geometry, connectivity witness, and the negative corpus (dangling /
zero-seg / degree-4 / duplicate edge / self-loop) — all typed refusals,
never runtime.

FIX 2026-07-17: fitting inference used to be degree-only (2->elbow always,
3->tee); a live semantic test found this fails on a REAL multi-segment
network — a straight collinear joint (riser continuing straight, no bend)
got an elbow forced onto it, and Revit throws "NewElbowFitting: failed to
insert elbow" because there is no bend to elbow. GraphSemantics below keeps
the pre-existing bend/tee cases (CHAIN is a genuine 90deg bend, TEE is a
genuine branch) UNCHANGED — this fix must not touch a correctly-classified
junction — and StraightJointSemantics adds the new collinear cases the bug
used to misclassify. JunctionClassification unit-tests the pure decision
function (connect.classify_junction/_angle_deg) directly, with no compiler/
Revit involved — the property-test layer for the classification logic
itself, per the task's own "compile-gate proves compile, not fitting
correctness" caveat: this is the layer that CAN be proven exhaustively
offline, so it is."""
import math
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import connect as CN  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}


def _sys(nodes, segments, oid="SYS1", **kw):
    op = {"op": "create_pipe_system", "id": oid, "level": LVL,
          "nodes": nodes, "segments": segments}
    op.update(kw)
    return {"ir_version": "1.0", "intent": "connect-test", "ops": [op]}


CHAIN = ([{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 15000]},
          {"id": "N3", "xyz_mm": [3000, 0, 15000]}],
         [{"from": "N1", "to": "N2", "diameter_mm": 100},
          {"from": "N2", "to": "N3", "diameter_mm": 50}])

TEE = ([{"id": "T", "xyz_mm": [0, 0, 0]}, {"id": "A", "xyz_mm": [3000, 0, 0]},
        {"id": "B", "xyz_mm": [-3000, 0, 0]}, {"id": "C", "xyz_mm": [0, 3000, 0]}],
       [{"from": "T", "to": "A"}, {"from": "T", "to": "B"}, {"from": "T", "to": "C"}])

# A genuine straight run (stояк): three colinear nodes on the same vertical
# axis, N2 is a pass-through (degree 2, angle exactly 180deg) — the case
# graph_validate/emit_fittings_cs used to force an elbow onto, and Revit
# would refuse at runtime ("failed to insert elbow" — there is no bend).
STRAIGHT_SAME_DIA = (
    [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 8000]},
     {"id": "N3", "xyz_mm": [0, 0, 16000]}],
    [{"from": "N1", "to": "N2", "diameter_mm": 100},
     {"from": "N2", "to": "N3", "diameter_mm": 100}])

# Same straight axis, but the declared diameter changes at the pass-through
# node -> a reducer (NewTransitionFitting) is the physically correct
# fitting, not an elbow and not a bare ConnectTo (Revit itself won't
# ConnectTo two differently-sized End connectors without a transition).
STRAIGHT_DIAMETER_CHANGE = (
    [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 8000]},
     {"id": "N3", "xyz_mm": [0, 0, 16000]}],
    [{"from": "N1", "to": "N2", "diameter_mm": 100},
     {"from": "N2", "to": "N3", "diameter_mm": 50}])

# TEE variant where two of the three incident segments are THEMSELVES
# collinear through the junction (A and B are antiparallel through T, same
# as the original TEE fixture) — locks in "degree wins at degree 3,
# regardless of any pairwise angle among its edges" as a real compiled case,
# not just a classify_junction() unit assertion.
TEE_WITH_COLLINEAR_PAIR = TEE


class GraphSemantics(unittest.TestCase):
    def test_chain_compiles_with_elbow(self):
        out = compile_program(_sys(*CHAIN, diameter_mm=80), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Pipe.Create(doc"), 2)
        self.assertIn("doc.Create.NewElbowFitting", cs)   # N2 degree 2
        self.assertNotIn("NewTeeFitting", cs)
        self.assertIn("not fully connected (topology)", cs)   # witness present

    def test_tee_infers_tee_fitting(self):
        out = compile_program(_sys(*TEE, diameter_mm=100), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Pipe.Create(doc"), 3)
        self.assertIn("doc.Create.NewTeeFitting", cs)       # T degree 3
        self.assertNotIn("NewElbowFitting", cs)

    def test_single_transaction_and_regen_before_fittings(self):
        out = compile_program(_sys(*CHAIN, diameter_mm=80), snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertEqual(cs.count("new Transaction"), 1)
        i_seg = cs.index("Pipe.Create(doc")
        i_regen = cs.index("connectors materialize after regen")
        i_fit = cs.index("NewElbowFitting")
        self.assertLess(i_seg, i_regen)
        self.assertLess(i_regen, i_fit)

    def test_stamps_and_witness_readback(self):
        out = compile_program(_sys(*CHAIN, diameter_mm=80), snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", cs)
        self.assertIn('__results["SYS1"]', cs)
        self.assertIn('__rb["segments"]', cs)

    def test_tee_with_collinear_incident_pair_stays_tee(self):
        """Regression lock (not just a classify_junction unit assertion):
        TEE's own T-A/T-B pair is antiparallel (a straight line through T),
        yet T is degree 3 -> must compile to a tee, never an elbow/ConnectTo/
        transition, no matter how the geometry-aware classifier reads angles
        among a degree-3 node's edges."""
        out = compile_program(_sys(*TEE_WITH_COLLINEAR_PAIR, diameter_mm=100),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("doc.Create.NewTeeFitting", cs)
        self.assertNotIn("NewElbowFitting", cs)
        self.assertNotIn("NewTransitionFitting", cs)
        self.assertNotIn(".ConnectTo(", cs)


class StraightJointSemantics(unittest.TestCase):
    """THE FIX: a degree-2 node on a straight (collinear) run must NOT get an
    elbow — Revit has nothing to bend there and NewElbowFitting legitimately
    throws "failed to insert elbow". Same declared diameter on both sides ->
    Connector.ConnectTo (no fitting element, matches the wiki's verified
    "same size -> ConnectTo" recipe); different declared diameter -> a
    reducer (NewTransitionFitting), per KIR_CONNECT_SPEC.md §2."""

    def test_straight_same_diameter_connects_no_elbow(self):
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Pipe.Create(doc"), 2)
        self.assertNotIn("NewElbowFitting", cs)
        self.assertNotIn("NewTeeFitting", cs)
        self.assertNotIn("NewTransitionFitting", cs)
        self.assertIn(".ConnectTo(", cs)
        self.assertIn("not fully connected (topology)", cs)   # witness untouched

    def test_straight_diameter_change_uses_transition_not_elbow(self):
        out = compile_program(_sys(*STRAIGHT_DIAMETER_CHANGE, oid="SYST"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("doc.Create.NewTransitionFitting", cs)
        self.assertNotIn("NewElbowFitting", cs)
        self.assertNotIn("NewTeeFitting", cs)
        self.assertNotIn(".ConnectTo(", cs)

    def test_straight_run_single_transaction_and_regen_order(self):
        """Invariant (e) still holds for the new 'connect' branch: one txn,
        Regenerate before the join, rollback-on-catch guard present."""
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertEqual(cs.count("new Transaction"), 1)
        i_seg = cs.index("Pipe.Create(doc")
        i_regen = cs.index("connectors materialize after regen")
        i_join = cs.index(".ConnectTo(")
        self.assertLess(i_seg, i_regen)
        self.assertLess(i_regen, i_join)
        self.assertIn("__t.RollBack()", cs)   # catch guard on the ConnectTo call too

    def test_straight_run_rollback_guard_on_connectto(self):
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertIn('"ConnectTo: "', cs)   # typed __Refuse message on catch


class SystemMembershipIsDerivedNotForced(unittest.TestCase):
    """Refuting test for the round-2 «system merge» (connect.py §A).

    Round 2 saw «segments span multiple systems (semantic)» on a live network
    and concluded that the emitter must BUILD the shared MEPSystem itself, so
    it emitted `doc.Create.NewPipingSystem` over every free connector before
    ConnectTo. On a live Revit 2023 that call answers, every single time:

        Some of the input connectors have been used.

    because `Pipe.Create(systemTypeId, ...)` has already put both connectors
    into an auto-created system (measured: `MEPSystem = «Канализация 1»
    #21201145` while `IsConnected == false`). All four graph ops failed on it.

    The half round 2 missed: after `Commit()` Revit merges the systems itself
    — two pipes joined by ConnectTo and committed came back both reporting
    `#21201856 «Канализация 2»`. Membership is DERIVED at commit, so it can
    only be READ afterwards, never asserted inside the transaction.
    """

    def test_no_system_factory_call_is_emitted(self):
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertNotIn("doc.Create.NewPipingSystem", cs)
        self.assertNotIn("doc.Create.NewMechanicalSystem", cs)
        self.assertNotIn("сборка единой MEPSystem", cs)

    def test_in_transaction_post_no_longer_asserts_one_system(self):
        """The in-txn semantic guarantee is connectivity, which IS knowable
        before commit; the system clause was unprovable there by construction."""
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertNotIn("are not all in one MEPSystem (semantic)", cs)
        self.assertIn("network not fully connected (topology)", cs)

    def test_system_identity_is_read_back_after_commit(self):
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertIn("mep-system readback", cs)
        self.assertIn('"mep_system_ids"', cs)
        self.assertIn('"one_system"', cs)
        # after the transaction, not inside it
        self.assertLess(cs.index("__t.Commit()"), cs.index("mep-system readback"))

    def test_readback_covers_every_segment_of_a_tee(self):
        out = compile_program(_sys(*TEE, diameter_mm=100), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn(
            "new MEPCurve[] { __seg_SYS1_0, __seg_SYS1_1, __seg_SYS1_2 }",
            out.csharp)

    def test_fittings_still_emitted_for_bend_and_branch(self):
        """Dropping the merge must not disturb junction handling: the physical
        connection is what Revit derives membership FROM."""
        for prog, tok in ((_sys(*CHAIN, diameter_mm=80), "NewElbowFitting"),
                          (_sys(*TEE, diameter_mm=100), "NewTeeFitting")):
            with self.subTest(fixture=tok):
                out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
                self.assertIn(tok, out.csharp)

    def test_witness_still_checks_diameter_and_endpoints(self):
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        cs = out.csharp
        self.assertIn("segment 0 diameter (semantic)", cs)
        self.assertIn("RBS_PIPE_DIAMETER_PARAM", cs)
        self.assertIn("segment 0 endpoints (geometry)", cs)

    def test_vertical_endpoint_orientation_uses_xyz_proximity(self):
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertIn("__a.DistanceTo(P(0.0, 0.0, 0.0)) <= "
                      "__b.DistanceTo(P(0.0, 0.0, 0.0))", out.csharp)
        self.assertNotIn("bool __fwd = Math.Abs(MM(__a.X)", out.csharp)


class TeeArgumentOrder(unittest.TestCase):
    """FIX round 2 §B: NewTeeFitting requires its three connectors in ROLE
    order (main1, main2, branch — the wiki's own MEPM-017 recipe and this
    module's own TEE fixture both list the collinear pair first). The
    previous code passed cvars in raw graph-edge order, which only
    accidentally matched when the IR happened to author the collinear pair
    first. connect._reorder_tee_mains_first fixes the ARGUMENT ORDER handed
    to NewTeeFitting regardless of authoring order — this is a pure Python
    unit test of the ordering function itself (no compiler/Revit needed),
    mirroring JunctionClassification's own "provable offline" layer."""

    def test_collinear_pair_first_regardless_of_authoring_order(self):
        # T-A/T-B antiparallel (collinear pair), T-C perpendicular (branch) —
        # same geometry as the module's own TEE fixture, but authored with
        # the branch FIRST and the collinear pair split apart, to prove the
        # reorder doesn't just accidentally pass through the fixture's own
        # already-convenient order. vars_here's 2nd element is a NODE ID
        # (matching the real emit_fittings_cs contract: incident[nid]
        # entries carry other_node_id, not raw coordinates), resolved
        # through `nodes`.
        xyz = [0, 0, 0]
        nodes = {"oC": [0, 3000, 0], "oA": [3000, 0, 0], "oB": [-3000, 0, 0]}
        vars_here = [("vC", "oC", None), ("vA", "oA", None), ("vB", "oB", None)]
        ordered = CN._reorder_tee_mains_first(vars_here, xyz, nodes)
        ordered_vars = [v for v, _o, _d in ordered]
        # the two mains (vA, vB) must be first (in either relative order),
        # branch (vC) must be last.
        self.assertEqual(ordered_vars[2], "vC")
        self.assertEqual(set(ordered_vars[:2]), {"vA", "vB"})

    def test_reorder_is_a_pure_permutation(self):
        """Property: for any three incident rays, the reordered list is a
        permutation of the input (never drops/duplicates an entry)."""
        rng = random.Random(20260717 + 3)
        for case in range(30):
            xyz = [rng.uniform(-5000, 5000) for _ in range(3)]
            vars_here = []
            nodes = {}
            for k in range(3):
                other = [xyz[j] + rng.uniform(-8000, 8000) for j in range(3)]
                if math.dist(xyz, other) < 1.0:
                    other = [xyz[j] + 5000 for j in range(3)]
                oid = f"o{case}_{k}"
                nodes[oid] = other
                vars_here.append((f"v{k}", oid, None))
            ordered = CN._reorder_tee_mains_first(vars_here, xyz, nodes)
            self.assertEqual({v for v, _o, _d in ordered},
                             {v for v, _o, _d in vars_here})
            self.assertEqual(len(ordered), 3)

    def test_tee_fixture_compiles_with_reordered_args(self):
        """End-to-end: the module's own TEE fixture (T-A/T-B collinear
        through T, T-C perpendicular) must call NewTeeFitting with the two
        collinear vars first — locks the compiled-C# argument order, not
        just the pure-Python reorder function in isolation. T's incident
        segments are declared (T-A, T-B, T-C) in THIS fixture's authoring
        order, and A/B (the collinear pair) already come first there —
        i.e. this fixture alone can't distinguish "reordered correctly" from
        "happened to already be in order" (see the authoring-order-
        independence test above for that); this end-to-end test locks the
        exact call shape so a future edit can't silently regress the arg
        order back to raw graph-edge order without a visible diff here."""
        out = compile_program(_sys(*TEE, diameter_mm=100), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("doc.Create.NewTeeFitting(__cn_0_0, __cn_0_1, __cn_0_2)", cs)

    def test_node_ids_never_become_csharp_identifiers(self):
        nodes = [{"id": "A-B; } malicious", "xyz_mm": [0, 0, 0]},
                 {"id": "B", "xyz_mm": [0, 0, 3000]},
                 {"id": "C", "xyz_mm": [3000, 0, 3000]}]
        segs = [{"from": "A-B; } malicious", "to": "B"},
                {"from": "B", "to": "C"}]
        out = compile_program(_sys(nodes, segs), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
        self.assertIn("var __cn_0_0", out.csharp)
        self.assertNotIn("var __cn_A-B", out.csharp)


class FittingRefusalContext(unittest.TestCase):
    """FIX round 2 §B: every fitting refusal now carries the incident
    angle/diameters alongside Revit's own __exf.Message — never INSTEAD of
    it (the honesty invariant), just with the geometric context a human
    reading a live-test failure would ask for next."""

    def test_elbow_refusal_carries_angle_and_diameters(self):
        out = compile_program(_sys(*CHAIN, diameter_mm=80), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn('"NewElbowFitting: " + __exf.Message + "', cs)
        self.assertIn("angle=", cs)

    def test_tee_refusal_carries_main_branch_diameters(self):
        out = compile_program(_sys(*TEE, diameter_mm=100), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn('"NewTeeFitting: " + __exf.Message + "', cs)
        self.assertIn("main ", cs)
        self.assertIn("branch ", cs)

    def test_transition_refusal_carries_angle_and_diameters(self):
        out = compile_program(_sys(*STRAIGHT_DIAMETER_CHANGE, oid="SYST"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn('"NewTransitionFitting: " + __exf.Message + "', cs)

    def test_connectto_refusal_still_carries_context(self):
        out = compile_program(_sys(*STRAIGHT_SAME_DIA, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn('"ConnectTo: " + __exf.Message + "', cs)

    def test_undeclared_diameter_renders_as_question_mark_not_python_none(self):
        """A degree-2 elbow with no declared diameter on either side (CHAIN's
        own N2 has both diameters declared, so use a fresh undeclared-dia
        bend) must never leak Python's "None" into the C# string literal."""
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 3000]},
                {"id": "N3", "xyz_mm": [3000, 0, 3000]}]
        segs = [{"from": "N1", "to": "N2"}, {"from": "N2", "to": "N3"}]
        out = compile_program(_sys(nodes, segs, oid="SYSU"), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertNotIn("None/None", cs)
        self.assertNotIn("Nonemm", cs)


class NegativeGraph(unittest.TestCase):
    def test_non_string_endpoint_is_typed_refusal_not_internal_error(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]},
                 {"id": "N2", "xyz_mm": [1000, 0, 0]}]
        out = compile_program(_sys(nodes, [{"from": ["N1"], "to": "N2"}]),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])
        self.assertNotIn("KIR-P000", [d.code for d in out.diagnostics])

    def test_node_shape_and_id_are_strict(self):
        cases = [
            {"id": " N1", "xyz_mm": [0, 0, 0]},
            {"id": "N" * 65, "xyz_mm": [0, 0, 0]},
            {"id": "N1", "xyz_mm": [0, 0, 0], "ignored": True},
        ]
        for bad in cases:
            with self.subTest(node=bad):
                nodes = [bad, {"id": "N2", "xyz_mm": [1000, 0, 0]}]
                out = compile_program(_sys(nodes, [{"from": bad["id"], "to": "N2"}]),
                                      snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_dangling_component_refused(self):
        # N3 disconnected from N1-N2
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [1000, 0, 0]},
                 {"id": "N3", "xyz_mm": [5000, 0, 0]}, {"id": "N4", "xyz_mm": [6000, 0, 0]}]
        segs = [{"from": "N1", "to": "N2"}, {"from": "N3", "to": "N4"}]
        out = compile_program(_sys(nodes, segs), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-T003"][0]
        self.assertIn("несвязная", d.message_ru)

    def test_zero_segment_refused(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 0]}]
        out = compile_program(_sys(nodes, [{"from": "N1", "to": "N2"}]),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_undeclared_node_refused(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [1000, 0, 0]}]
        out = compile_program(_sys(nodes, [{"from": "N1", "to": "GHOST"}]),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-L003", [d.code for d in out.diagnostics])

    def test_degree_four_refused(self):
        nodes = [{"id": "H", "xyz_mm": [0, 0, 0]}] + [
            {"id": f"L{k}", "xyz_mm": [1000 * (k + 1), 0, 0]} for k in range(4)]
        segs = [{"from": "H", "to": f"L{k}"} for k in range(4)]
        out = compile_program(_sys(nodes, segs), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T003", [d.code for d in out.diagnostics])

    def test_duplicate_edge_and_self_loop(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [1000, 0, 0]}]
        dup = compile_program(_sys(nodes, [{"from": "N1", "to": "N2"},
                                           {"from": "N2", "to": "N1"}]),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(dup.ok)
        loop = compile_program(_sys(nodes, [{"from": "N1", "to": "N1"},
                                            {"from": "N1", "to": "N2"}]),
                               snapshot=GROUND_SNAPSHOT)
        self.assertFalse(loop.ok)

    def test_diameter_out_of_range(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [3000, 0, 0]}]
        out = compile_program(_sys(nodes, [{"from": "N1", "to": "N2",
                                            "diameter_mm": 9000}]),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])


class JunctionClassification(unittest.TestCase):
    """Pure unit tests of connect.classify_junction / connect._angle_deg —
    no compiler, no C#, no Revit. This is the layer the task's own honesty
    clause calls out as provable offline (the compile-gate proves compile,
    NOT fitting-choice correctness; a live re-test is still required for
    that) — so the classification LOGIC itself is pinned down exhaustively
    here, boundary included, independent of any particular IR program."""

    def test_degree_3_is_always_tee_regardless_of_angle_or_diameter(self):
        for angle in (None, 0.0, 90.0, 175.0, 179.9, 180.0):
            with self.subTest(angle=angle):
                # classify_junction's degree==3 branch ignores angle_deg/dia
                # entirely (by construction — checked BEFORE those args are
                # even read); feeding it varied values here proves that, not
                # just asserts it by inspection.
                self.assertEqual(CN.classify_junction(3, angle, None, None), "tee")
                self.assertEqual(CN.classify_junction(3, angle, 100.0, 50.0), "tee")

    def test_degree_2_genuine_bend_is_elbow(self):
        for angle in (0.0, 1.0, 45.0, 90.0, 120.0, 174.9):
            with self.subTest(angle=angle):
                self.assertEqual(CN.classify_junction(2, angle, 100.0, 100.0), "elbow")
                self.assertEqual(CN.classify_junction(2, angle, 100.0, 50.0), "elbow")
                self.assertEqual(CN.classify_junction(2, angle, None, None), "elbow")

    def test_degree_2_collinear_same_diameter_is_connect(self):
        for angle in (175.0, 176.0, 178.0, 179.99, 180.0):
            with self.subTest(angle=angle):
                self.assertEqual(CN.classify_junction(2, angle, 100.0, 100.0), "connect")
                # within _SAME_DIA_TOL (0.5mm) counts as "same" (float noise
                # tolerance, not exact-equality brittleness)
                self.assertEqual(CN.classify_junction(2, angle, 100.0, 100.3), "connect")

    def test_degree_2_collinear_unknown_diameter_is_connect_not_transition(self):
        """Cannot prove a diameter DIFFERS if either side is undeclared — the
        safe default when we don't know is to treat it as a straight
        same-size run (ConnectTo), not to guess a reducer is needed."""
        for dia_a, dia_b in ((None, None), (100.0, None), (None, 50.0)):
            with self.subTest(dia_a=dia_a, dia_b=dia_b):
                self.assertEqual(CN.classify_junction(2, 180.0, dia_a, dia_b), "connect")

    def test_degree_2_collinear_different_known_diameter_is_transition(self):
        for dia_a, dia_b in ((100.0, 50.0), (50.0, 100.0), (200.0, 25.0)):
            with self.subTest(dia_a=dia_a, dia_b=dia_b):
                self.assertEqual(CN.classify_junction(2, 180.0, dia_a, dia_b), "transition")

    def test_collinear_threshold_boundary_is_exact(self):
        """Just under the threshold -> elbow; at or over -> connect. Locks
        the boundary itself (off-by-one/off-by-epsilon class of bug) rather
        than only sampling comfortably inside each region."""
        just_under = CN._COLLINEAR_ANGLE_DEG - 1e-6
        at = CN._COLLINEAR_ANGLE_DEG
        just_over = CN._COLLINEAR_ANGLE_DEG + 1e-6
        self.assertEqual(CN.classify_junction(2, just_under, 100.0, 100.0), "elbow")
        self.assertEqual(CN.classify_junction(2, at, 100.0, 100.0), "connect")
        self.assertEqual(CN.classify_junction(2, just_over, 100.0, 100.0), "connect")

    def test_invalid_degree_raises_not_silently_guesses(self):
        """degree must be 2 or 3 (graph_validate's own cap + emit_fittings_cs's
        len<2 skip guarantee this in the real pipeline); anything else is a
        caller bug and must be LOUD, never a silent fallback fitting choice."""
        for bad_degree in (0, 1, 4, 5, -1):
            with self.subTest(degree=bad_degree):
                with self.assertRaises(ValueError):
                    CN.classify_junction(bad_degree, 180.0, None, None)


class AngleGeometry(unittest.TestCase):
    """Pure unit tests of connect._angle_deg — the geometric primitive
    classify_junction's angle_deg input is computed from in emit_fittings_cs.
    Property-style: many synthetic node/ray configurations, well-typed by
    construction (every case is a real, finite, non-degenerate 3D point
    triple), boundary + degenerate cases included."""

    def test_right_angle_bend_is_90(self):
        self.assertAlmostEqual(CN._angle_deg([0, 0, 0], [1000, 0, 0], [0, 1000, 0]), 90.0, places=6)

    def test_straight_line_is_180(self):
        self.assertAlmostEqual(CN._angle_deg([0, 0, 0], [-5000, 0, 0], [5000, 0, 0]), 180.0, places=6)

    def test_hairpin_back_on_itself_is_near_0(self):
        self.assertLess(CN._angle_deg([0, 0, 0], [1000, 0, 0], [999, 10, 0]), 5.0)

    def test_symmetric_in_its_two_ray_arguments(self):
        """angle(node, p_a, p_b) == angle(node, p_b, p_a) — the classification
        must not depend on which incident segment happens to be listed
        first/second in seg_meta (an emit-order artifact, not a real
        geometric distinction)."""
        rng = random.Random(20260717)
        for _ in range(50):
            node = [rng.uniform(-5000, 5000) for _ in range(3)]
            pa = [node[k] + rng.uniform(-8000, 8000) for k in range(3)]
            pb = [node[k] + rng.uniform(-8000, 8000) for k in range(3)]
            if math.dist(node, pa) < 1.0 or math.dist(node, pb) < 1.0:
                continue   # skip the astronomically-unlikely near-zero ray
            self.assertAlmostEqual(CN._angle_deg(node, pa, pb),
                                   CN._angle_deg(node, pb, pa), places=6)

    def test_degenerate_zero_length_ray_returns_collinear_not_raise(self):
        """Defense in depth (module docstring): graph_validate's _EDGE_TOL
        should make this unreachable via the real pipeline, but the helper
        itself must never divide-by-zero if ever called with a coincident
        point — returning 180.0 (collinear) is the safe direction (routes to
        ConnectTo/transition, never forces a bogus elbow on a degenerate
        ray)."""
        self.assertEqual(CN._angle_deg([0, 0, 0], [0, 0, 0], [1000, 0, 0]), 180.0)
        self.assertEqual(CN._angle_deg([0, 0, 0], [1000, 0, 0], [0, 0, 0]), 180.0)

    def test_angle_always_in_valid_range(self):
        """Property: for ANY two non-degenerate rays, angle in [0, 180]."""
        rng = random.Random(20260717 + 1)
        for _ in range(200):
            node = [rng.uniform(-10000, 10000) for _ in range(3)]
            pa = [node[k] + rng.uniform(-10000, 10000) for k in range(3)]
            pb = [node[k] + rng.uniform(-10000, 10000) for k in range(3)]
            if math.dist(node, pa) < 1.0 or math.dist(node, pb) < 1.0:
                continue
            a = CN._angle_deg(node, pa, pb)
            self.assertGreaterEqual(a, 0.0)
            self.assertLessEqual(a, 180.0)


if __name__ == "__main__":
    unittest.main()
