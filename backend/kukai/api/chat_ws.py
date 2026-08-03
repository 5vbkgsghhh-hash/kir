"""WebSocket chat endpoint — primary streaming interface.

Message types sent TO client:
  - stream_start: LLM started generating text
  - stream_chunk: { text: "..." } — partial text
  - tool_start: { tool: "tool_name" } — tool execution began
  - tool_end: { result: "..." } — tool execution finished
  - stream_end: LLM finished generating
  - error: { error: "message" }
  - pong: keepalive response
  - session_key: { key: "base64" } — AES session key (sent once on connect)
  - identity: { token: "..." } — Step 11 (KUKAI_SIGNED_IDENTITY, flag-gated):
      server-minted signed identity; client stores it and re-presents it as
      `identity_token` on auth/chat payloads. Never sent when the flag is OFF.
  - bridge_request: { id: "uuid", encrypted_code: "...", method: "...", params: {...} }
  - context_ack: confirmation that context was received

Message types received FROM client:
  - chat: { message, session_id, preferences[, identity_token] }
  - cancel: { session_id } — cancel running chat task
  - ping: keepalive
  - auth: { token, device_id[, identity_token] } — credentials / identity
  - context: { data: {...} } — Revit model context from client
  - bridge_response: { id: "...", result: {...} } — result of bridge execution
"""

from __future__ import annotations

import asyncio
import base64
import hmac
import json
import logging
import os
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query

from kukai.config import get_settings
from kukai import turn_ledger as _tl  # TurnLedger v1 (KUKAI_TURN_LEDGER); stdlib-only, no-op when off
from kukai.llm import tool_observation as _tobs  # Phase 4 — unified per-turn observations (shadow)
from kukai.turn.context import TurnContext, TurnRunResult  # golden-path B2: prepare/run descriptors
from kukai.discovery import DiscoveryCache
from kukai.llm.envelope import (
    ErrCode,
    attach_err,
    classify_bridge_error,
    extract_cs_codes,
    friendly_bridge_message,
    result_is_error as _result_is_error,
)
from kukai.security.egress_filter import egress_mode as _egress_mode
from kukai.security.egress_filter import scrub_payload as _scrub_payload
from kukai.security.encryption import SessionEncryption
from kukai.security.obfuscator import obfuscate_code
from kukai.storage.models import Message

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Golden-path Phase 1 (2026-07-12, /root/kukai-golden-path-plan.md): the
# transport layer was peeled out of this file into kukai/api/{ws_send,
# ws_registry,bridge_protocol}.py as PURE MOVES (zero behavior change). The
# names below are re-exported so every existing importer (admin_remote,
# licensing/admin_api, graph_api, main, modeling's wrapper-sync test) and
# tests that monkeypatch `chat_ws.<name>` keep working. The state dicts are
# the SAME objects (shared by reference; mutated in place, never rebound).
from kukai.api.ws_send import (  # noqa: F401
    _WS_SEND_TIMEOUT_S,
    _emit_status,
    _send_json,
)
from kukai.api.ws_registry import (  # noqa: F401
    SESSION_INACTIVITY_TTL,
    _adapt_flat_context,
    _bridge_serialize_enabled,
    _bridge_serialize_locks,
    _build_model_details,
    _conn_identities,
    _device_websockets,
    _discovery_caches,
    _get_bridge_serialize_lock,
    _get_context_for_session,
    _handle_context,
    _handle_detailed_passport,
    _session_contexts,
    _session_detailed_passports,
    _session_keys,
    _session_last_activity,
    _session_states,
    _ws_object_to_ws_id,
    cleanup_stale_sessions,
    get_active_ws_count,
    send_ws_message,
)
from kukai.api.bridge_protocol import (  # noqa: F401
    BRIDGE_REQUEST_TIMEOUT,
    _BRIDGE_CHANGE_MANIFESTS_MAX,
    _accept_bridge_response,
    _EXECUTE_BRIDGE_TIMEOUT_S,
    _WRAPPER_FOOTER,
    _WRAPPER_HEADER,
    _WRAPPER_LINE_OFFSET,
    _bridge_callback,
    _bridge_change_manifests,
    _change_witness_enabled,
    _drain_witness,
    _effective_bridge_timeout,
    _handle_bridge_response,
    _handle_bridge_phase,
    _manifest_counts,
    _pending_bridge_requests,
    _pending_bridge_operations,
    _bridge_receipts,
    _bridge_receipt_hashes,
    _record_witness,
    _stash_change_manifest,
    _witness_log_path,
)


# Connection limit per IP to prevent DoS via WS spam
MAX_CONNECTIONS_PER_IP = int(os.getenv("KUKAI_MAX_CONN_PER_IP", "40"))
_ip_connection_count: dict[str, int] = {}
_ip_lock = asyncio.Lock()

# Graceful degradation: cap active chat tasks to prevent overload.
# Users beyond the limit get "server busy" instead of timeout.
MAX_ACTIVE_CHATS = 3000
_active_chat_count = 0

# --- Light per-device rate limits (auth is off → these protect the public WS
# from token-drain / floods WITHOUT throttling real work). Config-driven and
# FAIL-OPEN: any error → the turn is allowed. We limit what the USER initiates
# (chat turns + total daily input-tokens), NEVER the AI's internal tool rounds
# (those are already bounded per-turn by rounds_max + the wall-clock budget).
TURNS_PER_MIN = int(os.getenv("KUKAI_TURNS_PER_MIN", "20"))
TURNS_PER_DAY = int(os.getenv("KUKAI_TURNS_PER_DAY", "500"))
TOKENS_PER_DAY = int(os.getenv("KUKAI_TOKENS_PER_DAY", "10000000"))
_dev_turn_times: dict[str, deque] = {}   # device -> recent turn monotonic ts (per-min window)
_dev_day: dict[str, list] = {}           # device -> [date_str, turn_count, token_sum]


def _today_utc() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _dev_day_slot(device_id: str) -> list:
    d = _today_utc()
    slot = _dev_day.get(device_id)
    if slot is None or slot[0] != d:
        slot = [d, 0, 0]
        _dev_day[device_id] = slot
    return slot


def check_and_count_turn(device_id: str) -> Optional[str]:
    """Light, FAIL-OPEN per-device rate limit. Returns a reason string when over
    a limit (the caller rejects the turn); otherwise None AND records the turn.
    Counts the USER's turns + reads today's token total — never the AI's rounds."""
    try:
        if not device_id:
            return None
        slot = _dev_day_slot(device_id)
        if slot[2] >= TOKENS_PER_DAY:
            return "token_ceiling"
        if slot[1] >= TURNS_PER_DAY:
            return "daily_cap"
        now = time.monotonic()
        dq = _dev_turn_times.get(device_id)
        if dq is None:
            dq = deque()
            _dev_turn_times[device_id] = dq
        while dq and now - dq[0] > 60.0:
            dq.popleft()
        if len(dq) >= TURNS_PER_MIN:
            return "per_minute"
        dq.append(now)
        slot[1] += 1
        # bound memory (rare prod-restart cleanup)
        if len(_dev_turn_times) > 5000:
            _dev_turn_times.clear()
        if len(_dev_day) > 20000:
            _td = _today_utc()
            for k in [k for k, v in _dev_day.items() if v[0] != _td]:
                _dev_day.pop(k, None)
        return None
    except Exception:  # noqa: BLE001 — a rate limit must never break a turn
        return None


def add_device_tokens(device_id: str, n: Optional[int]) -> None:
    """Accumulate a turn's input tokens into the device's daily total (fail-open)."""
    try:
        if device_id and n:
            _dev_day_slot(device_id)[2] += int(n)
    except Exception:  # noqa: BLE001
        pass


def _fold_usage_into_metrics(metrics: Any, usage: Any) -> None:
    """Step 1: fold a `usage` StreamEvent's tokens into the per-turn metrics row
    (accumulating across rounds). The event was produced but never consumed, so
    the token columns stayed NULL and the daily anti-drain ceiling never fired."""
    if metrics is None or not isinstance(usage, dict):
        return
    p = usage.get("prompt_tokens")
    c = usage.get("cached_tokens")
    if p is not None:
        metrics.total_input_tokens = (metrics.total_input_tokens or 0) + p
    if c is not None:
        metrics.cached_input_tokens = (metrics.cached_input_tokens or 0) + c


def _record_suppressed_error(metrics: Any, reasoning_trace: Any, err: Any) -> None:
    """Step 1: un-blind the error channel. A silently-retried error must still
    reach telemetry AND the reasoning trace (the nightly grader's source) — the
    retry `break` fires before both, so today errors are structurally invisible."""
    if metrics is not None and not getattr(metrics, "error", ""):
        metrics.error = f"silent_retry:{str(err)[:80]}"
    if reasoning_trace is not None:
        try:
            reasoning_trace.on_error(err)
        except Exception:  # noqa: BLE001
            pass


# Step 6: markers of DETERMINISTIC errors — retrying them is a pointless storm.
_DETERMINISTIC_ERR_MARKERS = (
    "unsupportedparams", "does not support", "not valid", "invalid",
    "blocked", "заблокир", "unprocessable", "http 400", "http 401", "http 403", "http 422",
    " 400 ", " 401 ", " 403 ", " 422 ",
)


def _is_retryable_error(err: Any) -> bool:
    """Step 6: only transient errors (timeout, 5xx, temporarily-unavailable) are
    worth a silent retry; a deterministic error (bad param, blocked, 4xx) can
    never succeed on retry, so surface it instead of storming."""
    s = str(err).lower()
    return not any(m in s for m in _DETERMINISTIC_ERR_MARKERS)


# B1 (KUKAI_AUTOSHOW_WITNESSED) — the auto-show/vision trigger decision.
_WRITE_TOOLS = ("execute_revit_code", "apply_revit_write")


def autoshow_should_fire(write_ok: bool, wrote_heuristic: bool, witnessed_mode: bool) -> bool:
    """Whether the post-turn auto-show/vision should fire.

    * witnessed_mode ON  → fire ONLY on a real WRITE SUCCESS (a write tool that
      returned non-error) — so nothing fires after a FAILED write on a stale
      selection (the reported bug).
    * witnessed_mode OFF → legacy behavior: fire when a write tool was CALLED
      (the tool-name heuristic), regardless of whether it actually succeeded.
    """
    return bool(write_ok) if witnessed_mode else bool(wrote_heuristic)


# B3 — background outbox for best-effort work that must NOT block or break a turn
# (project-memory extraction, etc.). A strong ref is held until completion so the
# loop can't GC a pending task, and errors are logged, never re-raised (no
# "Task exception never retrieved").
_BG_TASKS: "set[asyncio.Task[Any]]" = set()


def _spawn_bg(coro: Any, label: str) -> "asyncio.Task[Any]":
    """Enqueue a detached fire-and-forget task; return it (callers may ignore)."""
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)

    def _done(t: "asyncio.Task[Any]") -> None:
        _BG_TASKS.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning("background task %s failed: %s", label, exc, exc_info=exc)

    task.add_done_callback(_done)
    return task




