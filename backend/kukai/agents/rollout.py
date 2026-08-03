"""Rollout helpers — deterministic A/B bucketing + best-effort telemetry.

Shared across the agent-architecture upgrade milestones (grounding gate,
intent router, convergence controller). Bucketing is a pure function of
``session_id`` so treatment assignment is stable across a session AND across
the 4 uvicorn workers (no shared state). Telemetry mirrors the safe-path,
never-raise pattern of ``kukai.agents.base._log_agent_telemetry``.

See plan: /root/.claude/plans/recursive-inventing-lecun.md (Milestone 0).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def ab_bucket(session_id: Optional[str]) -> int:
    """Deterministic bucket 0..99 for a session id (sha1-based).

    Sessionless ("" / None) returns 100 — a sentinel that is >= any real
    percent (<100), so such requests never fall into treatment.
    """
    if not session_id:
        return 100
    h = hashlib.sha1(session_id.encode("utf-8")).hexdigest()
    return int(h, 16) % 100


def in_treatment(session_id: Optional[str], percent: int) -> bool:
    """Whether this session is in the A/B treatment arm.

    ``percent`` <= 0 disables A/B (all control); >= 100 routes all real
    sessions to treatment. Sessionless requests are always control so
    anonymous/ephemeral traffic is never the guinea pig.
    """
    if not session_id:
        return False
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    return ab_bucket(session_id) < percent


# Reuse the exact safe-prefix guard from agents.base._log_agent_telemetry:
# server runs as root, so a misconfigured KUKAI_AGENT_TELEMETRY_PATH must not
# be able to write outside /tmp, cwd, or backend/data.
def _safe_prefixes() -> tuple[Path, ...]:
    return (
        Path("/tmp").resolve(),
        Path.cwd().resolve(),
        (Path(__file__).resolve().parents[2] / "data").resolve(),  # backend/data
    )


def log_rollout_telemetry(record: dict[str, Any]) -> None:
    """Append a JSONL line to ``KUKAI_AGENT_TELEMETRY_PATH``. Never raises.

    Tag records with a ``kind`` (e.g. "route" | "gate") so they are separable
    from the per-agent telemetry sharing the same file. Best-effort: silently
    no-ops if the path is unset, unsafe, or the write fails.
    """
    path = os.environ.get("KUKAI_AGENT_TELEMETRY_PATH", "")
    if not path:
        return
    try:
        p = Path(path).resolve()
        if not any(str(p).startswith(str(prefix)) for prefix in _safe_prefixes()):
            return
        rec = {"ts": time.time(), **record}
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — telemetry is best-effort
        pass
