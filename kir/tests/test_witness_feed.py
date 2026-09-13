"""Wave A6: the witness corpus — skeleton hashes without geometry, fail-open
recording, wired into handle_revit_ir on all three execution outcomes."""
import asyncio
import json
import os
import stat
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_a6_rej.jsonl"))

from kir import serving, witness_feed  # noqa: E402
from kir.tests.gate_fixture import enter_kir_mode
from kir.tests.envtools import подменить_env  # noqa: E402


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
    def test_ground_context_keeps_only_digests_and_authority_flags(self):
        from kir.midend import GroundingContext

        snapshot = {
            "__document_fingerprint": {
                "title": "SECRET MODEL",
                "path_name": r"C:\secret\project.rvt",
                "project_uid": "secret-project-uid",
            },
            "levels": [{"id": 42, "name": "SECRET LEVEL"}],
        }
        context = GroundingContext.from_snapshot(
            snapshot, source="trusted_bridge", trusted_source=True)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                witness_feed.record_witness(
                    program={"ops": []}, family="write",
                    revit_version="2026", ok=False, witness=None,
                    duration_ms=1, ground_context=context)

            row = json.loads(open(path, encoding="utf-8").readline())
            evidence = row["ground_context"]
            self.assertEqual(evidence["context_digest"],
                             context.context_digest)
            self.assertTrue(evidence["execution_bound"])
            self.assertFalse(evidence["authoritative"])
            encoded = json.dumps(evidence)
            self.assertNotIn("SECRET MODEL", encoded)
            self.assertNotIn("SECRET LEVEL", encoded)
            self.assertNotIn("project.rvt", encoded)

    def test_planned_execution_is_bound_to_immutable_digest(self):
        from kir.compiler import plan_program

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
            self.assertEqual(row["plan_schema"], "kir-planned-program/4")
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
                "schema_version": "kir-acceptance-evidence/2",
                "state": "accepted",
                "reason": "measured",
                "ground_selector_resolution_replayed": False,
                "ground_derived_artifacts_verified": True,
                "execution_artifact_binding_digest": "9" * 64,
                "evidence_digest": "a" * 64,
                "registration_digest": "b" * 64,
                "registration": {
                    "run_id": "c" * 32,
                    "plan_digest": "d" * 64,
                    "ground_digest": "1" * 64,
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
            self.assertEqual(
                row["acceptance_evidence"]["ground_digest"], "1" * 64)
            self.assertFalse(row["acceptance_evidence"][
                "ground_selector_resolution_replayed"])
            self.assertTrue(row["acceptance_evidence"][
                "ground_derived_artifacts_verified"])
            self.assertEqual(
                row["acceptance_evidence"][
                    "execution_artifact_binding_digest"],
                "9" * 64,
            )
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
            # the coordinates did not leak
            self.assertNotIn("5", json.dumps(row["ops"]))
        # fail-open: an impossible path does not bring it down
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
        подменить_env(self, "KUKAI_KIR_TOOL", "stage2")
        self._dev = mock.patch.object(serving, "_turn_device_id",
                                      return_value=serving.ADMIN_DEVICE)
        self._dev.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2024"
        # THE GATE'S THIRD CONDITION (08.13): KIR mode is set EXPLICITLY.
        enter_kir_mode(self)

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
        # the corpus does NOT record a compiler refusal (never executed) —
        # that is the coverage_feed's territory
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}):
                res = _run(serving.handle_revit_ir(
                    {"program": {"ir_version": "1.0", "ops": [
                        {"op": "query_count", "id": "q", "kind": "нет"}]}},
                    self.llm, bridge_callback=None))
            self.assertFalse(res["ok"])
            self.assertFalse(os.path.exists(path))


