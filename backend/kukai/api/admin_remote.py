"""Admin remote-control endpoints — SSH-equivalent to KUKI plugin.

[MARATHON] Built to satisfy the "встать на место лошади" requirement:
let the auditor initiate plugin operations on a specific device's WebSocket
from outside the running session, without needing AnyDesk/RDP to the user's
machine.

The path uses the SAME mechanism that `chat_ws.py` uses for normal tool
calls: backend sends a `bridge_request` JSON-RPC to the plugin's active
WebSocket, the plugin runs the operation in Revit, and the response comes
back through `bridge_response`. We just expose this via an HTTP endpoint
instead of going through the chat-flow.

Endpoints
---------
GET  /admin/remote/sessions          — list device_ids with live WS
POST /admin/remote/screenshot/{dev}  — trigger Revit view export on device's session
POST /admin/remote/exec/{dev}        — run arbitrary C# in Revit (admin escape hatch)

All endpoints require X-Admin-Token header matching KUKAI_ADMIN_TOKEN env.

Known limitation
----------------
`export_view` saves PNG to `Documents/KUKI/exports/` on the *user's*
machine. This backend on the VPS does not have direct file-system access
to that path. The endpoint returns the file_path the plugin wrote; the
auditor needs an out-of-band channel (manual share, OneDrive sync, etc.)
to actually see the image bytes. A future enhancement requires C# bridge
rebuild to return base64 inline — tracked separately.
"""

from __future__ import annotations

import hmac
import logging
import os
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from kukai.config import get_settings


# Worker PID stays constant for the life of the process. Returned in 503
# headers so the client knows which worker it just hit and can keep
# retrying until it lands on the worker that actually owns the WS.
_OWN_PID = os.getpid()


def _ws_not_found_response(device_id: str) -> JSONResponse:
    """Return 503 + Retry-After when a device's WS isn't on this worker.

    Background (F-NEW-025): uvicorn runs with `--workers 4`, and the
    `_device_websockets` registry lives in process memory per-worker. A
    WS connected to worker A is invisible to workers B/C/D. The admin
    endpoints are stateless HTTP, so uvicorn round-robins each request
    across workers — meaning ~75% of `/admin/remote/exec` calls land on
    the wrong worker and need to retry.

    We return 503 (Service Unavailable) with `Retry-After: 0` so a
    well-behaved client retries immediately, and uvicorn round-robins
    the retry to (usually) a different worker. After 4-12 retries the
    client is statistically guaranteed to land on the correct worker.

    Distinguishing "truly offline" from "wrong worker" is impossible
    from inside a single worker — the device could exist on another
    worker. The client's retry budget is what disambiguates: if all
    workers return 503, the device is truly offline.
    """
    return JSONResponse(
        status_code=503,
        content={
            "detail": f"No live WebSocket for device_id={device_id} on worker pid={_OWN_PID}",
            "worker_pid": _OWN_PID,
            "retry_hint": "device may be registered on another uvicorn worker; "
                          "retry up to 12× to round-robin across all workers",
        },
        headers={
            "Retry-After": "0",
            "X-Worker-Pid": str(_OWN_PID),
        },
    )

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/remote", tags=["admin-remote"])


async def verify_admin_token(
    x_admin_token: Optional[str] = Header(None),
) -> str:
    """Verify the admin token header. Shared pattern with licensing/admin_api."""
    settings = get_settings()
    if not settings.admin_token:
        raise HTTPException(
            status_code=503,
            detail="Admin API not configured. Set KUKAI_ADMIN_TOKEN.",
        )
    if not x_admin_token or not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return x_admin_token


