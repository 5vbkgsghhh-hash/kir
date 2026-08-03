"""Device-addressed remedy channel — targeted remote repair of ONE machine.

The operator's #1 pain: many users run pirated/stripped Revit, installs go
sideways in machine-specific ways, and today there is no way to fix a SINGLE
user without either a live UI session (WebSocket remote-exec) or asking them to
reinstall. This module is the missing middle layer: the operator queues a
directive for a specific device_id, and the client (on its next poll) obeys it.

Reachability tiers (this is Tier 2):
  Tier 1  UI alive     -> /admin/remote/exec (live C# in the user's Revit).
  Tier 2  bridge polls -> THIS channel: directive rides the startup poll even
                          when the chat UI is broken.
  Tier 3  loader dead  -> nothing phones home; recovery = user re-runs /download.

Security boundaries:
  * Authoring is admin-only (X-Admin-Token, reused verify_admin_token).
  * Actions are a fixed WHITELIST of verbs. We NEVER push arbitrary code here —
    'ota_override' names a SIGNED artifact the client re-verifies against the
    pinned RSA key before applying; arbitrary C# stays behind the already
    admin-gated live /admin/remote/exec path.
  * A device_id is routing metadata, not authentication. Client polling is
    disabled by default until the C# half has an independent device capability;
    do not enable this channel merely because the backend endpoints exist.

Client half (C# UpdateChecker) ships in the next signed build; this backend
half is deployed first so the schema + operator endpoints exist before rollout.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from kukai.api.admin_remote import verify_admin_token
from kukai.config import get_settings
from kukai.security import update_signing

logger = logging.getLogger(__name__)
router = APIRouter()

# Whitelisted directive verbs. Anything else is rejected at authoring time.
#   collect_logs  -> client uploads loader-<ver>.log + bridge log to /api/diagnostics
#   ota_override  -> serve THIS device a specific signed payload (payload.revit_version
#                    + payload.sha256); client verifies signature before applying
#   reinstall     -> client surfaces a one-click repair / runs the installer /REPAIR
#   rollback      -> client reverts active/ to the previous good payload
#   message       -> show payload.text to the user (support handoff)
_ACTIONS = frozenset({"collect_logs", "ota_override", "reinstall", "rollback", "message"})
_MAX_TTL = 30 * 24 * 3600  # 30 days
_DEFAULT_TTL = 7 * 24 * 3600
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_UPDATE_VERSIONS = frozenset({"2021", "2022", "2023", "2024", "2025", "2026"})

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """CREATE TABLE IF NOT EXISTS device_directives (
        id TEXT PRIMARY KEY,
        device_id TEXT NOT NULL,
        action TEXT NOT NULL,
        payload TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        created_by TEXT NOT NULL DEFAULT 'admin',
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        consumed_at TEXT,
        result TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS idx_directives_device ON device_directives(device_id)",
    "CREATE INDEX IF NOT EXISTS idx_directives_status ON device_directives(status)",
)

_schema_ensured: set[int] = set()


def _channel_enabled() -> bool:
    """Explicit rollout gate; backend-half deployment must expose no live channel."""
    return os.environ.get("KUKAI_DEVICE_DIRECTIVES_ENABLED", "") == "1"


