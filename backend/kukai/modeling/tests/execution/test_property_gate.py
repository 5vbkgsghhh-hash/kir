"""PropertyValidationGate (L5.5) unit tests + queue wiring."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import (
    MockBridgeClient, MockCompileClient, MockModelQueryClient,
)
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate, PropertyValidationGate,
)
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.schemas.execution import ExecutionTask
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


def _task(naming=None, required=None, level_name=None) -> ExecutionTask:
    return ExecutionTask(
        task_id="tid_x", csharp_code="// some C#",
        expected_elements=ExpectedElementsSpec(
            category="OST_StructuralColumns", count=1,
            naming_pattern=naming, level_name=level_name,
            required_parameters=required or [],
        ),
        revit_version="2026", transaction_name="Place column",
        max_compile_attempts=1, max_execute_attempts=1,
    )


@pytest.mark.asyncio
async def test_property_gate_passes_when_all_match():
    query = MockModelQueryClient(element_properties={
        9000: {"Mark": "C-1", "Level": "L1", "Comments": "test"},
    })
    outcome = await PropertyValidationGate(query).run(
        task=_task(naming=r"^C-\d+$", required=["Comments"], level_name="L1"),
        element_ids=[9000],
    )
    assert outcome.passed, outcome.error
    assert outcome.name == "L5.5_property"


@pytest.mark.asyncio
async def test_property_gate_fails_on_missing_required():
    query = MockModelQueryClient(element_properties={9000: {"Mark": "C-1"}})
    outcome = await PropertyValidationGate(query).run(
        task=_task(required=["Comments"]), element_ids=[9000],
    )
    assert outcome.passed is False
    assert "Comments" in outcome.error


@pytest.mark.asyncio
async def test_property_gate_fails_on_naming_mismatch():
    query = MockModelQueryClient(element_properties={9000: {"Mark": "X-junk"}})
    outcome = await PropertyValidationGate(query).run(
        task=_task(naming=r"^C-\d+$"), element_ids=[9000],
    )
    assert outcome.passed is False
    assert "Mark" in outcome.error


@pytest.mark.asyncio
async def test_queue_runs_property_gate_after_count_gate():
    """When property_gate supplied, ExecutionResult fails with property_mismatch on bad props."""
    compile_client = MockCompileClient()
    bridge_client = MockBridgeClient(responses=[
        {"success": True, "element_ids": [9000], "duration_ms": 20, "error": None},
    ])
    query = MockModelQueryClient(element_properties={9000: {"Mark": "wrong"}})
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(bridge_client, session_id="dev"),
        count_gate=CountValidationGate(),
        property_gate=PropertyValidationGate(query),
    )
    result = await queue.submit(_task(naming=r"^C-\d+$"))
    assert result.success is False
    assert result.failure_stage == "property_mismatch"
    assert result.l5_count_passed is True
