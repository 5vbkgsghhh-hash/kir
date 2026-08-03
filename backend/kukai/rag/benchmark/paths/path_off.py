"""Path OFF — the no-RAG control arm for the grounding A/B (plan 014).

Returns an empty prompt so the LLM answers from parametric memory only.
The Δ between this arm and PathA *is* the apex metric (scorecard C11):
does injecting our corpus raise the end-task pass-rate of whatever brain
is in prod? PathOff is the denominator of that question.
"""

from __future__ import annotations

from typing import Any, Optional

from kukai.rag.benchmark.paths.base import RAGPath, RAGResult


class PathOff(RAGPath):
    name = "OFF_no_rag"

    def enrich(
        self,
        query: str,
        context: Optional[dict[str, Any]] = None,
    ) -> RAGResult:
        return RAGResult(
            prompt_text="",
            retrieved_ids=[],
            retrieved_apis=[],
            metadata={"latency_ms": 0.0, "arm": "off"},
        )
