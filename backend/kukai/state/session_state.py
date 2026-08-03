"""Session state tracking — working sets, follow-up detection, goal tracking.

Tracks the current working set of elements, resolved entities,
session artifacts, and user goals across a conversation session.
Provides context enrichment for the LLM system prompt.
"""

from __future__ import annotations

import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

# --- Follow-up detection constants ---

FOLLOW_UP_PREFIXES_RU = [
    "теперь", "дальше", "далее", "затем", "потом",
    "после этого", "а ещё", "и ещё", "также",
]
FOLLOW_UP_PREFIXES_EN = [
    "now", "then", "next", "after that", "also",
    "and also", "furthermore",
]
FOLLOW_UP_TOKENS = [
    "это", "их", "эти", "тех", "те же",
    "them", "these", "those", "same", "it",
]
QUESTION_TOKENS = [
    "что", "как", "почему", "зачем", "когда", "сколько",
    "what", "how", "why", "when",
]

# --- Hint tables (bilingual) ---

ACTION_HINTS: dict[str, list[str]] = {
    "export": ["экспорт", "выгрузи", "export", "save to", "сохрани в файл"],
    "write": ["поменяй", "измени", "установи", "set", "change", "modify", "update", "rename"],
    "select": ["выдели", "выбери", "select", "highlight", "подсвети"],
    "read": ["покажи", "найди", "посчитай", "show", "find", "count", "list", "get"],
}

CATEGORY_HINTS: dict[str, list[str]] = {
    "walls": ["стена", "стены", "стен", "стенам", "стенами", "стенах", "стенку", "walls", "wall"],
    "floors": ["перекрытие", "перекрытия", "перекрытий", "перекрытиям", "пол", "полы", "полов", "плита", "плиты", "floors", "floor", "slab"],
    "columns": ["колонна", "колонны", "колонн", "колоннам", "колоннами", "столб", "столбы", "columns", "column"],
    "beams": ["балка", "балки", "балок", "балкам", "балками", "ригель", "ригели", "ригелей", "beams", "beam"],
    "rooms": ["помещение", "помещения", "помещений", "помещениям", "комната", "комнаты", "комнат", "rooms", "room", "space"],
    "doors": ["дверь", "двери", "дверей", "дверям", "дверями", "doors", "door"],
    "windows": ["окно", "окна", "окон", "окнам", "окнами", "оконный", "windows", "window"],
    "levels": ["уровень", "уровни", "уровней", "уровням", "этаж", "этажи", "этажей", "levels", "level"],
    "views": ["вид", "виды", "видов", "видам", "план", "разрез", "фасад", "views", "view"],
    "grids": ["ось", "оси", "осей", "осям", "сетка", "сетки", "grids", "grid"],
    "pipes": ["труба", "трубы", "труб", "трубам", "трубами", "трубопровод", "pipes", "pipe"],
    "ducts": ["воздуховод", "воздуховоды", "воздуховодов", "воздуховодам", "вентканал", "ducts", "duct"],
    "ceilings": ["потолок", "потолки", "потолков", "потолкам", "потолками", "ceilings", "ceiling"],
    "roofs": ["крыша", "крыши", "крыш", "крышам", "кровля", "кровли", "roofs", "roof"],
    "stairs": ["лестница", "лестницы", "лестниц", "лестницам", "ступень", "ступени", "stairs", "stair"],
    "furniture": ["мебель", "мебели", "мебелью", "стол", "столы", "стул", "стулья", "furniture"],
    "railings": ["ограждение", "ограждения", "ограждений", "перила", "перил", "railings", "railing"],
}

FILTER_HINTS: dict[str, list[str]] = {
    "external": ["наружн", "внешн", "exterior", "external"],
    "internal": ["внутрен", "interior", "internal"],
    "current_level": ["текущ", "этот уровень", "current level", "this level"],
    "active_view": ["текущий вид", "active view", "this view"],
    "selected": ["выделенн", "выбранн", "selected"],
}


def is_likely_follow_up(message: str) -> bool:
    """Detect if a message is likely a follow-up to a previous request.

    Criteria (need 2+ to be True):
    - Starts with a follow-up prefix (first 3 words)
    - Contains a follow-up token in first 3 words
    - NOT a question (doesn't start with a question token)
    - Short message (<=18 tokens)
    """
    if not message or not message.strip():
        return False

    words = message.lower().split()
    if not words:
        return False

    first_words = " ".join(words[:3])
    signals = 0

    # Check follow-up prefixes
    for prefix in FOLLOW_UP_PREFIXES_RU + FOLLOW_UP_PREFIXES_EN:
        if first_words.startswith(prefix.lower()):
            signals += 1
            break

    # Check follow-up tokens in first 3 words
    for token in FOLLOW_UP_TOKENS:
        if token.lower() in first_words:
            signals += 1
            break

    # NOT a question (bonus signal)
    is_question = any(words[0].startswith(q.lower()) for q in QUESTION_TOKENS)
    if not is_question:
        signals += 1

    # Short message
    if len(words) <= 18:
        signals += 1

    return signals >= 3