async def _get_db() -> Optional[Any]:
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


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _iso_plus(seconds: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


class DirectiveIn(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int = _DEFAULT_TTL


def _validated_payload(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Make the whitelist semantic, not just a list of verb strings.

    In particular ota_override must select the currently staged, locally
    signature-verified artifact. URLs/paths/code supplied by an admin request
    are never reflected to a client.
    """
    if action in {"collect_logs", "reinstall", "rollback"}:
        if payload:
            raise HTTPException(status_code=400, detail=f"{action} does not accept payload fields")
        return {}
    if action == "message":
        if set(payload) != {"text"} or not isinstance(payload.get("text"), str):
            raise HTTPException(status_code=400, detail="message payload must be exactly {text}")
        text = payload["text"].strip()
        if not text or len(text) > 2000:
            raise HTTPException(status_code=400, detail="message text must be 1..2000 chars")
        return {"text": text}
    if action == "ota_override":
        if set(payload) != {"revit_version", "sha256"}:
            raise HTTPException(
                status_code=400,
                detail="ota_override payload must be exactly {revit_version, sha256}",
            )
        ver = str(payload.get("revit_version", ""))
        digest = str(payload.get("sha256", "")).lower()
        if ver not in _UPDATE_VERSIONS or not _SHA256_RE.fullmatch(digest):
            raise HTTPException(status_code=400, detail="invalid ota_override version/hash")
        vdir = Path(get_settings()._get_data_base()) / "data" / "updates" / ver
        zip_path, sig_path, hash_path = (
            vdir / "latest.zip", vdir / "latest.zip.sig", vdir / "latest.sha256"
        )
        try:
            served_hash = hash_path.read_text(encoding="utf-8").strip().lower()
            zip_bytes = zip_path.read_bytes()
            sig_b64 = sig_path.read_text(encoding="utf-8").strip()
            pub_b64 = update_signing.fleet_public_key_b64()
        except OSError:
            raise HTTPException(status_code=409, detail="selected OTA artifact is not staged")
        if served_hash != digest:
            raise HTTPException(status_code=409, detail="selected hash is not the staged OTA target")
        if not update_signing.verify(zip_bytes, sig_b64, pub_b64):
            raise HTTPException(status_code=409, detail="selected OTA artifact signature is invalid")
        return {"revit_version": ver, "sha256": digest}
    raise HTTPException(status_code=400, detail="unsupported action")


# ---------------------------------------------------------------------------
# Operator side (admin-only)
# ---------------------------------------------------------------------------

@router.post("/admin/device/{device_id}/directive")
async def create_directive(
    device_id: str,
    body: DirectiveIn,
    _: None = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Queue a repair directive for one device. Idempotent per (device, action):
    a new pending directive supersedes an un-consumed one of the same action so
    the operator never stacks duplicates."""
    if not _channel_enabled():
        raise HTTPException(status_code=503, detail="device directives are rollout-disabled")
    if body.action not in _ACTIONS:
        raise HTTPException(status_code=400, detail=f"unknown action; allowed: {sorted(_ACTIONS)}")
    if not _DEVICE_ID_RE.fullmatch(device_id):
        raise HTTPException(status_code=400, detail="bad device_id")
    ttl = max(60, min(int(body.ttl_seconds or _DEFAULT_TTL), _MAX_TTL))
    payload = _validated_payload(body.action, body.payload)

    db = await _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    await _ensure_schema(db)

    # Supersede any still-pending directive of the same action for this device.
    await db.execute_raw(
        "UPDATE device_directives SET status='superseded' "
        "WHERE device_id=? AND action=? AND status='pending'",
        (device_id, body.action),
    )
    did = str(uuid.uuid4())
    await db.execute_raw(
        """INSERT INTO device_directives
               (id, device_id, action, payload, status, created_by, created_at, expires_at)
           VALUES (?, ?, ?, ?, 'pending', 'admin', ?, ?)""",
        (did, device_id, body.action, json.dumps(payload, ensure_ascii=False),
         _now(), _iso_plus(ttl)),
    )
    logger.info("DIRECTIVE queued device=%s action=%s id=%s", device_id, body.action, did)
    return {"id": did, "device_id": device_id, "action": body.action, "status": "pending",
            "expires_at": _iso_plus(ttl)}


@router.get("/admin/device/{device_id}/directives")
async def list_device_directives(
    device_id: str,
    limit: int = Query(50, ge=1, le=500),
    _: None = Depends(verify_admin_token),
) -> dict[str, Any]:
    db = await _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    await _ensure_schema(db)
    rows = await db.fetch_all(
        "SELECT * FROM device_directives WHERE device_id=? ORDER BY created_at DESC LIMIT ?",
        (device_id, limit),
    )
    return {"device_id": device_id, "directives": [dict(r) for r in rows]}


@router.get("/admin/directives")
async def list_recent_directives(
    limit: int = Query(100, ge=1, le=1000),
    _: None = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Operator dashboard: recent directives across all devices."""
    db = await _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    await _ensure_schema(db)
    rows = await db.fetch_all(
        "SELECT * FROM device_directives ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    return {"directives": [dict(r) for r in rows], "count": len(rows)}


# ---------------------------------------------------------------------------
# Client side.  The rollout gate below must remain off until requests carry an
# independent per-device capability; device_id is routing metadata, not auth.
# ---------------------------------------------------------------------------

@router.get("/api/device/directives")
async def poll_directives(device_id: str = Query("", max_length=128)) -> dict[str, Any]:
    """Client poll: return the oldest pending, non-expired directive for this
    device (or none). Expired pendings are lazily reaped. The client applies the
    directive then POSTs /api/device/directive/{id}/ack — a directive is only
    marked consumed on explicit ack, so a crash mid-apply leaves it retriable."""
    if not _channel_enabled() or not _DEVICE_ID_RE.fullmatch(device_id):
        return {"directive": None}
    db = await _get_db()
    if db is None:
        return {"directive": None}
    try:
        await _ensure_schema(db)
        now = _now()
        # Reap expired pendings for this device (cheap, bounded).
        await db.execute_raw(
            "UPDATE device_directives SET status='expired' "
            "WHERE device_id=? AND status='pending' AND expires_at < ?",
            (device_id, now),
        )
        rows = await db.fetch_all(
            "SELECT id, action, payload, expires_at FROM device_directives "
            "WHERE device_id=? AND status='pending' ORDER BY created_at ASC LIMIT 1",
            (device_id,),
        )
    except Exception as e:  # noqa: BLE001 — never fail the client's poll
        logger.error("directive poll failed device=%s: %s", device_id, e)
        return {"directive": None}
    if not rows:
        return {"directive": None}
    r = dict(rows[0])
    try:
        payload = json.loads(r.get("payload") or "{}")
    except Exception:
        payload = {}
    return {"directive": {"id": r["id"], "action": r["action"], "payload": payload,
                          "expires_at": r.get("expires_at")}}


class AckIn(BaseModel):
    device_id: str = ""
    ok: bool = True
    result: str = ""


@router.post("/api/device/directive/{directive_id}/ack")
async def ack_directive(
    directive_id: str,
    body: AckIn = Body(...),
) -> dict[str, Any]:
    """Client acknowledges it applied (or failed) a directive. Scoped: the ack
    must carry the same device_id the directive was addressed to."""
    if not _channel_enabled():
        raise HTTPException(status_code=503, detail="device directives are rollout-disabled")
    if not _DEVICE_ID_RE.fullmatch(body.device_id):
        raise HTTPException(status_code=400, detail="bad device_id")
    db = await _get_db()
    if db is None:
        raise HTTPException(status_code=503, detail="db unavailable")
    await _ensure_schema(db)
    rows = await db.fetch_all(
        "SELECT device_id, status FROM device_directives WHERE id=?", (directive_id,)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="unknown directive")
    if dict(rows[0]).get("device_id") != body.device_id:
        raise HTTPException(status_code=403, detail="device_id mismatch")
    if dict(rows[0]).get("status") != "pending":
        raise HTTPException(status_code=409, detail="directive is not pending")
    cur = await db.execute_raw(
        "UPDATE device_directives SET status=?, consumed_at=?, result=? "
        "WHERE id=? AND device_id=? AND status='pending'",
        ("consumed" if body.ok else "failed", _now(), (body.result or "")[:2000],
         directive_id, body.device_id),
    )
    if cur.rowcount != 1:
        raise HTTPException(status_code=409, detail="directive was already acknowledged")
    logger.info("DIRECTIVE ack device=%s id=%s ok=%s", body.device_id, directive_id, body.ok)
    return {"status": "consumed" if body.ok else "failed", "id": directive_id}
