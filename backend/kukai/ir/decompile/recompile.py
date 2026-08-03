"""Tier-G geometry contract and Revit DirectShape C# recompiler.

Wave G owns this schema because the frozen L0 schema and the deliberately
narrow Wave-A2 geometry store contain location geometry only.  The contract
below is the hand-off boundary for the future full-geometry extractor and for
geometric round-trip verification:

* all model-space coordinates and radii are finite millimetres;
* angles and surface parameters are finite radians/native parameters;
* topology is explicit (one shared edge table, face loops of coedges);
* every exact B-Rep candidate carries a mandatory tessellated fallback;
* one immutable geometry definition may have any number of 4x4 transforms.

The dataclasses are frozen and deeply immutable (nested collections are
tuples).  ``from_dict`` methods are strict; malformed persisted geometry is a
typed refusal, never normalized into plausible-looking geometry.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence, TypeAlias


class GeometrySchemaError(ValueError):
    """A Tier-G geometry definition violates the frozen Wave-G contract."""


class GeometryTier(str, Enum):
    GB = "Gb"
    GM = "Gm"


class CurveType(str, Enum):
    LINE = "Line"
    ARC = "Arc"
    ELLIPSE = "Ellipse"
    NURBS = "NURBS"


class SurfaceType(str, Enum):
    PLANAR = "Planar"
    CYLINDRICAL = "Cylindrical"
    CONICAL = "Conical"
    REVOLVED = "Revolved"
    RULED = "Ruled"
    NURBS = "NURBS"


Vec3: TypeAlias = tuple[float, float, float]
Matrix4: TypeAlias = tuple[
    float, float, float, float,
    float, float, float, float,
    float, float, float, float,
    float, float, float, float,
]

IDENTITY_TRANSFORM: Matrix4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)

_CATEGORY_RE = re.compile(r"OST_[A-Za-z0-9_]+\Z")
_ORTHO_TOL = 1.0e-8
_AFFINE_TOL = 1.0e-10
_DEGENERATE_AREA2_SQ_MM4 = 1.0e-18


def _finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GeometrySchemaError(f"{field_name} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise GeometrySchemaError(f"{field_name} must be a finite number")
    return number


def _integer(value: Any, field_name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GeometrySchemaError(
            f"{field_name} must be an integer >= {minimum}")
    return value


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise GeometrySchemaError(f"{field_name} must be a boolean")
    return value


def _nonempty(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise GeometrySchemaError(f"{field_name} must be a non-empty string")
    return value


def _tuple(value: Any, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, tuple):
        raise GeometrySchemaError(
            f"{field_name} must be a tuple in the immutable Python form")
    return value


def _vec3(value: Any, field_name: str) -> Vec3:
    items = _tuple(value, field_name)
    if len(items) != 3:
        raise GeometrySchemaError(
            f"{field_name} must contain exactly three finite numbers")
    return (
        _finite(items[0], f"{field_name}[0]"),
        _finite(items[1], f"{field_name}[1]"),
        _finite(items[2], f"{field_name}[2]"),
    )


def _vec3_from_json(value: Any, field_name: str) -> Vec3:
    if (not isinstance(value, Sequence) or isinstance(value, (str, bytes))
            or len(value) != 3):
        raise GeometrySchemaError(
            f"{field_name} must contain exactly three finite numbers")
    return (
        _finite(value[0], f"{field_name}[0]"),
        _finite(value[1], f"{field_name}[1]"),
        _finite(value[2], f"{field_name}[2]"),
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm_sq(value: Vec3) -> float:
    return _dot(value, value)


def _validate_unit_pair(x_axis: Vec3, y_axis: Vec3, field_name: str) -> None:
    if abs(_norm_sq(x_axis) - 1.0) > _ORTHO_TOL:
        raise GeometrySchemaError(f"{field_name}.x_axis must be unit length")
    if abs(_norm_sq(y_axis) - 1.0) > _ORTHO_TOL:
        raise GeometrySchemaError(f"{field_name}.y_axis must be unit length")
    if abs(_dot(x_axis, y_axis)) > _ORTHO_TOL:
        raise GeometrySchemaError(f"{field_name} axes must be orthogonal")


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise GeometrySchemaError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise GeometrySchemaError(f"{field_name} keys must be strings")
    return dict(value)


def _exact_fields(
    value: Any,
    expected: set[str],
    field_name: str,
) -> dict[str, Any]:
    row = _mapping(value, field_name)
    missing = sorted(expected - set(row))
    extra = sorted(set(row) - expected)
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(missing))
        if extra:
            detail.append("unexpected " + ", ".join(extra))
        raise GeometrySchemaError(f"{field_name} fields: {'; '.join(detail)}")
    return row


def _json_tuple(value: Any, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise GeometrySchemaError(f"{field_name} must be an array")
    return tuple(value)


def _float_tuple_from_json(value: Any, field_name: str) -> tuple[float, ...]:
    values = _json_tuple(value, field_name)
    return tuple(
        _finite(item, f"{field_name}[{index}]")
        for index, item in enumerate(values)
    )


def _validate_clamped_knots(
    knots: tuple[float, ...],
    degree: int,
    control_count: int,
    field_name: str,
) -> None:
    if len(knots) != degree + control_count + 1:
        raise GeometrySchemaError(
            f"{field_name} length must equal degree + control_count + 1")
    if any(knots[index] > knots[index + 1]
           for index in range(len(knots) - 1)):
        raise GeometrySchemaError(f"{field_name} must be non-decreasing")
    if knots[0] == knots[-1]:
        raise GeometrySchemaError(f"{field_name} must span a non-zero domain")
    if any(knots[index] != knots[0] for index in range(degree + 1)):
        raise GeometrySchemaError(
            f"{field_name} must be clamped at the start")
    if any(knots[-1 - index] != knots[-1]
           for index in range(degree + 1)):
        raise GeometrySchemaError(f"{field_name} must be clamped at the end")


@dataclass(frozen=True, slots=True)
class FrameDefinition:
    """Right-handed orthonormal local frame; origin is in millimetres."""

    origin_mm: Vec3
    basis_x: Vec3
    basis_y: Vec3
    basis_z: Vec3

    def __post_init__(self) -> None:
        origin = _vec3(self.origin_mm, "FrameDefinition.origin_mm")
        x_axis = _vec3(self.basis_x, "FrameDefinition.basis_x")
        y_axis = _vec3(self.basis_y, "FrameDefinition.basis_y")
        z_axis = _vec3(self.basis_z, "FrameDefinition.basis_z")
        _validate_unit_pair(x_axis, y_axis, "FrameDefinition")
        if abs(_norm_sq(z_axis) - 1.0) > _ORTHO_TOL:
            raise GeometrySchemaError(
                "FrameDefinition.basis_z must be unit length")
        if abs(_dot(x_axis, z_axis)) > _ORTHO_TOL \
                or abs(_dot(y_axis, z_axis)) > _ORTHO_TOL:
            raise GeometrySchemaError(
                "FrameDefinition basis vectors must be orthogonal")
        if _dot(_cross(x_axis, y_axis), z_axis) < 1.0 - _ORTHO_TOL:
            raise GeometrySchemaError(
                "FrameDefinition must be right-handed")
        # Validate even when values are integer-typed; the immutable tuple is
        # retained byte-for-byte so direct construction stays deterministic.
        _ = origin

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin_mm": list(self.origin_mm),
            "basis_x": list(self.basis_x),
            "basis_y": list(self.basis_y),
            "basis_z": list(self.basis_z),
        }

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "frame") \
            -> "FrameDefinition":
        row = _exact_fields(value, {
            "origin_mm", "basis_x", "basis_y", "basis_z",
        }, field_name)
        return cls(
            origin_mm=_vec3_from_json(
                row["origin_mm"], f"{field_name}.origin_mm"),
            basis_x=_vec3_from_json(
                row["basis_x"], f"{field_name}.basis_x"),
            basis_y=_vec3_from_json(
                row["basis_y"], f"{field_name}.basis_y"),
            basis_z=_vec3_from_json(
                row["basis_z"], f"{field_name}.basis_z"),
        )


@dataclass(frozen=True, slots=True)
class UVBounds:
    """A surface-envelope rectangle in the surface's native parameters."""

    min_u: float
    min_v: float
    max_u: float
    max_v: float

    def __post_init__(self) -> None:
        min_u = _finite(self.min_u, "UVBounds.min_u")
        min_v = _finite(self.min_v, "UVBounds.min_v")
        max_u = _finite(self.max_u, "UVBounds.max_u")
        max_v = _finite(self.max_v, "UVBounds.max_v")
        if min_u >= max_u or min_v >= max_v:
            raise GeometrySchemaError(
                "UVBounds minima must be strictly below maxima")

    def to_list(self) -> list[float]:
        return [self.min_u, self.min_v, self.max_u, self.max_v]

    @classmethod
    def from_json(cls, value: Any, field_name: str = "uv_bounds") \
            -> "UVBounds":
        values = _float_tuple_from_json(value, field_name)
        if len(values) != 4:
            raise GeometrySchemaError(
                f"{field_name} must contain exactly four numbers")
        return cls(values[0], values[1], values[2], values[3])


@dataclass(frozen=True, slots=True)
class LineCurve:
    start_mm: Vec3
    end_mm: Vec3

    def __post_init__(self) -> None:
        start = _vec3(self.start_mm, "LineCurve.start_mm")
        end = _vec3(self.end_mm, "LineCurve.end_mm")
        if _norm_sq(_sub(end, start)) <= 0.0:
            raise GeometrySchemaError("LineCurve endpoints must be distinct")

    @property
    def curve_type(self) -> CurveType:
        return CurveType.LINE

    def to_dict(self) -> dict[str, Any]:
        return {
            "curve_type": self.curve_type.value,
            "start_mm": list(self.start_mm),
            "end_mm": list(self.end_mm),
        }


