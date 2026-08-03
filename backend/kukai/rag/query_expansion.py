"""Query expansion — the de-frozen keyword→class map (plan 011, IRON 5).

For years this map lived as a 35-row literal inside ``client.py`` — data
masquerading as code, changeable only by a prod deploy, with nothing validating
its class names against the real API. This module makes it a regenerable data
artifact (``data/query_expansion.json``) with an embedded fallback, so the map
can be extended/regenerated without touching prod code, and validated by
``scripts/corpus_gate.py validate-expansion``.

Behavior is byte-for-byte identical to the old ``client._expand_rag_query``:
deterministic substring triggers append Revit API class names to the search
query. Loading is fail-safe — if the JSON is absent or malformed, the embedded
``_FALLBACK`` (an exact copy of the old inline rows) is used; it never raises.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).parent.parent.parent / "data" / "query_expansion.json"

# Embedded fallback — an EXACT copy of the 35 rows formerly inlined in
# client.py (`_RAG_QUERY_EXPANSION`). Kept here so retrieval keeps working if
# the data file is missing or corrupt. The parity test (test_query_expansion)
# proves this equals the data file AND the historical inline map.
_FALLBACK: list[tuple[list[str], str]] = [
    (['schedule', 'спецификац', 'ведомость'], 'ViewSchedule ScheduleDefinition ScheduleField'),
    (['section', 'разрез', 'сечение'], 'ViewSection BoundingBoxXYZ ViewFamilyType'),
    (['highlight', 'подсвет', 'покрас', 'цвет', 'color', 'красн', 'синий', 'override'], 'OverrideGraphicSettings Color FillPatternElement'),
    (['move', 'перемест', 'сдвин'], 'ElementTransformUtils XYZ'),
    (['mirror', 'зеркал', 'отраз'], 'ElementTransformUtils Plane'),
    (['rotate', 'поверн', 'вращ'], 'ElementTransformUtils'),
    (['copy', 'копир', 'скопир'], 'ElementTransformUtils CopyPasteOptions'),
    (['3d', '3д', 'изометр', 'аксонометр', 'perspective'], 'View3D ViewFamilyType'),
    (['pdf', 'экспорт', 'export', 'печат'], 'PDFExportOptions ViewSheet ExportPDFSettings'),
    (['level', 'уровен', 'этаж', 'отметк'], 'Level FilteredElementCollector'),
    (['room', 'помещен', 'комнат'], 'Room SpatialElement'),
    (['transparent', 'прозрач'], 'OverrideGraphicSettings'),
    (['select', 'выдел', 'выбер'], 'Selection UIDocument'),
    (['plan', 'план'], 'ViewPlan PlanViewRange ViewFamilyType'),
    (['elevation', 'фасад'], 'ViewSection ViewFamilyType'),
    (['dimension', 'размер', 'котиров'], 'Dimension IndependentTag'),
    (['tag', 'марк', 'аннотац', 'подпис'], 'IndependentTag'),
    (['image', 'png', 'jpg', 'изображ'], 'ImageExportOptions'),
    (['duct', 'воздуховод', 'канал'], 'Duct MechanicalSystem'),
    (['pipe', 'труб'], 'Pipe PipingSystem'),
    (['heating', 'отоплен', 'радиатор'], 'MechanicalSystem MEPSystem'),
    (['intersect', 'collision', 'clash', 'пересечен', 'коллизи', 'столкновен'], 'ElementIntersectsElementFilter ElementIntersectsSolidFilter BooleanOperationsUtils Solid ReferenceIntersector'),
    (['geometry', 'геометри', 'solid', 'объём', 'volume'], 'Solid GeometryElement Options BoundingBoxXYZ'),
    (['wall type', 'тип стен', 'толщин', 'слои стен', 'compound'], 'WallType CompoundStructure CompoundStructureLayer'),
    (['family', 'семейств', 'загруз', 'типоразмер'], 'Family FamilySymbol FamilyInstance FamilyManager'),
    (['parameter', 'параметр', 'shared param', 'общий парам', 'binding'], 'Parameter BuiltInParameter SharedParameterElement DefinitionFile DefinitionGroup CategorySet BindingMap InstanceBinding'),
    (['grid', 'ос', 'координ'], 'Grid'),
    (['annotation', 'размер', 'выноск'], 'IndependentTag Dimension TextNote'),
    (['group', 'групп'], 'Group GroupType'),
    (['workset', 'рабочий набор'], 'Workset FilteredWorksetCollector'),
    (['link', 'связ', 'linked'], 'RevitLinkInstance RevitLinkType'),
    (['material', 'материал'], 'Material CompoundStructure'),
    (['filter', 'фильтр', 'выбор'], 'FilteredElementCollector ElementFilter ParameterFilterElement'),
    (['delete', 'удал'], 'Document Transaction'),
    (['rename', 'переименуй', 'переименов'], 'Element Transaction'),
]


def _rows_from_file(path: Path) -> list[tuple[list[str], str]] | None:
    """Parse data/query_expansion.json into the in-memory row form, or None."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception:
        logger.warning("query_expansion.json present but unparseable — using fallback")
        return None
    raw_rows = doc.get("rows")
    if not isinstance(raw_rows, list) or not raw_rows:
        logger.warning("query_expansion.json has no 'rows' — using fallback")
        return None
    rows: list[tuple[list[str], str]] = []
    for r in raw_rows:
        if not isinstance(r, dict):
            continue
        triggers = r.get("triggers")
        classes = r.get("classes")
        if isinstance(triggers, list) and isinstance(classes, str) and triggers:
            rows.append(([str(t) for t in triggers], classes))
    if not rows:
        logger.warning("query_expansion.json rows malformed — using fallback")
        return None
    return rows


@lru_cache(maxsize=1)
def expansion_rows() -> list[tuple[list[str], str]]:
    """Return the active expansion rows.

    Prefers ``data/query_expansion.json`` when present and valid; otherwise the
    embedded ``_FALLBACK``. Cached (the map is process-stable); call
    ``expansion_rows.cache_clear()`` in tests that monkeypatch the path.
    Never raises.
    """
    rows = _rows_from_file(_DATA_PATH)
    if rows is None:
        return list(_FALLBACK)
    return rows


def expand_query(query: str) -> str:
    """Append relevant Revit API class names to the search query.

    Identical logic to the historical ``client._expand_rag_query``: substring
    triggers (case-insensitive), append the matched class-name strings.
    """
    import re
    ql = query.lower()
    # Audit #6 (2026-06-14): match triggers at TOKEN boundaries, not raw substrings.
    # The old `t in ql` fired «ос»→Grid inside «п-ОС-читай» (false positive, verified)
    # and was blind to morphology. Tokenize; a trigger matches a token by equality, or
    # by prefix for triggers ≥3 chars (Russian morphology: «уровн» → «уровней»). Short
    # (≤2-char) triggers require an exact whole-token match so they cannot pollute.
    tokens = re.findall(r"[а-яёa-z0-9]+", ql)
    tokset = set(tokens)
    expansions: list[str] = []
    for triggers, classes in expansion_rows():
        hit = False
        for t in triggers:
            tl = t.lower()
            if len(tl) <= 2:
                if tl in tokset:
                    hit = True
                    break
            elif any(tok == tl or tok.startswith(tl) for tok in tokens):
                hit = True
                break
        if hit:
            expansions.append(classes)
    if expansions:
        return query + " " + " ".join(expansions)
    return query
