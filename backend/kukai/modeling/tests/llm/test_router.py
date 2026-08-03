"""Phase 4 Task 2 — cascade routing: Flash vs Pro 3.1 by PlanTask complexity."""
from __future__ import annotations
import pytest

from kukai.modeling.llm.router import (
    ComplexityScore, ModelChoice, assess_complexity, select_model,
)
from kukai.modeling.schemas.foreman import PlanTask
from kukai.modeling.schemas.resolver import (
    FamilyHint, GridIntersectionSpec, ResolverIntent,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Tier


def _plan_task(*, tier=Tier.TIER_2, dims=None, is_repair=False,
               expected_count=1, grid=True) -> PlanTask:
    return PlanTask(
        plan_task_id="p1",
        intent=ResolverIntent(
            element_type="structural_column",
            family_hint=FamilyHint(
                category="OST_StructuralColumns",
                dimensions_mm=({"width": 400, "height": 400} if dims is None else dims)),
            grid_intersection=(GridIntersectionSpec(grid_x_name="A", grid_y_name="1",
                                                    level_name="L1") if grid else None),
            revit_version="2026",
        ),
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns",
                                               count=expected_count),
        tier=tier, skill_path="modeling/structure/columns", is_repair=is_repair,
    )


def test_simple_tier2_yields_flash():
    score = assess_complexity(_plan_task())
    assert score.score < 50 and select_model(score) is ModelChoice.FLASH


def test_tier3_yields_pro():
    score = assess_complexity(_plan_task(tier=Tier.TIER_3))
    assert "tier_3_parametric" in score.factors and score.score >= 50
    assert select_model(score) is ModelChoice.PRO


def test_repair_attempt_records_factor():
    score = assess_complexity(_plan_task(is_repair=True))
    assert "repair_attempt" in score.factors and score.score >= 30


def test_many_dimensions_increases_score():
    score = assess_complexity(_plan_task(dims={"a": 1, "b": 2, "c": 3, "d": 4}))
    assert "many_dimensions" in score.factors


def test_multi_element_count_increases_score():
    score = assess_complexity(_plan_task(expected_count=10))
    assert "multi_element_count" in score.factors


def test_complexity_score_capped_at_100():
    score = assess_complexity(_plan_task(
        tier=Tier.TIER_3, is_repair=True,
        dims={"a": 1, "b": 2, "c": 3, "d": 4, "e": 5}, expected_count=20))
    assert score.score == 100


def test_threshold_tuning():
    score = assess_complexity(_plan_task(is_repair=True))  # base 30
    assert select_model(score, threshold=20) is ModelChoice.PRO
    assert select_model(score, threshold=80) is ModelChoice.FLASH


def test_complexity_score_is_frozen():
    score = ComplexityScore(score=42, factors=["x"])
    with pytest.raises(Exception):
        score.score = 50  # type: ignore[misc]


@pytest.mark.asyncio
async def test_foreman_uses_pro_subagent_for_complex_task():
    from kukai.modeling.foreman.dispatcher import Foreman
    from kukai.modeling.subagent.structural import StructuralSubagent
    from kukai.modeling.resolver.dispatcher import Resolver
    from kukai.modeling.bridge.mocks import (
        MockBridgeClient, MockCompileClient, MockModelQueryClient,
    )
    from kukai.modeling.bridge.model_query_client import GridInfo
    from kukai.modeling.execution.gates import (
        CompileGate, CountValidationGate, ExecuteGate,
    )
    from kukai.modeling.execution.queue import ExecutionQueue
    from kukai.modeling.state.projections.project_state import ProjectState
    from kukai.modeling.llm.mocks import MockLLMClient
    from kukai.modeling.schemas.identifiers import deterministic_task_uuid
    from kukai.modeling.schemas.llm import CodeProposal, FailureCategory
    from kukai.modeling.schemas.resolver import FamilySymbolCandidate
    from kukai.modeling.schemas.tasks import Phase

    expected_task_id = deterministic_task_uuid("proj-1", Phase.STRUCTURE.value, 1)
    proposal = {
        "task_id": expected_task_id, "csharp_code": "// RAG:#s1\n// pro",
        "explanation": "p",
        "expected_elements": {"category": "OST_StructuralColumns", "count": 1},
        "requires_assemblies": ["RevitAPI"],
        "transaction_name": "Place column", "revit_version": "2026",
        "failure_mode_checks": {c.value: {"checked": True, "applicable": False, "note": None}
                                for c in FailureCategory},
        "rag_citations": [{"snippet_id": "s1", "api_called": "X"}],
        "dry_run": {"selected_symbol_id": 10, "proposed_xyz_mm": [0.0, 0.0, 0.0],
                    "params_to_set": {}},
        "declared_outputs": {"expected_element_count": 1,
                              "expected_category": "OST_StructuralColumns",
                              "expected_parameter_values": {},
                              "expected_level_name": None, "expected_family_name": None},
        "questions_to_foreman": [],
    }
    flash_llm = MockLLMClient()  # empty — flash must NOT be called for a Tier 3 task
    pro_llm = MockLLMClient()
    pro_llm.queue_proposal(CodeProposal.model_validate(proposal))
    flash_sub = StructuralSubagent(flash_llm)
    pro_sub = StructuralSubagent(pro_llm)

    queue = ExecutionQueue(
        compile_gate=CompileGate(compile_client=MockCompileClient()),
        execute_gate=ExecuteGate(bridge_client=MockBridgeClient(), session_id="mock"),
        count_gate=CountValidationGate(),
    )
    resolver = Resolver(MockModelQueryClient(
        families=[FamilySymbolCandidate(family_symbol_id=10, name="Col",
                                        family_name="ColF", category="OST_StructuralColumns")],
        grids=[GridInfo(grid_id=1, name="A", axis="horizontal", position_mm=0.0),
               GridInfo(grid_id=2, name="1", axis="vertical", position_mm=0.0)]))

    class _SL:
        def load(self, p): return "skill"

    from kukai.modeling.foreman.config import ForemanRouting
    foreman = Foreman(
        project_id="proj-1", resolver=resolver, subagent=flash_sub,
        execution_queue=queue, skill_loader=_SL(),
        rag_snippets=[("s1", "snip", "body")],
        project_state_provider=lambda: ProjectState(),
        routing=ForemanRouting(pro_subagent=pro_sub),
    )
    # No dims on the hint so FamilyResolver returns RESOLVED on the single
    # candidate. Tier 3 alone gets score 60 → PRO.
    pt = _plan_task(tier=Tier.TIER_3, dims={})
    outcome = await foreman.dispatch_task(pt, phase=Phase.STRUCTURE, task_seq=1)
    assert outcome.executed
    assert any("model: gemini-pro-3.1" in n for n in outcome.notes), outcome.notes
    # Flash must NOT have been called — its scripted queue is empty and any
    # call would have raised.
    assert len(flash_llm.calls) == 0
    assert len(pro_llm.calls) == 1


def test_vertex_client_pins_two_cascade_model_ids():
    from kukai.modeling.llm.vertex_client import FLASH_MODEL_ID, PRO_MODEL_ID
    assert FLASH_MODEL_ID == "gemini-3.1-flash-lite"
    assert PRO_MODEL_ID == "gemini-3.1-pro"
    assert FLASH_MODEL_ID != PRO_MODEL_ID
