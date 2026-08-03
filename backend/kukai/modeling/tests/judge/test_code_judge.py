"""Tests for CodeJudge — LLM-as-Judge offline harness."""
from __future__ import annotations
import json

import pytest
from pydantic import ValidationError

from kukai.modeling.judge.code_judge import CodeJudge
from kukai.modeling.schemas.identifiers import XYZ
from kukai.modeling.schemas.judge import JudgeSeverity, JudgeVerdict
from kukai.modeling.schemas.llm import (
    CodeProposal, DryRunSummary, FailureCategory, FailureCheckResult,
    InlineRagCitation,
)
from kukai.modeling.schemas.tasks import (
    ExpectedElementsSpec, ParameterRef, Phase, TaskBrief, Tier,
)


def _checks():
    return {c: FailureCheckResult(checked=True, applicable=False) for c in FailureCategory}


def _brief() -> TaskBrief:
    return TaskBrief(
        task_id="t1task01",
        phase=Phase.STRUCTURE,
        skill_path="modeling/structure/columns/concrete-columns.md",
        element_type="structural_column",
        placement_point=XYZ(x=0, y=0, z=0),
        family_symbol_id=10,
        parameter_map={"width": ParameterRef(name="b", scope="instance")},
        level_id=20,
        revit_version="2026",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        tier=Tier.TIER_2,
        estimated_cost_usd=0.05,
    )


def _proposal() -> CodeProposal:
    return CodeProposal(
        task_id="t1task01",
        csharp_code="// RAG:#s\n__result__ = new int[] { 1 };",
        explanation="x",
        expected_elements=ExpectedElementsSpec(category="OST_StructuralColumns", count=1),
        requires_assemblies=["RevitAPI"],
        transaction_name="Place column",
        revit_version="2026",
        failure_mode_checks=_checks(),
        rag_citations=[InlineRagCitation(snippet_id="s", api_called="X")],
        dry_run=DryRunSummary(selected_symbol_id=10, proposed_xyz_mm=(0.0, 0.0, 0.0)),
    )


class _RawTextLLM:
    """Minimal mock LLM that returns a pre-scripted raw JSON string."""

    def __init__(self, raw_responses: list[str]):
        self._raw = raw_responses
        self._idx = 0
        self.calls: list[str] = []

    async def generate_raw_text(self, prompt: str) -> str:
        self.calls.append(prompt)
        if self._idx >= len(self._raw):
            raise RuntimeError("scripted responses exhausted")
        response = self._raw[self._idx]
        self._idx += 1
        return response


def _verdict_json(**overrides) -> str:
    base = {
        "score": 5, "errors_detected": [], "severity": "none",
        "suggestions": [], "judge_explanation": "Code is idiomatic and complete.",
    }
    base.update(overrides)
    return json.dumps(base)


async def _run_judge(raw: str):
    llm = _RawTextLLM([raw])
    return llm, await CodeJudge(llm=llm).judge(_proposal(), _brief())


@pytest.mark.asyncio
async def test_judge_returns_high_score_for_clean_code():
    _, verdict = await _run_judge(_verdict_json(score=5, severity="none"))
    assert verdict.score == 5
    assert verdict.severity == JudgeSeverity.NONE
    assert verdict.errors_detected == []


@pytest.mark.asyncio
async def test_judge_flags_unit_mismatch():
    _, verdict = await _run_judge(_verdict_json(
        score=2, severity="high",
        errors_detected=["unit_mismatch", "missing_null_guard"],
        suggestions=["Use Millimeters.", "Null-check GetElement."],
    ))
    assert verdict.score == 2
    assert FailureCategory.UNIT_MISMATCH in verdict.errors_detected
    assert FailureCategory.MISSING_NULL_GUARD in verdict.errors_detected
    assert verdict.severity == JudgeSeverity.HIGH


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_payload", [
    {"score": 6},                                              # out of range high
    {"score": 0},                                              # out of range low
    {"errors_detected": ["not_a_real_category"], "score": 3},  # unknown category
])
async def test_judge_rejects_invalid_payloads(bad_payload):
    raw = _verdict_json(**bad_payload)
    with pytest.raises(ValidationError):
        await _run_judge(raw)


@pytest.mark.asyncio
async def test_judge_prompt_includes_taxonomy_brief_and_code():
    llm, _ = await _run_judge(_verdict_json())
    sent = llm.calls[0]
    assert "t1task01" in sent           # brief JSON appears
    assert "__result__" in sent          # code appears
    assert "silent_no_op" in sent        # taxonomy appears
    assert "scope_creep" in sent


