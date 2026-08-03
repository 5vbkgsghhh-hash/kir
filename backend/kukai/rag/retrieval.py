"""Typed retrieval pipeline behind ``RevitApiIndex.search`` (plan 018).

The pipeline that ``search()`` used to run inline — keyword / semantic /
phrasings legs, Reciprocal Rank Fusion, and the type-priority ranking — is
extracted here as small, pure-ish functions plus typed records. The point is to
make ranking a *measured policy*: ``rank_candidates`` is the only place the
type-priority preference lives, so the benchmark can run "legs once, rank N
ways" (``benchmark/rank_ablation.py``) without paying N retrievals, and the
``hard`` mode default is provably byte-identical to the pre-extraction sort.

Invariants this module is written to preserve (the Step-2 zero-diff gate
depends on every one of them):

  * **Leg order.** Candidates are accumulated in keyword -> semantic ->
    phrasings order. The fused-score dicts iterate in that insertion order and
    ``sorted`` is stable, so any tie in the final ranking falls back to that
    order — exactly as the old inline code did.
  * **RRF.** ``_RRF_K = 60``; each leg contributes ``1.0 / (k + rank + 1)``,
    summed per key. Same key convention everywhere:
    ``f"{entry_type}:{namespace}.{name}"``. Under the FITTED ranking policy
    (flag ``KUKAI_RANK_POLICY=1`` + a valid ``data/rank_policy.json``, IQ
    moment #9) the contribution becomes ``w_leg / (k + rank + 1)`` with
    per-leg weights measured on the gold set by
    ``scripts/fit_rank_policy.py``; flag OFF or file absent/invalid is
    byte-identical to the unweighted legacy math.
  * **Health reporting.** Every ``report_leg`` / ``add_flag`` call the old
    ``search()`` made is made here, with the same names, statuses and timings,
    so the plan-009 instrument (and therefore the benchmark) is unchanged. The
    one *addition* (plan 018 §4) is upgrading the semantic leg's report from a
    bare ``empty`` to ``tripped_breaker`` / ``error`` when the embedding client
    flagged a breaker-open / failure for this turn — a dead endpoint becomes a
    DEGRADED turn for the first time. That addition never fires on the keyless
    offline path (no flag is set), so the offline diff gate is unaffected.

This module is import-cheap: it does NO module-level I/O and type-hints
``ApiEntry`` only under ``TYPE_CHECKING``. ``RevitApiIndex.search`` imports it
lazily, matching the existing lazy-import discipline inside ``search()``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only
    from kukai.rag.revit_api_index import ApiEntry, RevitApiIndex

logger = logging.getLogger(__name__)

# Standard RRF constant — identical to the old inline ``_RRF_K`` in search().
_RRF_K = 60


# ---------------------------------------------------------------------------
# Bilingual-native retrieval (IQ moment #6, flag KUKAI_BILINGUAL_RETRIEVAL)
#
# The disease this removes: every Russian turn's retrieval WAITED on an LLM
# RU→EN translation (soft deadline under KUKAI_PREFLIGHT_V2; 10s legacy cap)
# because the keyword index's primary tokens were English-only. Under the
# flag:
#
#   * the search query is the RAW RU message — the keyword leg matches the
#     promoted RU primaries (revit_api_index._load_classes) and the semantic
#     leg embeds the RU text directly (text-embedding-3-large is
#     cross-lingual);
#   * the translation (which also does intent expansion — genuinely valuable)
#     becomes a PARALLEL enrichment leg: the client launches it at t=0 and
#     publishes a ``TranslationJoin``; ``run_legs`` holds the door open for
#     at most the REMAINING deadline (the wait overlaps all local leg work,
#     so the pre-prompt phase is max(legs), not Σ(legs)). If the English
#     interpretation lands in time it joins RRF as additional keyword and
#     semantic legs (``keyword_en``, ``semantic_en``); if not, retrieval
#     proceeds RU-only and the in-flight LLM call keeps warming the
#     translation cache in the background (``client._PF2_BG_TASKS``
#     machinery — nothing awaits it ever again).
#
# Flag OFF (default): none of this machinery is consulted — ``run_legs`` is
# byte-identical to the pre-#6 body.
# ---------------------------------------------------------------------------

_BILINGUAL_ENV = "KUKAI_BILINGUAL_RETRIEVAL"


def bilingual_retrieval_enabled() -> bool:
    """IQ #6 flag, read at call time (default OFF — dark)."""
    return os.getenv(_BILINGUAL_ENV, "0") == "1"


def _on_event_loop() -> bool:
    """True when called on a running asyncio event-loop thread."""
    import asyncio

    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


class TranslationJoin:
    """Cross-thread handoff for the parallel RU→EN enrichment leg (IQ #6).

    Created and published by ``client._stream_chat_inner`` under the flag;
    completed by the translate task's done-callback (event-loop thread);
    joined by ``run_legs`` inside the retrieval worker thread. A plain
    ``threading.Event`` is the bridge — the retrieval side never touches the
    event loop, and the join NEVER blocks an event-loop thread (misuse guard:
    a blocking wait there would deadlock the loop the translate runs on).

    ``query`` scopes the join to THE turn's retrieval: later searches in the
    same task (repair-hint lookups, recipe backfill) use different queries and
    are never contaminated by the enrichment leg.
    """

    __slots__ = ("query", "deadline_s", "launched_at", "raw_en",
                 "expanded_en", "_event")

    def __init__(self, deadline_s: float, query: str = "") -> None:
        self.query = query
        self.deadline_s = float(deadline_s)
        self.launched_at = time.monotonic()
        self.raw_en: Optional[str] = None       # pre-expansion EN (plan-019 shape)
        self.expanded_en: Optional[str] = None  # EN + query-expansion (search shape)
        self._event = threading.Event()

    def complete(self, raw_en: Optional[str],
                 expanded_en: Optional[str] = None) -> None:
        """Record the translate outcome (None = failed/skipped) and wake joiners."""
        self.raw_en = raw_en or None
        self.expanded_en = (expanded_en or raw_en) or None
        self._event.set()

    @property
    def done(self) -> bool:
        return self._event.is_set()

    def poll(self) -> Optional[str]:
        """Non-blocking: the expanded EN query if landed, else None."""
        return self.expanded_en if self._event.is_set() else None

    def remaining_s(self) -> float:
        return max(0.0, self.deadline_s - (time.monotonic() - self.launched_at))

    def join_bounded(self) -> Optional[str]:
        """Wait for the translation, bounded by the REMAINING deadline.

        The deadline is measured from launch, so time already spent running
        the local legs is subtracted — the wait only covers whatever budget
        the translate has left. On an event-loop thread this degrades to a
        non-blocking poll (never deadlock the loop).
        """
        if not self._event.is_set():
            remaining = self.remaining_s()
            if remaining > 0 and not _on_event_loop():
                self._event.wait(remaining)
        return self.poll()


# Per-turn published join. Set by the client in the TURN's context before any
# retrieval runs; ``asyncio.to_thread`` copies contextvars, so the retrieval
# worker thread sees the SAME TranslationJoin object (mutations propagate —
# the established mutable-holder pattern from ``turn_context``).
_turn_translation_join: ContextVar[Optional[TranslationJoin]] = ContextVar(
    "_turn_translation_join", default=None,
)


def publish_translation_join(join: Optional[TranslationJoin]) -> None:
    """Bind (or clear, with None) THIS turn's translation join."""
    _turn_translation_join.set(join)


def current_translation_join() -> Optional[TranslationJoin]:
    return _turn_translation_join.get()


def late_query_en() -> Optional[str]:
    """The turn's English interpretation if it has landed by NOW, else None.

    Serves downstream consumers of the EN query (plan-019 recipe capture)
    when the translation missed the retrieval join deadline but landed later
    in the turn (tool rounds take seconds — by capture time it usually has).
    Returns the PRE-expansion text, matching the legacy ``_turn_rag_query_en``
    shape. Never blocks, never raises.
    """
    try:
        tj = _turn_translation_join.get()
        if tj is not None and tj.done:
            return tj.raw_en
        return None
    except Exception:  # noqa: BLE001 — consumers are telemetry-adjacent
        return None

# The valid ranking-policy modes (plan 018 §1). ``hard`` is byte-identical to
# the pre-extraction sort and is the default; any unknown value falls back to it.
_VALID_MODES = frozenset({"hard", "tiebreak", "weight"})


def _entry_key(entry: "ApiEntry") -> str:
    """RRF/health key convention — identical to ``revit_api_index.search``."""
    return f"{entry.entry_type}:{entry.namespace}.{entry.name}"


# ---------------------------------------------------------------------------
# Version truth (corpus-flywheel design 2026-07-04 §2.2)
#
# Version-truth is a property of *retrieval*, not of prompt rendering. The
# entry-level filter used to live only inside ``RagPromptEnricher.enrich``
# (rag_prompt.py), which the reranked hot path bypassed on every prod turn
# (``client.py`` calls ``_index.search`` directly, reranks, then passes
# ``pre_retrieved_entries`` — disclosed as ``bypassed_on_reranked_path``).
# Moving the predicate HERE and applying it inside ``retrieve()`` makes every
# consumer of ``search()`` — plain path, reranked path, skills, repair-hint
# lookups — retrieve a version-clean pool: the reranker physically cannot
# resurrect a dead API because it never sees one. ONE predicate, every door
# (the enricher now delegates to these functions).
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"20\d{2}")


