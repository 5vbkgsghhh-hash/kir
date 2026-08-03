"""Preflight discovery — query Revit for real parameter names before code generation.

LRU cache per session (max 500 entries). Before each LLM call,
detect the target category from the user message, fetch real parameter
names/types from bridge, and inject them into the system prompt.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)

BridgeCallback = Callable[[str, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]

_MAX_CACHE_SIZE = 500


class DiscoveryCache:
    """LRU cache for discovered Revit parameters, one instance per WebSocket session."""

    def __init__(self, max_size: int = _MAX_CACHE_SIZE):
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._max_size = max_size

    @property
    def size(self) -> int:
        return len(self._cache)

    async def get(
        self,
        category: str,
        bridge_callback: BridgeCallback,
    ) -> Optional[dict[str, Any]]:
        """Get discovery data for a category. Returns cached or fetches from bridge."""
        if not category:
            return None

        # Cache hit — move to end (LRU)
        if category in self._cache:
            self._cache.move_to_end(category)
            return self._cache[category]

        # Cache miss — fetch from bridge
        try:
            result = await bridge_callback("discover", {"category": category})
            if isinstance(result, dict) and not result.get("error"):
                # Evict oldest if at capacity
                while len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
                self._cache[category] = result
                return result
            else:
                logger.warning("Discovery failed for %s: %s", category, result)
                return None
        except Exception as e:
            logger.warning("Discovery bridge call failed for %s: %s", category, e)
            return None

    def invalidate(self, category: str) -> None:
        """Remove a specific category from cache."""
        self._cache.pop(category, None)

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