@router.get("/sessions", dependencies=[Depends(verify_admin_token)])
async def list_sessions(model: Optional[str] = None) -> Any:
    """Enumerate device_ids with at least one live WebSocket connection.

    [MARATHON fix] The earlier implementation looked up `document_name` via
    "last-wins" iteration over `_session_contexts.values()` — that gave
    EVERY session the SAME document_name (whichever ws_id happened to be
    iterated last). Now we resolve the actual document per device by
    reverse-mapping each WS → ws_id → context.

    Optional `model` query filter — substring match on document_name.

    Each result now also includes `worker_pid` — the PID of the uvicorn
    worker that owns the WS. Together with the per-worker view, this lets
    research clients understand which slice of state they're seeing and
    explain "missing" devices (they may live on another worker — see
    F-NEW-025).
    """
    from kukai.api.chat_ws import (
        _device_websockets,
        _session_contexts,
        _ws_object_to_ws_id,
    )
    out: list[dict[str, Any]] = []
    for device_id, ws_set in _device_websockets.items():
        # Pick the most-recent ws_id for this device (any of them works
        # for context lookup since context is sent on every connect).
        doc_name = ""
        bridge_version = ""
        for ws in ws_set:
            wid = _ws_object_to_ws_id.get(id(ws))
            if not wid:
                continue
            ctx = _session_contexts.get(wid, {})
            name = ctx.get("document_name") or ""
            # [rc6] rc6+ bridges report their assembly version in every
            # context push; older builds simply lack the field ("" = pre-rc6).
            # First per-device "who runs what" signal for the fleet map.
            if not bridge_version:
                bridge_version = str(ctx.get("bridge_version") or "")
            if name:
                doc_name = name
                break
        if model and model.lower() not in doc_name.lower():
            continue
        out.append({
            "device_id": device_id,
            "ws_count": len(ws_set),
            "document_name": doc_name,
            "bridge_version": bridge_version,
        })
    return {
        "sessions": out,
        "count": len(out),
        "worker_pid": _OWN_PID,
        "_note": "This worker's view only. Devices on other workers are not listed. "
                 "Probe each device via /admin/remote/exec which auto-retries via "
                 "503+Retry-After across workers.",
    }


@router.post("/screenshot/{device_id}", dependencies=[Depends(verify_admin_token)])
async def trigger_screenshot(
    device_id: str,
    filename: str = "marathon_audit.png",
    fmt: str = "png",
) -> Any:
    """Ask the plugin to export the active Revit view to an image file.

    Returns the path the plugin wrote on the user's machine. To actually
    obtain the image bytes, the auditor needs an out-of-band copy step
    (this is a real limitation — see module docstring).

    `filename` and `fmt` are forwarded as bridge params; the plugin's
    `export_view` JSON-RPC method controls the output.
    """
    return await _send_bridge_request(
        device_id=device_id,
        method="export_view",
        params={"filename": filename, "format": fmt},
        timeout_s=30.0,
    )


