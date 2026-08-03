"""Execution-layer schemas: ExecutionTask, ExecutionResult, CompileResult, GateOutcome.

Per spec Section 11. ExecutionTask is what ExecutionQueue consumes;
ExecutionResult is what it returns; CompileResult is the L3 gate output;
GateOutcome is the generic per-gate verdict embedded in ExecutionResult.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

from kukai.modeling.schemas.tasks import ExpectedElementsSpec


class CompileError(BaseModel):
    """One Roslyn diagnostic. Matches C# CompileService.CompileError record exactly."""
    model_config = ConfigDict(frozen=True)

    code: str = Field(..., description="diagnostic id, e.g. CS1002 or KUKAI001")
    message: str = Field(..., min_length=1)
    line: int = Field(0, ge=0)
    column: int = Field(0, ge=0)


class CompileResult(BaseModel):
    """L3 gate output. Either success with compiled code + assembly ref,
    or failure with a list of CompileError diagnostics."""
    model_config = ConfigDict(frozen=True)

    success: bool
    code: str | None = None                          # The (possibly-fixed) source that compiled
    assembly_id: str | None = None                   # Reference returned by compile service
    errors: list[CompileError] = Field(default_factory=list)

    @property
    def error(self) -> str | None:
        """Back-compat helper: first error's message (or None on success)."""
        return self.errors[0].message if self.errors else None


class GateOutcome(BaseModel):
    """Generic per-gate verdict embedded in ExecutionResult."""
    model_config = ConfigDict(frozen=True)

    name: str = Field(..., description="e.g. L3_compile, L4_execute, L5_count")
    passed: bool
    duration_ms: int = Field(..., ge=0)
    error: str | None = None


class ExecutionTask(BaseModel):
    """One unit of work consumed by ExecutionQueue.

    Single Revit element by design; tier classification happens upstream.
    """
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(..., min_length=1)
    csharp_code: str = Field(..., min_length=1, description="raw C# body for bridge")
    expected_elements: ExpectedElementsSpec
    revit_version: str
    transaction_name: str = Field(..., min_length=1)
    max_compile_attempts: int = Field(..., ge=1, le=10)
    max_execute_attempts: int = Field(..., ge=1, le=10)


class ExecutionResult(BaseModel):
    """Output of ExecutionQueue.submit() for one ExecutionTask."""
    model_config = ConfigDict(frozen=True)

    task_id: str
    success: bool

    # On success
    element_ids: list[int] = Field(default_factory=list)

    # On failure
    failure_stage: Literal["compile", "execute", "count_mismatch", "property_mismatch", "geometry_check"] | None = None
    error_message: str | None = None
    error_signature: str | None = Field(None, description="hash key for CascadeDetector")

    # Per-gate flags (rolled up)
    l3_compile_passed: bool = False
    l4_execute_passed: bool = False
    l5_count_passed: bool = False
    l5_5_property_passed: bool = False
    l6_geometry_passed: bool = False

    # Timings
    compile_duration_ms: int = Field(..., ge=0)
    execute_duration_ms: int = Field(..., ge=0)

    # Optional detailed gate outcomes (omit for compactness in event log)
    gate_outcomes: list[GateOutcome] = Field(default_factory=list)

    # Repair tracking
    repair_attempts_used: int = 0
