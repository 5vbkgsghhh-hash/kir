"""Tests for individual gates L3, L4, L5."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate
)
from kukai.modeling.schemas.execution import ExecutionTask
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


def _make_task(code: str = "// placeholder", count: int = 1) -> ExecutionTask:
    return ExecutionTask(
        task_id="t_test",
        csharp_code=code,
        expected_elements=ExpectedElementsSpec(
            category="OST_StructuralColumns", count=count
        ),
        revit_version="2026",
        transaction_name="Test",
        max_compile_attempts=3,
        max_execute_attempts=3,
    )


class TestCompileGate:
    @pytest.mark.asyncio
    async def test_pass(self):
        gate = CompileGate(MockCompileClient())
        outcome, result = await gate.run(_make_task())
        assert outcome.passed is True
        assert outcome.name == "L3_compile"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_fail(self):
        client = MockCompileClient(
            responses=[{"success": False, "error": "CS1002"}]
        )
        gate = CompileGate(client)
        outcome, result = await gate.run(_make_task())
        assert outcome.passed is False
        assert result.success is False
        assert "CS1002" in (result.error or "")

    @pytest.mark.asyncio
    async def test_compile_gate_forwards_revit_version_to_client(self):
        """Regression: CompileGate must thread task.revit_version to the compile call."""
        from kukai.modeling.schemas.execution import ExecutionTask
        from kukai.modeling.schemas.tasks import ExpectedElementsSpec

        class _CapturingClient:
            def __init__(self):
                self.calls: list[tuple[str, str]] = []

            async def compile(self, csharp_code, revit_version="default"):
                self.calls.append((csharp_code[:20], revit_version))
                from kukai.modeling.schemas.execution import CompileResult
                return CompileResult(success=True, code=csharp_code, assembly_id="asm")

        client = _CapturingClient()
        gate = CompileGate(client)
        task = ExecutionTask(
            task_id="t1tver01",
            csharp_code="// code __result__ = new int[] { };",
            expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
            revit_version="2024",
            transaction_name="Place column",
            max_compile_attempts=1,
            max_execute_attempts=1,
        )
        outcome, result = await gate.run(task)
        assert client.calls == [("// code __result__ =", "2024")], (
            f"CompileGate must forward task.revit_version. Got: {client.calls}"
        )


class TestExecuteGate:
    @pytest.mark.asyncio
    async def test_pass(self):
        gate = ExecuteGate(MockBridgeClient(), session_id="sess")
        outcome, payload = await gate.run(_make_task())
        assert outcome.passed is True
        assert payload["success"] is True
        assert len(payload["element_ids"]) == 1

    @pytest.mark.asyncio
    async def test_fail(self):
        bridge = MockBridgeClient(
            responses=[{"success": False, "error": "Revit hang", "element_ids": [], "duration_ms": 50}]
        )
        gate = ExecuteGate(bridge, session_id="sess")
        outcome, payload = await gate.run(_make_task())
        assert outcome.passed is False
        assert payload["success"] is False


class TestGateExceptionSafety:
    """Wave 6A B#2 — any exception from the compile / bridge client must
    surface as a failure GateOutcome, not propagate out and abort the phase.
    """

    @pytest.mark.tier0
    @pytest.mark.asyncio
    async def test_compile_gate_returns_failure_on_client_exception(self):
        class _RaisingCompileClient:
            async def compile(self, *args, **kwargs):
                raise RuntimeError("connection refused")

        gate = CompileGate(_RaisingCompileClient())
        outcome, result = await gate.run(_make_task())

        assert outcome.passed is False
        assert outcome.name == "L3_compile"
        assert outcome.error is not None
        assert "RuntimeError" in outcome.error
        assert "connection refused" in outcome.error
        assert result.success is False
        assert len(result.errors) == 1
        assert result.errors[0].code == "GATE_EXCEPTION"

    @pytest.mark.tier0
    @pytest.mark.asyncio
    async def test_execute_gate_returns_failure_on_client_exception(self):
        class _RaisingBridgeClient:
            async def execute_code(self, *args, **kwargs):
                raise RuntimeError("bridge websocket dropped")

        gate = ExecuteGate(_RaisingBridgeClient(), session_id="sess")
        outcome, payload = await gate.run(_make_task())

        assert outcome.passed is False
        assert outcome.name == "L4_execute"
        assert outcome.error is not None
        assert "RuntimeError" in outcome.error
        assert "bridge websocket dropped" in outcome.error
        assert payload["success"] is False
        assert payload["element_ids"] == []
        assert "bridge websocket dropped" in payload["error"]


class TestCountValidationGate:
    def test_pass(self):
        gate = CountValidationGate()
        outcome = gate.run(_make_task(count=2), element_ids=[8001, 8002])
        assert outcome.passed is True

    def test_fail_too_few(self):
        gate = CountValidationGate()
        outcome = gate.run(_make_task(count=3), element_ids=[8001])
        assert outcome.passed is False
        assert "expected 3" in (outcome.error or "")

    def test_fail_too_many(self):
        gate = CountValidationGate()
        outcome = gate.run(_make_task(count=1), element_ids=[8001, 8002])
        assert outcome.passed is False
