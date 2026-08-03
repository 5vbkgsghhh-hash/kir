"""Location-curve EXTRACT boundary (Wave curve_index).

The frozen L0 schema records a wall or beam as a flat ``p0``/``p1`` segment.
That is correct for a straight ``Line`` but silently *flattens* a curved
location: an arc storefront, a swept beam, or a rounded facade collapses to
the chord between its endpoints.  The operator caught exactly this on LOT31's
curtained tower and rounded facade.  This module owns the additive side index
that records the *real* ``LocationCurve`` — ``Line`` | ``Arc`` |
``HermiteSpline`` | ``NurbSpline`` — for every requested element, keyed by
source ``element_id``, so a later lift can rebuild the true centreline rather
than the flattened chord.

Design mirrors the frozen extractor dialect used by
:mod:`curtain_extract`/:mod:`geom_extract`/:mod:`sketch_extract`:

* a deterministic, read-only Revit ``Execute`` body builder
  (:func:`build_curve_extract_cs`) that opens no ``Transaction`` and never
  calls ``get_Geometry``/``Tessellate``.  It reads ``element.Location`` as a
  ``LocationCurve``; a straight ``Line`` crosses the wire as two world
  millimetre endpoints, an ``Arc`` as its centre/radius/axes/end-parameters
  plus plane normal (matching the field set :mod:`geom_extract` emits from an
  edge ``Arc``), and any spline is honestly refused with a
  ``spline_unsupported`` marker that still carries the two world-millimetre
  endpoints — the spline is **never** tessellated, and the chord is **never**
  passed off as a straight ``Line``.  An element whose ``Location`` is not a
  ``LocationCurve`` (a ``LocationPoint`` or ``null``) is the typed
  ``no_location_curve`` marker;
* a strict, versioned Python parser (:func:`extract_curves`) that validates
  the wire payload field-for-field, converts nothing implicitly, refuses
  duplicates and unexpected fields, and builds a :class:`CurveExtraction` with
  a ``curve_index`` keyed by element ``element_id`` plus a ``failures`` list.

The ``arc`` record reuses :class:`kukai.ir.decompile.recompile.ArcCurve` for
its geometric validation (unit-length orthogonal axes, positive radius, an
angular span in ``(0, 2*pi]``): the parser converts the wire fields into that
frozen data-class so the location-curve index and the Tier-G recompiler share
one arc contract and cannot drift.  The contract is universal across any Revit
model; the LOT31 census only motivates it, it does not bound it.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from kukai.ir.decompile.recompile import ArcCurve, GeometrySchemaError
from kukai.ir.decompile.side_contract import source_binding_cs


CURVE_EXTRACT_SCHEMA_VERSION = "kir-decompile-curve-extract/1"
CURVE_INDEX_SCHEMA_VERSION = "kir-decompile-curve-index/1"

_ORTHO_TOL = 1.0e-6


class CurveExtractionError(ValueError):
    """Base class for a fail-closed location-curve extraction refusal."""


class CurvePayloadError(CurveExtractionError):
    """A bridge or persisted side-index payload violates the protocol."""


class CurveKind(str, Enum):
    """The representable state of an element's ``LocationCurve``.

    ``line`` carries two world-millimetre endpoints.  ``arc`` carries the exact
    :class:`ArcCurve`-compatible fields plus the plane normal.
    ``spline_unsupported`` is the honest refusal marker for a ``HermiteSpline``
    or ``NurbSpline`` location curve: the two world-millimetre endpoints are
    still recorded, but the interior is deferred to a later curved-spine wave
    rather than tessellated or passed off as a straight line.
    ``no_location_curve`` marks an element whose ``Location`` is a
    ``LocationPoint`` or ``null`` — it has no centreline to record at all.
    """

    LINE = "line"
    ARC = "arc"
    SPLINE_UNSUPPORTED = "spline_unsupported"
    NO_LOCATION_CURVE = "no_location_curve"


class CurveFailureReason(str, Enum):
    """Typed fail-safe reasons emitted in addition to legacy error strings."""

    TIME_BUDGET_EXCEEDED = "time_budget_exceeded"
    CALL_BUDGET_EXHAUSTED = "call_budget_exhausted"


Vec3 = tuple[float, float, float]


# ── Strict payload primitives (shape identical to the sibling extractors) ────


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CurvePayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise CurvePayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _exact_fields(
    value: Any,
    fields: set[str],
    field_name: str,
) -> dict[str, Any]:
    row = _mapping(value, field_name)
    missing = sorted(fields - set(row))
    extra = sorted(set(row) - fields)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise CurvePayloadError(f"{field_name} fields: {'; '.join(details)}")
    return row


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise CurvePayloadError(f"{field_name} must be an array")
    return value


def _string(value: Any, field_name: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value):
        qualifier = "a string" if empty else "a non-empty string"
        raise CurvePayloadError(f"{field_name} must be {qualifier}")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CurvePayloadError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise CurvePayloadError(f"{field_name} must be a finite number")
    return 0.0 if result == 0.0 else result


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CurvePayloadError(
            f"{field_name} must be a non-negative integer")
    return value


def _vec3(value: Any, field_name: str) -> Vec3:
    if (not isinstance(value, Sequence) or isinstance(value, (str, bytes))
            or len(value) != 3):
        raise CurvePayloadError(
            f"{field_name} must contain exactly three numbers")
    return (
        _number(value[0], f"{field_name}[0]"),
        _number(value[1], f"{field_name}[1]"),
        _number(value[2], f"{field_name}[2]"),
    )


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


# ── Validated side-index records ─────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class CurveRecord:
    """One element's frozen-L0 location-curve row, keyed by ``element_id``.

    ``curve_kind`` selects which geometry fields are present:

    * ``line`` — ``p0_mm``/``p1_mm`` world-millimetre endpoints only;
    * ``arc`` — ``p0_mm``/``p1_mm`` endpoints plus the exact
      :class:`ArcCurve` (centre/radius/axes/angles) and the plane ``normal``
      (a right-handed unit vector consistent with ``x_axis``×``y_axis``);
    * ``spline_unsupported`` — the two world-millimetre endpoints only, with
      the interior honestly deferred;
    * ``no_location_curve`` — no geometry at all.

    ``category`` is the element's ``OST_*`` BuiltInCategory name when the
    bridge could read it, retained so a lift can route a wall spine and a beam
    spine differently; it is ``None`` when unavailable.
    """

    element_id: str
    curve_kind: CurveKind
    category: str | None = None
    p0_mm: Vec3 | None = None
    p1_mm: Vec3 | None = None
    arc: ArcCurve | None = None
    normal: Vec3 | None = None

    def __post_init__(self) -> None:
        _string(self.element_id, "CurveRecord.element_id")
        if not isinstance(self.curve_kind, CurveKind):
            raise CurvePayloadError(
                "CurveRecord.curve_kind must be a CurveKind")
        if self.category is not None:
            _string(self.category, "CurveRecord.category")
        if self.curve_kind is CurveKind.NO_LOCATION_CURVE:
            if (self.p0_mm is not None or self.p1_mm is not None
                    or self.arc is not None or self.normal is not None):
                raise CurvePayloadError(
                    "no_location_curve record cannot carry geometry")
            return
        # line / arc / spline_unsupported all carry the two endpoints.
        if self.p0_mm is None or self.p1_mm is None:
            raise CurvePayloadError(
                f"{self.curve_kind.value} record requires p0_mm and p1_mm")
        _vec3(self.p0_mm, "CurveRecord.p0_mm")
        _vec3(self.p1_mm, "CurveRecord.p1_mm")
        if self.curve_kind is CurveKind.ARC:
            if self.arc is None or self.normal is None:
                raise CurvePayloadError(
                    "arc record requires an arc and a normal")
            if not isinstance(self.arc, ArcCurve):
                raise CurvePayloadError(
                    "CurveRecord.arc must be an ArcCurve")
            normal = _vec3(self.normal, "CurveRecord.normal")
            if abs(normal[0] * normal[0] + normal[1] * normal[1]
                   + normal[2] * normal[2] - 1.0) > _ORTHO_TOL:
                raise CurvePayloadError(
                    "CurveRecord.normal must be unit length")
            expected = _cross(self.arc.x_axis, self.arc.y_axis)
            if any(abs(expected[axis] - normal[axis]) > _ORTHO_TOL
                   for axis in range(3)):
                raise CurvePayloadError(
                    "CurveRecord.normal must equal x_axis cross y_axis")
        elif self.arc is not None or self.normal is not None:
            raise CurvePayloadError(
                f"{self.curve_kind.value} record cannot carry arc geometry")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "curve_kind": self.curve_kind.value,
            "category": self.category,
        }
        if self.curve_kind is CurveKind.NO_LOCATION_CURVE:
            return result
        result["p0_mm"] = list(self.p0_mm)  # type: ignore[arg-type]
        result["p1_mm"] = list(self.p1_mm)  # type: ignore[arg-type]
        if self.curve_kind is CurveKind.ARC:
            arc = self.arc.to_dict()  # type: ignore[union-attr]
            result["arc"] = {
                "center_mm": arc["center_mm"],
                "radius_mm": arc["radius_mm"],
                "x_axis": arc["x_axis"],
                "y_axis": arc["y_axis"],
                "start_angle_rad": arc["start_angle_rad"],
                "end_angle_rad": arc["end_angle_rad"],
            }
            result["normal"] = list(self.normal)  # type: ignore[arg-type]
        return result

    @classmethod
    def from_dict(
        cls,
        element_id: str,
        value: Any,
        field_name: str = "curve index record",
    ) -> "CurveRecord":
        row = _mapping(value, field_name)
        try:
            curve_kind = CurveKind(row.get("curve_kind"))
        except (TypeError, ValueError) as exc:
            raise CurvePayloadError(
                f"{field_name}.curve_kind is unsupported: "
                f"{row.get('curve_kind')!r}") from exc
        if curve_kind is CurveKind.NO_LOCATION_CURVE:
            row = _exact_fields(row, {"curve_kind", "category"}, field_name)
            return cls(
                element_id=element_id,
                curve_kind=curve_kind,
                category=_optional_category(
                    row["category"], f"{field_name}.category"),
            )
        if curve_kind is CurveKind.ARC:
            row = _exact_fields(row, {
                "curve_kind", "category", "p0_mm", "p1_mm", "arc", "normal",
            }, field_name)
            arc, normal = _parse_arc(
                row["arc"], row["normal"], field_name)
            return cls(
                element_id=element_id,
                curve_kind=curve_kind,
                category=_optional_category(
                    row["category"], f"{field_name}.category"),
                p0_mm=_vec3(row["p0_mm"], f"{field_name}.p0_mm"),
                p1_mm=_vec3(row["p1_mm"], f"{field_name}.p1_mm"),
                arc=arc,
                normal=normal,
            )
        # line / spline_unsupported: endpoints only.
        row = _exact_fields(row, {
            "curve_kind", "category", "p0_mm", "p1_mm",
        }, field_name)
        return cls(
            element_id=element_id,
            curve_kind=curve_kind,
            category=_optional_category(
                row["category"], f"{field_name}.category"),
            p0_mm=_vec3(row["p0_mm"], f"{field_name}.p0_mm"),
            p1_mm=_vec3(row["p1_mm"], f"{field_name}.p1_mm"),
        )


@dataclass(frozen=True, slots=True)
class CurveFailure:
    """One element that could not be read as a clean location curve."""

    element_id: str
    reason: str
    typed_reason: CurveFailureReason | None = None
    elapsed_ms: int | None = None

    def __post_init__(self) -> None:
        _string(self.element_id, "CurveFailure.element_id")
        _string(self.reason, "CurveFailure.reason")
        if self.typed_reason is None:
            if self.elapsed_ms is not None:
                raise CurvePayloadError(
                    "CurveFailure.elapsed_ms requires a typed reason")
        else:
            if not isinstance(self.typed_reason, CurveFailureReason):
                raise CurvePayloadError(
                    "CurveFailure.typed_reason must be a CurveFailureReason")
            _nonnegative_int(self.elapsed_ms, "CurveFailure.elapsed_ms")
            if self.typed_reason.value != self.reason:
                raise CurvePayloadError(
                    "CurveFailure.reason must equal the typed reason value")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "element_id": self.element_id,
            "reason": self.reason,
        }
        if self.typed_reason is not None:
            result["typed_reason"] = self.typed_reason.value
            result["elapsed_ms"] = self.elapsed_ms
        return result

    @classmethod
    def from_dict(cls, value: Any, field_name: str) -> "CurveFailure":
        row = _mapping(value, field_name)
        if "typed_reason" in row or "elapsed_ms" in row:
            row = _exact_fields(row, {
                "element_id", "reason", "typed_reason", "elapsed_ms",
            }, field_name)
            try:
                typed = CurveFailureReason(row["typed_reason"])
            except (TypeError, ValueError) as exc:
                raise CurvePayloadError(
                    f"{field_name}.typed_reason is unsupported") from exc
            return cls(
                element_id=_string(
                    row["element_id"], f"{field_name}.element_id"),
                reason=_string(row["reason"], f"{field_name}.reason"),
                typed_reason=typed,
                elapsed_ms=_nonnegative_int(
                    row["elapsed_ms"], f"{field_name}.elapsed_ms"),
            )
        row = _exact_fields(row, {"element_id", "reason"}, field_name)
        return cls(
            element_id=_string(row["element_id"], f"{field_name}.element_id"),
            reason=_string(row["reason"], f"{field_name}.reason"),
        )


@dataclass(frozen=True, slots=True)
class CurveExtraction:
    """Validated location-curve side index, keyed by ``element_id``."""

    records: tuple[CurveRecord, ...]
    failures: tuple[CurveFailure, ...] = ()

    def __post_init__(self) -> None:
        element_ids = [record.element_id for record in self.records]
        if len(element_ids) != len(set(element_ids)):
            raise CurvePayloadError(
                "curve index contains duplicate element_id")

    def __iter__(self) -> Iterator[CurveRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def curve_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.records,
                key=lambda record: _element_id_key(record.element_id))
        }

    def entry_for(self, element_id: str) -> CurveRecord:
        for record in self.records:
            if record.element_id == element_id:
                return record
        raise CurvePayloadError(
            f"element is absent from curve index: {element_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CURVE_INDEX_SCHEMA_VERSION,
            "curve_index": self.curve_index,
            "failures": [
                failure.to_dict()
                for failure in sorted(
                    self.failures,
                    key=lambda item: (
                        _element_id_key(item.element_id), item.reason))
            ],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_dict(cls, value: Any) -> "CurveExtraction":
        root = _exact_fields(value, {
            "schema_version", "curve_index", "failures",
        }, "persisted curve extraction")
        if root["schema_version"] != CURVE_INDEX_SCHEMA_VERSION:
            raise CurvePayloadError("curve index schema_version mismatch")
        raw_index = _mapping(
            root["curve_index"], "persisted curve extraction.curve_index")
        records = tuple(
            CurveRecord.from_dict(
                element_id,
                row,
                f"persisted curve extraction.curve_index[{element_id!r}]",
            )
            for element_id, row in sorted(
                raw_index.items(), key=lambda item: _element_id_key(item[0]))
        )
        raw_failures = _array(
            root["failures"], "persisted curve extraction.failures")
        failures = tuple(
            CurveFailure.from_dict(
                raw, f"persisted curve extraction.failures[{index}]")
            for index, raw in enumerate(raw_failures)
        )
        return cls(records=records, failures=failures)

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "CurveExtraction":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise CurvePayloadError(
                f"curve index is not valid JSON: {exc}") from exc
        return cls.from_dict(decoded)


def _optional_category(value: Any, field_name: str) -> str | None:
    return None if value is None else _string(value, field_name)


def _parse_arc(
    raw_arc: Any,
    raw_normal: Any,
    field_name: str,
) -> tuple[ArcCurve, Vec3]:
    """Convert the wire arc + normal into a validated :class:`ArcCurve`.

    The arc's geometric invariants (unit-length orthogonal axes, positive
    radius, angular span in ``(0, 2*pi]``) are enforced by ``ArcCurve``
    itself; a violation surfaces as a :class:`CurvePayloadError`.
    """

    arc_row = _exact_fields(raw_arc, {
        "center_mm", "radius_mm", "x_axis", "y_axis",
        "start_angle_rad", "end_angle_rad",
    }, f"{field_name}.arc")
    try:
        arc = ArcCurve(
            center_mm=_vec3(
                arc_row["center_mm"], f"{field_name}.arc.center_mm"),
            radius_mm=_number(
                arc_row["radius_mm"], f"{field_name}.arc.radius_mm"),
            x_axis=_vec3(arc_row["x_axis"], f"{field_name}.arc.x_axis"),
            y_axis=_vec3(arc_row["y_axis"], f"{field_name}.arc.y_axis"),
            start_angle_rad=_number(
                arc_row["start_angle_rad"],
                f"{field_name}.arc.start_angle_rad"),
            end_angle_rad=_number(
                arc_row["end_angle_rad"], f"{field_name}.arc.end_angle_rad"),
        )
    except GeometrySchemaError as exc:
        raise CurvePayloadError(f"{field_name}.arc is invalid: {exc}") from exc
    normal = _vec3(raw_normal, f"{field_name}.normal")
    return arc, normal


def _unwrap_bridge_payload(value: Any) -> Any:
    current = value
    for _ in range(2):
        if not isinstance(current, Mapping) or "ok" not in current:
            break
        if current.get("ok") is not True:
            detail = current.get("error") or current.get("message") \
                or "bridge refused curve extraction"
            raise CurvePayloadError(str(detail)[:300])
        if "result" not in current:
            break
        current = current["result"]
    return current


_ELEMENT_FIELDS = {
    "element_id", "status", "reason", "typed_reason", "elapsed_ms",
    "category", "curve_kind", "p0_mm", "p1_mm", "arc", "normal",
}
_GEOMETRY_FIELDS = ("curve_kind", "p0_mm", "p1_mm", "arc", "normal")


def _parse_typed_reason(
    row: Mapping[str, Any],
    field_name: str,
) -> tuple[CurveFailureReason | None, int | None]:
    raw_typed = row["typed_reason"]
    raw_elapsed = row["elapsed_ms"]
    if raw_typed is None:
        if raw_elapsed is not None:
            raise CurvePayloadError(
                f"{field_name}.elapsed_ms requires a typed_reason")
        return None, None
    try:
        typed = CurveFailureReason(raw_typed)
    except (TypeError, ValueError) as exc:
        raise CurvePayloadError(
            f"{field_name}.typed_reason is unsupported: {raw_typed!r}") \
            from exc
    elapsed = _nonnegative_int(raw_elapsed, f"{field_name}.elapsed_ms")
    return typed, elapsed


def _forbid_geometry(
    row: Mapping[str, Any],
    field_name: str,
    status: str,
) -> None:
    for key in _GEOMETRY_FIELDS:
        if row[key] is not None:
            raise CurvePayloadError(
                f"{field_name}: {status} element cannot carry {key}")


def _build_curve_record(
    element_id: str,
    row: Mapping[str, Any],
    field_name: str,
) -> CurveRecord:
    """Build one ``ok`` element's record from the wire fields."""

    try:
        curve_kind = CurveKind(row["curve_kind"])
    except (TypeError, ValueError) as exc:
        raise CurvePayloadError(
            f"{field_name}.curve_kind is unsupported: "
            f"{row['curve_kind']!r}") from exc
    category = _optional_category(row["category"], f"{field_name}.category")

    if curve_kind is CurveKind.NO_LOCATION_CURVE:
        for key in ("p0_mm", "p1_mm", "arc", "normal"):
            if row[key] is not None:
                raise CurvePayloadError(
                    f"{field_name}: no_location_curve cannot carry {key}")
        return CurveRecord(
            element_id=element_id,
            curve_kind=curve_kind,
            category=category)

    if row["p0_mm"] is None or row["p1_mm"] is None:
        raise CurvePayloadError(
            f"{field_name}: {curve_kind.value} requires p0_mm and p1_mm")
    p0 = _vec3(row["p0_mm"], f"{field_name}.p0_mm")
    p1 = _vec3(row["p1_mm"], f"{field_name}.p1_mm")

    if curve_kind is CurveKind.ARC:
        if row["arc"] is None or row["normal"] is None:
            raise CurvePayloadError(
                f"{field_name}: arc requires arc and normal")
        arc, normal = _parse_arc(row["arc"], row["normal"], field_name)
        return CurveRecord(
            element_id=element_id,
            curve_kind=curve_kind,
            category=category,
            p0_mm=p0,
            p1_mm=p1,
            arc=arc,
            normal=normal)

    # line / spline_unsupported: endpoints only, arc geometry forbidden.
    for key in ("arc", "normal"):
        if row[key] is not None:
            raise CurvePayloadError(
                f"{field_name}: {curve_kind.value} cannot carry {key}")
    return CurveRecord(
        element_id=element_id,
        curve_kind=curve_kind,
        category=category,
        p0_mm=p0,
        p1_mm=p1)