def parse_revit_year(version: Optional[str]) -> Optional[int]:
    """Extract a 4-digit Revit year (e.g. 2024) from a version string."""
    if not version:
        return None
    m = _YEAR_RE.search(str(version))
    return int(m.group(0)) if m else None


def version_filter_enabled() -> bool:
    """Plan-012 version filter flag (KUKAI_RAG_VERSION_FILTER, default ON).

    Read at call time (not cached) so tests/operators can toggle it. Fails
    open to True only if config import explodes — but the underlying
    api_versions helpers are themselves fail-open (no facts → no-op), so a
    True here with a missing artifact is still behaviourally legacy.
    """
    try:
        from kukai.config import get_settings
        return bool(get_settings().rag_version_filter)
    except Exception:
        return True


def keep_for_version(
    entry: Any, project_year: int, version_filter_on: bool = True,
) -> tuple[bool, str]:
    """The entry-level version predicate — verbatim semantics of the filter
    that lived inline in ``RagPromptEnricher.enrich`` (plan 012, IRON 4/5).

    Returns ``(keep, drop_reason)`` with ``drop_reason`` one of ``""``,
    ``"introduced_after"``, ``"removed"``, ``"recipe_compiles_on"``.

      (a) introduced-after — legacy ``since`` always; the diffed
          ``introduced`` fact only under the flag;
      (b) removed-by-now (flag-gated) — the type is gone in the project
          version;
      (c) recipe ``compiles_on`` stamps exclude this version (flag-gated) —
          compile facts (IRON 5-grade truth).

    Unknown type / no fact → kept (only positive facts act — fail-open).
    """
    intro = getattr(entry, "since", "") or (
        getattr(entry, "introduced", "") if version_filter_on else ""
    )
    if intro and (parse_revit_year(intro) or 0) > project_year:
        return False, "introduced_after"
    if version_filter_on:
        rem = getattr(entry, "removed_in", "")
        if rem and (parse_revit_year(rem) or 9999) <= project_year:
            return False, "removed"
        if getattr(entry, "entry_type", "") == "recipe":
            co = getattr(entry, "compiles_on", None)
            if co and str(project_year) not in [str(v) for v in co]:
                return False, "recipe_compiles_on"
    return True, ""


def _filter_items(
    items: list,
    entry_of: Callable[[Any], Any],
    revit_version: Optional[str],
    version_filter_on: Optional[bool],
    report: bool,
    detail: str,
) -> list:
    """Shared filter core over entries OR candidates (``entry_of`` adapts).

    Health reporting (only when ``report=True`` — exactly one
    ``version_filter`` leg is emitted per turn, at the door that acted):
      * no parsable version → ``report_leg("version_filter", "skipped_flag",
        detail="no_version")``, items returned unchanged;
      * version known → drop version-invalid items (order preserved),
        ``set_version_filtered_out(dropped)`` +
        ``report_leg("version_filter", "ran", kept, detail=...)``.

    NEVER throws into the hot path: any internal error → items unchanged.
    """
    try:
        from kukai.rag.retrieval_health import (
            report_leg as _report_leg,
            set_version_filtered_out as _set_vf,
        )

        project_year = parse_revit_year(revit_version)
        if project_year is None:
            if report:
                _report_leg("version_filter", "skipped_flag", 0, 0.0, "no_version")
            return items

        if version_filter_on is None:
            version_filter_on = version_filter_enabled()

        _t0 = time.perf_counter()
        kept: list = []
        dropped = {"introduced_after": 0, "removed": 0, "recipe_compiles_on": 0}
        for item in items:
            ok, reason = keep_for_version(
                entry_of(item), project_year, version_filter_on,
            )
            if ok:
                kept.append(item)
            else:
                dropped[reason] = dropped.get(reason, 0) + 1

        if len(kept) != len(items):
            logger.debug(
                "RAG version filter (Revit %d): %d -> %d entries "
                "(introduced-after=%d, removed=%d, recipe-compiles_on=%d)",
                project_year, len(items), len(kept),
                dropped["introduced_after"], dropped["removed"],
                dropped["recipe_compiles_on"],
            )
        if report:
            _set_vf(len(items) - len(kept))
            _report_leg(
                "version_filter", "ran", len(kept),
                (time.perf_counter() - _t0) * 1000.0, detail,
            )
        return kept
    except Exception:
        logger.exception("version filter failed — fail-open (unfiltered)")
        return items


def filter_entries(
    entries: list,
    revit_version: Optional[str],
    version_filter_on: Optional[bool] = None,
    report: bool = True,
    detail: str = "in_enrich",
) -> list:
    """Version-filter a list of ``ApiEntry`` (the enricher-side door)."""
    return _filter_items(
        entries, lambda e: e, revit_version, version_filter_on, report, detail,
    )


def filter_candidates(
    candidates: list["Candidate"],
    revit_version: Optional[str],
    report: bool = True,
) -> list["Candidate"]:
    """Version-filter ranked ``Candidate``s (the in-retrieval door).

    Called with the FULL (untruncated) ranked list, BEFORE the caller's
    ``top_k`` slice — so dropped entries are replaced by the next-ranked
    version-valid ones and the reranker's pool never shrinks below the
    ``len >= 5`` floor when enough valid entries exist (design §2.2 guard).
    """
    return _filter_items(
        candidates, lambda c: c.entry, revit_version,
        True,  # this door only runs when the flag is ON (see retrieve())
        report, "in_retrieval",
    )


def _turn_revit_version() -> Optional[str]:
    """Per-turn Revit version fallback (contextvar-backed ``TurnState``).

    The reranked hot path calls ``search()`` without a version kwarg
    (client.py); the version IS known per turn — ``_stream_chat_inner`` writes
    ``context.document.revit_version`` into ``current_turn().revit_version``
    before any retrieval runs, and ``asyncio.to_thread`` copies contextvars,
    so this resolves correctly inside the search worker thread too. Outside a
    turn (scripts, benchmark, tests) ``TurnState.revit_version`` is ``""`` →
    ``None`` → the filter stage is a disclosed no-op. ``kukai.llm.turn_state``
    is stdlib-only, so this lazy import adds no import weight / cycles.
    """
    try:
        from kukai.llm.turn_state import current_turn
        return current_turn().revit_version or None
    except Exception:
        return None


@dataclass(frozen=True)
class RetrievalRequest:
    """The inputs to one retrieval — a frozen, typed mirror of ``search()`` args.

    ``revit_version`` (design §2.2): the project's Revit version for the
    entry-level version filter that runs inside ``retrieve()``. ``None`` means
    "resolve from the per-turn ``TurnState``" (the prod reranked path passes
    nothing); an unparsable/empty resolved version disables the filter for the
    call (disclosed as ``skipped_flag/no_version``).

    ``intent`` (Wave-2 batch G): the turn's classified intent — one of the
    11-way ``kukai.agents.intent_classifier`` enum values, or whatever
    ``kukai.agents.intent_rules.quick_classify`` guesses when the LLM result
    hasn't landed. ``None`` (every call site that predates this change) means
    "no signal" — the intent-join adjustment inside ``retrieve()`` is skipped
    entirely, byte-identical to today's ranking.

    ``complexity`` (G-tune, Wave-2 batch G2): the turn's classified
    complexity — one of the 5-way ``trivial|simple|composite|hard|vague``
    enum, same two sources as ``intent`` (LLM classifier, else
    ``quick_classify``). Optional, default ``None`` — gates ONLY the
    composite-recipe conditional match inside ``apply_intent_join``; every
    other intent-join rule ignores it. ``None`` degrades safely (composite
    recipes stay NEUTRAL rather than universally boosted).

    ``action`` / ``object_kinds`` (capability-first RAG, Stage 2 — see
    CAPABILITY_FIRST_RAG.md §2/§6 step 2-3): the turn's classified
    OperationFrame — ``action`` a closed-vocab verb (finer than ``intent``,
    e.g. ``isolate``/``find_select`` vs the coarser ``filter``),
    ``object_kinds`` the closed-vocab object(s) it targets. Sourced from
    ``kukai.agents.intent_classifier`` (LLM) or its ``quick_classify``
    fallback, same non-blocking-peek discipline as ``intent``/``complexity``.
    Both default ``None`` (every call site that predates this change) — the
    capability-resolve stage inside ``retrieve()`` is then a strict no-op,
    gated additionally behind ``KUKAI_RAG_CAPABILITY_RESOLVE`` (default
    OFF/shadow).
    """

    query: str
    top_k: int = 15
    active_extension: Optional[str] = None
    revit_version: Optional[str] = None
    intent: Optional[str] = None
    complexity: Optional[str] = None
    action: Optional[str] = None
    object_kinds: Optional[list] = None


@dataclass
class LegResult:
    """One leg's ordered, materialised results (already extension-filtered)."""

    name: str                # keyword | semantic | phrasings
    entries: list            # list[ApiEntry] in this leg's rank order


@dataclass
class Candidate:
    """A fused candidate carrying everything the ranking policy needs."""

    key: str
    entry: Any               # ApiEntry
    rrf_score: float
    # 0 for recipe/class (the historically-preferred bucket), 1 otherwise.
    type_bucket: int


