"""Execution, witness and acceptance must never collapse into one boolean."""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_outcome_queue.jsonl"),
)

from kukai.ir import serving  # noqa: E402
from kukai.ir.outcome import (  # noqa: E402
    AcceptanceState,
    ExecutionState,
    ProgramOutcome,
    RetrySafety,
    WitnessState,
    execution_unconfirmed,
    query_accepted,
    write_committed,
)
from kukai.ir.tests.acceptance_fakes import PassingAcceptanceBridge  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402
from kukai.ir.tests.gate_fixture import enter_kir_mode


WRITE_PROGRAM = {"ir_version": "1.0", "ops": [{
    "op": "create_wall",
    "id": "W1",
    "p0_mm": [0, 0],
    "p1_mm": [6000, 0],
    "level": {"by": "element_id", "value": 42},
}]}


class ClosedOutcomeAlgebra(unittest.TestCase):
    def test_committed_rejection_forbids_retry(self) -> None:
        outcome = write_committed(witness=WitnessState.VIOLATED)

        self.assertEqual(outcome.execution, ExecutionState.COMMITTED)
        self.assertEqual(outcome.acceptance, AcceptanceState.NOT_RUN)
        self.assertEqual(outcome.retry_safety, RetrySafety.FORBIDDEN)

    def test_unconfirmed_execution_requires_readback(self) -> None:
        outcome = execution_unconfirmed()

        self.assertEqual(outcome.retry_safety, RetrySafety.VERIFY_FIRST)
        self.assertEqual(outcome.witness, WitnessState.INCOMPLETE)

    def test_read_only_result_has_no_mutation_acceptance(self) -> None:
        outcome = query_accepted()

        self.assertEqual(outcome.execution, ExecutionState.READ_COMPLETED)
        self.assertEqual(
            outcome.acceptance, AcceptanceState.NOT_APPLICABLE)

    def test_impossible_accepted_rollback_is_unrepresentable(self) -> None:
        with self.assertRaises(ValueError):
            ProgramOutcome(
                ExecutionState.ROLLED_BACK,
                WitnessState.SATISFIED,
                AcceptanceState.ACCEPTED,
            )


class ServingOutcomeContract(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["KUKAI_KIR_TOOL"] = "stage2"
        self._device = mock.patch.object(
            serving, "_turn_device_id", return_value=serving.ADMIN_DEVICE)
        self._device.start()
        self.llm = mock.Mock()
        self.llm._revit_version = "2024"
        self._acceptance_dir = tempfile.TemporaryDirectory()
        self._prev_acceptance_dir = os.environ.get(
            "KIR_ACCEPTANCE_EVIDENCE_DIR")
        os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = self._acceptance_dir.name
        # ТРЕТЬЕ УСЛОВИЕ ГЕЙТА (13.08): режим КИР ставится ЯВНО.
        enter_kir_mode(self)

    def tearDown(self) -> None:
        self._device.stop()
        os.environ.pop("KUKAI_KIR_TOOL", None)
        if self._prev_acceptance_dir is None:
            os.environ.pop("KIR_ACCEPTANCE_EVIDENCE_DIR", None)
        else:
            os.environ["KIR_ACCEPTANCE_EVIDENCE_DIR"] = (
                self._prev_acceptance_dir)
        self._acceptance_dir.cleanup()

    def _write(self, payload: dict) -> dict:
        acceptance = PassingAcceptanceBridge(WRITE_PROGRAM)

        async def execute(_llm, _bridge, _code, op, _timeout_ms):
            if op == "ground_snapshot":
                result = {"result": GROUND_SNAPSHOT}
            else:
                result = {"result": payload}
            return acceptance.dispatch(
                lambda _code, _op: result, _code, op)

        with mock.patch.object(
                serving, "_run_declarative", side_effect=execute):
            return asyncio.run(serving.handle_revit_ir(
                {"program": WRITE_PROGRAM}, self.llm, None))

    def test_committed_postcondition_violation_is_not_success(self) -> None:
        result = self._write({
            "ok": True,
            "W1": {"id": "9001"},
            "postcondition_violations": [
                "W1: endpoints mismatch (geometry)",
            ],
        })

        self.assertFalse(result["ok"])
        self.assertFalse(result["rolled_back"])
        self.assertIsNone(result["handoff"])
        self.assertEqual(result["diagnostics"][0]["code"], "KIR-W004")
        self.assertEqual(result["outcome"], {
            "schema_version": "kir-program-outcome/1",
            "execution": "committed",
            "witness": "violated",
            "acceptance": "inconclusive",
            "retry": "forbidden",
        })
        self.assertFalse(result["err"]["retryable"])

    def test_confirmed_commit_with_incomplete_readback_is_not_unknown_mutation(self) -> None:
        result = self._write({"ok": True})

        self.assertFalse(result["ok"])
        self.assertFalse(result["rolled_back"])
        self.assertEqual(result["outcome"]["execution"], "committed")
        self.assertEqual(result["outcome"]["witness"], "incomplete")
        self.assertEqual(result["outcome"]["acceptance"], "inconclusive")
        self.assertEqual(result["outcome"]["retry"], "forbidden")
        self.assertFalse(result["err"]["retryable"])


if __name__ == "__main__":
    unittest.main()