@router.post("/chat/{device_id}", dependencies=[Depends(verify_admin_token)])
async def inject_chat(
    device_id: str,
    payload: dict[str, Any],
) -> Any:
    """Inject a chat message into the device's active session.

    Triggers the FULL chat-flow on the backend as if the user typed:
      RAG retrieval → LLM call → tool dispatch → bridge execute →
      stream events → final assistant text.

    **VISIBLE TO USER**: stream events (`stream_chunk`, `reasoning_*`,
    `tool_*`) are sent through the device's real WebSocket, so the
    KUKI panel will SHOW the assistant working on this message just
    like a normal user-typed input. Use only on sessions where the
    operator has consent.

    Body: { "message": "<text>", "session_id": "<optional UUID>",
            "preferences": {<optional>}, "thinking_mode": "<optional>" }

    Returns immediately after dispatching the task (fire-and-forget).
    Watch journalctl for CHAT REQUEST / CHAT COMPLETE timestamps to
    measure end-to-end latency and inspect repair-loop iterations.
    """
    import asyncio as _asyncio
    import uuid
    from kukai.api import ws_registry as _wsreg
    from kukai.api.chat_ws import (
        _device_websockets,
        _tracked_handle_chat,
        _ws_object_to_ws_id,
        _active_chat_count,
        MAX_ACTIVE_CHATS,
    )

    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Missing 'message' in body")

    ws_set = _device_websockets.get(device_id)
    if not ws_set:
        # 503 instead of 404 — see _ws_not_found_response docstring.
        return _ws_not_found_response(device_id)
    ws = next(iter(ws_set))
    ws_id = _ws_object_to_ws_id.get(id(ws))
    if not ws_id:
        raise HTTPException(
            status_code=500,
            detail="ws_id mapping missing — cannot proceed",
        )

    session_id = payload.get("session_id") or str(uuid.uuid4())[:8]
    chat_data = {
        "type": "chat",
        "message": message,
        "session_id": session_id,
        "preferences": payload.get("preferences", {}),
    }
    if "thinking_mode" in payload:
        chat_data["thinking_mode"] = payload["thinking_mode"]

    # auth_info shape that downstream code expects. We pass synthetic
    # admin-grade tier; the device_id is real.
    auth_info = {
        "device_id": device_id,
        "device_token": "admin-injected",
        "tier": "free",
        "rate_limit_seconds": 0,
    }

    # Устройство уже занято? Пользовательский путь такой ход отклоняет
    # («Предыдущий запрос ещё обрабатывается», chat_ws), а этот — не отклонял, и
    # 29.07 это сорвало опыт KIR-против-C#: первый ход не влез в бюджет, второй
    # ушёл поверх него, и два хода восемь минут строили в ОДНУ модель вперемешку.
    # Разделить их вклад после этого нельзя ничем. Цена на флоте выше замера:
    # два хода на одной машине жгут общую квоту подписки и правят одну модель.
    busy = _wsreg.chat_task_for(ws_id)
    if busy is not None and not busy.done() and not payload.get("force"):
        raise HTTPException(
            status_code=409,
            detail="На устройстве уже идёт ход. Погасите его "
                   f"(POST /admin/remote/cancel/{device_id}) или передайте force=true.")

    # Fire-and-forget — chat tasks are long (LLM + tools, can be 30s+).
    # Returning immediately and letting it run on the event loop matches
    # the pattern in chat_ws.py:371 (chat_task = asyncio.create_task...).
    task = _asyncio.create_task(
        _tracked_handle_chat(ws, chat_data, device_id, auth_info, ws_id)
    )
    # РЕГИСТРАЦИЯ ОБЯЗАТЕЛЬНА. Без неё admin/remote/cancel честно отвечает
    # «turns_cancelled: 0, status: idle» при живом ходе — то есть рычаг отмены,
    # ради которого всё и делалось, не действует ровно на тот путь, которым
    # ходы запускаются снаружи. Поймано живьём: ход шёл 14.7 мин, отмена на 8-й
    # минуте не нашла, что гасить.
    _wsreg.register_chat_task(ws_id, task)
    task.add_done_callback(lambda _t, _w=ws_id: _wsreg.unregister_chat_task(_w))

    logger.info(
        "[admin/remote/chat] INJECT device=%s session=%s msg=%r",
        device_id, session_id, message[:80],
    )
    return {
        "status": "injected",
        "device_id": device_id,
        "session_id": session_id,
        "message_preview": message[:120],
        "note": "Fire-and-forget. Watch journalctl for CHAT REQUEST / CHAT COMPLETE.",
    }


@router.post("/reload/{device_id}", dependencies=[Depends(verify_admin_token)])
async def reload_panel(device_id: str) -> Any:
    """Push a soft reload to every open KUKI panel WebSocket for this device.

    Sends {"type": "reload"} — the frontend's WS handler responds with
    `location.reload()`. Re-fetches kukai_chat_v5.html fresh from the server
    (static.py serves it uncached), so any HTML/JS-only change (self-heal
    shim, per-device markers, etc.) takes effect with zero user action —
    no closing/reopening Revit needed. Does NOT update the C# bridge itself
    (that still requires the normal OTA/UpdateChecker path on next launch).
    """
    from kukai.api.chat_ws import _device_websockets, _send_json

    ws_set = _device_websockets.get(device_id)
    if not ws_set:
        return _ws_not_found_response(device_id)

    sent = 0
    for ws in list(ws_set):
        try:
            await _send_json(ws, {"type": "reload"})
            sent += 1
        except Exception:
            logger.exception("[admin/remote/reload] send failed device=%s", device_id)

    logger.info("[admin/remote/reload] pushed reload to %d socket(s) device=%s", sent, device_id)
    return {"status": "sent", "device_id": device_id, "sockets_notified": sent}


