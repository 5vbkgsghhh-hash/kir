"""Benchmark runner — feeds gold-set queries through each RAGPath.

Two modes:
1. retrieval_only=True (default): measure retrieval quality only (Hit@K,
   api_coverage, latency). No LLM, no compile, fast (~seconds for full set).
2. retrieval_only=False: full e2e — send enriched prompt to LLM, compile-check,
   record first_compile_ok and e2e_success. Slow (~minutes), real cost in
   LLM tokens. Run after retrieval-only winner is identified.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from kukai.rag.benchmark.gold_set import GoldQuery
from kukai.rag.benchmark.metrics import PathSummary, QueryResult, summarize
from kukai.rag.benchmark.paths.base import RAGPath

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkRun:
    path_name: str
    summary: PathSummary
    per_query: list[QueryResult]


def run_path_retrieval_only(
    path: RAGPath,
    gold: list[GoldQuery],
    context: Optional[dict[str, Any]] = None,
) -> BenchmarkRun:
    """Run all gold queries through one path, measure retrieval-side metrics.

    Skips LLM/compile — the cheapest, most repeatable measurement. Run this
    first to filter out paths that don't even retrieve the right APIs.
    """
    per_query: list[QueryResult] = []

    for q in gold:
        t_start = time.perf_counter()
        try:
            result = path.enrich(q.query, context=context)
        except Exception as exc:
            logger.exception("Path %s failed on query: %s", path.name, q.query)
            per_query.append(
                QueryResult(
                    query=q.query,
                    path_name=path.name,
                    hit_at_1=False,
                    hit_at_5=False,
                    api_coverage=0.0,
                    first_compile_ok=None,
                    repair_attempts_used=0,
                    e2e_success=None,
                    retrieval_latency_ms=0.0,
                    total_latency_ms=0.0,
                    final_error=str(exc)[:300],
                )
            )
            continue

        total_ms = (time.perf_counter() - t_start) * 1000.0
        retrieval_ms = float(result.metadata.get("latency_ms", total_ms))

        # Hit@K — match retrieved_ids against expected_snippet_ids
        # (only meaningful if gold entries have IDs filled in)
        hit_at_1 = False
        hit_at_5 = False
        if q.expected_snippet_ids:
            top1 = result.retrieved_ids[:1]
            top5 = result.retrieved_ids[:5]
            hit_at_1 = any(q.matches_id(rid) for rid in top1)
            hit_at_5 = any(q.matches_id(rid) for rid in top5)

        # API coverage — fraction of expected_apis in retrieved_apis
        if q.expected_apis:
            retrieved_set = {a.lower() for a in result.retrieved_apis}
            matched = sum(
                1 for api in q.expected_apis if api.lower() in retrieved_set
            )
            api_cov = matched / len(q.expected_apis)
        else:
            api_cov = 0.0

        per_query.append(
            QueryResult(
                query=q.query,
                path_name=path.name,
                hit_at_1=hit_at_1,
                hit_at_5=hit_at_5,
                api_coverage=api_cov,
                first_compile_ok=None,  # not measured in retrieval-only mode
                repair_attempts_used=0,
                e2e_success=None,
                retrieval_latency_ms=retrieval_ms,
                total_latency_ms=total_ms,
                retrieved_ids=result.retrieved_ids[:10],
            )
        )

    return BenchmarkRun(
        path_name=path.name,
        summary=summarize(path.name, per_query),
        per_query=per_query,
    )


def format_summary_table(runs: list[BenchmarkRun]) -> str:
    """Produce a side-by-side text table of path metrics."""
    if not runs:
        return "(no runs)"

    rows = [
        ("path", lambda s: s.path_name),
        ("n", lambda s: str(s.n_queries)),
        ("hit@1", lambda s: f"{s.hit_at_1_pct:.1f}%"),
        ("hit@5", lambda s: f"{s.hit_at_5_pct:.1f}%"),
        ("api_cov", lambda s: f"{100*s.api_coverage_avg:.1f}%"),
        ("retr_p50", lambda s: f"{s.retrieval_latency_p50_ms:.0f}ms"),
        ("retr_p95", lambda s: f"{s.retrieval_latency_p95_ms:.0f}ms"),
    ]

    headers = [name for name, _ in rows]
    cells = [[fn(r.summary) for _, fn in rows] for r in runs]
    cells.insert(0, headers)

    widths = [max(len(c[i]) for c in cells) for i in range(len(headers))]
    lines = []
    for ci, c in enumerate(cells):
        line = "  ".join(c[i].ljust(widths[i]) for i in range(len(c)))
        lines.append(line)
        if ci == 0:
            lines.append("  ".join("-" * widths[i] for i in range(len(c))))

    return "\n".join(lines)
