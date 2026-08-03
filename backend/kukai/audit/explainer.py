"""AuditExplainer — AI-powered issue explanations backed by normative database.

Two-step process:
1. Search norms.db for relevant normative context (semantic or keyword)
2. Feed the issue + norm context to the LLM for a human-readable explanation
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any

from kukai.audit.models import AuditIssue, AuditRule

if TYPE_CHECKING:
    from kukai.llm.client import LLMClient

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_NORMS_DB = _DATA_DIR / "norms.db"
_NORMS_EMB = _DATA_DIR / "norms_embeddings.npz"

# Similarity threshold for semantic search results
_SIM_THRESHOLD = 0.25
_MAX_NORM_CHARS = 1500


class AuditExplainer:
    """Generates AI explanations for audit issues using normative context."""

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def explain(
        self,
        issue: AuditIssue,
        rule: AuditRule | None = None,
    ) -> str | None:
        """Generate an explanation for an audit issue.

        1. Build a search query from the issue + rule norm_ref
        2. Search norms.db for relevant normative chunks
        3. Ask the LLM to explain the problem with norm context

        Returns None if explanation fails (LLM down, etc.).
        """
        try:
            norm_context = self._search_norms(issue, rule)
            prompt = self._build_prompt(issue, rule, norm_context)
            return await self._call_llm(prompt)
        except Exception as exc:
            logger.warning("Failed to explain issue %s: %s", issue.rule_id, exc)
            return None

    def _search_norms(
        self,
        issue: AuditIssue,
        rule: AuditRule | None,
    ) -> str:
        """Search norms.db for normative context relevant to the issue."""
        if not _NORMS_DB.exists():
            return ""

        query = self._build_search_query(issue, rule)
        if not query:
            return ""

        try:
            results = self._semantic_search(query)
        except Exception:
            logger.debug("Semantic search unavailable, falling back to keyword")
            results = self._keyword_search(query)

        if not results:
            return ""

        parts: list[str] = []
        total = 0
        for doc_name, text in results:
            snippet = text[:500]
            line = f"[{doc_name}]: {snippet}"
            if total + len(line) > _MAX_NORM_CHARS:
                break
            parts.append(line)
            total += len(line)

        return "\n\n".join(parts)

    @staticmethod
    def _build_search_query(issue: AuditIssue, rule: AuditRule | None) -> str:
        """Build a search query from the issue and rule metadata."""
        parts: list[str] = []
        if rule and rule.norm_ref:
            parts.append(rule.norm_ref)
        parts.append(issue.rule_name)
        if issue.message:
            parts.append(issue.message[:100])
        return " ".join(parts)

    def _semantic_search(self, query: str, limit: int = 5) -> list[tuple[str, str]]:
        """Search norms using embeddings. Raises if unavailable."""
        import numpy as np
        from openai import OpenAI

        oai_key = os.environ.get("KUKAI_OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
        if not oai_key or not _NORMS_EMB.exists():
            raise RuntimeError("Embeddings not available")

        # allow_pickle=False is the safe approach — only numeric arrays are loaded
        emb_data = np.load(str(_NORMS_EMB), allow_pickle=False)
        vectors = emb_data["vectors"]
        chunk_ids = emb_data["ids"]

        oai = OpenAI(api_key=oai_key)
        from kukai.config import get_settings
        qresp = oai.embeddings.create(model=get_settings().embedding_model, input=[query])
        qvec = np.array(qresp.data[0].embedding, dtype=np.float32)

        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms = np.maximum(norms, 1e-10)
        qnorm = np.linalg.norm(qvec)
        if qnorm == 0:
            return []

        sims = (vectors @ qvec) / (norms.flatten() * qnorm)
        top_idx = np.argsort(sims)[::-1][:limit]
        matched_ids = [str(chunk_ids[i]) for i in top_idx if sims[i] > _SIM_THRESHOLD]

        if not matched_ids:
            return []

        db = sqlite3.connect(str(_NORMS_DB))
        db.row_factory = sqlite3.Row
        try:
            placeholders = ",".join(["?"] * len(matched_ids))
            rows = db.execute(
                f"SELECT document_name, text FROM norm_chunks WHERE id IN ({placeholders})",
                matched_ids,
            ).fetchall()
            return [(r["document_name"], r["text"]) for r in rows]
        finally:
            db.close()

    @staticmethod
    def _keyword_search(query: str, limit: int = 5) -> list[tuple[str, str]]:
        """Fallback keyword search in norms.db."""
        db = sqlite3.connect(str(_NORMS_DB))
        db.row_factory = sqlite3.Row
        try:
            rows = db.execute(
                "SELECT document_name, text FROM norm_chunks WHERE text LIKE ? LIMIT ?",
                (f"%{query}%", limit),
            ).fetchall()
            return [(r["document_name"], r["text"]) for r in rows]
        finally:
            db.close()

    @staticmethod
    def _build_prompt(
        issue: AuditIssue,
        rule: AuditRule | None,
        norm_context: str,
    ) -> str:
        """Build the LLM prompt for explaining an audit issue."""
        lines = [
            "Ты эксперт по BIM-аудиту и российским строительным нормам.",
            "Объясни проблему, найденную при аудите BIM модели.",
            "",
            f"Правило: {issue.rule_name} ({issue.rule_id})",
            f"Категория: {issue.category.value}",
            f"Серьёзность: {issue.severity.value}",
            f"Сообщение: {issue.message}",
            f"Затронуто элементов: {issue.element_count}",
        ]
        if rule and rule.norm_ref:
            lines.append(f"Ссылка на норму: {rule.norm_ref}")
        if norm_context:
            lines.append("")
            lines.append("Релевантные нормативные документы:")
            lines.append(norm_context)
        lines.append("")
        lines.append(
            "Дай краткое (3-5 предложений) объяснение:\n"
            "1. В чём проблема\n"
            "2. Почему это важно (со ссылкой на норму, если есть)\n"
            "3. Как исправить"
        )
        return "\n".join(lines)

    async def _call_llm(self, prompt: str) -> str | None:
        """Call the LLM for a simple completion."""
        messages = [{"role": "user", "content": prompt}]
        chunks: list[str] = []
        async for event in self._llm.stream_chat(messages=messages, use_tools=False):
            if event.type == "stream_chunk" and event.data:
                chunks.append(event.data)
        result = "".join(chunks).strip()
        return result if result else None
