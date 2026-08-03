"""MockLLMClient — scripted responses for tests."""
from __future__ import annotations
from typing import Any

from kukai.modeling.schemas.llm import CodeProposal, LLMPromptInputs


class MockLLMClient:
    """Returns scripted CodeProposal responses in order; raises when exhausted."""

    def __init__(self, proposals: list[CodeProposal] | None = None):
        self._proposals = proposals or []
        self._idx = 0
        self.calls: list[dict[str, Any]] = []
        self.total_tokens_in = 0
        self.total_tokens_out = 0

    def queue_proposal(self, proposal: CodeProposal) -> None:
        """Append a CodeProposal to the scripted response queue (test convenience).

        Used when test setup constructs MockLLMClient first, then queues
        proposals after Foreman/Subagent wiring is built.
        """
        self._proposals.append(proposal)

    async def generate_code_proposal(
        self, inputs: LLMPromptInputs
    ) -> CodeProposal:
        # Approximate token usage from prompt size (testing instrumentation only)
        tokens_in = (
            len(inputs.persona_prompt) + len(inputs.skill_content)
            + len(inputs.task_brief_json) + len(inputs.failure_catalog_summary)
            + sum(len(t) + len(b) for _, t, b in inputs.rag_snippets)
        ) // 4
        self.total_tokens_in += tokens_in
        self.calls.append({
            "tokens_in": tokens_in,
            "skill_content_len": len(inputs.skill_content),
            "rag_count": len(inputs.rag_snippets),
        })
        if self._idx >= len(self._proposals):
            raise RuntimeError(
                f"MockLLMClient scripted responses exhausted after {self._idx} calls"
            )
        proposal = self._proposals[self._idx]
        self._idx += 1
        self.total_tokens_out += len(proposal.csharp_code) // 4
        return proposal