def _int_env_chat(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:  # noqa: BLE001
        return default


def _resolve_turn_tenant(
    data: dict[str, Any], ws_id: str, device_id: str,
) -> tuple[str, bool, Optional[str]]:
    """Resolve the EFFECTIVE tenancy isolation key for one inbound message.

    Returns (tenant_id, from_signed_identity, mint_token_to_send_or_None).
    Flag OFF → (device_id, False, None) — the exact legacy key, no state
    allocated. Flag ON → kukai.security.identity.resolve_for_turn with this
    connection's holder. NEVER raises (fail-open to legacy device_id).
    """
    try:
        from kukai.security import identity as _sid
        if not _sid.signed_identity_enabled():
            return device_id, False, None
        holder = _conn_identities.get(ws_id)
        if holder is None:
            holder = _sid.new_holder()
            _conn_identities[ws_id] = holder
        return _sid.resolve_for_turn(data, holder, device_id)
    except Exception:  # noqa: BLE001 — identity must never break a turn
        logger.warning(
            "signed-identity: tenant resolve failed — FAIL-OPEN to device_id",
            exc_info=True,
        )
        return device_id, False, None



# [MARATHON-F021] Per-receive idle timeout. If no message arrives within
# this window, we close the WebSocket and free the IP-slot. With the JS
# client now ping-ing every 5s ([MARATHON-F001-mitigation]), any live
# session will see traffic well inside this window. The previous code did
# `await websocket.receive_text()` with no timeout — a client could
# connect, send nothing, and hold the slot indefinitely (until TCP-FIN).
# This was a DoS vector: 50 idle connections = `limit_conn` exhausted.
WS_RECEIVE_TIMEOUT_S = 60



def get_active_chat_count() -> int:
    """Return the number of currently active chat tasks."""
    return _active_chat_count




async def _decrement_ip(client_ip: str) -> None:
    """Decrement IP connection counter (call from finally or early return)."""
    async with _ip_lock:
        if client_ip and _ip_connection_count.get(client_ip, 0) > 0:
            _ip_connection_count[client_ip] -= 1
            if _ip_connection_count[client_ip] <= 0:
                _ip_connection_count.pop(client_ip, None)


@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    device_token: str = Query(""),
    api_key: str = Query(""),
    device_id: str = Query(""),
) -> None:
    """WebSocket endpoint for streaming chat.

    Authentication: The client should send credentials in the first WebSocket
    message as { type: "auth", token: "...", device_id: "..." } instead of
    query parameters (which can be logged by proxies/load balancers).

    Legacy support: Query parameter auth still works for backward compatibility.
    """
    settings = get_settings()

    # Track client IP for connection limiting
    client_ip = ""
    if websocket.client:
        client_ip = websocket.client.host or ""

    # Accept connection first (required by ASGI protocol before any send/close)
    await websocket.accept()

    # Connection limit per IP — close immediately after accept if exceeded
    if client_ip:
        async with _ip_lock:
            current = _ip_connection_count.get(client_ip, 0)
            if current >= MAX_CONNECTIONS_PER_IP:
                await websocket.close(code=4029, reason="Too many connections")
                return
            _ip_connection_count[client_ip] = current + 1

    # Auth info — will be populated from auth message or legacy query params
    auth_info: dict[str, Any] = {
        "device_token": "",
        "device_id": device_id,
        "tier": "free",
        "daily_limit": 0,  # DISABLED: free trial period — unlimited
        "authenticated": False,
    }

    if settings.auth_enabled:
        # Try to authenticate from the first message (preferred: no tokens in URL)
        auth_info = await _authenticate_ws(
            websocket, settings, device_token, api_key, device_id
        )
        if auth_info is None:
            await _decrement_ip(client_ip)
            return  # Connection was closed by _authenticate_ws
        # Log license issues server-side only — never send to client
        if auth_info.get("license_error"):
            logger.info("License issue for device %s: %s", device_id, auth_info["license_error"])
    else:
        # No auth required — check for legacy query params for device_id
        if not device_id:
            # Try to get device_id from first auth message if sent
            pass  # device_id remains empty, which is fine for local mode

    # In remote mode, refuse to send session key over unencrypted connections.
    # Check actual protocol, considering reverse proxy (X-Forwarded-Proto header).
    # Exception: localhost connections (127.0.0.1, ::1) are allowed without WSS for development.
    if settings.remote_mode:
        headers_list = websocket.scope.get("headers", [])
        forwarded_proto = ""
        for hdr_name, hdr_value in headers_list:
            if hdr_name == b"x-forwarded-proto":
                forwarded_proto = hdr_value.decode("latin-1")
                break
        is_secure = websocket.scope.get("scheme") == "wss" or forwarded_proto == "https"
        # Allow localhost without WSS for local development
        is_localhost = client_ip in ("127.0.0.1", "::1", "localhost")
        if not is_secure and not is_localhost:
            logger.critical(
                "SECURITY: Refusing to send AES session key over unencrypted "
                "WebSocket in remote mode. Client must connect via WSS/HTTPS."
            )
            await websocket.close(
                code=4003,
                reason="Requires secure connection (WSS/HTTPS)",
            )
            await _decrement_ip(client_ip)
            return

    # Generate session encryption key and send to client
    ws_id = str(uuid.uuid4())
    session_key = SessionEncryption.generate_key()
    _session_keys[ws_id] = session_key
    _session_contexts[ws_id] = {}
    _discovery_caches[ws_id] = DiscoveryCache()
    from kukai.state.session_state import SessionState
    _session_states[ws_id] = SessionState()
    _session_last_activity[ws_id] = time.time()
    # [MARATHON-REMOTE-LOOKUP] Register ws-object → ws_id mapping so
    # /admin/remote/* endpoints can look up the encryption key for this
    # device's WebSocket.
    _ws_object_to_ws_id[id(websocket)] = ws_id

    await _send_json(websocket, {
        "type": "session_key",
        "key": base64.b64encode(session_key).decode("ascii"),
    })

    logger.info("WebSocket connected: device_id=%s tier=%s ws_id=%s", device_id, auth_info.get("tier"), ws_id)

    # Register in device->ws registry so background tasks can push messages.
    # Multiple Revit processes on the same machine share device_id — store as a set.
    if device_id:
        _device_websockets.setdefault(device_id, set()).add(websocket)

    chat_task: Optional[asyncio.Task[None]] = None

    async def _turn_heartbeat(turn_task: "asyncio.Task[None]", started: float) -> None:
        """[2026-07-19] Server half of the client's heartbeat contract.

        kukai_chat_v5.html has handled `{"type":"heartbeat","elapsed_s":N}`
        since Phase 7.3 (tracks __lastHeartbeatTs, re-syncs its thinking
        timer) — but the server never sent the frame. During a long MiMo
        generation the pipe goes silent for 60-200s and dies with 1006,
        losing the finished answer (2026-07-18 incident). While the chat
        turn runs, confirm liveness every 10s. Self-terminating on turn
        completion; a send failure just ends it (the read loop owns real
        error handling). Does NOT touch MARATHON-F021 idle-timeout: that
        guards the receive side for clients with no active turn."""
        try:
            while not turn_task.done():
                await asyncio.sleep(10)
                if turn_task.done():
                    break
                await _send_json(websocket, {
                    "type": "heartbeat",
                    "elapsed_s": round(time.time() - started, 1),
                })
        except asyncio.CancelledError:
            raise
        except Exception:
            pass  # closed/failing socket — the read loop handles the real error

    try:
        while True:
            try:
                # [MARATHON-F021] Bounded wait. Without this, a client that
                # connected but sent nothing held its slot forever.
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=WS_RECEIVE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.info(
                    "WebSocket idle timeout (%ds) — closing device_id=%s ws_id=%s",
                    WS_RECEIVE_TIMEOUT_S, device_id, ws_id,
                )
                try:
                    await websocket.close(code=1001, reason="Idle timeout")
                except Exception:
                    pass
                break
            if len(raw) > 15_000_000:
                await _send_json(websocket, {"type": "error", "error": "Сообщение слишком длинное"})
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await _send_json(websocket, {"type": "error", "error": "Некорректный формат данных"})
                continue

            msg_type = data.get("type", "")

            # Keep session alive — update activity timestamp on every message
            _session_last_activity[ws_id] = time.time()

            if msg_type == "ping":
                await _send_json(websocket, {"type": "pong"})
                continue

            if msg_type == "chat":
                # FIX 3A: Run chat handler as background task so read loop continues
                # processing bridge_response messages while chat awaits them.
                if chat_task and not chat_task.done():
                    await _send_json(websocket, {"type": "error", "error": "Предыдущий запрос ещё обрабатывается"})
                    continue
                # Graceful degradation: reject if server is overloaded
                if _active_chat_count >= MAX_ACTIVE_CHATS:
                    await _send_json(websocket, {"type": "error", "error": "Сервер перегружен. Попробуйте через минуту."})
                    continue
                chat_task = asyncio.create_task(
                    _tracked_handle_chat(websocket, data, device_id, auth_info, ws_id)
                )
                # Регистрируем ход, чтобы его можно было погасить снаружи
                # (admin/remote/cancel). Снимаем с учёта по завершении — иначе
                # словарь копил бы мёртвые задачи всю жизнь процесса.
                from kukai.api import ws_registry as _wsreg
                _wsreg.register_chat_task(ws_id, chat_task)
                chat_task.add_done_callback(
                    lambda _t, _w=ws_id: _wsreg.unregister_chat_task(_w))
                # Keepalive sibling for the turn (see _turn_heartbeat above).
                _spawn_bg(_turn_heartbeat(chat_task, time.time()),
                          f"turn-heartbeat:{ws_id}")
                continue

            if msg_type == "context":
                await _handle_context(data, ws_id, websocket)
                # A6: warm the census for this model-state (KUKAI_PERCEPTION_WARM,
                # default OFF) so the FIRST chat turn pays ~0 for the passport.
                _launch_perception_warm(websocket, ws_id)
                await _send_json(websocket, {"type": "context_ack"})
                continue

            if msg_type == "detailed_passport":
                await _handle_detailed_passport(data, ws_id)
                continue

            if msg_type == "bridge_response":
                # B5: pass the delivering connection so a response can only
                # resolve a request owned by that same connection.
                await _accept_bridge_response(
                    data,
                    sender_ws_id=ws_id,
                    device_id=device_id,
                    ws=websocket,
                )
                continue

            if msg_type == "bridge_phase":
                await _handle_bridge_phase(
                    data,
                    sender_ws_id=ws_id,
                    device_id=device_id,
                )
                continue

            if msg_type == "bridge_progress":
                # Forward batch operation progress from C# bridge to chat UI
                progress = data.get("progress", {})
                await _send_json(websocket, {
                    "type": "tool_progress",
                    "current": progress.get("current", 0),
                    "total": progress.get("total", 0),
                    "message": progress.get("message", ""),
                })
                continue

            if msg_type == "cancel":
                # Cancel running chat task and IMMEDIATELY drop any pending
                # bridge requests for this session. Without this drop, the
                # encrypted code payload (often >50 KB) plus its asyncio future
                # would sit in _pending_bridge_requests until the per-request
                # timeout fires (75 min). Cancel must mean "forget this now".
                cancelled_count = 0
                for req_id, (owner_ws_id, future) in list(_pending_bridge_requests.items()):
                    if owner_ws_id == ws_id:
                        if not future.done():
                            future.set_exception(
                                ConnectionError("Cancelled by user")
                            )
                        _pending_bridge_requests.pop(req_id, None)
                        cancelled_count += 1
                if cancelled_count:
                    logger.info(
                        "Cancel: dropped %d pending bridge requests for ws_id=%s",
                        cancelled_count, ws_id,
                    )
                if chat_task and not chat_task.done():
                    chat_task.cancel()
                    logger.info("Chat task cancelled by user: ws_id=%s", ws_id)
                    await _send_json(websocket, {"type": "stream_end"})
                continue

            if msg_type == "auth":
                # Auth message received in main loop — this happens when:
                # 1) auth_enabled=False (local mode) but client still sends auth
                # 2) Duplicate/late auth message after initial auth was already processed
                # Extract device_id if we don't have one yet.
                if not device_id and data.get("device_id"):
                    device_id = data["device_id"]
                    # Register late device_id in WS registry (multi-instance: set semantics)
                    _device_websockets.setdefault(device_id, set()).add(websocket)
                    # P4: the "WebSocket connected" log fires with an EMPTY device_id (the
                    # auth/hello arrives after accept). Log the real identity now so brick
                    # outreach (scripts/bricked_devices.py) can join brick errors → real
                    # devices — the accurate reinstall list, which is the fleet's heal path.
                    logger.info("WS device identified: device_id=%s ws_id=%s", device_id, ws_id)
                # Step 11 (KUKAI_SIGNED_IDENTITY, flag-gated): resolve the signed
                # connection identity from the auth payload; when the client has
                # no valid token yet, mint one and return it (the client stores
                # it and re-presents it as `identity_token`). Flag OFF ⇒
                # _resolve_turn_tenant returns immediately, nothing is sent.
                _t11_tenant, _t11_signed, _t11_mint = _resolve_turn_tenant(
                    data, ws_id, device_id
                )
                if _t11_mint:
                    try:
                        await _send_json(websocket, {"type": "identity", "token": _t11_mint})
                    except Exception:  # noqa: BLE001 — identity offer is best-effort
                        logger.debug("signed-identity: mint send failed (non-fatal)")
                continue

            # IFC message routing ARCHIVED 2026-06-10 (operator: archive Gemini+IFC+VOR).
            # ifc_* messages now fall through to "unknown type". Restore: re-add the
            # handle_ifc_message dispatch (see kukai/_archive/RESTORE.md).

            logger.warning("Unknown WS message type from device_id=%s: %s", device_id, msg_type[:50])
            await _send_json(websocket, {"type": "error", "error": "Неизвестный тип сообщения"})

    except WebSocketDisconnect as _disc:
        # [MARATHON-F001-diagnostic] Capture close code + reason so we can
        # finally identify who initiates the ~7-second disconnect cycle
        # observed in production for device_id=16e4c54b....
        #   • 1000 = normal close from client (user closed Revit)
        #   • 1001 = going away (navigation/refresh)
        #   • 1006 = abnormal closure (TCP cut, no close-frame) — proxy/network
        #   • 1011 = server error from client side
        #   • 4001 = our backend auth reject
        # Without this, all the journal says is "disconnected" — no signal.
        _code = getattr(_disc, "code", None)
        _reason = getattr(_disc, "reason", "") or ""
        logger.info(
            "WebSocket disconnected: device_id=%s ws_id=%s close_code=%s reason=%r",
            device_id, ws_id, _code, _reason[:80],
        )
    except Exception:
        logger.exception("WebSocket error")
        try:
            await _send_json(websocket, {"type": "error", "error": "Ошибка соединения"})
        except Exception:
            pass
    finally:
        # Cancel running chat task if any
        if chat_task and not chat_task.done():
            chat_task.cancel()

        # Decrement IP connection counter
        await _decrement_ip(client_ip)

        # Unregister from device->ws registry. Only drop THIS websocket — leaves any
        # other Revit instances that share the same device_id intact.
        if device_id:
            ws_set = _device_websockets.get(device_id)
            if ws_set is not None:
                ws_set.discard(websocket)
                if not ws_set:
                    _device_websockets.pop(device_id, None)

        # Cleanup session state
        _session_keys.pop(ws_id, None)
        _session_contexts.pop(ws_id, None)
        _session_detailed_passports.pop(ws_id, None)
        _discovery_caches.pop(ws_id, None)
        _session_states.pop(ws_id, None)
        _session_last_activity.pop(ws_id, None)
        _conn_identities.pop(ws_id, None)  # Step 11: signed-identity holder
        _bridge_serialize_locks.pop(ws_id, None)  # bridge serialization lock
        # [MARATHON-REMOTE-LOOKUP] Drop ws-object → ws_id mapping.
        _ws_object_to_ws_id.pop(id(websocket), None)
        # FIX 6: Only cancel pending bridge requests for THIS session, not all sessions
        for req_id, (owner_ws_id, future) in list(_pending_bridge_requests.items()):
            if owner_ws_id == ws_id:
                if not future.done():
                    future.set_exception(ConnectionError("WebSocket disconnected"))
                _pending_bridge_operations.pop(req_id, None)
                _bridge_receipts.pop(req_id, None)
                _bridge_receipt_hashes.pop(req_id, None)
                del _pending_bridge_requests[req_id]


AUTH_TIMEOUT = 20.0  # seconds to wait for auth message


async def _authenticate_ws(
    ws: WebSocket,
    settings: Any,
    legacy_device_token: str,
    legacy_api_key: str,
    legacy_device_id: str,
) -> Optional[dict[str, Any]]:
    """Authenticate WebSocket connection.

    Preferred flow: client sends { type: "auth", token: "...", device_id: "..." }
    as the first message. This avoids exposing tokens in URL query strings.

    Legacy flow: tokens passed via query parameters (backward compatible).

    Returns auth_info dict on success, None if connection was closed.
    """
    from kukai.main import get_app_state

    state = get_app_state()

    device_token = legacy_device_token
    api_key = legacy_api_key
    device_id = legacy_device_id

    client_hwid = ""

    # If no legacy credentials, wait for auth message
    if not device_token and not api_key:
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=AUTH_TIMEOUT)
            data = json.loads(raw)
            if data.get("type") == "auth":
                # The "token" field may contain either a device token or an API key.
                # Route to the correct auth path based on prefix.
                auth_token = data.get("token", "")
                if auth_token.startswith("KUKAI-DT-"):
                    device_token = auth_token
                else:
                    # Could be a plain API key for simple auth
                    api_key = auth_token
                if data.get("device_id"):
                    device_id = data["device_id"]
                # Extract HWID for verification
                client_hwid = data.get("hwid", "")
            else:
                # Not an auth message — close with error
                await _send_json(ws, {
                    "type": "error",
                    "error": "Первое сообщение должно быть авторизацией",
                })
                await ws.close(code=4001, reason="Требуется авторизация")
                return None
        except asyncio.TimeoutError:
            await ws.close(code=4001, reason="Таймаут авторизации")
            return None
        except Exception:
            await ws.close(code=4001, reason="Ошибка авторизации")
            return None

    # S8 fix: HTML sends device token via api_key param.
    if not device_token and api_key and api_key.startswith("KUKAI-DT-"):
        device_token = api_key

    if device_token and state.license_manager:
        from kukai.licensing.license_manager import (
            InvalidTokenError,
            LicenseError,
            LicenseExpiredError,
            LicenseInactiveError,
        )
        try:
            license_info = await state.license_manager.validate_device(device_token)

            # Verify HWID if client provided one (binds token to specific hardware)
            if client_hwid:
                try:
                    hwid_ok = await state.license_manager.verify_device_hwid(
                        device_token, client_hwid,
                    )
                    if not hwid_ok:
                        logger.warning(
                            "HWID mismatch for device_id=%s — possible token sharing",
                            device_id,
                        )
                        return {
                            "device_token": "",
                            "device_id": device_id,
                            "tier": "free",
                            "daily_limit": 0,  # DISABLED: free trial period — unlimited
                            "authenticated": False,
                            "license_error": (
                                "Лицензия привязана к другому компьютеру. "
                                "Деактивируйте устройство и активируйте заново."
                            ),
                        }
                except Exception as hwid_err:
                    # HWID check failure should not block auth — log and continue
                    logger.warning("HWID verification error (non-fatal): %s", hwid_err)

            # Check if token was auto-refreshed (expired but license still valid)
            actual_token = device_token
            refreshed_token = getattr(license_info, 'refreshed_token', None)
            if refreshed_token:
                actual_token = refreshed_token
                # Send new token to client so it can persist
                try:
                    await _send_json(ws, {
                        "type": "token_refreshed",
                        "device_token": refreshed_token,
                    })
                except Exception:
                    pass

            return {
                "device_token": actual_token,
                "device_id": device_id,
                "tier": license_info.tier,
                "daily_limit": license_info.daily_limit,
                "authenticated": True,
            }
        except (InvalidTokenError, LicenseExpiredError, LicenseInactiveError, LicenseError) as e:
            # Don't close the WS — degrade to free tier instead of spamming errors
            logger.warning("Device token invalid (%s), falling back to free tier", e)
            return {
                "device_token": "",
                "device_id": device_id,
                "tier": "free",
                "daily_limit": 0,  # DISABLED: free trial period — unlimited
                "authenticated": False,
                "license_error": str(e),
            }
    elif settings.api_key and api_key and hmac.compare_digest(api_key, settings.api_key):
        return {
            "device_token": "",
            "device_id": device_id,
            "tier": "pro",
            "daily_limit": 0,
            "authenticated": True,
        }
    else:
        # No valid token — allow connection but require license activation via UI
        logger.info("No auth token provided by device %s, allowing as unauthenticated", device_id)
        return {
            "device_token": "",
            "device_id": device_id,
            "tier": "free",
            "daily_limit": 0,  # DISABLED: free trial period — unlimited
            "authenticated": False,
            "license_error": "Требуется активация лицензии",
        }


