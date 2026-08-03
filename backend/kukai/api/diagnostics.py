"""Diagnostics endpoints — crash reports from Bridge.

Goal: collect crash logs from users' Bridge installs automatically, with zero
end-user action required. The Bridge's BridgeLogger writes FATAL entries to
%LOCALAPPDATA%\\KUKI\\logs\\bridge-YYYYMMDD.log when it catches process-level
unhandled exceptions, WebView2 process failures, or AccessViolation crashes
from user-generated C# code. After the next Revit restart, the Bridge's
CrashUploader scans those files and posts the ones that haven't been uploaded
yet here.

We deliberately keep this endpoint:
  * Unauthenticated — Bridge has no service token at startup (the auth token
    is per-session and acquired AFTER the Bridge initializes). Crashes can
    happen before any chat session. The /api/update/check endpoint follows
    the same pattern.
  * Size-limited — 1 MB max payload per request. A normal crash log is
    1-50 KB; anything larger is suspect.
  * Rate-limited per IP — defence-in-depth against accidental log floods or
    abuse. The rate limit is intentionally generous because legitimate fleets
    may have many users restarting Revit at the same time after a buggy
    update goes out.
"""
from __future__ import annotations

import logging
import json
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from kukai.api.admin_remote import verify_admin_token
from kukai.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Hard limits — chosen so a single malicious or buggy client cannot fill the
# disk. A real fleet of 200 users restarting Revit after a buggy update would
# burst through these for a few seconds; the rate limiter forgives that.
_MAX_PAYLOAD_BYTES = 1_048_576  # 1 MB
_MAX_LOG_CONTENT_BYTES = 800_000  # leave headroom for JSON envelope + metadata
_RATE_LIMIT_PER_IP_PER_HOUR = 60  # plenty for legitimate auto-uploads

# Sliding-window rate limiter, in-memory. Process-local — restarting the
# backend resets the counters. Good enough for spam protection; if we ever
# need cross-instance accuracy we move to Redis.
_rate_buckets: dict[str, deque[float]] = defaultdict(deque)

# Sanitisation patterns. We intentionally accept stack traces and exception
# messages verbatim — those are the forensic value. But we strip a few classes
# of identifier that have no diagnostic value and would just bloat storage:
#   - Email addresses (could leak if user names a Revit file with one)
#   - Long hex blobs that look like API keys / tokens
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_LONG_HEX_RE = re.compile(r"\b[A-Fa-f0-9]{32,}\b")
_BEARER_RE = re.compile(r"(?i)(bearer|sk-|api[_-]?key[=: ]+)[A-Za-z0-9._-]+")


def _client_ip(request: Request) -> str:
    """Best-effort client IP from the nginx-overwritten header."""
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        # Fallback only. X-Forwarded-For's first value is client-controlled when
        # nginx uses $proxy_add_x_forwarded_for, so prefer X-Real-IP above.
        return fwd.split(",")[-1].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _check_rate_limit(ip: str) -> bool:
    """Sliding window: at most _RATE_LIMIT_PER_IP_PER_HOUR submissions per IP."""
    now = time.monotonic()
    cutoff = now - 3600.0
    bucket = _rate_buckets[ip]
    while bucket and bucket[0] < cutoff:
        bucket.popleft()
    if len(bucket) >= _RATE_LIMIT_PER_IP_PER_HOUR:
        return False
    bucket.append(now)
    return True


def _sanitise(text: str) -> str:
    """Strip identifiers with no forensic value but high privacy risk."""
    text = _EMAIL_RE.sub("<email>", text)
    text = _BEARER_RE.sub(r"\1<redacted>", text)
    text = _LONG_HEX_RE.sub("<hex>", text)
    return text


def _safe_segment(value: Any, default: str, max_len: int = 64) -> str:
    """Coerce an arbitrary string into a safe path segment."""
    if not isinstance(value, str) or not value:
        return default
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", value)[:max_len]
    return cleaned or default


def _crash_dir() -> Path:
    """Where crash reports land on disk. Created on first use."""
    settings = get_settings()
    base = Path(settings._get_data_base()) / "data" / "crash_reports"
    base.mkdir(parents=True, exist_ok=True)
    return base


