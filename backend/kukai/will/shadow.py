"""The Evaluator's SHADOW orchestrator (plan 020) — the ONE hot-path entry
point + the per-turn fold + the offline report CLI.

``shadow_evaluate`` is the body the single ``client.py`` hook calls after every
write. It is **shadow only**: it observes the write's change-set, computes a
deterministic verdict (:func:`kukai.will.evaluator.evaluate_structural`),
optionally runs read-only probes (:mod:`kukai.will.probes`), and records the
verdict to ``eval_verdicts.jsonl`` joined to the turn by ``query_id``. It
NEVER gates the turn, NEVER mutates the tool result, and the model NEVER sees
the verdict. It NEVER raises (the hook also guards it) and NEVER calls an LLM
(IRON 3).

Levels (``config.EVALUATOR_SHADOW``, read at call time):
  * **0** (default) — immediate return; nothing computed, nothing written.
  * **1** — Tier-A structural checks only (pure, ~0 cost, no bridge calls).
  * **2** — Tier A + read-only probes (≤2 per write, ≤4 per turn, 8s cap each).

The turn verdict (:func:`aggregate_turn`) is a deterministic fold over the
recorded rows, computed offline by the report — NOT a second live hook — so v1
keeps exactly ONE call site in the hot path.
"""
from __future__ import annotations

import argparse
import logging
from collections import OrderedDict
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Per-turn state, keyed by the ambient retrieval_health query_id. Bounded LRU
# (insertion-ordered eviction), mirroring query/model_cache.py:31-32.
#   value = {"probes_run": int, "last_warnings": Optional[int]}
_TURN_STATE: "OrderedDict[str, dict]" = OrderedDict()
_MAX_TURNS = 256
_PROBE_BUDGET_PER_TURN = 4


def _turn_state(query_id: Optional[str]) -> dict:
    """Get-or-create the bounded per-turn probe budget / warnings-baseline slot.

    A null query_id (no active turn) gets a private, non-cached slot so probes
    still run but cannot accumulate across unrelated contexts."""
    if not query_id:
        return {"probes_run": 0, "last_warnings": None}
    st = _TURN_STATE.get(query_id)
    if st is None:
        st = {"probes_run": 0, "last_warnings": None}
        _TURN_STATE[query_id] = st
        while len(_TURN_STATE) > _MAX_TURNS:
            _TURN_STATE.popitem(last=False)
    else:
        _TURN_STATE.move_to_end(query_id)
    return st


def _current_query_id() -> Optional[str]:
    """Read the ambient turn's query_id (never-throws). None when no turn."""
    try:
        from kukai.rag import retrieval_health
        h = retrieval_health.current()
        return h.query_id if h is not None else None
    except Exception:  # noqa: BLE001 — telemetry helper must never break a turn
        return None


def _op_of(tool_name: str, args: dict) -> Optional[str]:
    if tool_name == "apply_revit_write" and isinstance(args, dict):
        op = args.get("operation")
        return op if isinstance(op, str) else None
    return None


