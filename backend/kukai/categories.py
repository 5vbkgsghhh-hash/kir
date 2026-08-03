"""Single source of truth for Revit category mappings.

All modules that need category name resolution should import from here.
This prevents inconsistencies between shortcuts, router, session_state, and chat_ws.
"""

from __future__ import annotations

# Russian word forms -> BuiltInCategory OST_ name
# Includes nominative, genitive, accusative, instrumental, prepositional forms
CATEGORY_MAP: dict[str, str] = {
    # Walls
    "стена": "OST_Walls", "стены": "OST_Walls", "стен": "OST_Walls",
    "стенам": "OST_Walls", "стенами": "OST_Walls", "стенах": "OST_Walls",
    "wall": "OST_Walls", "walls": "OST_Walls",

    # Doors
    "дверь": "OST_Doors", "двери": "OST_Doors", "дверей": "OST_Doors",
    "дверям": "OST_Doors", "дверями": "OST_Doors", "дверях": "OST_Doors",
    "door": "OST_Doors", "doors": "OST_Doors",

    # Windows
    "окно": "OST_Windows", "окна": "OST_Windows", "окон": "OST_Windows",
    "окнам": "OST_Windows", "окнами": "OST_Windows", "окнах": "OST_Windows",
    "window": "OST_Windows", "windows": "OST_Windows",

    # Floors
    "пол": "OST_Floors", "полы": "OST_Floors", "полов": "OST_Floors",
    "перекрытие": "OST_Floors", "перекрытия": "OST_Floors", "перекрытий": "OST_Floors",
    "floor": "OST_Floors", "floors": "OST_Floors",

    # Ceilings
    "потолок": "OST_Ceilings", "потолки": "OST_Ceilings", "потолков": "OST_Ceilings",
    "ceiling": "OST_Ceilings", "ceilings": "OST_Ceilings",

    # Roofs
    "крыша": "OST_Roofs", "крыши": "OST_Roofs", "крыш": "OST_Roofs",
    "кровля": "OST_Roofs", "кровли": "OST_Roofs",
    "roof": "OST_Roofs", "roofs": "OST_Roofs",

    # Stairs
    "лестница": "OST_Stairs", "лестницы": "OST_Stairs", "лестниц": "OST_Stairs",
    "stair": "OST_Stairs", "stairs": "OST_Stairs",

    # Rooms
    "комната": "OST_Rooms", "комнаты": "OST_Rooms", "комнат": "OST_Rooms",
    "помещение": "OST_Rooms", "помещения": "OST_Rooms", "помещений": "OST_Rooms",
    "room": "OST_Rooms", "rooms": "OST_Rooms",

    # Columns (structural -- this is the correct category for BIM)
    "колонна": "OST_StructuralColumns", "колонны": "OST_StructuralColumns",
    "колонн": "OST_StructuralColumns",
    "column": "OST_StructuralColumns", "columns": "OST_StructuralColumns",

    # Beams / Structural Framing
    "балка": "OST_StructuralFraming", "балки": "OST_StructuralFraming",
    "балок": "OST_StructuralFraming",
    "beam": "OST_StructuralFraming", "beams": "OST_StructuralFraming",

    # Pipes
    "труба": "OST_PipeCurves", "трубы": "OST_PipeCurves", "труб": "OST_PipeCurves",
    "pipe": "OST_PipeCurves", "pipes": "OST_PipeCurves",

    # Ducts
    "воздуховод": "OST_DuctCurves", "воздуховоды": "OST_DuctCurves",
    "воздуховодов": "OST_DuctCurves",
    "duct": "OST_DuctCurves", "ducts": "OST_DuctCurves",

    # Levels
    "уровень": "OST_Levels", "уровни": "OST_Levels", "уровней": "OST_Levels",
    "level": "OST_Levels", "levels": "OST_Levels",

    # Views
    "вид": "OST_Views", "виды": "OST_Views", "видов": "OST_Views",
    "view": "OST_Views", "views": "OST_Views",

    # Grids
    "ось": "OST_Grids", "оси": "OST_Grids", "осей": "OST_Grids",
    "grid": "OST_Grids", "grids": "OST_Grids",

    # Sheets
    "лист": "OST_Sheets", "листы": "OST_Sheets", "листов": "OST_Sheets",
    "sheet": "OST_Sheets", "sheets": "OST_Sheets",

    # Furniture
    "мебель": "OST_Furniture",
    "furniture": "OST_Furniture",

    # Lighting
    "светильник": "OST_LightingFixtures", "светильники": "OST_LightingFixtures",
    "светильников": "OST_LightingFixtures",
    "light": "OST_LightingFixtures", "lights": "OST_LightingFixtures",

    # Railings
    "перило": "OST_StairsRailing", "перила": "OST_StairsRailing",
    "ограждение": "OST_StairsRailing", "ограждения": "OST_StairsRailing",
    "railing": "OST_StairsRailing", "railings": "OST_StairsRailing",

    # --- MEP: Electrical ---
    "розетка": "OST_ElectricalFixtures", "розетки": "OST_ElectricalFixtures",
    "розеток": "OST_ElectricalFixtures", "выключатель": "OST_ElectricalFixtures",
    "выключатели": "OST_ElectricalFixtures",
    "outlet": "OST_ElectricalFixtures", "switch": "OST_ElectricalFixtures",

    "электрощит": "OST_ElectricalEquipment", "щит": "OST_ElectricalEquipment",
    "щиты": "OST_ElectricalEquipment", "электрооборудование": "OST_ElectricalEquipment",
    "панель": "OST_ElectricalEquipment",
    "panel": "OST_ElectricalEquipment", "switchboard": "OST_ElectricalEquipment",

    "кабельный лоток": "OST_CableTray", "лоток": "OST_CableTray",
    "лотки": "OST_CableTray", "лотков": "OST_CableTray",
    "cable tray": "OST_CableTray", "tray": "OST_CableTray",

    "кабелепровод": "OST_Conduit", "кондуит": "OST_Conduit",
    "conduit": "OST_Conduit", "conduits": "OST_Conduit",

    "провод": "OST_Wire", "провода": "OST_Wire", "проводка": "OST_Wire",
    "wire": "OST_Wire", "wires": "OST_Wire",

    "цепь": "OST_ElectricalCircuit", "цепи": "OST_ElectricalCircuit",
    "электроцепь": "OST_ElectricalCircuit",
    "circuit": "OST_ElectricalCircuit", "circuits": "OST_ElectricalCircuit",

    # --- MEP: Mechanical/HVAC ---
    "оборудование": "OST_MechanicalEquipment",
    "вентустановка": "OST_MechanicalEquipment",
    "кондиционер": "OST_MechanicalEquipment",
    "equipment": "OST_MechanicalEquipment",

    "фитинг": "OST_DuctFitting", "фитинги воздуховодов": "OST_DuctFitting",
    "duct fitting": "OST_DuctFitting",

    "диффузор": "OST_DuctTerminal", "решётка": "OST_DuctTerminal",
    "воздухораспределитель": "OST_DuctTerminal",
    "air terminal": "OST_DuctTerminal", "diffuser": "OST_DuctTerminal",

    "изоляция воздуховода": "OST_DuctInsulations",
    "duct insulation": "OST_DuctInsulations",

    "гибкий воздуховод": "OST_FlexDuctCurves",
    "flex duct": "OST_FlexDuctCurves",

    "пространство": "OST_MEPSpaces", "пространства": "OST_MEPSpaces",
    "space": "OST_MEPSpaces", "spaces": "OST_MEPSpaces",

    # --- MEP: Plumbing ---
    "сантехника": "OST_PlumbingFixtures", "раковина": "OST_PlumbingFixtures",
    "унитаз": "OST_PlumbingFixtures", "умывальник": "OST_PlumbingFixtures",
    "plumbing fixture": "OST_PlumbingFixtures", "sink": "OST_PlumbingFixtures",

    "фитинг трубы": "OST_PipeFitting", "фитинги труб": "OST_PipeFitting",
    "pipe fitting": "OST_PipeFitting",

    "задвижка": "OST_PipeAccessory", "клапан": "OST_PipeAccessory",
    "вентиль": "OST_PipeAccessory", "арматура трубопроводная": "OST_PipeAccessory",
    "valve": "OST_PipeAccessory", "pipe accessory": "OST_PipeAccessory",

    "изоляция трубы": "OST_PipeInsulations",
    "pipe insulation": "OST_PipeInsulations",

    "спринклер": "OST_Sprinklers", "спринклеры": "OST_Sprinklers",
    "ороситель": "OST_Sprinklers", "оросители": "OST_Sprinklers",
    "sprinkler": "OST_Sprinklers", "sprinklers": "OST_Sprinklers",

    # --- MEP: Fire/Security/Data ---
    "извещатель": "OST_FireAlarmDevices", "пожарный датчик": "OST_FireAlarmDevices",
    "пожарная сигнализация": "OST_FireAlarmDevices",
    "fire alarm": "OST_FireAlarmDevices", "detector": "OST_FireAlarmDevices",

    "камера": "OST_SecurityDevices", "видеонаблюдение": "OST_SecurityDevices",
    "security": "OST_SecurityDevices", "cctv": "OST_SecurityDevices",

    "датчик": "OST_DataDevices",
    "data device": "OST_DataDevices",

    # --- Structural ---
    "фундамент": "OST_StructuralFoundation", "фундаменты": "OST_StructuralFoundation",
    "фундаментов": "OST_StructuralFoundation",
    "foundation": "OST_StructuralFoundation", "foundations": "OST_StructuralFoundation",

    "арматура": "OST_Rebar", "армирование": "OST_Rebar",
    "стержень": "OST_Rebar", "стержни": "OST_Rebar",
    "rebar": "OST_Rebar", "reinforcement": "OST_Rebar",

    "ферма": "OST_StructuralTruss", "фермы": "OST_StructuralTruss",
    "truss": "OST_StructuralTruss",

    # --- Architecture extras ---
    "пандус": "OST_Ramps", "пандусы": "OST_Ramps",
    "ramp": "OST_Ramps", "ramps": "OST_Ramps",

    "витраж": "OST_CurtainWallPanels", "витражи": "OST_CurtainWallPanels",
    "curtain panel": "OST_CurtainWallPanels",

    "импост": "OST_CurtainWallMullions",
    "mullion": "OST_CurtainWallMullions",

    "зона": "OST_Areas", "зоны": "OST_Areas",
    "area": "OST_Areas", "areas": "OST_Areas",

    # --- Site ---
    "парковка": "OST_Parking", "парковки": "OST_Parking",
    "parking": "OST_Parking",

    "озеленение": "OST_Planting", "дерево": "OST_Planting",
    "planting": "OST_Planting",

    "рельеф": "OST_Topography", "топография": "OST_Topography",
    "topography": "OST_Topography",

    # --- General ---
    "материал": "OST_Materials", "материалы": "OST_Materials",
    "material": "OST_Materials", "materials": "OST_Materials",

    "связь": "OST_RvtLinks", "связи": "OST_RvtLinks",
    "линк": "OST_RvtLinks",
    "link": "OST_RvtLinks", "links": "OST_RvtLinks",
}


