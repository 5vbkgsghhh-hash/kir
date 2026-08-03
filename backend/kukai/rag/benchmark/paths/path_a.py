"""Path A — hardened baseline.

The current production RAG pipeline after Level 1 fixes (B1+B2+N1+B3+N2+N4):
- Double-truncation removed
- Code-example caps raised to 800/1000
- FEC.LINQ deterministic fixer
- Pre-flight Roslyn compile on every attempt
- Gotcha-section in Format B+

Production flow before retrieval (client.py:760-776):
  rag_query = translate_to_english(user_message)   # if not already English
  rag_query = _expand_rag_query(rag_query)         # add API class names
  enricher.enrich(rag_query)                       # what the index sees

Translation is treated as a separate concern from retrieval quality — the
benchmark gold-set uses English queries directly (matching what the index
actually receives in production). Query expansion IS applied here because
it's a deterministic part of the retrieval contract.

This path is the honest baseline that B and C must beat to justify their
extra complexity.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from kukai.llm.client import _expand_rag_query
from kukai.rag.benchmark.paths.base import RAGPath, RAGResult
from kukai.rag.rag_prompt import RagPromptEnricher
from kukai.rag.revit_api_index import RevitApiIndex


class PathA(RAGPath):
    name = "A_baseline_hardened"

    def __init__(self, enricher: Optional[RagPromptEnricher] = None) -> None:
        if enricher is None:
            enricher = RagPromptEnricher()
        self._enricher = enricher

    def enrich(
        self,
        query: str,
        context: Optional[dict[str, Any]] = None,
    ) -> RAGResult:
        self._enricher.ensure_loaded()
        active_extension = (context or {}).get("active_extension")

        # Match production: apply query expansion before retrieval.
        # Translation step is omitted (gold-set is already English).
        expanded_query = _expand_rag_query(query)

        t0 = time.perf_counter()
        # Tap directly into the index so we capture the retrieved entries
        # (the enricher only returns formatted text). Same query path as
        # production via search() → keyword + semantic + RRF.
        index: RevitApiIndex = self._enricher._index  # noqa: SLF001 — internal access by design
        retrieved = index.search(expanded_query, top_k=15, active_extension=active_extension)
        prompt_text = self._enricher.enrich(expanded_query, top_k=15, active_extension=active_extension)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        retrieved_ids = [
            f"{e.entry_type}:{e.namespace}.{e.name}" for e in retrieved
        ]
        retrieved_apis = [e.name for e in retrieved]

        return RAGResult(
            prompt_text=prompt_text,
            retrieved_ids=retrieved_ids,
            retrieved_apis=retrieved_apis,
            metadata={
                "latency_ms": round(latency_ms, 1),
                "result_count": len(retrieved),
                "prompt_chars": len(prompt_text),
                "expanded_query": expanded_query,
            },
        )