class ПотолокОграничиваетОПЫ_АНеВсёПодряд(unittest.TestCase):
    """🔴 THE TRUNCATION STOOD BEFORE THE FILTER (F-068, 2026-08-30).

    The receipt is FLAT: program-level keys with a dict value (`results`,
    `created_ids`, `postcondition_violations` — three of them today) sit in
    it mixed together with per-row readbacks by `oid`. The ceiling was
    cutting the payload BEFORE the check against the op list, so on a
    program at the legitimate maximum, exactly that many REAL ops silently
    fell out, and the record reported only "truncated N" — a number that
    included the program-level keys and so answered the wrong question.

    The cost is exactly what this file was written for: the corpus that
    `live_op_rates` uses to compute live shares was undercounting executed
    operations.
    """

    #: The ceiling is lowered to show the SAME class cheaply. In production
    #: it is 400,000, and collecting that many ops in a test would mean
    #: measuring the test rig's memory, not the truncation's behavior.
    ПОТОЛОК = 3

    def _запись(self, число_опов, лишние=0):
        ops = [{"op": "create_wall", "id": f"W{i}",
                "p0_mm": [0, 0], "p1_mm": [6000, 0], "height_mm": 3000,
                "level": {"by": "name", "value": "L1"}}
               for i in range(1, число_опов + 1)]
        payload = {"results": {"сводка": 1}, "created_ids": {"всего": 1},
                   "postcondition_violations": {}}
        payload.update({f"W{i}": {"id": 700 + i}
                        for i in range(1, число_опов + 1)})
        payload.update({f"чужой{i}": {"x": i} for i in range(лишние)})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "w.jsonl")
            with mock.patch.dict(os.environ, {"KIR_WITNESS_PATH": path}), \
                    mock.patch.object(witness_feed, "_MAX_OPS_PER_RECORD",
                                      self.ПОТОЛОК):
                witness_feed.record_witness(
                    program={"ir_version": "1.0", "intent": "t", "ops": ops},
                    family="authoring", revit_version="2026", ok=True,
                    witness=None, duration_ms=1.0, result_payload=payload)
            with open(path, encoding="utf-8") as fh:
                return json.loads(fh.read().strip().split("\n")[-1])

    def test_a_real_op_is_not_evicted_by_program_keys(self):
        """One real op at a ceiling of THREE. Before the fix, three
        program-level keys crowded it out, and it landed in neither the
        outcomes nor the facts."""
        r = self._запись(1)
        self.assertIn("W1", r["op_outcomes"])
        self.assertIsNone(r.get("op_outcomes_truncated"),
                          "усечение объявлено там, где опов меньше потолка")

    def test_the_pseudo_ops_stay_in_the_record(self):
        """A NARROWNESS CONTROL. Label continuity is a named property of the
        corpus, and `live_op_rates` reads it across the whole history. The
        fix changes ORDER, not composition: discarding the program-level
        keys would cure one thing and break another."""
        r = self._запись(1)
        for key in ("results", "created_ids", "postcondition_violations"):
            with self.subTest(key=key):
                self.assertIn(key, r["op_outcomes"])

    def test_truncation_counts_OPS_and_names_them(self):
        """"How many payload keys over the ceiling" and "how many OPS were
        lost" are different numbers. The first was printed, and read as the
        second."""
        r = self._запись(5)
        свои = sorted(k for k in r["op_outcomes"] if k.startswith("W"))
        self.assertEqual(свои, ["W1", "W2", "W3"])
        self.assertEqual(r["op_outcomes_truncated"], 2)
        # Canon forbids silent truncation: only HOW MANY was ever printed.
        self.assertEqual(r["op_outcomes_truncated_ids"], ["W4", "W5"])

    def test_the_record_stays_bounded_when_the_payload_is_odd(self):
        """🔴 THE RECORD'S BOUNDARY IS NOT LOST. Before, ONE ceiling held it;
        after splitting one's own from foreign, a payload with a hundred
        dict-valued non-op keys would inflate `op_outcomes` without limit."""
        r = self._запись(5, лишние=200)
        не_опы = [k for k in r["op_outcomes"] if not k.startswith("W")]
        self.assertEqual(len(не_опы),
                         witness_feed._MAX_FOREIGN_KEYS_PER_RECORD,
                         "запись потеряла верхнюю границу")
        # 🔴 PROGRAM-LEVEL KEYS ARE ALSO "FOREIGN" AND ALSO TAKE UP SLOTS —
        # this came out from a run, not from reading: the test first
        # expected 64 outsiders and got 61, because three program-level keys
        # sit FIRST in the payload and hit the limit sooner. Order is what
        # saves label continuity here: the very thing the pseudo-ops were
        # kept for survives the truncation of the foreign ones.
        for key in ("results", "created_ids", "postcondition_violations"):
            with self.subTest(key=key):
                self.assertIn(key, r["op_outcomes"])
        свои = sorted(k for k in r["op_outcomes"] if k.startswith("W"))
        self.assertEqual(свои, ["W1", "W2", "W3"],
                         "чужие ключи снова вытеснили настоящие опы")


