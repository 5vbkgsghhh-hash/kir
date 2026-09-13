"""Wave A5 — re-extract a KNOWN id set into L0 elements (idempotence readback).

The idempotence loop (``kir/idempotence.py``) rebuilds a decompiled model at a
Δ-offset and needs to read back ONLY the elements it just created, by their
witness ElementIds, and re-lift them.  A whole-model :func:`extract.extract_document`
run would be wrong here: the copy still contains all the originals, so a full
extract would re-lift the originals too and the id-restricted comparison would be
impossible.

This module builds ONE read-only bridge body that collects exactly the requested
ids (``doc.GetElement`` per id, whole-model, no category collector) and emits the
same per-element row shape ``extract.build_category_batch_cs`` emits — so the
frozen ``parse_geometry`` + ``L0Element.from_dict`` reader parses it unchanged.
The rows are then assembled into an :class:`L0Document` reusing the ORIGINAL
decompile metadata (levels/grids/rooms) so the re-lift has the same datum context
the Δ-rebuild pinned against.

Invariants: I1 (no LOT31 hardcode — the id list is data), I2 (a missing/typeless
id is a typed :class:`ReExtractError`, never a silently-dropped element), I4 (rows
are re-sorted by numeric id; the builder is a pure function of the id list).  The
C# body reuses the exact frozen extract helpers so its version-safety is the SAME
proof as the extractor's.

🔴 I5 WAS REWRITTEN ON 17.08.2026: THIS IS NOW A HOT PATH, AND THE COST IS
NAMED AS A NUMBER. The earlier version read "nothing imports this on a hot
path" — a prohibition resting on an unmeasured worry. Working around it
silently would have been cheaper than rewriting it, and so it was rewritten.

Measurement of 17.08.2026 on a live `13A-RD-AR-K2` (310,558 elements),
median of three:

    N=1 → 1.17 s · N=10 → 1.04 s · N=50 → 1.10 s · N=200 → 1.11 s

**The slope over N is ZERO** (−0.34 ms/element across the whole range), and
this follows from the body below: `_ROW_BODY_CS` walks the ENTIRE
`FilteredElementCollector` and only then filters by a `HashSet` of the
wanted ids. It is the document walk that is paid for, not the number of
ids — meaning a CONSTANT ~1.1 s lands on the turn, +6.3% against the 17-18 s
turn duration measured on 16.08, of which 84.6% is spent waiting on the
model.

There is exactly one hot caller — :mod:`kir.built_verdict`, the judge of
what was built (`serving`, after a confirmed commit, REPORTS and does not
hold up the turn). Exactly what this turn created is read back: a full
re-read would pull in foreign elements alongside our own and would cost
0.326 s + 12.2 ms per element (`extract.py:436`) — on 310 thousand that is
an hour.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from kir.decompile.extract import (
    _COMMON_HELPERS_CS,
    _ELEMENT_HELPERS_CS,
    _route_cs,
    ExtractionProtocolError,
)
from kir.decompile.geometry_store import GEOMETRY_HELPER_CS, parse_geometry
from kir.decompile.schema import (
    L0Document, L0Element, L0SchemaError, RoomInfo,
)
from kir.decompile.side_contract import (
    element_id_key,
    source_binding_cs,
)

#: 🔴 THE SOURCE BINDING IS THE FIRST LINE OF BOTH BODIES, AND THIS IS NOT STYLE.
#:
#: `extract`'s frozen helpers have, since 25.08 (`a91ac7fe`), read the
#: document by the name `__src`, not `doc`: an extraction body ALWAYS binds
#: its source, and one name is valid for both a host and a link. This
#: assembly — a SECOND consumer of the same helpers — was not laying down
#: the binding, and its C# had NOT A SINGLE `__src` declaration across five
#: reads. The body did not compile:
#: "CS0103: The name '__src' does not exist" at lines 45 and 274.
#:
#: THE COST WAS MEASURED LIVE ON 25.08: the judge of what was built
#: (`built_verdict`) rides exactly this body. For a full day after
#: `a91ac7fe`, EVERY live program returned `built.state="refused"` — meaning
#: it built and was NEVER RE-READ — while `outcome`/`witness`/`acceptance`
#: stayed green the whole time: they are about EMISSION, and the judge is
#: about the MODEL. BOTH bodies were broken: the element one (5 reads) and
#: the room one (1).
#:
#: 🔴 THIS IS THE SECOND TIME, THE SAME WAY, IN THIS SAME FILE. The first was
#: `__RouteSkips` on 20.08, analyzed in the comment further down: a helper
#: calls a name that a FOREIGN preamble declares, and this second consumer
#: does not lay it down. That time the CASE was treated (`_route_cs(None)`
#: was added), and the class stayed open: any next name from the
#: extraction's preamble would repeat exactly this. Hence the PROD FUNCTION
#: for the binding is called here rather than writing the literal
#: `Document __src = doc;`: two texts that must agree are exactly this
#: tree's named defect.
#:
#: `None` — because the judge has no links BY CONSTRUCTION: it re-reads what
#: we ourselves built, and building can only happen in the host. The
#: `source_binding_cs` docstring demands the same thing and names the cost
#: in advance: "a binding placed after the helpers would not compile under
#: Roslyn — meaning it would only be found out live." It was found out live.
_SOURCE_IS_HOST_CS = source_binding_cs(None)


class ReExtractError(RuntimeError):
    """A re-extraction body/response violated the frozen A5 readback contract."""


REEXTRACT_BATCH = 200


#: PROTOCOL FIELD NAMES — ONE CARRIER, NOT TWO.
#:
#: The C# emission and the Python parser must speak of one field with one
#: word. While the word stood in two places, agreement rested on
#: convention — exactly the "fixture from a matched pair" that stays green
#: for ANY value on either side (shape 48). The constants are declared
#: here, the parser reads THEM, and the guard derives its expectation of
#: the emission FROM THE SAME ONES.
SKIPPED_TYPES_KEY = "skipped_element_types"
SKIPPED_TYPE_PROOF_KEY = "skipped_element_type_proof"
SKIPPED_PROOF_CLASS_FIELD = "class"
ACTIVE_VIEW_VISIBILITY_STATE_KEY = "active_view_visibility_state"
ACTIVE_VIEW_VISIBLE_KEY = "active_view_visible"
ACTIVE_VIEW_VISIBILITY_ERROR_KEY = "active_view_visibility_error"
#: Three outcomes of the visibility measurement. Zero belongs ONLY to the first.
ACTIVE_VIEW_VISIBILITY_STATES = ("measured", "read_failed", "no_active_view")


#: Substitution of field names into the emitted C#. The key is the
#: placeholder in the template text, the value is the SOLE declaration of
#: the name the parser reads.
_PROTOCOL_KEY_BINDINGS: dict[str, str] = {
    "__K_SKIPPED__": SKIPPED_TYPES_KEY,
    "__K_SKIP_PROOF__": SKIPPED_TYPE_PROOF_KEY,
    "__K_SKIP_CLASS__": SKIPPED_PROOF_CLASS_FIELD,
    "__K_VIS_STATE__": ACTIVE_VIEW_VISIBILITY_STATE_KEY,
    "__K_VIS_N__": ACTIVE_VIEW_VISIBLE_KEY,
    "__K_VIS_ERR__": ACTIVE_VIEW_VISIBILITY_ERROR_KEY,
}


def _bind_protocol_keys(template: str, required: Sequence[str]) -> str:
    """Substitute the protocol's field names into the TEMPLATE, naming the expected slots.

    An unsubstituted placeholder would give C# that fails to compile — and
    that would be loud. The other outcome is silent: a slot that STOPPED
    occurring (someone wrote the literal back in) returns a second copy of
    the name, and the discrepancy becomes a matter of convention again.
    It is exactly this that gets checked, and the expectation is declared
    AT THE CALL SITE: the re-read body and the direct lookup have DIFFERENT
    slots, and the candidate walk carries none at all — one shared list for
    all three would be a third carrier of the same quantity.
    """

    for placeholder in required:
        if placeholder not in template:
            raise ReExtractError(
                f"emitted re-extract template lost the {placeholder} slot: "
                "the protocol field name has a second carrier again")
    for placeholder, name in _PROTOCOL_KEY_BINDINGS.items():
        template = template.replace(placeholder, '"' + name + '"')
    return template


# The re-extract row body reuses the SAME per-element field extraction as
# ``extract.build_category_batch_cs``; the only difference is the collector — a
# whole-model walk filtered by a wanted-id ``HashSet<long>`` rather than a
# category ``FilteredElementCollector`` — because the ids to read span whatever
# categories the rebuild created.  The id set is compared against ``__Id(e)`` (a
# ``long.Parse`` of ``e.Id.ToString()``, the frozen helper) so NO ``ElementId``
# is constructed from a 64-bit literal — ``new ElementId(long)`` exists only on
# Revit 2024+ and would break the 2021-2023 compile gate.  ``category`` is read
# from the live element, so a re-extracted wall row carries ``OST_Walls`` and the
# frozen reader accepts it.  Grid/Level instances are appended explicitly (they
# are class-only, outside ``WhereElementIsNotElementType`` category space).
_ROW_BODY_CS = r"""
var __wanted = new HashSet<long>(new long[] { __IDS__ });
// 🔴 ПРОПУСК ОБЯЗАН БЫТЬ НАЗВАН. Типоразмеры выбрасываются намеренно (см.
// `_CANDIDATES_DIRECT_CS`), и до 21.08 они выбрасывались МОЛЧА: судья
// построенного видел «просили N, увидели N-1» и отказывал целиком —
// «перечитанное не сошлось с обещанным». Так отказал первый же живой
// `author_family`, чья личность ЕСТЬ типоразмер: определение семейства
// нигде не стоит, стоит его экземпляр. Отказ был честным и бесполезным:
// он назвал число, а не причину. Теперь причина едет списком.
//
// 🔴 И НАЗВАН ОН БЫЛ БЕЗ ДОКАЗАТЕЛЬСТВА (02.09.2026). До этой правки ответ
// моста просто ПЕРЕЧИСЛЯЛ id, а разборщик вычитал их из сверки точности, не
// требуя ни того, чтобы id вернулся, ни того, чтобы он доказанно был
// `ElementType`. Значит ответ сам решал, о чём его не спрашивать: одна
// строка в собственном ответе прятала по-настоящему пропавший элемент, и
// перечитывание отвечало чистым успехом. Теперь у пропуска едет КЛАСС —
// улика, которую разборщик проверяет, а не принимает на слово.
var __skippedTypes = new List<string>();
var __skippedProof = new List<object>();
var __seen = new HashSet<long>();
var __candidates = new List<Element>();
__CANDIDATES__
var __rows = new List<object>();
foreach (var __element in __candidates.OrderBy(__x => __Id(__x)))
{
    long __eid = __Id(__element);
    if (!__wanted.Contains(__eid) || __seen.Contains(__eid)) continue;
    __seen.Add(__eid);
    var __row = new Dictionary<string, object>();
    __row["element_id"] = __element.Id.ToString();
    string __catName = "";
    try
    {
        if (__element.Category != null && __element.Category.Name != null)
            __catName = __element.Category.Name;
    }
    catch { }
    __row["category_ru"] = __catName;
    string __bic = "";
    try
    {
        if (__element.Category != null)
        {
            int __catId;
            if (Int32.TryParse(__element.Category.Id.ToString(), out __catId))
                __bic = Enum.GetName(typeof(BuiltInCategory), __catId) ?? "";
        }
    }
    catch { }
    // Class-only families (Grid/Level) carry no BuiltInCategory name.
    if (String.IsNullOrEmpty(__bic))
    {
        if (__element is Grid) __bic = "OST_Grids";
        else if (__element is Level) __bic = "OST_Levels";
    }
    __row["category"] = __bic;
    __row["type_id"] = "";
    __row["type_name"] = "";
    try
    {
        var __typeId = __element.GetTypeId();
        if (__typeId != null && __typeId != ElementId.InvalidElementId)
        {
            __row["type_id"] = __typeId.ToString();
            var __type = doc.GetElement(__typeId);
            if (__type != null && __type.Name != null)
                __row["type_name"] = __type.Name;
        }
    }
    catch { }
    __row["level_id"] = null;
    __row["level_name"] = null;
    var __level = __ElementLevel(__element);
    if (__level != null)
    {
        __row["level_id"] = __level.Id.ToString();
        __row["level_name"] = __level.Name ?? "";
    }
    __row["host_id"] = null;
    try
    {
        var __familyInstance = __element as FamilyInstance;
        if (__familyInstance != null && __familyInstance.Host != null)
            __row["host_id"] = __familyInstance.Host.Id.ToString();
    }
    catch { }
    __PutParams(__element, __row);
    __PutGroupingState(__element, __row);
    __PutGeometry(__element, __row);
    __rows.Add(__row);
}
// 🔴 ТРЕТИЙ ВОПРОС, И ОН ЕДЕТ ТЕМ ЖЕ РЕЙСОМ. Свидетель отвечает
// «построено ли заявленное», судья — «совпадает ли»; ни один не спрашивает
// «ВИДИТ ЛИ ЭТО ЧЕЛОВЕК». 21.08.2026: в документе 925 обобщённых моделей,
// в активном 3D-виде видно НОЛЬ — секущая рамка стояла на пустом месте в
// −52 км. Квитанции при этом были безупречны.
//
// Считается ЗДЕСЬ, а не отдельной поездкой: рейс судьи уже стоит ~2.7 с на
// ход, и второй такой же ради одного числа удвоил бы цену перечитывания.
// Коллектор, ограниченный `ActiveView`, возвращает ровно то, что вид
// пропускает — рамку, категории, фильтры, фазу, рабочие наборы.
//
// 🔴 И У ЭТОГО ЗАМЕРА ТРИ ИСХОДА, А ПРИЕЗЖАЛ ОН ОДНИМ ЧИСЛОМ (02.09.2026).
// Весь блок стоял под пустым `catch`, счётчик был инициализирован нулём, и
// поля доступности не было вовсе. Значит «Ревит не дал прочитать вид» и «в
// виде не видно ни одного элемента» приезжали неотличимо, а потребитель
// (`built_verdict`) обязан был счесть это фактом о ЗДАНИИ — «построено, но
// не видно» — хотя это факт о ЗАМЕРЕ. Форма 34 канона дословно: у прибора,
// чьё измеряемое действие может НЕ ПРОИЗОЙТИ, обязан быть отдельный исход
// «действие не состоялось», и он обязан быть ГРОМЧЕ нуля, а не тише.
//
// Третий исход назван отдельно и не сведён ко второму: активного вида нет
// вовсе (безоконный ход, фоновый документ) — это не отказ чтения и не ноль
// видимых, а отсутствие самого предмета замера.
var __visSeen = new HashSet<string>();
string __visView = "(нет активного вида)";
bool __visBox = false;
string __visState = "no_active_view";
string __visError = null;
try
{
    var __av = doc.ActiveView;
    if (__av != null)
    {
        __visView = __av.Name;
        var __v3 = __av as View3D;
        __visBox = __v3 != null && __v3.IsSectionBoxActive;
        // 🔴 АДРЕСНО, А НЕ ОБХОДОМ ВИДА, И БЕЗ КОНСТРУИРОВАНИЯ `ElementId`.
        // Первая редакция брала весь `FilteredElementCollector(doc, view)` —
        // собственный тест этого файла её поймал: перечитывание id-адресно
        // ПО КОНТРАКТУ, а обход вида на большом документе стоит столько же,
        // сколько обход документа.
        //
        // Вторая редакция строила `ElementId` из числа — а `new
        // ElementId(long)` существует только с Revit 2024 (см. шапку
        // `_ROW_BODY_CS`) и уронила бы ворота на 2021-2023.
        //
        // Здесь берутся `Id` УЖЕ СОБРАННЫХ элементов: ни парсинга, ни
        // конструктора, ни обхода — только сужение вида до наших же тел.
        var __visWant = new List<ElementId>();
        foreach (var __ce in __candidates) __visWant.Add(__ce.Id);
        if (__visWant.Count > 0)
            foreach (Element __ve in new FilteredElementCollector(doc, __av.Id)
                     .WherePasses(new ElementIdSetFilter(__visWant)))
                __visSeen.Add(__ve.Id.ToString());
        // Ставится ПОСЛЕДНИМ и только здесь: обрыв на любом шаге выше
        // оставляет исход неизмеренным, а не «измеренным наполовину».
        __visState = "measured";
    }
}
catch (Exception __visException)
{
    __visState = "read_failed";
    string __visMessage = __visException.Message ?? "";
    if (__visMessage.Length > 200) __visMessage = __visMessage.Substring(0, 200);
    __visError = __visException.GetType().Name + ": " + __visMessage;
    // Частичное множество — не меньшее число, а ДРУГОЕ: оно описывает, где
    // оборвался обход, и было бы прочитано как видимость.
    __visSeen.Clear();
}
// Счёт берётся прямо из множества: коллектор уже сужен фильтром до наших
// же тел, значит всё, что он вернул, — это наши ВИДИМЫЕ. Считать вторым
// проходом по строкам значило бы завести второй носитель одного числа.
var __result = new Dictionary<string, object> {
    {"elements", __rows},
    {__K_SKIPPED__, __skippedTypes},
    {__K_SKIP_PROOF__, __skippedProof},
    {"active_view_name", __visView},
    {__K_VIS_STATE__, __visState},
    {"active_view_section_box", __visBox}
};
// ЧИСЛО ЕДЕТ ТОЛЬКО ИЗМЕРЕННЫМ. `null` здесь — не потеря, а единственный
// честный ответ: потребитель, читающий это поле целым числом, ПО
// ПОСТРОЕНИЮ перестаёт получать несостоявшийся замер под видом факта.
__result[__K_VIS_N__] =
    __visState == "measured" ? (object)__visSeen.Count : null;
