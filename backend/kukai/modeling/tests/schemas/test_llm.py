"""Tests for LLM-output schemas (CodeProposal etc)."""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.llm import (
    CodeProposal,
    DryRunSummary,
    FailureCategory,
    FailureCheckResult,
    InlineRagCitation,
    LLMPromptInputs,
)
from kukai.modeling.schemas.tasks import ExpectedElementsSpec


def _failure_checks_filled() -> dict[FailureCategory, FailureCheckResult]:
    """Helper: produce a fully-attested checklist (all categories considered)."""
    return {
        cat: FailureCheckResult(checked=True, applicable=False, note=None)
        for cat in FailureCategory
    }


class TestFailureCategory:
    def test_all_audit_categories_present(self):
        names = {c.value for c in FailureCategory}
        # Per spec audit catalog — at minimum these 15 must be present
        required = {
            "unit_mismatch", "parameter_name_drift", "family_not_activated",
            "transaction_nesting", "missing_null_guard", "stale_element_id",
            "wrong_namespace", "duplicate_mark", "wrong_host_category",
            "wrong_level_binding", "geometry_out_of_range",
            "invalid_overload_selection", "missing_regenerate",
            "cyrillic_name_match", "version_api_mismatch",
        }
        missing = required - names
        assert not missing, f"missing failure categories: {missing}"


class TestFailureCheckResult:
    def test_creates(self):
        r = FailureCheckResult(checked=True, applicable=True, note="all good")
        assert r.checked is True

    def test_note_optional(self):
        r = FailureCheckResult(checked=True, applicable=False)
        assert r.note is None


class TestInlineRagCitation:
    def test_creates(self):
        c = InlineRagCitation(snippet_id="rag_42", api_called="NewFamilyInstance")
        assert c.snippet_id == "rag_42"


class TestDryRunSummary:
    def test_creates(self):
        d = DryRunSummary(
            selected_symbol_id=8821,
            proposed_xyz_mm=(6000.0, 6000.0, 0.0),
            params_to_set={"Mark": "C-1A"},
        )
        assert d.selected_symbol_id == 8821
        assert d.params_to_set["Mark"] == "C-1A"


class TestCodeProposal:
    def test_minimal_valid(self):
        p = CodeProposal(
            task_id="t1",
            csharp_code="// RAG:#rag_42\nvar x = 1;",
            explanation="placeholder",
            expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
            requires_assemblies=["RevitAPI"],
            transaction_name="Test",
            revit_version="2026",
            failure_mode_checks=_failure_checks_filled(),
            additional_concern=None,
            rag_citations=[InlineRagCitation(snippet_id="rag_42", api_called="NewFamilyInstance")],
            dry_run=DryRunSummary(
                selected_symbol_id=8821,
                proposed_xyz_mm=(0.0, 0.0, 0.0),
                params_to_set={},
            ),
            questions_to_foreman=[],
        )
        assert p.task_id == "t1"

    def test_questions_to_foreman_default_empty(self):
        p = CodeProposal(
            task_id="t1",
            csharp_code="// RAG:#rag_42\nvar x = 1;",
            explanation="x",
            expected_elements=ExpectedElementsSpec(category="OST_Walls", count=1),
            requires_assemblies=["RevitAPI"],
            transaction_name="Tx",
            revit_version="2026",
            failure_mode_checks=_failure_checks_filled(),
            rag_citations=[InlineRagCitation(snippet_id="rag_42", api_called="X")],
            dry_run=DryRunSummary(
                selected_symbol_id=1, proposed_xyz_mm=(0, 0, 0), params_to_set={},
            ),
        )
        assert p.questions_to_foreman == []

    def test_rejects_empty_code(self):
        with pytest.raises(ValidationError):
            CodeProposal(
                task_id="t1",
                csharp_code="",
                explanation="x",
                expected_elements=ExpectedElementsSpec(category="OST_Walls", count=1),
                requires_assemblies=["RevitAPI"],
                transaction_name="Tx",
                revit_version="2026",
                failure_mode_checks=_failure_checks_filled(),
                rag_citations=[],
                dry_run=DryRunSummary(
                    selected_symbol_id=1, proposed_xyz_mm=(0, 0, 0), params_to_set={},
                ),
            )

    def test_failure_mode_checks_required_for_all_categories(self):
        """Negative attestation requires every category be either checked-and-applicable or checked-and-not-applicable."""
        incomplete = {FailureCategory.UNIT_MISMATCH: FailureCheckResult(checked=True, applicable=False)}
        with pytest.raises(ValidationError, match="failure_mode_checks must cover all"):
            CodeProposal(
                task_id="t1",
                csharp_code="// RAG:#x\nvar x = 1;",
                explanation="x",
                expected_elements=ExpectedElementsSpec(category="OST_Walls", count=1),
                requires_assemblies=["RevitAPI"],
                transaction_name="Tx",
                revit_version="2026",
                failure_mode_checks=incomplete,
                rag_citations=[InlineRagCitation(snippet_id="x", api_called="y")],
                dry_run=DryRunSummary(
                    selected_symbol_id=1, proposed_xyz_mm=(0, 0, 0), params_to_set={},
                ),
            )


class TestLLMPromptInputs:
    def test_creates(self):
        inputs = LLMPromptInputs(
            persona_prompt="You are a structural subagent",
            skill_content="# columns\nplace columns at grid intersections",
            task_brief_json='{"task_id":"t1"}',
            rag_snippets=[("rag_42", "NewFamilyInstance docs", "...")],
            failure_catalog_summary="check transactions, units, ...",
        )
        assert inputs.skill_content.startswith("# columns")
        assert len(inputs.rag_snippets) == 1


def test_failure_category_has_21_values():
    """Phase 1 task 1.1 extension — guards against accidental removal of any of the 6 new categories."""
    from kukai.modeling.schemas.llm import FailureCategory
    assert len(list(FailureCategory)) == 21
    assert "silent_no_op" in {c.value for c in FailureCategory}
    assert "idempotency_violation" in {c.value for c in FailureCategory}
    assert "scope_creep" in {c.value for c in FailureCategory}
    assert "cross_discipline_contamination" in {c.value for c in FailureCategory}
    assert "view_dependent_filter_failure" in {c.value for c in FailureCategory}
    assert "parallel_safety_violation" in {c.value for c in FailureCategory}