def extract_curves(payload: Any) -> CurveExtraction:
    """Validate one emitted payload and build the frozen-L0 curve index.

    Wire-shape corruption is a typed exception.  A well-formed per-element
    failure — an element that could not be resolved, whose location read
    threw, or whose read overran a time budget — becomes an honest
    ``failures`` entry rather than being silently dropped or misreported as a
    straight line.  An element with no ``LocationCurve`` is recorded with the
    typed ``no_location_curve`` marker in the index (it is a fact about the
    element, not a failure).
    """

    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        {"schema_version", "elements"},
        "curve extraction",
    )
    if root["schema_version"] != CURVE_EXTRACT_SCHEMA_VERSION:
        raise CurvePayloadError("curve extraction schema_version mismatch")
    elements = _array(root["elements"], "curve extraction.elements")
    records: list[CurveRecord] = []
    failures: list[CurveFailure] = []
    seen_ids: set[str] = set()

    for element_index, raw_element in enumerate(elements):
        field_name = f"curve extraction.elements[{element_index}]"
        row = _exact_fields(raw_element, _ELEMENT_FIELDS, field_name)
        element_id = _string(row["element_id"], f"{field_name}.element_id")
        if element_id in seen_ids:
            raise CurvePayloadError(
                f"duplicate curve element_id: {element_id!r}")
        seen_ids.add(element_id)
        status = _string(row["status"], f"{field_name}.status")

        typed_reason, elapsed_ms = _parse_typed_reason(row, field_name)

        if status == "failed":
            _forbid_geometry(row, field_name, status)
            reason = _string(row["reason"], f"{field_name}.reason")
            if typed_reason is not None and typed_reason.value != reason:
                raise CurvePayloadError(
                    f"{field_name}: typed reason must match the failed reason")
            failures.append(CurveFailure(
                element_id, reason,
                typed_reason=typed_reason,
                elapsed_ms=elapsed_ms))
            continue

        if status != "ok":
            raise CurvePayloadError(
                f"{field_name}.status is unsupported: {status!r}")
        if row["reason"] is not None:
            raise CurvePayloadError(
                f"{field_name}: ok status cannot carry a reason")
        if typed_reason is not None:
            raise CurvePayloadError(
                f"{field_name}: ok status cannot carry a typed reason")
        if row["curve_kind"] is None:
            raise CurvePayloadError(
                f"{field_name}: ok status requires a curve_kind")
        records.append(_build_curve_record(element_id, row, field_name))

    return CurveExtraction(
        records=tuple(sorted(
            records, key=lambda record: _element_id_key(record.element_id))),
        failures=tuple(sorted(
            failures,
            key=lambda failure: (
                _element_id_key(failure.element_id), failure.reason))),
    )


