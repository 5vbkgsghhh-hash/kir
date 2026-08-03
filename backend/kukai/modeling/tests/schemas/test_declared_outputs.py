"""DeclaredOutputs is the Subagent's TDD attestation of what its code WILL produce.

Per Phase 4 Task 1 (VeriMAP pattern): the Subagent commits to a typed contract
BEFORE generating code, and the Foreman evaluates that contract after execute.
"""
from __future__ import annotations
import pytest
from pydantic import ValidationError

from kukai.modeling.schemas.llm import DeclaredOutputs


def test_declared_outputs_minimal_construction():
    d = DeclaredOutputs(expected_element_count=1, expected_category="OST_StructuralColumns")
    assert d.expected_element_count == 1
    assert d.expected_category == "OST_StructuralColumns"
    assert d.expected_parameter_values == {}
    assert d.expected_level_name is None
    assert d.expected_family_name is None


def test_declared_outputs_full_construction():
    d = DeclaredOutputs(
        expected_element_count=2,
        expected_category="OST_Walls",
        expected_parameter_values={"Width": "200", "Comments": "exterior"},
        expected_level_name="L1",
        expected_family_name="Generic Wall 200mm",
    )
    assert d.expected_parameter_values["Width"] == "200"
    assert d.expected_level_name == "L1"
    assert d.expected_family_name == "Generic Wall 200mm"


def test_declared_outputs_negative_count_rejected():
    with pytest.raises(ValidationError):
        DeclaredOutputs(expected_element_count=-1, expected_category="OST_Walls")


def test_declared_outputs_no_sentinel_pattern():
    """Fix G: DeclaredOutputs has no empty() / is_empty sentinel — pass None
    on CodeProposal.declared_outputs to mean 'not declared'. expected_category
    must be non-empty (min_length=1)."""
    from pydantic import ValidationError
    # Empty category is no longer permitted (no sentinel; min_length=1).
    with pytest.raises(ValidationError):
        DeclaredOutputs(expected_element_count=0, expected_category="")
    # A normal construction works and has no .is_empty attribute.
    real = DeclaredOutputs(expected_element_count=1, expected_category="OST_Walls")
    assert not hasattr(real, "is_empty")
    assert not hasattr(DeclaredOutputs, "empty")


def test_declared_outputs_frozen():
    d = DeclaredOutputs(expected_element_count=1, expected_category="OST_StructuralColumns")
    with pytest.raises(ValidationError):
        d.expected_element_count = 2  # type: ignore[misc]


def test_code_proposal_carries_declared_outputs():
    from kukai.modeling.schemas.llm import (
        CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult,
        InlineRagCitation,
    )
    from kukai.modeling.schemas.tasks import ExpectedElementsSpec

    checks = {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}
    p = CodeProposal(
        task_id="t1task01", csharp_code="// stub", explanation="x",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"], transaction_name="Place column",
        revit_version="2026", failure_mode_checks=checks,
        rag_citations=[InlineRagCitation(snippet_id="s", api_called="X")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
        declared_outputs=DeclaredOutputs(
            expected_element_count=1, expected_category="OST_StructuralColumns"),
    )
    assert p.declared_outputs.expected_element_count == 1
