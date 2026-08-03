"""Bridge request/response protocol — peeled verbatim from chat_ws.py.

Golden-path decomposition Phase 1 (2026-07-12): request/response correlation
(_pending_bridge_requests), timeouts, change-manifest witness, the C# wrapper
template, _handle_bridge_response and _bridge_callback. Pure file move, zero
behavior change. NOTE: the legacy execute chain inside _bridge_callback is
Phase-5 material (RevitExecutionPipeline retires it) — moved as-is here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import WebSocket

from kukai import turn_ledger as _tl
from kukai.llm.envelope import (
    ErrCode,
    attach_err,
    classify_bridge_error,
    extract_cs_codes,
    friendly_bridge_message,
)
from kukai.operations.protocol import (
    OperationIdentity,
    OperationOutcome,
    OperationPhase,
)
from kukai.operations.effects import (
    ExecutionEffect,
    ReadOnlyContractViolation,
    consume_execution_effect,
)
from kukai.operations.store import (
    InMemoryOperationStore,
    OperationConflict,
    OperationRecord,
    OperationStore,
)
from kukai.security.encryption import SessionEncryption
from kukai.security.obfuscator import obfuscate_code_with_map

from kukai.api.ws_send import _send_json
from kukai.api.ws_registry import (
    _build_model_details,
    _session_contexts,
    _session_detailed_passports,
    _session_keys,
)

logger = logging.getLogger(__name__)


_pending_bridge_requests: dict[str, tuple[str, asyncio.Future[dict[str, Any]]]] = {}
# req_id (transport attempt) -> operation identity/store. Kept separate from
# the legacy tuple map so existing cleanup code and tests remain compatible.
_pending_bridge_operations: dict[str, tuple[OperationIdentity, OperationStore]] = {}
_bridge_receipts: dict[str, dict[str, Any]] = {}
_bridge_receipt_hashes: dict[str, str] = {}
_BRIDGE_RECEIPTS_MAX = 512
_fallback_operation_store = InMemoryOperationStore()


def _operation_store() -> OperationStore:
    """Resolve the production Postgres store, with a strict in-memory fallback
    for unit tests and pre-start code paths."""
    try:
        from kukai.main import get_app_state

        store = getattr(get_app_state(), "operation_store", None)
        if store is not None:
            return store
    except Exception:
        pass
    return _fallback_operation_store


def _device_hash(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _operation_context(
    method: str,
    params: dict[str, Any],
) -> tuple[dict[str, Any], Optional[OperationIdentity], ExecutionEffect, Optional[str]]:
    """Remove internal metadata and resolve a fail-closed execution effect."""
    try:
        clean, effect, read_source = consume_execution_effect(method, params)
    except ReadOnlyContractViolation as exc:
        raise OperationConflict(str(exc)) from exc
    raw = clean.pop("_operation", None)
    if method != "execute":
        return clean, None, effect, read_source
    if effect is ExecutionEffect.READ_ONLY:
        if raw is not None:
            raise OperationConflict(
                "read-only execution cannot carry a write operation identity"
            )
        return clean, None, effect, read_source
    if isinstance(raw, dict):
        try:
            return (
                clean,
                OperationIdentity.from_mapping(raw),
                effect,
                read_source,
            )
        except ValueError as exc:
            logger.warning("invalid operation identity rejected: %s", exc)
            raise OperationConflict(str(exc)) from exc
    if raw is not None:
        raise OperationConflict("operation identity must be an object")

    # Legacy/internal caller: still give the dispatch a unique v2 identity.
    # It is not stable across a brand-new caller retry, so retry policy remains
    # conservative after SENT. Normal LLM writes arrive with explicit identity.
    ledger = _tl.current()
    turn_id = ledger.turn_id if ledger is not None else str(uuid.uuid4())
    return (
        clean,
        OperationIdentity.for_payload(
            turn_id=turn_id,
            tool_call_id=str(uuid.uuid4()),
            tool_name="execute_revit_code",
            method=method,
            params=clean,
        ),
        effect,
        read_source,
    )


def _stash_bridge_receipt(
    req_id: str,
    receipt: dict[str, Any],
    receipt_hash: str = "",
) -> None:
    if len(_bridge_receipts) >= _BRIDGE_RECEIPTS_MAX:
        oldest = next(iter(_bridge_receipts))
        _bridge_receipts.pop(oldest, None)
        _bridge_receipt_hashes.pop(oldest, None)
    _bridge_receipts[req_id] = receipt
    normalized_hash = str(receipt_hash or "").lower()
    if len(normalized_hash) == 64 and all(c in "0123456789abcdef" for c in normalized_hash):
        _bridge_receipt_hashes[req_id] = normalized_hash


def _unknown_operation_result(operation_id: str, message: str) -> dict[str, Any]:
    return attach_err(
        {
            "error": True,
            "state": OperationOutcome.RUNNING_UNKNOWN.value,
            "operation_id": operation_id,
            "message": message,
        },
        ErrCode.TRANSPORT_EXECUTION_UNKNOWN,
    )


def _tool_result_from_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Return a compact model-facing result from an already durable receipt."""
    raw = receipt.get("result")
    result = dict(raw) if isinstance(raw, dict) else {"result": raw}
    outcome = str(receipt.get("outcome") or "")
    operation_id = str(receipt.get("operation_id") or "")
    result.setdefault("operation", {"operation_id": operation_id, "outcome": outcome})
    if outcome in {
        OperationOutcome.REJECTED_BEFORE_EXECUTION.value,
        OperationOutcome.CANCELLED_BEFORE_START.value,
        OperationOutcome.FAILED_BEFORE_COMMIT.value,
        OperationOutcome.ROLLED_BACK.value,
        OperationOutcome.COMMITTED_PARTIAL.value,
    }:
        result.setdefault("error", True)
        result.setdefault("message", str(receipt.get("error") or outcome))
    else:
        result.setdefault("error", False)
    return result

