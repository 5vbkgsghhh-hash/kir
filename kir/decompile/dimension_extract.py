"""The DIMENSION side index: the one true reading hole of three.

THE TRIGGER IS A RE-LIFT, NOT A PLAN. The ranking this wave started with
named three reading holes: ``create_tag`` (20,459), ``create_dimension``
(13,908) and ``create_text`` (2,786) — all three "the operation is written,
but L0 carries NONE of its inputs". A re-lift of
``backend/data/decompile/k2_ar_rd_v8`` by the current lifter said something
else, read off ``atom_details`` rows, not from memory::

    13905  create_dimension ... L0 1.0 carries NONE of its inputs
      317  create_tag ... L0 1.0 carries NONE of its inputs
        0  create_text  (2697 of 2697 lifted into create_text)

Of the three "reading holes", two had already been closed before this wave:
the annotation stage reads all 2,697 notes, the tag stage reads 20,131 of
20,448 tags. The remaining 19,280 tags are refused for FORWARD-pass reasons
(11,594 SpatialElementTag, 4,122 leader, 3,564 orientation), not because
there is nothing to read them with. A dimension stage did not exist at
all — 13,905 of 13,905 — and that is exactly the hole this wave was started
for.

WHAT IS READ AND HOW THAT IS PROVEN. Not one name from memory: every member
below is named by the COMPILER through a deliberate CS0029 error (the
``tests/emitted_csharp_signature_closure`` technique — the compiler must
NAME the type in order to refuse), checked on 2021, 2023 and 2026::

    Dimension.References       -> Autodesk.Revit.DB.ReferenceArray
    Dimension.Curve            -> Autodesk.Revit.DB.Curve
    Dimension.Origin           -> Autodesk.Revit.DB.XYZ
    Dimension.NumberOfSegments -> int
    Dimension.DimensionShape   -> Autodesk.Revit.DB.DimensionShape
    Reference.ElementId        -> Autodesk.Revit.DB.ElementId
    Element.OwnerViewId        -> Autodesk.Revit.DB.ElementId

THE ``System.dll`` TRAP IS NOT HERE, AND THAT IS VERIFIED, NOT ASSUMED. The
tag stage died live on 04.08 on ``CS0012: The type ISet<> is defined in an
assembly that is not referenced`` — ``GetTaggedLocalElementIds`` returns an
``ISet<>`` from ``System.dll``, which is absent from the DEPLOYED plugin's
reference closure. So the FIRST thing asked of the compiler here is the type
of ``Dimension.References``: ``ReferenceArray`` lives in ``RevitAPI.dll``,
and ``foreach (Reference r in d.References)`` compiles on 2021 and 2023.

``ElementId.IntegerValue`` IS NOT USED: on 2026 this is ``CS1061``
(measured by the same run). The id travels as a string via
``ElementId.ToString()``, as in all neighbouring stages.

WHY ``line_at`` CLOSES BY IDENTITY, NOT BY COINCIDENCE. On the forward pass,
``line_at`` is ONE ANCHOR point that the dimension's line passes through;
the forward pass takes the direction from the first reference's normal, not
from it. Its own docstring (``authoring._emit_dimension``) cites the Revit
API Developer Guide: ``Dimension.Curve`` is ALWAYS unbound, and the
``Origin``'s position ALONG the line is an emergent property of where the
references project, not our input. So the lift side is satisfied with ANY
point on that line, and ``Dimension.Origin`` (the "midpoint of the
dimension line") is one by definition. The loop closes with the same view
basis (``rel = P - view.Origin; u = rel*Right; v = rel*Up``) that closes it
for tags and notes.

FOR THE SAME REASON THERE IS NO ``GetEndPoint`` HERE: on an unbound curve it
throws. From ``Dimension.Curve`` only ``Line.Origin`` is taken, and only as
a fallback, if ``Origin`` did not answer.

WHAT IS NOT HERE, AND WHY. ``SpotDimension`` (a spot elevation) is a
SUBCLASS of ``Dimension``, but the forward pass builds a dimension in
exactly one way, ``doc.Create.NewDimension``; an elevation mark is an
element of a different class, and rebuilding it would produce the wrong
element. The refusal is typed (``element_kind_mismatch``), not "close
enough". The elevation-mark category is separate (``OST_SpotElevations``,
2,292 elements in the same document) and is outside this stage.

WHAT THIS STAGE DOES NOT SETTLE (named, not hidden). An op's ``refs`` are
ELEMENTS, while ``NewDimension`` requires GEOMETRIC references (face/edge);
the forward pass picks a face through its own traversal. So the lift side
records BETWEEN WHAT a dimension ran, but not BY WHICH FACES it was drawn.
Whether the NUMBER matches after a rebuild is a question for a LIVE
session, not for this file: what is recorded here is exactly what was read,
and not one field beyond that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping

from kir.emit_utils import cs_string_literal
from kir.decompile.side_contract import (
    ELEMENT_ID_HELPER_CS,
    ELEMENT_ID_OUT_OF_RANGE_REASON,
    optional_failures,
    source_binding_cs,
)

DIMENSION_INDEX_SCHEMA_VERSION = "kir-decompile-dimension-index/1"
DIMENSION_EXTRACT_SCHEMA_VERSION = "kir-decompile-dimension-extract/1"

#: Categories this stage feeds. Moves TOGETHER with the row in
#: ``pipeline._STAGE_CATEGORIES``: a category here without a row there means
#: an id is never requested; a row there without a category here means every
#: id leaves with a receipt.
#:
#: EXACTLY ONE, and this is not stinginess. ``OST_SpotElevations`` (2,292)
#: and ``OST_WeakDims`` (19,547) sit in the census of the SAME document and
#: compile, but the first is a different element class for the FORWARD pass,
#: and the second is auto-dimensioning inside a sketch, which has no
#: standalone operation at all. A closed list is no place for guesses (the
#: same rule by which ``OST_CurtainGrids`` was not let into the category
#: table on 28.07).
DIMENSION_CATEGORIES = frozenset({"OST_Dimensions"})

#: The smallest number of references a dimension can even consist of. A
#: dimension with one reference has nothing to measure, and
#: ``create_dimension`` will not build one.
DIMENSION_MIN_REFS = 2

#: The only dimension shape the FORWARD pass builds: it knows exactly
#: ``doc.Create.NewDimension(view, Line, ReferenceArray)``, and that is a
#: linear dimension. The member name
#: ``Autodesk.Revit.DB.DimensionShape.Linear`` is named by the compiler on
#: 2021 and 2026, not taken from documentation.
#:
#: The constant lives HERE, not in the lifter, for the same reason the
#: categories live here too: a value written down in one place and
#: forgotten in another is either a mute refusal or a coverage claim that
#: does not hold.
DIMENSION_SHAPE_LINEAR = "Linear"

_FT_TO_MM = 304.8


class DimensionPayloadError(ValueError):
    """A wire response of the wrong shape — a typed refusal, not a guess."""


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DimensionPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise DimensionPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise DimensionPayloadError(f"{field_name} must be an array")
    return value


def _exact_fields(value: Any, allowed: set[str], field_name: str, *,
                  optional: set[str] | None = None) -> dict[str, Any]:
    root = _mapping(value, field_name)
    optional = optional or set()
    missing = allowed - optional - set(root)
    if missing:
        raise DimensionPayloadError(f"{field_name} is missing {sorted(missing)}")
    extra = set(root) - allowed
    if extra:
        raise DimensionPayloadError(
            f"{field_name} has unexpected {sorted(extra)}")
    return root


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DimensionPayloadError(f"{field_name} must be a non-empty string")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DimensionPayloadError(f"{field_name} must be a number")
    return float(value)


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DimensionPayloadError(
            f"{field_name} must be a non-negative integer")
    return value


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return (0, int(value), value)
    except (TypeError, ValueError):
        return (1, value, value)


@dataclass(frozen=True, slots=True)
class DimensionRecord:
    """One dimension: a view, a point on its line, and BETWEEN WHAT it runs."""

    element_id: str
    #: The owning view (``Element.OwnerViewId``). THE VIEW-BINDING LAW: a
    #: view's point exists only in its own view's plane.
    owner_view_id: str
    #: The view's name. The L1 reference dialect knows exactly one named
    #: form — ``{"by": "name", "value": <name>, "_id": <id>}`` — a reference
    #: cannot be assembled without a name.
    owner_view_name: str
    #: The point ON the dimension's LINE in view coordinates, millimetres.
    #: An anchor, not a segment's midpoint: the position along the line is
    #: emergent (see the module docstring).
    line_at_view_mm: tuple[float, float]
    #: The elements a dimension runs between, in ``References`` order.
    #: Revit's order is kept verbatim: ``NewDimension`` builds a
    #: multi-segment dimension exactly in reference order.
    ref_element_ids: tuple[str, ...]
    #: ``Dimension.NumberOfSegments``. A linear dimension has one fewer
    #: segment than references; a mismatch is evidence a live session must
    #: explain, so the number travels rather than being derived.
    segment_count: int
    #: ``Dimension.DimensionShape`` as a string (Linear / Radial / Angular /
    #: ...). The forward pass builds LINEAR; there is nothing to lift the
    #: rest with, and this is decided by the lifter, not the reader: the
    #: reader must read and name it.
    dimension_shape: str
    type_id: str | None = None
    type_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "element_id": self.element_id,
            "owner_view_id": self.owner_view_id,
            "owner_view_name": self.owner_view_name,
            "line_at_view_mm": [
                float(self.line_at_view_mm[0]), float(self.line_at_view_mm[1])],
            "ref_element_ids": list(self.ref_element_ids),
            "segment_count": self.segment_count,
            "dimension_shape": self.dimension_shape,
        }
        if self.type_id is not None:
            payload["type_id"] = self.type_id
        if self.type_name is not None:
            payload["type_name"] = self.type_name
        return payload

    @classmethod
    def from_dict(cls, value: Any) -> "DimensionRecord":
        root = _exact_fields(
            value,
            {"element_id", "owner_view_id", "owner_view_name",
             "line_at_view_mm", "ref_element_ids", "segment_count",
             "dimension_shape", "type_id", "type_name"},
            "dimension record", optional={"type_id", "type_name"})
        at = _array(root["line_at_view_mm"], "dimension record.line_at_view_mm")
        if len(at) != 2:
            raise DimensionPayloadError(
                "dimension record.line_at_view_mm must be [u, v]")
        refs = _array(root["ref_element_ids"],
                      "dimension record.ref_element_ids")
        if len(refs) < DIMENSION_MIN_REFS:
            raise DimensionPayloadError(
                "dimension record.ref_element_ids needs at least "
                f"{DIMENSION_MIN_REFS} entries")
        type_id = root.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise DimensionPayloadError(
                "dimension record.type_id must be a string")
        type_name = root.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise DimensionPayloadError(
                "dimension record.type_name must be a string")
        return cls(
            element_id=_string(root["element_id"],
                               "dimension record.element_id"),
            owner_view_id=_string(root["owner_view_id"],
                                  "dimension record.owner_view_id"),
            owner_view_name=_string(root["owner_view_name"],
                                    "dimension record.owner_view_name"),
            line_at_view_mm=(
                _number(at[0], "dimension record.line_at_view_mm[0]"),
                _number(at[1], "dimension record.line_at_view_mm[1]")),
            ref_element_ids=tuple(
                _string(item, f"dimension record.ref_element_ids[{index}]")
                for index, item in enumerate(refs)),
            segment_count=_nonnegative_int(
                root["segment_count"], "dimension record.segment_count"),
            dimension_shape=_string(root["dimension_shape"],
                                    "dimension record.dimension_shape"),
            type_id=type_id or None,
            type_name=type_name or None,
        )


@dataclass(frozen=True, slots=True)
class DimensionFailure:
    """A receipt: "did not read — and here is why". Silence is forbidden (§18.2)."""

    element_id: str
    reason: str
    typed_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "element_id": self.element_id,
            "reason": self.reason,
            "typed_reason": self.typed_reason,
        }

    @classmethod
    def from_dict(cls, value: Any) -> "DimensionFailure":
        root = _exact_fields(
            value, {"element_id", "reason", "typed_reason"},
            "dimension failure")
        return cls(
            element_id=_string(root["element_id"],
                               "dimension failure.element_id"),
            reason=_string(root["reason"], "dimension failure.reason"),
            typed_reason=_string(root["typed_reason"],
                                 "dimension failure.typed_reason"),
        )


@dataclass(frozen=True, slots=True)
class DimensionExtraction:
    """The stage's result.

    ``records`` and ``failures`` are the NAMES THE §18.2 RECONCILER ASKS
    FOR, and they are not accidental here. The annotation stage named its
    field ``text_notes``; its C# worked perfectly on the bridge, and the
    full run failed after ninety minutes with
    ``side_stage_count_mismatch: requested 26, without a row and without a
    receipt 26``. ``dimensions`` is kept as the READABLE name, while
    ``records`` answers the reconciler — exactly like ``tags``/``records``
    for the tag stage.
    """

    dimensions: tuple[DimensionRecord, ...] = ()
    failures: tuple[DimensionFailure, ...] = ()

    @property
    def records(self) -> tuple[DimensionRecord, ...]:
        return self.dimensions

    @property
    def dimension_index(self) -> dict[str, dict[str, Any]]:
        """id -> row. The lifter's address: it asks by element_id.

        **BUILDS THE WHOLE DICT ON EVERY ACCESS — O(n), not a field.**
        Read it EXACTLY ONCE into a local variable; accessing it from inside
        a comprehension or loop makes the work quadratic. Live on
        2026-08-12: `to_dict` read this property for every key, and on the
        tower's 13,905 dimensions the stage serialized for 20+ minutes
        without reaching the file write (`tools` stack: `to_dict →
        dimension_index → to_dict → _persist_json`). Measured: n=500 0.21s,
        1000 1.06, 2000 4.62, 4000 21.26 — ×4.6 per doubling. The goldens
        run 2-5 records, where a square is indistinguishable from a line, so
        offline testing could not have seen it.
        """
        return {record.element_id: record.to_dict()
                for record in self.dimensions}

    def to_dict(self) -> dict[str, Any]:
        # ONE access to the property; see its docstring — it is O(n).
        index = self.dimension_index
        return {
            "schema_version": DIMENSION_INDEX_SCHEMA_VERSION,
            "dimension_index": {
                key: index[key]
                for key in sorted(index, key=_element_id_key)},
            "failures": [failure.to_dict()
                         for failure in sorted(
                             self.failures,
                             key=lambda item: _element_id_key(
                                 item.element_id))],
        }

    @classmethod
    def from_dict(cls, value: Any) -> "DimensionExtraction":
        root = _exact_fields(
            value, {"schema_version", "dimension_index", "failures"},
            "dimension extraction", optional={"failures"})
        if root["schema_version"] != DIMENSION_INDEX_SCHEMA_VERSION:
            raise DimensionPayloadError(
                "dimension extraction schema_version mismatch")
        index = _mapping(root["dimension_index"],
                         "dimension extraction.dimension_index")
        records = []
        for key, row in index.items():
            record = DimensionRecord.from_dict(row)
            if record.element_id != key:
                raise DimensionPayloadError(
                    f"dimension_index[{key!r}] holds element_id "
                    f"{record.element_id!r}")
            records.append(record)
        failures = tuple(
            DimensionFailure.from_dict(row)
            for row in optional_failures(
                root.get("failures"), "dimension extraction.failures",
                DimensionPayloadError))
        return cls(dimensions=tuple(records), failures=failures)


def extract_dimensions(payload: Any) -> DimensionExtraction:
    """Validate one bridge response and assemble the index.

    A malformed wire shape is a typed exception. An honest refusal for a
    SPECIFIC element is a receipt row, not an exception: the stage must
    finish reading the rest and name what was missed.
    """
    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "elements", "failures"},
        "Dimension extraction", optional={"failures"})
    if root["schema_version"] != DIMENSION_EXTRACT_SCHEMA_VERSION:
        raise DimensionPayloadError(
            "Dimension extraction schema_version mismatch")

    records: list[DimensionRecord] = []
    for index, row in enumerate(_array(root["elements"],
                                       "Dimension extraction.elements")):
        item = _exact_fields(
            row,
            {"element_id", "owner_view_id", "owner_view_name",
             "line_at_view_ft", "ref_element_ids", "segment_count",
             "dimension_shape", "type_id", "type_name"},
            f"Dimension extraction.elements[{index}]",
            optional={"type_id", "type_name"})
        at = _array(item["line_at_view_ft"],
                    f"elements[{index}].line_at_view_ft")
        if len(at) != 2:
            raise DimensionPayloadError(
                f"elements[{index}].line_at_view_ft must be [u, v]")
        refs = _array(item["ref_element_ids"],
                      f"elements[{index}].ref_element_ids")
        if len(refs) < DIMENSION_MIN_REFS:
            raise DimensionPayloadError(
                f"elements[{index}].ref_element_ids needs at least "
                f"{DIMENSION_MIN_REFS} entries")
        type_id = item.get("type_id")
        if type_id is not None and not isinstance(type_id, str):
            raise DimensionPayloadError(
                f"elements[{index}].type_id must be a string")
        type_name = item.get("type_name")
        if type_name is not None and not isinstance(type_name, str):
            raise DimensionPayloadError(
                f"elements[{index}].type_name must be a string")
        records.append(DimensionRecord(
            element_id=_string(item["element_id"],
                               f"elements[{index}].element_id"),
            owner_view_id=_string(item["owner_view_id"],
                                  f"elements[{index}].owner_view_id"),
            owner_view_name=_string(item["owner_view_name"],
                                    f"elements[{index}].owner_view_name"),
            # THE CONVERSION LIVES HERE AND ONLY HERE: the wire carries raw feet.
            line_at_view_mm=(
                _number(at[0], f"elements[{index}].line_at_view_ft[0]")
                * _FT_TO_MM,
                _number(at[1], f"elements[{index}].line_at_view_ft[1]")
                * _FT_TO_MM),
            ref_element_ids=tuple(
                _string(value, f"elements[{index}].ref_element_ids[{position}]")
                for position, value in enumerate(refs)),
            segment_count=_nonnegative_int(
                item["segment_count"], f"elements[{index}].segment_count"),
            dimension_shape=_string(item["dimension_shape"],
                                    f"elements[{index}].dimension_shape"),
            type_id=type_id or None,
            type_name=type_name or None,
        ))

    failures = tuple(
        DimensionFailure.from_dict(row)
        for row in optional_failures(
            root.get("failures"), "Dimension extraction.failures",
            DimensionPayloadError))
    return DimensionExtraction(dimensions=tuple(records), failures=failures)


def merge_dimensions(parts: list[DimensionExtraction]) -> DimensionExtraction:
    """Merge one stage's pages without losing a record or a receipt."""
    records: list[DimensionRecord] = []
    failures: list[DimensionFailure] = []
    seen: set[str] = set()
    for part in parts:
        for record in part.dimensions:
            # The FIRST one read wins, not the last: "last wins" would
            # make the result depend on page order, that is, on the
            # network.
            if record.element_id in seen:
                continue
            seen.add(record.element_id)
            records.append(record)
        failures.extend(part.failures)
    return DimensionExtraction(dimensions=tuple(records),
                               failures=tuple(failures))