@dataclass(frozen=True, slots=True)
class ArcCurve:
    center_mm: Vec3
    radius_mm: float
    x_axis: Vec3
    y_axis: Vec3
    start_angle_rad: float
    end_angle_rad: float

    def __post_init__(self) -> None:
        _vec3(self.center_mm, "ArcCurve.center_mm")
        x_axis = _vec3(self.x_axis, "ArcCurve.x_axis")
        y_axis = _vec3(self.y_axis, "ArcCurve.y_axis")
        _validate_unit_pair(x_axis, y_axis, "ArcCurve")
        radius = _finite(self.radius_mm, "ArcCurve.radius_mm")
        start = _finite(self.start_angle_rad, "ArcCurve.start_angle_rad")
        end = _finite(self.end_angle_rad, "ArcCurve.end_angle_rad")
        if radius <= 0.0:
            raise GeometrySchemaError("ArcCurve.radius_mm must be positive")
        span = end - start
        if span <= 0.0 or span > math.tau + _ORTHO_TOL:
            raise GeometrySchemaError(
                "ArcCurve angular span must be in (0, 2*pi]")

    @property
    def curve_type(self) -> CurveType:
        return CurveType.ARC

    def to_dict(self) -> dict[str, Any]:
        return {
            "curve_type": self.curve_type.value,
            "center_mm": list(self.center_mm),
            "radius_mm": self.radius_mm,
            "x_axis": list(self.x_axis),
            "y_axis": list(self.y_axis),
            "start_angle_rad": self.start_angle_rad,
            "end_angle_rad": self.end_angle_rad,
        }


@dataclass(frozen=True, slots=True)
class EllipseCurve:
    center_mm: Vec3
    radius_x_mm: float
    radius_y_mm: float
    x_axis: Vec3
    y_axis: Vec3
    start_angle_rad: float
    end_angle_rad: float

    def __post_init__(self) -> None:
        _vec3(self.center_mm, "EllipseCurve.center_mm")
        x_axis = _vec3(self.x_axis, "EllipseCurve.x_axis")
        y_axis = _vec3(self.y_axis, "EllipseCurve.y_axis")
        _validate_unit_pair(x_axis, y_axis, "EllipseCurve")
        radius_x = _finite(self.radius_x_mm, "EllipseCurve.radius_x_mm")
        radius_y = _finite(self.radius_y_mm, "EllipseCurve.radius_y_mm")
        start = _finite(
            self.start_angle_rad, "EllipseCurve.start_angle_rad")
        end = _finite(self.end_angle_rad, "EllipseCurve.end_angle_rad")
        if radius_y <= 0.0 or radius_x < radius_y:
            raise GeometrySchemaError(
                "EllipseCurve requires radius_x_mm >= radius_y_mm > 0")
        span = end - start
        if span <= 0.0 or span > math.tau + _ORTHO_TOL:
            raise GeometrySchemaError(
                "EllipseCurve angular span must be in (0, 2*pi]")

    @property
    def curve_type(self) -> CurveType:
        return CurveType.ELLIPSE

    def to_dict(self) -> dict[str, Any]:
        return {
            "curve_type": self.curve_type.value,
            "center_mm": list(self.center_mm),
            "radius_x_mm": self.radius_x_mm,
            "radius_y_mm": self.radius_y_mm,
            "x_axis": list(self.x_axis),
            "y_axis": list(self.y_axis),
            "start_angle_rad": self.start_angle_rad,
            "end_angle_rad": self.end_angle_rad,
        }


@dataclass(frozen=True, slots=True)
class NurbsCurve:
    degree: int
    knots: tuple[float, ...]
    control_points_mm: tuple[Vec3, ...]
    weights: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        degree = _integer(self.degree, "NurbsCurve.degree", minimum=1)
        knots = _tuple(self.knots, "NurbsCurve.knots")
        points = _tuple(
            self.control_points_mm, "NurbsCurve.control_points_mm")
        if len(points) <= degree:
            raise GeometrySchemaError(
                "NurbsCurve control-point count must exceed degree")
        parsed_knots = tuple(
            _finite(value, f"NurbsCurve.knots[{index}]")
            for index, value in enumerate(knots))
        for index, point in enumerate(points):
            _vec3(point, f"NurbsCurve.control_points_mm[{index}]")
        _validate_clamped_knots(
            parsed_knots, degree, len(points), "NurbsCurve.knots")
        if self.weights is not None:
            weights = _tuple(self.weights, "NurbsCurve.weights")
            if len(weights) != len(points):
                raise GeometrySchemaError(
                    "NurbsCurve weights must match control points")
            if any(_finite(weight, f"NurbsCurve.weights[{index}]") <= 0.0
                   for index, weight in enumerate(weights)):
                raise GeometrySchemaError(
                    "NurbsCurve weights must all be positive")

    @property
    def curve_type(self) -> CurveType:
        return CurveType.NURBS

    def to_dict(self) -> dict[str, Any]:
        return {
            "curve_type": self.curve_type.value,
            "degree": self.degree,
            "knots": list(self.knots),
            "control_points_mm": [
                list(point) for point in self.control_points_mm],
            "weights": (
                list(self.weights) if self.weights is not None else None),
        }


CurveDefinition: TypeAlias = LineCurve | ArcCurve | EllipseCurve | NurbsCurve
_CURVE_CLASSES = (LineCurve, ArcCurve, EllipseCurve, NurbsCurve)


def curve_from_dict(value: Any, field_name: str = "curve") \
        -> CurveDefinition:
    row = _mapping(value, field_name)
    curve_type = row.get("curve_type")
    if curve_type == CurveType.LINE.value:
        row = _exact_fields(row, {"curve_type", "start_mm", "end_mm"},
                            field_name)
        return LineCurve(
            _vec3_from_json(row["start_mm"], f"{field_name}.start_mm"),
            _vec3_from_json(row["end_mm"], f"{field_name}.end_mm"),
        )
    if curve_type == CurveType.ARC.value:
        row = _exact_fields(row, {
            "curve_type", "center_mm", "radius_mm", "x_axis", "y_axis",
            "start_angle_rad", "end_angle_rad",
        }, field_name)
        return ArcCurve(
            center_mm=_vec3_from_json(
                row["center_mm"], f"{field_name}.center_mm"),
            radius_mm=_finite(row["radius_mm"], f"{field_name}.radius_mm"),
            x_axis=_vec3_from_json(
                row["x_axis"], f"{field_name}.x_axis"),
            y_axis=_vec3_from_json(
                row["y_axis"], f"{field_name}.y_axis"),
            start_angle_rad=_finite(
                row["start_angle_rad"], f"{field_name}.start_angle_rad"),
            end_angle_rad=_finite(
                row["end_angle_rad"], f"{field_name}.end_angle_rad"),
        )
    if curve_type == CurveType.ELLIPSE.value:
        row = _exact_fields(row, {
            "curve_type", "center_mm", "radius_x_mm", "radius_y_mm",
            "x_axis", "y_axis", "start_angle_rad", "end_angle_rad",
        }, field_name)
        return EllipseCurve(
            center_mm=_vec3_from_json(
                row["center_mm"], f"{field_name}.center_mm"),
            radius_x_mm=_finite(
                row["radius_x_mm"], f"{field_name}.radius_x_mm"),
            radius_y_mm=_finite(
                row["radius_y_mm"], f"{field_name}.radius_y_mm"),
            x_axis=_vec3_from_json(
                row["x_axis"], f"{field_name}.x_axis"),
            y_axis=_vec3_from_json(
                row["y_axis"], f"{field_name}.y_axis"),
            start_angle_rad=_finite(
                row["start_angle_rad"], f"{field_name}.start_angle_rad"),
            end_angle_rad=_finite(
                row["end_angle_rad"], f"{field_name}.end_angle_rad"),
        )
    if curve_type == CurveType.NURBS.value:
        row = _exact_fields(row, {
            "curve_type", "degree", "knots", "control_points_mm", "weights",
        }, field_name)
        points = _json_tuple(
            row["control_points_mm"], f"{field_name}.control_points_mm")
        weights = row["weights"]
        return NurbsCurve(
            degree=_integer(row["degree"], f"{field_name}.degree", minimum=1),
            knots=_float_tuple_from_json(
                row["knots"], f"{field_name}.knots"),
            control_points_mm=tuple(
                _vec3_from_json(point,
                                f"{field_name}.control_points_mm[{index}]")
                for index, point in enumerate(points)),
            weights=(
                None if weights is None else _float_tuple_from_json(
                    weights, f"{field_name}.weights")),
        )
    raise GeometrySchemaError(
        f"{field_name}.curve_type is unsupported: {curve_type!r}")


@dataclass(frozen=True, slots=True)
class PlanarSurface:
    frame: FrameDefinition

    def __post_init__(self) -> None:
        if not isinstance(self.frame, FrameDefinition):
            raise GeometrySchemaError(
                "PlanarSurface.frame must be a FrameDefinition")

    @property
    def surface_type(self) -> SurfaceType:
        return SurfaceType.PLANAR

    def to_dict(self) -> dict[str, Any]:
        return {"surface_type": self.surface_type.value,
                "frame": self.frame.to_dict()}


@dataclass(frozen=True, slots=True)
class CylindricalSurface:
    frame: FrameDefinition
    radius_mm: float

    def __post_init__(self) -> None:
        if not isinstance(self.frame, FrameDefinition):
            raise GeometrySchemaError(
                "CylindricalSurface.frame must be a FrameDefinition")
        if _finite(self.radius_mm, "CylindricalSurface.radius_mm") <= 0.0:
            raise GeometrySchemaError(
                "CylindricalSurface.radius_mm must be positive")

    @property
    def surface_type(self) -> SurfaceType:
        return SurfaceType.CYLINDRICAL

    def to_dict(self) -> dict[str, Any]:
        return {"surface_type": self.surface_type.value,
                "frame": self.frame.to_dict(), "radius_mm": self.radius_mm}


