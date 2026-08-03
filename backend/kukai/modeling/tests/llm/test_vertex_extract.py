"""Audit N6 — _extract_text surfaces non-STOP finishReason as a typed error."""
from __future__ import annotations
import pytest

from kukai.modeling.llm.vertex_client import _extract_text, VertexFinishReasonError


@pytest.mark.tier0
def test_extract_text_surfaces_safety_finish_reason():
    """SAFETY-blocked Gemini response must raise VertexFinishReasonError, not return ''."""
    response = {
        "candidates": [
            {
                "content": {"parts": []},
                "finishReason": "SAFETY",
                "safetyRatings": [
                    {"category": "HARM_CATEGORY_VIOLENCE", "probability": "HIGH"},
                ],
            }
        ]
    }
    with pytest.raises(VertexFinishReasonError) as ei:
        _extract_text(response)
    assert ei.value.reason == "SAFETY"
    assert "HARM_CATEGORY_VIOLENCE" in str(ei.value)


@pytest.mark.tier0
def test_extract_text_returns_empty_for_no_candidates():
    """No candidates at all → return empty string (preserves prior contract)."""
    assert _extract_text({}) == ""
    assert _extract_text({"candidates": []}) == ""


@pytest.mark.tier0
def test_extract_text_normal_stop_returns_text():
    """STOP finishReason with text content returns the text."""
    response = {
        "candidates": [
            {
                "content": {"parts": [{"text": "hello world"}]},
                "finishReason": "STOP",
            }
        ]
    }
    assert _extract_text(response) == "hello world"


@pytest.mark.tier0
def test_extract_text_max_tokens_returns_empty_not_error():
    """MAX_TOKENS with empty parts: legitimate truncation, returns '' not error."""
    response = {
        "candidates": [
            {"content": {"parts": []}, "finishReason": "MAX_TOKENS"}
        ]
    }
    assert _extract_text(response) == ""


@pytest.mark.tier0
def test_extract_text_recitation_surfaces():
    """RECITATION finishReason also raises (not in STOP/MAX_TOKENS allowlist)."""
    response = {
        "candidates": [
            {"content": {"parts": []}, "finishReason": "RECITATION"}
        ]
    }
    with pytest.raises(VertexFinishReasonError) as ei:
        _extract_text(response)
    assert ei.value.reason == "RECITATION"
