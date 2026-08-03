"""Phase 4 Task 3 — ExecutionResult exposes l6_geometry_passed flag."""
from __future__ import annotations

from kukai.modeling.schemas.execution import ExecutionResult


def test_execution_result_l6_geometry_passed_defaults_false():
    r = ExecutionResult(task_id="t1", success=True, compile_duration_ms=0, execute_duration_ms=0)
    assert hasattr(r, "l6_geometry_passed")
    assert r.l6_geometry_passed is False


def test_execution_result_l6_geometry_passed_settable():
    r = ExecutionResult(
        task_id="t1", success=True,
        compile_duration_ms=0, execute_duration_ms=0,
        l6_geometry_passed=True,
    )
    assert r.l6_geometry_passed is True
