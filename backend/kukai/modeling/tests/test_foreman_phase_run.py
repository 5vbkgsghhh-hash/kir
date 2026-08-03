"""Foreman.run_phase — full phase orchestration with mocked subagent."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient, MockModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo
from kukai.modeling.execution.gates import CompileGate, CountValidationGate, ExecuteGate
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman.dispatcher import Foreman
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.foreman import PhasePlan, PhaseRunStatus, PlanTask
from kukai.modeling.schemas.identifiers import deterministic_task_uuid
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.resolver import FamilyHint, FamilySymbolCandidate, GridIntersectionSpec, ResolverIntent
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, Tier
from kukai.modeling.state.projections.project_state import ProjectState
from kukai.modeling.subagent.structural import StructuralSubagent


def _checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _proposal(task_id: str) -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code=(
            "// RAG:#snip_a\nusing(Transaction t = new Transaction(doc,\"Place column\"))"
            "{t.Start();t.Commit();}\n__result__ = new int[] { 42 };"
        ),
        explanation="ok",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column",
        revit_version="2026",
        failure_mode_checks=_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_a", api_called="Document.Create.NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )


def _plan_task(plan_task_id: str, grid_x: str = "A") -> PlanTask:
    return PlanTask(
        plan_task_id=plan_task_id,
        intent=ResolverIntent(
            element_type="structural_column",
            family_hint=FamilyHint(category="OST_StructuralColumns"),
            grid_intersection=GridIntersectionSpec(grid_x_name=grid_x, grid_y_name="1", level_name="L1"),
            revit_version="2026",
        ),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        skill_path="modeling/structure/columns/concrete-columns.md",
    )


class _FakeSkillLoader:
    def load(self, skill_path: str) -> str:
        return "# Skill"


def _foreman(llm: MockLLMClient, project_state: ProjectState | None = None):
    # Gotcha 4: seed grids with A and B as horizontal, 1 as vertical
    query = MockModelQueryClient(grids=[
        GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
        GridInfo(grid_id=2, name="B", axis="horizontal", position_mm=6000.0),
        GridInfo(grid_id=3, name="1", axis="vertical", position_mm=0.0),
    ])
    # Gotcha 2: seed a family
    query._families = [FamilySymbolCandidate(
        family_symbol_id=10, name="C-300", family_name="ЖБ Колонна",
        category="OST_StructuralColumns",
    )]
    resolver = Resolver(query)
    # Gotcha 3: ExecuteGate needs session_id
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="dev"),
        count_gate=CountValidationGate(),
    )
    return Foreman(
        project_id="proj1",
        resolver=resolver,
        subagent=StructuralSubagent(llm),
        execution_queue=queue,
        skill_loader=_FakeSkillLoader(),
        rag_snippets=[("snip_a", "t", "body")],
        project_state_provider=lambda: project_state or ProjectState(),
    )


@pytest.mark.asyncio
async def test_run_phase_all_succeed_returns_completed():
    llm = MockLLMClient()
    tid1 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    tid2 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 2)
    llm.queue_proposal(_proposal(tid1))
    llm.queue_proposal(_proposal(tid2))
    foreman = _foreman(llm)
    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[_plan_task("pt_0001"), _plan_task("pt_0002", grid_x="B")])
    result = await foreman.run_phase(plan)
    assert result.status == PhaseRunStatus.COMPLETED
    assert set(result.succeeded_plan_task_ids) == {"pt_0001", "pt_0002"}
    # Budget tripwire: exactly two LLM calls (one per task), no retries.
    assert len(llm.calls) == 2, f"unexpected LLM call count: {len(llm.calls)}"


@pytest.mark.asyncio
async def test_run_phase_one_blocked_returns_partial():
    llm = MockLLMClient()
    tid1 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    tid2 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 2)
    good = _proposal(tid1)
    # Wave 6C — Fix A#5: previously this test used questions_to_foreman as
    # the "blocking" condition. After Fix A#5 questions are INFO and dispatch
    # continues, so we need a genuinely blocking issue: a deliberate
    # expected_count_mismatch (proposal says 5, brief says 1) is caught by
    # check_correctness as BLOCKING and rejects the proposal at review.
    bad = _proposal(tid2).model_copy(update={
        "expected_elements": ExpectedElementsSpec(
            category="OST_StructuralColumns", count=5),
    })
    llm.queue_proposal(good)
    llm.queue_proposal(bad)
    foreman = _foreman(llm)
    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[_plan_task("pt_0001"), _plan_task("pt_0002", grid_x="B")])
    result = await foreman.run_phase(plan)
    assert result.status == PhaseRunStatus.PARTIAL
    assert result.succeeded_plan_task_ids == ["pt_0001"]
    assert result.failed_plan_task_ids == ["pt_0002"]
    assert len(llm.calls) == 2  # both tasks asked for a proposal, even though one was blocked at review


@pytest.mark.asyncio
async def test_run_phase_question_continues_with_escalation():
    """Wave 6C Fix A#5 — a question-bearing proposal still succeeds and the
    escalation note appears in PhaseRunResult.notes."""
    llm = MockLLMClient()
    tid1 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    tid2 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 2)
    llm.queue_proposal(_proposal(tid1))
    # Second proposal asks a question — should still execute + succeed
    with_q = _proposal(tid2).model_copy(update={
        "questions_to_foreman": ["clarify level"]})
    llm.queue_proposal(with_q)
    foreman = _foreman(llm)
    plan = PhasePlan(phase=Phase.STRUCTURE,
                     tasks=[_plan_task("pt_0001"), _plan_task("pt_0002", grid_x="B")])
    result = await foreman.run_phase(plan)
    assert result.status == PhaseRunStatus.COMPLETED
    assert set(result.succeeded_plan_task_ids) == {"pt_0001", "pt_0002"}
    assert any("escalation:" in n and "pt_0002" in n for n in result.notes), (
        f"expected escalation note for pt_0002 in {result.notes}"
    )


@pytest.mark.asyncio
async def test_run_phase_aborts_when_user_intervention_required():
    llm = MockLLMClient()
    tid1 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    llm.queue_proposal(_proposal(tid1))
    intervened = ProjectState(user_intervention_required=True, user_intervention_reason="ambiguous")
    foreman = _foreman(llm, project_state=intervened)
    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[_plan_task("pt_0001"), _plan_task("pt_0002", grid_x="B")])
    result = await foreman.run_phase(plan)
    assert result.status == PhaseRunStatus.ABORTED
    assert "pt_0002" not in result.succeeded_plan_task_ids
    assert "pt_0002" not in result.failed_plan_task_ids
    assert any("user_intervention_required" in n for n in result.notes)
    assert len(llm.calls) == 0  # aborted before any subagent call


def test_interpret_result_success():
    from kukai.modeling.foreman.dispatcher import interpret_result
    from kukai.modeling.schemas.execution import ExecutionResult
    r = ExecutionResult(
        task_id="t1", success=True, element_ids=[42],
        l3_compile_passed=True, l4_execute_passed=True, l5_count_passed=True,
        compile_duration_ms=10, execute_duration_ms=20,
    )
    decoded = interpret_result(r)
    assert decoded.kind == "success"
    assert decoded.element_count == 1


@pytest.mark.asyncio
@pytest.mark.tier0
async def test_budget_guard_aborts_phase_on_llm_overrun():
    """Audit N1: ForemanBudgetGuard wired into run_phase aborts on cap breach."""
    from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient, MockModelQueryClient
    from kukai.modeling.bridge.model_query_client import GridInfo
    from kukai.modeling.execution.gates import CompileGate, CountValidationGate, ExecuteGate
    from kukai.modeling.execution.queue import ExecutionQueue
    from kukai.modeling.foreman.budget_guard import BudgetCaps
    from kukai.modeling.foreman.dispatcher import Foreman
    from kukai.modeling.resolver.dispatcher import Resolver

    llm = MockLLMClient()
    # queue 5 proposals (one per task) so dispatch doesn't fail for no-proposal
    tids = [deterministic_task_uuid("proj1", Phase.STRUCTURE.value, i) for i in range(1, 6)]
    for tid in tids:
        llm.queue_proposal(_proposal(tid))

    query = MockModelQueryClient(grids=[
        GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
        GridInfo(grid_id=2, name="B", axis="horizontal", position_mm=6000.0),
        GridInfo(grid_id=3, name="1", axis="vertical", position_mm=0.0),
    ])
    query._families = [FamilySymbolCandidate(
        family_symbol_id=10, name="C-300", family_name="ЖБ Колонна",
        category="OST_StructuralColumns",
    )]
    compile_c = MockCompileClient()
    bridge_c = MockBridgeClient()
    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_c),
        execute_gate=ExecuteGate(bridge_c, session_id="dev"),
        count_gate=CountValidationGate(),
    )
    foreman = Foreman(
        project_id="proj1",
        resolver=Resolver(query),
        subagent=StructuralSubagent(llm),
        execution_queue=queue,
        skill_loader=_FakeSkillLoader(),
        rag_snippets=[("snip_a", "t", "body")],
        project_state_provider=lambda: ProjectState(),
        budget_caps=BudgetCaps(max_llm_calls=2, max_compile_calls=200, max_execute_calls=200),
        llm_client_for_budget=llm,
        compile_client_for_budget=compile_c,
        bridge_client_for_budget=bridge_c,
    )
    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[
        _plan_task("pt_0001"), _plan_task("pt_0002", grid_x="B"),
        _plan_task("pt_0003"), _plan_task("pt_0004", grid_x="B"),
        _plan_task("pt_0005"),
    ])
    result = await foreman.run_phase(plan)
    assert result.status == PhaseRunStatus.ABORTED
    assert any("budget exceeded" in n for n in result.notes), result.notes
    # Should abort after 3rd dispatch (LLM cap=2 → 3rd call exceeds)
    assert len(llm.calls) <= 3


@pytest.mark.asyncio
@pytest.mark.tier0
async def test_phase_survives_single_task_crash():
    """Wave 6A B#1 — a subagent that raises arbitrary RuntimeError on one task
    must NOT destroy the entire phase. Other tasks still get a chance to run;
    the crashed task lands in `failed` with a 'dispatch crashed' note.
    """
    llm = MockLLMClient()
    tid1 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 1)
    tid3 = deterministic_task_uuid("proj1", Phase.STRUCTURE.value, 3)
    # Only queue proposals for tasks that actually invoke the subagent.
    # Task 2 crashes BEFORE reaching the subagent (our wrapper raises first).
    llm.queue_proposal(_proposal(tid1))
    llm.queue_proposal(_proposal(tid3))
    foreman = _foreman(llm)

    # Wrap dispatch_task so the SECOND task raises a RuntimeError. The other
    # two tasks must still complete normally.
    original_dispatch = foreman.dispatch_task
    call_counter = {"n": 0}

    async def _flaky_dispatch(plan_task, *, phase, task_seq):
        call_counter["n"] += 1
        if call_counter["n"] == 2:
            raise RuntimeError("simulated subagent crash")
        return await original_dispatch(plan_task, phase=phase, task_seq=task_seq)

    foreman.dispatch_task = _flaky_dispatch  # type: ignore[assignment]

    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[
        _plan_task("pt_0001"),
        _plan_task("pt_0002", grid_x="B"),
        _plan_task("pt_0003"),
    ])
    result = await foreman.run_phase(plan)

    assert result.status in (PhaseRunStatus.PARTIAL, PhaseRunStatus.FAILED), (
        f"phase should not abort on a single-task crash; got {result.status}"
    )
    # First and third tasks ran normally; second crashed.
    assert "pt_0001" in result.succeeded_plan_task_ids
    assert "pt_0003" in result.succeeded_plan_task_ids
    assert "pt_0002" in result.failed_plan_task_ids
    assert any(
        "pt_0002" in n and "dispatch crashed" in n and "RuntimeError" in n
        for n in result.notes
    ), f"missing 'dispatch crashed: RuntimeError' note for pt_0002: {result.notes}"


def test_interpret_result_compile_failure():
    from kukai.modeling.foreman.dispatcher import interpret_result
    from kukai.modeling.schemas.execution import ExecutionResult
    r = ExecutionResult(
        task_id="t1", success=False, failure_stage="compile",
        error_message="CS1002 expected ;", error_signature="compile_CS1002",
        l3_compile_passed=False, l4_execute_passed=False, l5_count_passed=False,
        compile_duration_ms=5, execute_duration_ms=0,
    )
    decoded = interpret_result(r)
    assert decoded.kind == "compile_failed"
    assert "CS1002" in decoded.human_summary
