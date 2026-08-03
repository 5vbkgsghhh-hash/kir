"""Live Vertex Gemini smoke test — gated by KUKAI_VERTEX_AI_API_KEY env presence.

Does NOT run in CI by default (env-gated). Run manually with creds available.
Validates that VertexGeminiClient + real Gemini Flash returns a parseable
CodeProposal-shaped JSON for a minimal prompt.
"""
from __future__ import annotations
import pytest

from kukai.modeling.llm.env_config import get_vertex_config
from kukai.modeling.llm.vertex_client import VertexGeminiClient
from kukai.modeling.schemas.llm import FailureCategory, LLMPromptInputs
from kukai.modeling.subagent.persona import CODE_PROPOSAL_SCHEMA_SPEC


pytestmark = pytest.mark.skipif(
    not get_vertex_config().available,
    reason="Vertex AI credentials not configured (set KUKAI_VERTEX_AI_*)",
)


def _failure_catalog_summary() -> str:
    lines = ["FailureCategory catalog (you must produce a FailureCheckResult for each):"]
    for c in FailureCategory:
        lines.append(f"  - {c.value}")
    return "\n".join(lines)


@pytest.mark.tier3
@pytest.mark.asyncio
async def test_real_vertex_returns_parseable_code_proposal():
    client = VertexGeminiClient()

    minimal_persona = (
        "You are a structural BIM subagent. Reply with JSON CodeProposal only."
        "\n\n" + CODE_PROPOSAL_SCHEMA_SPEC
    )
    minimal_skill = (
        "# placeholder skill\nPlace a structural column at the given XYZ point. "
        "Use Transaction. Cite each API call inline with `// RAG:#snip_basic`."
    )
    minimal_task = (
        '{"task_id":"smoke_test_001","phase":"structure",'
        '"skill_path":"structure/columns/concrete-columns",'
        '"element_type":"structural_column",'
        '"placement_point":{"x":6000.0,"y":6000.0,"z":0.0},'
        '"family_symbol_id":8821,"parameter_map":{},'
        '"level_id":1042,"top_level_id":1043,"revit_version":"2026",'
        '"expected_elements":{"category":"OST_StructuralColumns","count":1,'
        '"naming_pattern":null,"level_name":"Level 1","required_parameters":[]},'
        '"constraints":[],"tier":"subagent_per_element","is_repair":false,'
        '"repair_for_task_id":null,"estimated_cost_usd":0.0005}'
    )
    snippets = [
        ("snip_basic", "NewFamilyInstance overload",
         "doc.Create.NewFamilyInstance(location, symbol, level, StructuralType.Column)"),
    ]

    inputs = LLMPromptInputs(
        persona_prompt=minimal_persona,
        skill_content=minimal_skill,
        task_brief_json=minimal_task,
        rag_snippets=snippets,
        failure_catalog_summary=_failure_catalog_summary(),
    )

    proposal = await client.generate_code_proposal(inputs)

    # Basic shape assertions
    assert proposal.task_id == "smoke_test_001"
    assert proposal.csharp_code, "code must not be empty"
    assert "Transaction" in proposal.csharp_code, "Gemini should produce transactional code"
    # Negative attestation present for all FailureCategory values
    for cat in FailureCategory:
        assert cat in proposal.failure_mode_checks, f"missing attestation for {cat}"
    # Inline citation appears at least once
    assert "// RAG:#" in proposal.csharp_code, "Gemini must place inline RAG citations"

    print("\n=== GENERATED CODE ===\n")
    print(proposal.csharp_code)
    print("\n=== END ===\n")
