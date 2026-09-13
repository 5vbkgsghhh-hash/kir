"""wave/mep-electrical: an electrical conduit, two placeholders, two flex
runs — and one NAMED REFUSAL (`create_wire`).

Before this wave, everything below the tray and all "soft" engineering
were blind: `registry_base.KINDS` already knew how to COUNT conduits,
flex ducts, and flex pipes, but could not build a single one. Five
operations close exactly this gap.

New-op gate checklist (KIR_CONNECT_SPEC.md, the same one the mep wave
used):
  (a) property — `PropertyFlexPath` below: any correct polyline is built;
  (b) golden ×6 versions — `test_golden.mep_conduit_and_placeholders` /
      `mep_flex_runs`, plus the live gate_runner (both isolations);
  (d) negative — `NegativeShared`: no snapshot, an ambiguous pool, an
      empty pool, a degenerate link, a 2D point in a 3D path, a polyline
      of a single point, longer than 64 points;
  (e) invariant — one transaction, a null-guard on every creation;
  (f) witness — `WitnessReadsTheResult`: EVERY check reads the built
      element (`LocationCurve` / `IsPlaceholder` / `Points` / `GetTypeId`),
      and none merely confirms that the setter ran.

`WireIsDeliberatelyAbsent` stands apart. `Wire.Create` compiles on all six
versions together with two `null` connectors — that is, shipping the
operation WAS possible, and that is exactly why the decision not to ship
it needs to be pinned by a test: otherwise the next session will see a
green compiler, see no reason, and add a vacuous check. The full reasoning
is in the header of `ops_mep.py`.
"""
import os
import random
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_test_mep_electrical_queue.jsonl"))

from kir import spec                                        # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.schema_gen import program_schema                   # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT              # noqa: E402

LVL = {"by": "element_id", "value": 42}

