"""Norms RAG enricher - injects query-specific building code context into prompts.

Before each LLM call, this module:
1. Detects if the user's message is about building norms/codes
2. Searches the norms database (norms.db + norms_embeddings.npz) via semantic search
3. Formats the results into a compact prompt section (max ~3000 chars)
4. Returns the enriched context for injection into the system prompt

Uses OpenAI-compatible embeddings API for semantic search (fast, accurate for Russian text).
Falls back to keyword search if embeddings are unavailable.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_NORMS_DB = _DATA_DIR / "norms.db"
_NORMS_EMB = _DATA_DIR / "norms_embeddings.npz"

# Keywords that indicate the user is asking about building norms/codes.
# Uses regex patterns for robust matching (handles punctuation, whitespace,
# and word boundaries instead of fragile trailing-space checks).
_NORM_PATTERNS: list[str] = [
    # Direct norm abbreviations — word boundary to avoid false positives
    r"\bсп[.\s,;:)\n]",       # СП. / СП / СП, / СП; etc.
    r"\bгост[.\s,;:)\n]",     # ГОСТ. / ГОСТ / ГОСТ, etc.
    r"\bснип[.\s,;:)\n]",     # СНИП. / СНИП / СНИП, etc.
    r"\bпуэ\b",                # ПУЭ (always standalone)
    r"\bфз[.\s,;:)\n]",        # ФЗ. / ФЗ / ФЗ, etc.
    r"\bспн[.\s,;:)\n]",       # СПН (Строительные производственные нормы)
    # Combined references
    r"\bпо\s+(сп|гост|снип|пуэ|фз)\b",
    # Broad norm-related stems (Russian word stems — high specificity)
    r"\bнорм",                 # нормы, норматив, нормирование
    r"\bстроительн",           # строительные, строительная
    # Explicit requirement language
    r"\bтребован",             # требования, требованиям
    r"\bдопустим",             # допустимые, допустимый
    r"\bнеобходим",            # необходимые, необходимо
    r"\bследует\b",            # следует (as verb, not as "it follows that")
    r"\bне\s+менее\b",         # не менее
    r"\bне\s+более\b",         # не более
    # Safety/regulatory topics
    r"\bпожарн",               # пожарная, пожарные, пожарный
    r"\bэвакуац",              # эвакуация, эвакуационный
    # Documentation stage / project norms (narrowed to avoid false positives)
    r"\bстадия\s+(п|р)",       # стадия П / стадия Р
    r"\bпроектн",              # проектная, проектный
    r"\bдокументац",           # документация, документационный
    r"\bрабочая\s+документ",   # рабочая документация
]

_MAX_NORM_CHARS = 3000
_MAX_RESULTS = 5


class NormsRagEnricher:
    """Enriches the system prompt with query-specific building code context."""

    def __init__(self):
        self._loaded = False
        self._vectors = None
        self._chunk_ids = None
        self._db_exists = _NORMS_DB.exists()
        self._emb_exists = _NORMS_EMB.exists()

    def _ensure_loaded(self) -> bool:
        """Load embeddings into memory. Returns True if available."""
        if self._loaded:
            return self._vectors is not None

        self._loaded = True
        if not self._db_exists:
            logger.debug("Norms database not found at %s", _NORMS_DB)
            return False

        if not self._emb_exists:
            logger.debug("Norms embeddings not found at %s", _NORMS_EMB)
            return False

        try:
            import numpy as np
            emb_data = np.load(str(_NORMS_EMB), allow_pickle=False)
            self._vectors = emb_data["vectors"]
            self._chunk_ids = emb_data["ids"]
            logger.info(
                "Loaded norms embeddings: %d chunks, %d-dim vectors",
                len(self._vectors), self._vectors.shape[1],
            )
            return True
        except Exception as e:
            logger.warning("Failed to load norms embeddings: %s", e)
            return False

    def is_norms_query(self, query: str) -> bool:
        """Check if the query is likely about building norms/codes."""
        if not query:
            return False
        ql = query.lower()
        return any(re.search(pat, ql) for pat in _NORM_PATTERNS)

    def enrich(self, user_message: str, top_k: int = _MAX_RESULTS,
               scope_docs: Optional[list] = None) -> str:
        """Search the norms database and return a formatted prompt section.

        Path B (smart-inject): ``scope_docs`` (norm doc names from the tree router,
        e.g. ["СП 63.13330.2018"]) restricts retrieval to those documents so a
        query about a specific topic gets ONLY the relevant norm, not the whole
        base. Falls back to unscoped search if the scoped docs have no top hits."""
        if not self.is_norms_query(user_message):
            return ""

        if not self._ensure_loaded():
            return self._keyword_enrich(user_message, top_k, scope_docs)

        return self._semantic_enrich(user_message, top_k, scope_docs)

    def _semantic_enrich(self, query: str, top_k: int,
                         scope_docs: Optional[list] = None) -> str:
        """Search norms using OpenAI-compatible embeddings + cosine similarity."""
        try:
            import numpy as np
        except ImportError:
            return self._keyword_enrich(query, top_k)

        # Embedding now goes through the shared client (plan 018 §4): one cache +
        # circuit breaker in front of the (byte-identical) httpx call, replacing
        # the duplicated inline loop. A dead/slow embedding endpoint no longer
        # costs ~10s here on every norms query — the breaker short-circuits it.
        # ``api_key_override`` mirrors the old env-var fallback below.
        _override = os.environ.get(
            "KUKAI_OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")
        )
        try:
            from kukai.rag.embedding_client import get_query_embedding as _embed

            outcome = _embed(query, api_key_override=_override)
            if outcome.vector is None:
                # no_key / failed / breaker_open -> degrade to keyword-only.
                return self._keyword_enrich(query, top_k)
            qvec = np.asarray(outcome.vector, dtype=np.float32)

            norms = np.linalg.norm(self._vectors, axis=1, keepdims=True)
            norms = np.maximum(norms, 1e-10)
            qnorm = np.linalg.norm(qvec)
            if qnorm == 0:
                return ""

            sims = (self._vectors @ qvec) / (norms.flatten() * qnorm)

            fetch_k = top_k * 3
            top_idx = np.argsort(sims)[::-1][:fetch_k]
            from kukai.config import get_settings as _gs
            _thr = _gs().embedding_sim_threshold
            matched_ids = [str(self._chunk_ids[i]) for i in top_idx if sims[i] > _thr]

            if not matched_ids:
                return self._keyword_enrich(query, top_k)

            import sqlite3
            db = sqlite3.connect(str(_NORMS_DB))
            db.row_factory = sqlite3.Row
            try:
                placeholders = ",".join(["?"] * len(matched_ids))
                rows = db.execute(
                    f"SELECT id, document_name, text FROM norm_chunks WHERE id IN ({placeholders})",
                    matched_ids,
                ).fetchall()

                id_to_row = {r["id"]: (r["document_name"], r["text"]) for r in rows}

                def _collect(only_scoped: bool):
                    seen_docs: dict[str, int] = {}
                    acc = []
                    for mid in matched_ids:
                        if mid not in id_to_row:
                            continue
                        doc_name, text = id_to_row[mid]
                        if (only_scoped and scope_docs
                                and not any(sd in doc_name for sd in scope_docs)):
                            continue                     # Path B: keep only routed docs
                        if seen_docs.get(doc_name, 0) >= 2:
                            continue
                        seen_docs[doc_name] = seen_docs.get(doc_name, 0) + 1
                        acc.append((doc_name, text))
                        if len(acc) >= top_k:
                            break
                    return acc

                results = _collect(only_scoped=bool(scope_docs))
                if scope_docs and not results:          # router doc had no top hits → broaden
                    results = _collect(only_scoped=False)
            finally:
                db.close()

            if not results:
                return self._keyword_enrich(query, top_k)

            return self._format_results(results)

        except Exception as e:
            logger.warning("Norms semantic search failed: %s", e)
            return self._keyword_enrich(query, top_k)

    def _keyword_enrich(self, query: str, top_k: int,
                        scope_docs: Optional[list] = None) -> str:
        """Fallback keyword search in norms.db."""
        import sqlite3

        if not _NORMS_DB.exists():
            return ""

        words = [w for w in query.split() if len(w) >= 4]
        if not words:
            return ""

        stems = [w[:6].lower() for w in words[:3]]

        db = sqlite3.connect(str(_NORMS_DB))
        db.row_factory = sqlite3.Row
        try:
            where_parts = ["LOWER(text) LIKE ?" for _ in stems]
            where_clause = " OR ".join(where_parts)
            params = [f"%{s}%" for s in stems]
            params.append(top_k * 2)

            rows = db.execute(
                f"SELECT document_name, text FROM norm_chunks WHERE {where_clause} LIMIT ?",
                params,
            ).fetchall()

            if not rows:
                return ""

            seen: dict[str, int] = {}
            results = []
            for r in rows:
                if scope_docs and not any(sd in r["document_name"] for sd in scope_docs):
                    continue                             # Path B: keep only routed docs
                if seen.get(r["document_name"], 0) >= 2:
                    continue
                seen[r["document_name"]] = seen.get(r["document_name"], 0) + 1
                results.append((r["document_name"], r["text"]))
                if len(results) >= top_k:
                    break
            if scope_docs and not results:               # scoped empty → broaden
                for r in rows:
                    if seen.get(r["document_name"], 0) >= 2:
                        continue
                    seen[r["document_name"]] = seen.get(r["document_name"], 0) + 1
                    results.append((r["document_name"], r["text"]))
                    if len(results) >= top_k:
                        break

            return self._format_results(results) if results else ""
        finally:
            db.close()

    def _format_results(self, results: list[tuple[str, str]]) -> str:
        """Format norm search results into a compact prompt section."""
        if not results:
            return ""

        parts: list[str] = []
        parts.append("## Строительные нормы (релевантные запросу)")
        parts.append("")
        parts.append("Используй эти нормы при ответе. Ссылайся на конкретные документы.")
        parts.append("")

        total_chars = 0
        for doc_name, text in results:
            snippet = text[:600]
            line = f"### {doc_name}\n{snippet}"
            if total_chars + len(line) > _MAX_NORM_CHARS:
                break
            parts.append(line)
            parts.append("")
            total_chars += len(line)

        if total_chars >= _MAX_NORM_CHARS:
            parts.append("... (остальные нормы доступны через инструмент lookup_norm)")

        return "\n".join(parts)