@router.post("/cancel/{device_id}", dependencies=[Depends(verify_admin_token)])
async def cancel_turn(device_id: str) -> Any:
    """Погасить идущий ход на устройстве — снаружи, не трогая сервер.

    ЗАЧЕМ. 29.07 ход оператора ушёл в бесконечную самопроверку (176 чтений
    против 5 записей: критерий «1в1 с Эйфелевой башней» система проверить не
    может даже в принципе, поэтому у цикла не было условия выхода). Остановить
    его можно было только кнопкой в клиенте — снаружи рычага не существовало, и
    я потянулся к перезапуску бэкенда. Перезапуск оборвал ход на середине и
    оставил человека в тишине; это был неверный инструмент.

    На флоте цена выше: зациклившийся агент на чужой машине жжёт общую квоту
    подписки, а владельца может не быть за экраном.

    Делает ровно то же, что кнопка отмены в чате: снимает задачу хода И
    отпускает висящие запросы к мосту. Без второго зашифрованная программа
    (нередко >50 КБ) вместе со своим ожиданием провисела бы до собственного
    таймаута в 75 минут — «отменил» должно значить «забыли сейчас».
    """
    from kukai.api import ws_registry as _wsreg
    from kukai.api.chat_ws import _pending_bridge_requests

    ws_ids = _wsreg.ws_ids_for_device(device_id)
    if not ws_ids:
        return {"status": "no_connection", "device_id": device_id,
                "detail": "устройство не на связи — гасить нечего"}

    cancelled_tasks = 0
    dropped_requests = 0
    for ws_id in ws_ids:
        for req_id, (owner_ws_id, future) in list(_pending_bridge_requests.items()):
            if owner_ws_id == ws_id:
                if not future.done():
                    future.set_exception(ConnectionError("Cancelled by operator"))
                _pending_bridge_requests.pop(req_id, None)
                dropped_requests += 1
        task = _wsreg.chat_task_for(ws_id)
        if task is not None and not task.done():
            task.cancel()
            cancelled_tasks += 1

    logger.info(
        "[admin/remote/cancel] device=%s сокетов=%d ходов снято=%d запросов моста отпущено=%d",
        device_id, len(ws_ids), cancelled_tasks, dropped_requests)
    return {
        "status": "cancelled" if cancelled_tasks else "idle",
        "device_id": device_id,
        "sockets": len(ws_ids),
        "turns_cancelled": cancelled_tasks,
        "bridge_requests_dropped": dropped_requests,
    }


@router.post("/exec/{device_id}", dependencies=[Depends(verify_admin_token)])
async def exec_csharp(
    device_id: str,
    payload: dict[str, Any],
) -> Any:
    """Run arbitrary C# in Revit on the target device. Admin escape hatch.

    Body: { "code": "<C# source>", "timeout_ms": 30000 }

    The code is sent as a bridge `execute` request — the SAME path
    chat-driven `execute_revit_code` uses. Roslyn validates against the
    allowed-assembly list before running; System.IO/Net/Diagnostics are
    blocked at compile time.

    Use cases for the audit:
      - probe Revit state without going through Gemini
      - reproduce CS0117/CS1061 hallucinations to verify the failure mode
      - test repair-loop behavior by sending intentionally-bad code
    """
    code = payload.get("code", "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' in body")
    timeout_ms = int(payload.get("timeout_ms", 30000))
    return await _send_bridge_request(
        device_id=device_id,
        method="execute",
        params={"code": code, "timeout_ms": timeout_ms},
        timeout_s=(timeout_ms / 1000) + 10,
        # Необязателен ради совместимости, но настоятельно рекомендован:
        # без него окно выбирает сервер, и при двух открытых Revit код
        # уходит туда, куда он решил.
        doc_contains=str(payload.get("doc_contains") or ""),
    )


