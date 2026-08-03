"""Honest report writer for the plan-009 RAG benchmark.

Honesty rules, enforced in CODE (a number without disclosure is forbidden by
construction — this is exactly what made the 98.2% fiction possible):

  1. ``build_report`` raises ``ValueError`` if the leg manifest is empty.
  2. The rendered markdown ALWAYS prints the leg manifest table BEFORE any
     Hit@K number (``render_md`` index of "Leg manifest" < index of "Hit@").
  3. ``degraded_run`` is set in the header whenever any strong leg
     (translate/semantic/rerank) did not truly run for the whole set — a
     keyless offline run is ALWAYS ``degraded_run: true``.
  4. Every report embeds the git SHA + sha256[:12] fingerprints of the
     load-bearing files, so a run on a drifted tree self-discloses which tree
     it measured (the three-tree drift landmine, plan 009 "Current state").
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from kukai.rag.benchmark.gold_ru import UBIQUITOUS
from kukai.rag.benchmark.prod_replica import HIT_KS, ReplicaQueryResult

SCHEMA_VERSION = 1

# Strong legs whose absence makes a run degraded (cannot be quoted as "the" number).
_STRONG_LEGS = ("translate", "semantic", "rerank")

# The six load-bearing files whose fingerprints pin a report to a tree.
_FINGERPRINT_FILES = (
    "kukai/rag/revit_api_index.py",
    "kukai/rag/rag_prompt.py",
    "kukai/llm/client.py",
    "kukai/agents/cohere_rerank.py",
    "data/revit_api_db.json",
    "data/rag_embeddings.npz",
)


def _backend_root() -> Path:
    # backend/kukai/rag/benchmark/report.py -> backend/
    return Path(__file__).resolve().parents[3]


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_backend_root()),
            capture_output=True,
            text=True,
            timeout=5,
        )
        sha = out.stdout.strip()
        return sha or "unknown"
    except Exception:
        return "unknown"


def _fingerprints() -> dict:
    root = _backend_root()
    fp: dict = {}
    for rel in _FINGERPRINT_FILES:
        p = root / rel
        try:
            fp[rel] = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
        except Exception:
            fp[rel] = "absent"
    return fp


def _config_snapshot() -> dict:
    """All KUKAI_AGENT_* / KUKAI_RAG_* env values present (names + values)."""
    return {
        k: v
        for k, v in sorted(os.environ.items())
        if k.startswith("KUKAI_AGENT_") or k.startswith("KUKAI_RAG_")
    }


def _leg_manifest_from_health(healths: list[dict]) -> dict:
    """Per-leg status rollup across a list of ``RetrievalHealth.to_dict()``.

    A leg's manifest status is the MOST COMMON status it reported across turns
    (e.g. semantic: skipped_no_key on every keyless turn). Shared by the
    retrieval-mode and e2e-mode report builders.
    """
    from collections import Counter

    per_leg: dict[str, Counter] = {}
    for health in healths:
        for leg in health.get("legs", []):
            name = leg.get("name", "?")
            status = leg.get("status", "?")
            per_leg.setdefault(name, Counter())[status] += 1
    manifest: dict = {}
    for name, counter in per_leg.items():
        top_status, _ = counter.most_common(1)[0]
        manifest[name] = {
            "status": top_status,
            "by_status": dict(counter),
        }
    return manifest


def _leg_manifest(results: list[ReplicaQueryResult]) -> dict:
    """Per-leg status rollup across the run: leg -> {status: count}."""
    return _leg_manifest_from_health([r.health for r in results])


def _is_degraded(manifest: dict) -> bool:
    """A run is degraded if any strong leg never truly ran across the set."""
    for leg in _STRONG_LEGS:
        info = manifest.get(leg)
        if info is None:
            return True
        # If the leg's dominant status is anything other than ran/replayed-with-
        # a-real-run, treat the strong leg as not-truly-run for the whole set.
        statuses = set(info.get("by_status", {}).keys())
        if not (statuses & {"ran"}):
            # translate may legitimately be "replayed" offline — still degraded
            # because the LIVE translation leg did not run.
            return True
    return False


def _agg_hits(results: list[ReplicaQueryResult]) -> dict:
    """Aggregate Hit@K for raw and strict flavours.

    strict aggregates EXCLUDE queries whose strict-expected list is empty
    (counted separately as ``strict_excluded``).
    """
    out: dict = {"raw": {}, "strict": {}, "n_raw": 0, "n_strict": 0, "strict_excluded": 0}
    raw_rows = results
    strict_rows = [r for r in results if not r.strict_excluded]
    out["n_raw"] = len(raw_rows)
    out["n_strict"] = len(strict_rows)
    out["strict_excluded"] = sum(1 for r in results if r.strict_excluded)
    for k in HIT_KS:
        out["raw"][k] = (
            sum(1 for r in raw_rows if r.hits.get("raw", {}).get(k)) / len(raw_rows)
            if raw_rows
            else 0.0
        )
        out["strict"][k] = (
            sum(1 for r in strict_rows if r.hits.get("strict", {}).get(k))
            / len(strict_rows)
            if strict_rows
            else 0.0
        )
    return out


def _found_by_histogram(results: list[ReplicaQueryResult]) -> dict:
    from collections import Counter

    fb: Counter = Counter()
    ob: Counter = Counter()
    for r in results:
        for leg in r.found_by:
            fb[leg] += 1
        for leg in r.only_by:
            ob[leg] += 1
    return {"found_by": dict(fb), "only_by": dict(ob)}


def _rerank_ablation_aggregates(results: list[ReplicaQueryResult]) -> Optional[dict]:
    """Paired rerank-ablation aggregates (plan 018 §3) — None if no rerank ran.

    Counts ONLY queries whose rerank leg ``ran`` (mixed-n Δs lie). For each arm
    (baseline / rerank_raw / rerank_floored) reports Hit@K raw+strict; the
    headline deltas are Δ(floored−baseline) and Δ(raw−baseline) in pp on each K;
    flip lists are the query ids that gained/lost strict Hit@5 under the floored
    arm vs baseline. The arms here are evaluated on the SAME gold, BEFORE the
    version filter (disclosed in the per-query record).
    """
    rows = [r for r in results if (r.rerank_ablation or {}).get("ran")]
    if not rows:
        return None

    arms = ("baseline", "rerank_raw", "rerank_floored")
    # strict aggregates exclude strict-excluded queries (parity with _agg_hits).
    strict_rows = [r for r in rows if not r.rerank_ablation.get("strict_excluded")]

    per_arm: dict = {}
    for arm in arms:
        raw_d: dict = {}
        strict_d: dict = {}
        for k in HIT_KS:
            raw_d[k] = (
                sum(1 for r in rows if r.rerank_ablation[arm]["raw"].get(k)) / len(rows)
                if rows else 0.0
            )
            strict_d[k] = (
                sum(1 for r in strict_rows if r.rerank_ablation[arm]["strict"].get(k))
                / len(strict_rows)
                if strict_rows else 0.0
            )
        per_arm[arm] = {"raw": raw_d, "strict": strict_d}

    def _delta_pp(treat: str, base: str) -> dict:
        d: dict = {"raw": {}, "strict": {}}
        for k in HIT_KS:
            d["raw"][k] = round((per_arm[treat]["raw"][k] - per_arm[base]["raw"][k]) * 100.0, 1)
            d["strict"][k] = round(
                (per_arm[treat]["strict"][k] - per_arm[base]["strict"][k]) * 100.0, 1
            )
        return d

    # flips on strict Hit@5 (floored vs baseline) — plan 019 miss-feedback material.
    gained: list[str] = []
    lost: list[str] = []
    for r in strict_rows:
        b = r.rerank_ablation["baseline"]["strict"].get(5, False)
        f = r.rerank_ablation["rerank_floored"]["strict"].get(5, False)
        if f and not b:
            gained.append(r.id)
        elif b and not f:
            lost.append(r.id)

    return {
        "n": len(rows),
        "n_strict": len(strict_rows),
        "arms": per_arm,
        "delta_floored_vs_baseline_pp": _delta_pp("rerank_floored", "baseline"),
        "delta_raw_vs_baseline_pp": _delta_pp("rerank_raw", "baseline"),
        "flips_strict_at5": {"gained": gained, "lost": lost},
    }


def _latency_pcts(results: list[ReplicaQueryResult]) -> dict:
    lat = sorted(r.latency_ms for r in results)
    if not lat:
        return {"p50": 0.0, "p95": 0.0}

    def _pct(p: float) -> float:
        idx = min(len(lat) - 1, int(round(p * (len(lat) - 1))))
        return round(lat[idx], 2)

    return {"p50": _pct(0.50), "p95": _pct(0.95)}


def _assert_offline_uncontaminated(manifest: dict, results: list[ReplicaQueryResult]) -> None:
    """Plan-014 belt-and-braces: an "offline" report must contain NO money legs.

    Fires only for ``mode == "offline"``. A `.env` reachable from cwd (the prod
    tree) flips the semantic/rerank legs live silently — the hermeticity guard
    is the first defence; this is the second, at report-build time, so a number
    labelled offline can never have been bought. ``semantic: empty`` still means
    a live embedding call happened, so it counts as contamination too.
    """
    def _ran_or_empty(leg_name: str) -> bool:
        info = manifest.get(leg_name) or {}
        statuses = set(info.get("by_status", {}).keys())
        return bool(statuses & {"ran", "empty"})

    if _ran_or_empty("semantic"):
        raise ValueError(
            "offline report contaminated by live legs — the mode label would "
            "lie (semantic leg ran/empty means a live embedding call fired); "
            "see plan 014 hermeticity"
        )
    rerank = manifest.get("rerank") or {}
    if "ran" in set(rerank.get("by_status", {}).keys()):
        raise ValueError(
            "offline report contaminated by live legs — rerank ran live; "
            "see plan 014 hermeticity"
        )
    # A translate leg whose detail is "live" (prod_replica.run_query sets this)
    # also means a paid translation call happened under an "offline" label.
    for r in results:
        for leg in r.health.get("legs", []):
            if leg.get("name") == "translate" and leg.get("detail") == "live":
                raise ValueError(
                    "offline report contaminated by live legs — translate ran "
                    "live; see plan 014 hermeticity"
                )


def build_report(results: list[ReplicaQueryResult], config: dict) -> dict:
    """Assemble the report dict. Raises ValueError if the leg manifest is empty."""
    manifest = _leg_manifest(results)
    if not manifest:
        raise ValueError(
            "refusing to build a report with an empty leg manifest — a Hit@K "
            "without its leg manifest is forbidden by construction (plan 009)"
        )
    if config.get("mode") == "offline":
        _assert_offline_uncontaminated(manifest, results)
    degraded = _is_degraded(manifest)
    aggregates: dict = {
        "hits": _agg_hits(results),
        "attribution": _found_by_histogram(results),
        "latency_ms": _latency_pcts(results),
    }
    # plan 018 §3 — additive: only present when the live rerank leg actually ran
    # (offline reports stay byte-stable; the key never appears for them).
    rerank_ablation = _rerank_ablation_aggregates(results)
    if rerank_ablation is not None:
        aggregates["rerank_ablation"] = rerank_ablation
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "degraded_run": degraded,
        "mode": config.get("mode", "offline"),
        "n_queries": len(results),
        "leg_manifest": manifest,
        "config_snapshot": _config_snapshot(),
        "cli_config": config,
        "fingerprints": _fingerprints(),
        "ubiquitous_excluded_in_strict": sorted(UBIQUITOUS),
        "aggregates": aggregates,
        "queries": [
            {
                "id": r.id,
                "rag_query": r.rag_query[:240],
                "final_keys": r.final_keys,
                "hits": r.hits,
                "strict_excluded": r.strict_excluded,
                "found_by": r.found_by,
                "only_by": r.only_by,
                "latency_ms": round(r.latency_ms, 2),
                "degraded": r.health.get("degraded", False),
            }
            for r in results
        ],
    }


def render_md(report: dict) -> str:
    """Render the report as markdown — leg manifest table BEFORE any Hit@K."""
    lines: list[str] = []
    lines.append("# RAG measurement spine — benchmark report (plan 009)")
    lines.append("")
    lines.append(
        f"- generated: `{report['generated_utc']}` | git: `{report['git_sha']}` "
        f"| mode: `{report['mode']}` | queries: {report['n_queries']}"
    )
    lines.append(f"- **degraded_run: {str(report['degraded_run']).lower()}**")
    lines.append("")

    # -- LEG MANIFEST FIRST (honesty rule 2) ---------------------------------
    lines.append("## Leg manifest")
    lines.append("")
    lines.append("| leg | dominant status | by_status |")
    lines.append("|---|---|---|")
    for name in sorted(report["leg_manifest"].keys()):
        info = report["leg_manifest"][name]
        by = ", ".join(f"{s}={c}" for s, c in sorted(info["by_status"].items()))
        lines.append(f"| {name} | {info['status']} | {by} |")
    lines.append("")
    if report["degraded_run"]:
        lines.append(
            "> DEGRADED RUN: one or more strong legs (translate/semantic/rerank) "
            "did not truly run for the whole set — these Hit@K numbers are a "
            "floor, not the production number. Run with `--live` + API keys for "
            "the full figure."
        )
        lines.append("")

    # -- Hit@K ----------------------------------------------------------------
    agg = report["aggregates"]["hits"]
    lines.append("## Hit@K")
    lines.append("")
    lines.append(
        f"- raw over n={agg['n_raw']} | strict over n={agg['n_strict']} "
        f"(strict drops {report['ubiquitous_excluded_in_strict']}; "
        f"{agg['strict_excluded']} queries strict-excluded)"
    )
    lines.append("")
    lines.append("| K | Hit@K raw | Hit@K strict |")
    lines.append("|---|---|---|")
    for k in HIT_KS:
        lines.append(
            f"| {k} | {agg['raw'][k] * 100:.1f}% | {agg['strict'][k] * 100:.1f}% |"
        )
    lines.append("")

    # -- attribution ----------------------------------------------------------
    attr = report["aggregates"]["attribution"]
    lines.append("## Per-leg attribution")
    lines.append("")
    lines.append(f"- found_by (leg's isolated top-K held a gold API): `{attr['found_by']}`")
    lines.append(f"- only_by (sole finder): `{attr['only_by']}`")
    lines.append("")

    # -- rerank ablation (E3) — only present on live runs where rerank ran ---
    ra = report["aggregates"].get("rerank_ablation")
    if ra is not None:
        lines.append("## Rerank ablation (E3)")
        lines.append("")
        lines.append(
            f"- n (rerank ran) = {ra['n']} | strict over n={ra['n_strict']} "
            "| arms: baseline (fused, no rerank) / rerank_raw (pre-floor) / "
            "rerank_floored (prod)"
        )
        lines.append("")
        lines.append(
            "| K | base raw | raw raw | floored raw | base strict | raw strict | floored strict |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        arms = ra["arms"]
        for k in HIT_KS:
            lines.append(
                f"| {k} "
                f"| {arms['baseline']['raw'][k] * 100:.1f}% "
                f"| {arms['rerank_raw']['raw'][k] * 100:.1f}% "
                f"| {arms['rerank_floored']['raw'][k] * 100:.1f}% "
                f"| {arms['baseline']['strict'][k] * 100:.1f}% "
                f"| {arms['rerank_raw']['strict'][k] * 100:.1f}% "
                f"| {arms['rerank_floored']['strict'][k] * 100:.1f}% |"
            )
        lines.append("")
        df = ra["delta_floored_vs_baseline_pp"]
        dr = ra["delta_raw_vs_baseline_pp"]
        lines.append("| K | Δ floored−baseline (pp) | Δ raw−baseline (pp) | (raw/strict) |")
        lines.append("|---|---|---|---|")
        for k in HIT_KS:
            lines.append(
                f"| {k} | {df['raw'][k]:+.1f} / {df['strict'][k]:+.1f} "
                f"| {dr['raw'][k]:+.1f} / {dr['strict'][k]:+.1f} | raw / strict |"
            )
        lines.append("")
        flips = ra["flips_strict_at5"]
        lines.append(
            f"- flips strict@5 (floored vs baseline): "
            f"gained ({len(flips['gained'])}) {flips['gained']} | "
            f"lost ({len(flips['lost'])}) {flips['lost']}"
        )
        lines.append("")

    # -- latency + fingerprints ----------------------------------------------
    lat = report["aggregates"]["latency_ms"]
    lines.append(f"## Latency: p50={lat['p50']}ms p95={lat['p95']}ms")
    lines.append("")
    lines.append("## File fingerprints (sha256[:12])")
    lines.append("")
    for rel, fp in sorted(report["fingerprints"].items()):
        lines.append(f"- `{rel}` = `{fp}`")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# E2E pass-rate report (plan 014) — the apex metric (scorecard C11)
# ---------------------------------------------------------------------------


def _e2e_aggregates(results: list) -> dict:
    """Pass-rate aggregates over a list of ``e2e.E2EQueryResult``."""
    n = len(results)
    fc_done = [r.first_compile_ok for r in results if r.first_compile_ok is not None]
    e2e_done = [r.e2e_success for r in results if r.e2e_success is not None]
    rep = [r.repair_attempts_used for r in results]
    fix = [1 for r in results if r.fixer_changed]

    def _pct(xs: list) -> Optional[float]:
        return round(100.0 * sum(1 for x in xs if x) / len(xs), 1) if xs else None

    def _avg(xs: list) -> float:
        return round(sum(xs) / len(xs), 3) if xs else 0.0

    # Hit@K over the queries that carry hits (raw flavour).
    hit_ks: dict = {}
    for k in (5, 10):
        vals = [bool(r.hits.get("raw", {}).get(k)) for r in results if r.hits]
        hit_ks[k] = round(100.0 * sum(vals) / len(vals), 1) if vals else None

    return {
        "pass": {
            "first_compile_ok_pct": _pct(fc_done),
            "e2e_success_pct": _pct(e2e_done),
            "avg_repair_attempts": _avg(rep),
            "fixer_changed_pct": round(100.0 * len(fix) / n, 1) if n else None,
            "n_first_compile_scored": len(fc_done),
            "n_e2e_scored": len(e2e_done),
        },
        "hits": {"raw@5": hit_ks.get(5), "raw@10": hit_ks.get(10)},
    }


def _retrieval_outcome_2x2(results: list) -> dict:
    """The 2×2 that makes grounding visible: hit@10 ∧ e2e_success quadrants."""
    q = {"hit_pass": 0, "hit_fail": 0, "miss_pass": 0, "miss_fail": 0}
    for r in results:
        hit = bool(r.hits.get("raw", {}).get(10))
        ok = bool(r.e2e_success)
        if hit and ok:
            q["hit_pass"] += 1
        elif hit and not ok:
            q["hit_fail"] += 1
        elif not hit and ok:
            q["miss_pass"] += 1
        else:
            q["miss_fail"] += 1
    return q


def build_e2e_report(results: list, config: dict) -> dict:
    """Assemble the e2e pass-rate report dict.

    Same honesty skeleton as ``build_report``: raises on an empty leg manifest,
    embeds git SHA + fingerprints + config snapshot, and renders the manifest
    BEFORE any pass-rate. ``mode`` is ``e2e-smoke`` (mock body) or ``e2e-live``.
    """
    healths = [r.health for r in results]
    manifest = _leg_manifest_from_health(healths)
    if not manifest:
        raise ValueError(
            "refusing to build an e2e report with an empty leg manifest — a "
            "pass-rate without its leg manifest is forbidden by construction "
            "(plan 014 / plan 009)"
        )
    smoke = bool(config.get("smoke"))
    degraded = _is_degraded(manifest)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "e2e",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "mode": "e2e-smoke" if smoke else "e2e-live",
        "arm": config.get("arm", ""),
        "model": config.get("model", "mock-smoke" if smoke else ""),
        "degraded_run": degraded,
        "n_queries": len(results),
        "leg_manifest": manifest,
        "config_snapshot": _config_snapshot(),
        "cli_config": config,
        "fingerprints": _fingerprints(),
        "aggregates": _e2e_aggregates(results),
        "retrieval_outcome_2x2": _retrieval_outcome_2x2(results),
        "queries": [
            {
                "id": r.id,
                "arm": r.arm,
                "first_compile_ok": r.first_compile_ok,
                "repair_attempts_used": r.repair_attempts_used,
                "e2e_success": r.e2e_success,
                "fixer_changed": r.fixer_changed,
                "cs_errors_final": r.cs_errors_final,
                "hits": r.hits,
                "latency_ms": round(r.latency_ms, 2),
                "rag_query": (r.rag_query or "")[:240],
            }
            for r in results
        ],
    }


def render_e2e_md(report: dict) -> str:
    """Render the e2e report — leg manifest table BEFORE any pass-rate."""
    lines: list[str] = []
    lines.append("# RAG grounding grader — e2e pass-rate report (plan 014)")
    lines.append("")
    if report.get("mode") == "e2e-smoke":
        lines.append(
            "> MOCK LLM RUN — pass-rate measures the harness, not a model. "
            "Never quote it."
        )
        lines.append("")
    lines.append(
        f"- generated: `{report['generated_utc']}` | git: `{report['git_sha']}` "
        f"| mode: `{report['mode']}` | arm: `{report.get('arm','')}` "
        f"| model: `{report.get('model','')}` | queries: {report['n_queries']}"
    )
    lines.append(f"- **degraded_run: {str(report['degraded_run']).lower()}**")
    lines.append("")

    # -- LEG MANIFEST FIRST (honesty rule) -----------------------------------
    lines.append("## Leg manifest")
    lines.append("")
    lines.append("| leg | dominant status | by_status |")
    lines.append("|---|---|---|")
    for name in sorted(report["leg_manifest"].keys()):
        info = report["leg_manifest"][name]
        by = ", ".join(f"{s}={c}" for s, c in sorted(info["by_status"].items()))
        lines.append(f"| {name} | {info['status']} | {by} |")
    lines.append("")

    # -- pass-rate block ------------------------------------------------------
    agg = report["aggregates"]["pass"]
    lines.append("## Pass-rate")
    lines.append("")
    lines.append("| metric | value |")
    lines.append("|---|---|")
    lines.append(
        f"| first_compile_ok | {_fmt_pct(agg['first_compile_ok_pct'])} "
        f"(n={agg['n_first_compile_scored']}) |"
    )
    lines.append(
        f"| e2e_success | {_fmt_pct(agg['e2e_success_pct'])} "
        f"(n={agg['n_e2e_scored']}) |"
    )
    lines.append(f"| avg_repair_attempts | {agg['avg_repair_attempts']} |")
    lines.append(f"| fixer_changed | {_fmt_pct(agg['fixer_changed_pct'])} |")
    lines.append("")

    # -- retrieval → outcome (the grounding 2×2) -----------------------------
    q = report["retrieval_outcome_2x2"]
    hits = report["aggregates"]["hits"]
    lines.append("## Retrieval → outcome (hit@10 ∧ e2e_success)")
    lines.append("")
    lines.append(f"- Hit@5: {_fmt_pct(hits.get('raw@5'))} | Hit@10: {_fmt_pct(hits.get('raw@10'))}")
    lines.append(
        f"- hit∧pass={q['hit_pass']} | hit∧fail={q['hit_fail']} | "
        f"miss∧pass={q['miss_pass']} | miss∧fail={q['miss_fail']}"
    )
    lines.append("")

    # -- fingerprints ---------------------------------------------------------
    lines.append("## File fingerprints (sha256[:12])")
    lines.append("")
    for rel, fp in sorted(report["fingerprints"].items()):
        lines.append(f"- `{rel}` = `{fp}`")
    lines.append("")
    return "\n".join(lines)


def _fmt_pct(v: Optional[float]) -> str:
    return f"{v:.1f}%" if v is not None else "n/a"


# ---------------------------------------------------------------------------
# Rank-mode ablation report (plan 018 §2) — legs once, rank N ways
# ---------------------------------------------------------------------------


def _rank_ablation_aggregates(results: list, mode_labels: list[str]) -> dict:
    """Per-mode Hit@K aggregates + flip lists vs the reference mode.

    Flips are ids that gained/lost STRICT Hit@5 relative to ``hard`` (the
    reference). strict aggregates exclude strict-excluded queries.
    """
    from kukai.rag.benchmark.rank_ablation import REFERENCE_MODE

    strict_rows = [r for r in results if not r.strict_excluded]
    per_mode: dict = {}
    for label in mode_labels:
        raw_d: dict = {}
        strict_d: dict = {}
        for k in HIT_KS:
            raw_d[k] = (
                sum(1 for r in results if r.per_mode[label]["hits"]["raw"].get(k))
                / len(results)
                if results else 0.0
            )
            strict_d[k] = (
                sum(1 for r in strict_rows if r.per_mode[label]["hits"]["strict"].get(k))
                / len(strict_rows)
                if strict_rows else 0.0
            )
        per_mode[label] = {"raw": raw_d, "strict": strict_d}

    ref = REFERENCE_MODE if REFERENCE_MODE in mode_labels else mode_labels[0]
    flips: dict = {}
    for label in mode_labels:
        if label == ref:
            continue
        gained: list[str] = []
        lost: list[str] = []
        for r in strict_rows:
            base = r.per_mode[ref]["hits"]["strict"].get(5, False)
            cur = r.per_mode[label]["hits"]["strict"].get(5, False)
            if cur and not base:
                gained.append(r.id)
            elif base and not cur:
                lost.append(r.id)
        flips[label] = {"gained": gained, "lost": lost}

    return {
        "n_raw": len(results),
        "n_strict": len(strict_rows),
        "reference_mode": ref,
        "per_mode": per_mode,
        "flips_strict_at5_vs_reference": flips,
    }


def build_rank_ablation_report(results: list, config: dict) -> dict:
    """Assemble a kind=='rank-ablation' report (same honesty skeleton)."""
    healths = [r.health for r in results]
    manifest = _leg_manifest_from_health(healths)
    if not manifest:
        raise ValueError(
            "refusing to build a rank-ablation report with an empty leg manifest "
            "(plan 009 honesty rule)"
        )
    mode_labels = list(config.get("mode_labels", []))
    if config.get("mode") == "offline":
        _assert_offline_uncontaminated(manifest, results)
    degraded = _is_degraded(manifest)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "rank-ablation",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "degraded_run": degraded,
        "mode": config.get("mode", "offline"),
        "mode_labels": mode_labels,
        "n_queries": len(results),
        "leg_manifest": manifest,
        "config_snapshot": _config_snapshot(),
        "cli_config": config,
        "fingerprints": _fingerprints(),
        "ubiquitous_excluded_in_strict": sorted(UBIQUITOUS),
        "aggregates": _rank_ablation_aggregates(results, mode_labels),
        "queries": [
            {
                "id": r.id,
                "rag_query": r.rag_query[:240],
                "strict_excluded": r.strict_excluded,
                "per_mode": {
                    label: {
                        "final_keys": r.per_mode[label]["final_keys"],
                        "hits": r.per_mode[label]["hits"],
                    }
                    for label in mode_labels
                },
                "latency_ms": round(r.latency_ms, 2),
                "degraded": r.health.get("degraded", False),
            }
            for r in results
        ],
    }


def render_rank_ablation_md(report: dict) -> str:
    """Render the rank-ablation report — leg manifest table BEFORE the table."""
    lines: list[str] = []
    lines.append("# RAG rank-mode ablation — legs once, rank N ways (plan 018)")
    lines.append("")
    lines.append(
        f"- generated: `{report['generated_utc']}` | git: `{report['git_sha']}` "
        f"| mode: `{report['mode']}` | queries: {report['n_queries']}"
    )
    lines.append(f"- **degraded_run: {str(report['degraded_run']).lower()}**")
    lines.append("")

    # -- LEG MANIFEST FIRST (honesty rule) -----------------------------------
    lines.append("## Leg manifest")
    lines.append("")
    lines.append("| leg | dominant status | by_status |")
    lines.append("|---|---|---|")
    for name in sorted(report["leg_manifest"].keys()):
        info = report["leg_manifest"][name]
        by = ", ".join(f"{s}={c}" for s, c in sorted(info["by_status"].items()))
        lines.append(f"| {name} | {info['status']} | {by} |")
    lines.append("")
    if report["degraded_run"]:
        lines.append(
            "> DEGRADED RUN: a strong leg did not truly run for the whole set "
            "(keyless offline → semantic skipped). These numbers compare ranking "
            "modes over the legs that DID run; run `--live` for the 3-leg picture."
        )
        lines.append("")

    # -- per-mode Hit@K table -------------------------------------------------
    agg = report["aggregates"]
    ref = agg["reference_mode"]
    lines.append("## Hit@K by rank mode")
    lines.append("")
    lines.append(
        f"- raw over n={agg['n_raw']} | strict over n={agg['n_strict']} "
        f"| reference mode: `{ref}`"
    )
    lines.append("")
    header = "| mode | " + " | ".join(
        f"raw@{k}" for k in HIT_KS
    ) + " | " + " | ".join(f"str@{k}" for k in HIT_KS) + " |"
    lines.append(header)
    lines.append("|---" * (1 + 2 * len(HIT_KS)) + "|")
    for label in report["mode_labels"]:
        pm = agg["per_mode"][label]
        raw_cells = " | ".join(f"{pm['raw'][k] * 100:.1f}%" for k in HIT_KS)
        str_cells = " | ".join(f"{pm['strict'][k] * 100:.1f}%" for k in HIT_KS)
        marker = " (ref)" if label == ref else ""
        lines.append(f"| {label}{marker} | {raw_cells} | {str_cells} |")
    lines.append("")

    # -- flips vs reference ---------------------------------------------------
    lines.append(f"## Flips on strict Hit@5 vs `{ref}`")
    lines.append("")
    for label, flip in agg["flips_strict_at5_vs_reference"].items():
        lines.append(
            f"- `{label}`: gained ({len(flip['gained'])}) {flip['gained']} | "
            f"lost ({len(flip['lost'])}) {flip['lost']}"
        )
    lines.append("")

    # -- fingerprints ---------------------------------------------------------
    lines.append("## File fingerprints (sha256[:12])")
    lines.append("")
    for rel, fp in sorted(report["fingerprints"].items()):
        lines.append(f"- `{rel}` = `{fp}`")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, out_dir: Path, stem_suffix: str = "") -> Path:
    """Write {date}-{sha}{suffix}.json + .md under out_dir. Returns the JSON path.

    ``stem_suffix`` (plan 014) lets e2e arms write distinct files in the same
    out dir (e.g. ``-e2e-on``, ``-e2e-off-smoke``) so two arms of an A/B never
    overwrite each other. The renderer is chosen by ``report["kind"]``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    date = report["generated_utc"][:10]
    stem = f"{date}-{report['git_sha']}{stem_suffix}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    kind = report.get("kind")
    if kind == "e2e":
        renderer = render_e2e_md
    elif kind == "rank-ablation":
        renderer = render_rank_ablation_md
    else:
        renderer = render_md
    md_path.write_text(renderer(report), encoding="utf-8")
    return json_path
