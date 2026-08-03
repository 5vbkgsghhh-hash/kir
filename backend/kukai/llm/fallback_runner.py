"""Unified LLM fallback chain for mini-agents (project memory, RAG translation,
context compaction, etc). Mirrors the main chat chain but is FAST-mode only —
no thinking, no reasoning_effort on the primary. Call sites that previously
returned None on failure use this instead so single-tier flakes don't silently
drop user-visible state (the original ~31 fails/week on save_project_memory).

Chain (in order):
  1. vertex_ai/gemini-3-flash-preview            — Vertex API key
                                                   (settings.llm_api_key)
  2. gemini/gemini-3-flash-preview               — Google AI Studio key A
                                                   (env KUKAI_GOOGLE_AI_STUDIO_KEY_A
                                                    or settings.llm_google_fallback_api_key
                                                    for backward compat)
  3. gemini/gemini-3-flash-preview               — Google AI Studio key B
                                                   (env KUKAI_GOOGLE_AI_STUDIO_KEY_B)
  4. openrouter/deepseek/deepseek-v4-flash       — DeepSeek v4 Flash,
                                                   reasoning_effort stripped
                                                   (settings.llm_fallback_api_key)

Any tier whose key resolves empty is silently skipped — keeps single-key dev
environments working. If ALL tiers are unconfigured the chain raises
``FallbackChainExhausted`` with an empty ``tried`` list so callers see the
misconfiguration immediately rather than failing late.

Telemetry:
  - INFO log when a non-primary tier wins (so we can grep `fallback_used=true`
    in journal to count weekly silent failures we just rescued).
  - WARNING log per tier failure with the exception type + a 200-char preview.
  - ERROR log when every tier fails, just before raising
    ``FallbackChainExhausted``.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import litellm

from kukai.config import get_settings

logger = logging.getLogger(__name__)


class FallbackChainExhausted(Exception):
    """All tiers in the fallback chain failed.

    Attributes
    ----------
    label
        Caller-supplied label identifying the call site (e.g.
        ``"project_memory.save"``). Used for log correlation and to make
        ``str(exc)`` self-describing.
    tried
        Ordered list of tier names that were attempted before exhaustion.
        Empty when no tier was configured (all four api_key slots empty).
    last_exc
        The exception raised by the FINAL tier. Earlier failures are only
        in the logs — preserving every one would balloon the error object
        with often-identical 429s.
    """

    def __init__(self, label: str, tried: list[str], last_exc: BaseException):
        self.label = label
        self.tried = list(tried)
        self.last_exc = last_exc
        super().__init__(
            f"[{label}] fallback chain exhausted: tried={self.tried}; "
            f"last_error={last_exc!r}"
        )


def _resolve_google_keys(settings: Any) -> tuple[str, str]:
    """Resolve the two Google AI Studio keys.

    Priority:
      Key A: KUKAI_GOOGLE_AI_STUDIO_KEY_A env → settings.llm_google_fallback_api_key
             (the legacy single-key Settings field, kept for backward compat
             with existing .env files in prod).
      Key B: KUKAI_GOOGLE_AI_STUDIO_KEY_B env → "" (no legacy fallback).

    Returns (key_a, key_b). Either or both may be empty strings, in which
    case the corresponding tier is skipped.
    """
    key_a = os.environ.get("KUKAI_GOOGLE_AI_STUDIO_KEY_A", "") or getattr(
        settings, "llm_google_fallback_api_key", ""
    )
    key_b = os.environ.get("KUKAI_GOOGLE_AI_STUDIO_KEY_B", "")
    return key_a, key_b


def _gemini_studio_model(vertex_model: str) -> str:
    """Map a Vertex model id to its Google AI Studio equivalent.

    ``vertex_ai/gemini-3-flash-preview`` → ``gemini/gemini-3-flash-preview``.
    Anything that doesn't start with ``vertex_ai/`` is returned unchanged
    (defensive — covers the case where llm_model was overridden in .env).
    """
    if "/" not in vertex_model:
        return f"gemini/{vertex_model}"
    return "gemini/" + vertex_model.split("/", 1)[-1]


def _build_tiers() -> list[dict]:
    """Build the ordered tier list from current Settings + env.

    Each tier dict has::

        {
            "name": str,                 # human-readable, used in logs + tried list
            "model": str,                # litellm model id
            "api_key": str,              # provider-specific key
            "api_base": str | None,      # optional override
            "strip_reasoning_effort": bool,
        }

    Tiers with empty ``api_key`` are skipped. Tier order matches the docstring
    at the top of the module.
    """
    s = get_settings()
    tiers: list[dict] = []

    # ─── Tier 1: Vertex primary ───────────────────────────────────────────
    if s.llm_api_key:
        tiers.append({
            "name": "vertex_primary",
            "model": s.llm_model,
            "api_key": s.llm_api_key,
            "api_base": s.llm_api_base,
            "strip_reasoning_effort": False,
        })

    # ─── Tier 2 + 3: Google AI Studio keys A and B ────────────────────────
    studio_model = _gemini_studio_model(s.llm_model)
    key_a, key_b = _resolve_google_keys(s)
    if key_a:
        tiers.append({
            "name": "google_studio_a",
            "model": studio_model,
            "api_key": key_a,
            "api_base": None,
            "strip_reasoning_effort": False,
        })
    if key_b:
        tiers.append({
            "name": "google_studio_b",
            "model": studio_model,
            "api_key": key_b,
            "api_base": None,
            "strip_reasoning_effort": False,
        })

    # ─── Tier 4: OpenRouter DeepSeek ──────────────────────────────────────
    # DeepSeek v4 Flash rejects reasoning_effort with HTTP 400 — strip before
    # the call. The main chat chain already handles this; we mirror it here.
    if s.llm_fallback_api_key and s.llm_fallback_model:
        tiers.append({
            "name": "openrouter_deepseek",
            "model": s.llm_fallback_model,
            "api_key": s.llm_fallback_api_key,
            "api_base": None,
            "strip_reasoning_effort": True,
        })

    return tiers


async def run_with_fallback(
    messages: list[dict],
    *,
    label: str,
    **kwargs: Any,
) -> str:
    """Try each tier in order. Return the .content of the first success.

    Parameters
    ----------
    messages
        OpenAI-format chat messages to send to every tier.
    label
        Caller identifier for log correlation (e.g. ``"project_memory.save"``,
        ``"chat_helpers.compact_context"``). Surfaces in every log line and
        in ``FallbackChainExhausted.label``.
    **kwargs
        Pass-through to ``litellm.acompletion`` — temperature, max_tokens,
        response_format, etc. ``model``, ``messages``, ``api_key``, and
        ``api_base`` are SET by the runner per-tier and any value passed in
        kwargs for these names is silently overridden. ``reasoning_effort``
        is stripped for OpenRouter DeepSeek (which 400s on it).

    Returns
    -------
    str
        Content of the winning tier's first message (may be empty string if
        the provider returned a successful but empty response — caller's
        responsibility to validate).

    Raises
    ------
    FallbackChainExhausted
        Every configured tier failed. ``exc.tried`` lists the tier names in
        attempt order; ``exc.last_exc`` is the final tier's exception.
    """
    tiers = _build_tiers()
    if not tiers:
        # No keys configured at all — refuse to silently no-op. Better to
        # surface "no tiers" than to mysteriously return "" on every call.
        raise FallbackChainExhausted(
            label, [], RuntimeError("no LLM tiers configured (all api_key fields empty)")
        )

    tried: list[str] = []
    last_exc: BaseException | None = None

    for tier in tiers:
        tried.append(tier["name"])

        # Build per-tier call kwargs. We override the caller's model/api_key/
        # api_base/messages so the chain semantics are predictable. Caller
        # kwargs (temperature, max_tokens, response_format, stream=False, etc.)
        # pass through verbatim — except reasoning_effort which is stripped
        # for tiers that don't accept it.
        call_kwargs = dict(kwargs)
        call_kwargs.pop("model", None)
        call_kwargs.pop("api_key", None)
        call_kwargs.pop("api_base", None)
        call_kwargs.pop("messages", None)
        if tier["strip_reasoning_effort"]:
            call_kwargs.pop("reasoning_effort", None)
            # Mirror main chain: thinking dict is the Anthropic-shaped sibling
            # of reasoning_effort and OpenRouter DeepSeek doesn't accept it
            # either.
            call_kwargs.pop("thinking", None)

        try:
            resp = await litellm.acompletion(
                model=tier["model"],
                messages=messages,
                api_key=tier["api_key"],
                api_base=tier["api_base"],
                **call_kwargs,
            )
        except Exception as exc:  # noqa: BLE001 — every provider error is "try next"
            last_exc = exc
            logger.warning(
                "[%s] tier=%s failed (%s: %.200s) — trying next",
                label, tier["name"], type(exc).__name__, str(exc),
            )
            continue

        # Success — pull content. Defensive: some providers can return choices=[]
        # on a 200 with body but no candidates. Treat that as a tier failure so
        # we don't return an empty string when a later tier would have succeeded.
        try:
            content = resp.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            last_exc = exc
            logger.warning(
                "[%s] tier=%s returned malformed response (%s) — trying next",
                label, tier["name"], type(exc).__name__,
            )
            continue

        if tier["name"] != tiers[0]["name"]:
            logger.info(
                "[%s] fallback_used=true winning_tier=%s tried=%s",
                label, tier["name"], tried,
            )
        return content or ""

    # All tiers failed. last_exc is guaranteed non-None because tiers was
    # non-empty (we'd have raised at the top otherwise).
    assert last_exc is not None
    logger.error(
        "[%s] fallback_chain_exhausted tried=%s last_error=%r",
        label, tried, last_exc,
    )
    raise FallbackChainExhausted(label, tried, last_exc)


__all__ = ["FallbackChainExhausted", "run_with_fallback"]
