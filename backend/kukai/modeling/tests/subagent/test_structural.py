"""Tests for StructuralSubagent."""
from __future__ import annotations
import pytest

from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.llm import (
    CodeProposal,
    DryRunSummary,
    FailureCategory,
    FailureCheckResult,
    InlineRagCitation,
)
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, ParameterRef, Phase, TaskBrief, Tier
)
from kukai.modeling.subagent.citations import CitationValidationError
from kukai.modeling.subagent.structural import StructuralSubagent


def _full_checks() -> dict[FailureCategory, FailureCheckResult]:
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _task() -> TaskBrief:
    return TaskBrief(
        task_id="t_col_2B_L1",
        phase=Phase.STRUCTURE,
        skill_path="structure/columns/concrete-columns",
        element_type="structural_column",
        placement_point=XYZ(x=6000.0, y=6000.0, z=0.0),
        family_symbol_id=8821,
        parameter_map={"mark": ParameterRef(name="ALL_MODEL_MARK", scope="built_in")},
        level_id=1042,
        top_level_id=1043,
        revit_version="2026",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        estimated_cost_usd=0.0005,
    )


def _good_proposal(task_id: str = "t_col_2B_L1") -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code="// RAG:#snip1\nvar x = 1;",
        explanation="x",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column",
        revit_version="2026",
        failure_mode_checks=_full_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip1", api_called="NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=8821, proposed_xyz_mm=(6000, 6000, 0), params_to_set={}),
    )


@pytest.mark.asyncio
async def test_happy_path():
    llm = MockLLMClient(proposals=[_good_proposal()])
    sub = StructuralSubagent(llm)
    proposal = await sub.generate_code(
        task_brief=_task(),
        skill_content="# columns\nplace at grid intersections",
        rag_snippets=[("snip1", "NewFamilyInstance", "use the level overload")],
    )
    assert proposal.task_id == "t_col_2B_L1"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_rejects_task_id_mismatch():
    """If LLM returns proposal with wrong task_id, Subagent rejects it."""
    bad = _good_proposal(task_id="wrong_id")
    llm = MockLLMClient(proposals=[bad])
    sub = StructuralSubagent(llm)
    with pytest.raises(ValueError, match="task_id mismatch"):
        await sub.generate_code(
            task_brief=_task(),
            skill_content="x",
            rag_snippets=[("snip1", "x", "x")],
        )


@pytest.mark.asyncio
async def test_validates_citations_against_retrieved_set():
    """If LLM cites a snippet not in retrieved set, Subagent rejects it."""
    proposal = _good_proposal()  # cites "snip1"
    llm = MockLLMClient(proposals=[proposal])
    sub = StructuralSubagent(llm)
    with pytest.raises(CitationValidationError, match="not in retrieved set"):
        await sub.generate_code(
            task_brief=_task(),
            skill_content="x",
            rag_snippets=[("snip2", "other", "other")],  # snip1 NOT here
        )


@pytest.mark.asyncio
async def test_revit_version_must_match_task():
    bad = _good_proposal()
    bad = bad.model_copy(update={"revit_version": "2023"})
    llm = MockLLMClient(proposals=[bad])
    sub = StructuralSubagent(llm)
    with pytest.raises(ValueError, match="revit_version mismatch"):
        await sub.generate_code(
            task_brief=_task(),
            skill_content="x",
            rag_snippets=[("snip1", "x", "x")],
        )


@pytest.mark.asyncio
async def test_questions_to_foreman_path():
    """If proposal has questions_to_foreman, Subagent returns it unchanged (no code expected)."""
    proposal = CodeProposal(
        task_id="t_col_2B_L1",
        csharp_code="// RAG:#snip1\n// placeholder while waiting for clarification",
        explanation="awaiting clarification",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="x",
        revit_version="2026",
        failure_mode_checks=_full_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip1", api_called="X")],
        dry_run=DryRunSummary(selected_symbol_id=8821, proposed_xyz_mm=(0, 0, 0), params_to_set={}),
        questions_to_foreman=["which top level — Level 2 or Level 3?"],
    )
    llm = MockLLMClient(proposals=[proposal])
    sub = StructuralSubagent(llm)
    out = await sub.generate_code(
        task_brief=_task(),
        skill_content="x",
        rag_snippets=[("snip1", "x", "x")],
    )
    assert out.questions_to_foreman == ["which top level — Level 2 or Level 3?"]
