"""Path B — Doc2Query offline indexing.

Hypothesis: the production retrieval bottleneck is *vocabulary mismatch*
between user phrasings and corpus keywords, not the flow itself. Path B
augments every class/recipe entry with 5-8 plausible user phrasings
(generated offline by Gemini Flash via OpenRouter — see
`scripts/build_doc2query_index.py`) and merges that lookup with the regular
keyword search via Reciprocal Rank Fusion.

Production code is untouched. The phrasings file is loaded lazily on first
`enrich()` call so the path can be benchmarked without affecting cold-start
of the main server.

If `data/doc2query_v1.jsonl` does not exist, Path B falls back to a pure
keyword search — equivalent to a degraded Path A. Useful for smoke-testing
before the offline index has been built.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from kukai.llm.client import _expand_rag_query
from kukai.rag.benchmark.paths.base import RAGPath, RAGResult
from kukai.rag.rag_prompt import RagPromptEnricher
from kukai.rag.revit_api_index import ApiEntry, RevitApiIndex, _filter_stop_words, _tokenize

logger = logging.getLogger(__name__)

_DEFAULT_PHRASINGS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "data"
    / "doc2query_v1.jsonl"
)

# RRF constant — same as production search() in revit_api_index.py
_RRF_K = 60
# Per-source candidate pool size before RRF merge
_POOL_K = 20
# Final result count returned to the prompt formatter
_TOP_K = 15


class PathB(RAGPath):
    """Keyword search ⊕ Doc2Query phrasing match, fused via RRF."""

    name = "B_doc2query"

    def __init__(
        self,
        enricher: Optional[RagPromptEnricher] = None,
        phrasings_path: Optional[Path] = None,
    ) -> None:
        if enricher is None:
            enricher = RagPromptEnricher()
        self._enricher = enricher
        self._phrasings_path = phrasings_path or _DEFAULT_PHRASINGS_PATH
        # entry_id (str) -> set of phrasing-token-sets (each is a frozenset[str])
        self._phrasing_tokens: dict[str, list[frozenset[str]]] = {}
        self._loaded = False

    # --- Lazy phrasing loader --------------------------------------------

    def _ensure_phrasings_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True  # set early so failures don't retry forever
        if not self._phrasings_path.exists():
            logger.warning(
                "PathB: phrasings file %s not found — falling back to keyword-only.",
                self._phrasings_path,
            )
            return
        n = 0
        with self._phrasings_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                entry_id = row.get("entry_id")
                phrasings = row.get("phrasings") or []
                if not entry_id or not phrasings:
                    continue
                token_sets: list[frozenset[str]] = []
                for ph in phrasings:
                    toks = frozenset(_filter_stop_words(_tokenize(ph)))
                    if toks:
                        token_sets.append(toks)
                if token_sets:
                    self._phrasing_tokens[entry_id] = token_sets
                    n += 1
        logger.info("PathB: loaded phrasings for %d entries from %s", n, self._phrasings_path)

    # --- Phrasing-match scoring ------------------------------------------

    @staticmethod
    def _entry_id(entry: ApiEntry) -> str:
        return f"{entry.entry_type}:{entry.namespace}.{entry.name}".rstrip(".")

    def _phrasing_rank(self, query_tokens: frozenset[str], top_k: int) -> list[str]:
        """Return entry_ids ranked by max token-overlap across an entry's phrasings."""
        if not query_tokens or not self._phrasing_tokens:
            return []
        scored: list[tuple[int, str]] = []
        for entry_id, token_sets in self._phrasing_tokens.items():
            best = 0
            for ts in token_sets:
                overlap = len(query_tokens & ts)
                if overlap > best:
                    best = overlap
            if best > 0:
                scored.append((best, entry_id))
        # Highest overlap first; ties broken by entry_id for stability
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [eid for _, eid in scored[:top_k]]

    # --- Main entry point ------------------------------------------------

    def enrich(
        self,
        query: str,
        context: Optional[dict[str, Any]] = None,
    ) -> RAGResult:
        self._enricher.ensure_loaded()
        self._ensure_phrasings_loaded()

        active_extension = (context or {}).get("active_extension")

        # Match production: deterministic query expansion before retrieval.
        expanded_query = _expand_rag_query(query)

        t0 = time.perf_counter()
        index: RevitApiIndex = self._enricher._index  # noqa: SLF001 — internal access by design

        # Source 1: regular keyword search (top-N pool)
        keyword_pool = index.keyword_search(
            expanded_query, top_k=_POOL_K, active_extension=active_extension,
        )

        # Source 2: phrasing-overlap rank
        query_tokens = frozenset(_filter_stop_words(_tokenize(expanded_query)))
        phrasing_ids = self._phrasing_rank(query_tokens, top_k=_POOL_K)

        # Build entry lookup for phrasing IDs (skip entries not in the index)
        entry_by_id: dict[str, ApiEntry] = {}
        for entry in keyword_pool:
            entry_by_id[self._entry_id(entry)] = entry
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
                        if len(entry_by_id) >= len(keyword_pool) + len(phrasing_ids):
                            break

        # RRF merge — keyword rank + phrasing rank
        rrf_scores: dict[str, float] = {}
        for rank, entry in enumerate(keyword_pool):
            eid = self._entry_id(entry)
            rrf_scores[eid] = rrf_scores.get(eid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        for rank, eid in enumerate(phrasing_ids):
            if eid not in entry_by_id:
                continue  # phrasing references an entry not in the live index
            rrf_scores[eid] = rrf_scores.get(eid, 0.0) + 1.0 / (_RRF_K + rank + 1)

        # Sort by RRF score, type priority (recipe/class first), then id for stability
        def _sort_key(eid: str) -> tuple:
            entry = entry_by_id[eid]
            type_priority = 0 if entry.entry_type in ("recipe", "class") else 1
            return (type_priority, -rrf_scores[eid], eid)

        ranked_ids = sorted(rrf_scores.keys(), key=_sort_key)
        merged_entries = [entry_by_id[eid] for eid in ranked_ids[:_TOP_K]]

        # Reuse the production formatter — same Format B+ output as Path A.
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
                "phrasing_index_size": len(self._phrasing_tokens),
                "keyword_pool": len(keyword_pool),
                "phrasing_pool": len(phrasing_ids),
            },
        )
