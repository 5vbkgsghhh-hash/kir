"""Single source of truth for automatic production knowledge injection.

The immutable Wiki release is the only corpus that may enter a user prompt.
Historical RAG flags are accepted as retired aliases but deliberately resolve
to Wiki, so a stale deployment variable cannot re-enable embeddings or vector
retrieval.
"""

from __future__ import annotations

import logging
import os
from enum import Enum

logger = logging.getLogger(__name__)


class KnowledgeMode(str, Enum):
    WIKI = "wiki"
    OFF = "off"


_ALIASES = {
    "wiki": KnowledgeMode.WIKI,
    "wiki-only": KnowledgeMode.WIKI,
    "on": KnowledgeMode.WIKI,
    "off": KnowledgeMode.OFF,
    "none": KnowledgeMode.OFF,
    # Retired values fail safe to the production Wiki corpus.
    "legacy-rag": KnowledgeMode.WIKI,
    "rag": KnowledgeMode.WIKI,
}


def knowledge_mode() -> KnowledgeMode:
    """Return the process knowledge mode, defaulting to Wiki.

    ``KUKAI_KNOWLEDGE_MODE`` is authoritative for Wiki/off. Retired values
    ``rag`` and ``legacy-rag`` are logged and resolve to Wiki.
    """

    raw = (os.getenv("KUKAI_KNOWLEDGE_MODE") or "").strip().lower()
    if raw:
        if raw in {"rag", "legacy-rag"}:
            logger.error(
                "KUKAI_KNOWLEDGE_MODE=%r is retired; forcing immutable Wiki mode",
                raw,
            )
        mode = _ALIASES.get(raw)
        if mode is None:
            logger.error(
                "Unknown KUKAI_KNOWLEDGE_MODE=%r; failing safe to wiki", raw,
            )
            return KnowledgeMode.WIKI
        return mode

    old = (os.getenv("KUKAI_RAG_WIKI_ROUTER") or "").strip().lower()
    if old in {"on", "hybrid", "shadow"}:
        return KnowledgeMode.WIKI
    return KnowledgeMode.WIKI


def wiki_enabled() -> bool:
    return knowledge_mode() is KnowledgeMode.WIKI


def legacy_rag_enabled() -> bool:
    """Compatibility shim: automatic legacy retrieval can never be enabled."""
    return False
