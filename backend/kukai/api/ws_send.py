"""WS outbound send helpers — peeled verbatim from chat_ws.py.

Golden-path decomposition Phase 1 (2026-07-12, /root/kukai-golden-path-plan.md):
pure file move, zero behavior change. chat_ws re-exports these names.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from kukai.security.egress_filter import egress_mode as _egress_mode
from kukai.security.egress_filter import scrub_payload as _scrub_payload

logger = logging.getLogger(__name__)


_WS_SEND_TIMEOUT_S = 20.0


async def _send_json(ws: WebSocket, data: dict[str, Any]) -> None:
    """Send JSON over WebSocket, bounded so a half-open client can't hang the task.

    Egress filter (KUKAI_EGRESS_FILTER): the single outbound funnel — scrub KUKAI
    internals (model/provider names, backend architecture nouns, absolute paths) from
    user-visible text. off=no-op (byte-identical); shadow=log what WOULD be scrubbed;
    on=send scrubbed. Enforced guarantee vs the prompt's advisory secrecy rules. Never
    breaks a send.
    """
    _em = _egress_mode()
    if _em != "off":
        try:
            _scrubbed, _hits = _scrub_payload(data)
            if _hits:
                logger.info("EGRESS %s: scrubbed %d internal token(s): %s",
                            _em, len(_hits), sorted(set(h.lower() for h in _hits))[:10])
                if _em == "on":
                    data = _scrubbed
        except Exception:  # noqa: BLE001 — egress filter must never break a send
            pass
    await asyncio.wait_for(
        ws.send_text(json.dumps(data, ensure_ascii=False)),
        timeout=_WS_SEND_TIMEOUT_S,
    )


async def _emit_status(ws: WebSocket, text: str) -> None:
    """Send a product-language status bubble to the client.

    Use ONLY user-facing copy. Never expose internals (no 'Roslyn', no 'RAG',
    no entry counts, no agent names). Empty text clears the bubble.
    """
    try:
        await ws.send_json({"type": "status", "text": text})
    except Exception:
        pass  # Status is best-effort — never block on its failure.
