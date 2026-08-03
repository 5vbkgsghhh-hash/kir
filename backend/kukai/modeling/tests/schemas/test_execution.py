"""Tests for execution-layer schemas."""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.execution import (
    CompileError,
    CompileResult,
    ExecutionResult,
    ExecutionTask,
    GateOutcome,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


class TestExecutionTask:
    def test_creates_with_required(self):
        task = ExecutionTask(
            task_id="t_001",
            csharp_code="// hello",
            expected_elements=ExpectedElementsSpec(
                category="OST_StructuralColumns", count=1
            ),
            revit_version="2026",
            transaction_name="Place column",
            max_compile_attempts=3,
            max_execute_attempts=3,
        )
        assert task.task_id == "t_001"
        assert task.max_compile_attempts == 3

    def test_rejects_empty_code(self):
        with pytest.raises(ValidationError):
            ExecutionTask(
                task_id="t",
                csharp_code="",
                expected_elements=ExpectedElementsSpec(
                    category="OST_StructuralColumns", count=1
                ),
                revit_version="2026",
                transaction_name="X",
                max_compile_attempts=3,
                max_execute_attempts=3,
            )


class TestCompileResult:
    def test_success(self):
        r = CompileResult(success=True, code="// compiled", assembly_id="asm_1")
        assert r.success is True
        assert r.error is None

    def test_failure_with_error(self):
        r = CompileResult(
            success=False,
            errors=[CompileError(code="CS1002", message="; expected at line 5", line=5, column=1)],
        )
        assert r.success is False
        assert r.assembly_id is None
        assert r.error == "; expected at line 5"  # back-compat @property
        assert r.errors[0].code == "CS1002"
        assert r.errors[0].line == 5


class TestExecutionResult:
    def test_success_path(self):
        r = ExecutionResult(
            task_id="t_001",
            success=True,
            element_ids=[8001, 8002],
            l3_compile_passed=True,
            l4_execute_passed=True,
            l5_count_passed=True,
            compile_duration_ms=120,
            execute_duration_ms=850,
        )
        assert r.element_ids == [8001, 8002]

    def test_failure_path(self):
        r = ExecutionResult(
            task_id="t_001",
            success=False,
            failure_stage="compile",
            error_message="CS1002",
            error_signature="compile_CS1002",
            l3_compile_passed=False,
            l4_execute_passed=False,
            l5_count_passed=False,
            compile_duration_ms=120,
            execute_duration_ms=0,
        )
        assert r.failure_stage == "compile"
        assert r.element_ids == []


class TestGateOutcome:
    def test_pass(self):
        g = GateOutcome(name="L3_compile", passed=True, duration_ms=120)
        assert g.passed is True
        assert g.error is None

    def test_fail(self):
        g = GateOutcome(
            name="L4_execute", passed=False, duration_ms=50, error="Revit not responding"
        )
        assert g.error == "Revit not responding"
