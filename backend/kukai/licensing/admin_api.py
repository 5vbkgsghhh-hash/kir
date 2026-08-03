"""Admin API — license management + telemetry dashboard endpoints.

All endpoints require X-Admin-Token header matching KUKAI_ADMIN_TOKEN env var.
These are separate from user-facing endpoints to enforce admin-only access.
"""

from __future__ import annotations

import hmac
import html
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from kukai.config import get_settings

from kukai.licensing.license_manager import (
    LicenseError,
    LicenseManager,
    LicenseNotFoundError,
    TIER_LIMITS,
    VALID_TIERS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# --- Auth dependency ---

async def verify_admin_token(
    x_admin_token: Optional[str] = Header(None),
    token: Optional[str] = Query(None),
) -> str:
    """Verify admin token. Required for all admin endpoints.

    Accepts token via X-Admin-Token header OR ?token= query parameter.
    Query param is convenient for opening dashboard in browser.
    """
    settings = get_settings()

    if not settings.admin_token:
        raise HTTPException(
            status_code=503,
            detail="Admin API not configured. Set KUKAI_ADMIN_TOKEN.",
        )

    provided = x_admin_token or token
    if token and not x_admin_token:
        logger.warning(
            "SECURITY: Admin token provided via query parameter. "
            "This is logged by proxies/CDNs. Use X-Admin-Token header instead."
        )
    if not provided or not hmac.compare_digest(provided, settings.admin_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")

    return provided


# --- Request/Response models ---

class CreateLicenseRequest(BaseModel):
    tier: str = "pro"
    max_devices: Optional[int] = None
    daily_limit: Optional[int] = None
    days: int = 365
    key: Optional[str] = None  # Auto-generated if not provided
    name: str = ""  # Display name for tracking


class RenameLicenseRequest(BaseModel):
    name: str


class CreateLicenseResponse(BaseModel):
    id: str
    key: str
    tier: str
    max_devices: int
    daily_limit: int
    expires_at: str


class LicenseDetailResponse(BaseModel):
    key: str
    tier: str
    max_devices: int
    daily_limit: int
    expires_at: str
    active: bool
    device_count: int
    devices: list[dict[str, Any]] = Field(default_factory=list)


class LicenseListResponse(BaseModel):
    licenses: list[dict[str, Any]]
    total: int


class AuditLogResponse(BaseModel):
    entries: list[dict[str, Any]]
    total: int


class BroadcastRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Text to broadcast to all connected users")


# --- Helper to get LicenseManager ---

def _get_license_manager() -> LicenseManager:
    """Get the license manager from app state."""
    from kukai.main import get_app_state
    state = get_app_state()
    if not hasattr(state, "license_manager") or state.license_manager is None:
        raise HTTPException(
            status_code=503,
            detail="License manager not initialized",
        )
    return state.license_manager


# --- Endpoints ---

@router.post("/licenses", response_model=CreateLicenseResponse)
async def create_license(
    request: CreateLicenseRequest,
    _admin: str = Depends(verify_admin_token),
) -> CreateLicenseResponse:
    """Create a new license key."""
    lm = _get_license_manager()

    key = request.key or LicenseManager.generate_license_key()

    try:
        result = await lm.register_license(
            key=key,
            tier=request.tier,
            max_devices=request.max_devices,
            daily_limit=request.daily_limit,
            days=request.days,
            name=request.name,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create license")
        raise HTTPException(status_code=500, detail="Failed to create license")

    return CreateLicenseResponse(**result)


@router.get("/licenses", response_model=LicenseListResponse)
async def list_licenses(
    limit: int = Query(100, ge=1, le=1000),
    _admin: str = Depends(verify_admin_token),
) -> LicenseListResponse:
    """List all licenses."""
    lm = _get_license_manager()
    licenses = await lm.list_licenses(limit=limit)
    return LicenseListResponse(licenses=licenses, total=len(licenses))


@router.get("/licenses/{key}", response_model=LicenseDetailResponse)
async def get_license_detail(
    key: str,
    _admin: str = Depends(verify_admin_token),
) -> LicenseDetailResponse:
    """Get license details including devices."""
    lm = _get_license_manager()

    try:
        info = await lm.get_license_info(key)
    except LicenseNotFoundError:
        raise HTTPException(status_code=404, detail="License not found")

    devices = await lm.get_license_devices(key)

    return LicenseDetailResponse(
        key=info.key,
        tier=info.tier,
        max_devices=info.max_devices,
        daily_limit=info.daily_limit,
        expires_at=info.expires_at,
        active=info.active,
        device_count=info.device_count,
        devices=devices,
    )


@router.delete("/licenses/{key}/devices/{device_id}")
async def revoke_device(
    key: str,
    device_id: str,
    _admin: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Revoke a device from a license."""
    lm = _get_license_manager()

    try:
        await lm.get_license_info(key)
    except LicenseNotFoundError:
        raise HTTPException(status_code=404, detail="License not found")

    success = await lm.deactivate_device_by_id(key, device_id)
    if not success:
        raise HTTPException(status_code=404, detail="Device not found or already deactivated")

    return {"status": "ok", "detail": f"Device {device_id} deactivated"}


@router.patch("/licenses/{key}/name")
async def rename_license(
    key: str,
    request: RenameLicenseRequest,
    _admin: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Set display name for a license (for admin tracking)."""
    lm = _get_license_manager()
    success = await lm.update_license_name(key, request.name)
    if not success:
        raise HTTPException(status_code=404, detail="License not found")
    return {"status": "ok", "key": key, "name": request.name}


@router.get("/audit", response_model=AuditLogResponse)
async def get_audit_log(
    limit: int = Query(100, ge=1, le=1000),
    _admin: str = Depends(verify_admin_token),
) -> AuditLogResponse:
    """Get audit log entries."""
    lm = _get_license_manager()
    entries = await lm.get_audit_log(limit=limit)
    return AuditLogResponse(entries=entries, total=len(entries))


@router.patch("/licenses/batch/tier")
async def batch_update_tier(
    tier: str = Query(..., description="Target tier: free, pro, ultra"),
    _admin: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Update ALL licenses to specified tier. Used for bulk migration."""
    if tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}. Valid: {', '.join(VALID_TIERS)}")

    lm = _get_license_manager()
    tier_config = TIER_LIMITS[tier]

    # Use the manager's underlying connection adapter so this works against
    # whatever backend the storage layer is currently wired to (PG today,
    # SQLite previously). _db on LicenseManager is set by the constructor.
    db = lm._db  # type: ignore[attr-defined]
    cursor = await db.execute(
        "UPDATE licenses SET tier = ?, max_devices = ?, daily_limit = ?",
        (tier, tier_config["max_devices"], tier_config.get("daily_limit", 0)),
    )
    await db.commit()
    updated = cursor.rowcount

    logger.info("Batch tier update: %d licenses -> %s", updated, tier)
    return {"status": "ok", "updated": updated, "tier": tier}


@router.get("/connections")
async def get_active_connections(
    _admin: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Return count of active WebSocket connections (no side effects).

    Used by the Telegram ops bot for /users command — unlike /broadcast,
    this endpoint doesn't push anything to the connections, just counts them.
    """
    from kukai.api.chat_ws import _device_websockets  # noqa: PLC0415 — lazy

    devices_count = len(_device_websockets)
    connections_count = sum(len(ws_set) for ws_set in _device_websockets.values())
    return {
        "devices": devices_count,
        "connections": connections_count,
        "device_ids": list(_device_websockets.keys()),
    }


@router.post("/broadcast")
async def broadcast_message(
    request: BroadcastRequest,
    _admin: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Broadcast a text message to all currently connected WebSocket clients.

    The message appears as a normal KUKI chat response in every active session.
    Uses the standard stream sequence (stream_start → stream_chunk → stream_end)
    so no frontend changes are required.

    Returns counts of devices and websocket connections reached.
    """
    from kukai.api.chat_ws import _device_websockets
    from kukai.api.chat_ws import _send_json  # noqa: PLC0415 — lazy import avoids circular dep

    devices_reached = 0
    connections_reached = 0
    connections_failed = 0

    payload = request.message

    for device_id, ws_set in list(_device_websockets.items()):
        device_delivered = False
        for ws in list(ws_set):
            try:
                await _send_json(ws, {"type": "stream_start"})
                await _send_json(ws, {"type": "stream_chunk", "text": payload})
                await _send_json(ws, {"type": "stream_end"})
                connections_reached += 1
                device_delivered = True
            except Exception as exc:
                logger.warning("Broadcast: failed to send to device %s — %s", device_id, exc)
                connections_failed += 1
        if device_delivered:
            devices_reached += 1

    logger.info(
        "Broadcast sent: %d devices, %d connections reached, %d failed",
        devices_reached, connections_reached, connections_failed,
    )
    return {
        "status": "ok",
        "devices_reached": devices_reached,
        "connections_reached": connections_reached,
        "connections_failed": connections_failed,
    }


@router.get("/dashboard")
async def admin_dashboard(
    _admin: str = Depends(verify_admin_token),
    days: int = Query(30, ge=1, le=365),
) -> HTMLResponse:
    """Admin telemetry dashboard — premium Mission Control page."""
    from kukai.main import get_app_state
    from kukai.telemetry import TelemetryCollector
    from kukai.api.chat_ws import get_active_ws_count

    state = get_app_state()
    collector = TelemetryCollector(state.db)
    data = await collector.get_summary(days=days)

    # Live status indicators
    active_ws = get_active_ws_count()
    bridge_connected = state.bridge.connected
    errors_today = await collector.errors_today()

    # Fetch license summary + per-license usage
    license_info: dict[str, Any] = {"total": 0, "active": 0, "devices": 0}
    license_usage: list[dict[str, Any]] = []
    try:
        lm = _get_license_manager()
        licenses = await lm.list_licenses(limit=1000)
        license_info["total"] = len(licenses)
        license_info["active"] = sum(
            1 for lic in licenses if lic.get("active", False)
        )
        license_info["devices"] = sum(
            lic.get("device_count", 0) for lic in licenses
        )
        license_usage = await lm.get_license_usage(days=days)
    except Exception:
        pass

    # Fetch Gemini pool status + quotas
    gemini_info: dict[str, Any] = {}
    gemini_quota: list[dict[str, Any]] = []
    try:
        if state.llm and hasattr(state.llm, '_gemini_pool') and state.llm._gemini_pool:
            gemini_info = state.llm._gemini_pool.status()
            gemini_quota = await state.llm._gemini_pool.get_quota()
    except Exception:
        pass

    page = _build_dashboard_html(
        data, _admin, license_info, gemini_info, gemini_quota, license_usage,
        active_ws=active_ws, bridge_connected=bridge_connected, errors_today=errors_today,
    )
    return HTMLResponse(content=page)


def _build_dashboard_html(
    data: dict[str, Any],
    token: str,
    license_info: dict[str, Any],
    gemini_info: dict[str, Any] | None = None,
    gemini_quota: list[dict[str, Any]] | None = None,
    license_usage: list[dict[str, Any]] | None = None,
    *,
    active_ws: int = 0,
    bridge_connected: bool = False,
    errors_today: int = 0,
) -> str:
    """Build a premium Mission Control dashboard. Self-contained HTML."""

    if "error" in data:
        return (
            "<html><body style='background:#0a0a0f;color:#fff;font-family:sans-serif;"
            "padding:40px'><h1>Telemetry unavailable</h1>"
            f"<p>{html.escape(str(data['error']))}</p></body></html>"
        )

    safe_token = html.escape(token)
    totals = data.get("totals", {})
    total_requests = int(totals.get("total", 0) or 0)
    total_sessions = int(totals.get("sessions", 0) or 0)
    avg_ms = int(totals.get("avg_ms", 0) or 0)
    total_errors = int(totals.get("errors", 0) or 0)
    tool_ok = int(totals.get("tool_ok", 0) or 0)
    tool_fail = int(totals.get("tool_fail", 0) or 0)
    repairs = int(totals.get("repairs", 0) or 0)
    tool_total = tool_ok + tool_fail
    period = int(data.get("period_days", 30))

    error_rate_num = (
        round(total_errors / total_requests * 100, 1) if total_requests > 0 else 0
    )
    success_rate_num = (
        round(tool_ok / tool_total * 100, 1) if tool_total > 0 else 0
    )
    avg_sec = round(avg_ms / 1000, 1) if avg_ms > 0 else 0

    # --- Categories: build donut chart segments ---
    categories = data.get("categories", [])
    cat_total = sum(c.get("count", 0) for c in categories) or 1
    cat_colors = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#a855f7", "#06b6d4"]
    cat_segments_html = ""
    cat_legend_html = ""
    cat_offset = 0
    for i, c in enumerate(categories[:6]):
        c_name = html.escape(str(c.get("category", "other")))
        c_count = c.get("count", 0)
        c_pct = round(c_count / cat_total * 100, 1)
        color = cat_colors[i % len(cat_colors)]
        dash = round(c_pct * 3.1416, 2)  # circumference=314.16 for r=50
        gap = round(314.16 - dash, 2)
        cat_segments_html += (
            f'<circle cx="60" cy="60" r="50" fill="none" stroke="{color}" '
            f'stroke-width="20" stroke-dasharray="{dash} {gap}" '
            f'stroke-dashoffset="-{round(cat_offset * 3.1416, 2)}" '
            f'opacity="0.9"/>\n'
        )
        cat_offset += c_pct
        cat_legend_html += (
            f'<div class="legend-item">'
            f'<span class="legend-dot" style="background:{color}"></span>'
            f'<span class="legend-label">{c_name}</span>'
            f'<span class="legend-val">{c_pct}%</span></div>\n'
        )
    if not categories:
        cat_legend_html = '<div class="empty-note">No data yet</div>'

    # --- Tools: build horizontal bars ---
    tools = data.get("top_tools", [])
    max_tool_count = max((t.get("count", 0) for t in tools), default=1) or 1
    tool_bars_html = ""
    for t in tools[:8]:
        t_name = html.escape(str(t.get("tool_calls", "")))
        t_count = t.get("count", 0)
        t_pct = round(t_count / max_tool_count * 100)
        tool_bars_html += (
            f'<div class="bar-row">'
            f'<span class="bar-label">{t_name}</span>'
            f'<div class="bar-track"><div class="bar-fill" '
            f'style="--target-width:{t_pct}%"></div></div>'
            f'<span class="bar-val">{t_count}</span></div>\n'
        )
    if not tools:
        tool_bars_html = '<div class="empty-note">No tool calls yet</div>'

    # --- Errors list ---
    errors = data.get("top_errors", [])
    err_list_html = ""
    for e in errors[:6]:
        e_name = html.escape(str(e.get("error", "")))
        e_count = e.get("count", 0)
        err_list_html += (
            f'<div class="err-row">'
            f'<span class="err-name">{e_name}</span>'
            f'<span class="err-count">{e_count}</span></div>\n'
        )
    if not errors:
        err_list_html = '<div class="empty-note">No errors — all clear</div>'

    # --- Daily trend: build SVG area chart ---
    daily = data.get("daily", [])
    daily_sorted = list(reversed(daily))  # oldest first
    chart_svg = ""
    if len(daily_sorted) >= 2:
        max_req = max((d.get("total_requests", 0) for d in daily_sorted), default=1) or 1
        w, h = 600, 140
        n = len(daily_sorted)
        step = w / max(n - 1, 1)
        points = []
        for i, d in enumerate(daily_sorted):
            x = round(i * step, 1)
            y = round(h - (d.get("total_requests", 0) / max_req) * (h - 10), 1)
            points.append(f"{x},{y}")
        polyline = " ".join(points)
        polygon = f"0,{h} {polyline} {round((n - 1) * step, 1)},{h}"
        chart_svg = (
            f'<svg viewBox="0 0 {w} {h}" class="area-chart">'
            f'<defs><linearGradient id="ag" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0%" stop-color="#3b82f6" stop-opacity="0.4"/>'
            f'<stop offset="100%" stop-color="#3b82f6" stop-opacity="0.02"/>'
            f'</linearGradient></defs>'
            f'<polygon points="{polygon}" fill="url(#ag)"/>'
            f'<polyline points="{polyline}" fill="none" stroke="#3b82f6" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>'
            f'</svg>'
        )
    elif len(daily_sorted) == 1:
        chart_svg = '<div class="empty-note">Need 2+ days for trend chart</div>'
    else:
        chart_svg = '<div class="empty-note">No daily data yet</div>'

    # --- Daily table rows ---
    daily_rows = ""
    for d in daily:
        d_date = html.escape(str(d.get("date", "")))
        d_req = d.get("total_requests", 0)
        d_sess = d.get("unique_sessions", 0)
        d_tools = d.get("tool_requests", 0)
        d_err = d.get("errors", 0)
        d_avg = d.get("avg_response_ms", 0)
        err_class = ' class="val-err"' if d_err else ""
        daily_rows += (
            f"<tr><td>{d_date}</td><td>{d_req}</td><td>{d_sess}</td>"
            f"<td>{d_tools}</td><td{err_class}>{d_err}</td>"
            f"<td>{d_avg} ms</td></tr>\n"
        )

    # --- Licenses ---
    lic_total = license_info.get("total", 0)
    lic_active = license_info.get("active", 0)
    lic_devices = license_info.get("devices", 0)

    # --- Gemini Pool ---
    gemini_panel_html = ""
    if gemini_info and gemini_info.get("total_accounts", 0) > 0:
        gm_primary = html.escape(str(gemini_info.get("primary_model", "?")))
        gm_fallback = html.escape(str(gemini_info.get("fallback_model", "?")))
        gm_accounts = gemini_info.get("accounts", [])
        gm_avail_p = gemini_info.get("available_primary", 0)
        gm_avail_f = gemini_info.get("available_fallback", 0)
        gm_total = gemini_info.get("total_accounts", 0)

        acct_rows = ""
        for acc in gm_accounts:
            email = html.escape(str(acc.get("email", "?")))
            # Shorten email: first 3 chars + ... + domain
            email_short = email.split("@")[0][:6] + "..@" + email.split("@")[-1] if "@" in email else email
            p_ok = acc.get("primary_ok", False)
            f_ok = acc.get("fallback_ok", False)
            p_cd = acc.get("primary_cooldown_s", 0)
            f_cd = acc.get("fallback_cooldown_s", 0)
            p_dot = f'<span class="gm-dot {"gm-ok" if p_ok else "gm-cd"}">{p_cd}s</span>' if not p_ok and p_cd > 0 else f'<span class="gm-dot {"gm-ok" if p_ok else "gm-off"}"></span>'
            f_dot = f'<span class="gm-dot {"gm-ok" if f_ok else "gm-cd"}">{f_cd}s</span>' if not f_ok and f_cd > 0 else f'<span class="gm-dot {"gm-ok" if f_ok else "gm-off"}"></span>'
            acct_rows += (
                f'<div class="gm-row">'
                f'<span class="gm-email">{email_short}</span>'
                f'{p_dot}{f_dot}'
                f'</div>\n'
            )

        # Build quota bars per account
        quota_html = ""
        if gemini_quota:
            for qinfo in gemini_quota:
                q_email = html.escape(str(qinfo.get("email", "?")))
                q_short = q_email.split("@")[0][:6] + ".." if "@" in q_email else q_email
                if "error" in qinfo:
                    quota_html += f'<div class="gm-q-acct"><span class="gm-q-name">{q_short}</span><span class="gm-q-err">{html.escape(str(qinfo["error"]))}</span></div>'
                    continue
                buckets = qinfo.get("buckets", [])
                if not buckets:
                    continue
                quota_html += f'<div class="gm-q-acct"><span class="gm-q-name">{q_short}</span></div>'
                for bkt in buckets:
                    b_model = html.escape(str(bkt.get("model", "?")))
                    b_pct = bkt.get("remaining_pct", 0)
                    b_color = "#22c55e" if b_pct > 50 else ("#f59e0b" if b_pct > 20 else "#ef4444")
                    quota_html += (
                        f'<div class="gm-q-row">'
                        f'<span class="gm-q-model">{b_model}</span>'
                        f'<div class="gm-q-track"><div class="gm-q-fill" style="width:{b_pct}%;background:{b_color}"></div></div>'
                        f'<span class="gm-q-pct">{b_pct}%</span>'
                        f'</div>'
                    )

        gemini_panel_html = f"""
    <div class="panel fade-in d8">
      <div class="panel-title">Gemini Pool</div>
      <div class="gm-models">
        <div class="gm-model-row">
          <span class="gm-model-label">Pro</span>
          <span class="gm-model-name">{gm_primary}</span>
          <span class="gm-model-avail {"gm-ok" if gm_avail_p > 0 else "gm-off"}">{gm_avail_p}/{gm_total}</span>
        </div>
        <div class="gm-model-row">
          <span class="gm-model-label">Flash</span>
          <span class="gm-model-name">{gm_fallback}</span>
          <span class="gm-model-avail {"gm-ok" if gm_avail_f > 0 else "gm-off"}">{gm_avail_f}/{gm_total}</span>
        </div>
      </div>
      <div class="gm-header">
        <span class="gm-h-email">Account</span>
        <span class="gm-h-col">Pro</span>
        <span class="gm-h-col">Flash</span>
      </div>
      {acct_rows}
      {"<div style='margin-top:12px;border-top:1px solid #1a1d2e;padding-top:10px'><div class='panel-title' style='margin-bottom:8px'>Daily Quotas</div>" + quota_html + "</div>" if quota_html else ""}
    </div>"""

    # --- License usage table ---
    lic_table_rows = ""
    if license_usage:
        max_usage = max((lu.get("total_requests", 0) for lu in license_usage), default=1) or 1
        for lu in license_usage:
            lu_key = html.escape(str(lu.get("key", "?")))
            lu_name = html.escape(str(lu.get("name", "")))
            lu_tier = html.escape(str(lu.get("tier", "?")))
            lu_active = lu.get("active", False)
            lu_devs = lu.get("devices", 0)
            lu_total = lu.get("total_requests", 0)
            lu_today = lu.get("today_requests", 0)
            lu_pct = round(lu_total / max_usage * 100) if max_usage > 0 else 0
            # Shorten key for display
            lu_key_short = lu_key[:8] + ".." + lu_key[-4:] if len(lu_key) > 14 else lu_key
            tier_badge_color = {"pro": "#a855f7", "ultra": "#f59e0b", "free": "#5a5f76"}.get(lu_tier, "#5a5f76")
            status_dot = '<span style="color:#22c55e">&#x25CF;</span>' if lu_active else '<span style="color:#ef4444">&#x25CF;</span>'

            lic_table_rows += (
                f'<tr>'
                f'<td>{status_dot} {lu_name or lu_key_short}</td>'
                f'<td><span class="tier-badge" style="--tc:{tier_badge_color}">{lu_tier}</span></td>'
                f'<td>{lu_devs}</td>'
                f'<td><div class="usage-cell"><div class="usage-bar" style="width:{lu_pct}%"></div>'
                f'<span class="usage-num">{lu_total}</span></div></td>'
                f'<td>{lu_today}</td>'
                f'<td class="lic-key-cell">{lu_key_short}</td>'
                f'</tr>\n'
            )
    if not lic_table_rows:
        lic_table_rows = '<tr><td colspan="6" class="empty-note">No licenses</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KUKI Mission Control</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{
  background:#0a0a0f;color:#b0b4c0;
  font-family:'Outfit',system-ui,sans-serif;
  line-height:1.5;min-height:100vh;
  background-image:
    linear-gradient(rgba(59,130,246,0.03) 1px,transparent 1px),
    linear-gradient(90deg,rgba(59,130,246,0.03) 1px,transparent 1px);
  background-size:40px 40px;
}}
.wrap{{max-width:1400px;margin:0 auto;padding:24px 28px}}
header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px}}
.logo{{display:flex;align-items:center;gap:12px}}
.logo h1{{font-size:20px;font-weight:700;color:#fff;letter-spacing:1.5px}}
.logo .dot{{width:8px;height:8px;background:#22c55e;border-radius:50%;
  box-shadow:0 0 8px #22c55e;animation:pulse 2s infinite}}
@keyframes pulse{{0%,100%{{opacity:1}}50%{{opacity:.4}}}}
.logo span.sub{{color:#4b5068;font-size:13px;font-weight:400;letter-spacing:.5px}}
.controls{{display:flex;gap:8px;align-items:center}}
.period-btn{{
  background:transparent;border:1px solid #1e2130;color:#6b7084;
  padding:6px 14px;border-radius:6px;font-family:'Outfit',sans-serif;
  font-size:12px;cursor:pointer;transition:all .2s}}
.period-btn:hover,.period-btn.active{{
  border-color:#3b82f6;color:#3b82f6;background:rgba(59,130,246,.08)}}
.refresh-btn{{
  background:rgba(59,130,246,.1);border:1px solid #3b82f6;color:#3b82f6;
  padding:6px 14px;border-radius:6px;font-family:'Outfit',sans-serif;
  font-size:12px;cursor:pointer;transition:all .2s}}
.refresh-btn:hover{{background:rgba(59,130,246,.2)}}
.kpi-row{{
  display:grid;grid-template-columns:repeat(5,1fr);gap:14px;margin-bottom:24px}}
.kpi{{
  background:rgba(14,16,26,.7);border:1px solid #1a1d2e;border-radius:10px;
  padding:18px 20px;backdrop-filter:blur(8px);
  transition:all .3s;position:relative;overflow:hidden}}
.kpi:hover{{border-color:rgba(59,130,246,.3);box-shadow:0 0 20px rgba(59,130,246,.08)}}
.kpi::after{{content:'';position:absolute;top:0;left:0;right:0;height:2px;
  background:linear-gradient(90deg,transparent,var(--accent,#3b82f6),transparent);opacity:0;
  transition:opacity .3s}}
.kpi:hover::after{{opacity:1}}
.kpi-val{{
  font-family:'JetBrains Mono',monospace;font-size:26px;font-weight:500;
  color:#fff;margin-bottom:2px}}
.kpi-label{{font-size:12px;color:#5a5f76;letter-spacing:.3px}}
.kpi-sub{{font-family:'JetBrains Mono',monospace;font-size:11px;margin-top:4px}}
.kpi-sub.good{{color:#22c55e}} .kpi-sub.bad{{color:#ef4444}} .kpi-sub.neutral{{color:#5a5f76}}
.status-row{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:24px}}
.status-dot{{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}}
.status-dot.on{{background:#22c55e;box-shadow:0 0 6px #22c55e}}
.status-dot.off{{background:#5a5f76}}
.grid-main{{
  display:grid;grid-template-columns:1fr 300px;gap:20px;margin-bottom:20px}}
.panel{{
  background:rgba(14,16,26,.7);border:1px solid #1a1d2e;border-radius:10px;
  padding:20px;backdrop-filter:blur(8px)}}
.panel-title{{
  font-size:11px;font-weight:600;color:#5a5f76;letter-spacing:1.2px;
  text-transform:uppercase;margin-bottom:14px;
  display:flex;align-items:center;gap:8px}}
.panel-title::before{{content:'';display:inline-block;width:3px;height:12px;
  background:#3b82f6;border-radius:2px}}
.area-chart{{width:100%;height:auto;display:block}}
.sidebar{{display:flex;flex-direction:column;gap:20px}}
.donut-wrap{{display:flex;align-items:center;gap:18px}}
.donut-wrap svg{{width:120px;height:120px;flex-shrink:0}}
.legend-item{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.legend-dot{{width:8px;height:8px;border-radius:2px;flex-shrink:0}}
.legend-label{{font-size:12px;color:#8a8fa6;flex:1}}
.legend-val{{font-family:'JetBrains Mono',monospace;font-size:12px;color:#fff}}
.bar-row{{display:flex;align-items:center;gap:10px;margin-bottom:8px}}
.bar-label{{
  font-family:'JetBrains Mono',monospace;font-size:11px;color:#8a8fa6;
  width:180px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.bar-track{{flex:1;height:6px;background:#12141f;border-radius:3px;overflow:hidden}}
.bar-fill{{
  height:100%;border-radius:3px;width:0;
  background:linear-gradient(90deg,#3b82f6,#60a5fa);
  animation:barGrow .8s ease forwards}}
@keyframes barGrow{{to{{width:var(--target-width)}}}}
.bar-val{{
  font-family:'JetBrains Mono',monospace;font-size:11px;color:#fff;
  width:40px;text-align:right;flex-shrink:0}}
.lic-grid{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}}
.lic-stat{{text-align:center}}
.lic-stat .val{{font-family:'JetBrains Mono',monospace;font-size:22px;color:#fff}}
.lic-stat .lbl{{font-size:11px;color:#5a5f76}}
.err-row{{
  display:flex;align-items:center;justify-content:space-between;
  padding:8px 0;border-bottom:1px solid #13151f}}
.err-row:last-child{{border:none}}
.err-name{{
  font-family:'JetBrains Mono',monospace;font-size:11px;color:#ef4444;
  flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.err-count{{
  font-family:'JetBrains Mono',monospace;font-size:12px;color:#fff;
  margin-left:12px;flex-shrink:0}}
table{{width:100%;border-collapse:collapse}}
th{{
  font-size:10px;font-weight:600;color:#5a5f76;letter-spacing:.8px;
  text-transform:uppercase;text-align:left;padding:8px 12px;
  border-bottom:1px solid #1a1d2e}}
td{{
  font-family:'JetBrains Mono',monospace;font-size:12px;
  padding:7px 12px;border-bottom:1px solid #0f1018}}
tr:hover td{{background:rgba(59,130,246,.04)}}
.val-err{{color:#ef4444}}
.empty-note{{
  color:#3a3e52;font-size:12px;text-align:center;padding:20px;
  font-style:italic}}
.gm-models{{margin-bottom:12px}}
.gm-model-row{{display:flex;align-items:center;gap:8px;margin-bottom:6px}}
.gm-model-label{{font-size:10px;font-weight:600;color:#5a5f76;width:36px;
  text-transform:uppercase;letter-spacing:.5px}}
.gm-model-name{{font-family:'JetBrains Mono',monospace;font-size:11px;
  color:#8a8fa6;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.gm-model-avail{{font-family:'JetBrains Mono',monospace;font-size:12px;
  font-weight:500;padding:2px 8px;border-radius:4px;flex-shrink:0}}
.gm-model-avail.gm-ok{{color:#22c55e;background:rgba(34,197,94,.1)}}
.gm-model-avail.gm-off{{color:#ef4444;background:rgba(239,68,68,.1)}}
.gm-header{{display:flex;align-items:center;gap:8px;padding-bottom:6px;
  border-bottom:1px solid #1a1d2e;margin-bottom:8px}}
.gm-h-email{{font-size:9px;font-weight:600;color:#3a3e52;flex:1;
  text-transform:uppercase;letter-spacing:.5px}}
.gm-h-col{{font-size:9px;font-weight:600;color:#3a3e52;width:48px;
  text-align:center;text-transform:uppercase;letter-spacing:.5px}}
.gm-row{{display:flex;align-items:center;gap:8px;margin-bottom:5px}}
.gm-email{{font-family:'JetBrains Mono',monospace;font-size:10px;
  color:#6b7084;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.gm-dot{{display:inline-block;width:48px;text-align:center;font-family:'JetBrains Mono',monospace;
  font-size:10px;border-radius:3px;padding:1px 4px;flex-shrink:0}}
.gm-dot.gm-ok{{color:#22c55e;background:rgba(34,197,94,.1)}}
.gm-dot.gm-ok::before{{content:'';display:inline-block;width:6px;height:6px;
  background:#22c55e;border-radius:50%;box-shadow:0 0 4px #22c55e}}
.gm-dot.gm-cd{{color:#f59e0b;background:rgba(245,158,11,.1)}}
.gm-dot.gm-off{{color:#ef4444;background:rgba(239,68,68,.08)}}
.gm-dot.gm-off::before{{content:'';display:inline-block;width:6px;height:6px;
  background:#ef4444;border-radius:50%;opacity:.5}}
.gm-q-acct{{margin-bottom:6px}}
.gm-q-name{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#6b7084;
  font-weight:500}}
.gm-q-err{{font-family:'JetBrains Mono',monospace;font-size:10px;color:#ef4444;margin-left:6px}}
.gm-q-row{{display:flex;align-items:center;gap:6px;margin-bottom:3px;padding-left:8px}}
.gm-q-model{{font-family:'JetBrains Mono',monospace;font-size:9px;color:#5a5f76;
  width:130px;flex-shrink:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.gm-q-track{{flex:1;height:4px;background:#12141f;border-radius:2px;overflow:hidden}}
.gm-q-fill{{height:100%;border-radius:2px;transition:width .5s ease}}
.gm-q-pct{{font-family:'JetBrains Mono',monospace;font-size:9px;color:#8a8fa6;
  width:32px;text-align:right;flex-shrink:0}}
.tier-badge{{font-family:'JetBrains Mono',monospace;font-size:10px;
  padding:2px 8px;border-radius:4px;color:var(--tc);
  background:color-mix(in srgb,var(--tc) 12%,transparent);
  text-transform:uppercase;letter-spacing:.5px;font-weight:500}}
.usage-cell{{position:relative;min-width:80px}}
.usage-bar{{position:absolute;left:0;top:50%;transform:translateY(-50%);
  height:4px;background:linear-gradient(90deg,#3b82f6,#60a5fa);
  border-radius:2px;opacity:.3}}
.usage-num{{position:relative;z-index:1}}
.lic-key-cell{{font-size:10px;color:#3a3e52}}
.fade-in{{opacity:0;transform:translateY(8px);animation:fadeUp .5s ease forwards}}
@keyframes fadeUp{{to{{opacity:1;transform:translateY(0)}}}}
.d1{{animation-delay:.05s}}.d2{{animation-delay:.1s}}.d3{{animation-delay:.15s}}
.d4{{animation-delay:.2s}}.d5{{animation-delay:.25s}}.d6{{animation-delay:.3s}}
.d7{{animation-delay:.35s}}.d8{{animation-delay:.4s}}.d9{{animation-delay:.45s}}
@media(max-width:1100px){{
  .kpi-row{{grid-template-columns:repeat(3,1fr)}}
  .status-row{{grid-template-columns:repeat(3,1fr)}}
  .grid-main{{grid-template-columns:1fr}}
  .sidebar{{flex-direction:row;flex-wrap:wrap}}
  .sidebar .panel{{flex:1;min-width:250px}}
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="logo">
    <h1>KUKI</h1>
    <span class="sub">Mission Control</span>
    <div class="dot"></div>
  </div>
  <div class="controls">
    <a class="period-btn {"active" if period == 7 else ""}"
       href="#" onclick="nav(7);return false">7d</a>
    <a class="period-btn {"active" if period == 14 else ""}"
       href="#" onclick="nav(14);return false">14d</a>
    <a class="period-btn {"active" if period == 30 else ""}"
       href="#" onclick="nav(30);return false">30d</a>
    <a class="refresh-btn"
       href="#" onclick="nav({period});return false">Refresh</a>
  </div>
</header>

<div class="kpi-row">
  <div class="kpi fade-in d1" style="--accent:#3b82f6">
    <div class="kpi-val" data-count="{total_requests}">{total_requests}</div>
    <div class="kpi-label">Total Requests</div>
    <div class="kpi-sub neutral">{period}d period</div>
  </div>
  <div class="kpi fade-in d2" style="--accent:#a855f7">
    <div class="kpi-val" data-count="{total_sessions}">{total_sessions}</div>
    <div class="kpi-label">Unique Sessions</div>
  </div>
  <div class="kpi fade-in d3" style="--accent:#f59e0b">
    <div class="kpi-val">{avg_sec}s</div>
    <div class="kpi-label">Avg Response</div>
    <div class="kpi-sub neutral">{avg_ms} ms</div>
  </div>
  <div class="kpi fade-in d4" style="--accent:#22c55e">
    <div class="kpi-val">{success_rate_num}%</div>
    <div class="kpi-label">Tool Success</div>
    <div class="kpi-sub good">{tool_ok}/{tool_total} calls</div>
  </div>
  <div class="kpi fade-in d5" style="--accent:#ef4444">
    <div class="kpi-val">{error_rate_num}%</div>
    <div class="kpi-label">Error Rate</div>
    <div class="kpi-sub {"bad" if total_errors > 0 else "good"}">{total_errors} errors</div>
  </div>
</div>

<div class="status-row">
  <div class="kpi fade-in d3" style="--accent:#06b6d4">
    <div class="kpi-val"><span class="status-dot {"on" if active_ws > 0 else "off"}"></span>{active_ws}</div>
    <div class="kpi-label">Active Now</div>
    <div class="kpi-sub neutral">WebSocket sessions</div>
  </div>
  <div class="kpi fade-in d4" style="--accent:{"#22c55e" if bridge_connected else "#ef4444"}">
    <div class="kpi-val"><span class="status-dot {"on" if bridge_connected else "off"}"></span>{"Online" if bridge_connected else "Offline"}</div>
    <div class="kpi-label">Revit Bridge</div>
    <div class="kpi-sub {"good" if bridge_connected else "bad"}">{"Connected" if bridge_connected else "Disconnected"}</div>
  </div>
  <div class="kpi fade-in d5" style="--accent:{"#22c55e" if errors_today == 0 else "#ef4444"}">
    <div class="kpi-val">{errors_today}</div>
    <div class="kpi-label">Errors Today</div>
    <div class="kpi-sub {"good" if errors_today == 0 else "bad"}">{"All clear" if errors_today == 0 else "needs attention"}</div>
  </div>
</div>

<div class="grid-main">
  <div style="display:flex;flex-direction:column;gap:20px">
    <div class="panel fade-in d5">
      <div class="panel-title">Requests Over Time</div>
      {chart_svg}
    </div>
    <div class="panel fade-in d7">
      <div class="panel-title">Top Tools</div>
      {tool_bars_html}
    </div>
    <div class="panel fade-in d9">
      <div class="panel-title">Recent Errors</div>
      {err_list_html}
    </div>
  </div>
  <div class="sidebar">
    <div class="panel fade-in d6">
      <div class="panel-title">Categories</div>
      <div class="donut-wrap">
        <svg viewBox="0 0 120 120">
          {cat_segments_html}
          <text x="60" y="58" text-anchor="middle" fill="#fff"
            font-family="JetBrains Mono" font-size="16" font-weight="500">
            {cat_total if categories else 0}</text>
          <text x="60" y="72" text-anchor="middle" fill="#5a5f76"
            font-family="Outfit" font-size="8">total</text>
        </svg>
        <div>{cat_legend_html}</div>
      </div>
    </div>
    <div class="panel fade-in d7">
      <div class="panel-title">Licenses</div>
      <div class="lic-grid">
        <div class="lic-stat">
          <div class="val">{lic_total}</div><div class="lbl">Total</div>
        </div>
        <div class="lic-stat">
          <div class="val">{lic_active}</div><div class="lbl">Active</div>
        </div>
        <div class="lic-stat">
          <div class="val">{lic_devices}</div><div class="lbl">Devices</div>
        </div>
      </div>
    </div>
    {gemini_panel_html}
    <div class="panel fade-in d8">
      <div class="panel-title">Repairs</div>
      <div class="lic-grid" style="grid-template-columns:1fr 1fr">
        <div class="lic-stat">
          <div class="val">{repairs}</div><div class="lbl">Attempts</div>
        </div>
        <div class="lic-stat">
          <div class="val">{tool_fail}</div><div class="lbl">Tool Failures</div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="panel fade-in d9" style="margin-top:4px">
  <div class="panel-title">Licenses</div>
  <div style="overflow-x:auto">
  <table>
    <thead><tr>
      <th>Name</th><th>Tier</th><th>Devices</th>
      <th>Usage ({period}d)</th><th>Today</th><th>Key</th>
    </tr></thead>
    <tbody>{lic_table_rows}</tbody>
  </table>
  </div>
</div>

<div class="panel fade-in d9" style="margin-top:4px">
  <div class="panel-title">Daily Breakdown</div>
  <div style="overflow-x:auto">
  <table>
    <thead><tr>
      <th>Date</th><th>Requests</th><th>Sessions</th>
      <th>Tool Calls</th><th>Errors</th><th>Avg Response</th>
    </tr></thead>
    <tbody>{daily_rows if daily_rows else '<tr><td colspan="6" class="empty-note">No daily data</td></tr>'}</tbody>
  </table>
  </div>
</div>
</div>

<script>
function nav(days){{
  var p=new URLSearchParams(location.search);
  p.set('days',days);
  location.search=p.toString();
}}
document.addEventListener('DOMContentLoaded',function(){{
  document.querySelectorAll('[data-count]').forEach(function(el){{
    var target=parseInt(el.getAttribute('data-count'),10);
    if(target<2)return;
    var duration=600,start=0,step=Math.max(1,Math.floor(target/40));
    var iv=setInterval(function(){{
      start+=step;if(start>=target){{start=target;clearInterval(iv)}}
      el.textContent=start.toLocaleString();
    }},duration/40);
  }});
}});
</script>
</body>
</html>"""


# ─── Phase 1 (revit-coder pilot) — uptime stats endpoint ───
# Reports Kaggle Router uptime aggregates from kaggle_uptime.jsonl.
# See docs/superpowers/specs/2026-05-01-revit-coder-integration-design.md

@router.get("/kaggle_uptime")
async def kaggle_uptime(
    _: str = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Return uptime aggregates for revit-coder Kaggle Router.

    Returns enabled=False if USE_REVIT_CODER=0 (uptime monitor doesn't run).
    """
    from kukai.config import USE_REVIT_CODER
    if not USE_REVIT_CODER:
        return {
            "enabled": False,
            "message": "USE_REVIT_CODER is not enabled — uptime monitor not running.",
        }

    from kukai.revit_coder.uptime_monitor import compute_uptime_stats
    stats = compute_uptime_stats()
    stats["enabled"] = True
    return stats
