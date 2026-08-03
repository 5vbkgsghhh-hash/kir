"""Tests for TemplatedExecutor."""
from __future__ import annotations
import pathlib
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate
)
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.resolver import (
    FamilyResolutionStatus,
    ParameterScope,
    ResolverOutput,
)
from kukai.modeling.templated.executor import TemplatedExecutor
from kukai.modeling.templated.registry import TemplateRegistry


def _templates_dir() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    return here.parents[2] / "templates"


def _good_resolver_output() -> ResolverOutput:
    return ResolverOutput(
        family_resolution=FamilyResolutionStatus.RESOLVED,
        family_symbol_id=8821,
        candidate_symbols=[],
        parameter_map={"mark": ("ALL_MODEL_MARK", ParameterScope.BUILT_IN)},
        placement_point=XYZ(x=6000.0, y=6000.0, z=0.0),
        level_id=1042,
        top_level_id=1043,
        revit_version="2026",
        notes=[],
    )


def _make_queue():
    return ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="sess"),
        count_gate=CountValidationGate(),
    )


@pytest.mark.asyncio
async def test_executes_column_template_happy_path():
    registry = TemplateRegistry(_templates_dir())
    queue = _make_queue()
    ex = TemplatedExecutor(registry, queue)

    result = await ex.place_element(
        template_name="structural_column_at_point",
        resolver_output=_good_resolver_output(),
        task_id="t_col_2B_L1",
        mark="C-2B-L1",
        extra_args={},
    )
    assert result.success is True
    assert len(result.element_ids) == 1


@pytest.mark.asyncio
async def test_refuses_unresolved_family():
    registry = TemplateRegistry(_templates_dir())
    queue = _make_queue()
    ex = TemplatedExecutor(registry, queue)

    bad = _good_resolver_output().model_copy(update={
        "family_resolution": FamilyResolutionStatus.AMBIGUOUS,
        "family_symbol_id": None,
    })
    with pytest.raises(ValueError, match="family not resolved"):
        await ex.place_element(
            template_name="structural_column_at_point",
            resolver_output=bad,
            task_id="t_bad",
            mark="C-X",
            extra_args={},
        )


@pytest.mark.asyncio
async def test_passes_count_validation_against_manifest():
    """Manifest declares expected_count=1; queue's count gate gets that value."""
    registry = TemplateRegistry(_templates_dir())
    bridge = MockBridgeClient(responses=[
        {"success": True, "element_ids": [9001, 9002], "duration_ms": 50},  # 2 ids returned
    ])
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(bridge, session_id="sess"),
        count_gate=CountValidationGate(),
    )
    ex = TemplatedExecutor(registry, queue)

    result = await ex.place_element(
        template_name="structural_column_at_point",
        resolver_output=_good_resolver_output(),
        task_id="t_count_check",
        mark="C-Y",
        extra_args={},
    )
    # manifest.expected_count is 1, bridge returned 2 -> count gate fails
    assert result.success is False
    assert result.failure_stage == "count_mismatch"


@pytest.mark.asyncio
async def test_extra_args_passed_to_template():
    """extra_args can supply optional template params (e.g. override transaction_name)."""
    registry = TemplateRegistry(_templates_dir())
    compile_client = MockCompileClient()
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="sess"),
        count_gate=CountValidationGate(),
    )
    ex = TemplatedExecutor(registry, queue)

    await ex.place_element(
        template_name="structural_column_at_point",
        resolver_output=_good_resolver_output(),
        task_id="t_x",
        mark="C-X",
        extra_args={"transaction_name": "Custom Tx Name"},
    )
    # The compile client received the rendered code; verify our custom tx name appears
    assert any("Custom Tx Name" in code for code in compile_client.calls)


@pytest.mark.asyncio
async def test_default_transaction_name_includes_mark():
    """If extra_args doesn't override, default transaction_name is built from mark."""
    registry = TemplateRegistry(_templates_dir())
    compile_client = MockCompileClient()
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="sess"),
        count_gate=CountValidationGate(),
    )
    ex = TemplatedExecutor(registry, queue)

    await ex.place_element(
        template_name="structural_column_at_point",
        resolver_output=_good_resolver_output(),
        task_id="t_y",
        mark="C-9C-L3",
        extra_args={},
    )
    # Default transaction_name should contain the mark "C-9C-L3"
    assert any("C-9C-L3" in code for code in compile_client.calls)
