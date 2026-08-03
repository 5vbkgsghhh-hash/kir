"""Shared helpers for chat endpoints (WebSocket and HTTP).

Extracts duplicated logic: rate limiting, session ownership, message saving,
and history building. Both chat_ws.py and chat_http.py delegate to these.

Context management strategy:
- Gemini 3 Flash has ~1M token context. We use up to 500K for conversation.
- When context grows beyond COMPACT_THRESHOLD, older messages are summarized
  by the LLM into a compact block, preserving key facts and decisions.
- Recent messages are always kept verbatim for continuity.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Optional

from kukai.licensing.license_manager import DailyLimitError
from kukai.llm.fallback_runner import FallbackChainExhausted, run_with_fallback
from kukai.storage.models import Message

logger = logging.getLogger(__name__)


# --- Context limits (read from config at call time) ---
def _max_context_tokens():
    from kukai.config import get_settings
    return get_settings().max_context_tokens

def _compact_threshold():
    from kukai.config import get_settings
    return get_settings().compact_threshold

def _keep_recent():
    from kukai.config import get_settings
    return get_settings().keep_recent_messages

def _db_message_limit():
    from kukai.config import get_settings
    return get_settings().db_message_limit

def _history_tool_cap() -> int:
    """KUKAI_HISTORY_TOOL_CAP — max chars kept per STALE tool-result message
    when the history is replayed to the model. 0 disables the trim entirely.

    WHY (measured on prod 2026-07-26): tool results are 66% of ALL stored
    history mass (1.67M of 2.5M chars; 78% in the largest session) at ~1557
    chars each, while compaction is configured at a threshold no real session
    ever reaches — so every turn replays the full raw JSON of every past tool
    call. Turn latency p50 grows 36s → 79s between the first three turns of a
    session and turns 11-25. A stale tool result is dead weight: the assistant
    already folded it into its own reply, which stays verbatim.

    Read at call time (KUKAI_EXEC_PIPELINE convention) so the operator can
    flip it on a live process. Default ON with a kill-switch (set 0), like
    KUKAI_GOAHEAD_KEEPS_TOOLS — a dark default would leave the fix inert."""
    raw = os.environ.get("KUKAI_HISTORY_TOOL_CAP", "600").strip()
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 600

# Legacy constants for backward compatibility in case direct references exist
MAX_CONTEXT_TOKENS = 500_000
COMPACT_THRESHOLD = 400_000
KEEP_RECENT = 30
COMPACT_SUMMARY_TOKENS = 4000
DB_MESSAGE_LIMIT = 500

# KUKAI_COMPACT_CACHE — single sources of truth shared by the summarizer and
# the cache layer:
#   * _PRIOR_SUMMARY_PREFIX labels the stored rolling summary when it is
#     seeded into an incremental fold, so the compactor merges it with the
#     delta messages into ONE summary.
#   * _COMPACT_FAILURE_MARKER opens the summarization-failure stub; the cache
#     layer refuses to persist any summary starting with it (a failure stub
#     must never poison the session's rolling summary).
_PRIOR_SUMMARY_PREFIX = "[Резюме более ранней части разговора]"
_COMPACT_FAILURE_MARKER = "[Контекст сжат."


class RateLimitExceeded(Exception):
    """Raised when the daily request limit is exceeded."""
    pass


class SessionOwnershipError(Exception):
    """Raised when a session belongs to another device."""
    pass


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Rough token estimate: 1 token ~ 3 characters for Russian/Cyrillic."""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += len(content) // 3
        # Count tool calls content too
        if msg.get("tool_calls"):
            total += len(json.dumps(msg["tool_calls"])) // 4
    return total


def _estimate_tokens_single(text: str) -> int:
    """Token estimate for a single string."""
    return len(text) // 3


_TOOL_TRIM_MARKER = "[свёрнутый результат инструмента"