@router.post("/api/diagnostics/crash")
async def submit_crash(request: Request) -> dict[str, Any]:
    """Receive a crash log file from a Bridge install.

    Expected JSON payload (all string fields optional except log_content):
        {
            "session_id":     "a1b2c3d4",            # 8-char Bridge session id
            "bridge_version": "1.0.0.0",
            "revit_version":  "2022",                # narrows by Revit major
            "machine_id":     "anon-hwid-hash",      # opaque, hashed in Bridge
            "log_filename":   "bridge-20260512.log", # for grouping repeats
            "log_content":    "...full log file..."  # plain text
        }

    Returns: {"ok": true, "stored_as": "<relative path>"}
    """
    ip = _client_ip(request)
    if not _check_rate_limit(ip):
        # 429 lets the Bridge know to back off without retrying forever.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded",
        )

    # Size check before parsing — defends against memory-bomb payloads.
    cl_header = request.headers.get("content-length")
    if cl_header and cl_header.isdigit() and int(cl_header) > _MAX_PAYLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"payload exceeds {_MAX_PAYLOAD_BYTES} bytes",
        )

    try:
        chunks: list[bytes] = []
        received = 0
        async for chunk in request.stream():
            received += len(chunk)
            if received > _MAX_PAYLOAD_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"payload exceeds {_MAX_PAYLOAD_BYTES} bytes",
                )
            chunks.append(chunk)
        payload = json.loads(b"".join(chunks))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid JSON",
        )

    log_content = payload.get("log_content") or ""
    if not isinstance(log_content, str) or not log_content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="log_content required",
        )

    # Truncate log content to keep storage bounded. The Bridge already caps
    # its own daily file size; this is defence-in-depth.
    if len(log_content) > _MAX_LOG_CONTENT_BYTES:
        log_content = (
            log_content[:_MAX_LOG_CONTENT_BYTES]
            + "\n... [truncated by server]"
        )

    log_content = _sanitise(log_content)

    # Quick triage: was there actually a FATAL/ERROR in here? Bridge already
    # filters this client-side, but a second check here keeps the dataset
    # tight.
    has_fatal = "[FATAL]" in log_content
    has_error = "[ERROR]" in log_content
    if not (has_fatal or has_error):
        # Accept but don't store — the client doesn't need to know we filtered.
        return {"ok": True, "stored_as": None, "filtered": "no_fatal_or_error"}

    revit_version = _safe_segment(payload.get("revit_version", ""), "unknown")
    machine_id = _safe_segment(payload.get("machine_id", ""), "anon")
    bridge_version = _safe_segment(payload.get("bridge_version", ""), "unknown")
    session_id = _safe_segment(payload.get("session_id", ""), "nosession", max_len=16)
    log_filename = _safe_segment(
        payload.get("log_filename", ""),
        f"bridge-{datetime.now(timezone.utc).strftime('%Y%m%d')}.log",
        max_len=64,
    )

    # On-disk layout:
    #   data/crash_reports/YYYY-MM-DD/revit_<ver>/<machine>__<session>__<file>
    # Lets us scan by date+version when investigating a fleet-wide regression.
    date_dir = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    target_dir = _crash_dir() / date_dir / f"revit_{revit_version}"
    target_dir.mkdir(parents=True, exist_ok=True)

    # Never let a replay/spoof overwrite an earlier forensic report.
    target_name = f"{machine_id}__{session_id}__{uuid.uuid4().hex[:12]}__{log_filename}"
    target_path = target_dir / target_name

    # Prepend a small header with the JSON metadata for context. The body is
    # the verbatim sanitised log so it loads cleanly in any text editor.
    header = (
        f"# KUKI crash report received {datetime.now(timezone.utc).isoformat()}\n"
        f"# bridge_version={bridge_version}\n"
        f"# revit_version={revit_version}\n"
        f"# session_id={session_id}\n"
        f"# machine_id={machine_id}\n"
        f"# client_ip={ip}\n"
        f"# has_fatal={has_fatal}\n"
        f"# log_filename={log_filename}\n"
        f"# ===== begin log =====\n"
    )
    try:
        target_path.write_text(header + log_content, encoding="utf-8")
    except OSError as e:
        logger.error("crash report write failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="storage failure",
        )

    # High-signal log line — easy to grep with `journalctl | grep CRASH_RPT`.
    logger.warning(
        "CRASH_RPT received: revit=%s bridge=%s sid=%s machine=%s fatal=%s size=%d",
        revit_version, bridge_version, session_id, machine_id,
        has_fatal, len(log_content),
    )

    rel = target_path.relative_to(_crash_dir().parent)
    return {"ok": True, "stored_as": str(rel)}


@router.get("/admin/diagnostics/report")
async def crash_report(
    limit: int = Query(50, ge=1, le=500),
    device: str = Query("", description="filter: machine_id substring"),
    _: None = Depends(verify_admin_token),
) -> dict[str, Any]:
    """Operator visibility into the runtime crash logs the fleet uploads.

    Walks data/crash_reports/<date>/revit_<ver>/<machine>__<session>__<file>,
    newest first, and returns metadata + the FATAL/last lines of each. This is
    the runtime counterpart to /admin/install/report (install-time) — together
    they tell the operator exactly why device X is broken. Runtime logs light up
    as the v1.3.0 fleet (which carries CrashUploader) rolls out."""
    base = _crash_dir()
    files: list[Path] = []
    try:
        files = [p for p in base.rglob("*") if p.is_file()]
    except Exception as e:  # noqa: BLE001
        logger.error("crash report scan failed: %s", e)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    reports: list[dict[str, Any]] = []
    for p in files:
        try:
            rel = p.relative_to(base)
            parts = rel.parts  # <date>/revit_<ver>/<machine>__<session>__<file>
            date = parts[0] if len(parts) > 0 else ""
            revit = parts[1].replace("revit_", "") if len(parts) > 1 else ""
            name = parts[-1]
            machine = name.split("__", 1)[0] if "__" in name else ""
            if device and device not in machine:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            fatal_lines = [ln for ln in text.splitlines() if "FATAL" in ln][:5]
            reports.append({
                "date": date,
                "revit_version": revit,
                "machine_id": machine,
                "file": str(rel),
                "size": p.stat().st_size,
                "mtime": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat(),
                "fatal": fatal_lines,
                "tail": text.splitlines()[-8:],
            })
        except Exception:  # noqa: BLE001 — one bad file must not sink the report
            continue
        if len(reports) >= limit:
            break
    return {"reports": reports, "total_files": len(files)}