def _type_bucket(entry: "ApiEntry") -> int:
    return 0 if entry.entry_type in ("recipe", "class") else 1


# ---------------------------------------------------------------------------
# Stage 1: run the legs (verbatim from the old search() body)
# ---------------------------------------------------------------------------


def run_legs(index: "RevitApiIndex", req: RetrievalRequest) -> list[LegResult]:
    """Run keyword / semantic / phrasings legs, reporting per-leg health.

    Behaviour is line-for-line the old ``search()`` body for legs 1-3, including
    the exact ``report_leg`` calls, statuses, timings and the semantic-leg
    key-availability gate. The only addition is the breaker/failure status
    upgrade for the semantic leg (plan 018 §4), which is a no-op on the keyless
    offline path.
    """
    from kukai.rag.retrieval_health import add_flag as _add_flag  # noqa: F401
    from kukai.rag.retrieval_health import current as _rh_current
    from kukai.rag.retrieval_health import report_leg as _report_leg

    query = req.query
    top_k = req.top_k
    active_extension = req.active_extension

    legs: list[LegResult] = []

    # 1. Keyword search (reliable, fast)
    _kw_t0 = time.perf_counter()
    keyword_results = index.keyword_search(
        query, top_k=top_k, active_extension=active_extension,
    )
    _report_leg(
        "keyword",
        "ran" if keyword_results else "empty",
        len(keyword_results),
        (time.perf_counter() - _kw_t0) * 1000.0,
    )
    legs.append(LegResult("keyword", keyword_results))

    # 2. Semantic search (catches vocabulary mismatches)
    semantic_results: list = []
    if index.has_embeddings:
        api_key = index._openai_api_key
        if not api_key:
            try:
                from kukai.config import get_settings as _gs
                settings = _gs()
                api_key = settings.embedding_api_key or settings.openai_api_key
            except Exception:
                pass
        if api_key:
            _sem_t0 = time.perf_counter()
            semantic_results = index.semantic_search(
                query, top_k=top_k, active_extension=active_extension,
            )
            if semantic_results:
                _report_leg(
                    "semantic",
                    "ran",
                    len(semantic_results),
                    (time.perf_counter() - _sem_t0) * 1000.0,
                )
            else:
                # plan 018 §4: a *bare* empty here used to hide a dead embedding
                # endpoint. The embedding client now flags the turn when the
                # breaker is open / the call failed; promote those to DEGRADED
                # leg statuses so a sick endpoint is visible. No flag set (the
                # keyless offline path) -> plain "empty", byte-identical to today.
                status, detail = _semantic_empty_status(_rh_current())
                _report_leg(
                    "semantic",
                    status,
                    0,
                    (time.perf_counter() - _sem_t0) * 1000.0,
                    detail,
                )
        else:
            _report_leg("semantic", "skipped_no_key")
    else:
        _report_leg("semantic", "skipped_no_data", 0, 0.0, "no_npz")
    legs.append(LegResult("semantic", semantic_results))

    # 3. Phrasings leg (Doc2Query / Path B) — third RRF source.
    #    Behind feature flag KUKAI_RAG_PHRASINGS (default ON). Degrades
    #    transparently to 2-leg when the JSONL file is missing.
    phrasing_results: list = []
    _ph_t0 = time.perf_counter()
    try:
        from kukai.rag.phrasings import feature_enabled, jsonl_entry_id

        if not feature_enabled():
            _report_leg("phrasings", "skipped_flag")
        else:
            pidx = index._ensure_phrasing_index()
            pidx.ensure_loaded()
            if not pidx.is_available():
                _report_leg("phrasings", "skipped_no_data")
            if pidx.is_available():
                from kukai.rag.revit_api_index import (
                    _filter_stop_words,
                    _tokenize,
                )

                q_tokens = frozenset(_filter_stop_words(_tokenize(query)))
                phrasing_ids = pidx.rank(q_tokens, top_k=top_k)
                if phrasing_ids:
                    wanted = set(phrasing_ids)
                    # Build jid -> ApiEntry for ranked phrasing IDs.
                    # One pass over entries — O(N), but only when the
                    # feature is on AND phrasings file is non-empty.
                    jid_to_entry: dict = {}
                    for entry in index._entries:
                        # Same extension filtering as keyword/semantic legs.
                        if entry.extension_id and (
                            not active_extension
                            or entry.extension_id != active_extension
                        ):
                            continue
                        jid = jsonl_entry_id(
                            entry.entry_type, entry.namespace, entry.name,
                        )
                        if jid in wanted:
                            jid_to_entry[jid] = entry
                            wanted.discard(jid)
                            if not wanted:
                                break
                    # Materialise in the rank order returned by the index.
                    phrasing_results = [
                        jid_to_entry[jid]
                        for jid in phrasing_ids
                        if jid in jid_to_entry
                    ]
                _report_leg(
                    "phrasings",
                    "ran" if phrasing_results else "empty",
                    len(phrasing_results),
                    (time.perf_counter() - _ph_t0) * 1000.0,
                )
    except Exception as _ph_exc:
        # Phrasings must NEVER break production search. Log + continue.
        logger.exception("Phrasings leg failed — falling back to 2-leg RRF.")
        phrasing_results = []
        _report_leg("phrasings", "error", 0, 0.0, type(_ph_exc).__name__)
    legs.append(LegResult("phrasings", phrasing_results))

    # 4. Bilingual enrichment leg (IQ #6, flag KUKAI_BILINGUAL_RETRIEVAL,
    #    default OFF ⇒ this block is one boolean check). Runs LAST so the
    #    bounded join overlaps all local leg work above (keyword scan +
    #    embedding HTTP + phrasings), and so the existing legs' RRF tie-order
    #    is untouched (new keys only ever APPEND to the fused insertion
    #    order). The join is scoped to THIS turn's query — repair-hint /
    #    backfill searches in the same task never see it. Fail-open: any
    #    internal error keeps the RU-native legs.
    try:
        if bilingual_retrieval_enabled():
            tj = _turn_translation_join.get()
            if tj is not None and tj.query == query:
                _en_t0 = time.perf_counter()
                en_query = tj.join_bounded()
                _join_ms = (time.perf_counter() - _en_t0) * 1000.0
                _since_launch_ms = (time.monotonic() - tj.launched_at) * 1000.0
                if en_query:
                    en_results = index.keyword_search(
                        en_query, top_k=top_k, active_extension=active_extension,
                    )
                    _report_leg("translate", "ran", 1, _since_launch_ms,
                                "bilingual_join")
                    _report_leg(
                        "keyword_en",
                        "ran" if en_results else "empty",
                        len(en_results),
                        (time.perf_counter() - _en_t0) * 1000.0,
                    )
                    if en_results:
                        legs.append(LegResult("keyword_en", en_results))
                    # EN SEMANTIC enrichment (one embed call, landed-case
                    # only). Measured on the RU gold set (online instrument,
                    # scripts/bench_bilingual.py): without it the joined
                    # arm sits ~1pt BELOW today's strict Hit@5 (the RU-query
                    # embedding is weaker than the EN one against this
                    # corpus); with it the joined arm goes ~1.5pt ABOVE
                    # (55.56 vs 54.04). Keyless/no-npz → [] (fail-open).
                    sem_en: list = []
                    if index.has_embeddings:
                        _se_t0 = time.perf_counter()
                        sem_en = index.semantic_search(
                            en_query, top_k=top_k,
                            active_extension=active_extension,
                        )
                        _report_leg(
                            "semantic_en",
                            "ran" if sem_en else "empty",
                            len(sem_en),
                            (time.perf_counter() - _se_t0) * 1000.0,
                        )
                    else:
                        _report_leg("semantic_en", "skipped_no_data",
                                    0, 0.0, "no_npz")
                    if sem_en:
                        legs.append(LegResult("semantic_en", sem_en))
                elif tj.done:
                    # Translate finished but produced nothing (ASCII skip /
                    # junk / provider error) — RU-native retrieval IS the
                    # result; detail flags were set by _translate_for_rag.
                    _report_leg("translate", "empty", 0, _since_launch_ms,
                                "bilingual_join")
                    _report_leg("keyword_en", "skipped_no_data", 0, _join_ms)
                else:
                    # Deadline missed: the LLM call is now a pure background
                    # cache-warmer — nothing on this turn awaits it again.
                    _report_leg("translate", "skipped_deadline", 0,
                                _since_launch_ms, "bilingual_join")
                    _report_leg("keyword_en", "skipped_deadline", 0, _join_ms)
                    _add_flag("translate_deadline")
    except Exception as _bi_exc:  # noqa: BLE001 — enrichment never breaks search
        logger.exception("Bilingual enrichment leg failed — RU-native legs kept.")
        _report_leg("keyword_en", "error", 0, 0.0, type(_bi_exc).__name__)

    return legs


def _semantic_empty_status(health) -> tuple[str, str]:
    """Map embedding-client turn flags onto a richer semantic-leg status.

    Returns ``(status, detail)``. The embedding client (``embedding_client``)
    writes ``embedding_breaker_open`` / ``embedding_failed`` flags onto the
    current turn; here we read them back so the leg report discloses *why* the
    semantic leg returned nothing instead of the indistinguishable ``empty``.
    """
    try:
        flags = getattr(health, "flags", None) or []
        if "embedding_breaker_open" in flags:
            return "tripped_breaker", "embedding_breaker_open"
        if "embedding_failed" in flags:
            return "error", "embedding_failed"
    except Exception:
        pass
    return "empty", ""


