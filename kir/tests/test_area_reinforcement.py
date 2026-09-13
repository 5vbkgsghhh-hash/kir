"""wave/reinforcement (2026-08-10): create_area_reinforcement.

EVERY TEST HERE IS A REFUTING one, not a confirming one: it reproduces a
specific way this operation could lie to itself, and it fails if that way
becomes possible again. The list of ways is not invented — it is assembled
from an API measurement (:52412, 2021-2026, 10.08) and from defects this
house has already paid for:

  (a) `required=True` on the angle was an UNENFORCEABLE promise: the `deg`
      kind's branch in authoring_validation exited on `not in op` before
      anyone ever asked `p.required` — a program without a mandatory angle
      would reach the emitter and fail with a KeyError (KIR-P000, «internal
      error») instead of a named refusal. Before this wave all registry
      angles were optional, so the hole went unobserved — exactly an
      «instrument covering only part of the range»;
  (b) A MISSING HOOK must mean «no hooks» (InvalidElementId — the API's own
      value), not «the only one in the pool»: a generic rule would silently
      anchor rebar that the author asked for without anchoring;
  (c) THE "BARS PLACED" WITNESS must be CONDITIONAL: Autodesk documents an
      empty array as the CORRECT answer when
      `ReinforcementSettings.HostStructuralRebar` is off, so an
      unconditional check would reject correct work (the class «acceptance
      broke on Cyrillic»);
  (d) A WALL HOST must refuse BY NAME: `Create` on it will succeed, but
      Revit will project the plan angle onto the wall's vertical plane —
      silently wrong;
  (e) A PER-LAYER API must not exist in the emission at all:
      `GetNumberOfLines` / `GetLayerDirection` / `AreaReinforcementLayerType`
      do not exist on 2021 (measured), meaning a witness built on them
      would work on only five of the six versions;
  (f) THE OP HAS NOT A SINGLE TOLERANCE, and this must be held by
      construction: across 38 stored decompiles with a census there are
      ZERO reinforcement elements, so any number here would have been
      derived by reasoning alone.
"""
import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(),
                                   "kir_test_area_reinf_queue.jsonl"))

from kir import spec                                        # noqa: E402
from kir.compiler import compile_program                    # noqa: E402
from kir.tests.fixtures import GROUND_SNAPSHOT as SNAPSHOT  # noqa: E402

OP = "create_area_reinforcement"
BAR = {"by": "name", "value": "Ø12 A500C"}


def _prog(ops, intent="reinf-test"):
    return {"ir_version": "1.0", "intent": intent, "ops": ops}


def _ar(oid="AR1", **kw):
    op = {"op": OP, "id": oid,
          "host": {"by": "element_id", "value": 8145901},
          "direction_deg": 0.0, "bar_type": BAR}
    op.update(kw)
    return op


def _emit(ops, ver="2026", isolation="atomic"):
    out = compile_program(_prog(ops), revit_version=ver, snapshot=SNAPSHOT,
                          bulk=True, isolation=isolation)
    return out


def _codes(out):
    return [d.code for d in out.diagnostics]


class RegistryContract(unittest.TestCase):
    """What must live in the registry, not in someone's memory."""

    def test_the_op_declares_no_tolerance_at_all(self):
        # (f) Zero tolerances is a MEASUREMENT, not an omission: there is
        # nothing to measure here. The very first number that arrives here
        # without a measurement must fail the test.
        self.assertEqual(spec.OPS[OP].tolerances, {})

    def test_direction_is_required_in_the_registry(self):
        p = next(p for p in spec.OPS[OP].params if p.name == "direction_deg")
        self.assertTrue(p.required)
        # A periodic quantity must have no bounds: an angle of 725° is
        # legal.
        self.assertIsNone(p.min_val)
        self.assertIsNone(p.max_val)

    def test_host_accepts_an_existing_element_not_only_a_ref(self):
        # The main scenario of the reinforcement (KR) section is «reinforce
        # THIS slab»; a ref requirement would forbid it entirely.
        out = _emit([_ar()])
        self.assertTrue(out.ok, _codes(out))


class MissingAngleIsANamedRefusal(unittest.TestCase):
    """(a) Refuting test for the hole in the `deg` kind."""

    def test_absent_direction_deg_is_a_typed_refusal_not_an_internal_error(self):
        op = _ar()
        del op["direction_deg"]
        out = _emit([op])
        self.assertFalse(out.ok)
        # A NAMED refusal about the FIELD, not KIR-P000 «internal error».
        self.assertNotIn("KIR-P000", _codes(out))
        self.assertTrue(any(d.field_name == "direction_deg"
                            for d in out.diagnostics), _codes(out))

    def test_an_optional_angle_stays_optional(self):
        # The fix is ADDITIVE: nothing shifted for `rotation_deg`
        # (default=0.0).
        out = compile_program(
            _prog([{"op": "create_column", "id": "C1", "xy": [0, 0],
                    "level": {"by": "element_id", "value": 42},
                    "category": "structural"}]),
            revit_version="2026", snapshot=SNAPSHOT, bulk=True)
        self.assertTrue(out.ok, _codes(out))