def parse_dimension_index(payload: Any) -> DimensionExtraction:
    """A persistent envelope from disk -> the stage's result."""
    return DimensionExtraction.from_dict(payload)


def _unwrap_bridge_payload(payload: Any) -> Any:
    """The bridge wraps the response in an envelope; the stage also reads a bare dict."""
    value = payload
    for _ in range(4):
        if not isinstance(value, Mapping):
            break
        if "schema_version" in value:
            return value
        for key in ("result", "value", "payload", "data"):
            if key in value:
                value = value[key]
                break
        else:
            break
    return value


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


DIMENSION_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE — read-only dimension helpers. Никаких транзакций.
// Точка на линии считается ТОЙ ЖЕ формулой, что и прямой эмиттер:
//   rel = P - view.Origin;  u = rel·view.RightDirection;  v = rel·view.UpDirection
// Провод несёт СЫРЫЕ футы; пересчёт в мм принадлежит офлайн-разборщику.
//
// Имя класса берётся из Object.ToString() БЕЗ обращения к среде выполнения за
// типом: та форма записи целиком отвергается валидатором безопасности моста
// версий до 06.07.2026, который всё ещё стоит на части флота. Приём и его
// обоснование дословно те же, что в tag_extract.py.
Func<object, string> __dmClassName = (__dmcnObj) =>
{
    if (__dmcnObj == null) return "";
    string __dmcn = __dmcnObj.ToString();
    if (__dmcn == null) return "";
    int __dmcnCut = __dmcn.IndexOf((char)10);
    if (__dmcnCut >= 0) __dmcn = __dmcn.Substring(0, __dmcnCut);
    __dmcnCut = __dmcn.IndexOf(':');
    if (__dmcnCut >= 0) __dmcn = __dmcn.Substring(0, __dmcnCut);
    __dmcn = __dmcn.Trim();
    __dmcnCut = __dmcn.LastIndexOf('.');
    return __dmcnCut >= 0 && __dmcnCut + 1 < __dmcn.Length
        ? __dmcn.Substring(__dmcnCut + 1) : __dmcn;
};
// ElementId.IntegerValue НЕ ИСПОЛЬЗУЕТСЯ: на 2026 это CS1061 (замерено).
Func<ElementId, string> __dmValidIdString = (__id) =>
    (__id == null || __id == ElementId.InvalidElementId)
        ? null : __id.ToString();