# ---------------------------------------------------------------------------
# Stage 2: Reciprocal Rank Fusion (pure)
# ---------------------------------------------------------------------------


def rrf_fuse(
    legs: list[LegResult],
    k: int = _RRF_K,
    weights: Optional[dict[str, float]] = None,
) -> list[Candidate]:
    """Fuse leg results via RRF into a candidate list.

    Insertion order is the concatenation of the legs in the order given
    (keyword -> semantic -> phrasings for production), which — combined with the
    stable sort in ``rank_candidates`` — reproduces the old tie behaviour
    exactly. Pure: no I/O, no health calls.

    ``weights`` (IQ moment #9, fitted ranking policy): per-leg RRF weights
    keyed by ``LegResult.name``; each leg then contributes
    ``w_leg / (k + rank + 1)`` (missing names default to 1.0). ``None``
    (the default, and the only value the legacy path ever passes) evaluates
    the EXACT original expression — byte-identical scores, order and ties.
    """
    rrf_scores: dict[str, float] = {}
    entry_map: dict = {}
    order: list[str] = []  # first-seen order of keys (== old dict insertion order)

    for leg in legs:
        w = None if weights is None else float(weights.get(leg.name, 1.0))
        for rank, entry in enumerate(leg.entries):
            key = _entry_key(entry)
            if key not in entry_map:
                order.append(key)
            if w is None:
                rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (k + rank + 1)
            else:
                rrf_scores[key] = rrf_scores.get(key, 0) + w / (k + rank + 1)
            entry_map[key] = entry

    return [
        Candidate(
            key=key,
            entry=entry_map[key],
            rrf_score=rrf_scores[key],
            type_bucket=_type_bucket(entry_map[key]),
        )
        for key in order
    ]


# ---------------------------------------------------------------------------
# Stage 2.5: intent-join (Wave-2 batch G, flag KUKAI_RAG_INTENT_JOIN)
#
# Evidence (/root/kukai-rag-audit/agent_reports.md): noun-match, verb-blind
# retrieval is ~70% of measured retrieval harms — a read/audit/delete query
# surfaces create-recipes and vice versa, because RRF fusion only ever scores
# keyword/semantic/phrasing overlap on the NOUNS, never the intent. This stage
# re-scales an already-fused recipe candidate's ``rrf_score`` by how well the
# recipe's own ``intent`` field (from the corpus) agrees with the turn's
# classified intent — a targeted correction of the dominant failure mode, not
# a new retrieval leg (no new candidates are added or dropped here).
#
# Runs AFTER ``rrf_fuse`` (needs an ``rrf_score`` to adjust) and BEFORE
# ``rank_candidates`` (the adjusted score is what the type-priority sort keys
# off — a strongly-matching recipe can now out-rank a mismatched one within
# the same type bucket). Flag OFF, or no turn intent known -> untouched,
# byte-identical to legacy fusion.
# ---------------------------------------------------------------------------

_INTENT_JOIN_ENV = "KUKAI_RAG_INTENT_JOIN"

# Multiplicative adjustment factors (architect-fixed, Wave-2 batch G).
_INTENT_BOOST = 1.25
_INTENT_DEMOTE_HARD = 0.7   # recipe write-like vs turn read-like — real harm
_INTENT_DEMOTE_SOFT = 0.85  # recipe read-like vs turn create/delete — milder

# Turn-intent classes (kukai.agents.intent_classifier's 11-way enum).
_TURN_READLIKE = frozenset({"count", "list", "filter", "diagnose"})
_TURN_WRITELIKE = frozenset({"create", "modify", "delete", "schedule", "tag", "export"})

# Recipe-intent classes (as observed in data/revit_api_db.json, lowercased —
# ApiEntry.intent is normalized at load time in revit_api_index._load_recipes).
_RECIPE_READLIKE = frozenset({"query", "read", "count", "list", "analysis"})
_RECIPE_WRITE_WORD = frozenset({"write"})
_RECIPE_COMPOSITE = frozenset({"composite"})
_RECIPE_COORDINATION = frozenset({"coordination"})
_RECIPE_WRITELIKE_HARD = frozenset({"create", "delete", "modify", "write"})

# Turn-complexity classes that count as "the turn is itself multi-step"
# (G-tune, Wave-2 batch G2 — see G_TUNE_REPORT.md). Sourced from the same
# 5-way enum quick_classify/IntentClassifier already produce:
# trivial|simple|composite|hard|vague. "composite" is the direct signal;
# "hard" is what intent_rules._bump escalates a turn to when it was ALREADY
# composite and picked up a second compound/length signal — i.e. still
# multi-step, more so, not a different kind of turn — so it counts too.
# "vague" is deliberately excluded: an unclear turn is not a positive
# multi-step signal.
_TURN_COMPLEXITY_MULTISTEP = frozenset({"composite", "hard"})


def intent_join_enabled() -> bool:
    """Wave-2 batch G flag: default ON, ``"0"`` kills it (converse_gate's pattern)."""
    return os.getenv(_INTENT_JOIN_ENV, "1") != "0"


def _intent_match_factor(
    turn_intent: str,
    recipe_intent: str,
    turn_complexity: Optional[str] = None,
) -> float:
    """The multiplicative adjustment for one (turn_intent, recipe_intent) pair.

    Both sides are normalized lowercase (recipe side already normalized at
    load time; turn side normalized here so callers can pass either case).
    Order matters: MATCH checks run before HARD-MISMATCH checks — by
    construction the two never overlap for the class pairs below, but MATCH
    is checked first so a future class addition fails safe toward a boost
    rather than a demotion.

    ``turn_complexity`` (G-tune, Wave-2 batch G2 — see G_TUNE_REPORT.md,
    SKIPPED.md §G-2): optional, default ``None``. Batch G's original rule 4
    boosted EVERY ``composite``/``coordination``-tagged recipe (16.7% of the
    corpus) on virtually every non-converse turn, regardless of topical
    match — measured to displace on-point ``intent=None`` recipes out of
    top-10 in 15.4% of a 292-query battery. The fix makes the two recipe
    classes diverge:
      - ``composite`` recipe intent is now a CONDITIONAL match — boosted
        only when the turn ITSELF is classified multi-step
        (``turn_complexity`` in ``_TURN_COMPLEXITY_MULTISTEP``). Unknown/
        absent complexity (``None`` — the caller couldn't cheaply obtain
        it) or a known-simple turn -> NEUTRAL (never demoted; a composite
        recipe is not a hard mismatch for a simple turn, just not a
        positive signal for it).
      - ``coordination`` recipe intent (2/479 recipes, too small a sample
        and no cheap turn-side "coordination-ish" signal at this layer to
        justify a bespoke condition) is simplified to NEUTRAL always — the
        universal match is removed outright rather than guessed at.
    """
    turn = (turn_intent or "").strip().lower()
    recipe = (recipe_intent or "").strip().lower()
    complexity = (turn_complexity or "").strip().lower() or None
    if not turn or not recipe:
        return 1.0

    # 1. Exact same-word match (e.g. turn=create, recipe=create).
    if turn == recipe:
        return _INTENT_BOOST
    # 2. Cross-class MATCH: read-like turn <-> read-like recipe.
    if turn in _TURN_READLIKE and recipe in _RECIPE_READLIKE:
        return _INTENT_BOOST
    # 3. Cross-class MATCH: write-like turn <-> "write" recipe.
    if turn in _TURN_WRITELIKE and recipe in _RECIPE_WRITE_WORD:
        return _INTENT_BOOST
    # 4a. CONDITIONAL match (G-tune): a composite recipe matches only a
    #    turn that is itself multi-step. Never converse (defensive — a
    #    real converse turn's complexity is always "trivial" anyway, but
    #    this keeps the invariant explicit and testable). Falls through to
    #    NEUTRAL (1.0), never to a demotion — see docstring.
    if recipe in _RECIPE_COMPOSITE:
        if turn != "converse" and complexity in _TURN_COMPLEXITY_MULTISTEP:
            return _INTENT_BOOST
        return 1.0
    # 4b. NEUTRAL always (G-tune): coordination's universal match is
    #    removed outright rather than narrowed with an unverified guess.
    if recipe in _RECIPE_COORDINATION:
        return 1.0

    # 5. HARD-MISMATCH: a create/delete/modify/write recipe answering a
    #    count/list/filter/diagnose turn — the dominant measured harm.
    if recipe in _RECIPE_WRITELIKE_HARD and turn in _TURN_READLIKE:
        return _INTENT_DEMOTE_HARD
    # 6. Milder HARD-MISMATCH: a read/query/analysis recipe answering a
    #    create/delete turn — reads rarely harm writes, so a softer demote.
    if recipe in _RECIPE_READLIKE and turn in ("create", "delete"):
        return _INTENT_DEMOTE_SOFT

    return 1.0