def _summarize_tool_result(content: str, cap: int) -> str:
    """Collapse a stale tool result into a stub that can never be MISREAD.

    A plain prefix cut is dangerous here: `{"count": 412, "ids": ["1", "2",`
    reads as a complete-looking list of 50 ids when the real answer had 412, and
    a follow-up "удали найденные" would then act on the visible fraction. So we
    never hand back a truncated JSON *prefix* — we hand back a DESCRIPTION:
    scalars survive verbatim (they are the useful part: counts, verdicts, flags),
    while every collection is replaced by its size. Non-JSON payloads degrade to
    a clearly bracketed excerpt that cannot be mistaken for structured output."""
    try:
        parsed = json.loads(content)
    except (json.JSONDecodeError, TypeError, ValueError):
        parsed = None

    if isinstance(parsed, dict):
        kept: dict[str, Any] = {}
        for k, v in parsed.items():
            if isinstance(v, (str, int, float, bool)) or v is None:
                kept[k] = v if not isinstance(v, str) or len(v) <= 120 else v[:120] + "…"
            elif isinstance(v, list):
                kept[k] = f"<{len(v)} элем. — свёрнуто>"
            elif isinstance(v, dict):
                kept[k] = f"<объект, {len(v)} полей — свёрнуто>"
        body = json.dumps(kept, ensure_ascii=False)
        if len(body) > cap:
            body = body[:cap] + "…"
        return f"{_TOOL_TRIM_MARKER}, было {len(content)} символов] {body}"

    excerpt = content[:cap].replace("\n", " ")
    return f"{_TOOL_TRIM_MARKER}, было {len(content)} символов] {excerpt}…"


def _trim_stale_tool_results(
    messages: list[dict[str, Any]], keep_recent: int,
) -> list[dict[str, Any]]:
    """Collapse tool-result messages OUTSIDE the recent window.

    Structure-preserving by construction: role, ``tool_call_id`` and every
    other key are copied verbatim and only ``content`` is shortened, so
    assistant/tool pairing (``_fix_orphaned_tools``) and the compact-cache
    watermark (keyed by message id) are untouched. The most recent
    ``keep_recent`` messages — the ones the model is actually reasoning over —
    are never trimmed, and an already-short result is left alone.

    No LLM call: this is the cheap half of context management, complementary
    to (and running before) the summarizing compactor."""
    cap = _history_tool_cap()
    if cap <= 0 or keep_recent < 0 or len(messages) <= keep_recent:
        return messages
    cutoff = len(messages) - keep_recent
    out: list[dict[str, Any]] = []
    trimmed = 0
    saved = 0
    for i, msg in enumerate(messages):
        content = msg.get("content")
        if (i < cutoff and msg.get("role") == "tool"
                and isinstance(content, str) and len(content) > cap
                and _TOOL_TRIM_MARKER not in content):
            stub = _summarize_tool_result(content, cap)
            if len(stub) >= len(content):
                # A payload only just over the cap (or an all-scalar one) can
                # summarize LONGER than it started — a shrinker must never grow
                # its input. Keep the original; it was cheap anyway.
                out.append(msg)
                continue
            shortened = dict(msg)
            shortened["content"] = stub
            saved += len(content) - len(stub)
            trimmed += 1
            out.append(shortened)
        else:
            out.append(msg)
    if trimmed:
        logger.info(
            "History trim: %d stale tool results collapsed (cap %d) "
            "(~%d chars / ~%d tokens saved)", trimmed, cap, saved, saved // 3,
        )
    return out


