"""End-to-end Tier 2 integration: Resolver → Subagent → CodeProposal → Queue.

All via mocks (MockLLMClient, MockCompileClient, MockBridgeClient,
MockModelQueryClient). Proves the LLM path works through every layer.
"""
from __future__ import annotations
import pytest

from kukai.modeling.bridge.mocks import (
    MockBridgeClient, MockCompileClient, MockModelQueryClient,
)
from kukai.modeling.bridge.model_query_client import GridInfo, LevelInfo
from kukai.modeling.execution.gates import (
    CompileGate, CountValidationGate, ExecuteGate,
)
from kukai.modeling.execution.queue import ExecutionQueue
from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.resolver.dispatcher import Resolver
from kukai.modeling.schemas.execution import ExecutionTask
from kukai.modeling.schemas.identifiers import deterministic_task_uuid
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult,
    InlineRagCitation,
)
from kukai.modeling.schemas.resolver import (
    FamilyHint, FamilySymbolCandidate, GridIntersectionSpec, ResolverIntent,
)
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, ParameterRef, Phase, TaskBrief, Tier,
)
from kukai.modeling.subagent.structural import StructuralSubagent


def _full_checks() -> dict[FailureCategory, FailureCheckResult]:
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


@pytest.fixture
def stocked_query() -> MockModelQueryClient:
    return MockModelQueryClient(
        families=[FamilySymbolCandidate(
            family_symbol_id=8821, name="400 x 400mm",
            family_name="M_Concrete-Rectangular-Column",
            category="OST_StructuralColumns",
            dimensions_mm={"width": 400, "height": 400},
        )],
        levels=[
            LevelInfo(level_id=1042, name="Level 1", elevation_mm=0.0),
            LevelInfo(level_id=1043, name="Level 2", elevation_mm=3300.0),
        ],
        grids=[
            GridInfo(grid_id=2002, name="2", axis="horizontal", position_mm=6000.0),
            GridInfo(grid_id=2004, name="B", axis="vertical", position_mm=6000.0),
        ],
        parameter_info={8821: {"mark": ("ALL_MODEL_MARK", "built_in")}},
    )


@pytest.mark.asyncio
async def test_full_tier2_path_resolver_to_queue(stocked_query):
    # 1. Resolver — get fully-resolved data
    resolver = Resolver(stocked_query)
    intent = ResolverIntent(
        element_type="structural_column",
        family_hint=FamilyHint(
            category="OST_StructuralColumns",
            dimensions_mm={"width": 400, "height": 400},
        ),
        grid_intersection=GridIntersectionSpec(
            grid_x_name="2", grid_y_name="B", level_name="Level 1",
        ),
        top_level_name="Level 2",
        revit_version="2026",
    )
    resolved = await resolver.resolve(intent)
    assert resolved.family_symbol_id == 8821

    # 2. Build TaskBrief from resolved data
    task_id = deterministic_task_uuid("integration_test_project", "structure", 1)
    task_brief = TaskBrief(
        task_id=task_id,
        phase=Phase.STRUCTURE,
        skill_path="structure/columns/concrete-columns",
        element_type="structural_column",
        placement_point=resolved.placement_point,
        family_symbol_id=resolved.family_symbol_id,
        parameter_map={"mark": ParameterRef(name="ALL_MODEL_MARK", scope="built_in")},
        level_id=resolved.level_id,
        top_level_id=resolved.top_level_id,
        revit_version=resolved.revit_version,
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        estimated_cost_usd=0.0005,
    )

    # 3. Subagent generates code via mock LLM
    llm = MockLLMClient(proposals=[CodeProposal(
        task_id=task_id,
        csharp_code="// RAG:#snip_col_basic\nvar x = 1;",
        explanation="place column",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column at 2B",
        revit_version="2026",
        failure_mode_checks=_full_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_col_basic", api_called="NewFamilyInstance")],
        dry_run=DryRunSummary(
            selected_symbol_id=resolved.family_symbol_id,
            proposed_xyz_mm=(resolved.placement_point.x, resolved.placement_point.y, resolved.placement_point.z),
            params_to_set={"Mark": "C-2B-L1"},
        ),
    )])
    subagent = StructuralSubagent(llm)
    proposal = await subagent.generate_code(
        task_brief=task_brief,
        skill_content="# columns\nplace at grid intersections; use Activate()",
        rag_snippets=[("snip_col_basic", "NewFamilyInstance", "use the (XYZ, Symbol, Level, StructuralType.Column) overload")],
    )
    assert proposal.task_id == task_id

    # 4. Submit to ExecutionQueue
    queue = ExecutionQueue(
        compile_gate=CompileGate(MockCompileClient()),
        execute_gate=ExecuteGate(MockBridgeClient(), session_id="dev"),
        count_gate=CountValidationGate(),
    )
    exec_task = ExecutionTask(
        task_id=task_id,
        csharp_code=proposal.csharp_code,
        expected_elements=task_brief.expected_elements,
        revit_version=task_brief.revit_version,
        transaction_name=proposal.transaction_name,
        max_compile_attempts=3,
        max_execute_attempts=3,
    )
    result = await queue.submit(exec_task)
    assert result.success is True
    assert result.l3_compile_passed
    assert result.l4_execute_passed
    assert result.l5_count_passed
    assert len(result.element_ids) == 1