@dataclass(frozen=True, slots=True)
class ConicalSurface:
    frame: FrameDefinition
    half_angle_rad: float

    def __post_init__(self) -> None:
        if not isinstance(self.frame, FrameDefinition):
            raise GeometrySchemaError(
                "ConicalSurface.frame must be a FrameDefinition")
        angle = _finite(
            self.half_angle_rad, "ConicalSurface.half_angle_rad")
        if angle <= 0.0 or angle >= math.pi / 2.0:
            raise GeometrySchemaError(
                "ConicalSurface.half_angle_rad must be in (0, pi/2)")

    @property
    def surface_type(self) -> SurfaceType:
        return SurfaceType.CONICAL

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface_type": self.surface_type.value,
            "frame": self.frame.to_dict(),
            "half_angle_rad": self.half_angle_rad,
        }


@dataclass(frozen=True, slots=True)
class RevolvedSurface:
    frame: FrameDefinition
    profile: CurveDefinition

    def __post_init__(self) -> None:
        if not isinstance(self.frame, FrameDefinition):
            raise GeometrySchemaError(
                "RevolvedSurface.frame must be a FrameDefinition")
        if not isinstance(self.profile, _CURVE_CLASSES):
            raise GeometrySchemaError(
                "RevolvedSurface.profile must be a curve definition")

    @property
    def surface_type(self) -> SurfaceType:
        return SurfaceType.REVOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface_type": self.surface_type.value,
            "frame": self.frame.to_dict(),
            "profile": self.profile.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RuledSurface:
    profile_a: CurveDefinition
    profile_b: CurveDefinition | None = None
    point_b_mm: Vec3 | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile_a, _CURVE_CLASSES):
            raise GeometrySchemaError(
                "RuledSurface.profile_a must be a curve definition")
        if (self.profile_b is None) == (self.point_b_mm is None):
            raise GeometrySchemaError(
                "RuledSurface requires exactly one of profile_b or point_b_mm")
        if self.profile_b is not None \
                and not isinstance(self.profile_b, _CURVE_CLASSES):
            raise GeometrySchemaError(
                "RuledSurface.profile_b must be a curve definition")
        if self.point_b_mm is not None:
            _vec3(self.point_b_mm, "RuledSurface.point_b_mm")

    @property
    def surface_type(self) -> SurfaceType:
        return SurfaceType.RULED

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface_type": self.surface_type.value,
            "profile_a": self.profile_a.to_dict(),
            "profile_b": (
                self.profile_b.to_dict()
                if self.profile_b is not None else None),
            "point_b_mm": (
                list(self.point_b_mm)
                if self.point_b_mm is not None else None),
        }


@dataclass(frozen=True, slots=True)
class NurbsSurface:
    degree_u: int
    degree_v: int
    control_count_u: int
    control_count_v: int
    knots_u: tuple[float, ...]
    knots_v: tuple[float, ...]
    control_points_mm: tuple[Vec3, ...]
    weights: tuple[float, ...] | None = None
    reverse_orientation: bool = False

    def __post_init__(self) -> None:
        degree_u = _integer(
            self.degree_u, "NurbsSurface.degree_u", minimum=1)
        degree_v = _integer(
            self.degree_v, "NurbsSurface.degree_v", minimum=1)
        count_u = _integer(
            self.control_count_u, "NurbsSurface.control_count_u", minimum=2)
        count_v = _integer(
            self.control_count_v, "NurbsSurface.control_count_v", minimum=2)
        if count_u <= degree_u or count_v <= degree_v:
            raise GeometrySchemaError(
                "NurbsSurface control counts must exceed their degrees")
        knots_u = tuple(
            _finite(value, f"NurbsSurface.knots_u[{index}]")
            for index, value in enumerate(
                _tuple(self.knots_u, "NurbsSurface.knots_u")))
        knots_v = tuple(
            _finite(value, f"NurbsSurface.knots_v[{index}]")
            for index, value in enumerate(
                _tuple(self.knots_v, "NurbsSurface.knots_v")))
        _validate_clamped_knots(
            knots_u, degree_u, count_u, "NurbsSurface.knots_u")
        _validate_clamped_knots(
            knots_v, degree_v, count_v, "NurbsSurface.knots_v")
        points = _tuple(
            self.control_points_mm, "NurbsSurface.control_points_mm")
        if len(points) != count_u * count_v:
            raise GeometrySchemaError(
                "NurbsSurface control points must equal count_u * count_v")
        for index, point in enumerate(points):
            _vec3(point, f"NurbsSurface.control_points_mm[{index}]")
        if self.weights is not None:
            weights = _tuple(self.weights, "NurbsSurface.weights")
            if len(weights) != len(points):
                raise GeometrySchemaError(
                    "NurbsSurface weights must match control points")
            if any(_finite(weight, f"NurbsSurface.weights[{index}]") <= 0.0
                   for index, weight in enumerate(weights)):
                raise GeometrySchemaError(
                    "NurbsSurface weights must all be positive")
        _boolean(
            self.reverse_orientation, "NurbsSurface.reverse_orientation")

    @property
    def surface_type(self) -> SurfaceType:
        return SurfaceType.NURBS

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface_type": self.surface_type.value,
            "degree_u": self.degree_u,
            "degree_v": self.degree_v,
            "control_count_u": self.control_count_u,
            "control_count_v": self.control_count_v,
            "knots_u": list(self.knots_u),
            "knots_v": list(self.knots_v),
            "control_points_mm": [
                list(point) for point in self.control_points_mm],
            "weights": (
                list(self.weights) if self.weights is not None else None),
            "reverse_orientation": self.reverse_orientation,
        }


SurfaceDefinition: TypeAlias = (
    PlanarSurface | CylindricalSurface | ConicalSurface |
    RevolvedSurface | RuledSurface | NurbsSurface
)
_SURFACE_CLASSES = (
    PlanarSurface, CylindricalSurface, ConicalSurface,
    RevolvedSurface, RuledSurface, NurbsSurface,
)


def surface_from_dict(value: Any, field_name: str = "surface") \
        -> SurfaceDefinition:
    row = _mapping(value, field_name)
    surface_type = row.get("surface_type")
    if surface_type == SurfaceType.PLANAR.value:
        row = _exact_fields(row, {"surface_type", "frame"}, field_name)
        return PlanarSurface(FrameDefinition.from_dict(
            row["frame"], f"{field_name}.frame"))
    if surface_type == SurfaceType.CYLINDRICAL.value:
        row = _exact_fields(
            row, {"surface_type", "frame", "radius_mm"}, field_name)
        return CylindricalSurface(
            frame=FrameDefinition.from_dict(
                row["frame"], f"{field_name}.frame"),
            radius_mm=_finite(
                row["radius_mm"], f"{field_name}.radius_mm"),
        )
    if surface_type == SurfaceType.CONICAL.value:
        row = _exact_fields(
            row, {"surface_type", "frame", "half_angle_rad"}, field_name)
        return ConicalSurface(
            frame=FrameDefinition.from_dict(
                row["frame"], f"{field_name}.frame"),
            half_angle_rad=_finite(
                row["half_angle_rad"], f"{field_name}.half_angle_rad"),
        )
    if surface_type == SurfaceType.REVOLVED.value:
        row = _exact_fields(
            row, {"surface_type", "frame", "profile"}, field_name)
        return RevolvedSurface(
            frame=FrameDefinition.from_dict(
                row["frame"], f"{field_name}.frame"),
            profile=curve_from_dict(
                row["profile"], f"{field_name}.profile"),
        )
    if surface_type == SurfaceType.RULED.value:
        row = _exact_fields(row, {
            "surface_type", "profile_a", "profile_b", "point_b_mm",
        }, field_name)
        return RuledSurface(
            profile_a=curve_from_dict(
                row["profile_a"], f"{field_name}.profile_a"),
            profile_b=(
                curve_from_dict(row["profile_b"], f"{field_name}.profile_b")
                if row["profile_b"] is not None else None),
            point_b_mm=(
                _vec3_from_json(
                    row["point_b_mm"], f"{field_name}.point_b_mm")
                if row["point_b_mm"] is not None else None),
        )
    if surface_type in (SurfaceType.NURBS.value, "BSpline"):
        row = _exact_fields(row, {
            "surface_type", "degree_u", "degree_v", "control_count_u",
            "control_count_v", "knots_u", "knots_v", "control_points_mm",
            "weights", "reverse_orientation",
        }, field_name)
        points = _json_tuple(
            row["control_points_mm"], f"{field_name}.control_points_mm")
        return NurbsSurface(
            degree_u=_integer(
                row["degree_u"], f"{field_name}.degree_u", minimum=1),
            degree_v=_integer(
                row["degree_v"], f"{field_name}.degree_v", minimum=1),
            control_count_u=_integer(
                row["control_count_u"],
                f"{field_name}.control_count_u", minimum=2),
            control_count_v=_integer(
                row["control_count_v"],
                f"{field_name}.control_count_v", minimum=2),
            knots_u=_float_tuple_from_json(
                row["knots_u"], f"{field_name}.knots_u"),
            knots_v=_float_tuple_from_json(
                row["knots_v"], f"{field_name}.knots_v"),
            control_points_mm=tuple(
                _vec3_from_json(point,
                                f"{field_name}.control_points_mm[{index}]")
                for index, point in enumerate(points)),
            weights=(
                None if row["weights"] is None else _float_tuple_from_json(
                    row["weights"], f"{field_name}.weights")),
            reverse_orientation=_boolean(
                row["reverse_orientation"],
                f"{field_name}.reverse_orientation"),
        )
    raise GeometrySchemaError(
        f"{field_name}.surface_type is unsupported: {surface_type!r}")