def _detect_action(message: str) -> Optional[str]:
    """Detect action hint from message."""
    lower = message.lower()
    for action, keywords in ACTION_HINTS.items():
        for kw in keywords:
            if kw.lower() in lower:
                return action
    return None


# Lemma-keyed view of CATEGORY_HINTS (flag KUKAI_LEMMA_LEXICON, IQ-moment #7).
# Derived from the surface table at first use — never hand-written. Only
# consulted as a FALLBACK after the legacy substring scan misses, so flag ON
# is a strict superset of flag OFF (and flag OFF never builds it).
_LEMMA_HINT_INDEX: Optional[dict[str, str]] = None


def _lemma_hint_index() -> dict[str, str]:
    global _LEMMA_HINT_INDEX
    idx = _LEMMA_HINT_INDEX
    if idx is None:
        from kukai.nlp.lemma import lemma_phrase

        idx = {}
        for category, keywords in CATEGORY_HINTS.items():
            for kw in keywords:
                idx.setdefault(lemma_phrase(kw), category)
        _LEMMA_HINT_INDEX = idx
    return idx


def _detect_category(message: str) -> Optional[str]:
    """Detect category hint from message."""
    lower = message.lower()
    for category, keywords in CATEGORY_HINTS.items():
        for kw in keywords:
            if kw.lower() in lower:
                return category
    # Lemma fallback (flag-gated): closes the declension holes the enumerated
    # hint lists miss («в окне», «дверьми»). Never raises — a broken
    # morphology import degrades to the legacy miss (None).
    try:
        from kukai.nlp.lemma import lemma, lemma_lexicon_enabled

        if lemma_lexicon_enabled():
            idx = _lemma_hint_index()
            for word in lower.split():
                word = word.strip(".,!?;:\"'()[]{}«»")
                if len(word) >= 2:
                    category = idx.get(lemma(word))
                    if category:
                        return category
    except Exception:  # noqa: BLE001 — best-effort fallback only
        pass
    return None


def _detect_filters(message: str) -> list[str]:
    """Detect filter hints from message."""
    lower = message.lower()
    filters = []
    for filter_name, keywords in FILTER_HINTS.items():
        for kw in keywords:
            if kw.lower() in lower:
                filters.append(filter_name)
                break
    return filters


# --- Data classes ---

@dataclass
class WorkingSet:
    """Current working set of Revit elements."""
    label: str = ""
    source: str = ""  # "tool_result", "user_selection", "category_query"
    category: Optional[str] = None
    count: int = 0
    element_ids: list[int] = field(default_factory=list)  # sample up to 5
    filters: list[str] = field(default_factory=list)
    updated_at: str = ""

    @property
    def element_ids_are_sampled(self) -> bool:
        return len(self.element_ids) < self.count

    def set(
        self,
        label: str,
        source: str,
        category: Optional[str],
        count: int,
        element_ids: list[int],
        filters: Optional[list[str]] = None,
    ) -> None:
        self.label = label
        self.source = source
        self.category = category
        self.count = count
        self.element_ids = element_ids[:5]  # sample up to 5
        self.filters = filters or []
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def reset(self) -> None:
        self.label = ""
        self.source = ""
        self.category = None
        self.count = 0
        self.element_ids = []
        self.filters = []
        self.updated_at = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "source": self.source,
            "category": self.category,
            "count": self.count,
            "element_ids": self.element_ids,
            "filters": self.filters,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkingSet:
        ws = cls()
        ws.label = data.get("label", "")
        ws.source = data.get("source", "")
        ws.category = data.get("category")
        ws.count = data.get("count", 0)
        ws.element_ids = data.get("element_ids", [])
        ws.filters = data.get("filters", [])
        ws.updated_at = data.get("updated_at", "")
        return ws


@dataclass
class SessionArtifact:
    """An artifact produced during the session (file, report, preview)."""
    kind: str  # "file", "preview", "report"
    label: str
    file_id: Optional[str] = None
    filename: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "file_id": self.file_id,
            "filename": self.filename,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionArtifact:
        return cls(
            kind=data.get("kind", "file"),
            label=data.get("label", ""),
            file_id=data.get("file_id"),
            filename=data.get("filename"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class SessionState:
    """Full session state tracking for context-aware AI responses."""
    working_set: WorkingSet = field(default_factory=WorkingSet)
    resolved_entities: OrderedDict[str, list[dict[str, Any]]] = field(
        default_factory=OrderedDict
    )
    artifacts: list[SessionArtifact] = field(default_factory=list)
    current_goal: Optional[str] = None
    last_tool_name: Optional[str] = None
    last_tool_result_summary: Optional[str] = None
    briefing_sent: bool = False
    # Verdict from the vision critic on the PREVIOUS turn's result (the agent's
    # eyes). It was being written after every witnessed write and then read by
    # nobody — the build→SEE→critique→fix loop was open at the last step, so the
    # model kept re-asserting success it could not check while we paid for the
    # look. Surfaced in to_prompt_block so the next turn actually sees it.
    last_vision_verdict: Optional[dict[str, Any]] = None

    _MAX_ENTITIES = 20
    _MAX_ARTIFACTS = 10

    def store_resolved(
        self,
        label: str,
        element_ids: list[int],
        category: Optional[str] = None,
    ) -> None:
        """Store resolved entities for multi-turn reference.

        Args:
            label: Descriptive label (e.g. "34 наружные стены")
            element_ids: List of ElementIds found
            category: Optional category name
        """
        key = label.lower().strip()
        if not key:
            key = f"result_{len(self.resolved_entities)}"

        entry: dict[str, Any] = {
            "label": label,
            "element_ids": element_ids[:50],  # cap stored IDs
            "count": len(element_ids),
            "category": category,
        }

        # If at capacity, remove oldest
        if key not in self.resolved_entities and len(self.resolved_entities) >= self._MAX_ENTITIES:
            self.resolved_entities.popitem(last=False)

        self.resolved_entities[key] = [entry]

    def resolve_reference(self, message: str) -> Optional[dict[str, Any]]:
        """Resolve pronoun references in a message to cached entities.

        Detects pronouns like "их", "эти", "them", "these", "those"
        and returns the most recently stored entity set.

        Returns:
            The most recent entity dict if reference detected, None otherwise.
        """
        if not self.resolved_entities:
            return None

        msg_lower = message.lower()

        # Check for reference pronouns (first 5 words)
        words = msg_lower.split()[:5]
        reference_tokens = {
            "их", "им", "ими", "них", "ним", "ними",
            "эти", "этих", "этим", "этими",
            "те", "тех", "тем", "теми",
            "них", "те же", "этих же",
            "them", "these", "those", "they", "same",
            "it", "its",
        }

        has_reference = any(
            token in msg_lower
            for token in reference_tokens
            if any(token == w or f" {token} " in f" {msg_lower} " for w in words)
        )

        if not has_reference:
            return None

        # Return the most recent entity set
        last_key = list(self.resolved_entities.keys())[-1]
        entries = self.resolved_entities[last_key]
        if entries:
            return entries[0]
        return None

    def apply_user_turn(self, message: str) -> None:
        """Extract action/category/filter hints from user message.

        Detects target pivot (e.g., walls→floors resets working set chain).
        """
        new_category = _detect_category(message)

        # Target pivot detection: if user switches category, reset working set
        if (
            new_category
            and self.working_set.category
            and new_category != self.working_set.category
        ):
            self.working_set.reset()

        # Update filters from message
        new_filters = _detect_filters(message)
        if new_filters:
            self.working_set.filters = new_filters

        # Update goal
        self.update_current_goal(message)

    def update_current_goal(self, message: str) -> None:
        """Set or append to current goal based on follow-up detection."""
        if is_likely_follow_up(message) and self.current_goal:
            # Append to existing goal
            self.current_goal = f"{self.current_goal} → {message.strip()}"
        else:
            # New goal
            self.current_goal = message.strip()

    def remember_tool_result(self, tool_name: str, result: dict[str, Any] | str) -> None:
        """Parse tool result, infer working_set from output, track artifacts."""
        self.last_tool_name = tool_name

        # Parse result if it's a string
        if isinstance(result, str):
            try:
                import json
                result = json.loads(result)
            except (json.JSONDecodeError, TypeError):
                self.last_tool_result_summary = str(result)[:200]
                return

        if not isinstance(result, dict):
            self.last_tool_result_summary = str(result)[:200]
            return

        # Check for error
        if result.get("error"):
            self.last_tool_result_summary = f"Ошибка: {result.get('message', 'unknown')}"
            return

        # Extract working set info from result
        self.last_tool_result_summary = "Успешно выполнено"

        # Infer working set from common result patterns
        if "count" in result:
            count = result["count"]
            if isinstance(count, int):
                self.last_tool_result_summary = f"Найдено {count} элементов"

        element_ids = result.get("element_ids", result.get("working_set", []))
        if isinstance(element_ids, list) and element_ids:
            count = result.get("count", len(element_ids))
            category = result.get("category", self.working_set.category)
            self.working_set.set(
                label=f"{count} элементов",
                source="tool_result",
                category=category,
                count=count,
                element_ids=[eid for eid in element_ids if isinstance(eid, int)],
            )
            # Also store as resolved entities for multi-turn follow-up reference
            label = result.get("label", f"{count} элементов")
            int_ids = [eid for eid in element_ids if isinstance(eid, int)]
            if int_ids:
                self.store_resolved(str(label), int_ids, category)

        # Track artifacts (files, reports)
        if result.get("file_id"):
            artifact = SessionArtifact(
                kind="report" if result.get("filename", "").endswith(".xlsx") else "file",
                label=result.get("filename", "file"),
                file_id=result.get("file_id"),
                filename=result.get("filename"),
            )
            self.artifacts.append(artifact)
            if len(self.artifacts) > self._MAX_ARTIFACTS:
                self.artifacts = self.artifacts[-self._MAX_ARTIFACTS:]

    def to_prompt_block(self) -> str:
        """Generate text block for LLM prompt with current session context."""
        lines: list[str] = ["## Текущий контекст сессии"]

        if self.current_goal:
            lines.append(f"\n**Цель:** {self.current_goal}")

        if self.working_set.label:
            ws = self.working_set
            cat_info = f", категория: {ws.category}" if ws.category else ""
            filter_info = f", фильтр: {', '.join(ws.filters)}" if ws.filters else ""
            lines.append(f"\n**Рабочий набор:** {ws.label} ({ws.count} элементов{cat_info}{filter_info})")
            if ws.element_ids:
                sampled = " (из {})".format(ws.count) if ws.element_ids_are_sampled else ""
                lines.append(f"Примеры ElementId: {ws.element_ids}{sampled}")

        if self.last_tool_name:
            lines.append(
                f"\n**Последний инструмент:** {self.last_tool_name} → "
                f"{self.last_tool_result_summary or 'выполнен'}"
            )

        if isinstance(self.last_vision_verdict, dict) and self.last_vision_verdict:
            _v = self.last_vision_verdict
            _verdict = str(_v.get("вердикт") or _v.get("verdict") or "").strip()
            _comment = str(_v.get("комментарий") or _v.get("comment") or "").strip()
            if _verdict or _comment:
                lines.append(
                    "\n**Проверка глазами (предыдущий результат, независимый осмотр вида):** "
                    + (f"{_verdict}. " if _verdict else "")
                    + (_comment[:400] if _comment else "")
                    + "\nЕсли осмотр нашёл проблему — исправь её, не повторяй тот же шаг вслепую."
                )

        if self.resolved_entities:
            # Show last 3 resolved entity sets
            entity_keys = list(self.resolved_entities.keys())[-3:]
            entity_strs = []
            for key in entity_keys:
                entries = self.resolved_entities[key]
                if entries:
                    e = entries[0]
                    cat = f" ({e.get('category', '')})" if e.get("category") else ""
                    entity_strs.append(
                        f"{e.get('label', key)}: {e.get('count', 0)} элементов{cat}"
                    )
            if entity_strs:
                lines.append(f"\n**Запомненные наборы:** {'; '.join(entity_strs)}")
                # Show IDs of the most recent set
                last = self.resolved_entities[entity_keys[-1]]
                if last and last[0].get("element_ids"):
                    ids = last[0]["element_ids"][:10]
                    lines.append(f"Последние ElementId: {ids}")

        if self.artifacts:
            artifact_strs = []
            for a in self.artifacts[-3:]:  # Show last 3 artifacts
                artifact_strs.append(f"{a.filename or a.label} ({a.kind})")
            lines.append(f"\n**Артефакты:** {', '.join(artifact_strs)}")

        # Only return block if there's meaningful content
        if len(lines) <= 1:
            return ""
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "working_set": self.working_set.to_dict(),
            "resolved_entities": dict(self.resolved_entities),
            "artifacts": [a.to_dict() for a in self.artifacts],
            "current_goal": self.current_goal,
            "last_tool_name": self.last_tool_name,
            "last_tool_result_summary": self.last_tool_result_summary,
            "briefing_sent": self.briefing_sent,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionState:
        state = cls()
        if "working_set" in data:
            state.working_set = WorkingSet.from_dict(data["working_set"])
        if "resolved_entities" in data:
            state.resolved_entities = OrderedDict(data["resolved_entities"])
        if "artifacts" in data:
            state.artifacts = [
                SessionArtifact.from_dict(a) for a in data["artifacts"]
            ]
        state.current_goal = data.get("current_goal")
        state.last_tool_name = data.get("last_tool_name")
        state.last_tool_result_summary = data.get("last_tool_result_summary")
        state.briefing_sent = data.get("briefing_sent", False)
        return state
