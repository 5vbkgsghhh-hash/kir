"""v1.1 fix-batch regressions — «инцидент = вечный тест» (slab saga,
FULL_BUILDING_TEST.md 2026-07-17). Three находки, each pinned forever:
 №1 ok:true over result.error:true (the runner believed 5 phantom floors);
 №2 raw Revit runtime messages untyped (no KIR-X translation);
 №3 witness triple absent from tool results.
Plus the static-law cases (VISION §5а): duplicate closing point and
hole-touching-outline must die at the T stage, not in Revit."""
import asyncio
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

OUTLINE = [[0, 0], [16000, 0], [16000, 10000], [0, 10000]]
LVL = {"by": "name", "value": "Этаж 1"}


def _run(coro):
    # Python 3.12 no longer guarantees an implicit current loop, and another
    # test's asyncio.run() intentionally closes the loop it created.  Keep
    # this helper isolated and order-independent.
    return asyncio.run(coro)


class Nahodka1OkOverError(unittest.TestCase):
    """The exact live shape: run_declarative returns error inside result —
    the handler must NOT wrap it in ok:true ever again."""

    def setUp(self):
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._dev = mock.patch.object(serving, "_turn_device_id",
                                      return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2026"
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

    def _handle(self, exec_result):
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": OUTLINE,
             "level": LVL}]}
        acceptance = PassingAcceptanceBridge(program)

        async def fake_exec(llm, bridge, code, op, timeout_ms):
            return acceptance.dispatch(
                lambda _code, stage: (
                    {"result": GROUND_SNAPSHOT}
                    if stage == "ground_snapshot" else exec_result),
                code,
                op,
            )
        with mock.patch.object(serving, "_run_declarative", side_effect=fake_exec):
            return _run(serving.handle_revit_ir(
                {"program": program},
                self.llm, bridge_callback=None))

    def test_live_shape_short_curve(self):
        res = self._handle({"error": True,
                            "message": "Curve length is too small for Revit's "
                                       "tolerance (ShortCurveTolerance)"})
        self.assertFalse(res["ok"], "находка №1: внешний ok не смеет врать")
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X001")
        self.assertIn("ShortCurveTolerance", res["diagnostics"][0]["detail"])
        # A generic bridge error contains no transaction outcome.  The
        # serving layer must not fabricate rollback certainty from the error
        # text alone; structured KIR-X003/X004 responses carry that evidence.
        self.assertIsNone(res["rolled_back"])
        self.assertEqual(res["outcome"]["execution"], "unconfirmed")
        self.assertEqual(res["outcome"]["retry"], "verify_first")
        self.assertIsNone(res["handoff"])
        self.assertFalse(res["err"]["retryable"])

    def test_nested_error_layer(self):
        res = self._handle({"result": {"error": True,
                                       "message": "curve loops intersect"}})
        self.assertFalse(res["ok"])
        self.assertEqual(res["diagnostics"][0]["code"], "KIR-X002")

    def test_postconditions_rollback_translated(self):
        res = self._handle({"error": "postconditions_violated",
                            "violations": ["F1: bbox extents mismatch (geometry)",
                                           "F1: level binding mismatch (topology)"]})
        self.assertFalse(res["ok"])
        d = res["diagnostics"][0]
        self.assertEqual(d["code"], "KIR-X004")
        w = res["witness"]
        self.assertFalse(w["geometry_ok"])
        self.assertFalse(w["topology_ok"])
        self.assertTrue(w["semantic_ok"])

    def test_stale_and_duplicate_and_unclassified(self):
        for payload, want in (
                ({"error": "stale_or_failed", "op_id": "F1",
                  "message": "тип перекрытия не найден"}, "KIR-X003"),
                ({"error": True, "message": "Name is already in use"}, "KIR-X006"),
                ({"error": True, "message": "неведомая фигня"}, "KIR-X999")):
            res = self._handle(payload)
            self.assertFalse(res["ok"])
            self.assertEqual(res["diagnostics"][0]["code"], want, payload)

    def test_success_carries_witness_triple(self):
        res = self._handle({"result": {"ok": True, "F1": {"id": "1001"}}})
        self.assertTrue(res["ok"])
        self.assertEqual(res["witness"],
                         {"geometry_ok": True, "semantic_ok": True,
                          "topology_ok": True})

    def test_query_witness_read_only(self):
        async def fake_exec(llm, bridge, code, op, timeout_ms):
            return {"result": {"q": {"count": 5}}}
        with mock.patch.object(serving, "_run_declarative", side_effect=fake_exec):
            res = _run(serving.handle_revit_ir(
                {"program": {"ir_version": "1.0", "ops": [
                    {"op": "query_count", "id": "q", "kind": "wall"}]}},
                self.llm, bridge_callback=None))
        self.assertTrue(res["ok"])
        self.assertEqual(res["witness"], {"read_only": True})


