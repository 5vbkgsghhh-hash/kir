"""Path D — A + B combined (keyword + semantic + phrasings, 3-way RRF).

Hypothesis: Path A and Path B catch DIFFERENT failure modes.
  - Path A's semantic embedding catches concept-similarity (multilingual
    synonyms, paraphrases the LLM generator didn't anticipate).
  - Path B's phrasings catch domain-specific user phrasings the embedding
    model doesn't differentiate well.

Combining all three retrieval signals (keyword + semantic + phrasings) via
3-way Reciprocal Rank Fusion preserves both strengths. Doc2Query++ paper
(SIGIR'25) confirms Dual-Index Fusion (separate indexes, RRF at query time)
beats naive document append.

Cost profile:
  - Latency: same as Path A (~1.5s, dominated by OpenAI embedding call).
    Phrasings add no runtime cost beyond a hashmap lookup.
  - $: same as Path A (~$0.000004/query for embedding).
  - Setup: $0.10 one-time for offline phrasing generation (same as Path B).

If `data/doc2query_v1.jsonl` does not exist, Path D degrades gracefully to
Path A behavior (no phrasings leg in the RRF).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Optional

from kukai.llm.client import _expand_rag_query
from kukai.rag.benchmark.paths.base import RAGPath, RAGResult
from kukai.rag.benchmark.paths.path_b import (
    PathB,
    _DEFAULT_PHRASINGS_PATH,
    _POOL_K,
    _RRF_K,
    _TOP_K,
)
from kukai.rag.rag_prompt import RagPromptEnricher
from kukai.rag.revit_api_index import ApiEntry, RevitApiIndex, _filter_stop_words, _tokenize

logger = logging.getLogger(__name__)


class PathD(RAGPath):
    """3-way fusion: keyword ⊕ semantic ⊕ Doc2Query phrasings."""

    name = "D_combined_3leg"

    def __init__(
        self,
        enricher: Optional[RagPromptEnricher] = None,
        phrasings_path: Optional[Path] = None,
    ) -> None:
        if enricher is None:
            enricher = RagPromptEnricher()
        self._enricher = enricher
        # Reuse Path B's phrasing loader and ranker — same data, same logic.
        self._phrase_helper = PathB(
            enricher=enricher,
            phrasings_path=phrasings_path or _DEFAULT_PHRASINGS_PATH,
        )

    @staticmethod
    def _entry_id(entry: ApiEntry) -> str:
        return f"{entry.entry_type}:{entry.namespace}.{entry.name}".rstrip(".")

    def enrich(
        self,
        query: str,
        context: Optional[dict[str, Any]] = None,
    ) -> RAGResult:
        self._enricher.ensure_loaded()
        # Phrase loader is lazy — first call populates it, subsequent calls noop.
        self._phrase_helper._ensure_phrasings_loaded()  # noqa: SLF001

        active_extension = (context or {}).get("active_extension")
        expanded_query = _expand_rag_query(query)

        t0 = time.perf_counter()
        index: RevitApiIndex = self._enricher._index  # noqa: SLF001

        # --- Leg 1: keyword search ---
        keyword_pool = index.keyword_search(
            expanded_query, top_k=_POOL_K, active_extension=active_extension,
        )

        # --- Leg 2: semantic search (OpenAI text-embedding-3-large) ---
        # When the embedding key is missing or the call fails, semantic_search
        # returns []. Path D then degrades to keyword + phrasings (≈ Path B)
        # and remains correct.
        semantic_pool: list[ApiEntry] = []
        if index.has_embeddings:
            api_key = index._openai_api_key  # noqa: SLF001
            if not api_key:
                try:
                    from kukai.config import get_settings as _gs
                    settings = _gs()
                    api_key = settings.embedding_api_key or settings.openai_api_key
                except Exception:
                    api_key = None
            if api_key:
                semantic_pool = index.semantic_search(
                    expanded_query, top_k=_POOL_K, active_extension=active_extension,
                )

        # --- Leg 3: Doc2Query phrasing match ---
        query_tokens = frozenset(_filter_stop_words(_tokenize(expanded_query)))
        phrasing_ids = self._phrase_helper._phrasing_rank(query_tokens, top_k=_POOL_K)  # noqa: SLF001

        # --- Build entry lookup spanning all three pools ---
        entry_by_id: dict[str, ApiEntry] = {}
        for entry in keyword_pool:
            entry_by_id[self._entry_id(entry)] = entry
        for entry in semantic_pool:
            entry_by_id[self._entry_id(entry)] = entry
        # Pull entries referenced only by phrasings (not in keyword/semantic pools)
        if phrasing_ids:
            wanted = set(phrasing_ids) - set(entry_by_id)
            if wanted:
                for entry in index._entries:  # noqa: SLF001
                    if entry.extension_id and (
                        not active_extension or entry.extension_id != active_extension
                    ):
                        continue
                    eid = self._entry_id(entry)
                    if eid in wanted:
                        entry_by_id[eid] = entry
                        wanted.discard(eid)
                        if not wanted:
                            break

        # --- 3-way RRF merge ---
        rrf_scores: dict[str, float] = {}
        for rank, entry in enumerate(keyword_pool):
            eid = self._entry_id(entry)
            rrf_scores[eid] = rrf_scores.get(eid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        for rank, entry in enumerate(semantic_pool):
            eid = self._entry_id(entry)
            rrf_scores[eid] = rrf_scores.get(eid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        for rank, eid in enumerate(phrasing_ids):
            if eid not in entry_by_id:
                continue
            rrf_scores[eid] = rrf_scores.get(eid, 0.0) + 1.0 / (_RRF_K + rank + 1)

        # Sort: type priority (recipe/class first), then RRF score, then id for stability.
        def _sort_key(eid: str) -> tuple:
            entry = entry_by_id[eid]
            type_priority = 0 if entry.entry_type in ("recipe", "class") else 1
            return (type_priority, -rrf_scores[eid], eid)

        ranked_ids = sorted(rrf_scores.keys(), key=_sort_key)
        merged_entries = [entry_by_id[eid] for eid in ranked_ids[:_TOP_K]]

        # Format B+ output (same as A and B, recycles production enricher)
        prompt_text = self._enricher._format_results(merged_entries)  # noqa: SLF001

        latency_ms = (time.perf_counter() - t0) * 1000.0

        retrieved_ids = [self._entry_id(e) for e in merged_entries]
        retrieved_apis = [e.name for e in merged_entries]

        return RAGResult(
            prompt_text=prompt_text,
            retrieved_ids=retrieved_ids,
            retrieved_apis=retrieved_apis,
            metadata={
                "latency_ms": round(latency_ms, 1),
                "result_count": len(merged_entries),
                "prompt_chars": len(prompt_text),
                "expanded_query": expanded_query,
                "keyword_pool": len(keyword_pool),
                "semantic_pool": len(semantic_pool),
                "phrasing_pool": len(phrasing_ids),
                "phrasing_index_size": len(self._phrase_helper._phrasing_tokens),  # noqa: SLF001
            },
        )
