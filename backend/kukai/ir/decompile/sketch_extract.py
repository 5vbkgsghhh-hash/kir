"""Fail-closed Sketch-profile extraction for floors, roofs, and stairs.

The frozen Wave-A L0 schema deliberately remains untouched.  This module owns
an additive side index keyed by source ``element_id`` and a deterministic,
read-only Revit C# Execute body which produces the facts used to build it.

Closed floor/roof profiles retain every loop and every segment's primitive
kind.  A circular arc is represented by its two neighbouring loop vertices
plus an exact point at normalized parameter 0.5; it is never tessellated.
Anything that cannot satisfy that narrow, exact contract is recorded as
``profile_available=False``.  In particular, no bounding-box data is accepted
by the profile protocol, so a bbox can never be promoted into a contour.

Stairs do not have one universally meaningful closed footprint.  Their parent
profile therefore remains unavailable while the stable 2021--2026
``StairsRun.GetStairsPath`` result is retained in a separate side index.  This
keeps the future stairs lifter supplied with real run geometry without
mislabeling an open centre path as a closed profile.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from kukai.ir.decompile.side_contract import (
    SideFailureReason, legacy_typed_reason, source_binding_cs,
)


SKETCH_EXTRACT_SCHEMA_VERSION = "kir-decompile-sketch-extract/1"
PROFILE_INDEX_SCHEMA_VERSION = "kir-decompile-profile-index/1"


class SketchExtractionError(ValueError):
    """Base class for a fail-closed Sketch extraction refusal."""


class SketchPayloadError(SketchExtractionError):
    """A bridge or persisted side-index payload violates the protocol."""


class CurveKind(str, Enum):
    """Exact curve primitives supported by the side-profile contract."""

    LINE = "line"
    ARC = "arc"


Vec2 = tuple[float, float]


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SketchPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise SketchPayloadError(f"{field_name} keys must be strings")
    return dict(value)


def _exact_fields(
    value: Any,
    fields: set[str],
    field_name: str,
    optional: set[str] | None = None,
) -> dict[str, Any]:
    """Exactly ``fields``, except ``optional`` ones which may be absent.

    Optionality exists for fields added after records were already persisted:
    a roof written before the pitch was read has no ``slopes`` key and must
    still load. Extra keys are still refused — the point of the check is that
    nothing unnoticed rides along.
    """
    row = _mapping(value, field_name)
    optional = optional or set()
    missing = sorted(fields - set(row) - optional)
    extra = sorted(set(row) - fields)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise SketchPayloadError(
            f"{field_name} fields: {'; '.join(details)}")
    return row


def _array(value: Any, field_name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SketchPayloadError(f"{field_name} must be an array")
    return value


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise SketchPayloadError(f"{field_name} must be a non-empty string")
    return value


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise SketchPayloadError(f"{field_name} must be a boolean")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SketchPayloadError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise SketchPayloadError(f"{field_name} must be a finite number")
    return 0.0 if result == 0.0 else result


def _vec2(value: Any, field_name: str) -> Vec2:
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or len(value) != 2):
        raise SketchPayloadError(
            f"{field_name} must contain exactly two numbers")
    return (
        _number(value[0], f"{field_name}[0]"),
        _number(value[1], f"{field_name}[1]"),
    )


def _optional_vec2(value: Any, field_name: str) -> Vec2 | None:
    return None if value is None else _vec2(value, field_name)


def _distance_squared(left: Vec2, right: Vec2) -> float:
    return ((left[0] - right[0]) ** 2
            + (left[1] - right[1]) ** 2)


@dataclass(frozen=True, slots=True)
class ProfileLoop:
    """One ordered, closed, typed CurveArray loop in millimetres.

    ``points_mm[i]`` is segment ``i``'s start and the next point (wrapping at
    the end) is its end.  ``arc_midpoints_mm[i]`` is required exactly when the
    corresponding segment is an arc.  Thus a four-line rectangle contains
    exactly four points, while an arc remains reconstructible from
    start/mid/end rather than being chord-approximated.
    """

    points_mm: tuple[Vec2, ...]
    curve_kinds: tuple[CurveKind, ...]
    arc_midpoints_mm: tuple[Vec2 | None, ...]

    def __post_init__(self) -> None:
        count = len(self.points_mm)
        if count < 2:
            raise SketchPayloadError(
                "profile loop must contain at least two segments")
        if len(self.curve_kinds) != count:
            raise SketchPayloadError(
                "profile loop points and curve_kinds must have equal length")
        if len(self.arc_midpoints_mm) != count:
            raise SketchPayloadError(
                "profile loop points and arc_midpoints must have equal length")
        for index, point in enumerate(self.points_mm):
            _vec2(point, f"profile loop.points_mm[{index}]")
            next_point = self.points_mm[(index + 1) % count]
            if _distance_squared(point, next_point) == 0.0:
                raise SketchPayloadError(
                    f"profile loop segment {index} has coincident endpoints")
        for index, (kind, midpoint) in enumerate(zip(
                self.curve_kinds, self.arc_midpoints_mm)):
            if not isinstance(kind, CurveKind):
                raise SketchPayloadError(
                    f"profile loop.curve_kinds[{index}] is invalid")
            if kind is CurveKind.ARC:
                if midpoint is None:
                    raise SketchPayloadError(
                        f"arc segment {index} requires an exact midpoint")
                _vec2(midpoint, f"profile loop.arc_midpoints_mm[{index}]")
            elif midpoint is not None:
                raise SketchPayloadError(
                    f"line segment {index} cannot carry an arc midpoint")

    @classmethod
    def from_wire(cls, value: Any, field_name: str = "profile loop") \
            -> "ProfileLoop":
        row = _exact_fields(value, {
            "points_mm", "curve_kinds", "arc_midpoints_mm",
        }, field_name)
        points_raw = _array(row["points_mm"], f"{field_name}.points_mm")
        kinds_raw = _array(row["curve_kinds"], f"{field_name}.curve_kinds")
        midpoints_raw = _array(
            row["arc_midpoints_mm"], f"{field_name}.arc_midpoints_mm")
        try:
            kinds = tuple(CurveKind(value) for value in kinds_raw)
        except (TypeError, ValueError) as exc:
            raise SketchPayloadError(
                f"{field_name}.curve_kinds supports only line/arc") from exc
        return cls(
            points_mm=tuple(
                _vec2(point, f"{field_name}.points_mm[{index}]")
                for index, point in enumerate(points_raw)),
            curve_kinds=kinds,
            arc_midpoints_mm=tuple(
                _optional_vec2(
                    point, f"{field_name}.arc_midpoints_mm[{index}]")
                for index, point in enumerate(midpoints_raw)),
        ).canonical_start()

    def canonical_start(self) -> "ProfileLoop":
        """Rotate, but never reverse, to a deterministic segment boundary."""

        choices = []
        count = len(self.points_mm)
        for index in range(count):
            rotated_points = self.points_mm[index:] + self.points_mm[:index]
            rotated_kinds = self.curve_kinds[index:] + self.curve_kinds[:index]
            rotated_mids = (
                self.arc_midpoints_mm[index:]
                + self.arc_midpoints_mm[:index])
            key = tuple(
                (point[0], point[1], kind.value,
                 () if midpoint is None else midpoint)
                for point, kind, midpoint in zip(
                    rotated_points, rotated_kinds, rotated_mids))
            choices.append((key, rotated_points, rotated_kinds, rotated_mids))
        _, points, kinds, midpoints = min(choices, key=lambda item: item[0])
        if (points == self.points_mm and kinds == self.curve_kinds
                and midpoints == self.arc_midpoints_mm):
            return self
        return ProfileLoop(points, kinds, midpoints)

    def to_wire(self) -> dict[str, Any]:
        return {
            "points_mm": [list(point) for point in self.points_mm],
            "curve_kinds": [kind.value for kind in self.curve_kinds],
            "arc_midpoints_mm": [
                list(point) if point is not None else None
                for point in self.arc_midpoints_mm
            ],
        }

    @property
    def signed_area_mm2(self) -> float:
        """Exact signed area, including circular-arc sector contribution."""

        area = 0.0
        count = len(self.points_mm)
        for index, kind in enumerate(self.curve_kinds):
            start = self.points_mm[index]
            end = self.points_mm[(index + 1) % count]
            if kind is CurveKind.LINE:
                area += 0.5 * (
                    start[0] * end[1] - end[0] * start[1])
                continue
            midpoint = self.arc_midpoints_mm[index]
            if midpoint is None:  # guarded by __post_init__; keeps mypy clear
                raise SketchPayloadError("arc midpoint is absent")
            center_x, center_y, radius, _, delta = _arc_geometry(
                start, midpoint, end)
            area += 0.5 * (
                radius * radius * delta
                + center_x * (end[1] - start[1])
                - center_y * (end[0] - start[0]))
        if not math.isfinite(area):
            raise SketchPayloadError("profile loop area is not finite")
        return area


@dataclass(frozen=True, slots=True)
class TypedPath:
    """One ordered open StairsRun path, preserving exact arc midpoints."""

    points_mm: tuple[Vec2, ...]
    curve_kinds: tuple[CurveKind, ...]
    arc_midpoints_mm: tuple[Vec2 | None, ...]

    def __post_init__(self) -> None:
        if len(self.points_mm) < 2:
            raise SketchPayloadError("stairs run path needs at least two points")
        if len(self.curve_kinds) + 1 != len(self.points_mm):
            raise SketchPayloadError(
                "stairs path needs one more point than curve kind")
        if len(self.arc_midpoints_mm) != len(self.curve_kinds):
            raise SketchPayloadError(
                "stairs path curve_kinds and arc_midpoints must align")
        for index, point in enumerate(self.points_mm):
            _vec2(point, f"stairs path.points_mm[{index}]")
            if index and _distance_squared(point, self.points_mm[index - 1]) == 0:
                raise SketchPayloadError(
                    f"stairs path segment {index - 1} has coincident endpoints")
        for index, (kind, midpoint) in enumerate(zip(
                self.curve_kinds, self.arc_midpoints_mm)):
            if not isinstance(kind, CurveKind):
                raise SketchPayloadError(
                    f"stairs path.curve_kinds[{index}] is invalid")
            if kind is CurveKind.ARC and midpoint is None:
                raise SketchPayloadError(
                    f"stairs path arc {index} requires an exact midpoint")
            if kind is CurveKind.LINE and midpoint is not None:
                raise SketchPayloadError(
                    f"stairs path line {index} cannot carry an arc midpoint")

    @classmethod
    def from_wire(cls, value: Any, field_name: str = "stairs path") \
            -> "TypedPath":
        row = _exact_fields(value, {
            "points_mm", "curve_kinds", "arc_midpoints_mm",
        }, field_name)
        points = _array(row["points_mm"], f"{field_name}.points_mm")
        kinds = _array(row["curve_kinds"], f"{field_name}.curve_kinds")
        midpoints = _array(
            row["arc_midpoints_mm"], f"{field_name}.arc_midpoints_mm")
        try:
            parsed_kinds = tuple(CurveKind(value) for value in kinds)
        except (TypeError, ValueError) as exc:
            raise SketchPayloadError(
                f"{field_name}.curve_kinds supports only line/arc") from exc
        return cls(
            tuple(_vec2(point, f"{field_name}.points_mm[{index}]")
                  for index, point in enumerate(points)),
            parsed_kinds,
            tuple(_optional_vec2(
                point, f"{field_name}.arc_midpoints_mm[{index}]")
                  for index, point in enumerate(midpoints)),
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "points_mm": [list(point) for point in self.points_mm],
            "curve_kinds": [kind.value for kind in self.curve_kinds],
            "arc_midpoints_mm": [
                list(point) if point is not None else None
                for point in self.arc_midpoints_mm
            ],
        }


def _align_slopes(loop: "ProfileLoop", entries: list) -> tuple[float | None, ...]:
    """Slopes re-indexed onto ``loop``'s own edges, matched by endpoints.

    Returns one entry per edge of the loop, ``None`` where that edge is level.
    An entry whose endpoints match no edge is dropped rather than guessed at:
    a pitch on the wrong edge rotates the roof, which is worse than a flat one.
    """
    points = loop.points_mm
    count = len(points)
    out: list[float | None] = [None] * count

    def _close(a, b) -> bool:
        return abs(a[0] - b[0]) <= 1.0 and abs(a[1] - b[1]) <= 1.0

    for entry in entries:
        p0, p1 = entry.get("p0_mm"), entry.get("p1_mm")
        deg = entry.get("deg")
        if not (isinstance(p0, (list, tuple)) and isinstance(p1, (list, tuple))
                and isinstance(deg, (int, float))):
            continue
        for index in range(count):
            a, b = points[index], points[(index + 1) % count]
            if ((_close(a, p0) and _close(b, p1))
                    or (_close(a, p1) and _close(b, p0))):
                out[index] = float(deg)
                break
    return tuple(out)


@dataclass(frozen=True, slots=True)
class ProfileIndexRecord:
    """One element's frozen-L0 side-profile row."""

    element_id: str
    profile_available: bool
    exterior_loop: ProfileLoop | None = None
    holes: tuple[ProfileLoop, ...] = ()
    #: Pitch in DEGREES per boundary curve of the exterior loop, ``None`` where
    #: that edge stays level.  Same length and order as the loop's curves, so
    #: it lines up with ``create_roof.slopes`` without re-deriving anything.
    slopes: tuple[float | None, ...] = ()

    def __post_init__(self) -> None:
        _string(self.element_id, "ProfileIndexRecord.element_id")
        if not isinstance(self.profile_available, bool):
            raise SketchPayloadError(
                "ProfileIndexRecord.profile_available must be a boolean")
        if self.profile_available:
            if self.exterior_loop is None:
                raise SketchPayloadError(
                    "available profile requires an exterior loop")
            if not isinstance(self.exterior_loop, ProfileLoop):
                raise SketchPayloadError(
                    "available profile exterior_loop is invalid")
            if not all(isinstance(loop, ProfileLoop) for loop in self.holes):
                raise SketchPayloadError("available profile holes are invalid")
        elif self.exterior_loop is not None or self.holes:
            raise SketchPayloadError(
                "unavailable profile cannot carry contours")

    @classmethod
    def unavailable(cls, element_id: str) -> "ProfileIndexRecord":
        return cls(element_id=element_id, profile_available=False)

    @property
    def curve_kinds(self) -> tuple[tuple[CurveKind, ...], ...]:
        if self.exterior_loop is None:
            return ()
        return (self.exterior_loop.curve_kinds,) + tuple(
            loop.curve_kinds for loop in self.holes)

    def to_dict(self) -> dict[str, Any]:
        if not self.profile_available:
            return {"profile_available": False}
        exterior = self.exterior_loop
        if exterior is None:  # guarded by __post_init__
            raise SketchPayloadError("available profile lost exterior loop")
        loops = (exterior,) + self.holes
        return {
            "profile_available": True,
            # Absent when no edge is pitched, so every roof persisted before
            # this field existed round-trips byte-identically.
            **({"slopes": [None if v is None else float(v)
                           for v in self.slopes]}
               if any(v is not None for v in self.slopes) else {}),
            "exterior_loop": [list(point) for point in exterior.points_mm],
            "holes": [
                [list(point) for point in loop.points_mm]
                for loop in self.holes
            ],
            "curve_kinds": [
                [kind.value for kind in loop.curve_kinds]
                for loop in loops
            ],
            "arc_midpoints": [
                [list(point) if point is not None else None
                 for point in loop.arc_midpoints_mm]
                for loop in loops
            ],
        }

    @classmethod
    def from_dict(
        cls,
        element_id: str,
        value: Any,
        field_name: str = "profile index record",
    ) -> "ProfileIndexRecord":
        row = _mapping(value, field_name)
        available = _boolean(
            row.get("profile_available"), f"{field_name}.profile_available")
        if not available:
            _exact_fields(row, {"profile_available"}, field_name)
            return cls.unavailable(element_id)
        row = _exact_fields(row, {
            "profile_available", "exterior_loop", "holes",
            "curve_kinds", "arc_midpoints", "slopes",
        }, field_name, optional={"slopes"})
        # Absent means "no edge is pitched", not "no edges": a record persisted
        # before the field existed must reload equal to the one that produced
        # it, and that one carries a None per edge.
        raw_slopes = row.get("slopes")
        pitches: tuple[float | None, ...] | None = None
        if isinstance(raw_slopes, list):
            pitches = tuple(None if v is None else float(v)
                            for v in raw_slopes
                            if v is None or isinstance(v, (int, float)))
        exterior_points = _array(
            row["exterior_loop"], f"{field_name}.exterior_loop")
        hole_points = _array(row["holes"], f"{field_name}.holes")
        kinds = _array(row["curve_kinds"], f"{field_name}.curve_kinds")
        midpoints = _array(
            row["arc_midpoints"], f"{field_name}.arc_midpoints")
        all_points = [exterior_points] + [
            _array(points, f"{field_name}.holes[{index}]")
            for index, points in enumerate(hole_points)
        ]
        if len(kinds) != len(all_points) or len(midpoints) != len(all_points):
            raise SketchPayloadError(
                f"{field_name} loop geometry/kind arrays must align")
        loops = []
        for index, points in enumerate(all_points):
            kind_row = _array(kinds[index], f"{field_name}.curve_kinds[{index}]")
            midpoint_row = _array(
                midpoints[index], f"{field_name}.arc_midpoints[{index}]")
            loops.append(ProfileLoop.from_wire({
                "points_mm": points,
                "curve_kinds": kind_row,
                "arc_midpoints_mm": midpoint_row,
            }, f"{field_name}.loop[{index}]"))
        if pitches is None:
            pitches = (None,) * len(loops[0].points_mm)
        return cls(element_id, True, loops[0], tuple(loops[1:]), pitches)


