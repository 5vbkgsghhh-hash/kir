"""Project memory — persistent AI memory tied to a Revit project.

When an engineer works on a project for months, the AI remembers
the entire lifecycle: what was built, modified, checked, and decided.

Memory lifecycle:
1. After each chat session ends, the conversation is summarized
2. The summary is saved to project_memory table, keyed by project name
3. When a new session starts, all memories are loaded into system prompt
4. When memories grow too large, they're compacted into a single summary

The project name comes from the Revit document context (e.g., "ЖК Рассвет.rvt").
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from kukai.llm.fallback_runner import FallbackChainExhausted, run_with_fallback

logger = logging.getLogger(__name__)

# Max tokens for all project memories combined before compacting them
MAX_MEMORY_TOKENS = 15_000
# Target size after compacting memories
COMPACT_TARGET_TOKENS = 5_000


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ~ 3 chars for Russian."""
    return len(text) // 3


async def save_session_memory(
    db: Any,
    device_id: str,
    project_name: str,
    messages: list[dict[str, Any]],
    model: str,
    api_key: str = "",
    api_base: Optional[str] = None,
) -> None:
    """Summarize a chat session and save to project memory.

    Called when a session ends (disconnect, timeout, or explicit clear).
    Only saves if there were meaningful exchanges (>= 2 user messages).
    Each user (device_id) has their own memory per project.
    """
    if not project_name or project_name == "unknown":
        return
    if not device_id:
        return

    # Count meaningful messages (user + assistant with content)
    user_msgs = [m for m in messages if m.get("role") == "user"]
    if len(user_msgs) < 2:
        return  # Too short to remember

    # Build conversation text for summarization
    conversation_parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if not content or role == "system":
            continue
        if role == "user":
            conversation_parts.append(f"Пользователь: {content}")
        elif role == "assistant" and content:
            # Truncate long AI responses
            if len(content) > 500:
                content = content[:500] + "..."
            conversation_parts.append(f"AI: {content}")
        elif role == "tool":
            # Just note that a tool was used
            if len(content) > 200:
                content = content[:200] + "..."
            conversation_parts.append(f"[Результат инструмента]: {content}")

    text = "\n".join(conversation_parts)
    if len(text) < 100:
        return  # Nothing meaningful to save

    # Cap text for summary request
    if len(text) > 100_000:
        text = text[:100_000] + "\n...[обрезано]"

    try:
        summary_prompt = [
            {
                "role": "system",
                "content": (
                    "Ты записываешь краткую заметку о рабочей сессии инженера с AI-ассистентом в Revit. "
                    "Напиши 2-5 предложений о том что было сделано. Сохрани:\n"
                    "- Какие задачи решались\n"
                    "- Какие элементы/категории затрагивались (стены, перекрытия, трубы...)\n"
                    "- Какие изменения внесены в модель\n"
                    "- Какие проблемы обнаружены\n"
                    "Пиши кратко, по делу, на русском. Это заметка для будущих сессий."
                ),
            },
            {
                "role": "user",
                "content": f"Запиши краткое содержание этой сессии:\n\n{text}",
            },
        ]

        # W3: route through the unified fallback chain so transient Vertex
        # 429s don't drop the user's project memory on the floor. The legacy
        # ``model``/``api_key``/``api_base`` args are still accepted by this
        # function for back-compat with callers, but the runner now picks the
        # tier from Settings. (model/api_key/api_base parameters are kept in
        # the signature to avoid churning every call site at once.)
        try:
            summary = (await run_with_fallback(
                messages=summary_prompt,
                label="project_memory.save",
                max_tokens=500,
                temperature=0.1,
                stream=False,
            )).strip()
        except FallbackChainExhausted as exc:
            # Match the prior behaviour: swallow + log so a memory-write
            # failure never kills the chat path. The chain logs the tier
            # detail itself, we just log the high-level "save failed".
            logger.warning("Failed to save project memory: %s", exc)
            return

        if summary:
            await db.save_project_memory(device_id, project_name, summary, len(user_msgs))
            logger.info(
                "Project memory saved for '%s' (device=%s): %d chars, %d user messages",
                project_name, device_id[:8], len(summary), len(user_msgs),
            )

            # Check if memories need compacting
            await _maybe_compact_memories(db, device_id, project_name, model, api_key, api_base)

    except Exception as e:
        logger.warning("Failed to save project memory: %s", e)


def memory_mode() -> str:
    """``auto`` (historical) — the block rides along on every turn for this .rvt.
    ``optin`` — only when the turn explicitly asks for it.

    Read at call time so the mode can be flipped without a redeploy."""
    return os.environ.get("KUKAI_PROJECT_MEMORY_MODE", "auto").strip().lower()


