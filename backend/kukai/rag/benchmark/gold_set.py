"""Gold-set of Revit-task queries for RAG benchmark.

Each entry has:
- query: natural-language request (English only — production translates RU→EN
  before retrieval; the index never sees Cyrillic)
- intent: query | create | modify | delete | export | analyze
- expected_apis: API class/method names that any decent retrieval should surface
- expected_snippet_ids: stable corpus IDs that should appear in top-K
  (format: "entry_type:namespace.Name", matching RagPath.retrieved_ids)
- complexity: simple | multi_step | version_specific | project_aware

GOLD_SET_STARTER — original 15 entries (10 from CRITICAL_QUERIES + 5
production-derived). Kept stable for backward-compat with existing benchmark
runs.

GOLD_SET_FULL — 32 entries: starter (15) + extended (17) across MEP (3),
annotation (3), QA/QC (2), filter+report (2), schedule variants (2),
family (2), geometry/spatial (2), and project-level (1). Brief asked for
"30 with broader coverage"; the explicit category list sums to 17 so the
final total is 32 — the category list is treated as the binding spec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Intent = Literal["query", "create", "modify", "delete", "export", "analyze"]
Complexity = Literal["simple", "multi_step", "version_specific", "project_aware"]


@dataclass
class GoldQuery:
    query: str
    intent: Intent
    expected_apis: list[str]
    expected_snippet_ids: list[str] = field(default_factory=list)
    complexity: Complexity = "simple"
    notes: str = ""

    def __post_init__(self) -> None:
        # Make Hit@K non-vacuous without hand-curating stable snippet IDs for all 32
        # queries: default the gold snippet set to the expected APIs. matches_id()
        # suffix-matches on `.Name`, so a retrieved "class:Autodesk.Revit.DB.Wall"
        # matches expected "Wall". Hit@1/Hit@5 then measure "did the top-1/5 retrieved
        # include an expected API" — a real top-K signal (was always 0.0 before, since
        # runner.py guards `if q.expected_snippet_ids`). Explicit IDs still override.
        if not self.expected_snippet_ids:
            self.expected_snippet_ids = list(self.expected_apis)

    def matches_id(self, retrieved_id: str) -> bool:
        """Fuzzy match: retrieved_id is "entry_type:namespace.Name". Compare on
        the .Name suffix because namespaces drift between corpus versions."""
        if retrieved_id in self.expected_snippet_ids:
            return True
        ret_name = retrieved_id.rsplit(".", 1)[-1] if "." in retrieved_id else retrieved_id
        for expected in self.expected_snippet_ids:
            exp_name = expected.rsplit(".", 1)[-1] if "." in expected else expected
            if ret_name == exp_name:
                return True
        return False


# --- Starter gold-set (15 queries) ---------------------------------------
# Borrowed from tests/test_rag.py CRITICAL_QUERIES + production patterns.
# expected_apis is the most important field for retrieval-only benchmark —
# expected_snippet_ids matters once we have stable corpus IDs.

GOLD_SET_STARTER: list[GoldQuery] = [
    # --- Simple query (10 from CRITICAL_QUERIES) ---
    GoldQuery(
        query="find all walls",
        intent="query",
        expected_apis=["Wall", "FilteredElementCollector"],
        complexity="simple",
    ),
    GoldQuery(
        query="create wall schedule",
        intent="create",
        expected_apis=["ViewSchedule", "ScheduleDefinition", "ScheduleField"],
        complexity="simple",
    ),
    GoldQuery(
        query="highlight red elements",
        intent="modify",
        expected_apis=["OverrideGraphicSettings", "Color", "FillPatternElement"],
        complexity="simple",
    ),
    GoldQuery(
        query="move element",
        intent="modify",
        expected_apis=["ElementTransformUtils", "XYZ"],
        complexity="simple",
    ),
    GoldQuery(
        query="find all rooms",
        intent="query",
        expected_apis=["Room", "SpatialElement", "FilteredElementCollector"],
        complexity="simple",
    ),
    GoldQuery(
        query="export sheets to PDF",
        intent="export",
        expected_apis=["ExportPDFSettings", "PDFExportOptions", "ViewSheet"],
        complexity="simple",
    ),
    GoldQuery(
        query="create 3D view",
        intent="create",
        expected_apis=["View3D", "ViewFamilyType"],
        complexity="simple",
    ),
    GoldQuery(
        query="get current selection",
        intent="query",
        expected_apis=["Selection", "UIDocument"],
        complexity="simple",
    ),
    GoldQuery(
        query="filter ducts",
        intent="query",
        expected_apis=["Duct", "MechanicalSystem", "FilteredElementCollector"],
        complexity="simple",
    ),
    GoldQuery(
        query="place family instance",
        intent="create",
        expected_apis=["FamilyInstance", "FamilySymbol"],
        complexity="simple",
    ),
    # --- Multi-step (production-derived) ---
    # All queries in English: production translates RU→EN before retrieval
    # (client.py:_translate_for_rag) and the index never sees Cyrillic.
    GoldQuery(
        query="find walls with length greater than 5 meters and set Mark parameter",
        intent="modify",
        expected_apis=[
            "Wall", "FilteredElementCollector", "Transaction",
            "BuiltInParameter", "Parameter",
        ],
        complexity="multi_step",
        notes="Filter + modify with transaction (RU origin: 'найди стены длиной больше 5 метров и помечь Mark').",
    ),
    GoldQuery(
        query="filter walls by type WallType_120 and change phase",
        intent="modify",
        expected_apis=[
            "Wall", "WallType", "FilteredElementCollector", "Transaction", "Phase",
        ],
        complexity="multi_step",
        notes="Type-based filtering + parameter modify.",
    ),
    GoldQuery(
        query="create wall schedule with phase filter and length and type fields",
        intent="create",
        expected_apis=[
            "ViewSchedule", "ScheduleDefinition", "ScheduleField",
            "ScheduleFilter", "BuiltInCategory",
        ],
        complexity="multi_step",
        notes="Schedule with custom fields + filters (RU origin: 'создай спецификацию по стенам с фильтром по фазе и поля длина и тип').",
    ),
    # --- Version-specific ---
    GoldQuery(
        query="get element id as long value",
        intent="query",
        expected_apis=["ElementId"],
        complexity="version_specific",
        notes="Should surface ElementId.Value (2024+) not IntegerValue.",
    ),
    # --- Analyze / multi-class ---
    GoldQuery(
        query="find collisions between walls and pipes",
        intent="analyze",
        expected_apis=[
            "ElementIntersectsElementFilter", "FilteredElementCollector",
            "Wall", "Pipe",
        ],
        complexity="multi_step",
        notes="Clash detection (RU origin: 'найди коллизии стен и труб').",
    ),
]


# --- Extended gold-set (17 additional queries, total 32) -----------------
# Categories: MEP (3), Annotation (3), QA/QC (2), Filter+report (2),
# Schedule variants (2), Family (2), Geometry/spatial (2), Project-level (1).
# All queries in English (production translates RU→EN before retrieval).

_GOLD_SET_EXTENDED: list[GoldQuery] = [
    # --- MEP (3) ---
    GoldQuery(
        query="create a pipe between two points and assign it to a piping system",
        intent="create",
        expected_apis=[
            "Pipe", "PipingSystem", "PipingSystemType", "XYZ", "Transaction",
        ],
        complexity="multi_step",
        notes="MEP pipe creation with system assignment "
              "(RU origin: 'создай трубу между двумя точками и присвой её системе').",
    ),
    GoldQuery(
        query="route a duct from one connector to another with a given duct type",
        intent="create",
        expected_apis=[
            "Duct", "DuctType", "Connector", "MechanicalSystem", "Transaction",
        ],
        complexity="multi_step",
        notes="Duct routing between connectors "
              "(RU origin: 'проложи воздуховод между двумя коннекторами с заданным типом').",
    ),
    GoldQuery(
        query="filter all elements belonging to a specific MEP system by system name",
        intent="query",
        expected_apis=[
            "MEPSystem", "MechanicalSystem", "PipingSystem",
            "FilteredElementCollector", "BuiltInParameter",
        ],
        complexity="multi_step",
        notes="Filter elements by MEP system "
              "(RU origin: 'найди все элементы инженерной системы по имени').",
    ),

    # --- Annotation (3) ---
    GoldQuery(
        query="create a dimension between two elements in the active view",
        intent="create",
        expected_apis=[
            "Dimension", "DimensionType", "ReferenceArray",
            "Transaction", "View",
        ],
        complexity="multi_step",
        notes="Place linear dimension between two element references "
              "(RU origin: 'создай размер между двумя элементами на активном виде').",
    ),
    GoldQuery(
        query="tag all walls in the current view with their type mark",
        intent="create",
        expected_apis=[
            "IndependentTag", "Wall", "FilteredElementCollector",
            "Transaction", "View",
        ],
        complexity="multi_step",
        notes="Bulk wall tagging in active view "
              "(RU origin: 'промаркируй все стены на текущем виде').",
    ),
    GoldQuery(
        query="place a text note at a point with custom text and text type",
        intent="create",
        expected_apis=[
            "TextNote", "TextNoteType", "TextNoteOptions", "XYZ", "Transaction",
        ],
        complexity="simple",
        notes="Text annotation placement "
              "(RU origin: 'поставь текстовую заметку в точке с заданным текстом').",
    ),

    # --- QA/QC (2) ---
    GoldQuery(
        query="generate clash detection report grouped by category",
        intent="analyze",
        expected_apis=[
            "ElementIntersectsElementFilter", "ElementIntersectsSolidFilter",
            "FilteredElementCollector", "BuiltInCategory", "Element",
        ],
        complexity="multi_step",
        notes="Clash report by category "
              "(RU origin: 'отчёт о коллизиях с группировкой по категориям').",
    ),
    GoldQuery(
        query="find walls where the Mark parameter is empty or not set",
        intent="analyze",
        expected_apis=[
            "Wall", "FilteredElementCollector", "BuiltInParameter", "Parameter",
        ],
        complexity="multi_step",
        notes="QA/QC: parameter-naming-convention check for empty Mark "
              "(RU origin: 'найди стены без заполненного параметра Марка').",
    ),

    # --- Filter+report (2) ---
    GoldQuery(
        query="group walls by level and report total length per level",
        intent="analyze",
        expected_apis=[
            "Wall", "Level", "FilteredElementCollector", "BuiltInParameter",
        ],
        complexity="multi_step",
        notes="Filter+aggregate: walls grouped by level with totals "
              "(RU origin: 'сгруппируй стены по уровням и посчитай суммарную длину').",
    ),
    GoldQuery(
        query="sum total area of all rooms in the project",
        intent="analyze",
        expected_apis=[
            "Room", "SpatialElement", "FilteredElementCollector", "BuiltInParameter",
        ],
        complexity="simple",
        notes="Aggregate room areas "
              "(RU origin: 'посчитай суммарную площадь всех помещений проекта').",
    ),

    # --- Schedule variants (2) ---
    GoldQuery(
        query="create a material takeoff schedule for walls with quantity and material name",
        intent="create",
        expected_apis=[
            "ViewSchedule", "ScheduleDefinition", "ScheduleField", "BuiltInCategory",
        ],
        complexity="multi_step",
        notes="Material takeoff schedule "
              "(RU origin: 'создай ведомость материалов по стенам с объёмом и названием материала').",
    ),
    GoldQuery(
        query="create a sheet list schedule with sheet number and current revision fields",
        intent="create",
        expected_apis=[
            "ViewSchedule", "ScheduleDefinition", "ScheduleField",
            "ViewSheet", "Revision",
        ],
        complexity="multi_step",
        notes="Sheet list with revision column "
              "(RU origin: 'создай ведомость листов с номером листа и текущей ревизией').",
    ),

    # --- Family (2) ---
    GoldQuery(
        query="load a family from an rfa file path and place an instance at a point",
        intent="create",
        expected_apis=[
            "Family", "FamilySymbol", "FamilyInstance", "XYZ", "Transaction",
        ],
        complexity="multi_step",
        notes="Load family + place instance "
              "(RU origin: 'загрузи семейство из файла и расставь экземпляр в точке').",
    ),
    GoldQuery(
        query="place a family instance and set several instance parameters after creation",
        intent="create",
        expected_apis=[
            "FamilyInstance", "FamilySymbol", "Parameter", "BuiltInParameter",
            "Transaction",
        ],
        complexity="multi_step",
        notes="Create instance + set parameters "
              "(RU origin: 'размести экземпляр семейства и задай параметры').",
    ),

    # --- Geometry/spatial (2) ---
    GoldQuery(
        query="get the bounding box of the current selection",
        intent="query",
        expected_apis=[
            "BoundingBoxXYZ", "Selection", "UIDocument", "Element", "XYZ",
        ],
        complexity="simple",
        notes="Bounding box of selected elements "
              "(RU origin: 'получи габаритный бокс текущего выделения').",
    ),
    GoldQuery(
        query="find all elements located inside a given room",
        intent="query",
        expected_apis=[
            "Room", "BoundingBoxIntersectsFilter", "FilteredElementCollector",
            "Outline", "BoundingBoxXYZ",
        ],
        complexity="multi_step",
        notes="Spatial containment: elements inside room "
              "(RU origin: 'найди все элементы, расположенные внутри помещения').",
    ),

    # --- Project-level (1) ---
    GoldQuery(
        query="create a new level at a given elevation",
        intent="create",
        expected_apis=["Level", "Transaction", "Document"],
        complexity="simple",
        notes="Project-level: new Level at elevation "
              "(RU origin: 'создай новый уровень на заданной отметке').",
    ),
]


GOLD_SET_FULL: list[GoldQuery] = GOLD_SET_STARTER + _GOLD_SET_EXTENDED
# Sanity check on the extended set size; the category breakdown above is the
# binding spec, not the round number "30".
assert len(GOLD_SET_FULL) == 32, f"Expected 32 gold queries, got {len(GOLD_SET_FULL)}"
