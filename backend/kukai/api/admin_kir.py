"""Admin KIR endpoints — device-pinned, document-guarded revit_ir driver.

Built for the 2026-07-16 full-building KIR test (operator-authorized): drive
KIR programs through the EXACT serving path (kukai.ir.serving.handle_revit_ir:
ground-snapshot -> compile_program -> run_declarative/EXEC_PIPELINE) against
the ADMIN DEVICE's live Revit session WITHOUT an LLM in the loop — the unit
under test is the compiler+serving plumbing, not a model's JSON fidelity.
Also the reusable harness for STAGE2_DIFFERENTIAL re-runs.

Strictly narrower than the existing /admin/remote/exec (arbitrary C#):
- device taken from the installation's allow-list
  (kukai.ir.serving.admin_devices(), env KUKAI_ADMIN_DEVICES); an empty
  list is a typed 503, never a guess (§18.5);
- target ws selected by DOCUMENT-NAME match (`doc_contains`), never
  next(iter(ws_set)): with two Revit instances on the admin machine the
  write target must not be a coin flip;
- deny-list guard: a document whose name contains a deny token (default
  "коорд") is never selected even if it matches;
- payload is a typed KIR program — validation/refusal semantics belong to
  the compiler (Any-Query invariant), destructive ops stay behind the
  program envelope + compiler policy.

Endpoints (X-Admin-Token, same auth as /admin/remote):
  GET  /admin/kir/contexts  — per-ws {ws_id, document_name, revit_version,...}
                              of the admin device (both Revit windows visible)
  POST /admin/kir/run       — {"program": {...}, "doc_contains": "проект1",
                               "timeout_ms": 120000, "bulk": false}
                              -> serving result verbatim.  ``bulk`` выбирает
                              ВНУТРЕННЮЮ дверь serving (бюджет чанка
                              материализатора вместо авторского бюджета
                              программы) — она доступна только отсюда.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException

from kukai.api.admin_remote import verify_admin_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/kir", tags=["admin-kir"])

_DENY_TOKENS = ("коорд", "акцент")   # hard guard: never write into these docs


def _norm(s: str) -> str:
    return "".join((s or "").lower().split())


def _allowed_devices() -> tuple[str, ...]:
    """Список допуска этой установки (§18.5, env KUKAI_ADMIN_DEVICES)."""
    from kukai.ir.serving import admin_devices
    return admin_devices()


def _pinned_device() -> str:
    """Устройство, от имени которого выполняется админский ход.

    Маршруты admin/kir водят живой Revit БЕЗ модели в петле, поэтому им нужен
    конкретный device_id для ContextVar хода. Берём ПЕРВОЕ устройство списка
    допуска: пустой список — не повод угадывать, а типизированный 503 с именем
    переменной, которую надо настроить.

    Куда уйдёт запись, это НЕ решает: адресат выбирается совпадением имени
    документа среди ws (см. ``_match_admin_ws``), а ContextVar служит только
    свидетелем для гейта и логов. При двух допущенных устройствах гейт открыт
    для обоих, поэтому первый элемент списка здесь безопасен.
    """
    devices = _allowed_devices()
    if not devices:
        raise HTTPException(
            status_code=503,
            detail=("список допущенных устройств пуст — задай "
                    "KUKAI_ADMIN_DEVICES (id устройств через запятую)"))
    return devices[0]


def _admin_ws_rows() -> list[dict[str, Any]]:
    from kukai.api.ws_registry import (
        _device_websockets, _session_contexts, _ws_object_to_ws_id,
    )

    rows: list[dict[str, Any]] = []
    for device_id in _allowed_devices():
        for ws in _device_websockets.get(device_id, set()):
            ws_id = _ws_object_to_ws_id.get(id(ws))
            ctx = _session_contexts.get(ws_id or "", {}) or {}
            rows.append({
                "ws": ws,
                "ws_id": ws_id,
                "device_id": device_id,
                "document_name": ctx.get("document_name") or "",
                "document_path": ctx.get("document_path") or "",
                "revit_version": str(ctx.get("revit_version") or ""),
                "has_document": ctx.get("has_document"),
                "warnings_count": ctx.get("warnings_count"),
            })
    return rows


@router.get("/contexts", dependencies=[Depends(verify_admin_token)])
async def contexts() -> Any:
    """Per-ws contexts of the admin device (no side effects)."""
    rows = [{k: v for k, v in r.items() if k != "ws"} for r in _admin_ws_rows()]
    return {"device": "admin", "ws_rows": rows, "count": len(rows)}


@router.post("/run", dependencies=[Depends(verify_admin_token)])
async def run_program(payload: dict[str, Any]) -> Any:
    """Run one KIR program via the production serving path on the admin device.

    Body: {"program": {...}, "doc_contains": "проект1", "timeout_ms": 120000,
           "bulk": false}
    The ws whose document_name (normalized) contains doc_contains (normalized)
    is selected; 0 or >1 matches -> 409, deny-token match -> 403.

    ``bulk`` (по умолчанию false) выбирает ВНУТРЕННЮЮ дверь serving
    (`handle_revit_ir_bulk`): бюджет чанка материализатора вместо авторского
    бюджета программы. Это переключатель ДВЕРИ, а не политики: каждая дверь
    несёт свою политику целиком (см. serving.handle_revit_ir_bulk). Поле живёт
    здесь, а не во входе инструмента, потому что сюда ходят только по
    X-Admin-Token — чат до этого тела запроса не дотягивается никак.
    """
    program = payload.get("program")
    if not isinstance(program, dict):
        raise HTTPException(status_code=400, detail="Missing 'program' object")
    bulk = payload.get("bulk", False)
    if not isinstance(bulk, bool):
        # Строка "false" — истина в Python. Молчаливое приведение здесь открыло
        # бы внутренний бюджет опечаткой, поэтому тип проверяется, а не гадается.
        raise HTTPException(
            status_code=400,
            detail=f"'bulk' must be a boolean, got {type(bulk).__name__}")
    doc_contains = _norm(str(payload.get("doc_contains") or "проект1"))
    if not doc_contains:
        raise HTTPException(status_code=400, detail="Empty doc_contains")

    matches = []
    for r in _admin_ws_rows():
        name = _norm(r["document_name"])
        if doc_contains in name:
            if any(t in name for t in _DENY_TOKENS):
                raise HTTPException(
                    status_code=403,
                    detail=f"Denied: document {r['document_name']!r} is deny-listed",
                )
            matches.append(r)
    if not matches:
        raise HTTPException(
            status_code=409,
            detail={"error": "no ws with matching document on admin device",
                    "wanted": doc_contains,
                    "have": [r["document_name"] for r in _admin_ws_rows()]},
        )
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail={"error": "ambiguous document match", "wanted": doc_contains,
                    "matches": [r["document_name"] for r in matches]},
        )
    target = matches[0]
    ws, ws_id = target["ws"], target["ws_id"]
    if not ws_id:
        raise HTTPException(status_code=500, detail="ws_id mapping missing")

    from kukai.api.bridge_protocol import _bridge_callback

    async def bridge_callback(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return await _bridge_callback(ws, ws_id, method, params)

    class _ShimLLMClient:
        """Minimal llm_client surface for the declarative KIR path:
        _revit_version is read by serving + from_llm_client; _repair_code is
        never invoked by run_declarative (declarative = no LLM repair)."""
        _revit_version = target["revit_version"] or "2026"

        async def _repair_code(self, *a: Any, **k: Any) -> Optional[str]:
            return None

    from kukai.ir import serving as _serving
    from kukai.llm import turn_context

    # Дверь выбирается ЗДЕСЬ и по имени. Модуль читается через атрибут (а не
    # `from ... import`), чтобы имя внутренней двери существовало ровно в двух
    # местах дерева — в serving и тут.
    door = _serving.handle_revit_ir_bulk if bulk else _serving.handle_revit_ir

    query_id = f"admin-kir-{uuid.uuid4().hex[:8]}"
    token = turn_context._active_device_id.set(_pinned_device())
    t0 = time.monotonic()
    try:
        result = await door(
            {"program": program}, _ShimLLMClient(), bridge_callback,
            query_id=query_id)
    finally:
        turn_context._active_device_id.reset(token)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    logger.info("[admin/kir] doc=%r ws_id=%s query_id=%s bulk=%s "
                "elapsed_ms=%d ok=%s",
                target["document_name"], ws_id, query_id, bulk, elapsed_ms,
                result.get("ok") if isinstance(result, dict) else "?")
    return {
        "document_name": target["document_name"],
        "ws_id": ws_id,
        "revit_version": _ShimLLMClient._revit_version,
        "query_id": query_id,
        "elapsed_ms": elapsed_ms,
        "bulk": bulk,
        "kir": result,
    }


# ---------------------------------------------------------------------------
# Wave A1 — decompile driver route (KUKAI_KIR_DECOMPILE=stage2, admin device).
# Additive: mirrors /run's device-pin + doc-name match; start wires the same
# read-only bridge executor handle_revit_decompile expects; status/cancel only
# touch status.json (no bridge).  Lead-authored during the 2026-07-21 live
# acceptance to expose the A1 pipeline that had a handler but no HTTP surface.
# ---------------------------------------------------------------------------
def _match_admin_ws(doc_contains: str) -> dict[str, Any]:
    """Single admin-device ws whose document matches; HTTPException otherwise."""
    dc = _norm(doc_contains)
    if not dc:
        raise HTTPException(status_code=400, detail="Empty doc_contains")
    matches = []
    for r in _admin_ws_rows():
        name = _norm(r["document_name"])
        if dc in name:
            if any(t in name for t in _DENY_TOKENS):
                raise HTTPException(
                    status_code=403,
                    detail=f"Denied: document {r['document_name']!r} is deny-listed")
            matches.append(r)
    if not matches:
        raise HTTPException(
            status_code=409,
            detail={"error": "no ws with matching document on admin device",
                    "wanted": dc,
                    "have": [r["document_name"] for r in _admin_ws_rows()]})
    if len(matches) > 1:
        raise HTTPException(
            status_code=409,
            detail={"error": "ambiguous document match", "wanted": dc,
                    "matches": [r["document_name"] for r in matches]})
    return matches[0]


@router.post("/decompile", dependencies=[Depends(verify_admin_token)])
async def decompile(payload: dict[str, Any]) -> Any:
    """Drive handle_revit_decompile on the admin device (Wave A1).

    Body: {"action": "start"|"status"|"cancel", "doc_stamp"?: "...",
           "doc_contains"?: "демо"}.  ``start`` needs a matching ws to wire the
    read-only bridge executor; ``status``/``cancel`` only read/write status.json.
    """
    from kukai.ir.serving import handle_revit_decompile
    from kukai.llm import turn_context

    action = str(payload.get("action") or "status")
    doc_stamp = payload.get("doc_stamp")

    class _ShimLLM:
        _revit_version = "2026"

        async def _repair_code(self, *a: Any, **k: Any) -> Optional[str]:
            return None

    if action in ("status", "cancel"):
        async def _noop_bridge(method: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("bridge not used for status/cancel")

        token = turn_context._active_device_id.set(_pinned_device())
        try:
            return await handle_revit_decompile(
                {"action": action, "doc_stamp": doc_stamp},
                _ShimLLM(), _noop_bridge)
        finally:
            turn_context._active_device_id.reset(token)

    # action == "start" (any other value -> handler returns a typed args error)
    target = _match_admin_ws(str(payload.get("doc_contains") or "проект1"))
    ws, ws_id = target["ws"], target["ws_id"]
    if not ws_id:
        raise HTTPException(status_code=500, detail="ws_id mapping missing")
    if not (isinstance(doc_stamp, str) and doc_stamp):
        doc_stamp = _norm(target["document_name"]) or "document"

    from kukai.api.bridge_protocol import _bridge_callback

    doc_name_norm = _norm(target["document_name"])

    async def bridge_callback(method: str, params: dict[str, Any]) -> dict[str, Any]:
        # Сокет моста СМЕРТЕН посреди многостраничного извлечения (сеть
        # оператора рвётся, 1006; окно возвращается с НОВЫМ ws_id — замер
        # 29.07 на К2 РД: три прогона умерли на плавающей странице). Поэтому
        # окно резолвится заново НА КАЖДЫЙ вызов по точному имени документа;
        # подмену содержимого ловит ревизионный страж каждой страницы
        # (_RevisionGuardedExecutor), а «окно ещё не вернулось» — обычная
        # ретраибельная ошибка транспорта, её выдерживает бюджет ретраев.
        rows = [r for r in _admin_ws_rows()
                if _norm(r["document_name"]) == doc_name_norm]
        if len(rows) != 1:
            raise RuntimeError(
                f"bridge window for {target['document_name']!r} is not "
                f"connected (matches: {len(rows)})")
        current = rows[0]
        return await _bridge_callback(
            current["ws"], current["ws_id"], method, params)

    _shim = _ShimLLM()
    _shim._revit_version = target["revit_version"] or "2026"
    token = turn_context._active_device_id.set(_pinned_device())
    try:
        result = await handle_revit_decompile(
            {"action": "start", "doc_stamp": doc_stamp,
             # Снять СВЯЗЬ окна, а не сам документ окна. Открывать ничего
             # не нужно: связи уже открыты в сессии Revit.
             "link_title": payload.get("link_title")},
            _shim, bridge_callback)
    finally:
        turn_context._active_device_id.reset(token)
    logger.info("[admin/kir] decompile start doc=%r ws_id=%s stamp=%r ok=%s",
                target["document_name"], ws_id, doc_stamp,
                result.get("ok") if isinstance(result, dict) else "?")
    return {"document_name": target["document_name"], "ws_id": ws_id,
            "doc_stamp": doc_stamp,
            "revit_version": _shim._revit_version, "decompile": result}


# ---------------------------------------------------------------------------
# Wave A1/A3 — rebuild driver route (KUKAI_KIR_DECOMPILE=stage2, admin device).
# Additive: mirrors /decompile.  ``dry_run`` (default) only materialises the
# persisted decompile leaves and compile-gates every chunk — NO bridge, NO model
# write.  A live rebuild (dry_run=false) wires the same read/write bridge, but is
# admin-gated and intended for operator-supervised use.  Lead-authored during the
# 2026-07-21 live acceptance to prove the rebuild half on the real building.
# ---------------------------------------------------------------------------
@router.post("/rebuild", dependencies=[Depends(verify_admin_token)])
async def rebuild(payload: dict[str, Any]) -> Any:
    """Drive handle_revit_rebuild on the admin device.

    Body: {"doc_stamp": "...", "dry_run": true, "doc_contains"?: "демо",
           "offset_mm"?: [dx,dy,dz]}.  dry_run compiles only (no ws needed);
    a live rebuild needs a matching ws for the write bridge.
    """
    from kukai.ir.serving import handle_revit_rebuild
    from kukai.llm import turn_context

    doc_stamp = payload.get("doc_stamp")
    dry_run = payload.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise HTTPException(status_code=422, detail="dry_run must be boolean")
    for field in ("keep", "whole_model", "disposable_copy", "allow_partial"):
        if field in payload and not isinstance(payload[field], bool):
            raise HTTPException(
                status_code=422, detail=f"{field} must be boolean")

    class _ShimLLM:
        _revit_version = "2026"

        async def _repair_code(self, *a: Any, **k: Any) -> Optional[str]:
            return None

    # dry_run never touches the bridge; a live rebuild resolves the ws.
    if dry_run:
        async def bridge_callback(method: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("bridge must not be called in a dry_run rebuild")
        shim: Any = _ShimLLM()
    else:
        target = _match_admin_ws(str(payload.get("doc_contains") or "проект1"))
        ws, ws_id = target["ws"], target["ws_id"]
        if not ws_id:
            raise HTTPException(status_code=500, detail="ws_id mapping missing")
        from kukai.api.bridge_protocol import _bridge_callback

        async def bridge_callback(method: str, params: dict[str, Any]) -> dict[str, Any]:  # type: ignore[misc]
            return await _bridge_callback(ws, ws_id, method, params)
        shim = _ShimLLM()
        shim._revit_version = target["revit_version"] or "2026"

    args: dict[str, Any] = {"doc_stamp": doc_stamp, "dry_run": dry_run}
    if "offset_mm" in payload:
        args["offset_mm"] = payload["offset_mm"]
    # §18.4: гейт частичного чтения на rebuild бесполезен, если его именной
    # карваут недостижим через маршрут — оператору осталось бы либо не
    # пересобирать вовсе, либо снять гейт. Ровно та же проброска, что у A5.
    if payload.get("allow_partial") is not None:
        args["allow_partial"] = payload["allow_partial"]

    token = turn_context._active_device_id.set(_pinned_device())
    t0 = time.monotonic()
    try:
        result = await handle_revit_rebuild(args, shim, bridge_callback)
    finally:
        turn_context._active_device_id.reset(token)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("[admin/kir] rebuild dry_run=%s stamp=%r elapsed_ms=%d ok=%s",
                dry_run, doc_stamp, elapsed_ms,
                result.get("ok") if isinstance(result, dict) else "?")
    return {"doc_stamp": doc_stamp, "dry_run": dry_run,
            "elapsed_ms": elapsed_ms, "rebuild": result}


# ---------------------------------------------------------------------------
# Wave A5 — idempotence driver route (KUKAI_KIR_DECOMPILE=stage2, admin device).
# Additive: mirrors /rebuild.  ``dry_run`` (default) compile-gates the Δ-programs
# offline — NO bridge, NO model write, NO title probe.  The live path
# (dry_run=false) wires the read/write bridge and fails closed via the
# orchestrator's SafetyContext (copy suffix AND confirm_token) — WRITE-bearing,
# operator-gated.  Lead-authored during the 2026-07-21 live acceptance.
# ---------------------------------------------------------------------------
@router.post("/idempotence", dependencies=[Depends(verify_admin_token)])
async def idempotence(payload: dict[str, Any]) -> Any:
    """Drive handle_revit_idempotence on the admin device (Wave A5).

    Body: {"doc_stamp": "...", "dry_run": true, "confirm_token"?: "...",
           "doc_contains"?: "демо"}.
    """
    from kukai.ir.serving import handle_revit_idempotence
    from kukai.llm import turn_context

    doc_stamp = payload.get("doc_stamp")
    dry_run = payload.get("dry_run", True)
    if not isinstance(dry_run, bool):
        raise HTTPException(status_code=422, detail="dry_run must be boolean")
    for field in ("keep", "whole_model", "allow_partial"):
        if field in payload and not isinstance(payload[field], bool):
            raise HTTPException(
                status_code=422, detail=f"{field} must be boolean")

    class _ShimLLM:
        _revit_version = "2026"

        async def _repair_code(self, *a: Any, **k: Any) -> Optional[str]:
            return None

    if dry_run:
        async def bridge_callback(method: str, params: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("bridge must not be called in a dry_run idempotence")
        shim: Any = _ShimLLM()
    else:
        target = _match_admin_ws(str(payload.get("doc_contains") or "проект1"))
        ws, ws_id = target["ws"], target["ws_id"]
        if not ws_id:
            raise HTTPException(status_code=500, detail="ws_id mapping missing")
        from kukai.api.bridge_protocol import _bridge_callback

        async def bridge_callback(method: str, params: dict[str, Any]) -> dict[str, Any]:  # type: ignore[misc]
            return await _bridge_callback(ws, ws_id, method, params)
        shim = _ShimLLM()
        shim._revit_version = target["revit_version"] or "2026"

    args: dict[str, Any] = {"doc_stamp": doc_stamp, "dry_run": dry_run}
    if payload.get("confirm_token") is not None:
        args["confirm_token"] = payload["confirm_token"]
    # Тот же класс дыры, что allow_partial у /rebuild (волна a0a85aff):
    # SafetyContext принимает явное заявление оператора disposable_copy, а
    # маршрут его не пробрасывал — карваут был недостижим, оставляя оператору
    # только переименование документа.
    if payload.get("disposable_copy") is not None:
        if not isinstance(payload["disposable_copy"], bool):
            raise HTTPException(
                status_code=422, detail="disposable_copy must be boolean")
        args["disposable_copy"] = payload["disposable_copy"]
    if payload.get("limit_ops") is not None:
        args["limit_ops"] = payload["limit_ops"]
    if payload.get("only_kinds") is not None:
        args["only_kinds"] = payload["only_kinds"]
    if payload.get("level_scope") is not None:
        args["level_scope"] = payload["level_scope"]
    if payload.get("keep") is not None:
        args["keep"] = payload["keep"]
    if payload.get("whole_model") is not None:
        args["whole_model"] = payload["whole_model"]
    if payload.get("disposable_copy") is not None:
        args["disposable_copy"] = payload["disposable_copy"]
    # §18.4: карваут частичного чтения обязан быть ДОСТИЖИМ с единственного
    # живого входа — иначе закон превращается в глухой тупик для оператора.
    if payload.get("allow_partial") is not None:
        args["allow_partial"] = payload["allow_partial"]
    if payload.get("offset_mm") is not None:
        args["offset_mm"] = payload["offset_mm"]

    token = turn_context._active_device_id.set(_pinned_device())
    t0 = time.monotonic()
    try:
        from kukai.main import get_app_state
        result = await handle_revit_idempotence(
            args, shim, bridge_callback,
            lease_store=get_app_state().db)
    finally:
        turn_context._active_device_id.reset(token)
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info("[admin/kir] idempotence dry_run=%s stamp=%r elapsed_ms=%d ok=%s",
                dry_run, doc_stamp, elapsed_ms,
                result.get("ok") if isinstance(result, dict) else "?")
    return {"doc_stamp": doc_stamp, "dry_run": dry_run,
            "elapsed_ms": elapsed_ms, "idempotence": result}


#: Task #69, decision by the lead (measured, not proposed): a type found by
#: the census is NEVER a delete candidate, ever, regardless of ``delete``.
#: Element.Delete() on an ElementType deletes every INSTANCE of that type,
#: including ones this program did not create — consenting to "undo what I
#: built" is not consent to delete a stranger's elements, and no stamp of
#: ours changes who else is using that type. This is a boundary of the
#: feature, stated up front, not a gap the reader has to infer from a
#: number that does not add up.
_TYPES_NOT_DELETED_NOTE = (
    "типы (например, дублированные create_type) сюда не входят: удаление "
    "типа удаляет ВСЕ его экземпляры, включая не построенные этой "
    "программой, поэтому типы никогда не удаляются автоматически и "
    "снимаются вручную")


def _reconcile_stamp_census(
    expected_count: Optional[int], envelope: Any, *,
    stamp_prefix: str, delete: bool,
) -> dict[str, Any]:
    """Compare what the caller says it built against what the sweep found.

    Task #69: a plain program's stamp write is fail-open
    (``authoring._stamp_block`` — ``try { ... } catch { }`` for every
    non-A5 stamp), so "found by prefix" can silently undercount "elements
    the program actually created". ``expected_count`` is optional and
    caller-supplied (from the build receipt's created-id list); without it
    there is nothing to reconcile against, and that is reported explicitly
    rather than silently treated as a match.

    Reading ``envelope`` goes through ``serving._a5_sweep_payload`` — the
    SAME reader the pre-existing A5 ``_sweep``/``_preview`` runners
    (serving.py ~3222-3262) already use on the identical
    ``_run_declarative`` output — rather than a second hand-rolled
    ``.get("found")``. Two reasons, not one: (1) ``_a5_sweep_payload``
    unwraps the bridge envelope's nesting (``_a5_payload``, up to three
    ``result`` levels) the way this route's raw dict does NOT promise to
    be flat, so a naive top-level read can silently read past the real
    payload and report "unreadable" on a perfectly good sweep; (2) it also
    checks ``schema_version`` and — the part ``_a5_payload`` alone does
    NOT give you — that the payload's own ``prefix`` field is the exact
    ``stamp_prefix`` this call asked for, refusing a stale/foreign sweep's
    numbers instead of quietly reconciling against them. The name is
    legacy ("a5_"); the schema and the prefix-binding check are generic —
    they work identically for the ``kir:<hash8>:`` grammar this task adds.

    Types (task #69, second pass, decision by the lead): ``create_type``
    stamps its duplicated FamilySymbol on ``ALL_MODEL_TYPE_COMMENTS`` —
    MEASURED (compiled a real ``create_type`` program and inspected the
    emitted C#) to be a parameter ``WhereElementIsNotElementType()``
    structurally never reaches, so the instance census alone would
    silently undercount any program that used ``create_type`` and
    misattribute the gap to a fail-open Comments write that never
    happened. The sweep now runs a SEPARATE ``WhereElementIsElementType()``
    census for exactly that reason — types are counted into the
    built↔found comparison (a program that used create_type can still
    reconcile to true), but are NEVER a delete candidate: see
    ``_TYPES_NOT_DELETED_NOTE``.
    """
    from kukai.ir.a5_recovery import A5JournalError
    from kukai.ir.serving import _a5_sweep_payload

    try:
        payload = _a5_sweep_payload(envelope, stamp_prefix=stamp_prefix)
    except A5JournalError as exc:
        # A5JournalError is a NAMED census verdict, not a route-level 500:
        # "перепись не привязана к этому префиксу" is as legitimate an
        # answer as a matching count.
        return {
            "expected_count": expected_count,
            "found_count": None, "deleted_count": None,
            "remaining_count": None,
            "types_found_count": None, "types_found": [], "types_note": None,
            "census_matched": None, "cleanup_complete": None,
            "reconciled": False,
            "verdict": f"перепись невозможна: {exc}",
        }

    found = payload["found"]
    deleted = payload["deleted"]
    remaining = payload["remaining"]
    types_found = payload["types_found"]
    types_rows = [{"id": i, "name": n} for i, n in
                  zip(payload["types_found_ids"], payload["types_found_names"])]
    total_found = found + types_found

    census_matched: Optional[bool]
    found_desc = (f"экземпляров: {found}, типов: {types_found}"
                  if types_found else f"{found}")
    if expected_count is None:
        census_matched = None
        census_note = (f"expected_count не передан — построено↔найдено "
                        f"не проверено (найдено {found_desc})")
    else:
        gap = expected_count - total_found
        census_matched = gap == 0
        if census_matched:
            census_note = f"построено↔найдено сошлось: {found_desc}"
        elif gap > 0:
            # Deliberately generic — same discipline as naming an observed
            # fact instead of guessing a cause: the sweep can see THAT
            # built and found disagree, not WHICH of several mechanisms
            # did it (fail-open Comments write at build time, a later
            # overwrite of the stamp, or the element no longer existing),
            # so it names the categories and says outright it cannot tell
            # them apart — not one hypothesis dressed up as the answer.
            census_note = (
                f"построено↔найдено НЕ сошлось: программа заявила "
                f"{expected_count}, найдено {found_desc} (не хватает "
                f"{gap}) — причину рантайм не определяет: возможные "
                f"варианты — параметр Comments недоступен/только для "
                f"чтения при сборке (fail-open запись штампа), штамп "
                f"перезаписан после сборки чем-то другим, либо элемент "
                f"более не существует в документе; перепись их не "
                f"различает")
        else:
            census_note = (
                f"построено↔найдено НЕ сошлось: найдено {found_desc}, это "
                f"на {-gap} больше заявленных {expected_count} — "
                f"вероятная причина: тот же program-hash уже стоял на "
                f"элементах ДО этой сборки (kir:<hash8> не различает "
                f"прогоны одной программы)")

    # Preview never deletes (found/remaining after the second scan are the
    # same set), so "everything is gone" is a fact ONLY delete=true can
    # earn — never blend it into the built↔found gap above. Types are
    # EXCLUDED from this fact on purpose: a leftover type is policy, not
    # failure, and must never read as "cleanup incomplete".
    if delete:
        cleanup_complete = remaining == 0
        cleanup_note = (
            f"удаление: убрано всё найденное среди экземпляров ({deleted} "
            f"из {found})"
            if cleanup_complete else
            f"удаление: НЕ всё убрано — после удаления осталось "
            f"{remaining} экземпляров со штампом (найдено {found}, "
            f"удалено {deleted})")
    else:
        cleanup_complete = None
        cleanup_note = (f"предпросмотр — удаление не выполнялось (найдено "
                        f"{found} экземпляров)")

    known = [c for c in (census_matched, cleanup_complete) if c is not None]
    reconciled = False if any(c is False for c in known) else (
        True if known else None)

    verdict = f"{census_note}; {cleanup_note}"
    types_note = None
    if types_found:
        types_note = _TYPES_NOT_DELETED_NOTE
        shown = ", ".join(f"{r['id']} «{r['name']}»" for r in types_rows[:5])
        if len(types_rows) > 5:
            shown += ", …"
        verdict += f"; {types_note} ({types_found}: {shown})"

    return {
        "expected_count": expected_count, "found_count": found,
        "deleted_count": deleted, "remaining_count": remaining,
        "types_found_count": types_found, "types_found": types_rows,
        "types_note": types_note,
        "census_matched": census_matched, "cleanup_complete": cleanup_complete,
        "reconciled": reconciled,
        "verdict": verdict,
    }


@router.post("/cleanup_stamps", dependencies=[Depends(verify_admin_token)])
async def cleanup_stamps(payload: dict[str, Any]) -> Any:
    """Preview or delete stamps owned by one exact A5 run OR one exact
    regular-program content hash (task #69 — cancellation as a feature).

    Preview is the default.  Deletion requires both ``delete=true`` and the
    caller to repeat the exact prefix in ``confirm_prefix``.  ``stamp_prefix``
    must be one of the two closed grammars ``_orphan_sweep_cs`` accepts —
    ``kir:a5:<doc12>:<run16>:`` (one A5 run) or ``kir:<hash8>:`` (one
    program's content hash, chat or ``/admin/kir/run``); see that function's
    docstring for what the program-hash form does and does not scope to.

    Optional ``expected_count``: how many elements the CALLING side's build
    receipt says the program created.  When given, the response carries an
    explicit ``reconciliation`` verdict comparing it against how many
    elements the sweep found still carrying the stamp — the only way to
    surface a fail-open stamp write (see ``_reconcile_stamp_census``)
    instead of leaving a silent gap for the reader to guess at.  Types
    (``create_type``) are found and reported in
    ``reconciliation.types_found`` (id + name) but are NEVER a delete
    candidate, regardless of ``delete`` — deleting a type deletes every
    instance of it, including ones this program did not build; see
    ``_TYPES_NOT_DELETED_NOTE``.
    """
    stamp_prefix = payload.get("stamp_prefix")
    if not isinstance(stamp_prefix, str):
        raise HTTPException(status_code=422, detail="stamp_prefix is required")
    delete = payload.get("delete", False)
    if not isinstance(delete, bool):
        raise HTTPException(status_code=422, detail="delete must be boolean")
    if delete and payload.get("confirm_prefix") != stamp_prefix:
        raise HTTPException(
            status_code=422,
            detail="confirm_prefix must exactly repeat stamp_prefix")
    expected_count = payload.get("expected_count")
    if expected_count is not None and (
            isinstance(expected_count, bool)
            or not isinstance(expected_count, int)
            or expected_count < 0):
        raise HTTPException(
            status_code=422,
            detail="expected_count must be a non-negative integer")
    # Validate the closed prefix grammar (A5 run OR program content hash)
    # before selecting or contacting a live document.  The generated preview
    # is discarded here.
    from kukai.ir.serving import _orphan_sweep_cs
    try:
        _orphan_sweep_cs(stamp_prefix, delete=delete)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    target = _match_admin_ws(str(payload.get("doc_contains") or "проект1"))
    ws, ws_id = target["ws"], target["ws_id"]
    from kukai.api.bridge_protocol import _bridge_callback
    from kukai.ir.serving import (
        _probe_document_fingerprint, _run_declarative)
    from kukai.llm import turn_context

    async def bridge_callback(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return await _bridge_callback(ws, ws_id, method, params)

    class _Shim:
        _revit_version = target["revit_version"] or "2026"

        async def _repair_code(self, *a: Any, **k: Any) -> Optional[str]:
            return None

    token = turn_context._active_device_id.set(_pinned_device())
    try:
        fingerprint = await _probe_document_fingerprint(
            _Shim(), bridge_callback)
        if fingerprint is None:
            raise HTTPException(
                status_code=409,
                detail="active document fingerprint could not be proven")
        code = _orphan_sweep_cs(
            stamp_prefix, delete=delete,
            document_fingerprint=fingerprint)
        res = await _run_declarative(
            _Shim(), bridge_callback, code, "cleanup_stamps", 120000)
    finally:
        turn_context._active_device_id.reset(token)
    reconciliation = _reconcile_stamp_census(
        expected_count, res, stamp_prefix=stamp_prefix, delete=delete)
    logger.info(
        "[admin/kir] cleanup_stamps preview=%s doc=%r result=%s "
        "reconciliation=%s",
        not delete, target["document_name"], res, reconciliation)
    return {"document_name": target["document_name"],
            "stamp_prefix": stamp_prefix, "preview": not delete,
            "document_fingerprint": fingerprint.digest,
            "result": res, "reconciliation": reconciliation}
