"""Lightweight extension metadata/profile reader.

This replaces the accidental dependency on ``RevitApiIndex.ensure_loaded``:
listing one extension must not load a 16 MB API DB or a 59 MB embedding index.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .release import current_release
from .text import normalized_tokens

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtensionEntry:
    entry_id: str
    entry_type: str
    name_ru: str
    description_ru: str
    content_ru: str
    keywords_ru: tuple[str, ...]
    keywords_en: tuple[str, ...]
    regulatory_ref: str
    formula: str
    common_mistakes: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionRecord:
    extension_id: str
    name_ru: str
    name_en: str
    icon: str
    profile_ru: str
    entries: tuple[ExtensionEntry, ...]

    def listing(self) -> dict[str, str]:
        return {
            "id": self.extension_id,
            "name_ru": self.name_ru,
            "name_en": self.name_en,
            "icon": self.icon,
        }


@lru_cache(maxsize=1)
def _catalog() -> dict[str, ExtensionRecord]:
    out: dict[str, ExtensionRecord] = {}
    root = current_release().extensions_root
    for path in sorted(root.glob("ext-*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            extension_id = str(raw.get("id") or "").strip()
            if not extension_id or extension_id in out:
                raise ValueError("missing or duplicate extension id")
            out[extension_id] = ExtensionRecord(
                extension_id=extension_id,
                name_ru=str(raw.get("name_ru") or extension_id),
                name_en=str(raw.get("name_en") or extension_id),
                icon=str(raw.get("icon") or "box"),
                profile_ru=str(raw.get("profile_ru") or ""),
                entries=tuple(_parse_entry(item, path) for item in raw.get("entries") or []),
            )
        except Exception as exc:
            logger.error("Invalid extension asset %s: %s", path, exc)
            raise
    return out


def _parse_entry(raw: Any, path: Path) -> ExtensionEntry:
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: extension entry must be an object")
    mistakes = raw.get("common_mistakes") or []
    if isinstance(mistakes, str):
        mistakes = [mistakes]
    return ExtensionEntry(
        entry_id=str(raw.get("id") or ""),
        entry_type=str(raw.get("type") or ""),
        name_ru=str(raw.get("name_ru") or ""),
        description_ru=str(raw.get("description_ru") or ""),
        content_ru=str(raw.get("content_ru") or ""),
        keywords_ru=tuple(str(value) for value in raw.get("keywords_ru") or []),
        keywords_en=tuple(str(value) for value in raw.get("keywords_en") or []),
        regulatory_ref=str(raw.get("regulatory_ref") or ""),
        formula=str(raw.get("formula") or ""),
        common_mistakes=tuple(str(value) for value in mistakes),
    )


def _entry_score(entry: ExtensionEntry, query_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    keyword_phrases = entry.keywords_ru + entry.keywords_en
    keyword_tokens = set().union(*(
        normalized_tokens(value) for value in keyword_phrases
    )) if keyword_phrases else set()
    title_tokens = normalized_tokens(entry.name_ru)
    body_tokens = normalized_tokens(
        f"{entry.description_ru} {entry.content_ru} {entry.regulatory_ref}"
    )
    score = (
        6.0 * len(query_tokens & keyword_tokens)
        + 3.0 * len(query_tokens & title_tokens)
        + 0.6 * len(query_tokens & body_tokens)
    )
    for phrase in keyword_phrases:
        phrase_tokens = normalized_tokens(phrase)
        if len(phrase_tokens) >= 2 and phrase_tokens.issubset(query_tokens):
            score += 8.0
    return score


def search_extension_entries(
    extension_id: str,
    query: str,
    *,
    limit: int = 3,
) -> list[ExtensionEntry]:
    """Route within one active extension without embeddings or model calls."""
    if limit <= 0:
        return []
    record = _catalog().get((extension_id or "").strip())
    if record is None:
        return []
    query_tokens = normalized_tokens(query)
    ranked = [
        (score, -index, entry)
        for index, entry in enumerate(record.entries)
        if (score := _entry_score(entry, query_tokens)) > 0
    ]
    ranked.sort(key=lambda row: (-row[0], -row[1], row[2].entry_id))
    return [entry for _score, _index, entry in ranked[:limit]]


def get_extension_context(
    extension_id: str,
    query: str,
    *,
    limit: int = 3,
    max_chars: int = 4500,
) -> str:
    """Render bounded, query-relevant entries from the versioned release.

    Regulatory references are presented as curated guidance, not as verified
    clause quotations; exact normative claims must still use ``lookup_norm``.
    """
    if max_chars < 200:
        return ""
    entries = search_extension_entries(extension_id, query, limit=limit)
    if not entries:
        return ""
    parts = [
        "## Специализированные материалы активного расширения",
        "Версионированные памятки KUKAI. Для точной цитаты пункта СП/ГОСТ "
        "используй `lookup_norm`; не выдавай памятку за дословный текст нормы.",
    ]
    for entry in entries:
        block = [f"### {entry.name_ru}  ·  `{entry.entry_id}`"]
        if entry.description_ru:
            block.append(entry.description_ru)
        if entry.content_ru:
            block.append(entry.content_ru)
        if entry.formula:
            block.append(f"Формула: {entry.formula}")
        if entry.regulatory_ref:
            block.append(f"Ориентир: {entry.regulatory_ref}")
        if entry.common_mistakes:
            block.append("Частые ошибки: " + "; ".join(entry.common_mistakes[:3]))
        rendered = "\n".join(block)
        candidate = "\n\n".join(parts + [rendered])
        if len(candidate) > max_chars:
            break
        parts.append(rendered)
    return "\n\n".join(parts) if len(parts) > 2 else ""


def get_extension_profile(extension_id: str) -> str:
    record = _catalog().get((extension_id or "").strip())
    return record.profile_ru if record else ""


def get_extensions_list() -> list[dict[str, str]]:
    return [record.listing() for record in _catalog().values()]


def reset_extension_cache() -> None:
    _catalog.cache_clear()