BRIDGE_REQUEST_TIMEOUT = 4500.0  # seconds (75 min) — legacy global ceiling (exports etc.)
# Per-method ceiling for the hot execute path (Step 5): a non-responding Revit bridge
# must fail FAST with an honest "Revit не ответил" error, not hang the user for 75 min
# on an infinite spinner. Operator-set 200s (2026-07-08). Env-tunable; default in code
# so no .env edit is needed (avoids the .env-perms restart trap).
_EXECUTE_BRIDGE_TIMEOUT_S = float(os.environ.get("KUKAI_EXECUTE_BRIDGE_TIMEOUT_S", "200"))
_BRIDGE_METHOD_TIMEOUTS_S = {
    "discover": float(os.environ.get("KUKAI_DISCOVER_BRIDGE_TIMEOUT_S", "8")),
    "context": float(os.environ.get("KUKAI_CONTEXT_BRIDGE_TIMEOUT_S", "20")),
    "get_model_details": float(os.environ.get("KUKAI_MODEL_DETAILS_BRIDGE_TIMEOUT_S", "20")),
    "select": float(os.environ.get("KUKAI_SELECT_BRIDGE_TIMEOUT_S", "15")),
    "highlight": float(os.environ.get("KUKAI_HIGHLIGHT_BRIDGE_TIMEOUT_S", "15")),
    "export_view": float(os.environ.get("KUKAI_EXPORT_VIEW_BRIDGE_TIMEOUT_S", "90")),
}


def _effective_bridge_timeout(method: str, params: dict) -> float:
    """The wait ceiling for a bridge request. An explicit ``timeout_ms`` wins, but the
    hot ``execute`` path is HARD-capped at _EXECUTE_BRIDGE_TIMEOUT_S so a stuck bridge
    can never hang the user for 75 min — an honest timeout + retry beats a dead spinner."""
    t = BRIDGE_REQUEST_TIMEOUT
    if "timeout_ms" in params:
        # +10s buffer for compilation + network overhead on top of execution timeout
        t = (params["timeout_ms"] / 1000.0) + 10.0
    if method == "execute":
        t = min(t, _EXECUTE_BRIDGE_TIMEOUT_S)
    elif method in _BRIDGE_METHOD_TIMEOUTS_S:
        t = min(t, _BRIDGE_METHOD_TIMEOUTS_S[method])
    return t

# ── Change-manifest witness (truth-layer P1, flag KUKAI_CHANGE_WITNESS) ──────
# The Step-4 C# bridge attaches a top-level `changes` object to bridge_response
# for executes that committed transactions:
#   { "added": [ids], "modified": [ids], "deleted": [ids],
#     "txns": ["KUKAI: ..."], "truncated": false }
# `changes` is ABSENT (not null) for reads, non-execute methods, and errors —
# so this whole path is a no-op for every pre-Step-4 DLL. Flag OFF (default)
# is byte-identical to pre-witness behavior. The FULL manifest goes to
# data/witness_changes.jsonl (fail-open, never blocks the bridge future);
# ONLY a counts summary {"changed": {added,modified,deleted}} rides the dict
# tool-result so raw id arrays never flood LLM context. The stash is bounded
# FIFO — an abandoned req_id can never grow it past the cap.
_bridge_change_manifests: dict[str, dict[str, Any]] = {}  # req_id -> manifest
_BRIDGE_CHANGE_MANIFESTS_MAX = 256

# The obfuscator renames local variables before code leaves the server, and it
# correctly skips string literals — but C# shorthand members take their NAME
# from the variable: `new { minX, maxX }` serialises to keys "minX"/"maxX", so
# renaming the variable renames the RESULT KEY the model then has to read back.
# Measured on prod 2026-07-27: 22 of 873 bridge results came back with `_0x…`
# keys, including one carrying element ids ({'_0xa703': '874533'}) — the model
# asked for ids and got a field it cannot recognise. The rename map already
# exists (it de-obfuscates error text); this keeps it for the result too.
_obf_maps: dict[str, dict[str, str]] = {}  # req_id -> {original: obfuscated}
_OBF_MAPS_MAX = 256


def _deobfuscate_result(value: Any, inverse: dict[str, str]) -> Any:
    """Map ``_0x…`` identifiers in a bridge result back to what the model wrote.

    Keys and exact-match string values only — a partial/substring rewrite could
    corrupt legitimate content, and the obfuscator only ever emits whole
    ``_0x{4 hex}`` tokens.
    """
    if isinstance(value, dict):
        return {
            (inverse.get(k, k) if isinstance(k, str) else k):
            _deobfuscate_result(v, inverse)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_deobfuscate_result(v, inverse) for v in value]
    if isinstance(value, str) and _OBF_TOKEN_RE.fullmatch(value):
        return inverse.get(value, value)
    return value


_OBF_TOKEN_RE = re.compile(r"_0x[0-9a-fA-F]{4}")


def _restore_obfuscated_names(req_id: str, result: Any) -> Any:
    """Undo the outbound rename on an inbound result. Never raises."""
    rename_map = _obf_maps.pop(req_id, None)
    if not rename_map or not isinstance(result, (dict, list)):
        return result
    try:
        return _deobfuscate_result(
            result, {obf: orig for orig, obf in rename_map.items()})
    except Exception:  # noqa: BLE001 — a cosmetic repair must never fail a turn
        logger.exception("de-obfuscating bridge result failed")
        return result


def _change_witness_enabled() -> bool:
    """KUKAI_CHANGE_WITNESS flag — default OFF; read per-call so tests and
    ops can flip it without a restart."""
    return os.getenv("KUKAI_CHANGE_WITNESS", "0").strip().lower() in (
        "1", "true", "yes", "on"
    )


def _stash_change_manifest(req_id: str, changes: dict[str, Any]) -> None:
    """Keep the manifest until _bridge_callback resolves; bounded FIFO."""
    if len(_bridge_change_manifests) >= _BRIDGE_CHANGE_MANIFESTS_MAX:
        _bridge_change_manifests.pop(next(iter(_bridge_change_manifests)), None)
    _bridge_change_manifests[req_id] = changes


