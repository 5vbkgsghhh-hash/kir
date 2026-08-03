"""Integration: Foreman runs a 2-element phase end-to-end via mocks."""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import MockBridgeClient, MockCompileClient, MockModelQueryClient
from kukai.modeling.bridge.model_query_client import GridInfo
from kukai.modeling.execution.gates import CompileGate, CountValidationGate, ExecuteGate
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.foreman import Foreman, ForemanToolBox
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
            "{t.Start();t.Commit();}\n__result__ = new int[] { 100 };"
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


class _FakeSkillLoader:
    def load(self, skill_path: str) -> str:
        return "# Skill"


def _plan_task(plan_task_id: str, grid_x: str) -> PlanTask:
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


@pytest.mark.asyncio
async def test_two_tasks_get_distinct_task_ids_and_phase_completes():
    llm = MockLLMClient()
    tid1 = deterministic_task_uuid("proj_X", Phase.STRUCTURE.value, 1)
    tid2 = deterministic_task_uuid("proj_X", Phase.STRUCTURE.value, 2)
    assert tid1 != tid2, "deterministic ids must differ when seq differs"
    llm.queue_proposal(_proposal(tid1))
    llm.queue_proposal(_proposal(tid2))

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
    foreman = Foreman(
        project_id="proj_X",
        resolver=resolver,
        subagent=StructuralSubagent(llm),
        execution_queue=queue,
        skill_loader=_FakeSkillLoader(),
        rag_snippets=[("snip_a", "t", "body")],
        project_state_provider=lambda: ProjectState(),
    )
    plan = PhasePlan(phase=Phase.STRUCTURE, tasks=[
        _plan_task("pt_0001", "A"),
        _plan_task("pt_0002", "B"),
    ])

    result = await foreman.run_phase(plan)
    assert result.status == PhaseRunStatus.COMPLETED
    assert result.succeeded_plan_task_ids == ["pt_0001", "pt_0002"]
    assert len(llm.calls) == 2  # one LLM call per task, no retries


@pytest.mark.asyncio
async def test_toolbox_reflects_query_through_foreman_path():
    """ForemanToolBox surface is functional alongside the dispatcher path."""
    query = MockModelQueryClient()
    tb = ForemanToolBox(
        query_client=query,
        project_state_provider=lambda: ProjectState(),
        recent_events_provider=lambda limit=50: [],
    )
    families = await tb.list_families()
    assert isinstance(families, list)
    levels = await tb.list_levels()
    assert isinstance(levels, list)
    assert tb.current_phase().value == "setup"
    assert tb.phase_counts() == (0, 0)
