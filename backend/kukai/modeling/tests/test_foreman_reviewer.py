"""Deterministic CodeProposal review (not LLM)."""
from __future__ import annotations
import pytest

from kukai.modeling.foreman.reviewer import review_proposal
from kukai.modeling.schemas.foreman import ReviewSeverity
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult, InlineRagCitation,
)
from kukai.modeling.schemas.resolver import ParameterScope
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, Phase, ParameterRef, TaskBrief, Tier


def _brief(task_id: str = "t1task01", count: int = 1, version: str = "2026") -> TaskBrief:
    return TaskBrief(
        task_id=task_id,
        phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=0, y=0, z=0),
        family_symbol_id=10,
        parameter_map={"width": ParameterRef(name="b", scope="instance")},
        level_id=20,
        revit_version=version,
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=count),
        tier=Tier.TIER_2,
        estimated_cost_usd=0.05,
    )


def _full_failure_checks() -> dict[FailureCategory, FailureCheckResult]:
    return {
        cat: FailureCheckResult(checked=True, applicable=False)
        for cat in FailureCategory
    }


def _proposal(**overrides) -> CodeProposal:
    base = dict(
        task_id="t1task01",
        csharp_code="// RAG:#snip_a\nvar x = 1;",
        explanation="places a column",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column",
        revit_version="2026",
        failure_mode_checks=_full_failure_checks(),
        rag_citations=[InlineRagCitation(snippet_id="snip_a", api_called="Document.Create.NewFamilyInstance")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )
    base.update(overrides)
    return CodeProposal(**base)


def test_review_passes_when_consistent():
    verdict = review_proposal(_proposal(), _brief())
    assert verdict.passed is True
    assert verdict.issues == []


def test_review_blocks_on_task_id_mismatch():
    verdict = review_proposal(_proposal(task_id="WRONG"), _brief())
    assert verdict.passed is False
    cats = {i.category for i in verdict.issues}
    assert "task_id_mismatch" in cats
    assert all(i.severity == ReviewSeverity.BLOCKING for i in verdict.issues if i.category == "task_id_mismatch")


def test_review_blocks_on_version_mismatch():
    verdict = review_proposal(_proposal(revit_version="2025"), _brief(version="2026"))
    assert verdict.passed is False
    assert any(i.category == "version_mismatch" and i.severity == ReviewSeverity.BLOCKING for i in verdict.issues)


def test_review_blocks_on_expected_count_mismatch():
    bad = ExpectedElementsSpec(category="OST_StructuralColumns", count=5)
    verdict = review_proposal(_proposal(expected_elements=bad), _brief(count=1))
    assert verdict.passed is False
    assert any(i.category == "expected_count_mismatch" for i in verdict.issues)


def test_review_blocks_on_expected_category_mismatch():
    bad = ExpectedElementsSpec(category="OST_Walls", count=1)
    verdict = review_proposal(_proposal(expected_elements=bad), _brief())
    assert verdict.passed is False
    assert any(i.category == "expected_category_mismatch" for i in verdict.issues)


def test_review_blocks_on_todo_marker_in_code():
    bad_code = "// TODO: implement\nvar x = 1;"
    verdict = review_proposal(_proposal(csharp_code=bad_code), _brief())
    assert verdict.passed is False
    assert any(i.category == "placeholder_code" for i in verdict.issues)


def test_review_blocks_on_placeholder_text():
    verdict = review_proposal(_proposal(csharp_code="placeholder body"), _brief())
    assert verdict.passed is False
    assert any(i.category == "placeholder_code" for i in verdict.issues)


def test_review_warns_when_questions_to_foreman_present():
    # Wave 6C — Fix A#5: questions_to_foreman is INFO, not blocking.
    # Persona teaches the LLM to use the field for ambiguity escapes; the
    # dispatcher escalates to an operator note instead of refusing dispatch.
    verdict = review_proposal(
        _proposal(questions_to_foreman=["which family?"]),
        _brief(),
    )
    assert verdict.passed is True  # INFO does not block
    q_issues = [i for i in verdict.issues if i.category == "questions_to_foreman"]
    assert len(q_issues) == 1
    assert q_issues[0].severity == ReviewSeverity.INFO


def test_review_blocks_on_empty_assemblies_or_transaction():
    p = _proposal()
    object.__setattr__(p, "transaction_name", "   ")  # bypass Pydantic frozen
    verdict = review_proposal(p, _brief())
    assert verdict.passed is False
    assert any(i.category == "empty_transaction_name" for i in verdict.issues)


def test_review_summary_is_non_empty():
    verdict = review_proposal(_proposal(), _brief())
    assert len(verdict.summary) > 0