def _manifest_counts(changes: dict[str, Any]) -> dict[str, int]:
    """Counts-only summary for the LLM-facing tool result. Defensive: any
    non-list field (malformed DLL output) counts as 0 rather than raising."""
    def _n(key: str) -> int:
        v = changes.get(key)
        return len(v) if isinstance(v, (list, tuple)) else 0

    return {"added": _n("added"), "modified": _n("modified"), "deleted": _n("deleted")}


def _witness_log_path() -> Path:
    """Resolve the witness sink: env override or backend/data/ (same pattern
    as reasoning_traces.jsonl — backend/data/ exists in dev and prod)."""
    override = os.getenv("KUKAI_WITNESS_LOG_PATH", "").strip()
    if override:
        return Path(override)
    # this file lives at backend/kukai/api/chat_ws.py → backend/
    return Path(__file__).resolve().parent.parent.parent / "data" / "witness_changes.jsonl"


def _record_witness(ws_id: str, req_id: str, method: str, changes: dict[str, Any]) -> None:
    """Append the FULL manifest as one JSONL row. Fail-open: any error is
    logged at debug and swallowed — the witness must never break a turn."""
    try:
        path = _witness_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": time.time(),
            "ws_id": ws_id,
            "req_id": req_id,
            "method": method,
            "changes": changes,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 — witness is strictly best-effort
        logger.debug("witness write failed", exc_info=True)


# ws_id -> ElementIds this session's last write actually touched. The witness
# manifest already knows them; keeping the last set in memory lets the post-write
# vision shot FRAME the result (select + zoom) instead of photographing whatever
# the camera happened to look at. Bounded, best-effort, dropped on reconnect.
_last_write_ids: dict[str, list[int]] = {}
_LAST_WRITE_IDS_MAX = 200


def take_last_write_ids(ws_id: str) -> list[int]:
    """Pop the ids the last witnessed write touched on this connection."""
    return _last_write_ids.pop(ws_id, [])


def _remember_write_ids(ws_id: str, changes: dict[str, Any]) -> None:
    try:
        ids: list[int] = []
        for key in ("added", "modified"):
            for v in (changes.get(key) or []):
                try:
                    ids.append(int(v))
                except (TypeError, ValueError):
                    continue
        if not ids:
            return
        if len(_last_write_ids) > 500:
            _last_write_ids.clear()
        _last_write_ids[ws_id] = ids[:_LAST_WRITE_IDS_MAX]
    except Exception:  # noqa: BLE001 — framing is a nicety, never a turn-breaker
        logger.debug("remember write ids failed", exc_info=True)


def _drain_witness(req_id: str, ws_id: str, method: str) -> None:
    """Pop the stashed manifest for a completed bridge request and persist it.
    No-op when nothing was stashed (flag OFF, reads, old DLL)."""
    manifest = _bridge_change_manifests.pop(req_id, None)
    if manifest is not None:
        _record_witness(ws_id, req_id, method, manifest)
        _remember_write_ids(ws_id, manifest)

# Wrapper template for LLM-generated C# code. Compiled into a Kukai.UserCode
# class with an Execute(Document, UIDocument) method. Roslyn diagnostics report
# line numbers in the wrapped code; we subtract _WRAPPER_LINE_OFFSET to map them
# back to user-code line numbers when surfacing errors to the LLM repair loop.
#
# The offset is DERIVED from the header so it stays correct if anyone edits
# the using-list or class skeleton — a hardcoded value silently goes off-by-one.
_WRAPPER_HEADER = (
    "using System;\n"
    "using System.Linq;\n"
    "using System.Collections.Generic;\n"
    "using System.Text;\n"
    "using System.Text.RegularExpressions;\n"
    "using Autodesk.Revit.DB;\n"
    "using Autodesk.Revit.DB.Architecture;\n"
    "using Autodesk.Revit.DB.Structure;\n"
    "using Autodesk.Revit.DB.Mechanical;\n"
    "using Autodesk.Revit.DB.Electrical;\n"
    "using Autodesk.Revit.DB.Plumbing;\n"
    "using Autodesk.Revit.UI;\n"
    "\n"
    "namespace Kukai\n"
    "{\n"
    "    public class UserCode\n"
    "    {\n"
    "        public static object Execute(Document doc, UIDocument uidoc)\n"
    "        {\n"
)
_WRAPPER_FOOTER = (
    "\n"
    "        }\n"
    "    }\n"
    "}\n"
)
# Number of lines the header occupies. User code line N appears in wrapped
# code at line N + _WRAPPER_LINE_OFFSET, so wrapped_line - offset == user_line.
_WRAPPER_LINE_OFFSET = _WRAPPER_HEADER.count("\n")