# Bound every WS send: a half-open client (TCP buffer full, never reading) used to
# block `send_text` indefinitely → the chat task hung until restart (the 210s turn
# deadline can't fire while suspended in the consumer-side send). On timeout the chat
# loop's error handler catches it and aborts cleanly.


# ── Model passport build — the census IS the perception path (A6, 2026-07-13) ─
# SCAR / cutover 2026-07-13: the legacy 3-exec enrichment pipeline
# (type_meta → vitals → graph → ModelPassport.format_v2_core) is DELETED. ONE
# read-only census pass (model_snapshot.build_census_cs) + a deterministic
# render (render_passport) IS the passport now — no per-turn prompt-cache churn,
# no mutating-`detailed` fingerprint drift. Proof anchors: KUKAI_SNAPSHOT_PASSPORT
# was fleet-ON in prod and proven (live corroborations: exact floor areas,
# never-fabricate) BEFORE this cutover. The flag is GONE from this path — the
# census is UNCONDITIONAL; ROLLBACK is now `git revert` of the A6 commit, NOT a
# flag flip. FAIL-OPEN: any census miss/empty/exception falls through to the
# honest thin fallback — ModelPassport.format_quick() + the get_model_details
# hint — which is the WHOLE passport surface on devices where the census C#
# cannot run. COUPLING NOTE: model_cache.invalidate_after_write still reads
# KUKAI_SNAPSHOT_PASSPORT (_snapshot_passport_enabled) to gate census staleness-
# drop after writes; in prod KUKAI_GESTALT_V2/KUKAI_GRAPH_V3 are ON so it fires
# regardless, but do NOT unset KUKAI_SNAPSHOT_PASSPORT in .env unless one of
# those stays on (else a count-preserving write serves a stale census).
async def _build_model_passport(ws_id: str, ws_bridge_callback) -> Optional[str]:
    """Build the injected model-passport markdown for this turn (or None).

    The census path is THE passport (unconditional, fail-open); when the census
    is unavailable it falls through to a thin format_quick fallback."""
    # --- Snapshot passport: ONE census pass → deterministic render (fail-open) ---
    try:
        basic_ctx = _session_contexts.get(ws_id, {})
        if basic_ctx:
            from kukai.query import model_cache as _mc
            from kukai.query.model_snapshot import build_census_cs, render_passport
            # Content fingerprint (same key family as the retired execs) so the
            # census is reused turn-to-turn AND is visible to
            # graph_api._cached_graph (census→graph fallback).
            fp = _mc.world_version(basic_ctx, {})

            async def _compute_census():
                from kukai.operations.effects import ReadOnlySource, mark_read_only
                _params = mark_read_only(
                    {"code": build_census_cs()},
                    ReadOnlySource.MODEL_CENSUS,
                )
                _r = await ws_bridge_callback("execute", _params)
                return _r if (isinstance(_r, dict) and not _r.get("error")) else None

            census = await _mc.get_or_compute(fp, "census", _compute_census)
            if isinstance(census, dict) and census:
                from kukai.model_passport import ModelPassport
                text = render_passport(census, basic_ctx)
                # Re-attach the PER_TURN active-context tail: prompts.py splits
                # STABLE/PER_TURN on the literal "### Активный контекст"
                # (_active_context returns that header + body), so the
                # deterministic census core stays cacheable while selection/view
                # ride the per-turn layer.
                text += "\n\n" + ModelPassport(basic_ctx)._active_context()
                logger.info(
                    "Snapshot passport for ws_id=%s (census fp=%s, %d chars)",
                    ws_id, fp, len(text),
                )
                return text
            logger.warning(
                "Snapshot passport: census unavailable (fp=%s) — falling back "
                "to format_quick [ws_id=%s]", fp, ws_id,
            )
    except Exception:  # noqa: BLE001 — the passport must never break a turn
        logger.warning(
            "Snapshot passport path failed — falling back to format_quick "
            "[ws_id=%s]", ws_id, exc_info=True,
        )

    # --- Thin fallback: census unavailable ⇒ quick passport (+ get_model_details) --
    model_passport_md: Optional[str] = None
    settings = get_settings()
    if settings.detailed_context:
        try:
            from kukai.model_passport import ModelPassport
            basic_ctx = _session_contexts.get(ws_id, {})
            if basic_ctx:
                # The LIGHT quick passport (~5K tokens) is the fallback body. The
                # heavy ~20K detail (family types, parameter tables, sheets,
                # schedules) is fetched ON DEMAND by the LLM via get_model_details.
                detailed = _session_detailed_passports.get(ws_id)
                if not detailed:
                    # A restart wipes in-memory detailed (pure plugin push, sent on
                    # model-open — the server cannot request it). Repopulate from the
                    # on-disk cache by document so the get_model_details TOOL works
                    # without waiting for the next push. NB: _session_detailed_passports
                    # is the store that TOOL reads (ws_registry._build_model_details) —
                    # this repop refeeds the tool, not just this passport.
                    try:
                        from kukai.model_passport import PassportCache
                        _cached = PassportCache().get_by_document(
                            basic_ctx.get("document_path"), basic_ctx.get("document_name"),
                        )
                        if _cached:
                            _session_detailed_passports[ws_id] = _cached
                            detailed = _cached
                            logger.info(
                                "Passport: repopulated detailed from cache for ws_id=%s (%s)",
                                ws_id, basic_ctx.get("document_name"),
                            )
                    except Exception as _rp_exc:
                        logger.debug("passport cache-repop failed (non-fatal): %s", _rp_exc)
                passport = ModelPassport(basic_ctx)
                model_passport_md = passport.format_quick()
                if detailed:
                    model_passport_md += (
                        "\n\n_Это КРАТКИЙ паспорт. Для типоразмеров семейств, таблиц "
                        "параметров, спецификаций, листов и стандартов вызови инструмент "
                        "`get_model_details` (можно секцию: structure/parameters/views/...)._"
                    )
        except Exception as e:
            logger.warning("Failed to build model passport: %s", e)
    return model_passport_md


# ── Connect-time census warm (KUKAI_PERCEPTION_WARM, default OFF) ─────────────
# The passport's census is the ONE expensive read on the request path. Warming
# it when the model context arrives (msg_type=="context" → _handle_context)
# populates the exact model_cache "census" slot _build_model_passport reads
# (same fp = world_version(basic_ctx, {})), so the FIRST chat turn on a freshly
# opened model hits a warm cache and pays ~0 for the passport. Fail-open +
# non-blocking (fire-and-forget task); throttled per content-fingerprint so a
# burst of context pushes — or two connections on the same model — share ONE
# roundtrip (model_cache has no single-flight of its own; _WARM_INFLIGHT_FPS is
# the throttle). Flag OFF ⇒ strict no-op (no task, no bridge traffic).
_WARM_INFLIGHT_FPS: set[str] = set()


async def _warm_perception_cache(ws, ws_id: str) -> None:
    """Prewarm the census slot for this session (fail-open, idempotent)."""
    try:
        basic_ctx = _session_contexts.get(ws_id, {})
        if not basic_ctx:
            return
        from kukai.query import model_cache as _mc
        from kukai.query.model_snapshot import build_census_cs
        fp = _mc.world_version(basic_ctx, {})
        # Already warm, or a warm for this exact model-state is in flight → skip
        # (no duplicate Revit roundtrip).
        if fp in _WARM_INFLIGHT_FPS or _mc.peek(fp, "census"):
            return
        _WARM_INFLIGHT_FPS.add(fp)
        try:
            async def _compute_census():
                from kukai.operations.effects import ReadOnlySource, mark_read_only
                _params = mark_read_only(
                    {"code": build_census_cs()},
                    ReadOnlySource.MODEL_CENSUS,
                )
                _r = await _bridge_callback(ws, ws_id, "execute", _params)
                return _r if (isinstance(_r, dict) and not _r.get("error")) else None

            await _mc.get_or_compute(fp, "census", _compute_census)
        finally:
            _WARM_INFLIGHT_FPS.discard(fp)
    except Exception:  # noqa: BLE001 — a warm must never break a connection
        logger.debug("perception warm failed (fail-open) [ws_id=%s]", ws_id, exc_info=True)


def _launch_perception_warm(ws, ws_id: str) -> None:
    """Fire-and-forget the census warm iff KUKAI_PERCEPTION_WARM is on."""
    if os.environ.get("KUKAI_PERCEPTION_WARM", "0").strip().lower() not in (
        "1", "true", "yes", "on"
    ):
        return
    try:
        asyncio.create_task(_warm_perception_cache(ws, ws_id))
    except RuntimeError:  # no running loop (shouldn't happen in the WS handler)
        logger.debug("perception warm: no running loop, skipped [ws_id=%s]", ws_id)


async def _tracked_handle_chat(
    ws: WebSocket,
    data: dict[str, Any],
    device_id: str,
    auth_info: dict[str, Any],
    ws_id: str,
) -> None:
    """Wrapper that tracks active chat count for graceful degradation."""
    global _active_chat_count
    _active_chat_count += 1
    try:
        await _handle_chat(ws, data, device_id, auth_info, ws_id)
    finally:
        _active_chat_count -= 1
        # TurnLedger v1: the ONE sink write — the only always-run, after-everything
        # site (the _handle_chat finally runs before the grounding/save/memory tail,
        # and 9 early returns bypass an end-of-body flush). No-op when the flag is off.
        try:
            from kukai.main import get_app_state as _gas
            await _tl.flush_turn(getattr(_gas(), "db", None))
        except Exception:  # noqa: BLE001 — the ledger must never break the turn task
            pass


