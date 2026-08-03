"""ExecutionQueue — async single-threaded serializer for Revit bridge.

Per spec Section 7.3: Revit's API is single-threaded. Even with multiple
subagents producing code, only one execution may run against the bridge
at a time. ExecutionQueue enforces this with an asyncio.Lock.

Gates: L3 (compile) → L4 (execute) → L5 (count) → L5.5 (property, optional)
→ L6 (geometry, optional). Auto-repair Reflexion loops belong elsewhere.
"""
from __future__ import annotations
import asyncio

from kukai.modeling.bridge.bridge_client import BridgeBriefForwarder
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate, PropertyValidationGate,
)
from kukai.modeling.execution.geometry_gate import GeometryGate
from kukai.modeling.schemas.execution import ExecutionResult, ExecutionTask
from kukai.modeling.schemas.llm import CodeProposal
from kukai.modeling.schemas.tasks import TaskBrief


class ExecutionQueue:
    """FIFO async queue. Serializes execution through gates L3-L6."""

    def __init__(
        self,
        compile_gate: CompileGate,
        execute_gate: ExecuteGate,
        count_gate: CountValidationGate,
        *,
        property_gate: PropertyValidationGate | None = None,
        geometry_gate: GeometryGate | None = None,
    ):
        self._compile = compile_gate
        self._execute = execute_gate
        self._count = count_gate
        self._property = property_gate
        self._geometry = geometry_gate
        self._lock = asyncio.Lock()
        self._brief: TaskBrief | None = None

    async def submit(
        self,
        task: ExecutionTask,
        *,
        brief: TaskBrief | None = None,
        proposal: CodeProposal | None = None,
    ) -> ExecutionResult:
        """Submit a task. Returns ExecutionResult when done.

        Sequential within a single ExecutionQueue instance — second concurrent
        submit() awaits the first via internal lock.

        `brief` is optional but REQUIRED if a geometry_gate was wired in
        the constructor; geometry checks need placement_point + category
        from the brief to evaluate deviation and host requirements.

        `proposal` is the originating CodeProposal. When supplied, CompileGate
        runs the property-invariants pre-check (INV001-INV012) BEFORE invoking
        Roslyn. Catching invariant violations here short-circuits a network
        round-trip and produces a stable rule_id in the error message. Callers
        in legacy paths that don't have the proposal pass None unchanged.
        """
        async with self._lock:
            self._brief = brief
            # Wave 6C — Fix A#3: brief forwarding now goes through the
            # BridgeBriefForwarder Protocol on the bridge client itself
            # rather than reaching through ExecuteGate privates to find
            # a `_revit_session` attribute on the underlying client.
            # MockBridgeClient implements forward_brief/clear_brief and
            # delegates to its wrapped MockRevitSession. Real
            # WebSocketBridgeClient deliberately does NOT implement the
            # protocol — the isinstance check fails and forwarding is
            # skipped (production Revit knows the current task from its
            # own state, no forwarding needed).
            bridge_client = getattr(self._execute, "_client", None)
            forwarder: BridgeBriefForwarder | None = (
                bridge_client if isinstance(bridge_client, BridgeBriefForwarder)
                else None
            )
            if forwarder is not None and brief is not None:
                forwarder.forward_brief(task_brief=brief)
            try:
                return await self._run_gates(task, proposal=proposal)
            finally:
                self._brief = None
                if forwarder is not None:
                    forwarder.clear_brief()

    async def _run_gates(
        self,
        task: ExecutionTask,
        *,
        proposal: CodeProposal | None = None,
    ) -> ExecutionResult:
        outcomes = []

        # L3 — compile (with optional invariants pre-check when proposal supplied)
        compile_outcome, compile_result = await self._compile.run(task, proposal=proposal)
        outcomes.append(compile_outcome)
        if not compile_outcome.passed:
            return ExecutionResult(
                task_id=task.task_id,
                success=False,
                failure_stage="compile",
                error_message=compile_result.error,
                error_signature=f"compile_{(compile_result.error or '')[:32]}",
                l3_compile_passed=False,
                l4_execute_passed=False,
                l5_count_passed=False,
                compile_duration_ms=compile_outcome.duration_ms,
                execute_duration_ms=0,
                gate_outcomes=outcomes,
            )

        # L4 — execute
        execute_outcome, payload = await self._execute.run(task)
        outcomes.append(execute_outcome)
        element_ids = list(payload.get("element_ids", []))
        if not execute_outcome.passed:
            return ExecutionResult(
                task_id=task.task_id,
                success=False,
                failure_stage="execute",
                error_message=payload.get("error"),
                error_signature=f"execute_{(payload.get('error') or '')[:32]}",
                l3_compile_passed=True,
                l4_execute_passed=False,
                l5_count_passed=False,
                compile_duration_ms=compile_outcome.duration_ms,
                execute_duration_ms=execute_outcome.duration_ms,
                gate_outcomes=outcomes,
            )

        # L5 — count
        count_outcome = self._count.run(task, element_ids)
        outcomes.append(count_outcome)
        if not count_outcome.passed:
            return ExecutionResult(
                task_id=task.task_id,
                success=False,
                failure_stage="count_mismatch",
                error_message=count_outcome.error,
                error_signature=f"count_{count_outcome.error}",
                element_ids=element_ids,
                l3_compile_passed=True,
                l4_execute_passed=True,
                l5_count_passed=False,
                compile_duration_ms=compile_outcome.duration_ms,
                execute_duration_ms=execute_outcome.duration_ms,
                gate_outcomes=outcomes,
            )

        # L5.5 — property (optional; only when configured AND elements exist)
        l5_5_passed = True
        if self._property is not None and element_ids:
            property_outcome = await self._property.run(task, element_ids)
            outcomes.append(property_outcome)
            l5_5_passed = property_outcome.passed
            if not property_outcome.passed:
                return ExecutionResult(
                    task_id=task.task_id,
                    success=False,
                    failure_stage="property_mismatch",
                    error_message=property_outcome.error,
                    error_signature=f"property_{(property_outcome.error or '')[:32]}",
                    element_ids=element_ids,
                    l3_compile_passed=True,
                    l4_execute_passed=True,
                    l5_count_passed=True,
                    l5_5_property_passed=False,
                    compile_duration_ms=compile_outcome.duration_ms,
                    execute_duration_ms=execute_outcome.duration_ms,
                    gate_outcomes=outcomes,
                )

        # L6 — geometry (optional; requires both gate and brief)
        l6_passed = True
        if self._geometry is not None and self._brief is not None and element_ids:
            geom_outcome, _ = await self._geometry.run(
                task=task, element_ids=element_ids, brief=self._brief,
            )
            outcomes.append(geom_outcome)
            l6_passed = geom_outcome.passed
            if not geom_outcome.passed:
                return ExecutionResult(
                    task_id=task.task_id,
                    success=False,
                    failure_stage="geometry_check",
                    error_message=geom_outcome.error,
                    error_signature=f"geometry_{(geom_outcome.error or '')[:32]}",
                    element_ids=element_ids,
                    l3_compile_passed=True,
                    l4_execute_passed=True,
                    l5_count_passed=True,
                    l5_5_property_passed=l5_5_passed,
                    l6_geometry_passed=False,
                    compile_duration_ms=compile_outcome.duration_ms,
                    execute_duration_ms=execute_outcome.duration_ms,
                    gate_outcomes=outcomes,
                )

        # All gates passed
        return ExecutionResult(
            task_id=task.task_id,
            success=True,
            element_ids=element_ids,
            l3_compile_passed=True,
            l4_execute_passed=True,
            l5_count_passed=True,
            l5_5_property_passed=l5_5_passed,
            l6_geometry_passed=l6_passed,
            compile_duration_ms=compile_outcome.duration_ms,
            execute_duration_ms=execute_outcome.duration_ms,
            gate_outcomes=outcomes,
        )
