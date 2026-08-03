"""RagReranker — promotes the most-useful 5 of 20 retrieved entries to the top.

Pre-validated 2026-05-11 on 200 audit_500 ground-truth queries:
  hit@3 62.5% → 79.0% (+16.5pp)
  hit@5 71.5% → 88.0% (+16.5pp)
  HARD-tier hit@3 68% → 92% (+24pp)
  200/200 reranks succeeded via hybrid Vertex→Studio routing.

Latency: ~700ms p50 parallel @ thinkingLevel=medium.

Output JSON contract (see prompts/rag_reranker.md):
  {"top_5_indices": [int×5 unique within [0,20)], "reasoning": "1-line"}
"""
from __future__ import annotations

import json
from typing import Any, Sequence

from .base import AgentBase, parse_json_block


_NUM_CANDIDATES_EXPECTED = 20
_TOP_K = 5


class RagReranker(AgentBase):
    """Re-rank top-20 RAG retrieval into top-5 + rest."""

    name = "rag_reranker"
    model = "gemini-3.5-flash"
    thinking_level = "medium"
    max_tokens = 64000  # no cap per Token budget policy
    timeout_s = 8.0     # parallel pre-flight stage budget
    prompt_file = "rag_reranker"

    def build_user_message(
        self,
        query_ru: str,
        query_en: str,
        candidates: Sequence[dict],
        intent_metadata: dict | None = None,
        revit_version: str = "2024",
    ) -> str:
        """Serialize input as JSON-friendly listing the LLM can parse."""
        cands = list(candidates)[:_NUM_CANDIDATES_EXPECTED]
        lines = []
        for i, c in enumerate(cands):
            type_ = c.get("type") or c.get("entry_type") or "class"
            ns = c.get("namespace") or c.get("ns") or ""
            name = c.get("name") or "?"
            desc = (c.get("description") or c.get("desc") or "")[:200]
            has_ex = bool(c.get("has_executable_examples", False))
            ex_tag = " [+example]" if has_ex else ""
            lines.append(f"{i}: {type_} {ns}.{name}{ex_tag}  (desc: {desc})")
        intent_blob = ""
        if intent_metadata:
            try:
                intent_blob = (
                    f"Intent metadata: {json.dumps(intent_metadata, ensure_ascii=False)}\n"
                )
            except (TypeError, ValueError):
                intent_blob = ""
        return (
            f"Query (Russian): {(query_ru or '')[:300]}\n"
            f"Query (English): {(query_en or '')[:300]}\n"
            f"Target Revit version: {revit_version}\n"
            f"{intent_blob}\n"
            f"Candidates ({len(cands)}):\n"
            + "\n".join(lines)
            + "\n\nPick top 5 indices for the code-gen LLM (most useful FIRST)."
        )

    def parse_response(self, text: str) -> dict[str, Any]:
        data = parse_json_block(text)
        indices = data.get("top_5_indices")
        if not isinstance(indices, list):
            raise ValueError(f"top_5_indices is not a list: {indices!r}")
        if len(indices) != _TOP_K:
            raise ValueError(
                f"expected 5 indices, got count={len(indices)}: {indices!r}"
            )
        for v in indices:
            if not isinstance(v, int) or isinstance(v, bool):
                raise ValueError(f"index is not an int: {v!r}")
            if v < 0 or v >= _NUM_CANDIDATES_EXPECTED:
                raise ValueError(
                    f"index out of range [0,{_NUM_CANDIDATES_EXPECTED}): {v}"
                )
        if len(set(indices)) != _TOP_K:
            raise ValueError(f"duplicate / not-unique indices: {indices!r}")
        return {
            "top_5_indices": indices,
            "reasoning": str(data.get("reasoning", ""))[:200],
        }
