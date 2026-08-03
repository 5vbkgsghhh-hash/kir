"""HTTP client for revit-coder router (OpenAI-compatible)."""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

import kukai.config as _config
from kukai.revit_coder.prompt_composer import compose_messages
from kukai.revit_coder.types import (
    ModelContext,
    RevitCoderError,
    RevitCoderResult,
)

logger = logging.getLogger(__name__)


async def generate_code(
    task: str,
    model_context: ModelContext,
    api_context: Optional[list[str]] = None,
    error_to_fix: Optional[str] = None,
    broken_code: Optional[str] = None,
    previous_code: Optional[str] = None,
) -> RevitCoderResult:
    """Call revit-coder router and return generated C# code.

    Args:
        task: Plain-English task description.
        model_context: Revit model state (version, active view, etc).
        api_context: Optional RAG snippets, top-3 by similarity.
        error_to_fix: If retrying after compile error — pass stderr here.
        broken_code: If retrying — pass the previous (broken) code.
        previous_code: For multi-turn — last successful code in this
                       conversation (when user asks to modify it).

    Returns:
        RevitCoderResult with `code` field containing C# body.

    Raises:
        RevitCoderError: Network error, 5xx response, or auth failure.
                         No fallback in Phase 1.
    """
    if not _config.REVIT_CODER_API_KEY:
        raise RevitCoderError(
            "KUKAI_REVIT_CODER_API_KEY not set. "
            "See docs/superpowers/specs/2026-05-01-revit-coder-integration-design.md"
        )

    messages = compose_messages(
        task=task,
        model_context=model_context,
        api_context=api_context,
        error_to_fix=error_to_fix,
        broken_code=broken_code,
        previous_code=previous_code,
    )

    payload = {
        "model": _config.REVIT_CODER_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": 0.1,    # deterministic-ish for code-gen
        "top_p": 0.95,
        "max_tokens": 2048,
    }

    headers = {
        "Authorization": f"Bearer {_config.REVIT_CODER_API_KEY}",
        "Content-Type": "application/json",
    }

    url = f"{_config.REVIT_CODER_URL.rstrip('/')}/chat/completions"
    started = time.monotonic()

    try:
        async with httpx.AsyncClient(timeout=_config.REVIT_CODER_TIMEOUT_SEC) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        raise RevitCoderError(
            f"Router returned {e.response.status_code}: {e.response.text[:200]}"
        ) from e
    except httpx.HTTPError as e:
        raise RevitCoderError(f"Network error: {e}") from e

    latency_ms = int((time.monotonic() - started) * 1000)

    try:
        choice = data["choices"][0]
        content = choice["message"]["content"]
        finish_reason = choice.get("finish_reason", "stop")
        usage = data.get("usage", {})
        model = data.get("model", _config.REVIT_CODER_MODEL)
    except (KeyError, IndexError) as e:
        raise RevitCoderError(f"Malformed response from router: {e}. Body: {data!r}") from e

    return RevitCoderResult(
        code=_strip_markdown_fences(content),
        finish_reason=finish_reason,
        latency_ms=latency_ms,
        model=model,
        prompt_tokens=usage.get("prompt_tokens", 0),
        completion_tokens=usage.get("completion_tokens", 0),
        node_used=None,  # router doesn't surface this in v1
    )


def _strip_markdown_fences(content: str) -> str:
    """Remove ```csharp ... ``` fences if revit-coder accidentally adds them."""
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
