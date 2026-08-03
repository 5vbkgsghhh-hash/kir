"""Write preview generator — shows what will be done before executing.

Generates a preview dict with operation summary, risk level,
and target information for user confirmation.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from kukai.write.router import RE_ELEMENT_ID, RE_BUILTIN_CAT, RE_LOOKUP_PARAM, RE_SET_LITERAL

# Risk indicators
_HIGH_RISK_PATTERNS = [
    re.compile(r'\.Delete\s*\(', re.IGNORECASE),
    re.compile(r'doc\.Delete\s*\(', re.IGNORECASE),
    re.compile(r'ElementTransformUtils\.(Move|Rotate|Mirror)', re.IGNORECASE),
    re.compile(r'foreach.*FilteredElementCollector.*\.Set\(', re.DOTALL),
]

# Operation labels (Russian)
OPERATION_LABELS: dict[str, str] = {
    "set_parameter": "Изменение параметра",
    "create_schedule": "Создание спецификации",
    "hide_or_isolate": "Скрытие/Изоляция элементов",
    "rename_entities": "Переименование",
    "delete": "УДАЛЕНИЕ ЭЛЕМЕНТОВ",
}


def _estimate_risk(
    operation: str,
    target_count: int,
    code: str = "",
) -> str:
    """Estimate risk level for a write operation.

    Returns: "low", "medium", or "high".
    """
    # Check for high-risk patterns in code
    for pattern in _HIGH_RISK_PATTERNS:
        if pattern.search(code):
            return "high"

    # Delete is always high risk
    if operation == "delete":
        return "high"

    # Mass operations (>=100 elements)
    if target_count >= 100:
        return "high"

    # Medium risk thresholds
    if operation == "set_parameter" and target_count >= 50:
        return "medium"
    if operation == "rename_entities":
        return "medium"

    # Everything else is low risk
    return "low"


def build_write_preview(
    code: str,
    explanation: str = "",
    session_state: Any = None,
) -> Optional[dict[str, Any]]:
    """Build a preview dict for a write operation.

    Analyzes the code to determine what will be changed, estimates risk,
    and generates a user-friendly summary.

    Args:
        code: The C# code that will be executed.
        explanation: LLM's explanation of what the code does.
        session_state: Current session state for context.

    Returns:
        Preview dict, or None if the code isn't a recognizable write.
    """
    from kukai.write.router import infer_deterministic_write

    write_info = infer_deterministic_write(code, explanation, session_state)
    if write_info is None:
        return None

    operation = write_info.get("operation", "unknown")
    element_ids = write_info.get("element_ids", [])
    category = write_info.get("category")

    # Estimate target count
    target_count = len(element_ids)
    if session_state and hasattr(session_state, "working_set"):
        ws = session_state.working_set
        if ws.count > target_count:
            target_count = ws.count

    # Build target label
    target_label = f"{target_count} элементов"
    if category:
        target_label = f"{target_count} {category}"

    # Build summary
    summary = ""
    if operation == "set_parameter":
        param_name = write_info.get("parameter_name", "")
        value = write_info.get("value", "")
        summary = f"Установить {param_name} = '{value}' для {target_label}"
    elif operation == "create_schedule":
        summary = f"Создать спецификацию для {category or 'элементов'}"
    elif operation == "hide_or_isolate":
        action = write_info.get("action", "hide")
        action_label = "Скрыть" if action == "hide" else "Изолировать"
        summary = f"{action_label} {target_label}"
    elif operation == "rename_entities":
        new_name = write_info.get("new_name", "")
        summary = f"Переименовать {target_label} в '{new_name}'"

    risk_level = _estimate_risk(operation, target_count, code)

    # Require confirmation for medium and high risk
    requires_confirmation = risk_level in ("medium", "high")

    preview = {
        "operation": operation,
        "operation_label": OPERATION_LABELS.get(operation, operation),
        "summary": summary,
        "risk_level": risk_level,
        "target_label": target_label,
        "target_category": category,
        "target_count_estimate": target_count,
        "sample_targets": element_ids[:3],
        "requires_confirmation": requires_confirmation,
    }

    # Add operation-specific details
    if operation == "set_parameter":
        preview["parameter_changes"] = {
            write_info.get("parameter_name", ""): write_info.get("value", "")
        }

    return preview