#: (op name, body without id/level) — the corpus over which the shared laws run.
LINEAR_OPS = (
    ("create_conduit", {"p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000]}),
    ("create_pipe_placeholder",
     {"p0_mm": [0, 1000, 2800], "p1_mm": [6000, 1000, 2800]}),
    ("create_duct_placeholder",
     {"p0_mm": [0, 2000, 3200], "p1_mm": [6000, 2000, 3200]}),
)

FLEX_OPS = (
    ("create_flex_duct", {"path": [[0, 3000, 3000], [1500, 3000, 2800],
                                   [3000, 3200, 2600]]}),
    ("create_flex_pipe", {"path": [[0, 4000, 3000], [1500, 4000, 2700]]}),
)

ALL_OPS = LINEAR_OPS + FLEX_OPS


def _prog(op_name: str, body: dict, oid: str = "X1", **kw) -> dict:
    op = {"op": op_name, "id": oid, "level": LVL}
    op.update(body)
    op.update(kw)
    return {"ir_version": "1.0", "intent": f"{op_name}-test", "ops": [op]}


def _cs(op_name: str, body: dict, snapshot=GROUND_SNAPSHOT, **kw) -> str:
    out = compile_program(_prog(op_name, body, **kw), snapshot=snapshot)
    assert out.ok, [d.as_dict() for d in out.diagnostics][:3]
    return out.csharp


class CableTraySectionOperands(unittest.TestCase):
    BODY = {"p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000]}

    def test_positive_section_has_no_invented_upper_bound(self):
        params = {p.name: p for p in spec.OPS["create_cable_tray"].params}
        for name in ("width_mm", "height_mm"):
            self.assertEqual(params[name].min_val, 1)
            self.assertIsNone(params[name].max_val)

        out = compile_program(
            _prog("create_cable_tray", self.BODY,
                  width_mm=5000, height_mm=4000),
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

    def test_zero_section_is_still_a_typed_refusal(self):
        out = compile_program(
            _prog("create_cable_tray", self.BODY,
                  width_mm=0, height_mm=100),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_emitter_sets_and_reads_each_declared_dimension(self):
        cs = _cs("create_cable_tray", self.BODY,
                 width_mm=300, height_mm=100)
        self.assertEqual(cs.count("RBS_CABLETRAY_WIDTH_PARAM"), 2)
        self.assertEqual(cs.count("RBS_CABLETRAY_HEIGHT_PARAM"), 2)
        self.assertIn(".Set(U(300.0))", cs)
        self.assertIn(".Set(U(100.0))", cs)
        self.assertIn("width mismatch", cs)
        self.assertIn("height mismatch", cs)

        absent = _cs("create_cable_tray", self.BODY)
        self.assertNotIn("RBS_CABLETRAY_WIDTH_PARAM", absent)
        self.assertNotIn("RBS_CABLETRAY_HEIGHT_PARAM", absent)

    def test_live_gate_corpus_reaches_sized_section_branch(self):
        from kir.gate_runner import (
            SIZED_CABLE_TRAY_GATE_NAME,
            register_sized_cable_tray_gate,
            sized_cable_tray_branch_reached,
        )

        programs = {}
        register_sized_cable_tray_gate(programs)
        self.assertEqual(set(programs), {SIZED_CABLE_TRAY_GATE_NAME})
        program = programs[SIZED_CABLE_TRAY_GATE_NAME]
        self.assertEqual(program["ops"][0]["id"], "CT2")

        for isolation in ("atomic", "per_op"):
            with self.subTest(isolation=isolation):
                out = compile_program(
                    program,
                    revit_version="2026",
                    snapshot=GROUND_SNAPSHOT,
                    isolation=isolation,
                )
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])
                self.assertTrue(sized_cable_tray_branch_reached(out.csharp))


class TheApiCallIsTheMeasuredOne(unittest.TestCase):
    """Every operation's signature was taken off the reference assemblies
    and compiled on all six versions BEFORE the emitter was written. What
    is frozen here is the call's SHAPE — above all the argument order,
    which is DIFFERENT for a conduit than for a pipe."""

    def test_conduit_takes_the_level_last_like_a_cable_tray(self):
        cs = _cs(*LINEAR_OPS[0])
        self.assertIn("Autodesk.Revit.DB.Electrical.Conduit.Create(doc, "
                      "new ElementId(1400), P(0, 0, 3000), P(6000, 0, 3000), "
                      "__lv_X1.Id)", cs)

    def test_placeholders_take_the_level_before_the_points(self):
        cs_pipe = _cs(*LINEAR_OPS[1])
        self.assertIn("Autodesk.Revit.DB.Plumbing.Pipe.CreatePlaceholder(doc, "
                      "new ElementId(300), new ElementId(200), __lv_X1.Id, "
                      "P(0, 1000, 2800), P(6000, 1000, 2800))", cs_pipe)
        cs_duct = _cs(*LINEAR_OPS[2])
        self.assertIn("Autodesk.Revit.DB.Mechanical.Duct.CreatePlaceholder("
                      "doc, new ElementId(1001), new ElementId(1000), "
                      "__lv_X1.Id, P(0, 2000, 3200), P(6000, 2000, 3200))",
                      cs_duct)

    def test_flex_passes_an_ilist_of_points_not_two_endpoints(self):
        cs = _cs(*FLEX_OPS[0])
        self.assertIn("var __pts_X1 = new List<XYZ>();", cs)
        self.assertEqual(cs.count("__pts_X1.Add(P("), 3)
        self.assertIn("Autodesk.Revit.DB.Mechanical.FlexDuct.Create(doc, "
                      "new ElementId(1001), new ElementId(1401), __lv_X1.Id, "
                      "__pts_X1)", cs)
        self.assertIn("Autodesk.Revit.DB.Plumbing.FlexPipe.Create(doc, ",
                      _cs(*FLEX_OPS[1]))

    def test_the_tangent_overload_is_not_used(self):
        """The overload with tangents exists on all six versions and is
        NOT used: a tangent has no neutral value (a zero vector is
        ignored), so there is nothing to substitute for it besides
        invention."""
        for name, body in FLEX_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertNotIn("StartTangent", cs)
                self.assertNotIn("EndTangent", cs)

    def test_no_version_split_and_no_forbidden_element_id_idiom(self):
        """None of the five diverges across versions — and none touches
        `.IntegerValue`/`.Value` (ElementId has no idiom common to all
        six)."""
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                bodies = {}
                for ver in spec.REVIT_VERSIONS:
                    out = compile_program(_prog(name, body), snapshot=GROUND_SNAPSHOT,
                                          revit_version=ver)
                    self.assertTrue(out.ok, f"{ver}: {[d.as_dict() for d in out.diagnostics][:2]}")
                    self.assertNotIn(".IntegerValue", out.csharp)
                    bodies[ver] = out.csharp
                self.assertEqual(len(set(bodies.values())), 1,
                                 f"{name}: эмиссия разошлась по версиям")


class WitnessReadsTheResult(unittest.TestCase):
    """The MAIN law of the house: the witness reads the RESULT, not the
    call. For each of the five operations it is checked that post
    contains a read of the built element, and that the signature's axis
    matches what was read."""

    def test_linear_ops_read_the_location_curve_revit_returns(self):
        for name, body in LINEAR_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("var __lc = __el_X1.Location as LocationCurve;", cs)
                self.assertIn("__lc.Curve.GetEndPoint(0)", cs)
                self.assertIn("X1: endpoints mismatch (geometry)", cs)

    def test_every_op_reads_the_reference_level_back(self):
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("BuiltInParameter.RBS_START_LEVEL_PARAM", cs)
                self.assertIn("X1: level binding mismatch (topology)", cs)

    def test_every_op_reads_its_type_back_off_the_built_element(self):
        expected = {
            "create_conduit": "conduit type",
            "create_pipe_placeholder": "pipe type",
            "create_duct_placeholder": "duct type",
            "create_flex_duct": "flex duct type",
            "create_flex_pipe": "flex pipe type",
        }
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("var __ty = __el_X1.GetTypeId();", cs)
                self.assertIn(f"X1: {expected[name]} mismatch (semantic)", cs)

    def test_a_placeholder_proves_it_is_a_placeholder(self):
        """The one bit that distinguishes a placeholder from an ordinary
        run. Without it the operation would be a renamed pipe, and the
        word "placeholder" would be a line in the log, not a fact in the
        model."""
        for name, body in LINEAR_OPS[1:]:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("if (!__el_X1.IsPlaceholder)", cs)
                self.assertIn("X1: созданный элемент не заготовка (semantic)", cs)

    def test_conduit_makes_no_placeholder_claim(self):
        self.assertNotIn("IsPlaceholder", _cs(*LINEAR_OPS[0]))

    def test_flex_witness_walks_the_whole_path_not_just_the_ends(self):
        """Checking only the ends would let a DROPPED MIDDLE through: the
        route would drift with a green verdict. So all points and their
        count are compared."""
        cs = _cs(*FLEX_OPS[0])
        self.assertIn("var __pp = __el_X1.Points;", cs)
        self.assertIn("__pp.Count != 3", cs)
        self.assertIn("double[] __ex = new double[] { 0.0, 3000.0, 3000.0, "
                      "1500.0, 3000.0, 2800.0, 3000.0, 3200.0, 2600.0 };", cs)
        self.assertIn("for (int __i = 0; __i < 3; __i++)", cs)
        self.assertIn("X1: flex path points mismatch (geometry)", cs)
        # Two DIAGNOSES kept apart: "a different point count" and "a point
        # is in the wrong place" are different causes, and one word for
        # both would name the consequence instead of the cause.
        self.assertIn("flex path point count mismatch", cs)

    def test_flex_does_not_lean_on_location_curve(self):
        """A flex element's `Location` is a Hermite spline, and its ends
        are DERIVED from the points. What is primary here is `Points`."""
        for name, body in FLEX_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertNotIn("var __lc = __el_X1.Location as LocationCurve;", cs)

    def test_flex_receipt_carries_the_whole_path(self):
        cs = _cs(*FLEX_OPS[0])
        self.assertIn('__rb["path_mm"]', cs)
        self.assertNotIn('__rb["start_mm"]', cs)

    def test_every_geometry_verdict_is_within_the_registry_tolerance(self):
        """The tolerance law: the comparison number comes FROM THE
        REGISTRY. Touch it and the bytes must move (the strong form lives
        in test_tolerance_provenance.py; here it is just that the number
        is indeed that very one)."""
        self.assertEqual(spec.OPS["create_conduit"].tolerances,
                         {"endpoint_mm": 5.0})
        self.assertEqual(spec.OPS["create_flex_duct"].tolerances,
                         {"point_mm": 5.0})
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                self.assertIn("> 5.0", _cs(name, body))


class InvariantsShared(unittest.TestCase):
    def test_one_transaction_and_a_null_guard_per_creation(self):
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertEqual(cs.count("new Transaction"), 1)
                self.assertIn("вернул null", cs)
                self.assertGreaterEqual(cs.count("__t.RollBack()"), 1)

    def test_the_refusal_statement_has_one_owner_in_per_op_too(self):
        """`emit_utils.refuse_stmt` is the sole owner of the refusal text;
        under `per_op` isolation it must become `throw __OpRefuse(` rather
        than stay a rollback of the whole program (otherwise one op's
        refusal wipes out neighbors that are already committed)."""
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                out = compile_program(_prog(name, body), snapshot=GROUND_SNAPSHOT,
                                      bulk=True, isolation="per_op")
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                self.assertIn("throw __OpRefuse(", out.csharp)

    def test_stamp_and_result_row(self):
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                cs = _cs(name, body)
                self.assertIn("ALL_MODEL_INSTANCE_COMMENTS", cs)
                self.assertIn('__results["X1"]', cs)


class NegativeShared(unittest.TestCase):
    def test_no_snapshot_refused(self):
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                out = compile_program(_prog(name, body), snapshot=None)
                self.assertFalse(out.ok)
                self.assertIn("KIR-G103", [d.code for d in out.diagnostics])

    def test_ambiguous_pool_refuses_with_candidates(self):
        """Two types in the pool and an omitted selector are NOT "take the
        first." The candidates travel on the refusal itself, so the next
        turn can proceed by id."""
        cases = (("create_conduit", LINEAR_OPS[0][1], "conduit_types",
                  {"id": 1310, "name": "Короб гибкий"}),
                 ("create_flex_duct", FLEX_OPS[0][1], "flex_duct_types",
                  {"id": 1311, "name": "Гибкий воздуховод овальный"}))
        for name, body, pool, extra in cases:
            with self.subTest(op=name):
                snap = dict(GROUND_SNAPSHOT)
                snap[pool] = list(GROUND_SNAPSHOT[pool]) + [extra]
                out = compile_program(_prog(name, body), snapshot=snap)
                self.assertFalse(out.ok)
                diag = [d for d in out.diagnostics if d.code == "KIR-G102"][0]
                self.assertTrue(diag.as_dict().get("candidates"))

    def test_empty_pool_refuses_rather_than_inventing_a_default(self):
        snap = dict(GROUND_SNAPSHOT)
        snap["conduit_types"] = []
        out = compile_program(_prog(*LINEAR_OPS[0]), snapshot=snap)
        self.assertFalse(out.ok)
        self.assertIn("KIR-G104", [d.code for d in out.diagnostics])

    def test_zero_length_linear_run_refused(self):
        out = compile_program(
            _prog("create_conduit", {"p0_mm": [0, 0, 3000],
                                     "p1_mm": [0, 0, 3000]}),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_flex_path_with_coincident_points_refused_before_emission(self):
        """Autodesk writes about Flex*.Create verbatim: "duplicate points
        don't take into account." So Revit would build a route WITH A
        DIFFERENT NUMBER OF POINTS than requested — that is, a different
        route. The refusal here names the CAUSE; a witness on the path
        would only name the consequence."""
        out = compile_program(
            _prog("create_flex_pipe",
                  {"path": [[0, 0, 3000], [0, 0, 3000], [1000, 0, 3000]]}),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])
        self.assertIn("выбрасывает",
                      " ".join(d.message_ru or "" for d in out.diagnostics))

    def test_flex_path_must_be_three_dimensional(self):
        """A 2D point is NOT silently padded with zero: a flex connection
        almost always runs from the floor to the ceiling, and a
        substituted Z=0 would place the route at absolute zero — exactly
        the class of error that made create_beam require pt_xyz."""
        out = compile_program(
            _prog("create_flex_duct", {"path": [[0, 0], [1000, 0]]}),
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_flex_path_bounds(self):
        for bad in ([[0, 0, 3000]],
                    [[float(k) * 100.0, 0.0, 3000.0] for k in range(65)]):
            with self.subTest(n=len(bad)):
                out = compile_program(
                    _prog("create_flex_pipe", {"path": bad}),
                    snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertIn("KIR-T001", [d.code for d in out.diagnostics])

    def test_missing_required_path_is_typed(self):
        """A missing required `path` is KIR-T001, exactly like a missing
        required `outline` for a floor slab: the parameter-kind branch
        sees `None` and names the TYPE, not a separate "field missing"
        code. What gets frozen is the actual behavior, not the desired
        one."""
        out = compile_program(
            {"ir_version": "1.0", "intent": "без пути",
             "ops": [{"op": "create_flex_duct", "id": "X1", "level": LVL}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])


class PropertyFlexPath(unittest.TestCase):
    """Gate (a): any polyline that is correct by construction gets built,
    and the point count in the witness always equals the count ordered."""

    N = 40
    SEED = 20260809

    def test_random_wellformed_paths_compile(self):
        rng = random.Random(self.SEED)
        for case in range(self.N):
            n = rng.randint(2, 12)
            x = 0.0
            path = []
            for _ in range(n):
                x += rng.randint(500, 4000)
                path.append([x, float(rng.randint(-4000, 4000)),
                             float(rng.randint(2000, 4000))])
            op = rng.choice(["create_flex_duct", "create_flex_pipe"])
            with self.subTest(case=case, n=n, op=op):
                out = compile_program(_prog(op, {"path": path}),
                                      snapshot=GROUND_SNAPSHOT)
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
                self.assertEqual(out.csharp.count("__pts_X1.Add(P("), n)
                self.assertIn(f"__pp.Count != {n}", out.csharp)
                self.assertIn(f"for (int __i = 0; __i < {n}; __i++)", out.csharp)


class GroundingPoolsAreCollectedTheSameWay(unittest.TestCase):
    """A new pool must be assembled by the SAME path as the old ones, and
    must land in the snapshot — otherwise grounding promises a catalog
    nobody reads."""

    def test_the_three_new_pools_reach_the_snapshot_and_the_profile(self):
        from kir.open_model import (GROUND_SNAPSHOT_CS,
                                         required_grounding_pools)
        pools = required_grounding_pools()
        for pool in ("conduit_types", "flex_duct_types", "flex_pipe_types"):
            with self.subTest(pool=pool):
                self.assertIn(pool, pools)
                self.assertIn(f'__AddPool("{pool}"', GROUND_SNAPSHOT_CS)
                self.assertIn(f'"{pool}"', GROUND_SNAPSHOT_CS)

    def test_query_types_can_ask_for_them(self):
        choices = [p for p in spec.OPS["query_types"].params
                   if p.name == "pool"][0].choices
        for pool in ("conduit_types", "flex_duct_types", "flex_pipe_types"):
            with self.subTest(pool=pool):
                self.assertIn(pool, choices)
                out = compile_program(
                    {"ir_version": "1.0", "intent": "каталог",
                     "ops": [{"op": "query_types", "id": "q", "pool": pool}]})
                self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])

    def test_the_collector_tables_do_not_drift(self):
        from kir.compiler import _TYPE_POOL_COLLECTOR_CS
        from kir.open_model import GROUND_SNAPSHOT_CS
        for pool in ("conduit_types", "flex_duct_types", "flex_pipe_types"):
            with self.subTest(pool=pool):
                chain = _TYPE_POOL_COLLECTOR_CS[pool]
                self.assertIn(chain, GROUND_SNAPSHOT_CS)


class SchemaAndVocabulary(unittest.TestCase):
    def test_path3_is_declared_three_dimensional_in_the_schema(self):
        schema = program_schema()
        variants = schema["properties"]["ops"]["items"]["oneOf"]
        flex = next(v for v in variants
                    if v["properties"]["op"].get("const") == "create_flex_duct")
        path = flex["properties"]["path"]
        # The schema may be hoisted into $defs by the deduplicator — in which case this is a $ref.
        if "$ref" in path:
            ref = path["$ref"].split("/")[-1]
            path = schema["$defs"][ref]
        self.assertEqual(path["items"]["minItems"], 3)
        self.assertEqual(path["items"]["maxItems"], 3)
        self.assertEqual(path["minItems"], 2)
        self.assertEqual(path["maxItems"], 64)

    def test_conduit_takes_no_diameter(self):
        """A NAMED ABSENCE, not an oversight: a conduit's trade size is a
        commercial size out of the type table, not a length from a
        continuum. A witness on an arbitrary millimeter value would fail
        on a CORRECTLY built conduit, and there is nothing to refuse at
        compile time — the size table is not in the snapshot."""
        params = {p.name for p in spec.OPS["create_conduit"].params}
        self.assertNotIn("diameter_mm", params)
        self.assertNotIn("RBS_CONDUIT_DIAMETER_PARAM", _cs(*LINEAR_OPS[0]))

    def test_flex_ops_are_not_stackable_but_the_linear_ones_are(self):
        """The `stack` macro carries the Z offset for OPS WITH A PAIR OF
        ENDS. A flex run has no ends — it has a path, and nobody has
        measured a carry for that."""
        from kir import macros
        for name in ("create_conduit", "create_pipe_placeholder",
                     "create_duct_placeholder"):
            self.assertIn(name, macros._STACKABLE)
            self.assertIn(name, macros._Z_SHIFTED)
        for name in ("create_flex_duct", "create_flex_pipe"):
            self.assertNotIn(name, macros._STACKABLE)
            self.assertNotIn(name, macros._Z_SHIFTED)


class WireIsDeliberatelyAbsent(unittest.TestCase):
    """`Electrical.Wire.Create` compiles on all six versions TOGETHER with
    two `null` connectors — meaning the operation could have been
    shipped. It was not shipped, and the decision is pinned here so the
    next session sees not just a green compiler but the reason.

    Briefly (in full — in the header of ops_mep.py): a `Connector` is not
    an `Element`, it has no `ElementId`, and KIR's frozen reference
    dialect CANNOT name it AT ALL; a wire without a circuit builds, draws
    on the plan, and comes up empty in `GetMEPSystems()` — from the
    outside indistinguishable from a completed electrical section;
    vertices are projected onto the view plane, so a wire has no 3D path
    by construction.
    """

    def test_no_wire_op_exists(self):
        self.assertNotIn("create_wire", spec.OPS)

    def test_an_attempt_to_use_it_is_a_typed_refusal_not_a_crash(self):
        out = compile_program(
            {"ir_version": "1.0", "intent": "провод",
             "ops": [{"op": "create_wire", "id": "W1", "level": LVL,
                      "path": [[0, 0, 3000], [1000, 0, 3000]]}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertTrue(out.diagnostics)

    def test_no_dead_wire_pool_was_left_behind(self):
        """A wire-type pool is NOT set up: a pool with no op is a catalog
        nobody queries, and it is also the first step toward an op
        appearing "since the pool already exists"."""
        from kir.open_model import GROUND_SNAPSHOT_CS
        self.assertNotIn("wire_types", GROUND_SNAPSHOT_CS)
        self.assertNotIn("WireType", GROUND_SNAPSHOT_CS)


class ReverseSideIsDeclaredHonestly(unittest.TestCase):
    """The reverse-path manifest is exhaustive over writing ops, so it
    ASSERTS something about each of the five. What is checked here is
    that it asserts exactly what is in the code — not what would be
    pleasant."""

    def test_conduit_is_a_real_direct_inverse(self):
        from kir.decompile import lift
        from kir.reverse_contract import REVERSE_CONTRACTS, ReverseMode
        contract = REVERSE_CONTRACTS["create_conduit"]
        self.assertIs(contract.mode, ReverseMode.DIRECT)
        self.assertEqual(lift._CANDIDATES["OST_Conduit"].op, "create_conduit")
        self.assertIn("_lift_conduit", lift._LIFTERS)

    def test_placeholders_and_flex_never_promise_the_form_they_lose(self):
        """🔴 THE MODE'S NAME USED TO STAND HERE, AND IT ROTTED
        (04.09.2026).

        The test required `CAPTURE_GAP` for four ops. The 04.09 wave
        CLOSED the gap (`e20335e`, `d74a12e`): the placeholder is lifted by
        `is_placeholder`, the flex run by its own points, and the mode
        became `DIRECT`. The red meant not a regression but a COPY OF THE
        TABLE, stale sooner than the table itself: the manifest and the
        exhaustive laws over it live in
        `kir/decompile/tests/test_reverse_contract.py`
        (`test_every_declared_direct_entrypoint_exists_and_names_the_emitted_op`
        traverses ALL entries, without naming a single op). This is a
        remedy the house already prescribed itself on 11.08.2026 for
        exactly this illness: ASK THE AUTHORITY, rather than declaring
        what it holds.

        So the mode's name is no longer here. What remains is what is
        true both BEFORE and AFTER the gap was closed and belongs
        specifically to these four: the placeholder loses its diameter,
        the flex run loses its exact route, so `FORM_EXACT` is
        UNREACHABLE for them NO MATTER WHAT, and the loss must be named.

        Neither of the two checks is done for us by the contract's
        constructor: `__post_init__` (reverse_contract.py:131) forbids
        `DIRECT` only together with the `NONE` guarantee and does not ask
        about `limitation` at all — while it DERIVES the input and
        `direct_same_op_lift`, and checking those from here would mean
        writing something green by construction."""
        from kir.reverse_contract import REVERSE_CONTRACTS, ReverseGuarantee
        for name in ("create_pipe_placeholder", "create_duct_placeholder",
                     "create_flex_duct", "create_flex_pipe"):
            with self.subTest(op=name):
                contract = REVERSE_CONTRACTS[name]
                self.assertIsNot(contract.guarantee,
                                 ReverseGuarantee.FORM_EXACT)
                self.assertTrue(contract.limitation)

    def test_a_conduit_row_lifts_to_the_op(self):
        from kir.decompile.lift import lift_document_detailed
        from kir.decompile.tests.test_lift import _document, make_element
        result = lift_document_detailed(
            _document([make_element("OST_Conduit", 9900, ordinal=0)]))
        self.assertEqual([n["op_name"] for n in result.nodes], ["create_conduit"])
        self.assertIn("conduit_type", result.nodes[0]["params"])
        self.assertNotIn("diameter_mm", result.nodes[0]["params"])


class CertificateCoversTheWave(unittest.TestCase):
    def test_every_new_op_is_certified_and_the_registry_audit_is_clean(self):
        from kir import ground as ground_mod
        from kir.compiler import _parse_and_check
        from kir.translation_cert import audit_registry_coverage, certify_op
        self.assertEqual(audit_registry_coverage(), ())
        for name, body in ALL_OPS:
            with self.subTest(op=name):
                grounded = ground_mod.ground(
                    _parse_and_check(_prog(name, body)), GROUND_SNAPSHOT)
                cert = certify_op(grounded[0], "2024")
                self.assertTrue(cert.proven, cert.gaps)


if __name__ == "__main__":
    unittest.main()
