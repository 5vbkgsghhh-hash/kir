"""Deterministic write router — intercepts simple writes and routes them safely.

Analyzes LLM-generated C# code for known safe patterns (set parameter,
create schedule, hide/isolate, rename) and routes them through a
deterministic code generator instead of raw execution.

This is faster, cheaper (fewer tokens), and safer than raw code execution.
"""

from __future__ import annotations

import re
from typing import Any, Optional

# --- 190+ bilingual category aliases → BuiltInCategory ---

CATEGORY_TO_BUILTIN: dict[str, str] = {
    # Structural
    "стены": "OST_Walls", "стена": "OST_Walls", "стен": "OST_Walls",
    "стенам": "OST_Walls", "стенами": "OST_Walls",
    "walls": "OST_Walls", "wall": "OST_Walls",

    "полы": "OST_Floors", "пол": "OST_Floors", "полов": "OST_Floors",
    "перекрытия": "OST_Floors", "перекрытий": "OST_Floors",
    "floors": "OST_Floors", "floor": "OST_Floors", "slab": "OST_Floors",

    "колонны": "OST_StructuralColumns", "колонн": "OST_StructuralColumns",
    "столбы": "OST_StructuralColumns",
    "columns": "OST_StructuralColumns", "column": "OST_StructuralColumns",

    "балки": "OST_StructuralFraming", "балок": "OST_StructuralFraming",
    "ригели": "OST_StructuralFraming",
    "beams": "OST_StructuralFraming", "beam": "OST_StructuralFraming",

    "фундаменты": "OST_StructuralFoundation",
    "foundations": "OST_StructuralFoundation",

    # Architecture
    "комнаты": "OST_Rooms", "помещения": "OST_Rooms", "помещений": "OST_Rooms",
    "rooms": "OST_Rooms", "room": "OST_Rooms",

    "двери": "OST_Doors", "дверей": "OST_Doors",
    "doors": "OST_Doors", "door": "OST_Doors",

    "окна": "OST_Windows", "окон": "OST_Windows",
    "windows": "OST_Windows", "window": "OST_Windows",

    "крыши": "OST_Roofs", "крыш": "OST_Roofs",
    "roofs": "OST_Roofs", "roof": "OST_Roofs",

    "потолки": "OST_Ceilings", "потолков": "OST_Ceilings",
    "ceilings": "OST_Ceilings", "ceiling": "OST_Ceilings",

    "лестницы": "OST_Stairs", "лестниц": "OST_Stairs",
    "stairs": "OST_Stairs", "stair": "OST_Stairs",

    "ограждения": "OST_StairsRailing", "перила": "OST_StairsRailing",
    "railings": "OST_StairsRailing", "railing": "OST_StairsRailing",

    "пандусы": "OST_Ramps", "ramps": "OST_Ramps",

    "витражи": "OST_CurtainWallPanels", "curtain walls": "OST_CurtainWallPanels",

    # MEP
    "воздуховоды": "OST_DuctCurves", "воздуховодов": "OST_DuctCurves",
    "ducts": "OST_DuctCurves", "duct": "OST_DuctCurves",

    "трубы": "OST_PipeCurves", "труб": "OST_PipeCurves",
    "pipes": "OST_PipeCurves", "pipe": "OST_PipeCurves",

    "кабельные лотки": "OST_CableTray",
    "cable trays": "OST_CableTray",

    "короба": "OST_Conduit", "conduits": "OST_Conduit",

    "оборудование": "OST_MechanicalEquipment",
    "mechanical equipment": "OST_MechanicalEquipment",

    "светильники": "OST_LightingFixtures", "освещение": "OST_LightingFixtures",
    "lighting": "OST_LightingFixtures", "lights": "OST_LightingFixtures",

    "спринклеры": "OST_Sprinklers", "sprinklers": "OST_Sprinklers",

    # General
    "мебель": "OST_Furniture", "furniture": "OST_Furniture",
    "парковка": "OST_Parking", "parking": "OST_Parking",
    "озеленение": "OST_Planting", "planting": "OST_Planting",
    "площадка": "OST_Site", "site": "OST_Site",

    # Annotations & Views
    "оси": "OST_Grids", "сетка": "OST_Grids",
    "grids": "OST_Grids", "grid": "OST_Grids",

    "уровни": "OST_Levels", "levels": "OST_Levels", "level": "OST_Levels",

    "листы": "OST_Sheets", "sheets": "OST_Sheets", "sheet": "OST_Sheets",

    "виды": "OST_Views", "views": "OST_Views", "view": "OST_Views",

    "площади": "OST_Areas", "areas": "OST_Areas",

    "типовые модели": "OST_GenericModel",
    "обобщенные модели": "OST_GenericModel", "обобщённые модели": "OST_GenericModel",
    "обобщенная модель": "OST_GenericModel", "обобщённая модель": "OST_GenericModel",
    "обобщенные": "OST_GenericModel", "обобщённые": "OST_GenericModel",
    "generic models": "OST_GenericModel", "generic model": "OST_GenericModel",
    "generic": "OST_GenericModel",
}

# --- Regex extractors for C# code patterns ---

