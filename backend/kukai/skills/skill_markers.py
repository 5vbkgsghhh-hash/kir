"""Marker-based skill side-effect protocol — alternative to LLM tool calls.

Why markers, not tools:
  Gemini already orchestrates many tools (execute_revit_code, search_norms,
  schedule_*, ifc_*, etc.). Adding more dilutes the tool routing accuracy.
  Markers ride on the regular chat stream — Gemini just emits them as part
  of its reply, no schema, no decision overhead.

Protocol:
  Gemini emits, at the END of a normal chat reply, a fenced marker block:

    [[KUKI_SKILL_DRAFT_SAVE]]
    name: <draft_name>
    code: |
      // @KUKI-SKILL v1
      // ... full skill code ...
    [[/KUKI_SKILL_DRAFT_SAVE]]

  Or:

    [[KUKI_SKILL_PROMOTE]]
    draft: <draft_name>
    trigger: /маркировка
    category: АР
    [[/KUKI_SKILL_PROMOTE]]

  Or update existing:

    [[KUKI_SKILL_UPDATE]]
    trigger: /маркировка
    code: |
      ...
    [[/KUKI_SKILL_UPDATE]]

  Or delete:

    [[KUKI_SKILL_DELETE]]
    trigger: /маркировка
    [[/KUKI_SKILL_DELETE]]

  Backend extracts blocks, executes side-effects via Bridge WS messages,
  strips blocks from user-visible chat. Frontend has its own (looser) regex
  strip in case anything leaks through.

This module is pure parsing — no I/O, no Bridge calls. Caller wires the
parsed actions to Bridge dispatch.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class MarkerKind(str, Enum):
    DRAFT_SAVE = "DRAFT_SAVE"        # save a transient .draft\<name>.cs
    PROMOTE = "PROMOTE"              # rename draft → permanent /trigger
    UPDATE = "UPDATE"                # overwrite an existing /trigger
    DELETE = "DELETE"                # remove /trigger from disk
    CANCEL_DRAFT = "CANCEL_DRAFT"    # discard draft (user said /отмена)


# Markers that signal "we're done with this skill" — emitting any of them
# means builder mode should exit back to IDLE. DRAFT_SAVE is NOT finalising
# (user is still testing); the others all terminate the conversation.
FINALISING_KINDS: frozenset[MarkerKind] = frozenset({
    MarkerKind.PROMOTE,
    MarkerKind.UPDATE,
    MarkerKind.DELETE,
    MarkerKind.CANCEL_DRAFT,
})


# Match a complete [[KUKI_SKILL_XXX]] ... [[/KUKI_SKILL_XXX]] block, including
# multi-line bodies. (?s) makes . match newlines. The kind is captured for
# dispatch, the body is captured for parsing.
_MARKER_BLOCK_RE = re.compile(
    r"\[\[KUKI_SKILL_(?P<kind>[A-Z_]+)\]\]"
    r"(?P<body>.*?)"
    r"\[\[/KUKI_SKILL_(?P=kind)\]\]",
    re.DOTALL,
)

# Within a body, key: value pairs (single line) and `code: |` block scalar.
_KEY_VAL_RE = re.compile(r"^\s*(?P<key>[a-z_]+)\s*:\s*(?P<value>.*?)\s*$", re.MULTILINE)


@dataclass
class SkillMarker:
    """One parsed marker block from Gemini's reply."""

    kind: MarkerKind
    fields: dict[str, str] = field(default_factory=dict)
    code: str = ""
    raw_match: str = ""  # exact substring to strip from output

    def get(self, key: str, default: str = "") -> str:
        return self.fields.get(key, default)