async def prepare_turn(
    ws: WebSocket,
    data: dict[str, Any],
    device_id: str,
    auth_info: dict[str, Any],
    ws_id: str,
) -> Optional[TurnContext]:
    """Prepare ONE chat turn: run phases 1-9 (validation -> tenant/auth/rate-limit
    -> document context -> skill/QA -> zero-LLM shortcut -> session state + project
    memory -> model passport -> grounding/steer -> stream init) and return a
    TurnContext with every input the stream_chat + fold + post-loop read.

    Returns None when the turn is fully handled here (each early return below
    already sent its own WS message / recorded its metrics): message validation,
    rate limits, prompt-injection block, empty message, session ownership, the
    zero-LLM shortcut, and the deterministic нормоконтроль path."""
    import time as _time

    request_start = _time.monotonic()

    # Initialize telemetry metrics
    metrics = None
    try:
        from kukai.telemetry import RequestMetrics
        metrics = RequestMetrics()
    except ImportError:
        pass

    # plan-009: open the per-turn retrieval_health record. begin_turn() installs
    # a fresh mutable record in this task's context; the LLM/RAG path mutates it
    # (even across the build_system_prompt to_thread hop), and we close it at the
    # record site below. Guarded so a missing module never breaks a chat turn.
    _turn_health = None
    try:
        from kukai.rag import retrieval_health as _rh
        _turn_health = _rh.begin_turn()
    except ImportError:
        _turn_health = None

    # TurnLedger v1 (KUKAI_TURN_LEDGER): open the per-turn ledger. No-op when off.
    _turn_ledger = _tl.begin_turn(ws_id=ws_id, device_id=device_id)
    # Operation identity must exist even when the optional shadow TurnLedger is
    # disabled.  It stays stable across the outer provider retry loop.
    turn_id = _turn_ledger.turn_id if _turn_ledger is not None else str(uuid.uuid4())

    from kukai.main import get_app_state

    from kukai.api.chat_helpers import (
        RateLimitExceeded,
        SessionOwnershipError,
        check_rate_limit,
        prepare_chat_session,
        verify_session_ownership,
    )

    state = get_app_state()
    settings = get_settings()
    message_text = (data.get("message", "") or data.get("text", "")).strip()
    logger.info("CHAT REQUEST [%s]: %s", ws_id, message_text[:200])
    if len(message_text) > 1_000_000:
        await _send_json(ws, {"type": "error", "error": "Сообщение слишком длинное. Максимум: 1 000 000 символов."})
        return

    # ── Step 11 (KUKAI_SIGNED_IDENTITY, flag-gated) ──────────────────────────
    # Resolve the EFFECTIVE tenancy isolation key for this turn. Flag OFF ⇒
    # tenant_id IS device_id (identical value → byte-identical behavior at
    # every site below). Flag ON ⇒ a verified server-minted identity when the
    # client presented one; otherwise the mode's fallback (compat: legacy
    # device_id; strict: fresh minted identity). tenant_id — and ONLY
    # tenant_id — keys ownership, session creation, project memory and the
    # per-tenant rate limits below. The raw device_id keeps its non-isolation
    # roles (WS push registry, reasoning-trace/audit observability).
    tenant_id, tenant_signed, _t11_mint = _resolve_turn_tenant(data, ws_id, device_id)
    if _t11_mint:
        try:
            await _send_json(ws, {"type": "identity", "token": _t11_mint})
        except Exception:  # noqa: BLE001 — identity offer is best-effort
            logger.debug("signed-identity: mint send failed (non-fatal)")

    # Resolve the tenant's account tier/entitlements for this turn and stash them on
    # auth_info (no-op when KUKAI_LICENSING is off -> tier stays the 'free' default
    # read below). Fail-open; never breaks a turn.
    from kukai.api.entitlement_gate import resolve_turn_account
    await resolve_turn_account(state, tenant_id, device_id, auth_info)

    # Light per-device rate limit (fail-open) — protects the public WS from
    # token-drain / floods; real users never hit it. Limits USER turns, not AI rounds.
    _rl = check_and_count_turn(tenant_id)
    if _rl is not None:
        _rl_msg = ("Достигнут дневной лимит использования — продолжим завтра 🙏"
                   if _rl == "token_ceiling"
                   else "Слишком много запросов подряд — подождите немного 🙏")
        await _send_json(ws, {"type": "error", "error": _rl_msg})
        logger.info("rate-limit [%s] device=%s reason=%s", ws_id, device_id, _rl)
        return

    # Prompt injection check
    from kukai.security.prompt_guard import check_input
    guard_result = check_input(message_text)
    if guard_result.blocked:
        logger.warning(
            "Prompt injection blocked: score=%.1f detections=%s device_id=%s",
            guard_result.score,
            [d.label for d in guard_result.detections],
            device_id,
        )
        await _send_json(ws, {
            "type": "error",
            "error": "Сообщение заблокировано системой безопасности",
        })
        return
    if guard_result.risk == "suspicious":
        logger.warning(
            "Suspicious input (allowed): score=%.1f detections=%s device_id=%s",
            guard_result.score,
            [d.label for d in guard_result.detections],
            device_id,
        )
        # Use sanitized text for suspicious input
        message_text = guard_result.sanitized

    session_st = _session_states.get(ws_id)
    if session_st:
        session_st.apply_user_turn(message_text)

    raw_session_id = data.get("session_id", "")
    # Sanitize session_id — limit length
    session_id = raw_session_id[:32] if raw_session_id else str(uuid.uuid4())[:8]
    if tenant_signed:
        # Step 11 (flag ON, signed tenant only): stop trusting the client's
        # session_id — derive a full-length server-side id namespaced by the
        # unguessable identity (deterministic per claimed id ⇒ conversations
        # persist across turns/reconnects; two tenants claiming the same id
        # can never collide). Legacy/fallback tenants keep the raw id above.
        from kukai.security import identity as _sid11
        session_id = _sid11.namespaced_session_id(tenant_id, raw_session_id)
    # Audit tracing (SCOPED to audit sessions only — production traffic untouched):
    # publish the session id on the per-task ContextVar so the per-stage tracer
    # can attribute rag/translate/deepseek_call/tool/repair/finish records.
    if session_id.startswith(("audit-", "claude-", "ladder-", "scen-", "ragcert-")):
        from kukai.llm.client import _active_session_id as _audit_active_sid
        _audit_active_sid.set(session_id)
    preferences = data.get("preferences", {})
    units = preferences.get("units", "metric")

    # Extension system: read active extension from preferences
    active_extension = preferences.get("extension", "") or ""
    extension_profile = ""
    if active_extension:
        try:
            extension_profile = state.llm.get_extension_profile(active_extension)
        except Exception:
            logger.debug("Failed to load extension profile for %s", active_extension)

    if metrics:
        metrics.session_id = session_id
        _tl.set_ids(session_id=session_id, tenant_id=tenant_id)

    if not message_text:
        await _send_json(ws, {"type": "error", "error": "Пустое сообщение"})
        return

    device_token = auth_info.get("device_token", "")

    # Rate limit check
    try:
        ws_client_ip = ws.client.host if ws.client else ""
        await check_rate_limit(state, device_token, session_id, client_ip=ws_client_ip)
    except RateLimitExceeded as e:
        await _send_json(ws, {"type": "error", "error": str(e)})
        return

    # Session ownership check (Step 11: operates on the effective tenant key;
    # deny-by-default kept — flag OFF this is the same device_id value as before)
    try:
        await verify_session_ownership(state, session_id, tenant_id)
    except SessionOwnershipError as e:
        await _send_json(ws, {"type": "error", "error": str(e)})
        return

    # Prepare session, save user message, build LLM history
    llm_messages = await prepare_chat_session(state, session_id, tenant_id, message_text)

    # Картинка, вставленная человеком в чат (Ctrl+V / перетаскивание).
    #
    # ЗАЧЕМ. Оператор 29.07: «чтоб я скрин той же эйфелевой башни сделал и
    # скинул». Канал зрения у нас уже есть и работает — им уходят снимки видов
    # Revit; не хватало ровно того, чтобы человек мог подсунуть СВОЁ изображение.
    #
    # Больше, чем удобство: 29.07 все пять записей KIR получили вердикт
    # `unverifiable` — сверять «1в1» было не с чем, и ход честно крутился в
    # бесконечной самопроверке. Присланная картинка даёт эталон, то есть
    # ПРОВЕРЯЕМЫЙ критерий вместо непроверяемого.
    #
    # В историю БД идёт только текст с пометкой — само изображение в переписке
    # не копим: 29.07 снимки по 140 КБ уже дали 35 пустых ответов из 48, когда
    # накапливались в контексте.
    _img_b64 = data.get("image_base64") if isinstance(data, dict) else None
    if _img_b64 and isinstance(_img_b64, str) and llm_messages:
        try:
            from kukai.llm.client import _image_mime
            _kb = len(_img_b64) * 3 // 4 // 1024
            _cap = _int_env_chat("KUKAI_CHAT_IMAGE_MAX_KB", 400)
            if _kb > _cap:
                logger.warning("вложение %d КБ больше потолка %d КБ — не отдаём модели",
                               _kb, _cap)
            else:
                for _m in reversed(llm_messages):
                    if _m.get("role") == "user":
                        _m["content"] = [
                            {"type": "text", "text": message_text or
                             "Смотри на изображение."},
                            {"type": "image_url", "image_url": {
                                "url": f"data:{_image_mime(_img_b64)};base64,{_img_b64}"}},
                        ]
                        break
                logger.info("к ходу приложено изображение от пользователя (%d КБ)", _kb)
                # Подтверждение НА ЭКРАН, что картинка принята и ушла модели.
                # Оператор 29.07: «вообще не понятно, увидел он что-то или нет».
                # Отправлять вслепую и гадать по ответу — плохо: если вложение
                # молча не доехало (перевес, кривой формат), человек будет
                # спорить с моделью о том, чего она не видела. Говорит сервер,
                # потому что только он знает, что изображение реально вложено
                # в запрос, а не осталось в браузере.
                await _send_json(ws, {
                    "type": "tool_progress", "kind": "attachment",
                    "message": f"изображение принято и передано модели · {_kb} КБ",
                    "current": 1, "total": 0,
                })
        except Exception:  # noqa: BLE001 — вложение не может ломать ход
            logger.debug("не удалось приложить изображение", exc_info=True)

    # Get context from WebSocket session (V+ architecture: context comes from client)
    context = _get_context_for_session(ws_id)
    has_document = context is not None
    _tl.record_flags_snapshot("chat_ws._handle_chat", _tl.snapshot_flags(extra={
        "tier": auth_info.get("tier", "free"), "tenant_signed": bool(tenant_signed),
        "has_document": has_document, "msg_len": len(message_text)}),
        file_line="kukai/api/chat_ws.py:1594")

    # Fallback: if no WebSocket context, try bridge (backward compat)
    if context is None and state.bridge.connected:
        from kukai.api.chat_helpers import get_bridge_context
        context, has_document = await get_bridge_context(state)

    # Determine if we should use tools:
    # - Always enable tools for lookup (GESN, norms, reports) — they work without Revit
    # - Revit-specific tools (execute_revit_code, etc.) are guarded inside _execute_tool
    # - Extensions (estimator, etc.) NEED tools even without open document
    use_tools = has_document or bool(active_extension)

    # Skill detection — multi-step AI workflows (priority over QA triggers)
    from kukai.skills import detect_skill, load_skill_prompt
    active_skill = detect_skill(message_text)
    skill_prompt = ""
    skill_name = ""
    if active_skill and has_document:
        skill_prompt = load_skill_prompt(active_skill)
        skill_name = active_skill.name_ru
        logger.info("Skill activated: %s (%s)", active_skill.id, skill_name)

    # QA/QC trigger detection — enrich the LLM prompt with check instructions
    # Skip if a skill is active (skills are a superset of QA)
    from kukai.qa_checks import detect_qa_trigger, get_package_checks
    qa_package = detect_qa_trigger(message_text) if not active_skill else None
    qa_context: Optional[dict[str, Any]] = None
    if qa_package and has_document:
        checks = get_package_checks(qa_package)
        qa_context = {
            "package": qa_package,
            "checks": [
                {"id": c.id, "name": c.name_ru, "description": c.description_ru, "code": c.code, "severity": c.severity}
                for c in checks
            ],
        }
        logger.info("QA trigger detected: package=%s checks=%d", qa_package, len(checks))

    # Model context is stored per-session, used for RAG and tool routing

    # Try shortcuts first (zero-LLM responses)
    from kukai.shortcuts import try_shortcut
    shortcut_events = try_shortcut(message_text, context)
    if shortcut_events is not None:
        # The only turn shape that reaches the user without a single line in the
        # journal — no CHAT COMPLETE, and a ledger row holding just the flags
        # snapshot. From the outside it is indistinguishable from a turn that
        # hung (2026-07-27: "привет, ты работаешь?" read as a 5-minute hang
        # until the messages table showed the canned reply had been delivered
        # in 0.3s). Name it.
        logger.info("CHAT SHORTCUT [%s]: %r — answered with no LLM call",
                    ws_id, message_text[:60])
        if metrics:
            metrics.shortcut_used = True
            metrics.category = "shortcut"
        for event in shortcut_events:
            await _send_json(ws, event)
        # Save assistant message to DB
        shortcut_text = ""
        for ev in shortcut_events:
            if ev.get("type") == "stream_chunk":
                shortcut_text += ev.get("text", "")
        if shortcut_text:
            assistant_msg = Message(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=shortcut_text,
            )
            await state.db.save_message(assistant_msg)
        # NOTE: do NOT log_request here — check_rate_limit() already logged it
        # Record telemetry for shortcut
        if metrics:
            metrics.response_time_ms = int((_time.monotonic() - request_start) * 1000)
            try:
                from kukai.telemetry import TelemetryCollector
                collector = TelemetryCollector(state.db)
                await collector.record(metrics)
            except Exception as e:
                # IRON 10 — telemetry stays non-blocking, but no longer silent.
                from kukai.telemetry import note_telemetry_failure
                note_telemetry_failure(e)
        return

    # Create bridge callback that routes through WebSocket
    async def ws_bridge_callback(method: str, params: dict[str, Any]) -> dict[str, Any]:
        # Serialize bridge round-trips per connection (KUKAI_BRIDGE_SERIALIZE): one
        # ExternalEvent op at a time, so concurrent turns/tool-calls queue instead of
        # colliding with "Failed to raise ExternalEvent: Pending". get_model_details is
        # cache-served (no ExternalEvent) — never block it behind a long execute.
        if not _bridge_serialize_enabled() or method == "get_model_details":
            return await _bridge_callback(
                ws, ws_id, method, params,
                actor={"session_id": session_id, "tenant_id": tenant_id, "device_id": device_id},
            )
        async with _get_bridge_serialize_lock(ws_id):
            return await _bridge_callback(
                ws, ws_id, method, params,
                actor={"session_id": session_id, "tenant_id": tenant_id, "device_id": device_id},
            )

    # Нормоконтроль (KUKAI_NORMCONTROL, default OFF) — DETERMINISTIC norm-compliance
    # with NO model in the loop: extract via the bridge, evaluate curated corpus-
    # verified rules, return a grounded report. The whole point of the truth layer
    # is that norm claims are NOT model-generated (no fabrication). Flag-gated so it
    # ships byte-identical; the operator flips it for the live DODELKA test.
    # NOTE: deliberately fires even when the model-mediated `compliance` skill
    # matched — the DETERMINISTIC path supersedes it for norm audits (no fabrication).
    if os.environ.get("KUKAI_NORMCONTROL", "0") == "1" and has_document:
        from kukai.norm_control import detect_normcontrol_trigger
        from kukai.norm_tree import run_tree_audit
        if detect_normcontrol_trigger(message_text):
            # Entitlement gate (no-op when licensing off or feature un-restricted;
            # shadow logs would-deny but proceeds; enforce blocks unentitled tiers).
            from kukai.api.entitlement_gate import gate_feature
            from kukai.licensing.features import FEATURE_NORMCONTROL
            _nc_deny = await gate_feature(state, FEATURE_NORMCONTROL, auth_info, tenant_id)
            if _nc_deny:
                await _send_json(ws, {"type": "stream_start"})
                await _send_json(ws, {"type": "stream_chunk", "text": _nc_deny})
                await _send_json(ws, {"type": "stream_end"})
                return
            logger.info("Нормоконтроль trigger [%s] (deterministic tree audit)", ws_id)
            try:
                _nc_report = await run_tree_audit(ws_bridge_callback)
            except Exception:  # noqa: BLE001 — never crash the turn on a check failure
                logger.exception("normcontrol run failed")
                _nc_report = "Не удалось выполнить нормоконтроль. Попробуйте позже."
            await _send_json(ws, {"type": "stream_start"})
            await _send_json(ws, {"type": "stream_chunk", "text": _nc_report})
            await _send_json(ws, {"type": "stream_end"})
            _nc_msg = Message(id=str(uuid.uuid4()), session_id=session_id,
                              role="assistant", content=_nc_report)
            await state.db.save_turn([_nc_msg])
            return

    # Preflight discovery — detect category and fetch real parameters
    discovery_context: Optional[dict[str, Any]] = None
    if has_document:
        from kukai.categories import find_category_in_text
        ost_cat = find_category_in_text(message_text)
        if not ost_cat:
            # Fallback: use session state's last known category
            ws_state = _session_states.get(ws_id)
            if ws_state and ws_state.working_set.category:
                ost_cat = ws_state.working_set.category
        if ost_cat:
            cache = _discovery_caches.get(ws_id)
            if cache:
                discovery_context = await cache.get(ost_cat, ws_bridge_callback)

    # Compute session state block for LLM context
    session_state_block = ""
    if session_st:
        session_state_block = session_st.to_prompt_block()

    # User notes as soft context (from frontend localStorage)
    # Sanitize to prevent prompt injection via notes
    notes_context = data.get("notes_context", "")
    if notes_context:
        from kukai.security.prompt_guard import check_input
        notes_guard = check_input(notes_context)
        if notes_guard.blocked:
            logger.warning("Prompt injection in notes_context blocked: %s", [d.label for d in notes_guard.detections])
            notes_context = ""
        elif notes_guard.risk == "suspicious":
            notes_context = notes_guard.sanitized

    # Load project memory — persistent AI knowledge about this project.
    # Memory key includes the document path when available, so two .rvt files
    # with the same display name (common: "Project1.rvt" in different folders,
    # or two parallel Revit instances on the same machine) keep separate memory.
    project_memory_block = ""
    project_name = ""
    if context and hasattr(context, 'document') and context.document:
        doc_name = getattr(context.document, 'name', '') or ''
        doc_path = getattr(context.document, 'path', '') or ''
        if doc_name:
            project_name = f"{doc_name}|{doc_path}" if doc_path else doc_name
    if project_name and tenant_id:
        # Step 11: memory is keyed by the effective tenant (flag OFF ⇒ device_id)
        from kukai.llm.project_memory import load_project_memory
        try:
            project_memory_block = await load_project_memory(
                state.db, tenant_id, project_name,
                # optin mode only: the client asks for the file's notes explicitly.
                # Absent key ⇒ False ⇒ a new dialog starts clean.
                requested=bool(data.get("use_project_memory")),
            )
        except Exception as e:
            logger.warning("Failed to load project memory: %s", e)

    if project_memory_block and session_state_block:
        session_state_block = project_memory_block + "\n\n" + session_state_block
    elif project_memory_block:
        session_state_block = project_memory_block

    # Build Model Passport (~20K tokens of structured model context) — built by
    # the extracted _build_model_passport seam (snapshot A/B, 2026-07-12).
    model_passport_md = await _build_model_passport(ws_id, ws_bridge_callback)

    # Pillar C (grounding gate) — PREVENTIVE: on an analysis/normcontrol/persona
    # turn, instruct the model to ground via a tool BEFORE answering. Streaming-
    # safe (changes behavior pre-generation), unlike a post-hoc reprompt. Flag-
    # gated + A/B; dark by default. Fixes s30 (0 tool calls → fabricated GOST).
    try:
        from kukai import config as _kcfg
        from kukai.agents.rollout import in_treatment as _in_treat
        from kukai.api.grounding_gate import is_analysis_turn as _is_analysis
        if (_kcfg.AGENT_USE_GROUNDING_GATE
                and _in_treat(session_id, _kcfg.AGENT_TEST_PERCENT)
                and _is_analysis(message_text)):
            llm_messages.append({"role": "system", "content": (
                "Это аналитический/нормоконтрольный запрос. Обязательно вызови хотя бы "
                "один инструмент заземления (get_model_info / query_model / lookup_norm) "
                "ПЕРЕД финальным ответом. НЕ цитируй конкретный пункт нормы "
                "(ГОСТ/СП/СНиП/п.N), если его не вернул lookup_norm — иначе честно "
                "скажи, что нужна сверка по официальному тексту нормы."
            )})
            logger.info("grounding-gate: preventive nudge applied [%s]", ws_id)
    except Exception as _e:  # noqa: BLE001 — gate must never block the chat
        logger.warning("grounding gate (preventive) skipped: %s", _e)

    # Pillar A (M3) — STEER query_model to filter by the REAL property
    # (function/width_mm/layer_material_contains/level) instead of type-name
    # substring. Gated + audit/treatment-only → real users keep current behavior
    # until validated. Fixes the study's name-vs-property bug (s2 68→420, s6 977→1234).
    try:
        from kukai import config as _kcfg
        from kukai.agents.rollout import in_treatment as _in_treat
        if bool(_kcfg.AGENT_USE_QUERY_SEMANTIC) and (
                _in_treat(session_id, _kcfg.AGENT_TEST_PERCENT) or str(session_id).startswith("audit-")):
            llm_messages.append({"role": "system", "content": (
                "Фильтруя стены/перекрытия через query_model, фильтруй по РЕАЛЬНОМУ "
                "свойству элемента, а не по подстроке имени типа. Предикаты:\n"
                "- function (exterior/interior/foundation/...) — функция стены. Сам "
                "сопоставь смысл запроса с предикатом, ПОНИМАЯ синонимы и опечатки "
                "(наружные/фасадные/внешние → exterior; перегородки/внутренние → interior).\n"
                "- width_mm {op,value} — реальная толщина в мм.\n"
                "- layer_material_contains — имя материала слоя конструкции. Бери РЕАЛЬНОЕ "
                "имя материала ИЗ ПАСПОРТА этой модели (для монолита/ЖБ — конструкционный "
                "железобетон), не угадывай и не подставляй константу.\n"
                "- level — имя уровня. Сопоставь «N этаж» с ФАКТИЧЕСКИМ уровнем из паспорта "
                "(раздел УРОВНИ) и передай его реальное имя/подстроку.\n"
                "ВАЖНО: значения материалов и уровней — всегда из реальных данных модели "
                "(паспорт), а не из общих предположений. Если нужного имени нет в паспорте — "
                "сначала уточни запросом, потом фильтруй."
            )})
            logger.info("query-semantic steer applied [%s]", ws_id)
    except Exception as _e:  # noqa: BLE001 — steer must never block the chat
        logger.warning("query-semantic steer skipped: %s", _e)

    # Phase 7.3 — product-language status bubbles. We emit unconditionally;
    # the copy ("Думаю...", "Пишу код...", "Проверяю...") is benign whether
    # or not the multi-agent layer is enabled — it accurately describes the
    # phases the normal RAG + LLM + bridge pipeline already runs through.
    # Track which statuses we've already emitted within this turn so we
    # don't spam the client on every chunk/tool call.
    _status_seen: set[str] = set()

    async def _status_once(text: str) -> None:
        if text in _status_seen:
            return
        _status_seen.add(text)
        await _emit_status(ws, text)

    # Thinking mode: honour the UI-selected mode (fast/thinking). The frontend
    # sends preferences.thinking = (aiMode === 'thinking'). Family-editor
    # context auto-forces thinking mode (matches the HTTP /chat path in
    # client.py). thinking_mode then flows through stream_chat to model
    # selection, which routes to settings.llm_thinking_model (no hardcoded id).
    _user_thinking_pref = bool((preferences or {}).get("thinking", False))
    _is_family_editor = bool(context and getattr(context, "is_family_editor", False))
    thinking_mode = _user_thinking_pref or _is_family_editor

    # Pre-flight phase — retrieval, model passport, optional agent layer.
    await _status_once("Думаю...")

    # _REASONING_TRACE_PATCHED_ — capture model's chain-of-thought + tool
    # results per turn so we can debug what the model struggled with on real
    # prod queries. Best-effort; never blocks the user-facing chat.
    # Disable via env KUKAI_REASONING_LOG_ENABLED=0.
    reasoning_trace = None
    _flush_reasoning_trace = None
    try:
        from kukai.llm.reasoning_logger import (
            ReasoningTrace as _ReasoningTrace,
            flush_trace as _flush_reasoning_trace_imported,
        )
        _flush_reasoning_trace = _flush_reasoning_trace_imported
        _revit_version_for_trace = ""
        if context and getattr(context, "document", None):
            _revit_version_for_trace = getattr(context.document, "revit_version", "") or ""
        reasoning_trace = _ReasoningTrace(
            session_id=session_id,
            device_id=device_id or "",
            query=message_text or "",
            is_family_editor=_is_family_editor,
            revit_version=_revit_version_for_trace,
            thinking_mode=bool(thinking_mode),
        )
    except Exception as _trace_init_err:  # noqa: BLE001
        logger.debug("reasoning_trace init failed: %s", _trace_init_err)
        reasoning_trace = None
        _flush_reasoning_trace = None

    _tl.record_prompt_inputs("chat_ws._handle_chat", {
        "history_n": len(llm_messages), "msg": _tl.digest_preview(message_text),
        "skill": skill_name or "", "thinking": bool(thinking_mode),
        "passport_len": len(model_passport_md or ""), "has_document": has_document},
        file_line="kukai/api/chat_ws.py:prompt")

    # ── Hand the round engine everything it needs as ONE value. ──────────────
    return TurnContext(
        ws=ws,
        turn_id=turn_id,
        ws_id=ws_id,
        device_id=device_id,
        tenant_id=tenant_id,
        session_id=session_id,
        message_text=message_text,
        preferences=preferences,
        units=units,
        active_extension=active_extension,
        extension_profile=extension_profile,
        state=state,
        settings=settings,
        metrics=metrics,
        llm_messages=llm_messages,
        context=context,
        has_document=has_document,
        use_tools=use_tools,
        session_st=session_st,
        skill_name=skill_name,
        skill_prompt=skill_prompt,
        qa_context=qa_context,
        discovery_context=discovery_context,
        session_state_block=session_state_block,
        notes_context=notes_context,
        model_passport_md=model_passport_md,
        project_name=project_name,
        thinking_mode=thinking_mode,
        reasoning_trace=reasoning_trace,
        _flush_reasoning_trace=_flush_reasoning_trace,
        request_start=request_start,
        _turn_health=_turn_health,
        ws_bridge_callback=ws_bridge_callback,
        _status_seen=_status_seen,
        _status_once=_status_once,
    )


