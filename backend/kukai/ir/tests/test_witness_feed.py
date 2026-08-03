"""Волна A6: witness-корпус — скелет-хэши без геометрии, fail-open запись,
вживление в handle_revit_ir на всех трёх исходах исполнения."""
import asyncio
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_a6_rej.jsonl"))

from kukai.ir import serving, witness_feed  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class SkeletonHash(unittest.TestCase):
    def test_numbers_stripped_structure_kept(self):
        a = {"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
             "p1_mm": [6000, 0], "height_mm": 3000,
             "level": {"by": "element_id", "value": 42}}
        b = dict(a, id="W2", p0_mm=[100, 200], p1_mm=[9000, 200],
                 height_mm=2800)
        b["level"] = {"by": "element_id", "value": 77}
        self.assertEqual(witness_feed.op_skeleton_hash(a),
                         witness_feed.op_skeleton_hash(b))
        c = dict(a)
        c["level"] = {"by": "name", "value": "Этаж 1"}
        self.assertNotEqual(witness_feed.op_skeleton_hash(a),
                            witness_feed.op_skeleton_hash(c))

    def test_malformed_op(self):
        self.assertEqual(witness_feed.op_skeleton_hash("junk"), "malformed")


class Writer(unittest.TestCase):
    def test_planned_execution_is_bound_to_immutable_digest(self):
        from kukai.ir.compiler import plan_program

        planned = plan_program({
            "ir_version": "1.0",
            "ops": [{"op": "query_count", "id": "q", "kind": "wall"}],
        })
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program=planned, family="query", revit_version="2026",
                    ok=True, witness={"readback_ok": True}, duration_ms=1,
                    result_payload={"q": {"count": 1}})

            row = json.loads(open(path, encoding="utf-8").readline())
            self.assertEqual(row["plan_schema"], "kir-planned-program/1")
            self.assertEqual(row["plan_digest"], planned.plan_digest)
            self.assertEqual(row["source_op_count"], 1)

    def test_v2_rows_are_fsynced_and_checksum_chained(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program={"ops": []}, family="query",
                    revit_version="2026", ok=True, witness={"read_only": True},
                    duration_ms=1)
                witness_feed.record_witness(
                    program={"ops": []}, family="query",
                    revit_version="2026", ok=False, witness={"read_only": True},
                    duration_ms=2)
            rows = [json.loads(line) for line in open(path)]
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual([row["v"] for row in rows], [2, 2])
            self.assertEqual(rows[1]["prev_checksum"], rows[0]["checksum"])
            self.assertEqual(witness_feed.verify_witness_chain(path), 2)

            rows[0]["ok"] = False
            with open(path, "w", encoding="utf-8") as sink:
                for row in rows:
                    sink.write(json.dumps(row) + "\n")
            with self.assertRaises(witness_feed.WitnessChainError):
                witness_feed.verify_witness_chain(path)

    def test_legacy_prefix_starts_an_explicit_v2_chain_segment(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with open(path, "w", encoding="utf-8") as sink:
                sink.write('{"v": 1, "ok": true}\n')
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program={"ops": []}, family="query",
                    revit_version="2026", ok=True, witness=None,
                    duration_ms=1)
            rows = [json.loads(line) for line in open(path)]
            self.assertTrue(rows[1]["chain_reset"])
            self.assertEqual(rows[1]["prev_checksum"], "0" * 64)
            self.assertEqual(witness_feed.verify_witness_chain(path), 1)

    def test_acceptance_index_keeps_digests_but_not_model_scope_names(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            evidence = {
                "schema_version": "kir-acceptance-evidence/1",
                "state": "accepted",
                "reason": "measured",
                "evidence_digest": "a" * 64,
                "registration_digest": "b" * 64,
                "registration": {
                    "run_id": "c" * 32,
                    "plan_digest": "d" * 64,
                    "expectation_digest": "e" * 64,
                    "before": [{"level_name": "SECRET PROJECT LEVEL"}],
                },
                "journal": {
                    "durable": True,
                    "run_id": "c" * 32,
                    "sequence": 1,
                    "checksum": "f" * 64,
                },
            }
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program={"ops": []}, family="write",
                    revit_version="2026", ok=True, witness=None,
                    duration_ms=1, acceptance_evidence=evidence)
            row = json.loads(open(path, encoding="utf-8").readline())
            encoded = json.dumps(row["acceptance_evidence"])
            self.assertEqual(
                row["acceptance_evidence"]["evidence_digest"], "a" * 64)
            self.assertTrue(row["acceptance_evidence"]["journal"]["durable"])
            self.assertNotIn("SECRET PROJECT LEVEL", encoded)

    def test_prepared_registration_index_keeps_private_journal_locator(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            registration = {
                "schema_version": "kir-acceptance-journal/1",
                "state": "prepared",
                "run_id": "c" * 32,
                "registration_digest": "d" * 64,
                "expectation_digest": "e" * 64,
                "mutation_expectation_digest": "f" * 64,
                "plan_digest": "a" * 64,
                "revit_version": "2026",
                "journal_checksum": "b" * 64,
                "journal_finalized": True,
                "private_detail": "SECRET TARGET UNIQUE ID",
            }
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program={"ops": []}, family="write",
                    revit_version="2026", ok=False, witness=None,
                    duration_ms=1, acceptance_evidence=registration)

            index = json.loads(
                open(path, encoding="utf-8").readline()
            )["acceptance_evidence"]
            self.assertEqual(index["run_id"], "c" * 32)
            self.assertEqual(index["journal_checksum"], "b" * 64)
            self.assertTrue(index["journal_finalized"])
            self.assertNotIn("SECRET TARGET", json.dumps(index))

    def test_record_and_fail_open(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program={"ops": [{"op": "create_wall", "id": "W",
                                      "p0_mm": [0, 0], "p1_mm": [5, 0]}]},
                    family="write", revit_version="2024", ok=True,
                    witness={"geometry_ok": True}, duration_ms=12.34,
                    result_payload={"W": {"id": "101"}})
            rows = [json.loads(x) for x in open(path)]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertTrue(row["ok"])
            self.assertEqual(row["ops"][0]["op"], "create_wall")
            self.assertEqual(row["op_outcomes"]["W"], "created")
            # координаты не утекли
            self.assertNotIn("5", json.dumps(row["ops"]))
        # fail-open: невозможный путь не роняет
        with mock.patch.dict(os.environ,
                             {"KIR_WITNESS_PATH": "/proc/nope/x.jsonl"}):
            witness_feed.record_witness(
                program={}, family="query", revit_version="2026", ok=False,
                witness=None, duration_ms=1)

    def test_committed_rejection_keeps_effect_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program={"ops": [{"op": "create_wall", "id": "W"}]},
                    family="write", revit_version="2026", ok=False,
                    witness={"geometry_ok": False}, duration_ms=1,
                    diag_code="KIR-W004",
                    violations=["W: geometry (geometry)"],
                    result_payload={"ok": True, "W": {"id": "101"}},
                    outcome={
                        "schema_version": "kir-program-outcome/1",
                        "execution": "committed",
                        "witness": "violated",
                        "acceptance": "not_run",
                        "retry": "forbidden",
                    })

            row = json.loads(open(path, encoding="utf-8").readline())
            self.assertFalse(row["ok"])
            self.assertEqual(row["outcome"]["execution"], "committed")
            self.assertEqual(row["op_outcomes"]["W"], "created")