# --- Lemma lexicon (flag KUKAI_LEMMA_LEXICON, IQ-moment #7) -----------------
# CATEGORY_MAP hand-enumerates case forms and has PROVEN holes («стене»,
# «стеной», «окне», «дверью» are missing — 2026-07-04 audit §1.3). Under the
# flag, lookups fall back to a lemma-keyed view of the SAME table: keys are
# derived from CATEGORY_MAP at first use (never hand-written), so whole
# declension paradigms resolve by construction. The exact surface-form lookup
# always runs FIRST — flag ON is a strict superset of flag OFF; flag OFF is
# byte-identical legacy behavior (the lemma map is not even built).

_LEMMA_CATEGORY_MAP: dict[str, str] | None = None


def _lemma_category_map() -> dict[str, str]:
    """Build (once) the lemma-keyed view of CATEGORY_MAP.

    First-wins on lemma collisions (insertion order of CATEGORY_MAP), which
    keeps the same precedence the surface table already encodes.
    """
    global _LEMMA_CATEGORY_MAP
    lemma_map = _LEMMA_CATEGORY_MAP
    if lemma_map is None:
        from kukai.nlp.lemma import lemma_phrase

        lemma_map = {}
        for surface, ost in CATEGORY_MAP.items():
            lemma_map.setdefault(lemma_phrase(surface), ost)
        _LEMMA_CATEGORY_MAP = lemma_map
    return lemma_map


