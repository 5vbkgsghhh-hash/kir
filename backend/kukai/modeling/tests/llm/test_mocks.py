"""Tests for MockLLMClient."""
from __future__ import annotations
import pytest

from kukai.modeling.llm.mocks import MockLLMClient
from kukai.modeling.schemas.llm import (
    CodeProposal,
    DryRunSummary,
    FailureCategory,
    FailureCheckResult,
    InlineRagCitation,
    LLMPromptInputs,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


def _full_checks() -> dict[FailureCategory, FailureCheckResult]:
    return {
        c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory
    }


def _proposal(task_id: str = "t1") -> CodeProposal:
    return CodeProposal(
        task_id=task_id,
        csharp_code="// RAG:#rag_42\nvar x = 1;",
        explanation="placeholder",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Tx",
        revit_version="2026",
        failure_mode_checks=_full_checks(),
        rag_citations=[InlineRagCitation(snippet_id="rag_42", api_called="X")],
        dry_run=DryRunSummary(selected_symbol_id=1, proposed_xyz_mm=(0, 0, 0), params_to_set={}),
    )


def _inputs() -> LLMPromptInputs:
    return LLMPromptInputs(
        persona_prompt="p", skill_content="s",
        task_brief_json="{}", rag_snippets=[],
        failure_catalog_summary="c",
    )


@pytest.mark.asyncio
async def test_returns_scripted_proposal():
    mock = MockLLMClient(proposals=[_proposal("scripted_1")])
    out = await mock.generate_code_proposal(_inputs())
    assert out.task_id == "scripted_1"


@pytest.mark.asyncio
async def test_records_calls():
    mock = MockLLMClient(proposals=[_proposal(), _proposal("second")])
    await mock.generate_code_proposal(_inputs())
    await mock.generate_code_proposal(_inputs())
    assert len(mock.calls) == 2


@pytest.mark.asyncio
async def test_raises_if_exhausted():
    mock = MockLLMClient(proposals=[_proposal()])
    await mock.generate_code_proposal(_inputs())
    with pytest.raises(RuntimeError, match="scripted responses exhausted"):
        await mock.generate_code_proposal(_inputs())


@pytest.mark.asyncio
async def test_records_token_usage():
    mock = MockLLMClient(proposals=[_proposal()])
    await mock.generate_code_proposal(_inputs())
    assert mock.total_tokens_in >= 0
    assert mock.total_tokens_out >= 0
