"""Per-connection session registries — peeled verbatim from chat_ws.py.

Golden-path decomposition Phase 1 (2026-07-12): all per-ws_id state dicts
(contexts, keys, passports, discovery, states, activity, identities, bridge
serialize locks, device→WS registry) + their accessors. Pure file move, zero
behavior change; the dict objects are shared with chat_ws via re-export and
are mutated in place, never rebound.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Optional

from fastapi import WebSocket

from kukai.discovery import DiscoveryCache
from kukai.api.ws_send import _send_json

logger = logging.getLogger(__name__)


# Per-session state: context and pending bridge requests
# Key: session identifier (websocket id), Value: session data
_session_contexts: dict[str, dict[str, Any]] = {}
_session_keys: dict[str, bytes] = {}
_session_detailed_passports: dict[str, dict[str, Any]] = {}
_discovery_caches: dict[str, DiscoveryCache] = {}
_session_states: dict[str, Any] = {}

# ── Step 11 (KUKAI_SIGNED_IDENTITY, flag-gated) ─────────────────────────────
# Per-connection signed-identity holder: ws_id -> {identity, source, minted_sent}.
# Process-local by design, like every other live-connection map in this module
# (see the transport/StateStore split: only the serializable directory belongs
# in the StateStore; the deployment is single-worker — kukai-backend.service
# runs uvicorn --workers 1). Populated ONLY when the flag is ON; flag OFF
# allocates nothing and the tenancy path stays byte-identical to legacy.
_conn_identities: dict[str, dict[str, Any]] = {}

# Bridge serialization (KUKAI_BRIDGE_SERIALIZE, default ON): Revit runs C# through ONE
# single-threaded ExternalEvent, so overlapping execute/context round-trips collide with
# "Failed to raise ExternalEvent: Pending" (observed live 2026-07-08). One asyncio.Lock per
# ws_id ⇒ at most one bridge op in flight for that Revit at a time, ACROSS concurrent turns
# (rapid user messages each spawn a turn sharing the same connection).
_bridge_serialize_locks: dict[str, asyncio.Lock] = {}


def _bridge_serialize_enabled() -> bool:
    return os.environ.get("KUKAI_BRIDGE_SERIALIZE", "1") != "0"


def _get_bridge_serialize_lock(ws_id: str) -> asyncio.Lock:
    lock = _bridge_serialize_locks.get(ws_id)
    if lock is None:
        lock = asyncio.Lock()
        _bridge_serialize_locks[ws_id] = lock
    return lock

# WebSocket registry: device_id -> set of active WebSocket objects.
# Multiple Revit processes on the same machine share device_id (HWID-derived),
# so a single-WS-per-device map silently drops the older connection on the
# second connect and breaks push messages (VOR progress, save_file, etc.) for it.
# Storing a set lets every connected Revit instance receive broadcasts.
_device_websockets: dict[str, set[WebSocket]] = {}


# Session activity tracking for TTL cleanup (prevents memory leaks from zombie connections).
# Updated on every incoming message — only INACTIVE sessions get cleaned.
# Chat history is in SQLite (kukai.db) and is NOT affected by session cleanup.
_session_last_activity: dict[str, float] = {}
SESSION_INACTIVITY_TTL = 28800  # 8 hours of silence = zombie, clean up

# [MARATHON-REMOTE-LOOKUP] Reverse mapping: WebSocket id → ws_id.
# Used by /admin/remote/* endpoints to look up the ws_id for a given
# device's WebSocket (needed for encryption: the per-session AES key
# is stored in `_session_keys[ws_id]`). Without this, admin endpoint
# can't encrypt code for `execute` bridge_request.
# Keyed by id(websocket) — Python object identity. Cleared on disconnect.
_ws_object_to_ws_id: dict[int, str] = {}

# Идущая задача хода на соединение — чтобы ход можно было остановить СНАРУЖИ
# того сокета, который его начал.
#
# ЗАЧЕМ ЭТОТ РЕЕСТР (29.07). Задача жила только в локальной переменной
# обработчика вебсокета, поэтому единственным способом прервать ход была кнопка
# в клиенте. Когда ход оператора ушёл в бесконечную самопроверку (176 чтений
# против 5 записей, в погоне за критерием «1в1 с Эйфелевой башней», который
# система не может проверить даже в принципе), на сервере не осталось ничего,
# кроме перезапуска бэкенда — а он оборвал ход на середине и оставил человека
# в тишине. Перезапуск был неверным инструментом и стоил живой сессии.
#
# На флоте это перестаёт быть историей про один ход: зациклившийся агент на
# чужой машине жжёт общую квоту подписки, и гасить его надо снаружи, не задевая
# остальных.
_chat_tasks: dict[str, Any] = {}


def register_chat_task(ws_id: str, task: Any) -> None:
    if ws_id:
        _chat_tasks[ws_id] = task


def unregister_chat_task(ws_id: str) -> None:
    _chat_tasks.pop(ws_id, None)


def chat_task_for(ws_id: str) -> Any:
    return _chat_tasks.get(ws_id)


def ws_ids_for_device(device_id: str) -> list[str]:
    """Соединения этого устройства. Их может быть несколько: человек открыл
    KUKI в двух окнах Revit — гасить надо все, иначе «отменил, а оно идёт»."""
    out = []
    for ws in list(_device_websockets.get(device_id) or ()):
        wid = _ws_object_to_ws_id.get(id(ws))
        if wid:
            out.append(wid)
    return out


def get_active_ws_count() -> int:
    """Return the number of currently connected WebSocket clients (across all device_ids)."""
    return sum(len(ws_set) for ws_set in _device_websockets.values())


async def send_ws_message(device_id: str, message: dict[str, Any]) -> bool:
    """Broadcast a message to every active WebSocket for the given device_id.

    Returns True if at least one delivery succeeded, False if no live connection.
    Used by background tasks (e.g. VOR pipeline) to push progress updates.

    Multi-instance note: when two Revit processes run on the same machine they
    share device_id, so this broadcasts to both. For tasks bound to a single
    originating chat (e.g. progress updates), the caller should prefer to send
    over the specific WebSocket it already holds rather than going through this
    registry.
    """
    ws_set = _device_websockets.get(device_id)
    if not ws_set:
        return False
    delivered = False
    # Snapshot the set since failed sends are pruned mid-iteration.
    for ws in list(ws_set):
        try:
            await _send_json(ws, message)
            delivered = True
        except Exception:
            logger.debug("Failed to send WS message to device %s — dropping stale ws", device_id)
            ws_set.discard(ws)
    if not ws_set:
        _device_websockets.pop(device_id, None)
    return delivered


async def cleanup_stale_sessions() -> None:
    """Remove sessions that have been INACTIVE for SESSION_INACTIVITY_TTL seconds.

    Only cleans zombie connections (no messages for 2+ hours).
    Active users are never affected — their timestamp refreshes on every message.
    Chat history in SQLite (kukai.db) is NOT touched.
    """
    now = time.time()
    stale = [ws_id for ws_id, last in _session_last_activity.items()
             if now - last > SESSION_INACTIVITY_TTL]
    for ws_id in stale:
        _session_keys.pop(ws_id, None)
        _session_contexts.pop(ws_id, None)
        _session_detailed_passports.pop(ws_id, None)
        _discovery_caches.pop(ws_id, None)
        _session_states.pop(ws_id, None)
        _session_last_activity.pop(ws_id, None)
        _conn_identities.pop(ws_id, None)  # Step 11: signed-identity holder
        _bridge_serialize_locks.pop(ws_id, None)  # bridge serialization lock
        # [MARATHON-REMOTE-LOOKUP] Stale ws-object mappings will be GC'd
        # when the WebSocket object itself is collected; we don't have a
        # cheap reverse lookup here. Acceptable: id() collisions across
        # different live websockets in practice rare on a long-running
        # server, and the next disconnect path on the same id rebinds.
    if stale:
        logger.info("Cleaned up %d inactive sessions (idle > %ds)", len(stale), SESSION_INACTIVITY_TTL)



async def _handle_context(data: dict[str, Any], ws_id: str, ws: WebSocket) -> None:
    """Handle context message — store Revit model context."""
    context_data = data.get("data", {})
    _session_contexts[ws_id] = context_data
    logger.debug("Received context for ws_id=%s: %s", ws_id, list(context_data.keys()))


async def _handle_detailed_passport(data: dict[str, Any], ws_id: str) -> None:
    """Handle detailed_passport message — store enriched model passport from C# bridge.

    This is Tier 2 of the Model Passport system. Arrives 5-10 seconds after connect,
    contains rich data: family/type hierarchy, parameters, rooms, grids, naming conventions.
    Merged with basic context to produce ~20K token Markdown passport for LLM.
    """
    passport_data = data.get("data", {})
    _session_detailed_passports[ws_id] = passport_data

    # Cache to disk for fast reload on next connect
    try:
        from kukai.model_passport import ModelPassport, PassportCache

        basic_ctx = _session_contexts.get(ws_id, {})
        passport = ModelPassport({**basic_ctx, "detailed": passport_data})
        fingerprint = passport.compute_fingerprint()
        formatted = passport.format_full()

        cache = PassportCache()
        cache.save(fingerprint, passport_data, formatted)
        cache.cleanup(keep=5)

        logger.info(
            "Detailed passport cached for ws_id=%s (fingerprint=%s, %d chars)",
            ws_id, fingerprint, len(formatted),
        )
    except Exception:
        logger.warning("Failed to cache detailed passport (non-fatal)", exc_info=True)


def _build_model_details(ws_id: str, section: str = "full") -> dict[str, Any]:
    """Serve the on-demand `get_model_details` tool.

    Returns the FULL model passport (or a single section) from the detailed
    passport the C# bridge already pushed for this session — no Revit round-trip.
    The default per-request passport is the LIGHT one (format_quick, ~5K tokens);
    the LLM calls this tool to pull the heavy ~20K detail only when it needs it.
    """
    try:
        from kukai.model_passport import ModelPassport
        basic_ctx = _session_contexts.get(ws_id, {})
        detailed = _session_detailed_passports.get(ws_id)
        if not basic_ctx and not detailed:
            return {"success": False, "error": "Модель не открыта или паспорт ещё не собран."}
        passport = ModelPassport({**basic_ctx, "detailed": detailed} if detailed else basic_ctx)
        section = (section or "full").strip().lower()
        section_map = {
            "structure": passport._structure,
            "parameters": passport._parameters,
            "spatial": passport._spatial,
            "views": passport._views_sheets,
            "standards": passport._standards,
        }
        if detailed and section in section_map:
            text = passport._header() + "\n\n" + section_map[section]()
        else:
            text = passport.format_full() if detailed else passport.format_quick()
        return {"success": True, "section": section, "details": text}
    except Exception as e:
        logger.warning("get_model_details failed for ws_id=%s: %s", ws_id, e)
        return {"success": False, "error": "Не удалось собрать детальный паспорт."}


def _adapt_flat_context(ctx_data: dict[str, Any]) -> dict[str, Any]:
    """Adapt flat C# ModelContext JSON to nested ContextResult schema.

    C# DataExporter sends:
      { has_document, revit_version, document_name, document_path, categories, levels, ... }
    Python ContextResult expects:
      { document: { name, path, revit_version }, categories, levels, phase, ... }

    Returns a dict matching ContextResult schema, or the original dict if it already
    has the nested 'document' key.
    """
    # Already in nested format — return as-is
    if "document" in ctx_data:
        return ctx_data

    # Flat format from C# — adapt
    return {
        "document": {
            "name": ctx_data.get("document_name", "Unknown"),
            "path": ctx_data.get("document_path", ""),
            "revit_version": ctx_data.get("revit_version", ""),
        },
        "categories": ctx_data.get("categories", []),
        "levels": ctx_data.get("levels", []),
        "current_view": ctx_data.get("current_view", {"name": "", "type": "", "id": 0}),
        "selection": ctx_data.get("selection", {"count": 0, "element_ids": [], "categories": []}),
        "phase": ctx_data.get("phase", {"name": "", "id": 0}),
        "units": ctx_data.get("units", "metric"),
        "warnings_count": ctx_data.get("warnings_count", 0),
    }


def _get_context_for_session(ws_id: str) -> Optional[Any]:
    """Get stored context for a WebSocket session.

    Returns a ContextResult-like object if context is available,
    or None if no context has been sent by the client.

    Handles both the flat C# ModelContext format and the nested ContextResult format
    via _adapt_flat_context().
    """
    from kukai.bridge.models import (
        CategoryInfo,
        ContextResult,
        DocumentInfo,
        LevelInfo,
        PhaseInfo,
        SelectionInfo,
        ViewInfo,
    )

    ctx_data = _session_contexts.get(ws_id, {})
    if not ctx_data:
        return None

    # If flat C# data has has_document=false, there's no document open
    if ctx_data.get("has_document") is False:
        return None

    # Adapt flat C# format to nested ContextResult format
    adapted = _adapt_flat_context(ctx_data)

    try:
        return ContextResult.model_validate(adapted)
    except Exception:
        logger.debug("Context data doesn't match ContextResult schema after adaptation, building manually")
        try:
            doc_data = adapted.get("document", {})
            return ContextResult(
                document=DocumentInfo(
                    name=doc_data.get("name", "Unknown"),
                    path=doc_data.get("path", ""),
                    revit_version=doc_data.get("revit_version", ""),
                ),
                categories=[
                    CategoryInfo(**c) for c in adapted.get("categories", [])
                ],
                levels=[
                    LevelInfo(**l) for l in adapted.get("levels", [])
                ],
                current_view=ViewInfo(**adapted.get("current_view", {"name": "", "type": "", "id": 0})),
                selection=SelectionInfo(**adapted.get("selection", {"count": 0, "element_ids": [], "categories": []})),
                phase=PhaseInfo(**adapted.get("phase", {"name": "", "id": 0})),
                units=adapted.get("units", "metric"),
                warnings_count=adapted.get("warnings_count", 0),
            )
        except Exception:
            logger.warning("Failed to parse context data for ws_id=%s", ws_id)
            return None
