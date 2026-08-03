"""Shared query-embedding client: LRU cache + circuit breaker (plan 018 §4).

The semantic leg is the sole finder for a large share of live hits, yet its
embedding call used to have **no circuit breaker and no cache** — a dead/slow
embedding endpoint cost ~10s (2 × 5s timeouts) on EVERY query, every turn,
forever, and identical strings were re-embedded each call. The same inline
``httpx`` block was duplicated in ``revit_api_index._get_query_embedding`` and
``norms_rag._semantic_enrich``.

This module collapses both into ONE call that:

  1. **Serves from an LRU cache first** (key ``(api_base, model, query)``), so a
     repeated query never re-hits the network — and the cache still serves even
     when the breaker is OPEN. Failures are **never cached** (avoids the
     permanent-negative-cache disease).
  2. **Consults a circuit breaker second** (reused from
     ``kukai.llm.circuit_breaker``). After 3 consecutive failures the breaker
     OPENs and ``get_query_embedding`` returns ``breaker_open`` immediately with
     NO HTTP call, for a 60s cooldown; the first call after cooldown is the
     HALF_OPEN probe.
  3. Otherwise performs the **byte-for-byte** original HTTP call
     (``httpx.post`` to ``{api_base}/embeddings``, ``timeout=5.0``, one retry).

Thread-safety: ``search()`` runs inside ``asyncio.to_thread`` workers, so cache
+ breaker state are guarded by one module-level ``threading.Lock``. The lock is
NEVER held across the HTTP call — only around the cheap cache/breaker
bookkeeping — so a slow endpoint can never serialise every worker.

Vitals (``EMBED_STATS``) follow the ``cohere_rerank.RERANK_STATS`` pattern and
are surfaced on ``/health/deep`` (``status._retrieval_vitals``).
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

try:  # numpy is a hard dep in prod but keep the import defensive (mirrors index)
    import numpy as np
    _HAS_NUMPY = True
except Exception:  # pragma: no cover - numpy always present in prod/test
    _HAS_NUMPY = False

from kukai.llm.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)

# Process-level vitals for /health/deep — same spirit as cohere_rerank.RERANK_STATS.
EMBED_STATS: dict = {
    "calls": 0,          # HTTP attempts that actually fired (cache miss + breaker allowed)
    "ok": 0,             # successful embeddings (fresh)
    "cache_hits": 0,     # served from the LRU without touching the network
    "failures": 0,       # HTTP attempts that exhausted retries
    "breaker_skips": 0,  # calls short-circuited because the breaker was OPEN
    "last_error": None,  # short type name of the last failure (no PII)
}

# Tuning constants (plan 018 maintenance note: tune HERE, not via env).
_CACHE_MAXSIZE = 512
_FAILURE_THRESHOLD = 3
_COOLDOWN_S = 60.0
_TIMEOUT_S = 5.0

_lock = threading.Lock()
_cache: "OrderedDict[tuple[str, str, str], Any]" = OrderedDict()
_breaker = CircuitBreaker(failure_threshold=_FAILURE_THRESHOLD, cooldown_s=_COOLDOWN_S)


@dataclass
class EmbeddingOutcome:
    """The result of one ``get_query_embedding`` call."""

    vector: Optional[Any]   # np.ndarray | None
    status: str             # ok | cache_hit | no_key | failed | breaker_open


def _http_embed(api_base: str, api_key: str, model: str, query: str) -> Any:
    """The raw embedding POST — byte-for-byte the original inline semantics.

    Factored into a module-level function so tests can monkeypatch the HTTP
    layer with a counting stub. Raises on any failure (the caller's retry loop
    and the breaker decide what to do). The lock is NOT held while this runs.
    """
    import httpx

    response = httpx.post(
        f"{api_base}/embeddings",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "input": [query]},
        timeout=_TIMEOUT_S,
    )
    response.raise_for_status()
    data = response.json()
    if _HAS_NUMPY:
        return np.array(data["data"][0]["embedding"], dtype=np.float32)
    return data["data"][0]["embedding"]


def get_query_embedding(
    query: str, *, api_key_override: Optional[str] = None
) -> EmbeddingOutcome:
    """Embed ``query`` for semantic search, with cache + breaker in front.

    Key resolution order is preserved exactly from the old inline code:
    ``settings.embedding_api_key or settings.openai_api_key or api_key_override``
    (the index passes ``self._openai_api_key`` as the override).
    """
    # --- resolve key + endpoint (no network) ---------------------------------
    try:
        from kukai.config import get_settings as _gs
        settings = _gs()
        api_key = settings.embedding_api_key or settings.openai_api_key or (api_key_override or "")
        api_base = settings.embedding_api_base or "https://api.openai.com/v1"
        model = settings.embedding_model or "text-embedding-3-large"
    except Exception:
        api_key = api_key_override or ""
        api_base = "https://api.openai.com/v1"
        model = "text-embedding-3-large"

    if not api_key:
        # No key → semantic leg simply unavailable. No HTTP, no breaker mutation,
        # no stats bump (byte-identical to today's early ``return None``).
        return EmbeddingOutcome(vector=None, status="no_key")

    cache_key = (api_base, model, query)

    # --- 1. cache first (serves even when the breaker is open) ---------------
    with _lock:
        if cache_key in _cache:
            vec = _cache[cache_key]
            _cache.move_to_end(cache_key)  # LRU touch
            EMBED_STATS["cache_hits"] += 1
            return EmbeddingOutcome(vector=vec, status="cache_hit")

        # --- 2. breaker second -----------------------------------------------
        # should_use_fallback() returns True only in the OPEN state; HALF_OPEN
        # falls through so the call below becomes the recovery probe.
        if _breaker.should_use_fallback():
            EMBED_STATS["breaker_skips"] += 1
            return EmbeddingOutcome(vector=None, status="breaker_open")

    # --- 3. HTTP call (lock released) — original semantics: one retry --------
    last_exc: Optional[Exception] = None
    t0 = time.perf_counter()
    for _attempt in range(2):  # one retry
        try:
            vec = _http_embed(api_base, api_key, model, query)
            duration = time.perf_counter() - t0
            with _lock:
                EMBED_STATS["calls"] += 1
                EMBED_STATS["ok"] += 1
                _breaker.record_success(duration)
                _cache[cache_key] = vec
                _cache.move_to_end(cache_key)
                while len(_cache) > _CACHE_MAXSIZE:
                    _cache.popitem(last=False)  # evict LRU
            return EmbeddingOutcome(vector=vec, status="ok")
        except Exception as e:  # noqa: BLE001
            last_exc = e

    # All attempts failed — record the failure (drives the breaker), NEVER cache.
    duration = time.perf_counter() - t0
    with _lock:
        EMBED_STATS["calls"] += 1
        EMBED_STATS["failures"] += 1
        EMBED_STATS["last_error"] = type(last_exc).__name__ if last_exc else "unknown"
        _breaker.record_failure(duration)
    logger.warning(
        "Query embedding failed after retry — degrading to keyword-only: %s",
        last_exc,
    )
    return EmbeddingOutcome(vector=None, status="failed")


def _reset_for_tests() -> None:
    """Reset cache, breaker and stats — test-only helper."""
    with _lock:
        _cache.clear()
        _breaker.reset()
        EMBED_STATS.update(
            calls=0, ok=0, cache_hits=0, failures=0, breaker_skips=0, last_error=None
        )
