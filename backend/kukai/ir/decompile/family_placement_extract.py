"""Strict offline contract for the FamilyInstance placement side index.

Frozen L0 1.0 intentionally does not carry the placement semantics needed to
recreate arbitrary loaded-family instances.  This additive, versioned index
keeps those facts separate.  Its raw dialect mirrors the read-only Revit
collector: internal feet/radians are accepted only at that boundary and are
immediately normalized to millimetres/degrees.

Rows without both ``point_ft`` and ``rotation_rad`` are retained with
``placement_available=False``.  This is an honest extraction result (some
hosted FamilyInstances expose no LocationPoint), not permission to infer a
point from a bbox.  Supplying only one of the pair is malformed and fails
closed.

MEASURED (2026-07-27, SKLNK_EOM_R26_V2, ``backend/data/decompile/
sklnk_eom_r26_v2``): a ``FamilyPlacementType.CurveBased`` instance never
carries a ``LocationPoint`` -- its ``Location`` is a ``LocationCurve``
instead.  That census showed 1916 elements at 67.7% honest lift coverage
where the *entire* remaining gap (79 elements) was ``CurveBased`` rows
sitting in the index with ``placement_available: false`` even though every
one of them has a live, straight ``Line`` location curve (example: element
1268396, host 1221482 ``CableTray``).  The optional
``curve_state``/``curve_p0_mm``/``curve_p1_mm`` fields close that hole using
the same ``line``/``curved_unsupported`` contract as
:class:`kukai.ir.decompile.curtain_extract.CurveState` -- reused verbatim
here rather than re-invented, so the two extractors never disagree on what
"an exact straight curve" means.  A ``line`` curve alone (no ``point_mm``)
is enough to mark ``placement_available=True``: Revit's ``Location``
property is either a ``LocationPoint`` or a ``LocationCurve`` for one
instance, never both, so the two location kinds are alternatives, not a
stronger/weaker pair -- a row claiming both fails closed as malformed.
"""
from __future__ import annotations

import json
from kukai.ir.emit_utils import cs_string_literal
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from kukai.ir.decompile.curtain_extract import CurveState
from kukai.ir.decompile.side_contract import (
    SideFailure,
    SideFailureReason,
    parse_wire_failures,
    sorted_failures,
    source_binding_cs,
)


FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION = (
    "kir-decompile-family-placement-extract/1"
)


FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION = (
    "kir-decompile-family-placement-index/1"
)
_FT_TO_MM = 304.8
_VECTOR_TOLERANCE = 1e-6


class FamilyPlacementPayloadError(ValueError):
    """A raw or persisted family-placement payload violates the contract."""


class FamilyPlacementMirrorInvariantError(FamilyPlacementPayloadError):
    """``mirrored != hand_flipped XOR facing_flipped`` on one row.

    Отдельный подкласс существует ради ОДНОГО решения: такая строка становится
    квитанцией с типизированной причиной ``mirror_invariant_violated``, а не
    смертью прогона (см. :meth:`FamilyPlacementExtraction.from_rows`).
    """


class FamilyPlacementType(str, Enum):
    """Stable names of Autodesk.Revit.DB.FamilyPlacementType values."""

    INVALID = "Invalid"
    ONE_LEVEL_BASED = "OneLevelBased"
    ONE_LEVEL_BASED_HOSTED = "OneLevelBasedHosted"
    TWO_LEVELS_BASED = "TwoLevelsBased"
    WORK_PLANE_BASED = "WorkPlaneBased"
    CURVE_BASED = "CurveBased"
    CURVE_BASED_DETAIL = "CurveBasedDetail"
    CURVE_DRIVEN_STRUCTURAL = "CurveDrivenStructural"
    VIEW_BASED = "ViewBased"
    ADAPTIVE = "Adaptive"


class LocationAbsence(str, Enum):
    """Почему у экземпляра НЕТ точки вставки.

    «Не прочиталось» и «его тут не бывает» — разные утверждения, и только
    второе что-то говорит о модели. До этой волны обе ситуации приходили в
    лифт одинаково (``placement_available=False``, две пустые клетки), и
    единственная формулировка, которую он мог выдать, звучала как признание
    недосмотра: «FamilyInstance has no captured LocationPoint and rotation».

    ЗАМЕР 2026-07-29 (четыре документа, поимённый разбор всех 7 083
    элементов с этой причиной): 7 083 из 7 083 — ``OST_CurtainWallPanels``.
    Ни одного face-hosted, ни одного work-plane-based; больше того, все
    5 060 экземпляров ``WorkPlaneBased`` в K2 точку ИМЕЮТ. То есть
    подавляющая часть причины — не недосмотр вовсе, а форма, у которой
    точки вставки не бывает.
    """

    #: Витражная панель: положение порождает сетка разрезки носителя.
    #: ``Location`` пуст ПО ПОСТРОЕНИЮ, и ставится такая панель не
    #: ``NewFamilyInstance``, а назначением типа ячейке — свободная точка
    #: была бы тихой потерей привязки, а не приближением.
    CURTAIN_GRID_GENERATED = "curtain_grid_generated"
    #: Семейство посажено на ГРАНЬ (``FamilyInstance.HostFace`` не пуст).
    #: Положение восстановимо трансформом, но ставится такое семейство
    #: перегрузкой ``NewFamilyInstance(Reference face, ...)``, а её у нас
    #: нет — отказ остаётся, но теперь он называет ФОРМУ, а не недосмотр.
    FACE_HOSTED = "face_hosted"
    #: Семейство на рабочей плоскости без ``Location``. ЗАМЕР 2026-07-29:
    #: в четырёх документах таких НЕТ ни одного — ветка держится ради
    #: полноты разбора, а не ради известного адресата.
    WORK_PLANE_BASED = "work_plane_based"
    #: Ни одна из форм не опознана, либо чтение бросило. Единственное
    #: значение, которое честно значит «мы не знаем».
    UNREADABLE = "unreadable"


Vec3 = tuple[float, float, float]


def _mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise FamilyPlacementPayloadError(f"{field_name} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise FamilyPlacementPayloadError(
            f"{field_name} keys must be strings")
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
        raise FamilyPlacementPayloadError(
            f"{field_name} fields: {'; '.join(details)}")
    return row


def _string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise FamilyPlacementPayloadError(
            f"{field_name} must be a non-empty string")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    return None if value is None else _string(value, field_name)


def _boolean(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise FamilyPlacementPayloadError(f"{field_name} must be a boolean")
    return value


def _number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FamilyPlacementPayloadError(
            f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise FamilyPlacementPayloadError(
            f"{field_name} must be a finite number")
    return 0.0 if result == 0.0 else result


def _vec3(value: Any, field_name: str) -> Vec3:
    if (not isinstance(value, Sequence)
            or isinstance(value, (str, bytes))
            or len(value) != 3):
        raise FamilyPlacementPayloadError(
            f"{field_name} must contain exactly three finite numbers")
    return (
        _number(value[0], f"{field_name}[0]"),
        _number(value[1], f"{field_name}[1]"),
        _number(value[2], f"{field_name}[2]"),
    )


def _orientation(value: Any, field_name: str) -> Vec3:
    result = _vec3(value, field_name)
    norm = math.sqrt(sum(component * component for component in result))
    if abs(norm - 1.0) > _VECTOR_TOLERANCE:
        raise FamilyPlacementPayloadError(
            f"{field_name} must be a unit vector")
    return result


def _raw_element_id(row: Any, index: int) -> str:
    """id элемента из СЫРОЙ строки — для квитанции о самой этой строке.

    Строка, у которой не читается даже id, всё равно обязана оставить след:
    порядковый номер в пачке — худший, но честный адрес, и он лучше молчания.
    """
    if isinstance(row, Mapping):
        value = row.get("element_id")
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return f"<row {index}>"


def _element_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


_RAW_BASE_FIELDS = {
    "element_id", "symbol_id", "type_name", "family_name",
    "placement_type", "in_place", "mirrored", "hand_flipped",
    "facing_flipped", "super_component_id", "group_id", "host_id",
    "host_class", "hand_orientation", "facing_orientation", "status",
}
_PERSISTED_FIELDS_V1 = {
    "symbol_id", "type_name", "family_name", "placement_type", "in_place",
    "mirrored", "hand_flipped", "facing_flipped", "super_component_id",
    "group_id", "host_id", "host_class", "hand_orientation",
    "facing_orientation", "placement_available", "point_mm",
    "rotation_deg",
}
# MEASURED (2026-07-27, SKLNK_EOM_R26_V2 and every other frozen
# ``family_placement.index.json`` under ``backend/data/decompile``): every
# persisted row on disk today is exactly the V1 field set above -- none
# carry curve_state/curve_p0_mm/curve_p1_mm.  ``FamilyPlacementRecord.
# from_dict`` accepts either shape so those frozen files keep loading
# unchanged (see the V1/V2 fallback there).
#: Необязательные группы персистента. Каждая пишется ЦЕЛИКОМ или не пишется
#: вовсе (идиома ``to_dict`` этого файла и ``CurtainWallRecord.to_dict``:
#: «неприменимо» — это ОТСУТСТВИЕ ключей, а не явный null). Полугруппа —
#: всегда ошибка: «начало трансформа есть, базиса нет» неотличимо от точки.
_OPTIONAL_PERSISTED_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"curve_state", "curve_p0_mm", "curve_p1_mm"}),
    frozenset({"location_absence"}),
    frozenset({"transform_origin_mm", "transform_basis_x",
               "transform_basis_y", "transform_basis_z"}),
)
_PERSISTED_FIELDS = _PERSISTED_FIELDS_V1 | frozenset().union(
    *_OPTIONAL_PERSISTED_GROUPS)


