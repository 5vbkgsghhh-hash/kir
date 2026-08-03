"""Serving-layer tests: stage-2 device gate, schema injection, handler
outcomes — including the coordinator-required «handoff не ломает turn» proof
and the structural-filter live-case regression."""
import asyncio
import copy
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir import serving  # noqa: E402
from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class StructuralFilterLiveCase(unittest.TestCase):
    """2026-07-16 prod case: «выдели несущие стены» burned ~5 min of repair
    (invented STATIC_WALL_BASE_IMAGE / Wall.Structural). One filter now."""

    def test_structural_walls_compile(self):
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_list", "id": "sw", "kind": "wall",
             "where": {"structural": True}, "fields": ["id", "name", "type_name"]}]})
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("WALL_STRUCTURAL_SIGNIFICANT", out.csharp)
        self.assertNotIn("STATIC_WALL_BASE_IMAGE", out.csharp)

    def test_structural_on_nonwall_refused(self):
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "door",
             "where": {"structural": True}}]})
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-T001"][0]
        self.assertEqual(d.expected, ["wall"])

    def test_structural_value_typed(self):
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall",
             "where": {"structural": "да"}}]})
        self.assertFalse(out.ok)

    def test_snapshot_collects_every_grounding_pool_used_by_struct_and_contour(self):
        cs = serving._SNAPSHOT_CS
        self.assertIn('__AddPool("beam_types"', cs)
        self.assertIn("OST_StructuralFraming", cs)
        self.assertIn('__AddPool("foundation_symbols"', cs)
        self.assertIn("OST_StructuralFoundation", cs)
        self.assertIn('__snap["grids"]', cs)
        self.assertIn('__r["p0_mm"]', cs)
        self.assertIn('__r["p1_mm"]', cs)
        # audit F7: a capped pool must be MARKED, never silently partial
        self.assertIn('__snap[__pool + "__truncated"]', cs)
        self.assertIn('__snap["grids__truncated"]', cs)

    def test_snapshot_family_pool_is_universal_and_canonically_identified(self):
        cs = serving._SNAPSHOT_CS
        family_line = next(
            line for line in cs.splitlines()
            if '__AddPool("family_symbols"' in line)
        self.assertIn("OfClass(typeof(FamilySymbol))", family_line)
        self.assertNotIn("OfCategory", family_line)
        self.assertIn("int.MaxValue", family_line)
        self.assertIn('__r["category"]', cs)
        self.assertIn('__r["family_name"]', cs)
        self.assertIn('__r["type_name"]', cs)
        self.assertNotIn("IntegerValue", cs)

    def test_snapshot_parameter_projection_is_bounded_and_program_specific(self):
        program = {"ops": [{
            "duct_type": {
                "by": "name",
                "value": "По умолчанию",
                "disambiguate_by": {"param": "Диаметр", "value": "100 мм"},
            },
        }]}
        cs = serving._snapshot_cs(program)
        self.assertIn('new string[] { "Диаметр" }', cs)
        self.assertIn("__e.GetParameters(__paramName)", cs)
        self.assertIn("__matches.Count != 1", cs)
        self.assertEqual(
            serving._snapshot_parameter_names(program), ["Диаметр"])