def _handle_bridge_response(data: dict[str, Any], sender_ws_id: Optional[str] = None) -> None:
    """Handle bridge_response message — resolve pending future.

    C# sends: { type, id, success, error?, result? }
    JS fallback sends: { type, id, error?: {code, message}, result? }

    B5: ``sender_ws_id`` is the connection that DELIVERED this response. A
    response may only resolve a request OWNED by the same connection — a response
    arriving on a different WS must not resolve (or consume) another session's
    pending future (cross-session bridge bleed, same class as the WAVE0 leak).
    None ⇒ owner check skipped (back-compat for internal callers).
    """
    req_id = data.get("id", "")
    entry = _pending_bridge_requests.get(req_id)  # peek — consume only once owned
    if entry is None:
        logger.warning("Received bridge_response for unknown/completed request: %s", req_id)
        _tl.orphan_bridge_response(req_id)
        # Change witness (KUKAI_CHANGE_WITNESS): a LATE response carrying a
        # manifest = a committed write the model never saw (its request was
        # already cancelled/timed out — the double-commit root). Record it
        # straight to the sink for forensics; nothing to stash or resolve.
        try:
            _orphan_changes = data.get("changes")
            if _change_witness_enabled() and isinstance(_orphan_changes, dict):
                _record_witness("", req_id, "orphaned_response", _orphan_changes)
        except Exception:  # noqa: BLE001 — witness is strictly best-effort
            logger.debug("orphan witness failed", exc_info=True)
        return

    _ws_id, future = entry
    # B5: reject a response whose sender is not the request's owner — leave the
    # pending future intact so the real owner can still be resolved.
    if sender_ws_id is not None and _ws_id and sender_ws_id != _ws_id:
        logger.warning(
            "bridge_response sender=%s != owner=%s for req %s — rejected",
            sender_ws_id, _ws_id, req_id,
        )
        _tl.record_bridge(
            "chat_ws._handle_bridge_response",
            {"req_id": req_id, "sender": sender_ws_id, "owner": _ws_id},
            ok=False, err_code="bridge_sender_mismatch",
            file_line="kukai/api/chat_ws.py:sender_mismatch",
        )
        return

    op_entry = _pending_bridge_operations.get(req_id)
    if op_entry is not None:
        expected_identity, _ = op_entry
        response_operation_id = str(data.get("operation_id") or "")
        if response_operation_id and response_operation_id != expected_identity.operation_id:
            logger.error(
                "bridge_response operation mismatch req=%s expected=%s got=%s",
                req_id,
                expected_identity.operation_id,
                response_operation_id,
            )
            _tl.record_bridge(
                "chat_ws._handle_bridge_response",
                {
                    "req_id": req_id,
                    "expected_operation_id": expected_identity.operation_id,
                    "response_operation_id": response_operation_id,
                },
                ok=False,
                err_code="bridge_operation_mismatch",
                file_line="kukai/api/bridge_protocol.py:operation_mismatch",
            )
            return
        receipt = data.get("receipt")
        if isinstance(receipt, dict):
            try:
                receipt_identity = OperationIdentity.from_mapping(receipt)
            except ValueError:
                logger.error("bridge receipt has invalid identity req=%s", req_id)
                return
            if receipt_identity != expected_identity:
                logger.error("bridge receipt identity mismatch req=%s", req_id)
                return
            try:
                OperationOutcome(str(receipt.get("outcome") or ""))
            except ValueError:
                logger.error("bridge receipt has invalid outcome req=%s", req_id)
                return
            _stash_bridge_receipt(
                req_id,
                receipt,
                str(data.get("receipt_hash") or ""),
            )
    _pending_bridge_requests.pop(req_id, None)  # now consume — it is ours
    if future.done():
        return

    # Check for error conditions:
    # 1) C# path: success=false, error="message string"
    # 2) JS fallback path: error={code, message}
    error_field = data.get("error")
    success_field = data.get("success", True)

    if error_field is not None:
        err_msg = error_field.get("message", str(error_field)) if isinstance(error_field, dict) else str(error_field)
        logger.warning("BRIDGE ERROR [%s]: %s", _ws_id, err_msg[:300])
        # Error from bridge — propagate as dict with error flag
        if isinstance(error_field, dict):
            # JS fallback format: {code: -32010, message: "..."}
            # Legacy numeric `code` (JSON-RPC) is preserved; the new machine
            # `err.code` is added additively alongside it.
            _msg = error_field.get("message", "Bridge error")
            _code = classify_bridge_error(_msg)
            future.set_result(attach_err(
                {
                    "error": True,
                    "message": friendly_bridge_message(_code, _msg),
                    "code": error_field.get("code", -32010),
                },
                _code,
                cs_codes=extract_cs_codes(_msg),
            ))
        else:
            # C# format: error is a string
            _msg = str(error_field)
            _code = classify_bridge_error(_msg)
            future.set_result(attach_err(
                {
                    "error": True,
                    "message": friendly_bridge_message(_code, _msg),
                },
                _code,
                cs_codes=extract_cs_codes(_msg),
            ))
    elif success_field is False:
        # success=false but no error field
        _msg = "Bridge execution failed"
        future.set_result(attach_err(
            {
                "error": True,
                "message": _msg,
            },
            classify_bridge_error(_msg),
        ))
    else:
        # Success — pass result
        result = data.get("result", {})
        # Change witness (KUKAI_CHANGE_WITNESS, default OFF): stash the FULL
        # manifest for _bridge_callback to persist, and attach ONLY a counts
        # summary to the dict tool-result (id arrays never enter LLM context).
        # Fail-open: a malformed manifest must never block future resolution.
        # Flag OFF, or `changes` absent (reads / errors / pre-Step-4 DLL),
        # leaves `result` and all module state completely untouched.
        try:
            _changes = data.get("changes")
            if _change_witness_enabled() and isinstance(_changes, dict):
                _stash_change_manifest(req_id, _changes)
                if isinstance(result, dict):
                    result.setdefault("changed", _manifest_counts(_changes))
        except Exception:  # noqa: BLE001 — witness is strictly best-effort
            logger.debug("change-witness stash failed", exc_info=True)
        logger.info("BRIDGE SUCCESS [%s]: %s", _ws_id, str(result)[:200])
        future.set_result(result)


def _late_sender_matches(record: OperationRecord, sender_ws_id: str, device_id: str) -> bool:
    """Authorize a reconnect delivery without binding operations to one socket."""
    if record.device_id_hash and device_id:
        return record.device_id_hash == _device_hash(device_id)
    return bool(record.ws_id and record.ws_id == sender_ws_id)