@dataclass(frozen=True, slots=True)
class GmMesh:
    vertices_mm: tuple[Vec3, ...]
    triangles: tuple[tuple[int, int, int], ...]

    def __post_init__(self) -> None:
        vertices = _tuple(self.vertices_mm, "GmMesh.vertices_mm")
        triangles = _tuple(self.triangles, "GmMesh.triangles")
        if len(vertices) < 3:
            raise GeometrySchemaError("GmMesh requires at least three vertices")
        if not triangles:
            raise GeometrySchemaError("GmMesh requires at least one triangle")
        for index, vertex in enumerate(vertices):
            _vec3(vertex, f"GmMesh.vertices_mm[{index}]")
        for index, triangle in enumerate(triangles):
            parts = _tuple(triangle, f"GmMesh.triangles[{index}]")
            if len(parts) != 3:
                raise GeometrySchemaError(
                    f"GmMesh.triangles[{index}] must contain three indices")
            parsed = tuple(
                _integer(part, f"GmMesh.triangles[{index}][{part_index}]")
                for part_index, part in enumerate(parts))
            if len(set(parsed)) != 3:
                raise GeometrySchemaError(
                    f"GmMesh.triangles[{index}] repeats a vertex")
            if any(part >= len(vertices) for part in parsed):
                raise GeometrySchemaError(
                    f"GmMesh.triangles[{index}] index is out of range")
            a = _vec3(vertices[parsed[0]], "mesh vertex")
            b = _vec3(vertices[parsed[1]], "mesh vertex")
            c = _vec3(vertices[parsed[2]], "mesh vertex")
            if _norm_sq(_cross(_sub(b, a), _sub(c, a))) \
                    <= _DEGENERATE_AREA2_SQ_MM4:
                raise GeometrySchemaError(
                    f"GmMesh.triangles[{index}] is degenerate")

    @property
    def tier(self) -> GeometryTier:
        return GeometryTier.GM

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "vertices_mm": [list(vertex) for vertex in self.vertices_mm],
            "triangles": [list(triangle) for triangle in self.triangles],
        }

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "mesh") -> "GmMesh":
        row = _exact_fields(
            value, {"tier", "vertices_mm", "triangles"}, field_name)
        if row["tier"] != GeometryTier.GM.value:
            raise GeometrySchemaError(f"{field_name}.tier must be 'Gm'")
        vertices = _json_tuple(row["vertices_mm"], f"{field_name}.vertices_mm")
        triangles = _json_tuple(row["triangles"], f"{field_name}.triangles")
        parsed_triangles = []
        for index, triangle in enumerate(triangles):
            values = _json_tuple(
                triangle, f"{field_name}.triangles[{index}]")
            if len(values) != 3:
                raise GeometrySchemaError(
                    f"{field_name}.triangles[{index}] must contain three indices")
            parsed_triangles.append(tuple(
                _integer(value,
                         f"{field_name}.triangles[{index}][{part_index}]")
                for part_index, value in enumerate(values)))
        return cls(
            vertices_mm=tuple(
                _vec3_from_json(vertex,
                                f"{field_name}.vertices_mm[{index}]")
                for index, vertex in enumerate(vertices)),
            triangles=tuple(parsed_triangles),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class GbEdge:
    edge_id: str
    curve: CurveDefinition

    def __post_init__(self) -> None:
        _nonempty(self.edge_id, "GbEdge.edge_id")
        if not isinstance(self.curve, _CURVE_CLASSES):
            raise GeometrySchemaError("GbEdge.curve must be a curve definition")

    def to_dict(self) -> dict[str, Any]:
        return {"edge_id": self.edge_id, "curve": self.curve.to_dict()}

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "edge") -> "GbEdge":
        row = _exact_fields(value, {"edge_id", "curve"}, field_name)
        return cls(
            edge_id=_nonempty(row["edge_id"], f"{field_name}.edge_id"),
            curve=curve_from_dict(row["curve"], f"{field_name}.curve"),
        )


@dataclass(frozen=True, slots=True)
class GbCoEdge:
    edge_id: str
    reversed: bool

    def __post_init__(self) -> None:
        _nonempty(self.edge_id, "GbCoEdge.edge_id")
        _boolean(self.reversed, "GbCoEdge.reversed")

    def to_dict(self) -> dict[str, Any]:
        return {"edge_id": self.edge_id, "reversed": self.reversed}

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "coedge") -> "GbCoEdge":
        row = _exact_fields(value, {"edge_id", "reversed"}, field_name)
        return cls(
            edge_id=_nonempty(row["edge_id"], f"{field_name}.edge_id"),
            reversed=_boolean(row["reversed"], f"{field_name}.reversed"),
        )


@dataclass(frozen=True, slots=True)
class GbLoop:
    coedges: tuple[GbCoEdge, ...]

    def __post_init__(self) -> None:
        coedges = _tuple(self.coedges, "GbLoop.coedges")
        if not coedges:
            raise GeometrySchemaError("GbLoop requires at least one coedge")
        if any(not isinstance(coedge, GbCoEdge) for coedge in coedges):
            raise GeometrySchemaError(
                "GbLoop.coedges must contain GbCoEdge values")

    def to_dict(self) -> dict[str, Any]:
        return {"coedges": [coedge.to_dict() for coedge in self.coedges]}

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "loop") -> "GbLoop":
        row = _exact_fields(value, {"coedges"}, field_name)
        coedges = _json_tuple(row["coedges"], f"{field_name}.coedges")
        return cls(tuple(
            GbCoEdge.from_dict(
                coedge, f"{field_name}.coedges[{index}]")
            for index, coedge in enumerate(coedges)))


@dataclass(frozen=True, slots=True)
class GbFace:
    surface: SurfaceDefinition
    reversed: bool
    loops: tuple[GbLoop, ...]
    uv_bounds: UVBounds | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.surface, _SURFACE_CLASSES):
            raise GeometrySchemaError(
                "GbFace.surface must be a surface definition")
        _boolean(self.reversed, "GbFace.reversed")
        loops = _tuple(self.loops, "GbFace.loops")
        if not loops:
            raise GeometrySchemaError("GbFace requires at least one edge loop")
        if any(not isinstance(loop, GbLoop) for loop in loops):
            raise GeometrySchemaError("GbFace.loops must contain GbLoop values")
        if self.uv_bounds is not None \
                and not isinstance(self.uv_bounds, UVBounds):
            raise GeometrySchemaError(
                "GbFace.uv_bounds must be UVBounds or null")
        if isinstance(self.surface, NurbsSurface) and self.uv_bounds is None:
            raise GeometrySchemaError(
                "NURBS GbFace requires an explicit native-parameter uv_bounds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface.to_dict(),
            "reversed": self.reversed,
            "loops": [loop.to_dict() for loop in self.loops],
            "uv_bounds": (
                self.uv_bounds.to_list()
                if self.uv_bounds is not None else None),
        }

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "face") -> "GbFace":
        row = _exact_fields(
            value, {"surface", "reversed", "loops", "uv_bounds"},
            field_name)
        loops = _json_tuple(row["loops"], f"{field_name}.loops")
        return cls(
            surface=surface_from_dict(
                row["surface"], f"{field_name}.surface"),
            reversed=_boolean(row["reversed"], f"{field_name}.reversed"),
            loops=tuple(
                GbLoop.from_dict(loop, f"{field_name}.loops[{index}]")
                for index, loop in enumerate(loops)),
            uv_bounds=(
                None if row["uv_bounds"] is None else UVBounds.from_json(
                    row["uv_bounds"], f"{field_name}.uv_bounds")),
        )


@dataclass(frozen=True, slots=True)
class GbSolid:
    edges: tuple[GbEdge, ...]
    faces: tuple[GbFace, ...]
    fallback_mesh: GmMesh
    brep_candidate_valid: bool = True

    def __post_init__(self) -> None:
        edges = _tuple(self.edges, "GbSolid.edges")
        faces = _tuple(self.faces, "GbSolid.faces")
        if not edges:
            raise GeometrySchemaError("GbSolid requires at least one edge")
        if not faces:
            raise GeometrySchemaError("GbSolid requires at least one face")
        if any(not isinstance(edge, GbEdge) for edge in edges):
            raise GeometrySchemaError("GbSolid.edges must contain GbEdge values")
        if any(not isinstance(face, GbFace) for face in faces):
            raise GeometrySchemaError("GbSolid.faces must contain GbFace values")
        if not isinstance(self.fallback_mesh, GmMesh):
            raise GeometrySchemaError(
                "GbSolid.fallback_mesh must be a validated GmMesh")
        _boolean(
            self.brep_candidate_valid, "GbSolid.brep_candidate_valid")
        ids = [edge.edge_id for edge in edges]
        if len(set(ids)) != len(ids):
            raise GeometrySchemaError("GbSolid edge ids must be unique")
        references: dict[str, list[bool]] = {edge_id: [] for edge_id in ids}
        for face_index, face in enumerate(faces):
            for loop_index, loop in enumerate(face.loops):
                for coedge_index, coedge in enumerate(loop.coedges):
                    if coedge.edge_id not in references:
                        raise GeometrySchemaError(
                            "GbSolid face loop references unknown edge "
                            f"{coedge.edge_id!r} at face {face_index}, "
                            f"loop {loop_index}, coedge {coedge_index}")
                    references[coedge.edge_id].append(coedge.reversed)
        for edge_id, orientations in references.items():
            if len(orientations) != 2:
                raise GeometrySchemaError(
                    f"GbSolid edge {edge_id!r} must have exactly two coedges")
            if orientations[0] == orientations[1]:
                raise GeometrySchemaError(
                    f"GbSolid edge {edge_id!r} coedges must have opposite orientation")

    @property
    def tier(self) -> GeometryTier:
        return GeometryTier.GB

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier.value,
            "edges": [edge.to_dict() for edge in self.edges],
            "faces": [face.to_dict() for face in self.faces],
            "fallback_mesh": self.fallback_mesh.to_dict(),
            "brep_candidate_valid": self.brep_candidate_valid,
        }

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "solid") -> "GbSolid":
        row = _exact_fields(value, {
            "tier", "edges", "faces", "fallback_mesh",
            "brep_candidate_valid",
        }, field_name)
        if row["tier"] != GeometryTier.GB.value:
            raise GeometrySchemaError(f"{field_name}.tier must be 'Gb'")
        edges = _json_tuple(row["edges"], f"{field_name}.edges")
        faces = _json_tuple(row["faces"], f"{field_name}.faces")
        return cls(
            edges=tuple(
                GbEdge.from_dict(edge, f"{field_name}.edges[{index}]")
                for index, edge in enumerate(edges)),
            faces=tuple(
                GbFace.from_dict(face, f"{field_name}.faces[{index}]")
                for index, face in enumerate(faces)),
            fallback_mesh=GmMesh.from_dict(
                row["fallback_mesh"], f"{field_name}.fallback_mesh"),
            brep_candidate_valid=_boolean(
                row["brep_candidate_valid"],
                f"{field_name}.brep_candidate_valid"),
        )


