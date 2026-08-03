"""Repair knowledge: error-hint tables + pure classifiers (extracted from client.py).

Pure relocation (2026-07-04 client.py decomposition, Step 1): every body below
is byte-identical to its previous definition in ``kukai/llm/client.py``.
``client.py`` re-exports all names (and rebinds ``_is_compilation_error`` /
``_get_repair_hint`` as ``LLMClient`` staticmethods) so every existing importer
and test keeps working unchanged.

Deliberately a SIBLING of ``repair_hints.py`` — do NOT merge them: the two
tables feed different prompts, and merging changes prompt bytes = behavior
(see the decomposition plan, section 2). Stateless: data + pure functions.

Repair-pair mining (IQ moment N1, 2026-07-06) — ADDITIVE section at the bottom
of this module, everything gated by ``KUKAI_REPAIR_MINING`` (default OFF ⇒
byte-identical prompts, zero telemetry writes):

  * ``record_repair_pair`` — capture side: persists a verified (broken→fixed)
    pair at the pipeline's repair-success moment via the existing async-safe
    ``kukai.telemetry_rag`` background writer → data/telemetry/repair_pairs.jsonl.
  * ``error_signature`` — the ONE error-class definition shared by capture,
    the offline miner (scripts/mine_repair_pairs.py) and retrieval.
  * ``scrub_snippet`` — cross-tenant hygiene: strips string literals, comments
    and user-declared identifiers from exemplars while keeping API names and
    code structure. The playbook is the only cross-tenant artifact; raw pairs
    stay server-side like every other telemetry stream.
  * ``get_playbook_hint`` — retrieval hook: exact-signature (confident) match
    against data/rag/repair_playbook.json → a bounded ≤600-char hint that
    ``_get_repair_hint`` appends, so BOTH repair paths (legacy client.py loop
    and RevitExecutionPipeline, whose ``llm_repair`` delegates to
    ``LLMClient._repair_code``) receive it through this single seam.

The relocated bodies above the mining section stay byte-identical to the
decomposition except the flag-gated tail of ``_get_repair_hint``.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_RUNTIME_ERROR_HINTS: list[tuple[str, str]] = [
    # ─── ORDERING POLICY: most specific triggers FIRST, broad fallbacks LAST ───
    # _enrich_runtime_error scans top-to-bottom and returns on first match.
    # Roslyn's CS1061 errors ALL contain "no accessible extension method" (it's a
    # generic suffix on every missing-member error, not just LINQ), so the broad
    # LINQ hint MUST come AFTER specific class-name hints — otherwise it shadows
    # them and we serve the wrong advice.

    # ─── PROD HALLUCINATIONS (mined 2026-05-13 from 24h compile-fail log) ───
    # Each hint targets a specific Gemini-invented API that the deterministic
    # fixer can't fix automatically (multi-line refactor needed). Triggered on
    # repair-loop attempt 2/3 when first regex didn't help. MUST come BEFORE
    # the broad "no accessible extension method" trigger to avoid shadowing.

    # View3D shadow properties — 4 cases in 24h
    ("shadowsvisible",
     "View3D.ShadowsVisible/ShadowsDisplay/EnableShadows do NOT exist. "
     "Use view3D.GetSunAndShadowSettings() to read settings, then "
     "Document.SetSunAndShadowSettings(...) inside a Transaction to update. "
     "Shadow visibility is also controlled via DisplayStyle (view.DisplayStyle = DisplayStyle.Shading)."),
    ("shadowsdisplay",
     "View3D.ShadowsDisplay does NOT exist. Use view3D.GetSunAndShadowSettings() "
     "for read; for show/hide shadows use view.DisplayStyle = DisplayStyle.ShadingWithEdges."),
    ("enableshadows",
     "View3D.EnableShadows does NOT exist. Set view.DisplayStyle to a style that "
     "includes shadows (ShadingWithEdges) or use SunAndShadowSettings."),
    ("isorientationlocked",
     "View3D.IsOrientationLocked does NOT exist. Orientation lock state is "
     "managed via view3D.IsLocked (read-only). To lock/unlock use "
     "view3D.SaveOrientationAndLock() / RestoreOrientationAndUnlock()."),

    # RevitLinkGraphicsSettings — 5 cases in 24h (multiple wrong method names)
    ("revitlinkgraphicssettings",
     "RevitLinkGraphicsSettings has NO methods GetCategoryHidden / "
     "IsCategoryHidden / LinkVisibility. To hide categories in a linked view, "
     "use view.SetCategoryHidden(catId, true) on the host view; for finer "
     "control use OverrideGraphicSettings via "
     "view.SetCategoryOverrides(catId, ogs). Read via view.GetCategoryHidden(catId)."),

    # RebarShapeDrivenAccessor — 3 cases in 24h
    ("setlayoutfixedspacing",
     "RebarShapeDrivenAccessor has NO SetLayoutFixedSpacing method. "
     "Use one of: SetLayoutAsFixedNumber(numberOfBars, arrayLength, ...) — "
     "fixed count with calculated spacing, OR "
     "SetLayoutAsMaximumSpacing(spacing, arrayLength, ...) — fixed max spacing, OR "
     "SetLayoutAsMinimumClearSpacing(spacing, arrayLength, ...). "
     "Each takes (double spacingOrCount, double arrayLength, bool barsOnNormalSide, "
     "bool includeFirstBar, bool includeLastBar)."),

    # Document.NewModelCurveLoop — 2 cases in 24h
    ("newmodelcurveloop",
     "Document.NewModelCurveLoop does NOT exist. Create model curves one at a time "
     "with Document.Create.NewModelCurve(curve, sketchPlane) inside a foreach. "
     "Wrap in a single Transaction for atomicity."),

    # View.CanModifyVisibility — 2 cases in 24h
    ("canmodifyvisibility",
     "View.CanModifyVisibility does NOT exist. Use "
     "view.CanCategoryBeHidden(categoryId) to check if a specific category can be "
     "hidden in this view. View-level visibility is governed by view.ViewTemplateId "
     "(if set, most overrides are read-only)."),

    # RevitLinkInstance.GetCorrespondingPhaseId — 2 cases in 24h
    ("getcorrespondingphaseid",
     "RevitLinkInstance has NO GetCorrespondingPhaseId. Phase mapping is read via "
     "linkInstance.GetLinkDocument().Phases (linked phases) and host doc Phases. "
     "Match by name or order: hostDoc.Phases[i].Id corresponds to linkDoc.Phases[i].Id."),

    # FootPrintRoof methods — 2 cases in 24h
    ("getboundarycurve",
     "FootPrintRoof.GetBoundaryCurve does NOT exist. Use roof.GetProfiles() which "
     "returns ModelCurveArrArray (one CurveArray per loop in the boundary). "
     "For the sketch itself use roof.SketchId or doc.GetElement(roof.SketchId) as Sketch."),

    # Family.IsShared — 1 case (substring trigger: error text contains
    # "'Family' does not contain a definition for 'IsShared'")
    ("isshared",
     "Family.IsShared does NOT exist. Use family.FamilyCategory.IsSharedFamily "
     "for type check; alternatively read parameter "
     "family.get_Parameter(BuiltInParameter.FAMILY_SHARED).AsInteger() == 1."),

    # LinkElementId.ElementId — 1 case (no det.fix because regex would clobber Reference.ElementId)
    ("linkelementid",
     "LinkElementId has NO .ElementId property. Use .LinkedElementId for the "
     "element id INSIDE the linked document, and .HostElementId for the host-side "
     "instance id. Critically: do NOT global-replace .ElementId — Reference.ElementId "
     "(from uidoc.Selection.PickObject etc) is a VALID API and must be preserved."),

    # IEnumerable<Element>.GetElementCount — 1 case (no det.fix because regex would
    # clobber FEC.GetElementCount(), which is valid)
    ("ienumerable<element>",
     "After a LINQ chain (Where/Select/OfType) you can NOT call .GetElementCount() — "
     "that's a FilteredElementCollector method. Use System.Linq .Count() on the "
     "IEnumerable<T> result. Note: FilteredElementCollector itself does NOT support "
     ".Count() (non-generic IEnumerable) — keep fec.GetElementCount() for raw FEC, "
     "but use .Count() AFTER you've applied .OfType<T>() or another LINQ method."),

    # CompoundStructure family — 3+ cases on 2026-05-14
    # (also covered by det.fixer for IsCompound, but hint helps repair-loop
    # when fixer didn't run for some reason)
    ("'iscompound'",
     "CompoundStructure.IsCompound does NOT exist — it's a tautological property "
     "(if you have a CompoundStructure object, it IS compound by definition). "
     "To check 'has more than one layer' use cs.LayerCount > 1. "
     "To check 'wallType has compound structure' use wallType.GetCompoundStructure() != null."),
    ("'canhavestructuraldeck'",
     "CompoundStructure.CanHaveStructuralDeck does NOT exist. Iterate layers via "
     "cs.GetLayers() and check each layer.Function == "
     "MaterialFunctionAssignment.StructuralDeck. Example: "
     "bool hasDeck = cs.GetLayers().Any(l => l.Function == MaterialFunctionAssignment.StructuralDeck);"),
    ("'insertlayer'",
     "CompoundStructure has NO InsertLayer method. To add a layer: 1) get current "
     "layers via cs.GetLayers() → IList<CompoundStructureLayer>; 2) build new "
     "List<CompoundStructureLayer> with extra layer at desired index; 3) call "
     "cs.SetLayers(newList). Example to prepend a finish layer: "
     "var layers = new List<CompoundStructureLayer>(cs.GetLayers()); "
     "layers.Insert(0, new CompoundStructureLayer(width, MaterialFunctionAssignment.Finish1, materialId)); "
     "cs.SetLayers(layers); wallType.SetCompoundStructure(cs);"),

    # ─── Specific non-hallucination triggers (security, slab editor, etc.) ───

    # Security validator blocks reflection — actual message format is
    # `"violations": ["Blocked: GetField (reflection) (line N)"]`. Lowercase substring match.
    ("blocked: getfield",
     "Reflection через .GetField()/.GetProperty()/.GetMethod() запрещён security guard. "
     "Используй прямой публичный API: element.LookupParameter(\"имя\"), "
     "element.get_Parameter(BuiltInParameter.X), element.Location, element.Category. "
     "Если параметр кастомный — он доступен через LookupParameter по имени."),

    # ─── Pre-existing hints (general patterns, fallback after specific ones above) ───
    ("should be enabled", "Call .Enable() on the editor BEFORE modifying. Example: editor.Enable(); then editor.AddPoint(...)"),
    ("SlabShapeEditor", "You must call floor.SlabShapeEditor.Enable() before adding points or modifying the slab shape"),
    ("exists in the API, but not in Revit's native object model", "Use the base class instead. Example: use CurveElement instead of ModelCurve, use HostObject instead of specific type"),
    ("folder does not exist", "Create the folder first: System.IO.Directory.CreateDirectory(path)"),
    ("timed out", "The operation took too long. Try processing fewer elements (use .Take(100)) or split into smaller batches"),
    ("not a valid element", "The ElementId may refer to a deleted or invalid element. Filter with doc.GetElement(id) != null"),
    ("cannot be modified", "The element may be pinned, in a group, or on a locked workset. Check element.Pinned and element.GroupId"),
    ("parameter is read-only", "This parameter cannot be set directly. Check if it's a system/calculated parameter"),

    # ─── BROAD FALLBACK (LAST) — Roslyn appends "no accessible extension method"
    # to virtually every CS1061 error, so this trigger is genuinely broad and
    # would shadow ALL above hints if it came first. Keep it at the end as the
    # last-resort hint for actual LINQ binding failures (Cast/Where/Select).
    ("no accessible extension method",
     "Roslyn не видит LINQ extension methods (.Cast, .Where, .Select, .OfType, .ToList). "
     "Перепиши БЕЗ LINQ цепочек: используй обычный foreach, явное приведение типа "
     "((Wall)elem вместо elem.Cast<Wall>()), и `new List<T>()` с .Add() вместо .ToList()."),
]


def _enrich_runtime_error(message: str) -> str:
    """Add actionable hints to runtime errors so Gemini can self-correct."""
    if not message:
        return message
    ml = message.lower()
    for trigger, hint in _RUNTIME_ERROR_HINTS:
        if trigger.lower() in ml:
            return f"{message}\n\nHINT: {hint}"
    return message


_CS_ERROR_TRANSLATIONS = {
    "CS0103": "Переменная или тип не найден",
    "CS0246": "Тип не найден — возможно, версия Revit не поддерживает этот API",
    "CS0117": "Метод или свойство не существует у данного типа",
    "CS1061": "Объект не содержит такого метода или свойства",
    "CS0029": "Невозможно преобразовать один тип в другой",
    "CS0019": "Оператор не применим к данным типам",
    "CS1501": "Метод вызван с неправильным количеством аргументов",
    "CS0266": "Невозможно неявно преобразовать тип",
}


def _is_compilation_error(result: dict[str, Any]) -> bool:
    """Check if a bridge result is a compilation error (repairable)."""
    msg = str(result.get("message", "")).lower()
    return any(kw in msg for kw in [
        "compilation failed",
        "compile",
        "cs0",  # C# error codes like CS0103, CS0246
        "cs1",
        "syntax error",
        "not found in type",
        "does not contain a definition",
    ])


def _get_repair_hint(error: str) -> str:
    """Generate error-specific repair guidance based on CS error code.

    Returns a focused hint that tells repair LLM exactly how to fix
    this TYPE of error, without bloating context with unrelated info.
    """
    error_lower = error.lower()
    hints: list[str] = []

    # CS0117: "X does not contain a definition for Y"
    # Most common: wrong BuiltInParameter or BuiltInCategory name
    if "cs0117" in error_lower:
        hints.append(
            "ОШИБКА CS0117 — неправильное имя члена.\n"
            "Частые ошибки и правильные замены:\n"
            "- STRUCTURAL_VOLUME → HOST_VOLUME_COMPUTED\n"
            "- STRUCTURAL_AREA → HOST_AREA_COMPUTED\n"
            "- ELEMENT_VOLUME → HOST_VOLUME_COMPUTED\n"
            "- ELEMENT_AREA → HOST_AREA_COMPUTED\n"
            "- WALL_LENGTH → CURVE_ELEM_LENGTH\n"
            "- WALL_LENGTH_PARAM → CURVE_ELEM_LENGTH\n"
            "- WALL_HEIGHT → WALL_USER_HEIGHT_PARAM\n"
            "- ROOM_NAME_PARAM → ROOM_NAME\n"
            "- MARK → ALL_MODEL_MARK\n"
            "Если параметр не из этого списка — используй LookupParameter(\"имя\") вместо get_Parameter(BuiltInParameter.XXX)."
        )

    # CS0246: "The type or namespace name 'X' could not be found"
    if "cs0246" in error_lower:
        hints.append(
            "ОШИБКА CS0246 — тип не найден.\n"
            "Доступные using (уже в wrapper): System, System.Linq, System.Collections.Generic, "
            "System.Text, System.Text.RegularExpressions, "
            "Autodesk.Revit.DB, Autodesk.Revit.DB.Architecture, Autodesk.Revit.DB.Structure, "
            "Autodesk.Revit.DB.Mechanical, Autodesk.Revit.DB.Electrical, Autodesk.Revit.DB.Plumbing, "
            "Autodesk.Revit.UI.\n"
            "Если тип не находится — используй полное имя (Autodesk.Revit.DB.Architecture.Room).\n"
            "DisplayUnitType — только Revit 2021-2023. Для 2024+ используй UnitTypeId или умножай на коэффициент."
        )

    # CS1061: "X does not contain a definition for Y"
    if "cs1061" in error_lower:
        hints.append(
            "ОШИБКА CS1061 — метод/свойство не существует у типа.\n"
            "Частые ошибки:\n"
            "- element.Volume → element.get_Parameter(BuiltInParameter.HOST_VOLUME_COMPUTED).AsDouble()\n"
            "- element.Area → element.get_Parameter(BuiltInParameter.HOST_AREA_COMPUTED).AsDouble()\n"
            "- element.Length → element.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble()\n"
            "- wall.Length → wall.get_Parameter(BuiltInParameter.CURVE_ELEM_LENGTH).AsDouble()\n"
            "- Нужен cast? Используй (Wall)element или .Cast<Wall>()\n"
            "- Для IEnumerable нет .Count — используй .Count() (LINQ) или .ToList().Count"
        )

    # CS1056: Unexpected character (backticks, encoding)
    if "cs1056" in error_lower:
        hints.append(
            "ОШИБКА CS1056 — недопустимый символ в коде.\n"
            "Это обычно backtick (`) от markdown. Убери ВСЕ символы ``` из кода.\n"
            "Верни чистый C# без markdown-разметки."
        )

    # CS0103: "The name 'X' does not exist in the current context"
    if "cs0103" in error_lower:
        hints.append(
            "ОШИБКА CS0103 — переменная/тип не определена.\n"
            "Проверь: правильно ли написано имя? Объявлена ли переменная выше?\n"
            "Для BuiltInCategory: используй BuiltInCategory.OST_Walls (с префиксом).\n"
            "Для BuiltInParameter: используй BuiltInParameter.XXX (с префиксом)."
        )

    # CS0029/CS0266: Cannot implicitly convert type
    if "cs0029" in error_lower or "cs0266" in error_lower:
        hints.append(
            "ОШИБКА CS0029/CS0266 — несовместимые типы.\n"
            "Частые решения:\n"
            "- IEnumerable → List: добавь .ToList()\n"
            "- Element → Wall: добавь cast (Wall)element\n"
            "- int → long (ElementId): для Revit 2024+ ElementId.Value возвращает long\n"
            "- double → string: используй .ToString() или $\"{value}\""
        )

    # CS1002: Missing semicolon
    if "cs1002" in error_lower:
        hints.append(
            "ОШИБКА CS1002 — пропущена точка с запятой.\n"
            "Найди строку из ошибки и добавь ; в конце."
        )

    # CS1513: Missing closing brace
    if "cs1513" in error_lower or "cs1001" in error_lower:
        hints.append(
            "ОШИБКА CS1513/CS1001 — незакрытые скобки или пропущен идентификатор.\n"
            "Проверь баланс { } во всём коде. Каждому { должен соответствовать }.\n"
            "Проверь что все if/for/foreach/using/try блоки закрыты."
        )

    if not hints:
        hints.append(
            "Внимательно прочитай ошибку компиляции и исправь ТОЛЬКО проблемное место.\n"
            "Не меняй логику, не переписывай код целиком."
        )

    hint_text = "\n".join(hints)

    # IQ N1 (2026-07-06): mined-playbook hint, flag-gated (KUKAI_REPAIR_MINING).
    # OFF ⇒ get_playbook_hint returns None ⇒ the return value is byte-identical
    # to the pre-mining build. This is the ONE seam both repair paths share:
    # the legacy client.py loop and the pipeline both reach _repair_code, which
    # calls this function.
    playbook_hint = get_playbook_hint(error)
    if playbook_hint:
        return hint_text + "\n\n" + playbook_hint
    return hint_text


# ═════════════════════════════════════════════════════════════════════════════
# Repair-pair mining (IQ moment N1, 2026-07-06) — KUKAI_REPAIR_MINING, dark.
#
# Every successful repair is a verified (broken → fixed) lesson about how a
# real error class gets fixed. This section owns:
#   capture   record_repair_pair()  ← RevitExecutionPipeline repair-success hook
#   identity  error_signature()     ← shared by capture / miner / retrieval
#   hygiene   scrub_snippet()       ← cross-tenant exemplar scrub
#   retrieval get_playbook_hint()   ← consumed by _get_repair_hint above
# Default OFF ⇒ every function below is a no-op returning None/"" — prompts and
# telemetry stay byte-identical to the pre-mining build.
# ═════════════════════════════════════════════════════════════════════════════

def repair_mining_enabled() -> bool:
    """KUKAI_REPAIR_MINING=1 turns capture + playbook retrieval on.

    Read from the environment on every call (same convention as
    ``pipeline_enabled`` in revit_execution_pipeline.py — per-process A/B
    without importing kukai.config)."""
    return os.environ.get("KUKAI_REPAIR_MINING", "0") == "1"


# ---------------------------------------------------------------------------
# Error-class signature — ONE definition for capture, miner and retrieval.
# Roslyn localizes messages (RU backends emit «не содержит определения»), and
# quote characters vary: ' " ‘ ’ “ ” « » — same handling as rag/benchmark's
# Path C parser, self-contained here so the miner script stays light.
# ---------------------------------------------------------------------------

_SIG_CS_RE = re.compile(r"\bCS\d{4}\b")
_SIG_Q = "['\"‘’“”«»]"
_SIG_NAME = r"([A-Za-z_][\w<>,\.\s]*?)"

_SIG_MEMBER_EN = re.compile(
    rf"CS(\d{{4}})\s*[:\.]?\s*{_SIG_Q}{_SIG_NAME}{_SIG_Q}"
    r"\s+(?:does not contain|did not contain)"
    r"(?:\s+a\s+definition)?(?:\s+(?:for|of))?\s+"
    rf"{_SIG_Q}{_SIG_NAME}{_SIG_Q}",
    re.IGNORECASE,
)
_SIG_MEMBER_RU = re.compile(
    rf"CS(\d{{4}})\s*[:\.]?\s*{_SIG_Q}{_SIG_NAME}{_SIG_Q}"
    r"\s+не\s+содержит\s+(?:определения|члена|метода|свойства)?\s*"
    rf"{_SIG_Q}{_SIG_NAME}{_SIG_Q}",
    re.IGNORECASE | re.UNICODE,
)
_SIG_TYPE_EN = re.compile(
    rf"CS(0246)\s*[:\.]?\s*(?:the\s+)?type\s+or\s+namespace\s+name\s+"
    rf"{_SIG_Q}{_SIG_NAME}{_SIG_Q}",
    re.IGNORECASE,
)
_SIG_TYPE_RU = re.compile(
    rf"CS(0246)\s*[:\.]?\s*(?:не\s+удалось\s+найти\s+)?"
    r"(?:тип|имя\s+типа|пространство\s+имен)\s+(?:или\s+\S+\s+)?"
    rf"{_SIG_Q}{_SIG_NAME}{_SIG_Q}",
    re.IGNORECASE | re.UNICODE,
)
_SIG_NAME_EN = re.compile(
    rf"CS(0103)\s*[:\.]?\s*(?:the\s+)?name\s+{_SIG_Q}{_SIG_NAME}{_SIG_Q}"
    r"\s+does\s+not\s+exist",
    re.IGNORECASE,
)
_SIG_NAME_RU = re.compile(
    rf"CS(0103)\s*[:\.]?\s*(?:имя|имени)\s+{_SIG_Q}{_SIG_NAME}{_SIG_Q}",
    re.IGNORECASE | re.UNICODE,
)
_SIG_NUM_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")


def _sig_template(error_text: str) -> str:
    """Line/column-invariant fallback template for unparsed messages."""
    text = error_text.strip()
    m = _SIG_CS_RE.search(text)
    if m:
        text = text[m.start():]
    text = text.splitlines()[0] if text else ""
    text = _SIG_CS_RE.sub("", text)
    text = _SIG_NUM_RE.sub("⟨n⟩", text)
    text = re.sub(r"\s+", " ", text).strip(" :;.,-")
    return text.lower()[:90]


def error_signature(error_text: Optional[str]) -> tuple[str, list[str]]:
    """Return ``(signature, cs_codes)`` for a compile/repair error message.

    Signature grammar (most→least specific, first match wins):
      ``CS1061:Type.Member``   — missing member (EN + RU Roslyn phrasing)
      ``CS0246:TypeName``      — unknown type/namespace
      ``CS0103:name``          — unknown identifier
      ``CSxxxx:<template>``    — any other coded error, line-number-invariant
      ``NOCS:<template>``      — no CS code (never used for injection)
    Deterministic and pure — capture, the offline miner and retrieval MUST all
    agree on this function or the playbook silently stops matching."""
    if not error_text or not isinstance(error_text, str):
        return "", []
    codes = list(dict.fromkeys(_SIG_CS_RE.findall(error_text)))
    for rx in (_SIG_MEMBER_EN, _SIG_MEMBER_RU):
        m = rx.search(error_text)
        if m:
            return (
                f"CS{m.group(1)}:{m.group(2).strip()}.{m.group(3).strip()}",
                codes,
            )
    for rx in (_SIG_TYPE_EN, _SIG_TYPE_RU):
        m = rx.search(error_text)
        if m:
            return f"CS{m.group(1)}:{m.group(2).strip()}", codes
    for rx in (_SIG_NAME_EN, _SIG_NAME_RU):
        m = rx.search(error_text)
        if m:
            return f"CS{m.group(1)}:{m.group(2).strip()}", codes
    if codes:
        return f"{codes[0]}:{_sig_template(error_text)}", codes
    return f"NOCS:{_sig_template(error_text)}", codes


# ---------------------------------------------------------------------------
# Exemplar scrub — the cross-tenant hygiene line.
# ---------------------------------------------------------------------------

_CS_KEYWORDS = frozenset("""
abstract as base bool break byte case catch char checked class const continue
decimal default delegate do double dynamic else enum event explicit extern
false finally fixed float for foreach from goto if implicit in int interface
internal is lock long nameof namespace new null object operator out override
params private protected public readonly ref return sbyte sealed select short
sizeof stackalloc static string struct switch this throw true try typeof uint
ulong unchecked unsafe ushort using var virtual void volatile когда where
while yield when
""".split())

# Wrapper parameters — structural, never user data, always kept verbatim.
_KEEP_IDENTS = frozenset({"doc", "uidoc"})

_IDENT = r"[^\W\d]\w*"
_DECL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(rf"\bvar\s+({_IDENT})", re.UNICODE),
    re.compile(
        rf"\b(?:int|long|double|float|decimal|bool|string|object|char)\s+"
        rf"({_IDENT})\s*(?==|;|,|\))",
        re.UNICODE,
    ),
    re.compile(rf"\b(?:out|ref)\s+(?:var\s+)?({_IDENT})", re.UNICODE),
    re.compile(
        rf"\bforeach\s*\(\s*(?:var|[A-Za-z_][\w<>,\.]*)\s+({_IDENT})\s+in\b",
        re.UNICODE,
    ),
    # "Type name =" declarations (PascalCase type, declared name = group 2)
    re.compile(rf"\b[A-Z]\w*(?:<[^<>]*>)?\s+({_IDENT})\s*=(?!=)", re.UNICODE),
    re.compile(rf"\bcatch\s*\(\s*[\w\.]+\s+({_IDENT})\s*\)", re.UNICODE),
    re.compile(rf"\bfor\s*\(\s*(?:var|int|long)\s+({_IDENT})", re.UNICODE),
    re.compile(rf"\busing\s*\(\s*(?:var|[A-Z]\w*)\s+({_IDENT})\s*=", re.UNICODE),
    # lambda: single param and (a, b) param lists
    re.compile(rf"({_IDENT})\s*=>", re.UNICODE),
    re.compile(r"\(([^()]{0,80})\)\s*=>", re.UNICODE),
]
_NUM_LITERAL_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
# Numeric literals longer than this are treated as potentially identifying
# (coordinates, project codes); short ones (unit factors like 304.8, indices)
# are structural knowledge and kept.
_NUM_KEEP_MAX_CHARS = 6


def _strip_strings_and_comments(code: str) -> str:
    """One-pass scanner: comments removed, every string/char literal → "…"."""
    out: list[str] = []
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        nxt = code[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = code.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and nxt == "*":
            j = code.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c in "@$":
            k = i
            prefix = ""
            while k < n and code[k] in "@$":
                prefix += code[k]
                k += 1
            if k < n and code[k] == '"':
                verbatim = "@" in prefix
                j = k + 1
                while j < n:
                    if code[j] == '"':
                        if verbatim and j + 1 < n and code[j + 1] == '"':
                            j += 2
                            continue
                        break
                    if not verbatim and code[j] == "\\":
                        j += 2
                        continue
                    j += 1
                out.append('"…"')
                i = j + 1
                continue
            out.append(c)
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == '"':
                    break
                j += 1
            out.append('"…"')
            i = j + 1
            continue
        if c == "'":
            j = i + 1
            while j < n:
                if code[j] == "\\":
                    j += 2
                    continue
                if code[j] == "'":
                    break
                j += 1
            if j < n and j - i <= 5:  # char literal ('x', '\n'); else raw quote
                out.append("'…'")
                i = j + 1
                continue
            out.append(c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _declared_identifiers(code: str) -> list[str]:
    """User-declared identifiers in first-appearance order (locals, lambda
    params, loop vars). API names are never declared inside a snippet, so
    they survive the rename by construction."""
    found: dict[str, int] = {}

    def _note(name: str, pos: int) -> None:
        name = name.strip()
        if (
            name
            and name not in _CS_KEYWORDS
            and name not in _KEEP_IDENTS
            and re.fullmatch(_IDENT, name)
        ):
            found.setdefault(name, pos)

    for rx in _DECL_PATTERNS:
        for m in rx.finditer(code):
            grp = m.group(1)
            if "," in grp or " " in grp.strip():
                # lambda param list "(a, b)" / typed "(Wall w)" — last word each
                for part in grp.split(","):
                    words = part.strip().split()
                    if words:
                        _note(words[-1], m.start())
            else:
                _note(grp, m.start())
    return [name for name, _ in sorted(found.items(), key=lambda kv: kv[1])]


def scrub_snippet(code: str, max_chars: int = 1200) -> str:
    """Scrub a code exemplar for cross-tenant reuse.

    Removes the three carriers of user/project data while keeping API names
    and structure:
      1. comments and ALL string/char literals (→ "…"),
      2. declared identifiers → v1, v2, … (consistent, first-appearance order),
      3. long numeric literals (> 6 chars — coordinates/project codes) → 0.
    Deterministic; returns at most ``max_chars`` characters."""
    if not code:
        return ""
    text = _strip_strings_and_comments(code)
    taken = set(re.findall(r"\bv\d+\b", text))
    rename: dict[str, str] = {}
    counter = 1
    for name in _declared_identifiers(text):
        while f"v{counter}" in taken:
            counter += 1
        rename[name] = f"v{counter}"
        taken.add(f"v{counter}")
        counter += 1
    for name, repl in rename.items():
        text = re.sub(rf"\b{re.escape(name)}\b", repl, text, flags=re.UNICODE)
    text = _NUM_LITERAL_RE.sub(
        lambda m: m.group(0) if len(m.group(0)) <= _NUM_KEEP_MAX_CHARS else "0",
        text,
    )
    # tidy: strip trailing spaces, collapse the blank runs comment-removal left
    lines = [ln.rstrip() for ln in text.splitlines()]
    tidy: list[str] = []
    for ln in lines:
        if ln == "" and (not tidy or tidy[-1] == ""):
            continue
        tidy.append(ln)
    return "\n".join(tidy).strip()[:max_chars]


# ---------------------------------------------------------------------------
# Capture side — called by RevitExecutionPipeline at the repair-success moment.
# ---------------------------------------------------------------------------

_PAIR_ERROR_CAP = 4_000
_PAIR_CODE_CAP = 16_000


def record_repair_pair(
    *,
    error_text: Optional[str],
    broken_code: Optional[str],
    fixed_code: Optional[str],
    fix_source: str,
    revit_version: str = "",
    attempts: int = 0,
    model: Optional[str] = None,
) -> None:
    """Persist one VERIFIED (broken→fixed) repair pair — fail-open telemetry.

    Flag-gated (KUKAI_REPAIR_MINING, default OFF ⇒ no-op, no imports, no
    writes). Reuses ``kukai.telemetry_rag``'s background writer thread — the
    same fire-and-forget queue every other telemetry stream rides — so this
    NEVER blocks or fails the turn. Rows land in
    data/telemetry/repair_pairs.jsonl (size-capped per field; error text is
    PII-scrubbed; code bodies stay raw like reasoning_traces — the playbook,
    not this file, is the cross-tenant artifact)."""
    if not repair_mining_enabled():
        return
    try:
        if not (error_text and broken_code and fixed_code):
            return
        from kukai import telemetry_rag as _tel

        if model is None:
            try:
                from kukai.config import get_settings

                model = getattr(get_settings(), "llm_model", "") or ""
            except Exception:  # noqa: BLE001 — config absent in tools/tests
                model = ""
        signature, cs_codes = error_signature(str(error_text))
        row = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "error_text": _tel._scrub_pii(str(error_text))[:_PAIR_ERROR_CAP],
            "cs_codes": cs_codes,
            "error_signature": signature,
            "broken_code": str(broken_code)[:_PAIR_CODE_CAP],
            "fixed_code": str(fixed_code)[:_PAIR_CODE_CAP],
            "fix_source": str(fix_source),
            "revit_version": str(revit_version or ""),
            "model": str(model or ""),
            "attempts": int(attempts or 0),
        }
        _tel._writer.enqueue("repair_pairs", row)
    except Exception:  # noqa: BLE001 — telemetry must never break a turn
        logger.debug("record_repair_pair failed (non-fatal)", exc_info=True)


# ---------------------------------------------------------------------------
# Retrieval hook — playbook lookup for the repair prompt.
# ---------------------------------------------------------------------------

_PLAYBOOK_HINT_CAP = 600
_playbook_cache: dict[str, Any] = {"key": None, "clusters": None}


def playbook_path() -> Path:
    """data/rag/repair_playbook.json (env-overridable for tests/tools)."""
    env = os.environ.get("KUKAI_REPAIR_PLAYBOOK_PATH", "")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "rag" / "repair_playbook.json"


def _load_playbook_clusters() -> dict[str, dict[str, Any]]:
    """signature → cluster map; (path, mtime, size)-cached; {} on ANY failure."""
    path = playbook_path()
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    if _playbook_cache["key"] == key and _playbook_cache["clusters"] is not None:
        return _playbook_cache["clusters"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        clusters: dict[str, dict[str, Any]] = {}
        for cluster in data.get("clusters", []):
            sig = cluster.get("error_signature")
            if isinstance(sig, str) and sig and isinstance(cluster, dict):
                clusters.setdefault(sig, cluster)
        _playbook_cache["key"] = key
        _playbook_cache["clusters"] = clusters
        return clusters
    except Exception:  # noqa: BLE001 — corrupt playbook must never break repair
        logger.debug("repair playbook load failed (non-fatal)", exc_info=True)
        return {}


def get_playbook_hint(error: Optional[str]) -> Optional[str]:
    """Bounded «проверенный фикс» hint for one compile error, or None.

    Injection policy (deliberately strict — the hint competes for repair-prompt
    attention): flag ON + a CS-coded signature + an EXACT signature match in
    the mined playbook. Top-1 cluster only, ≤600 chars. Because the match is
    exact, every symbol in the hint already appears in the requesting user's
    own error text — no cross-tenant symbol leakage by construction."""
    if not repair_mining_enabled():
        return None
    try:
        signature, _ = error_signature(error or "")
        if not signature or signature.startswith("NOCS:"):
            return None
        cluster = _load_playbook_clusters().get(signature)
        if not cluster:
            return None
        pattern = str(cluster.get("fix_pattern_text") or "").strip()
        if not pattern:
            return None
        count = cluster.get("count") or 1
        head = (
            f"ПРОВЕРЕННЫЙ ФИКС этого класса ошибки "
            f"({signature}; {count}× успешно исправлено в проде):\n"
        )
        return (head + pattern)[:_PLAYBOOK_HINT_CAP]
    except Exception:  # noqa: BLE001 — retrieval must never break repair
        logger.debug("get_playbook_hint failed (non-fatal)", exc_info=True)
        return None