if __name__ == "__main__":
    unittest.main()


class НосительЗадачиДоезжаетДоСвидетеля(unittest.TestCase):
    """🔴 THE CONSTITUTION'S MAIN METRIC COUNTS WITHIN THE BOUNDS OF A SINGLE
    TASK, AND THERE WAS NO TASK IN THE FEED (measured 2026-09-04).

    The `kir.instruments.decision_changes` instrument first came together
    when rights to three journals were revoked — and it refused to
    announce a result: "distinguishable tasks in the feed: 0." The task's
    carrier is the DOCUMENT, and the number of witness rows with `doc_key`
    was ZERO out of 4268: the field did not exist at all.

    The quantity sat in the caller's (`serving`) scope — exactly the same
    one-argument distance as the turn identity that arrived on 08.26.
    """

    def _строка(self, **kw):
        import json, tempfile, pathlib as _pl
        from kir import witness_feed as wf
        with tempfile.TemporaryDirectory() as d:
            путь = _pl.Path(d) / "kir_witness.jsonl"
            прежний = wf._feed_path
            wf._feed_path = lambda: путь                      # noqa: SLF001
            try:
                wf.record_witness(
                    program={"ops": [{"op": "create_level", "id": "l1"}]},
                    family="write", revit_version="2026", ok=True,
                    witness=None, duration_ms=1.0, **kw)
            finally:
                wf._feed_path = прежний
            текст = путь.read_text(encoding="utf-8").strip()
            return json.loads(текст) if текст else {}

    def test_документ_едет_полем(self) -> None:
        строка = self._строка(doc_key="Проект1")
        self.assertEqual(строка.get("doc_key"), "Проект1")

    def test_без_документа_поля_нет_вовсе(self) -> None:
        """An empty string in the corpus would read as "there was a task and
        it did not give its name," and that is a DIFFERENT statement — the
        same law as for turn identity and for `author_digest`."""
        строка = self._строка()
        self.assertNotIn("doc_key", строка)

    def test_служба_подаёт_его_во_всех_вызовах_свидетеля(self) -> None:
        """One call out of three with no carrier is a hole invisible to the eye.

        The subject is taken by an AST TRAVERSAL, not by text: the first
        edition cut the source on `)` and caught the very first nested
        parenthesis — an instrument about a different subject, caught by its
        own run.
        """
        import ast
        import pathlib as _pl
        дерево = ast.parse(_pl.Path(__file__).resolve().parents[1]
                           .joinpath("serving.py").read_text(encoding="utf-8"))
        вызовы = [n for n in ast.walk(дерево)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "record_witness"]
        self.assertEqual(len(вызовы), 3, "число вызовов свидетеля изменилось")
        без = [n.lineno for n in вызовы
               if "doc_key" not in {k.arg for k in n.keywords if k.arg}]
        self.assertEqual(без, [],
                         f"вызовы свидетеля без носителя задачи, строки: {без}")
