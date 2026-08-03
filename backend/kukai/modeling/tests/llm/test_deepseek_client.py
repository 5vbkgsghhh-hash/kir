"""Unit tests for DeepSeekModelingClient — provider-pin + JSON-mode kwargs and the
H-3 robust parser (strips <think>, fences, trailing prose). litellm is mocked.
"""
import json
import types

import pytest

import kukai.modeling.llm.deepseek_client as dc
from kukai.modeling.llm.deepseek_client import (
    DeepSeekModelingClient,
    _parse_code_proposal_robust,
)
from kukai.modeling.schemas.llm import CodeProposal, FailureCategory, LLMPromptInputs
from kukai.modeling.subagent.persona import SCHEMA_SPEC_MARKER


def _valid_proposal_json() -> str:
    checks = {c.value: {"checked": True, "applicable": False, "note": None} for c in FailureCategory}
    return json.dumps({
        "task_id": "t1",
        "csharp_code": "// RAG:#a\nusing(var t=new Transaction(doc,\"x\")){t.Start();t.Commit();}\n__result__ = new int[]{9000};",
        "explanation": "place one column",
        "expected_elements": {"category": "OST_StructuralColumns", "count": 1},
        "requires_assemblies": ["RevitAPI"],
        "transaction_name": "x",
        "revit_version": "2026",
        "failure_mode_checks": checks,
        "rag_citations": [{"snippet_id": "a", "api_called": "NewFamilyInstance"}],
        "dry_run": {"selected_symbol_id": 10, "proposed_xyz_mm": [0.0, 0.0, 0.0]},
    })


def _resp(content: str):
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))]
    )


def _inputs() -> LLMPromptInputs:
    return LLMPromptInputs(
        persona_prompt="...\n" + SCHEMA_SPEC_MARKER + "\n...",
        skill_content="skill", task_brief_json="{}",
        rag_snippets=[("a", "title", "body")], failure_catalog_summary="catalog",
    )


def _patch(monkeypatch, content: str, captured: dict):
    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        return _resp(content)
    monkeypatch.setattr(dc.litellm, "acompletion", fake_acompletion)


@pytest.mark.asyncio
async def test_provider_pin_jsonmode_and_valid_parse(monkeypatch):
    captured: dict = {}
    _patch(monkeypatch, _valid_proposal_json(), captured)
    c = DeepSeekModelingClient(model="openrouter/deepseek/deepseek-v4-flash", api_key="k")
    proposal = await c.generate_code_proposal(_inputs())
    assert isinstance(proposal, CodeProposal) and proposal.task_id == "t1"
    assert captured["response_format"] == {"type": "json_object"}
    eb = captured["extra_body"]
    assert eb["provider"]["order"] == ["DeepInfra", "Novita", "AtlasCloud"]
    assert eb["provider"]["allow_fallbacks"] is False
    assert eb["reasoning"]["effort"] == "high"
    assert len(c.calls) == 1  # budget-guard contract


@pytest.mark.asyncio
async def test_no_provider_pin_for_non_openrouter(monkeypatch):
    captured: dict = {}
    _patch(monkeypatch, _valid_proposal_json(), captured)
    c = DeepSeekModelingClient(model="gpt-4o-mini", api_key="k")
    await c.generate_code_proposal(_inputs())
    assert "extra_body" not in captured  # pin only for openrouter/* models


@pytest.mark.asyncio
async def test_empty_response_raises(monkeypatch):
    _patch(monkeypatch, "", {})
    c = DeepSeekModelingClient(model="openrouter/deepseek/deepseek-v4-flash", api_key="k")
    with pytest.raises(RuntimeError, match="empty"):
        await c.generate_code_proposal(_inputs())


def test_parser_strips_think_and_json_fence():
    raw = "<think>let me reason about units...</think>\n```json\n" + _valid_proposal_json() + "\n```"
    assert _parse_code_proposal_robust(raw).task_id == "t1"


def test_parser_greedy_extracts_trailing_prose():
    raw = "<think>reasoning</think>\nHere is the proposal: " + _valid_proposal_json() + "\nDone — hope it helps!"
    assert _parse_code_proposal_robust(raw).task_id == "t1"


def test_parser_bare_json():
    assert _parse_code_proposal_robust(_valid_proposal_json()).task_id == "t1"