async def _handle_chat(
    ws: WebSocket,
    data: dict[str, Any],
    device_id: str,
    auth_info: dict[str, Any],
    ws_id: str,
) -> None:
    """Handle a chat message — stream LLM response back."""
    ctx = await prepare_turn(ws, data, device_id, auth_info, ws_id)
    if ctx is None:
        return
    # Golden-path B2 chunk 2: the engine half (stream-retry fold) and the
    # post-loop tail are two functions now; the try/except/finally that used to
    # wrap the loop lives INSIDE finalize_turn, and run_turn defers any loop
    # exception to it (res.pending_exc) so the exact semantics are preserved.
    res = await run_turn(ctx, auth_info)
    await finalize_turn(ctx, res)


async def _emit_turn_event(ctx: TurnContext, payload: dict[str, Any]) -> None:
    """Stream one event to the user — surviving a socket that went away.

    The turn used to hold ONE WebSocket object for its whole life and die at the
    next send if that object closed. Measured 2026-07-27 10:40: the panel dropped
    with close_code=1006 mid-turn and reconnected 1.4s later with a fresh ws_id;
    the turn kept writing to the dead one, raised, and threw away everything it
    had already done — the operator sees this as "снова оборвался по шагам".
    Bounded by the same window: 66 abnormal 1006 drops in a day, and WebView2
    inside Revit throttles a backgrounded panel, so a drop is normal weather.

    Two degradations, in order, instead of one failure:
      1. rebind to any live socket the SAME device currently holds (the panel
         that just reconnected) and retry once;
      2. if the device has no socket at all, keep the TURN running with the
         stream muted — the work still completes and still persists, so the
         answer is there when the panel comes back.
    """
    try:
        await _send_json(ctx.ws, payload)
        return
    except Exception as first_err:  # noqa: BLE001 — transport, not logic
        live = [
            w for w in (_device_websockets.get(ctx.device_id) or set())
            if w is not ctx.ws
        ]
        for w in live:
            try:
                await _send_json(w, payload)
                logger.info(
                    "stream rebound to the device's live socket after %s "
                    "[ws_id=%s device=%s]",
                    type(first_err).__name__, ctx.ws_id, ctx.device_id[:12],
                )
                ctx.ws = w
                return
            except Exception:  # noqa: BLE001 — try the next one
                continue
        if not getattr(ctx, "_stream_muted", False):
            ctx._stream_muted = True  # type: ignore[attr-defined]
            logger.warning(
                "no live socket for device=%s — muting the stream, the turn "
                "keeps running and persists its answer [ws_id=%s]: %s",
                ctx.device_id[:12], ctx.ws_id, str(first_err)[:120],
            )
            _tl.record_degradation(
                "chat_ws.stream_muted", {"err": type(first_err).__name__},
                err_code="stream_muted", file_line="kukai/api/chat_ws.py:mute_stream")