def apply_intent_join(
    candidates: list[Candidate],
    turn_intent: Optional[str],
    turn_complexity: Optional[str] = None,
) -> tuple[list[Candidate], int]:
    """Re-scale recipe candidates' ``rrf_score`` by turn/recipe intent agreement.

    Mutates ``rrf_score`` in place on the ``Candidate`` objects (the list
    itself, and every non-recipe / no-intent candidate, is untouched) and
    returns ``(candidates, n_adjusted)`` where ``n_adjusted`` counts every
    candidate whose score was actually multiplied (boosted OR demoted — a
    ``1.0`` factor never counts). ``turn_intent is None`` -> immediate no-op.

    ``turn_complexity`` (G-tune, optional, default ``None``): threaded
    through to ``_intent_match_factor`` to gate the composite-recipe
    conditional match. ``None`` degrades safely to NEUTRAL for composite
    recipes (never boosted "for free") — callers that cannot cheaply obtain
    it (e.g. an older call site) get the same safe behaviour as before this
    tune, minus the over-broad universal boost.

    Classes/categories/parameters/rules/edges are never touched — this is
    scoped to ``entry_type == "recipe"`` candidates with a known ``.intent``.
    """
    if not turn_intent:
        return candidates, 0
    n_adjusted = 0
    for c in candidates:
        if c.entry.entry_type != "recipe":
            continue
        recipe_intent = getattr(c.entry, "intent", None)
        if not recipe_intent:
            continue
        factor = _intent_match_factor(turn_intent, recipe_intent, turn_complexity)
        if factor != 1.0:
            c.rrf_score *= factor
            n_adjusted += 1
    return candidates, n_adjusted


# ---------------------------------------------------------------------------
# Stage 2.6: capability-resolve (Stage 2, flag KUKAI_RAG_CAPABILITY_RESOLVE)
#
# CAPABILITY_FIRST_RAG.md §2/§6 step 3: "Resolve-then-Retrieve". Intent-join
# (above) is a soft, NOUN-agnostic nudge keyed on the recipe corpus's coarse
# `intent` field. Capability-resolve is the sharper structural stage the
# design doc calls for: the turn's OperationFrame `action` (closed 28-verb
# vocab, finer than `intent`) is matched against each recipe's OWN
# `capability.action` (Stage 1, CAPABILITY_CATALOG.md) — a lookup, not a
# fuzzy score. «изолируй монолит» resolves to `action=isolate`; the corpus's
# ONE isolate recipe should now structurally outrank the ~40 API classes and
# the foundation/concrete recipes that keyword/semantic similarity drags in
# (the diagnosed disease, §1 of the design doc).
#
# This is a STRUCTURAL BOOST, not a hard filter (design §7 risk: a
# mis-normalized action must never make the corpus's real answer
# unreachable) — matching recipes get a strong multiplicative boost.
# object_kinds overlap is a secondary, per-shared-kind boost layered on top
# of the action-match boost only (a tie-breaker WITHIN the resolved
# shortlist, not a signal for the fallback pool).
#
# Stage 2.1 (architect refinement, 2026-07-08 — see STAGE2_1_REPORT.md), two
# iterations, both measured on the 264-replay + 292-battery offline sets:
#
#   Iteration 1 — PROMOTE-ONLY (``apply_capability_resolve`` below, kept for
#   reference + its own regression tests, but NOT what ``retrieve()`` calls
#   anymore). The Stage-2 shadow measurement found the blanket ×0.5 DEMOTE of
#   every non-matching recipe sank plenty of otherwise-relevant recipes below
#   untouched classes in prod's "hard" ranking bucket (recipes+classes share
#   type_bucket 0). Dropping the demote (matched recipes keep the ×3.0 ×
#   object-kind promote; every OTHER recipe stays at its plain fused score)
#   shrank the regression a lot (recipes@10 delta roughly -1.8/-1.5 -> -0.36/
#   -0.13 on replay/battery) but did NOT eliminate it. Root cause, verified
#   directly against the measured output (STAGE2_1_REPORT.md §3): it isn't
#   really the ×3.0 losing a fair fight inside the shared bucket — it's that
#   whenever capability-resolve fires it SUBSUMES ``apply_intent_join`` for
#   that turn (the precedence rule below existed to avoid double-adjusting
#   the SAME recipe's score from two overlapping signals), which silently
#   un-boosts every OTHER recipe in the SAME pool that intent-join would
#   independently have helped — collateral damage from a precedence rule
#   written for a score-mutating mechanism.
#
#   Iteration 2 — POSITIONAL (``apply_capability_resolve_positional`` below,
#   SHIPPED — this is what ``retrieve()`` calls). Per the brief's authorized
#   fallback: matched-action recipes move to the FRONT of the final,
#   already-ranked candidate order (stable partition, no score math at all);
#   everything else keeps its EXISTING order — which now includes whatever
#   ``apply_intent_join`` already did to it, because intent-join no longer
#   needs to be subsumed: a pure reorder never competes with a score
#   adjustment for the same dimension, so the original double-adjustment
#   concern does not apply here. Runs as the LAST ranking step, AFTER
#   ``rank_candidates`` (a reorder before the score-based type/rrf sort would
#   just get re-sorted away — the type-bucket+score key doesn't know about
#   list position), immediately before the version-filter stage.
#
# object_kinds is accepted by both functions (secondary tie-break signal in
# the design doc, §3) but iteration 2 does not use it to reorder the matched
# shortlist — the brief's positional fallback is explicitly "no score math",
# and object-kind-aware reordering would still be a scored tie-break;
# documented as a known, deliberate simplification versus iteration 1 (see
# STAGE2_1_REPORT.md) rather than silently dropped.
#
# Both flag OFF (default, shadow) or no turn action known -> untouched,
# byte-identical to the pre-Stage-2 fusion+intent-join path.
#
# Stage 2.1-shadow (KUKAI_RAG_CAPABILITY_SHADOW, SHADOW_REPORT.md,
# 2026-07-08): a SEPARATE flag from KUKAI_RAG_CAPABILITY_RESOLVE, ON in prod
# BEFORE any flip decision. When resolve is OFF but shadow is ON and
# req.action is known, apply_capability_resolve_positional still runs — but
# on a COPY of the ranked list (see _emit_capability_shadow) — and the
# would-be reorder is LOGGED to data/telemetry/capability_shadow.jsonl
# instead of applied. Purpose: the offline A/B in STAGE2_1_REPORT.md drove
# req.action through quick_classify (rules-only, 18/28 actions); this
# collects the REAL LLM IntentClassifier OperationFrame on live traffic —
# what it actually emits, and what capability-resolve would do with it —
# before the flip decision. Resolve ON makes shadow moot (it is already
# live, skipped below); both OFF -> nothing.
# ---------------------------------------------------------------------------

_CAPABILITY_RESOLVE_ENV = "KUKAI_RAG_CAPABILITY_RESOLVE"

# Multiplicative boost (iteration 1, promote-only — architect-locked; see the
# block comment above). The whole point is to make the resolved shortlist
# dominate a corpus where a single real recipe is otherwise drowned by ~40
# topically-similar API classes (design §1); non-matching recipes are left
# at their plain fused score, never demoted.
_CAP_ACTION_BOOST = 3.0
_CAP_OBJECT_KIND_BOOST_PER = 1.15
_CAP_OBJECT_KIND_BOOST_CAP = 1.5


def capability_resolve_enabled() -> bool:
    """Stage 2 flag: default OFF (shadow) — ``"1"`` enables."""
    return os.getenv(_CAPABILITY_RESOLVE_ENV, "0") == "1"


_CAPABILITY_SHADOW_ENV = "KUKAI_RAG_CAPABILITY_SHADOW"


def capability_shadow_enabled() -> bool:
    """Stage 2.1-shadow flag (SHADOW_REPORT.md): default OFF — ``"1"`` enables.

    Independent of ``KUKAI_RAG_CAPABILITY_RESOLVE`` — read at call time, same
    discipline as ``capability_resolve_enabled``/``version_filter_enabled``,
    fail-open ``False`` on any error reading the environment. When resolve
    itself is ON there is nothing to shadow (the stage already runs live —
    ``retrieve()`` only consults this flag in the resolve-OFF branch). When
    resolve is OFF and this is ON, ``retrieve()`` computes what
    ``apply_capability_resolve_positional`` WOULD produce on a COPY of the
    final ranked list and logs it to ``data/telemetry/capability_shadow.jsonl``
    — the real ranked order used to answer the turn is never touched. Exists
    to collect REAL-LLM-classifier ``action``/``object_kinds`` data (via
    ``req.action`` threaded from the router's ``IntentClassifier`` result,
    independent of the resolve flag) on live prod traffic before deciding
    whether to flip ``KUKAI_RAG_CAPABILITY_RESOLVE``.
    """
    try:
        return os.getenv(_CAPABILITY_SHADOW_ENV, "0") == "1"
    except Exception:
        return False


def _capability_of(entry: "ApiEntry") -> Optional[dict]:
    cap = getattr(entry, "capability", None)
    return cap if isinstance(cap, dict) else None