# ── Deterministic Revit C# emission ─────────────────────────────────────────
#
# This is an Execute-method body for the same ``wrap_user_code`` path used in
# serving.  It opens no Transaction and never calls get_Geometry/Tessellate.
# LocationCurve endpoints and arc geometry cross the wire in world
# millimetres / native units; host-local re-projection is a later offline
# parser concern, not something the bridge attempts.


CURVE_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE Wave curve_index — read-only LocationCurve helpers.
// Endpoints/centre/radius cross the wire in world millimetres. No Transaction.
Func<double, double> __cvMM = (__feet) =>
    UnitUtils.ConvertFromInternalUnits(__feet, UnitTypeId.Millimeters);
Func<XYZ, bool> __cvFiniteXYZ = (__point) =>
    __point != null
    && !Double.IsNaN(__point.X) && !Double.IsInfinity(__point.X)
    && !Double.IsNaN(__point.Y) && !Double.IsInfinity(__point.Y)
    && !Double.IsNaN(__point.Z) && !Double.IsInfinity(__point.Z);
Func<double, bool> __cvFinite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
Func<XYZ, object> __cvPoint = (__point) => (object)new double[] {
    __cvMM(__point.X), __cvMM(__point.Y), __cvMM(__point.Z)
};
Func<XYZ, object> __cvVector = (__vector) => (object)new double[] {
    __vector.X, __vector.Y, __vector.Z
};
Func<Exception, string> __cvError = (__error) =>
{
    string __message = __error.GetType().Name + ": " + (__error.Message ?? "");
    return __message.Length <= 300 ? __message : __message.Substring(0, 300);
};
// Classify one LocationCurve into ("line"|"arc"|"spline_unsupported") with the
// two world-millimetre endpoints always present; an arc additionally carries
// its exact centre/radius/axes/angles and plane normal. A spline is refused
// honestly with its endpoints (never tessellated, never chorded to a line).
Func<Curve, Dictionary<string, object>> __cvCurve = (__curve) =>
{
    var __row = new Dictionary<string, object>();
    __row["curve_kind"] = null;
    __row["p0_mm"] = null;
    __row["p1_mm"] = null;
    __row["arc"] = null;
    __row["normal"] = null;
    if (__curve == null) return __row;
    XYZ __p0 = __curve.GetEndPoint(0);
    XYZ __p1 = __curve.GetEndPoint(1);
    if (!__cvFiniteXYZ(__p0) || !__cvFiniteXYZ(__p1)) return __row;
    __row["p0_mm"] = __cvPoint(__p0);
    __row["p1_mm"] = __cvPoint(__p1);
    Line __line = __curve as Line;
    if (__line != null)
    {
        __row["curve_kind"] = "line";
        return __row;
    }
    Arc __arc = __curve as Arc;
    if (__arc != null)
    {
        double __start = __arc.GetEndParameter(0);
        double __end = __arc.GetEndParameter(1);
        double __radius = __arc.Radius;
        XYZ __xDir = __arc.XDirection;
        XYZ __yDir = __arc.YDirection;
        XYZ __normal = __arc.Normal;
        double __span = __end - __start;
        if (__cvFinite(__start) && __cvFinite(__end)
            && __cvFinite(__radius) && __radius > 0.0
            && __span > 0.0 && __span <= 2.0 * Math.PI + 1.0e-8
            && __cvFiniteXYZ(__xDir) && __cvFiniteXYZ(__yDir)
            && __cvFiniteXYZ(__arc.Center) && __cvFiniteXYZ(__normal))
        {
            var __arcRow = new Dictionary<string, object>();
            __arcRow["center_mm"] = __cvPoint(__arc.Center);
            __arcRow["radius_mm"] = __cvMM(__radius);
            __arcRow["x_axis"] = __cvVector(__xDir);
            __arcRow["y_axis"] = __cvVector(__yDir);
            __arcRow["start_angle_rad"] = __start;
            __arcRow["end_angle_rad"] = __end;
            __row["curve_kind"] = "arc";
            __row["arc"] = __arcRow;
            __row["normal"] = __cvVector(__normal);
        }
        else
        {
            // A degenerate/unreadable arc is deferred honestly, not chorded.
            __row["curve_kind"] = "spline_unsupported";
        }
        return __row;
    }
    // HermiteSpline / NurbSpline / any other curve: refuse with endpoints.
    __row["curve_kind"] = "spline_unsupported";
    return __row;
};
"""


_CURVE_EXTRACT_BODY_CS = r"""
var __cvRequestedIds = new string[] { __CV_ELEMENT_IDS__ };
long __cvElementBudgetMs = __CV_ELEMENT_BUDGET_MS__L;
long __cvCallBudgetMs = __CV_CALL_BUDGET_MS__L;
var __cvCallWatch = System.Diagnostics.Stopwatch.StartNew();

