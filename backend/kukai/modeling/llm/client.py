"""LLMClient protocol — abstracts over Gemini Flash / mocks.

Real implementation deferred to Plan 6. Plan 5 only uses MockLLMClient.
"""
from __future__ import annotations
from typing import Protocol

from kukai.modeling.schemas.llm import CodeProposal, LLMPromptInputs


class LLMClient(Protocol):
    """Async LLM client returning structured CodeProposal."""

    async def generate_code_proposal(
        self, inputs: LLMPromptInputs
    ) -> CodeProposal: ...
