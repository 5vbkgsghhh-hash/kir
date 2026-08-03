"""Shortcuts — handle trivial requests without calling the LLM.

Three categories:
1. Greetings: привет, hello -> welcome message + hints
2. Quick counts: сколько стен -> context category count
3. Help: что ты умеешь -> capabilities list
"""

from __future__ import annotations

import re
import logging
from typing import Any, Optional

from kukai.categories import resolve_category as _resolve_category

logger = logging.getLogger(__name__)


# --- Pattern matchers ---

_GREETING_PATTERNS = [
    r"^привет\b", r"^здравствуй", r"^добрый\s+(день|вечер|утро)",
    r"^доброе\s+утро", r"^hello\b", r"^hi\b", r"^hey\b",
    r"^good\s+(morning|afternoon|evening)",
    r"^хай\b", r"^салют\b", r"^приветствую",
]

_HELP_PATTERNS = [
    r"что (ты )?(умеешь|можешь|знаешь)",
    r"помо(щь|ги)\b", r"^help\b", r"как пользоваться",
    r"что (ты )?делаешь", r"какие (у тебя )?возможности",
    r"what can you do", r"capabilities", r"функции\b",
    r"какие команды", r"инструкция\b",
]

_COUNT_PATTERN = re.compile(
    r"сколько\s+(стен|дверей|окон|перекрытий|потолков|крыш|лестниц|помещений|комнат|"
    r"колонн|балок|труб|воздуховодов|уровней|видов|осей|листов|мебели|светильников|"
    r"walls|doors|windows|floors|rooms|columns|pipes|ducts|levels)",
    re.IGNORECASE,
)

# Category resolution delegated to kukai.categories (single source of truth)

_GREETING_RESPONSE = (
    "Привет! Я KUKI — AI-ассистент для Autodesk Revit. Вот что я умею:\n\n"
    "- **Анализ модели** — найти элементы, посчитать, проверить параметры\n"
    "- **Изменения** — поменять параметры, переименовать, скрыть/изолировать\n"
    "- **Отчёты** — выгрузить данные в Excel\n"
    "- **Проверка качества** — найти дубликаты, ошибки, предупреждения\n\n"
    "Просто напишите, что нужно сделать с моделью."
)

_HELP_RESPONSE = (
    "## Возможности KUKI\n\n"
    "### Чтение модели\n"
    "- Найти элементы по категории, типу, параметрам\n"
    "- Посчитать элементы («сколько стен»)\n"
    "- Показать параметры элемента\n"
    "- Проанализировать предупреждения\n\n"
    "### Изменение модели\n"
    "- Изменить параметры элементов\n"
    "- Переименовать элементы\n"
    "- Скрыть/изолировать в виде\n"
    "- Создать спецификацию\n\n"
    "### Экспорт\n"
    "- Выгрузить данные в Excel\n"
    "- Сформировать отчёт\n\n"
    "### Проверка качества\n"
    "- Найти дубликаты\n"
    "- Проверить именование\n"
    "- Найти помещения без имён\n\n"
    "**Примеры запросов:**\n"
    "- «покажи все наружные стены»\n"
    "- «сколько дверей в проекте»\n"
    "- «поменяй марку у выделенных стен на НС-400»\n"
    "- «выгрузи список помещений в Excel»\n"
)