@pytest.mark.asyncio
async def test_judge_prompt_includes_all_phase1_new_categories():
    """Regression: prompt must reference every Phase 1 new category."""
    llm, _ = await _run_judge(_verdict_json())
    sent = llm.calls[0]
    for new_cat in [
        "silent_no_op", "idempotency_violation", "scope_creep",
        "cross_discipline_contamination", "view_dependent_filter_failure",
        "parallel_safety_violation",
    ]:
        assert new_cat in sent, f"prompt missing taxonomy entry for {new_cat!r}"


@pytest.mark.asyncio
async def test_judge_parses_code_fence_wrapped_json():
    """LLMs often wrap JSON in ```json fences — parser must strip them."""
    raw = "```json\n" + _verdict_json(score=4, severity="low") + "\n```"
    _, verdict = await _run_judge(raw)
    assert verdict.score == 4
    assert verdict.severity == JudgeSeverity.LOW


@pytest.mark.asyncio
async def test_judge_parses_uppercase_json_fence():
    """LLMs sometimes use ```JSON (uppercase) — extractor must still find the object."""
    raw = "```JSON\n" + _verdict_json(
        score=3, severity="medium",
        errors_detected=["unit_mismatch"],
        suggestions=["Use Millimeters."],
    ) + "\n```"
    _, verdict = await _run_judge(raw)
    assert verdict.score == 3
    assert verdict.severity == JudgeSeverity.MEDIUM


@pytest.mark.asyncio
async def test_judge_parses_prose_wrapped_json():
    """Gemini Pro thinking mode prefixes verdicts with prose — extractor must skip it."""
    raw = (
        "I have analyzed the proposal step by step.\n\n"
        + _verdict_json(score=2, severity="high",
                        errors_detected=["unit_mismatch"],
                        suggestions=["Use Millimeters."])
        + "\n\nThat is my final verdict."
    )
    _, verdict = await _run_judge(raw)
    assert verdict.score == 2
    assert FailureCategory.UNIT_MISMATCH in verdict.errors_detected


@pytest.mark.asyncio
async def test_judge_raises_value_error_on_empty_response():
    """Defense: empty LLM response surfaces a clear ValueError, not opaque JSONDecodeError."""
    with pytest.raises(ValueError, match="empty"):
        await _run_judge("")


@pytest.mark.asyncio
async def test_judge_raises_value_error_when_no_json_object():
    """Defense: response with no `{...}` surfaces a clear ValueError."""
    with pytest.raises(ValueError, match="no .*JSON object"):
        await _run_judge("I have no opinion.")


@pytest.mark.asyncio
async def test_judge_handles_thinking_prefix_then_verdict_object():
    """Audit N8: when LLM emits two JSON objects (thinking trace + verdict),
    raw_decode picks the FIRST valid one. Tests intentionally place a valid
    thinking object before the verdict — the legacy find('{') + rfind('}')
    approach would mis-parse the union as one giant invalid object."""
    thinking = '{"thinking": "Let me analyze step by step...", "step": 1}'
    verdict = _verdict_json(score=4, severity="low")
    raw = thinking + "\n\n" + verdict
    # _extract_json_object must pick the first parseable object.
    from kukai.modeling.judge.code_judge import _extract_json_object
    extracted = _extract_json_object(raw)
    assert extracted == thinking, f"expected first object, got: {extracted!r}"
    # And feeding it to json.loads must succeed.
    assert json.loads(extracted)["step"] == 1


@pytest.mark.tier0
def test_judge_verdict_rejects_low_score_no_errors():
    """Audit N13: score<4 with empty errors_detected is self-contradiction."""
    with pytest.raises(ValidationError, match="errors_detected"):
        JudgeVerdict(
            score=2, errors_detected=[], severity=JudgeSeverity.MEDIUM,
            suggestions=[], judge_explanation="vague",
        )


@pytest.mark.tier0
def test_judge_verdict_rejects_high_score_critical_severity():
    """Audit N13: score=5 with severity CRITICAL is self-contradiction."""
    with pytest.raises(ValidationError, match="ship-it"):
        JudgeVerdict(
            score=5, errors_detected=[], severity=JudgeSeverity.CRITICAL,
            suggestions=[], judge_explanation="contradictory verdict",
        )


def test_judge_blurb_dict_covers_all_failure_categories():
    """Defense: every FailureCategory must have a non-empty blurb (curated or fallback)."""
    from kukai.modeling.judge.code_judge import _BLURBS
    from kukai.modeling.schemas.llm import FailureCategory

    for category in FailureCategory:
        assert category in _BLURBS, f"missing blurb for {category!r}"
        assert _BLURBS[category], f"empty blurb for {category!r}"
