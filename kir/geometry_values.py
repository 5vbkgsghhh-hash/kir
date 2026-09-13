"""Composable geometry values for the authoring Python SDK.

This is deliberately NOT a second geometry language and NOT a second KIR
validator. The module gives the author immutable, reusable values and lowers
them through the already-existing :mod:`kir.sdk` builders, generated from the
registry. The compiler remains the sole owner of semantics.

For an LLM the distinction is concrete: a profile is computed once, used
across several operations, and is not repeated as huge dictionaries in
context, and the resulting KIR matches byte-for-byte what would be written
by hand through the SDK.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class GeometryValueError(TypeError):
    """A Python value cannot cross the JSON-shaped KIR seam."""


@dataclass(frozen=True, slots=True)
class _MapValue:
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _ListValue:
    items: tuple[Any, ...]


def _plain_scalar(value: Any) -> Any:
    """The same dependency-free duck-typed numpy coercion as in ``kir.sdk``."""

    if hasattr(value, "tolist") and not isinstance(
            value, (str, bytes, list, tuple, dict)):
        return value.tolist()
    if hasattr(value, "item") and not isinstance(
            value, (str, bytes, list, tuple, dict)):
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    return value


def _freeze(value: Any, field: str) -> Any:
    value = _plain_scalar(value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Mapping):
        rows: list[tuple[str, Any]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise GeometryValueError(
                    f"{field}: object keys must be strings, got {key!r}")
            rows.append((key, _freeze(item, f"{field}.{key}")))
        return _MapValue(tuple(rows))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return _ListValue(tuple(
            _freeze(item, f"{field}[{index}]")
            for index, item in enumerate(value)))
    raise GeometryValueError(
        f"{field}: expected a JSON-shaped value, got {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, _MapValue):
        return {key: _thaw(item) for key, item in value.items}
    if isinstance(value, _ListValue):
        return [_thaw(item) for item in value.items]
    return value


def _freeze_scalar(value: Any, field: str) -> Any:
    """Strip a numpy-like value now, not at some future lowering."""

    frozen = _freeze(value, field)
    if isinstance(frozen, (_MapValue, _ListValue)):
        raise GeometryValueError(f"{field}: expected a scalar value")
    return frozen


@dataclass(frozen=True, slots=True, init=False)
class Profile2D:
    """A reusable ``region``; the rules still belong to the compiler."""

    _value: _MapValue

    def __init__(self, value: Mapping[str, Any]) -> None:
        frozen = _freeze(value, "profile")
        if not isinstance(frozen, _MapValue):
            raise GeometryValueError("profile must be an object")
        object.__setattr__(self, "_value", frozen)

    def to_kir(self) -> dict[str, Any]:
        return _thaw(self._value)


@dataclass(frozen=True, slots=True, init=False)
class PlaneFrame:
    """A reusable ``plane`` with no local geometry adjustment."""

    _value: _MapValue

    def __init__(self, *, origin_mm: Sequence[Any], normal: Sequence[Any],
                 x_dir: Sequence[Any]) -> None:
        frozen = _freeze({
            "origin_mm": origin_mm,
            "normal": normal,
            "x_dir": x_dir,
        }, "plane")
        object.__setattr__(self, "_value", frozen)

    def to_kir(self) -> dict[str, Any]:
        return _thaw(self._value)


@dataclass(frozen=True, slots=True, init=False)
class Polyline3:
    """A reusable KIR spatial polyline ``path3``."""

    _value: _ListValue

    def __init__(self, points_mm: Sequence[Sequence[Any]]) -> None:
        frozen = _freeze(points_mm, "path_mm")
        if not isinstance(frozen, _ListValue):
            raise GeometryValueError("path_mm must be a sequence")
        object.__setattr__(self, "_value", frozen)

    def to_kir(self) -> list[Any]:
        return _thaw(self._value)


@dataclass(frozen=True, slots=True, init=False)
class MeshValue:
    """A reusable KIR mesh value."""

    _value: _MapValue

    def __init__(self, *, vertices_mm: Sequence[Sequence[Any]],
                 triangles: Sequence[Sequence[Any]]) -> None:
        frozen = _freeze({
            "vertices_mm": vertices_mm,
            "triangles": triangles,
        }, "mesh")
        object.__setattr__(self, "_value", frozen)

    def to_kir(self) -> dict[str, Any]:
        return _thaw(self._value)

    def materialize(self, *, category: str, name: str,
                    id: str | None = None) -> dict[str, Any]:  # noqa: A002
        return _build("create_directshape", id=id, mesh=self.to_kir(),
                      category=category, name=name)


@dataclass(frozen=True, slots=True, init=False)
class NurbsSurfaceValue:
    """A reusable KIR NURBS-surface value."""

    _value: _MapValue

    def __init__(self, value: Mapping[str, Any]) -> None:
        frozen = _freeze(value, "surface")
        if not isinstance(frozen, _MapValue):
            raise GeometryValueError("surface must be an object")
        object.__setattr__(self, "_value", frozen)

    def to_kir(self) -> dict[str, Any]:
        return _thaw(self._value)

    def materialize(self, *, category: str, name: str,
                    id: str | None = None) -> dict[str, Any]:  # noqa: A002
        return _build("create_surface", id=id, surface=self.to_kir(),
                      category=category, name=name)


class SolidExpr:
    """A pure expression, lowered to exactly one existing KIR op."""

    def materialize(self, *, category: str, name: str,
                    id: str | None = None) -> dict[str, Any]:  # noqa: A002
        raise NotImplementedError


def _optional(fields: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        fields[key] = value.to_kir() if hasattr(value, "to_kir") else value


def _build(op_name: str, *, id: str | None, **fields: Any) -> dict[str, Any]:
    # An import at the boundary keeps values lightweight, and the
    # registry-generated builder the sole owner of the signature and coercion.
    from kir import sdk

    builder = sdk.builders()[op_name]
    if id is None:
        return builder(**fields)
    return builder(id=id, **fields)


@dataclass(frozen=True, slots=True)
class Extrude(SolidExpr):
    profile: Profile2D
    height_mm: Any
    base_z_mm: Any | None = None
    plane: PlaneFrame | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, Profile2D):
            raise GeometryValueError("profile must be Profile2D")
        object.__setattr__(self, "height_mm",
                           _freeze_scalar(self.height_mm, "height_mm"))
        if self.base_z_mm is not None:
            object.__setattr__(self, "base_z_mm",
                               _freeze_scalar(self.base_z_mm, "base_z_mm"))
        if self.plane is not None and not isinstance(self.plane, PlaneFrame):
            raise GeometryValueError("plane must be PlaneFrame or null")

    def materialize(self, *, category: str, name: str,
                    id: str | None = None) -> dict[str, Any]:  # noqa: A002
        fields = {"profile": self.profile.to_kir(),
                  "height_mm": self.height_mm,
                  "category": category, "name": name}
        _optional(fields, "base_z_mm", self.base_z_mm)
        _optional(fields, "plane", self.plane)
        return _build("create_solid_extrusion", id=id, **fields)


@dataclass(frozen=True, slots=True)
class Blend(SolidExpr):
    profile: Profile2D
    profile_top: Profile2D
    height_mm: Any
    base_z_mm: Any | None = None
    plane: PlaneFrame | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, Profile2D) \
                or not isinstance(self.profile_top, Profile2D):
            raise GeometryValueError(
                "profile and profile_top must be Profile2D")
        object.__setattr__(self, "height_mm",
                           _freeze_scalar(self.height_mm, "height_mm"))
        if self.base_z_mm is not None:
            object.__setattr__(self, "base_z_mm",
                               _freeze_scalar(self.base_z_mm, "base_z_mm"))
        if self.plane is not None and not isinstance(self.plane, PlaneFrame):
            raise GeometryValueError("plane must be PlaneFrame or null")

    def materialize(self, *, category: str, name: str,
                    id: str | None = None) -> dict[str, Any]:  # noqa: A002
        fields = {"profile": self.profile.to_kir(),
                  "profile_top": self.profile_top.to_kir(),
                  "height_mm": self.height_mm,
                  "category": category, "name": name}
        _optional(fields, "base_z_mm", self.base_z_mm)
        _optional(fields, "plane", self.plane)
        return _build("create_solid_blend", id=id, **fields)


@dataclass(frozen=True, slots=True)
class Sweep(SolidExpr):
    profile: Profile2D
    path: Polyline3
    ref_dir: Sequence[Any]
    variety: str = "frame"
    anchor_uv_mm: Sequence[Any] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, Profile2D):
            raise GeometryValueError("profile must be Profile2D")
        if not isinstance(self.path, Polyline3):
            raise GeometryValueError("path must be Polyline3")
        variety = _freeze_scalar(self.variety, "variety")
        if not isinstance(variety, str):
            raise GeometryValueError("variety: expected a string value")
        object.__setattr__(self, "variety", variety)
        ref_dir = _thaw(_freeze(self.ref_dir, "ref_dir"))
        object.__setattr__(self, "ref_dir", tuple(ref_dir))
        if self.anchor_uv_mm is not None:
            anchor = _thaw(_freeze(self.anchor_uv_mm, "anchor_uv_mm"))
            object.__setattr__(self, "anchor_uv_mm", tuple(anchor))

    def materialize(self, *, category: str, name: str,
                    id: str | None = None) -> dict[str, Any]:  # noqa: A002
        fields = {"variety": self.variety,
                  "profile": self.profile.to_kir(),
                  "path_mm": self.path.to_kir(),
                  "ref_dir": self.ref_dir,
                  "category": category, "name": name}
        _optional(fields, "anchor_uv_mm", self.anchor_uv_mm)
        return _build("create_solid_sweep", id=id, **fields)


@dataclass(frozen=True, slots=True)
class Revolve(SolidExpr):
    profile: Profile2D
    axis_xy_mm: Sequence[Any]
    sweep_deg: Any
    base_z_mm: Any | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, Profile2D):
            raise GeometryValueError("profile must be Profile2D")
        axis = _thaw(_freeze(self.axis_xy_mm, "axis_xy_mm"))
        object.__setattr__(self, "axis_xy_mm", tuple(axis))
        object.__setattr__(self, "sweep_deg",
                           _freeze_scalar(self.sweep_deg, "sweep_deg"))
        if self.base_z_mm is not None:
            object.__setattr__(self, "base_z_mm",
                               _freeze_scalar(self.base_z_mm, "base_z_mm"))

    def materialize(self, *, category: str, name: str,
                    id: str | None = None) -> dict[str, Any]:  # noqa: A002
        fields = {"profile": self.profile.to_kir(),
                  "axis_xy_mm": self.axis_xy_mm,
                  "sweep_deg": self.sweep_deg,
                  "category": category, "name": name}
        _optional(fields, "base_z_mm", self.base_z_mm)
        return _build("create_solid_revolve", id=id, **fields)


@dataclass(frozen=True, slots=True, init=False)
class SolidPart:
    """One existing ``solid_parts`` entry, with no new nesting semantics."""

    _value: _MapValue

    def __init__(self, value: Mapping[str, Any]) -> None:
        frozen = _freeze(value, "solid_part")
        if not isinstance(frozen, _MapValue):
            raise GeometryValueError("solid_part must be an object")
        object.__setattr__(self, "_value", frozen)

    def to_kir(self) -> dict[str, Any]:
        return _thaw(self._value)


@dataclass(frozen=True, slots=True)
class BooleanSolid(SolidExpr):
    """The current flat KIR boolean, deliberately not a universal DAG."""

    operation: str
    profile: Profile2D
    height_mm: Any
    parts: tuple[SolidPart, ...]
    base_z_mm: Any | None = None
    plane: PlaneFrame | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.profile, Profile2D):
            raise GeometryValueError("profile must be Profile2D")
        operation = _freeze_scalar(self.operation, "operation")
        if not isinstance(operation, str):
            raise GeometryValueError("operation: expected a string value")
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "height_mm",
                           _freeze_scalar(self.height_mm, "height_mm"))
        if self.base_z_mm is not None:
            object.__setattr__(self, "base_z_mm",
                               _freeze_scalar(self.base_z_mm, "base_z_mm"))
        parts = tuple(self.parts)
        if not parts or not all(isinstance(part, SolidPart) for part in parts):
            raise GeometryValueError("parts must contain SolidPart values")
        object.__setattr__(self, "parts", parts)
        if self.plane is not None and not isinstance(self.plane, PlaneFrame):
            raise GeometryValueError("plane must be PlaneFrame or null")

    def materialize(self, *, category: str, name: str,
                    id: str | None = None) -> dict[str, Any]:  # noqa: A002
        fields = {"operation": self.operation,
                  "profile": self.profile.to_kir(),
                  "height_mm": self.height_mm,
                  "parts": [part.to_kir() for part in self.parts],
                  "category": category, "name": name}
        _optional(fields, "base_z_mm", self.base_z_mm)
        _optional(fields, "plane", self.plane)
        return _build("create_solid_boolean", id=id, **fields)


__all__ = [
    "GeometryValueError", "Profile2D", "PlaneFrame", "Polyline3",
    "MeshValue", "NurbsSurfaceValue", "SolidExpr", "Extrude", "Blend",
    "Sweep", "Revolve", "SolidPart", "BooleanSolid",
]
