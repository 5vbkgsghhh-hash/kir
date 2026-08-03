"""StructuralSubagent — generates C# code for a single Structural task.

Per spec Section 5.4. The optional repair_context is forwarded to the prompt
builder so the LLM sees the previous attempt's diagnostics + verbal reflection.
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from kukai.modeling.llm.client import LLMClient
from kukai.modeling.schemas.llm import CodeProposal
from kukai.modeling.schemas.tasks import TaskBrief
from kukai.modeling.subagent.citations import normalize_inline_citations, validate_citations
from kukai.modeling.subagent.persona import build_llm_prompt_inputs

if TYPE_CHECKING:
    from kukai.modeling.foreman.repair_loop import RepairContext


class StructuralSubagent:
    """Subagent specialized for structural elements."""

    def __init__(self, llm: LLMClient):
        self._llm = llm

    @property
    def llm(self) -> LLMClient:
        return self._llm

    async def generate_code(
        self, *, task_brief: TaskBrief, skill_content: str,
        rag_snippets: list[tuple[str, str, str]],
        repair_context: "RepairContext | None" = None,
    ) -> CodeProposal:
        inputs = build_llm_prompt_inputs(
            task_brief=task_brief, skill_content=skill_content,
            rag_snippets=rag_snippets, repair_context=repair_context,
        )
        proposal = await self._llm.generate_code_proposal(inputs)
        # Defensively terminate inline `// RAG:#id` citations with a newline so a
        # single-line emission can't comment out the rest of the body (see
        # normalize_inline_citations). Done BEFORE validation so INV/compile/exec
        # all see the same recovered code.
        if proposal.csharp_code and not proposal.questions_to_foreman:
            fixed = normalize_inline_citations(proposal.csharp_code)
            if fixed != proposal.csharp_code:
                proposal = proposal.model_copy(update={"csharp_code": fixed})
        self._validate(proposal, task_brief, rag_snippets)
        return proposal

    @staticmethod
    def _validate(proposal: CodeProposal, task_brief: TaskBrief,
                  rag_snippets: list[tuple[str, str, str]]) -> None:
        if proposal.task_id != task_brief.task_id:
            raise ValueError(f"task_id mismatch: brief={task_brief.task_id!r} proposal={proposal.task_id!r}")
        if proposal.revit_version != task_brief.revit_version:
            raise ValueError(f"revit_version mismatch: brief={task_brief.revit_version!r} proposal={proposal.revit_version!r}")
        if proposal.questions_to_foreman:
            return
        retrieved_ids = {sid for sid, _, _ in rag_snippets}
        validate_citations(code=proposal.csharp_code, cited=proposal.rag_citations,
                           retrieved_snippet_ids=retrieved_ids)