async def _send_bridge_request(
    *,
    device_id: str,
    method: str,
    params: dict[str, Any],
    timeout_s: float,
    doc_contains: str = "",
) -> Any:
    """Common path: reuse production `_bridge_callback` from chat_ws.

    Earlier version of this function duplicated the bridge_request build
    logic and sent unencrypted payloads. That worked for `export_view` and
    `context` (no encryption needed) but FAILED for `execute` — bridge
    expects `encrypted_code` after AES-256-CBC obfuscation, and an
    unencrypted `code` field returns "No code provided" from the bridge.

    The proper path is to call `_bridge_callback(ws, ws_id, method, params)`
    from `chat_ws` which handles:
      * code fixer + safety re-validation (for execute)
      * wrap → obfuscate → AES encrypt with `_session_keys[ws_id]`
      * pending-future registration in `_pending_bridge_requests`
      * Roslyn pre-flight compile check
      * send + await response + decrypt

    This thin admin shim becomes a wrapper that authenticates and routes
    to the same production path used by the chat flow.
    """
    import asyncio as _asyncio
    from kukai.api.chat_ws import _device_websockets, _bridge_callback

    ws_set = _device_websockets.get(device_id)
    if not ws_set:
        # 503 instead of 404 — see _ws_not_found_response docstring.
        # FastAPI accepts a Response from a path-operation function's call
        # chain and uses it directly; the caller routes pass this through.
        return _ws_not_found_response(device_id)

    # Выбор ОКНА, а не устройства.
    #
    # Прежний код брал `next(iter(ws_set))` — «первое живое соединение», и в
    # комментарии рядом честно признавал: «Multi-Revit: caller can re-request
    # to hit other connections». Повтор попадает в то же самое окно, то есть
    # выбора не было вовсе.
    #
    # ЗАМЕР 28.07: у оператора открыты два Revit. Запрос с явным ожиданием
    # документа `SOB_ATR` фактически ушёл в `SKLNK_ЭОМ`; позже все вызовы
    # стали уходить в окно Revit 2023 со сломанной надстройкой, и рабочее
    # окно стало НЕДОСТИЖИМО. Для чтения это портит замер, для записи это
    # запись не в тот документ — тот самый молчаливо-неверный исход, который
    # этот проект объявляет невыразимым.
    #
    # `doc_contains` работает как у `/admin/kir/*` (`_match_admin_ws`), и
    # ОТКАЗЫВАЕТ, если подходящего окна нет: «взять первое попавшееся»
    # вместо запрошенного — именно та ошибка, которую параметр устраняет.
    ws = None
    if doc_contains:
        from kukai.api.chat_ws import _session_contexts
        needle = doc_contains.strip().lower()
        matches = []
        for candidate in ws_set:
            wid = _find_ws_id_for_websocket(candidate)
            name = str((_session_contexts.get(wid or "") or {}).get(
                "document_name") or "")
            if needle in name.lower():
                matches.append((candidate, name))
        if not matches:
            raise HTTPException(
                status_code=404,
                detail=(f"нет окна с документом, содержащим {doc_contains!r}; "
                        "открытые: " + ", ".join(sorted(
                            str((_session_contexts.get(
                                _find_ws_id_for_websocket(c) or "") or {}
                            ).get("document_name") or "?")
                            for c in ws_set))),
            )
        # Несколько совпадений — тоже неоднозначность, и молча выбирать
        # нельзя: уточнить запрос дешевле, чем угадать не тот документ.
        if len(matches) > 1:
            raise HTTPException(
                status_code=409,
                detail=("под условие подходит несколько окон: "
                        + ", ".join(name for _c, name in matches)),
            )
        ws = matches[0][0]
    if ws is None:
        ws = next(iter(ws_set))

    # _bridge_callback needs the ws_id that owns this WS so it can look up
    # the per-session AES key. We reverse-lookup it from the global registry.
    from kukai.api.chat_ws import _session_keys
    ws_id = _find_ws_id_for_websocket(ws)
    if not ws_id:
        # No ws_id known → encryption keys also unknown → exec will fail.
        # Non-execute methods (export_view, context) still work.
        logger.warning(
            "[admin/remote] device=%s method=%s: no ws_id mapping found "
            "(execute will fail; other methods OK)",
            device_id, method,
        )

    started = time.time()
    try:
        result = await _asyncio.wait_for(
            _bridge_callback(ws, ws_id or "", method, params, actor={"device_id": device_id}),
            timeout=timeout_s,
        )
    except _asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Plugin did not respond within {timeout_s}s",
        )

    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(
        "[admin/remote] device=%s method=%s elapsed_ms=%d",
        device_id, method, elapsed_ms,
    )
    return {
        "device_id": device_id,
        "method": method,
        "elapsed_ms": elapsed_ms,
        "result": result,
    }


def _find_ws_id_for_websocket(target_ws: Any) -> Optional[str]:
    """Reverse-lookup ws_id from a WebSocket object via the direct
    mapping `_ws_object_to_ws_id` populated in chat_ws on connect.
    Returns None if the WS isn't tracked (e.g. cleaned up already)."""
    from kukai.api.chat_ws import _ws_object_to_ws_id
    return _ws_object_to_ws_id.get(id(target_ws))