if (__visError != null) __result[__K_VIS_ERR__] = __visError;
return __result;
""".strip()


#: GATHERING CANDIDATES, METHOD ONE — WALKING THE WHOLE DOCUMENT (fallback).
#: Needed exactly when a direct lookup is impossible: see `_candidates_cs`.
_CANDIDATES_WALK_CS = r"""foreach (var __e in new FilteredElementCollector(doc)
        .WhereElementIsNotElementType().Cast<Element>())
    __candidates.Add(__e);
foreach (var __g in new FilteredElementCollector(doc)
        .OfClass(typeof(Grid)).Cast<Element>())
    __candidates.Add(__g);
foreach (var __lv in new FilteredElementCollector(doc)
        .OfClass(typeof(Level)).Cast<Element>())
    __candidates.Add(__lv);"""


#: METHOD TWO — DIRECT LOOKUP BY id. `__INT_IDS__` is the same ids, but as
#: int literals.
#:
#: `if (__el is ElementType) continue;` reproduces `WhereElementIsNotElementType()`
#: VERBATIM: without it, a direct lookup would see a type (e.g. one created
#: by `create_type`) that the walk did not show, and behaviour would drift
#: apart silently. Grid and Level are not types and pass through.
_CANDIDATES_DIRECT_CS = r"""foreach (var __wid in new int[] { __INT_IDS__ })
{
    Element __el = null;
    try { __el = doc.GetElement(new ElementId(__wid)); } catch { }
    if (__el == null) continue;
    if (__el is ElementType)
    {
        var __skipRow = new Dictionary<string, object>();
        __skipRow["element_id"] = __el.Id.ToString();
        __skipRow[__K_SKIP_CLASS__] = __el.GetType().Name;
        __skippedTypes.Add(__el.Id.ToString());
        __skippedProof.Add(__skipRow);
        continue;
    }
    __candidates.Add(__el);
}"""

#: The boundary of a direct lookup: `new ElementId(int)` compiles on ALL six
#: versions, `new ElementId(long)` only since 2024. The body is emitted as
#: ONE text for all versions (the gate compiles it six times), so a 64-bit
#: id is unavailable to a direct lookup and falls back to a walk.
_ROW_BODY_CS = _bind_protocol_keys(_ROW_BODY_CS, (
    "__K_SKIPPED__", "__K_SKIP_PROOF__",
    "__K_VIS_STATE__", "__K_VIS_N__", "__K_VIS_ERR__",
))
_CANDIDATES_DIRECT_CS = _bind_protocol_keys(
    _CANDIDATES_DIRECT_CS, ("__K_SKIP_CLASS__",))


_INT32_MAX = 2_147_483_647


def _candidates_cs(numeric: Sequence[int]) -> tuple[str, str]:
    """(the candidate-gathering body, the NAMED reason for the choice).

    🔴 THE MEASUREMENT of 18.08.2026, a live tower, phase analysis from
    `EXEC_PIPELINE_RECORD`: `built_reread` cost **2663 ms** per turn, and
    the canon already named the mechanism — "the slope over N is zero, the
    document walk is what is paid for, not the number of ids." The body
    below was exactly the reason: it materialized the ENTIRE document into
    a list and SORTED it (`OrderBy(__Id)`) to find no more than 200 ids. On
    the tower that is 310,558 elements, each needing `e.Id.ToString()` and
    `long.Parse` (the `__Id` body) — that is three hundred thousand string
    parses for two hundred matches.

    A direct lookup asks the document exactly for what is needed: N calls
    instead of a walk. Possible as long as every id fits into an Int32 —
    `new ElementId(int)` exists on all six versions, `new ElementId(long)`
    only since 2024, and the body is emitted as one text for all of them.

    WHAT THIS DOES NOT CHANGE: the set of rows in the output. `is
    ElementType` repeats `WhereElementIsNotElementType()`, Grid and Level
    are reached by the same direct call, and the `__wanted` filter and
    `__seen` dedup in the body below are left untouched — on the direct
    path they simply become identities.
    """
    if not numeric:
        return _CANDIDATES_WALK_CS, "пусто"
    too_big = [value for value in numeric if value > _INT32_MAX]
    if too_big:
        return (_CANDIDATES_WALK_CS,
                f"обход: {len(too_big)} id больше Int32 "
                f"(первый {too_big[0]}), прямая выборка недоступна до 2024")
    literals = ", ".join(str(value) for value in numeric)
    return (_CANDIDATES_DIRECT_CS.replace("__INT_IDS__", literals, 1),
            f"прямая выборка: {len(numeric)} id")


# Δ-room boundary re-extract (2026-07-21).  `reextracted_document` binds
# `rooms=metadata.rooms` — the ORIGINAL rooms keyed by ORIGINAL element_ids —
# but the Δ-copy's rebuilt rooms carry NEW ids, so `_lift_room`'s
# `rooms_by_id.get(new_id)` returned None and EVERY Δ-room atomized (live
# floor-20: 0/87).  Same blindness class as floors-without-sketch: the re-lift
# must see the Δ-copy's OWN room boundaries.  This body reads the boundary loops
# of exactly the created room ids (SpatialElementBoundary, area-gated exactly as
# the whole-model extractor) so `RoomInfo.from_dict` reconstructs them keyed by
# the NEW id.  Fail-open: an unreadable boundary yields no room row, degrading
# to the honest atomization it already had.
_ROOM_BODY_CS = r"""
var __wanted = new HashSet<long>(new long[] { __IDS__ });
var __rooms = new List<object>();
var __boundaryOptions = new SpatialElementBoundaryOptions();
foreach (var __room in new FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_Rooms)
        .WhereElementIsNotElementType()
        .Cast<Autodesk.Revit.DB.Architecture.Room>()
        .Where(__x => __wanted.Contains(__Id(__x)))
        .OrderBy(__x => __Id(__x)))
{
    var __roomRow = new Dictionary<string, object>();
    __roomRow["id"] = __room.Id.ToString();
    Parameter __roomName = __room.get_Parameter(BuiltInParameter.ROOM_NAME);
    Parameter __roomNumber = __room.get_Parameter(BuiltInParameter.ROOM_NUMBER);
    if (__roomName == null || __roomNumber == null)
        throw new InvalidOperationException(
            "Room " + __room.Id.ToString() +
            " has no ROOM_NAME/ROOM_NUMBER parameter");
    __roomRow["name"] = __roomName.AsString() ?? "";
    __roomRow["number"] = __roomNumber.AsString() ?? "";
    __roomRow["level_id"] = null;
    __roomRow["level_name"] = null;
    try
    {
        var __level = __room.Level;
        if (__level != null)
        {
            __roomRow["level_id"] = __level.Id.ToString();
            __roomRow["level_name"] = __level.Name ?? "";
        }
    }
    catch { }
    double __roomArea = UnitUtils.ConvertFromInternalUnits(
        __room.Area, UnitTypeId.SquareMeters);
    __roomRow["area_m2"] = __roomArea;
    var __loopsOut = new List<object>();
    var __boundaryIds = new List<object>();
    var __seenBoundaryIds = new HashSet<string>();
    if (__roomArea > 0.0)
    {
        var __loops = __room.GetBoundarySegments(__boundaryOptions);
        if (__loops != null)
        {
            foreach (var __loop in __loops)
            {
                var __points = new List<object>();
                foreach (var __segment in __loop)
                {
                    var __point = __segment.GetCurve().GetEndPoint(0);
                    __points.Add(new double[] {
                        __MM(__point.X), __MM(__point.Y)
                    });
                    var __boundaryId = __segment.ElementId;
                    if (__boundaryId != null &&
                        __boundaryId != ElementId.InvalidElementId)
                    {
                        string __id = __boundaryId.ToString();
                        if (__seenBoundaryIds.Add(__id))
                            __boundaryIds.Add(__id);
                    }
                }
                __loopsOut.Add(__points);
            }
        }
    }
    __roomRow["boundary_loops_mm"] = __loopsOut;
    __roomRow["boundary_mm"] =
        __loopsOut.Count > 0 ? __loopsOut[0] : new List<object>();
    __roomRow["bounding_element_ids"] = __boundaryIds;
    __rooms.Add(__roomRow);
}
return new Dictionary<string, object> {
    {"rooms", __rooms}
};
""".strip()


def build_room_reextract_cs(ids: Sequence[str]) -> str:
    """Read-only body: boundary loops of exactly the created room ids.

    Pure function of the (sorted, deduped) id list.  Non-room ids in ``ids`` are
    simply not matched (the collector is OST_Rooms-scoped), so callers may pass
    the whole created-id set.
    """

    numeric = _numeric_ids(ids)
    if len(numeric) > REEXTRACT_BATCH:
        raise ReExtractError(
            f"room re-extract batch exceeds {REEXTRACT_BATCH} ids")
    literals = ", ".join(f"{value}L" for value in numeric)
    body = _ROOM_BODY_CS.replace("__IDS__", literals, 1)
    return "\n".join((_SOURCE_IS_HOST_CS, _COMMON_HELPERS_CS, body))


def parse_room_reextract(
    payload: Any,
    *,
    requested_ids: Sequence[str] | None = None,
) -> list[RoomInfo]:
    """Parse a Δ-room re-extract payload into validated :class:`RoomInfo`.

    Fail-closed on a malformed envelope; a single unreadable room row is a typed
    :class:`ReExtractError` (never silently dropped, mirroring
    :func:`parse_reextract_rows`).  Rooms are keyed by their NEW Δ id downstream.
    """

    inner = payload
    if isinstance(payload, Mapping) and isinstance(
            payload.get("result"), Mapping):
        inner = payload["result"]
    if not isinstance(inner, Mapping):
        raise ReExtractError("room re-extract payload is not an object")
    raw_rooms = inner.get("rooms")
    if not isinstance(raw_rooms, list):
        raise ReExtractError("room re-extract payload lacks a rooms array")
    rooms: list[RoomInfo] = []
    seen: set[str] = set()
    for index, raw_room in enumerate(raw_rooms):
        try:
            room = RoomInfo.from_dict(raw_room)
        except (L0SchemaError, ValueError) as exc:
            raise ReExtractError(
                f"invalid re-extracted room at index {index}: {exc}") from exc
        if room.id in seen:
            raise ReExtractError(f"room re-extract duplicate id {room.id}")
        seen.add(room.id)
        rooms.append(room)
    rooms.sort(key=lambda room: int(room.id))
    if requested_ids is not None:
        _require_exact_ids(
            requested_ids, [room.id for room in rooms], "room re-extract")
    return rooms


def _numeric_ids(ids: Sequence[str]) -> list[int]:
    numeric: list[int] = []
    for value in ids:
        if isinstance(value, bool):
            raise ReExtractError(
                f"re-extract id {value!r} is not a numeric ElementId")
        try:
            numeric.append(int(value))
        except (TypeError, ValueError) as exc:
            raise ReExtractError(
                f"re-extract id {value!r} is not a numeric ElementId") from exc
    # Deterministic order (I4); duplicates collapse — a duplicate id read twice
    # would produce two identical rows and break L0 uniqueness downstream.
    return sorted(set(numeric))


def _require_exact_ids(
    requested_ids: Sequence[str],
    seen_ids: Sequence[str],
    label: str,
) -> None:
    requested = {str(value) for value in _numeric_ids(requested_ids)}
    seen = {str(value) for value in _numeric_ids(seen_ids)}
    missing = sorted(requested - seen, key=int)
    extra = sorted(seen - requested, key=int)
    if missing or extra:
        detail: list[str] = []
        if missing:
            detail.append("missing=" + ",".join(missing[:20]))
        if extra:
            detail.append("extra=" + ",".join(extra[:20]))
        raise ReExtractError(
            f"{label} requested/seen mismatch: {'; '.join(detail)}")


def build_reextract_cs(ids: Sequence[str]) -> str:
    """Return one read-only body collecting exactly ``ids`` as L0 element rows.

    The body is a pure function of the (sorted, deduped) id list; the emitted C#
    reuses the frozen extract helpers so its version-safety is the extractor's.
    """

    numeric = _numeric_ids(ids)
    if len(numeric) > REEXTRACT_BATCH:
        raise ReExtractError(
            f"re-extract batch exceeds {REEXTRACT_BATCH} ids")
    literals = ", ".join(f"{value}L" for value in numeric)
    candidates, _why = _candidates_cs(numeric)
    body = _ROW_BODY_CS.replace("__IDS__", literals, 1)
    body = body.replace("__CANDIDATES__", candidates, 1)
    return "\n".join((
        _SOURCE_IS_HOST_CS,
        _COMMON_HELPERS_CS,
        # 🔴 THE ROUTE IS DECLARED BEFORE THE HELPERS, AND HERE IT IS SWITCHED OFF.
        #
        # `_ELEMENT_HELPERS_CS` has, since 20.08, called `__RouteSkips`, and it
        # is the route's preamble that declares it. The full extractor lays it
        # down (`extract.build_category_batch_cs`), but this assembly — a
        # SECOND consumer of the same helpers — was not, and the body did not
        # compile: "CS0103: The name '__RouteSkips' does not exist" at line 76.
        # The cost of the silence was measured: the judge of what was built
        # (`built_verdict`) rides exactly this body and refused for 49
        # commits straight, through a whole night of building, printing its
        # refusal into EVERY receipt.
        #
        # Switched off (`None`), not "by category", for a reason of substance:
        # the re-read run is id-addressed and spans several categories — it
        # has no category at all. `_route_cs(None)` yields an empty set and a
        # branch that is never taken, i.e. the previous behaviour
        # byte-for-byte. Cutting off probes here would also be wrong: the
        # judge checks EXACTLY the parameters the program declared.
        _route_cs(None),
        _ELEMENT_HELPERS_CS,
        GEOMETRY_HELPER_CS,
        body,
    ))


def parse_reextract_rows(
    payload: Any,
    *,
    requested_ids: Sequence[str] | None = None,
) -> list[L0Element]:
    """Parse a re-extract bridge payload into validated L0 elements.

    Mirrors ``extract._parse_page``'s row→L0Element path (geometry projection +
    ``L0Element.from_dict``), but is id-scoped (no category/scope invariants).  A
    malformed row is a typed :class:`ReExtractError` (I2 — never silently
    dropped).  Rows are returned sorted by numeric id with duplicates refused.
    """

    inner = payload
    if isinstance(payload, Mapping) and "result" in payload \
            and isinstance(payload.get("result"), Mapping):
        inner = payload["result"]
    if not isinstance(inner, Mapping):
        raise ReExtractError("re-extract payload is not an object")
    raw_elements = inner.get("elements")
    if not isinstance(raw_elements, list):
        raise ReExtractError("re-extract payload lacks an elements array")

    elements: list[L0Element] = []
    seen: set[str] = set()
    for index, raw_element in enumerate(raw_elements):
        if not isinstance(raw_element, Mapping):
            raise ReExtractError(f"re-extract elements[{index}] is not an object")
        element_row = dict(raw_element)
        try:
            geometry = parse_geometry(element_row)
            element_row.update(geometry.to_element_fields())
            element = L0Element.from_dict(element_row)
        except (L0SchemaError, ExtractionProtocolError, ValueError) as exc:
            raise ReExtractError(
                f"invalid re-extracted element at index {index}: {exc}") from exc
        if element.element_id in seen:
            raise ReExtractError(
                f"re-extract returned duplicate id {element.element_id}")
        seen.add(element.element_id)
        elements.append(element)
    elements.sort(key=lambda element: int(element.element_id))
    if requested_ids is not None:
        # 🔴 A TYPE IS NOT A LOSS, BUT A DIFFERENT KIND. The body deliberately
        # drops `ElementType` (see `_CANDIDATES_DIRECT_CS`), and before 21.08
        # it landed in `missing` right alongside a real loss. The first live
        # `author_family` stumbled on exactly this: its identity IS a type —
        # a family's definition stands nowhere, its instance does — and the
        # judge of what was built refused wholesale, naming a number instead
        # of a reason.
        #
        # The distinction is honest in both directions: what was skipped is
        # ENUMERATED by the body, not inferred here by guesswork, and only
        # that is subtracted. A real loss (an id absent from the document) is
        # still a refusal.
        skipped = _proved_skipped_types(
            inner,
            requested_ids=[str(value) for value in requested_ids],
            returned_ids={element.element_id for element in elements},
        )
        wanted = [str(x) for x in requested_ids if str(x) not in skipped]
        _require_exact_ids(
            wanted,
            [element.element_id for element in elements],
            "re-extract",
        )
    return elements


def _proved_skipped_types(
    inner: Mapping[str, Any],
    *,
    requested_ids: Sequence[str],
    returned_ids: set[str],
) -> set[str]:
    """Skips that the bridge's response PROVED, not merely named.

    🔴 WHY THIS FUNCTION EXISTS (F-213, 02.09.2026). Before it, the
    subtraction looked like this: ``skipped =
    inner.get("skipped_element_types")`` — and that was all. Not one
    condition. That is, THE RESPONSE ITSELF DECIDED what not to be asked
    about:

        parse_reextract_rows({"elements": [], "skipped_element_types": ["42"]},
                             requested_ids=["42"])        -> []  with no complaint
        parse_reextract_rows({"elements": [], "skipped_element_types": []},
                             requested_ids=["42"])        -> ReExtractError

    The very same real refusal ("the created element was not found") hid
    behind one line in the bridge's own response, and the judge of what was
    built got a clean success. The difference between "we looked and it is
    a type" and "we were just told so" is exactly the subject of §18.2.

    Four conditions, each killing its OWN way of lying:

    * the skip has EVIDENCE (``skipped_element_type_proof`` with the
      element's class) — without it the skip is once again the bridge's
      own word about itself;
    * the id sets of the evidence and of the skip list MATCH — otherwise
      evidence could be produced for one id while subtracting ten;
    * the skipped id was REQUESTED — the bridge has no right to withdraw a
      question it was never asked;
    * the skipped id did NOT COME BACK as a row — "skipped and returned" is
      a contradiction, and silently picking one half means guessing.

    The refusal is typed (``ReExtractError``), not soft: an empty set
    cannot be returned — that is exactly the silence all of this was
    written to forbid.
    """

    raw_skipped = inner.get(SKIPPED_TYPES_KEY)
    if raw_skipped is None:
        raw_skipped = []
    if not isinstance(raw_skipped, list):
        raise ReExtractError(
            "re-extract skipped_element_types must be an array")
    skipped = [str(value) for value in raw_skipped]
    raw_proof = inner.get(SKIPPED_TYPE_PROOF_KEY)
    if raw_proof is None:
        raw_proof = []
    if not isinstance(raw_proof, list):
        raise ReExtractError(
            "re-extract skipped_element_type_proof must be an array")
    proved: dict[str, str] = {}
    for index, row in enumerate(raw_proof):
        if not isinstance(row, Mapping):
            raise ReExtractError(
                f"re-extract skipped_element_type_proof[{index}] "
                "is not an object")
        element_id = row.get("element_id")
        class_name = row.get(SKIPPED_PROOF_CLASS_FIELD)
        if not isinstance(element_id, str) or not element_id:
            raise ReExtractError(
                f"re-extract skipped_element_type_proof[{index}] "
                "lacks an element_id")
        if not isinstance(class_name, str) or not class_name:
            raise ReExtractError(
                "re-extract skip of id "
                f"{element_id} carries no proving class name")
        proved[element_id] = class_name
    if set(skipped) != set(proved):
        unproved = sorted(set(skipped) - set(proved), key=element_id_key)
        unclaimed = sorted(set(proved) - set(skipped), key=element_id_key)
        raise ReExtractError(
            "re-extract skipped ids are not the proved ids: "
            f"unproved={','.join(unproved) or '-'} "
            f"unclaimed={','.join(unclaimed) or '-'}")
    requested = set(requested_ids)
    intruders = sorted(set(skipped) - requested, key=element_id_key)
    if intruders:
        raise ReExtractError(
            "re-extract skipped ids that were never requested: "
            + ",".join(intruders))
    contradictory = sorted(set(skipped) & returned_ids, key=element_id_key)
    if contradictory:
        raise ReExtractError(
            "re-extract both returned and skipped: " + ",".join(contradictory))
    return set(skipped)


def reextracted_document(
    metadata: L0Document,
    elements: Sequence[L0Element],
    *,
    change_stamp: str | None = None,
    rooms: Sequence[RoomInfo] | None = None,
) -> L0Document:
    """Assemble an L0Document from re-extracted elements + original metadata.

    The Δ-rebuild pinned levels/grids by their EXISTING ElementIds, so the copy's
    datum context is unchanged; re-lift must use the same levels/grids so hosted
    refs and level bindings resolve exactly as the decompile did.  Only the
    element population is replaced with the re-extracted subset.

    ``rooms`` overrides the room context: the Δ-rebuild CREATES new rooms with
    new ids, so re-lifting them needs THEIR OWN re-extracted boundaries (keyed by
    the new id), not the original metadata rooms.  ``None`` keeps the original
    rooms (legacy path / no created rooms).
    """

    return L0Document(
        doc_name=metadata.doc_name,
        revit_version=metadata.revit_version,
        units=metadata.units,
        change_stamp=change_stamp or metadata.change_stamp,
        levels=metadata.levels,
        grids=metadata.grids,
        rooms=tuple(rooms) if rooms is not None else metadata.rooms,
        project_info=metadata.project_info,
        elements=tuple(elements),
    )


__all__ = [
    "ACTIVE_VIEW_VISIBILITY_ERROR_KEY",
    "ACTIVE_VIEW_VISIBILITY_STATE_KEY",
    "ACTIVE_VIEW_VISIBILITY_STATES",
    "ACTIVE_VIEW_VISIBLE_KEY",
    "SKIPPED_PROOF_CLASS_FIELD",
    "SKIPPED_TYPES_KEY",
    "SKIPPED_TYPE_PROOF_KEY",
    "ReExtractError",
    "REEXTRACT_BATCH",
    "build_reextract_cs",
    "parse_reextract_rows",
    "reextracted_document",
]