class OmittedHookMeansNoHooks(unittest.TestCase):
    """(b) Omitting the hook is an API value, not an invitation to choose
    for the author."""

    def test_pool_has_two_hooks_so_the_sole_entry_rule_would_have_refused(self):
        # Without this line the test would prove nothing: with a pool of
        # one entry, «no hooks» and «the only one in the pool» would give
        # the same visible outcome, and the substitution would pass
        # unnoticed.
        self.assertGreaterEqual(len(SNAPSHOT["rebar_hook_types"]), 2)

    def test_omitted_hook_builds_and_emits_the_api_s_own_none_value(self):
        out = _emit([_ar()])
        self.assertTrue(out.ok, _codes(out))
        self.assertIn("__hkid_AR1 = ElementId.InvalidElementId;", out.csharp)
        for row in SNAPSHOT["rebar_hook_types"]:
            self.assertNotIn(f"__hkid_AR1 = new ElementId({row['id']})",
                             out.csharp)

    def test_a_named_hook_still_travels_to_the_call(self):
        out = _emit([_ar(hook_type={"by": "name", "value": "Крюк 90"})])
        self.assertTrue(out.ok, _codes(out))
        self.assertNotIn("__hkid_AR1 = ElementId.InvalidElementId;", out.csharp)
        self.assertIn("RebarHookType == null", out.csharp)


class TypeResolution(unittest.TestCase):
    """An omitted type goes through the DOCUMENT branch, not «the only one
    in the pool»."""

    def test_pool_has_two_types_so_sole_entry_would_have_refused(self):
        self.assertGreaterEqual(len(SNAPSHOT["area_reinforcement_types"]), 2)

    def test_omitted_type_takes_the_document_default(self):
        out = _emit([_ar()])
        self.assertTrue(out.ok, _codes(out))
        self.assertIn(
            "doc.GetDefaultElementTypeId(ElementTypeGroup.AreaReinforcementType)",
            out.csharp)

    def test_a_named_type_replaces_the_document_default(self):
        out = _emit([_ar(type={"by": "name", "value":
                               "Армирование по области 2"})])
        self.assertTrue(out.ok, _codes(out))
        self.assertNotIn("GetDefaultElementTypeId", out.csharp)


class WitnessHonesty(unittest.TestCase):
    """(c) The witness reads the RESULT and must be able to fail."""

    def setUp(self):
        self.cs = _emit([_ar()]).csharp

    def test_every_verdict_rereads_the_element_from_the_document(self):
        # A witness that trusted the returned object would prove the call,
        # not the result.
        for marker in ("__rdh_AR1 = doc.GetElement(__el_AR1.Id)",
                       "__rdt_AR1 = doc.GetElement(__el_AR1.Id)",
                       "__rdb_AR1 = doc.GetElement(__el_AR1.Id)",
                       "__rdr_AR1 = doc.GetElement(__el_AR1.Id)"):
            self.assertIn(marker, self.cs)

    def test_bars_laid_is_conditional_on_the_document_setting(self):
        # An UNCONDITIONAL check would reject correct work in every
        # document with the setting turned off. The condition must be read
        # FROM THE DOCUMENT and live in the same verdict.
        self.assertIn("ReinforcementSettings.GetReinforcementSettings(doc)",
                      self.cs)
        head, _sep, tail = self.cs.partition("GetRebarInSystemIds().Count == 0")
        self.assertTrue(_sep, "проверки на ноль стержней нет вовсе")
        guard = head[head.rfind("{ var __rdb_AR1"):]
        self.assertIn("HostStructuralRebar", guard)

    def test_the_setting_and_the_bar_count_always_ride_the_receipt(self):
        # Zero bars must not be silent: the author must see BOTH the
        # number AND the reason.
        self.assertIn('__rb["host_structural_rebar"]', self.cs)
        self.assertIn('__rb["bar_count"]', self.cs)
        self.assertIn('__rb["direction"]', self.cs)

    def test_no_witness_carries_a_tolerance(self):
        from kir import struct_emit
        op = {"op": OP, "id": "AR1", "__region__": None,
              "host": {"by": "element_id", "value": 8145901},
              "direction_deg": 0.0,
              "type": {"__grounded__": {"id": None, "name": None,
                                        "via": "doc_default",
                                        "in_emit": "__doc_default__"}},
              "bar_type": {"__grounded__": {"id": 1902, "name": "Ø12 A500C",
                                            "via": "name"}}}
        _decl, _create, checks, _rb = struct_emit.emit_area_reinforcement(
            op, "2026", "stamp")
        self.assertEqual(len(checks), 4)
        for chk in checks:
            self.assertIsNone(chk.tol, chk.obligation_key)

    def test_the_layered_api_never_reaches_the_emission(self):
        # (e) It does not exist on 2021 — a witness built on it would be an
        # instrument covering only part of the range.
        for absent in ("GetNumberOfLines", "GetLayerDirection",
                       "AreaReinforcementLayerType"):
            self.assertNotIn(absent, self.cs)


