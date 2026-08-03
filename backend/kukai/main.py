"""FastAPI application — entry point for the KUKI backend."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from kukai import __version__
from kukai.bridge.client import BridgeClient
from kukai.compile_client import CompileClient
from kukai.config import Settings, get_settings
from kukai.licensing.license_manager import LicenseManager
from kukai.licensing.accounts import AccountManager
from kukai.licensing.mode import MODE_OFF, licensing_mode
from kukai.llm.client import LLMClient
# [archived 2026-06-12] Gemini OAuth pool → kukai/_archive/llm_gemini/
from kukai.llm.prompts import PromptAssembler
from kukai.operations.store import DatabaseOperationStore, OperationStore
from kukai.storage.database import Database

logger = logging.getLogger(__name__)

# These are the two origins shipped in the Revit bridge as primary/fallback.
# Keep them allowed in remote mode even if a hand-edited production .env is
# restored from an older backup. Losing the primary origin caused a fleet-visible
# blank-screen incident on 2026-07-19 and regressed again on 2026-07-29.
_REQUIRED_REMOTE_UI_ORIGINS = (
    "https://revit-kukai.org",
    "https://direct.revit-kukai.org",
)

# Global app state — initialized on startup
_app_state: Optional["AppState"] = None


@dataclass
class AppState:
    """Holds all shared application state."""
    bridge: BridgeClient
    llm: LLMClient
    db: Database
    prompts: PromptAssembler
    operation_store: Optional[OperationStore] = field(default=None)
    compile_client: Optional[CompileClient] = field(default=None)
    license_manager: Optional[LicenseManager] = field(default=None)
    account_manager: Optional[AccountManager] = field(default=None)
    module_registry: Optional[Any] = field(default=None)  # ModuleRegistry — lazy import
    _cleanup_task: Optional[asyncio.Task] = field(default=None, repr=False)


def get_app_state() -> AppState:
    """Get the global application state. Raises if not initialized."""
    if _app_state is None:
        raise RuntimeError("Application not started. AppState is None.")
    return _app_state


def _cors_origins_with_client_contract(settings: Settings) -> list[str]:
    """Return configured CORS origins plus the bridge's public UI origins.

    The Revit client can navigate on either public origin and then fail over to
    the other. Requests on that cross-origin path use custom headers and require
    a successful preflight, so omitting either origin strands a subset of the
    fleet even while health checks remain green.
    """
    origins = settings.get_cors_origins_list()
    if settings.remote_mode and "*" in origins:
        raise RuntimeError(
            "CORS wildcard '*' is not allowed in remote mode. "
            "Set KUKAI_CORS_ORIGINS to specific origins."
        )
    if settings.remote_mode:
        missing = [origin for origin in _REQUIRED_REMOTE_UI_ORIGINS if origin not in origins]
        if missing:
            logger.warning(
                "KUKAI_CORS_ORIGINS omitted required Revit UI origin(s); "
                "adding trusted client origins at runtime: %s",
                ", ".join(missing),
            )
            origins.extend(missing)
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — startup and shutdown."""
    global _app_state
    settings = get_settings()

    # Configure logging — stdout + file for live monitoring
    log_level = logging.DEBUG if settings.debug else logging.INFO
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(level=log_level, format=log_format)

    # File handler for live test monitoring
    log_file = Path(__file__).parent.parent / "data" / "live_test.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(str(log_file), mode="a", encoding="utf-8")
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(log_format))
    logging.getLogger().addHandler(file_handler)

    # Silence noisy third-party DEBUG spam. httpcore/LiteLLM/pdfminer DEBUG
    # bloated live_test.log to ~14GB and buried real signal (bridge/ngrok
    # connect failures, the actual errors). App-level debug is unaffected;
    # these libraries only emit useful info at WARNING+.
    for _noisy in ("httpcore", "httpx", "LiteLLM", "litellm", "openai",
                   "urllib3", "pdfminer", "pdfminer.psparser", "pdfminer.pdfinterp"):
        logging.getLogger(_noisy).setLevel(logging.WARNING)

    logger.info("KUKI Backend starting on %s:%d", settings.host, settings.port)

    # Validate and prewarm the exact production knowledge release before any
    # external resource is opened. In Wiki mode this is a startup invariant:
    # missing/stale/tampered assets or routing-index drift must stop deployment,
    # never degrade a live request into an ungrounded or legacy-RAG response.
    from kukai.knowledge.mode import KnowledgeMode, knowledge_mode

    _knowledge_mode = knowledge_mode()
    if _knowledge_mode is KnowledgeMode.WIKI:
        from kukai.rag.wiki_router import get_wiki_router

        _knowledge_metadata = get_wiki_router().metadata()
        logger.info(
            "KNOWLEDGE READY mode=wiki release=%s manifest=%s pages=%s "
            "recipes=%s domains=%s",
            _knowledge_metadata.get("release_id"),
            _knowledge_metadata.get("manifest_sha256"),
            _knowledge_metadata.get("runtime", {}).get("pages"),
            _knowledge_metadata.get("runtime", {}).get("recipe_cards"),
            _knowledge_metadata.get("runtime", {}).get("domains"),
        )
    else:
        logger.warning("KNOWLEDGE MODE off: no Revit knowledge will be injected")

    # Initialize components
    bridge = BridgeClient(
        base_url=settings.bridge_url,
        timeout=settings.bridge_timeout,
        execute_timeout=settings.bridge_execute_timeout,
    )

    db = Database(
        settings.database_url,
        min_pool=settings.db_pool_min,
        max_pool=settings.db_pool_max,
    )
    await db.connect()
    operation_store = DatabaseOperationStore(db)

    # Transport state store (IRON 8 — multi-worker / Redis-ready seam). In-process
    # by default (zero behaviour change); KUKAI_STATE_BACKEND=redis connects Redis here.
    from kukai.transport import init_state_store
    await init_state_store()

    prompts = PromptAssembler(settings.get_prompts_dir())

    # [archived 2026-06-12] Gemini OAuth pool → kukai/_archive/llm_gemini/
    # (was inert in prod: gemini_oauth_enabled=False + openrouter primary)
    gemini_pool = None

    llm = LLMClient(
        model=settings.llm_model,
        thinking_model=settings.llm_thinking_model,
        api_key=settings.llm_api_key,
        api_base=settings.llm_api_base,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        max_tool_rounds=settings.llm_max_tool_rounds,
        timeout=settings.llm_timeout,
        prompt_assembler=prompts,
        bridge_client=bridge,
        google_backup_api_key=settings.llm_google_backup_api_key,
        google_fallback_api_key=settings.llm_google_fallback_api_key,
        fallback_model=settings.llm_fallback_model,
        fallback_api_key=settings.llm_fallback_api_key,
        fallback_timeout=settings.llm_fallback_timeout,
        thinking_timeout=settings.llm_thinking_timeout,
        gemini_pool=gemini_pool,
        # last_resort_* still passed for backward compat — ignored by new chain
        last_resort_model=settings.llm_last_resort_model,
        last_resort_api_key=settings.llm_last_resort_api_key,
        last_resort_api_base=settings.llm_last_resort_api_base,
    )

    # Initialize license + account managers. Constructed when auth is enabled OR
    # KUKAI_LICENSING is shadow/enforce (shadow needs the managers to compute the
    # would-allow/would-deny decisions it logs). With prod's default (auth off +
    # licensing unset -> off) NOTHING is constructed and behavior is byte-identical.
    license_manager: Optional[LicenseManager] = None
    account_manager: Optional[AccountManager] = None
    _licensing = licensing_mode()
    if settings.auth_enabled or _licensing != MODE_OFF:
        try:
            server_secret = settings.get_server_secret()
            raw_db = db.raw_connection
            license_manager = LicenseManager(raw_db, server_secret)
            await license_manager.initialize()
            license_manager.apply_config_limits(
                free_window_limit=settings.free_daily_limit,
                pro_window_limit=settings.pro_window_limit,
                ultra_window_limit=settings.ultra_window_limit,
            )
            account_manager = AccountManager(raw_db, license_manager)
            await account_manager.initialize()
            logger.info("License + account managers initialized (auth=%s, licensing=%s)",
                        settings.auth_enabled, _licensing)
        except Exception as e:
            logger.error("Failed to initialize license/account managers: %s", e)
            # In remote mode, this is fatal
            if settings.remote_mode:
                raise
    else:
        logger.info("Auth disabled and licensing off — running in local mode")

    # Initialize telemetry tables
    try:
        from kukai.telemetry import TelemetryCollector
        telemetry = TelemetryCollector(db)
        await telemetry.initialize()
        logger.info("Telemetry initialized")
    except Exception:
        logger.warning("Telemetry initialization failed (non-fatal)")

    # Initialize compile service (optional — degrades gracefully)
    compile_process = None
    compile_client = CompileClient()

    # Try to start compile service as subprocess — but only if it isn't
    # already running. With multiple uvicorn workers (or systemd-managed
    # kukai-compile.service) the port is already bound; an extra spawn
    # would just fail and leave a zombie dotnet process.
    compile_service_dir = Path(__file__).parent.parent / "compile-service"
    if compile_service_dir.exists() and not await compile_client.health():
        import subprocess as _sp
        try:
            compile_process = _sp.Popen(
                ["dotnet", "run", "--no-build", "--project", str(compile_service_dir)],
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
            )
            # Wait for service to start (up to 10 seconds)
            for _ in range(20):
                await asyncio.sleep(0.5)
                if await compile_client.health():
                    break
        except FileNotFoundError:
            logger.info("dotnet not found — compile service disabled")

    if await compile_client.health():
        logger.info("Compile service running on localhost:52412")
    else:
        logger.info("Compile service not available — will use Revit for compilation")
        if compile_process:
            compile_process.terminate()
            compile_process = None

    _app_state = AppState(
        bridge=bridge,
        llm=llm,
        db=db,
        operation_store=operation_store,
        prompts=prompts,
        compile_client=compile_client,
        license_manager=license_manager,
        account_manager=account_manager,
    )

    # Load KUKAI modules via registry
    from kukai.modules.registry import ModuleRegistry
    from kukai.modules.base import ModuleDeps

    registry = ModuleRegistry()
    deps = ModuleDeps(
        bridge=bridge,
        llm=llm,
        db=db,
        prompts=prompts,
        data_dir=Path(__file__).parent.parent / "data",
    )
    await registry.load_modules(settings.get_modules_list(), deps)
    _app_state.module_registry = registry

    # Wire module tools into LLM client for dynamic tool dispatch
    llm.set_module_registry(registry)

    # (IFC integration removed 2026-06-10 — module archived to kukai/_archive/ifc/)

    # Start periodic cleanup of old sessions and generated files (every 24 hours)
    _app_state._cleanup_task = asyncio.create_task(
        _periodic_cleanup(db, settings.session_ttl_days, settings.file_ttl_hours, settings.get_files_dir())
    )

    # Phase 1 (revit-coder pilot): start uptime monitor when enabled.
    # See docs/superpowers/specs/2026-05-01-revit-coder-integration-design.md
    from kukai.config import USE_REVIT_CODER as _USE_REVIT_CODER
    uptime_task: Optional[asyncio.Task] = None
    if _USE_REVIT_CODER:
        from kukai.revit_coder.uptime_monitor import uptime_monitor_loop
        uptime_task = asyncio.create_task(uptime_monitor_loop())
        logger.info("revit-coder uptime monitor started")

    # Step 11 — startup security-posture banner (pure logging, always on).
    # Makes the ACCEPTED dev-stage posture visible at every boot instead of
    # implicit: auth intentionally OFF, sandbox mode, and WHICH value is the
    # tenancy isolation key (client-supplied device_id vs signed identity).
    try:
        from kukai.security.identity import identity_mode as _identity_mode
        from kukai.security.validation import _weak_sandbox
        _iso = {
            "off": "device_id (client-supplied, spoofable)",
            "compat": "signed-identity COMPAT (KUKAI_SIGNED_IDENTITY=1; legacy device_id fallback)",
            "strict": "signed-identity STRICT (server-minted only)",
        }.get(_identity_mode(), "unknown")
        logger.warning(
            "SECURITY POSTURE (dev-stage, operator-accepted): auth=%s | sandbox=%s | isolation-key=%s",
            "ENABLED" if settings.auth_enabled else "OFF",
            "WEAK (KUKAI_WEAK_SANDBOX)" if _weak_sandbox() else "pattern-validation",
            _iso,
        )
    except Exception:  # noqa: BLE001 — a banner must never block startup
        logger.debug("security posture banner failed (non-fatal)", exc_info=True)

    # OBSERVABILITY / FEATURE-FLAG banner — makes a process that booted with the
    # wrong environment (e.g. KUKAI_TURN_LEDGER missing → the measurement spine
    # silently records ZERO turns, as happened 2026-07-07) obvious at boot instead
    # of discovering the data gap hours later. Never blocks startup.
    try:
        import os as _os
        from kukai import turn_ledger as _tl_boot
        logger.info(
            "OBSERVABILITY: turn_ledger=%s | brain=%s | autoshow_witnessed=%s | auto_show=%s | vision_critic=%s",
            "ON" if _tl_boot.enabled() else "OFF (no ledger data!)",
            _os.environ.get("KUKAI_LLM_MODEL", "?"),
            _os.environ.get("KUKAI_AUTOSHOW_WITNESSED", "0"),
            _os.environ.get("KUKAI_AUTO_SHOW", "0"),
            _os.environ.get("KUKAI_VISION_CRITIC", "0"),
        )
    except Exception:  # noqa: BLE001 — a banner must never block startup
        logger.debug("observability banner failed (non-fatal)", exc_info=True)

    logger.info("KUKI Backend started successfully")

    yield

    # Shutdown
    logger.info("KUKI Backend shutting down...")
    if uptime_task is not None:
        uptime_task.cancel()
        try:
            await uptime_task
        except asyncio.CancelledError:
            pass
    if _app_state._cleanup_task:
        _app_state._cleanup_task.cancel()
        try:
            await _app_state._cleanup_task
        except asyncio.CancelledError:
            pass

    if _app_state.compile_client:
        await _app_state.compile_client.close()
    if compile_process:
        compile_process.terminate()
        logger.info("Compile service stopped")
    if _app_state.module_registry:
        await _app_state.module_registry.shutdown()
    if gemini_pool:
        await gemini_pool.close()
    try:
        from kukai.transport import get_state_store
        await get_state_store().close()
    except Exception:
        pass
    await bridge.close()
    await db.close()
    _app_state = None
    logger.info("KUKI Backend stopped")