async def _compact_messages(
    old_messages: list[dict[str, Any]],
    model: str,
    api_key: str = "",
    api_base: Optional[str] = None,
    prior_summary: str = "",
) -> str:
    """Send older messages to LLM for summarization.

    Returns a compact summary that preserves:
    - What the user asked to do
    - What was done (operations, results, element counts)
    - Important decisions and preferences
    - Errors encountered and how they were resolved
    - Current state of the model/project

    `prior_summary` (KUKAI_COMPACT_CACHE incremental fold): a previously
    produced summary covering everything BEFORE `old_messages`. When set, it
    is seeded into the payload so the LLM merges it with the new messages
    into one summary — the default "" keeps the legacy behavior identical.
    """
    # Build a text representation of old messages
    conversation_text = []
    if prior_summary:
        conversation_text.append(f"{_PRIOR_SUMMARY_PREFIX}: {prior_summary}")
    for msg in old_messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "tool":
            # Truncate large tool results for the compaction prompt
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            conversation_text.append(f"[Tool result]: {content}")
        elif role == "assistant":
            if msg.get("tool_calls"):
                tools = [tc.get("function", {}).get("name", "?") for tc in msg["tool_calls"]]
                conversation_text.append(f"[AI вызвал инструменты: {', '.join(tools)}]")
            if content:
                conversation_text.append(f"[AI]: {content}")
        elif role == "user":
            conversation_text.append(f"[Пользователь]: {content}")
        elif role == "system":
            # Skip system messages in compaction
            continue

    if prior_summary and len(conversation_text) == 1:
        # Nothing new produced any text — the stored summary already covers
        # everything worth keeping; skip the LLM call entirely.
        return prior_summary
    if not conversation_text:
        return ""

    text_block = "\n".join(conversation_text)
    # Cap the text we send for compaction (don't exceed ~100K chars)
    if len(text_block) > 300_000:
        text_block = text_block[:300_000] + "\n... [остальное обрезано]"

    compact_prompt = [
        {
            "role": "system",
            "content": (
                "Ты — компактор контекста для AI-ассистента Revit. "
                "Твоя задача — сжать историю разговора в краткое резюме, сохранив ВСЕ важные факты.\n\n"
                "Обязательно сохрани:\n"
                "- Что пользователь просил сделать (запросы, задачи)\n"
                "- Что было выполнено (какие операции, результаты, числа элементов)\n"
                "- Решения и предпочтения пользователя\n"
                "- Ошибки и как они были исправлены\n"
                "- Текущее состояние (что открыто, что изменено)\n"
                "- Имена элементов, категории, параметры которые упоминались\n\n"
                "НЕ включай:\n"
                "- Внутренние детали кода (C#, API вызовы)\n"
                "- Повторяющиеся попытки одного и того же\n"
                "- Системные сообщения и техническую отладку\n\n"
                "Формат: сплошной текст на языке пользователя, 5-15 предложений. "
                "Пиши от третьего лица: 'Пользователь попросил...', 'Было выполнено...'."
            ),
        },
        {
            "role": "user",
            "content": f"Сожми эту историю разговора:\n\n{text_block}",
        },
    ]

    # W3: route through unified fallback chain. The previous version called
    # litellm once and then tried the Gemini OAuth pool — but the pool is
    # DEV-ONLY and not configured in prod, so the pool-fallback branch
    # always failed too and we hit the "[Контекст сжат]" stub message.
    # The unified chain replaces both with Vertex → Google A → B → DeepSeek.
    try:
        summary = (await run_with_fallback(
            messages=compact_prompt,
            label="chat_helpers.compact_context",
            max_tokens=COMPACT_SUMMARY_TOKENS,
            temperature=0.1,  # deterministic for summaries
            stream=False,
        )).strip()
        logger.info(
            "Context compacted: %d messages → %d char summary (~%d tokens)",
            len(old_messages), len(summary), _estimate_tokens_single(summary),
        )
        return summary
    except FallbackChainExhausted as exc:
        logger.warning("Context compaction failed across all tiers: %s", exc)
        # Same stub message as before, but now only emitted when EVERY tier
        # in the prod chain has failed — not after a single Vertex 429.
        # Built from _COMPACT_FAILURE_MARKER (byte-identical to the literal)
        # so the compact-cache layer can recognize and never persist it.
        return (
            f"{_COMPACT_FAILURE_MARKER} В разговоре было {len(old_messages)} сообщений. "
            "Подробности утрачены из-за ошибки сжатия.]"
        )


def _apply_context_window(
    messages: list[dict[str, Any]],
    max_messages: int = 20,
) -> list[dict[str, Any]]:
    """Legacy sync context window for backward compatibility.

    Applies simple sliding window + token trimming + orphan tool cleanup.
    Used by existing tests. Production code uses async _build_context_messages.
    """
    if len(messages) <= max_messages:
        truncated = messages
    else:
        truncated = messages[-max_messages:]

    was_truncated = len(truncated) < len(messages)
    while len(truncated) > 1 and _estimate_tokens(truncated) > _max_context_tokens():
        truncated = truncated[1:]
        was_truncated = True

    cleaned = _fix_orphaned_tools(truncated)

    if not was_truncated and len(cleaned) == len(truncated):
        return cleaned

    truncation_notice: dict[str, Any] = {
        "role": "system",
        "content": "[Предыдущие сообщения были обрезаны для экономии контекста]",
    }
    return [truncation_notice] + cleaned