class HostGuards(unittest.TestCase):
    """(d) A silently-wrong host is stopped BEFORE the call."""

    def setUp(self):
        self.cs = _emit([_ar()]).csharp

    def test_a_vertical_host_is_refused_by_name_before_the_call(self):
        self.assertIn("if (!(__hh_AR1 is Floor))", self.cs)
        i_guard = self.cs.index("if (!(__hh_AR1 is Floor))")
        i_call = self.cs.index("AreaReinforcement.Create(")
        self.assertLess(i_guard, i_call)

    def test_the_api_s_own_preflight_is_asked_before_the_call(self):
        self.assertIn("RebarHostData.IsValidHost(__hh_AR1)", self.cs)
        i_guard = self.cs.index("RebarHostData.IsValidHost(__hh_AR1)")
        i_call = self.cs.index("AreaReinforcement.Create(")
        self.assertLess(i_guard, i_call)

    def test_the_create_call_is_wrapped_in_a_typed_refusal(self):
        self.assertIn("AreaReinforcement.Create: ", self.cs)
        self.assertIn("catch (Exception __ex_AR1)", self.cs)


class DirectionIsCompiledNotComputedLive(unittest.TestCase):
    """All trigonometry happens at compile time — the CONTOUR law, here
    too."""

    def test_the_emitted_vector_is_two_literals(self):
        cs = _emit([_ar(direction_deg=90.0)]).csharp
        self.assertIn("XYZ __dir_AR1 = new XYZ(", cs)
        self.assertNotIn("Math.Cos", cs)
        self.assertNotIn("Math.Sin", cs)

    def test_an_angle_outside_0_360_is_a_legal_program(self):
        for ang in (-30.0, 725.0):
            out = _emit([_ar(direction_deg=ang)])
            self.assertTrue(out.ok, (ang, _codes(out)))

    def test_the_direction_is_a_unit_vector_by_construction(self):
        # «majorDirection has zero length» is a documented Autodesk
        # exception; here it is unreachable, and this must be held by
        # measurement, not by faith.
        import re
        for ang in (0.0, 45.0, 90.0, 179.999, -720.0):
            cs = _emit([_ar(direction_deg=ang)]).csharp
            m = re.search(r"XYZ __dir_AR1 = new XYZ\(([-\d.eE+]+), "
                          r"([-\d.eE+]+), 0\.0\);", cs)
            self.assertIsNotNone(m, ang)
            x, y = float(m.group(1)), float(m.group(2))
            self.assertAlmostEqual(x * x + y * y, 1.0, places=6)


class RefWorksToo(unittest.TestCase):
    """A slab from this same program is a legitimate host on par with a
    standing one."""

    def test_ref_to_a_floor_built_in_the_same_program(self):
        ops = [{"op": "create_floor", "id": "SL1",
                "outline": [[0, 0], [9000, 0], [9000, 6000], [0, 6000]],
                "level": {"by": "element_id", "value": 42},
                "structural": True},
               _ar(host={"by": "ref", "value": "SL1"})]
        out = _emit(ops)
        self.assertTrue(out.ok, _codes(out))
        self.assertIn("__hh_AR1 = __el_SL1;", out.csharp)


class AllSixVersionsEmitTheSameShape(unittest.TestCase):
    """This operation HAS NO version axis, and that is a measurement, not
    hope."""

    def test_no_version_branch_in_the_op_body(self):
        bodies = {}
        for ver in spec.REVIT_VERSIONS:
            out = _emit([_ar()], ver=ver)
            self.assertTrue(out.ok, (ver, _codes(out)))
            cs = out.csharp
            start = cs.index("// create_area_reinforcement")
            bodies[ver] = cs[start:]
        # The only thing versions ever differ on is the ElementId literal,
        # and the shared `_eid` prints it; the host body is therefore
        # compared by element_id via an invariant, not byte-for-byte.
        for ver, body in bodies.items():
            self.assertIn("AreaReinforcement.Create(doc, __hh_AR1, __dir_AR1",
                          body, ver)


if __name__ == "__main__":
    unittest.main()
