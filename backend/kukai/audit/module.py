"""AuditModule — KukaiModule implementation for the Audit Engine."""

from __future__ import annotations

import logging
from typing import Any

from kukai.audit.engine import AuditEngine
from kukai.audit.models import Category
from kukai.modules.base import KukaiModule, ModuleDeps, ToolDef

logger = logging.getLogger(__name__)

# Valid category names for the tool parameter enum
_CATEGORY_VALUES = [c.value for c in Category]


class AuditModule(KukaiModule):
    """BIM model validation and quality checking module."""

    @property
    def name(self) -> str:
        return "audit"

    @property
    def version(self) -> str:
        return "1.0"

    async def on_startup(self, deps: ModuleDeps) -> None:
        self._engine = AuditEngine(deps.bridge, deps.llm, deps.db)

    async def _handle_audit_model(
        self, params: dict[str, Any], context: Any,
    ) -> dict[str, Any]:
        """Tool handler for audit_model — dispatches to AuditEngine."""
        categories = params.get("categories")
        quick = params.get("quick", False)

        try:
            if quick:
                report = await self._engine.quick_check()
            else:
                report = await self._engine.run(categories=categories)
        except Exception as exc:
            logger.exception("Audit failed")
            return {"error": True, "message": f"Audit failed: {exc}"}

        markdown = self._engine.format_chat(report)

        issues_list = []
        for issue in report.issues:
            issues_list.append({
                "rule_id": issue.rule_id,
                "rule_name": issue.rule_name,
                "category": issue.category.value,
                "severity": issue.severity.value,
                "element_ids": issue.element_ids[:50],
                "element_count": issue.element_count,
                "message": issue.message,
                "explanation": issue.explanation,
            })

        return {
            "status": report.status.value,
            "summary": markdown,
            "errors": report.summary.errors,
            "warnings": report.summary.warnings,
            "total_rules": report.summary.total_rules,
            "passed": report.summary.passed,
            "infos": report.summary.infos,
            "issues": issues_list,
            "total_elements": report.total_elements,
            "checked_at": report.checked_at.isoformat(),
            "duration_seconds": report.duration_seconds,
            "categories_checked": report.categories_checked,
        }

    def register_tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                name="audit_model",
                description=(
                    "Run BIM model audit — check naming, parameters, geometry, "
                    "levels, warnings, and IFC readiness. Returns a structured "
                    "report with issues, severity, and affected element IDs."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "categories": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": _CATEGORY_VALUES,
                            },
                            "description": (
                                "Categories to check. Default: all. "
                                "Options: naming, parameters, geometry, levels, warnings, ifc_ready"
                            ),
                        },
                        "quick": {
                            "type": "boolean",
                            "description": (
                                "Quick mode: skip AI explanations, just run checks. "
                                "Default: false."
                            ),
                        },
                    },
                    "required": [],
                },
                handler=self._handle_audit_model,
            ),
        ]

    def register_prompts(self) -> dict[str, str]:
        return {
            "audit": (
                "## /аудит — Проверка модели\n\n"
                "Инструмент `audit_model` запускает автоматическую проверку BIM-модели "
                "по 24 правилам в 6 категориях:\n"
                "- **naming** — именование семейств, типов стен, видов, уровней, листов\n"
                "- **parameters** — заполненность материалов, помещений, марок, фаз, workset\n"
                "- **geometry** — нулевые стены/перекрытия, дубли помещений, габариты модели\n"
                "- **levels** — привязка стен, неиспользуемые уровни, высоты этажей\n"
                "- **warnings** — общее количество предупреждений, overlap/duplicate\n"
                "- **ifc_ready** — IfcExportAs, адрес проекта, координаты, base quantities\n\n"
                "### Когда вызывать audit_model:\n"
                "- Пользователь пишет `/аудит`, `/audit`, «проверь модель», «аудит модели»\n"
                "- Пользователь спрашивает о качестве модели или проблемах\n"
                "- Перед экспортом в IFC (проверь ifc_ready категорию)\n\n"
                "### Как использовать результат:\n"
                "1. Покажи сводку: сколько правил прошло, сколько ошибок/предупреждений\n"
                "2. Для ERROR — подсвети элементы через `highlight_elements` (красный)\n"
                "3. Для WARNING — подсвети (жёлтый: r=255,g=165,b=0)\n"
                "4. Предложи экспорт отчёта через `generate_report`\n"
                "5. Если есть element_ids — предложи выбрать/подсветить проблемные элементы\n\n"
                "### Параметры:\n"
                "- `categories` — список категорий для проверки (по умолчанию все)\n"
                "- `quick: true` — быстрый режим без AI-объяснений (для регулярных проверок)\n"
            ),
        }

    @property
    def engine(self) -> AuditEngine:
        return self._engine
