"""Golden-replay — a drift + metrics scoreboard over the TurnLedger decision events.

WHAT THIS IS (and is not), per the Codex Phase-3 audit:
  * It is a **prod-behavior DRIFT report + metrics scoreboard**. For each recorded
    turn it re-derives the gate verdict from the RECORDED INPUTS and compares it to
    the RECORDED VERDICT. A mismatch ("drift") means the live gate code no longer
    agrees with what produced the historical row — i.e. someone changed gate logic
    (or the recorded inputs are insufficient to reproduce it).
  * It is **NOT a correctness oracle.** Comparing a re-computed verdict to a verdict
    the same code produced is circular — it cannot catch a bug that was always
    wrong. The correctness oracle is the HAND-LABELLED unit suites
    (tests/test_grounding_gate.py, tests/test_autoshow_witnessed.py) which assert
    expected verdicts on curated inputs. Keep those as the source of truth.

The value here is (a) catching silent gate-logic drift in CI, and (b) the aggregate
scoreboard over REAL traffic: auto-show fire-rate, grounding annotate-rate,
lookup-hit rate, and the derivable slice of "fake-готово".

Requires the A0 ledger enrichment (grounding events carry analysis_turn /
cited_norms / lookup_norm_hit; auto_show events carry wrote_heuristic / write_ok /
witnessed_mode). Rows recorded before A0 are reported as "insufficient" (skipped),
never silently counted as agreeing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Reuse the SAME pure gate functions the live path uses — replay must not fork logic.
from kukai.api.chat_ws import autoshow_should_fire


# ── event extraction ────────────────────────────────────────────────────────

def _events(row: dict[str, Any]) -> list[dict[str, Any]]:
    ev = row.get("events")
    if isinstance(ev, str):
        try:
            ev = json.loads(ev)
        except (json.JSONDecodeError, TypeError):
            return []
    return ev if isinstance(ev, list) else []


def _payloads(row: dict[str, Any], source: str) -> list[dict[str, Any]]:
    out = []
    for e in _events(row):
        if e.get("source") == source:
            p = e.get("payload")
            if isinstance(p, dict):
                out.append(p)
    return out


# ── replay: re-derive the verdict from RECORDED INPUTS ───────────────────────

def replay_autoshow_fire(p: dict[str, Any]) -> Optional[bool]:
    """Re-derive the auto-show fire decision from a recorded auto_show_gate payload.
    None ⇒ payload lacks the inputs (pre-A1 row)."""
    if "wrote_heuristic" not in p or "witnessed_mode" not in p:
        return None
    return autoshow_should_fire(
        write_ok=bool(p.get("write_ok")),
        wrote_heuristic=bool(p.get("wrote_heuristic")),
        witnessed_mode=bool(p.get("witnessed_mode")),
    )


def replay_grounding_verdict(p: dict[str, Any]) -> Optional[str]:
    """Re-derive the grounding verdict from a recorded (A0-enriched) grounding
    payload. Mirrors grounding_gate.evaluate_grounding EXACTLY, from the recorded
    fields. None ⇒ payload lacks the A0 inputs."""
    if "analysis_turn" not in p or "lookup_norm_hit" not in p:
        return None
    if not p.get("analysis_turn"):
        return "pass"
    if not p.get("tools"):  # no grounding tool call at all
        return "reprompt"
    if p.get("cited_norms") and not p.get("lookup_norm_hit"):
        return "annotate"
    return "pass"


# ── report ───────────────────────────────────────────────────────────────────

@dataclass
class Report:
    turns: int = 0
    # auto-show
    autoshow_events: int = 0
    autoshow_insufficient: int = 0
    autoshow_drift: int = 0
    autoshow_fire: int = 0
    # grounding
    grounding_events: int = 0
    grounding_insufficient: int = 0
    grounding_drift: int = 0
    grounding_annotate: int = 0
    grounding_lookup_hit: int = 0
    # fake-готово (derivable slice): write intent (a write tool present) but no
    # witnessed write success.
    write_turns: int = 0
    write_unwitnessed: int = 0
    drift_samples: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "drift_samples"}
        d["drift_samples"] = self.drift_samples[:20]
        return d


def analyze_rows(rows: Iterable[dict[str, Any]]) -> Report:
    r = Report()
    for row in rows:
        r.turns += 1
        for p in _payloads(row, "chat_ws.auto_show_gate"):
            r.autoshow_events += 1
            predicted = replay_autoshow_fire(p)
            if predicted is None:
                r.autoshow_insufficient += 1
                continue
            recorded = bool(p.get("fire"))
            if predicted:
                r.autoshow_fire += 1
            if predicted != recorded:
                r.autoshow_drift += 1
                r.drift_samples.append({"kind": "auto_show", "recorded": recorded,
                                        "replayed": predicted, "payload": p})
            # write-intent slice for fake-готово
            if p.get("wrote_heuristic"):
                r.write_turns += 1
                if not p.get("write_ok"):
                    r.write_unwitnessed += 1
        for p in _payloads(row, "chat_ws.grounding_gate"):
            r.grounding_events += 1
            predicted = replay_grounding_verdict(p)
            if predicted is None:
                r.grounding_insufficient += 1
                continue
            recorded = p.get("verdict")
            if recorded == "annotate":
                r.grounding_annotate += 1
            if p.get("lookup_norm_hit"):
                r.grounding_lookup_hit += 1
            if predicted != recorded:
                r.grounding_drift += 1
                r.drift_samples.append({"kind": "grounding", "recorded": recorded,
                                        "replayed": predicted, "payload": p})
    return r


def _rate(n: int, d: int) -> str:
    return f"{(100.0 * n / d):.1f}%" if d else "—"


def format_report(r: Report) -> str:
    L = [
        f"GOLDEN-REPLAY over {r.turns} turns",
        "── auto-show gate ──",
        f"  events={r.autoshow_events}  insufficient(pre-A1)={r.autoshow_insufficient}"
        f"  DRIFT={r.autoshow_drift}",
        f"  fire-rate={_rate(r.autoshow_fire, r.autoshow_events - r.autoshow_insufficient)}",
        "── grounding gate ──",
        f"  events={r.grounding_events}  insufficient(pre-A0)={r.grounding_insufficient}"
        f"  DRIFT={r.grounding_drift}",
        f"  annotate-rate={_rate(r.grounding_annotate, r.grounding_events)}"
        f"  lookup-hit-rate={_rate(r.grounding_lookup_hit, r.grounding_events)}",
        "── fake-готово (write-intent slice) ──",
        f"  write-turns={r.write_turns}  unwitnessed={r.write_unwitnessed}"
        f"  ({_rate(r.write_unwitnessed, r.write_turns)})",
    ]
    if r.autoshow_drift or r.grounding_drift:
        L.append(f"  ⚠️  DRIFT DETECTED — live gate logic disagrees with {len(r.drift_samples)} recorded rows")
    return "\n".join(L)


# ── data sources ──────────────────────────────────────────────────────────────

async def load_rows_from_db(db: Any, since_days: int = 7, limit: int = 5000) -> list[dict]:
    """Read recent turn_ledger rows via the app's asyncpg pool."""
    pool = await db._ensure_pool()
    async with pool.acquire() as conn:
        recs = await conn.fetch(
            "SELECT events FROM turn_ledger "
            "WHERE started_at >= (now() - ($1 || ' days')::interval)::text "
            "ORDER BY started_at DESC LIMIT $2",
            str(since_days), limit,
        )
    return [dict(rec) for rec in recs]


def load_rows_from_jsonl(path: str) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _main() -> None:
    import argparse
    import asyncio

    ap = argparse.ArgumentParser(description="Golden-replay drift + metrics scoreboard")
    ap.add_argument("--since", type=int, default=7, help="days of ledger history")
    ap.add_argument("--jsonl", help="read rows from a JSONL fixture instead of the DB")
    args = ap.parse_args()

    if args.jsonl:
        rows = load_rows_from_jsonl(args.jsonl)
    else:
        from kukai.storage.database import Database
        from kukai.config import get_settings

        async def _fetch() -> list[dict]:
            db = Database(get_settings().database_url)
            await db.connect()
            try:
                return await load_rows_from_db(db, since_days=args.since)
            finally:
                await db.close()

        rows = asyncio.run(_fetch())

    print(format_report(analyze_rows(rows)))


if __name__ == "__main__":
    _main()