def _optional_groups_are_whole(extra: set[str]) -> bool:
    """Лишние ключи раскладываются на ЦЕЛЫЕ необязательные группы?"""
    remaining = set(extra)
    for group in _OPTIONAL_PERSISTED_GROUPS:
        if remaining & group:
            if not group <= remaining:
                return False
            remaining -= group
    return not remaining


@dataclass(frozen=True, slots=True)
class FamilyPlacementRecord:
    """One normalized FamilyInstance placement row."""

    element_id: str
    symbol_id: str
    type_name: str
    family_name: str
    placement_type: FamilyPlacementType
    in_place: bool
    mirrored: bool
    hand_flipped: bool
    facing_flipped: bool
    super_component_id: str | None
    group_id: str | None
    host_id: str | None
    host_class: str | None
    hand_orientation: Vec3
    facing_orientation: Vec3
    placement_available: bool
    point_mm: Vec3 | None
    rotation_deg: float | None
    # MEASURED (2026-07-27, SKLNK_EOM_R26_V2): a CurveBased instance's only
    # location is this line; see the module docstring for the census.
    curve_state: CurveState | None = None
    curve_p0_mm: Vec3 | None = None
    curve_p1_mm: Vec3 | None = None
    # ТИПИЗИРОВАННАЯ причина пустой точки. ``None`` здесь значит РОВНО
    # «разбор снят схемой, которая причину не читала» — замороженный корпус
    # (все ``family_placement.index.json`` до 2026-07-29) именно такой, и
    # лифт обязан отличать это от «причины нет».
    location_absence: "LocationAbsence | None" = None
    # ТРЕТИЙ ИСТОЧНИК положения — ``Instance.GetTransform()``.
    #
    # Имя поля выбрано так, чтобы точкой вставки оно не притворялось: у
    # экземпляра, у которого ``Location`` пуст, положение ЕСТЬ, а точки
    # вставки НЕТ, и это не одно и то же. Инвариант ниже запрещает строке
    # нести точку и трансформ одновременно — подменить одно другим нельзя
    # структурно, а не по договорённости.
    transform_origin_mm: Vec3 | None = None
    transform_basis_x: Vec3 | None = None
    transform_basis_y: Vec3 | None = None
    transform_basis_z: Vec3 | None = None

    def __post_init__(self) -> None:
        _string(self.element_id, "FamilyPlacementRecord.element_id")
        _string(self.symbol_id, "FamilyPlacementRecord.symbol_id")
        _string(self.type_name, "FamilyPlacementRecord.type_name")
        _string(self.family_name, "FamilyPlacementRecord.family_name")
        if not isinstance(self.placement_type, FamilyPlacementType):
            raise FamilyPlacementPayloadError(
                "FamilyPlacementRecord.placement_type is invalid")
        for name in ("in_place", "mirrored", "hand_flipped",
                     "facing_flipped", "placement_available"):
            _boolean(getattr(self, name), f"FamilyPlacementRecord.{name}")
        # ЕДИНСТВЕННОЕ утверждение этого файла БЕЗ пометки ЗАМЕР — и оно
        # неверно в общем случае. Живые пробы 2026-07-21 (см. authoring.py
        # :2291) показали XOR-модель для зеркалирования относительно
        # ВЕРТИКАЛЬНОЙ плоскости семейства; для work-plane-based и адаптивных
        # семейств, зеркалимых относительно произвольной плоскости, Revit
        # ставит Mirrored, не трогая ни Hand, ни Facing. Замер конвенции —
        # отдельная работа (нужен живой Revit и семейство каждого вида
        # размещения); до неё нарушение инварианта считается фактом ОБ ЭТОМ
        # ЭЛЕМЕНТЕ, а не о прогоне: подкласс ловится в ``from_rows`` и
        # становится квитанцией §18.2, элемент — честным атомом.
        if self.mirrored != (self.hand_flipped != self.facing_flipped):
            raise FamilyPlacementMirrorInvariantError(
                "mirrored must equal hand_flipped XOR facing_flipped")
        for name in ("super_component_id", "group_id", "host_id",
                     "host_class"):
            _optional_string(
                getattr(self, name), f"FamilyPlacementRecord.{name}")
        if (self.host_id is None) != (self.host_class is None):
            raise FamilyPlacementPayloadError(
                "host_id and host_class must both be present or both be null")
        hand = _orientation(
            self.hand_orientation, "FamilyPlacementRecord.hand_orientation")
        facing = _orientation(
            self.facing_orientation,
            "FamilyPlacementRecord.facing_orientation")
        if abs(sum(a * b for a, b in zip(hand, facing))) > _VECTOR_TOLERANCE:
            raise FamilyPlacementPayloadError(
                "hand_orientation and facing_orientation must be orthogonal")
        if self.point_mm is not None or self.rotation_deg is not None:
            if self.point_mm is None or self.rotation_deg is None:
                raise FamilyPlacementPayloadError(
                    "point_mm and rotation_deg must both be present or "
                    "both be null")
            _vec3(self.point_mm, "FamilyPlacementRecord.point_mm")
            _number(self.rotation_deg, "FamilyPlacementRecord.rotation_deg")
        has_point = self.point_mm is not None

        if self.curve_state is not None and not isinstance(
                self.curve_state, CurveState):
            raise FamilyPlacementPayloadError(
                "FamilyPlacementRecord.curve_state must be a CurveState "
                "or None")
        if self.curve_state is CurveState.LINE:
            if self.curve_p0_mm is None or self.curve_p1_mm is None:
                raise FamilyPlacementPayloadError(
                    "a 'line' curve_state requires curve_p0_mm and "
                    "curve_p1_mm")
            _vec3(self.curve_p0_mm, "FamilyPlacementRecord.curve_p0_mm")
            _vec3(self.curve_p1_mm, "FamilyPlacementRecord.curve_p1_mm")
        elif self.curve_p0_mm is not None or self.curve_p1_mm is not None:
            raise FamilyPlacementPayloadError(
                "curve_p0_mm/curve_p1_mm require curve_state to be 'line'")
        has_curve_line = self.curve_state is CurveState.LINE

        # MEASURED (2026-07-27, SKLNK_EOM_R26_V2 live census): Revit's
        # FamilyInstance.Location property is either a LocationPoint or a
        # LocationCurve for one instance, never both -- no counterexample
        # across the census. A row claiming both is a malformed payload.
        if has_point and has_curve_line:
            raise FamilyPlacementPayloadError(
                "point_mm/rotation_deg and a line curve are mutually "
                "exclusive")

        # placement_available is the disjunction of the two location kinds
        # a FamilyInstance can honestly expose (MEASURED: a straight-line
        # LocationCurve is exactly as usable as a LocationPoint for
        # recreating a CurveBased instance's position -- see the module
        # docstring's 79/79 CurveBased census).
        if self.placement_available:
            if not (has_point or has_curve_line):
                raise FamilyPlacementPayloadError(
                    "available placement requires point_mm/rotation_deg "
                    "or a line curve")
        elif has_point or has_curve_line:
            raise FamilyPlacementPayloadError(
                "unavailable placement cannot carry point_mm/rotation_deg "
                "or a line curve")

        # ── третий источник: положение, которое НЕ точка вставки ──────────
        if self.location_absence is not None and not isinstance(
                self.location_absence, LocationAbsence):
            raise FamilyPlacementPayloadError(
                "FamilyPlacementRecord.location_absence must be a "
                "LocationAbsence or None")
        if self.placement_available and self.location_absence is not None:
            # Точка есть — объяснять нечего. Строка, несущая и то и другое,
            # означает, что эмиттер сам себе противоречит.
            raise FamilyPlacementPayloadError(
                "an available placement cannot carry location_absence")
        basis = (self.transform_basis_x, self.transform_basis_y,
                 self.transform_basis_z)
        has_origin = self.transform_origin_mm is not None
        if has_origin != all(vector is not None for vector in basis):
            # Половина трансформа — не трансформ: без базиса ориентацию
            # нечем восстановить, а «начало есть, поворота нет» выглядит
            # ровно как точка вставки, которой здесь быть не должно.
            raise FamilyPlacementPayloadError(
                "transform_origin_mm requires all three basis vectors")
        if has_origin:
            # ГЛАВНЫЙ СТРАЖ ФАЙЛА. Пока эти два поля не могут стоять рядом,
            # ни одна ветка кода не сможет молча повысить трансформ до точки
            # вставки: для этого ей пришлось бы сначала нарушить инвариант.
            # Запрет — не стилистика: семейство на грани ставится
            # перегрузкой NewFamilyInstance(Reference face, ...), которой у
            # нас нет, и свободная точка вместо привязки к грани — тихая
            # потеря привязки, выглядящая успехом (§18.1).
            if self.placement_available or has_point or has_curve_line:
                raise FamilyPlacementPayloadError(
                    "a transform and an insertion point are mutually "
                    "exclusive: the transform is a diagnosis, not a point")
            _vec3(self.transform_origin_mm,
                  "FamilyPlacementRecord.transform_origin_mm")
            names = ("transform_basis_x", "transform_basis_y",
                     "transform_basis_z")
            vectors = [
                _orientation(vector, f"FamilyPlacementRecord.{name}")
                for name, vector in zip(names, basis)
            ]
            for first in range(3):
                for second in range(first + 1, 3):
                    dot = sum(a * b for a, b in zip(
                        vectors[first], vectors[second]))
                    if abs(dot) > _VECTOR_TOLERANCE:
                        raise FamilyPlacementPayloadError(
                            "transform basis vectors must be mutually "
                            "orthogonal")

    @classmethod
    def from_raw(
        cls,
        value: Any,
        field_name: str = "family placement raw row",
    ) -> "FamilyPlacementRecord":
        raw = _mapping(value, field_name)
        has_point = "point_ft" in raw
        has_rotation = "rotation_rad" in raw
        if has_point != has_rotation:
            raise FamilyPlacementPayloadError(
                f"{field_name} must carry point_ft and rotation_rad together")
        has_curve_state = "curve_state" in raw
        has_curve_p0 = "curve_p0_ft" in raw
        has_curve_p1 = "curve_p1_ft" in raw
        if has_curve_p0 != has_curve_p1:
            raise FamilyPlacementPayloadError(
                f"{field_name} must carry curve_p0_ft and curve_p1_ft "
                "together")
        if has_curve_p0 and not has_curve_state:
            raise FamilyPlacementPayloadError(
                f"{field_name} curve_p0_ft/curve_p1_ft require curve_state")
        has_absence = "location_absence" in raw
        # Трансформ приходит ЧЕТВЕРКОЙ (начало + три базиса) или не приходит
        # вовсе: полугруппа неотличима от точки со сломанным поворотом.
        _TRANSFORM_RAW = ("transform_origin_ft", "transform_basis_x",
                          "transform_basis_y", "transform_basis_z")
        transform_present = [name for name in _TRANSFORM_RAW if name in raw]
        if transform_present and len(transform_present) != len(_TRANSFORM_RAW):
            raise FamilyPlacementPayloadError(
                f"{field_name} must carry transform_origin_ft and all three "
                "transform_basis_* together")
        has_transform = bool(transform_present)
        fields = _RAW_BASE_FIELDS | (
            {"point_ft", "rotation_rad"} if has_point else set())
        if has_curve_state:
            fields = fields | {"curve_state"}
        if has_curve_p0:
            fields = fields | {"curve_p0_ft", "curve_p1_ft"}
        if has_absence:
            fields = fields | {"location_absence"}
        if has_transform:
            fields = fields | set(_TRANSFORM_RAW)
        row = _exact_fields(raw, fields, field_name)
        if row["status"] != "ok":
            raise FamilyPlacementPayloadError(
                f"{field_name}.status must be the literal 'ok'")
        try:
            placement_type = FamilyPlacementType(row["placement_type"])
        except (TypeError, ValueError) as exc:
            raise FamilyPlacementPayloadError(
                f"{field_name}.placement_type is unsupported") from exc
        point_mm: Vec3 | None = None
        rotation_deg: float | None = None
        if has_point:
            point_ft = _vec3(row["point_ft"], f"{field_name}.point_ft")
            point_mm = tuple(
                0.0 if value * _FT_TO_MM == 0.0 else value * _FT_TO_MM
                for value in point_ft
            )
            rotation_deg = math.degrees(_number(
                row["rotation_rad"], f"{field_name}.rotation_rad"))
            if rotation_deg == 0.0:
                rotation_deg = 0.0

        # MEASURED (2026-07-27, SKLNK_EOM_R26_V2, sklnk_eom_r26_v2): 79 of
        # 1916 elements are FamilyPlacementType.CurveBased and expose a
        # LocationCurve (always a straight Line in this census) instead of a
        # LocationPoint. Before this, the whole 79-element gap was the
        # entire remainder of the 67.7% honest lift-coverage hole -- see the
        # module docstring.
        curve_state: CurveState | None = None
        curve_p0_mm: Vec3 | None = None
        curve_p1_mm: Vec3 | None = None
        if has_curve_state:
            try:
                curve_state = CurveState(row["curve_state"])
            except (TypeError, ValueError) as exc:
                raise FamilyPlacementPayloadError(
                    f"{field_name}.curve_state is unsupported") from exc
            if curve_state is CurveState.LINE:
                if not has_curve_p0:
                    raise FamilyPlacementPayloadError(
                        f"{field_name} a 'line' curve_state requires "
                        "curve_p0_ft and curve_p1_ft")
                curve_p0_ft = _vec3(
                    row["curve_p0_ft"], f"{field_name}.curve_p0_ft")
                curve_p1_ft = _vec3(
                    row["curve_p1_ft"], f"{field_name}.curve_p1_ft")
                curve_p0_mm = tuple(
                    0.0 if value * _FT_TO_MM == 0.0 else value * _FT_TO_MM
                    for value in curve_p0_ft
                )
                curve_p1_mm = tuple(
                    0.0 if value * _FT_TO_MM == 0.0 else value * _FT_TO_MM
                    for value in curve_p1_ft
                )
            elif has_curve_p0:
                raise FamilyPlacementPayloadError(
                    f"{field_name} curve_p0_ft/curve_p1_ft require "
                    "curve_state to be 'line'")

        location_absence: LocationAbsence | None = None
        if has_absence:
            try:
                location_absence = LocationAbsence(row["location_absence"])
            except (TypeError, ValueError) as exc:
                # Незнакомое слово — НЕ «наверное, unreadable»: причина,
                # которую мы не умеем читать, обязана падать, а не тихо
                # огрубляться до самой безобидной из известных.
                raise FamilyPlacementPayloadError(
                    f"{field_name}.location_absence is unsupported") from exc

        transform_origin_mm: Vec3 | None = None
        transform_basis: list[Vec3 | None] = [None, None, None]
        if has_transform:
            origin_ft = _vec3(
                row["transform_origin_ft"], f"{field_name}.transform_origin_ft")
            transform_origin_mm = tuple(
                0.0 if value * _FT_TO_MM == 0.0 else value * _FT_TO_MM
                for value in origin_ft
            )
            # Базисы — направления, а не длины: пересчитывать их в мм было бы
            # ошибкой размерности.
            transform_basis = [
                _orientation(row[name], f"{field_name}.{name}")
                for name in ("transform_basis_x", "transform_basis_y",
                             "transform_basis_z")
            ]

        return cls(
            element_id=_string(row["element_id"], f"{field_name}.element_id"),
            symbol_id=_string(row["symbol_id"], f"{field_name}.symbol_id"),
            type_name=_string(row["type_name"], f"{field_name}.type_name"),
            family_name=_string(row["family_name"], f"{field_name}.family_name"),
            placement_type=placement_type,
            in_place=_boolean(row["in_place"], f"{field_name}.in_place"),
            mirrored=_boolean(row["mirrored"], f"{field_name}.mirrored"),
            hand_flipped=_boolean(
                row["hand_flipped"], f"{field_name}.hand_flipped"),
            facing_flipped=_boolean(
                row["facing_flipped"], f"{field_name}.facing_flipped"),
            super_component_id=_optional_string(
                row["super_component_id"],
                f"{field_name}.super_component_id"),
            group_id=_optional_string(row["group_id"], f"{field_name}.group_id"),
            host_id=_optional_string(row["host_id"], f"{field_name}.host_id"),
            host_class=_optional_string(
                row["host_class"], f"{field_name}.host_class"),
            hand_orientation=_orientation(
                row["hand_orientation"], f"{field_name}.hand_orientation"),
            facing_orientation=_orientation(
                row["facing_orientation"],
                f"{field_name}.facing_orientation"),
            placement_available=has_point or curve_state is CurveState.LINE,
            point_mm=point_mm,
            rotation_deg=rotation_deg,
            curve_state=curve_state,
            curve_p0_mm=curve_p0_mm,
            curve_p1_mm=curve_p1_mm,
            location_absence=location_absence,
            transform_origin_mm=transform_origin_mm,
            transform_basis_x=transform_basis[0],
            transform_basis_y=transform_basis[1],
            transform_basis_z=transform_basis[2],
        )

    @classmethod
    def from_dict(
        cls,
        element_id: str,
        value: Any,
        field_name: str = "family placement index row",
    ) -> "FamilyPlacementRecord":
        raw = _mapping(value, field_name)
        field_set = set(raw)
        # V1 — обязательное ядро; сверх него допускаются только ЦЕЛЫЕ
        # необязательные группы. Так замороженный корпус (V1 и V1+curve)
        # грузится неизменным, а новые группы не требуют ни новой версии
        # схемы, ни перечисления комбинаций.
        if (_PERSISTED_FIELDS_V1 <= field_set
                and _optional_groups_are_whole(field_set - _PERSISTED_FIELDS_V1)):
            row = raw
        else:
            # Ни одна законная форма: падаем в полный набор, чтобы ошибка
            # назвала точно, чего не хватает или что лишнее — ровно как
            # V1/V2-запасной путь в GroupInstanceRecord.from_dict.
            row = _exact_fields(raw, _PERSISTED_FIELDS, field_name)
        has_curve_fields = "curve_state" in row
        has_absence = "location_absence" in row
        has_transform = "transform_origin_mm" in row
        try:
            placement_type = FamilyPlacementType(row["placement_type"])
        except (TypeError, ValueError) as exc:
            raise FamilyPlacementPayloadError(
                f"{field_name}.placement_type is unsupported") from exc
        available = _boolean(
            row["placement_available"], f"{field_name}.placement_available")
        point = (
            _vec3(row["point_mm"], f"{field_name}.point_mm")
            if row["point_mm"] is not None else None)
        rotation = (
            _number(row["rotation_deg"], f"{field_name}.rotation_deg")
            if row["rotation_deg"] is not None else None)
        curve_state: CurveState | None = None
        curve_p0_mm: Vec3 | None = None
        curve_p1_mm: Vec3 | None = None
        if has_curve_fields:
            raw_curve_state = row["curve_state"]
            if raw_curve_state is not None:
                try:
                    curve_state = CurveState(raw_curve_state)
                except (TypeError, ValueError) as exc:
                    raise FamilyPlacementPayloadError(
                        f"{field_name}.curve_state is unsupported") from exc
            curve_p0_mm = (
                _vec3(row["curve_p0_mm"], f"{field_name}.curve_p0_mm")
                if row["curve_p0_mm"] is not None else None)
            curve_p1_mm = (
                _vec3(row["curve_p1_mm"], f"{field_name}.curve_p1_mm")
                if row["curve_p1_mm"] is not None else None)
        location_absence: LocationAbsence | None = None
        if has_absence and row["location_absence"] is not None:
            try:
                location_absence = LocationAbsence(row["location_absence"])
            except (TypeError, ValueError) as exc:
                raise FamilyPlacementPayloadError(
                    f"{field_name}.location_absence is unsupported") from exc
        transform_origin_mm: Vec3 | None = None
        transform_basis: list[Vec3 | None] = [None, None, None]
        if has_transform and row["transform_origin_mm"] is not None:
            transform_origin_mm = _vec3(
                row["transform_origin_mm"],
                f"{field_name}.transform_origin_mm")
            transform_basis = [
                _orientation(row[name], f"{field_name}.{name}")
                for name in ("transform_basis_x", "transform_basis_y",
                             "transform_basis_z")
            ]
        return cls(
            element_id=_string(element_id, f"{field_name} key"),
            symbol_id=_string(row["symbol_id"], f"{field_name}.symbol_id"),
            type_name=_string(row["type_name"], f"{field_name}.type_name"),
            family_name=_string(row["family_name"], f"{field_name}.family_name"),
            placement_type=placement_type,
            in_place=_boolean(row["in_place"], f"{field_name}.in_place"),
            mirrored=_boolean(row["mirrored"], f"{field_name}.mirrored"),
            hand_flipped=_boolean(
                row["hand_flipped"], f"{field_name}.hand_flipped"),
            facing_flipped=_boolean(
                row["facing_flipped"], f"{field_name}.facing_flipped"),
            super_component_id=_optional_string(
                row["super_component_id"],
                f"{field_name}.super_component_id"),
            group_id=_optional_string(row["group_id"], f"{field_name}.group_id"),
            host_id=_optional_string(row["host_id"], f"{field_name}.host_id"),
            host_class=_optional_string(
                row["host_class"], f"{field_name}.host_class"),
            hand_orientation=_orientation(
                row["hand_orientation"], f"{field_name}.hand_orientation"),
            facing_orientation=_orientation(
                row["facing_orientation"],
                f"{field_name}.facing_orientation"),
            placement_available=available,
            point_mm=point,
            rotation_deg=rotation,
            curve_state=curve_state,
            curve_p0_mm=curve_p0_mm,
            curve_p1_mm=curve_p1_mm,
            location_absence=location_absence,
            transform_origin_mm=transform_origin_mm,
            transform_basis_x=transform_basis[0],
            transform_basis_y=transform_basis[1],
            transform_basis_z=transform_basis[2],
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "symbol_id": self.symbol_id,
            "type_name": self.type_name,
            "family_name": self.family_name,
            "placement_type": self.placement_type.value,
            "in_place": self.in_place,
            "mirrored": self.mirrored,
            "hand_flipped": self.hand_flipped,
            "facing_flipped": self.facing_flipped,
            "super_component_id": self.super_component_id,
            "group_id": self.group_id,
            "host_id": self.host_id,
            "host_class": self.host_class,
            "hand_orientation": list(self.hand_orientation),
            "facing_orientation": list(self.facing_orientation),
            "placement_available": self.placement_available,
            "point_mm": (
                list(self.point_mm) if self.point_mm is not None else None),
            "rotation_deg": self.rotation_deg,
        }
        # MEASURED (2026-07-27, demo side index: 59927 rows, almost all
        # point-based): a curve is the exception, not the rule, unlike
        # point_mm/rotation_deg which every row already carries (even as
        # explicit null) regardless of placement kind. Writing three more
        # explicit-null keys into every point-based row would grow the whole
        # side index for a minority feature and reshape every existing row
        # for no informational gain. CurtainWallRecord.to_dict() in the
        # sibling curtain_extract.py already treats "not applicable" as key
        # absence (``{"curtain_available": False}`` carries no grid/panel/
        # mullion keys at all) rather than an explicit null group -- this
        # mirrors that exact contract.  ``from_dict`` reads both the absent
        # and the present shape (see the V1/V2 field-set fallback there).
        if self.curve_state is not None:
            result["curve_state"] = self.curve_state.value
            result["curve_p0_mm"] = (
                list(self.curve_p0_mm)
                if self.curve_p0_mm is not None else None)
            result["curve_p1_mm"] = (
                list(self.curve_p1_mm)
                if self.curve_p1_mm is not None else None)
        # Та же идиома: «неприменимо» — это отсутствие ключей. У строки с
        # точкой причины отсутствия нет и быть не может, и писать ей явный
        # null значило бы утверждать, что вопрос осмыслен.
        if self.location_absence is not None:
            result["location_absence"] = self.location_absence.value
        if self.transform_origin_mm is not None:
            result["transform_origin_mm"] = list(self.transform_origin_mm)
            result["transform_basis_x"] = list(self.transform_basis_x)
            result["transform_basis_y"] = list(self.transform_basis_y)
            result["transform_basis_z"] = list(self.transform_basis_z)
        return result