@dataclass(frozen=True, slots=True)
class StairsRunPathRecord:
    stairs_element_id: str
    run_id: str
    path_available: bool
    path: TypedPath | None = None

    def __post_init__(self) -> None:
        _string(self.stairs_element_id, "StairsRunPathRecord.stairs_element_id")
        _string(self.run_id, "StairsRunPathRecord.run_id")
        if not isinstance(self.path_available, bool):
            raise SketchPayloadError(
                "StairsRunPathRecord.path_available must be a boolean")
        if self.path_available != (self.path is not None):
            raise SketchPayloadError(
                "stairs path availability and path data disagree")

    def to_dict(self) -> dict[str, Any]:
        if not self.path_available:
            return {"path_available": False}
        if self.path is None:  # guarded by __post_init__
            raise SketchPayloadError("available stairs path lost its geometry")
        row = {"path_available": True}
        row.update(self.path.to_wire())
        return row

    @classmethod
    def from_dict(
        cls,
        stairs_element_id: str,
        run_id: str,
        value: Any,
        field_name: str,
    ) -> "StairsRunPathRecord":
        row = _mapping(value, field_name)
        available = _boolean(
            row.get("path_available"), f"{field_name}.path_available")
        if not available:
            _exact_fields(row, {"path_available"}, field_name)
            return cls(stairs_element_id, run_id, False)
        row = _exact_fields(row, {
            "path_available", "points_mm", "curve_kinds",
            "arc_midpoints_mm",
        }, field_name)
        path = TypedPath.from_wire({
            "points_mm": row["points_mm"],
            "curve_kinds": row["curve_kinds"],
            "arc_midpoints_mm": row["arc_midpoints_mm"],
        }, field_name)
        return cls(stairs_element_id, run_id, True, path)