Func<double, bool> __dmFinite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
"""


_DIMENSION_EXTRACT_BODY_CS = r"""
long __dmCallBudgetMs = __DM_CALL_BUDGET_MS__L;
long __dmCallWatchT0 = DateTime.UtcNow.Ticks;

var __dmFailures = new List<object>();
Action<string, string, string> __dmFail =
    (__failedId, __reason, __typed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __dmFailures.Add(__failure);
};

var __dmIds = new List<string> { __DIMENSION_IDS__ };
var __dmRows = new List<object>();
bool __dmBudgetOut = false;
foreach (string __dmRaw in __dmIds)
{
    if (__dmBudgetOut
        || ((DateTime.UtcNow.Ticks - __dmCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __dmCallBudgetMs)
    {
        __dmBudgetOut = true;
        __dmFail(__dmRaw, "call_budget_exhausted", "call_budget_exhausted");
        continue;
    }
    // ИМЯ ШАГА, КОТОРЫЙ СЕЙЧАС ИДЁТ. Урок 2846 групп: тип исключения без
    // имени вызова — одно ведро на всё, и по нему нельзя сказать ни ЧТО
    // читали, ни ЧТО ответил Revit.
    string __dmStep = "ElementId.Parse";
    try
    {
        long __dmNum = 0L;
        if (!Int64.TryParse(__dmRaw, out __dmNum))
        {
            __dmFail(__dmRaw, "element id is not numeric", "element_unresolved");
            continue;
        }
        __dmStep = "Document.GetElement";
        ElementId __dmId = __sideElementId(__dmNum);
        if (__dmId == null)
        {
            __dmFail(__dmRaw, "__ELEMENT_ID_OUT_OF_RANGE__", "element_unresolved");
            continue;
        }
        Element __dmEl = __src.GetElement(__dmId);
        if (__dmEl == null)
        {
            __dmFail(__dmRaw, "element not found in document", "element_unresolved");
            continue;
        }
        __dmStep = "cast to Dimension";
        Autodesk.Revit.DB.Dimension __dmDim =
            __dmEl as Autodesk.Revit.DB.Dimension;
        if (__dmDim == null)
        {
            __dmFail(__dmRaw,
                     "not a dimension element: " + __dmClassName(__dmEl),
                     "element_kind_mismatch");
            continue;
        }
        // ВЫСОТНАЯ ОТМЕТКА — ПОДКЛАСС Dimension, но прямой ход строит размер
        // ровно одним способом (doc.Create.NewDimension); пересборка отметки
        // дала бы элемент другого класса, а не эту отметку.
        __dmStep = "cast to SpotDimension";
        Autodesk.Revit.DB.SpotDimension __dmSpot =
            __dmEl as Autodesk.Revit.DB.SpotDimension;
        if (__dmSpot != null)
        {
            __dmFail(__dmRaw,
                     "spot dimension (SpotDimension) is not built by "
                         + "NewDimension; create_dimension would rebuild "
                         + "another element class",
                     "element_kind_mismatch");
            continue;
        }

        __dmStep = "Element.OwnerViewId";
        ElementId __dmViewId = __dmEl.OwnerViewId;
        string __dmViewIdStr = __dmValidIdString(__dmViewId);
        if (__dmViewIdStr == null)
        {
            // ЗАКОН ПРИВЯЗКИ К ВИДУ: аннотация живёт в конкретном виде, и
            // точка вида существует ТОЛЬКО в его плоскости.
            __dmFail(__dmRaw, "dimension has no owner view", "aspect_not_present");
            continue;
        }
        __dmStep = "Document.GetElement(OwnerViewId) as View";
        Autodesk.Revit.DB.View __dmView =
            __src.GetElement(__dmViewId) as Autodesk.Revit.DB.View;
        if (__dmView == null)
        {
            __dmFail(__dmRaw, "owner view is not a View element",
                     "aspect_not_present");
            continue;
        }

        __dmStep = "View basis (Origin/RightDirection/UpDirection)";
        XYZ __dmOrigin = __dmView.Origin;
        XYZ __dmRight = __dmView.RightDirection;
        XYZ __dmUp = __dmView.UpDirection;
        if (__dmOrigin == null || __dmRight == null || __dmUp == null)
        {
            __dmFail(__dmRaw, "owner view has no usable basis",
                     "dimension_line_unreadable");
            continue;
        }

        // ТОЧКА НА ЛИНИИ РАЗМЕРА. Dimension.Origin — «средняя точка линии
        // размера»; для многосегментных её документация объявляет
        // неприменимой и на SpotDimension бросает (те отказаны выше).
        // Запасной ход — Dimension.Curve, у которой берётся ТОЛЬКО Origin:
        // кривая размера документирована ВСЕГДА неограниченной, и
        // GetEndPoint на ней бросает.
        __dmStep = "Dimension.Origin";
        XYZ __dmPoint = null;
        try { __dmPoint = __dmDim.Origin; } catch { __dmPoint = null; }
        if (__dmPoint == null)
        {
            __dmStep = "Dimension.Curve as Line -> Origin";
            try
            {
                Line __dmLine = __dmDim.Curve as Line;
                if (__dmLine != null) __dmPoint = __dmLine.Origin;
            }
            catch { __dmPoint = null; }
        }
        if (__dmPoint == null)
        {
            __dmFail(__dmRaw,
                     "neither Dimension.Origin nor Dimension.Curve gave a "
                         + "point on the dimension line",
                     "dimension_line_unreadable");
            continue;
        }

        __dmStep = "project point into view basis";
        XYZ __dmRel = __dmPoint - __dmOrigin;
        double __dmU = __dmRel.DotProduct(__dmRight);
        double __dmV = __dmRel.DotProduct(__dmUp);
        if (!__dmFinite(__dmU) || !__dmFinite(__dmV))
        {
            __dmFail(__dmRaw, "dimension line point is not finite in view space",
                     "dimension_line_unreadable");
            continue;
        }

        // МЕЖДУ ЧЕМ ПРОВЕДЁН РАЗМЕР. Dimension.References -> ReferenceArray
        // (тип назван компилятором; RevitAPI.dll, не System.dll — ловушки
        // ISet<>, убившей стадию марок, здесь нет).
        __dmStep = "Dimension.References";
        var __dmRefIds = new List<object>();
        bool __dmRefBad = false;
        string __dmRefWhy = "";
        ReferenceArray __dmRefs = __dmDim.References;
        if (__dmRefs == null)
        {
            __dmFail(__dmRaw, "dimension has no references at all",
                     "aspect_not_present");
            continue;
        }
        foreach (Reference __dmRef in __dmRefs)
        {
            if (__dmRef == null)
            {
                __dmRefBad = true;
                __dmRefWhy = "a reference of this dimension is null";
                break;
            }
            string __dmRefId = __dmValidIdString(__dmRef.ElementId);
            if (__dmRefId == null)
            {
                // Ссылка на элемент СВЯЗАННОГО файла или на то, чего в этом
                // документе не адресовать: refs опа собрать нечем. Привязать
                // размер к похожему элементу своего файла — худшее, что здесь
                // можно сделать: это прошло бы схему L1 и выглядело бы
                // покрытием (§18.1).
                __dmRefBad = true;
                __dmRefWhy = "a reference of this dimension names no element "
                    + "of this document (linked host or non-element reference)";
                break;
            }
            __dmRefIds.Add(__dmRefId);
        }
        if (__dmRefBad)
        {
            __dmFail(__dmRaw, __dmRefWhy, "dimension_ref_not_local");
            continue;
        }
        if (__dmRefIds.Count < __DM_MIN_REFS__)
        {
            __dmFail(__dmRaw,
                     "dimension binds " + __dmRefIds.Count.ToString()
                         + " element(s); create_dimension needs at least "
                         + "__DM_MIN_REFS__",
                     "aspect_not_present");
            continue;
        }

        __dmStep = "Dimension.NumberOfSegments";
        int __dmSegments = 0;
        try { __dmSegments = __dmDim.NumberOfSegments; } catch { __dmSegments = 0; }
        if (__dmSegments < 0) __dmSegments = 0;

        __dmStep = "Dimension.DimensionShape";
        string __dmShape = "";
        try { __dmShape = __dmDim.DimensionShape.ToString(); } catch { __dmShape = ""; }
        if (__dmShape == null || __dmShape.Length == 0) __dmShape = "Unknown";

        __dmStep = "Element.GetTypeId";
        string __dmTypeIdStr = null;
        string __dmTypeName = null;
        try
        {
            ElementId __dmTypeId = __dmEl.GetTypeId();
            __dmTypeIdStr = __dmValidIdString(__dmTypeId);
            if (__dmTypeIdStr != null)
            {
                Element __dmType = __src.GetElement(__dmTypeId);
                if (__dmType != null) __dmTypeName = __dmType.Name;
            }
        }
        catch { __dmTypeIdStr = null; __dmTypeName = null; }

        var __dmRow = new Dictionary<string, object>();
        __dmRow["element_id"] = __dmRaw;
        __dmRow["owner_view_id"] = __dmViewIdStr;
        __dmRow["owner_view_name"] = __dmView.Name;
        __dmRow["line_at_view_ft"] = new List<object> { __dmU, __dmV };
        __dmRow["ref_element_ids"] = __dmRefIds;
        __dmRow["segment_count"] = __dmSegments;
        __dmRow["dimension_shape"] = __dmShape;
        if (__dmTypeIdStr != null && __dmTypeName != null)
        {
            __dmRow["type_id"] = __dmTypeIdStr;
            __dmRow["type_name"] = __dmTypeName;
        }
        __dmRows.Add(__dmRow);
    }
    catch (Exception __dmEx)
    {
        __dmFail(__dmRaw, __dmStep + ": " + __dmClassName(__dmEx), "read_failed");
    }
}

var __dmPayload = new Dictionary<string, object>();
__dmPayload["schema_version"] = __DM_SCHEMA__;
__dmPayload["elements"] = __dmRows;
__dmPayload["failures"] = __dmFailures;
return __dmPayload;
"""


def build_dimension_extract_cs(element_ids: list[str], *,
                               call_budget_ms: int = 20_000,
                               link_title: str | None = None) -> str:
    """The C# for one page of the dimension stage.

    THERE IS NO VERSION HERE, and this is MEASURED, not an oversight. For
    the tag stage a version is a required input, because the tag's target
    has not one member living across all six versions. For a dimension, all
    the needed members live across all six (``References`` / ``Curve`` /
    ``Origin`` / ``NumberOfSegments`` / ``DimensionShape``, checked against
    the trap index and named by the compiler), so there is no seam to route
    around. A member with a version seam will appear — a parameter will
    appear too, but not before.

    An empty id list is NOT a reason to assemble a body that would walk the
    whole document: the stage is page-based, and "no ids" means "nothing to
    read".

    ``link_title`` — read not the HOST, but its link, by that link's own ``Document.Title``.
    """
    quoted = ", ".join(_csharp_string(str(item)) for item in element_ids)
    body = _DIMENSION_EXTRACT_BODY_CS
    body = body.replace("__DM_CALL_BUDGET_MS__", str(int(call_budget_ms)))
    body = body.replace("__DIMENSION_IDS__", quoted)
    body = body.replace("__DM_MIN_REFS__", str(int(DIMENSION_MIN_REFS)))
    body = body.replace(
        "__ELEMENT_ID_OUT_OF_RANGE__", ELEMENT_ID_OUT_OF_RANGE_REASON)
    body = body.replace(
        "__DM_SCHEMA__", _csharp_string(DIMENSION_EXTRACT_SCHEMA_VERSION))
    return (source_binding_cs(link_title) + "\n"
            + ELEMENT_ID_HELPER_CS + "\n"
            + DIMENSION_EXTRACT_HELPER_CS + body)


__all__ = [
    "DIMENSION_CATEGORIES",
    "DIMENSION_EXTRACT_SCHEMA_VERSION",
    "DIMENSION_INDEX_SCHEMA_VERSION",
    "DIMENSION_MIN_REFS",
    "DIMENSION_SHAPE_LINEAR",
    "DimensionExtraction",
    "DimensionFailure",
    "DimensionPayloadError",
    "DimensionRecord",
    "build_dimension_extract_cs",
    "extract_dimensions",
    "merge_dimensions",
    "parse_dimension_index",
]
