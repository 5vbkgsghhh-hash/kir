"""User-defined Skills — personal command templates created via /шаблон.

Unlike the built-in skills (print_export, model_audit, ...) which live as
.md files in `data/skills/` and activate by NL trigger detection, user
skills live on the user's local filesystem (`Documents\\KUKI\\Skills\\`)
and are loaded by the C# Bridge. The frontend reads them via Bridge and
ships full content in the chat WS payload as `skill_content`.

This module is responsible for:
  1. Parsing the `// @KUKI-SKILL` header block (Python mirror of the C# parser).
  2. Extracting skill payload from incoming WebSocket data.
  3. Formatting the skill content as a prompt section that Gemini reads
     as REFERENCE material — not as a script to execute verbatim.

Backend NEVER writes user-skill files. All persistence happens through
the Bridge (where the user's filesystem actually lives).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Header markers (must mirror SkillMetadataParser in C#).
_START_META_RE = re.compile(r"^\s*//\s*@KUKI-SKILL(\s+v\d+)?\s*$")
_END_META_RE = re.compile(r"^\s*//\s*@END-META\s*$")
_HEADER_LINE_RE = re.compile(
    r"^\s*//\s*@(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*?)\s*$"
)


@dataclass
class UserSkillMetadata:
    """Parsed @KUKI-SKILL header. Mirrors C# SkillMetadata POCO."""

    name: str = ""
    category: str = ""
    trigger: str = ""
    params_raw: str = ""
    destructive: bool = False
    description: str = ""
    created: str = ""
    updated: str = ""
    author: str = ""
    tested_on: str = ""
    extras: dict[str, str] = field(default_factory=dict)


def parse_skill_header(content: str) -> Optional[UserSkillMetadata]:
    """Parse the @KUKI-SKILL header block.

    Returns None on malformed input — callers should treat that as
    "this is not a valid skill file" and decline to inject anything.
    """
    if not content:
        return None

    meta = UserSkillMetadata()
    inside = False
    found_end = False

    for line in content.splitlines():
        if not inside:
            if _START_META_RE.match(line):
                inside = True
                continue
            if not line.strip():
                continue
            # Hit non-blank, non-marker line before @KUKI-SKILL → invalid file.
            return None

        if _END_META_RE.match(line):
            found_end = True
            break

        m = _HEADER_LINE_RE.match(line)
        if not m:
            continue

        key = m.group("key").lower()
        value = m.group("value")

        if key == "name":
            meta.name = value
        elif key == "category":
            meta.category = value
        elif key == "trigger":
            meta.trigger = value
        elif key == "params":
            meta.params_raw = value
        elif key == "destructive":
            meta.destructive = value.strip().lower() == "true"
        elif key == "description":
            meta.description = value
        elif key == "created":
            meta.created = value
        elif key == "updated":
            meta.updated = value
        elif key == "author":
            meta.author = value
        elif key == "tested_on":
            meta.tested_on = value
        else:
            meta.extras[key] = value

    if not (inside and found_end):
        return None
    if not meta.trigger or not meta.name:
        return None
    return meta