def extract_markers(text: str) -> tuple[list[SkillMarker], str]:
    """Find every marker block, return (markers, text_with_markers_removed).

    Order of returned markers is the order they appeared in the text.
    Text without markers is returned unchanged.

    Robustness:
      • Unrecognised kinds (e.g. typo) are dropped silently — they get
        stripped from the displayed text but no action is taken.
      • Malformed body (missing required field for that kind) is logged
        and skipped — caller should not crash on bad input.
    """
    if not text or "KUKI_SKILL_" not in text:
        return [], text

    markers: list[SkillMarker] = []
    cleaned_parts: list[str] = []
    cursor = 0

    for m in _MARKER_BLOCK_RE.finditer(text):
        # Append everything up to this marker, then drop the marker itself.
        cleaned_parts.append(text[cursor:m.start()])
        cursor = m.end()

        raw_kind = m.group("kind")
        body = m.group("body") or ""

        try:
            kind = MarkerKind(raw_kind)
        except ValueError:
            logger.warning("Unknown skill marker kind: %s", raw_kind)
            continue

        marker = SkillMarker(kind=kind, raw_match=m.group(0))

        # Extract `code: |` block scalar first, then strip it from body
        # so plain key:value parsing doesn't accidentally consume code lines.
        code_text, body_minus_code = _extract_code_block(body)
        if code_text:
            marker.code = code_text

        # Plain key: value pairs
        for kv in _KEY_VAL_RE.finditer(body_minus_code):
            key = kv.group("key").strip()
            value = kv.group("value").strip()
            if key and key != "code":
                marker.fields[key] = value

        markers.append(marker)

    cleaned_parts.append(text[cursor:])
    cleaned = "".join(cleaned_parts)
    # Collapse runs of blank lines that result from marker removal so the
    # user-visible chat doesn't have weird gaps.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).rstrip() + "\n" if cleaned.strip() else ""

    return markers, cleaned


def _extract_code_block(body: str) -> tuple[str, str]:
    """Pull a `code: |` block out of the body, return (code, body_without_code).

    The block is delimited by:
      code: |
        <indented lines>
      <next key: value at original indentation, OR end of body>

    Indentation is the convention but we accept lazy formats too — Gemini
    will sometimes drop the |, sometimes mis-indent. Be lenient about it
    while still extracting cleanly.
    """
    # Look for `code:` followed by either `|` or empty, then code content.
    m = re.search(r"^[ \t]*code\s*:\s*\|?\s*\n", body, re.MULTILINE)
    if not m:
        # Try inline form: "code: <one-liner>"
        m_inline = re.search(r"^[ \t]*code\s*:\s*(?P<v>\S.*?)$", body, re.MULTILINE)
        if m_inline:
            return m_inline.group("v"), body.replace(m_inline.group(0), "", 1)
        return "", body

    after = body[m.end():]

    # The code block runs until either:
    #   a) end of body
    #   b) a line at column 0 that looks like another `key: value` header
    next_key = re.search(
        r"^[ \t]*(name|trigger|category|draft)\s*:",
        after,
        re.MULTILINE,
    )
    if next_key:
        code_chunk = after[:next_key.start()]
        rest = after[next_key.start():]
    else:
        code_chunk = after
        rest = ""

    # Dedent: strip the common leading whitespace from non-empty lines.
    lines = code_chunk.split("\n")
    non_empty = [ln for ln in lines if ln.strip()]
    if non_empty:
        common_indent = min(
            (len(ln) - len(ln.lstrip(" \t")) for ln in non_empty),
            default=0,
        )
        if common_indent:
            lines = [ln[common_indent:] if len(ln) >= common_indent else ln for ln in lines]
    code = "\n".join(lines).strip()

    body_without_code = body[:m.start()] + rest
    return code, body_without_code


def validate_marker(marker: SkillMarker) -> Optional[str]:
    """Return None if marker is well-formed, else a human-readable error."""
    if marker.kind in (MarkerKind.DRAFT_SAVE,):
        if not marker.get("name"):
            return "DRAFT_SAVE: missing 'name'"
        if not marker.code:
            return "DRAFT_SAVE: missing 'code' block"
    elif marker.kind == MarkerKind.PROMOTE:
        if not marker.get("draft"):
            return "PROMOTE: missing 'draft'"
        if not marker.get("trigger"):
            return "PROMOTE: missing 'trigger'"
        if not marker.get("category"):
            return "PROMOTE: missing 'category'"
    elif marker.kind == MarkerKind.UPDATE:
        if not marker.get("trigger"):
            return "UPDATE: missing 'trigger'"
        if not marker.code:
            return "UPDATE: missing 'code' block"
    elif marker.kind == MarkerKind.DELETE:
        if not marker.get("trigger"):
            return "DELETE: missing 'trigger'"
    elif marker.kind == MarkerKind.CANCEL_DRAFT:
        if not marker.get("name"):
            return "CANCEL_DRAFT: missing 'name'"
    return None
