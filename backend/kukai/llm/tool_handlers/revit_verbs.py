"""Deterministic Revit verb handlers (extracted from client.py).

Pure relocation (2026-07-04 client.py decomposition, Step 2): every body below
is byte-identical to its former ``LLMClient._execute_*`` method — including the
first parameter, deliberately still named ``self``: it is the ``LLMClient``
instance (``self._bridge`` is the legacy HTTP bridge client), and ``LLMClient``
rebinds each function as a plain class attribute so they remain the SAME bound
methods for the dispatcher, the tests, and any external caller.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Optional

from kukai.llm.loop_policy import _calculate_execute_timeout

# Type alias for the bridge callback function (same shape as client.py's):
#   async def callback(method: str, params: dict) -> dict
BridgeCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]

logger = logging.getLogger(__name__)


async def _execute_query_model(
    self,
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback] = None,
) -> dict[str, Any]:
    """Declarative element discovery (G3, query_model). Builds ONE verified,
    version-safe read-only C# template from the spec and executes it — the
    model never writes discovery C#, so this cannot compile-error or
    version-drift (F2/F5). Mirrors _execute_apply_revit_write."""
    from kukai.query.query_builder import build_query_code
    from kukai.security.validation import validate_code_safety

    try:
        code = build_query_code(args)
    except ValueError as e:
        return {"error": True, "message": f"query_model: неверный запрос — {e}"}
    except Exception as e:  # noqa: BLE001
        return {"error": True, "message": f"query_model: ошибка сборки — {e}"}

    violations = validate_code_safety(code)
    if violations:
        return {
            "error": True,
            "message": "query_model: сгенерированный код не прошёл проверку безопасности",
            "violations": violations,
        }

    from kukai.config import get_settings as _get_settings_qm
    max_timeout_ms = _get_settings_qm().max_execute_timeout * 1000
    timeout_ms = _calculate_execute_timeout(code, None, max_timeout_ms=max_timeout_ms)

    if bridge_callback:
        return await bridge_callback("execute", {"code": code, "timeout_ms": timeout_ms, "attempt": 1})
    elif self._bridge:
        result = await self._bridge.execute(code, timeout_ms=timeout_ms)
        return result.model_dump()
    else:
        return {"error": True, "message": "Revit не подключён"}


async def _execute_inspect(
    self,
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback] = None,
) -> dict[str, Any]:
    """Wave 1c — inspect(element_id): one element's category/type/level + all
    non-empty parameters (version-safe). Returns a perceptual dict. The bridge
    returns the C# dict directly (see A2), so perceive_inspect shapes it."""
    from kukai.llm.verbs import build_inspect_code, perceive_inspect
    from kukai.security.validation import validate_code_safety

    eid = str(args.get("element_id", "")).strip()
    if not eid:
        return {"error": True, "message": "inspect: укажите element_id"}
    code = build_inspect_code(eid)
    if validate_code_safety(code):
        return {"error": True, "message": "inspect: код не прошёл проверку безопасности"}
    if bridge_callback:
        raw = await bridge_callback("execute", {"code": code, "timeout_ms": 30000, "attempt": 1})
    elif self._bridge:
        raw = (await self._bridge.execute(code, timeout_ms=30000)).model_dump()
    else:
        return {"error": True, "message": "Revit не подключён"}
    return perceive_inspect(raw)


