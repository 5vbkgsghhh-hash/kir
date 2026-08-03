"""Extensions list endpoint — returns available extension packs."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extensions"])


@router.get("/extensions")
async def list_extensions() -> list[dict[str, Any]]:
    """List available extensions.

    Returns a list of extension metadata dicts with keys:
    id, name_ru, name_en, icon.
    """
    try:
        from kukai.main import get_app_state

        state = get_app_state()
        return state.llm.get_extensions_list()
    except Exception:
        logger.debug("Failed to load extensions list", exc_info=True)

    return []