GeometryDefinition: TypeAlias = GbSolid | GmMesh


def validate_transform(value: Any, field_name: str = "transform") -> Matrix4:
    """Validate the frozen row-major affine transform.

    Layout is ``[m00,m01,m02,tx, m10,...,ty, m20,...,tz, 0,0,0,1]``.
    Translation is in millimetres; the 3x3 basis is unitless.  Any invertible
    affine basis is admitted.  Revit B-Rep transforms may reject a
    non-conformal basis at runtime, in which case emitted code uses Gm.
    """

    values = _tuple(value, field_name)
    if len(values) != 16:
        raise GeometrySchemaError(
            f"{field_name} must contain exactly 16 numbers")
    matrix = tuple(
        _finite(item, f"{field_name}[{index}]")
        for index, item in enumerate(values))
    if (abs(matrix[12]) > _AFFINE_TOL
            or abs(matrix[13]) > _AFFINE_TOL
            or abs(matrix[14]) > _AFFINE_TOL
            or abs(matrix[15] - 1.0) > _AFFINE_TOL):
        raise GeometrySchemaError(
            f"{field_name} last row must be [0, 0, 0, 1]")
    a, b, c = matrix[0], matrix[1], matrix[2]
    d, e, f = matrix[4], matrix[5], matrix[6]
    g, h, i = matrix[8], matrix[9], matrix[10]
    determinant = (
        a * (e * i - f * h)
        - b * (d * i - f * g)
        + c * (d * h - e * g)
    )
    if abs(determinant) <= _AFFINE_TOL:
        raise GeometrySchemaError(f"{field_name} basis must be invertible")
    return matrix  # type: ignore[return-value]


def _transform_from_json(value: Any, field_name: str) -> Matrix4:
    values = _float_tuple_from_json(value, field_name)
    return validate_transform(values, field_name)


@dataclass(frozen=True, slots=True)
class GeometryNode:
    """One geometry definition, one source category, and N instances."""

    node_id: str
    category: str
    geometry: GeometryDefinition
    transforms: tuple[Matrix4, ...] = (IDENTITY_TRANSFORM,)

    def __post_init__(self) -> None:
        _nonempty(self.node_id, "GeometryNode.node_id")
        category = _nonempty(self.category, "GeometryNode.category")
        if _CATEGORY_RE.fullmatch(category) is None:
            raise GeometrySchemaError(
                "GeometryNode.category must be a BuiltInCategory OST_* name")
        if not isinstance(self.geometry, (GbSolid, GmMesh)):
            raise GeometrySchemaError(
                "GeometryNode.geometry must be GbSolid or GmMesh")
        transforms = _tuple(self.transforms, "GeometryNode.transforms")
        if not transforms:
            raise GeometrySchemaError(
                "GeometryNode requires at least one transform")
        for index, transform in enumerate(transforms):
            validate_transform(transform, f"GeometryNode.transforms[{index}]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "category": self.category,
            "geometry": self.geometry.to_dict(),
            "transforms": [list(transform) for transform in self.transforms],
        }

    @classmethod
    def from_dict(cls, value: Any, field_name: str = "geometry_node") \
            -> "GeometryNode":
        row = _exact_fields(
            value, {"node_id", "category", "geometry", "transforms"},
            field_name)
        geometry_row = _mapping(row["geometry"], f"{field_name}.geometry")
        tier = geometry_row.get("tier")
        if tier == GeometryTier.GB.value:
            geometry: GeometryDefinition = GbSolid.from_dict(
                geometry_row, f"{field_name}.geometry")
        elif tier == GeometryTier.GM.value:
            geometry = GmMesh.from_dict(
                geometry_row, f"{field_name}.geometry")
        else:
            raise GeometrySchemaError(
                f"{field_name}.geometry.tier is unsupported: {tier!r}")
        transforms = _json_tuple(
            row["transforms"], f"{field_name}.transforms")
        return cls(
            node_id=_nonempty(row["node_id"], f"{field_name}.node_id"),
            category=_nonempty(row["category"], f"{field_name}.category"),
            geometry=geometry,
            transforms=tuple(
                _transform_from_json(
                    transform, f"{field_name}.transforms[{index}]")
                for index, transform in enumerate(transforms)),
        )


# ── Deterministic C# emission ───────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EmittedNodeStatus:
    """Static path selected by the emitter for one node.

    A valid Gb candidate still has a guarded runtime Gm path.  Its *actual*
    tier is therefore returned by the emitted C# per instance; this static
    status records that Gb is the first path selected at emission time.
    """

    node_id: str
    requested_tier: GeometryTier
    chosen_tier: GeometryTier
    degraded_to_gm: bool
    instance_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "requested_tier": self.requested_tier.value,
            "chosen_tier": self.chosen_tier.value,
            "degraded_to_gm": self.degraded_to_gm,
            "instance_count": self.instance_count,
        }


@dataclass(frozen=True, slots=True)
class EmittedCSharp:
    """A complete Execute-body plus its deterministic static tier decision."""

    csharp: str
    chosen_tier: GeometryTier | None
    degraded_to_gm: bool
    nodes: tuple[EmittedNodeStatus, ...]
    direct_shape_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "csharp": self.csharp,
            "chosen_tier": (
                self.chosen_tier.value
                if self.chosen_tier is not None else "mixed"),
            "degraded_to_gm": self.degraded_to_gm,
            "nodes": [node.to_dict() for node in self.nodes],
            "direct_shape_count": self.direct_shape_count,
        }


_CS_PREAMBLE = r"""
// KIR DECOMPILE Wave G — generated Tier-G reconstruction body.
// XYZ/radius inputs are millimetres; UnitUtils owns conversion to Revit units.
Func<double, double> __U = (__mm) => UnitUtils.ConvertToInternalUnits(__mm, UnitTypeId.Millimeters);
Func<double, double, double, XYZ> __P = (__x, __y, __z) => new XYZ(__U(__x), __U(__y), __U(__z));
Func<double, double, double, XYZ> __V = (__x, __y, __z) => new XYZ(__x, __y, __z);
Func<string, string> __Clip = (__message) =>
{
    if (__message == null) return "unknown Revit geometry error";
    return __message.Length <= 300 ? __message : __message.Substring(0, 300);
};
var __results = new Dictionary<string, object>();
var __nodeResults = new List<object>();
int __createdTotal = 0;
int __failedTotal = 0;
Transaction __txn = null;
""".strip("\n")


def _cs_string(value: str) -> str:
    """Injection-safe deterministic C# string literal."""

    return cs_string_literal(value)


def _cs_number(value: float) -> str:
    number = _finite(value, "C# numeric literal")
    literal = format(number, ".17g")
    if "." not in literal and "e" not in literal.lower():
        literal += ".0"
    return literal


def _cs_bool(value: bool) -> str:
    return "true" if value else "false"


def _indent_cs(value: str, spaces: int = 4) -> str:
    prefix = " " * spaces
    return "\n".join(
        prefix + line if line else line for line in value.splitlines())


def _xyz_mm_cs(point: Vec3) -> str:
    return "__P({0}, {1}, {2})".format(*(_cs_number(v) for v in point))


def _vector_cs(vector: Vec3) -> str:
    return "__V({0}, {1}, {2})".format(*(_cs_number(v) for v in vector))


def _frame_cs(frame: FrameDefinition) -> str:
    return "new Frame({0}, {1}, {2}, {3})".format(
        _xyz_mm_cs(frame.origin_mm),
        _vector_cs(frame.basis_x),
        _vector_cs(frame.basis_y),
        _vector_cs(frame.basis_z),
    )


def _double_list_cs(values: tuple[float, ...]) -> str:
    return "new List<double> {{ {0} }}".format(
        ", ".join(_cs_number(value) for value in values))


def _point_list_cs(values: tuple[Vec3, ...]) -> str:
    return "new List<XYZ> {{ {0} }}".format(
        ", ".join(_xyz_mm_cs(value) for value in values))


def _curve_cs(curve: CurveDefinition) -> str:
    if isinstance(curve, LineCurve):
        return "Line.CreateBound({0}, {1})".format(
            _xyz_mm_cs(curve.start_mm), _xyz_mm_cs(curve.end_mm))
    if isinstance(curve, ArcCurve):
        return "Arc.Create({0}, __U({1}), {2}, {3}, {4}, {5})".format(
            _xyz_mm_cs(curve.center_mm),
            _cs_number(curve.radius_mm),
            _cs_number(curve.start_angle_rad),
            _cs_number(curve.end_angle_rad),
            _vector_cs(curve.x_axis),
            _vector_cs(curve.y_axis),
        )
    if isinstance(curve, EllipseCurve):
        return (
            "Ellipse.CreateCurve({0}, __U({1}), __U({2}), {3}, {4}, {5}, {6})"
        ).format(
            _xyz_mm_cs(curve.center_mm),
            _cs_number(curve.radius_x_mm),
            _cs_number(curve.radius_y_mm),
            _vector_cs(curve.x_axis),
            _vector_cs(curve.y_axis),
            _cs_number(curve.start_angle_rad),
            _cs_number(curve.end_angle_rad),
        )
    if isinstance(curve, NurbsCurve):
        arguments = [
            str(curve.degree),
            _double_list_cs(curve.knots),
            _point_list_cs(curve.control_points_mm),
        ]
        if curve.weights is not None:
            arguments.append(_double_list_cs(curve.weights))
        return "NurbSpline.CreateCurve({0})".format(", ".join(arguments))
    raise AssertionError(f"unsupported curve: {type(curve).__name__}")


