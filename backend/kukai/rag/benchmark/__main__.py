"""CLI entry for the plan-009 honest RAG benchmark + plan-014 grounding grader.

    python -m kukai.rag.benchmark --offline --limit 200          # retrieval Hit@K
    python -m kukai.rag.benchmark --e2e --smoke --arm on --limit 2  # pass-rate (mock)
    python -m kukai.rag.benchmark --compare BASE.json TREATMENT.json  # Δpass-rate (E1)

Offline by default (no network): translation is replayed from the gold ``en``;
the semantic and rerank legs report ``skipped_no_*`` and the report header says
``degraded_run: true``. The keyless offline number is a FLOOR (keyword-leg-
mostly), not "the" production number — the report says so, prominently.

MONEY GATE (plan 014): any keyed run (``--live`` retrieval, or non-smoke
``--e2e``) requires the explicit ``--yes-spend`` flag. The offline/smoke modes
run the hermeticity guard first, which refuses to start if live keys are
reachable via a .env file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def _default_out_dir() -> Path:
    # backend/kukai/rag/benchmark/__main__.py -> backend/
    return Path(__file__).resolve().parents[3] / "data" / "benchmarks" / "rag_spine"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kukai.rag.benchmark",
        description="Honest per-leg RAG retrieval benchmark (plan 009) + "
        "e2e pass-rate grounding grader (plan 014).",
    )
    parser.add_argument("--gold", type=str, default=None, help="path to gold jsonl")
    parser.add_argument(
        "--limit", type=int, default=None, help="max queries (default all 200)"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--offline", dest="live", action="store_false", help="offline (default)"
    )
    mode.add_argument(
        "--live", dest="live", action="store_true", help="run live legs (needs keys+net)"
    )
    parser.set_defaults(live=False)
    parser.add_argument("--top-k", type=int, default=10, help="final top-K (default 10)")
    parser.add_argument(
        "--revit-version", type=str, default=None, help="apply version filter"
    )
    parser.add_argument("--out", type=str, default=None, help="output dir")
    parser.add_argument(
        "--fail-under-hit10-strict",
        type=float,
        default=None,
        help="exit 2 if strict Hit@10 falls below X (default: off — no gate)",
    )
    # -- plan 014: e2e pass-rate grounding grader ----------------------------
    parser.add_argument(
        "--e2e",
        action="store_true",
        help="pass-rate mode: RU gold → retrieve → LLM → compile (:52412)",
    )
    parser.add_argument(
        "--arm",
        choices=["on", "off"],
        default="on",
        help="e2e arm: production RAG (on) vs no-RAG control (off)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="e2e model (default: $KUKAI_BENCH_LLM_MODEL → $KUKAI_LLM_MODEL)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="e2e with a mock LLM — zero spend, proves the wiring",
    )
    parser.add_argument(
        "--yes-spend",
        action="store_true",
        help="explicit consent to spend API budget (required for --live and "
        "non-smoke --e2e)",
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BASE", "TREATMENT"),
        help="diff two e2e report JSONs (Δpass-rate) — this output IS E1",
    )
    # -- plan 018: rank-mode ablation (legs once, rank N ways) ----------------
    parser.add_argument(
        "--rank-ablation",
        action="store_true",
        help="rank-mode ablation: run legs once per gold, score every "
        "--rank-modes ranking policy (plan 018). Offline by default.",
    )
    parser.add_argument(
        "--rank-modes",
        type=str,
        default="hard,tiebreak,weight@0.9,weight@0.75",
        help="comma-separated rank modes for --rank-ablation "
        "(default: hard,tiebreak,weight@0.9,weight@0.75)",
    )
    return parser


def _run_rank_ablation(args) -> int:
    """plan 018 §2: rank-mode ablation. Offline by default; --live is gated."""
    from kukai.rag.benchmark.gold_ru import load_control_audit500
    from kukai.rag.benchmark.rank_ablation import RankAblationPipeline
    from kukai.rag.benchmark.report import build_rank_ablation_report, render_rank_ablation_md, write_report

    hermeticity_info = None
    if args.live:
        if not args.yes_spend:
            print("--rank-ablation --live spends API budget (translation + "
                  "embeddings). Re-run with --yes-spend to consent (operator gate).",
                  file=sys.stderr)
            return 2
    else:
        from kukai.rag.benchmark.hermeticity import enforce_offline_hermeticity

        hermeticity_info = enforce_offline_hermeticity()

    modes = [m for m in (args.rank_modes or "").split(",") if m.strip()]
    if not modes:
        print("--rank-modes is empty.", file=sys.stderr)
        return 2

    gold_path = Path(args.gold) if args.gold else None
    gold = load_control_audit500(gold_path)
    if args.limit is not None:
        gold = gold[: args.limit]

    pipeline = RankAblationPipeline(
        modes=modes, top_k_final=args.top_k, live=args.live,
    )
    results = [pipeline.run_query(g) for g in gold]

    config = {
        "mode": "live" if args.live else "offline",
        "limit": args.limit,
        "top_k": args.top_k,
        "mode_labels": [label for (label, _m, _w) in pipeline.mode_specs],
        "n_gold_loaded": len(gold),
    }
    if hermeticity_info is not None:
        config["hermeticity"] = hermeticity_info
    report = build_rank_ablation_report(results, config)

    out_dir = Path(args.out) if args.out else _default_out_dir()
    json_path = write_report(report, out_dir, stem_suffix="-rank-ablation")

    print(render_rank_ablation_md(report))
    print(f"\n[report written] {json_path}")
    print(f"[report written] {json_path.with_suffix('.md')}")
    return 0


def _run_compare(base_path: str, treatment_path: str) -> int:
    """E1: diff two e2e reports. Refuses unless both are comparable. Returns exit code."""
    try:
        base = json.loads(Path(base_path).read_text(encoding="utf-8"))
        treat = json.loads(Path(treatment_path).read_text(encoding="utf-8"))
    except Exception as e:
        print(f"--compare: could not read a report JSON: {e}", file=sys.stderr)
        return 2

    for label, rep in (("BASE", base), ("TREATMENT", treat)):
        if rep.get("kind") != "e2e":
            print(f"--compare refused: {label} is not an e2e report (kind != 'e2e').",
                  file=sys.stderr)
            return 2
        if rep.get("mode") == "e2e-smoke":
            print(f"--compare refused: {label} is a MOCK (smoke) run — never "
                  "quote a smoke pass-rate.", file=sys.stderr)
            return 2
    if base.get("model") != treat.get("model"):
        print(f"--compare refused: model mismatch "
              f"({base.get('model')!r} != {treat.get('model')!r}) — arms must "
              "share the brain.", file=sys.stderr)
        return 2
    if base.get("fingerprints") != treat.get("fingerprints"):
        print("--compare refused: fingerprint mismatch — the two arms measured "
              "different trees (corpus/code drift). Re-run both on one tree.",
              file=sys.stderr)
        return 2
    base_ids = {q["id"] for q in base.get("queries", [])}
    treat_ids = {q["id"] for q in treat.get("queries", [])}
    if base_ids != treat_ids:
        print("--compare refused: query id sets differ between arms.", file=sys.stderr)
        return 2

    ba = base["aggregates"]["pass"]
    ta = treat["aggregates"]["pass"]

    def _d(a, b):
        if a is None or b is None:
            return None
        return round(b - a, 1)

    d_fc = _d(ba["first_compile_ok_pct"], ta["first_compile_ok_pct"])
    d_e2e = _d(ba["e2e_success_pct"], ta["e2e_success_pct"])
    d_rep = round(ta["avg_repair_attempts"] - ba["avg_repair_attempts"], 3)

    # per-query flips on e2e_success
    base_q = {q["id"]: q for q in base["queries"]}
    fail_to_pass: list[str] = []
    pass_to_fail: list[str] = []
    for q in treat["queries"]:
        b = base_q.get(q["id"], {})
        if not b.get("e2e_success") and q.get("e2e_success"):
            fail_to_pass.append(q["id"])
        elif b.get("e2e_success") and not q.get("e2e_success"):
            pass_to_fail.append(q["id"])

    print("=== E1: Δpass-rate (grounding effectiveness, scorecard C11) ===")
    print(f"n = {len(base_ids)} | model = {base.get('model')}")
    print(f"BASE arm={base.get('arm')}  : "
          f"first_compile_ok={ba['first_compile_ok_pct']}%  "
          f"e2e_success={ba['e2e_success_pct']}%  "
          f"avg_repair={ba['avg_repair_attempts']}")
    print(f"TREAT arm={treat.get('arm')} : "
          f"first_compile_ok={ta['first_compile_ok_pct']}%  "
          f"e2e_success={ta['e2e_success_pct']}%  "
          f"avg_repair={ta['avg_repair_attempts']}")
    print(f"Δ first_compile_ok = {d_fc} pp")
    print(f"Δ e2e_success      = {d_e2e} pp   <-- the apex number")
    print(f"Δ avg_repair       = {d_rep}")
    print(f"flips fail→pass ({len(fail_to_pass)}): {fail_to_pass}")
    print(f"flips pass→fail ({len(pass_to_fail)}): {pass_to_fail}")
    return 0


def _run_e2e(args) -> int:
    """Run the e2e pass-rate mode for one arm. Returns exit code."""
    from kukai.rag.benchmark.e2e import resolve_model, run_e2e
    from kukai.rag.benchmark.gold_ru import load_control_audit500
    from kukai.rag.benchmark.llm_runner import LlmRunnerConfig
    from kukai.rag.benchmark.report import build_e2e_report, render_e2e_md, write_report

    if args.limit is None:
        print("--e2e requires an explicit --limit (refusing an accidental "
              "200-query spend). Use e.g. --limit 2 for smoke.", file=sys.stderr)
        return 2

    model = None
    if args.smoke:
        # zero-spend: prove no live key is reachable, then mock the LLM.
        from kukai.rag.benchmark.hermeticity import enforce_offline_hermeticity

        enforce_offline_hermeticity()  # raises SystemExit(3) if keys reachable
    else:
        if not args.yes_spend:
            print("non-smoke --e2e spends API budget. Re-run with --yes-spend to "
                  "consent (operator gate). For a zero-spend wiring check use "
                  "--smoke.", file=sys.stderr)
            return 2
        model = resolve_model(args.model)

    gold_path = Path(args.gold) if args.gold else None
    gold = load_control_audit500(gold_path)[: args.limit]

    config = LlmRunnerConfig(
        revit_version=args.revit_version or "2026",
        llm_model=model,
    )
    results = asyncio.run(run_e2e(gold, args.arm, config, smoke=args.smoke))

    report = build_e2e_report(
        results,
        {
            "mode": "e2e-smoke" if args.smoke else "e2e-live",
            "smoke": args.smoke,
            "arm": args.arm,
            "model": model or "mock-smoke",
            "limit": args.limit,
            "revit_version": config.revit_version,
            "n_gold_loaded": len(gold),
        },
    )

    out_dir = Path(args.out) if args.out else _default_out_dir()
    suffix = f"-e2e-{args.arm}" + ("-smoke" if args.smoke else "")
    json_path = write_report(report, out_dir, stem_suffix=suffix)

    print(render_e2e_md(report))
    print(f"\n[report written] {json_path}")
    print(f"[report written] {json_path.with_suffix('.md')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # -- plan 018: --rank-ablation (mutually exclusive with --e2e/--compare) -
    if getattr(args, "rank_ablation", False):
        if args.compare or args.e2e:
            print("--rank-ablation is mutually exclusive with --e2e / --compare.",
                  file=sys.stderr)
            return 2
        return _run_rank_ablation(args)

    # -- plan 014: --compare (no retrieval, no spend) ------------------------
    if args.compare:
        return _run_compare(args.compare[0], args.compare[1])

    # -- plan 014: --e2e pass-rate mode --------------------------------------
    if args.e2e:
        return _run_e2e(args)

    # -- retrieval mode (plan 009) -------------------------------------------
    from kukai.rag.benchmark.gold_ru import load_control_audit500
    from kukai.rag.benchmark.prod_replica import ProdReplicaPipeline
    from kukai.rag.benchmark.report import build_report, render_md, write_report

    hermeticity_info = None
    if args.live:
        if not args.yes_spend:
            print("--live spends API budget (translation + embeddings + rerank). "
                  "Re-run with --yes-spend to consent (operator gate).",
                  file=sys.stderr)
            return 2
    else:
        # offline default: refuse to start if live keys are reachable.
        from kukai.rag.benchmark.hermeticity import enforce_offline_hermeticity

        hermeticity_info = enforce_offline_hermeticity()

    gold_path = Path(args.gold) if args.gold else None
    gold = load_control_audit500(gold_path)
    if args.limit is not None:
        gold = gold[: args.limit]

    pipeline = ProdReplicaPipeline(
        top_k_final=args.top_k,
        live=args.live,
        revit_version=args.revit_version,
    )

    results = [pipeline.run_query(g) for g in gold]

    config = {
        "mode": "live" if args.live else "offline",
        "limit": args.limit,
        "top_k": args.top_k,
        "revit_version": args.revit_version,
        "n_gold_loaded": len(gold),
    }
    if hermeticity_info is not None:
        config["hermeticity"] = hermeticity_info
    report = build_report(results, config)

    out_dir = Path(args.out) if args.out else _default_out_dir()
    json_path = write_report(report, out_dir)

    print(render_md(report))
    print(f"\n[report written] {json_path}")
    print(f"[report written] {json_path.with_suffix('.md')}")

    strict_hit10 = report["aggregates"]["hits"]["strict"].get(10, 0.0)
    if args.fail_under_hit10_strict is not None and strict_hit10 < args.fail_under_hit10_strict:
        print(
            f"\n[GATE] strict Hit@10 {strict_hit10 * 100:.1f}% < "
            f"{args.fail_under_hit10_strict * 100:.1f}% — failing (exit 2)",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