def _object_kind_boost_factor(
    candidate_kinds: Any, requested_kinds: list[str],
) -> float:
    """×1.15 per object_kind shared between the recipe and the turn, capped.

    Neutral (1.0) whenever either side has nothing to compare — this is a
    secondary refinement, never a source of demotion.
    """
    if not requested_kinds or not candidate_kinds:
        return 1.0
    shared = {
        k.strip().lower() for k in candidate_kinds if isinstance(k, str)
    } & {
        k.strip().lower() for k in requested_kinds if isinstance(k, str)
    }
    if not shared:
        return 1.0
    return min(
        _CAP_OBJECT_KIND_BOOST_CAP, _CAP_OBJECT_KIND_BOOST_PER ** len(shared),
    )


def _match_capability(
    candidates: list[Candidate], action: Optional[str],
) -> tuple[Optional[str], list[Candidate], str]:
    """Shared match/validate core for both capability-resolve variants below:
    closed-vocab validation of ``action`` + finding every recipe candidate
    whose OWN ``capability.action`` equals it (in input order — callers that
    care about order get it for free).

    Returns ``(action_l, matched, detail)``:
      * ``detail`` in ``("no_action", "unknown_action")`` -> declined to run
        at all; ``action_l is None``, ``matched == []``.
      * ``detail == ""`` -> genuinely evaluated; ``matched`` may still be
        ``[]`` — a true capability gap, the caller's job to leave the pool
        untouched and flag it (never treat an empty match list here as
        "the same as an invalid action").
    """
    if not action:
        return None, [], "no_action"
    action_l = action.strip().lower()

    try:
        from kukai.agents.capability_vocab import action_vocab as _action_vocab
        known = action_l in _action_vocab()
    except Exception:
        logger.exception(
            "capability-resolve: vocab load failed — treating action as "
            "known (fail-open, do not silently drop a real turn signal)",
        )
        known = True
    if not known:
        return None, [], "unknown_action"

    matched: list[Candidate] = []
    for c in candidates:
        if c.entry.entry_type != "recipe":
            continue
        cap = _capability_of(c.entry)
        cap_action = cap.get("action") if cap else None
        if isinstance(cap_action, str) and cap_action.strip().lower() == action_l:
            matched.append(c)
    return action_l, matched, ""


def apply_capability_resolve(
    candidates: list[Candidate],
    action: Optional[str],
    object_kinds: Optional[list] = None,
) -> tuple[list[Candidate], int, bool, str]:
    """Resolve-then-retrieve capability stage — ITERATION 1, promote-only
    (CAPABILITY_FIRST_RAG §2, STAGE2_1_REPORT.md).

    NOT called by ``retrieve()`` — kept as a correct, independently-tested
    building block and for the measured A/B comparison in
    STAGE2_1_REPORT.md. See ``apply_capability_resolve_positional`` for what
    actually ships (the module-level block comment above explains why).

    Mutates ``rrf_score`` in place on recipe ``Candidate``s exactly like
    ``apply_intent_join`` — classes/categories/parameters/rules/edges are
    NEVER touched (scoped to ``entry_type == "recipe"``).

    Behaviour:
      * ``action`` falsy -> no-op, ``detail="no_action"``.
      * ``action`` not in the closed capability vocabulary (a hallucinated
        verb slipping past the classifier's own validation, or a stale
        caller) -> no-op, ``detail="unknown_action"`` — never treated as a
        real "gap" since it isn't a real action in the first place.
      * ``action`` known, ``>=1`` recipe candidate has
        ``capability.action == action`` -> those recipes get
        ``rrf_score *= 3.0 * object_kind_factor``; every OTHER recipe
        candidate (any entry_type=="recipe", matched or not — including
        recipes with no capability signal at all) is left untouched
        (Stage 2.1: no demote — see the module-level block comment).
        Fallback stays reachable at its plain fused rank, never sunk below
        it either.
      * ``action`` known, but NO recipe candidate matches -> a true
        capability GAP: candidates are returned COMPLETELY UNTOUCHED (no
        boost, no demotion — the honest "I have no recipe for this" signal;
        the caller sets a ``capability_gap:<action>`` health flag).

    Returns ``(candidates, n_matched, fired, detail)``:
      * ``n_matched`` — count of recipe candidates whose capability.action
        equals ``action`` (0 == gap).
      * ``fired`` — True iff candidates were actually boosted
        (``n_matched > 0``).
      * ``detail`` — ``""`` when the stage was genuinely evaluated (matched
        or gap); ``"no_action"``/``"unknown_action"`` when it declined to
        run at all.
    """
    action_l, matched, detail = _match_capability(candidates, action)
    if detail:
        return candidates, 0, False, detail
    if not matched:
        # True gap: leave the RRF-fused order completely untouched.
        return candidates, 0, False, ""

    requested_kinds = [
        k for k in (object_kinds or []) if isinstance(k, str) and k.strip()
    ]
    matched_ids = {id(c) for c in matched}
    for c in candidates:
        if c.entry.entry_type != "recipe" or id(c) not in matched_ids:
            continue
        cap = _capability_of(c.entry)
        cap_kinds = cap.get("object_kinds") if cap else None
        ok_factor = _object_kind_boost_factor(cap_kinds, requested_kinds)
        c.rrf_score *= _CAP_ACTION_BOOST * ok_factor
    # Every other recipe candidate is left untouched — no demote (iteration 1).

    return candidates, len(matched), True, ""


def apply_capability_resolve_positional(
    ranked_candidates: list[Candidate],
    action: Optional[str],
    object_kinds: Optional[list] = None,
) -> tuple[list[Candidate], int, bool, str]:
    """Resolve-then-retrieve capability stage — ITERATION 2, POSITIONAL.
    SHIPPED: this is what ``retrieve()`` calls (STAGE2_1_REPORT.md).

    No score mutation at all — a stable partition of an ALREADY-RANKED
    candidate list: every recipe candidate whose OWN ``capability.action``
    matches the turn's resolved ``action`` moves to the FRONT, keeping its
    existing relative order among themselves; everything else keeps its
    existing relative order too (which already reflects the type/rrf sort
    AND ``apply_intent_join``, since intent-join no longer needs to be
    subsumed for this variant — see the module-level block comment). Must be
    called on the FINAL ranked list (after ``rank_candidates``), not before
    it — reordering a pre-sort candidate list would just be re-sorted away
    by the subsequent score-keyed sort.

    ``object_kinds`` is accepted for signature symmetry with
    ``apply_capability_resolve`` and forward-compatibility, but — "no score
    math" — is NOT used to reorder the matched shortlist (a deliberate,
    documented simplification vs iteration 1; see STAGE2_1_REPORT.md).

    Behaviour and return shape mirror ``apply_capability_resolve`` exactly
    (``no_action``/``unknown_action`` no-ops, true-gap-untouched, matched
    count + fired flag) — only the mechanism (reorder vs score) differs.
    """
    action_l, matched, detail = _match_capability(ranked_candidates, action)
    if detail:
        return ranked_candidates, 0, False, detail
    if not matched:
        # True gap: leave the ranked order completely untouched.
        return ranked_candidates, 0, False, ""

    matched_ids = {id(c) for c in matched}
    rest = [c for c in ranked_candidates if id(c) not in matched_ids]
    return matched + rest, len(matched), True, ""


# ---------------------------------------------------------------------------
# Stage 2.1-shadow: capability-resolve SHADOW logging
# (flag KUKAI_RAG_CAPABILITY_SHADOW; SHADOW_REPORT.md)
#
# Every offline measurement of capability-resolve so far (STAGE2_REPORT.md,
# STAGE2_1_REPORT.md) drove ``req.action`` through ``quick_classify`` — the
# RULES-ONLY fallback. It cannot fully represent the real LLM
# ``IntentClassifier``'s OperationFrame (CHANGE 2 widened rules-only reach to
# 18/28 actions, still short of the LLM's full 28-way vocab + object_kinds
# fidelity). Before flipping ``KUKAI_RAG_CAPABILITY_RESOLVE`` for real, we
# want to see what the REAL classifier emits on LIVE prod traffic, and what
# capability-resolve WOULD reorder on that real signal — WITHOUT applying it.
#
# ``_emit_capability_shadow`` is the observe-only twin of the resolve branch
# in ``retrieve()``: same match logic (``apply_capability_resolve_
# positional``), but called on a COPY of the final ranked list so the
# production candidate order is provably untouched, then logs a compact
# before/after/quick-vs-real record to ``capability_shadow.jsonl`` and a
# ``capability_shadow`` retrieval_health leg. Guarded end-to-end: never
# raises, never slows, never alters the turn it observes.
# ---------------------------------------------------------------------------


def _shadow_top5(candidates: list[Candidate]) -> list[str]:
    """Top-5 entry keys, same ``f"{entry_type}:{namespace}.{name}"`` key
    convention as ``retrieval_health.set_final``'s ``final_keys`` — so a
    ``capability_shadow.jsonl`` row can be cross-referenced against the
    paired ``rag_retrieval.jsonl`` row's ``health.final_keys`` by
    ``query_id``."""
    return [c.key for c in candidates[:5]]


