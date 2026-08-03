"""Tests for persona + prompt assembly."""
from __future__ import annotations

from kukai.modeling.schemas.llm import LLMPromptInputs
from kukai.modeling.schemas.tasks import ExpectedElementsSpec, ParameterRef, Phase, TaskBrief, Tier
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.subagent.persona import (
    STRUCTURAL_SUBAGENT_PERSONA,
    FAILURE_CATALOG_SUMMARY,
    build_llm_prompt_inputs,
)


def _task_brief() -> TaskBrief:
    return TaskBrief(
        task_id="abc123def456",
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


def test_persona_is_english_and_includes_audit_rules():
    p = STRUCTURAL_SUBAGENT_PERSONA
    # Per spec persona — must mention key concepts
    assert "Structural" in p or "structural" in p
    assert "Transaction" in p
    assert "RAG" in p
    # Negative attestation language
    assert "FailureCategory" in p or "failure_mode_checks" in p
    # ASK over guess
    assert "ASK" in p.upper() or "ask" in p.lower()
    # English-only enforcement
    assert "English" in p


def test_failure_catalog_summary_lists_all_categories():
    s = FAILURE_CATALOG_SUMMARY
    # Per Plan 5 — every FailureCategory must appear by name in summary
    from kukai.modeling.schemas.llm import FailureCategory
    for c in FailureCategory:
        assert c.value in s


def test_build_inputs_includes_task_brief():
    task = _task_brief()
    inputs = build_llm_prompt_inputs(
        task_brief=task,
        skill_content="# columns\nplace at grid intersections",
        rag_snippets=[("snippet1", "NewFamilyInstance", "Use overload XYZ,Symbol,Level,StructuralType.Column")],
    )
    assert isinstance(inputs, LLMPromptInputs)
    assert "abc123def456" in inputs.task_brief_json
    assert inputs.skill_content.startswith("# columns")
    assert len(inputs.rag_snippets) == 1
    # Persona prompt now includes the schema spec appended after the persona
    # (so every LLMClient sees the CodeProposal contract, not just Vertex).
    assert inputs.persona_prompt.startswith(STRUCTURAL_SUBAGENT_PERSONA)
    assert "CodeProposal output JSON schema" in inputs.persona_prompt
    assert inputs.failure_catalog_summary == FAILURE_CATALOG_SUMMARY


def test_build_inputs_serializes_task_brief_as_compact_json():
    task = _task_brief()
    inputs = build_llm_prompt_inputs(
        task_brief=task,
        skill_content="x",
        rag_snippets=[],
    )
    # JSON should be parseable and contain task_id
    import json
    parsed = json.loads(inputs.task_brief_json)
    assert parsed["task_id"] == "abc123def456"
    assert parsed["element_type"] == "structural_column"


# --- CODE_PROPOSAL_SCHEMA_SPEC tests ---

from kukai.modeling.subagent.persona import CODE_PROPOSAL_SCHEMA_SPEC


def test_schema_spec_lists_all_top_level_fields():
    spec = CODE_PROPOSAL_SCHEMA_SPEC
    for field in [
        "task_id", "csharp_code", "explanation", "expected_elements",
        "requires_assemblies", "transaction_name", "revit_version",
        "failure_mode_checks", "rag_citations", "dry_run", "questions_to_foreman",
    ]:
        assert field in spec, f"schema spec missing field {field!r}"


def test_schema_spec_describes_failure_check_shape():
    """The most-violated-in-Plan-6 shape: dict of FailureCategory → {checked,applicable,note}."""
    spec = CODE_PROPOSAL_SCHEMA_SPEC
    assert "FailureCheckResult" in spec or "failure_mode_checks" in spec
    assert "checked" in spec and "applicable" in spec


def test_schema_spec_describes_inline_citation_format():
    spec = CODE_PROPOSAL_SCHEMA_SPEC
    assert "// RAG:#" in spec, "schema spec must show inline citation comment format"


def test_schema_spec_describes_dry_run_units():
    """dry_run.proposed_xyz_mm must say millimeters explicitly (not feet)."""
    spec = CODE_PROPOSAL_SCHEMA_SPEC
    # Must clarify units to prevent Gemini from converting to feet
    assert ("mm" in spec or "millimeter" in spec.lower())


def test_schema_spec_declares_cardinality_must_constraints():
    """Plan 6 review: prevent silent loss of MUST constraints from the old vertex_client spec."""
    spec = CODE_PROPOSAL_SCHEMA_SPEC
    assert "rag_citations" in spec and "non-empty" in spec
    assert "requires_assemblies" in spec
    assert "RevitAPI" in spec
    assert "family_symbol_id" in spec