async def _execute_apply_revit_write(
    self,
    args: dict[str, Any],
    bridge_callback: Optional[BridgeCallback] = None,
) -> dict[str, Any]:
    """Execute a deterministic write operation via safe code generation."""
    from kukai.write.operations import (
        generate_set_parameter_code,
        generate_create_schedule_code,
        generate_hide_or_isolate_code,
        generate_rename_code,
        generate_delete_elements_code,
        generate_copy_elements_code,
        generate_move_elements_code,
    )
    from kukai.security.validation import validate_code_safety

    operation = args.get("operation", "")
    element_ids = args.get("element_ids", [])
    category = args.get("category", "")

    # ── create_element — the 8th, flag-gated declarative op (KUKAI_CREATE_ELEMENT,
    # design 2026-07-04: ground → render(verified template) → execute →
    # read-back witness → probe → Evaluator verdict). Flag OFF (default): the op
    # is absent from the tool schema, and a stray call falls through to the
    # terminal unknown-operation branch below — byte-identical to the
    # pre-create_element handler. The 7 legacy operations are untouched.
    if operation == "create_element":
        from kukai.write.create_element import (
            create_element_enabled as _ce_enabled,
            execute_create_element as _ce_execute,
        )
        if _ce_enabled():
            return await _ce_execute(self, args, bridge_callback)
        return {"error": True, "message": f"Неизвестная операция: {operation}"}

    # Resolve category alias to BuiltInCategory
    if category:
        from kukai.write.router import resolve_category
        resolved = resolve_category(category)
        if resolved:
            category = resolved

    if operation == "set_parameter":
        param_name = args.get("parameter_name", "")
        value = args.get("value", "")
        if not param_name:
            return {"error": True, "message": "parameter_name обязателен для set_parameter"}
        code = generate_set_parameter_code(element_ids, param_name, value, category)

    elif operation == "create_schedule":
        schedule_name = args.get("schedule_name")
        fields = args.get("schedule_fields")
        code = generate_create_schedule_code(category or "OST_Walls", schedule_name, fields)

    elif operation == "hide_or_isolate":
        action = args.get("view_action", "hide")
        if not element_ids:
            # 2026-07-10 (operator): hiding/isolating an EMPTY set is never the
            # intent — Revit enters temporary hide/isolate with nothing kept and
            # the view visually "empties" (live incident: a schedule turn fired
            # isolate with 0 resolved ids, {'action':'isolate','count':0}).
            # Refuse BEFORE codegen with an honest error so the model reacts.
            # Clearing isolation is a different API (DisableTemporaryViewMode)
            # and is not affected. Mirrors the delete_elements guard below.
            return {"error": True, "message": f"0 элементов — {action} не выполнен (пустой набор; защита вида)"}
        code = generate_hide_or_isolate_code(element_ids, action)

    elif operation == "rename_entities":
        new_name = args.get("new_name", "")
        mode = args.get("rename_mode", "exact")
        if not new_name:
            return {"error": True, "message": "new_name обязателен для rename_entities"}
        code = generate_rename_code(element_ids, new_name, mode)

    elif operation == "delete_elements":
        if not element_ids:
            return {"error": True, "message": "element_ids обязателен для delete_elements"}
        code = generate_delete_elements_code(element_ids)

    elif operation == "copy_elements":
        offset_x = float(args.get("offset_x", 0))
        offset_y = float(args.get("offset_y", 0))
        offset_z = float(args.get("offset_z", 0))
        if not element_ids:
            return {"error": True, "message": "element_ids обязателен для copy_elements"}
        code = generate_copy_elements_code(element_ids, offset_x, offset_y, offset_z)

    elif operation == "move_elements":
        offset_x = float(args.get("offset_x", 0))
        offset_y = float(args.get("offset_y", 0))
        offset_z = float(args.get("offset_z", 0))
        if not element_ids:
            return {"error": True, "message": "element_ids обязателен для move_elements"}
        code = generate_move_elements_code(element_ids, offset_x, offset_y, offset_z)

    else:
        return {"error": True, "message": f"Неизвестная операция: {operation}"}

    # Safety check generated code (should always pass, but defense-in-depth)
    violations = validate_code_safety(code)
    if violations:
        return {"error": True, "message": "Сгенерированный код не прошёл проверку безопасности", "violations": violations}

    # Execute via bridge
    from kukai.llm.client import _calculate_execute_timeout
    from kukai.config import get_settings as _get_settings2
    max_timeout_ms = _get_settings2().max_execute_timeout * 1000
    timeout_ms = _calculate_execute_timeout(code, len(element_ids) if element_ids else None, max_timeout_ms=max_timeout_ms)

    if bridge_callback:
        # apply_revit_write has no internal repair loop — single shot, mark as attempt=1.
        return await bridge_callback("execute", {"code": code, "timeout_ms": timeout_ms, "attempt": 1})
    elif self._bridge:
        result = await self._bridge.execute(code, timeout_ms=timeout_ms)
        return result.model_dump()
    else:
        return {"error": True, "message": "Revit не подключён"}


async def _execute_export_sheets_pdf(
    self, args: dict[str, Any], bridge_callback: Optional[BridgeCallback] = None,
) -> dict[str, Any]:
    """Export Revit sheets to PDF using deterministic C# code generation."""
    import tempfile
    import os

    if not bridge_callback and not self._bridge:
        return {"error": True, "message": "Revit не подключён"}

    sheet_ids = args.get("sheet_ids", [])
    combine = args.get("combine", False)
    quality = args.get("quality", "standard")

    # Create temp directory for export
    export_dir = tempfile.mkdtemp(prefix="kukai_export_")

    # Generate deterministic C# code
    from kukai.write.pdf_export import generate_pdf_export_code
    code = generate_pdf_export_code(
        export_dir=export_dir,
        sheet_ids=sheet_ids or None,
        combine=combine,
        quality=quality,
    )

    # Validate generated code (should always pass — doc.Export is not System.IO)
    from kukai.security.validation import validate_code_safety
    violations = validate_code_safety(code)
    if violations:
        logger.error("PDF export code failed validation: %s", violations)
        return {"error": True, "message": "Внутренняя ошибка генерации кода экспорта"}

    # Execute via bridge
    timeout_ms = 9_000_000  # 2.5 hours for PDF export (large sheet sets)
    try:
        if bridge_callback:
            # export_pdf is single-shot, no repair loop — attempt=1.
            result = await bridge_callback("execute", {"code": code, "timeout_ms": timeout_ms, "attempt": 1})
        else:
            bridge_result = await self._bridge.execute(code, timeout_ms=timeout_ms)  # type: ignore[union-attr]
            result = bridge_result.model_dump()
    except Exception as e:
        return {"error": True, "message": f"Ошибка экспорта: {e}"}

    if isinstance(result, dict) and result.get("error"):
        return result

    # List exported PDF files
    pdf_files = []
    try:
        for f in os.listdir(export_dir):
            if f.lower().endswith(".pdf"):
                fpath = os.path.join(export_dir, f)
                fsize = os.path.getsize(fpath)
                pdf_files.append({
                    "path": fpath,
                    "name": f,
                    "size_kb": round(fsize / 1024, 1),
                })
    except Exception:
        pass

    return {
        "success": True,
        "export_dir": export_dir,
        "files": pdf_files,
        "count": len(pdf_files),
        "message": f"Экспортировано {len(pdf_files)} PDF файлов. Используй send_local_file для отправки каждого файла пользователю.",
    }