RE_LOOKUP_PARAM = re.compile(r'LookupParameter\s*\(\s*"([^"]+)"\s*\)')
RE_SET_VALUE = re.compile(r'\.(Set|SetValueString)\s*\(')
RE_BUILTIN_CAT = re.compile(r'BuiltInCategory\.(OST_\w+)')
RE_ELEMENT_ID = re.compile(r'ElementId\s*\(\s*(\d+)\s*\)')
RE_CREATE_SCHEDULE = re.compile(r'ViewSchedule\.CreateSchedule')
RE_HIDE_ELEMENTS = re.compile(r'\.HideElements\s*\(')
RE_ISOLATE_ELEMENTS = re.compile(r'\.IsolateElementsTemporary\s*\(')
RE_NAME_ASSIGN = re.compile(r'\.Name\s*=\s*"([^"]*)"')
RE_SET_LITERAL = re.compile(
    r'\.(Set|SetValueString)\s*\(\s*(?:"([^"]*)"|(\d+(?:\.\d+)?))\s*\)'
)


def resolve_category(text: str) -> Optional[str]:
    """Resolve a category name (Russian or English) to BuiltInCategory.

    IQ-fix (2026-06-07): delegate to the canonical map in ``kukai.categories``
    (the documented single-source-of-truth, ~190 aliases), falling back to this
    module's own map only for any router-only aliases. Ends the two-maps drift
    the audit found (router vs chat_ws/shortcuts gave different answers) and
    widens query_model's synonym coverage with NO alias lost.
    """
    key = text.lower().strip()
    try:
        from kukai.categories import resolve_category as _canonical
        r = _canonical(key)
        if r:
            return r
    except Exception:  # noqa: BLE001 — fall back to the local map
        pass
    r = CATEGORY_TO_BUILTIN.get(key)
    if r:
        return r
    # Dictionary miss → semantic fallback (IQ-fix P1, flag-gated): resolve by
    # MEANING via embeddings so synonyms/typos/unlisted phrasings don't hard-fail
    # query_model. Conservative threshold → low confidence stays None.
    try:
        from kukai.config import CATEGORY_SEMANTIC, CATEGORY_SEMANTIC_THRESHOLD
        if CATEGORY_SEMANTIC and text and text.strip():
            from kukai.query.category_semantic import semantic_resolve
            hit = semantic_resolve(text, threshold=CATEGORY_SEMANTIC_THRESHOLD)
            if hit:
                return hit[0]
    except Exception:  # noqa: BLE001 — semantic is best-effort
        pass
    return None


def infer_deterministic_write(
    code: str,
    explanation: str = "",
    session_state: Any = None,
) -> Optional[dict[str, Any]]:
    """Analyze LLM-generated C# code and infer a deterministic write operation.

    If the code matches a known safe pattern, returns a dict describing
    the operation. Otherwise returns None (code should go through raw execution).

    Recognized patterns:
    - set_parameter: LookupParameter("X").Set(value) on a collection
    - create_schedule: ViewSchedule.CreateSchedule
    - hide_or_isolate: HideElements / IsolateElementsTemporary
    - rename_entities: .Name = "..."

    Returns None for complex code (multi-param, conditions, unrecognized).
    """
    if not code or not code.strip():
        return None

    # Extract data from code
    param_matches = RE_LOOKUP_PARAM.findall(code)
    set_matches = RE_SET_VALUE.findall(code)
    builtin_cats = RE_BUILTIN_CAT.findall(code)
    element_ids = [int(x) for x in RE_ELEMENT_ID.findall(code)]
    set_literals = RE_SET_LITERAL.findall(code)

    # Check for create_schedule
    if RE_CREATE_SCHEDULE.search(code):
        return {
            "operation": "create_schedule",
            "category": builtin_cats[0] if builtin_cats else None,
        }

    # Check for hide/isolate
    if RE_HIDE_ELEMENTS.search(code):
        return {
            "operation": "hide_or_isolate",
            "action": "hide",
            "element_ids": element_ids,
            "category": builtin_cats[0] if builtin_cats else None,
        }
    if RE_ISOLATE_ELEMENTS.search(code):
        return {
            "operation": "hide_or_isolate",
            "action": "isolate",
            "element_ids": element_ids,
            "category": builtin_cats[0] if builtin_cats else None,
        }

    # Check for rename
    name_assigns = RE_NAME_ASSIGN.findall(code)
    if name_assigns and not param_matches:
        return {
            "operation": "rename_entities",
            "new_name": name_assigns[0],
            "element_ids": element_ids,
            "category": builtin_cats[0] if builtin_cats else None,
        }

    # Check for set_parameter (single parameter + single value)
    if len(param_matches) == 1 and set_matches:
        param_name = param_matches[0]
        value = None

        if set_literals:
            # Extract the value from Set("value") or Set(123)
            _, str_val, num_val = set_literals[0]
            value = str_val if str_val else num_val

        # Get target IDs from session state if not in code
        target_ids = element_ids
        if not target_ids and session_state and hasattr(session_state, "working_set"):
            ws = session_state.working_set
            if ws.element_ids:
                target_ids = ws.element_ids

        category = builtin_cats[0] if builtin_cats else None
        if not category and session_state and hasattr(session_state, "working_set"):
            category = session_state.working_set.category

        return {
            "operation": "set_parameter",
            "parameter_name": param_name,
            "value": value,
            "element_ids": target_ids,
            "category": category,
        }

    # Multi-parameter or complex code — fall through to raw execution
    if len(param_matches) > 1:
        return None

    return None