async def shadow_evaluate(
    tool_name: str,
    tool_args: dict,
    result: Any,
    *,
    is_error: bool,
    bridge_callback=None,
    revit_version: str = "",
) -> None:
    """Plan-020 shadow hook body. NEVER raises; returns nothing.

    Level 0 → immediate return. Level 1 → Tier A only (pure). Level 2 →
    Tier A + read-only probes (delete→inspect_absent, any success→warnings
    delta), budget- and time-capped. Safe with ``bridge_callback=None`` (probes
    skipped) and from any task context (no turn → ``query_id`` null).
    """
    try:
        from kukai import config
        level = int(getattr(config, "EVALUATOR_SHADOW", 0) or 0)
    except Exception:  # noqa: BLE001
        level = 0
    if level <= 0:
        return

    try:
        from kukai.will.evaluator import EVALUATOR_VERSION, evaluate_structural

        args = tool_args if isinstance(tool_args, dict) else {}
        op = _op_of(tool_name, args)
        query_id = _current_query_id()

        # Op-attached witness evidence (2026-07-10): ops with a real grounded
        # witness (read-back + probe, e.g. create_element) embed their Check
        # evidence on result["witness"]["checks"]; we CONSUME it through the
        # trust registry (kukai/will/witness.py — allowlisted server-lowered
        # ops only, forged witnesses from raw C# are ignored) instead of
        # blindly re-deriving per-op. One verdict engine, evidence flows.
        from kukai.will.witness import lift_op_checks, op_witness_id
        lifted = lift_op_checks(tool_name, op, result)

        extra_checks: list = list(lifted)
        probes_run = 0
        probe_ms = 0

        # --- Tier B: read-only probes (level 2, success only, budgeted) ---
        if level >= 2 and not is_error and bridge_callback is not None:
            import time

            from kukai.will import probes as _probes
            st = _turn_state(query_id)

            def _budget_left() -> bool:
                return st["probes_run"] < _PROBE_BUDGET_PER_TURN

            # Probe 1: inspect_absent — a true world-witness that a delete happened.
            if op == "delete_elements":
                ids = args.get("element_ids")
                if isinstance(ids, (list, tuple)) and ids:
                    if _budget_left():
                        t0 = time.monotonic()
                        chk = await _probes.probe_inspect_absent(ids[0], bridge_callback)
                        probe_ms += int((time.monotonic() - t0) * 1000)
                        probes_run += 1
                        st["probes_run"] += 1
                        extra_checks.append(chk)
                    else:
                        extra_checks.append(_unbudgeted_check("probe.inspect_absent"))

            # Probe 2: warnings_count — within-turn delta ("did I damage the model").
            if _budget_left():
                t0 = time.monotonic()
                wchk, count = await _probes.probe_warnings_count(bridge_callback)
                probe_ms += int((time.monotonic() - t0) * 1000)
                probes_run += 1
                st["probes_run"] += 1
                baseline = st["last_warnings"]
                if count is not None:
                    if baseline is None:
                        # First snapshot of the turn → record the baseline only.
                        extra_checks.append(wchk)
                    else:
                        extra_checks.append(_probes.warnings_delta_check(baseline, count))
                    st["last_warnings"] = count
                else:
                    extra_checks.append(wchk)  # undecidable snapshot
            else:
                extra_checks.append(_unbudgeted_check("probe.warnings_delta"))

        # --- Tier A (+ folded probes) → the verdict ---
        report = evaluate_structural(
            tool_name, args, result,
            is_error=is_error,
            extra_checks=extra_checks or None,
            cost={"probes_run": probes_run, "probe_ms": probe_ms},
        )

        row = {
            "tool": tool_name,
            "op": op,
            "is_error": bool(is_error),
            "err_code": _err_code(result),
            "verdict": report.verdict,
            "score": round(report.score, 4),
            "checks": [_check_to_dict(c) for c in report.checks],
            "violations": list(report.violations),
            "blast_radius": dict(report.blast_radius),
            "probes_run": probes_run,
            "probe_ms": probe_ms,
            # Attribution: "op" = grounded evidence consumed from the op's own
            # witness (the truthful path); "derived" = blind re-derivation
            # (the only path before 2026-07-10).
            "witness_source": "op" if lifted else "derived",
            "revit_version": revit_version or "",
            "evaluator_version": EVALUATOR_VERSION,
        }
        if lifted:
            _oid = op_witness_id(result)
            if _oid:
                row["op_id"] = _oid

        from kukai.telemetry_rag import log_eval_verdict
        log_eval_verdict(query_id, row)

    except Exception as e:  # noqa: BLE001 — shadow never breaks a turn
        logger.debug("shadow_evaluate failed (non-fatal)", exc_info=True)
        try:
            from kukai.telemetry import note_telemetry_failure
            note_telemetry_failure(e)
        except Exception:  # noqa: BLE001
            pass


def _unbudgeted_check(kind: str):
    from kukai.will.evaluator import Check
    return Check(kind=kind, expect=None, observed=None, ok=None,
                 source="probe", detail="probe_budget_exhausted")


def _err_code(result: Any) -> Optional[str]:
    if isinstance(result, dict):
        err = result.get("err")
        if isinstance(err, dict) and isinstance(err.get("code"), str):
            return err["code"]
    return None


def _check_to_dict(c) -> dict:
    d = {
        "kind": c.kind,
        "expect": c.expect,
        "observed": c.observed,
        "ok": c.ok,
        "source": c.source,
    }
    if getattr(c, "detail", None):
        d["detail"] = c.detail
    if getattr(c, "partial", False):
        d["partial"] = True
    return d


# ---------------------------------------------------------------------------
# The per-turn fold (deterministic, offline — exercised by the report)
# ---------------------------------------------------------------------------

# Verdict precedence for a turn: any fail dominates, then partial, then
# unverifiable, then pass. A turn with no write rows is "no_writes".
_VERDICT_RANK = {"fail": 3, "partial": 2, "unverifiable": 1, "pass": 0}


