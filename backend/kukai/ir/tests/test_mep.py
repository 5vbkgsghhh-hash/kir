"""wave/mep gates: route_pipe_system (ВК) / route_duct_system (ОВ) — CONNECT
graph pattern tiled onto the full МЕР network family (KIR_CONNECT_SPEC.md,
REGISTRY_MODULES.md). Mirrors test_connect.py's structure 1:1 (same graph
laws reused from connect.py: connectivity BFS, degree-cap, fitting-by-degree,
zero/dup-edge/self-loop) plus the wave-added checked slope postcondition and
the ring-topology case the CONNECT checklist calls out ("кольцо — если
домен допускает").

FIX 2026-07-17: this is the exact op family the live semantic test found
broken — a multi-segment stояк+отвод / тройник network refused at RUNTIME
("NewElbowFitting: failed to insert elbow") because every degree-2 node got
an elbow forced onto it, even a straight (collinear) pass-through with
nothing to bend. StraightRunSemantics below adds the riser-with-a-straight-
continuation case (the literal failure shape from the diagnosis) for BOTH
route_pipe_system and route_duct_system; CHAIN/TEE/RING above are all
GENUINE bends/branches (see connect.py's classify_junction) and are left
completely unchanged — this fix must not alter a correctly-classified
junction, on either op.

Gate checklist (KIR_CONNECT_SPEC.md "Чеклист ворот нового CONNECT-опа"):
  (a) property: linear chain / T-branch / ring — GraphSemantics + PropertyMEP
  (b) golden 6 versions — see gate_runner.py (this wave adds programs there)
  (d) negative: dangling node (T003), dup edge, zero segment (T002),
      degree-4 refusal, undeclared node (L003), out-of-range diameter (T002),
      slope requirement violated (L004, live-witness only — a compile-time
      corpus can't fake a live LocationCurve reading, flagged below)
  (e) invariant: 1 transaction, Regenerate before fittings, rollback-on-catch
  (f) witness: connector-graph BFS obход in post (topology) — reused
      connect.emit_connectivity_witness_cs, same as create_pipe_system
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_mep_queue.jsonl"))

from kukai.ir import route_mep as RM  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.schema_gen import program_schema  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

LVL = {"by": "element_id", "value": 42}


def _pipe_sys(nodes, segments, oid="SYS1", **kw):
    op = {"op": "route_pipe_system", "id": oid, "level": LVL,
          "nodes": nodes, "segments": segments}
    op.update(kw)
    return {"ir_version": "1.0", "intent": "route_pipe-test", "ops": [op]}


def _duct_sys(nodes, segments, oid="SYS1", **kw):
    op = {"op": "route_duct_system", "id": oid, "level": LVL,
          "nodes": nodes, "segments": segments}
    op.update(kw)
    return {"ir_version": "1.0", "intent": "route_duct-test", "ops": [op]}


CHAIN = ([{"id": "N1", "xyz_mm": [0, 0, 3000]}, {"id": "N2", "xyz_mm": [0, 0, 0]},
          {"id": "N3", "xyz_mm": [3000, 0, 0]}],
         [{"from": "N1", "to": "N2", "diameter_mm": 100},
          {"from": "N2", "to": "N3", "diameter_mm": 50}])

TEE = ([{"id": "T", "xyz_mm": [0, 0, 0]}, {"id": "A", "xyz_mm": [3000, 0, 0]},
        {"id": "B", "xyz_mm": [-3000, 0, 0]}, {"id": "C", "xyz_mm": [0, 3000, 0]}],
       [{"from": "T", "to": "A"}, {"from": "T", "to": "B"}, {"from": "T", "to": "C"}])

# Ring: closed square loop, every node degree 2 — the CONNECT checklist's
# "кольцо (если домен допускает)" case. Nothing in the graph model (BFS
# connectivity + degree<=3 cap) forbids a cycle; this proves it end to end.
RING = ([{"id": "R1", "xyz_mm": [0, 0, 3000]}, {"id": "R2", "xyz_mm": [4000, 0, 3000]},
         {"id": "R3", "xyz_mm": [4000, 4000, 3000]}, {"id": "R4", "xyz_mm": [0, 4000, 3000]}],
        [{"from": "R1", "to": "R2"}, {"from": "R2", "to": "R3"},
         {"from": "R3", "to": "R4"}, {"from": "R4", "to": "R1"}])

# THE FAILURE SHAPE: a riser (stояк) that continues straight — N2 is a
# pass-through on the same vertical line, not a bend. Before the fix,
# route_pipe_system/route_duct_system emitted NewElbowFitting at N2 anyway;
# at runtime Revit refuses ("failed to insert elbow") because there is
# nothing to elbow on a straight line. This is the network shape the
# operator's live test actually exercised (стояк с ПРЯМЫМ продолжением, not
# стояк+отвод — that one, route_pipe_system_riser_branch's golden, is a
# genuine 90deg bend and stays an elbow, unaffected by this fix).
RISER_STRAIGHT = (
    [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 6000]},
     {"id": "N3", "xyz_mm": [0, 0, 12000]}],
    [{"from": "N1", "to": "N2", "diameter_mm": 100},
     {"from": "N2", "to": "N3", "diameter_mm": 100}])


class PipeGraphSemantics(unittest.TestCase):
    """route_pipe_system: same graph invariants as create_pipe_system (this
    op reuses connect.graph_validate/emit_fittings_cs/emit_connectivity_
    witness_cs unmodified — see authoring.py's _emit_route_pipe_system)."""

    def test_chain_compiles_with_elbow(self):
        out = compile_program(_pipe_sys(*CHAIN, diameter_mm=80), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Pipe.Create(doc"), 2)
        self.assertIn("doc.Create.NewElbowFitting", cs)
        self.assertNotIn("NewTeeFitting", cs)
        self.assertIn("not fully connected (topology)", cs)

    def test_tee_infers_tee_fitting(self):
        out = compile_program(_pipe_sys(*TEE, diameter_mm=100), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Pipe.Create(doc"), 3)
        self.assertIn("doc.Create.NewTeeFitting", cs)
        self.assertNotIn("NewElbowFitting", cs)

    def test_ring_compiles_all_elbows_no_tee(self):
        """Closed loop: every node degree 2 -> all elbows, zero tees, and the
        connectivity witness still reaches every segment (a cycle is NOT a
        dangling component)."""
        out = compile_program(_pipe_sys(*RING, diameter_mm=100), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Pipe.Create(doc"), 4)
        self.assertIn("doc.Create.NewElbowFitting", cs)
        self.assertNotIn("NewTeeFitting", cs)
        self.assertIn("not fully connected (topology)", cs)

    def test_single_transaction_and_regen_before_fittings(self):
        out = compile_program(_pipe_sys(*CHAIN, diameter_mm=80), snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertEqual(cs.count("new Transaction"), 1)
        i_seg = cs.index("Pipe.Create(doc")
        i_regen = cs.index("connectors materialize after regen")
        i_fit = cs.index("NewElbowFitting")
        self.assertLess(i_seg, i_regen)
        self.assertLess(i_regen, i_fit)

    def test_stamps_and_witness_readback(self):
        out = compile_program(_pipe_sys(*CHAIN, diameter_mm=80), snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", cs)
        self.assertIn('__results["SYS1"]', cs)
        self.assertIn('__rb["segments"]', cs)

    def test_rollback_on_null_guard(self):
        """Invariant (e): every emitted create call has a RollBack-on-null
        guard (in-txn commit-gate, zero-trace-on-fail) — at least as many
        RollBack() call-sites as segment creations (fittings add more)."""
        out = compile_program(_pipe_sys(*TEE, diameter_mm=100), snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertGreaterEqual(cs.count("__t.RollBack()"), cs.count("Pipe.Create(doc"))


class PipeSlopeWitness(unittest.TestCase):
    def test_canonical_edge_key_is_injective(self):
        self.assertNotEqual(RM.edge_key("a", "b␟c"),
                            RM.edge_key("a␟b", "c"))

    def test_schema_exposes_supported_slope_requirement(self):
        schema = program_schema()
        variants = schema["properties"]["ops"]["items"]["oneOf"]
        route = next(v for v in variants
                     if v["properties"]["op"].get("const") == "route_pipe_system")
        seg_props = route["properties"]["segments"]["items"]["properties"]
        self.assertIn("slope_min_pct", seg_props)
        self.assertEqual(seg_props["slope_min_pct"]["maximum"], 100.0)

    """The wave-added CHECKED (not generative) slope postcondition — see
    ops_connect.py's module docstring for why this is a witness, not a
    Z-deriving param. Compile-time we can only assert the witness CODE is
    emitted with the right threshold; whether it actually fires needs a
    live segment whose real slope is under the floor, which only the
    compile-gate / a live Revit run can prove (flagged: no offline harness
    fakes a LocationCurve readback)."""

    def test_slope_requirement_emits_checked_witness(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 500]}, {"id": "N2", "xyz_mm": [0, 0, 0]}]
        segs = [{"from": "N1", "to": "N2", "diameter_mm": 100, "slope_min_pct": 2.0}]
        out = compile_program(_pipe_sys(nodes, segs), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("slope witness", cs)
        self.assertIn("slope below required 2.0%", cs)
        self.assertIn("KIR-L004", cs)
        # checked AFTER the connectivity witness, both inside the same post
        # block (both run before commit -> both can roll back the same txn)
        self.assertLess(cs.index("not fully connected (topology)"),
                        cs.index("slope witness"))

    def test_no_slope_key_no_witness_emitted(self):
        """Omitting slope_min_pct must not emit ANY slope-check code — the
        postcondition is opt-in per segment, never a hidden default floor."""
        out = compile_program(_pipe_sys(*CHAIN, diameter_mm=80), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertNotIn("slope witness", out.csharp)
        self.assertNotIn("KIR-L004", out.csharp)

    def test_slope_min_pct_out_of_bounds_refused(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 500]}, {"id": "N2", "xyz_mm": [0, 0, 0]}]
        out = compile_program(_pipe_sys(
            nodes, [{"from": "N1", "to": "N2", "slope_min_pct": 150.0}]),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_slope_key_stripped_before_shared_graph_validate(self):
        """The slope_min_pct key must never leak into connect.graph_validate
        (its closed segment-shape set {from,to,diameter_mm} would otherwise
        reject every sloped segment as a malformed dict — see
        route_mep.strip_slope_keys)."""
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 500]}, {"id": "N2", "xyz_mm": [0, 0, 0]},
                 {"id": "N3", "xyz_mm": [3000, 0, 0]}]
        segs = [{"from": "N1", "to": "N2", "diameter_mm": 100, "slope_min_pct": 1.5},
                {"from": "N2", "to": "N3", "diameter_mm": 50, "slope_min_pct": 3.0}]
        out = compile_program(_pipe_sys(nodes, segs), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("slope below required 1.5%", cs)
        self.assertIn("slope below required 3.0%", cs)


class StraightRunSemantics(unittest.TestCase):
    """THE FIX, run through BOTH route_pipe_system and route_duct_system —
    proves the connect.emit_fittings_cs fix is REAL for the exact ops the
    live semantic test diagnosed as broken (multi-segment ВК/ОВ networks),
    not just for create_pipe_system's own test_connect.py coverage. A
    straight (collinear) riser continuation must join via ConnectTo — no
    NewElbowFitting, which used to throw "failed to insert elbow" here at
    runtime because there was never a real bend to insert."""

    def test_pipe_straight_riser_connects_no_elbow(self):
        out = compile_program(_pipe_sys(*RISER_STRAIGHT, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Pipe.Create(doc"), 2)
        self.assertNotIn("NewElbowFitting", cs)
        self.assertNotIn("NewTeeFitting", cs)
        self.assertIn(".ConnectTo(", cs)
        self.assertIn("not fully connected (topology)", cs)

    def test_duct_straight_riser_connects_no_elbow(self):
        out = compile_program(_duct_sys(*RISER_STRAIGHT, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Duct.Create(doc"), 2)
        self.assertNotIn("NewElbowFitting", cs)
        self.assertNotIn("NewTeeFitting", cs)
        self.assertIn(".ConnectTo(", cs)

    def test_pipe_straight_diameter_change_uses_transition(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 6000]},
                 {"id": "N3", "xyz_mm": [0, 0, 12000]}]
        segs = [{"from": "N1", "to": "N2", "diameter_mm": 100},
                {"from": "N2", "to": "N3", "diameter_mm": 50}]
        out = compile_program(_pipe_sys(nodes, segs, oid="SYST"), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertIn("doc.Create.NewTransitionFitting", cs)
        self.assertNotIn("NewElbowFitting", cs)
        self.assertNotIn(".ConnectTo(", cs)

    def test_straight_run_still_single_transaction_and_regen_order(self):
        """Invariant (e) unaffected by the fix on the route_* ops too."""
        out = compile_program(_pipe_sys(*RISER_STRAIGHT, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertEqual(cs.count("new Transaction"), 1)
        i_seg = cs.index("Pipe.Create(doc")
        i_regen = cs.index("connectors materialize after regen")
        i_join = cs.index(".ConnectTo(")
        self.assertLess(i_seg, i_regen)
        self.assertLess(i_regen, i_join)

    def test_existing_bend_and_branch_fixtures_unaffected(self):
        """Regression lock: CHAIN (genuine 90deg bend) and TEE (genuine
        branch) — the two fixtures this whole module was built on — must
        emit EXACTLY what they did before this fix, on both ops. Written
        explicitly here (not just relying on the pre-existing
        PipeGraphSemantics/DuctGraphSemantics tests staying green) so a
        future reader sees the "did I break the old cases" question
        answered in the same place as the new ones."""
        for maker, create_tok in ((_pipe_sys, "Pipe.Create(doc"), (_duct_sys, "Duct.Create(doc")):
            with self.subTest(op=maker.__name__, fixture="CHAIN"):
                out = compile_program(maker(*CHAIN, oid="C1"), snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
                self.assertIn("doc.Create.NewElbowFitting", out.csharp)
                self.assertNotIn(".ConnectTo(", out.csharp)
                self.assertNotIn("NewTransitionFitting", out.csharp)
            with self.subTest(op=maker.__name__, fixture="TEE"):
                dia = 100 if maker is _pipe_sys else 250
                out = compile_program(maker(*TEE, oid="T1", diameter_mm=dia),
                                      snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
                self.assertIn("doc.Create.NewTeeFitting", out.csharp)
                self.assertNotIn("NewElbowFitting", out.csharp)
                self.assertNotIn(".ConnectTo(", out.csharp)


class SystemMembershipMEP(unittest.TestCase):
    """connect.py §A run through BOTH route_pipe_system and route_duct_system.

    Same measured facts as test_connect.SystemMembershipIsDerivedNotForced:
    `NewPipingSystem`/`NewMechanicalSystem` cannot be called on connectors
    `Pipe.Create`/`Duct.Create` already placed in an auto-created system, and
    Revit merges the systems itself at commit. Both ops therefore emit no
    system factory call and read membership back afterwards.
    """

    def test_pipe_route_emits_no_system_factory(self):
        out = compile_program(_pipe_sys(*RISER_STRAIGHT, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertNotIn("doc.Create.NewPipingSystem", cs)
        self.assertNotIn("сборка единой MEPSystem", cs)
        self.assertIn("mep-system readback", cs)
        self.assertLess(cs.index("__t.Commit()"), cs.index("mep-system readback"))

    def test_duct_route_emits_no_system_factory(self):
        out = compile_program(_duct_sys(*RISER_STRAIGHT, oid="SYSR"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertNotIn("doc.Create.NewMechanicalSystem", cs)
        self.assertNotIn("doc.Create.NewPipingSystem", cs)
        self.assertIn('"one_system"', cs)

    def test_both_domains_keep_their_fittings(self):
        out_p = compile_program(_pipe_sys(*TEE, diameter_mm=100),
                                snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out_p.ok, [d.as_dict() for d in out_p.diagnostics][:3])
        self.assertIn("doc.Create.NewTeeFitting", out_p.csharp)

        out_d = compile_program(_duct_sys(*TEE, diameter_mm=250),
                                snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out_d.ok, [d.as_dict() for d in out_d.diagnostics][:3])
        self.assertIn("doc.Create.NewTeeFitting", out_d.csharp)

    def test_ring_topology_reads_back_every_segment(self):
        """A closed ring has no dangling end; the readback must still cover
        all four segments (this was the reason the old merge grabbed all 2*N
        connectors up front)."""
        out = compile_program(_pipe_sys(*RING, diameter_mm=100, oid="SYSRING"),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn(
            "new MEPCurve[] { __seg_SYSRING_0, __seg_SYSRING_1, "
            "__seg_SYSRING_2, __seg_SYSRING_3 }", out.csharp)


class DuctGraphSemantics(unittest.TestCase):
    """route_duct_system: mirrors PipeGraphSemantics over Duct.Create /
    RBS_CURVE_DIAMETER_PARAM (route_mep.emit_segments_route_cs, NOT
    connect.emit_segments_cs — that one hardcodes the pipe-only diameter
    BIP, which would silently no-op on a Duct element)."""

    def test_chain_compiles_with_elbow(self):
        out = compile_program(_duct_sys(*CHAIN, diameter_mm=300), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Duct.Create(doc"), 2)
        self.assertIn("doc.Create.NewElbowFitting", cs)
        self.assertNotIn("NewTeeFitting", cs)
        self.assertIn("RBS_CURVE_DIAMETER_PARAM", cs)
        self.assertNotIn("RBS_PIPE_DIAMETER_PARAM", cs)   # domain BIP correctness
        self.assertIn("segment 0 diameter (semantic)", cs)
        # The in-txn MEPSystem clause was replaced by the post-commit readback
        # (connect.py §A): Revit derives membership at commit, so the duct
        # chain's semantic guarantee inside the transaction is connectivity.
        self.assertIn("network not fully connected (topology)", cs)
        self.assertIn('"one_system"', cs)

    def test_tee_infers_tee_fitting(self):
        out = compile_program(_duct_sys(*TEE, diameter_mm=250), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Duct.Create(doc"), 3)
        self.assertIn("doc.Create.NewTeeFitting", cs)
        self.assertNotIn("NewElbowFitting", cs)

    def test_ring_compiles(self):
        out = compile_program(_duct_sys(*RING, diameter_mm=200), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        cs = out.csharp
        self.assertEqual(cs.count("Duct.Create(doc"), 4)
        self.assertIn("doc.Create.NewElbowFitting", cs)
        self.assertNotIn("NewTeeFitting", cs)

    def test_single_transaction_and_regen_before_fittings(self):
        out = compile_program(_duct_sys(*CHAIN, diameter_mm=300), snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertEqual(cs.count("new Transaction"), 1)
        i_seg = cs.index("Duct.Create(doc")
        i_regen = cs.index("connectors materialize after regen")
        i_fit = cs.index("NewElbowFitting")
        self.assertLess(i_seg, i_regen)
        self.assertLess(i_regen, i_fit)

    def test_stamps_and_witness_readback(self):
        out = compile_program(_duct_sys(*CHAIN, diameter_mm=300), snapshot=GROUND_SNAPSHOT)
        cs = out.csharp
        self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", cs)
        self.assertIn('__results["SYS1"]', cs)
        self.assertIn('__rb["segments"]', cs)

    def test_slope_witness_reuses_same_mechanism(self):
        nodes = [{"id": "A", "xyz_mm": [0, 0, 3000]}, {"id": "B", "xyz_mm": [5000, 0, 2900]}]
        segs = [{"from": "A", "to": "B", "diameter_mm": 200, "slope_min_pct": 0.5}]
        out = compile_program(_duct_sys(nodes, segs), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
        self.assertIn("KIR-L004", out.csharp)


class NegativeGraphShared(unittest.TestCase):
    """The graph-law negative corpus, run through BOTH route_pipe_system and
    route_duct_system — proves the connect.graph_validate reuse is REAL (same
    typed refusals fire identically for both ops), not a copy that quietly
    diverged."""

    def _both(self, nodes, segs, **kw):
        return (_pipe_sys(nodes, segs, **kw), _duct_sys(nodes, segs, **kw))

    def test_dangling_component_refused(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [1000, 0, 0]},
                 {"id": "N3", "xyz_mm": [5000, 0, 0]}, {"id": "N4", "xyz_mm": [6000, 0, 0]}]
        segs = [{"from": "N1", "to": "N2"}, {"from": "N3", "to": "N4"}]
        for prog in self._both(nodes, segs):
            with self.subTest(op=prog["ops"][0]["op"]):
                out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                d = [x for x in out.diagnostics if x.code == "KIR-T004"][0]
                self.assertIn("несвязная", d.message_ru)

    def test_zero_segment_refused(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [0, 0, 0]}]
        for prog in self._both(nodes, [{"from": "N1", "to": "N2"}]):
            with self.subTest(op=prog["ops"][0]["op"]):
                out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_undeclared_node_refused(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [1000, 0, 0]}]
        for prog in self._both(nodes, [{"from": "N1", "to": "GHOST"}]):
            with self.subTest(op=prog["ops"][0]["op"]):
                out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-L003", [d.code for d in out.diagnostics])

    def test_degree_four_refused(self):
        nodes = [{"id": "H", "xyz_mm": [0, 0, 0]}] + [
            {"id": f"L{k}", "xyz_mm": [1000 * (k + 1), 0, 0]} for k in range(4)]
        segs = [{"from": "H", "to": f"L{k}"} for k in range(4)]
        for prog in self._both(nodes, segs):
            with self.subTest(op=prog["ops"][0]["op"]):
                out = compile_program(prog, snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-T004", [d.code for d in out.diagnostics])

    def test_duplicate_edge_and_self_loop(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [1000, 0, 0]}]
        for maker in (_pipe_sys, _duct_sys):
            with self.subTest(op=maker.__name__):
                dup = compile_program(maker(nodes, [{"from": "N1", "to": "N2"},
                                                     {"from": "N2", "to": "N1"}]),
                                      snapshot=GROUND_SNAPSHOT)
                self.assertFalse(dup.ok)
                loop = compile_program(maker(nodes, [{"from": "N1", "to": "N1"},
                                                      {"from": "N1", "to": "N2"}]),
                                       snapshot=GROUND_SNAPSHOT)
                self.assertFalse(loop.ok)

    def test_diameter_out_of_range_pipe(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [3000, 0, 0]}]
        out = compile_program(_pipe_sys(nodes, [{"from": "N1", "to": "N2",
                                                 "diameter_mm": 9000}]),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_duct_uses_duct_specific_diameter_range(self):
        nodes = [{"id": "N1", "xyz_mm": [0, 0, 0]}, {"id": "N2", "xyz_mm": [3000, 0, 0]}]
        out = compile_program(_duct_sys(nodes, [{"from": "N1", "to": "N2",
                                                  "diameter_mm": 2500}]),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

        too_large = compile_program(_duct_sys(
            nodes, [{"from": "N1", "to": "N2", "diameter_mm": 3001}]),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(too_large.ok)
        self.assertIn("KIR-T002", [d.code for d in too_large.diagnostics])


class PropertyMEP(unittest.TestCase):
    """Gate (a): property-based — every well-typed graph program
    (linear/branching/random, no dangling components, degree<=3, no
    zero/dup edges) compiles ok. Generator follows test_pbt.py's
    well-typed-by-construction discipline (build valid, don't generate-and-
    filter) so every case is a REAL positive proof, not a lottery."""
    N = 60
    SEED = 20260717

    @staticmethod
    def _gen_tree(rng: random.Random, n_nodes: int) -> tuple:
        """A random SPANNING TREE (guarantees connectivity by construction)
        with degree capped at 3 by construction (skip a parent once it
        already has 3 children/parent-edges)."""
        ids = [f"N{k}" for k in range(n_nodes)]
        nodes = [{"id": ids[0], "xyz_mm": [0, 0, 0]}]
        placed = {ids[0]}
        degree = {ids[0]: 0}
        segs = []
        frontier = [ids[0]]
        for nid in ids[1:]:
            # pick a parent with degree < 3 (exists: a fresh spanning tree
            # always has at least one attach point while frontier nonempty)
            candidates = [p for p in frontier if degree[p] < 3]
            if not candidates:
                candidates = [p for p in placed if degree[p] < 3]
            parent = rng.choice(candidates)
            px, py, pz = next(n["xyz_mm"] for n in nodes if n["id"] == parent)
            # deterministic small offset so no two nodes ever coincide
            dx = rng.choice([-1, 1]) * rng.randint(1000, 4000)
            dy = rng.choice([-1, 1]) * rng.randint(1000, 4000)
            nodes.append({"id": nid, "xyz_mm": [px + dx, py + dy, pz]})
            segs.append({"from": parent, "to": nid,
                        "diameter_mm": rng.choice([25, 50, 80, 100, 150])})
            degree[parent] += 1
            degree[nid] = 1
            placed.add(nid)
            frontier.append(nid)
        return nodes, segs

    def test_random_trees_compile_pipe(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            n_nodes = rng.randint(2, 12)
            nodes, segs = self._gen_tree(rng, n_nodes)
            with self.subTest(case=case, n_nodes=n_nodes):
                out = compile_program(_pipe_sys(nodes, segs, oid=f"P{case}"),
                                      snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
                self.assertEqual(out.csharp.count("Pipe.Create(doc"), len(segs))
                self.assertIn("not fully connected (topology)", out.csharp)

    def test_random_trees_compile_duct(self):
        rng = random.Random(self.SEED + 1)
        for case in range(self.N):
            n_nodes = rng.randint(2, 12)
            nodes, segs = self._gen_tree(rng, n_nodes)
            # bump diameters into duct-legal range for this domain
            for s in segs:
                s["diameter_mm"] = rng.choice([100, 150, 200, 300, 400])
            with self.subTest(case=case, n_nodes=n_nodes):
                out = compile_program(_duct_sys(nodes, segs, oid=f"D{case}"),
                                      snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:3])
                self.assertEqual(out.csharp.count("Duct.Create(doc"), len(segs))
                self.assertIn("not fully connected (topology)", out.csharp)

    def test_every_generated_tree_respects_degree_cap(self):
        """Sanity on the generator itself (P0: the generator must actually
        produce what it claims — a spanning tree with degree<=3 — or the
        positive-compile assertions above would be vacuous)."""
        rng = random.Random(self.SEED + 2)
        for case in range(self.N):
            n_nodes = rng.randint(2, 20)
            nodes, segs = self._gen_tree(rng, n_nodes)
            degree = {n["id"]: 0 for n in nodes}
            for s in segs:
                degree[s["from"]] += 1
                degree[s["to"]] += 1
            with self.subTest(case=case):
                self.assertEqual(len(segs), n_nodes - 1, "tree has n-1 edges")
                self.assertTrue(all(d <= 3 for d in degree.values()))


class SnapshotAndVersionAxis(unittest.TestCase):
    """Gate (e)-adjacent: no-snapshot refusal (grounded selectors need a
    census) and per-version emit stability, mirroring test_authoring.py's
    VersionAxis / Ground.test_missing_snapshot conventions for the new ops."""

    def test_no_snapshot_refused(self):
        out = compile_program(_pipe_sys(*CHAIN, diameter_mm=80), snapshot=None)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G103", [d.code for d in out.diagnostics])

    def test_compiles_on_all_six_versions(self):
        from kukai.ir import spec
        for ver in spec.REVIT_VERSIONS:
            with self.subTest(ver=ver):
                out = compile_program(_pipe_sys(*TEE, diameter_mm=100),
                                      revit_version=ver, snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, f"{ver}: {[d.as_dict() for d in out.diagnostics][:3]}")
                out2 = compile_program(_duct_sys(*TEE, diameter_mm=250),
                                       revit_version=ver, snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out2.ok, f"{ver}: {[d.as_dict() for d in out2.diagnostics][:3]}")


if __name__ == "__main__":
    unittest.main()
