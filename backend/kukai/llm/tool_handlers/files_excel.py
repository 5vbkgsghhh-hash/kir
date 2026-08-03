"""File/Excel tool handlers (extracted from client.py).

Pure relocation (2026-07-04 client.py decomposition, Step 2): every body below
is byte-identical to its former ``LLMClient._execute_*`` method — including the
first parameter, deliberately still named ``self``: it is the ``LLMClient``
instance, and ``LLMClient`` rebinds each function as a plain class attribute so
they remain the SAME bound methods (``client._execute_generate_report(args)``)
for the dispatcher, the tests, and any external caller.

NOTE: ``_execute_generate_report`` did NOT move — tests/test_step6_bridge_cancel.py
pins its filename-sanitization line to client.py's source text, so it stays
there (same freeze class as test_repair_loop's getsource pin on _execute_tool).

Turn-scoped state is reached exactly as before: the WebSocket via the shared
``_active_ws`` ContextVar (kukai.llm.turn_context — same object client.py
re-exports) and the per-turn Excel bytes/filename/large-result via the
``self._last_*`` TurnState properties on the client instance.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from kukai.llm.turn_context import _active_ws

logger = logging.getLogger(__name__)


async def _execute_process_file(self, args: dict[str, Any]) -> dict[str, Any]:
    """Process an uploaded file — extract content for analysis."""
    from kukai.files.processor import FileProcessor
    from kukai.config import get_settings

    file_id = args.get("file_id", "")
    if not file_id:
        return {"error": True, "message": "file_id обязателен"}

    settings = get_settings()
    files_dir = settings.get_files_dir()

    # Find file by ID
    matching = [f for f in files_dir.iterdir() if f.name.startswith(file_id)]
    if not matching:
        return {"error": True, "message": f"Файл {file_id} не найден"}

    file_path = matching[0]
    processor = FileProcessor(files_dir=files_dir)
    data = file_path.read_bytes()
    result = processor.extract(data, file_path.name)

    return {
        "success": result.success,
        "text": result.text[:5000],  # Limit for LLM context
        "format": result.format,
        "rows_count": result.rows_count,
        "pages_count": result.pages_count,
        "error": result.error,
    }


async def _execute_modify_excel(self, args: dict[str, Any]) -> dict[str, Any]:
    """Apply operations to the last generated Excel file and re-send."""
    import base64

    operations = args.get("operations", [])
    if not operations:
        return {"error": True, "message": "No operations specified"}

    last_bytes = getattr(self, '_last_generated_excel_bytes', None)
    if not last_bytes:
        return {"error": True, "message": "No previous Excel file to modify. Use generate_report first."}

    orig_name = getattr(self, '_last_generated_excel_filename', 'report.xlsx')
    filename = args.get("filename", "")
    if not filename:
        base = orig_name.rsplit('.', 1)[0]
        filename = f"{base}_modified.xlsx"

    try:
        from kukai.files.excel_ops import apply_excel_operations
        modified_bytes = apply_excel_operations(last_bytes, operations)
    except Exception as e:
        logger.exception("modify_excel operations failed")
        return {"error": True, "message": f"Ошибка операций: {e}"}

    # Update stored bytes
    self._last_generated_excel_bytes = modified_bytes
    self._last_generated_excel_filename = filename

    # Send via WebSocket
    file_b64 = base64.b64encode(modified_bytes).decode('ascii')
    _ws = _active_ws.get()
    if _ws:
        try:
            await _ws.send_text(json.dumps({
                "type": "save_file",
                "filename": filename,
                "data": file_b64,
            }, ensure_ascii=False))
            logger.info("Sent modified Excel: %s (%d bytes)", filename, len(modified_bytes))
        except Exception as ws_err:
            logger.warning("Failed to send modified Excel via WS: %s", ws_err)

    op_types = [op.get("type", "?") for op in operations]
    return {
        "success": True,
        "filename": filename,
        "operations_applied": op_types,
        "message": f"Файл {filename} обновлён ({', '.join(op_types)}) и отправлен.",
    }


async def _execute_excel_script(self, args: dict[str, Any]) -> dict[str, Any]:
    """Execute openpyxl Python script on the current Excel file."""
    import base64

    script = args.get("script", "").strip()
    if not script:
        return {"error": True, "message": "No script provided"}

    # Get Excel bytes: prefer generated, fallback to uploaded
    excel_bytes = getattr(self, '_last_generated_excel_bytes', None)
    if not excel_bytes:
        excel_bytes = getattr(self, '_last_uploaded_file_bytes', None)
    if not excel_bytes:
        return {"error": True, "message": "Нет Excel файла. Сначала сгенерируйте отчёт (generate_report) или загрузите файл."}

    # Build filename
    orig_name = getattr(self, '_last_generated_excel_filename', 'report.xlsx')
    filename = args.get("filename", "")
    if not filename:
        base = orig_name.rsplit('.', 1)[0]
        filename = f"{base}_scripted.xlsx"
    if not filename.endswith(".xlsx"):
        filename += ".xlsx"

    try:
        from kukai.files.excel_script import run_excel_script
        modified_bytes, log_output = run_excel_script(excel_bytes, script)
    except ValueError as e:
        # Validation error
        return {"error": True, "message": f"Скрипт не прошёл валидацию: {e}"}
    except RuntimeError as e:
        return {"error": True, "message": str(e)}

    # Store modified bytes for chaining
    self._last_generated_excel_bytes = modified_bytes
    self._last_generated_excel_filename = filename

    # Send via WebSocket
    file_b64 = base64.b64encode(modified_bytes).decode('ascii')
    _ws = _active_ws.get()
    if _ws:
        try:
            await _ws.send_text(json.dumps({
                "type": "save_file",
                "filename": filename,
                "data": file_b64,
            }, ensure_ascii=False))
            logger.info("Sent scripted Excel: %s (%d bytes)", filename, len(modified_bytes))
        except Exception as ws_err:
            logger.warning("Failed to send scripted Excel via WS: %s", ws_err)

    result = {
        "success": True,
        "filename": filename,
        "message": f"Скрипт выполнен. Файл {filename} отправлен.",
    }
    if log_output:
        result["script_output"] = log_output[:2000]
    return result


async def _execute_send_local_file(self, args: dict[str, Any]) -> dict[str, Any]:
    """Read a file from local disk and send to user via WebSocket save_file."""
    import base64
    import tempfile
    from pathlib import Path

    file_path_str = args.get("file_path", "").strip()
    display_name = args.get("filename", "")

    if not file_path_str:
        return {"error": True, "message": "file_path is required"}

    file_path = Path(file_path_str)

    # Security: only allow files in temp directories (where Revit exports to)
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        resolved = file_path.resolve()
        if not resolved.is_relative_to(temp_root):
            return {"error": True, "message": "Доступ к файлу запрещён — только временные директории"}
    except Exception:
        return {"error": True, "message": "Некорректный путь к файлу"}

    if not file_path.exists():
        return {"error": True, "message": f"Файл не найден: {file_path.name}"}

    # Size check: max 50MB
    size = file_path.stat().st_size
    if size > 50 * 1024 * 1024:
        return {"error": True, "message": "Файл слишком большой (макс. 50 МБ)"}

    if not display_name:
        display_name = file_path.name

    # Determine MIME type
    ext = file_path.suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xls": "application/vnd.ms-excel",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".dwg": "application/acad",
        ".zip": "application/zip",
    }
    mime_type = mime_map.get(ext, "application/octet-stream")

    # Read and encode
    try:
        file_bytes = file_path.read_bytes()
        file_b64 = base64.b64encode(file_bytes).decode("ascii")
    except Exception as e:
        return {"error": True, "message": f"Ошибка чтения файла: {e}"}

    # Send via WebSocket
    _ws = _active_ws.get()
    if _ws:
        try:
            await _ws.send_text(json.dumps({
                "type": "save_file",
                "filename": display_name,
                "data": file_b64,
                "mime_type": mime_type,
            }, ensure_ascii=False))
            logger.info("Sent local file via WS: %s (%d KB, %s)", display_name, size // 1024, mime_type)
        except Exception as ws_err:
            logger.warning("Failed to send file via WS: %s", ws_err)

    size_kb = round(size / 1024, 1)
    return {
        "success": True,
        "filename": display_name,
        "size_kb": size_kb,
        "mime_type": mime_type,
        "message": f"Файл {display_name} ({size_kb} КБ) отправлен пользователю.",
    }