_ACTION_KEYWORDS = [
    "покажи", "найди", "посчитай", "поменяй", "измени", "установи", "выдели",
    "подсвети", "создай", "удали", "скрой", "изолируй", "переименуй",
    "выгрузи", "экспорт", "сколько", "проверь", "сохрани", "загрузи",
    "show", "find", "count", "change", "set", "select", "highlight",
    "create", "delete", "hide", "isolate", "rename", "export", "check",
    "how many", "list", "get", "save",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    """Check if text matches any regex pattern."""
    text_lower = text.lower().strip()
    for pattern in patterns:
        if re.search(pattern, text_lower):
            return True
    return False


def _has_action_keyword(text: str) -> bool:
    """Check if text contains an action keyword indicating a real request."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _ACTION_KEYWORDS)


def try_shortcut(
    message: str,
    context: Any = None,
) -> Optional[list[dict[str, Any]]]:
    """Try to handle message as a shortcut. Returns list of stream events or None.

    Returns events in the same format as StreamEvent.to_dict():
    [{"type": "stream_start"}, {"type": "stream_chunk", "text": "..."}, {"type": "stream_end"}]
    """
    if not message or not message.strip():
        return None

    text = message.strip()
    words = text.split()

    # 1. Greetings — only if short and no action keywords in the rest
    if _matches_any(text, _GREETING_PATTERNS):
        # If greeting + action request (e.g. "привет покажи стены"), skip shortcut
        if len(words) > 1 and _has_action_keyword(text):
            pass  # Fall through to LLM
        else:
            return _make_text_events(_GREETING_RESPONSE)

    # 2. Help — only if short and no action keywords
    if len(words) <= 6 and not _has_action_keyword(text) and _matches_any(text, _HELP_PATTERNS):
        return _make_text_events(_HELP_RESPONSE)

    # 3. Quick counts — only for SIMPLE count queries without extra conditions
    # "Сколько стен?" -> shortcut, "Сколько стен без имени?" -> LLM (has filter)
    count_match = _COUNT_PATTERN.search(text)
    if count_match and context:
        # Check if message has additional filtering beyond "сколько X"
        # If text after the match contains filtering words, skip shortcut -> LLM handles
        after_match = text[count_match.end():].strip().rstrip("?!.")
        _FILTER_INDICATORS = [
            "без", "с ", "на ", "длиннее", "короче", "больше", "меньше", "выше",
            "ниже", "типа", "тип ", "где", "которые", "у которых", "имеющ",
            "without", "with", "on ", "longer", "shorter", "where", "type",
            # Compound query indicators — user wants more than just a count
            "какие", "какой", "каких",
            "и какие", "и покажи", "и выведи", "и их",
            "типоразмер", "типоразмеры",
            "параметр", "параметры",
            "характеристик", "свойств",
        ]
        has_filter = any(ind in after_match.lower() for ind in _FILTER_INDICATORS) if after_match else False

        # If there is substantial text after the count match, user likely wants more than a count
        if after_match and sum(1 for c in after_match if not c.isspace()) > 10:
            has_filter = True

        if not has_filter:
            word = count_match.group(1).lower()
            builtin = _resolve_category(word)
            if builtin and hasattr(context, "categories"):
                for cat in context.categories:
                    if cat.builtin == builtin:
                        response = f"В проекте **{cat.count}** элементов категории «{cat.name_ru}» ({cat.name})."
                        return _make_text_events(response)

    # 4. Selection info
    _SELECTION_PATTERNS = [
        r"что выделено", r"выделенн", r"выбранн",
        r"текущ\w+ выделени", r"текущ\w+ выбор",
        r"what.*select", r"show.*select", r"current selection",
        r"selected elements",
    ]
    if context and hasattr(context, "selection") and context.selection:
        sel = context.selection
        if sel.count > 0 and _matches_any(text, _SELECTION_PATTERNS):
            parts = [f"Выделено **{sel.count}** элементов."]
            if hasattr(sel, "categories") and sel.categories:
                cats = ", ".join(sel.categories[:5])
                parts.append(f"Категории: {cats}")
            if hasattr(sel, "element_ids") and sel.element_ids:
                ids_preview = ", ".join(str(i) for i in sel.element_ids[:10])
                if sel.count > 10:
                    ids_preview += f"... (и ещё {sel.count - 10})"
                parts.append(f"ID: {ids_preview}")
            return _make_text_events("\n".join(parts))

    return None


def _make_text_events(text: str) -> list[dict[str, Any]]:
    """Create stream events for a text response."""
    return [
        {"type": "stream_start"},
        {"type": "stream_chunk", "text": text},
        {"type": "stream_end"},
    ]