async def load_project_memory(
    db: Any, device_id: str, project_name: str, *, requested: bool = False,
) -> str:
    """Load all memories for a device+project, formatted for the system prompt.

    Returns empty string if no memories exist.
    Each user sees only their own project memory.

    WHY THE WORDING BELOW IS CAREFUL (operator report, 2026-07-29). A brand-new
    chat gets a fresh session_id and an EMPTY message history — yet the model
    still opened by talking about work from previous sessions, on a model the
    user had just switched to. This block is why: it is keyed by device+project,
    not by dialog, so it rides into every new chat on the same .rvt, and it sits
    in the SYSTEM prompt, which is why changing the model changed nothing.

    The old header ("Ты работаешь с этим проектом не первый раз. Вот что
    происходило раньше:") reads as a handover — an instruction to CONTINUE. The
    text below keeps the same knowledge available but frames it as reference the
    model may consult, not a conversation it is resuming. ``optin`` mode turns
    the block off entirely unless the turn asks for it.
    """
    if not project_name or project_name == "unknown":
        return ""
    if not device_id:
        return ""
    if memory_mode() == "optin" and not requested:
        return ""

    memories = await db.get_project_memories(device_id, project_name)
    if not memories:
        return ""

    parts = []
    for mem in memories:
        date = mem["created_at"][:10]  # YYYY-MM-DD
        parts.append(f"[{date}] {mem['summary']}")

    memory_text = "\n\n".join(parts)

    header = (
        "## Заметки по файлу (справочно)\n"
        "Ниже — краткие заметки с прошлых сеансов работы по ЭТОМУ ФАЙЛУ. "
        "Это НЕ текущий разговор: пользователь их не писал и мог их не видеть.\n"
        "Пользуйся ими как справкой, когда они относятся к делу. НЕ начинай ответ "
        "с них, не продолжай прошлую задачу по своей инициативе и не ссылайся на "
        "них, пока пользователь сам не заговорит об этом.\n\n"
    )

    return header + memory_text


async def _maybe_compact_memories(
    db: Any,
    device_id: str,
    project_name: str,
    model: str,
    api_key: str = "",
    api_base: Optional[str] = None,
) -> None:
    """If project memories exceed MAX_MEMORY_TOKENS, compact them."""
    memories = await db.get_project_memories(device_id, project_name)
    if len(memories) < 5:
        return  # Not enough to bother compacting

    total_text = "\n".join(m["summary"] for m in memories)
    if _estimate_tokens(total_text) < MAX_MEMORY_TOKENS:
        return  # Still within budget

    logger.info(
        "Compacting project memories for '%s': %d entries, ~%d tokens",
        project_name, len(memories), _estimate_tokens(total_text),
    )

    total_messages = sum(m["message_count"] for m in memories)

    try:
        compact_prompt = [
            {
                "role": "system",
                "content": (
                    "Ты компактор памяти проекта Revit. "
                    "Объедини все заметки в одну сводку 10-20 предложений. Сохрани:\n"
                    "- Основные этапы работы над проектом\n"
                    "- Ключевые решения и изменения\n"
                    "- Повторяющиеся задачи и паттерны работы пользователя\n"
                    "- Известные проблемы модели\n"
                    "- Предпочтения пользователя\n"
                    "Расположи хронологически. Пиши на русском."
                ),
            },
            {
                "role": "user",
                "content": f"Объедини эти заметки о проекте:\n\n{total_text}",
            },
        ]

        # W3: route through unified fallback chain. Compaction failure used
        # to drop the consolidation silently and let memory grow without
        # bound (each session adds 200-500 chars; 100 sessions = 20-50K chars
        # in the system prompt). The chain catches transient Vertex 429s and
        # falls over to Google AI Studio + OpenRouter DeepSeek.
        try:
            compacted = (await run_with_fallback(
                messages=compact_prompt,
                label="project_memory.compact",
                max_tokens=2000,
                temperature=0.1,
                stream=False,
            )).strip()
        except FallbackChainExhausted as exc:
            logger.warning("Failed to compact project memories: %s", exc)
            return

        if compacted:
            await db.replace_project_memories(device_id, project_name, compacted, total_messages)
            logger.info(
                "Project memories compacted for '%s' (device=%s): %d entries → 1 (%d chars)",
                project_name, device_id[:8], len(memories), len(compacted),
            )

    except Exception as e:
        logger.warning("Failed to compact project memories: %s", e)