def _emit_capability_shadow(
    ranked: list[Candidate], req: "RetrievalRequest",
) -> None:
    """Compute + log what capability-resolve WOULD do, without applying it.

    Called from ``retrieve()`` only when ``capability_resolve_enabled()`` is
    False, ``capability_shadow_enabled()`` is True, and ``req.action`` is
    truthy. Runs ``apply_capability_resolve_positional`` on a **copy** of
    ``ranked`` (``list(ranked)``) — the positional helper performs no score
    mutation and already returns a new list, but the copy is a deliberate
    defensive boundary: this function's contract ("the real ranked list is
    never touched") must hold even if a future change to the positional
    helper started mutating its input. The caller's ``ranked`` is NEVER
    reassigned or written to.

    Silently declines (no record, no health leg) when the action is unknown
    to the closed vocab or absent — mirrors the resolve branch's own
    ``no_action``/``unknown_action`` silence (a stage that never genuinely
    evaluated the turn stays quiet rather than reporting noise).

    Never raises — every internal step (quick_classify comparison, telemetry
    emit, health leg) is independently guarded so a bug in this OBSERVE-ONLY
    path can never break, slow, or alter the real turn it is watching.
    """
    from kukai.rag.retrieval_health import current as _rh_current
    from kukai.rag.retrieval_health import report_leg as _report_leg

    _t0 = time.perf_counter()
    shadow_ranked, n_matched, fired, detail = apply_capability_resolve_positional(
        list(ranked), req.action, req.object_kinds,
    )
    if detail in ("no_action", "unknown_action"):
        return  # declined to evaluate at all — nothing to shadow, stay silent

    action_l = (req.action or "").strip().lower()

    # The offline proxy (quick_classify) vs the real action actually driving
    # this shadow computation (req.action, sourced from the LLM classifier
    # when it landed — see client.py's Phase-7.5 plumbing) — the whole point
    # of this stage is measuring how often/where these two disagree.
    quick_action = None
    try:
        from kukai.agents.intent_rules import quick_classify as _qc
        quick_action = _qc(req.query or "").get("action")
    except Exception:
        quick_action = None

    top5_before = _shadow_top5(ranked)          # the REAL, live order
    top5_after = _shadow_top5(shadow_ranked)     # the would-be order (unapplied)

    query_id = None
    try:
        h = _rh_current()
        query_id = h.query_id if h is not None else None
    except Exception:
        query_id = None

    row = {
        "action": req.action,
        "object_kinds": req.object_kinds,
        "quick_action": quick_action,
        "matched_recipe_count": n_matched,
        "capability_gap": {"gap": not fired, "action": action_l},
        "top5_before": top5_before,
        "top5_after": top5_after,
        "changed": top5_before != top5_after,
    }
    try:
        from kukai.telemetry_rag import log_capability_shadow
        log_capability_shadow(query_id, row)
    except Exception as _shadow_exc:
        logger.debug("capability-shadow telemetry emit failed (non-fatal)", exc_info=True)
        try:
            from kukai.telemetry import note_telemetry_failure
            note_telemetry_failure(_shadow_exc)
        except Exception:
            pass

    _report_leg(
        "capability_shadow", "ran", n_matched,
        (time.perf_counter() - _t0) * 1000.0, req.action,
    )


# ---------------------------------------------------------------------------
# Stage 3: the ranking policy (pure, measured)
# ---------------------------------------------------------------------------


def rank_candidates(
    candidates: list[Candidate],
    mode: str = "hard",
    weight_other: float = 0.9,
) -> list[Candidate]:
    """Rank fused candidates under one of the measured policies (plan 018 §1).

    Each mode returns a NEW list, ordered by a STABLE sort so that ties fall
    back to the input (insertion) order. The input order is never mutated.

      * ``hard``     — ``(type_bucket, -rrf_score)``: classes/recipes always
        outrank everything else. **Byte-identical** to the pre-extraction sort.
      * ``tiebreak`` — ``(-rrf_score, type_bucket)``: RRF decides; the type
        bucket only breaks exact RRF ties.
      * ``weight``   — fold the type prior into the score
        (``rrf_score`` for bucket 0, ``rrf_score * weight_other`` for bucket 1),
        sort by ``-weighted``; tie-break on the bucket. ``weight_other``
        defaults to 0.9 (a soft, tunable prior).

    An unknown mode logs a WARNING once and falls back to ``hard`` — config must
    never throw on the hot path.
    """
    if mode not in _VALID_MODES:
        _warn_unknown_mode(mode)
        mode = "hard"

    if mode == "hard":
        return sorted(candidates, key=lambda c: (c.type_bucket, -c.rrf_score))
    if mode == "tiebreak":
        return sorted(candidates, key=lambda c: (-c.rrf_score, c.type_bucket))
    # mode == "weight"
    return sorted(
        candidates,
        key=lambda c: (
            -(c.rrf_score * (1.0 if c.type_bucket == 0 else weight_other)),
            c.type_bucket,
        ),
    )


_WARNED_MODES: set[str] = set()


def _warn_unknown_mode(mode: str) -> None:
    if mode not in _WARNED_MODES:
        _WARNED_MODES.add(mode)
        logger.warning(
            "Unknown rag_rank_type_mode %r — falling back to 'hard'. "
            "Valid modes: %s",
            mode,
            sorted(_VALID_MODES),
        )


def _resolve_mode() -> tuple[str, float]:
    """Read the ranking mode + weight from settings (getattr-defaulted).

    Defaults are byte-identical to today: ``hard`` / 0.9. Read per call via
    ``get_settings()`` (same pattern as ``semantic_search``). Tolerant of a
    Settings object that doesn't yet declare the fields (getattr default), so
    the module works whether or not the config declarations have landed.
    """
    try:
        from kukai.config import get_settings as _gs
        settings = _gs()
        mode = getattr(settings, "rag_rank_type_mode", "hard") or "hard"
        weight_other = float(getattr(settings, "rag_type_weight_other", 0.9))
        return mode, weight_other
    except Exception:
        return "hard", 0.9


# ---------------------------------------------------------------------------
# Fitted ranking policy (IQ moment #9): measured-and-set, not hand-guessed
#
# The module docstring has always promised "a *measured policy*"; this is the
# mechanism that finally closes the loop. ``scripts/fit_rank_policy.py`` grid-
# searches (w_keyword, w_semantic, w_phrasings, type_prior, mode) against the
# gold set and writes the winner to ``data/rank_policy.json``. At retrieval
# time the policy is consulted ONLY when BOTH gates are open:
#
#   * env flag ``KUKAI_RANK_POLICY=1``   (default OFF — dark, same pattern as
#     ``KUKAI_BM25F``), AND
#   * the policy file exists and validates (mode ∈ _VALID_MODES, weights
#     finite ≥ 0, type_prior finite > 0).
#
# Every other state — flag off, file absent, malformed JSON, bad values —
# fails OPEN to the legacy path (unweighted fuse + settings-resolved mode),
# which is byte-identical to today. Never raises into the hot path.
# ---------------------------------------------------------------------------

_RANK_POLICY_FLAG_ENV = "KUKAI_RANK_POLICY"
_RANK_POLICY_FILE_ENV = "KUKAI_RANK_POLICY_FILE"

# The three production RRF legs, in leg order (== LegResult.name values).
RRF_LEG_NAMES: tuple[str, ...] = ("keyword", "semantic", "phrasings")


@dataclass(frozen=True)
class RankPolicy:
    """A fitted ranking policy: per-leg RRF weights + type-prior knob + mode.

    ``type_prior_weight`` is ``rank_candidates``' ``weight_other`` (the factor
    applied to non-recipe/class candidates under ``mode='weight'``; unused by
    ``hard``/``tiebreak`` but always carried so the artifact is complete).
    """

    weights: dict[str, float] = field(default_factory=dict)
    mode: str = "hard"
    type_prior_weight: float = 0.9
    source: str = ""


def rank_policy_enabled() -> bool:
    """Feature flag ``KUKAI_RANK_POLICY`` — default OFF (dark), '1' enables."""
    return os.getenv(_RANK_POLICY_FLAG_ENV, "0") == "1"


