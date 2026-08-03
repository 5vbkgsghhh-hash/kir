"""Tests for ExecutionQueue."""
from __future__ import annotations
import asyncio
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate
)
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.schemas.execution import ExecutionTask
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult,
    InlineRagCitation,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


def _make_queue(
    compile_responses=None,
    bridge_responses=None,
) -> ExecutionQueue:
    compile_client = MockCompileClient(responses=compile_responses)
    bridge_client = MockBridgeClient(responses=bridge_responses)
    return ExecutionQueue(
        compile_gate=CompileGate(compile_client),
        execute_gate=ExecuteGate(bridge_client, session_id="test_session"),
        count_gate=CountValidationGate(),
    )


def _make_task(task_id: str = "t1", count: int = 1) -> ExecutionTask:
    return ExecutionTask(
        task_id=task_id,
        csharp_code="// placeholder",
        expected_elements=ExpectedElementsSpec(
            category="OST_StructuralColumns", count=count
        ),
        revit_version="2026",
        transaction_name="Test",
        max_compile_attempts=3,
        max_execute_attempts=3,
    )


class TestExecutionQueue:
    @pytest.mark.asyncio
    async def test_happy_path_single_element(self):
        q = _make_queue()
        result = await q.submit(_make_task())
        assert result.success is True
        assert len(result.element_ids) == 1
        assert result.l3_compile_passed
        assert result.l4_execute_passed
        assert result.l5_count_passed
        assert result.failure_stage is None

    @pytest.mark.asyncio
    async def test_compile_failure_short_circuits(self):
        q = _make_queue(compile_responses=[
            {"success": False, "error": "CS1002"},
        ])
        result = await q.submit(_make_task())
        assert result.success is False
        assert result.failure_stage == "compile"
        assert result.l3_compile_passed is False
        assert result.l4_execute_passed is False  # never ran
        assert "CS1002" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_execute_failure(self):
        q = _make_queue(bridge_responses=[
            {"success": False, "error": "Revit hung", "element_ids": [], "duration_ms": 50},
        ])
        result = await q.submit(_make_task())
        assert result.success is False
        assert result.failure_stage == "execute"
        assert result.l3_compile_passed is True
        assert result.l4_execute_passed is False
        assert "Revit hung" in (result.error_message or "")

    @pytest.mark.asyncio
    async def test_count_mismatch_failure(self):
        # Compile passes, execute returns 1 id but task expects 2
        q = _make_queue(bridge_responses=[
            {"success": True, "element_ids": [9001], "duration_ms": 50},
        ])
        result = await q.submit(_make_task(count=2))
        assert result.success is False
        assert result.failure_stage == "count_mismatch"
        assert result.l5_count_passed is False

    @pytest.mark.asyncio
    async def test_queue_invariants_short_circuit_when_proposal_passed(self):
        """Fix A: when caller passes the originating proposal, CompileGate's
        invariants pre-check runs BEFORE Roslyn. A proposal that violates
        INV001 (missing __result__) must short-circuit with the typed error
        and zero compile_client invocations.
        """
        compile_client = MockCompileClient()
        bridge_client = MockBridgeClient()
        q = ExecutionQueue(
            compile_gate=CompileGate(compile_client),
            execute_gate=ExecuteGate(bridge_client, session_id="test"),
            count_gate=CountValidationGate(),
        )
        # Proposal violating INV001 (no __result__) and INV010 (no Start/Commit).
        bad_proposal = CodeProposal(
            task_id="tid_inv1",
            csharp_code=(
                "using (var t = new Transaction(doc, \"Place column\")) {\n"
                "  // missing __result__ token + missing Start/Commit\n"
                "}\n"
            ),
            explanation="bad",
            expected_elements=ExpectedElementsSpec(
                category="OST_StructuralColumns", count=1),
            requires_assemblies=["RevitAPI"],
            transaction_name="Place column",
            revit_version="2026",
            failure_mode_checks={
                c: FailureCheckResult(checked=True, applicable=False)
                for c in FailureCategory
            },
            rag_citations=[InlineRagCitation(snippet_id="s", api_called="X")],
            dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
        )
        result = await q.submit(_make_task(), proposal=bad_proposal)
        assert result.success is False
        assert result.failure_stage == "compile"
        assert result.l3_compile_passed is False
        assert (result.error_message or "").startswith("invariant_violation: INV001")
        # Roslyn was never invoked — invariants short-circuited the gate.
        assert compile_client.calls == []

    @pytest.mark.asyncio
    async def test_queue_proposal_None_skips_invariants(self):
        """Fix A: default call (no proposal) preserves legacy behavior —
        invariants are NOT evaluated, Roslyn runs as normal.
        """
        compile_client = MockCompileClient()
        bridge_client = MockBridgeClient()
        q = ExecutionQueue(
            compile_gate=CompileGate(compile_client),
            execute_gate=ExecuteGate(bridge_client, session_id="test"),
            count_gate=CountValidationGate(),
        )
        # No proposal kwarg -> legacy code path; Roslyn must be called.
        result = await q.submit(_make_task())
        assert result.success is True
        assert len(compile_client.calls) == 1

    @pytest.mark.asyncio
    async def test_serial_execution(self):
        """Two submits in parallel must serialize through the queue's lock."""
        q = _make_queue()
        order: list[str] = []

        async def submit_and_track(task_id: str):
            order.append(f"start_{task_id}")
            r = await q.submit(_make_task(task_id=task_id))
            order.append(f"end_{task_id}")
            return r

        results = await asyncio.gather(
            submit_and_track("a"),
            submit_and_track("b"),
        )
        # Both succeed
        assert all(r.success for r in results)
        # Execution serialized: end_a before start_b OR end_b before start_a
        idx_end_a = order.index("end_a")
        idx_start_b = order.index("start_b")
        idx_end_b = order.index("end_b")
        idx_start_a = order.index("start_a")
        assert (idx_end_a < idx_start_b) or (idx_end_b < idx_start_a)
