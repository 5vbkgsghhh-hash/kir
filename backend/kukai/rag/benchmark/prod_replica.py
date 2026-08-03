"""Prod-replica retrieval pipeline for the plan-009 honest benchmark.

Mirrors the LIVE retrieval sequence in ``client.py:_stream_chat_inner``
(translate -> expand -> ``index.search`` -> rerank -> version filter) by
calling the SAME production symbols, with a ``retrieval_health.begin_turn()``
active so the per-leg health reports come from the production instrumentation
itself — not a parallel reimplementation. This is what makes the benchmark a
measurement of production, not of a copy.

Parity guard: ``test_replica_calls_prod_symbols`` spies on
``kukai.llm.client._expand_rag_query`` and ``RevitApiIndex.search`` to prove
``run_query`` invoked the real functions. If the client retrieval sequence
changes, this replica must change in the same PR (see plan 009 Maintenance
notes — the parity risk to watch until a typed RetrievalService exists).

Offline (default): translation is *replayed* from the gold ``en`` reading; the
semantic and rerank legs report ``skipped_no_*`` because no key is present.
Live (``--live``, out of CI): the real ``LLMClient._translate_for_rag``,
``semantic_search`` and ``cohere_rerank`` run, requiring API keys + network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from kukai.rag import retrieval_health
from kukai.rag.benchmark.gold_ru import RuGoldQuery
from kukai.rag.revit_api_index import RevitApiIndex

# K values reported for every query (raw + strict flavours).
HIT_KS: tuple[int, ...] = (1, 3, 5, 10)


def _build_live_llm_client():
    """Live-mode LLMClient, constructed from settings like kukai/main.py:105-127.

    Only the fields translation needs: model + keys + fallback. No bridge,
    no prompt assembler (we never stream tools from the benchmark). Fixes the
    plan-014 crash: the previous ``LLMClient()`` call omitted the required
    positional ``model`` and raised ``TypeError`` on every ``--live`` run.
    """
    from kukai.config import get_settings
    from kukai.llm.client import LLMClient

    s = get_settings()
    return LLMClient(
        model=s.llm_model,
        api_key=s.llm_api_key,
        api_base=s.llm_api_base,
        fallback_model=s.llm_fallback_model,
        fallback_api_key=s.llm_fallback_api_key,
        fallback_timeout=s.llm_fallback_timeout,
        timeout=s.llm_timeout,
    )


def _entry_key(e) -> str:
    """Final-key convention identical to ``revit_api_index.search`` RRF keys."""
    return f"{getattr(e, 'entry_type', '')}:{getattr(e, 'namespace', '')}.{getattr(e, 'name', '')}"


@dataclass
class RerankOrderings:
    """The three orderings captured around the live rerank leg (plan 018 §3).

    ``baseline`` is the fused order with NO rerank; ``raw`` is the cohere/
    nemotron order BEFORE the essentials floor; ``floored`` is after the floor
    (the prod treatment — this is what ``run_query`` continues to use for
    everything existing). ``ran`` is False when the rerank leg did not produce
    an order (no key, error, fewer than 5 entries) — the ablation aggregates
    count ONLY queries where ``ran`` is True (mixed-n Δs lie).
    """

    baseline: list           # list[ApiEntry] — fused order, pre-rerank
    raw: list                # list[ApiEntry] — cohere order, pre-floor
    floored: list            # list[ApiEntry] — cohere order, post-floor (prod)
    ran: bool = False


@dataclass
class ReplicaQueryResult:
    """Per-query benchmark result holding hits, attribution and the health dict."""

    id: str
    rag_query: str
    final_keys: list[str]
    health: dict
    # hit[flavour][k] -> bool ; flavour in {"raw","strict"}
    hits: dict = field(default_factory=dict)
    strict_excluded: bool = False
    # legs whose ISOLATED top-K contained a gold API (raw flavour)
    found_by: list[str] = field(default_factory=list)
    # legs that were the SOLE finder (raw flavour)
    only_by: list[str] = field(default_factory=list)
    latency_ms: float = 0.0
    # plan 018 §3 — paired rerank ablation, present ONLY when the rerank leg ran.
    # {"ran": bool, "<arm>": {"raw": {k: bool}, "strict": {k: bool}}} for arms
    # baseline / rerank_raw / rerank_floored; hits computed on the same gold,
    # truncated to top_k_final, BEFORE the version filter (disclosed).
    rerank_ablation: Optional[dict] = None


class ProdReplicaPipeline:
    """Replays the production retrieval sequence over a shared, preloaded index."""

    def __init__(
        self,
        top_k_retrieve: int = 15,
        top_k_final: int = 10,
        live: bool = False,
        revit_version: Optional[str] = None,
        index: Optional[RevitApiIndex] = None,
    ) -> None:
        self.top_k_retrieve = top_k_retrieve
        self.top_k_final = top_k_final
        self.live = live
        self.revit_version = revit_version
        self.index = index or RevitApiIndex()
        self.index.load()
        self._llm = None  # constructed lazily only in live mode

    # -- live-only translation -------------------------------------------------
    def _translate_live(self, gold: RuGoldQuery) -> str:
        import asyncio

        if self._llm is None:
            self._llm = _build_live_llm_client()
        try:
            translated = asyncio.run(self._llm._translate_for_rag(gold.ru))
            return translated or gold.en or gold.ru
        except Exception:
            return gold.en or gold.ru

    # -- main ------------------------------------------------------------------
    def run_query(self, gold: RuGoldQuery) -> ReplicaQueryResult:
        from kukai.llm.client import _expand_rag_query

        t0 = time.perf_counter()
        h = retrieval_health.begin_turn()
        try:
            # 1. translate leg
            if self.live:
                rag_query = self._translate_live(gold)
                retrieval_health.report_leg("translate", "ran", 1, 0.0, "live")
            else:
                rag_query = gold.en or gold.ru
                retrieval_health.report_leg("translate", "replayed")

            # 2. expand leg — the REAL module-level production function.
            pre_expand = rag_query
            rag_query = _expand_rag_query(rag_query)
            retrieval_health.report_leg(
                "expand", "ran" if rag_query != pre_expand else "empty"
            )

            # 3. fused retrieval — the REAL instrumented production search. Its
            #    keyword/semantic/phrasings/rrf_fuse legs are reported into `h`.
            fused = self.index.search(rag_query, top_k=self.top_k_retrieve)

            # -- per-leg attribution: run keyword/semantic in ISOLATION ---------
            kw_keys = [
                _entry_key(e)
                for e in self.index.keyword_search(rag_query, top_k=self.top_k_final)
            ]
            if self.live and self.index.has_embeddings:
                sem_keys = [
                    _entry_key(e)
                    for e in self.index.semantic_search(
                        rag_query, top_k=self.top_k_final
                    )
                ]
                sem_available = True
            else:
                sem_keys = []
                sem_available = False

            # 4. rerank leg
            ordered = fused
            rerank_ablation: Optional[dict] = None
            if self.live and len(fused) >= 5:
                orderings = self._rerank_live(rag_query, gold, fused)
                # The floored order is the prod treatment — everything existing
                # continues to use it, so all existing aggregates are untouched.
                ordered = orderings.floored
                if orderings.ran:
                    rerank_ablation = self._rerank_ablation(gold, orderings)
            else:
                retrieval_health.report_leg("rerank", "skipped_no_key")

            # 5. version filter leg
            if self.revit_version:
                ordered = self._apply_version_filter(ordered)
            else:
                retrieval_health.report_leg("version_filter", "skipped_flag")

            final_entries = ordered[: self.top_k_final]
            final_keys = [_entry_key(e) for e in final_entries]
            retrieval_health.set_final(final_entries)

            # -- hits at K (raw + strict) on the FINAL fused order --------------
            hits: dict = {"raw": {}, "strict": {}}
            for k in HIT_KS:
                hits["raw"][k] = gold.hit_at_k(final_keys, k, strict=False)
                hits["strict"][k] = gold.hit_at_k(final_keys, k, strict=True)

            # -- found_by / only_by attribution (raw, top-K of each leg) -------
            leg_keys = {
                "keyword": kw_keys,
                "semantic": sem_keys if sem_available else None,
                "fused": final_keys,
            }
            found_by: list[str] = []
            for leg, keys in leg_keys.items():
                if keys is None:
                    continue
                if any(gold.matches_key(key, strict=False) for key in keys):
                    found_by.append(leg)
            # only_by = legs (excluding the aggregate "fused") that were sole finders
            attributable = [lg for lg in found_by if lg != "fused"]
            only_by = attributable if len(attributable) == 1 else []

            health = h.to_dict()
        finally:
            retrieval_health.finish_turn(h)

        return ReplicaQueryResult(
            id=gold.id,
            rag_query=rag_query,
            final_keys=final_keys,
            health=health,
            hits=hits,
            strict_excluded=gold.strict_excluded(),
            found_by=found_by,
            only_by=only_by,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            rerank_ablation=rerank_ablation,
        )

    # -- live rerank (same args as client.py:1480-1495) ------------------------
    def _rerank_live(
        self, rag_query: str, gold: RuGoldQuery, entries: list
    ) -> "RerankOrderings":
        """Run the live rerank and return the THREE orderings (plan 018 §3).

        Mirrors the client args exactly. Previously this discarded the
        pre-rerank order and the pre-floor order — exactly the data the paired
        ablation needs. The floored order remains what ``run_query`` uses for
        ``final_keys`` and every existing aggregate, so prod behaviour and the
        existing report schema are untouched.
        """
        import asyncio

        try:
            from kukai.agents.cohere_rerank import (
                cohere_rerank,
                apply_essentials_floor,
                looks_like_write,
            )
            from kukai import config as _kcfg

            names = [getattr(e, "name", "") for e in entries]
            docs = [
                f"{getattr(e,'entry_type','class')} "
                f"{getattr(e,'namespace','')}.{getattr(e,'name','?')}: "
                f"{(getattr(e,'description','') or '')[:300]}"
                for e in entries
            ]
            order = asyncio.run(
                cohere_rerank(
                    rag_query, docs,
                    model=getattr(_kcfg, "AGENT_RERANK_MODEL", None),
                    timeout=5.0,
                )
            )
            if order:
                raw_entries = [entries[i] for i in order]
                floored_order = apply_essentials_floor(
                    list(order), names,
                    is_write=looks_like_write(gold.ru or rag_query),
                )
                floored_entries = [entries[i] for i in floored_order]
                retrieval_health.report_leg("rerank", "ran", len(floored_order))
                retrieval_health.set_rerank_moved(
                    sum(1 for i, j in enumerate(floored_order[:5]) if i != j)
                )
                return RerankOrderings(
                    baseline=entries,
                    raw=raw_entries,
                    floored=floored_entries,
                    ran=True,
                )
            retrieval_health.report_leg("rerank", "error", 0, 0.0, "no_order")
        except Exception as e:  # pragma: no cover - live only
            retrieval_health.report_leg("rerank", "error", 0, 0.0, type(e).__name__)
        # No usable order — every arm falls back to the fused baseline; ran=False
        # so the ablation aggregates skip this query (mixed-n Δs would lie).
        return RerankOrderings(baseline=entries, raw=entries, floored=entries, ran=False)

    def _rerank_ablation(self, gold: RuGoldQuery, orderings: "RerankOrderings") -> dict:
        """Per-arm Hit@K for the three orderings (plan 018 §3).

        Hits are computed on the SAME gold, truncated to ``top_k_final``, and
        BEFORE any version filter (disclosed) so the three arms are compared on
        equal footing. Arm names match the report aggregator
        (``build_report``): baseline / rerank_raw / rerank_floored.
        """
        def _arm_hits(entries: list) -> dict:
            keys = [_entry_key(e) for e in entries[: self.top_k_final]]
            out: dict = {"raw": {}, "strict": {}}
            for k in HIT_KS:
                out["raw"][k] = gold.hit_at_k(keys, k, strict=False)
                out["strict"][k] = gold.hit_at_k(keys, k, strict=True)
            return out

        return {
            "ran": True,
            "strict_excluded": gold.strict_excluded(),
            "baseline": _arm_hits(orderings.baseline),
            "rerank_raw": _arm_hits(orderings.raw),
            "rerank_floored": _arm_hits(orderings.floored),
        }

    # -- version filter (predicate from rag_prompt.py:106-118) -----------------
    def _apply_version_filter(self, entries: list) -> list:
        from kukai.rag.rag_prompt import _parse_revit_year

        project_year = _parse_revit_year(self.revit_version)
        if project_year is None:
            retrieval_health.report_leg("version_filter", "skipped_flag")
            return entries
        before = len(entries)
        kept = [
            e for e in entries
            if not (
                getattr(e, "since", "")
                and (_parse_revit_year(getattr(e, "since", "")) or 0) > project_year
            )
        ]
        retrieval_health.set_version_filtered_out(before - len(kept))
        retrieval_health.report_leg("version_filter", "ran", len(kept))
        return kept
