"""StreamEvent protocol + usage extraction (extracted from client.py).

Pure relocation (2026-07-04 client.py decomposition, Step 1): bodies are
byte-identical to their previous definitions in ``kukai/llm/client.py``;
``client.py`` re-exports both names so every existing importer keeps working.
Stateless — this module owns no mutable state.
"""
from __future__ import annotations

from typing import Any, Optional


class StreamEvent:
    """Event emitted during LLM streaming."""
    def __init__(self, event_type: str, data: Any = None):
        self.type = event_type  # "stream_start", "stream_chunk", "tool_start", "tool_end", "stream_end", "error"
        self.data = data

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        if self.type == "stream_chunk" and self.data:
            d["text"] = self.data
        elif self.type == "reasoning_chunk" and self.data:
            d["text"] = self.data
        elif self.type == "error" and self.data:
            d["error"] = self.data
        elif self.type == "tool_start" and self.data:
            d["tool"] = self.data
        elif self.type == "tool_end" and self.data:
            d["result"] = self.data
        # NOTE: the internal "usage" event (plan 013) intentionally has NO
        # payload here — it is consumed and dropped by the chat_ws event loop
        # before reaching the frontend, so it serializes to a bare {"type":
        # "usage"} if it ever leaks (harmless: no text/result key to render).
        return d


def _extract_usage(chunk: Any) -> Optional[dict[str, Any]]:
    """Read provider token usage from a streaming chunk, if it carries any.

    Plan 013 (IRON 10). A usage-bearing chunk (the final one when
    ``stream_options={"include_usage": True}``) has empty ``choices`` and a
    populated ``.usage``. Returns ``{prompt_tokens, cached_tokens,
    completion_tokens}`` or ``None`` when there is no usage on the chunk.

    Cached-token field name varies by provider/litellm: OpenAI-shape exposes
    ``usage.prompt_tokens_details.cached_tokens``; DeepSeek-native exposes
    ``usage.prompt_cache_hit_tokens``. Both are probed; ``cached_tokens`` is
    ``None`` when neither is present (provider reported no cache hit info).
    Pure + defensive so it is unit-testable and never throws into the stream.
    """
    u = getattr(chunk, "usage", None)
    if not u:
        return None
    details = getattr(u, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", None) if details else None
    if cached is None:
        cached = getattr(u, "prompt_cache_hit_tokens", None)  # DeepSeek-native
    return {
        "prompt_tokens": getattr(u, "prompt_tokens", None),
        "cached_tokens": cached,
        "completion_tokens": getattr(u, "completion_tokens", None),
    }
