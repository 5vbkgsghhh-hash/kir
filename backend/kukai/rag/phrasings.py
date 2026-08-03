"""Doc2Query phrasings index (Path B integrated into production RAG).

Loads `data/doc2query_v1.jsonl` lazily on first use. Provides a third
retrieval leg for `RevitApiIndex.search()` ranked by token overlap between
the query and pre-generated user phrasings of each API entry.

Behaviour when the file is missing or empty:
  - First call logs INFO once (no warning spam on subsequent searches).
  - `is_available()` returns False.
  - `rank()` returns []. Production search degrades to its 2-leg form
    transparently — no exceptions, no extra latency.

Format of each JSONL line (produced by scripts/build_doc2query_index.py):
    {"entry_id": "class:Autodesk.Revit.DB.Wall",
     "name": "Wall",
     "namespace": "Autodesk.Revit.DB",
     "entry_type": "class",
     "phrasings": ["...", "..."]}

Entry-id format note: the JSONL uses ``f"{entry_type}:{namespace}.{name}".rstrip(".")``,
matching scripts/build_doc2query_index.py exactly. ``rstrip(".")`` only
strips trailing dots, so for the entries actually indexed by Doc2Query
(class+recipe) the JSONL entry_id is identical to the production RRF key
``f"{entry_type}:{namespace}.{name}"``. No translation needed when merging.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class PhrasingIndex:
    """Lazy-loaded Doc2Query phrasings index for the production search."""

    def __init__(self, jsonl_path: Path) -> None:
        # Coerce str → Path so callers can pass either form. Defensive: a
        # string slipping in here used to hide the bug behind a logger.exception
        # in search() and silently degrade to 2-leg with no signal.
        self._jsonl_path: Path = Path(jsonl_path)
        # JSONL entry_id -> list of phrasing token-sets
        self._phrasing_tokens: dict[str, list[frozenset[str]]] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def is_available(self) -> bool:
        """True iff the index is loaded and contains at least one entry."""
        return self._loaded and len(self._phrasing_tokens) > 0

    def ensure_loaded(self) -> None:
        """Idempotent lazy loader.

        Logs once at INFO. Subsequent calls are O(1). On any IO error or
        missing file: marks loaded with empty index — no retries.
        """
        if self._loaded:
            return
        # Mark loaded eagerly so failures can't trigger a retry loop on every search.
        self._loaded = True

        # Import here to avoid circular import (revit_api_index imports nothing
        # from phrasings, but phrasings tokenizes queries the same way).
        from kukai.rag.revit_api_index import _filter_stop_words, _tokenize

        if not self._jsonl_path.exists():
            logger.info(
                "Phrasings: file %s not found — search continues with 2-leg RRF.",
                self._jsonl_path,
            )
            return

        n_loaded = 0
        try:
            with self._jsonl_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        # Skip garbage lines silently — same policy as the
                        # benchmark version. A corrupt line shouldn't kill load.
                        continue
                    entry_id = row.get("entry_id")
                    phrasings = row.get("phrasings") or []
                    if not entry_id or not phrasings:
                        continue
                    token_sets: list[frozenset[str]] = []
                    for ph in phrasings:
                        if not isinstance(ph, str):
                            continue
                        toks = frozenset(_filter_stop_words(_tokenize(ph)))
                        if toks:
                            token_sets.append(toks)
                    if token_sets:
                        self._phrasing_tokens[entry_id] = token_sets
                        n_loaded += 1
        except OSError as exc:
            logger.warning("Phrasings: failed to read %s: %s", self._jsonl_path, exc)
            return

        if n_loaded:
            logger.info(
                "Phrasings: loaded %d entries from %s", n_loaded, self._jsonl_path,
            )
        else:
            logger.info(
                "Phrasings: file %s parsed but contained zero usable entries.",
                self._jsonl_path,
            )

    def rank(
        self,
        query_tokens: frozenset[str],
        top_k: int,
    ) -> list[str]:
        """Return JSONL entry_ids ranked by max token-overlap.

        Highest overlap first; ties broken alphabetically by entry_id for
        stability across runs. Returns [] if the index is unavailable, the
        query is empty, or no phrasing has any token overlap with the query.
        """
        if not query_tokens or not self.is_available():
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
        scored.sort(key=lambda x: (-x[0], x[1]))
        if top_k > 0:
            scored = scored[:top_k]
        return [eid for _, eid in scored]


def default_phrasings_path() -> Path:
    """Resolve the canonical phrasings file location: backend/data/doc2query_v1.jsonl."""
    # this file is backend/kukai/rag/phrasings.py → up 3 to backend/, then data/
    return Path(__file__).resolve().parent.parent.parent / "data" / "doc2query_v1.jsonl"


def jsonl_entry_id(entry_type: str, namespace: str, name: str) -> str:
    """Build the JSONL-form entry_id used in doc2query_v1.jsonl.

    Identical to the convention in scripts/build_doc2query_index.py:
        f"{entry_type}:{namespace}.{name}".rstrip(".")

    `rstrip(".")` only affects trailing dots, so for an entry like
    ``("recipe", "", "CountWalls")`` the result is ``"recipe:.CountWalls"``
    (the leading dot after the colon is *kept* — same as the production
    RRF key). The strip only matters in the unusual case where ``name``
    itself is empty.

    For all entries currently indexed by Doc2Query (class+recipe), the
    JSONL form matches the production RRF key character-for-character.
    """
    return f"{entry_type}:{namespace}.{name}".rstrip(".")


_FEATURE_FLAG_ENV = "KUKAI_RAG_PHRASINGS"


def feature_enabled() -> bool:
    """Return False if env var KUKAI_RAG_PHRASINGS is set to a falsy value.

    Defaults to True when unset. Recognised falsy values: "0", "false",
    "no", "off" (case-insensitive). Anything else, including empty string
    and unset, is treated as enabled.
    """
    import os

    raw = os.environ.get(_FEATURE_FLAG_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")
