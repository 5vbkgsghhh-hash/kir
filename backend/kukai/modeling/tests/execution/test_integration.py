"""End-to-end integration test for bridge + execution layers.

No Revit, no real services — all via mocks. Verifies that a realistic
multi-task sequence flows through the queue and produces consistent
ExecutionResult outputs.
"""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate
)
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.schemas.execution import ExecutionTask
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


def _make_task(task_id: str, code: str = "// ok", count: int = 1) -> ExecutionTask:
    return ExecutionTask(
        task_id=task_id,
        csharp_code=code,
        expected_elements=ExpectedElementsSpec(
            category="OST_StructuralColumns", count=count
        ),
        revit_version="2026",
        transaction_name=f"Tx {task_id}",
        max_compile_attempts=3,
        max_execute_attempts=3,
    )


@pytest.mark.asyncio
async def test_three_task_sequence_all_pass():
    compile_client = MockCompileClient()
    bridge_client = MockBridgeClient()
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(bridge_client, session_id="dev"),
        count_gate=CountValidationGate(),
    )

    tasks = [_make_task(f"t{i}") for i in range(3)]
    results = [await queue.submit(t) for t in tasks]

    assert all(r.success for r in results)
    assert all(len(r.element_ids) == 1 for r in results)
    # All compile + bridge calls were recorded
    assert len(compile_client.calls) == 3
    assert len(bridge_client.calls) == 3


@pytest.mark.asyncio
async def test_mixed_success_and_failure():
    """Test that one failed task doesn't poison the queue for the next."""
    compile_client = MockCompileClient(responses=[
        {"success": True, "assembly_id": "a1"},        # t0 compile ok
        {"success": False, "error": "CS1002 t1"},      # t1 compile fails
        {"success": True, "assembly_id": "a2"},        # t2 compile ok
    ])
    bridge_client = MockBridgeClient(responses=[
        {"success": True, "element_ids": [9001], "duration_ms": 50},  # t0 execute ok
        # t1 never executes (compile failed)
        {"success": True, "element_ids": [9002], "duration_ms": 50},  # t2 execute ok
    ])
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(bridge_client, session_id="dev"),
        count_gate=CountValidationGate(),
    )

    r0 = await queue.submit(_make_task("t0"))
    r1 = await queue.submit(_make_task("t1"))
    r2 = await queue.submit(_make_task("t2"))

    assert r0.success is True
    assert r1.success is False
    assert r1.failure_stage == "compile"
    assert r2.success is True
    # Bridge was called for t0 and t2 only
    assert len(bridge_client.calls) == 2


@pytest.mark.asyncio
async def test_error_signatures_distinct():
    """Different failures produce different signatures for CascadeDetector."""
    compile_client = MockCompileClient(responses=[
        {"success": False, "error": "CS1002"},
        {"success": False, "error": "CS1525"},
    ])
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="dev"),
        count_gate=CountValidationGate(),
    )

    r1 = await queue.submit(_make_task("t1"))
    r2 = await queue.submit(_make_task("t2"))
    assert r1.error_signature != r2.error_signature