// One bounded collector pass resolves the requested elements by their
// version-safe ElementId.ToString() representation.
var __cvRequestedSet = new HashSet<string>(__cvRequestedIds);
var __cvFound = new Dictionary<string, Element>();
foreach (Element __element in new FilteredElementCollector(__src)
         .WhereElementIsNotElementType())
{
    if (__cvCallWatch.ElapsedMilliseconds >= __cvCallBudgetMs) break;
    string __id = __element.Id.ToString();
    if (__cvRequestedSet.Contains(__id) && !__cvFound.ContainsKey(__id))
    {
        __cvFound[__id] = __element;
        if (__cvFound.Count == __cvRequestedSet.Count) break;
    }
}

var __cvElementRows = new List<object>();
foreach (string __requestedId in __cvRequestedIds)
{
    var __row = new Dictionary<string, object>();
    __row["element_id"] = __requestedId;
    __row["status"] = "failed";
    __row["reason"] = "element not resolved";
    __row["typed_reason"] = null;
    __row["elapsed_ms"] = null;
    __row["category"] = null;
    __row["curve_kind"] = null;
    __row["p0_mm"] = null;
    __row["p1_mm"] = null;
    __row["arc"] = null;
    __row["normal"] = null;

    string __cvBudgetReason = null;
    long __cvBudgetElapsed = 0L;

    if (__cvCallWatch.ElapsedMilliseconds >= __cvCallBudgetMs)
    {
        __cvBudgetReason = "call_budget_exhausted";
        __cvBudgetElapsed = __cvCallWatch.ElapsedMilliseconds;
    }
    else
    {
        var __cvElementWatch = System.Diagnostics.Stopwatch.StartNew();
        Element __element = null;
        if (__cvFound.TryGetValue(__requestedId, out __element)
            && __element != null)
        {
            try
            {
                Category __category = __element.Category;
                if (__category != null)
                {
                    // BuiltInCategory round-trips as an OST_* name only when
                    // the id maps to a built-in; otherwise category stays null.
                    // ElementId.ToString() + Int64.TryParse is the version-safe
                    // value read (ElementId.IntegerValue is gone in 2026).
                    ElementId __catId = __category.Id;
                    long __catValue = 0L;
                    if (__catId != null
                        && Int64.TryParse(__catId.ToString(), out __catValue)
                        && __catValue >= (long)Int32.MinValue
                        && __catValue <= (long)Int32.MaxValue)
                    {
                        // Enum.IsDefined(type, boxed int) throws when the
                        // enum's underlying type differs across Revit
                        // versions; the ToString round-trip is version-safe:
                        // a defined value prints its OST_* name, an undefined
                        // one prints the bare number.
                        string __catName =
                            ((BuiltInCategory)(int)__catValue).ToString();
                        if (__catName.StartsWith("OST_",
                                StringComparison.Ordinal))
                            __row["category"] = __catName;
                    }
                }
            }
            catch { }

            try
            {
                Location __location = __element.Location;
                LocationCurve __locationCurve = __location as LocationCurve;
                if (__locationCurve == null)
                {
                    // A LocationPoint or a null Location has no centreline.
                    __row["status"] = "ok";
                    __row["reason"] = null;
                    __row["curve_kind"] = "no_location_curve";
                }
                else
                {
                    Curve __curve = __locationCurve.Curve;
                    var __curveRow = __cvCurve(__curve);
                    if (__curveRow["curve_kind"] == null)
                    {
                        __row["reason"] =
                            "location curve endpoints are not finite";
                    }
                    else
                    {
                        __row["status"] = "ok";
                        __row["reason"] = null;
                        __row["curve_kind"] = __curveRow["curve_kind"];
                        __row["p0_mm"] = __curveRow["p0_mm"];
                        __row["p1_mm"] = __curveRow["p1_mm"];
                        __row["arc"] = __curveRow["arc"];
                        __row["normal"] = __curveRow["normal"];
                    }
                }
            }
            catch (Exception __locationException)
            {
                __row["status"] = "failed";
                __row["reason"] =
                    "location read failed: " + __cvError(__locationException);
            }
        }

        if (__cvElementWatch.ElapsedMilliseconds >= __cvElementBudgetMs)
        {
            __cvBudgetReason = "time_budget_exceeded";
            __cvBudgetElapsed = __cvElementWatch.ElapsedMilliseconds;
        }
        else if (__cvCallWatch.ElapsedMilliseconds >= __cvCallBudgetMs)
        {
            __cvBudgetReason = "call_budget_exhausted";
            __cvBudgetElapsed = __cvCallWatch.ElapsedMilliseconds;
        }
    }

    if (__cvBudgetReason != null)
    {
        // Never mislabel a timed-out partial location read as usable geometry.
        __row["status"] = "failed";
        __row["reason"] = __cvBudgetReason;
        __row["typed_reason"] = __cvBudgetReason;
        __row["elapsed_ms"] = __cvBudgetElapsed;
        __row["curve_kind"] = null;
        __row["p0_mm"] = null;
        __row["p1_mm"] = null;
        __row["arc"] = null;
        __row["normal"] = null;
    }
    __cvElementRows.Add(__row);
}
return new Dictionary<string, object> {
    {"schema_version", "kir-decompile-curve-extract/1"},
    {"elements", __cvElementRows}
};
"""


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


def build_curve_extract_cs(
    element_ids: Sequence[str | int],
    *,
    element_budget_ms: int = 2_000,
    call_budget_ms: int = 20_000,
    link_title: str | None = None,
) -> str:
    """Emit one deterministic, read-only Revit Execute body.

    Numeric ids are resolved by their version-safe ``ElementId.ToString()``
    representation, avoiding the 2021/2024 ``int``/``long`` constructor fork.

    The two time budgets are cooperative fail-safes, not hard preemption
    (mirroring :func:`curtain_extract.build_curtain_extract_cs`).  Elapsed time
    is checked before the resolve loop, before each element's read, and after
    each element.  A single blocking API call may still exceed its budget, but
    any partial geometry is discarded, the overrun is reported as a typed
    ``time_budget_exceeded`` / ``call_budget_exhausted`` failure, and every
    remaining element id is still accounted for.

    ``link_title`` — читать не ХОЗЯИНА, а его СВЯЗЬ с таким ``Document.Title``.
    Источник один на ВСЁ тело: у документов разные пространства
    идентификаторов, поэтому id связи, спрошенный у хозяина, либо не находится
    (квитанция на ровном месте), либо находит ЧУЖОЙ элемент с тем же числом —
    и тогда стадия записывает чужую строку как свою, молча. Замер 30.07 на
    связанной электрике Snowdon дал оба исхода разом.
    """

    if isinstance(element_ids, (str, bytes)):
        raise ValueError("element_ids must be a sequence, not a string")
    normalized = []
    for index, value in enumerate(element_ids):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError(
                f"element_ids[{index}] must be a numeric string or integer")
        item = str(value)
        if re.fullmatch(r"-?[0-9]+", item) is None:
            raise ValueError(
                f"element_ids[{index}] must be a numeric Revit id")
        normalized.append(item)
    if not normalized:
        raise ValueError("at least one element id is required")
    if len(set(normalized)) != len(normalized):
        raise ValueError("element_ids must be unique")

    for field_name, value in (
        ("element_budget_ms", element_budget_ms),
        ("call_budget_ms", call_budget_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
        if value > 9_223_372_036_854_775_807:
            raise ValueError(f"{field_name} exceeds the C# Int64 range")

    body = _CURVE_EXTRACT_BODY_CS.replace(
        "__CV_ELEMENT_IDS__",
        ", ".join(_csharp_string(value) for value in normalized),
        1,
    )
    body = body.replace("__CV_ELEMENT_BUDGET_MS__", str(element_budget_ms))
    body = body.replace("__CV_CALL_BUDGET_MS__", str(call_budget_ms))
    if "__CV_" in body:
        raise CurveExtractionError(
            "internal curve emitter placeholder was not resolved")
    return (
        source_binding_cs(link_title)
        + "\n" + CURVE_EXTRACT_HELPER_CS.strip()
        + "\n" + body.strip())


# Descriptive aliases keep the public boundary discoverable.
parse_curve_index = extract_curves


__all__ = [
    "CURVE_EXTRACT_SCHEMA_VERSION",
    "CURVE_INDEX_SCHEMA_VERSION",
    "CURVE_EXTRACT_HELPER_CS",
    "CurveExtraction",
    "CurveExtractionError",
    "CurveFailure",
    "CurveFailureReason",
    "CurveKind",
    "CurvePayloadError",
    "CurveRecord",
    "build_curve_extract_cs",
    "extract_curves",
    "parse_curve_index",
]