def _uv_bounds_cs(bounds: UVBounds | None) -> str:
    if bounds is None:
        return "null"
    return "new BoundingBoxUV({0}, {1}, {2}, {3})".format(
        _cs_number(bounds.min_u),
        _cs_number(bounds.min_v),
        _cs_number(bounds.max_u),
        _cs_number(bounds.max_v),
    )


def _surface_geometry_cs(face: GbFace) -> str:
    surface = face.surface
    envelope = _uv_bounds_cs(face.uv_bounds)
    if isinstance(surface, PlanarSurface):
        value = f"Plane.Create({_frame_cs(surface.frame)})"
    elif isinstance(surface, CylindricalSurface):
        value = (
            f"CylindricalSurface.Create({_frame_cs(surface.frame)}, "
            f"__U({_cs_number(surface.radius_mm)}))"
        )
    elif isinstance(surface, ConicalSurface):
        value = (
            f"ConicalSurface.Create({_frame_cs(surface.frame)}, "
            f"{_cs_number(surface.half_angle_rad)})"
        )
    elif isinstance(surface, RevolvedSurface):
        value = (
            f"RevolvedSurface.Create({_frame_cs(surface.frame)}, "
            f"{_curve_cs(surface.profile)})"
        )
    elif isinstance(surface, RuledSurface):
        second = (
            _curve_cs(surface.profile_b)
            if surface.profile_b is not None
            else _xyz_mm_cs(surface.point_b_mm)  # type: ignore[arg-type]
        )
        value = f"RuledSurface.Create({_curve_cs(surface.profile_a)}, {second})"
    elif isinstance(surface, NurbsSurface):
        args = [
            str(surface.degree_u),
            str(surface.degree_v),
            _double_list_cs(surface.knots_u),
            _double_list_cs(surface.knots_v),
            _point_list_cs(surface.control_points_mm),
        ]
        if surface.weights is not None:
            args.append(_double_list_cs(surface.weights))
        args.extend((_cs_bool(surface.reverse_orientation), envelope))
        return "BRepBuilderSurfaceGeometry.CreateNURBSSurface({0})".format(
            ", ".join(args))
    else:  # pragma: no cover - schema union makes this unreachable
        raise AssertionError(f"unsupported surface: {type(surface).__name__}")
    return f"BRepBuilderSurfaceGeometry.Create({value}, {envelope})"


def _emit_transform_cs(name: str, matrix: Matrix4) -> str:
    # Frozen contract is row-major. Revit's BasisX/Y/Z are matrix columns.
    return (
        f"Transform {name} = new Transform(Transform.Identity);\n"
        f"{name}.BasisX = __V({_cs_number(matrix[0])}, "
        f"{_cs_number(matrix[4])}, {_cs_number(matrix[8])});\n"
        f"{name}.BasisY = __V({_cs_number(matrix[1])}, "
        f"{_cs_number(matrix[5])}, {_cs_number(matrix[9])});\n"
        f"{name}.BasisZ = __V({_cs_number(matrix[2])}, "
        f"{_cs_number(matrix[6])}, {_cs_number(matrix[10])});\n"
        f"{name}.Origin = __P({_cs_number(matrix[3])}, "
        f"{_cs_number(matrix[7])}, {_cs_number(matrix[11])});"
    )


def _emit_mesh_definition(mesh: GmMesh, prefix: str) -> str:
    vertices = ",\n".join(
        "    " + _xyz_mm_cs(vertex) for vertex in mesh.vertices_mm)
    triangles = ",\n".join(
        "    { " + ", ".join(str(index) for index in triangle) + " }"
        for triangle in mesh.triangles)
    return (
        f"var {prefix}_meshVertices = new XYZ[]\n{{\n{vertices}\n}};\n"
        f"var {prefix}_meshTriangles = new int[,]\n{{\n{triangles}\n}};"
    )


def _emit_brep_definition(solid: GbSolid, prefix: str) -> str:
    """Emit one guarded base-solid build. Every exception stays local."""

    if not solid.brep_candidate_valid:
        return (
            f"Solid {prefix}_baseSolid = null;\n"
            f"bool {prefix}_gbReady = false;\n"
            f"string {prefix}_gbError = "
            '"brep_candidate_valid=false";'
        )

    lines = [
        f"Solid {prefix}_baseSolid = null;",
        f"bool {prefix}_gbReady = false;",
        f"string {prefix}_gbError = null;",
        "try",
        "{",
        f"    var {prefix}_brep = new BRepBuilder(BRepType.Solid);",
        f"    if (!{prefix}_brep.CanAddGeometry())",
        f'        {prefix}_gbError = "BRepBuilder cannot accept geometry";',
        f"    if ({prefix}_gbError == null)",
        "    {",
    ]
    edge_vars: dict[str, str] = {}
    for edge_index, edge in enumerate(solid.edges):
        edge_var = f"{prefix}_edge_{edge_index}"
        edge_vars[edge.edge_id] = edge_var
        lines.append(
            f"        var {edge_var} = {prefix}_brep.AddEdge("
            f"BRepBuilderEdgeGeometry.Create({_curve_cs(edge.curve)}));")
    for face_index, face in enumerate(solid.faces):
        face_var = f"{prefix}_face_{face_index}"
        lines.append(
            f"        var {face_var} = {prefix}_brep.AddFace("
            f"{_surface_geometry_cs(face)}, {_cs_bool(face.reversed)});")
        for loop_index, loop in enumerate(face.loops):
            loop_var = f"{prefix}_loop_{face_index}_{loop_index}"
            lines.append(
                f"        var {loop_var} = {prefix}_brep.AddLoop({face_var});")
            for coedge in loop.coedges:
                lines.append(
                    f"        {prefix}_brep.AddCoEdge({loop_var}, "
                    f"{edge_vars[coedge.edge_id]}, {_cs_bool(coedge.reversed)});")
            lines.append(f"        {prefix}_brep.FinishLoop({loop_var});")
        lines.append(f"        {prefix}_brep.FinishFace({face_var});")
    lines.extend((
        f"        var {prefix}_finish = {prefix}_brep.Finish();",
        f"        if ({prefix}_finish != BRepBuilderOutcome.Success)",
        f"            {prefix}_gbError = \"BRepBuilder.Finish: \" + "
        f"{prefix}_finish.ToString();",
        f"        else if (!{prefix}_brep.IsResultAvailable())",
        f'            {prefix}_gbError = "BRepBuilder result unavailable";',
        "        else",
        "        {",
        f"            {prefix}_baseSolid = {prefix}_brep.GetResult();",
        f"            if ({prefix}_baseSolid == null)",
        f'                {prefix}_gbError = "BRepBuilder returned null Solid";',
        "            else",
        f"                {prefix}_gbReady = true;",
        "        }",
        "    }",
        "}",
        f"catch (Exception {prefix}_gbEx)",
        "{",
        f"    {prefix}_gbError = __Clip({prefix}_gbEx.Message);",
        f"    {prefix}_gbReady = false;",
        "}",
    ))
    return "\n".join(lines)


def _emit_category_cs(node: GeometryNode, prefix: str) -> str:
    category_literal = _cs_string(node.category)
    return (
        f"bool {prefix}_categoryReady = false;\n"
        f"string {prefix}_categoryError = null;\n"
        f"ElementId {prefix}_categoryId = null;\n"
        f"try\n"
        f"{{\n"
        f"    BuiltInCategory {prefix}_bic;\n"
        f"    if (!Enum.TryParse<BuiltInCategory>({category_literal}, false, "
        f"out {prefix}_bic))\n"
        f"        {prefix}_categoryError = \"unknown BuiltInCategory: \" + "
        f"{category_literal};\n"
        f"    else\n"
        f"    {{\n"
        f"        {prefix}_categoryId = new ElementId({prefix}_bic);\n"
        f"        if (!DirectShape.IsValidCategoryId({prefix}_categoryId, doc))\n"
        f"            {prefix}_categoryError = \"category is invalid for "
        f"DirectShape: \" + {category_literal};\n"
        f"        else\n"
        f"            {prefix}_categoryReady = true;\n"
        f"    }}\n"
        f"}}\n"
        f"catch (Exception {prefix}_categoryEx)\n"
        f"{{\n"
        f"    {prefix}_categoryError = __Clip({prefix}_categoryEx.Message);\n"
        f"}}"
    )