async def _accept_bridge_response(
    data: dict[str, Any],
    *,
    sender_ws_id: str,
    device_id: str = "",
    ws: Optional[WebSocket] = None,
) -> bool:
    """Accept a normal response or reconcile a durable late outbox receipt.

    Returns True when the frame was accepted. The synchronous legacy handler is
    retained for old tests/importers; the live receive loop uses this function.
    """
    req_id = str(data.get("id") or "")
    if req_id in _pending_bridge_requests:
        _handle_bridge_response(data, sender_ws_id=sender_ws_id)
        return req_id not in _pending_bridge_requests

    receipt = data.get("receipt")
    operation_id = str(
        data.get("operation_id")
        or (receipt.get("operation_id") if isinstance(receipt, dict) else "")
        or ""
    )
    if not operation_id or not isinstance(receipt, dict):
        _handle_bridge_response(data, sender_ws_id=sender_ws_id)
        return False

    store = _operation_store()
    try:
        record = await store.get(operation_id)
        if record is None:
            logger.warning("late bridge receipt for unknown operation: %s", operation_id)
            return False
        try:
            receipt_identity = OperationIdentity.from_mapping(receipt)
            OperationOutcome(str(receipt.get("outcome") or ""))
        except ValueError:
            return False
        if receipt_identity != record.identity:
            return False
        # Reconnect-survival (KUKAI_BRIDGE_IDENTITY_ACCEPT, default on). The full
        # OperationIdentity (turn_id + operation_id + payload_hash) is unique per
        # turn and known only to the server and the owning client — so an identity
        # MATCH is itself proof this receipt belongs to THIS operation, whichever
        # socket delivered it. During a WS reconnect the receipt lands on a fresh
        # socket, frequently BEFORE it is device-identified (device_id="") — which
        # made the ws/device owner check spuriously reject it and orphan the result.
        # For a long agentic turn (Codex working for minutes) that silently kills
        # the whole task. We now gate on identity; the owner check is advisory.
        # Kill-switch: set KUKAI_BRIDGE_IDENTITY_ACCEPT=0 to restore strict owner.
        if not _late_sender_matches(record, sender_ws_id, device_id):
            if os.environ.get("KUKAI_BRIDGE_IDENTITY_ACCEPT", "1") != "1":
                logger.warning(
                    "late bridge receipt owner mismatch op=%s sender=%s",
                    operation_id,
                    sender_ws_id,
                )
                return False
            logger.info(
                "bridge receipt accepted via identity across reconnect op=%s (owner_ws=%s sender_ws=%s)",
                operation_id, record.ws_id, sender_ws_id,
            )
        await store.transition(
            operation_id,
            OperationPhase.RECEIPT_DELIVERED_SERVER,
            attempt_id=str(data.get("attempt_id") or req_id),
            outcome=str(receipt.get("outcome") or ""),
            receipt=dict(receipt),
            error=(
                {"message": str(data.get("error"))[:1000]}
                if data.get("error") else None
            ),
        )
        if ws is not None:
            receipt_hash = str(data.get("receipt_hash") or "")
            if not receipt_hash:
                receipt_hash = hashlib.sha256(
                    json.dumps(
                        receipt,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        default=str,
                    ).encode("utf-8")
                ).hexdigest()
            await _send_json(
                ws,
                {
                    "type": "bridge_ack",
                    "protocol_version": 2,
                    "operation_id": operation_id,
                    "receipt_hash": receipt_hash,
                },
            )
        logger.info("late bridge receipt reconciled: operation_id=%s", operation_id)
        return True
    except (KeyError, OperationConflict, ValueError):
        logger.exception("late bridge receipt rejected: operation_id=%s", operation_id)
        return False
    except Exception:
        # No ACK on persistence failure: client outbox will replay later.
        logger.exception("late bridge receipt persistence failed: operation_id=%s", operation_id)
        return False


async def _handle_bridge_phase(
    data: dict[str, Any],
    *,
    sender_ws_id: str,
    device_id: str = "",
) -> bool:
    """Persist an accepted/queued/started phase emitted by protocol-v2 DLL."""
    operation_id = str(data.get("operation_id") or "")
    if not operation_id:
        return False
    try:
        phase = OperationPhase(str(data.get("phase") or ""))
    except ValueError:
        return False
    store = _operation_store()
    try:
        record = await store.get(operation_id)
        if record is None or not _late_sender_matches(record, sender_ws_id, device_id):
            return False
        await store.transition(
            operation_id,
            phase,
            attempt_id=str(data.get("attempt_id") or ""),
            outcome=str(data.get("outcome") or ""),
        )
        return True
    except Exception:
        logger.exception("bridge phase rejected op=%s phase=%s", operation_id, phase.value)
        return False


async def _finalize_operation_receipt(
    *,
    ws: WebSocket,
    req_id: str,
    identity: Optional[OperationIdentity],
    store: Optional[OperationStore],
    result: dict[str, Any],
    changes: Optional[dict[str, Any]],
    expose_operation: bool,
) -> dict[str, Any]:
    """Durably accept terminal client truth, then ACK its local outbox."""
    # A bridge op may return None (void success) OR a bare str (e.g. "демо"
    # demo-mode) — neither supports .get/.setdefault. Normalise to a dict so
    # the receipt/ACK logic below completes: if it raises, the op is never
    # ACKed, the DLL outbox REPLAYS it forever, and the turn loops (and with
    # one worker, starves the whole backend). Preserve any payload.
    if not isinstance(result, dict):
        result = {} if result is None else {"result": result}
    receipt = _bridge_receipts.pop(req_id, None)
    client_receipt_hash = _bridge_receipt_hashes.pop(req_id, "")
    if identity is None or store is None:
        return result

    actual_client_receipt = receipt is not None
    if receipt is None:
        if result.get("error") is True:
            # A transport/error response without a durable client receipt is not
            # proof that arbitrary C# never committed. Hold for late outbox
            # reconciliation and never manufacture a retryable terminal.
            try:
                await store.transition(
                    identity.operation_id,
                    OperationPhase.RUNNING_UNKNOWN,
                    attempt_id=req_id,
                    outcome=OperationOutcome.RUNNING_UNKNOWN.value,
                    error={"message": str(result.get("message", ""))[:1000]},
                )
            except Exception:
                logger.exception("failed to persist receipt-less unknown outcome")
            if expose_operation:
                result.setdefault(
                    "operation",
                    {
                        "operation_id": identity.operation_id,
                        "action_id": identity.action_id,
                        "outcome": OperationOutcome.RUNNING_UNKNOWN.value,
                        "verified": False,
                    },
                )
            return result
        # Old DLL compatibility: completion is known, but transaction truth is
        # not independently proven by a durable client receipt.
        receipt = {
            **identity.to_mapping(),
            "attempt_id": req_id,
            "outcome": OperationOutcome.COMMITTED_UNVERIFIED.value,
            "legacy_unverified": True,
            "changes": changes if isinstance(changes, dict) else None,
        }
    else:
        receipt = dict(receipt)
        receipt.setdefault("operation_id", identity.operation_id)
        receipt.setdefault("action_id", identity.action_id)
        receipt.setdefault("turn_id", identity.turn_id)
        receipt.setdefault("payload_hash", identity.payload_hash)
        receipt.setdefault("attempt_id", req_id)

    try:
        await store.transition(
            identity.operation_id,
            OperationPhase.RECEIPT_DELIVERED_SERVER,
            attempt_id=req_id,
            outcome=str(receipt.get("outcome") or ""),
            receipt=receipt,
            error=(
                {"message": str(result.get("message", ""))[:1000]}
                if result.get("error") is True
                else None
            ),
        )
        if actual_client_receipt:
            receipt_hash = client_receipt_hash or hashlib.sha256(
                json.dumps(receipt, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), default=str).encode("utf-8")
            ).hexdigest()
            await _send_json(
                ws,
                {
                    "type": "bridge_ack",
                    "protocol_version": 2,
                    "operation_id": identity.operation_id,
                    "receipt_hash": receipt_hash,
                },
            )
    except Exception:
        # No ACK on failure: the DLL outbox retains and replays the receipt.
        logger.exception("operation receipt persistence/ack failed")

    if expose_operation:
        result.setdefault(
            "operation",
            {
                "operation_id": identity.operation_id,
                "action_id": identity.action_id,
                "outcome": str(receipt.get("outcome") or ""),
                "verified": str(receipt.get("outcome") or "")
                == OperationOutcome.COMMITTED_VERIFIED.value,
            },
        )
    return result