def _rank_policy_path() -> Path:
    """Policy file location: ``$KUKAI_RANK_POLICY_FILE`` override, else
    ``backend/data/rank_policy.json`` (path anchored on this file, not cwd)."""
    override = (os.getenv(_RANK_POLICY_FILE_ENV) or "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / "rank_policy.json"


def load_rank_policy(path: "Path | str") -> Optional[RankPolicy]:
    """Parse + validate a rank-policy JSON file. ``None`` on ANY problem.

    Accepted schema (extra keys — fit metadata — are ignored):
      ``{"mode": "hard|tiebreak|weight", "type_prior_weight": float > 0,
        "weights": {"keyword": w, "semantic": w, "phrasings": w}}``
    Missing leg weights default to 1.0 (neutral); weights must be finite and
    ≥ 0 (0 silences a leg — a legitimate fitted outcome).
    """
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        _warn_bad_policy(p, "not a JSON object")
        return None

    mode = doc.get("mode")
    if not isinstance(mode, str) or mode not in _VALID_MODES:
        _warn_bad_policy(p, f"invalid mode {mode!r}")
        return None

    try:
        type_prior = float(doc.get("type_prior_weight", 0.9))
    except (TypeError, ValueError):
        _warn_bad_policy(p, "non-numeric type_prior_weight")
        return None
    if not math.isfinite(type_prior) or not (0.0 < type_prior <= 10.0):
        _warn_bad_policy(p, f"type_prior_weight out of range: {type_prior!r}")
        return None

    raw_weights = doc.get("weights", {})
    if not isinstance(raw_weights, dict):
        _warn_bad_policy(p, "weights is not an object")
        return None
    weights: dict[str, float] = {}
    for leg in RRF_LEG_NAMES:
        try:
            w = float(raw_weights.get(leg, 1.0))
        except (TypeError, ValueError):
            _warn_bad_policy(p, f"non-numeric weight for leg {leg!r}")
            return None
        if not math.isfinite(w) or w < 0.0:
            _warn_bad_policy(p, f"weight for leg {leg!r} out of range: {w!r}")
            return None
        weights[leg] = w

    return RankPolicy(
        weights=weights, mode=mode, type_prior_weight=type_prior, source=str(p),
    )


_WARNED_POLICIES: set[str] = set()


def _warn_bad_policy(path: Path, reason: str) -> None:
    tag = f"{path}::{reason}"
    if tag not in _WARNED_POLICIES:
        _WARNED_POLICIES.add(tag)
        logger.warning(
            "rank policy %s rejected (%s) — falling back to the legacy "
            "ranking path", path, reason,
        )


# Single-slot cache keyed by (path, mtime_ns, size): one stat() per retrieval,
# JSON re-parsed only when the file actually changes. Caches None for an
# invalid file too, so a bad artifact does not re-parse+re-warn every turn.
_POLICY_CACHE: dict = {"sig": None, "policy": None}
_ANNOUNCED_POLICIES: set = set()


def _reset_rank_policy_cache() -> None:
    """Test/refit hook: forget the cached policy (and its announcement)."""
    _POLICY_CACHE["sig"] = None
    _POLICY_CACHE["policy"] = None
    _ANNOUNCED_POLICIES.clear()


def active_rank_policy() -> Optional[RankPolicy]:
    """The policy the hot path should use RIGHT NOW, or ``None`` for legacy.

    Reads the flag + file signature at call time (same read-at-call discipline
    as ``version_filter_enabled``/``feature_enabled``) so operators can flip
    the flag or drop a re-fitted file without a restart. NEVER raises.
    """
    try:
        if not rank_policy_enabled():
            return None
        p = _rank_policy_path()
        try:
            st = p.stat()
        except OSError:
            return None  # absent file — dark, legacy path
        sig = (str(p), st.st_mtime_ns, st.st_size)
        if _POLICY_CACHE["sig"] == sig:
            return _POLICY_CACHE["policy"]
        policy = load_rank_policy(p)
        _POLICY_CACHE["sig"] = sig
        _POLICY_CACHE["policy"] = policy
        if policy is not None and sig not in _ANNOUNCED_POLICIES:
            _ANNOUNCED_POLICIES.add(sig)
            logger.info(
                "rank policy ACTIVE from %s: mode=%s type_prior=%.3f weights=%s",
                p, policy.mode, policy.type_prior_weight, policy.weights,
            )
        return policy
    except Exception:
        logger.exception("active_rank_policy failed — legacy ranking path")
        return None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def retrieve(index: "RevitApiIndex", req: RetrievalRequest) -> list[Candidate]:
    """Run legs -> RRF -> ranking policy -> version filter; report health.

    Returns the ranked candidate list (NOT truncated; the caller slices to
    ``top_k``). The ``rrf_fuse`` leg report and the ``no_results`` /
    ``keyword_only`` flags are emitted here exactly as the old ``search()`` did.

    The version-filter stage (design §2.2) runs LAST, on the full ranked list,
    so the caller's ``top_k`` slice yields top-k *version-valid* entries
    (dropped entries are refilled from deeper ranks, never shrinking the
    reranker pool). ``KUKAI_RAG_VERSION_FILTER=0`` skips this stage entirely —
    the exact legacy world where filtering (if any) happens in the enricher.
    """
    from kukai.rag.retrieval_health import add_flag as _add_flag
    from kukai.rag.retrieval_health import report_leg as _report_leg

    legs = run_legs(index, req)

    # Fitted ranking policy (IQ moment #9): active ONLY when the
    # KUKAI_RANK_POLICY flag is on AND data/rank_policy.json validates —
    # then the fitted per-leg weights + mode + type prior replace the
    # hand-guessed defaults. Inactive (the dark default) → the EXACT legacy
    # path below: unweighted fuse, settings-resolved mode. active_rank_policy
    # never raises (fail-open to legacy).
    policy = active_rank_policy()
    if policy is not None:
        candidates = rrf_fuse(legs, _RRF_K, weights=policy.weights)
    else:
        candidates = rrf_fuse(legs, _RRF_K)

    # Intent-join (Wave-2 batch G, Stage 2.5): re-scale recipe candidates'
    # rrf_score by turn/recipe intent agreement, AFTER fusion and BEFORE the
    # type-priority sort so the adjusted score is what ``rank_candidates``
    # sorts on. Flag OFF or no turn intent known -> untouched (candidates is
    # the same list rank_candidates would have seen anyway). Never raises.
    #
    # Stage 2.1: runs UNCONDITIONALLY on its own gates now (no longer
    # subsumed by capability-resolve — see the capability-resolve block
    # comment above for why: capability-resolve is now a positional reorder
    # of the FINAL ranked list, which never competes with a score
    # adjustment, so the double-adjustment concern the old precedence rule
    # guarded against does not apply).
    if intent_join_enabled() and req.intent:
        try:
            _ij_t0 = time.perf_counter()
            candidates, _ij_n = apply_intent_join(
                candidates, req.intent, req.complexity,
            )
            _report_leg(
                "intent_join", "ran", _ij_n,
                (time.perf_counter() - _ij_t0) * 1000.0, req.intent,
            )
        except Exception:
            logger.exception("intent-join failed — fail-open (unadjusted)")

    if policy is not None:
        ranked = rank_candidates(candidates, policy.mode, policy.type_prior_weight)
    else:
        mode, weight_other = _resolve_mode()
        ranked = rank_candidates(candidates, mode, weight_other)

    # Capability-resolve (Stage 2, Stage 2.6; Stage 2.1: POSITIONAL,
    # iteration 2 — see the stage's own docstring/comment block above for
    # the full design rationale + why this replaced the promote-only score
    # variant). Runs LAST, on the FINAL ranked list (after intent-join AND
    # the type/rrf sort) — a stable partition, matched-action recipes moved
    # to the front, everything else keeping its already-ranked relative
    # order. Flag OFF (default/shadow) or no turn action known -> no report
    # is emitted at all (mirrors the intent-join precedent: a stage that
    # never attempted anything stays silent, not "skipped_flag"-chatty).
    # Never raises.
    if capability_resolve_enabled():
        try:
            _cr_t0 = time.perf_counter()
            ranked, _cap_n, _cap_fired, _cap_detail = apply_capability_resolve_positional(
                ranked, req.action, req.object_kinds,
            )
            if _cap_detail not in ("no_action", "unknown_action"):
                _report_leg(
                    "capability_resolve", "ran", _cap_n,
                    (time.perf_counter() - _cr_t0) * 1000.0, req.action,
                )
                if not _cap_fired:
                    # A true gap (§6 step 4 of the design doc): the corpus
                    # has no recipe for a resolved, KNOWN action — exactly
                    # the data the gap map (CAPABILITY_CATALOG.md §d) is
                    # meant to surface. Candidates are untouched (see
                    # apply_capability_resolve_positional's own gap branch).
                    _add_flag(f"capability_gap:{(req.action or '').strip().lower()}")
        except Exception:
            logger.exception("capability-resolve failed — fail-open (unadjusted)")
    elif capability_shadow_enabled() and req.action:
        # Stage 2.1-shadow (KUKAI_RAG_CAPABILITY_SHADOW, SHADOW_REPORT.md):
        # resolve is OFF, but we want REAL-LLM-classifier data on live prod
        # traffic before deciding whether to flip it. Computes what the
        # positional reorder WOULD produce on a COPY of `ranked` and logs
        # it; `ranked` itself is NEVER reassigned here — the real candidate
        # order returned by this call stays byte-identical to the resolve-
        # and-shadow-both-off path. Never raises.
        try:
            _emit_capability_shadow(ranked, req)
        except Exception:
            logger.exception(
                "capability-shadow failed — fail-open (observe-only, no-op)",
            )

    _report_leg("rrf_fuse", "ran" if ranked else "empty", len(ranked))
    if not ranked:
        _add_flag("no_results")
    else:
        # keyword_only iff only the keyword leg produced anything.
        leg_by_name = {leg.name: leg for leg in legs}
        kw = leg_by_name.get("keyword")
        sem = leg_by_name.get("semantic")
        ph = leg_by_name.get("phrasings")
        if (
            kw is not None and kw.entries
            and (sem is None or not sem.entries)
            and (ph is None or not ph.entries)
        ):
            _add_flag("keyword_only")

    # Version-filter stage (design §2.2): the reranked path is filtered BY
    # CONSTRUCTION because every consumer of retrieve()/search() passes
    # through here. Flag OFF → stage skipped wholesale (legacy behaviour,
    # including the enricher-side filter and its disclosures, is preserved
    # exactly). Fail-open: an internal error never breaks retrieval.
    try:
        if version_filter_enabled():
            ranked = filter_candidates(
                ranked, req.revit_version or _turn_revit_version(),
            )
    except Exception:
        logger.exception("version-filter stage failed — fail-open (unfiltered)")

    return ranked