def _emit_brep_attempt_cs(
    node: GeometryNode,
    prefix: str,
    instance_prefix: str,
) -> str:
    application_data = _cs_string(
        f"{node.node_id}:{instance_prefix.rsplit('_', 1)[-1]}")
    return (
        f"SubTransaction {instance_prefix}_gbSub = null;\n"
        f"try\n"
        f"{{\n"
        f"    {instance_prefix}_gbSub = new SubTransaction(doc);\n"
        f"    var {instance_prefix}_gbStart = {instance_prefix}_gbSub.Start();\n"
        f"    if ({instance_prefix}_gbStart != TransactionStatus.Started)\n"
        f"        {instance_prefix}_attemptError = \"Gb subtransaction start: \" "
        f"+ {instance_prefix}_gbStart.ToString();\n"
        f"    else\n"
        f"    {{\n"
        f"        var {instance_prefix}_solid = SolidUtils.CreateTransformed("
        f"{prefix}_baseSolid, {instance_prefix}_xf);\n"
        f"        if ({instance_prefix}_solid == null)\n"
        f"            {instance_prefix}_attemptError = \"Solid transform "
        f"returned null\";\n"
        f"        else\n"
        f"        {{\n"
        f"            var {instance_prefix}_shape = new List<GeometryObject>();\n"
        f"            {instance_prefix}_shape.Add({instance_prefix}_solid);\n"
        f"            var {instance_prefix}_ds = DirectShape.CreateElement(doc, "
        f"{prefix}_categoryId);\n"
        f"            if ({instance_prefix}_ds == null)\n"
        f"                {instance_prefix}_attemptError = \"DirectShape.CreateElement "
        f"returned null\";\n"
        f"            else\n"
        f"            {{\n"
        f"                {instance_prefix}_ds.SetShape({instance_prefix}_shape);\n"
        f"                try {{ {instance_prefix}_ds.ApplicationId = "
        f"\"KUKAI.RECOMPILE\"; {instance_prefix}_ds.ApplicationDataId = "
        f"{application_data}; }} catch {{ }}\n"
        f"                var {instance_prefix}_gbCommit = "
        f"{instance_prefix}_gbSub.Commit();\n"
        f"                if ({instance_prefix}_gbCommit == "
        f"TransactionStatus.Committed)\n"
        f"                {{\n"
        f"                    {instance_prefix}_created = true;\n"
        f"                    {instance_prefix}_chosenTier = \"Gb\";\n"
        f"                    {instance_prefix}_directShapeId = "
        f"{instance_prefix}_ds.Id.ToString();\n"
        f"                }}\n"
        f"                else\n"
        f"                    {instance_prefix}_attemptError = "
        f"\"Gb subtransaction commit: \" + "
        f"{instance_prefix}_gbCommit.ToString();\n"
        f"            }}\n"
        f"        }}\n"
        f"    }}\n"
        f"}}\n"
        f"catch (Exception {instance_prefix}_gbPlaceEx)\n"
        f"{{\n"
        f"    {instance_prefix}_attemptError = "
        f"__Clip({instance_prefix}_gbPlaceEx.Message);\n"
        f"}}\n"
        f"finally\n"
        f"{{\n"
        f"    try {{ if ({instance_prefix}_gbSub != null && "
        f"{instance_prefix}_gbSub.HasStarted() && "
        f"!{instance_prefix}_gbSub.HasEnded()) "
        f"{instance_prefix}_gbSub.RollBack(); }} catch {{ }}\n"
        f"    try {{ if ({instance_prefix}_gbSub != null) "
        f"{instance_prefix}_gbSub.Dispose(); }} catch {{ }}\n"
        f"}}"
    )


def _emit_mesh_attempt_cs(
    node: GeometryNode,
    prefix: str,
    instance_prefix: str,
) -> str:
    application_data = _cs_string(
        f"{node.node_id}:{instance_prefix.rsplit('_', 1)[-1]}")
    return (
        f"SubTransaction {instance_prefix}_gmSub = null;\n"
        f"try\n"
        f"{{\n"
        f"    {instance_prefix}_gmSub = new SubTransaction(doc);\n"
        f"    var {instance_prefix}_gmStart = {instance_prefix}_gmSub.Start();\n"
        f"    if ({instance_prefix}_gmStart != TransactionStatus.Started)\n"
        f"        {instance_prefix}_meshError = \"Gm subtransaction start: \" "
        f"+ {instance_prefix}_gmStart.ToString();\n"
        f"    else\n"
        f"    {{\n"
        f"        var {instance_prefix}_tsb = new TessellatedShapeBuilder();\n"
        f"        {instance_prefix}_tsb.OpenConnectedFaceSet(false);\n"
        f"        for (int {instance_prefix}_ti = 0; {instance_prefix}_ti < "
        f"{prefix}_meshTriangles.GetLength(0); {instance_prefix}_ti++)\n"
        f"        {{\n"
        f"            var {instance_prefix}_corners = new List<XYZ>();\n"
        f"            for (int {instance_prefix}_ci = 0; "
        f"{instance_prefix}_ci < 3; {instance_prefix}_ci++)\n"
        f"            {{\n"
        f"                int {instance_prefix}_vi = {prefix}_meshTriangles["
        f"{instance_prefix}_ti, {instance_prefix}_ci];\n"
        f"                {instance_prefix}_corners.Add("
        f"{instance_prefix}_xf.OfPoint("
        f"{prefix}_meshVertices[{instance_prefix}_vi]));\n"
        f"            }}\n"
        f"            var {instance_prefix}_face = new TessellatedFace("
        f"{instance_prefix}_corners, ElementId.InvalidElementId);\n"
        f"            if (!{instance_prefix}_tsb.DoesFaceHaveEnoughLoopsAndVertices("
        f"{instance_prefix}_face))\n"
        f"                {instance_prefix}_meshError = \"Gm face rejected at "
        f"triangle \" + {instance_prefix}_ti.ToString();\n"
        f"            else\n"
        f"                {instance_prefix}_tsb.AddFace({instance_prefix}_face);\n"
        f"            if ({instance_prefix}_meshError != null) break;\n"
        f"        }}\n"
        f"        if ({instance_prefix}_meshError == null)\n"
        f"        {{\n"
        f"            {instance_prefix}_tsb.CloseConnectedFaceSet();\n"
        f"            {instance_prefix}_tsb.Target = "
        f"TessellatedShapeBuilderTarget.AnyGeometry;\n"
        f"            {instance_prefix}_tsb.Fallback = "
        f"TessellatedShapeBuilderFallback.Mesh;\n"
        f"            {instance_prefix}_tsb.Build();\n"
        f"            var {instance_prefix}_built = "
        f"{instance_prefix}_tsb.GetBuildResult().GetGeometricalObjects();\n"
        f"            if ({instance_prefix}_built == null || "
        f"{instance_prefix}_built.Count == 0)\n"
        f"                {instance_prefix}_meshError = "
        f"\"TessellatedShapeBuilder produced no geometry\";\n"
        f"            else\n"
        f"            {{\n"
        f"                var {instance_prefix}_ds = DirectShape.CreateElement(doc, "
        f"{prefix}_categoryId);\n"
        f"                if ({instance_prefix}_ds == null)\n"
        f"                    {instance_prefix}_meshError = "
        f"\"DirectShape.CreateElement returned null\";\n"
        f"                else\n"
        f"                {{\n"
        f"                    {instance_prefix}_ds.SetShape({instance_prefix}_built);\n"
        f"                    try {{ {instance_prefix}_ds.ApplicationId = "
        f"\"KUKAI.RECOMPILE\"; {instance_prefix}_ds.ApplicationDataId = "
        f"{application_data}; }} catch {{ }}\n"
        f"                    var {instance_prefix}_gmCommit = "
        f"{instance_prefix}_gmSub.Commit();\n"
        f"                    if ({instance_prefix}_gmCommit == "
        f"TransactionStatus.Committed)\n"
        f"                    {{\n"
        f"                        {instance_prefix}_created = true;\n"
        f"                        {instance_prefix}_chosenTier = \"Gm\";\n"
        f"                        {instance_prefix}_directShapeId = "
        f"{instance_prefix}_ds.Id.ToString();\n"
        f"                    }}\n"
        f"                    else\n"
        f"                        {instance_prefix}_meshError = "
        f"\"Gm subtransaction commit: \" + "
        f"{instance_prefix}_gmCommit.ToString();\n"
        f"                }}\n"
        f"            }}\n"
        f"        }}\n"
        f"    }}\n"
        f"}}\n"
        f"catch (Exception {instance_prefix}_gmEx)\n"
        f"{{\n"
        f"    {instance_prefix}_meshError = __Clip({instance_prefix}_gmEx.Message);\n"
        f"}}\n"
        f"finally\n"
        f"{{\n"
        f"    try {{ if ({instance_prefix}_gmSub != null && "
        f"{instance_prefix}_gmSub.HasStarted() && "
        f"!{instance_prefix}_gmSub.HasEnded()) "
        f"{instance_prefix}_gmSub.RollBack(); }} catch {{ }}\n"
        f"    try {{ if ({instance_prefix}_gmSub != null) "
        f"{instance_prefix}_gmSub.Dispose(); }} catch {{ }}\n"
        f"}}"
    )


