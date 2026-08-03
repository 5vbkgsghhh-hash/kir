"""cohere/rerank-4-fast via OpenRouter — fast, purpose-built RAG reranker.

Used when ``KUKAI_AGENT_RERANK_BACKEND=cohere`` (the current default state while
the gemini agent stack is down — see memory kukai-gemini-down-deepseek-only).
Measured ~0.4-0.5s, reliable, no timeouts — unlike the LLM reranker on DeepSeek
(1-68s, a reasoning model). Goes DIRECT to OpenRouter (openrouter.ai is in the
worker NO_PROXY, so default trust_env routing skips the SOCKS proxy).

cohere is a SEMANTIC reranker: it scores text-similarity, not code-gen utility.
That makes it drop universally-needed classes that aren't lexically similar to
the query (FilteredElementCollector, Transaction). ``apply_essentials_floor``
guarantees those stay in the top-5 — which is exactly the slice that contributes
code examples + gotchas to the prompt (rag_prompt._format_results uses entries[:5]
for examples, entries[:8] for gotchas).

Both functions are best-effort / non-fatal: on any failure the caller keeps the
baseline RRF order.
"""
from __future__ import annotations

import logging
import os
from typing import Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

_OR_RERANK_URL = "https://openrouter.ai/api/v1/rerank"
# Default OpenRouter rerank model. cohere/rerank-* and nvidia nemotron-rerank
# speak the IDENTICAL /rerank endpoint and shape, so this path is model-agnostic;
# the model is chosen by ``KUKAI_AGENT_RERANK_MODEL`` (or the ``model`` arg).
_DEFAULT_MODEL = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"

# Disclosure counters (Article 9 / IRON 10): a silently-degrading reranker is
# worse than absent. Surfaced on /health; degradation is logged at WARNING.
RERANK_STATS = {"calls": 0, "ok": 0, "rate_limited": 0, "error": 0, "last_status": None}

# Classes needed by almost every code-gen task but rarely lexically similar to
# the user's words → cohere ranks them low. The floor keeps them in the top-5.
_ESSENTIALS_ALWAYS = ("FilteredElementCollector",)
# Added to the floor only when the task writes to the model.
_ESSENTIALS_WRITE = ("Transaction",)
_WRITE_HINTS_RU = ("созда", "удал", "измен", "покрас", "перемест", "поверн", "постав",
                   "добав", "назнач", "переимен", "вырав", "скоп")
_WRITE_HINTS_EN = ("creat", "delet", "remov", "modif", "set ", "paint", "color",
                   "move ", "rotat", "place", "add ", "assign", "renam", "align")


async def cohere_rerank(
    query: str,
    documents: Sequence[str],
    *,
    model: Optional[str] = None,
    top_n: Optional[int] = None,
    timeout: float = 5.0,
) -> Optional[list[int]]:
    """Reorder ``documents`` by relevance to ``query`` via OpenRouter /rerank.

    Model-agnostic: ``model`` (else env ``KUKAI_AGENT_RERANK_MODEL``, else the
    nemotron default) picks the rerank model; cohere/rerank-* and nemotron-rerank
    share this endpoint/shape. Returns None on any failure (caller keeps the
    baseline RRF order); every failure is counted and logged, never silent.
    """
    mdl = model or os.environ.get("KUKAI_AGENT_RERANK_MODEL") or _DEFAULT_MODEL
    key = os.environ.get("KUKAI_LLM_FALLBACK_API_KEY")
    docs = list(documents)
    if not key or not query or not docs:
        return None
    RERANK_STATS["calls"] += 1
    body = {
        "model": mdl,
        "query": str(query)[:2000],
        "documents": [str(d)[:1500] for d in docs],
        "top_n": top_n or len(docs),
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://revit-kukai.org",
        "X-Title": "KUKI",
    }
    try:
        # No explicit proxy: trust_env honors NO_PROXY → openrouter.ai goes direct.
        async with httpx.AsyncClient(timeout=timeout) as cl:
            r = await cl.post(_OR_RERANK_URL, json=body, headers=headers)
        RERANK_STATS["last_status"] = r.status_code
        if r.status_code != 200:
            if r.status_code == 429:
                RERANK_STATS["rate_limited"] += 1
                logger.warning("Reranker rate-limited (429) on %s — baseline order kept", mdl)
            else:
                RERANK_STATS["error"] += 1
                logger.warning("Reranker HTTP %s on %s — baseline order kept", r.status_code, mdl)
            return None
        results = r.json().get("results", [])
        order: list[int] = []
        seen: set[int] = set()
        for it in results:
            i = it.get("index")
            if isinstance(i, int) and 0 <= i < len(docs) and i not in seen:
                order.append(i)
                seen.add(i)
        if order:
            RERANK_STATS["ok"] += 1
        return order or None
    except Exception as exc:
        RERANK_STATS["error"] += 1
        logger.warning("Reranker call failed on %s (%s) — baseline order kept", mdl, exc)
        return None


def apply_essentials_floor(
    order: list[int],
    names: Sequence[str],
    *,
    is_write: bool = False,
) -> list[int]:
    """Promote essential classes into the top-5 of ``order`` if cohere dropped them.

    ``names[i]`` is the class/entry name for original index ``i``. Pure reorder —
    never drops anything. Promotes by replacing the LOWEST non-essential entry
    currently in the top-5, so genuinely-relevant cohere picks are preserved.
    """
    if not order:
        return order
    essentials = set(_ESSENTIALS_ALWAYS)
    if is_write:
        essentials |= set(_ESSENTIALS_WRITE)

    top = order[:5]
    top_names = {names[i] for i in top if 0 <= i < len(names)}
    # Candidates to promote: essential, present in the set, not already in top.
    for i in order[5:]:
        if not (0 <= i < len(names)):
            continue
        nm = names[i]
        if nm in essentials and nm not in top_names:
            # find lowest-ranked non-essential slot in top to evict
            for j in range(len(top) - 1, -1, -1):
                jn = names[top[j]] if 0 <= top[j] < len(names) else ""
                if jn not in essentials:
                    top[j] = i
                    break
            top_names = {names[k] for k in top if 0 <= k < len(names)}

    used = set(top)
    return top + [i for i in order if i not in used]


def looks_like_write(text: str) -> bool:
    """Cheap heuristic: does the user's request modify the model?"""
    t = (text or "").lower()
    return any(h in t for h in _WRITE_HINTS_RU) or any(h in t for h in _WRITE_HINTS_EN)
