"""QA/QC Check Packages — predefined model quality checks.

Three levels of checks:
- quick (3 checks): duplicates, warnings count, unnamed rooms
- standard (6 checks): quick + unused types, level consistency, parameter completeness
- thorough (10 checks): standard + view template usage, workset assignment, room boundaries, family naming

Each check is a C# code snippet that runs via execute_revit_code through the bridge.
Results are aggregated and returned as a formatted report.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class QaCheck:
    """A single QA check definition."""
    id: str
    name_ru: str
    name_en: str
    description_ru: str
    code: str
    severity: str = "warning"  # "info", "warning", "error"


# --- Check definitions ---

CHECK_WARNINGS_COUNT = QaCheck(
    id="warnings_count",
    name_ru="Предупреждения модели",
    name_en="Model warnings",
    description_ru="Количество предупреждений в модели",
    code=(
        "var warnings = doc.GetWarnings();\n"
        "var byType = warnings\n"
        "    .GroupBy(w => w.GetDescriptionText())\n"
        "    .Select(g => new { description = g.Key, count = g.Count() })\n"
        "    .OrderByDescending(g => g.count)\n"
        "    .Take(10)\n"
        "    .ToList();\n"
        "return new { total = warnings.Count, top_warnings = byType };"
    ),
    severity="warning",
)

CHECK_UNNAMED_ROOMS = QaCheck(
    id="unnamed_rooms",
    name_ru="Помещения без имени",
    name_en="Unnamed rooms",
    description_ru="Помещения с пустым или стандартным названием",
    code=(
        "var rooms = new FilteredElementCollector(doc)\n"
        "    .OfCategory(BuiltInCategory.OST_Rooms)\n"
        "    .WhereElementIsNotElementType()\n"
        "    .ToElements();\n"
        "var unnamed = rooms\n"
        "    .Where(r => {\n"
        "        var name = r.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? \"\";\n"
        "        return string.IsNullOrWhiteSpace(name) || name == \"Room\" || name == \"Помещение\";\n"
        "    })\n"
        "    .Select(r => new { id = r.Id.Value, number = r.get_Parameter(BuiltInParameter.ROOM_NUMBER)?.AsString() ?? \"\" })\n"
        "    .Take(20)\n"
        "    .ToList();\n"
        "return new { total_rooms = rooms.Count, unnamed_count = unnamed.Count, unnamed = unnamed };"
    ),
    severity="warning",
)

CHECK_DUPLICATE_INSTANCES = QaCheck(
    id="duplicate_instances",
    name_ru="Дублированные элементы",
    name_en="Duplicate instances",
    description_ru="Элементы одного типа на одной точке (возможные дубликаты)",
    code=(
        "var categories = new[] {\n"
        "    BuiltInCategory.OST_Doors,\n"
        "    BuiltInCategory.OST_Windows,\n"
        "    BuiltInCategory.OST_Furniture,\n"
        "    BuiltInCategory.OST_LightingFixtures\n"
        "};\n"
        "var duplicates = new List<object>();\n"
        "foreach (var cat in categories) {\n"
        "    var elements = new FilteredElementCollector(doc)\n"
        "        .OfCategory(cat)\n"
        "        .WhereElementIsNotElementType()\n"
        "        .ToElements();\n"
        "    var byLocation = elements\n"
        "        .Where(e => e.Location is LocationPoint)\n"
        "        .GroupBy(e => {\n"
        "            var lp = (LocationPoint)e.Location;\n"
        "            return $\"{Math.Round(lp.Point.X, 3)},{Math.Round(lp.Point.Y, 3)},{Math.Round(lp.Point.Z, 3)},{e.GetTypeId().Value}\";\n"
        "        })\n"
        "        .Where(g => g.Count() > 1);\n"
        "    foreach (var g in byLocation) {\n"
        "        duplicates.Add(new { category = cat.ToString(), count = g.Count(), ids = g.Select(e => e.Id.Value).Take(5).ToList() });\n"
        "        if (duplicates.Count >= 20) break;\n"
        "    }\n"
        "    if (duplicates.Count >= 20) break;\n"
        "}\n"
        "return new { duplicate_groups = duplicates.Count, details = duplicates };"
    ),
    severity="error",
)

CHECK_UNUSED_TYPES = QaCheck(
    id="unused_types",
    name_ru="Неиспользуемые типы",
    name_en="Unused types",
    description_ru="Типы семейств без экземпляров в модели",
    code=(
        "var categories = new[] {\n"
        "    BuiltInCategory.OST_Walls, BuiltInCategory.OST_Doors,\n"
        "    BuiltInCategory.OST_Windows, BuiltInCategory.OST_Floors,\n"
        "    BuiltInCategory.OST_Furniture\n"
        "};\n"
        "var unusedList = new List<object>();\n"
        "foreach (var cat in categories) {\n"
        "    var types = new FilteredElementCollector(doc)\n"
        "        .OfCategory(cat)\n"
        "        .WhereElementIsElementType()\n"
        "        .ToElements();\n"
        "    var instances = new FilteredElementCollector(doc)\n"
        "        .OfCategory(cat)\n"
        "        .WhereElementIsNotElementType()\n"
        "        .ToElements();\n"
        "    var usedTypeIds = new HashSet<long>(instances.Select(e => e.GetTypeId().Value));\n"
        "    var unused = types.Where(t => !usedTypeIds.Contains(t.Id.Value))\n"
        "        .Select(t => new { name = t.Name, id = t.Id.Value, category = cat.ToString() })\n"
        "        .ToList();\n"
        "    unusedList.AddRange(unused);\n"
        "}\n"
        "return new { count = unusedList.Count, unused_types = unusedList.Take(30).ToList() };"
    ),
    severity="info",
)

CHECK_LEVEL_CONSISTENCY = QaCheck(
    id="level_consistency",
    name_ru="Согласованность уровней",
    name_en="Level consistency",
    description_ru="Проверка выравнивания уровней и нестандартных высот этажей",
    code=(
        "var levels = new FilteredElementCollector(doc)\n"
        "    .OfClass(typeof(Level))\n"
        "    .Cast<Level>()\n"
        "    .OrderBy(l => l.Elevation)\n"
        "    .ToList();\n"
        "var issues = new List<object>();\n"
        "for (int i = 1; i < levels.Count; i++) {\n"
        "    var heightFt = levels[i].Elevation - levels[i - 1].Elevation;\n"
        "    var heightM = Math.Round(heightFt * 0.3048, 2);\n"
        "    if (heightM < 2.0 || heightM > 6.0) {\n"
        "        issues.Add(new {\n"
        "            from_level = levels[i - 1].Name,\n"
        "            to_level = levels[i].Name,\n"
        "            height_m = heightM,\n"
        "            warning = heightM < 2.0 ? \"Слишком низкий этаж\" : \"Нестандартная высота этажа\"\n"
        "        });\n"
        "    }\n"
        "}\n"
        "return new { total_levels = levels.Count, issues = issues };"
    ),
    severity="warning",
)

CHECK_PARAMETER_COMPLETENESS = QaCheck(
    id="parameter_completeness",
    name_ru="Заполненность параметров",
    name_en="Parameter completeness",
    description_ru="Процент заполнения ключевых параметров",
    code=(
        "var checks = new[] {\n"
        "    (\"Rooms\", BuiltInCategory.OST_Rooms, new[] { BuiltInParameter.ROOM_NAME, BuiltInParameter.ROOM_NUMBER }),\n"
        "    (\"Doors\", BuiltInCategory.OST_Doors, new[] { BuiltInParameter.ALL_MODEL_MARK }),\n"
        "    (\"Windows\", BuiltInCategory.OST_Windows, new[] { BuiltInParameter.ALL_MODEL_MARK }),\n"
        "};\n"
        "var results = new List<object>();\n"
        "foreach (var (catName, cat, paramIds) in checks) {\n"
        "    var elements = new FilteredElementCollector(doc)\n"
        "        .OfCategory(cat)\n"
        "        .WhereElementIsNotElementType()\n"
        "        .ToElements();\n"
        "    if (elements.Count == 0) continue;\n"
        "    foreach (var pid in paramIds) {\n"
        "        var filled = elements.Count(e => {\n"
        "            var p = e.get_Parameter(pid);\n"
        "            return p != null && p.HasValue && !string.IsNullOrWhiteSpace(p.AsString());\n"
        "        });\n"
        "        var pct = Math.Round(100.0 * filled / elements.Count, 1);\n"
        "        results.Add(new { category = catName, parameter = pid.ToString(), filled = filled, total = elements.Count, percent = pct });\n"
        "    }\n"
        "}\n"
        "return new { checks = results };"
    ),
    severity="info",
)

CHECK_VIEW_TEMPLATES = QaCheck(
    id="view_templates",
    name_ru="Использование шаблонов видов",
    name_en="View template usage",
    description_ru="Виды без назначенного шаблона вида",
    code=(
        "var views = new FilteredElementCollector(doc)\n"
        "    .OfClass(typeof(View))\n"
        "    .Cast<View>()\n"
        "    .Where(v => !v.IsTemplate && v.CanBePrinted)\n"
        "    .ToList();\n"
        "var noTemplate = views\n"
        "    .Where(v => v.ViewTemplateId == null || v.ViewTemplateId == ElementId.InvalidElementId)\n"
        "    .Select(v => new { name = v.Name, type = v.ViewType.ToString(), id = v.Id.Value })\n"
        "    .Take(20)\n"
        "    .ToList();\n"
        "return new { total_views = views.Count, without_template = noTemplate.Count, details = noTemplate };"
    ),
    severity="info",
)

CHECK_ROOM_BOUNDARIES = QaCheck(
    id="room_boundaries",
    name_ru="Границы помещений",
    name_en="Room boundaries",
    description_ru="Помещения без замкнутых границ или с нулевой площадью",
    code=(
        "var rooms = new FilteredElementCollector(doc)\n"
        "    .OfCategory(BuiltInCategory.OST_Rooms)\n"
        "    .WhereElementIsNotElementType()\n"
        "    .ToElements();\n"
        "var issues = rooms\n"
        "    .Where(r => {\n"
        "        var area = r.get_Parameter(BuiltInParameter.ROOM_AREA);\n"
        "        return area == null || !area.HasValue || area.AsDouble() <= 0;\n"
        "    })\n"
        "    .Select(r => new {\n"
        "        id = r.Id.Value,\n"
        "        name = r.get_Parameter(BuiltInParameter.ROOM_NAME)?.AsString() ?? \"\",\n"
        "        number = r.get_Parameter(BuiltInParameter.ROOM_NUMBER)?.AsString() ?? \"\"\n"
        "    })\n"
        "    .Take(20)\n"
        "    .ToList();\n"
        "return new { total_rooms = rooms.Count, unbounded = issues.Count, details = issues };"
    ),
    severity="error",
)

CHECK_FAMILY_NAMING = QaCheck(
    id="family_naming",
    name_ru="Именование семейств",
    name_en="Family naming conventions",
    description_ru="Семейства с нестандартными именами (содержащие спецсимволы или слишком длинные)",
    code=(
        "var types = new FilteredElementCollector(doc)\n"
        "    .OfClass(typeof(FamilySymbol))\n"
        "    .Cast<FamilySymbol>()\n"
        "    .ToList();\n"
        "var issues = types\n"
        "    .Where(t => {\n"
        "        var fname = t.Family?.Name ?? \"\";\n"
        "        return fname.Length > 80 || fname.Contains(\"  \") || fname.Contains(\"Copy\") || fname.Contains(\"Копия\");\n"
        "    })\n"
        "    .Select(t => new { family = t.Family?.Name ?? \"\", type = t.Name, id = t.Id.Value })\n"
        "    .Take(20)\n"
        "    .ToList();\n"
        "return new { total_types = types.Count, naming_issues = issues.Count, details = issues };"
    ),
    severity="info",
)

CHECK_WORKSET_ASSIGNMENT = QaCheck(
    id="workset_assignment",
    name_ru="Назначение рабочих наборов",
    name_en="Workset assignment",
    description_ru="Элементы в рабочем наборе по умолчанию (Workset1)",
    code=(
        "if (!doc.IsWorkshared) return new { workshared = false, message = \"Модель не использует рабочие наборы\" };\n"
        "var categories = new[] {\n"
        "    BuiltInCategory.OST_Walls, BuiltInCategory.OST_Floors,\n"
        "    BuiltInCategory.OST_Doors, BuiltInCategory.OST_Windows\n"
        "};\n"
        "var inDefault = new List<object>();\n"
        "foreach (var cat in categories) {\n"
        "    var elements = new FilteredElementCollector(doc)\n"
        "        .OfCategory(cat)\n"
        "        .WhereElementIsNotElementType()\n"
        "        .ToElements();\n"
        "    var defaultWs = elements\n"
        "        .Where(e => {\n"
        "            var wsParam = e.get_Parameter(BuiltInParameter.ELEM_PARTITION_PARAM);\n"
        "            return wsParam != null && (wsParam.AsValueString() == \"Workset1\" || wsParam.AsValueString() == \"Рабочий набор1\");\n"
        "        })\n"
        "        .Count();\n"
        "    if (defaultWs > 0) {\n"
        "        inDefault.Add(new { category = cat.ToString(), count = defaultWs, total = elements.Count });\n"
        "    }\n"
        "}\n"
        "return new { workshared = true, in_default_workset = inDefault };"
    ),
    severity="warning",
)


# --- Package definitions ---

PACKAGES: dict[str, list[QaCheck]] = {
    "quick": [
        CHECK_DUPLICATE_INSTANCES,
        CHECK_WARNINGS_COUNT,
        CHECK_UNNAMED_ROOMS,
    ],
    "standard": [
        CHECK_DUPLICATE_INSTANCES,
        CHECK_WARNINGS_COUNT,
        CHECK_UNNAMED_ROOMS,
        CHECK_UNUSED_TYPES,
        CHECK_LEVEL_CONSISTENCY,
        CHECK_PARAMETER_COMPLETENESS,
    ],
    "thorough": [
        CHECK_DUPLICATE_INSTANCES,
        CHECK_WARNINGS_COUNT,
        CHECK_UNNAMED_ROOMS,
        CHECK_UNUSED_TYPES,
        CHECK_LEVEL_CONSISTENCY,
        CHECK_PARAMETER_COMPLETENESS,
        CHECK_VIEW_TEMPLATES,
        CHECK_ROOM_BOUNDARIES,
        CHECK_FAMILY_NAMING,
        CHECK_WORKSET_ASSIGNMENT,
    ],
}

ALL_CHECKS: dict[str, QaCheck] = {
    check.id: check
    for checks in PACKAGES.values()
    for check in checks
}


# --- Trigger detection ---

_QA_TRIGGERS_RU = [
    "проверь модель", "проверка модели", "проверить модель",
    "qc проверка", "контроль качества", "аудит модели",
    "проверка качества", "проверь качество",
]
_QA_TRIGGERS_EN = [
    "check model", "model check", "qa check", "qc check",
    "quality check", "audit model", "model audit",
]

_PACKAGE_TRIGGERS: dict[str, list[str]] = {
    "quick": ["быстр", "quick", "кратк", "экспресс"],
    "standard": ["стандарт", "standard", "обычн", "нормальн"],
    "thorough": ["полн", "thorough", "подробн", "детальн", "глубок", "full", "deep"],
}


def detect_qa_trigger(message: str) -> Optional[str]:
    """Detect if a message is a QA check request.

    Returns the package name ("quick", "standard", "thorough") if matched,
    or None if not a QA trigger.
    """
    msg_lower = message.strip().lower()

    # Check if message contains a QA trigger phrase
    is_qa = any(t in msg_lower for t in _QA_TRIGGERS_RU + _QA_TRIGGERS_EN)
    if not is_qa:
        return None

    # Determine package level
    for package, keywords in _PACKAGE_TRIGGERS.items():
        if any(kw in msg_lower for kw in keywords):
            return package

    # Default to standard
    return "standard"


def get_package_checks(package: str) -> list[QaCheck]:
    """Get the list of checks for a package."""
    return PACKAGES.get(package, PACKAGES["standard"])


def get_all_check_codes() -> dict[str, str]:
    """Return all check IDs mapped to their C# code.

    Used by the model_audit skill to reference existing checks.
    """
    return {check.id: check.code for check in ALL_CHECKS.values()}


def format_qa_report(
    results: list[tuple[QaCheck, dict[str, Any]]],
    package: str,
) -> str:
    """Format QA check results into a readable report.

    Args:
        results: List of (check, result_dict) tuples.
        package: The package name that was run.

    Returns:
        Formatted report string.
    """
    package_names = {
        "quick": "Быстрая проверка",
        "standard": "Стандартная проверка",
        "thorough": "Полная проверка",
    }

    lines = [
        f"## {package_names.get(package, package)} модели",
        f"Выполнено проверок: {len(results)}",
        "",
    ]

    errors = 0
    warnings = 0
    info = 0

    for check, result in results:
        if isinstance(result, dict) and result.get("error"):
            icon = "X"
            errors += 1
            lines.append(f"### {icon} {check.name_ru}")
            lines.append(f"Ошибка: {result.get('message', 'неизвестная ошибка')}")
            lines.append("")
            continue

        icon = {
            "error": "X",
            "warning": "!",
            "info": "i",
        }.get(check.severity, "i")

        lines.append(f"### [{icon}] {check.name_ru}")
        lines.append(f"_{check.description_ru}_")

        # Format result details
        if isinstance(result, dict):
            for key, value in result.items():
                if key in ("error", "success"):
                    continue
                if isinstance(value, list):
                    if len(value) == 0:
                        lines.append(f"- {key}: нет")
                    else:
                        lines.append(f"- {key}: {len(value)} записей")
                elif isinstance(value, (int, float)):
                    lines.append(f"- {key}: {value}")
                elif isinstance(value, str):
                    lines.append(f"- {key}: {value}")
                elif isinstance(value, bool):
                    lines.append(f"- {key}: {'да' if value else 'нет'}")

            # Count issues by severity
            has_issues = False
            for key in ["unnamed_count", "duplicate_groups", "unbounded", "naming_issues"]:
                v = result.get(key)
                if isinstance(v, (int, float)) and v > 0:
                    has_issues = True
                    break
            total_val = result.get("total", result.get("count", 0))
            if isinstance(total_val, int) and total_val > 0 and check.severity == "warning":
                has_issues = True

            if has_issues and check.severity == "error":
                errors += 1
            elif has_issues and check.severity == "warning":
                warnings += 1
            else:
                info += 1
        else:
            info += 1

        lines.append("")

    # Summary
    lines.append("---")
    lines.append(f"**Итого:** {errors} ошибок, {warnings} предупреждений, {info} информация")

    return "\n".join(lines)
