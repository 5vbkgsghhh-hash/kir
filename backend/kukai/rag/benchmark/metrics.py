"""Benchmark metrics — what we measure to declare a winner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class QueryResult:
    """Per-query measurements for one path."""

    query: str
    path_name: str

    # Retrieval quality
    hit_at_1: bool
    """Top-1 retrieved entry is in gold's expected_snippet_ids."""
    hit_at_5: bool
    """Any of top-5 retrieved is in expected_snippet_ids."""
    api_coverage: float
    """Fraction of expected_apis that appear in retrieved_apis (0..1)."""

    # Generation quality (requires LLM in the loop)
    first_compile_ok: Optional[bool]
    """Did the LLM's first code attempt compile? None if generation skipped."""
    repair_attempts_used: int
    """How many repair iterations needed (0 = first-shot success). Up to 3."""
    e2e_success: Optional[bool]
    """Did the final code compile within the repair budget? None if generation skipped."""

    # Performance
    retrieval_latency_ms: float
    total_latency_ms: float

    # Optional debug payload
    retrieved_ids: list[str] = field(default_factory=list)
    final_code: Optional[str] = None
    final_error: Optional[str] = None


@dataclass
class PathSummary:
    """Aggregated metrics for one path across the gold-set."""

    path_name: str
    n_queries: int

    hit_at_1_pct: float
    hit_at_5_pct: float
    api_coverage_avg: float

    first_compile_ok_pct: Optional[float]
    e2e_success_pct: Optional[float]
    avg_repair_attempts: float

    retrieval_latency_p50_ms: float
    retrieval_latency_p95_ms: float
    total_latency_p50_ms: float


def summarize(path_name: str, results: list[QueryResult]) -> PathSummary:
    """Aggregate per-query results into a path summary."""
    n = len(results)
    if n == 0:
        return PathSummary(
            path_name=path_name,
            n_queries=0,
            hit_at_1_pct=0.0,
            hit_at_5_pct=0.0,
            api_coverage_avg=0.0,
            first_compile_ok_pct=None,
            e2e_success_pct=None,
            avg_repair_attempts=0.0,
            retrieval_latency_p50_ms=0.0,
            retrieval_latency_p95_ms=0.0,
            total_latency_p50_ms=0.0,
        )

    pct = lambda xs: round(100.0 * sum(xs) / len(xs), 1) if xs else 0.0
    avg = lambda xs: round(sum(xs) / len(xs), 3) if xs else 0.0

    hit1 = [r.hit_at_1 for r in results]
    hit5 = [r.hit_at_5 for r in results]
    cov = [r.api_coverage for r in results]
    rep_iters = [r.repair_attempts_used for r in results]

    fc_done = [r.first_compile_ok for r in results if r.first_compile_ok is not None]
    e2e_done = [r.e2e_success for r in results if r.e2e_success is not None]

    rt_lats = sorted(r.retrieval_latency_ms for r in results)
    tot_lats = sorted(r.total_latency_ms for r in results)

    def _pct(sorted_vals: list[float], q: float) -> float:
        if not sorted_vals:
            return 0.0
        idx = max(0, min(len(sorted_vals) - 1, int(round(q * (len(sorted_vals) - 1)))))
        return round(sorted_vals[idx], 1)

    return PathSummary(
        path_name=path_name,
        n_queries=n,
        hit_at_1_pct=pct(hit1),
        hit_at_5_pct=pct(hit5),
        api_coverage_avg=avg(cov),
        first_compile_ok_pct=pct(fc_done) if fc_done else None,
        e2e_success_pct=pct(e2e_done) if e2e_done else None,
        avg_repair_attempts=avg(rep_iters),
        retrieval_latency_p50_ms=_pct(rt_lats, 0.5),
        retrieval_latency_p95_ms=_pct(rt_lats, 0.95),
        total_latency_p50_ms=_pct(tot_lats, 0.5),
    )
