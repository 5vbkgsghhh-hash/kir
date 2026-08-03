"""HTTP chat endpoints — fallback for when WebSocket is unavailable.

Endpoints:
  POST /chat — synchronous chat (full response)
  POST /chat/file — chat with file upload
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from kukai.api.dependencies import verify_device_token
from kukai.config import get_settings
from kukai.storage.models import Message

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""
    preferences: dict[str, Any] = {}


class ChatResponse(BaseModel):
    reply: str
    file_id: Optional[str] = None
    file_name: Optional[str] = None


@router.post("/chat", response_model=ChatResponse)
async def chat_http(
    request: ChatRequest,
    auth: dict[str, Any] = Depends(verify_device_token),
) -> ChatResponse:
    """HTTP fallback chat endpoint — returns full response."""
    from kukai.main import get_app_state
    from kukai.api.chat_helpers import (
        RateLimitExceeded,
        SessionOwnershipError,
        check_rate_limit,
        get_bridge_context,
        prepare_chat_session,
        verify_session_ownership,
    )

    state = get_app_state()
    device_id = auth.get("device_id", "")
    device_token = auth.get("device_token", "")
    session_id = request.session_id or str(uuid.uuid4())[:8]
    preferences = request.preferences
    units = preferences.get("units", "metric")

    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Пустое сообщение")

    # Message length check
    if len(request.message) > 1_000_000:
        raise HTTPException(
            status_code=400,
            detail="Сообщение слишком длинное. Максимум: 1 000 000 символов.",
        )

    # Prompt injection check
    from kukai.security.prompt_guard import check_input
    guard_result = check_input(request.message)
    if guard_result.blocked:
        logger.warning(
            "Prompt injection blocked (HTTP): score=%.1f detections=%s device_id=%s",
            guard_result.score,
            [d.label for d in guard_result.detections],
            device_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Сообщение заблокировано системой безопасности",
        )
    if guard_result.risk == "suspicious":
        logger.warning(
            "Suspicious input (HTTP, allowed): score=%.1f device_id=%s",
            guard_result.score, device_id,
        )
        # Use sanitized text for suspicious input (same as WebSocket path)
        request.message = guard_result.sanitized

    # Rate limit check
    try:
        await check_rate_limit(state, device_token, session_id)
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    # Session ownership check
    try:
        await verify_session_ownership(state, session_id, device_id)
    except SessionOwnershipError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Prepare session, save user message, build LLM history
    llm_messages = await prepare_chat_session(state, session_id, device_id, request.message)

    # Bridge context
    context, _ = await get_bridge_context(state)

    # Extension system: read active extension from preferences
    active_extension = preferences.get("extension", "") or ""
    extension_profile = ""
    if active_extension:
        try:
            extension_profile = state.llm.get_extension_profile(active_extension)
        except Exception:
            logger.debug("Failed to load extension profile for %s", active_extension)

    # Get full response
    try:
        reply = await state.llm.simple_chat(
            messages=llm_messages,
            context=context,
            preferences=preferences,
            units=units,
            active_extension=active_extension or None,
            extension_profile=extension_profile or None,
        )
    except Exception as e:
        logger.exception("HTTP chat error")
        raise HTTPException(status_code=500, detail="Произошла внутренняя ошибка. Попробуйте повторить запрос.")

    # Note: rate limit logging moved to check_rate_limit() (log-before-process)

    # Save assistant message
    assistant_msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=reply,
    )
    await state.db.save_message(assistant_msg)

    return ChatResponse(reply=reply)


@router.post("/chat/file", response_model=ChatResponse)
async def chat_with_file(
    message: str = Form("Проанализируй файл"),
    session_id: str = Form(""),
    preferences: str = Form("{}"),
    file: UploadFile = File(...),
    auth: dict[str, Any] = Depends(verify_device_token),
) -> ChatResponse:
    """Chat with file upload — extracts file content and sends to LLM."""
    from kukai.main import get_app_state

    state = get_app_state()
    settings = get_settings()
    device_id = auth.get("device_id", "")
    device_token = auth.get("device_token", "")
    session_id = session_id or str(uuid.uuid4())[:8]

    # Rate limit check (same as /chat)
    from kukai.api.chat_helpers import RateLimitExceeded, check_rate_limit
    try:
        await check_rate_limit(state, device_token, session_id)
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))

    # Parse preferences
    try:
        prefs = json.loads(preferences)
    except json.JSONDecodeError:
        prefs = {}

    # Message length check
    if len(message) > 1_000_000:
        raise HTTPException(
            status_code=400,
            detail="Сообщение слишком длинное. Максимум: 1 000 000 символов.",
        )

    # Prompt injection check on user message
    from kukai.security.prompt_guard import check_input, check_file as check_file_content
    guard_result = check_input(message)
    if guard_result.blocked:
        logger.warning(
            "Prompt injection blocked (HTTP file): score=%.1f detections=%s device_id=%s",
            guard_result.score,
            [d.label for d in guard_result.detections],
            device_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Сообщение заблокировано системой безопасности",
        )
    if guard_result.risk == "suspicious":
        logger.warning(
            "Suspicious input (HTTP file, allowed): score=%.1f device_id=%s",
            guard_result.score, device_id,
        )
        message = guard_result.sanitized

    # File type check
    ALLOWED_EXTENSIONS = {
        '.xlsx', '.xls', '.csv', '.tsv', '.pdf', '.docx',
        '.json', '.xml', '.html', '.htm', '.txt', '.md', '.log',
        '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff',
        '.py', '.cs', '.js', '.ts', '.yaml', '.yml', '.toml',
    }
    from pathlib import Path as _Path
    ext = _Path(file.filename or "").suffix.lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемый тип файла: {ext}",
        )

    # File size check
    content = await file.read()
    if len(content) > settings.max_file_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"Файл слишком большой. Максимум: {settings.max_file_size_mb} МБ.",
        )

    # Magic-bytes validation (blocks executables disguised with wrong extension)
    from kukai.files.processor import validate_file_type
    is_valid, type_error = validate_file_type(file.filename or "unknown", content)
    if not is_valid:
        raise HTTPException(status_code=400, detail=type_error)

    # Raw bytes for tools that need them (e.g. price_vor) are passed into
    # simple_chat() below → seeded into the per-turn TurnState (NOT stored on the
    # shared singleton, which leaked across concurrent users). See turn_state.py.

    # Extract file content. For images we pull both a short text marker AND
    # a base64 data URL so we can attach the image to the LLM call as a
    # multimodal part (Gemini sees the picture natively, no OCR detour).
    file_text, image_attachments = _extract_file_content(content, file.filename or "unknown")

    # Prompt injection check on file content
    file_guard = check_file_content(file_text, file.filename or "unknown")
    if file_guard.blocked:
        logger.warning(
            "File content injection blocked (HTTP): score=%.1f detections=%s device_id=%s",
            file_guard.score,
            [d.label for d in file_guard.detections],
            device_id,
        )
        raise HTTPException(
            status_code=400,
            detail="Содержимое файла заблокировано системой безопасности",
        )

    # Build augmented message
    fname = file.filename or "unknown"
    is_excel = fname.lower().endswith((".xlsx", ".xls"))

    # VOR shortcut ARCHIVED 2026-06-10 (operator: archive Gemini+IFC+VOR). Excel +
    # "расценка" no longer creates a VOR session; the file goes through the normal
    # LLM path. Restore: re-add create_session_from_bytes branch (kukai/_archive/RESTORE.md).

    # --- Normal flow: send to LLM ---
    is_large_excel = is_excel and len(file_text) > 5000
    if is_large_excel:
        augmented_message = (
            f"<user_message>{message}</user_message>\n\n"
            f"<uploaded_file filename=\"{fname}\" type=\"excel\" rows=\"{file_text.count(chr(10))}\" "
            f"size_bytes=\"{len(content)}\">\n"
            f"Загружен Excel файл. Для расценки используй команду /расценка.\n"
            f"</uploaded_file>"
        )
    else:
        augmented_message = f"<user_message>{message}</user_message>\n\n<file_content filename=\"{fname}\">\n{file_text}\n</file_content>"

    # Session ownership check
    from kukai.api.chat_helpers import (
        SessionOwnershipError,
        get_bridge_context,
        prepare_chat_session,
        verify_session_ownership,
    )

    try:
        await verify_session_ownership(state, session_id, device_id)
    except SessionOwnershipError as e:
        raise HTTPException(status_code=403, detail=str(e))

    # Prepare session, save augmented message, build LLM history
    llm_messages = await prepare_chat_session(state, session_id, device_id, augmented_message)

    # Get response
    context, _ = await get_bridge_context(state)

    # Extension system: read active extension from preferences
    file_active_ext = prefs.get("extension", "") or ""
    file_ext_profile = ""
    if file_active_ext:
        try:
            file_ext_profile = state.llm.get_extension_profile(file_active_ext)
        except Exception:
            logger.debug("Failed to load extension profile for %s", file_active_ext)

    try:
        reply = await state.llm.simple_chat(
            messages=llm_messages,
            context=context,
            preferences=prefs,
            units=prefs.get("units", "metric"),
            active_extension=file_active_ext or None,
            extension_profile=file_ext_profile or None,
            image_attachments=image_attachments or None,
            uploaded_file_bytes=content,
        )
    except Exception as e:
        logger.exception("File chat error")
        raise HTTPException(status_code=500, detail="Произошла внутренняя ошибка. Попробуйте повторить запрос.")

    # Note: rate limit logging moved to check_rate_limit() (log-before-process)

    # Save assistant message
    assistant_msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=reply,
    )
    await state.db.save_message(assistant_msg)

    return ChatResponse(reply=reply)


def _extract_file_content(
    data: bytes, filename: str
) -> tuple[str, list[dict[str, str]]]:
    """Extract content from an uploaded file.

    Returns ``(text, image_attachments)``:
      - ``text`` is the textual representation that goes into chat history
        and the LLM context (Excel rows, PDF pages, marker for images, etc.)
      - ``image_attachments`` is a list of ``{"data_url", "filename"}`` dicts
        for any uploaded images. When non-empty, the caller should pass it
        through to ``LLMClient.simple_chat`` so the image attaches directly
        to the user message in multimodal format.

    Supports: Excel, CSV, PDF, Word, images (multimodal), JSON, XML, HTML,
    and plain text formats.
    """
    from kukai.files.processor import FileProcessor

    processor = FileProcessor()
    result = processor.extract(data, filename)

    image_attachments: list[dict[str, str]] = []
    if result.format == "image" and result.image_data_url:
        image_attachments.append({
            "data_url": result.image_data_url,
            "filename": result.image_filename or filename,
        })

    if result.success and result.text:
        return result.text, image_attachments

    if result.error:
        return f"[File: {filename}. Error: {result.error}]", image_attachments

    return (
        f"[File: {filename}, size: {len(data)} bytes. Could not extract content.]",
        image_attachments,
    )