@dataclass(frozen=True, slots=True)
class RailingPathRecord:
    """Один захват ограждения: путь, хозяин и базовый уровень.

    ТРИ НЕЗАВИСИМЫХ ЧТЕНИЯ, а не одно. Каждое имеет собственную доступность,
    потому что имеет собственного стража на стороне Revit: непрочитанный
    хозяин обязан оставить прочитанный путь на месте. Ровно этой раздельности
    не хватило, когда чтение поворота унесло точку у ВСЕХ помещений во всех
    моделях (cb9c3b65) — общий ``try`` на элемент и есть тот баг.

    ``plane_z_mm`` — высота плоскости пути. ``__ReadChain`` отдаёт точки в
    [x,y], и без этого поля отметка исчезала бы молча: у башни в 59 этажей
    ограждение 41-го этажа легло бы на землю, и никто бы не заметил, потому
    что контур был бы правильный.

    ``has_host is None`` означает «прочитать не удалось», а ``False`` —
    «прочитали, хозяина нет». Это РАЗНЫЕ факты, и схлопывать их в один
    ``bool`` значило бы соврать про второй.
    """

    element_id: str
    path_available: bool
    path: TypedPath | None = None
    plane_z_mm: float | None = None
    has_host: bool | None = None
    host_id: str | None = None
    base_level_id: str | None = None

    def __post_init__(self) -> None:
        _string(self.element_id, "RailingPathRecord.element_id")
        if not isinstance(self.path_available, bool):
            raise SketchPayloadError(
                "RailingPathRecord.path_available must be a boolean")
        if self.path_available != (self.path is not None):
            raise SketchPayloadError(
                "railing path availability and path data disagree")
        if not self.path_available and self.plane_z_mm is not None:
            raise SketchPayloadError(
                "unavailable railing path cannot carry an elevation")
        if self.has_host is not None and not isinstance(self.has_host, bool):
            raise SketchPayloadError(
                "RailingPathRecord.has_host must be a boolean or None")
        # Идентификатор хозяина без самого хозяина — это не «почти данные»,
        # а противоречие: пришло бы оно из живой модели, лифт привязал бы
        # ограждение к элементу, про который сам же сказал «хозяина нет».
        if self.host_id is not None and self.has_host is not True:
            raise SketchPayloadError(
                "railing host_id requires has_host to be true")
        for name in ("host_id", "base_level_id"):
            value = getattr(self, name)
            if value is not None:
                _string(value, f"RailingPathRecord.{name}")

    def to_dict(self) -> dict[str, Any]:
        row: dict[str, Any] = {"path_available": self.path_available}
        if self.path_available and self.path is not None:
            row.update(self.path.to_wire())
            row["plane_z_mm"] = self.plane_z_mm
        else:
            row["points_mm"] = []
            row["curve_kinds"] = []
            row["arc_midpoints_mm"] = []
            row["plane_z_mm"] = None
        row["has_host"] = self.has_host
        row["host_id"] = self.host_id
        row["base_level_id"] = self.base_level_id
        return row

    @classmethod
    def from_dict(
        cls,
        element_id: str,
        value: Any,
        field_name: str = "railing path record",
    ) -> "RailingPathRecord":
        row = _exact_fields(value, {
            "path_available", "points_mm", "curve_kinds", "arc_midpoints_mm",
            "plane_z_mm", "has_host", "host_id", "base_level_id",
        }, field_name)
        available = _boolean(
            row["path_available"], f"{field_name}.path_available")
        path = None
        plane_z = None
        if available:
            path = TypedPath.from_wire({
                "points_mm": row["points_mm"],
                "curve_kinds": row["curve_kinds"],
                "arc_midpoints_mm": row["arc_midpoints_mm"],
            }, field_name)
            raw_plane_z = row["plane_z_mm"]
            if raw_plane_z is not None:
                plane_z = _number(raw_plane_z, f"{field_name}.plane_z_mm")
        elif any(row[key] for key in (
                "points_mm", "curve_kinds", "arc_midpoints_mm")):
            raise SketchPayloadError(
                f"{field_name}: unavailable path cannot carry geometry")
        raw_has_host = row["has_host"]
        if raw_has_host is not None and not isinstance(raw_has_host, bool):
            raise SketchPayloadError(f"{field_name}.has_host must be boolean")
        return cls(
            element_id,
            available,
            path,
            plane_z,
            raw_has_host,
            row["host_id"],
            row["base_level_id"],
        )


@dataclass(frozen=True, slots=True)
class ProfileFailure:
    """Одна квитанция §18.2 профильного индекса.

    ``typed_reason`` добавлен этой волной: до неё sketch был единственной
    стадией БЕЗ бюджета (три полномодельных прохода в одном вызове при
    таймауте 30 с и ``retries=0``), и потому единственной, у которой срез
    вообще нечем было назвать.

    Поле БОЛЬШЕ НЕ НЕОБЯЗАТЕЛЬНОЕ по существу: если конструктор его не дал,
    тип выводится из строки таблицей совместимости. Прежний довод — «строки
    вроде „dependent Sketch count is 2“ суть наблюдения об элементе, и
    подписывать их типом было бы враньём» — верен в наблюдении и неверен в
    выводе: из него следовало не отсутствие типа, а отсутствие второго
    КЛАССА причин. Класс теперь есть (:class:`SideFailureKind`), наблюдение
    называется наблюдением, и при этом остаётся агрегируемым. Пока типа не
    было, эти 227 строк не попадали ни в одну разбивку паспорта.
    """

    element_id: str
    reason: str
    typed_reason: SideFailureReason | None = None
    elapsed_ms: int | None = None

    def __post_init__(self) -> None:
        _string(self.element_id, "ProfileFailure.element_id")
        _string(self.reason, "ProfileFailure.reason")
        if self.typed_reason is None:
            # Вывод стоит ЗДЕСЬ, а не на пяти местах постройки: закон «у
            # отказа обязана быть причина» должен держаться независимо от
            # того, какая ветка экстрактора его создала, иначе следующая
            # добавленная ветка снова родит квитанцию без причины.
            inferred = legacy_typed_reason("sketch", self.reason)
            if inferred is not None:
                object.__setattr__(self, "typed_reason", inferred)
        if self.typed_reason is None:
            if self.elapsed_ms is not None:
                raise SketchPayloadError(
                    "ProfileFailure.elapsed_ms requires a typed reason")
        elif not isinstance(self.typed_reason, SideFailureReason):
            raise SketchPayloadError(
                "ProfileFailure.typed_reason must be a SideFailureReason")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "element_id": self.element_id, "reason": self.reason}
        if self.typed_reason is not None:
            result["typed_reason"] = self.typed_reason.value
            result["elapsed_ms"] = self.elapsed_ms
        return result


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


def _typed_reason(value: Any, field_name: str) -> SideFailureReason | None:
    if value is None:
        return None
    try:
        return SideFailureReason(value)
    except (TypeError, ValueError) as exc:
        raise SketchPayloadError(
            f"{field_name}.typed_reason is unsupported") from exc


