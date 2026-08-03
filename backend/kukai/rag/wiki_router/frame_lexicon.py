"""Frame-lexicon enrichment + frame cache for the floor/quick OperationFrame
(FRAME_UPLIFT_TASKS.md S2 + S3).

Context: ``capability_router.derive_quick_frame`` (the offline FLOOR reached
whenever the request-level classifier hasn't finished in time) always
returns ``object_kinds=[]`` and ``domain=None`` — see its docstring. That
blinds ROUTER_V3's soft-fusion object/domain bonuses on every floor-path
request, degrading routing to pure content/token-overlap scoring. This
module offers a monotone, vocab-closed, offline-computed RU-token lexicon
(``data/wiki/frame_lexicon.json``, built by ``/root/kukai-cube/
build_frame_lexicon.py`` from the SAME ``wiki_query.tokenize`` — no second
tokenizer, no drift) to fill in ONLY the empty slots.

S2 — enrich_frame() / adapter call-site
----------------------------------------
Flag: KUKAI_FRAME_LEXICON (env, read at call time — KIR-shadow convention).
  off (default) -> no-op, zero import/compute cost.
  shadow        -> compute both frame_pre/frame_post + lexicon_votes, log to
                    wiki_router_shadow.jsonl via WikiRouter.shadow_log(), but
                    the ORIGINAL (pre) frame is what actually routes.
  on            -> the enriched (post) frame is what actually routes.

MONOTONICITY (hard rule, never relaxed here): enrichment only ever fills a
slot that started EMPTY. ``object_kinds == []`` -> may be replaced by
lexicon kind-votes. ``domain is None`` -> may be replaced by a lexicon
domain-vote. A non-empty classifier/floor output is NEVER touched — this
module has no code path that mutates a populated field.

ABSOLUTE FAIL-OPEN: any exception anywhere in this module's public entries
(missing/corrupt lexicon file, bad frame shape, tokenizer import failure,
whatever) returns the ORIGINAL frame unchanged. The caller's turn is never
affected — mirrors kukai/ir/shadow.py's discipline (import inside try,
except Exception -> debug log, never raise).

S3 — FrameCache (LRU + TTL)
----------------------------
Caches only source=deepseek frames (the threaded, model-produced frame) —
NEVER the floor/quick frame, which must not be pinned across turns (spec:
"floor не кэшировать — пиннит деградацию": caching a degraded floor result
would freeze that degradation in place for every repeat of the same
normalized query). Key = sha1 of the lower-cased, whitespace-collapsed
query. Single-process OrderedDict LRU (prod is 1 uvicorn worker — no lock
needed, matches spec).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# S2 constants
# ---------------------------------------------------------------------------
_FLAG = "KUKAI_FRAME_LEXICON"
_LEXICON_PATH_ENV = "FRAME_LEXICON_PATH"
_LEXICON_PATH_DEFAULT = "/opt/kukai-rebuild1/backend/data/wiki/frame_lexicon.json"

# ---------------------------------------------------------------------------
# Lexicon load (module-level cache — the file is an immutable-per-deploy
# artifact, same convention as WikiRouter's own load-once-per-process; a
# fresh process picks up a re-deployed file, matching current_release()'s
# own @lru_cache(maxsize=1) staleness contract elsewhere in this package).
# ---------------------------------------------------------------------------
_lexicon_cache: Optional[dict] = None
_lexicon_load_failed = False


def _load_lexicon() -> Optional[dict]:
    global _lexicon_cache, _lexicon_load_failed
    if _lexicon_cache is not None:
        return _lexicon_cache
    if _lexicon_load_failed:
        return None
    path = os.environ.get(_LEXICON_PATH_ENV, _LEXICON_PATH_DEFAULT)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data.pop("_meta", None)
        _lexicon_cache = data
        return data
    except Exception:
        _lexicon_load_failed = True
        logger.debug("frame_lexicon: load failed (fail-open, no enrichment)",
                      exc_info=True)
        return None


def _reset_lexicon_cache_for_tests() -> None:
    """Test-only hook — production code never calls this."""
    global _lexicon_cache, _lexicon_load_failed
    _lexicon_cache = None
    _lexicon_load_failed = False


def lexicon_votes(user_message: str) -> dict[str, Any]:
    """Aggregate lexicon votes for ``user_message``: sums each contributing
    token's per-kind / per-domain share, same simple aggregation as
    /root/kukai-cube/eval_lexicon.py's domain_votes_for_query (no separate
    v2 scoring invented here). Returns
    {"kinds": {kind: score, ...}, "domains": {domain: score, ...},
     "tokens_matched": [...]}. Empty dict on any failure (fail-open)."""
    lexicon = _load_lexicon()
    if not lexicon or not user_message:
        return {"kinds": {}, "domains": {}, "tokens_matched": []}
    try:
        from kukai.rag.wiki_router.wiki_query import tokenize
        toks = tokenize(user_message)
        kind_score: dict[str, float] = {}
        domain_score: dict[str, float] = {}
        matched: list[str] = []
        for t in toks:
            entry = lexicon.get(t)
            if not entry:
                continue
            matched.append(t)
            for k, share in (entry.get("kinds") or {}).items():
                kind_score[k] = kind_score.get(k, 0.0) + share
            for d, share in (entry.get("domains") or {}).items():
                domain_score[d] = domain_score.get(d, 0.0) + share
        return {"kinds": kind_score, "domains": domain_score, "tokens_matched": sorted(matched)}
    except Exception:
        logger.debug("frame_lexicon: vote computation failed (fail-open)", exc_info=True)
        return {"kinds": {}, "domains": {}, "tokens_matched": []}


def _top_kinds(kind_score: dict[str, float], limit: int = 3) -> list[str]:
    # Deterministic: score desc, then kind name asc for ties.
    ranked = sorted(kind_score.items(), key=lambda kv: (-kv[1], kv[0]))
    return [k for k, _ in ranked[:limit]]


def _top_domain(domain_score: dict[str, float]) -> Optional[str]:
    if not domain_score:
        return None
    best = max(domain_score.values())
    candidates = sorted(d for d, s in domain_score.items() if s == best)
    return candidates[0]


def enrich_frame(frame: Optional[dict], user_message: str) -> tuple[dict, dict]:
    """(enriched_frame, votes). MONOTONE: only fills object_kinds==[] and/or
    domain is None on a COPY of ``frame``; never mutates a non-empty slot,
    never mutates the input dict in place. On any failure, returns
    (frame unchanged, empty votes) — absolute fail-open."""
    try:
        base = dict(frame) if isinstance(frame, dict) else {}
        votes = lexicon_votes(user_message)
        enriched = dict(base)

        object_kinds = base.get("object_kinds") or []
        if not object_kinds:
            top_kinds = _top_kinds(votes["kinds"])
            if top_kinds:
                enriched["object_kinds"] = top_kinds

        if base.get("domain") is None:
            top_domain = _top_domain(votes["domains"])
            if top_domain is not None:
                enriched["domain"] = top_domain

        return enriched, votes
    except Exception:
        logger.debug("frame_lexicon: enrich_frame failed (fail-open, frame unchanged)",
                      exc_info=True)
        return (dict(frame) if isinstance(frame, dict) else {}), {"kinds": {}, "domains": {}, "tokens_matched": []}


def apply_to_floor_frame(frame: Optional[dict], user_message: str,
                          shadow_log_fn=None) -> dict:
    """Adapter call-site entry for the floor/quick-frame branch. Reads
    KUKAI_FRAME_LEXICON at call time (env, not import time — env can change
    between requests in tests / ops toggles without a process restart
    changing behaviour on the NEXT call).

    off (default): returns ``frame`` byte-identical, zero lexicon-module
        work attempted beyond the flag check itself.
    shadow: computes frame_pre/frame_post/votes, best-effort logs via
        ``shadow_log_fn(record)`` if provided, returns frame_pre (the
        ORIGINAL) — enrichment is observed, not applied.
    on: returns frame_post (the enriched frame) — enrichment is applied.

    ABSOLUTE FAIL-OPEN: any exception here (including inside shadow_log_fn)
    -> returns the original ``frame`` unchanged. Never raises.
    """
    frame_pre = frame if isinstance(frame, dict) else {}
    try:
        mode = os.environ.get(_FLAG, "off")
        if mode == "off":
            return frame_pre

        frame_post, votes = enrich_frame(frame_pre, user_message)

        if mode == "shadow":
            if shadow_log_fn is not None:
                try:
                    shadow_log_fn({
                        "kind": "frame_lexicon_shadow",
                        "ts": time.time(),
                        "query": user_message,
                        "frame_pre": frame_pre,
                        "frame_post": frame_post,
                        "lexicon_votes": votes,
                    })
                except Exception:
                    logger.debug("frame_lexicon: shadow_log_fn failed (fail-open)",
                                 exc_info=True)
            return frame_pre

        if mode == "on":
            return frame_post

        # Unknown flag value -> treat as off (fail-open, conservative default).
        return frame_pre
    except Exception:
        logger.debug("frame_lexicon: apply_to_floor_frame failed (fail-open)",
                      exc_info=True)
        return frame_pre


# ---------------------------------------------------------------------------
# S3 — LRU+TTL cache for deepseek-sourced frames ONLY (never floor frames).
#
# HONEST MAPPING NOTE: the adapter's inject() telemetry only ever emits
# frame_source in {"threaded", "quick", "quick_after_timeout", "cache"} —
# there is no literal "deepseek" value anywhere in the current call graph
# (verified: the request-level IntentClassifier is the sole producer of a
# non-None `frame` argument to inject(), which becomes frame_source=
# "threaded"; whatever LLM provider actually serves that classifier call
# under the locked provider-routing config is an operational fact, not a
# string this module can see). Per spec ("кэшировать только deepseek-
# фреймы... floor не кэшировать — пиннит деградацию") the INTENT is: cache
# the model-produced frame, never the floor/quick fallback. In this
# codebase that intent maps 1:1 onto frame_source == "threaded" (the only
# non-floor frame source) — so that is the literal gate value below.
# ---------------------------------------------------------------------------
_CACHE_MAXSIZE = 2000
_CACHE_TTL_SECONDS = 6 * 3600
_CACHED_FRAME_SOURCE = "threaded"


def _normalize_query(user_message: str) -> str:
    return re.sub(r"\s+", " ", (user_message or "").strip().lower())


def _cache_key(user_message: str) -> str:
    normalized = _normalize_query(user_message)
    return hashlib.sha1(normalized.encode("utf-8", "replace")).hexdigest()


class FrameCache:
    """Single-process OrderedDict LRU with per-entry TTL. No locking (prod
    runs exactly 1 uvicorn worker — spec-confirmed prod fact, matches the
    existing WikiRouter/current_release() single-process assumptions
    elsewhere in this package). NOT thread-safe by design; do not reuse
    across a multi-worker deployment without adding a lock."""

    def __init__(self, maxsize: int = _CACHE_MAXSIZE, ttl_seconds: float = _CACHE_TTL_SECONDS):
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._store: "OrderedDict[str, tuple[float, dict]]" = OrderedDict()

    def get(self, user_message: str, *, now: Optional[float] = None) -> Optional[dict]:
        key = _cache_key(user_message)
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, frame = entry
        if (now if now is not None else time.time()) - ts > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return dict(frame)

    def put(self, user_message: str, frame: dict, *, now: Optional[float] = None) -> None:
        """Unconditional store — source gating (deepseek-only) lives in
        put_if_deepseek(), the call-site entry point; this method is the
        low-level primitive used by both put_if_deepseek() and tests."""
        if not isinstance(frame, dict):
            return
        key = _cache_key(user_message)
        self._store[key] = ((now if now is not None else time.time()), dict(frame))
        self._store.move_to_end(key)
        while len(self._store) > self._maxsize:
            self._store.popitem(last=False)

    def put_if_deepseek(self, user_message: str, frame: dict, frame_source: str,
                         *, now: Optional[float] = None) -> bool:
        """Only caches when frame_source == _CACHED_FRAME_SOURCE ("threaded"
        — the model-produced frame; S3 rule: floor/quick frames must never
        be cached — see the HONEST MAPPING NOTE above the constant and the
        module docstring). Returns True if
        the frame was stored."""
        if frame_source != _CACHED_FRAME_SOURCE:
            return False
        if not isinstance(frame, dict):
            return False
        self.put(user_message, frame, now=now)
        return True

    def __len__(self) -> int:
        return len(self._store)


_frame_cache: Optional[FrameCache] = None


def get_frame_cache() -> FrameCache:
    global _frame_cache
    if _frame_cache is None:
        _frame_cache = FrameCache()
    return _frame_cache