async def _periodic_cleanup(db: Database, ttl_days: int, file_ttl_hours: int = 24, files_dir: Path | None = None) -> None:
    """Background task: clean up expired sessions, old files, and request_log entries.

    Runs on startup and then every 24 hours.
    """
    cleanup_interval = 24 * 60 * 60  # 24 hours in seconds
    while True:
        try:
            # Run cleanup first, then sleep (so first cleanup runs immediately on startup)
            count = await db.cleanup_old_sessions(ttl_days)
            if count > 0:
                logger.info("Periodic cleanup: removed %d old sessions", count)

            # Clean up generated files older than file_ttl_hours
            if files_dir and files_dir.exists():
                import time
                cutoff = time.time() - file_ttl_hours * 3600
                removed_files = 0
                for f in files_dir.iterdir():
                    if f.is_file() and f.stat().st_mtime < cutoff:
                        try:
                            f.unlink()
                            removed_files += 1
                        except OSError:
                            pass
                if removed_files > 0:
                    logger.info("Periodic cleanup: removed %d old generated files", removed_files)

            # Clean up old request_log entries (older than 7 days)
            if _app_state and _app_state.license_manager:
                try:
                    rl_count = await _app_state.license_manager.cleanup_request_log()
                    if rl_count > 0:
                        logger.info("Periodic cleanup: removed %d old request_log entries", rl_count)
                except Exception:
                    logger.warning("Failed to clean up request_log (non-fatal)")

            # Clean up old telemetry data (older than 90 days)
            if _app_state:
                try:
                    from kukai.telemetry import TelemetryCollector
                    tc = TelemetryCollector(_app_state.db)
                    tl_count = await tc.cleanup(keep_days=90)
                    if tl_count > 0:
                        logger.info("Periodic cleanup: removed %d old telemetry entries", tl_count)
                except Exception as e:
                    # IRON 10 — telemetry maintenance failure is counted/surfaced,
                    # not silently swallowed. Non-blocking: the cleanup loop
                    # continues to the next housekeeping step regardless.
                    from kukai.telemetry import note_telemetry_failure
                    note_telemetry_failure(e)

            # Clean up old TurnLedger rows (KUKAI_TURN_LEDGER shadow spine — one
            # row per turn, no retention of its own). Keep 30 days.
            if _app_state:
                try:
                    tl_rows = await _app_state.db.cleanup_turn_ledger(keep_days=30)
                    if tl_rows > 0:
                        logger.info("Periodic cleanup: removed %d old turn_ledger rows", tl_rows)
                except Exception:
                    logger.warning("turn_ledger cleanup failed (non-fatal)")

            # Operation-truth ledger retention: terminal rows after 90 days,
            # stuck non-terminal rows (old-client RUNNING_UNKNOWN, crashed SENT)
            # after 180. Was dead code until wired here (verify 2026-07-16).
            if _app_state:
                try:
                    op_rows = await _app_state.db.cleanup_operations(
                        keep_days=90, stuck_keep_days=180
                    )
                    if op_rows > 0:
                        logger.info("Periodic cleanup: removed %d old operation rows", op_rows)
                except Exception:
                    logger.warning("operations cleanup failed (non-fatal)")

            # Clean up stale WebSocket sessions (zombie connections)
            try:
                from kukai.api.chat_ws import cleanup_stale_sessions
                await cleanup_stale_sessions()
            except Exception:
                pass

            await asyncio.sleep(cleanup_interval)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Periodic cleanup error")
            # Avoid tight loop on persistent errors
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    from kukai.api.chat_http import router as chat_http_router
    from kukai.api.chat_ws import router as chat_ws_router
    from kukai.api.extensions import router as extensions_router
    from kukai.api.setup import router as setup_router
    from kukai.api.static import router as static_router
    from kukai.api.status import router as status_router
    from kukai.licensing.admin_api import router as admin_router
    from kukai.api.admin_remote import router as admin_remote_router
    from kukai.api.admin_kir import router as admin_kir_router
    from kukai.api.diagnostics import router as diagnostics_router
    from kukai.api.device_directives import router as device_directives_router
    from kukai.api.install_telemetry import router as install_telemetry_router
    # ARCHIVED 2026-06-10 (operator: archive Gemini+IFC+VOR): VOR (/api/vor/*) and
    # IFC (/ws/ifc, bridge-token) entrypoints removed from the active product.
    # vor.matcher stays (scheduling depends on it); dirs not physically moved
    # (kukai.vor.* / kukai.ifc.* coupling → see kukai/_archive/RESTORE.md).

    if settings is None:
        settings = get_settings()

    app = FastAPI(
        title="KUKI Backend",
        version=__version__,
        description="AI Assistant for Autodesk Revit",
        lifespan=lifespan,
    )

    # CORS — configurable origins
    cors_origins = _cors_origins_with_client_contract(settings)
    cors_kwargs: dict[str, Any] = {
        "allow_origins": cors_origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }
    # Only allow arbitrary ngrok subdomains in local (non-remote) mode
    if not settings.remote_mode:
        cors_kwargs["allow_origin_regex"] = r"https://.*\.ngrok-free\.(app|dev)"
    app.add_middleware(CORSMiddleware, **cors_kwargs)

    # Register routers
    app.include_router(setup_router)
    app.include_router(chat_ws_router)
    app.include_router(chat_http_router)
    app.include_router(extensions_router)
    app.include_router(status_router)
    app.include_router(static_router)
    app.include_router(admin_router)
    app.include_router(admin_remote_router)
    app.include_router(admin_kir_router)
    # Bridge crash reports (api/diagnostics.py existed but was never included —
    # CrashUploader POSTs 404'd; found+fixed during the installer-v2 work) and
    # installer telemetry (install_start/complete/failed + /admin/install/report).
    app.include_router(diagnostics_router)
    app.include_router(device_directives_router)
    app.include_router(install_telemetry_router)
    # ARCHIVED 2026-06-10: vor_router (/api/vor/*), bridge_ws_router (/ws/ifc),
    # bridge_token_router — VOR + IFC removed from the active product.

    return app


# The app instance used by uvicorn.
# Lazy creation: avoids RuntimeError during test imports when .env has
# production settings (KUKAI_REMOTE_MODE=true, KUKAI_CORS_ORIGINS=*).
# Uvicorn and tests that need the default app call create_app() explicitly.
_app: Optional[FastAPI] = None


def _get_default_app() -> FastAPI:
    global _app
    if _app is None:
        _app = create_app()
    return _app


# Module-level 'app' attribute accessed by uvicorn ("kukai.main:app").
# Uses __getattr__ so creation is deferred until first access.
def __getattr__(name: str) -> Any:
    if name == "app":
        return _get_default_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
