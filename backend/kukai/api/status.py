"""Status, hints, diagnostics, license, session, units, and file download endpoints.

These match the API contract expected by kukai_chat_v5.html.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from kukai import __version__
from kukai.api.dependencies import verify_device_token
from kukai.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Models ---

class StatusResponse(BaseModel):
    license_tier: str = "free"
    license_status: str = ""
    daily_usage: int = 0
    daily_limit: int = 0  # DISABLED: free trial period — unlimited
    revit_connected: bool = False
    revit_version: Optional[str] = None
    document_name: Optional[str] = None
    project_name: Optional[str] = None  # alias for HTML compatibility


class HintsResponse(BaseModel):
    hints: list[dict[str, str]]
    model_title: Optional[str] = None


class VersionResponse(BaseModel):
    current_version: str = __version__
    min_supported_version: str = "1.0.0"
    download_url: str = "https://revit-kukai.org/download"
    changelog: str = ""


class DiagnosticsResponse(BaseModel):
    backend_version: str = __version__
    bridge_connected: bool = False
    bridge_version: Optional[str] = None
    revit_version: Optional[str] = None
    document_name: Optional[str] = None
    database_ok: bool = True
    llm_model: str = ""
    sessions_count: int = 0


class LicenseActivateRequest(BaseModel):
    key: str
    device_id: str = ""
    hwid: str = ""


class LicenseActivateResponse(BaseModel):
    ok: bool
    plan: str = ""
    expires: str = ""
    device_token: str = ""
    detail: str = ""


# --- Endpoints ---

@router.get("/health")
async def health_check() -> dict[str, Any]:
    """Unauthenticated health check for monitoring (no auth required)."""
    from kukai.knowledge.mode import KnowledgeMode, knowledge_mode

    mode = knowledge_mode()
    payload: dict[str, Any] = {"status": "ok", "knowledge_mode": mode.value}
    # Turns in flight. Restarting on top of these is what actually broke users'
    # work: 424 close_code=1012 disconnects in the 2026-07-26/27 window, 36 of
    # them on the operator's device, every one an interrupted turn. Exposing the
    # count is what lets tools/safe_restart.py wait for a quiet moment instead of
    # relying on whoever is deploying to remember.
    try:
        from kukai.api.chat_ws import get_active_chat_count  # noqa: PLC0415

        payload["active_chats"] = get_active_chat_count()
    except Exception:  # noqa: BLE001 — a probe must answer even if this does not
        payload["active_chats"] = None
    if mode is KnowledgeMode.WIKI:
        # Startup already performed full verification; this is a cheap cached
        # provenance read suitable for frequent load-balancer probes.
        from kukai.rag.wiki_router import get_wiki_router

        metadata = get_wiki_router().metadata()
        metrics = metadata.get("metrics", {})
        payload.update({
            "knowledge_release": metadata.get("release_id"),
            "knowledge_manifest": metadata.get("manifest_sha256"),
            "knowledge_pages": metadata.get("runtime", {}).get("pages"),
            "knowledge_recipes": metadata.get("runtime", {}).get("recipe_cards"),
            "knowledge_verified_recipes": metrics.get("verified_cards"),
            "knowledge_staged_recipes": metrics.get("staged_cards"),
            "knowledge_extensions": metrics.get("extensions"),
            "knowledge_extension_entries": metrics.get("extension_entries"),
            "knowledge_api_versions": metrics.get("api_versions"),
        })
    return payload


# ─── Deep health check — admin-protected, runs real probes ───────────────
# Single endpoint that probes every external dependency we rely on:
# DB, WARP proxy, LLM primary, LLM fallback, OpenRouter, compile service and
# the immutable Wiki release. Each probe runs concurrently with its own timeout so a slow
# dependency doesn't stall the whole report.
#
# Returns one of:
#   "ok"        — all critical probes succeed
#   "degraded"  — some non-critical probes fail OR fallback worked
#   "failed"    — at least one critical probe is down (LLM unreachable, DB down)

# Mark "critical": if any of these fails, overall status = "failed".
# Non-critical probes can fail without flipping overall status.
_CRITICAL_PROBES = {"db", "llm_primary", "knowledge"}

# In-process cache — /health/deep result is reused for N seconds.
# Prevents accidental DoS-by-monitoring (e.g. a Grafana scrape every 10s
# would otherwise burn LLM tokens 8640× per day). Operators get fresh data
# by passing `?fresh=1`; routine monitoring hits the cache.
_HEALTH_CACHE: dict[str, Any] = {"result": None, "ts": 0.0}
_HEALTH_CACHE_TTL = 60.0  # seconds


async def _probe_db() -> dict[str, Any]:
    """Ping Postgres with `SELECT 1`. Returns ok if connection + query succeed."""
    from kukai.main import get_app_state
    t0 = time.monotonic()
    try:
        state = get_app_state()
        if not getattr(state, "db", None):
            return {"status": "skipped", "detail": "db not initialised"}
        # Database class wraps both PG and SQLite via execute_raw(sql, params).
        await state.db.execute_raw("SELECT 1")
        return {"status": "ok", "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception as e:
        return {
            "status": "failed",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
        }


async def _probe_warp() -> dict[str, Any]:
    """Verify SOCKS5 proxy at HTTPS_PROXY env var routes traffic to Google.

    Hits https://www.gstatic.com/generate_204 — Google's "is the network up"
    canary that returns 204 with empty body. Cheap, no auth, geo-blocked
    without WARP from RU/KZ — a 204 here proves the proxy is live AND
    routing through Cloudflare WARP egress (= unblocked).
    """
    import os
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return {"status": "skipped", "detail": "no HTTPS_PROXY in env"}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=8.0) as client:
            resp = await client.get("https://www.gstatic.com/generate_204")
        latency = int((time.monotonic() - t0) * 1000)
        if resp.status_code == 204:
            return {"status": "ok", "latency_ms": latency, "proxy": proxy}
        return {
            "status": "degraded",
            "latency_ms": latency,
            "detail": f"unexpected HTTP {resp.status_code}",
        }
    except Exception as e:
        return {
            "status": "failed",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
            "proxy": proxy,
        }


async def _probe_llm(model: str, api_key: str, label: str) -> dict[str, Any]:
    """Tiny LLM completion to verify model+auth+quota all alive.

    Uses 1-token max output to keep cost negligible. label distinguishes
    primary/fallback in the response.

    Timeout = 600s (10 min). Only flag "failed" on real outage, not when a
    thinking model legitimately spends 30s reasoning. Watchdog notifications
    should fire on prolonged hangs, not transient slowness — false positives
    train operators to ignore alerts.
    """
    import litellm
    t0 = time.monotonic()
    try:
        # metadata={"source": "health_probe"} lets analytics queries exclude
        # these synthetic calls from real user traffic counts. extra_body
        # is litellm's pass-through for vendor-specific fields.
        resp = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            api_key=api_key or None,
            max_tokens=4,  # micro-budget; thinking models will mostly use this on reasoning
            timeout=600.0,
            metadata={"source": "health_probe", "label": label},
        )
        latency = int((time.monotonic() - t0) * 1000)
        # Some thinking models return empty content but the call itself succeeded.
        # We treat any non-error response as ok for liveness purposes.
        return {
            "status": "ok",
            "latency_ms": latency,
            "model": model,
            "label": label,
        }
    except Exception as e:
        err = str(e)[:200]
        # Rate limits and quota errors mean the route is reachable but unusable —
        # surface separately so operators see "you ran out" not "it's broken".
        cls = type(e).__name__
        if "RateLimit" in cls or "RESOURCE_EXHAUSTED" in err or "429" in err:
            status = "exhausted"
        else:
            status = "failed"
        return {
            "status": status,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "model": model,
            "label": label,
            "detail": f"{cls}: {err}",
        }


async def _probe_compile_service() -> dict[str, Any]:
    """Roslyn compile service runs as separate process on port 52412."""
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://127.0.0.1:52412/health")
        latency = int((time.monotonic() - t0) * 1000)
        if 200 <= resp.status_code < 300:
            return {"status": "ok", "latency_ms": latency}
        return {
            "status": "degraded",
            "latency_ms": latency,
            "detail": f"HTTP {resp.status_code}",
        }
    except Exception as e:
        return {
            "status": "failed",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
        }


async def _probe_telemetry() -> dict[str, Any]:
    """Detect silent failures of the telemetry pipeline.

    Two classes of regression this catches:
      1. Writer broken — DB inserts silently fail; row count drops to zero.
         Real outage: 2026-05-02/03 weekend lost all assistant_msg rows.
      2. Tool-tracking broken — rows insert but tool_calls/tool_success/
         tool_failure stay empty. Real outage: the deindent regression that
         lived 30+ days (2026-04-09 .. 2026-05-11) before we caught it.

    Heuristic boundaries chosen from observed prod baseline:
      • 24h volume typically 100-200 rows on weekdays, 15-30 on weekends.
        Zero rows in 24h = writer broken (or backend down — caught elsewhere).
      • Of 24h rows, ~30-50% normally have tools populated. Zero with-tools
        when total > 50 means tool tracking is silently failing — return
        degraded so the watchdog alerts immediately rather than weeks later.
    """
    t0 = time.monotonic()
    try:
        from kukai.main import get_app_state
        state = get_app_state()
        if not state or not getattr(state, "db", None):
            return {
                "status": "failed",
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "detail": "app state / db not initialized",
            }

        row = await state.db.fetch_one(
            """
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE tool_calls IS NOT NULL AND tool_calls <> '')
                     AS with_tools
            FROM telemetry_requests
            WHERE timestamp::timestamp > NOW() - INTERVAL '24 hours'
            """
        )
        latency = int((time.monotonic() - t0) * 1000)

        total = int((row or {}).get("total", 0))
        with_tools = int((row or {}).get("with_tools", 0))

        if total == 0:
            return {
                "status": "failed",
                "latency_ms": latency,
                "detail": "0 telemetry rows in last 24h — writer likely broken",
                "total_24h": 0,
            }

        # >50 chats yet 0 of them recorded any tool = pipeline broken.
        # Threshold 50 picked so a genuinely quiet day (e.g. all general-Q&A
        # weekend) doesn't trip the alert.
        if total > 50 and with_tools == 0:
            return {
                "status": "degraded",
                "latency_ms": latency,
                "detail": f"{total} rows in 24h but 0 with tools — tool tracking broken",
                "total_24h": total,
                "with_tools_24h": 0,
            }

        return {
            "status": "ok",
            "latency_ms": latency,
            "total_24h": total,
            "with_tools_24h": with_tools,
            "tool_usage_pct": round(100.0 * with_tools / total, 1) if total else 0.0,
        }
    except Exception as e:
        return {
            "status": "failed",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
        }


def _retrieval_vitals() -> dict:
    """Compatibility field exposing the active local Wiki router only."""
    try:
        from kukai.rag.wiki_router import get_wiki_router

        metadata = get_wiki_router().metadata()
        return {
            "source": "wiki",
            "release_id": metadata.get("release_id"),
            "manifest_sha256": metadata.get("manifest_sha256"),
            "runtime": metadata.get("runtime"),
            "vector_retrieval": "retired",
            "embedding_requests": 0,
            "reranker": "retired",
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:120]}"}


def _knowledge_vitals() -> dict[str, Any]:
    """Re-hash the exact release and compare it with the prewarmed router."""
    t0 = time.monotonic()
    try:
        from kukai.knowledge.mode import KnowledgeMode, knowledge_mode

        mode = knowledge_mode()
        if mode is not KnowledgeMode.WIKI:
            return {
                "status": "failed",
                "mode": mode.value,
                "detail": "production Wiki mode is not active",
            }
        from kukai.knowledge.release import load_release
        from kukai.rag.wiki_router import get_wiki_router

        disk = load_release(verify=True)
        runtime = get_wiki_router().metadata()
        if (disk.release_id != runtime.get("release_id")
                or disk.manifest_sha256 != runtime.get("manifest_sha256")):
            return {
                "status": "failed",
                "mode": mode.value,
                "detail": "disk pointer differs from the prewarmed runtime release",
                "disk_release": disk.release_id,
                "runtime_release": runtime.get("release_id"),
            }
        return {
            "status": "ok",
            "mode": mode.value,
            "latency_ms": int((time.monotonic() - t0) * 1000),
            **runtime,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "latency_ms": int((time.monotonic() - t0) * 1000),
            "detail": f"{type(exc).__name__}: {str(exc)[:240]}",
        }


@router.get("/health/deep")
async def health_deep(
    fresh: bool = False,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
) -> dict[str, Any]:
    """Comprehensive health probe — runs real network calls to every dependency.

    Admin-token protected because: (a) it costs micro-amounts of LLM money,
    (b) detailed error messages may leak infra info to attackers.

    Result is cached for 60s (see _HEALTH_CACHE_TTL). Pass `?fresh=1` to
    force a re-probe — useful when actively diagnosing an outage. Routine
    monitoring should NOT pass fresh=1; it defeats the cache and burns
    tokens on every scrape.
    """
    import asyncio

    settings = get_settings()
    if not settings.admin_token:
        raise HTTPException(503, "Admin API not configured")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(401, "Invalid admin token")

    # Serve from cache when fresh data isn't required.
    now = time.monotonic()
    if not fresh and _HEALTH_CACHE["result"] is not None:
        age = now - _HEALTH_CACHE["ts"]
        if age < _HEALTH_CACHE_TTL:
            cached = dict(_HEALTH_CACHE["result"])
            cached["cached"] = True
            cached["cache_age_s"] = round(age, 1)
            return cached

    probes_started = time.monotonic()

    # Build the probe set — primary always, fallback only if configured.
    # `telemetry` runs always but is NOT in _CRITICAL_PROBES — a broken
    # observability pipeline shouldn't return failed at top level (real
    # users are still served fine), just degraded so the watchdog notices.
    probe_coros: dict[str, Any] = {
        "db": _probe_db(),
        "warp_proxy": _probe_warp(),
        "compile_service": _probe_compile_service(),
        "telemetry": _probe_telemetry(),
        "llm_primary": _probe_llm(
            settings.llm_model, settings.llm_api_key, "primary"
        ),
    }
    if settings.llm_fallback_model:
        probe_coros["llm_fallback"] = _probe_llm(
            settings.llm_fallback_model,
            settings.llm_fallback_api_key or settings.llm_api_key,
            "fallback",
        )
    # Last-resort probe — historically configured via `llm_last_resort_model`
    # but that field was removed from Settings (Anthropic last-resort retired
    # per ADR; OpenRouter DeepSeek serves as the emergency fallback now). Use
    # getattr so future field churn doesn't crash /health/deep again.
    if getattr(settings, "llm_last_resort_model", None):
        # Tracked as info only — LLMClient handles the wiring internally.
        pass

    # Run all in parallel — cap total wait at 620s. Must be > _probe_llm's
    # 600s + buffer for other probes to complete. Real outages are detected
    # at the per-probe level; this global cap is a last-line safety so a stuck
    # probe doesn't block forever.
    results: dict[str, Any] = {}
    try:
        completed = await asyncio.wait_for(
            asyncio.gather(*probe_coros.values(), return_exceptions=True),
            timeout=620.0,
        )
        for name, res in zip(probe_coros.keys(), completed):
            if isinstance(res, Exception):
                results[name] = {
                    "status": "failed",
                    "detail": f"{type(res).__name__}: {str(res)[:200]}",
                }
            else:
                results[name] = res
    except asyncio.TimeoutError:
        for name in probe_coros.keys():
            results.setdefault(name, {"status": "failed", "detail": "global 620s timeout"})

    # Local, deterministic integrity probe. Run after network probes so it
    # cannot delay their start and include it in the critical roll-up.
    results["knowledge"] = _knowledge_vitals()

    # Roll up overall status. Critical = must be ok. Anything else = degrade.
    failed_critical = [
        name for name in _CRITICAL_PROBES
        if results.get(name, {}).get("status") not in ("ok",)
    ]
    failed_any = [
        name for name, r in results.items() if r.get("status") not in ("ok",)
    ]

    if failed_critical:
        overall = "failed"
    elif failed_any:
        overall = "degraded"
    else:
        overall = "ok"

    payload = {
        "status": overall,
        "total_latency_ms": int((time.monotonic() - probes_started) * 1000),
        "probes": results,
        "failed_critical": failed_critical,
        "failed_any": failed_any,
        "config": {
            "primary_model": settings.llm_model,
            "fallback_model": settings.llm_fallback_model,
            "last_resort_model": getattr(settings, "llm_last_resort_model", None),
            "knowledge_mode": results["knowledge"].get("mode"),
        },
        "retrieval_vitals": _retrieval_vitals(),
        "cached": False,
    }

    # Persist to cache so the next scrape (within TTL) returns instantly
    # without burning another LLM token.
    _HEALTH_CACHE["result"] = payload
    _HEALTH_CACHE["ts"] = now

    return payload


_ngrok_cache: dict = {"url": None, "ts": 0}


@router.get("/health/tunnels")
async def tunnel_info() -> dict:
    """Return primary and fallback (ngrok) tunnel URLs. Unauthenticated."""
    settings = get_settings()
    primary = getattr(settings, 'public_url', 'https://revit-kukai.org')

    # Cache ngrok URL for 30 seconds
    now = time.time()
    if now - _ngrok_cache["ts"] < 30 and _ngrok_cache["url"] is not None:
        return {"primary": primary, "fallback": _ngrok_cache["url"]}

    fallback = None
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://localhost:4040/api/tunnels")
            data = resp.json()
            tunnels = data.get("tunnels", [])
            for t in tunnels:
                if t.get("proto") == "https":
                    fallback = t.get("public_url")
                    break
            if not fallback and tunnels:
                fallback = tunnels[0].get("public_url")
    except Exception:
        pass

    _ngrok_cache["url"] = fallback
    _ngrok_cache["ts"] = now
    return {"primary": primary, "fallback": fallback}


# --- Auto-update (hash-based, per-Revit-version) ---
#
# Layout on disk:
#   data/updates/2021/latest.zip   + latest.sha256   (sha of KukaiRevitBridge.dll inside)
#   data/updates/2022/...
#   ...
#   data/updates/2026/...
#
# Each ZIP contains the Bridge DLL for that specific Revit version (different
# .NET runtimes: net48 for 2021-2024, net8 for 2025-2026). Mixing them across
# versions BREAKS the install, so per-version separation is mandatory.
#
# Old clients that don't send revit_version receive update_available=False
# (safe default — we won't risk shipping the wrong-runtime DLL). They need ONE
# manual reinstall to pick up the version-aware UpdateChecker; after that,
# updates flow automatically.

_UPDATE_DIR: Path | None = None
_SUPPORTED_REVIT_VERSIONS = frozenset({"2021", "2022", "2023", "2024", "2025", "2026"})


def _get_update_dir() -> Path:
    """Return the root directory where per-version update ZIPs are stored."""
    global _UPDATE_DIR
    if _UPDATE_DIR is None:
        settings = get_settings()
        _UPDATE_DIR = Path(settings._get_data_base()) / "data" / "updates"
        _UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    return _UPDATE_DIR


# --- P3: hash->version routing for the legacy fleet (RELEASING.md "server patch P3") ---
#
# The 2026-04/05 ad-hoc builds poll /api/update/check?hash=<sha256> WITHOUT
# revit_version, so they can never match a per-version channel on their own.
# data/known_builds.json maps those field hashes (from release provenance +
# git-blob forensics) to their Revit version:
#
#   { "<sha256-of-KukaiRevitBridge.dll>": {"revit_version": "2023", "ota_safe": true}, ... }
#
# GATED OFF by default (KUKAI_LEGACY_HASH_ROUTING=1 enables): the 2026-07 rollout
# is consent-based — users choose KUKI_Update.ps1 or the installer exe. This
# routing exists for the straggler wave the operator flips on deliberately.
# Unknown hashes and ota_safe=false entries keep the old safe default (False).

def _legacy_route_version(client_hash: str) -> str | None:
    if os.environ.get("KUKAI_LEGACY_HASH_ROUTING", "") != "1":
        return None
    if not client_hash:
        return None
    try:
        kb_file = Path(get_settings()._get_data_base()) / "data" / "known_builds.json"
        entry = json.loads(kb_file.read_text(encoding="utf-8")).get(client_hash.lower())
    except Exception:
        return None
    if not entry or entry.get("ota_safe") is not True:
        return None
    ver = str(entry.get("revit_version", ""))
    return ver if ver in _SUPPORTED_REVIT_VERSIONS else None


def _beta_ring_devices() -> set[str]:
    """Update rings (2026-07-16): data/updates/rings.json lists device ids that
    receive the beta channel. Test builds reach ONLY these devices; the fleet
    keeps serving latest.zip. Any error fails open to the stable channel."""
    try:
        import json as _json

        rings_file = _get_update_dir() / "rings.json"
        if not rings_file.exists():
            return set()
        data = _json.loads(rings_file.read_text(encoding="utf-8"))
        return {str(d).strip().lower() for d in data.get("beta_devices", []) if d}
    except Exception:
        return set()


# Banner gate (2026-07-19): a device that polls /api/update/check has a working
# UpdateChecker -> it auto-updates, so the manual reinstall migration banner must
# NOT show for it. Devices that never poll (old builds, no checker) still get it.
#
# 2026-07-26: persisted to disk with a 30d TTL. It used to be in-memory with a 1h
# TTL, so every backend restart re-nagged the already-migrated part of the fleet
# until each device polled again — and a migrated client stays migrated, an hour is
# not the right horizon. Disk state is best-effort: any IO error falls back to the
# in-memory view (i.e. fail-open to showing the banner), never to a 500.
_UPDATE_CAPABLE_DEVICES: dict[str, float] = {}
_UPDATE_CAPABLE_TTL = 30 * 86400.0
_UPDATE_CAPABLE_LOADED = False


def _capable_file() -> Path:
    return Path(get_settings()._get_data_base()) / "data" / "update_capable_devices.json"


def _capable_load() -> None:
    """Load persisted capability marks once per process."""
    global _UPDATE_CAPABLE_LOADED
    if _UPDATE_CAPABLE_LOADED:
        return
    _UPDATE_CAPABLE_LOADED = True
    try:
        data = json.loads(_capable_file().read_text(encoding="utf-8"))
        for dev, ts in data.items():
            if isinstance(dev, str) and isinstance(ts, (int, float)):
                _UPDATE_CAPABLE_DEVICES.setdefault(dev.strip(), float(ts))
    except FileNotFoundError:
        pass
    except Exception as exc:  # corrupt file must not break the endpoint
        logger.warning("update-capable state unreadable: %s", exc)


def _capable_mark(dev: str) -> None:
    """Record that this device has a working UpdateChecker. Writes are throttled:
    only a new device or a mark older than an hour touches the disk."""
    _capable_load()
    now = time.time()
    prev = _UPDATE_CAPABLE_DEVICES.get(dev)
    _UPDATE_CAPABLE_DEVICES[dev] = now
    if prev is not None and (now - prev) < 3600.0:
        return
    try:
        path = _capable_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        fresh = {
            d: ts for d, ts in _UPDATE_CAPABLE_DEVICES.items()
            if (now - ts) < _UPDATE_CAPABLE_TTL
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(fresh), encoding="utf-8")
        os.replace(tmp, path)
    except Exception as exc:
        logger.warning("update-capable state not persisted: %s", exc)


@router.get("/api/banner/update-needed")
async def banner_update_needed(device_id: str = Query("")) -> dict:
    """Return {show: bool} for the migration banner. Fail-open to show."""
    dev = device_id.strip()
    if not dev:
        return {"show": True}
    _capable_load()
    ts = _UPDATE_CAPABLE_DEVICES.get(dev)
    capable = ts is not None and (time.time() - ts) < _UPDATE_CAPABLE_TTL
    return {"show": not capable}


@router.get("/api/update/check")
async def check_update(
    hash: str = Query(""),
    revit_version: str = Query(""),
    device_id: str = Query(""),
) -> dict:
    """Check if a client update is available.

    Client sends:
      - hash: SHA256 of its current KukaiRevitBridge.dll
      - revit_version: "2021".."2026" — the Revit major version the Bridge
        is running under (required for routing to the right DLL).

    Server compares the client's DLL hash against the per-version target.
    """
    if device_id.strip():
        _capable_mark(device_id.strip())
    if revit_version not in _SUPPORTED_REVIT_VERSIONS:
        # Old client (no version param) OR unknown version: try P3 hash-routing
        # (gated, known ota_safe builds only), else the old safe default.
        routed = _legacy_route_version(hash)
        if routed is None:
            return {"update_available": False}
        revit_version = routed

    # Ring routing: a beta device with staged beta artifacts gets the beta
    # channel; everyone else (and any error) gets stable, exactly as before.
    channel = ""
    update_dir = _get_update_dir() / revit_version
    if device_id.strip().lower() in _beta_ring_devices():
        beta_dir = update_dir / "beta"
        if (beta_dir / "latest.sha256").exists() and (beta_dir / "latest.zip").exists():
            channel = "beta"
            update_dir = beta_dir
    hash_file = update_dir / "latest.sha256"
    zip_file = update_dir / "latest.zip"

    if not hash_file.exists() or not zip_file.exists():
        return {"update_available": False}

    server_hash = hash_file.read_text(encoding="utf-8").strip().lower()
    client_hash = hash.strip().lower()

    if not client_hash or client_hash == server_hash:
        return {"update_available": False}

    _chan_q = f"&channel={channel}" if channel else ""
    resp = {
        "update_available": True,
        "channel": channel or "stable",
        "download_url": f"/api/update/download?revit_version={revit_version}{_chan_q}",
        "size": zip_file.stat().st_size,
    }
    # Signed-update support (closes the unsigned-ZIP RCE). When a detached signature
    # exists, advertise it; the client MUST download it and verify against a PINNED
    # public key before swapping. public_key here is for reference/bootstrap only —
    # a secure client embeds (pins) the key, it does NOT trust this field.
    if (update_dir / "latest.zip.sig").exists():
        resp["signature_url"] = f"/api/update/signature?revit_version={revit_version}{_chan_q}"
        try:
            from kukai.security.update_signing import public_key_b64
            _pk = public_key_b64()
            if _pk:
                resp["public_key"] = _pk
        except Exception:
            pass
    return resp


@router.get("/api/update/signature")
async def download_signature(revit_version: str = Query(""), channel: str = Query("")):
    """Detached Ed25519 signature of latest.zip. The C# KukaiLoader MUST verify it
    against a PINNED public key BEFORE extracting/swapping the DLL — otherwise the
    unsigned-update RCE remains open."""
    if revit_version not in _SUPPORTED_REVIT_VERSIONS:
        raise HTTPException(status_code=400, detail="revit_version query param required (e.g., 2024)")
    if channel not in ("", "beta"):
        raise HTTPException(status_code=400, detail="unknown channel")
    _sub = ("beta",) if channel == "beta" else ()
    sig_file = _get_update_dir().joinpath(revit_version, *_sub) / "latest.zip.sig"
    if not sig_file.exists():
        raise HTTPException(status_code=404, detail="No signature available")
    return FileResponse(
        path=str(sig_file),
        filename=f"kuki_update_{revit_version}.zip.sig",
        media_type="text/plain",
    )


@router.get("/api/update/download")
async def download_update(revit_version: str = Query(""), channel: str = Query("")):
    """Download the latest client update ZIP for a specific Revit version."""
    if revit_version not in _SUPPORTED_REVIT_VERSIONS:
        raise HTTPException(
            status_code=400,
            detail="revit_version query param required (e.g., 2024)",
        )
    if channel not in ("", "beta"):
        raise HTTPException(status_code=400, detail="unknown channel")

    _sub = ("beta",) if channel == "beta" else ()
    update_dir = _get_update_dir().joinpath(revit_version, *_sub)
    zip_file = update_dir / "latest.zip"

    if not zip_file.exists():
        raise HTTPException(status_code=404, detail="No update available")

    return FileResponse(
        path=str(zip_file),
        filename=f"kuki_update_{revit_version}.zip",
        media_type="application/zip",
    )


@router.get("/api/version", response_model=VersionResponse)
async def get_version() -> VersionResponse:
    """Return current server version info for auto-update checks.

    Reads from data/version.json if it exists, otherwise returns defaults.
    This allows updating version info without redeploying the backend.
    """
    settings = get_settings()
    version_file = Path(settings._get_data_base()) / "data" / "version.json"

    if version_file.exists():
        try:
            import json
            data = json.loads(version_file.read_text(encoding="utf-8"))
            return VersionResponse(
                current_version=data.get("current_version", __version__),
                min_supported_version=data.get("min_supported_version", "1.0.0"),
                download_url=data.get("download_url", "https://revit-kukai.org/download"),
                changelog=data.get("changelog", ""),
            )
        except Exception:
            pass

    return VersionResponse()


@router.get("/status", response_model=StatusResponse)
async def get_status(
    auth: dict[str, Any] = Depends(verify_device_token),
) -> StatusResponse:
    """Return server status — license, usage, bridge connection."""
    from kukai.main import get_app_state

    state = get_app_state()
    settings = get_settings()

    # Get tier and limit from auth info
    tier = auth.get("tier", "free")

    # Determine window-based limits for the tier
    from kukai.licensing.license_manager import TIER_LIMITS
    tier_config = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
    window_limit = tier_config.get("window_limit", 0)
    window_hours = tier_config.get("window_hours", 0)

    # Use window_limit for display (0 = unlimited)
    daily_limit = window_limit

    # Get window usage
    daily_usage = 0
    device_token = auth.get("device_token", "")
    if device_token and state.license_manager and window_hours > 0:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
        raw_db = state.license_manager._db
        cursor = await raw_db.execute(
            "SELECT COUNT(*) FROM request_log WHERE device_token = ? AND created_at >= ?",
            (device_token, cutoff),
        )
        row = await cursor.fetchone()
        daily_usage = row[0] if row else 0

    revit_connected = state.bridge.connected
    revit_version = None
    document_name = None

    if state.bridge.last_ping:
        revit_version = state.bridge.last_ping.revit_version
        document_name = state.bridge.last_ping.document_name

    return StatusResponse(
        license_tier=tier,
        daily_usage=daily_usage,
        daily_limit=daily_limit,
        revit_connected=revit_connected,
        revit_version=revit_version,
        document_name=document_name,
        project_name=document_name,
    )


@router.get("/hints", response_model=HintsResponse)
async def get_hints(
    session_id: str = Query(""),
    auth: dict[str, Any] = Depends(verify_device_token),
) -> HintsResponse:
    """Return contextual hint suggestions for the chat UI."""
    from kukai.main import get_app_state

    state = get_app_state()

    if state.bridge.connected and state.bridge.last_ping:
        doc = state.bridge.last_ping.document_name
        model_title = doc or "Revit"
        # Connected to Revit — actionable model hints
        hints = [
            {"text": "Сколько элементов в модели?", "icon": "search"},
            {"text": "Покажи все уровни", "icon": "home"},
            {"text": "Проверь модель на ошибки", "icon": "tool"},
            {"text": "Выдели все стены", "icon": "box"},
            {"text": "Посчитай помещения", "icon": "search"},
            {"text": "Создай спецификацию стен", "icon": "tool"},
        ]
    else:
        model_title = "KUKI"
        # Not connected — help-oriented hints
        hints = [
            {"text": "Что ты умеешь?", "icon": "help"},
            {"text": "Изолируй монолит", "icon": "info"},
            {"text": "Сделай и открой спецификацию стен для ВОР и выгрузи ее в эксель", "icon": "file"},
        ]

    return HintsResponse(hints=hints, model_title=model_title)


@router.put("/units/{unit}")
async def set_units(
    unit: str,
    auth: dict[str, Any] = Depends(verify_device_token),
) -> dict[str, str]:
    """Set the unit system (metric/imperial)."""
    if unit not in ("metric", "imperial"):
        raise HTTPException(status_code=400, detail="Единицы измерения: 'metric' или 'imperial'")
    # Units are stored client-side in preferences and sent with each request.
    # This endpoint just acknowledges the change.
    return {"units": unit, "status": "ok"}


@router.post("/session/clear")
async def clear_session(
    auth: dict[str, Any] = Depends(verify_device_token),
    session_id: str = Query(""),
) -> dict[str, str]:
    """Clear chat history for a session (with ownership check)."""
    from kukai.main import get_app_state

    state = get_app_state()
    if session_id:
        # Verify the requesting device owns this session.
        # Step 11: identity-aware gate — flag OFF (and for all legacy-owned
        # sessions) this is the EXACT legacy truth table; for sessions owned
        # by a server-minted signed identity ("kid_…") only a verified
        # identity token can match (closes the empty-requester bypass).
        requesting_device = auth.get("device_id", "")
        session = await state.db.get_or_create_session(session_id)
        from kukai.security.identity import owner_access_ok
        if not owner_access_ok(session.device_id, requesting_device):
            raise HTTPException(status_code=403, detail="Session belongs to another device")
        await state.db.clear_session(session_id)
    return {"status": "ok"}


@router.get("/chat/export")
async def export_chat(
    session_id: str = Query(...),
    auth: dict[str, Any] = Depends(verify_device_token),
) -> dict[str, Any]:
    """Export chat session as JSON for saving/sharing."""
    from kukai.main import get_app_state

    state = get_app_state()

    messages = await state.db.get_session_messages(session_id, limit=10000)
    session = await state.db.get_or_create_session(session_id)

    # Verify device owns this session.
    # Step 11: identity-aware gate (see /session/clear) — legacy sessions keep
    # the exact legacy semantics; "kid_…"-owned exports require a verified token.
    requesting_device = auth.get("device_id", "")
    from kukai.security.identity import owner_access_ok
    if not owner_access_ok(session.device_id, requesting_device):
        raise HTTPException(status_code=403, detail="Нет доступа к этой сессии")

    return {
        "session_id": session_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "device_id": session.device_id,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.get("/diagnostics", response_model=DiagnosticsResponse)
async def get_diagnostics(
    session_id: str = Query(""),
    auth: dict[str, Any] = Depends(verify_device_token),
) -> DiagnosticsResponse:
    """Return diagnostic information for troubleshooting."""
    from kukai.main import get_app_state

    state = get_app_state()
    settings = get_settings()

    bridge_version = None
    revit_version = None
    document_name = None
    if state.bridge.last_ping:
        bridge_version = state.bridge.last_ping.bridge_version
        revit_version = state.bridge.last_ping.revit_version
        document_name = state.bridge.last_ping.document_name

    return DiagnosticsResponse(
        backend_version=__version__,
        bridge_connected=state.bridge.connected,
        bridge_version=bridge_version,
        revit_version=revit_version,
        document_name=document_name,
        database_ok=True,
        llm_model=settings.llm_model,
    )


@router.get("/files/{file_id}")
async def download_file(
    file_id: str,
    session_id: str = Query(""),
    auth: dict[str, Any] = Depends(verify_device_token),
) -> FileResponse:
    """Download a generated file."""
    import re

    settings = get_settings()
    files_dir = settings.get_files_dir()

    # Validate file_id — must be alphanumeric with optional hyphens, no glob/path characters
    if not re.match(r'^[a-zA-Z0-9\-]{1,36}$', file_id):
        raise HTTPException(status_code=400, detail="Некорректный идентификатор файла")

    # Find file by ID (files are stored as {file_id}_{filename})
    matching = list(files_dir.glob(f"{file_id}_*"))
    if not matching:
        raise HTTPException(status_code=404, detail="Файл не найден")

    file_path = matching[0].resolve()
    # Ensure the file is inside files_dir (prevent path traversal)
    if not str(file_path).startswith(str(files_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    filename = file_path.name.split("_", 1)[1] if "_" in file_path.name else file_path.name
    return FileResponse(path=file_path, filename=filename)


@router.post("/license/activate", response_model=LicenseActivateResponse)
async def activate_license(
    request: LicenseActivateRequest,
) -> LicenseActivateResponse:
    """Activate a license key and get a device token.

    This endpoint does NOT require auth — it IS the auth entry point.
    The client sends a license key + device info and receives a device token.
    """
    from kukai.main import get_app_state

    key = request.key.strip()

    # Basic format validation: KUKAI-XXXX-XXXX-XXXX-XXXX
    if not key.startswith("KUKAI-") or len(key.split("-")) != 5:
        return LicenseActivateResponse(
            ok=False,
            detail="Неверный формат ключа. Ожидается: KUKAI-XXXX-XXXX-XXXX-XXXX",
        )

    # Check all parts are 4 alphanumeric chars
    parts = key.split("-")
    for part in parts[1:]:
        if len(part) != 4:
            return LicenseActivateResponse(
                ok=False,
                detail="Каждая группа должна содержать ровно 4 символа",
            )

    state = get_app_state()
    settings = get_settings()

    # If auth is disabled (local mode), accept any correctly-formatted key
    if not settings.auth_enabled or not state.license_manager:
        return LicenseActivateResponse(
            ok=True,
            plan="Pro",
            expires="2027-12-31",
            detail="Local mode — auth not enforced",
        )

    # Real license activation
    device_id = request.device_id or f"device-{uuid.uuid4().hex[:8]}"
    hwid = request.hwid or ""

    from kukai.licensing.license_manager import (
        DeviceLimitError,
        HwidConflictError,
        LicenseExpiredError,
        LicenseInactiveError,
        LicenseNotFoundError,
    )

    try:
        result = await state.license_manager.activate_license(
            key=key,
            device_id=device_id,
            hwid=hwid,
        )
    except LicenseNotFoundError:
        return LicenseActivateResponse(
            ok=False,
            detail="Ключ лицензии не найден. Проверьте ключ и попробуйте снова.",
        )
    except LicenseExpiredError:
        return LicenseActivateResponse(
            ok=False,
            detail="Срок лицензии истёк. Обратитесь в поддержку для продления.",
        )
    except LicenseInactiveError:
        return LicenseActivateResponse(
            ok=False,
            detail="Лицензия деактивирована. Обратитесь в поддержку.",
        )
    except HwidConflictError:
        return LicenseActivateResponse(
            ok=False,
            detail="Это устройство уже зарегистрировано с другой учётной записью. Используйте существующий ключ лицензии.",
        )
    except DeviceLimitError as e:
        return LicenseActivateResponse(
            ok=False,
            detail=str(e),
        )

    return LicenseActivateResponse(
        ok=True,
        plan=result["tier"],
        expires=result["expires_at"],
        device_token=result["device_token"],
    )


# ─── Multi-Agent telemetry — admin-only (Phase 8.3) ──────────────────────
@router.get("/admin/agent-stats")
async def agent_stats(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
):
    """Per-agent telemetry summary as JSON.

    Token is checked against ``KUKAI_ADMIN_TOKEN`` env var. Reads the
    telemetry JSONL file pointed to by ``KUKAI_AGENT_TELEMETRY_PATH``
    (default ``backend/data/agent_telemetry.jsonl``).

    NOTE: token is passed via X-Admin-Token header (NOT query param) to
    keep secrets out of nginx access logs.
    """
    import json as _json
    import os as _os
    import statistics as _stats
    from collections import defaultdict as _dd

    expected = _os.environ.get("KUKAI_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(503, detail="admin token not configured")
    if not x_admin_token or not hmac.compare_digest(x_admin_token, expected):
        raise HTTPException(403, detail="bad admin token")

    path = Path(_os.environ.get(
        "KUKAI_AGENT_TELEMETRY_PATH",
        "backend/data/agent_telemetry.jsonl",
    ))
    if not path.exists():
        return {"agents": {}, "total": 0,
                "telemetry_path": str(path), "note": "no log yet"}

    by_agent: dict[str, list[dict]] = _dd(list)
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            by_agent[rec.get("agent", "?")].append(rec)

    agents_summary: dict[str, dict[str, Any]] = {}
    for agent, records in by_agent.items():
        latencies = sorted(r.get("latency_ms", 0.0) for r in records)
        agents_summary[agent] = {
            "count": len(records),
            "p50_ms": (_stats.median(latencies) if latencies else 0.0),
            "p95_ms": (latencies[int(len(latencies) * 0.95)] if latencies else 0.0),
            "avg_tokens_in": (
                _stats.mean(r.get("tokens_in", 0) for r in records)
                if records else 0
            ),
            "avg_tokens_out": (
                _stats.mean(r.get("tokens_out", 0) for r in records)
                if records else 0
            ),
            "fallback_pct": (
                100.0 * sum(1 for r in records if r.get("fallback_used")) / len(records)
                if records else 0
            ),
        }
    return {
        "agents": agents_summary,
        "total": sum(len(r) for r in by_agent.values()),
        "telemetry_path": str(path),
    }