def extract_user_skill_payload(data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Pull skill_content + skill_trigger from a chat WS payload.

    Returns a dict with 'content', 'trigger', 'metadata' or None if not
    present. Validates the header — invalid content is rejected silently
    and we fall through to the regular chat path (better UX than erroring).
    """
    content = data.get("skill_content")
    trigger = data.get("skill_trigger", "")

    if not content or not isinstance(content, str):
        return None

    metadata = parse_skill_header(content)
    if metadata is None:
        logger.warning(
            "User skill payload received but header invalid; trigger=%r, len=%d",
            trigger,
            len(content),
        )
        return None

    # Defensive: if frontend trigger disagrees with file's @trigger, log it.
    # We trust the file's metadata (single source of truth).
    if trigger and trigger != metadata.trigger:
        logger.info(
            "User skill trigger mismatch: WS=%r vs header=%r — using header",
            trigger,
            metadata.trigger,
        )

    return {
        "content": content,
        "trigger": metadata.trigger,
        "metadata": metadata,
    }


def build_user_skill_prompt(
    skill_content: str,
    metadata: UserSkillMetadata,
    *,
    current_revit_version: Optional[str] = None,
) -> str:
    """Format the skill as a prompt section that Gemini reads as REFERENCE.

    The wrapping is critical — Gemini must understand:
      1. This code WORKED for the user (don't second-guess the approach).
      2. Adapt to current project context (no blind copy-paste of element IDs).
      3. If skill was tested on a different Revit version, translate the API.
    """
    sections: list[str] = []

    sections.append("=" * 60)
    sections.append("ACTIVE USER SKILL — reference template provided by the user")
    sections.append("=" * 60)
    sections.append("")
    sections.append(f"Skill name:    {metadata.name}")
    sections.append(f"Trigger:       {metadata.trigger}")
    sections.append(f"Category:      {metadata.category}")
    if metadata.description:
        sections.append(f"Description:   {metadata.description}")
    if metadata.params_raw:
        sections.append(f"Parameters:    {metadata.params_raw}")
    if metadata.tested_on:
        sections.append(f"Tested on:     {metadata.tested_on}")

    if current_revit_version and metadata.tested_on \
            and metadata.tested_on.lower().strip() != current_revit_version.lower().strip():
        sections.append("")
        sections.append(
            f"⚠ VERSION ADAPTATION NEEDED: This skill was authored for "
            f"{metadata.tested_on}, but the user's current project is on "
            f"{current_revit_version}. Adapt the API calls (ElementId.Value vs "
            f"IntegerValue, ForgeTypeId vs DisplayUnitType, etc.) accordingly."
        )

    if metadata.destructive:
        sections.append("")
        sections.append(
            "⚠ DESTRUCTIVE: This skill deletes or overwrites elements. "
            "Confirm with the user (in plain Russian) before invoking the bridge."
        )

    sections.append("")
    sections.append("INSTRUCTIONS FOR USING THIS SKILL:")
    sections.append(
        "  • This is a WORKING reference, not a literal script. The user has "
        "verified that this code produced the desired result in their environment."
    )
    sections.append(
        "  • Adapt element IDs, view names, and FamilyType references to the "
        "currently open document — never copy hardcoded IDs from the reference."
    )
    sections.append(
        "  • If the user supplied parameter overrides on the command line "
        "(e.g. /trigger height=3500), use those values instead of the defaults."
    )
    sections.append(
        "  • Preserve the user's structural choices (transaction names, error "
        "handling style, parameter names) — do not refactor unless asked."
    )
    sections.append(
        "  • If the user describes a problem with this skill (\"шкала не та\", "
        "\"имя не правильное\"), apply minimal targeted fixes to this specific "
        "behavior, leaving everything else intact."
    )
    sections.append("")
    # Defang triple-backticks inside the skill body so a malicious file
    # cannot escape the code fence and inject prompt instructions in the
    # outer system prompt context.
    safe_code = skill_content.replace("```", "``​`")  # zero-width-space splitter
    sections.append("REFERENCE CODE:")
    sections.append("```csharp")
    sections.append(safe_code)
    sections.append("```")
    sections.append("=" * 60)

    return "\n".join(sections)


def is_user_skill_message(message: str) -> bool:
    """Quick check: does the message look like a user-skill invocation?

    Used as an early gate — but the authoritative answer comes from
    `extract_user_skill_payload(data)` which looks for skill_content.
    A message can start with `/` and not be a user skill (e.g. `/расценка`).
    """
    if not message:
        return False
    s = message.strip()
    if not s.startswith("/"):
        return False
    # Reject if it's a known built-in skill trigger.
    first_token = s.split()[0] if s else ""
    builtin_aliases = {
        "/расценка", "/расценить", "/price", "/аудит",
    }
    return first_token not in builtin_aliases