def aggregate_turn(rows: list) -> dict:
    """Fold a turn's per-write verdict rows into one turn verdict.

    Precedence ``fail > partial > unverifiable > pass``; ``no_writes`` when the
    turn produced no rows. Pure; used by the offline report, NOT a live hook.
    """
    if not rows:
        return {"turn_verdict": "no_writes", "writes": 0}
    worst = "pass"
    worst_rank = -1
    for r in rows:
        v = r.get("verdict", "unverifiable")
        rank = _VERDICT_RANK.get(v, 1)
        if rank > worst_rank:
            worst_rank = rank
            worst = v
    return {
        "turn_verdict": worst,
        "writes": len(rows),
        "verdicts": [r.get("verdict") for r in rows],
    }


# ---------------------------------------------------------------------------
# Offline report CLI:  python -m kukai.will.shadow --report [--days N]
# ---------------------------------------------------------------------------

def _build_report(window_days: int = 7) -> dict:
    """Aggregate eval_verdicts.jsonl over the last N days → the summary dict
    (incl. the disagreement rate — the founding statistic for v2 enforce)."""
    from datetime import datetime, timezone

    from kukai.telemetry_rag import _read_jsonl

    cutoff = datetime.now(timezone.utc).timestamp() - window_days * 86400

    def _within(row: dict) -> bool:
        try:
            return datetime.fromisoformat(row["ts"]).timestamp() >= cutoff
        except (KeyError, ValueError, TypeError):
            return True

    rows = [r for r in _read_jsonl("eval_verdicts") if _within(r)]

    verdict_dist: dict = {}
    by_tool_op: dict = {}
    probes_total = 0
    probe_ms_total = 0
    disagreements = 0  # is_error == False but verdict in {fail, partial}
    success_claimed = 0  # is_error == False rows (the harness's "success")

    turns: dict = {}
    for r in rows:
        v = r.get("verdict", "unverifiable")
        verdict_dist[v] = verdict_dist.get(v, 0) + 1
        key = f"{r.get('tool')}::{r.get('op')}"
        slot = by_tool_op.setdefault(key, {})
        slot[v] = slot.get(v, 0) + 1
        probes_total += int(r.get("probes_run", 0) or 0)
        probe_ms_total += int(r.get("probe_ms", 0) or 0)
        if not r.get("is_error", False):
            success_claimed += 1
            if v in ("fail", "partial"):
                disagreements += 1
        qid = r.get("query_id")
        if qid:
            turns.setdefault(qid, []).append(r)

    turn_verdicts: dict = {}
    for qid, trows in turns.items():
        tv = aggregate_turn(trows)["turn_verdict"]
        turn_verdicts[tv] = turn_verdicts.get(tv, 0) + 1

    disagreement_rate = (disagreements / success_claimed) if success_claimed else 0.0

    return {
        "window_days": window_days,
        "rows": len(rows),
        "turns_with_writes": len(turns),
        "verdict_distribution": verdict_dist,
        "turn_verdict_distribution": turn_verdicts,
        "by_tool_op": by_tool_op,
        "probes_run_total": probes_total,
        "probe_ms_total": probe_ms_total,
        "success_claimed_rows": success_claimed,
        "disagreements": disagreements,
        "disagreement_rate": round(disagreement_rate, 4),
    }


def _print_report(rep: dict) -> None:
    print("=== KUKAI Evaluator — shadow report (plan 020) ===")
    print(f"window: last {rep['window_days']} days")
    print(f"rows (per-write verdicts): {rep['rows']}")
    print(f"turns with writes: {rep['turns_with_writes']}")
    print(f"verdict distribution: {rep['verdict_distribution']}")
    print(f"turn-verdict distribution: {rep['turn_verdict_distribution']}")
    print("per (tool, op):")
    for key, dist in sorted(rep["by_tool_op"].items()):
        print(f"  {key}: {dist}")
    print(f"probes run: {rep['probes_run_total']}  (total {rep['probe_ms_total']} ms)")
    print(
        f"DISAGREEMENT RATE: {rep['disagreement_rate']} "
        f"({rep['disagreements']} of {rep['success_claimed_rows']} "
        f"harness-success rows judged fail/partial)"
    )
    print("  ^ the founding statistic for the v2 enforce decision (VISION Phase 0).")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kukai.will.shadow",
        description="Offline report over the Evaluator's shadow verdict stream.",
    )
    parser.add_argument("--report", action="store_true",
                        help="print the verdict/disagreement summary")
    parser.add_argument("--days", type=int, default=7,
                        help="window in days (default 7)")
    args = parser.parse_args(argv)
    if args.report:
        _print_report(_build_report(args.days))
    else:
        parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
