"""Install telemetry — every installer run, visible server-side.

The Inno Setup installer ([Code] section of installer/kukai_client_setup.iss)
fires fire-and-forget HTTPS POSTs here at install_start, per-step results and
install_complete / install_failed. This is the "we see EVERY install and EVERY
failure" half of the installer overhaul: with ~50 machines in the field on a
zoo of Revit versions (2021-2026, many cracked) and an ad campaign coming, a
failed install that we cannot see is a churned user we never knew existed.

Design constraints (mirrors api/diagnostics.py, the crash-report receiver):
  * UNAUTHENTICATED POST — the installer runs before any session token exists.
  * Fail-open storage — PostgreSQL is the queryable store, but a PG outage
    must NEVER surface as an installer error: every event is also appended to
    data/telemetry/install_events.jsonl, and the endpoint returns 200 even if
    both sinks fail. Telemetry must never block or break an install.
  * Size-capped + lightly rate-limited per IP.

Admin read side: GET /admin/install/report (X-Admin-Token, same dependency as
the licensing admin API) — last installs grouped by device with status,
failures and environment, so remote-guided healing (installer /REPAIR mode)
can be driven from what the machine actually reported.

Wiring (both repo and /opt are additive, two lines in kukai/main.py):
    from kukai.api.install_telemetry import router as install_telemetry_router
    app.include_router(install_telemetry_router)
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from kukai.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

# An install emits a handful of small events (~1-4 KB each). 64 KB leaves
# room for a long missing-files list in the self-check without letting a
# buggy/malicious client stream megabytes at us.
_MAX_PAYLOAD_BYTES = 65_536
# The `details` column stores the full payload for forensics; cap it so a
# single row can't bloat the table.
_MAX_DETAILS_BYTES = 32_768
_MAX_FIELD_LEN = 512

# A single install run sends ~4 events. 240/h per IP allows ~60 installs/hour
# behind one corporate NAT — generous for an ad-driven rollout, still a wall
# against floods. (Module-level so tests can shrink it.)
_RATE_LIMIT_PER_IP_PER_HOUR = 240

_ALLOWED_EVENTS = frozenset(
    {"install_start", "install_step", "install_complete", "install_failed"}
)

# Sliding-window rate limiter, in-memory per process (same trade-off as
# diagnostics.py: restart resets it; good enough for spam protection).
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)


# ---------------------------------------------------------------------------
# Storage plumbing
# ---------------------------------------------------------------------------

# DDL follows the storage/database.py conventions: TEXT uuid primary keys,
# TEXT ISO-8601 timestamps, CREATE TABLE IF NOT EXISTS + named indexes.
# Executed lazily (idempotent) so this module is a self-contained additive
# graft — no edit to storage/database.py needed on either tree.
_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS install_events (
        id TEXT PRIMARY KEY,
        install_id TEXT NOT NULL DEFAULT '',
        event TEXT NOT NULL,
        device_id TEXT NOT NULL DEFAULT '',
        fingerprint TEXT NOT NULL DEFAULT '',
        installer_version TEXT NOT NULL DEFAULT '',
        os_version TEXT NOT NULL DEFAULT '',
        locale TEXT NOT NULL DEFAULT '',
        step TEXT NOT NULL DEFAULT '',
        ok INTEGER,
        error TEXT NOT NULL DEFAULT '',
        details TEXT NOT NULL DEFAULT '{}',
        client_ip TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS idx_install_events_device "
    "ON install_events(device_id)",
    "CREATE INDEX IF NOT EXISTS idx_install_events_created "
    "ON install_events(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_install_events_install "
    "ON install_events(install_id)",
)

# Databases we've already ensured the schema on (keyed by id() — Database
# instances live for the process; worst case after a swap we re-run an
# idempotent CREATE TABLE IF NOT EXISTS).
_schema_ensured: set[int] = set()


async def get_install_db() -> Optional[Any]:
    """Resolve the app's Database. Overridable in tests via FastAPI
    dependency_overrides. Returns None when the backend isn't fully up —
    the POST path treats that as "JSONL only", never an error."""
    try:
        from kukai.main import get_app_state

        return get_app_state().db
    except Exception:
        return None


async def _ensure_schema(db: Any) -> None:
    if id(db) in _schema_ensured:
        return
    for stmt in _SCHEMA_STATEMENTS:
        await db.execute_raw(stmt)
    _schema_ensured.add(id(db))


def _jsonl_path() -> Path:
    """Where the fail-open JSONL sink lives (monkeypatched in tests)."""
    settings = get_settings()
    return (
        Path(settings._get_data_base())
        / "data"
        / "telemetry"
        / "install_events.jsonl"
    )


def _append_jsonl(record: dict[str, Any]) -> bool:
    try:
        path = _jsonl_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as e:  # noqa: BLE001 — sink must be fail-open
        logger.error("install telemetry JSONL append failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Request helpers (same conventions as diagnostics.py)
# ---------------------------------------------------------------------------


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate_limit(ip: str) -> bool:
    now = time.monotonic()
    cutoff = now - 3600.0
    bucket = _rate_buckets[ip]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_PER_IP_PER_HOUR:
        return False
    bucket.append(now)
    return True


def _s(payload: dict[str, Any], key: str, max_len: int = _MAX_FIELD_LEN) -> str:
    """String field, coerced + length-capped."""
    value = payload.get(key, "")
    if not isinstance(value, str):
        value = str(value) if value is not None else ""
    return value[:max_len]


# ---------------------------------------------------------------------------
# POST /api/install/telemetry
# ---------------------------------------------------------------------------


@router.post("/api/install/telemetry")
async def submit_install_event(
    request: Request,
    db: Optional[Any] = Depends(get_install_db),
) -> dict[str, Any]:
    """Receive one installer event.

    Contract with installer/kukai_client_setup.iss (TelemetryPost):
        {
          "event": "install_start|install_step|install_complete|install_failed",
          "install_id": "<16 hex, one per installer run>",
          "installer_version": "1.3.0", "git_sha": "<sha>",
          "device_id": "<hwid — the server-side chat identity, if known>",
          "install_device_id": "<kukai-... from device_id.txt, if present>",
          "fingerprint": "<sha256(MachineGuid|KUKAI)>",
          "os_version": "10.0.19045", "locale": "1049",
          "mode": "install|repair", "silent": bool, "revit_running": bool,
          "revit_versions": [{"version","method","prior_state"}, ...],
          "step": "...", "ok": bool, "error": "...",       # step/failed
          "self_check": {...}                               # install_complete
        }

    Always returns {"ok": true} unless the request itself is malformed —
    storage failures are logged server-side, never surfaced to the installer.
    """
    ip = _client_ip(request)
    if not _check_rate_limit(ip):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
        )

    body = await request.body()
    if len(body) > _MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"payload exceeds {_MAX_PAYLOAD_BYTES} bytes",
        )
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid JSON"
        )
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="object expected"
        )

    event = _s(payload, "event", 64)
    if event not in _ALLOWED_EVENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"event must be one of {sorted(_ALLOWED_EVENTS)}",
        )

    now = datetime.now(timezone.utc).isoformat()
    ok_raw = payload.get("ok")
    ok_val: Optional[int] = None
    if isinstance(ok_raw, bool):
        ok_val = 1 if ok_raw else 0

    details = json.dumps(payload, ensure_ascii=False)
    if len(details.encode("utf-8")) > _MAX_DETAILS_BYTES:
        details = json.dumps(
            {"truncated": True, "event": event, "install_id": _s(payload, "install_id")},
            ensure_ascii=False,
        )

    # Sink 1: JSONL — append-only, fail-open, survives PG outages/migrations.
    jsonl_ok = _append_jsonl({"received_at": now, "ip": ip, "payload": payload})

    # Sink 2: PostgreSQL — the queryable store behind /admin/install/report.
    pg_ok = False
    if db is not None:
        try:
            await _ensure_schema(db)
            await db.execute_raw(
                """INSERT INTO install_events
                       (id, install_id, event, device_id, fingerprint,
                        installer_version, os_version, locale, step, ok,
                        error, details, client_ip, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    _s(payload, "install_id", 64),
                    event,
                    _s(payload, "device_id", 128),
                    _s(payload, "fingerprint", 128),
                    _s(payload, "installer_version", 64),
                    _s(payload, "os_version", 128),
                    _s(payload, "locale", 32),
                    _s(payload, "step", 128),
                    ok_val,
                    _s(payload, "error", 2000),
                    details,
                    ip[:64],
                    now,
                ),
            )
            pg_ok = True
        except Exception as e:  # noqa: BLE001 — fail-open by contract
            logger.error("install telemetry PG insert failed: %s", e)

    # High-signal log line — greppable in journalctl / live_test.log.
    logger.info(
        "INSTALL_TLM %s device=%s install=%s step=%s ok=%s (pg=%s jsonl=%s)",
        event,
        _s(payload, "device_id", 64) or _s(payload, "fingerprint", 16) or "?",
        _s(payload, "install_id", 32),
        _s(payload, "step", 64) or "-",
        ok_raw,
        pg_ok,
        jsonl_ok,
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# GET /admin/install/report
# ---------------------------------------------------------------------------


async def _verify_admin(request: Request) -> str:
    # Indirection keeps module import light and avoids a hard import cycle;
    # verify_admin_token accepts header or ?token= query.
    from kukai.licensing.admin_api import verify_admin_token

    return await verify_admin_token(
        x_admin_token=request.headers.get("X-Admin-Token"),
        token=request.query_params.get("token"),
    )


@router.get("/admin/install/report")
async def install_report(
    request: Request,
    limit: int = Query(default=50, ge=1, le=500),
    db: Optional[Any] = Depends(get_install_db),
) -> dict[str, Any]:
    """Last installs grouped by device: status, failures, environment.

    Response shape:
        {
          "devices": [
            {
              "device": "<device_id or fp:<fingerprint>>",
              "last_seen": "<iso>",
              "environment": {"os_version", "locale", "installer_version",
                               "revit_versions": [...]},
              "installs": [
                {"install_id", "started_at", "status":
                     "complete|failed|in_progress",
                 "verified": bool|None, "mode", "failures":
                     [{"step","error","at"}]}
              ]
            }, ...
          ],
          "total_events": N
        }
    """
    await _verify_admin(request)

    if db is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    try:
        await _ensure_schema(db)
        rows = await db.fetch_all(
            "SELECT * FROM install_events ORDER BY created_at DESC LIMIT ?",
            (limit * 8,),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("install report query failed: %s", e)
        raise HTTPException(status_code=503, detail="query failed")

    # Group: device -> install_id -> events (rows come newest-first).
    devices: dict[str, dict[str, Any]] = {}
    for row in rows:
        device = row["device_id"] or (
            "fp:" + row["fingerprint"] if row["fingerprint"] else "unknown"
        )
        dev = devices.setdefault(
            device,
            {"device": device, "last_seen": row["created_at"], "installs": {},
             "environment": {}},
        )
        install_id = row["install_id"] or row["id"]
        inst = dev["installs"].setdefault(
            install_id,
            {
                "install_id": install_id,
                "started_at": row["created_at"],
                "status": "in_progress",
                "verified": None,
                "mode": "",
                "failures": [],
            },
        )
        inst["started_at"] = row["created_at"]  # rows are DESC; last write wins = earliest

        try:
            details = json.loads(row["details"])
        except Exception:
            details = {}

        if row["event"] == "install_complete":
            inst["status"] = "complete"
            self_check = details.get("self_check") or {}
            if isinstance(self_check, dict) and "verified" in self_check:
                inst["verified"] = bool(self_check.get("verified"))
        elif row["event"] == "install_failed":
            if inst["status"] != "complete":
                inst["status"] = "failed"
            inst["failures"].append(
                {"step": row["step"], "error": row["error"], "at": row["created_at"]}
            )
        elif row["event"] == "install_step" and row["ok"] == 0:
            inst["failures"].append(
                {"step": row["step"], "error": row["error"], "at": row["created_at"]}
            )
        elif row["event"] == "install_start":
            if isinstance(details.get("mode"), str):
                inst["mode"] = details["mode"]
            # install_start carries the richest environment snapshot; only
            # overwrite if we haven't captured one yet (rows are newest-first,
            # so the first install_start we meet is the most recent).
            if not dev["environment"]:
                dev["environment"] = {
                    "os_version": row["os_version"],
                    "locale": row["locale"],
                    "installer_version": row["installer_version"],
                    "revit_versions": details.get("revit_versions") or [],
                }

    result_devices = []
    for dev in devices.values():
        installs = sorted(
            dev["installs"].values(),
            key=lambda i: i["started_at"],
            reverse=True,
        )
        result_devices.append(
            {
                "device": dev["device"],
                "last_seen": dev["last_seen"],
                "environment": dev["environment"],
                "installs": installs[:10],
            }
        )
    result_devices.sort(key=lambda d: d["last_seen"], reverse=True)

    return {"devices": result_devices[:limit], "total_events": len(rows)}