@dataclass(frozen=True, slots=True)
class ProfileExtraction:
    """Validated side-index result, independent of frozen ``schema.py``."""

    records: tuple[ProfileIndexRecord, ...]
    stairs_run_paths: tuple[StairsRunPathRecord, ...] = ()
    failures: tuple[ProfileFailure, ...] = ()
    #: Дописано В КОНЕЦ намеренно: существующие позиционные конструкции
    #: ``ProfileExtraction(records, paths, failures)`` обязаны остаться
    #: верными, иначе правка «добавили поле» тихо переставила бы квитанции.
    railing_paths: tuple[RailingPathRecord, ...] = ()

    def __post_init__(self) -> None:
        record_ids = [record.element_id for record in self.records]
        if len(record_ids) != len(set(record_ids)):
            raise SketchPayloadError("profile index contains duplicate element_id")
        path_keys = [
            (record.stairs_element_id, record.run_id)
            for record in self.stairs_run_paths
        ]
        if len(path_keys) != len(set(path_keys)):
            raise SketchPayloadError("stairs path index contains duplicate run_id")
        railing_ids = [record.element_id for record in self.railing_paths]
        if len(railing_ids) != len(set(railing_ids)):
            raise SketchPayloadError(
                "railing path index contains duplicate element_id")

    def __iter__(self) -> Iterator[ProfileIndexRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def profile_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.records, key=lambda record: _element_id_key(record.element_id))
        }

    @property
    def stairs_run_path_index(self) -> dict[str, dict[str, dict[str, Any]]]:
        result: dict[str, dict[str, dict[str, Any]]] = {}
        for record in sorted(
                self.stairs_run_paths,
                key=lambda item: (
                    _element_id_key(item.stairs_element_id),
                    _element_id_key(item.run_id))):
            result.setdefault(record.stairs_element_id, {})[
                record.run_id] = record.to_dict()
        return result

    @property
    def railing_path_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.railing_paths,
                key=lambda record: _element_id_key(record.element_id))
        }

    def entry_for(self, element_id: str) -> ProfileIndexRecord:
        for record in self.records:
            if record.element_id == element_id:
                return record
        raise SketchPayloadError(
            f"element is absent from profile index: {element_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_INDEX_SCHEMA_VERSION,
            "profile_index": self.profile_index,
            "stairs_run_path_index": self.stairs_run_path_index,
            # ОТСУТСТВУЕТ, когда ограждений нет, — ровно как ``slopes`` у
            # кровли. Здание без ограждений обязано лечь на диск байт в байт
            # так же, как до этой волны, иначе «мы ничего не меняли» станет
            # непроверяемым утверждением, а версия индекса — обязана была бы
            # смениться и обесценить все существующие возобновления.
            **({"railing_path_index": self.railing_path_index}
               if self.railing_paths else {}),
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
    def from_dict(cls, value: Any) -> "ProfileExtraction":
        root = _exact_fields(value, {
            "schema_version", "profile_index", "stairs_run_path_index",
            "failures", "railing_path_index",
        }, "persisted profile extraction",
            # Необязателен на ЧТЕНИИ: каждый уже записанный sketch.index.json
            # этого ключа не имеет, и обязан читаться дальше. Без optional
            # правка «добавили индекс» сломала бы возобновление на всех
            # существующих слепках разом.
            optional={"railing_path_index"})
        if root["schema_version"] != PROFILE_INDEX_SCHEMA_VERSION:
            raise SketchPayloadError("profile index schema_version mismatch")
        raw_index = _mapping(
            root["profile_index"], "persisted profile extraction.profile_index")
        records = tuple(
            ProfileIndexRecord.from_dict(
                element_id,
                row,
                f"persisted profile extraction.profile_index[{element_id!r}]",
            )
            for element_id, row in sorted(
                raw_index.items(), key=lambda item: _element_id_key(item[0]))
        )
        raw_stairs = _mapping(
            root["stairs_run_path_index"],
            "persisted profile extraction.stairs_run_path_index")
        paths = []
        for stairs_id, raw_runs in sorted(
                raw_stairs.items(), key=lambda item: _element_id_key(item[0])):
            _string(stairs_id, "stairs element id")
            runs = _mapping(raw_runs, f"stairs path index[{stairs_id!r}]")
            for run_id, row in sorted(
                    runs.items(), key=lambda item: _element_id_key(item[0])):
                paths.append(StairsRunPathRecord.from_dict(
                    stairs_id, run_id, row,
                    f"stairs path index[{stairs_id!r}][{run_id!r}]"))
        raw_failures = _array(
            root["failures"], "persisted profile extraction.failures")
        failures = []
        for index, raw_failure in enumerate(raw_failures):
            row = _exact_fields(
                raw_failure,
                {"element_id", "reason", "typed_reason", "elapsed_ms"},
                f"persisted profile extraction.failures[{index}]",
                optional={"typed_reason", "elapsed_ms"})
            failures.append(ProfileFailure(
                _string(row["element_id"], f"failures[{index}].element_id"),
                _string(row["reason"], f"failures[{index}].reason"),
                _typed_reason(
                    row.get("typed_reason"), f"failures[{index}]"),
                row.get("elapsed_ms"),
            ))
        raw_railings = _mapping(
            root.get("railing_path_index") or {},
            "persisted profile extraction.railing_path_index")
        railings = tuple(
            RailingPathRecord.from_dict(
                element_id,
                row,
                "persisted profile extraction."
                f"railing_path_index[{element_id!r}]",
            )
            for element_id, row in sorted(
                raw_railings.items(),
                key=lambda item: _element_id_key(item[0]))
        )
        return cls(records, tuple(paths), tuple(failures), railings)

    @classmethod
    def from_json(cls, value: str | bytes | bytearray) -> "ProfileExtraction":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise SketchPayloadError(f"profile index is not valid JSON: {exc}") \
                from exc
        return cls.from_dict(decoded)


def _normalize_angle(value: float) -> float:
    result = math.fmod(value, math.tau)
    return result + math.tau if result < 0.0 else result


def _arc_geometry(
    start: Vec2,
    midpoint: Vec2,
    end: Vec2,
) -> tuple[float, float, float, float, float]:
    """Return center, radius, start angle, and directed sweep through mid."""

    x1, y1 = start
    x2, y2 = midpoint
    x3, y3 = end
    denominator = 2.0 * (
        x1 * (y2 - y3)
        + x2 * (y3 - y1)
        + x3 * (y1 - y2))
    scale = max(
        _distance_squared(start, midpoint),
        _distance_squared(midpoint, end),
        _distance_squared(start, end),
        1.0,
    )
    if abs(denominator) <= 1e-12 * scale:
        raise SketchPayloadError("arc start/mid/end are collinear")
    start_sq = x1 * x1 + y1 * y1
    middle_sq = x2 * x2 + y2 * y2
    end_sq = x3 * x3 + y3 * y3
    center_x = (
        start_sq * (y2 - y3)
        + middle_sq * (y3 - y1)
        + end_sq * (y1 - y2)) / denominator
    center_y = (
        start_sq * (x3 - x2)
        + middle_sq * (x1 - x3)
        + end_sq * (x2 - x1)) / denominator
    radius = math.hypot(x1 - center_x, y1 - center_y)
    if not math.isfinite(radius) or radius <= 0.0:
        raise SketchPayloadError("arc radius is invalid")
    start_angle = math.atan2(y1 - center_y, x1 - center_x)
    middle_angle = math.atan2(y2 - center_y, x2 - center_x)
    end_angle = math.atan2(y3 - center_y, x3 - center_x)
    ccw_end = _normalize_angle(end_angle - start_angle)
    ccw_middle = _normalize_angle(middle_angle - start_angle)
    tolerance = 1e-10
    if tolerance < ccw_middle < ccw_end - tolerance:
        delta = ccw_end
    else:
        clockwise_end = _normalize_angle(start_angle - end_angle)
        clockwise_middle = _normalize_angle(start_angle - middle_angle)
        if not (tolerance < clockwise_middle < clockwise_end - tolerance):
            raise SketchPayloadError(
                "arc midpoint does not lie strictly between its endpoints")
        delta = -clockwise_end
    return center_x, center_y, radius, start_angle, delta


def _arc_parameter(angle: float, start: float, delta: float) -> float:
    progress = (
        _normalize_angle(angle - start)
        if delta > 0.0 else _normalize_angle(start - angle))
    return progress / abs(delta)


def _point_in_loop(point: Vec2, loop: ProfileLoop) -> bool:
    """Analytic even/odd test; arcs are intersected as circles, not chords."""

    px, py = point
    crossings = 0
    count = len(loop.points_mm)
    for index, kind in enumerate(loop.curve_kinds):
        start = loop.points_mm[index]
        end = loop.points_mm[(index + 1) % count]
        if kind is CurveKind.LINE:
            if (start[1] > py) != (end[1] > py):
                x_intersection = (
                    start[0]
                    + (py - start[1]) * (end[0] - start[0])
                    / (end[1] - start[1]))
                if x_intersection > px:
                    crossings += 1
            continue
        midpoint = loop.arc_midpoints_mm[index]
        if midpoint is None:  # guarded by ProfileLoop
            raise SketchPayloadError("arc midpoint is absent")
        center_x, center_y, radius, start_angle, delta = _arc_geometry(
            start, midpoint, end)
        normalized_y = (py - center_y) / radius
        if normalized_y < -1.0 or normalized_y > 1.0:
            continue
        normalized_y = min(1.0, max(-1.0, normalized_y))
        first = math.asin(normalized_y)
        for angle in (first, math.pi - first):
            parameter = _arc_parameter(angle, start_angle, delta)
            # Half-open [0,1) prevents a shared endpoint from being counted
            # twice.  Horizontal tangencies do not cross the test ray.
            if parameter < -1e-10 or parameter >= 1.0 - 1e-10:
                continue
            derivative_y = radius * math.cos(angle) * delta
            if abs(derivative_y) <= radius * 1e-12:
                continue
            x_intersection = center_x + radius * math.cos(angle)
            if x_intersection > px:
                crossings += 1
    return crossings % 2 == 1


def _loop_sort_key(loop: ProfileLoop) -> tuple[Any, ...]:
    return tuple(
        (point[0], point[1], kind.value,
         () if midpoint is None else midpoint)
        for point, kind, midpoint in zip(
            loop.points_mm, loop.curve_kinds, loop.arc_midpoints_mm))


def _classify_loops(
    loops: Sequence[ProfileLoop],
) -> tuple[ProfileLoop, tuple[ProfileLoop, ...]]:
    if not loops:
        raise SketchPayloadError("profile contains no loops")
    areas = []
    for loop in loops:
        area = loop.signed_area_mm2
        if abs(area) <= 1e-6:
            raise SketchPayloadError("profile contains a zero-area loop")
        areas.append(area)
    exterior_index = min(
        range(len(loops)),
        key=lambda index: (-abs(areas[index]), _loop_sort_key(loops[index])))
    exterior = loops[exterior_index]
    holes = []
    for index, loop in enumerate(loops):
        if index == exterior_index:
            continue
        if abs(areas[index]) >= abs(areas[exterior_index]):
            raise SketchPayloadError(
                "profile has no unique containing exterior loop")
        # A valid Revit sketch cannot touch its exterior.  Testing a real hole
        # vertex therefore proves containment without inventing a centroid;
        # the outer loop's arcs are intersected analytically above.
        if not _point_in_loop(loop.points_mm[0], exterior):
            raise SketchPayloadError(
                "profile has a disjoint/nested exterior that the side schema "
                "cannot represent")
        holes.append(loop)
    holes.sort(key=_loop_sort_key)
    return exterior, tuple(holes)


def _unwrap_bridge_payload(value: Any) -> Any:
    current = value
    for _ in range(2):
        if not isinstance(current, Mapping) or "ok" not in current:
            break
        if current.get("ok") is not True:
            detail = current.get("error") or current.get("message") \
                or "bridge refused Sketch extraction"
            raise SketchPayloadError(str(detail)[:300])
        if "result" not in current:
            break
        current = current["result"]
    return current


def _parse_railing_block(
    element_id: str,
    value: Any,
    field_name: str,
    failures: list[ProfileFailure],
) -> RailingPathRecord:
    """Разбор трёх НЕЗАВИСИМЫХ чтений ограждения.

    Каждое из трёх (путь, хозяин, базовый уровень) либо прочитано, либо
    отказано ПОИМЁННО — и отказ одного не трогает остальные два. Именно
    поэтому здесь три отдельных блока, а не один ``try``: общий страж на
    элемент — это тот самый дефект, что унёс точку у всех помещений.

    Нечитаемое НИКОГДА не подменяется умолчанием: непрочитанный хозяин даёт
    ``has_host=None`` (а не ``False``) и квитанцию, потому что «не смогли
    посмотреть» и «посмотрели, хозяина нет» — разные факты о здании.
    """
    block = _exact_fields(
        value, {"path", "host", "base_level"}, field_name)

    path_row = _exact_fields(block["path"], {
        "available", "points_mm", "curve_kinds", "arc_midpoints_mm",
        "plane_z_mm", "reason",
    }, f"{field_name}.path")
    path_available = _boolean(
        path_row["available"], f"{field_name}.path.available")
    path: TypedPath | None = None
    plane_z: float | None = None
    if path_available:
        if path_row["reason"] is not None:
            raise SketchPayloadError(
                f"{field_name}.path: available path cannot carry a reason")
        path = TypedPath.from_wire({
            "points_mm": path_row["points_mm"],
            "curve_kinds": path_row["curve_kinds"],
            "arc_midpoints_mm": path_row["arc_midpoints_mm"],
        }, f"{field_name}.path")
        raw_plane_z = path_row["plane_z_mm"]
        if raw_plane_z is not None:
            plane_z = _number(raw_plane_z, f"{field_name}.path.plane_z_mm")
    else:
        if any(path_row[key] for key in (
                "points_mm", "curve_kinds", "arc_midpoints_mm")):
            raise SketchPayloadError(
                f"{field_name}.path: unavailable path cannot carry geometry")
        if path_row["plane_z_mm"] is not None:
            raise SketchPayloadError(
                f"{field_name}.path: unavailable path cannot carry elevation")
        reason = _string(path_row["reason"], f"{field_name}.path.reason")
        # CUT, а не DETERMINATION: путь у ограждения ЕСТЬ всегда, и если мы
        # его не прочитали — это про нас. Класс намеренно самокритичен.
        failures.append(ProfileFailure(
            element_id, f"railing path unavailable: {reason}"[:300],
            SideFailureReason.READ_FAILED))

    host_row = _exact_fields(block["host"], {
        "available", "has_host", "host_id", "reason",
    }, f"{field_name}.host")
    host_available = _boolean(
        host_row["available"], f"{field_name}.host.available")
    has_host: bool | None = None
    host_id: str | None = None
    if host_available:
        if host_row["reason"] is not None:
            raise SketchPayloadError(
                f"{field_name}.host: available host cannot carry a reason")
        raw_has_host = host_row["has_host"]
        if not isinstance(raw_has_host, bool):
            raise SketchPayloadError(
                f"{field_name}.host.has_host must be a boolean")
        has_host = raw_has_host
        if host_row["host_id"] is not None:
            host_id = _string(
                host_row["host_id"], f"{field_name}.host.host_id")
    else:
        if host_row["has_host"] is not None or host_row["host_id"] is not None:
            raise SketchPayloadError(
                f"{field_name}.host: unavailable host cannot carry a value")
        reason = _string(host_row["reason"], f"{field_name}.host.reason")
        failures.append(ProfileFailure(
            element_id, f"railing host unavailable: {reason}"[:300],
            SideFailureReason.READ_FAILED))

    base_row = _exact_fields(block["base_level"], {
        "available", "level_id", "reason",
    }, f"{field_name}.base_level")
    base_available = _boolean(
        base_row["available"], f"{field_name}.base_level.available")
    base_level_id: str | None = None
    if base_available:
        if base_row["reason"] is not None:
            raise SketchPayloadError(
                f"{field_name}.base_level: available level cannot carry a reason")
        base_level_id = _string(
            base_row["level_id"], f"{field_name}.base_level.level_id")
    else:
        if base_row["level_id"] is not None:
            raise SketchPayloadError(
                f"{field_name}.base_level: unavailable level cannot carry a value")
        reason = _string(
            base_row["reason"], f"{field_name}.base_level.reason")
        # Спорный случай (параметра нет ИЛИ чтение упало — снаружи не
        # различить), а правило класса на спорный случай одно: в CUT.
        failures.append(ProfileFailure(
            element_id, f"railing base level unavailable: {reason}"[:300],
            SideFailureReason.READ_FAILED))

    return RailingPathRecord(
        element_id, path_available, path, plane_z,
        has_host, host_id, base_level_id)


def extract_sketch_profiles(payload: Any) -> ProfileExtraction:
    """Validate one emitted payload and build the frozen-L0 side index.

    Wire-shape corruption is a typed exception.  A well-formed per-element
    failure or an exact profile that cannot be represented by one exterior
    plus holes becomes an honest unavailable record and a diagnostic entry.
    """

    root = _exact_fields(
        _unwrap_bridge_payload(payload),
        # §18.2: ``failures`` — вторая половина ответа. Необязателен только на
        # ЧТЕНИИ уже записанных полезных нагрузок (эмиттер пишет его всегда).
        {"schema_version", "elements", "failures"},
        "Sketch extraction",
        optional={"failures"},
    )
    if root["schema_version"] != SKETCH_EXTRACT_SCHEMA_VERSION:
        raise SketchPayloadError("Sketch extraction schema_version mismatch")
    elements = _array(root["elements"], "Sketch extraction.elements")
    records = []
    stairs_paths = []
    railing_paths = []
    failures = []
    for index, raw_failure in enumerate(
            _array(root.get("failures") or [], "Sketch extraction.failures")):
        row = _exact_fields(
            raw_failure,
            {"element_id", "reason", "typed_reason", "elapsed_ms"},
            f"Sketch extraction.failures[{index}]",
            optional={"typed_reason", "elapsed_ms"})
        failures.append(ProfileFailure(
            _string(row["element_id"],
                    f"Sketch extraction.failures[{index}].element_id"),
            _string(row["reason"],
                    f"Sketch extraction.failures[{index}].reason")[:300],
            _typed_reason(row.get("typed_reason"),
                          f"Sketch extraction.failures[{index}]"),
            row.get("elapsed_ms"),
        ))
    seen_ids: set[str] = set()
    # Дописано В КОНЕЦ (потолок — эскизный элемент, ограждения — путевые).
    # Это ЖЁСТКИЙ отказ на всю стадию, а не на элемент: категория, которую
    # начал отдавать C#, но не принимает разбор, убивает весь пакет разом.
    # Поэтому список обязан расширяться РАНЬШЕ коллектора, а не позже.
    allowed_categories = {
        "OST_Floors", "OST_Roofs", "OST_Stairs",
        "OST_Ceilings", "OST_StairsRailing", "OST_Railings",
    }
    railing_categories = {"OST_StairsRailing", "OST_Railings"}

    for element_index, raw_element in enumerate(elements):
        field_name = f"Sketch extraction.elements[{element_index}]"
        row = _exact_fields(raw_element, {
            "element_id", "category", "profile_available", "loops",
            "slopes", "reason", "stairs_run_paths", "railing",
        }, field_name, optional={"slopes", "railing"})
        element_id = _string(row["element_id"], f"{field_name}.element_id")
        if element_id in seen_ids:
            raise SketchPayloadError(
                f"duplicate profile element_id: {element_id!r}")
        seen_ids.add(element_id)
        category = _string(row["category"], f"{field_name}.category")
        if category not in allowed_categories:
            raise SketchPayloadError(
                f"{field_name}.category is unsupported: {category!r}")
        available = _boolean(
            row["profile_available"], f"{field_name}.profile_available")
        raw_loops = _array(row["loops"], f"{field_name}.loops")
        raw_paths = _array(
            row["stairs_run_paths"], f"{field_name}.stairs_run_paths")

        raw_railing = row.get("railing")
        if raw_railing is not None and category not in railing_categories:
            raise SketchPayloadError(
                f"{field_name}: only a railing may carry a railing block")
        if raw_railing is not None:
            railing_paths.append(_parse_railing_block(
                element_id, raw_railing, f"{field_name}.railing", failures))

        if available:
            if category in railing_categories:
                raise SketchPayloadError(
                    f"{field_name}: a railing cannot claim a closed profile")
            if category == "OST_Stairs":
                raise SketchPayloadError(
                    f"{field_name}: stairs cannot claim a closed parent profile")
            if row["reason"] is not None:
                raise SketchPayloadError(
                    f"{field_name}: available profile cannot carry a reason")
            if raw_paths:
                raise SketchPayloadError(
                    f"{field_name}: floor/roof cannot carry stairs run paths")
            if not raw_loops:
                raise SketchPayloadError(
                    f"{field_name}: available profile requires loops")
            try:
                parsed_loops = tuple(
                    ProfileLoop.from_wire(
                        raw_loop, f"{field_name}.loops[{loop_index}]")
                    for loop_index, raw_loop in enumerate(raw_loops)
                )
                exterior, holes = _classify_loops(parsed_loops)
                # Each pitched edge arrives WITH its endpoints, because
                # __ReadLoops canonicalises the ring: a positional list would
                # attribute the slope to whichever edge happened to land in
                # that slot. Measured live before this: a pitch authored on the
                # bottom edge came back on the left one. So align by geometry,
                # in either direction, and leave every unmatched edge level.
                raw_slopes = row.get("slopes")
                entries = []
                if isinstance(raw_slopes, list) and raw_slopes:
                    first = raw_slopes[0]
                    if isinstance(first, list):
                        entries = [e for e in first if isinstance(e, dict)]
                pitches = _align_slopes(exterior, entries)
                records.append(ProfileIndexRecord(
                    element_id, True, exterior, holes, pitches))
            except SketchPayloadError as exc:
                records.append(ProfileIndexRecord.unavailable(element_id))
                failures.append(ProfileFailure(
                    element_id,
                    f"exact profile topology unavailable: {exc}"[:300],
                ))
            continue

        if raw_loops:
            raise SketchPayloadError(
                f"{field_name}: unavailable profile cannot carry loops")
        reason = _string(row["reason"], f"{field_name}.reason")
        records.append(ProfileIndexRecord.unavailable(element_id))
        failures.append(ProfileFailure(element_id, reason[:300]))
        if category != "OST_Stairs" and raw_paths:
            raise SketchPayloadError(
                f"{field_name}: floor/roof cannot carry stairs run paths")
        for path_index, raw_path in enumerate(raw_paths):
            path_name = f"{field_name}.stairs_run_paths[{path_index}]"
            path_row = _exact_fields(raw_path, {
                "run_id", "path_available", "points_mm", "curve_kinds",
                "arc_midpoints_mm", "reason",
            }, path_name)
            run_id = _string(path_row["run_id"], f"{path_name}.run_id")
            path_available = _boolean(
                path_row["path_available"], f"{path_name}.path_available")
            if path_available:
                if path_row["reason"] is not None:
                    raise SketchPayloadError(
                        f"{path_name}: available path cannot carry a reason")
                path = TypedPath.from_wire({
                    "points_mm": path_row["points_mm"],
                    "curve_kinds": path_row["curve_kinds"],
                    "arc_midpoints_mm": path_row["arc_midpoints_mm"],
                }, path_name)
                stairs_paths.append(StairsRunPathRecord(
                    element_id, run_id, True, path))
            else:
                if any(path_row[key] for key in (
                        "points_mm", "curve_kinds", "arc_midpoints_mm")):
                    raise SketchPayloadError(
                        f"{path_name}: unavailable path cannot carry geometry")
                path_reason = _string(
                    path_row["reason"], f"{path_name}.reason")
                stairs_paths.append(StairsRunPathRecord(
                    element_id, run_id, False))
                failures.append(ProfileFailure(
                    element_id,
                    f"stairs run {run_id} path unavailable: {path_reason}"[:300],
                ))

    return ProfileExtraction(
        records=tuple(sorted(
            records, key=lambda record: _element_id_key(record.element_id))),
        stairs_run_paths=tuple(sorted(
            stairs_paths,
            key=lambda record: (
                _element_id_key(record.stairs_element_id),
                _element_id_key(record.run_id)))),
        failures=tuple(sorted(
            failures,
            key=lambda failure: (
                _element_id_key(failure.element_id), failure.reason))),
        railing_paths=tuple(sorted(
            railing_paths,
            key=lambda record: _element_id_key(record.element_id))),
    )


# This is a method body for the same ``wrap_user_code`` path used in serving.
# It performs no transaction and never calls get_BoundingBox/get_Geometry.
SKETCH_EXTRACT_CS = r"""
// Имя класса БЕЗ обращения к среде выполнения за типом: та форма записи
// целиком отвергается валидатором безопасности моста версий до 06.07.2026,
// который всё ещё стоит на части флота, — тело браковалось бы на машине
// пользователя ДО компиляции, и сервер об этом не узнавал бы.
// Object.ToString() у Element/Curve/Surface и у исключений — это полное имя
// типа CLR: из Autodesk.Revit.DB его перекрывают только ElementId, UV, XYZ,
// WorksetId, ScheduleFieldId и PolymeshFacet (замер по индексу ловушек), и
// ни один из них сюда не передаётся. Исключение дописывает ": сообщение" и
// стек, поэтому срез идёт по первому переводу строки и первому двоеточию.
// Результат побайтно равен прежнему .Name.
Func<object, string> __skClassName = (__skcnObj) =>
{
    if (__skcnObj == null) return "";
    string __skcn = __skcnObj.ToString();
    if (__skcn == null) return "";
    int __skcnCut = __skcn.IndexOf((char)10);
    if (__skcnCut >= 0) __skcn = __skcn.Substring(0, __skcnCut);
    __skcnCut = __skcn.IndexOf(':');
    if (__skcnCut >= 0) __skcn = __skcn.Substring(0, __skcnCut);
    __skcn = __skcn.Trim();
    __skcnCut = __skcn.LastIndexOf('.');
    return __skcnCut >= 0 && __skcnCut + 1 < __skcn.Length
        ? __skcn.Substring(__skcnCut + 1) : __skcn;
};
Func<double, double> __MM = (__value) =>
    UnitUtils.ConvertFromInternalUnits(__value, UnitTypeId.Millimeters);
double __JoinTolerance = UnitUtils.ConvertToInternalUnits(
    0.01, UnitTypeId.Millimeters);
Func<XYZ, bool> __FiniteXYZ = (__point) =>
    __point != null
    && !Double.IsNaN(__point.X) && !Double.IsInfinity(__point.X)
    && !Double.IsNaN(__point.Y) && !Double.IsInfinity(__point.Y)
    && !Double.IsNaN(__point.Z) && !Double.IsInfinity(__point.Z);
Func<XYZ, double[]> __XYMM = (__point) => new double[] {
    __MM(__point.X), __MM(__point.Y)
};
Func<ElementId, long> __IdValue = (__id) =>
{
    try { return long.Parse(__id.ToString()); }
    catch { return long.MinValue; }
};

Func<IList<Curve>, bool, Dictionary<string, object>> __ReadChain =
    (__curves, __closed) =>
{
    var __result = new Dictionary<string, object>();
    __result["ok"] = false;
    __result["reason"] = null;
    __result["points_mm"] = new List<object>();
    __result["curve_kinds"] = new List<object>();
    __result["arc_midpoints_mm"] = new List<object>();
    // Высота плоскости цепи. Точки уходят в [x,y], и до этой волны Z просто
    // ИСЧЕЗАЛ: для замкнутого контура пола это безобидно (уровень + смещение
    // восстанавливают его), а для пути ограждения — нет. Ключ добавлен, а не
    // подставлен: читатели контуров (__ReadLoops, stairs) копируют
    // ИМЕНОВАННЫЕ ключи и этого не видят, так что старый диалект не двинулся.
    __result["plane_z_mm"] = null;
    int __minimum = __closed ? 2 : 1;
    if (__curves == null || __curves.Count < __minimum)
    {
        __result["reason"] = "curve chain is empty/too short";
        return __result;
    }
    try
    {
        var __points = new List<object>();
        var __kinds = new List<object>();
        var __arcMidpoints = new List<object>();
        XYZ __first = null;
        XYZ __previousEnd = null;
        double __planeZ = 0.0;
        bool __havePlane = false;
        for (int __index = 0; __index < __curves.Count; ++__index)
        {
            Curve __curve = __curves[__index];
            if (__curve == null || !__curve.IsBound)
            {
                __result["reason"] = "profile contains null/unbound curve";
                return __result;
            }
            XYZ __start = __curve.GetEndPoint(0);
            XYZ __end = __curve.GetEndPoint(1);
            if (!__FiniteXYZ(__start) || !__FiniteXYZ(__end))
            {
                __result["reason"] = "profile contains non-finite endpoint";
                return __result;
            }
            if (__start.DistanceTo(__end) <= __JoinTolerance)
            {
                __result["reason"] = "profile contains degenerate segment";
                return __result;
            }
            if (__previousEnd != null
                    && __start.DistanceTo(__previousEnd) > __JoinTolerance)
            {
                __result["reason"] = "profile curve order is disconnected";
                return __result;
            }
            if (!__havePlane)
            {
                __planeZ = __start.Z;
                __havePlane = true;
            }
            if (Math.Abs(__start.Z - __planeZ) > __JoinTolerance
                    || Math.Abs(__end.Z - __planeZ) > __JoinTolerance)
            {
                __result["reason"] = "profile is not a horizontal XY contour";
                return __result;
            }
            string __kind = null;
            object __arcMidpoint = null;
            var __line = __curve as Line;
            var __arc = __curve as Arc;
            if (__line != null)
            {
                __kind = "line";
            }
            else if (__arc != null)
            {
                XYZ __middle = __arc.Evaluate(0.5, true);
                if (!__FiniteXYZ(__middle)
                        || Math.Abs(__middle.Z - __planeZ) > __JoinTolerance)
                {
                    __result["reason"] = "arc midpoint is invalid/non-planar";
                    return __result;
                }
                __kind = "arc";
                __arcMidpoint = __XYMM(__middle);
            }
            else
            {
                __result["reason"] = "unsupported exact curve kind: "
                    + __skClassName(__curve);
                return __result;
            }
            if (__index == 0) __first = __start;
            __points.Add(__XYMM(__start));
            __kinds.Add(__kind);
            __arcMidpoints.Add(__arcMidpoint);
            __previousEnd = __end;
        }
        if (__closed)
        {
            if (__first == null || __previousEnd == null
                    || __first.DistanceTo(__previousEnd) > __JoinTolerance)
            {
                __result["reason"] = "profile curve chain is open";
                return __result;
            }
        }
        else
        {
            if (__previousEnd == null)
            {
                __result["reason"] = "stairs path has no endpoint";
                return __result;
            }
            __points.Add(__XYMM(__previousEnd));
        }
        __result["ok"] = true;
        __result["reason"] = null;
        __result["points_mm"] = __points;
        __result["curve_kinds"] = __kinds;
        __result["arc_midpoints_mm"] = __arcMidpoints;
        // __havePlane истинно на любом непустом успехе, и все точки уже
        // проверены на одну плоскость выше — иначе сюда не дошли бы.
        if (__havePlane) __result["plane_z_mm"] = __MM(__planeZ);
        return __result;
    }
    catch (Exception __error)
    {
        __result["reason"] = "curve read failed: " + __skClassName(__error);
        return __result;
    }
};

Func<List<List<Curve>>, Dictionary<string, object>> __ReadLoops =
    (__sourceLoops) =>
{
    var __result = new Dictionary<string, object>();
    var __loops = new List<object>();
    __result["ok"] = false;
    __result["reason"] = null;
    __result["loops"] = __loops;
    if (__sourceLoops == null || __sourceLoops.Count == 0)
    {
        __result["reason"] = "profile API returned no loops";
        return __result;
    }
    foreach (var __sourceLoop in __sourceLoops)
    {
        var __loop = __ReadChain(__sourceLoop, true);
        if (!((bool)__loop["ok"]))
        {
            __result["reason"] = __loop["reason"];
            return __result;
        }
        var __wireLoop = new Dictionary<string, object>();
        __wireLoop["points_mm"] = __loop["points_mm"];
        __wireLoop["curve_kinds"] = __loop["curve_kinds"];
        __wireLoop["arc_midpoints_mm"] = __loop["arc_midpoints_mm"];
        __loops.Add(__wireLoop);
    }
    __result["ok"] = true;
    return __result;
};

Func<Element, Dictionary<string, object>> __DependentSketchLoops = (__element) =>
{
    var __result = new Dictionary<string, object>();
    __result["ok"] = false;
    __result["reason"] = "element has no unique dependent Sketch";
    __result["loops"] = new List<object>();
    try
    {
        var __sketches = new List<Sketch>();
        foreach (ElementId __dependentId in __element.GetDependentElements(null))
        {
            var __sketch = __src.GetElement(__dependentId) as Sketch;
            if (__sketch != null) __sketches.Add(__sketch);
        }
        if (__sketches.Count != 1)
        {
            __result["reason"] = "dependent Sketch count is "
                + __sketches.Count.ToString();
            return __result;
        }
        CurveArrArray __profile = __sketches[0].Profile;
        var __sourceLoops = new List<List<Curve>>();
        foreach (CurveArray __curveArray in __profile)
        {
            var __curves = new List<Curve>();
            foreach (Curve __curve in __curveArray) __curves.Add(__curve);
            __sourceLoops.Add(__curves);
        }
        return __ReadLoops(__sourceLoops);
    }
    catch (Exception __error)
    {
        __result["reason"] = "Sketch.Profile failed: "
            + __skClassName(__error);
        return __result;
    }
};

Func<FootPrintRoof, Dictionary<string, object>> __FootPrintRoofLoops = (__roof) =>
{
    var __result = new Dictionary<string, object>();
    __result["ok"] = false;
    __result["reason"] = "FootPrintRoof.GetProfiles failed";
    __result["loops"] = new List<object>();
    try
    {
        var __sourceLoops = new List<List<Curve>>();
        // The pitch lives on the very ModelCurve whose geometry we are already
        // reading, and was being dropped one line before it could be kept —
        // which is why every roof came back flat no matter how it was built.
        // set_SlopeAngle takes a RATIO (measured 2026-07-26, not documented),
        // so degrees are recovered with atan and the schema stays in degrees.
        var __slopeLoops = new List<object>();
        ModelCurveArrArray __profiles = __roof.GetProfiles();
        foreach (ModelCurveArray __modelCurveArray in __profiles)
        {
            var __curves = new List<Curve>();
            var __slopes = new List<object>();
            foreach (ModelCurve __modelCurve in __modelCurveArray)
            {
                if (__modelCurve == null || __modelCurve.GeometryCurve == null)
                {
                    __result["reason"] = "roof profile contains null ModelCurve";
                    return __result;
                }
                __curves.Add(__modelCurve.GeometryCurve);
                try
                {
                    if (__roof.get_DefinesSlope(__modelCurve))
                    {
                        double __ratio = __roof.get_SlopeAngle(__modelCurve);
                        if (__ratio > 0.0)
                        {
                            // WITH its endpoints: __ReadLoops canonicalises the
                            // ring (start vertex and direction), so a bare
                            // positional list lands on the wrong edge — measured
                            // live, the pitch authored on the bottom edge came
                            // back attributed to the left one.
                            var __c = __modelCurve.GeometryCurve;
                            var __s0 = __c.GetEndPoint(0);
                            var __s1 = __c.GetEndPoint(1);
                            __slopes.Add(new Dictionary<string, object> {
                                { "deg", Math.Round(
                                    Math.Atan(__ratio) * 180.0 / Math.PI, 6) },
                                { "p0_mm", new double[] {
                                    Math.Round(__MM(__s0.X), 3),
                                    Math.Round(__MM(__s0.Y), 3) } },
                                { "p1_mm", new double[] {
                                    Math.Round(__MM(__s1.X), 3),
                                    Math.Round(__MM(__s1.Y), 3) } },
                            });
                        }
                    }
                }
                catch { }
            }
            __sourceLoops.Add(__curves);
            __slopeLoops.Add(__slopes);
        }
        var __loopResult = __ReadLoops(__sourceLoops);
        __loopResult["slopes"] = __slopeLoops;
        return __loopResult;
    }
    catch (Exception __error)
    {
        __result["reason"] = "FootPrintRoof.GetProfiles failed: "
            + __skClassName(__error);
        return __result;
    }
};

Func<ExtrusionRoof, Dictionary<string, object>> __ExtrusionRoofLoops = (__roof) =>
{
    var __result = new Dictionary<string, object>();
    __result["ok"] = false;
    __result["reason"] = "ExtrusionRoof.GetProfile failed";
    __result["loops"] = new List<object>();
    try
    {
        var __curves = new List<Curve>();
        ModelCurveArray __profile = __roof.GetProfile();
        foreach (ModelCurve __modelCurve in __profile)
        {
            if (__modelCurve == null || __modelCurve.GeometryCurve == null)
            {
                __result["reason"] = "extrusion profile contains null ModelCurve";
                return __result;
            }
            __curves.Add(__modelCurve.GeometryCurve);
        }
        return __ReadLoops(new List<List<Curve>> { __curves });
    }
    catch (Exception __error)
    {
        __result["reason"] = "ExtrusionRoof.GetProfile failed: "
            + __skClassName(__error);
        return __result;
    }
};

Func<Element, string, Dictionary<string, object>> __ProfileRow =
    (__element, __category) =>
{
    var __row = new Dictionary<string, object>();
    __row["element_id"] = __element.Id.ToString();
    __row["category"] = __category;
    __row["profile_available"] = false;
    __row["loops"] = new List<object>();
    __row["slopes"] = null;
    __row["reason"] = "profile API path unavailable";
    __row["stairs_run_paths"] = new List<object>();

    Dictionary<string, object> __profile = null;
    if (__category == "OST_Roofs")
    {
        var __footprint = __element as FootPrintRoof;
        if (__footprint != null) __profile = __FootPrintRoofLoops(__footprint);
    }
    if (__profile == null || !((bool)__profile["ok"]))
        __profile = __DependentSketchLoops(__element);
    if ((__profile == null || !((bool)__profile["ok"]))
            && __category == "OST_Roofs")
    {
        var __extrusion = __element as ExtrusionRoof;
        if (__extrusion != null) __profile = __ExtrusionRoofLoops(__extrusion);
    }
    if (__profile != null && ((bool)__profile["ok"]))
    {
        __row["profile_available"] = true;
        __row["loops"] = __profile["loops"];
        // Without this line the pitch is computed and then dropped: __profile
        // is a scratch dictionary and only the keys copied here survive.
        __row["slopes"] = __profile.ContainsKey("slopes") ? __profile["slopes"] : null;
        __row["reason"] = null;
    }
    else if (__profile != null && __profile["reason"] != null)
    {
        __row["reason"] = __profile["reason"].ToString();
    }
    return __row;
};

// Ограждение — ПУТЕВОЙ элемент, а не эскизный: замкнутого профиля у него нет
// вовсе, ровно как у лестницы. Поэтому строка строится здесь, а не в
// __ProfileRow, и несёт три НЕЗАВИСИМЫХ чтения — путь, хозяина и базовый
// уровень. Каждое под своим стражем: общий try на весь элемент — это тот
// самый баг, из-за которого чтение поворота унесло точку у ВСЕХ помещений
// (cb9c3b65). Непрочитанный хозяин не имеет права унести прочитанный путь.
//
// Позиции установки (RailingPlacementPosition) здесь нет и быть не может:
// весь член-состав Railing на шести версиях — 20 членов, и это перечисление
// встречается ТОЛЬКО как параметр двух перегрузок Create. Геттера не
// существует, поэтому выдумывать «Treads по умолчанию» мы не станем —
// путевая перегрузка Railing.Create(doc, CurveLoop, typeId, baseLevelId)
// позиции не требует вовсе.
Func<Autodesk.Revit.DB.Architecture.Railing, string, Dictionary<string, object>>
    __RailingRow = (__railing, __category) =>
{
    var __row = new Dictionary<string, object>();
    __row["element_id"] = __railing.Id.ToString();
    __row["category"] = __category;
    __row["profile_available"] = false;
    __row["loops"] = new List<object>();
    __row["slopes"] = null;
    __row["reason"] = "railing is a path element and has no closed Sketch profile";
    __row["stairs_run_paths"] = new List<object>();

    var __railBlock = new Dictionary<string, object>();

    var __pathRow = new Dictionary<string, object>();
    __pathRow["available"] = false;
    __pathRow["points_mm"] = new List<object>();
    __pathRow["curve_kinds"] = new List<object>();
    __pathRow["arc_midpoints_mm"] = new List<object>();
    __pathRow["plane_z_mm"] = null;
    __pathRow["reason"] = "Railing.GetPath unavailable";
    try
    {
        IList<Curve> __railPathCurves = __railing.GetPath();
        var __railCurves = new List<Curve>();
        if (__railPathCurves != null)
            foreach (Curve __curve in __railPathCurves)
                __railCurves.Add(__curve);
        // ОТКРЫТАЯ цепь. Потребуй замыкания — и первая же прямая нитка
        // лестничного марша уйдёт в отказ «контур не замкнут».
        var __railPath = __ReadChain(__railCurves, false);
        if ((bool)__railPath["ok"])
        {
            __pathRow["available"] = true;
            __pathRow["points_mm"] = __railPath["points_mm"];
            __pathRow["curve_kinds"] = __railPath["curve_kinds"];
            __pathRow["arc_midpoints_mm"] = __railPath["arc_midpoints_mm"];
            __pathRow["plane_z_mm"] = __railPath["plane_z_mm"];
            __pathRow["reason"] = null;
        }
        else
        {
            __pathRow["reason"] = __railPath["reason"];
        }
    }
    catch (Exception __error)
    {
        // Autodesk документирует это на всех шести версиях:
        // InapplicableDataException «The railing has incorrect internal data».
        __pathRow["reason"] = "Railing.GetPath failed: "
            + __skClassName(__error);
    }
    __railBlock["path"] = __pathRow;

    var __hostRow = new Dictionary<string, object>();
    __hostRow["available"] = false;
    __hostRow["has_host"] = null;
    __hostRow["host_id"] = null;
    __hostRow["reason"] = "Railing.HasHost/HostId unavailable";
    try
    {
        bool __hasHost = __railing.HasHost;
        string __hostId = null;
        if (__hasHost)
        {
            ElementId __hostElementId = __railing.HostId;
            if (__hostElementId != null
                    && __hostElementId != ElementId.InvalidElementId)
                __hostId = __hostElementId.ToString();
        }
        __hostRow["available"] = true;
        __hostRow["has_host"] = __hasHost;
        __hostRow["host_id"] = __hostId;
        __hostRow["reason"] = null;
    }
    catch (Exception __error)
    {
        __hostRow["reason"] = "Railing host read failed: "
            + __skClassName(__error);
    }
    __railBlock["host"] = __hostRow;

    var __baseRow = new Dictionary<string, object>();
    __baseRow["available"] = false;
    __baseRow["level_id"] = null;
    __baseRow["reason"] = "railing base level unavailable";
    try
    {
        Parameter __baseParam = __railing.get_Parameter(
            BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM);
        if (__baseParam == null)
        {
            __baseRow["reason"] =
                "railing has no STAIRS_RAILING_BASE_LEVEL_PARAM";
        }
        else
        {
            ElementId __baseId = __baseParam.AsElementId();
            if (__baseId == null || __baseId == ElementId.InvalidElementId)
            {
                __baseRow["reason"] = "railing base level parameter is unset";
            }
            else
            {
                __baseRow["available"] = true;
                __baseRow["level_id"] = __baseId.ToString();
                __baseRow["reason"] = null;
            }
        }
    }
    catch (Exception __error)
    {
        __baseRow["reason"] = "railing base level read failed: "
            + __skClassName(__error);
    }
    __railBlock["base_level"] = __baseRow;

    __row["railing"] = __railBlock;
    return __row;
};

// §18.2 + M9: до этой волны здесь стояли ТРИ полномодельных прохода без
// единого бюджета, при таймауте моста 30 с и retries=0 — «работает на нашем
// здании, не работает на вашем». Теперь стадия страничная (pipeline режет
// L0-ids по _SIDE_BATCH) и кооперативно бюджетированная, ровно как
// curve/curtain: время проверяется перед каждым элементом и после него, а
// каждый запрошенный id обязан уйти строкой или квитанцией.
//
// Пустой __skRequestedIds означает «весь документ» (прямой вызов эмиттера вне
// конвейера). Бюджеты действуют и там; квитанция тогда называет то, что успел
// увидеть коллектор, — иначе о срезе не сказал бы никто.
var __skRequestedIds = new string[] { __SK_ELEMENT_IDS__ };
long __skElementBudgetMs = __SK_ELEMENT_BUDGET_MS__L;
long __skCallBudgetMs = __SK_CALL_BUDGET_MS__L;
long __skCallWatchT0 = DateTime.UtcNow.Ticks;
var __skRequestedSet = new HashSet<string>(__skRequestedIds);
bool __skAll = (__skRequestedIds.Length == 0);
var __skSeen = new HashSet<string>();
var __skFailures = new List<object>();
bool __skBudgetOut = false;
Action<string, string, string, object> __skFail =
    (__failedId, __reason, __typed, __elapsed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __failure["elapsed_ms"] = __elapsed;
    __skFailures.Add(__failure);
};
// true ⇒ элемент читаем; false ⇒ он либо не заказан, либо уже списан в
// квитанцию по бюджету. Одна точка решения на все три коллектора.
Func<string, bool> __skAccept = (__elementId) =>
{
    if (!__skAll && !__skRequestedSet.Contains(__elementId)) return false;
    __skSeen.Add(__elementId);
    if (__skBudgetOut
        || ((DateTime.UtcNow.Ticks - __skCallWatchT0) / TimeSpan.TicksPerMillisecond) >= __skCallBudgetMs)
    {
        __skBudgetOut = true;
        __skFail(__elementId, "call_budget_exhausted",
                 "call_budget_exhausted",
                 (object)((DateTime.UtcNow.Ticks - __skCallWatchT0) / TimeSpan.TicksPerMillisecond));
        return false;
    }
    return true;
};

var __rows = new List<object>();
foreach (Floor __floor in new FilteredElementCollector(__src)
         .OfCategory(BuiltInCategory.OST_Floors)
         .WhereElementIsNotElementType().OfType<Floor>()
         .OrderBy(__item => __IdValue(__item.Id)))
{
    string __floorId = __floor.Id.ToString();
    if (!__skAccept(__floorId)) continue;
    long __floorWatchT0 = DateTime.UtcNow.Ticks;
    var __floorRow = __ProfileRow(__floor, "OST_Floors");
    long __floorElapsed = ((DateTime.UtcNow.Ticks - __floorWatchT0) / TimeSpan.TicksPerMillisecond);
    if (__floorElapsed >= __skElementBudgetMs)
    {
        // Перерасход не выдаётся за прочитанное: строка выбрасывается, а
        // хвост документа получает свои квитанции через __skAccept.
        __skFail(__floorId, "time_budget_exceeded", "time_budget_exceeded",
                 (object)__floorElapsed);
        __skBudgetOut = true;
        continue;
    }
    __rows.Add(__floorRow);
}
foreach (RoofBase __roof in new FilteredElementCollector(__src)
         .OfCategory(BuiltInCategory.OST_Roofs)
         .WhereElementIsNotElementType().OfType<RoofBase>()
         .OrderBy(__item => __IdValue(__item.Id)))
{
    string __roofId = __roof.Id.ToString();
    if (!__skAccept(__roofId)) continue;
    long __roofWatchT0 = DateTime.UtcNow.Ticks;
    var __roofRow = __ProfileRow(__roof, "OST_Roofs");
    long __roofElapsed = ((DateTime.UtcNow.Ticks - __roofWatchT0) / TimeSpan.TicksPerMillisecond);
    if (__roofElapsed >= __skElementBudgetMs)
    {
        __skFail(__roofId, "time_budget_exceeded", "time_budget_exceeded",
                 (object)__roofElapsed);
        __skBudgetOut = true;
        continue;
    }
    __rows.Add(__roofRow);
}
foreach (Autodesk.Revit.DB.Architecture.Stairs __stairs
         in new FilteredElementCollector(__src)
         .OfCategory(BuiltInCategory.OST_Stairs)
         .WhereElementIsNotElementType()
         .OfType<Autodesk.Revit.DB.Architecture.Stairs>()
         .OrderBy(__item => __IdValue(__item.Id)))
{
    string __stairsId = __stairs.Id.ToString();
    if (!__skAccept(__stairsId)) continue;
    long __stairsWatchT0 = DateTime.UtcNow.Ticks;
    var __row = new Dictionary<string, object>();
    __row["element_id"] = __stairsId;
    __row["category"] = "OST_Stairs";
    __row["profile_available"] = false;
    __row["loops"] = new List<object>();
    __row["slopes"] = null;
    __row["reason"] =
        "stairs parent has no single reliable closed Sketch profile";
    var __runRows = new List<object>();
    try
    {
        foreach (ElementId __runId in __stairs.GetStairsRuns()
                 .OrderBy(__id => __IdValue(__id)))
        {
            var __runRow = new Dictionary<string, object>();
            __runRow["run_id"] = __runId.ToString();
            __runRow["path_available"] = false;
            __runRow["points_mm"] = new List<object>();
            __runRow["curve_kinds"] = new List<object>();
            __runRow["arc_midpoints_mm"] = new List<object>();
            __runRow["reason"] = "StairsRun path unavailable";
            try
            {
                var __run = __src.GetElement(__runId)
                    as Autodesk.Revit.DB.Architecture.StairsRun;
                if (__run == null)
                {
                    __runRow["reason"] = "stairs run element is missing";
                }
                else
                {
                    var __pathCurves = __run.GetStairsPath();
                    var __curves = new List<Curve>();
                    if (__pathCurves != null)
                        foreach (Curve __curve in __pathCurves)
                            __curves.Add(__curve);
                    var __path = __ReadChain(__curves, false);
                    if ((bool)__path["ok"])
                    {
                        __runRow["path_available"] = true;
                        __runRow["points_mm"] = __path["points_mm"];
                        __runRow["curve_kinds"] = __path["curve_kinds"];
                        __runRow["arc_midpoints_mm"] =
                            __path["arc_midpoints_mm"];
                        __runRow["reason"] = null;
                    }
                    else
                    {
                        __runRow["reason"] = __path["reason"];
                    }
                }
            }
            catch (Exception __error)
            {
                __runRow["reason"] = "StairsRun.GetStairsPath failed: "
                    + __skClassName(__error);
            }
            __runRows.Add(__runRow);
        }
    }
    catch (Exception __error)
    {
        __row["reason"] = "Stairs.GetStairsRuns failed: "
            + __skClassName(__error);
    }
    __row["stairs_run_paths"] = __runRows;
    long __stairsElapsed = ((DateTime.UtcNow.Ticks - __stairsWatchT0) / TimeSpan.TicksPerMillisecond);
    if (__stairsElapsed >= __skElementBudgetMs)
    {
        __skFail(__stairsId, "time_budget_exceeded", "time_budget_exceeded",
                 (object)__stairsElapsed);
        __skBudgetOut = true;
        continue;
    }
    __rows.Add(__row);
}
// Потолок дописан В КОНЕЦ, а не вставлен в середину: порядок коллекторов —
// часть замороженного формата возобновления. Собственной ветки чтения у него
// НЕТ и быть не должно: потолок — такой же эскизный элемент, как пол, и идёт
// тем же __DependentSketchLoops. Вторая ветка означала бы вторую правду о
// профиле, а её потом никто не сверит.
foreach (Ceiling __ceiling in new FilteredElementCollector(__src)
         .OfCategory(BuiltInCategory.OST_Ceilings)
         .WhereElementIsNotElementType().OfType<Ceiling>()
         .OrderBy(__item => __IdValue(__item.Id)))
{
    string __ceilingId = __ceiling.Id.ToString();
    if (!__skAccept(__ceilingId)) continue;
    long __ceilingWatchT0 = DateTime.UtcNow.Ticks;
    var __ceilingRow = __ProfileRow(__ceiling, "OST_Ceilings");
    long __ceilingElapsed = ((DateTime.UtcNow.Ticks - __ceilingWatchT0) / TimeSpan.TicksPerMillisecond);
    if (__ceilingElapsed >= __skElementBudgetMs)
    {
        __skFail(__ceilingId, "time_budget_exceeded", "time_budget_exceeded",
                 (object)__ceilingElapsed);
        __skBudgetOut = true;
        continue;
    }
    __rows.Add(__ceilingRow);
}
// Ограждения живут в ДВУХ категориях, и обе уже перечислены в таблице лифта
// (OST_StairsRailing и OST_Railings). Читать одну — значит терять другую
// молча на первом же здании, где проектировщик поставил балконное
// ограждение вместо лестничного.
foreach (Autodesk.Revit.DB.Architecture.Railing __railing
         in new FilteredElementCollector(__src)
         .OfCategory(BuiltInCategory.OST_StairsRailing)
         .WhereElementIsNotElementType()
         .OfType<Autodesk.Revit.DB.Architecture.Railing>()
         .OrderBy(__item => __IdValue(__item.Id)))
{
    string __railingId = __railing.Id.ToString();
    if (!__skAccept(__railingId)) continue;
    long __railingWatchT0 = DateTime.UtcNow.Ticks;
    var __railingRow = __RailingRow(__railing, "OST_StairsRailing");
    long __railingElapsed = ((DateTime.UtcNow.Ticks - __railingWatchT0) / TimeSpan.TicksPerMillisecond);
    if (__railingElapsed >= __skElementBudgetMs)
    {
        __skFail(__railingId, "time_budget_exceeded", "time_budget_exceeded",
                 (object)__railingElapsed);
        __skBudgetOut = true;
        continue;
    }
    __rows.Add(__railingRow);
}
foreach (Autodesk.Revit.DB.Architecture.Railing __balcony
         in new FilteredElementCollector(__src)
         .OfCategory(BuiltInCategory.OST_Railings)
         .WhereElementIsNotElementType()
         .OfType<Autodesk.Revit.DB.Architecture.Railing>()
         .OrderBy(__item => __IdValue(__item.Id)))
{
    string __balconyId = __balcony.Id.ToString();
    if (!__skAccept(__balconyId)) continue;
    long __balconyWatchT0 = DateTime.UtcNow.Ticks;
    var __balconyRow = __RailingRow(__balcony, "OST_Railings");
    long __balconyElapsed = ((DateTime.UtcNow.Ticks - __balconyWatchT0) / TimeSpan.TicksPerMillisecond);
    if (__balconyElapsed >= __skElementBudgetMs)
    {
        __skFail(__balconyId, "time_budget_exceeded", "time_budget_exceeded",
                 (object)__balconyElapsed);
        __skBudgetOut = true;
        continue;
    }
    __rows.Add(__balconyRow);
}
// Заказанный id, которого не нашёл ни один из коллекторов, — не молчание,
// а факт: элемент есть в L0, но эта стадия его не читает (или он исчез).
foreach (string __requestedId in __skRequestedIds)
{
    if (!__skSeen.Contains(__requestedId))
        __skFail(__requestedId, "element_unresolved", "element_unresolved",
                 null);
}
return new Dictionary<string, object> {
    {"schema_version", "kir-decompile-sketch-extract/1"},
    {"elements", __rows},
    {"failures", __skFailures}
};
""".strip()


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


def build_sketch_extract_cs(
    element_ids: Sequence[str | int] = (),
    *,
    element_budget_ms: int = 2_000,
    call_budget_ms: int = 20_000,
    link_title: str | None = None,
) -> str:
    """Return the deterministic read-only Revit Execute method body.

    ``element_ids`` — страница L0-идентификаторов полов/кровель/лестниц. Пустая
    последовательность означает «весь документ» и остаётся законной формой для
    прямого вызова вне конвейера; конвейер всегда передаёт страницу.

    Оба бюджета — кооперативные предохранители, а НЕ вытеснение (та же
    дисциплина, что у :func:`curve_extract.build_curve_extract_cs` и
    :func:`curtain_extract.build_curtain_extract_cs`). Один блокирующий вызов
    API всё ещё может перебрать свой бюджет, но его частичный результат
    отбрасывается, перерасход уходит типизированной квитанцией
    ``time_budget_exceeded`` / ``call_budget_exhausted``, и каждый оставшийся
    id всё равно оказывается посчитан.

    До этой волны стадия была единственной без бюджета: три полномодельных
    прохода в одном вызове при таймауте моста 30 с и ``retries=0`` (M9 аудита
    28.07).

    ШЕСТЬ КОЛЛЕКТОРОВ И ДВА ``GetElement`` В ОДНОМ ТЕЛЕ — и все восемь обязаны
    смотреть в ОДИН документ. Стадия читает эскиз через зависимые элементы
    (``GetDependentElements`` → ``GetElement``), и достаточно одного чтения по
    хозяину, чтобы профиль пола из связи оказался профилем чужого пола.

    ``link_title`` — читать не ХОЗЯИНА, а его СВЯЗЬ с таким ``Document.Title``.
    Источник один на ВСЁ тело: у документов разные пространства
    идентификаторов, поэтому id связи, спрошенный у хозяина, либо не находится
    (квитанция на ровном месте), либо находит ЧУЖОЙ элемент с тем же числом —
    и тогда стадия записывает чужую строку как свою, молча. Замер 30.07 на
    связанной электрике Snowdon дал оба исхода разом.
    """

    if isinstance(element_ids, (str, bytes)):
        raise ValueError("element_ids must be a sequence, not a string")
    normalized: list[str] = []
    for index, value in enumerate(element_ids):
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValueError(
                f"element_ids[{index}] must be a numeric string or integer")
        item = str(value)
        if re.fullmatch(r"-?[0-9]+", item) is None:
            raise ValueError(
                f"element_ids[{index}] must be a numeric Revit id")
        normalized.append(item)
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

    body = SKETCH_EXTRACT_CS.replace(
        "__SK_ELEMENT_IDS__",
        ", ".join(_csharp_string(value) for value in normalized),
        1,
    )
    body = body.replace("__SK_ELEMENT_BUDGET_MS__", str(element_budget_ms))
    body = body.replace("__SK_CALL_BUDGET_MS__", str(call_budget_ms))
    if "__SK_" in body:
        raise SketchExtractionError(
            "internal sketch emitter placeholder was not resolved")
    return source_binding_cs(link_title) + "\n" + body


# Descriptive aliases make the public boundary easy to discover without
# widening any frozen package ``__init__`` file.
build_profile_extract_cs = build_sketch_extract_cs
parse_sketch_profiles = extract_sketch_profiles


__all__ = [
    "CurveKind",
    "PROFILE_INDEX_SCHEMA_VERSION",
    "ProfileExtraction",
    "ProfileFailure",
    "ProfileIndexRecord",
    "ProfileLoop",
    "RailingPathRecord",
    "SKETCH_EXTRACT_CS",
    "SKETCH_EXTRACT_SCHEMA_VERSION",
    "SketchExtractionError",
    "SketchPayloadError",
    "StairsRunPathRecord",
    "TypedPath",
    "build_profile_extract_cs",
    "build_sketch_extract_cs",
    "extract_sketch_profiles",
    "parse_sketch_profiles",
]