def _lemma_lookup(phrase: str) -> str | None:
    """Lemma-keyed lookup of one (possibly multi-word) phrase; never raises."""
    try:
        from kukai.nlp.lemma import lemma_phrase

        return _lemma_category_map().get(lemma_phrase(phrase))
    except Exception:  # noqa: BLE001 — morphology is best-effort, never breaks
        return None


def _lemma_enabled() -> bool:
    """KUKAI_LEMMA_LEXICON flag, read at call time; never raises."""
    try:
        from kukai.nlp.lemma import lemma_lexicon_enabled

        return lemma_lexicon_enabled()
    except Exception:  # noqa: BLE001 — missing module ⇒ legacy behavior
        return False


def resolve_category(text: str) -> str | None:
    """Resolve a Russian/English category name to BuiltInCategory OST_ string.

    Case-insensitive lookup. Returns None if not found. With
    ``KUKAI_LEMMA_LEXICON=1`` a dictionary miss falls back to the lemma-keyed
    view of the same table («дверью» → «дверь» → OST_Doors).
    """
    key = text.lower().strip()
    hit = CATEGORY_MAP.get(key)
    if hit is not None:
        return hit
    if _lemma_enabled():
        return _lemma_lookup(key)
    return None


def find_category_in_text(text: str) -> str | None:
    """Find the first category mention in a text string.

    Scans n-grams (3-word, 2-word, 1-word) against CATEGORY_MAP
    to support multi-word entries like "кабельный лоток".
    Returns the OST_ category or None. With ``KUKAI_LEMMA_LEXICON=1`` each
    n-gram is also checked by lemma (exact match keeps priority per n-gram),
    so «на этой стене» finds OST_Walls.
    """
    lower = text.lower()
    words = lower.split()
    cleaned = [w.strip(".,!?;:\"'()[]{}«»") for w in words]
    use_lemma = _lemma_enabled()

    # Check 3-word, 2-word, then 1-word phrases (longest match wins)
    for n in (3, 2, 1):
        for i in range(len(cleaned) - n + 1):
            phrase = " ".join(cleaned[i:i + n])
            result = CATEGORY_MAP.get(phrase)
            if result:
                return result
            if use_lemma:
                result = _lemma_lookup(phrase)
                if result:
                    return result

    return None