def _emit_instance_cs(
    node: GeometryNode,
    node_index: int,
    instance_index: int,
) -> str:
    prefix = f"__g{node_index}"
    instance_prefix = f"{prefix}_i{instance_index}"
    requested_gb = isinstance(node.geometry, GbSolid)
    statically_degraded = (
        requested_gb and not node.geometry.brep_candidate_valid)
    lines = [
        "{",
        f"    var {instance_prefix}_result = "
        "new Dictionary<string, object>();",
        f'    {instance_prefix}_result["instance_index"] = {instance_index};',
        f'    {instance_prefix}_result["requested_tier"] = '
        f'"{"Gb" if requested_gb else "Gm"}";',
        f"    bool {instance_prefix}_created = false;",
        f"    bool {instance_prefix}_degraded = "
        f"{_cs_bool(statically_degraded)};",
        f"    string {instance_prefix}_chosenTier = null;",
        f"    string {instance_prefix}_directShapeId = null;",
        f"    string {instance_prefix}_attemptError = null;",
        f"    string {instance_prefix}_meshError = null;",
        f"    string {instance_prefix}_degradationReason = null;",
        _indent_cs(_emit_transform_cs(
            f"{instance_prefix}_xf", node.transforms[instance_index]), 4),
        f"    if (!{prefix}_categoryReady)",
        f"        {instance_prefix}_meshError = {prefix}_categoryError;",
        "    else",
        "    {",
    ]
    if requested_gb:
        lines.extend((
            f"        if ({prefix}_gbReady)",
            "        {",
            _indent_cs(_emit_brep_attempt_cs(
                node, prefix, instance_prefix), 12),
            "        }",
            "        else",
            f"            {instance_prefix}_attemptError = {prefix}_gbError;",
            f"        if (!{instance_prefix}_created)",
            "        {",
            f"            {instance_prefix}_degraded = true;",
            f"            {instance_prefix}_degradationReason = "
            f"{instance_prefix}_attemptError ?? \"Gb path unavailable\";",
            _indent_cs(_emit_mesh_attempt_cs(
                node, prefix, instance_prefix), 12),
            "        }",
        ))
    else:
        lines.append(_indent_cs(_emit_mesh_attempt_cs(
            node, prefix, instance_prefix), 8))
    lines.extend((
        "    }",
        f"    if ({instance_prefix}_created)",
        "    {",
        f"        {instance_prefix}_result[\"status\"] = \"created\";",
        f"        {instance_prefix}_result[\"chosen_tier\"] = "
        f"{instance_prefix}_chosenTier;",
        f"        {instance_prefix}_result[\"direct_shape_id\"] = "
        f"{instance_prefix}_directShapeId;",
        f"        {prefix}_created++;",
        "        __createdTotal++;",
        f"        if ({instance_prefix}_chosenTier == \"Gb\") {prefix}_gbCount++;",
        f"        if ({instance_prefix}_chosenTier == \"Gm\") {prefix}_gmCount++;",
        "    }",
        "    else",
        "    {",
        f"        {instance_prefix}_result[\"status\"] = \"failed\";",
        f"        string {instance_prefix}_finalError = "
        f"{instance_prefix}_meshError ?? {instance_prefix}_attemptError "
        f"?? \"unknown reconstruction failure\";",
        f"        {instance_prefix}_result[\"error\"] = "
        f"__Clip({instance_prefix}_finalError);",
        f"        {prefix}_failed++;",
        "        __failedTotal++;",
        "    }",
        f"    {instance_prefix}_result[\"degraded_to_gm\"] = "
        f"{instance_prefix}_degraded;",
        f"    if ({instance_prefix}_degradationReason != null)",
        f"        {instance_prefix}_result[\"degradation_reason\"] = "
        f"__Clip({instance_prefix}_degradationReason);",
        f"    {prefix}_degraded = {prefix}_degraded || "
        f"{instance_prefix}_degraded;",
        f"    {prefix}_instances.Add({instance_prefix}_result);",
        "}",
    ))
    return "\n".join(lines)


def _emit_node_cs(node: GeometryNode, node_index: int) -> str:
    prefix = f"__g{node_index}"
    geometry = node.geometry
    mesh = geometry.fallback_mesh if isinstance(geometry, GbSolid) else geometry
    requested = "Gb" if isinstance(geometry, GbSolid) else "Gm"
    initial_degraded = (
        isinstance(geometry, GbSolid) and not geometry.brep_candidate_valid)
    parts = [
        f"// geometry node {node_index}: {_cs_string(node.node_id)}",
        "{",
        f"    var {prefix}_node = new Dictionary<string, object>();",
        f"    var {prefix}_instances = new List<object>();",
        f"    int {prefix}_created = 0;",
        f"    int {prefix}_failed = 0;",
        f"    int {prefix}_gbCount = 0;",
        f"    int {prefix}_gmCount = 0;",
        f"    bool {prefix}_degraded = {_cs_bool(initial_degraded)};",
        _indent_cs(_emit_category_cs(node, prefix), 4),
        _indent_cs(_emit_mesh_definition(mesh, prefix), 4),
    ]
    if isinstance(geometry, GbSolid):
        parts.append(_indent_cs(_emit_brep_definition(geometry, prefix), 4))
    for instance_index in range(len(node.transforms)):
        parts.append(_indent_cs(
            _emit_instance_cs(node, node_index, instance_index), 4))
    parts.extend((
        f"    {prefix}_node[\"node_id\"] = {_cs_string(node.node_id)};",
        f"    {prefix}_node[\"category\"] = {_cs_string(node.category)};",
        f"    {prefix}_node[\"requested_tier\"] = \"{requested}\";",
        f"    {prefix}_node[\"degraded_to_gm\"] = {prefix}_degraded;",
        f"    {prefix}_node[\"created_count\"] = {prefix}_created;",
        f"    {prefix}_node[\"failed_count\"] = {prefix}_failed;",
        f"    {prefix}_node[\"chosen_tier\"] = {prefix}_gbCount > 0 && "
        f"{prefix}_gmCount > 0 ? \"mixed\" : ({prefix}_gbCount > 0 ? \"Gb\" "
        f": ({prefix}_gmCount > 0 ? \"Gm\" : null));",
        f"    {prefix}_node[\"instances\"] = {prefix}_instances;",
        f"    __nodeResults.Add({prefix}_node);",
        "}",
    ))
    return "\n".join(parts)


def _coerce_node(value: GeometryNode | Mapping[str, Any], field_name: str) \
        -> GeometryNode:
    if isinstance(value, GeometryNode):
        return value
    if isinstance(value, Mapping):
        return GeometryNode.from_dict(value, field_name)
    raise GeometrySchemaError(
        f"{field_name} must be a GeometryNode or geometry-node object")


def recompile_node(
    geom_node: GeometryNode | Mapping[str, Any],
) -> EmittedCSharp:
    """Emit one complete, wrapped-ready Execute body for a Tier-G node."""

    return recompile((_coerce_node(geom_node, "geom_node"),))


def recompile(
    nodes: Iterable[GeometryNode | Mapping[str, Any]],
) -> EmittedCSharp:
    """Emit one guarded transaction for a batch of immutable geometry nodes.

    Each instance owns a ``SubTransaction``. A Gb assembly or placement error
    is caught and retried through the mandatory Gm definition. A bad Gm
    instance is recorded as failed while other nodes continue; no geometry
    exception is re-thrown from the generated Execute body.
    """

    if isinstance(nodes, (GeometryNode, Mapping, str, bytes)):
        raise GeometrySchemaError("nodes must be an iterable of geometry nodes")
    try:
        normalized = tuple(
            _coerce_node(node, f"nodes[{index}]")
            for index, node in enumerate(nodes))
    except TypeError as exc:
        raise GeometrySchemaError("nodes must be an iterable of geometry nodes") \
            from exc
    if not normalized:
        raise GeometrySchemaError("recompile requires at least one geometry node")
    node_ids = [node.node_id for node in normalized]
    if len(set(node_ids)) != len(node_ids):
        raise GeometrySchemaError("recompile node_id values must be unique")

    node_bodies = "\n\n".join(
        _indent_cs(_emit_node_cs(node, index), 4)
        for index, node in enumerate(normalized))
    csharp = (
        f"{_CS_PREAMBLE}\n"
        f"try\n"
        f"{{\n"
        f"    __txn = new Transaction(doc, \"KIR: recompile Tier G\");\n"
        f"    var __txnStart = __txn.Start();\n"
        f"    if (__txnStart != TransactionStatus.Started)\n"
        f"    {{\n"
        f"        __results[\"ok\"] = false;\n"
        f"        __results[\"error\"] = \"transaction start: \" + "
        f"__txnStart.ToString();\n"
        f"        return __results;\n"
        f"    }}\n"
        f"{node_bodies}\n"
        f"    var __txnCommit = __txn.Commit();\n"
        f"    if (__txnCommit != TransactionStatus.Committed)\n"
        f"    {{\n"
        f"        try {{ if (__txn.HasStarted() && !__txn.HasEnded()) "
        f"__txn.RollBack(); }} catch {{ }}\n"
        f"        __results[\"ok\"] = false;\n"
        f"        __results[\"error\"] = \"transaction commit: \" + "
        f"__txnCommit.ToString();\n"
        f"        __results[\"nodes\"] = __nodeResults;\n"
        f"        return __results;\n"
        f"    }}\n"
        f"}}\n"
        f"catch (Exception __fatalGeometryEx)\n"
        f"{{\n"
        f"    try {{ if (__txn != null && __txn.HasStarted() && "
        f"!__txn.HasEnded()) __txn.RollBack(); }} catch {{ }}\n"
        f"    __results[\"ok\"] = false;\n"
        f"    __results[\"error\"] = __Clip(__fatalGeometryEx.Message);\n"
        f"    __results[\"nodes\"] = __nodeResults;\n"
        f"    return __results;\n"
        f"}}\n"
        f"finally\n"
        f"{{\n"
        f"    try {{ if (__txn != null) __txn.Dispose(); }} catch {{ }}\n"
        f"}}\n"
        f"__results[\"ok\"] = (__failedTotal == 0);\n"
        f"__results[\"created_count\"] = __createdTotal;\n"
        f"__results[\"failed_count\"] = __failedTotal;\n"
        f"__results[\"nodes\"] = __nodeResults;\n"
        f"return __results;"
    )

    statuses = []
    for node in normalized:
        requested = node.geometry.tier
        if isinstance(node.geometry, GbSolid) \
                and not node.geometry.brep_candidate_valid:
            chosen = GeometryTier.GM
            degraded = True
        else:
            chosen = requested
            degraded = False
        statuses.append(EmittedNodeStatus(
            node_id=node.node_id,
            requested_tier=requested,
            chosen_tier=chosen,
            degraded_to_gm=degraded,
            instance_count=len(node.transforms),
        ))
    chosen_tiers = {status.chosen_tier for status in statuses}
    return EmittedCSharp(
        csharp=csharp,
        chosen_tier=(next(iter(chosen_tiers))
                     if len(chosen_tiers) == 1 else None),
        degraded_to_gm=any(status.degraded_to_gm for status in statuses),
        nodes=tuple(statuses),
        direct_shape_count=sum(status.instance_count for status in statuses),
    )