async def run_turn(ctx: TurnContext, auth_info: dict[str, Any]) -> TurnRunResult:
    """Run ONE turn's engine half: create the LLM stream and drive the
    stream-retry `while True:` fold (silent-retry, usage/truth-gate folds, tool
    persistence, per-turn evidence accumulation), returning a TurnRunResult with
    everything the post-loop tail reads.

    `auth_info` is passed alongside `ctx` ONLY for `user_tier` (the one fold
    input prepare_turn does not stash on TurnContext). A loop exception is NOT
    handled here — it is captured into `res.pending_exc` and re-raised by
    `finalize_turn` inside the SAME try/except/finally the loop used to sit in,
    so the exception + finally ordering is byte-for-byte the original's."""
    import time as _time

    # Bind this turn's device for the optional Codex-subscription route (isolated
    # ContextVar in codex_route — NOT KIR's gate). No-op unless KUKAI_CODEXPROXY_ENABLED.
    from kukai.llm import codex_route
    codex_route.bind_turn_device(ctx.device_id)

    # Живой доклад с хода на экран. Здесь единственное место, где сокет клиента
    # и ход встречаются: KIR-исполнение сидит глубоко в kukai.ir и веб-слоя не
    # знает — и знать не должно. Отдаём ему только «как отправить», сам канал
    # остаётся здесь. Fail-open: доклад никогда не ломает ход.
    try:
        from kukai.llm import turn_progress as _tp

        async def _progress_sink(payload: dict) -> None:
            await _send_json(ctx.ws, payload)

        _tp.bind(_progress_sink)
    except Exception:  # noqa: BLE001
        logger.debug("turn progress bind failed", exc_info=True)

    # …and for KIR's gate, which is a DIFFERENT ContextVar and was never set on
    # this path. `revit_ir_enabled()` = flag AND turn_context._active_device_id
    # == ADMIN_DEVICE, and until now that ContextVar was written ONLY by the
    # admin_kir HTTP endpoints — so in CHAT it was always None, the gate
    # fail-closed, and the `revit_ir` tool was never offered to the model. Not a
    # flag problem: KUKAI_KIR_TOOL=stage2 has been set the whole time, the
    # compiler works, admin-driven KIR writes land. The model simply never saw
    # the tool, and said so plainly when pushed — "в текущем сеансе недоступен
    # revit_ir" (four turns in a row, 2026-07-27). This one line is what makes
    # the KIR path reachable from a conversation at all.
    try:
        from kukai.llm import turn_context as _tc
        _tc._active_device_id.set(ctx.device_id)
    except Exception:  # noqa: BLE001 — a gate input must never break the turn
        logger.debug("publishing device id for the KIR gate failed", exc_info=True)

    # Stream LLM response
    collected_text = ""
    # Track tool interactions for DB persistence
    pending_tool_call_name: str = ""
    pending_tool_call_id: str = ""
    # Silent retry: when LLM crashes mid-task, nudge it to continue (max 10)
    _silent_retries = 0
    _MAX_SILENT_RETRIES = 2  # Step 6: was 10 — a load-amplifying storm; cap low + classify + backoff
    _should_retry = False
    # Mute-turn guard: did this turn produce any tool call / surface any error?
    # Used at the end of the try-block to detect a fully-silent turn.
    tool_invoked = False
    error_emitted = False
    # Pillar C (grounding gate): names of tools actually executed this turn —
    # feeds the post-hoc anti-fabrication check (analysis-turn must ground).
    _turn_tool_names: list[str] = []
    # B1: witnessed-write signal — set True when a WRITE tool returns non-error.
    _turn_write_ok = False
    # Safety boundary: once a side-effecting tool has STARTED, an outer provider
    # retry must never rebuild the turn from its original messages. The client
    # may still finish/repair inside the same stream, but a fresh stream could
    # execute the same Revit action twice after a lost response.
    _turn_write_started = False
    # B2: raw lookup_norm results this turn (aligned to lookup_norm entries in
    # _turn_tool_names by order) — lets the grounding gate see a real HIT vs miss.
    _turn_lookup_norm_results: list[Any] = []
    # Phase 4: unified per-turn observations (populated in SHADOW alongside the three
    # legacy structures above; consumers still read legacy until KUKAI_TOOL_OBSERVATIONS).
    turn_observations: list[_tobs.ToolObservation] = []
    # Reveal (KUKAI_REVEAL_FOUND): ids of the latest find this turn, so the post-turn
    # present block can select+frame them deterministically ("show what was found").
    _turn_found_ids: list[str] = []
    # NAV-V2 (KUKAI_NAV_V2): monotonic timestamp of the last per-action mid-turn
    # zoom, turn-scoped — throttles consecutive write ops to one mini-nav per
    # KUKAI_NAV_V2_THROTTLE_S (default 2.5s). None = never fired this turn.
    _nav_v2_last_fire_ts: Optional[float] = None
    _pending_exc: Optional[BaseException] = None
    try:
        while True:
            _should_retry = False
            _stream = ctx.state.llm.stream_chat(
                messages=ctx.llm_messages,
                context=ctx.context,
                preferences=ctx.preferences,
                units=ctx.units,
                use_tools=ctx.use_tools,
                has_document=ctx.has_document,
                bridge_callback=ctx.ws_bridge_callback,
                discovery_context=ctx.discovery_context,
                qa_context=ctx.qa_context,
                session_state_block=ctx.session_state_block,
                notes_context=ctx.notes_context,
                active_extension=ctx.active_extension or None,
                extension_profile=ctx.extension_profile or None,
                thinking_mode=ctx.thinking_mode,
                model_passport=ctx.model_passport_md,
                skill_prompt=ctx.skill_prompt or None,
                skill_name=ctx.skill_name or "",
                ws_send=ctx.ws,
                user_tier=auth_info.get("tier", "free"),
                turn_id=ctx.turn_id,
            )
            async for event in _stream:
                # Intercept error events — silently retry instead of showing to user
                if event.type == "error" and _silent_retries < _MAX_SILENT_RETRIES \
                        and _is_retryable_error(event.data) and not _turn_write_started:
                    _silent_retries += 1
                    logger.warning("Silent retry %d/%d: suppressing error '%s'",
                                   _silent_retries, _MAX_SILENT_RETRIES, str(event.data)[:100])
                    # Step 1: un-blind — record the suppressed error to telemetry +
                    # reasoning trace before we swallow it (was invisible to both).
                    _record_suppressed_error(ctx.metrics, ctx.reasoning_trace, event.data)
                    _tl.record_degradation("chat_ws.silent_retry", {"retry": _silent_retries, "err": str(event.data)[:200]}, err_code="silent_retry", file_line="kukai/api/chat_ws.py:silent")
                    # Nudge LLM to continue where it stopped
                    if collected_text:
                        ctx.llm_messages.append({"role": "assistant", "content": collected_text})
                    ctx.llm_messages.append({"role": "user", "content": "[continue from where you stopped — complete the task]"})
                    collected_text = ""
                    await asyncio.sleep(min(float(_silent_retries), 3.0))  # Step 6: backoff (was: instant storm)
                    _should_retry = True
                    break

                # Step 1: usage is internal telemetry — fold tokens into the metrics
                # row and do NOT forward the raw event to the plugin.
                if event.type == "usage":
                    _fold_usage_into_metrics(ctx.metrics, event.data)
                    _tl.record_llm("chat_ws.usage_fold", event.data if isinstance(event.data, dict) else {"usage": str(event.data)}, file_line="kukai/api/chat_ws.py:usage")
                    continue

                # Step 8 (KUKAI_TRUTH_GATE): fake-готово detection signal —
                # internal telemetry like "usage": fold into the reasoning-trace
                # row (data/reasoning_traces.jsonl) and do NOT forward to the
                # plugin. Emitted by client.py only when the flag is shadow/
                # enforce, so with the flag OFF this branch never fires and the
                # turn is byte-identical. Guarded — telemetry must never break
                # the stream.
                if event.type == "truth_gate":
                    if ctx.reasoning_trace is not None and isinstance(event.data, dict):
                        try:
                            ctx.reasoning_trace.truth_gate.append(event.data)
                        except Exception as _tg_err:  # noqa: BLE001
                            logger.debug("truth_gate trace fold failed: %s", _tg_err)
                    _tl.record_llm("chat_ws.truth_gate_fold", event.data, ok=False, err_code="truth_gate", file_line="kukai/api/chat_ws.py:tg")
                    continue

                await _emit_turn_event(ctx, event.to_dict())
                # _REASONING_TRACE_PATCHED_ — feed event into accumulator
                if ctx.reasoning_trace is not None:
                    try:
                        if event.type == "reasoning_chunk" and isinstance(event.data, str):
                            ctx.reasoning_trace.on_reasoning_chunk(event.data)
                        elif event.type == "stream_chunk" and isinstance(event.data, str):
                            ctx.reasoning_trace.on_stream_chunk(event.data)
                        elif event.type == "tool_start":
                            ctx.reasoning_trace.on_tool_start(str(event.data or ""))
                        elif event.type == "tool_end":
                            ctx.reasoning_trace.on_tool_end(event.data)
                        elif event.type == "error":
                            ctx.reasoning_trace.on_error(event.data)
                    except Exception as _trace_evt_err:  # noqa: BLE001
                        logger.debug("reasoning_trace event hook failed: %s", _trace_evt_err)
                if event.type == "error":
                    error_emitted = True
                    _tl.record_llm("chat_ws.stream_error", {"err": str(event.data)[:300]}, ok=False, err_code="stream_error", file_line="kukai/api/chat_ws.py:strerr")
                if event.type == "stream_chunk" and event.data:
                    # First text from the model — LLM is now generating output.
                    # W5-a salvage: time-to-first-token (the schema column existed but
                    # the live path never populated it — recovered from the dead fork).
                    if ctx.metrics and ctx.metrics.first_token_ms is None:
                        ctx.metrics.first_token_ms = int((_time.monotonic() - ctx.request_start) * 1000)
                    await ctx._status_once("Пишу код...")
                    collected_text += event.data

                # Phase 7.3 — surface "Проверяю..." when code execution
                # begins (compile + Revit bridge round-trip). Other tools
                # don't get a bubble — they're short and we'd just flicker.
                if event.type == "tool_start" and event.data == "execute_revit_code":
                    # Reset 'Пишу код...' so a follow-up turn after the
                    # tool returns can re-emit it cleanly.
                    ctx._status_seen.discard("Пишу код...")
                    await _emit_status(ctx.ws, "Проверяю...")
                    ctx._status_seen.add("Проверяю...")
                    # TODO(Phase 7.4): emit "Исправляю..." when client.py
                    # _repair_code activates. No hook today — needs a
                    # deeper signal from the LLM client stream.
                # Track tool_start to build tool_calls list
                if event.type == "tool_start" and event.data:
                    pending_tool_call_name = event.data
                    pending_tool_call_id = str(uuid.uuid4())[:12]
                    tool_invoked = True
                    if event.data in _WRITE_TOOLS:
                        _turn_write_started = True
                    if ctx.metrics:
                        ctx.metrics.tool_calls.append(event.data)

                # Save tool interactions to DB for conversation context persistence
                if event.type == "tool_end" and event.data:
                    tool_name = event.data.get("tool", "unknown")
                    _turn_tool_names.append(tool_name)  # Pillar C: grounding evidence
                    if ctx.metrics and ctx.metrics.tool_name is None:
                        ctx.metrics.tool_name = tool_name  # W5-a salvage: primary tool used
                    tool_result_str = str(event.data.get("result", ""))

                    # B2: capture lookup_norm's real result so the grounding gate
                    # can tell a HIT (found>0) from a miss/error (a norm citation
                    # after an empty lookup must be annotated, not passed).
                    if tool_name == "lookup_norm":
                        _turn_lookup_norm_results.append(event.data.get("result"))

                    # Handle add_user_note: forward as WS message to client
                    if tool_name == "add_user_note":
                        try:
                            raw = event.data.get("result", "{}")
                            parsed = json.loads(raw) if isinstance(raw, str) else raw
                            if isinstance(parsed, dict) and parsed.get("action") == "add_note":
                                await _emit_turn_event(ctx, {"type": "add_note", "text": parsed.get("text", "")})
                        except (json.JSONDecodeError, TypeError):
                            pass

                    # Handle file delivery: send file to client for saving to Desktop
                    if tool_name in ("generate_report", "price_vor"):
                        try:
                            raw = event.data.get("result", "{}")
                            parsed_report = json.loads(raw) if isinstance(raw, str) else raw
                            if isinstance(parsed_report, dict) and parsed_report.get("file_base64"):
                                await _emit_turn_event(ctx, {
                                    "type": "save_file",
                                    "filename": parsed_report.get("filename", "report.xlsx"),
                                    "data": parsed_report["file_base64"],
                                })
                                logger.info("File sent to client: %s", parsed_report.get("filename"))
                            elif isinstance(parsed_report, dict) and parsed_report.get("error"):
                                logger.warning("Report generation failed: %s", parsed_report.get("message"))
                            else:
                                logger.warning("Report tool returned no file_base64: %s", str(raw)[:200])
                        except Exception as file_err:
                            logger.error("File delivery failed: %s", file_err)

                    # Save assistant message with tool_calls (if we have collected text + tool call)
                    tool_args_str = event.data.get("arguments", "{}") if isinstance(event.data, dict) else "{}"
                    tool_call_entry = {
                        "id": pending_tool_call_id or str(uuid.uuid4())[:12],
                        "type": "function",
                        "function": {"name": tool_name, "arguments": tool_args_str},
                    }
                    # Build the assistant-tool_calls message + the tool-result message.
                    assistant_tc_msg = Message(
                        id=str(uuid.uuid4()),
                        session_id=ctx.session_id,
                        role="assistant",
                        content=collected_text or "",
                        tool_calls=[tool_call_entry],
                    )
                    tool_result_msg = Message(
                        id=str(uuid.uuid4()),
                        session_id=ctx.session_id,
                        role="tool",
                        content=tool_result_str[:5000],
                        tool_call_id=tool_call_entry["id"],
                    )
                    # Reset collected text — it's now folded into the tool-call assistant msg.
                    collected_text = ""

                    # Classify for audit/telemetry.
                    audit_result = "success"
                    try:
                        parsed_result = json.loads(tool_result_str)
                        # Same widening as the turn loop (kukai/llm/client.py:1569):
                        # `error is True` alone never matched a typed refusal, so a
                        # failed write was audited and ledgered as a success.
                        if _result_is_error(parsed_result):
                            audit_result = "error"
                    except (json.JSONDecodeError, TypeError):
                        pass

                    # B1: a WRITE tool that returned non-error is the honest
                    # trigger for auto-show/vision (not merely being CALLED).
                    if tool_name in _WRITE_TOOLS and audit_result == "success":
                        _turn_write_ok = True

                    # TurnLedger v1: the tool_end fold — where "success" is currently a
                    # JSON substring. Fresh parse (2198's parsed_result can carry a STALE
                    # value across loop iterations). No-op when the flag is off.
                    try:
                        _tl_parsed = json.loads(tool_result_str)
                    except (json.JSONDecodeError, TypeError):
                        _tl_parsed = None

                    # Phase 4: unified observation (SHADOW) — exactly one per tool_end,
                    # name verbatim (event.data["tool"]), RAW result for lookup_norm,
                    # safe parsed dict for change counts. Never breaks the turn.
                    try:
                        turn_observations.append(_tobs.observe(
                            name=tool_name,
                            raw_result=event.data.get("result"),
                            parsed_result=_tl_parsed,
                            audit_result=audit_result,
                            write_tools=_WRITE_TOOLS,
                            seq=len(turn_observations),
                        ))
                    except Exception:  # noqa: BLE001 — shadow population must never break a turn
                        pass

                    # NAV-V2 (KUKAI_NAV_V2, default OFF): per-action mid-turn zoom —
                    # "created a wall → zoomed to it". THROTTLED (>= 2.5s apart,
                    # turn-scoped monotonic clock), fire-and-forget (via the
                    # existing _spawn_bg background-outbox — B3), select+ShowElements
                    # ONLY (no un-isolate, no view-open — the finally-block hook
                    # consolidates those once at the end of the turn). Hard-capped at
                    # 3s via asyncio.wait_for so a slow/lost bridge round-trip can
                    # never stall the stream loop; _spawn_bg's done-callback logs (does
                    # not raise) any failure — errors are swallowed by design.
                    if turn_observations and ctx.ws_bridge_callback is not None:
                        try:
                            from kukai.llm import nav_v2 as _nav_v2
                            if _nav_v2.nav_v2_enabled():
                                _last_obs = turn_observations[-1]
                                if _last_obs.is_write and _last_obs.ok:
                                    _mini_ids = _nav_v2.harvest_nav_targets([_last_obs])["element_ids"]
                                    _mini_now = _time.monotonic()
                                    if _mini_ids and _nav_v2.should_fire_mini_nav(_nav_v2_last_fire_ts, _mini_now):
                                        _mini_code = _nav_v2.build_mini_nav_code(_mini_ids)
                                        if _mini_code:
                                            _nav_v2_last_fire_ts = _mini_now
                                            _spawn_bg(
                                                asyncio.wait_for(
                                                    ctx.ws_bridge_callback("execute", {"code": _mini_code}),
                                                    timeout=3.0),
                                                label=f"nav_v2_mini:{ctx.ws_id}")
                                            _tl.record_present("chat_ws.nav_v2_mini", {
                                                "kind": "nav_v2_mini", "tool": tool_name, "n": len(_mini_ids)},
                                                file_line="kukai/api/chat_ws.py:navv2mini")
                        except Exception:  # noqa: BLE001 — mini-nav must never break the turn
                            pass

                    # Reveal (KUKAI_REVEAL_FOUND): remember the ids of the latest
                    # find so the post-turn present block can select+frame them
                    # deterministically — "show what was found" without the LLM.
                    try:
                        from kukai.llm import reveal as _reveal
                        if _reveal.reveal_mode() != "off":
                            _rids = _reveal.extract_found_ids(_tl_parsed)
                            if _rids:
                                _turn_found_ids = _rids
                    except Exception:  # noqa: BLE001 — reveal capture must never break a turn
                        pass
                    _tl.record_tool("chat_ws.tool_end_fold", {
                        "tool": tool_name, "args": _tl.digest_preview(tool_args_str),
                        "result": _tl.digest_preview(tool_result_str),
                        "changed": _tl_parsed.get("changed") if isinstance(_tl_parsed, dict) else None},
                        ok=(audit_result != "error"), file_line="kukai/api/chat_ws.py:2202")
                    if tool_name == "execute_revit_code":
                        try:
                            from kukai.llm.revit_execution_pipeline import last_turn_record
                            _rec = last_turn_record()
                            if _rec is not None:
                                _tl.record_witness("exec_pipeline.turn_record", _rec.summary(), ok=bool(_rec.ok), file_line="kukai/api/chat_ws.py:2202")
                        except Exception:
                            pass
                    # Op-attached witness (2026-07-10): server-lowered writes
                    # (create_element) carry a grounded read-back+probe verdict —
                    # surface it in the ledger too, same trust registry as the
                    # shadow layer (forged witnesses from raw C# never lift).
                    try:
                        from kukai.will.witness import WITNESS_OPS
                        _w_op = None
                        try:
                            _w_args = json.loads(tool_args_str) if tool_args_str else {}
                            _w_op = _w_args.get("operation") if isinstance(_w_args, dict) else None
                        except Exception:
                            _w_op = None
                        if (tool_name, _w_op) in WITNESS_OPS and isinstance(_tl_parsed, dict):
                            _w = _tl_parsed.get("witness")
                            if isinstance(_w, dict) and isinstance(_w.get("verdict"), str):
                                _tl.record_witness(
                                    f"op_witness.{_w_op}",
                                    {"verdict": _w.get("verdict"),
                                     "score": _w.get("score"),
                                     "checks_decided": _w.get("checks_decided"),
                                     "op_id": _w.get("op_id")},
                                    ok=(_w.get("verdict") == "pass"),
                                    file_line="kukai/api/chat_ws.py:op_witness")
                    except Exception:  # noqa: BLE001 — ledger must never break a turn
                        pass

                    # Persist per-event (BEST-EFFORT): this block now runs inside the
                    # streaming loop (C1 fix), so a DB hiccup mid-turn must NOT kill the
                    # live stream after tools already ran (Fable review #9a).
                    try:
                        # Step 6 (audit D1 fix): persist the assistant tool_call
                        # message and its tool-result ATOMICALLY. Two separate
                        # save_message calls could land the first and lose the
                        # second → an orphaned assistant tool_call with no result
                        # → the next turn's history is invalid → the session is
                        # permanently bricked. One transaction = both or neither.
                        await ctx.state.db.save_turn([assistant_tc_msg, tool_result_msg])
                        await ctx.state.db.log_audit(
                            session_id=ctx.session_id,
                            action=tool_name,
                            details={"result_preview": tool_result_str[:500]},
                            result=audit_result,
                            device_id=ctx.device_id,
                        )
                        _tl.record_persistence("chat_ws.tool_pair_save", {"op": "save_turn_pair", "n": 2}, ok=True, file_line="kukai/api/chat_ws.py:toolpair_ok")
                    except Exception as _persist_err:  # noqa: BLE001
                        logger.warning("tool interaction persist failed (non-fatal): %s", _persist_err)
                        _tl.record_persistence("chat_ws.tool_pair_save", {"op": "save_turn_pair"}, ok=False, err_code=type(_persist_err).__name__, file_line="kukai/api/chat_ws.py:toolpair_err")

                    # In-memory session state (independent of DB).
                    if ctx.session_st:
                        try:
                            parsed_result = json.loads(tool_result_str)
                        except (json.JSONDecodeError, TypeError):
                            parsed_result = tool_result_str
                        ctx.session_st.remember_tool_result(tool_name, parsed_result)

                    # Telemetry: track tool success/failure
                    if ctx.metrics:
                        if audit_result == "error":
                            ctx.metrics.tool_failure += 1
                        else:
                            ctx.metrics.tool_success += 1

            # Step 5: close the stream generator so it isn't finalized in a foreign
            # context (root of "Task exception never retrieved" / "Unclosed client
            # session"), and so a retry can't leave the prior stream open.
            try:
                await _stream.aclose()
            except Exception:  # noqa: BLE001
                pass

            # After async for ends: retry or break the while loop
            if _should_retry:
                continue  # restart stream_chat with nudge message
            break  # normal completion — exit while loop
    except BaseException as _re:  # noqa: BLE001 — deferred verbatim; finalize_turn re-raises it
        # inside its try so it flows through the ORIGINAL except/finally (exact-equivalent).
        _pending_exc = _re
    return TurnRunResult(
        collected_text=collected_text,
        tool_invoked=tool_invoked,
        error_emitted=error_emitted,
        turn_tool_names=_turn_tool_names,
        turn_write_ok=_turn_write_ok,
        turn_lookup_norm_results=_turn_lookup_norm_results,
        turn_observations=turn_observations,
        turn_found_ids=_turn_found_ids,
        pending_exc=_pending_exc,
    )


