"""Skill Builder mode — /шаблон conversational creation flow.

Lightweight per-WebSocket state. The actual conversation is driven by Gemini
using `prompts/skill_builder.md` as the system prompt. This module's
responsibilities are narrow:

  • Detect when the user enters /шаблон mode (and remember they're in it).
  • Detect /запись, /всё, /стоп, /отмена commands within the mode.
  • Inject the recording result (when frontend ships it) into the LLM context.
  • Provide the alternative system prompt path.
  • Track lifecycle so backend doesn't accidentally apply normal skill
    detection or QA detection while user is in builder mode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SKILL_BUILDER_PROMPT_FILE = Path(__file__).parent.parent.parent / "prompts" / "skill_builder.md"


class BuilderStage(str, Enum):
    """Coarse lifecycle marker. Gemini handles fine-grained dialog flow."""

    IDLE = "idle"            # not in builder mode
    DESCRIBING = "describing"  # user is describing the workflow in words
    RECORDING = "recording"    # /запись fired — Bridge is collecting events
    REVIEWING = "reviewing"    # /стоп was hit, KUKI is processing the capture
    TESTING = "testing"        # draft is saved, user is trying it in Revit
    NAMING = "naming"          # user said "ok", asking for /trigger name


# Slash commands that the builder cares about.
# Entry/exit accept inflections — real users type /шаблоны, /шаблон-новый etc.
# Recognised as long as the token STARTS WITH the canonical prefix.
ENTRY_COMMAND_PREFIXES = ("/шаблон", "/skill", "/template")
RECORD_START_COMMAND = "/запись"
RECORD_STOP_COMMANDS = ("/всё", "/все", "/стоп", "/stop")
CANCEL_COMMAND = "/отмена"
# Explicit "I'm done, drop me back to normal chat" — distinct from /отмена
# (which sounds destructive). Accepts the slash form AND the bare word.
EXIT_COMMAND_PREFIXES = ("/выход", "/exit", "/done", "/готово")

# Natural-language phrases that ALSO enter builder mode. Real users don't
# always remember to type the exact slash command — "хочу шаблон / сделай
# мне команду" is the same intent and must produce the same behavior.
# Order: longer phrases first so we match the most specific intent.
_NL_ENTRY_PHRASES = (
    "создай шаблон",
    "сделай шаблон",
    "хочу шаблон",
    "новый шаблон",
    "сохрани шаблон",
    "запиши шаблон",
    "сделай мне команду",
    "сделай команду",
    "хочу команду",
    "запиши команду",
    "автоматизируй это",
    "автоматизируй такое",
    "автоматизируй мне",
)


@dataclass
class SkillBuilderState:
    """Per-WebSocket-session state. Lives in memory only."""

    stage: BuilderStage = BuilderStage.IDLE
    description_so_far: str = ""
    last_recording_result: Optional[dict[str, Any]] = None
    draft_filename: Optional[str] = None
    proposed_metadata: dict[str, str] = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.stage != BuilderStage.IDLE

    def reset(self) -> None:
        self.stage = BuilderStage.IDLE
        self.description_so_far = ""
        self.last_recording_result = None
        self.draft_filename = None
        self.proposed_metadata = {}


def is_builder_entry(message: str) -> bool:
    """Did the user just trigger Skill Builder mode — by /шаблон* OR a
    recognised natural-language phrase ("сделай шаблон", "хочу команду", …)?

    Slash form: first token STARTS WITH /шаблон (catches /шаблоны, /шаблон-new).
    NL form: substring match anywhere in the message, lowercase.
    """
    if not message:
        return False
    lower = message.strip().lower()
    if not lower:
        return False
    first = _strip_first_token(message)
    if any(first.startswith(p) for p in ENTRY_COMMAND_PREFIXES):
        return True
    return any(phrase in lower for phrase in _NL_ENTRY_PHRASES)


def is_record_start(message: str) -> bool:
    return _strip_first_token(message) == RECORD_START_COMMAND


def is_record_stop(message: str) -> bool:
    return _strip_first_token(message) in RECORD_STOP_COMMANDS


def is_cancel(message: str) -> bool:
    return _strip_first_token(message) == CANCEL_COMMAND


def is_exit_builder(message: str) -> bool:
    """Explicit non-destructive exit: /выход, /exit, /done, /готово.

    Distinct from /отмена — exit means 'we're done here, back to normal chat',
    while /отмена means 'throw everything away'.
    """
    first = _strip_first_token(message)
    return any(first.startswith(p) for p in EXIT_COMMAND_PREFIXES)


def _strip_first_token(message: str) -> str:
    if not message:
        return ""
    return message.strip().split()[0].lower() if message.strip() else ""


def load_builder_system_prompt() -> str:
    """Load skill_builder.md. Cached aggressively in production via OS file cache."""
    if not _SKILL_BUILDER_PROMPT_FILE.exists():
        logger.warning("skill_builder.md not found at %s", _SKILL_BUILDER_PROMPT_FILE)
        return ""
    try:
        return _SKILL_BUILDER_PROMPT_FILE.read_text(encoding="utf-8")
    except Exception:
        logger.exception("Failed to load skill_builder.md")
        return ""


def format_recording_result_block(result: dict[str, Any]) -> str:
    """Format a Bridge recording_result for inclusion in the LLM turn.

    The Bridge ships compressed JSON (intent_summary[], pre_snapshot, raw_deltas).
    We unpack the high-level summary as a Markdown block — Gemini reads this
    naturally as part of the user message context, no special tool call needed.
    """
    if not result:
        return ""

    lines: list[str] = []
    lines.append("[RECORDING_RESULT]")
    lines.append("")

    summary = result.get("intent_summary") or []
    if isinstance(summary, list) and summary:
        lines.append("Что система зафиксировала:")
        for item in summary:
            lines.append(f"  {item}")
        lines.append("")

    duration = result.get("duration_seconds")
    if isinstance(duration, (int, float)):
        lines.append(f"Длительность записи: {duration:.1f} сек.")

    limits = result.get("limits") or {}
    if limits.get("hit_transaction_limit"):
        lines.append("⚠ Достигнут лимит 100 транзакций.")
    if limits.get("hit_time_limit"):
        lines.append("⚠ Достигнут лимит 30 минут.")
    if limits.get("worksharing_disabled"):
        lines.append("⚠ Документ workshared — запись была остановлена.")

    pre = result.get("pre_snapshot") or {}
    if pre.get("element_count"):
        cats = pre.get("categories_covered") or []
        cat_str = ", ".join(cats[:6]) if cats else ""
        lines.append(
            f"Предзамер до записи: {pre['element_count']} элементов "
            f"({cat_str}{'…' if len(cats) > 6 else ''})."
        )

    lines.append("")
    lines.append("[/RECORDING_RESULT]")
    return "\n".join(lines)


def derive_stage_from_message(
    state: SkillBuilderState, message: str, has_recording_result: bool
) -> BuilderStage:
    """Update state.stage based on incoming message.

    Returns the new stage (also writes it back to state).
    Pure-state transition — no I/O, no side effects beyond mutating state.
    """
    if is_cancel(message) or is_exit_builder(message):
        # /отмена and /выход both terminate the conversation cleanly. The
        # difference is semantic only (cancel = discard, exit = done) — the
        # state transition is identical: drop back to IDLE.
        state.reset()
        return state.stage

    if is_builder_entry(message):
        state.stage = BuilderStage.DESCRIBING
        state.description_so_far = ""
        return state.stage

    if not state.is_active():
        # Not in builder mode → caller should not invoke us
        return state.stage

    if is_record_start(message):
        state.stage = BuilderStage.RECORDING
        return state.stage

    if is_record_stop(message) or has_recording_result:
        state.stage = BuilderStage.REVIEWING
        return state.stage

    # Within DESCRIBING/REVIEWING/TESTING/NAMING — Gemini drives the conversation
    # and will tell us via tool calls when to advance. For V1 we don't try to
    # mind-read which sub-stage we're in; the shared prompt handles it.
    return state.stage


def should_inject_builder_prompt(state: SkillBuilderState) -> bool:
    """Should the system prompt be replaced with skill_builder.md this turn?"""
    return state.is_active()
