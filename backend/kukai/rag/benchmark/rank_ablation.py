"""Rank-mode ablation: legs once, rank N ways (plan 018 §2).

The expensive part of retrieval (the legs + RRF fusion) is run EXACTLY ONCE per
gold query; then each candidate ranking mode is applied to the same fused
candidate list and scored with ``gold.hit_at_k``. This is what makes a ranking
experiment cost one retrieval instead of N (research P1.1), and it shares the
plan-009 health instrument + plan-009 honest report so the table self-documents
which tree/legs produced it.

Offline-legal: only the keyword + phrasings legs run (semantic reports
``skipped_no_key`` without a key) — disclosed via the leg manifest. The live
3-leg confirmation is operator-gated (``--live --yes-spend``).

A "mode spec" is a string: ``hard`` | ``tiebreak`` | ``weight`` | ``weight@0.9``
(the ``@`` suffix overrides ``weight_other`` for that arm; default 0.9).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from kukai.rag import retrieval_health
from kukai.rag.benchmark.gold_ru import RuGoldQuery
from kukai.rag.benchmark.prod_replica import HIT_KS, _entry_key
from kukai.rag.retrieval import (
    RetrievalRequest,
    rank_candidates,
    rrf_fuse,
    run_legs,
)
from kukai.rag.revit_api_index import RevitApiIndex

DEFAULT_MODES: tuple[str, ...] = ("hard", "tiebreak", "weight@0.9", "weight@0.75")
# The reference mode every other mode's flips are measured against.
REFERENCE_MODE = "hard"


def parse_mode_spec(spec: str) -> tuple[str, str, float]:
    """``"weight@0.75"`` -> ``("weight@0.75", "weight", 0.75)``.

    Returns ``(label, mode, weight_other)``. ``weight_other`` is only meaningful
    for the ``weight`` mode; for others it is the default 0.9 (unused).
    """
    spec = spec.strip()
    if "@" in spec:
        mode, _, raw = spec.partition("@")
        try:
            return spec, mode.strip(), float(raw)
        except ValueError:
            return spec, mode.strip(), 0.9
    return spec, spec, 0.9


@dataclass
class RankAblationQueryResult:
    """One gold query scored under every mode (raw+strict Hit@K per mode)."""

    id: str
    rag_query: str
    health: dict
    strict_excluded: bool
    # per mode-label -> {"raw": {k: bool}, "strict": {k: bool}} + final_keys
    per_mode: dict = field(default_factory=dict)
    latency_ms: float = 0.0


class RankAblationPipeline:
    """Runs the legs once per query, then scores every requested ranking mode."""

    def __init__(
        self,
        modes: Optional[list[str]] = None,
        top_k_retrieve: int = 15,
        top_k_final: int = 10,
        live: bool = False,
        index: Optional[RevitApiIndex] = None,
    ) -> None:
        self.mode_specs = [parse_mode_spec(m) for m in (modes or list(DEFAULT_MODES))]
        self.top_k_retrieve = top_k_retrieve
        self.top_k_final = top_k_final
        self.live = live
        self.index = index or RevitApiIndex()
        self.index.load()
        self._llm = None

    def _translate(self, gold: RuGoldQuery) -> str:
        if self.live:
            # Reuse the prod-replica live translator for parity.
            from kukai.rag.benchmark.prod_replica import ProdReplicaPipeline

            if self._llm is None:
                self._llm = ProdReplicaPipeline(live=True, index=self.index)
            rag_query = self._llm._translate_live(gold)
            retrieval_health.report_leg("translate", "ran", 1, 0.0, "live")
            return rag_query
        rag_query = gold.en or gold.ru
        retrieval_health.report_leg("translate", "replayed")
        return rag_query

    def run_query(self, gold: RuGoldQuery) -> RankAblationQueryResult:
        from kukai.llm.client import _expand_rag_query

        t0 = time.perf_counter()
        h = retrieval_health.begin_turn()
        try:
            rag_query = self._translate(gold)

            pre_expand = rag_query
            rag_query = _expand_rag_query(rag_query)
            retrieval_health.report_leg(
                "expand", "ran" if rag_query != pre_expand else "empty"
            )

            # Legs + fusion ONCE.
            req = RetrievalRequest(query=rag_query, top_k=self.top_k_retrieve)
            legs = run_legs(self.index, req)
            candidates = rrf_fuse(legs)
            retrieval_health.report_leg(
                "rrf_fuse", "ran" if candidates else "empty", len(candidates)
            )

            per_mode: dict = {}
            for label, mode, weight_other in self.mode_specs:
                ranked = rank_candidates(candidates, mode, weight_other)
                keys = [_entry_key(c.entry) for c in ranked[: self.top_k_final]]
                hits: dict = {"raw": {}, "strict": {}}
                for k in HIT_KS:
                    hits["raw"][k] = gold.hit_at_k(keys, k, strict=False)
                    hits["strict"][k] = gold.hit_at_k(keys, k, strict=True)
                per_mode[label] = {"final_keys": keys, "hits": hits}

            health = h.to_dict()
        finally:
            retrieval_health.finish_turn(h)

        return RankAblationQueryResult(
            id=gold.id,
            rag_query=rag_query,
            health=health,
            strict_excluded=gold.strict_excluded(),
            per_mode=per_mode,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )
