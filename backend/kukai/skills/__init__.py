"""AI Skill system — multi-step workflows activated by keyword detection.

Skills inject detailed prompts (~8-10K chars) that guide the AI through
professional workflows like print/export or model audit. Unlike extension
profiles (~1K tokens), skills contain full step-by-step instructions,
code patterns, and decision rules.

Activation priority: skill detection > QA trigger detection.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_SKILLS_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "skills"


@dataclass
class SkillDefinition:
    """A registered AI skill."""

    id: str
    name_ru: str
    triggers_ru: list[str] = field(default_factory=list)
    triggers_en: list[str] = field(default_factory=list)
    prompt_file: str = ""
    max_chars: int = 10000


SKILLS: list[SkillDefinition] = [
    SkillDefinition(
        id="print_export",
        name_ru="Печ��ть и экспорт в PDF",
        triggers_ru=[
            "печать", "напечатай", "выведи на печать", "экспорт pdf",
            "экспорт в pdf", "создай чертежи", "оформи чертежи",
            "экспортируй листы", "подготовь документацию", "комплект чертежей",
            "выведи чертежи", "распечатай", "экспортируй в pdf",
        ],
        triggers_en=[
            "print", "export pdf", "export to pdf", "create drawings",
            "prepare sheets", "print drawings", "export sheets",
        ],
        prompt_file="print_export.md",
    ),
    SkillDefinition(
        id="model_audit",
        name_ru="Аудит и исправление модели",
        triggers_ru=[
            "аудит модели", "полная проверка", "исправь модель",
            "найди ошибки", "чистка модели", "приведи в порядок",
            "bim аудит", "проверь и исправь", "почисти модель",
            "найди и исправь", "полный аудит",
        ],
        triggers_en=[
            "model audit", "full audit", "fix model", "cleanup model",
            "bim audit", "find and fix", "full check",
        ],
        prompt_file="model_audit.md",
    ),
    SkillDefinition(
        id="compliance",
        name_ru="Проверка на соответствие нормам СП/ГОСТ",
        triggers_ru=[
            "проверь на нормы", "на соответствие нормам", "проверка нормативов",
            "нарушения ГОСТ", "соответствие СНиП", "проверь нормативы",
            "проверка на соответствие", "нормоконтроль", "соответствие СП",
            "на нормы", "по нормативам", "проверь на СП",
            "проверка СП", "проверка ГОСТ", "нормативная проверка",
        ],
        triggers_en=[
            "check norms", "norm compliance", "code compliance",
            "building code check", "sp check", "gost check",
        ],
        prompt_file="compliance.md",
        max_chars=15000,
    ),
    SkillDefinition(
        id="construction_schedule",
        name_ru="Календарное планирование строительства",
        triggers_ru=[
            "календарный план", "график строительства", "4d", "4д",
            "сроки строительства", "рассчитай сроки", "трудозатраты",
            "длительность строительства", "план производства работ",
            "ппр", "календарный график", "построй график",
            "сколько займёт строительство", "продолжительность строительства",
            "рассчитай длительность", "посчитай сроки",
        ],
        triggers_en=[
            "construction schedule", "4d bim", "timeline", "gantt",
            "labor hours", "construction duration", "build schedule",
        ],
        prompt_file="construction_schedule.md",
    ),
    SkillDefinition(
        id="build_from_underlay",
        name_ru="Построение модели по подложке (пошагово)",
        triggers_ru=[
            "построй по подложке", "модель по подложке", "модель по dwg",
            "модель по чертежу", "построй по чертежу", "подними 3д по dwg",
            "подними модель по dwg", "подними 3d по подложке",
            "построй этаж по подложке", "смоделируй по подложке",
            "по подложке построй", "по dwg построй", "построй по подгруженной",
            "по cad построй", "модель по cad",
        ],
        triggers_en=[
            "build from underlay", "model from dwg", "model from cad",
            "build from dwg", "model from drawing", "raise 3d from dwg",
        ],
        prompt_file="build_from_underlay.md",
    ),
]

_SKILL_MAP: dict[str, SkillDefinition] = {s.id: s for s in SKILLS}


def detect_skill(message: str) -> Optional[SkillDefinition]:
    """Detect if a message triggers a skill.

    Returns the matched SkillDefinition or None.
    Checks multi-word triggers first (longer = more specific).
    """
    msg_lower = message.strip().lower()
    if not msg_lower:
        return None

    # Sort all triggers by length descending — longer phrases match first
    candidates: list[tuple[str, SkillDefinition]] = []
    for skill in SKILLS:
        for trigger in skill.triggers_ru + skill.triggers_en:
            candidates.append((trigger.lower(), skill))
    candidates.sort(key=lambda x: len(x[0]), reverse=True)

    for trigger, skill in candidates:
        if trigger in msg_lower:
            return skill

    return None


def load_skill_prompt(skill: SkillDefinition) -> str:
    """Load skill prompt from file, cap at max_chars."""
    if not skill.prompt_file:
        return ""
    path = _SKILLS_DATA_DIR / skill.prompt_file
    if not path.exists():
        logger.warning("Skill prompt not found: %s", path)
        return ""
    try:
        text = path.read_text(encoding="utf-8")
        if len(text) > skill.max_chars:
            text = text[: skill.max_chars]
            # Close any unclosed markdown code blocks
            if text.count("```") % 2 == 1:
                text += "\n```"
            text += "\n... (промпт обрезан)"
        return text
    except Exception:
        logger.exception("Failed to load skill prompt: %s", path)
        return ""


def get_skill(skill_id: str) -> Optional[SkillDefinition]:
    """Get a skill by ID."""
    return _SKILL_MAP.get(skill_id)