class StaticGeometryLaw(unittest.TestCase):
    """Slab-saga iterations 1-2, now T-stage refusals/normalization."""

    def test_iter1_closing_duplicate_normalized(self):
        closed = OUTLINE + [OUTLINE[0]]        # the exact iter-1 shape
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": closed, "level": LVL}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        # normalized to 4 unique points -> exactly 4 outline segments
        self.assertEqual(out.csharp.count("__ol_F1.Append"), 4)

    def test_mid_ring_duplicate_refused(self):
        bad = [[0, 0], [8000, 0], [8000, 0.5], [8000, 6000], [0, 6000]]
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": bad, "level": LVL}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])

    def test_self_intersection_refused(self):
        """Positive-area crossing quad (a zero-area bowtie dies earlier as
        T002 degenerate — also correct, covered implicitly)."""
        crossing = [[0, 0], [8000, 0], [2000, 4000], [6000, 4000]]
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": crossing, "level": LVL}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T003", [d.code for d in out.diagnostics])
        bowtie = [[0, 0], [8000, 6000], [8000, 0], [0, 6000]]
        out2 = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": bowtie, "level": LVL}]},
            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out2.ok)          # zero-area -> T002, still typed

    def test_nonadjacent_touch_and_collinear_overlap_are_intersections(self):
        from kukai.ir.geom import _seg_intersect
        self.assertTrue(_seg_intersect([0, 0], [10, 0], [5, 0], [15, 0]))
        touching = [[0, 0], [8000, 0], [8000, 6000], [4000, 0], [0, 6000]]
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": touching,
             "level": LVL}]}, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T003", [d.code for d in out.diagnostics])

    def test_iter2_hole_touching_boundary_refused(self):
        touching = [[0, 0], [3000, 0], [3000, 6000], [0, 6000]]  # shares x=0 edge
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": OUTLINE,
             "holes": [touching], "level": LVL}]}, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-T003"][0]
        self.assertIn("касание", d.message_ru)

    def test_iter2_human_fix_compiles(self):
        inset = [[200, 2000], [3000, 2000], [3000, 6000], [200, 6000]]  # x=200 fix
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": OUTLINE,
             "holes": [inset], "level": LVL}]}, snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])

    def test_hole_outside_and_overlapping_refused(self):
        outside = [[20000, 2000], [22000, 2000], [22000, 4000], [20000, 4000]]
        out = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": OUTLINE,
             "holes": [outside], "level": LVL}]}, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        h1 = [[2000, 2000], [6000, 2000], [6000, 6000], [2000, 6000]]
        h2 = [[4000, 4000], [8000, 4000], [8000, 8000], [4000, 8000]]
        out2 = compile_program({"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "F1", "outline": OUTLINE,
             "holes": [h1, h2], "level": LVL}]}, snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out2.ok)
        self.assertIn("KIR-T003", [d.code for d in out2.diagnostics])


if __name__ == "__main__":
    unittest.main()
