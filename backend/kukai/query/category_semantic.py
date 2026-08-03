"""Semantic category resolution (IQ-fix P1, the "meaning" part).

When the alias DICTIONARY misses (kukai.categories), match the user's term
against category aliases by MEANING (embeddings) so synonyms / typos / unlisted
phrasings resolve instead of hard-failing query_model. This is a FALLBACK — it
fires only on a dict miss, with a conservative threshold so a low-confidence
match falls through to None (today's behavior) rather than mis-resolving.

Reuses the same OpenAI-compatible embedding endpoint as norms_rag / the API
index (text-embedding-3-large). Embeddings are a SEPARATE budget from DeepSeek.
The per-category index is embedded once and cached to data/category_embeddings.npz.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Optional

# Module cache: (osts: list[str], matrix: np.ndarray | None, model: str)
_INDEX: Optional[tuple] = None


def _cache_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "category_embeddings.npz"


def _embed_settings():
    from kukai.config import get_settings
    s = get_settings()
    key = (s.embedding_api_key or s.openai_api_key
           or os.environ.get("KUKAI_OPENAI_API_KEY", "") or os.environ.get("OPENAI_API_KEY", ""))
    base = s.embedding_api_base or "https://api.openai.com/v1"
    model = s.embedding_model or "text-embedding-3-large"
    return key, base, model


def _embed(texts: list[str], key: str, base: str, model: str):
    import httpx
    import numpy as np
    r = httpx.post(
        f"{base}/embeddings",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "input": texts}, timeout=60.0,
    )
    r.raise_for_status()
    return np.array([d["embedding"] for d in r.json()["data"]], dtype=np.float32)


def _build_or_load():
    """Build (or load cached) one embedding per OST category, from its aliases."""
    global _INDEX
    if _INDEX is not None:
        return _INDEX
    import numpy as np
    from kukai.categories import CATEGORY_MAP
    key, base, model = _embed_settings()
    if not key:
        _INDEX = ([], None, model)  # no key → semantic disabled
        return _INDEX
    by_ost: dict[str, list[str]] = {}
    for alias, ost in CATEGORY_MAP.items():
        by_ost.setdefault(ost, []).append(alias)
    osts = sorted(by_ost)
    # One representative string per category = name + its aliases (richer signal).
    texts = [ost.replace("OST_", "") + ": " + ", ".join(by_ost[ost][:14]) for ost in osts]
    fp = hashlib.sha1((model + "|" + "|".join(osts) + "|" + str(len(CATEGORY_MAP))).encode()).hexdigest()
    cp = _cache_path()
    if cp.exists():
        try:
            d = np.load(cp, allow_pickle=True)
            if str(d["fp"]) == fp:
                _INDEX = (list(d["osts"]), d["mat"], model)
                return _INDEX
        except Exception:  # noqa: BLE001 — stale/corrupt cache → rebuild
            pass
    mat = _embed(texts, key, base, model)
    try:
        cp.parent.mkdir(parents=True, exist_ok=True)
        np.savez(cp, osts=np.array(osts), mat=mat, fp=np.array(fp))
    except Exception:  # noqa: BLE001 — cache write best-effort
        pass
    _INDEX = (osts, mat, model)
    return _INDEX


def semantic_resolve(term: str, threshold: float = 0.50) -> Optional[tuple[str, float]]:
    """Best (OST_category, score) for a term by embedding similarity, or None if
    below threshold / unavailable. Conservative by design — a miss = None."""
    try:
        import numpy as np
        if not term or not term.strip():
            return None
        osts, mat, _ = _build_or_load()
        if mat is None or len(osts) == 0:
            return None
        key, base, model = _embed_settings()
        if not key:
            return None
        qv = _embed([term], key, base, model)[0]
        qn = float(np.linalg.norm(qv))
        if qn == 0.0:
            return None
        sims = (mat @ qv) / (np.linalg.norm(mat, axis=1) * qn + 1e-10)
        i = int(np.argmax(sims))
        score = float(sims[i])
        if score >= threshold:
            return (osts[i], score)
    except Exception:  # noqa: BLE001 — semantic is a best-effort fallback
        pass
    return None
