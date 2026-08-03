"""Wave A5 — re-extract a KNOWN id set into L0 elements (idempotence readback).

The idempotence loop (``kir_idempotence.py``) rebuilds a decompiled model at a
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
are re-sorted by numeric id; the builder is a pure function of the id list), I5
(nothing imports this on a hot path).  The C# body reuses the exact frozen
extract helpers so its version-safety is the SAME proof as the extractor's.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from kukai.ir.decompile.extract import (
    _COMMON_HELPERS_CS,
    _ELEMENT_HELPERS_CS,
    ExtractionProtocolError,
)
from kukai.ir.decompile.geometry_store import GEOMETRY_HELPER_CS, parse_geometry
from kukai.ir.decompile.schema import (
    L0Document, L0Element, L0SchemaError, RoomInfo,
)


class ReExtractError(RuntimeError):
    """A re-extraction body/response violated the frozen A5 readback contract."""


REEXTRACT_BATCH = 200


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
var __seen = new HashSet<long>();
var __candidates = new List<Element>();
foreach (var __e in new FilteredElementCollector(doc)
        .WhereElementIsNotElementType().Cast<Element>())
    __candidates.Add(__e);
foreach (var __g in new FilteredElementCollector(doc)
        .OfClass(typeof(Grid)).Cast<Element>())
    __candidates.Add(__g);
foreach (var __lv in new FilteredElementCollector(doc)
        .OfClass(typeof(Level)).Cast<Element>())
    __candidates.Add(__lv);
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
return new Dictionary<string, object> {
    {"elements", __rows}
};
""".strip()


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
    __roomRow["name"] = __room.Name ?? "";
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
    return "\n".join((_COMMON_HELPERS_CS, body))


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
    body = _ROW_BODY_CS.replace("__IDS__", literals, 1)
    return "\n".join((
        _COMMON_HELPERS_CS,
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
        _require_exact_ids(
            requested_ids,
            [element.element_id for element in elements],
            "re-extract",
        )
    return elements


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
    "ReExtractError",
    "REEXTRACT_BATCH",
    "build_reextract_cs",
    "parse_reextract_rows",
    "reextracted_document",
]
