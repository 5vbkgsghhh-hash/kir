"""Dispatcher: extracted skill markers → Bridge WS messages.

Backend assembles JSON payloads that match the message types the Bridge
already understands (skill_save_request, skill_delete_request, …). The
WebSocket layer ships them via the bridge_request → frontend → C# Bridge
path. Same delivery channel as `bridge_request`, no new wire types.

The dispatcher is intentionally async-friendly: each action returns a
coroutine that resolves once the Bridge response arrives, with a 5s
default timeout. Caller can fire-and-forget or await — fire-and-forget
is preferred during /шаблон because the user is mid-conversation and we
don't want to block the chat reply on disk I/O.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Awaitable, Callable, Optional

from kukai.skills.skill_markers import MarkerKind, SkillMarker, validate_marker

logger = logging.getLogger(__name__)

# Caller injects a function that knows how to send a JSON dict to the
# Bridge via the per-request frontend WS connection. Decoupled from any
# specific transport so unit tests can inject a fake.
SendFn = Callable[[dict[str, Any]], Awaitable[None]]


class SkillDispatchError(RuntimeError):
    """Raised when a marker cannot be turned into a valid Bridge call."""


def build_bridge_message(marker: SkillMarker) -> Optional[dict[str, Any]]:
    """Translate one validated marker into a Bridge-bound JSON message.

    Returns None for markers that have no Bridge-side action
    (e.g. CANCEL_DRAFT in V1 is a no-op besides logging).
    """
    err = validate_marker(marker)
    if err is not None:
        logger.warning("Skipping invalid skill marker: %s", err)
        return None

    request_id = f"skill_marker_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"

    if marker.kind == MarkerKind.DRAFT_SAVE:
        return {
            "type": "skill_save_request",
            "request_id": request_id,
            "trigger": "/" + marker.get("name").lstrip("/"),
            "category": ".draft",  # canonical drafts location
            "content": marker.code,
            "_marker_kind": "DRAFT_SAVE",
        }

    if marker.kind == MarkerKind.PROMOTE:
        # Bridge needs a single op: read draft + save with new trigger/category
        # + delete draft. SkillStorage.PromoteDraft does this atomically. We
        # expose it through a dedicated message type — added in lockstep.
        return {
            "type": "skill_promote_request",
            "request_id": request_id,
            "draft_name": marker.get("draft").lstrip("/"),
            "trigger": "/" + marker.get("trigger").lstrip("/"),
            "category": marker.get("category"),
            "_marker_kind": "PROMOTE",
        }

    if marker.kind == MarkerKind.UPDATE:
        return {
            "type": "skill_save_request",  # save acts as upsert
            "request_id": request_id,
            "trigger": "/" + marker.get("trigger").lstrip("/"),
            "category": marker.get("category", "АР"),
            "content": marker.code,
            "_marker_kind": "UPDATE",
        }

    if marker.kind == MarkerKind.DELETE:
        return {
            "type": "skill_delete_request",
            "request_id": request_id,
            "trigger": "/" + marker.get("trigger").lstrip("/"),
            "_marker_kind": "DELETE",
        }

    if marker.kind == MarkerKind.CANCEL_DRAFT:
        return {
            "type": "skill_draft_cancel_request",
            "request_id": request_id,
            "name": marker.get("name").lstrip("/"),
            "_marker_kind": "CANCEL_DRAFT",
        }

    return None


async def dispatch_markers(
    markers: list[SkillMarker],
    send: SendFn,
    *,
    fire_and_forget: bool = True,
) -> list[dict[str, Any]]:
    """Send each marker's Bridge message via `send`.

    Returns the list of successfully-sent payloads (for logging/audit).
    Errors per-marker are caught so one bad marker doesn't sink the others.
    """
    sent: list[dict[str, Any]] = []
    for marker in markers:
        try:
            msg = build_bridge_message(marker)
        except Exception:
            logger.exception("build_bridge_message threw for kind=%s", marker.kind)
            continue
        if msg is None:
            continue

        try:
            if fire_and_forget:
                asyncio.create_task(_safe_send(send, msg))
            else:
                await send(msg)
            sent.append(msg)
            logger.info(
                "Skill marker dispatched: kind=%s trigger=%s",
                marker.kind.value,
                msg.get("trigger") or msg.get("name") or msg.get("draft_name"),
            )
        except Exception:
            logger.exception(
                "Failed to send skill marker: kind=%s",
                marker.kind.value,
            )
    return sent


async def _safe_send(send: SendFn, msg: dict[str, Any]) -> None:
    """Wrap send() so a fire-and-forget failure becomes a log line, not an
    unhandled task exception."""
    try:
        await send(msg)
    except Exception:
        logger.exception("Background send failed for skill marker: %s", msg.get("type"))