class DeviceGate(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("KUKAI_KIR_TOOL", None)

    def test_flag_off_and_shadow_hidden(self):
        for v in (None, "off", "shadow"):
            if v is None:
                os.environ.pop("KUKAI_KIR_TOOL", None)
            else:
                os.environ["KUKAI_KIR_TOOL"] = v
            self.assertFalse(serving.revit_ir_enabled())

    def test_stage2_wrong_device_hidden(self):
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        with mock.patch.object(serving, "_turn_device_id", return_value="deadbeef"):
            self.assertFalse(serving.revit_ir_enabled())
        with mock.patch.object(serving, "_turn_device_id", return_value=None):
            self.assertFalse(serving.revit_ir_enabled())

    def test_stage2_admin_device_visible(self):
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        with mock.patch.object(serving, "_turn_device_id",
                               return_value=serving.ADMIN_DEVICE):
            self.assertTrue(serving.revit_ir_enabled())

    def test_schema_injection_idempotent(self):
        tools = []
        serving.inject_revit_ir_schema(tools)
        serving.inject_revit_ir_schema(tools)
        self.assertEqual(len(tools), 1)
        fn = tools[0]["function"]
        self.assertEqual(fn["name"], "revit_ir")
        self.assertIn("program", fn["parameters"]["properties"])


class HandlerOutcomes(unittest.TestCase):
    def setUp(self):
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._dev = mock.patch.object(serving, "_turn_device_id",
                                      return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2024"
        self._acceptance_dir = tempfile.TemporaryDirectory()
        self._prev_acceptance_dir = os.environ.get(
            "KIR_ACCEPTANCE_EVIDENCE_DIR")
        os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._acceptance_dir.name

    def tearDown(self):
        self._dev.stop()
        os.environ.pop("KUKAI_KIR_TOOL", None)
        if self._prev_acceptance_dir is None:
            os.environ.pop("KIR_ACCEPTANCE_EVIDENCE_DIR", None)
        else:
            os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = (
                self._prev_acceptance_dir)
        self._acceptance_dir.cleanup()

    def _handle(self, program, execute=None):
        acceptance = PassingAcceptanceBridge(program)

        async def fake_exec(llm, bridge, code, op, timeout_ms):
            if execute:
                return acceptance.dispatch(execute, code, op)
            return {"result": {"pdf": {"count": 2}}}
        with mock.patch.object(serving, "_run_declarative", side_effect=fake_exec):
            return _run(serving.handle_revit_ir(
                {"program": program}, self.llm, bridge_callback=None))

    def test_query_ok_path(self):
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "pdf", "kind": "pdf_underlay"}]})
        self.assertTrue(res["ok"])
        self.assertTrue(res["kir"])

    def test_outer_ok_false_is_runtime_failure(self):
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]},
            execute=lambda _code, _op: {"ok": False, "message": "bridge failed"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X999")
        self.assertIsNone(res["rolled_back"])

    def test_nested_ok_false_is_runtime_failure(self):
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]},
            execute=lambda _code, _op: {
                "ok": True, "result": {"ok": False, "message": "inner failed"}})
        self.assertFalse(res["ok"])
        self.assertIn("inner failed", res["diagnostics"][0]["detail"])

    def test_timeout_never_claims_rollback(self):
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]},
            execute=lambda _code, _op: {"state": "timeout_unconfirmed"})
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X007")
        self.assertIsNone(res["rolled_back"])
        self.assertIsNone(res["handoff"])

    def test_structured_write_refusal_proves_rollback(self):
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"error": "postconditions_violated",
                               "violations": ["W1: endpoints (geometry)"]}}

        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0],
             "level": {"by": "element_id", "value": 42}}]}, execute=execute)
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X004")
        self.assertTrue(res["rolled_back"])

    def test_handoff_is_normal_result_not_exception(self):
        """«handoff не ломает turn»: out-of-coverage -> typed dict, no raise."""
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "OST_ImportInstances"}]})
        self.assertFalse(res["ok"])
        self.assertTrue(res["refused"])
        self.assertEqual(res["handoff"], "recipe-path")
        self.assertTrue(res["diagnostics"])

    def test_write_program_fetches_snapshot(self):
        calls = []
        def execute(code, op):
            calls.append(op)
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"ok": True, "W1": {"id": "9001"}}}
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Этаж 1"}}]}, execute=execute)
        self.assertTrue(res["ok"], res)
        self.assertEqual(calls, ["ground_snapshot", "write"])

    def test_write_always_guards_document_with_exact_preflight_off(self):
        calls = []

        def execute(code, op):
            calls.append((op, code))
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"ok": True, "W1": {"id": "9001"}}}

        result = self._handle({
            "ir_version": "1.0",
            "ops": [{
                "op": "create_wall",
                "id": "W1",
                "p0_mm": [0, 0],
                "p1_mm": [6000, 0],
                "level": {"by": "element_id", "value": 42},
            }],
        }, execute=execute)

        self.assertTrue(result["ok"], result)
        emitted = calls[1][1]
        self.assertIn("active document fingerprint changed", emitted)
        self.assertIn("KIR Test Model", emitted)
        self.assertLess(
            emitted.index("active document fingerprint changed"),
            emitted.index("Wall.Create"),
        )
        # Exact element identity remains independently gated.
        self.assertNotIn("kir-model-binding-guard/1", emitted)

    def test_write_refuses_snapshot_without_document_identity(self):
        calls = []
        snapshot = copy.deepcopy(GROUND_SNAPSHOT)
        snapshot.pop("__document_fingerprint")

        def execute(_code, op):
            calls.append(op)
            if op == "ground_snapshot":
                return {"result": snapshot}
            self.fail("write must not execute without document identity")

        result = self._handle({
            "ir_version": "1.0",
            "ops": [{
                "op": "create_wall",
                "id": "W1",
                "p0_mm": [0, 0],
                "p1_mm": [6000, 0],
                "level": {"by": "element_id", "value": 42},
            }],
        }, execute=execute)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ground")
        self.assertEqual(calls, ["ground_snapshot"])

    def test_live_exact_snapshot_guards_document_and_pinned_identity(self):
        # Преflight открытой модели — opt-in (умеет отказать в записи на
        # усечённом снапшоте большой модели и живьём не проверялся), поэтому
        # тест сам включает флаг: он проверяет ГЕЙТОВАННОЕ поведение.
        os.environ["KUKAI_IR_OPEN_MODEL_PREFLIGHT"] = "1"
        self.addCleanup(os.environ.pop, "KUKAI_IR_OPEN_MODEL_PREFLIGHT", None)
        calls = []
        snapshot = copy.deepcopy(GROUND_SNAPSHOT)
        level = next(row for row in snapshot["levels"] if row["id"] == 42)
        level.update({
            "unique_id": "level-42",
            "version_guid": "0" * 32,
        })
        snapshot["levels__total"] = len(snapshot["levels"])
        snapshot["__document_fingerprint"] = {
            "title": "Tower COPY",
            "path_name": r"C:\models\tower-copy.rvt",
            "project_uid": "tower-project-uid",
        }

        def execute(code, op):
            calls.append((op, code))
            if op == "ground_snapshot":
                return {"result": snapshot}
            return {"result": {"ok": True, "W1": {"id": "9001"}}}

        result = self._handle({
            "ir_version": "1.0",
            "ops": [{
                "op": "create_wall",
                "id": "W1",
                "p0_mm": [0, 0],
                "p1_mm": [6000, 0],
                "level": {"by": "name", "value": "Этаж 1"},
            }],
        }, execute=execute)

        self.assertTrue(result["ok"], result)
        emitted = calls[1][1]
        self.assertIn("active document fingerprint changed", emitted)
        self.assertIn("kir-model-binding-guard/1", emitted)
        self.assertIn("level-42", emitted)
        self.assertLess(
            emitted.index("active document fingerprint changed"),
            emitted.index("Wall.Create"),
        )
        self.assertLess(
            emitted.index("kir-model-binding-guard/1"),
            emitted.index("Wall.Create"),
        )

    def test_disambiguate_by_parameter_is_fetched_and_resolved_same_round_trip(self):
        calls = []
        snap = dict(GROUND_SNAPSHOT)
        snap["duct_types"] = [
            {"id": 1000, "name": "По умолчанию",
             "params": {"Диаметр": {"raw": 0.328, "display": "100 мм"}}},
            {"id": 1001, "name": "По умолчанию",
             "params": {"Диаметр": {"raw": 0.656, "display": "200 мм"}}},
        ]

        def execute(code, op):
            calls.append((op, code))
            if op == "ground_snapshot":
                return {"result": snap}
            return {"result": {"ok": True, "D1": {"id": "9001"}}}

        selector = {
            "by": "name",
            "value": "По умолчанию",
            "disambiguate_by": {"param": "Диаметр", "value": "100 мм"},
        }
        res = self._handle({"ir_version": "1.0", "ops": [{
            "op": "create_duct", "id": "D1",
            "p0_mm": [0, 0, 3000], "p1_mm": [6000, 0, 3000],
            "level": {"by": "element_id", "value": 42},
            "duct_type": selector,
        }]}, execute=execute)
        self.assertTrue(res["ok"], res)
        self.assertEqual([op for op, _ in calls], ["ground_snapshot", "write"])
        self.assertIn('new string[] { "Диаметр" }', calls[0][1])
        self.assertIn("new ElementId(1000)", calls[1][1])

    def test_incomplete_write_readback_is_unknown_not_success(self):
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"ok": True}}

        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0],
             "level": {"by": "element_id", "value": 42}}]}, execute=execute)
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X008")
        # The exact inner ok=true is the emitter's post-Commit marker.  What
        # is incomplete is the witness, not the transaction state.
        self.assertFalse(res["rolled_back"])
        self.assertEqual(res["outcome"]["execution"], "committed")
        self.assertEqual(res["outcome"]["witness"], "incomplete")
        self.assertIsNone(res["handoff"])

    def test_network_readback_identifies_by_segment_ids(self):
        """A graph op creates N elements, so it has no single `id`.

        Found live 2026-07-27: with the CONNECT system-merge blocker gone,
        `route_pipe_system` reached commit for the first time — and serving
        then refused its own successful write with
        `KIR-X008: result keys without id/deleted_id: RP`. The contract exists
        to prove WHICH elements the program produced; for a network that
        evidence is `segment_ids`, and inventing a singular `id` would
        misreport an N-element result as one element.
        """
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"ok": True, "PS": {
                "segments": 2,
                "segment_ids": ["21201900", "21201903"],
                "mep_system_ids": ["21201906"],
                "one_system": True,
            }}}

        res = self._handle({"ir_version": "1.0", "ops": [{
            "op": "create_pipe_system", "id": "PS",
            "nodes": [{"id": "a", "xyz_mm": [0, 0, 2700]},
                      {"id": "b", "xyz_mm": [4000, 0, 2700]},
                      {"id": "c", "xyz_mm": [8000, 0, 2700]}],
            "segments": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
            "level": {"by": "element_id", "value": 42},
        }]}, execute=execute)
        self.assertTrue(res["ok"], res)
        self.assertNotIn("diagnostics", res)

    def test_network_readback_without_any_ids_is_still_refused(self):
        """The widening must not blunt the contract: an EMPTY segment_ids
        list proves nothing and must stay an unknown outcome."""
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"ok": True, "PS": {"segments": 2,
                                                  "segment_ids": []}}}

        res = self._handle({"ir_version": "1.0", "ops": [{
            "op": "create_pipe_system", "id": "PS",
            "nodes": [{"id": "a", "xyz_mm": [0, 0, 2700]},
                      {"id": "b", "xyz_mm": [4000, 0, 2700]}],
            "segments": [{"from": "a", "to": "b"}],
            "level": {"by": "element_id", "value": 42},
        }]}, execute=execute)
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X008")

    def test_move_identity_and_independent_location_read_are_accepted(self):
        """move_elements moves N existing elements — there is no single `id`.

        Found live 2026-07-28 (проба П9, ЭОМ, Revit 2026): the op moved a
        CONNECTED cable-tray pair and serving refused its own successful
        write with `KIR-X008: result keys without id/deleted_id: MV9`. The
        identity evidence of a move is the non-empty `moved_ids` list —
        the exact precedent of `segment_ids` for graph ops: the contract
        is widened, not blunted."""
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"ok": True, "MV9": {
                "moved_ids": ["1290216", "1290218"], "count": 2}}}

        res = self._handle({"ir_version": "1.0", "ops": [{
            "op": "move_elements", "id": "MV9",
            "targets": [{"by": "element_id", "value": 1290216},
                        {"by": "element_id", "value": 1290218}],
            "delta_mm": [0, 0, 500]}]}, execute=execute)
        # The result identity contract accepts moved_ids and the separate
        # before/after location probe proves the exact registered delta.
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["outcome"]["execution"], "committed")
        self.assertEqual(res["outcome"]["witness"], "satisfied")
        self.assertEqual(res["outcome"]["acceptance"], "accepted")
        self.assertEqual(res["outcome"]["retry"], "forbidden")

    def test_move_readback_with_empty_moved_ids_is_still_refused(self):
        """An empty moved_ids list proves nothing — stays refused."""
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"result": GROUND_SNAPSHOT}
            return {"result": {"ok": True, "MV9": {"moved_ids": [],
                                                   "count": 0}}}

        res = self._handle({"ir_version": "1.0", "ops": [{
            "op": "move_elements", "id": "MV9",
            "targets": [{"by": "element_id", "value": 1290216}],
            "delta_mm": [0, 0, 500]}]}, execute=execute)
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X008")

    def test_incomplete_query_readback_is_unknown_not_success(self):
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]},
            execute=lambda _code, _op: {"result": {}})
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X008")
        self.assertEqual(res["witness"], {"read_only": True})

    def test_non_object_bridge_payload_is_unknown_not_success(self):
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "query_count", "id": "q", "kind": "wall"}]},
            execute=lambda _code, _op: None)
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X008")

    def test_snapshot_failure_typed(self):
        def execute(code, op):
            raise RuntimeError("bridge down")
        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0], "p1_mm": [6000, 0],
             "level": {"by": "name", "value": "Этаж 1"}}]}, execute=execute)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "ground")
        self.assertEqual(res["handoff"], "recipe-path")

    def test_snapshot_error_cannot_hide_behind_levels_key(self):
        def execute(_code, op):
            if op == "ground_snapshot":
                return {"ok": False, "levels": [], "message": "snapshot failed"}
            self.fail("write must not execute after a failed snapshot")

        res = self._handle({"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0],
             "level": {"by": "element_id", "value": 42}}]}, execute=execute)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "ground")

    def test_internal_crash_absorbed(self):
        with mock.patch("kukai.ir.compiler.compile_program",
                        side_effect=MemoryError("boom")):
            res = _run(serving.handle_revit_ir(
                {"program": {"ir_version": "1.0", "ops": []}},
                self.llm, bridge_callback=None))
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "internal")

    def test_gate_recheck_at_dispatch(self):
        self._dev.stop()
        with mock.patch.object(serving, "_turn_device_id", return_value="other"):
            res = _run(serving.handle_revit_ir(
                {"program": {"ir_version": "1.0", "ops": []}},
                self.llm, bridge_callback=None))
        self._dev = mock.patch.object(serving, "_turn_device_id",
                                      return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "gate")


if __name__ == "__main__":
    unittest.main()