def _invalidate_model_cache_after_bridge(
    ws_id: str,
    method: str,
    params: dict[str, Any],
    result: dict[str, Any],
    changes: Optional[dict[str, Any]],
) -> None:
    """Best-effort ModelGraph invalidation after a successful write."""
    try:
        if not result.get("error"):
            from kukai.query.model_cache import invalidate_after_write

            invalidate_after_write(
                _session_contexts.get(ws_id) or {},
                _session_detailed_passports.get(ws_id),
                code=params.get("code", ""),
                changes=changes,
                method=method,
            )
    except Exception:  # noqa: BLE001 — invalidation is strictly best-effort
        logger.debug("gestalt-v2 invalidation skipped", exc_info=True)


async def _bridge_callback(
    ws: WebSocket,
    ws_id: str,
    method: str,
    params: dict[str, Any],
    *,
    actor: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """Bridge callback — sends request to client via WebSocket, waits for response.

    For execute_revit_code: obfuscates and encrypts the code.
    For other methods: sends params as-is (they don't contain secrets).
    """
    # Local fast-path: the LLM's get_model_details tool is served entirely
    # server-side from the session's cached detailed passport — no bridge
    # round-trip to Revit.
    if method == "get_model_details":
        return _build_model_details(ws_id, params.get("section", "full"))

    # EMERGENCY KILL-SWITCH (KUKAI_DISABLE_REVIT_EXECUTE=1): stop ALL code
    # execution in users' Revit — "execute" is the sole path by which generated
    # C# runs, and with mismatched assemblies / broken installs it can CRASH
    # their Revit. Returns a NON-retryable maintenance result so the agent tells
    # the user in text instead of looping. Chat stays alive; nothing runs in Revit.
    if method == "execute" and os.getenv("KUKAI_DISABLE_REVIT_EXECUTE") == "1":
        _allow = {d.strip() for d in os.getenv("KUKAI_EXECUTE_ALLOW_DEVICES", "").split(",") if d.strip()}
        _dev = str((actor or {}).get("device_id", "") or "")
        if _dev not in _allow:
            logger.warning("EXECUTE BLOCKED [%s] device=%s: kill-switch (not allow-listed)", ws_id, (_dev or "?")[:12])
            return {
                "error": True,
                "message": "Выполнение операций в Revit временно приостановлено администратором для профилактики. Модель не изменялась — сообщите это пользователю и не повторяйте попытку.",
                "err": {"code": "service.maintenance", "retryable": False, "transient": False},
            }
        logger.info("EXECUTE ALLOWED [%s] device=%s: allow-listed", ws_id, _dev[:12])

    explicit_operation_identity = isinstance((params or {}).get("_operation"), dict)
    try:
        params, operation_identity, execution_effect, read_source = (
            _operation_context(method, params)
        )
    except OperationConflict as exc:
        return attach_err(
            {"error": True, "message": f"Operation identity rejected: {exc}"},
            ErrCode.INTERNAL_UNHANDLED,
        )

    req_id = str(uuid.uuid4())
    session_key = _session_keys.get(ws_id)

    message: dict[str, Any] = {
        "type": "bridge_request",
        "id": req_id,
        "method": method,
    }
    if operation_identity is not None:
        message.update(operation_identity.to_mapping())
        message["attempt_id"] = req_id
    if method == "execute":
        message["execution_effect"] = execution_effect.value
        if read_source is not None:
            message["read_source"] = read_source

    if method == "execute" and session_key and params.get("_pipeline_prepared"):
        # ── Step 7 (KUKAI_EXEC_PIPELINE) — transport-only branch ──────────
        # RevitExecutionPipeline (kukai/llm/revit_execution_pipeline.py) has
        # already run validate → fix(once) → wrap → compile-gate → obfuscate;
        # params["code"] is the wrapped+obfuscated payload. From here this
        # callback is pure transport: encrypt → send → await. The legacy
        # duplicate stages below must NOT re-run — the double fixer (with a
        # different revit_version source) is exactly what corrupted
        # execution.final_code provenance for the repair trail.
        message["encrypted_code"] = SessionEncryption.encrypt(
            params.get("code", ""), session_key
        )
        if "timeout_ms" in params:
            message["timeout_ms"] = params["timeout_ms"]
    elif method == "execute" and session_key:
        code = params.get("code", "")
        # Step 0: Fix common LLM mistakes deterministically
        from kukai.security.code_fixer import RevitCodeFixer
        ctx_data = _session_contexts.get(ws_id, {})
        revit_version = ctx_data.get("revit_version", "") or (
            ctx_data.get("document", {}).get("revit_version", "")
        )
        _fixer = RevitCodeFixer(revit_version=revit_version)
        original_code = code
        code = _fixer.fix(code)
        if code != original_code:
            logger.info("CODE FIXER [%s]: auto-fixed code (version=%s)", ws_id, revit_version or "unknown")

        # Re-validate after code fixer (strip_wrappers may reveal blocked patterns)
        from kukai.security.validation import validate_code_safety
        post_fix_violations = validate_code_safety(code)
        if post_fix_violations:
            logger.warning("SECURITY BLOCKED [%s]: %s", ws_id, "; ".join(post_fix_violations)[:200])
            _blocked_msg = f"Code blocked after fixing: {'; '.join(post_fix_violations)}"
            # Legacy keys preserved: `success` (False) and `error` (the prose
            # STRING, not a bool, in this shape). Add `message` so every
            # consumer has one place to read the text, and the `err` block.
            return attach_err(
                {
                    "success": False,
                    "error": _blocked_msg,
                    "message": _blocked_msg,
                },
                ErrCode.SECURITY_BLOCKED_PATTERN,
            )

        logger.info("CODE GENERATED [%s]:\n%s", ws_id, code[:500])

        # Step 0b: Wrap code in a compilable class
        # The C# compiler expects namespace Kukai, class UserCode, method Execute
        # matching TemplateRenderer.WrapperClassName = "Kukai.UserCode"
        # Indent all lines of user code to match the method body level
        indented_code = "\n".join(
            "            " + line if line.strip() else line
            for line in code.split("\n")
        )
        wrapped_code = _WRAPPER_HEADER + indented_code + _WRAPPER_FOOTER
        # Step 0c: Pre-flight Roslyn compile check on EVERY attempt (path-A N2).
        # Previously skipped on attempt 1 to save 200-500ms on the assumed 80%
        # happy path. live_test.log evidence (14394 CS errors) shows that
        # assumption is wrong — compile-fail is common, and pre-flight saves
        # the bridge round-trip + Revit-side compile + decryption when code
        # won't compile anyway. Net positive when compile-fail rate > ~10%.
        attempt = int(params.get("attempt", 1) or 1)
        from kukai.main import get_app_state
        compile_client = get_app_state().compile_client
        if compile_client and compile_client.available:
            compile_result = await compile_client.check(wrapped_code, revit_version)
            if compile_result is not None:
                if not compile_result.success:
                    # Correct line numbers: subtract wrapper header offset so LLM sees user code lines
                    error_msgs = "; ".join(
                        f"{e.code}: {e.message} (line {max(1, e.line - _WRAPPER_LINE_OFFSET)})"
                        for e in compile_result.errors[:3]
                    )
                    logger.info("PRE-FLIGHT COMPILE FAILED [%s] attempt=%d: %s", ws_id, attempt, error_msgs[:300])
                    # CS codes come STRUCTURALLY from compile_result.errors, not
                    # from re-parsing the prose we just flattened.
                    return attach_err(
                        {"error": True, "message": f"Compilation failed: {error_msgs}"},
                        ErrCode.COMPILE_CS_ERROR,
                        cs_codes=[e.code for e in compile_result.errors[:3]],
                    )
                else:
                    logger.info("PRE-FLIGHT COMPILE OK [%s] attempt=%d", ws_id, attempt)

        # Step 1: Obfuscate variable names (keep the map — see _obf_maps)
        obfuscated, _rename_map = obfuscate_code_with_map(wrapped_code)
        if _rename_map:
            if len(_obf_maps) >= _OBF_MAPS_MAX:
                _obf_maps.pop(next(iter(_obf_maps)), None)
            _obf_maps[req_id] = _rename_map
        # Step 2: Encrypt with session AES key
        encrypted = SessionEncryption.encrypt(obfuscated, session_key)
        message["encrypted_code"] = encrypted
        # Pass timeout if present
        if "timeout_ms" in params:
            message["timeout_ms"] = params["timeout_ms"]
    else:
        # For non-execute methods (select, highlight, context), pass params directly.
        # Strip the harness-internal pipeline marker if it ever lands here (an
        # execute without a session key) — it must never reach the C# side.
        if isinstance(params, dict) and "_pipeline_prepared" in params:
            params = {k: v for k, v in params.items() if k != "_pipeline_prepared"}
        message["params"] = params

    operation_store: Optional[OperationStore] = None
    if operation_identity is not None:
        operation_store = _operation_store()
        ledger = _tl.current()
        record = OperationRecord(
            identity=operation_identity,
            method=method,
            ws_id=ws_id,
            session_id=str((actor or {}).get("session_id") or (
                ledger.session_id if ledger is not None else ""
            )),
            tenant_id=str((actor or {}).get("tenant_id") or (
                ledger.tenant_id if ledger is not None else ""
            )),
            device_id_hash=_device_hash(str((actor or {}).get("device_id", "")))
            if (actor or {}).get("device_id")
            else (ledger.device_id_hash if ledger is not None else ""),
            phase=OperationPhase.PERSISTED_SERVER,
            attempt_id=req_id,
        )
        try:
            existing = await operation_store.create(record)
        except Exception as exc:
            # Write-ahead persistence is the safety boundary. Never dispatch a
            # side effect when its identity could not be durably recorded.
            logger.exception("operation write-ahead persistence failed")
            return attach_err(
                {
                    "error": True,
                    "operation_id": operation_identity.operation_id,
                    "message": "Не удалось безопасно зарегистрировать операцию; выполнение не начато.",
                },
                ErrCode.INTERNAL_UNHANDLED,
                detail=str(exc)[:300],
            )

        if existing.receipt is not None:
            # Idempotent replay after a lost server response: return the exact
            # terminal truth instead of dispatching the effect again.
            return _tool_result_from_receipt(existing.receipt)
        if existing.phase not in {
            OperationPhase.CREATED,
            OperationPhase.PERSISTED_SERVER,
        }:
            return _unknown_operation_result(
                operation_identity.operation_id,
                "Операция уже была отправлена в Revit; повторная запись заблокирована до сверки результата.",
            )

    # Create future for the response, keyed by (ws_id, future) for per-session cleanup
    loop = asyncio.get_running_loop()
    future: asyncio.Future[dict[str, Any]] = loop.create_future()
    _pending_bridge_requests[req_id] = (ws_id, future)
    if operation_identity is not None and operation_store is not None:
        _pending_bridge_operations[req_id] = (operation_identity, operation_store)

    # Send request to client
    logger.info("BRIDGE SEND [%s]: method=%s req_id=%s", ws_id, method, req_id)
    try:
        await _send_json(ws, message)
    except Exception:
        _pending_bridge_requests.pop(req_id, None)
        _pending_bridge_operations.pop(req_id, None)
        _bridge_receipts.pop(req_id, None)
        _bridge_receipt_hashes.pop(req_id, None)
        _obf_maps.pop(req_id, None)
        raise
    if operation_identity is not None and operation_store is not None:
        try:
            await operation_store.transition(
                operation_identity.operation_id,
                OperationPhase.SENT,
                attempt_id=req_id,
            )
        except Exception:
            # The message may already be on the wire. Treat this as unknown and
            # never manufacture a second operation; a late client outbox receipt
            # can still reconcile the write-ahead row.
            logger.exception("operation SENT transition failed after dispatch")

    # Wait for response with timeout (use propagated timeout + buffer for compile time)
    effective_timeout = _effective_bridge_timeout(method, params)

    async def _mark_unknown(reason: str) -> None:
        if operation_identity is None or operation_store is None:
            return
        try:
            await operation_store.transition(
                operation_identity.operation_id,
                OperationPhase.RUNNING_UNKNOWN,
                attempt_id=req_id,
                outcome=OperationOutcome.RUNNING_UNKNOWN.value,
                error={"reason": reason},
            )
        except Exception:
            logger.exception("failed to mark operation running_unknown")

    try:
        result = await asyncio.wait_for(future, timeout=effective_timeout)
        result = _restore_obfuscated_names(req_id, result)
        _wchanges = _bridge_change_manifests.get(req_id)  # peek before drain (gestalt-v2 hook)
        # Change witness (KUKAI_CHANGE_WITNESS): persist the manifest stashed by
        # _handle_bridge_response now that the turn owns the result. No-op when
        # nothing was stashed (flag OFF / reads / pre-Step-4 DLL).
        _drain_witness(req_id, ws_id, method)
        result = await _finalize_operation_receipt(
            ws=ws,
            req_id=req_id,
            identity=operation_identity,
            store=operation_store,
            result=result,
            changes=_wchanges if isinstance(_wchanges, dict) else None,
            expose_operation=explicit_operation_identity,
        )
        _tl.record_bridge("chat_ws._bridge_callback", {"method": method, "req_id": req_id,
            "changed": _manifest_counts(_wchanges) if isinstance(_wchanges, dict) else None},
            ok=not (isinstance(result, dict) and result.get("error")),
            err_code=(result.get("err", {}).get("code") if isinstance(result, dict) and isinstance(result.get("err"), dict) else None),
            file_line="kukai/api/chat_ws.py:bridge_ok")
        _invalidate_model_cache_after_bridge(ws_id, method, params, result, _wchanges)
        _pending_bridge_operations.pop(req_id, None)
        _bridge_receipt_hashes.pop(req_id, None)
        _obf_maps.pop(req_id, None)
        return result
    except asyncio.TimeoutError:
        _pending_bridge_requests.pop(req_id, None)
        _bridge_change_manifests.pop(req_id, None)
        _bridge_receipts.pop(req_id, None)
        _bridge_receipt_hashes.pop(req_id, None)
        _obf_maps.pop(req_id, None)
        _pending_bridge_operations.pop(req_id, None)
        _tl.record_bridge("chat_ws._bridge_callback", {"method": method, "req_id": req_id, "timeout_s": effective_timeout}, ok=False, err_code="TRANSPORT_BRIDGE_TIMEOUT", file_line="kukai/api/chat_ws.py:bridge_to")
        if operation_identity is not None:
            await _mark_unknown("bridge_timeout")
            return _unknown_operation_result(
                operation_identity.operation_id,
                f"Revit не подтвердил завершение за {effective_timeout:.0f}с. Операция не будет повторена вслепую.",
            )
        return attach_err(
            {"error": True, "message": f"Revit не ответил вовремя ({effective_timeout:.0f}с)"},
            ErrCode.TRANSPORT_BRIDGE_TIMEOUT,
        )
    except asyncio.CancelledError:
        # Step 6: the tool/turn was cancelled (e.g. the 90s tool-budget cap) — drop
        # the orphaned pending future so a late bridge_response can't resolve a
        # committed write the model already saw as a timeout (double-commit root).
        # Re-raise to honor cancellation.
        _pending_bridge_requests.pop(req_id, None)
        _bridge_change_manifests.pop(req_id, None)
        _bridge_receipts.pop(req_id, None)
        _bridge_receipt_hashes.pop(req_id, None)
        _obf_maps.pop(req_id, None)
        _pending_bridge_operations.pop(req_id, None)
        if operation_identity is not None:
            try:
                await asyncio.shield(_mark_unknown("server_task_cancelled"))
            except Exception:
                pass
        _tl.record_bridge("chat_ws._bridge_callback", {"method": method, "req_id": req_id}, ok=False, err_code="cancelled", file_line="kukai/api/chat_ws.py:bridge_cancel")
        raise
    except ConnectionError:
        _pending_bridge_requests.pop(req_id, None)
        _bridge_change_manifests.pop(req_id, None)
        _bridge_receipts.pop(req_id, None)
        _bridge_receipt_hashes.pop(req_id, None)
        _obf_maps.pop(req_id, None)
        _pending_bridge_operations.pop(req_id, None)
        if operation_identity is not None:
            await _mark_unknown("connection_lost")
        _tl.record_bridge("chat_ws._bridge_callback", {"method": method, "req_id": req_id}, ok=False, err_code="connection_lost", file_line="kukai/api/chat_ws.py:bridge_conn")
        if operation_identity is not None:
            return _unknown_operation_result(
                operation_identity.operation_id,
                "Соединение с Revit потеряно после отправки операции; повтор заблокирован до сверки.",
            )
        return {"error": True, "message": "Соединение с Revit потеряно"}