async def finalize_turn(ctx: TurnContext, res: TurnRunResult) -> None:
    """Finish ONE turn: the post-loop tail — mute-fallback, skill markers, the
    finally-epilogues (status clear, tool-obs shadow-compare, auto-nav/reveal/
    vision, reasoning-trace flush, retrieval-health close, token accounting,
    telemetry) and the after-block (grounding post-hoc, final persistence,
    detached project-memory extraction).

    The try/except/finally that used to wrap the loop lives HERE now: run_turn
    deferred any loop exception into `res.pending_exc`, which we re-raise as the
    first statement of the try so CancelledError / Exception / finally fire in
    the exact original order and the after-block is skipped on error as before."""
    import time as _time
    # Re-bind the fold-locals the tail reads (same names ⇒ the moved code + its
    # `locals().get(...)` probes and `'collected_text' in dir()` resolve identically).
    collected_text = res.collected_text
    tool_invoked = res.tool_invoked
    error_emitted = res.error_emitted
    _turn_tool_names = res.turn_tool_names
    _turn_write_ok = res.turn_write_ok
    _turn_lookup_norm_results = res.turn_lookup_norm_results
    turn_observations = res.turn_observations
    _turn_found_ids = res.turn_found_ids
    try:
        if res.pending_exc is not None:
            raise res.pending_exc
        # Mute-turn guard: if the turn produced no assistant text, no tool call,
        # and no error was surfaced, the final-save below (gated on
        # collected_text) would leave the user with complete silence. Surface a
        # clear fallback instead. (Observed: DeepSeek returning finish_reason=
        # stop with empty content → dropped user turns.)
        if not collected_text and not tool_invoked and not error_emitted:
            _fallback = (
                "Не удалось сформировать ответ — модель вернула пустой результат. "
                "Попробуйте переформулировать запрос или повторить."
            )
            # Bracket with stream_start/stream_end so the frontend renders one
            # clean bubble (no lingering cursor / empty bubble on an empty turn).
            await _emit_turn_event(ctx, {"type": "stream_start"})
            await _emit_turn_event(ctx, {"type": "stream_chunk", "text": _fallback})
            await _emit_turn_event(ctx, {"type": "stream_end"})
            collected_text = _fallback
            _tl.record_present("chat_ws.mute_fallback", {"kind": "fallback_bubble"}, file_line="kukai/api/chat_ws.py:mute")

        # H12: act on skill-builder markers (KUKI_SKILL_*) the model emitted, then
        # strip them so they don't leak as raw markup into the saved message.
        # Session-scoped, fire-and-forget, error-isolated. Kill-switch, default OFF
        # pending Revit-client validation of the skill bridge messages:
        # KUKAI_SKILLS_ENABLED=1.
        if collected_text and "KUKI_SKILL_" in collected_text \
                and os.environ.get("KUKAI_SKILLS_ENABLED", "0") == "1":
            try:
                from kukai.skills.skill_markers import extract_markers
                from kukai.skills.skill_dispatcher import dispatch_markers
                _skill_markers, _skill_cleaned = extract_markers(collected_text)
                if _skill_markers:
                    await dispatch_markers(_skill_markers, lambda _m: _emit_turn_event(ctx, _m))
                    collected_text = _skill_cleaned
                    _tl.record_present("chat_ws.skill_markers", {"kind": "skill_markers", "n": len(_skill_markers)}, file_line="kukai/api/chat_ws.py:skill")
            except Exception:
                logger.exception("skill marker dispatch failed (non-fatal)")

    except asyncio.CancelledError:
        logger.info("Chat task cancelled by user")
        _tl.record_degradation("chat_ws.cancelled", {}, err_code="cancelled_by_user", file_line="kukai/api/chat_ws.py:cancel")
        return
    except Exception as exc:
        logger.exception("Chat streaming error")
        if ctx.metrics:
            ctx.metrics.error = type(exc).__name__
        logger.error("CHAT ERROR [%s]: %s: %s", ctx.ws_id, type(exc).__name__, str(exc)[:200])
        _tl.record_degradation("chat_ws.chat_error", {"err": str(exc)[:200]}, err_code=type(exc).__name__, file_line="kukai/api/chat_ws.py:chaterr")
        await _emit_turn_event(ctx, {"type": "error", "error": "Произошла внутренняя ошибка. Попробуйте повторить запрос."})
        return
    finally:
        # Phase 7.3 — clear the product-language status bubble on the way out
        # (empty text = dismiss). Best-effort: _emit_status swallows errors.
        await _emit_status(ctx.ws, "")

        # Auto-navigate (KUKAI_AUTO_SHOW, default OFF): after a turn that WROTE to
        # the model, point the user's LIVE Revit camera at the result — reset any
        # temporary isolation the model left, then ShowElements(selection) to zoom
        # to the created/selected elements WITHOUT isolating (rest of model stays
        # visible). The user is already looking at Revit, so we navigate THERE — we
        # do NOT push a screenshot into the panel (redundant: «зачем скрин когда он
        # видит модель напрямую в Ревите»). Screenshot capture is reserved for the
        # future vision-eyes loop (a separate vision model critiques the result),
        # NOT for the user. Fail-open — never breaks the turn.

        # Phase 4 SHADOW-COMPARE (in-process, per Codex audit #8): assert the
        # obs-derived signals equal the three legacy structures byte-for-byte —
        # names + write_ok + the RAW lookup_norm results (grounding_messages/wrote
        # all follow from these). Record a divergence event so a future cutover is
        # data-backed. Never alters behavior; legacy still drives every consumer.
        try:
            _legacy_ln = list(_turn_lookup_norm_results)
            _obs_ln = [o.result for o in turn_observations if o.name == "lookup_norm"]
            _legacy_wok = bool(locals().get("_turn_write_ok", False))
            if (_tobs.tool_names(turn_observations) != list(_turn_tool_names)
                    or _tobs.write_ok_any(turn_observations) != _legacy_wok
                    or _obs_ln != _legacy_ln):
                _tl.record_degradation("chat_ws.tool_obs_shadow", {
                    "obs_names": _tobs.tool_names(turn_observations)[:20],
                    "legacy_names": list(_turn_tool_names)[:20],
                    "obs_write_ok": _tobs.write_ok_any(turn_observations),
                    "legacy_write_ok": _legacy_wok,
                    "lookup_match": _obs_ln == _legacy_ln,
                }, err_code="tool_obs_divergence", file_line="kukai/api/chat_ws.py:obs_shadow")
        except Exception:  # noqa: BLE001 — shadow-compare must never break the turn
            pass

        try:
            from kukai.llm.vision_critic import vision_critic_enabled as _vc_on
            _auto_nav = os.environ.get("KUKAI_AUTO_SHOW", "0") == "1"
            _wrote = (ctx.ws_bridge_callback is not None
                      and any(t in _WRITE_TOOLS
                              for t in (locals().get("_turn_tool_names") or [])))
            # B1 (KUKAI_AUTOSHOW_WITNESSED, default OFF): fire on a witnessed WRITE
            # SUCCESS, not a mere write-tool call — no auto-show/vision after a
            # FAILED write on a stale selection. Ledger records BOTH signals so the
            # disagreement rate is measurable in shadow before the flag is flipped.
            _write_ok = bool(locals().get("_turn_write_ok", False))
            _witnessed_mode = os.environ.get("KUKAI_AUTOSHOW_WITNESSED", "0") == "1"
            _fire = autoshow_should_fire(_write_ok, _wrote, _witnessed_mode)
            _tl.record_present("chat_ws.auto_show_gate", {"kind": "auto_show_gate", "wrote_heuristic": bool(_wrote), "write_ok": _write_ok, "fire": bool(_fire), "witnessed_mode": _witnessed_mode, "auto_nav": _auto_nav, "vision": _vc_on()}, file_line="kukai/api/chat_ws.py:2317")
            if _fire and (_auto_nav or _vc_on()):
                # Step 1 — NAVIGATE the live view to the result FIRST (operator's
                # insight: select the elements as the result, THEN Zoom-to-Fit, so
                # both the user's Revit camera AND the upcoming screenshot frame the
                # actual result — not a distant overview). Reset the model's temp
                # isolation so the rest of the model stays visible (context).
                #
                # NAV-V2 (KUKAI_NAV_V2, default OFF): richer, harvest-driven
                # navigation — union of every successful write's element ids this
                # turn (not just whatever happens to be selected right now),
                # un-isolate on EVERY open view (not just the active one), and OPEN
                # a view/schedule/sheet the turn created instead of merely zooming.
                # Flag OFF ⇒ this whole branch is skipped and the legacy _NAV_CS
                # path in the `else` below runs exactly as it does today (byte-
                # identical — untouched).
                _nav_v2_on = False
                try:
                    from kukai.llm import nav_v2 as _nav_v2
                    _nav_v2_on = _nav_v2.nav_v2_enabled()
                except Exception:  # noqa: BLE001 — a broken import must not break auto-show
                    _nav_v2_on = False

                if _nav_v2_on:
                    try:
                        _nv_targets = _nav_v2.harvest_nav_targets(turn_observations)
                        _nv_ids = _nv_targets["element_ids"]
                        _nv_view = _nv_targets["open_view_id"]
                        _nv_files = _nv_targets["file_paths"]
                        _nv_skip_unisolate = _nv_targets["explicit_isolate_active"]
                        _nv_code = _nav_v2.build_nav_v2_code(
                            _nv_ids, _nv_view, skip_unisolate=_nv_skip_unisolate)
                        if _nv_code:
                            _nav = await ctx.ws_bridge_callback("execute", {"code": _nv_code})
                            _nv_opened = _nav.get("nav_opened") if isinstance(_nav, dict) else None
                            _nv_zoomed = _nav.get("nav_zoomed") if isinstance(_nav, dict) else None
                            _nv_unisolated = _nav.get("unisolated") if isinstance(_nav, dict) else None
                            logger.info("NAV_V2: opened=%s zoomed=%s unisolated=%s [%s]",
                                        _nv_opened, _nv_zoomed, _nv_unisolated, ctx.ws_id)
                            _tl.record_present("chat_ws.nav_v2_act", {
                                "kind": "nav_v2_act", "opened": _nv_opened, "zoomed": _nv_zoomed,
                                "unisolated": _nv_unisolated, "ids_n": len(_nv_ids),
                                "skip_unisolate": _nv_skip_unisolate},
                                ok=isinstance(_nav, dict) and not _nav.get("error"),
                                file_line="kukai/api/chat_ws.py:navv2act")
                        elif _nv_files:
                            # Only export file paths harvested — nothing to navigate
                            # to in Revit; surface the path in the panel instead
                            # (existing status channel), no bridge call.
                            await _emit_status(ctx.ws, f"Файл: {_nv_files[-1]}")
                            logger.info("NAV_V2: file_paths only, status emitted [%s]: %s",
                                        ctx.ws_id, _nv_files[-1])
                            _tl.record_present("chat_ws.nav_v2_act", {
                                "kind": "nav_v2_act", "opened": None, "zoomed": 0,
                                "unisolated": 0, "file_paths_n": len(_nv_files)},
                                file_line="kukai/api/chat_ws.py:navv2files")
                        else:
                            logger.info("NAV_V2: nothing to navigate this turn [%s]", ctx.ws_id)
                    except Exception as _nv_err:  # noqa: BLE001 — NAV_V2 must never break the turn
                        logger.debug("NAV_V2 final navigation failed (non-fatal): %s", _nv_err)
                        _tl.record_degradation("chat_ws.nav_v2_act", {"err": str(_nv_err)[:200]},
                                               err_code="nav_v2_failed", file_line="kukai/api/chat_ws.py:navv2deg")
                else:
                    _NAV_CS = (
                        "var res=new Dictionary<string,object>();"
                        "try{var v=uidoc.ActiveView;"
                        "try{if(v.IsTemporaryHideIsolateActive()){"
                        "using(var t=new Transaction(doc,\"kukai_unisolate\")){t.Start();"
                        "v.DisableTemporaryViewMode(TemporaryViewMode.TemporaryHideIsolate);t.Commit();}}}catch{}"
                        "var sel=uidoc.Selection.GetElementIds();"
                        "if(sel!=null && sel.Count>0){try{uidoc.ShowElements(sel);res[\"nav\"]=sel.Count;}catch{}}"
                        "}catch{}return res;"
                    )
                    _nav = await ctx.ws_bridge_callback("execute", {"code": _NAV_CS})
                    logger.info("Auto-navigate: pointed Revit camera at result [%s] (elements=%s)",
                                ctx.ws_id, _nav.get("nav") if isinstance(_nav, dict) else None)
                    _tl.record_present("chat_ws.auto_nav", {"kind": "auto_nav", "nav": _nav.get("nav") if isinstance(_nav, dict) else None}, ok=isinstance(_nav, dict) and not _nav.get("error"), file_line="kukai/api/chat_ws.py:autonav")

                # Step 2 — VISION CRITIC (KUKAI_VISION_CRITIC): the chat model is
                # blind (text-only), so a SEPARATE vision model looks at the framed
                # result and returns an engineering verdict (created? placed right?
                # missing parts? anomalies?). Kills fake-готово: the eyes judge
                # INDEPENDENTLY of what deepseek claimed. The verdict goes to the
                # user AND is stashed for the next turn's context so the brain can
                # fix on the next round. Screenshot is captured HERE (after
                # navigation), NOT pushed to the panel — it's the agent's eyes.
                if _vc_on():
                    try:
                        # FRAME the result before shooting: select exactly what this
                        # write touched and zoom to it, keeping the rest of the building
                        # visible. NOT isolation — judging "did I fix this floor right"
                        # needs the neighbours (does it meet the walls, hang in the air,
                        # clash?); an isolated element floating in the void always looks
                        # perfect and proves nothing. Selection also paints the elements
                        # blue, so the inspector knows which ones are the subject.
                        try:
                            from kukai.api.bridge_protocol import take_last_write_ids
                            _wids = take_last_write_ids(ctx.ws_id)
                        except Exception:  # noqa: BLE001
                            _wids = []
                        if _wids:
                            _ids_cs = ",".join(str(i) for i in _wids[:200])
                            # Zoom by BOUNDING BOX, not ShowElements: ShowElements can
                            # raise the modal "no open view shows these elements" dialog,
                            # which would park Revit waiting for a click that nobody is
                            # there to make. ZoomAndCenterRectangle never prompts. The box
                            # is padded 1.5x so neighbours stay in frame — the inspector
                            # judges the result IN CONTEXT, not floating in the void.
                            _FRAME_CS = (
                                "var res=new Dictionary<string,object>();"
                                "var ids=new List<ElementId>();"
                                f"foreach(var n in new int[]{{{_ids_cs}}})"
                                "{ try{ ids.Add(new ElementId(n)); }catch{} }"
                                "if(ids.Count==0){ res[\"framed\"]=0; return res; }"
                                "try{ uidoc.Selection.SetElementIds(ids); }catch{}"
                                "double x1=1e12,y1=1e12,z1=1e12,x2=-1e12,y2=-1e12,z2=-1e12; int seen=0;"
                                "foreach(var id in ids){ try{"
                                " var el=doc.GetElement(id); if(el==null) continue;"
                                " var bb=el.get_BoundingBox(doc.ActiveView); if(bb==null) bb=el.get_BoundingBox(null);"
                                " if(bb==null) continue; seen++;"
                                " if(bb.Min.X<x1)x1=bb.Min.X; if(bb.Min.Y<y1)y1=bb.Min.Y; if(bb.Min.Z<z1)z1=bb.Min.Z;"
                                " if(bb.Max.X>x2)x2=bb.Max.X; if(bb.Max.Y>y2)y2=bb.Max.Y; if(bb.Max.Z>z2)z2=bb.Max.Z;"
                                "}catch{} }"
                                "res[\"framed\"]=ids.Count; res[\"boxed\"]=seen;"
                                "if(seen>0){ try{"
                                " double cx=(x1+x2)/2, cy=(y1+y2)/2, cz=(z1+z2)/2;"
                                " double hx=Math.Max((x2-x1)/2,1.0)*1.5, hy=Math.Max((y2-y1)/2,1.0)*1.5, hz=Math.Max((z2-z1)/2,1.0)*1.5;"
                                " var p1=new XYZ(cx-hx,cy-hy,cz-hz); var p2=new XYZ(cx+hx,cy+hy,cz+hz);"
                                " foreach(var uv in uidoc.GetOpenUIViews()){"
                                "  if(uv.ViewId==doc.ActiveView.Id){ uv.ZoomAndCenterRectangle(p1,p2); res[\"zoomed\"]=true; break; } }"
                                "}catch(Exception ze){ res[\"zoom_error\"]=ze.Message; } }"
                                "return res;"
                            )
                            try:
                                _fr = await ctx.ws_bridge_callback("execute", {"code": _FRAME_CS})
                                logger.info("Vision framing [%s]: выделено %s элементов записи",
                                            ctx.ws_id,
                                            _fr.get("framed") if isinstance(_fr, dict) else "?")
                            except Exception as _fr_err:  # noqa: BLE001
                                logger.debug("vision framing failed (non-fatal): %s", _fr_err)
                        _shot = await ctx.ws_bridge_callback(
                            "export_view", {"filename": "kukai_vision.png", "format": "png"})
                        _b64 = _shot.get("image_base64") if isinstance(_shot, dict) else None
                        if _b64 and ctx.message_text:
                            from kukai.llm.vision_critic import critique
                            _v = await critique(
                                ctx.message_text, _b64,
                                api_key=os.environ.get("KUKAI_LLM_API_KEY") or None)
                            if isinstance(_v, dict):
                                # User-facing «Проверка глазами» briefing removed per
                                # operator (2026-07-07): the eyes stay (the verdict feeds
                                # the blind text model on the next turn), the user is NOT
                                # notified.
                                # stash for next turn's brain context
                                try:
                                    _st = _session_states.get(ctx.ws_id)
                                    if _st is not None:
                                        _st.last_vision_verdict = _v
                                except Exception:  # noqa: BLE001
                                    pass
                                logger.info("Vision critic [%s]: вердикт=%s комментарий=%s",
                                            ctx.ws_id, _v.get("вердикт"), _v.get("комментарий"))
                                _tl.record_present("chat_ws.vision_critic", {"kind": "vision_verdict", "verdict": _v.get("вердикт"), "comment": str(_v.get("комментарий", ""))[:200]}, file_line="kukai/api/chat_ws.py:vision")
                    except Exception as _vc_err:  # noqa: BLE001
                        logger.debug("vision critic failed (non-fatal): %s", _vc_err)
                        _tl.record_degradation("chat_ws.vision_critic", {"err": str(_vc_err)[:200]}, err_code="vision_failed", file_line="kukai/api/chat_ws.py:vis_deg")
        except Exception as _as_err:  # noqa: BLE001
            logger.debug("auto-navigate/vision failed (non-fatal): %s", _as_err)
            _tl.record_degradation("chat_ws.auto_show", {"err": str(_as_err)[:200]}, err_code="auto_show_failed", file_line="kukai/api/chat_ws.py:as_deg")

        # Reveal (KUKAI_REVEAL_FOUND): deterministically SELECT + FRAME the latest
        # find so the user ALWAYS sees the result — no LLM decision. This is a READ
        # sibling of the write-only auto-show above. Shadow records the fire
        # decision + size (to sight the effect before enabling); on acts. Never
        # breaks the turn.
        try:
            from kukai.llm import reveal as _reveal
            _rmode = _reveal.reveal_mode()
            if _rmode != "off":
                _rcap = _reveal.reveal_cap()
                _rfire = _reveal.should_reveal(
                    _turn_found_ids, bool(locals().get("_turn_write_ok", False)),
                    (locals().get("_turn_tool_names") or []), _rcap)
                _tl.record_present("chat_ws.reveal_gate", {
                    "kind": "reveal_gate", "mode": _rmode, "found": len(_turn_found_ids),
                    "fire": bool(_rfire), "cap": _rcap}, file_line="kukai/api/chat_ws.py:reveal")
                # Log the gate in BOTH shadow and on, so the reveal fire-rate + find
                # sizes are measurable from live_test.log even if the TurnLedger is
                # not persisting queryable rows (review finding #1).
                logger.info("Reveal-found gate [%s]: mode=%s found=%s fire=%s cap=%s",
                            ctx.ws_id, _rmode, len(_turn_found_ids), bool(_rfire), _rcap)
                if _rfire and _rmode == "on" and ctx.ws_bridge_callback is not None:
                    _rcode = _reveal.build_reveal_code(_turn_found_ids)
                    _rres = await ctx.ws_bridge_callback("execute", {"code": _rcode})
                    _rn = _rres.get("revealed") if isinstance(_rres, dict) else None
                    logger.info("Reveal-found [%s]: selected+framed %s elements", ctx.ws_id, _rn)
                    _tl.record_present("chat_ws.reveal_act", {"kind": "reveal_act", "revealed": _rn},
                                       ok=isinstance(_rres, dict) and not _rres.get("error"),
                                       file_line="kukai/api/chat_ws.py:reveal_act")
        except Exception as _rev_err:  # noqa: BLE001 — reveal must never break a turn
            logger.debug("reveal-found failed (non-fatal): %s", _rev_err)
            _tl.record_degradation("chat_ws.reveal", {"err": str(_rev_err)[:200]},
                                   err_code="reveal_failed", file_line="kukai/api/chat_ws.py:rev_deg")

        # _REASONING_TRACE_PATCHED_ — flush accumulated trace (best-effort)
        if ctx.reasoning_trace is not None and ctx._flush_reasoning_trace is not None:
            try:
                await ctx._flush_reasoning_trace(ctx.reasoning_trace)
            except Exception as _trace_flush_err:  # noqa: BLE001
                logger.debug("reasoning_trace flush failed: %s", _trace_flush_err)

        elapsed_ms = int((_time.monotonic() - ctx.request_start) * 1000)
        logger.info("CHAT COMPLETE [%s]: %dms, text=%d chars", ctx.ws_id, elapsed_ms, len(collected_text) if 'collected_text' in dir() else 0)
        # plan-009: attach the per-turn retrieval_health snapshot to the metrics
        # row and close the turn. Guarded — never lets instrument bookkeeping
        # break the telemetry write or the request.
        if ctx._turn_health is not None:
            # Guard the ARGUMENT eval (_turn_health.to_dict()) — it runs OUTSIDE
            # record()'s own try/except, and this is in the finally BEFORE the
            # final-save, so an unlucky raise here must not skip persistence.
            try:
                _tl.record_retrieval("chat_ws.turn_close", ctx._turn_health.to_dict(), ok=not ctx._turn_health.degraded, file_line="kukai/api/chat_ws.py:retr")
            except Exception:  # noqa: BLE001 — the ledger must never break the finally
                pass
            try:
                if ctx.metrics is not None:
                    ctx.metrics.retrieval_health = (
                        ctx._turn_health.to_json() if ctx._turn_health.legs else None
                    )
            finally:
                from kukai.rag import retrieval_health as _rh
                _rh.finish_turn(ctx._turn_health)

        # Accumulate this turn's input tokens into the tenant's daily total for
        # the soft KUKAI_TOKENS_PER_DAY ceiling (checked at the next turn's start).
        # Step 11: must use the SAME key as check_and_count_turn above.
        if ctx.metrics is not None:
            add_device_tokens(ctx.tenant_id, getattr(ctx.metrics, "total_input_tokens", None))
        # Record telemetry regardless of success/failure
        if ctx.metrics:
            ctx.metrics.response_time_ms = elapsed_ms
            try:
                from kukai.telemetry import TelemetryCollector
                collector = TelemetryCollector(ctx.state.db)
                await collector.record(ctx.metrics)
                _tl.record_persistence("chat_ws.telemetry", {"op": "telemetry_record"}, ok=True, file_line="kukai/api/chat_ws.py:tel_ok")
            except Exception as e:
                # IRON 10 — telemetry stays non-blocking, but no longer silent.
                from kukai.telemetry import note_telemetry_failure
                note_telemetry_failure(e)
                _tl.record_persistence("chat_ws.telemetry", {"op": "telemetry_record"}, ok=False, err_code=type(e).__name__, file_line="kukai/api/chat_ws.py:tel_err")

    # Note: rate limit logging moved to check_rate_limit() (log-before-process)

    # Pillar C (grounding gate) — POST-HOC: log the grounding verdict for A/B,
    # and on "annotate" (a specific norm clause cited without a lookup_norm
    # result) append a non-destructive caveat to the persisted answer. We do NOT
    # send a late stream_chunk (the stream already ended) — the caveat lands in
    # history; the PREVENTIVE nudge above is the primary live fix.
    if collected_text:
        try:
            from kukai import config as _kcfg
            from kukai.agents.rollout import (
                in_treatment as _in_treat,
                log_rollout_telemetry as _log_route,
            )
            from kukai.api.grounding_gate import (
                evaluate_grounding as _eval_ground,
                cited_norm_clauses as _cited_norms,
                lookup_norm_hit as _ln_hit,
                is_analysis_turn as _is_analysis_g,
            )
            if _kcfg.AGENT_USE_GROUNDING_GATE and _in_treat(ctx.session_id, _kcfg.AGENT_TEST_PERCENT):
                # B2: attach each lookup_norm's real result (aligned by order) so
                # the gate distinguishes a HIT from a miss — a norm cited after an
                # empty lookup gets the ⚠️ annotation instead of a silent pass.
                _ln_iter = iter(_turn_lookup_norm_results)
                _turn_msgs = [
                    ({"role": "tool", "_tool_name": n, "_result": next(_ln_iter, None)}
                     if n == "lookup_norm" else {"role": "tool", "_tool_name": n})
                    for n in _turn_tool_names
                ]
                _g = _eval_ground(ctx.message_text, collected_text, _turn_msgs)
                _log_route({"kind": "gate", "session": ctx.session_id, "verdict": _g.verdict,
                            "reason": _g.reason, "tools": _turn_tool_names})
                # A0 (golden-replay): record the gate INPUTS, not just the verdict,
                # so the grounding decision is auditable and faithfully replayable
                # (verdict alone is circular — can't re-derive without the inputs).
                _cn = _cited_norms(collected_text)
                _tl.record_present("chat_ws.grounding_gate", {
                    "kind": "grounding", "verdict": _g.verdict,
                    "reason": str(_g.reason)[:200],
                    "tools": list(_turn_tool_names)[:20],
                    "analysis_turn": bool(_is_analysis_g(ctx.message_text)),
                    "cited_norms": [str(c) for c in _cn[:8]],
                    "cited_norms_n": len(_cn),
                    "lookup_norm_hit": bool(_ln_hit(_turn_msgs)),
                    "answer_len": len(collected_text or ""),
                }, ok=(_g.verdict != "annotate"), file_line="kukai/api/chat_ws.py:grounding")
                if _g.verdict == "annotate":
                    collected_text += (
                        "\n\n⚠️ _Пункт нормы указан без подтверждения через `lookup_norm` — "
                        "требуется сверка по официальному тексту нормы._"
                    )
        except Exception as _e:  # noqa: BLE001 — gate must never block the save
            logger.warning("grounding gate (post-hoc) skipped: %s", _e)
            _tl.record_degradation("chat_ws.grounding_gate", {"err": str(_e)[:200]}, err_code="gate_skipped", file_line="kukai/api/chat_ws.py:gate_deg")

    # Save final assistant text message (after all tool calls are done)
    # B4: route the final visible message through save_turn (the transactional
    # path) so ALL turn persistence uses one atomic primitive — consistent with
    # the tool_call/tool_result pair save above. Tool pairs already commit
    # atomically (orphan hazard closed); this unifies the final leg on the same
    # transaction machinery instead of a lone save_message.
    if collected_text:
        assistant_msg = Message(
            id=str(uuid.uuid4()),
            session_id=ctx.session_id,
            role="assistant",
            content=collected_text,
        )
        await ctx.state.db.save_turn([assistant_msg])
        _tl.record_persistence("chat_ws.final_save", {"op": "save_final_message", "chars": len(collected_text)}, ok=True, file_line="kukai/api/chat_ws.py:finalsave")

    # Project memory: save periodically (every 5 exchanges)
    # B3: enqueue to the background outbox — save_session_memory makes its OWN LLM
    # call, and awaiting it here held the per-WS chat slot open for seconds AFTER
    # the user already had their answer (throttling concurrent turns). The cheap
    # DB reads stay inline (they gate whether to save at all); only the expensive
    # extraction is detached via _spawn_bg.
    if ctx.project_name and ctx.tenant_id and collected_text:
        # Step 11: memory writes go to the effective tenant (flag OFF ⇒ device_id)
        try:
            msg_count = await ctx.state.db.count_project_memories(ctx.tenant_id, ctx.project_name)
            history_msgs = await ctx.state.db.get_session_messages(ctx.session_id, limit=20)
            user_count = sum(1 for m in history_msgs if m.role == "user")
            # Save memory every 5 user messages, or on first message if no memory exists
            if user_count >= 5 and user_count % 5 == 0 or (msg_count == 0 and user_count >= 2):
                from kukai.llm.project_memory import save_session_memory
                msg_dicts = [{"role": m.role, "content": m.content} for m in history_msgs]
                _spawn_bg(
                    save_session_memory(
                        ctx.state.db, ctx.tenant_id, ctx.project_name, msg_dicts,
                        ctx.settings.llm_model, ctx.settings.llm_api_key,
                        ctx.settings.llm_api_base,
                    ),
                    label=f"project_memory:{ctx.session_id[:8]}",
                )
        except Exception as e:
            logger.debug("Project memory save skipped: %s", e)
            _tl.record_persistence("chat_ws.project_memory", {"op": "project_memory"}, ok=False, err_code=type(e).__name__, file_line="kukai/api/chat_ws.py:pmem")
