"""End-to-end vertical slice with REAL Vertex Gemini.

Gated by KUKAI_VERTEX_AI_* env presence. Does:
1. Build a realistic TaskBrief for "place RC column at grid 2B level +0.000"
2. Load the real concrete-columns.md skill content
3. Provide three retrieved RAG snippets (handcrafted, representing what kukai.rag would return)
4. Call StructuralSubagent (from Plan 5) backed by VertexGeminiClient
5. Validate the returned CodeProposal: task_id matches, citations validate, schema strict
6. Print generated C# for human inspection

This is the answer to systematic-debugging Phase 3 hypothesis:
"Does real Gemini Flash, given persona + skill + RAG, actually produce valid C#?"
"""
from __future__ import annotations
import pytest

from kukai.modeling.llm.env_config import get_vertex_config
from kukai.modeling.llm.vertex_client import VertexGeminiClient
from kukai.modeling.schemas.identifiers import XYZ, deterministic_task_uuid
from kukai.modeling.schemas.llm import FailureCategory
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, ParameterRef, Phase, TaskBrief, Tier,
)
from kukai.modeling.subagent.skill_loader import SkillLoader
from kukai.modeling.subagent.structural import StructuralSubagent


pytestmark = pytest.mark.skipif(
    not get_vertex_config().available,
    reason="Vertex AI credentials not configured (set KUKAI_VERTEX_AI_*)",
)


REALISTIC_RAG_SNIPPETS = [
    (
        "snip_column_basic",
        "Document.Create.NewFamilyInstance — column overload",
        "FamilyInstance NewFamilyInstance(XYZ location, FamilySymbol symbol, "
        "Level level, StructuralType structuralType). Creates a non-hosted family "
        "instance of a structural column at the specified location on the specified level.",
    ),
    (
        "snip_column_top_level",
        "SCHEDULE_TOP_LEVEL_PARAM for structural columns",
        "BuiltInParameter.SCHEDULE_TOP_LEVEL_PARAM controls the top constraint of a "
        "structural column when bound to a higher level. Setting it via "
        "col.get_Parameter(BuiltInParameter.SCHEDULE_TOP_LEVEL_PARAM).Set(topLevel.Id) "
        "binds the column top to that level's elevation.",
    ),
    (
        "snip_symbol_activate",
        "FamilySymbol.Activate must be followed by Document.Regenerate",
        "if (!symbol.IsActive) { symbol.Activate(); doc.Regenerate(); } — after "
        "activating a previously-inactive symbol, you MUST call doc.Regenerate() "
        "before using it for placement in the same transaction.",
    ),
]


@pytest.mark.tier3
@pytest.mark.asyncio
async def test_vertical_slice_real_gemini_places_column():
    """Real Gemini Flash + real skill content + realistic RAG → valid CodeProposal."""
    # 1. Build TaskBrief (fully-resolved as Resolver would have done)
    task_id = deterministic_task_uuid("vertical_slice_test", "structure", 1)
    task_brief = TaskBrief(
        task_id=task_id,
        phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns",
        element_type="structural_column",
        placement_point=XYZ(x=6000.0, y=6000.0, z=0.0),
        family_symbol_id=8821,
        parameter_map={
            "mark": ParameterRef(name="ALL_MODEL_MARK", scope="built_in"),
        },
        level_id=1042,
        top_level_id=1043,
        revit_version="2026",
        expected_elements=ExpectedElementsSpec(
            category="OST_StructuralColumns",
            count=1,
            naming_pattern=None,
            level_name="Level 1",
            required_parameters=["Mark"],
        ),
        tier=Tier.TIER_2,
        estimated_cost_usd=0.001,
    )

    # 2. Load real skill content
    loader = SkillLoader()
    skill_content = loader.load("modeling/structure/columns/concrete-columns")
    assert "Concrete Columns Placement Methodology" in skill_content

    # 3. Real Gemini + StructuralSubagent
    llm = VertexGeminiClient()
    subagent = StructuralSubagent(llm)

    # 4. Run vertical slice
    proposal = await subagent.generate_code(
        task_brief=task_brief,
        skill_content=skill_content,
        rag_snippets=REALISTIC_RAG_SNIPPETS,
    )

    # 5. Validate
    assert proposal.task_id == task_id
    assert proposal.revit_version == "2026"
    assert "Transaction" in proposal.csharp_code
    assert "UnitUtils.ConvertToInternalUnits" in proposal.csharp_code
    assert "NewFamilyInstance" in proposal.csharp_code
    assert "__result__" in proposal.csharp_code
    # Inline citations refer to at least one of our snippets
    cited_inline = set()
    for line in proposal.csharp_code.splitlines():
        if "RAG:#" in line:
            for sid, _, _ in REALISTIC_RAG_SNIPPETS:
                if sid in line:
                    cited_inline.add(sid)
    assert cited_inline, f"no recognised RAG snippet citations inline; code: {proposal.csharp_code[:400]}"
    # Failure-mode catalog complete (negative attestation)
    for cat in FailureCategory:
        assert cat in proposal.failure_mode_checks

    # 6. Print for human inspection
    print("\n\n=== GENERATED REVIT C# (real Vertex Gemini Flash) ===\n")
    print(proposal.csharp_code)
    print("\n=== EXPLANATION ===\n")
    print(proposal.explanation)
    print("\n=== DRY-RUN SUMMARY ===\n")
    print(f"selected_symbol_id: {proposal.dry_run.selected_symbol_id}")
    print(f"proposed_xyz_mm: {proposal.dry_run.proposed_xyz_mm}")
    print(f"params_to_set: {proposal.dry_run.params_to_set}")
    print("\n=== RAG CITATIONS DECLARED ===\n")
    for cit in proposal.rag_citations:
        print(f"  {cit.snippet_id} -> {cit.api_called}")
    print("\n=== END ===\n")