def _fix_orphaned_tools(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop 'tool' messages whose parent assistant+tool_calls was removed."""
    cleaned: list[dict[str, Any]] = []
    for msg in messages:
        if msg.get("role") == "tool":
            tool_call_id = msg.get("tool_call_id", "")
            has_parent = False
            for prev in cleaned:
                if prev.get("role") == "assistant" and prev.get("tool_calls"):
                    for tc in prev["tool_calls"]:
                        if tc.get("id") == tool_call_id:
                            has_parent = True
                            break
                if has_parent:
                    break
            if not has_parent:
                continue
        cleaned.append(msg)
    return cleaned


async def _build_context_messages(
    all_messages: list[dict[str, Any]],
    model: str,
    api_key: str = "",
    api_base: Optional[str] = None,
    compact_fn: Any = None,
) -> list[dict[str, Any]]:
    """Smart context management: use full history when possible, compact when needed.

    Strategy:
    0. Cap stale tool results (KUKAI_HISTORY_TOOL_CAP) — the cheap, lossless-
       enough trim that runs on EVERY turn, before any threshold is consulted
    1. If total tokens < COMPACT_THRESHOLD → use everything as-is
    2. If total tokens >= COMPACT_THRESHOLD → split into old + recent:
       - Recent KEEP_RECENT messages stay verbatim
       - Older messages get compacted into a summary via LLM
    3. Always fix orphaned tool results

    `compact_fn` (KUKAI_COMPACT_CACHE): optional async override
    `old_part -> summary` so the cache-aware path shares this exact spine —
    same threshold, same split, same summary-block wrapper. None (default)
    keeps the legacy per-turn full summarization byte-identical.
    """
    # Step 0 — runs before the token count so the threshold sees the trimmed
    # size, and before the old/recent split so a summarized prefix is built
    # from capped (not raw) tool dumps. Same KEEP_RECENT window as the split.
    all_messages = _trim_stale_tool_results(all_messages, _keep_recent())

    total_tokens = _estimate_tokens(all_messages)

    if total_tokens <= _compact_threshold():
        # Everything fits — just fix orphaned tools and return
        cleaned = _fix_orphaned_tools(all_messages)
        logger.debug("Context fits: %d tokens, %d messages", total_tokens, len(cleaned))
        return cleaned

    # Need to compact: split into old (to summarize) and recent (to keep)
    if len(all_messages) <= _keep_recent():
        # Even with few messages, they're huge — trim tool results
        recent = all_messages
        old_part: list[dict[str, Any]] = []
    else:
        split_point = len(all_messages) - _keep_recent()
        old_part = all_messages[:split_point]
        recent = all_messages[split_point:]

    logger.info(
        "Compacting context: %d total tokens, %d old msgs → summary, %d recent kept",
        total_tokens, len(old_part), len(recent),
    )

    # Compact old messages into summary
    result_messages: list[dict[str, Any]] = []
    if old_part:
        if compact_fn is None:
            summary = await _compact_messages(old_part, model, api_key, api_base)
        else:
            summary = await compact_fn(old_part)
        if summary:
            result_messages.append({
                "role": "system",
                "content": (
                    "## Краткое содержание предыдущей части разговора\n\n"
                    f"{summary}\n\n"
                    "---\n"
                    "Ниже — последние сообщения разговора (полный текст)."
                ),
            })

    # Add recent messages, fixing orphaned tools
    recent_cleaned = _fix_orphaned_tools(recent)
    result_messages.extend(recent_cleaned)

    final_tokens = _estimate_tokens(result_messages)
    logger.info("After compaction: %d tokens, %d messages", final_tokens, len(result_messages))

    return result_messages


# ---------------------------------------------------------------------------
# KUKAI_COMPACT_CACHE — persisted rolling compaction summary (flag-gated)
#
# Problem (IQ-moments #1): once a session crosses COMPACT_THRESHOLD, the
# legacy path re-summarizes the ENTIRE old-message prefix with an LLM call on
# EVERY turn, because the summary is never persisted — a hidden per-turn
# latency+cost tax that grows with the session.
#
# Fix: persist (summary, watermark) per session in the compact_cache table.
# `watermark_id` is the id of the LAST message the summary covers. On the
# next turn the old prefix is split at the watermark: everything up to it is
# already summarized (reused verbatim), and only the delta — messages that
# slid out of the KEEP_RECENT window since — is folded into the summary with
# ONE small LLM call. If the watermark is not found in the current prefix
# (history edited/cleared, or it scrolled past the DB load window), the cache
# is treated as stale and the prefix is re-summarized from scratch — i.e. the
# worst case is exactly today's behavior.
#
# Correctness: the assembled context keeps the legacy shape (one system
# summary-block + KEEP_RECENT verbatim messages) via the shared
# _build_context_messages spine, and the summary covers the same message
# prefix — same information, computed incrementally. Every cache interaction
# is fail-open: a store error degrades to the legacy full summarization,
# never breaks the chat turn.
# ---------------------------------------------------------------------------

async def _compact_messages_cached(
    db: Any,
    session_id: str,
    old_part: list[dict[str, Any]],
    old_ids: list[Optional[str]],
    model: str,
    api_key: str = "",
    api_base: Optional[str] = None,
) -> str:
    """Summarize `old_part` reusing the persisted rolling summary.

    `old_ids` are the DB message ids aligned 1:1 with `old_part`.
    """
    prior_summary = ""
    covered = 0

    cached: Optional[dict[str, Any]] = None
    try:
        cached = await db.get_compact_cache(session_id)
    except Exception:
        logger.warning(
            "compact-cache read failed for session %s — falling back to full "
            "summarization", session_id, exc_info=True,
        )

    if cached and cached.get("summary") and cached.get("watermark_id"):
        try:
            covered = old_ids.index(cached["watermark_id"]) + 1
            prior_summary = cached["summary"]
        except ValueError:
            # Watermark not in the current prefix: history was edited/cleared
            # or the covered messages scrolled past the DB load window.
            # Stale → full re-summarization (exactly the legacy behavior).
            logger.info(
                "compact-cache STALE for session %s (watermark %s not in "
                "current %d-message prefix) — full re-summarization",
                session_id, cached["watermark_id"], len(old_ids),
            )
            covered = 0

    if prior_summary and covered >= len(old_part):
        logger.info(
            "compact-cache HIT for session %s: %d messages already summarized, "
            "0 LLM calls", session_id, covered,
        )
        return prior_summary

    new_old = old_part[covered:]
    if prior_summary:
        logger.info(
            "compact-cache INCREMENTAL for session %s: %d covered, folding %d new",
            session_id, covered, len(new_old),
        )
    summary = await _compact_messages(
        new_old, model, api_key, api_base, prior_summary=prior_summary,
    )

    if summary.startswith(_COMPACT_FAILURE_MARKER):
        # Summarization failed across all tiers. Never cache the stub; with a
        # prior summary on hand, degrade to it (strictly more information than
        # the legacy stub) and declare the gap.
        if prior_summary:
            return (
                f"{prior_summary}\n\n"
                f"[Плюс ещё {len(new_old)} сообщений, сжатие которых не удалось.]"
            )
        return summary

    if summary and old_ids and old_ids[-1]:
        try:
            await db.save_compact_cache(
                session_id, summary, old_ids[-1], len(old_part),
            )
        except Exception:
            logger.warning(
                "compact-cache write failed for session %s (summary still "
                "used this turn)", session_id, exc_info=True,
            )
    return summary


async def _build_context_messages_cached(
    db: Any,
    session_id: str,
    all_messages: list[dict[str, Any]],
    message_ids: list[Optional[str]],
    model: str,
    api_key: str = "",
    api_base: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Cache-aware variant of _build_context_messages (KUKAI_COMPACT_CACHE).

    Shares the legacy spine (threshold, old/recent split, summary-block
    wrapper) via `compact_fn`; only the summarization of the old prefix is
    replaced with the persisted-watermark incremental fold.
    """
    if len(message_ids) != len(all_messages):
        # Defensive: ids must align 1:1 with messages for watermark math.
        logger.warning(
            "compact-cache: ids/messages misaligned (%d vs %d) for session %s "
            "— using legacy path", len(message_ids), len(all_messages), session_id,
        )
        return await _build_context_messages(all_messages, model, api_key, api_base)

    async def _cached_compactor(old_part: list[dict[str, Any]]) -> str:
        # old_part is always the leading slice of all_messages, so its ids
        # are the same-length leading slice of message_ids.
        return await _compact_messages_cached(
            db, session_id, old_part, message_ids[:len(old_part)],
            model, api_key, api_base,
        )

    return await _build_context_messages(
        all_messages, model, api_key, api_base, compact_fn=_cached_compactor,
    )


# IP-based rate limit tracking for unauthenticated users
# Key: IP address, Value: list of request timestamps
_ip_request_times: dict[str, list[float]] = {}
_IP_FREE_WINDOW_SECONDS = 7 * 24 * 3600  # 7 days
_IP_FREE_MAX_REQUESTS = 30  # Max requests per IP per week (when auth enabled)


async def check_rate_limit(
    state: Any,
    device_token: str,
    session_id: str,
    client_ip: str = "",
) -> None:
    """Check rate limit using sliding window. Raises RateLimitExceeded if exceeded.

    Only enforced when auth/license manager is active. During testing (auth disabled),
    all rate limits are bypassed.
    """
    if device_token and state.license_manager:
        try:
            rate_info = await state.license_manager.check_rate_limit_window(device_token)
            license_key = rate_info.get("license_key", "")
            await state.license_manager.log_request(device_token, license_key=license_key)
        except DailyLimitError as e:
            # Mode-aware: enforce -> actually block; shadow (or off) -> observe only,
            # never block (lets the quota be validated on real traffic before enforcing).
            from kukai.licensing.mode import licensing_enforced
            if licensing_enforced():
                raise RateLimitExceeded(str(e))
            logger.info("rate-limit would-exceed (shadow, session=%s): %s", session_id, e)
        except Exception:
            pass  # Never block on unexpected error
    return


async def verify_session_ownership(
    state: Any,
    session_id: str,
    device_id: str,
) -> None:
    """Verify that the session belongs to this device. Raises SessionOwnershipError."""
    existing_owner = await state.db.get_session_device_id(session_id)
    # Step 11 (deny-by-default): if the session has a REAL owner, the requester
    # must match it. The old `and device_id` skipped the check whenever the
    # requester's device_id was empty → an empty/missing device_id could read any
    # real-owned session (cross-tenant bleed, same class as the WAVE0 leak).
    # Empty-owner (anonymous, dev-stage) sessions stay shareable.
    if existing_owner and existing_owner != device_id:
        raise SessionOwnershipError("Сессия принадлежит другому устройству.")


async def prepare_chat_session(
    state: Any,
    session_id: str,
    device_id: str,
    message_text: str,
    max_context_messages: int = 500,  # overridden by _db_message_limit() at call site
) -> list[dict[str, Any]]:
    """Create/get session, save user message, build LLM message history.

    Uses smart compaction: sends full history to the LLM when possible
    (Gemini has 1M context), and only compacts when approaching 400K tokens.
    """
    from kukai.config import get_settings
    settings = get_settings()

    await state.db.get_or_create_session(session_id, device_id)

    user_msg = Message(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role="user",
        content=message_text,
    )
    await state.db.save_message(user_msg)

    history_messages = await state.db.get_session_messages(session_id, limit=max_context_messages)
    all_messages: list[dict[str, Any]] = []
    message_ids: list[Optional[str]] = []
    for msg in history_messages:
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = msg.tool_calls
        if msg.tool_call_id:
            entry["tool_call_id"] = msg.tool_call_id
        all_messages.append(entry)
        message_ids.append(msg.id)

    # Smart context management: full history up to 400K tokens, then compact
    if settings.compact_cache:
        # KUKAI_COMPACT_CACHE: reuse the persisted rolling summary and only
        # fold in messages past the stored watermark (incremental) instead of
        # re-summarizing the whole prefix with an LLM call on every turn.
        llm_messages = await _build_context_messages_cached(
            state.db,
            session_id,
            all_messages,
            message_ids,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
        )
    else:
        llm_messages = await _build_context_messages(
            all_messages,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            api_base=settings.llm_api_base,
        )

    return llm_messages


async def get_bridge_context(state: Any) -> tuple[Any, bool]:
    """Get bridge context if connected.

    Returns (context, has_document).
    """
    context = None
    has_document = False
    if state.bridge.connected:
        try:
            context = await state.bridge.context()
            has_document = True
        except Exception as e:
            logger.warning("Failed to get bridge context: %s", e)
            if state.bridge.last_ping and state.bridge.last_ping.has_document:
                has_document = True

    return context, has_document