class HandlerIntegration(unittest.TestCase):
    def setUp(self):
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._dev = mock.patch.object(serving, "_turn_device_id",
                                      return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2024"

    def tearDown(self):
        self._dev.stop()
        os.environ.pop("KUKAI_KIR_TOOL", None)

    def _handle(self, execute, path):
        async def fake_exec(llm, bridge, code, op, timeout_ms):
            return execute(code, op)
        with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}), \
                mock.patch.object(serving, "_run_declarative",
                                  side_effect=fake_exec):
            return _run(serving.handle_revit_ir(
                {"program": {"ir_version": "1.0", "ops": [
                    {"op": "query_count", "id": "q", "kind": "wall"}]}},
                self.llm, bridge_callback=None))

    def test_success_and_failure_both_recorded(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            res = self._handle(
                lambda _c, _o: {"result": {"q": {"count": 3}}}, path)
            self.assertTrue(res["ok"])
            res = self._handle(
                lambda _c, _o: {"ok": False, "message": "bridge failed"}, path)
            self.assertFalse(res["ok"])
            rows = [json.loads(x) for x in open(path)]
            self.assertEqual([r["ok"] for r in rows], [True, False])
            self.assertEqual(rows[1]["diag_code"], "KIR-X999")
            self.assertEqual(rows[0]["family"], "query")
            self.assertGreaterEqual(rows[0]["duration_ms"], 0)

    def test_refusal_not_recorded(self):
        # отказ компилятора (не исполнялось) корпус НЕ пишет — это зона
        # coverage_feed
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                res = _run(serving.handle_revit_ir(
                    {"program": {"ir_version": "1.0", "ops": [
                        {"op": "query_count", "id": "q", "kind": "нет"}]}},
                    self.llm, bridge_callback=None))
            self.assertFalse(res["ok"])
            self.assertFalse(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
