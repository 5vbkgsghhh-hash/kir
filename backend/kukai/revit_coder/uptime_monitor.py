"""Polls revit-coder router /health endpoint and logs uptime to JSONL.

Started in FastAPI lifespan when USE_REVIT_CODER=1.
Stats endpoint /admin/kaggle_uptime computes aggregates from the log.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

import kukai.config as _config

logger = logging.getLogger(__name__)


def _health_url() -> str:
    """Derive /health URL from /v1 base URL.

    Examples:
        REVIT_CODER_URL = 'https://coder.revit-kukai.org/v1'
        → 'https://coder.revit-kukai.org/health'
        REVIT_CODER_URL = 'https://coder.revit-kukai.org'
        → 'https://coder.revit-kukai.org/health'
    """
    base = _config.REVIT_CODER_URL.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return f"{base.rstrip('/')}/health"


async def poll_once() -> None:
    """Single poll cycle — never raises."""
    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(_health_url())
            r.raise_for_status()
            data = r.json()
            record["alive_nodes"] = data.get("alive_nodes", 0)
            record["total_nodes"] = data.get("total_nodes", 0)
            record["status"] = data.get("status", "unknown")
    except Exception as e:
        record["alive_nodes"] = 0
        record["total_nodes"] = 0
        record["status"] = "unreachable"
        record["error"] = str(e)[:200]

    try:
        path = Path(_config.UPTIME_LOG_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        logger.warning("Uptime log write failed: %s", e)


async def uptime_monitor_loop() -> None:
    """Forever loop — polls every UPTIME_POLL_INTERVAL_SEC seconds."""
    logger.info("Uptime monitor starting, interval=%ss", _config.UPTIME_POLL_INTERVAL_SEC)
    while True:
        await poll_once()
        await asyncio.sleep(_config.UPTIME_POLL_INTERVAL_SEC)


def compute_uptime_stats(since_hours: int = 24) -> dict[str, Any]:
    """Compute aggregates from JSONL log.

    Phase 1 simplification: computes over entire log (recent enough, < 1 week).
    Phase 3 will add since_hours filtering via ts comparison.
    """
    path = Path(_config.UPTIME_LOG_PATH)
    if not path.exists():
        return {
            "samples": 0,
            "alive_pct": 0.0,
            "current_status": "no_data",
            "current_alive_nodes": 0,
        }

    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not records:
        return {
            "samples": 0,
            "alive_pct": 0.0,
            "current_status": "no_data",
            "current_alive_nodes": 0,
        }

    alive_count = sum(1 for r in records if r.get("alive_nodes", 0) > 0)
    alive_pct = round(alive_count / len(records) * 100, 1)

    return {
        "period_hours": since_hours,
        "samples": len(records),
        "alive_pct": alive_pct,
        "current_status": records[-1].get("status", "unknown"),
        "current_alive_nodes": records[-1].get("alive_nodes", 0),
    }