@dataclass(frozen=True, slots=True)
class FamilyPlacementExtraction:
    """Validated, deterministic family-placement side-index bundle.

    §18.2: ответ стадии — ЭТО пара ``records`` + ``failures``. Второй ключ
    обязателен и в персистенте: без него нельзя отличить «панель не читается»
    от «панель никто не спросил».
    """

    records: tuple[FamilyPlacementRecord, ...]
    failures: tuple[SideFailure, ...] = ()

    def __post_init__(self) -> None:
        ids = [record.element_id for record in self.records]
        if len(ids) != len(set(ids)):
            raise FamilyPlacementPayloadError(
                "family placement index contains duplicate element_id")
        object.__setattr__(self, "records", tuple(sorted(
            self.records, key=lambda item: _element_id_key(item.element_id))))
        object.__setattr__(self, "failures", sorted_failures(self.failures))

    def __iter__(self) -> Iterator[FamilyPlacementRecord]:
        return iter(self.records)

    def __len__(self) -> int:
        return len(self.records)

    @property
    def family_placement_index(self) -> dict[str, dict[str, Any]]:
        return {
            record.element_id: record.to_dict()
            for record in sorted(
                self.records,
                key=lambda item: _element_id_key(item.element_id))
        }

    def entry_for(self, element_id: str) -> FamilyPlacementRecord:
        for record in self.records:
            if record.element_id == element_id:
                return record
        raise FamilyPlacementPayloadError(
            f"element is absent from family placement index: {element_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION,
            "family_placement_index": self.family_placement_index,
            "failures": [failure.to_dict() for failure in self.failures],
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
    def from_rows(
        cls,
        rows: Iterable[Any],
        *,
        wire_failures: Iterable[Any] | None = None,
    ) -> "FamilyPlacementExtraction":
        """Разобрать строки ПОСТРОЧНО: битая строка — квитанция, не смерть.

        Раньше это был генератор внутри конструктора: первое же исключение
        ``FamilyPlacementPayloadError`` уходило в общий ``except`` pipeline и
        превращалось во «внутреннюю ошибка декомпайла» — без указания
        элемента, без остальных 200 строк пачки и без остальных пачек.
        Одна панель роняла разбор здания (M6 аудита 28.07).
        """
        records: list[FamilyPlacementRecord] = []
        failures: list[SideFailure] = list(
            parse_wire_failures(
                list(wire_failures) if wire_failures is not None else None,
                "family placement wire failures"))
        for index, row in enumerate(rows):
            field_name = f"family placement raw row[{index}]"
            try:
                records.append(
                    FamilyPlacementRecord.from_raw(row, field_name))
            except FamilyPlacementMirrorInvariantError as exc:
                failures.append(SideFailure(
                    _raw_element_id(row, index),
                    str(exc)[:300],
                    typed_reason=SideFailureReason.MIRROR_INVARIANT_VIOLATED))
            except FamilyPlacementPayloadError as exc:
                failures.append(SideFailure(
                    _raw_element_id(row, index),
                    str(exc)[:300],
                    typed_reason=SideFailureReason.ROW_UNPARSABLE))
        return cls(tuple(records), tuple(failures))

    @classmethod
    def from_jsonl(cls, value: str) -> "FamilyPlacementExtraction":
        rows = []
        for line_number, line in enumerate(value.splitlines(), start=1):
            if not line.strip():
                raise FamilyPlacementPayloadError(
                    f"family placement JSONL line {line_number} is blank")
            try:
                rows.append(json.loads(line))
            except (TypeError, ValueError) as exc:
                raise FamilyPlacementPayloadError(
                    f"family placement JSONL line {line_number} is invalid: "
                    f"{exc}") from exc
        return cls.from_rows(rows)

    @classmethod
    def load_jsonl(cls, path: str | Path) -> "FamilyPlacementExtraction":
        with Path(path).open("r", encoding="utf-8") as stream:
            rows = []
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    raise FamilyPlacementPayloadError(
                        f"family placement JSONL line {line_number} is blank")
                try:
                    rows.append(json.loads(line))
                except (TypeError, ValueError) as exc:
                    raise FamilyPlacementPayloadError(
                        f"family placement JSONL line {line_number} is "
                        f"invalid: {exc}") from exc
        # Тот же построчный карантин, что и на живом пути: битая строка не
        # обязана уносить с собой остальной файл.
        return cls.from_rows(rows)

    @classmethod
    def from_dict(cls, value: Any) -> "FamilyPlacementExtraction":
        # ``failures`` НЕОБЯЗАТЕЛЕН на чтении и ОБЯЗАТЕЛЕН на записи. Разборы,
        # сделанные до этой волны, ключа не несут: объявить их нечитаемыми
        # значило бы ретроактивно уничтожить архив ради формы. Та же осознанная
        # миграция, что у полей рабочих наборов в §18.4.
        raw = _mapping(value, "persisted family placement extraction")
        root = _exact_fields(
            raw,
            ({"schema_version", "family_placement_index", "failures"}
             if "failures" in raw
             else {"schema_version", "family_placement_index"}),
            "persisted family placement extraction")
        if root["schema_version"] != FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION:
            raise FamilyPlacementPayloadError(
                "family placement index schema_version mismatch")
        raw_index = _mapping(
            root["family_placement_index"],
            "persisted family placement extraction.family_placement_index")
        return cls(
            tuple(
                FamilyPlacementRecord.from_dict(
                    element_id,
                    row,
                    "persisted family placement extraction."
                    f"family_placement_index[{element_id!r}]",
                )
                for element_id, row in sorted(
                    raw_index.items(),
                    key=lambda item: _element_id_key(item[0]))
            ),
            parse_wire_failures(
                root.get("failures"),
                "persisted family placement extraction.failures"),
        )

    @classmethod
    def from_json(
        cls,
        value: str | bytes | bytearray,
    ) -> "FamilyPlacementExtraction":
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise FamilyPlacementPayloadError(
                f"family placement index is not valid JSON: {exc}") from exc
        return cls.from_dict(decoded)


def parse_family_placement_index(
    value: FamilyPlacementExtraction | Mapping[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Return a strict normalized index; ``None`` is the empty index."""

    if value is None:
        return {}
    if isinstance(value, FamilyPlacementExtraction):
        return value.family_placement_index
    raw = _mapping(value, "family_placement_index")
    if "schema_version" in raw or "family_placement_index" in raw:
        return FamilyPlacementExtraction.from_dict(raw).family_placement_index
    extraction = FamilyPlacementExtraction(tuple(
        FamilyPlacementRecord.from_dict(
            element_id,
            row,
            f"family_placement_index[{element_id!r}]",
        )
        for element_id, row in sorted(
            raw.items(), key=lambda item: _element_id_key(item[0]))
    ))
    return extraction.family_placement_index


def parse_family_placement_failures(
    value: FamilyPlacementExtraction | Mapping[str, Any] | None,
) -> dict[str, SideFailure]:
    """Квитанции индекса, ключом по element_id; ``None`` — пустой словарь.

    Нужны ЛИФТУ (§18.2/M5): элемент, чей id лежит здесь, обязан атомизоваться
    с причиной ИЗ КВИТАНЦИИ, а не с безликим «absent from side index».
    Форма входа та же, что у :func:`parse_family_placement_index`: сам объект,
    персистентный конверт или голый индекс (у последнего квитанций нет).
    """
    if value is None:
        return {}
    if isinstance(value, FamilyPlacementExtraction):
        failures = value.failures
    elif isinstance(value, Mapping):
        if "schema_version" in value or "family_placement_index" in value:
            try:
                failures = parse_wire_failures(
                    value.get("failures"), "family_placement failures")
            except Exception:  # noqa: BLE001 — битые квитанции не ломают лифт
                return {}
        else:
            return {}
    else:
        return {}
    return {failure.element_id: failure for failure in failures}


# ── Deterministic Revit C# emission ─────────────────────────────────────────
#
# This is an Execute-method body for the same ``wrap_user_code`` path used in
# serving.  It opens no Transaction and never calls get_Geometry/Tessellate.
# ``LocationPoint`` position crosses the wire in RAW internal FEET and rotation
# in RAW radians — the strict parser (:meth:`FamilyPlacementRecord.from_raw`)
# owns the feet→millimetre / radian→degree conversion at the offline boundary,
# so the bridge never converts (single conversion authority, I3-friendly).
#
# Fail-closed contract (I2): a requested element that is not a FamilyInstance,
# whose orientation vectors are degenerate, or whose read throws is simply
# ABSENT from the ``placements`` list rather than emitted as a wrong row.  The
# strict ``from_raw`` parser only accepts ``status == "ok"`` rows, so a
# silently-wrong placement is inexpressible: the emitter must never produce a
# row it could not fully and correctly populate.  A hosted door/window carries
# its ``host_id``/``host_class`` and its flip flags, so the F5 hosted-flip wave
# reads them straight from this index.
#
# MEASURED (SKLNK_EOM_R26_V2): a CurveBased instance's ``Location`` is a
# LocationCurve, never a LocationPoint.  When the LocationPoint cast comes
# back null the emitter falls back to ``Location as LocationCurve`` and
# records a straight ``Line`` as ``curve_state="line"`` plus its two RAW-feet
# endpoints, or the honest ``curved_unsupported`` marker for anything else
# (arc, spline, unbound) -- the same two-state contract as
# :data:`kukai.ir.decompile.curtain_extract.CURTAIN_EXTRACT_HELPER_CS`'s
# ``__cwCurve`` helper.  The marker starts pessimistic (``curved_unsupported``,
# null endpoints) before the ``Line`` cast/``GetEndPoint`` calls are even
# attempted, so a read that throws partway never masquerades as a
# successfully read line.


FAMILY_PLACEMENT_EXTRACT_HELPER_CS = r"""
// KIR DECOMPILE Wave A1b — read-only FamilyInstance placement helpers.
// Position crosses the wire in RAW internal feet, rotation in RAW radians;
// the offline parser owns unit conversion. No Transaction opens.
Func<XYZ, bool> __fpFiniteXYZ = (__point) =>
    __point != null
    && !Double.IsNaN(__point.X) && !Double.IsInfinity(__point.X)
    && !Double.IsNaN(__point.Y) && !Double.IsInfinity(__point.Y)
    && !Double.IsNaN(__point.Z) && !Double.IsInfinity(__point.Z);
Func<double, bool> __fpFinite = (__value) =>
    !Double.IsNaN(__value) && !Double.IsInfinity(__value);
Func<XYZ, object> __fpRawPoint = (__point) => (object)new double[] {
    __point.X, __point.Y, __point.Z
};
// Normalise an orientation vector to unit length in C# so the offline parser
// (which requires exactly-unit orthogonal vectors) receives a clean pair.  A
// vector whose length is below the degeneracy floor yields null — the whole
// element is then skipped rather than emitted with a bad orientation.
Func<XYZ, object> __fpUnitVector = (__vector) =>
{
    if (!__fpFiniteXYZ(__vector)) return null;
    double __len = Math.Sqrt(
        __vector.X * __vector.X
        + __vector.Y * __vector.Y
        + __vector.Z * __vector.Z);
    if (!__fpFinite(__len) || __len < 1.0e-9) return null;
    return (object)new double[] {
        __vector.X / __len, __vector.Y / __len, __vector.Z / __len
    };
};
Func<ElementId, string> __fpValidIdString = (__id) =>
    (__id == null || __id == ElementId.InvalidElementId)
        ? null : __id.ToString();
// КАЖДОЕ НЕОБЯЗАТЕЛЬНОЕ ЧТЕНИЕ — ПОД СВОИМ СТРАЖЕМ.
//
// Общий try на весь элемент — это и есть форма бага: он превращает отказ
// ОДНОГО свойства в потерю ВСЕЙ строки. Ровно так 12 369 помещений во всех
// моделях никогда не имели точки (починено 2026-07-28, cb9c3b65). Три
// чтения ниже необязательны по построению, поэтому у каждого свой catch, и
// его отказ стоит ровно самого себя.
Func<FamilyInstance, Autodesk.Revit.DB.Location> __fpTryLocation =
    (__instance) =>
{
    try { return __instance.Location; } catch { return null; }
};
// FamilyInstance.HostFace: ссылка на грань, если семейство посажено на
// грань. Замерено по индексу ловушек — свойство есть во всех шести версиях,
// документированных исключений не объявлено.
Func<FamilyInstance, Autodesk.Revit.DB.Reference> __fpTryHostFace =
    (__instance) =>
{
    try { return __instance.HostFace; } catch { return null; }
};
// ТРЕТИЙ ИСТОЧНИК положения. Член объявлен на Autodesk.Revit.DB.Instance
// (все шесть версий, Autodesk <since> 2012), а НЕ на FamilyInstance —
// проверено индексом ловушек, а не памятью: 'FamilyInstance.GetTransform'
// в индексе 35 516 членов отсутствует, и код, написанный по этому имени,
// не собрался бы ни на одной версии.
Func<FamilyInstance, Transform> __fpTryTransform = (__instance) =>
{
    try { return __instance.GetTransform(); } catch { return null; }
};
// A bound straight Line becomes ("line", p0_ft, p1_ft) in RAW internal feet;
// any other curve (arc, spline, unbound, ...) is the honest
// curved_unsupported marker with no endpoints. The marker starts pessimistic
// BEFORE the Line cast/GetEndPoint calls are attempted (mirrors
// curtain_extract's __cwCurve helper), so a read that throws partway never
// masquerades as a successfully read line. Feet, not millimetres: the
// offline parser is this module's single conversion authority.
Func<Curve, Dictionary<string, object>> __fpCurveRow = (__curve) =>
{
    var __row = new Dictionary<string, object>();
    __row["curve_state"] = "curved_unsupported";
    __row["curve_p0_ft"] = null;
    __row["curve_p1_ft"] = null;
    try
    {
        Line __line = __curve as Line;
        if (__line != null && __line.IsBound)
        {
            XYZ __start = __line.GetEndPoint(0);
            XYZ __end = __line.GetEndPoint(1);
            if (__fpFiniteXYZ(__start) && __fpFiniteXYZ(__end))
            {
                __row["curve_state"] = "line";
                __row["curve_p0_ft"] = __fpRawPoint(__start);
                __row["curve_p1_ft"] = __fpRawPoint(__end);
            }
        }
    }
    catch { }
    return __row;
};
"""


_FAMILY_PLACEMENT_BODY_CS = r"""
var __fpRequestedIds = new string[] { __FP_ELEMENT_IDS__ };
long __fpElementBudgetMs = __FP_ELEMENT_BUDGET_MS__L;
long __fpCallBudgetMs = __FP_CALL_BUDGET_MS__L;
var __fpCallWatch = System.Diagnostics.Stopwatch.StartNew();

// §18.2, закон квитанции: КАЖДЫЙ запрошенный id уходит либо строкой в
// placements, либо записью {element_id, reason, typed_reason} в failures.
// Раньше здесь было три немых выхода — break по бюджету, continue на
// неподходящем классе и пустой catch {} — и на живом разборе SOB6.2 они
// съели 242 из 1799 запрошенных элементов (все OST_CurtainWallPanels:
// панель-стена витража не FamilyInstance). Снаружи это неотличимо от дыры
// в возможностях компилятора.
var __fpFailures = new List<object>();
Action<string, string, string, object> __fpFail =
    (__failedId, __reason, __typed, __elapsed) =>
{
    var __failure = new Dictionary<string, object>();
    __failure["element_id"] = __failedId;
    __failure["reason"] = __reason;
    __failure["typed_reason"] = __typed;
    __failure["elapsed_ms"] = __elapsed;
    __fpFailures.Add(__failure);
};

// One bounded collector pass resolves the requested elements by their
// version-safe ElementId.ToString() representation.
var __fpRequestedSet = new HashSet<string>(__fpRequestedIds);
var __fpFound = new Dictionary<string, Element>();
foreach (Element __element in new FilteredElementCollector(__src)
         .WhereElementIsNotElementType())
{
    if (__fpCallWatch.ElapsedMilliseconds >= __fpCallBudgetMs) break;
    string __id = __element.Id.ToString();
    if (__fpRequestedSet.Contains(__id) && !__fpFound.ContainsKey(__id))
    {
        __fpFound[__id] = __element;
        if (__fpFound.Count == __fpRequestedSet.Count) break;
    }
}

// One element's read, as a value: either a complete "ok" row or a typed
// refusal. Expressed as a Func (not goto/flags) because a placement row is
// emitted only when EVERY field could be read -- the early exits are the
// whole point, and a helper that returns them is the only shape in which
// each exit is forced to name itself.
Func<string, Element, Dictionary<string, object>> __fpReadRow =
    (__requestedId, __element) =>
{
    var __outcome = new Dictionary<string, object>();
    __outcome["row"] = null;
    __outcome["reason"] = "read_failed";
    __outcome["typed"] = "read_failed";
    try
    {
        FamilyInstance __instance = __element as FamilyInstance;
        if (__instance == null)
        {
            __outcome["reason"] =
                "not a FamilyInstance: " + __element.GetType().Name;
            __outcome["typed"] = "element_kind_mismatch";
            return __outcome;
        }

        FamilySymbol __symbol = __instance.Symbol;
        if (__symbol == null)
        {
            __outcome["reason"] = "FamilyInstance has no Symbol";
            __outcome["typed"] = "element_kind_mismatch";
            return __outcome;
        }
        Family __family = __symbol.Family;
        if (__family == null)
        {
            __outcome["reason"] = "FamilySymbol has no Family";
            __outcome["typed"] = "element_kind_mismatch";
            return __outcome;
        }

        string __symbolName = __symbol.Name;
        string __familyName = __family.Name;
        if (String.IsNullOrEmpty(__symbolName)
            || String.IsNullOrEmpty(__familyName))
        {
            __outcome["reason"] = "family or type name is empty";
            __outcome["typed"] = "element_kind_mismatch";
            return __outcome;
        }

        // FamilyPlacementType lives on Family (NOT FamilySymbol). Its ToString()
        // is the version-safe enum name the parser's FamilyPlacementType accepts.
        string __placementType =
            __family.FamilyPlacementType.ToString();

        object __hand = __fpUnitVector(__instance.HandOrientation);
        object __facing = __fpUnitVector(__instance.FacingOrientation);
        if (__hand == null || __facing == null)
        {
            __outcome["reason"] = "degenerate hand or facing orientation";
            __outcome["typed"] = "element_kind_mismatch";
            return __outcome;
        }

        var __row = new Dictionary<string, object>();
        __row["element_id"] = __requestedId;
        __row["symbol_id"] = __symbol.Id.ToString();
        __row["type_name"] = __symbolName;
        __row["family_name"] = __familyName;
        __row["placement_type"] = __placementType;
        __row["in_place"] = (object)__family.IsInPlace;
        __row["mirrored"] = (object)__instance.Mirrored;
        __row["hand_flipped"] = (object)__instance.HandFlipped;
        __row["facing_flipped"] = (object)__instance.FacingFlipped;

        Element __super = __instance.SuperComponent;
        __row["super_component_id"] =
            (__super == null) ? null : __super.Id.ToString();

        // GroupId: a valid id becomes a string, InvalidElementId becomes null.
        __row["group_id"] = __fpValidIdString(__instance.GroupId);

        Element __host = __instance.Host;
        if (__host == null)
        {
            __row["host_id"] = null;
            __row["host_class"] = null;
        }
        else
        {
            __row["host_id"] = __host.Id.ToString();
            __row["host_class"] = __host.GetType().Name;
        }

        __row["hand_orientation"] = __hand;
        __row["facing_orientation"] = __facing;
        __row["status"] = "ok";

        // The point+rotation pair is emitted together or not at all (the parser
        // refuses a lone member). A hosted family with no LocationPoint yields
        // an available-flag-false record downstream, an honest extraction fact
        // -- UNLESS its Location is a LocationCurve (MEASURED, SKLNK_EOM_R26_V2:
        // every CurveBased instance in the census is exactly this case), in
        // which case the honest line/curved_unsupported curve pair is read
        // instead so the record is not left unavailable for no reason.
        Autodesk.Revit.DB.Location __rawLocation = __fpTryLocation(__instance);
        LocationPoint __location = __rawLocation as LocationPoint;
        // «Объяснено» = строка сама говорит, ГДЕ элемент или ПОЧЕМУ его
        // положение не точка. Пока это не так, причину обязан назвать
        // блок ниже — молчание здесь и было той самой подстановкой нуля.
        bool __explained = false;
        if (__location != null)
        {
            XYZ __point = null;
            double __rotation = Double.NaN;
            try
            {
                __point = __location.Point;
                __rotation = __location.Rotation;
            }
            catch { __point = null; }
            if (__fpFiniteXYZ(__point) && __fpFinite(__rotation))
            {
                __row["point_ft"] = __fpRawPoint(__point);
                __row["rotation_rad"] = __rotation;
                __explained = true;
            }
        }
        else
        {
            LocationCurve __locCurve = __rawLocation as LocationCurve;
            if (__locCurve != null && __locCurve.Curve != null)
            {
                var __curveRow = __fpCurveRow(__locCurve.Curve);
                __row["curve_state"] = __curveRow["curve_state"];
                __row["curve_p0_ft"] = __curveRow["curve_p0_ft"];
                __row["curve_p1_ft"] = __curveRow["curve_p1_ft"];
                // Даже curved_unsupported — это УЖЕ названная причина
                // ("прямую снять не удалось"), и вторая поверх неё только
                // спорила бы с первой.
                __explained = true;
            }
        }
        if (!__explained)
        {
            // ПОЧЕМУ ТОЧКИ НЕТ — ОТДЕЛЬНЫЙ ФАКТ О МОДЕЛИ.
            //
            // ЗАМЕР 2026-07-29 (четыре документа, поимённо все 7 083
            // элемента с причиной "no captured LocationPoint"): 7 083 из
            // 7 083 — витражные панели. Форма опознаётся КЛАССОМ
            // Autodesk.Revit.DB.Panel, а не именем семейства и не именем
            // категории: имя врёт легко (шаблон, локализация, копия).
            string __absence = "unreadable";
            if (__instance is Autodesk.Revit.DB.Panel)
            {
                __absence = "curtain_grid_generated";
            }
            else if (__fpTryHostFace(__instance) != null)
            {
                __absence = "face_hosted";
            }
            else if (__placementType == "WorkPlaneBased")
            {
                __absence = "work_plane_based";
            }
            __row["location_absence"] = __absence;

            // ТРЕТИЙ ИСТОЧНИК — И ОН НЕ ТОЧКА ВСТАВКИ.
            //
            // У экземпляра без Location положение ЕСТЬ, а точки вставки
            // НЕТ, и это не одно и то же. Трансформ кладётся в СВОИ поля:
            // семейство на грани ставится перегрузкой
            // NewFamilyInstance(Reference face, ...), которой у нас нет, и
            // свободная точка вместо привязки к грани была бы тихой
            // потерей привязки, выглядящей успехом (§18.1). Офлайновый
            // разбор запрещает строке нести точку и трансформ разом, так
            // что подменить одно другим нельзя структурно.
            Transform __xf = __fpTryTransform(__instance);
            if (__xf != null
                && __fpFiniteXYZ(__xf.Origin)
                && __fpUnitVector(__xf.BasisX) != null
                && __fpUnitVector(__xf.BasisY) != null
                && __fpUnitVector(__xf.BasisZ) != null)
            {
                __row["transform_origin_ft"] = __fpRawPoint(__xf.Origin);
                __row["transform_basis_x"] = __fpUnitVector(__xf.BasisX);
                __row["transform_basis_y"] = __fpUnitVector(__xf.BasisY);
                __row["transform_basis_z"] = __fpUnitVector(__xf.BasisZ);
            }
        }
        __outcome["row"] = __row;
        __outcome["reason"] = null;
        __outcome["typed"] = null;
        return __outcome;
    }
    catch (Exception __readError)
    {
        // fail-closed by absence from PLACEMENTS, never from the ANSWER.
        __outcome["row"] = null;
        __outcome["reason"] =
            "placement read failed: " + __readError.GetType().Name;
        __outcome["typed"] = "read_failed";
        return __outcome;
    }
};

var __fpPlacements = new List<object>();
bool __fpBudgetOut = false;
foreach (string __requestedId in __fpRequestedIds)
{
    if (__fpBudgetOut
        || __fpCallWatch.ElapsedMilliseconds >= __fpCallBudgetMs)
    {
        // Хвост пачки после исчерпания бюджета — не «ничего не нашли», а
        // «не смотрели»: каждый оставшийся id получает свою квитанцию.
        __fpBudgetOut = true;
        __fpFail(__requestedId, "call_budget_exhausted",
                 "call_budget_exhausted",
                 (object)__fpCallWatch.ElapsedMilliseconds);
        continue;
    }

    Element __element = null;
    if (!__fpFound.TryGetValue(__requestedId, out __element)
        || __element == null)
    {
        __fpFail(__requestedId, "element_unresolved", "element_unresolved",
                 null);
        continue;
    }

    var __fpElementWatch = System.Diagnostics.Stopwatch.StartNew();
    var __fpOutcome = __fpReadRow(__requestedId, __element);
    long __fpElementElapsed = __fpElementWatch.ElapsedMilliseconds;
    if (__fpElementElapsed >= __fpElementBudgetMs)
    {
        // Cooperative element budget: a read that overran is NOT trusted --
        // its partial row is discarded and the overrun is reported. Every id
        // after this one gets a call_budget-style receipt of its own on the
        // next iteration, so the tail is accounted for rather than dropped.
        __fpFail(__requestedId, "time_budget_exceeded",
                 "time_budget_exceeded", (object)__fpElementElapsed);
        __fpBudgetOut = true;
        continue;
    }
    object __fpRow = __fpOutcome["row"];
    if (__fpRow == null)
    {
        __fpFail(__requestedId,
                 __fpOutcome["reason"] == null
                     ? "read_failed" : __fpOutcome["reason"].ToString(),
                 __fpOutcome["typed"] == null
                     ? "read_failed" : __fpOutcome["typed"].ToString(),
                 null);
        continue;
    }
    __fpPlacements.Add(__fpRow);
}
return new Dictionary<string, object> {
    {"schema_version", "kir-decompile-family-placement-extract/1"},
    {"placements", __fpPlacements},
    {"failures", __fpFailures}
};
"""


def _csharp_string(value: str) -> str:
    return cs_string_literal(value)


def _normalize_ids(element_ids: Sequence[str | int]) -> list[str]:
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
    if not normalized:
        raise ValueError("at least one element id is required")
    if len(set(normalized)) != len(normalized):
        raise ValueError("element_ids must be unique")
    return normalized


def _validate_budgets(element_budget_ms: int, call_budget_ms: int) -> None:
    for field_name, value in (
        ("element_budget_ms", element_budget_ms),
        ("call_budget_ms", call_budget_ms),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")
        if value > 9_223_372_036_854_775_807:
            raise ValueError(f"{field_name} exceeds the C# Int64 range")


def build_family_placement_extract_cs(
    element_ids: Sequence[str | int],
    *,
    element_budget_ms: int = 2_000,
    call_budget_ms: int = 20_000,
    link_title: str | None = None,
) -> str:
    """Emit one deterministic, read-only FamilyInstance placement Execute body.

    Numeric ids are resolved by their version-safe ``ElementId.ToString()``
    representation, avoiding the 2021/2024 ``int``/``long`` constructor fork.
    The two time budgets are cooperative fail-safes (mirroring
    :func:`kukai.ir.decompile.curve_extract.build_curve_extract_cs`): elapsed
    time is checked before the resolve loop, before each element's read, and
    after each element.

    Position crosses the wire as RAW internal feet and rotation as RAW
    radians; :meth:`FamilyPlacementRecord.from_raw` owns the sole
    feet→millimetre / radian→degree conversion.  Only a fully-read, valid
    placement is emitted: a non-``FamilyInstance``, a degenerate orientation,
    or a read that throws is left absent from the ``placements`` list rather
    than mislabelled as a usable row (I2).

    When ``Location as LocationPoint`` is null the emitter falls back to
    ``Location as LocationCurve`` (MEASURED, SKLNK_EOM_R26_V2: every
    ``CurveBased`` instance in that census is exactly this case) and emits
    the straight-line/curved_unsupported ``curve_state`` pair in the same
    RAW-feet dialect, also owned by :meth:`FamilyPlacementRecord.from_raw`.

    ``link_title`` — читать не ХОЗЯИНА, а его СВЯЗЬ с таким ``Document.Title``.
    ИМЕННО ЭТА СТАДИЯ дала замер 30.07: слепок связанной электрики, снятый из
    окна сантехники, вернул 1837 квитанций из 2650 элементов (1770
    ``element_unresolved``) — коллектор искал id связи в документе хозяина. А
    20 раз хозяин ОТВЕТИЛ: элемент связи ``1442277``
    (``OST_ElectricalEquipment``) получил семейство ``Tee - Generic`` —
    тройник САНТЕХНИКИ. Пустая квитанция говорит «не прочитал» громко; такая
    строка врёт молча, и опровергнуть её нечем.
    """

    normalized = _normalize_ids(element_ids)
    _validate_budgets(element_budget_ms, call_budget_ms)

    body = _FAMILY_PLACEMENT_BODY_CS.replace(
        "__FP_ELEMENT_IDS__",
        ", ".join(_csharp_string(value) for value in normalized),
        1,
    )
    body = body.replace("__FP_ELEMENT_BUDGET_MS__", str(element_budget_ms))
    body = body.replace("__FP_CALL_BUDGET_MS__", str(call_budget_ms))
    if "__FP_" in body:
        raise FamilyPlacementPayloadError(
            "internal family-placement emitter placeholder was not resolved")
    return (
        source_binding_cs(link_title)
        + "\n" + FAMILY_PLACEMENT_EXTRACT_HELPER_CS.strip()
        + "\n" + body.strip())


__all__ = [
    "FAMILY_PLACEMENT_INDEX_SCHEMA_VERSION",
    "FAMILY_PLACEMENT_EXTRACT_SCHEMA_VERSION",
    "FAMILY_PLACEMENT_EXTRACT_HELPER_CS",
    # Re-exported, not re-invented: the curve_state contract is owned by
    # curtain_extract.CurveState and reused verbatim here (module docstring).
    "CurveState",
    "FamilyPlacementExtraction",
    "FamilyPlacementPayloadError",
    "FamilyPlacementRecord",
    "FamilyPlacementType",
    "build_family_placement_extract_cs",
    "parse_family_placement_index",
]
