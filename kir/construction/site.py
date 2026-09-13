"""The deterministic core of the digital construction site.

The building and its temporal execution are different graphs. KIR describes
the product; this module describes the resources the product can be built
with. That is why a crane or a hoist does not become a permanent BIM element
and does not enter KIR's registry of writing operations.

The strength of each claim is named explicitly:

* the rated load chart is checked against conservative ranges;
* an ``exact_zone`` obstacle gives a confirmed prohibition;
* a shell from ``kir.clash`` only ever contains the real body, so its
  intersection yields ``unknown``, not a fabricated clash;
* an unknown mass is never turned into zero and can never earn ``feasible``.

🔴 **QUARANTINE. A NAMED ABSENCE WITHOUT WHICH THE LIST ABOVE READS AS
COMPLETE (measured 02.09.2026, by grepping for the property, tree
``70e62a2``).** The crane's counter-jib body is NOT PRESENT AS AN OBJECT in
this module: occurrences of ``контрстрел`` / ``counter`` / ``tail`` /
``противовес`` / ``балласт`` across 998 lines — **zero**. ``_conflicts``
builds a capsule around segments of the LOAD PATH with radius
``load_radius_mm + clearance_mm`` and around nothing else. Hence:
**an obstacle in the counter-jib's sector cannot turn a single scenario
red** — not because the check is soft, but because there is nothing there
to check, and the experiment has exactly one possible outcome (canon shape 8).

Until that exists, ``Feasibility.FEASIBLE`` from here is a claim about the
LOAD PATH, not about the lift, and is not an engineering conclusion. The
module is inert: nothing in the tracked code calls it except its own example.

The numbers here are millimeters, kilograms, and seconds. No hidden
conversions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Iterable, Sequence

from kir.clash import geom as G

CONSTRUCTION_SCHEMA = "kir-construction-site/1"
_EPS = 1e-6
_MAX_SLEW_STEP_DEG = 5.0
# An exact touch of the inflated trajectory counts as a conflict. That is
# why a level derived from the top of an obstacle must sit at least one
# named numeric clearance higher, or else the very candidate found
# automatically turns red at its own boundary because of the correct
# contact rule.
_PATH_NUMERIC_MARGIN_MM = 1e-3

Point2 = tuple[float, float]
Point3 = tuple[float, float, float]


class ConstructionError(ValueError):
    """The input does not allow an honest claim about the construction site."""


class CoverageState(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    NONE = "none"


class Feasibility(str, Enum):
    FEASIBLE = "feasible"
    REFUSED = "refused"
    UNKNOWN = "unknown"


class GeometryAuthority(str, Enum):
    EXACT = "exact"
    OUTER_ENVELOPE = "outer_envelope"


class ObstacleAuthority(str, Enum):
    """What the obstacle's geometry actually means."""

    EXACT_ZONE = "exact_zone"
    OUTER_ENVELOPE = "outer_envelope"


def _number(value: Any, name: str, *, positive: bool = False,
            nonnegative: bool = False) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(float(value))):
        raise ConstructionError(f"{name} must be a finite number")
    out = float(value)
    if positive and out <= 0.0:
        raise ConstructionError(f"{name} must be positive")
    if nonnegative and out < 0.0:
        raise ConstructionError(f"{name} must be non-negative")
    return out


def _identifier(value: Any, name: str = "id") -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConstructionError(f"{name} must be a non-empty string")
    return value.strip()


def _point3(value: Sequence[float], name: str) -> Point3:
    if (isinstance(value, (str, bytes)) or not isinstance(value, Sequence)
            or len(value) != 3):
        raise ConstructionError(f"{name} must contain exactly three numbers")
    return tuple(_number(item, f"{name}[{index}]")
                 for index, item in enumerate(value))  # type: ignore[return-value]


def _point2(value: Sequence[float], name: str) -> Point2:
    if (isinstance(value, (str, bytes)) or not isinstance(value, Sequence)
            or len(value) != 2):
        raise ConstructionError(f"{name} must contain exactly two numbers")
    return tuple(_number(item, f"{name}[{index}]")
                 for index, item in enumerate(value))  # type: ignore[return-value]


def _enum(value: Any, enum_type: type[Enum], name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        allowed = sorted(item.value for item in enum_type)
        raise ConstructionError(f"{name} must be one of {allowed}") from exc


def _unique_ids(items: Iterable[Any], name: str) -> tuple[Any, ...]:
    out = tuple(items)
    ids = [getattr(item, "id", None) for item in out]
    if len(ids) != len(set(ids)):
        raise ConstructionError(f"{name} ids must be unique")
    return out


@dataclass(frozen=True, slots=True)
class CapacityBand:
    """The rated load capacity up to and including the radius boundary.

    There is no interpolation between chart rows: the first outer row is
    taken. This is more conservative than linear guessing and matches the
    shape of tables where each row sets the allowance up to the next radius.
    """

    max_radius_mm: float
    max_gross_load_kg: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_radius_mm", _number(
            self.max_radius_mm, "max_radius_mm", positive=True))
        object.__setattr__(self, "max_gross_load_kg", _number(
            self.max_gross_load_kg, "max_gross_load_kg", positive=True))

    def to_dict(self) -> dict[str, float]:
        return {"max_radius_mm": self.max_radius_mm,
                "max_gross_load_kg": self.max_gross_load_kg}


@dataclass(frozen=True, slots=True)
class TowerCrane:
    id: str
    base_mm: Point3
    max_hook_height_mm: float
    min_radius_mm: float
    load_chart: tuple[CapacityBand, ...]
    hoist_speed_mm_s: float
    trolley_speed_mm_s: float
    slew_speed_deg_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "crane.id"))
        object.__setattr__(self, "base_mm", _point3(self.base_mm, "base_mm"))
        object.__setattr__(self, "max_hook_height_mm", _number(
            self.max_hook_height_mm, "max_hook_height_mm", positive=True))
        object.__setattr__(self, "min_radius_mm", _number(
            self.min_radius_mm, "min_radius_mm", nonnegative=True))
        chart = tuple(self.load_chart)
        if not chart or not all(isinstance(item, CapacityBand) for item in chart):
            raise ConstructionError("load_chart must contain CapacityBand values")
        for previous, current in zip(chart, chart[1:]):
            if current.max_radius_mm <= previous.max_radius_mm:
                raise ConstructionError(
                    "load_chart radii must be strictly increasing")
            if current.max_gross_load_kg > previous.max_gross_load_kg + _EPS:
                raise ConstructionError(
                    "load_chart capacity must not increase with radius")
        if chart[-1].max_radius_mm <= self.min_radius_mm:
            raise ConstructionError(
                "load_chart outer radius must exceed min_radius_mm")
        object.__setattr__(self, "load_chart", chart)
        for field_name in ("hoist_speed_mm_s", "trolley_speed_mm_s",
                           "slew_speed_deg_s"):
            object.__setattr__(self, field_name, _number(
                getattr(self, field_name), field_name, positive=True))

    @property
    def max_radius_mm(self) -> float:
        return self.load_chart[-1].max_radius_mm

    @property
    def max_hook_z_mm(self) -> float:
        return self.base_mm[2] + self.max_hook_height_mm

    def capacity_at(self, radius_mm: float) -> float | None:
        radius = _number(radius_mm, "radius_mm", nonnegative=True)
        if radius + _EPS < self.min_radius_mm:
            return None
        for band in self.load_chart:
            if radius <= band.max_radius_mm + _EPS:
                return band.max_gross_load_kg
        return None

    def with_base(self, base_mm: Sequence[float]) -> "TowerCrane":
        return replace(self, base_mm=_point3(base_mm, "base_mm"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_mm": list(self.base_mm),
            "min_radius_mm": self.min_radius_mm,
            "max_radius_mm": self.max_radius_mm,
            "max_hook_height_mm": self.max_hook_height_mm,
            "max_hook_z_mm": self.max_hook_z_mm,
            "load_chart": [item.to_dict() for item in self.load_chart],
            "speeds": {"hoist_mm_s": self.hoist_speed_mm_s,
                       "trolley_mm_s": self.trolley_speed_mm_s,
                       "slew_deg_s": self.slew_speed_deg_s},
        }


@dataclass(frozen=True, slots=True)
class CoverageTarget:
    """An addressable part of the building and, if present, its installation hook/mass."""

    id: str
    lo_mm: Point3
    hi_mm: Point3
    hook_point_mm: Point3 | None = None
    gross_load_kg: float | None = None
    geometry_authority: GeometryAuthority = GeometryAuthority.EXACT

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "target.id"))
        lo = _point3(self.lo_mm, "lo_mm")
        hi = _point3(self.hi_mm, "hi_mm")
        if any(lo[index] > hi[index] for index in range(3)):
            raise ConstructionError("target lo_mm must not exceed hi_mm")
        object.__setattr__(self, "lo_mm", lo)
        object.__setattr__(self, "hi_mm", hi)
        if self.hook_point_mm is not None:
            object.__setattr__(self, "hook_point_mm", _point3(
                self.hook_point_mm, "hook_point_mm"))
        if self.gross_load_kg is not None:
            object.__setattr__(self, "gross_load_kg", _number(
                self.gross_load_kg, "gross_load_kg", positive=True))
        object.__setattr__(self, "geometry_authority", _enum(
            self.geometry_authority, GeometryAuthority,
            "target.geometry_authority"))

    @classmethod
    def from_hull_record(
            cls, record: Any, *, hook_point_mm: Sequence[float] | None = None,
            gross_load_kg: float | None = None) -> "CoverageTarget":
        """Feed an existing clash shell straight into the coverage
        calculation.

        The bounding envelope is enough for a conservative answer about
        spatial coverage. It carries neither the sling point nor the mass,
        so those remain explicit arguments and default to
        ``liftability=unknown``.
        """
        try:
            lo, hi = record.bounds()
            source_id = record.source_id
        except (AttributeError, TypeError) as exc:
            raise ConstructionError(
                "from_hull_record needs source_id and bounds()") from exc
        return cls(id=str(source_id), lo_mm=lo, hi_mm=hi,
                   hook_point_mm=hook_point_mm, gross_load_kg=gross_load_kg,
                   geometry_authority=GeometryAuthority.OUTER_ENVELOPE)


@dataclass(frozen=True, slots=True)
class CoverageAssessment:
    crane_id: str
    target_id: str
    coverage: CoverageState
    geometry_authority: GeometryAuthority
    coverage_assertion: str
    liftability: Feasibility
    reasons: tuple[str, ...]
    min_radius_mm: float
    max_radius_mm: float
    hook_radius_mm: float | None
    height_margin_mm: float
    available_capacity_kg: float | None
    gross_load_kg: float | None
    capacity_margin_kg: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "crane_id": self.crane_id,
            "target_id": self.target_id,
            "coverage": self.coverage.value,
            "geometry_authority": self.geometry_authority.value,
            "coverage_assertion": self.coverage_assertion,
            "liftability": self.liftability.value,
            "reasons": list(self.reasons),
            "radial_range_mm": [self.min_radius_mm, self.max_radius_mm],
            "hook_radius_mm": self.hook_radius_mm,
            "height_margin_mm": self.height_margin_mm,
            "available_capacity_kg": self.available_capacity_kg,
            "gross_load_kg": self.gross_load_kg,
            "capacity_margin_kg": self.capacity_margin_kg,
        }


@dataclass(frozen=True, slots=True)
class CoverageReport:
    crane: TowerCrane
    assessments: tuple[CoverageAssessment, ...]

    @property
    def census(self) -> dict[str, dict[str, int]]:
        coverage = {state.value: 0 for state in CoverageState}
        liftability = {state.value: 0 for state in Feasibility}
        for item in self.assessments:
            coverage[item.coverage.value] += 1
            liftability[item.liftability.value] += 1
        assert sum(coverage.values()) == len(self.assessments)
        assert sum(liftability.values()) == len(self.assessments)
        return {"coverage": coverage, "liftability": liftability}

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CONSTRUCTION_SCHEMA,
                "kind": "tower_crane_coverage",
                "units": {"length": "mm", "mass": "kg", "time": "s"},
                "assertion": "declared_equipment_and_target_inputs",
                "crane": self.crane.to_dict(),
                "census": self.census,
                "assessments": [item.to_dict() for item in self.assessments]}


def _radius(base: Point3, point: Point3) -> float:
    return math.hypot(point[0] - base[0], point[1] - base[1])


def _radial_range(base: Point3, lo: Point3, hi: Point3) -> tuple[float, float]:
    bx, by = base[:2]
    dx = (lo[0] - bx if bx < lo[0] else bx - hi[0] if bx > hi[0] else 0.0)
    dy = (lo[1] - by if by < lo[1] else by - hi[1] if by > hi[1] else 0.0)
    minimum = math.hypot(dx, dy)
    maximum = max(math.hypot(x - bx, y - by)
                  for x in (lo[0], hi[0]) for y in (lo[1], hi[1]))
    return minimum, maximum


def _assess_target(crane: TowerCrane,
                   target: CoverageTarget) -> CoverageAssessment:
    minimum, maximum = _radial_range(crane.base_mm, target.lo_mm, target.hi_mm)
    radial_intersection = (
        maximum + _EPS >= crane.min_radius_mm
        and minimum <= crane.max_radius_mm + _EPS)
    vertical_intersection = target.lo_mm[2] <= crane.max_hook_z_mm + _EPS
    full = (minimum + _EPS >= crane.min_radius_mm
            and maximum <= crane.max_radius_mm + _EPS
            and target.hi_mm[2] <= crane.max_hook_z_mm + _EPS)
    coverage = (CoverageState.FULL if full else
                CoverageState.PARTIAL if radial_intersection
                and vertical_intersection else CoverageState.NONE)
    coverage_assertion = (
        "possible" if target.geometry_authority
        is GeometryAuthority.OUTER_ENVELOPE
        and coverage is CoverageState.PARTIAL else "confirmed")

    reasons: list[str] = []
    if coverage is CoverageState.PARTIAL:
        if minimum < crane.min_radius_mm - _EPS:
            reasons.append("volume_enters_inner_dead_zone")
        if maximum > crane.max_radius_mm + _EPS:
            reasons.append("volume_exceeds_outer_radius")
        if target.hi_mm[2] > crane.max_hook_z_mm + _EPS:
            reasons.append("volume_exceeds_hook_height")
    elif coverage is CoverageState.NONE:
        if maximum < crane.min_radius_mm - _EPS:
            reasons.append("volume_inside_inner_dead_zone")
        if minimum > crane.max_radius_mm + _EPS:
            reasons.append("volume_outside_outer_radius")
        if target.lo_mm[2] > crane.max_hook_z_mm + _EPS:
            reasons.append("volume_above_hook_height")

    hook_radius: float | None = None
    available: float | None = None
    margin: float | None = None
    if target.hook_point_mm is None:
        liftability = Feasibility.UNKNOWN
        reasons.append("hook_point_unknown")
    elif target.gross_load_kg is None:
        hook_radius = _radius(crane.base_mm, target.hook_point_mm)
        liftability = Feasibility.UNKNOWN
        reasons.append("gross_load_unknown")
    else:
        hook_radius = _radius(crane.base_mm, target.hook_point_mm)
        available = crane.capacity_at(hook_radius)
        hook_in_height = target.hook_point_mm[2] <= crane.max_hook_z_mm + _EPS
        if available is not None:
            margin = available - target.gross_load_kg
        if available is None:
            liftability = Feasibility.REFUSED
            reasons.append("hook_point_outside_radial_reach")
        elif not hook_in_height:
            liftability = Feasibility.REFUSED
            reasons.append("hook_point_above_hook_height")
        elif margin is not None and margin < -_EPS:
            liftability = Feasibility.REFUSED
            reasons.append("gross_load_exceeds_chart")
        else:
            liftability = Feasibility.FEASIBLE

    return CoverageAssessment(
        crane_id=crane.id, target_id=target.id, coverage=coverage,
        geometry_authority=target.geometry_authority,
        coverage_assertion=coverage_assertion,
        liftability=liftability, reasons=tuple(dict.fromkeys(reasons)),
        min_radius_mm=minimum, max_radius_mm=maximum,
        hook_radius_mm=hook_radius,
        height_margin_mm=crane.max_hook_z_mm - target.hi_mm[2],
        available_capacity_kg=available, gross_load_kg=target.gross_load_kg,
        capacity_margin_kg=margin)


def analyze_crane_coverage(
        crane: TowerCrane,
        targets: Sequence[CoverageTarget]) -> CoverageReport:
    if not isinstance(crane, TowerCrane):
        raise ConstructionError("crane must be TowerCrane")
    checked = _unique_ids(targets, "target")
    if not all(isinstance(item, CoverageTarget) for item in checked):
        raise ConstructionError("targets must contain CoverageTarget values")
    return CoverageReport(crane=crane, assessments=tuple(
        _assess_target(crane, target) for target in checked))


@dataclass(frozen=True, slots=True)
class CranePositionEvaluation:
    base_mm: Point3
    report: CoverageReport
    serviceable_targets: int
    serviceable_known_load_kg: float
    fully_covered_targets: int
    uncovered_targets: int

    def to_dict(self) -> dict[str, Any]:
        return {"base_mm": list(self.base_mm),
                "serviceable_targets": self.serviceable_targets,
                "serviceable_known_load_kg": self.serviceable_known_load_kg,
                "fully_covered_targets": self.fully_covered_targets,
                "uncovered_targets": self.uncovered_targets,
                "coverage": self.report.census,
                "assessments": [item.to_dict()
                                for item in self.report.assessments]}


def rank_crane_positions(
        crane: TowerCrane,
        candidate_bases_mm: Sequence[Sequence[float]],
        targets: Sequence[CoverageTarget]) -> tuple[CranePositionEvaluation, ...]:
    """Recompute the crane at user-supplied points and rank them.

    The function does not invent where a crane foundation can go. Candidates
    must already have passed geotechnical checks, site boundaries, and
    organizational constraints.
    """

    bases = tuple(_point3(item, "candidate_base") for item in candidate_bases_mm)
    if len(bases) != len(set(bases)):
        raise ConstructionError("candidate crane bases must be unique")
    evaluations: list[CranePositionEvaluation] = []
    for base in bases:
        report = analyze_crane_coverage(crane.with_base(base), targets)
        serviceable = [item for item in report.assessments
                       if item.liftability is Feasibility.FEASIBLE]
        evaluations.append(CranePositionEvaluation(
            base_mm=base, report=report,
            serviceable_targets=len(serviceable),
            serviceable_known_load_kg=sum(
                item.gross_load_kg or 0.0 for item in serviceable),
            fully_covered_targets=sum(
                item.coverage is CoverageState.FULL
                for item in report.assessments),
            uncovered_targets=sum(
                item.coverage is CoverageState.NONE
                for item in report.assessments)))
    return tuple(sorted(evaluations, key=lambda item: (
        -item.serviceable_targets, -item.serviceable_known_load_kg,
        -item.fully_covered_targets, item.uncovered_targets, item.base_mm)))


@dataclass(frozen=True, slots=True)
class Obstacle:
    id: str
    hull: G.Hull
    authority: ObstacleAuthority
    label: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "obstacle.id"))
        object.__setattr__(self, "authority", _enum(
            self.authority, ObstacleAuthority, "obstacle.authority"))
        if not isinstance(self.hull, (G.Aabb, G.Prism, G.PrismSet, G.Capsule)):
            raise ConstructionError("obstacle hull is not a kir.clash hull")
        lo, hi = G.hull_bounds(self.hull)
        if not all(math.isfinite(value) for value in (*lo, *hi)):
            raise ConstructionError("obstacle hull must have finite bounds")
        if not isinstance(self.label, str):
            raise ConstructionError("obstacle.label must be a string")

    @classmethod
    def from_hull_record(cls, record: Any) -> "Obstacle":
        """Оболочка разбора содержит тело, но не обязана быть самим телом."""
        try:
            return cls(id=str(record.source_id), hull=record.hull,
                       authority=ObstacleAuthority.OUTER_ENVELOPE,
                       label=str(record.category))
        except AttributeError as exc:
            raise ConstructionError(
                "from_hull_record needs source_id/category/hull") from exc


@dataclass(frozen=True, slots=True)
class LiftRequest:
    id: str
    pickup_mm: Point3
    set_mm: Point3
    gross_load_kg: float
    load_radius_mm: float
    clearance_mm: float = 500.0
    minimum_travel_z_mm: float | None = None
    ignore_obstacle_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "lift.id"))
        object.__setattr__(self, "pickup_mm", _point3(
            self.pickup_mm, "pickup_mm"))
        object.__setattr__(self, "set_mm", _point3(self.set_mm, "set_mm"))
        object.__setattr__(self, "gross_load_kg", _number(
            self.gross_load_kg, "gross_load_kg", positive=True))
        object.__setattr__(self, "load_radius_mm", _number(
            self.load_radius_mm, "load_radius_mm", nonnegative=True))
        object.__setattr__(self, "clearance_mm", _number(
            self.clearance_mm, "clearance_mm", nonnegative=True))
        if self.minimum_travel_z_mm is not None:
            object.__setattr__(self, "minimum_travel_z_mm", _number(
                self.minimum_travel_z_mm, "minimum_travel_z_mm"))
        ignored = tuple(_identifier(item, "ignore_obstacle_id")
                        for item in self.ignore_obstacle_ids)
        if len(ignored) != len(set(ignored)):
            raise ConstructionError("ignore_obstacle_ids must be unique")
        object.__setattr__(self, "ignore_obstacle_ids", ignored)


@dataclass(frozen=True, slots=True)
class MotionSegment:
    equipment_id: str
    action: str
    start_mm: Point3
    end_mm: Point3
    start_s: float
    end_s: float
    envelope_radius_mm: float
    approximation_error_mm: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"equipment_id": self.equipment_id, "action": self.action,
                "start_mm": list(self.start_mm), "end_mm": list(self.end_mm),
                "start_s": self.start_s, "end_s": self.end_s,
                "envelope_radius_mm": self.envelope_radius_mm,
                "approximation_error_mm": self.approximation_error_mm}


@dataclass(frozen=True, slots=True)
class MotionKeyframe:
    equipment_id: str
    time_s: float
    position_mm: Point3
    state: str
    boom_angle_deg: float | None = None
    trolley_radius_mm: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"equipment_id": self.equipment_id, "time_s": self.time_s,
                "position_mm": list(self.position_mm), "state": self.state,
                "boom_angle_deg": self.boom_angle_deg,
                "trolley_radius_mm": self.trolley_radius_mm}


@dataclass(frozen=True, slots=True)
class ObstacleConflict:
    obstacle_id: str
    authority: ObstacleAuthority
    conclusion: str
    segment_index: int
    action: str
    signed_distance_mm: float

    def to_dict(self) -> dict[str, Any]:
        return {"obstacle_id": self.obstacle_id,
                "authority": self.authority.value,
                "conclusion": self.conclusion,
                "segment_index": self.segment_index, "action": self.action,
                "signed_distance_mm": self.signed_distance_mm}


@dataclass(frozen=True, slots=True)
class LiftPlan:
    crane_id: str
    lift_id: str
    feasibility: Feasibility
    reasons: tuple[str, ...]
    motion_order: str | None
    travel_z_mm: float | None
    required_capacity_kg: float
    available_capacity_kg: float | None
    segments: tuple[MotionSegment, ...]
    keyframes: tuple[MotionKeyframe, ...]
    conflicts: tuple[ObstacleConflict, ...]
    approximation_error_mm: float

    @property
    def duration_s(self) -> float:
        return self.keyframes[-1].time_s if self.keyframes else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CONSTRUCTION_SCHEMA, "kind": "tower_crane_lift",
                "units": {"length": "mm", "mass": "kg", "time": "s"},
                "crane_id": self.crane_id, "lift_id": self.lift_id,
                "feasibility": self.feasibility.value,
                "reasons": list(self.reasons),
                "motion_order": self.motion_order,
                "travel_z_mm": self.travel_z_mm,
                "required_capacity_kg": self.required_capacity_kg,
                "available_capacity_kg": self.available_capacity_kg,
                "duration_s": self.duration_s,
                "approximation_error_mm": self.approximation_error_mm,
                "segments": [item.to_dict() for item in self.segments],
                "keyframes": [item.to_dict() for item in self.keyframes],
                "conflicts": [item.to_dict() for item in self.conflicts]}


def _bearing_deg(base: Point3, point: Point3) -> float:
    return math.degrees(math.atan2(point[1] - base[1],
                                   point[0] - base[0])) % 360.0


def _signed_shortest_angle(start: float, end: float) -> float:
    delta = (end - start + 180.0) % 360.0 - 180.0
    return 180.0 if abs(delta + 180.0) <= _EPS else delta


def _polar(base: Point3, radius: float, angle_deg: float, z: float) -> Point3:
    angle = math.radians(angle_deg)
    return (base[0] + radius * math.cos(angle),
            base[1] + radius * math.sin(angle), z)


def _frame(crane: TowerCrane, time_s: float, point: Point3,
           state: str) -> MotionKeyframe:
    return MotionKeyframe(
        equipment_id=crane.id, time_s=time_s, position_mm=point, state=state,
        boom_angle_deg=_bearing_deg(crane.base_mm, point),
        trolley_radius_mm=_radius(crane.base_mm, point))


def _build_crane_motion(
        crane: TowerCrane, lift: LiftRequest, travel_z: float,
        order: str) -> tuple[tuple[MotionSegment, ...],
                             tuple[MotionKeyframe, ...], float]:
    envelope = lift.load_radius_mm + lift.clearance_mm
    segments: list[MotionSegment] = []
    frames: list[MotionKeyframe] = [_frame(
        crane, 0.0, lift.pickup_mm, "pickup")]
    current = lift.pickup_mm
    time_s = 0.0
    max_error = 0.0

    def straight(action: str, end: Point3, speed: float) -> None:
        nonlocal current, time_s
        distance = math.dist(current, end)
        if distance <= _EPS:
            current = end
            return
        end_s = time_s + distance / speed
        segments.append(MotionSegment(
            equipment_id=crane.id, action=action, start_mm=current, end_mm=end,
            start_s=time_s, end_s=end_s, envelope_radius_mm=envelope))
        current, time_s = end, end_s
        frames.append(_frame(crane, time_s, current, action))

    def slew(radius: float, start_angle: float, end_angle: float) -> None:
        nonlocal current, time_s, max_error
        delta = _signed_shortest_angle(start_angle, end_angle)
        if abs(delta) <= _EPS or radius <= _EPS:
            current = _polar(crane.base_mm, radius, end_angle, travel_z)
            return
        count = max(1, math.ceil(abs(delta) / _MAX_SLEW_STEP_DEG))
        step = delta / count
        error = radius * (1.0 - math.cos(math.radians(abs(step)) / 2.0))
        max_error = max(max_error, error)
        for index in range(count):
            end = _polar(crane.base_mm, radius,
                         start_angle + step * (index + 1), travel_z)
            end_s = time_s + abs(step) / crane.slew_speed_deg_s
            segments.append(MotionSegment(
                equipment_id=crane.id, action="slew", start_mm=current,
                end_mm=end, start_s=time_s, end_s=end_s,
                envelope_radius_mm=envelope + error,
                approximation_error_mm=error))
            current, time_s = end, end_s
            frames.append(_frame(crane, time_s, current, "slew"))

    pickup_radius = _radius(crane.base_mm, lift.pickup_mm)
    set_radius = _radius(crane.base_mm, lift.set_mm)
    pickup_angle = _bearing_deg(crane.base_mm, lift.pickup_mm)
    set_angle = _bearing_deg(crane.base_mm, lift.set_mm)
    straight("hoist", (lift.pickup_mm[0], lift.pickup_mm[1], travel_z),
             crane.hoist_speed_mm_s)
    current = _polar(crane.base_mm, pickup_radius, pickup_angle, travel_z)

    if order == "slew_then_trolley":
        slew(pickup_radius, pickup_angle, set_angle)
        straight("trolley", _polar(
            crane.base_mm, set_radius, set_angle, travel_z),
            crane.trolley_speed_mm_s)
    elif order == "trolley_then_slew":
        straight("trolley", _polar(
            crane.base_mm, set_radius, pickup_angle, travel_z),
            crane.trolley_speed_mm_s)
        slew(set_radius, pickup_angle, set_angle)
    else:
        raise ConstructionError(f"unknown crane motion order {order!r}")

    current = (lift.set_mm[0], lift.set_mm[1], travel_z)
    straight("lower", lift.set_mm, crane.hoist_speed_mm_s)
    if frames[-1].state != "lower":
        frames.append(_frame(crane, time_s, lift.set_mm, "placed"))
    else:
        frames[-1] = _frame(crane, time_s, lift.set_mm, "placed")
    return tuple(segments), tuple(frames), max_error


def _conflicts(segments: Sequence[MotionSegment],
               obstacles: Sequence[Obstacle]) -> tuple[ObstacleConflict, ...]:
    out: list[ObstacleConflict] = []
    for index, segment in enumerate(segments):
        swept = G.Capsule(path=(segment.start_mm, segment.end_mm),
                          radius=segment.envelope_radius_mm)
        for obstacle in obstacles:
            distance = G.signed_distance(swept, obstacle.hull)
            if distance <= _EPS:
                conclusion = ("confirmed_intersection" if obstacle.authority
                              is ObstacleAuthority.EXACT_ZONE
                              else "possible_intersection")
                out.append(ObstacleConflict(
                    obstacle_id=obstacle.id, authority=obstacle.authority,
                    conclusion=conclusion, segment_index=index,
                    action=segment.action, signed_distance_mm=distance))
    return tuple(out)


def _empty_lift_plan(crane: TowerCrane, lift: LiftRequest,
                     reasons: Sequence[str], available: float | None
                     ) -> LiftPlan:
    return LiftPlan(
        crane_id=crane.id, lift_id=lift.id,
        feasibility=Feasibility.REFUSED,
        reasons=tuple(dict.fromkeys(reasons)), motion_order=None,
        travel_z_mm=None, required_capacity_kg=lift.gross_load_kg,
        available_capacity_kg=available, segments=(), keyframes=(),
        conflicts=(), approximation_error_mm=0.0)


def plan_tower_crane_lift(
        crane: TowerCrane,
        lift: LiftRequest,
        obstacles: Sequence[Obstacle] = ()) -> LiftPlan:
    """Build the lowest admissible trajectory of the two kinematic orders.

    The jib's arc is approximated with chords no coarser than five degrees.
    Each chord is inflated by its own sagitta, so its capsule contains the
    real arc segment: discretization cannot silently miss an obstruction.
    """

    if not isinstance(crane, TowerCrane) or not isinstance(lift, LiftRequest):
        raise ConstructionError("plan needs TowerCrane and LiftRequest")
    checked = _unique_ids(obstacles, "obstacle")
    if not all(isinstance(item, Obstacle) for item in checked):
        raise ConstructionError("obstacles must contain Obstacle values")
    ignored = set(lift.ignore_obstacle_ids)
    active = tuple(item for item in checked if item.id not in ignored)

    pickup_radius = _radius(crane.base_mm, lift.pickup_mm)
    set_radius = _radius(crane.base_mm, lift.set_mm)
    worst_radius = max(pickup_radius, set_radius)
    available = crane.capacity_at(worst_radius)
    reasons: list[str] = []
    if crane.capacity_at(pickup_radius) is None:
        reasons.append("pickup_outside_radial_reach")
    if crane.capacity_at(set_radius) is None:
        reasons.append("set_outside_radial_reach")
    if max(lift.pickup_mm[2], lift.set_mm[2]) > crane.max_hook_z_mm + _EPS:
        reasons.append("endpoint_above_hook_height")
    if available is not None and lift.gross_load_kg > available + _EPS:
        reasons.append("gross_load_exceeds_chart_at_worst_radius")
    if available is None or reasons:
        return _empty_lift_plan(crane, lift, reasons, available)

    base_level = max(lift.pickup_mm[2], lift.set_mm[2],
                     lift.minimum_travel_z_mm
                     if lift.minimum_travel_z_mm is not None else -math.inf)
    envelope = lift.load_radius_mm + lift.clearance_mm
    # A height candidate must account not only for the load and the
    # regulatory clearance, but also for the chord inflation with which we
    # conservatively cover the real arc. Otherwise the discretizer will
    # honestly find a conflict at a level the planner itself declared
    # sufficient.
    arc_bound = worst_radius * (
        1.0 - math.cos(math.radians(_MAX_SLEW_STEP_DEG) / 2.0))
    levels = {base_level}
    for obstacle in active:
        _lo, hi = G.hull_bounds(obstacle.hull)
        candidate = (hi[2] + envelope + arc_bound
                     + _PATH_NUMERIC_MARGIN_MM)
        if candidate > base_level + _EPS:
            levels.add(candidate)
    levels = {level for level in levels
              if level <= crane.max_hook_z_mm + _EPS}
    if not levels:
        return _empty_lift_plan(
            crane, lift, ("no_travel_level_below_hook_limit",), available)

    candidates: list[LiftPlan] = []
    for travel_z in sorted(levels):
        for order in ("slew_then_trolley", "trolley_then_slew"):
            segments, frames, error = _build_crane_motion(
                crane, lift, travel_z, order)
            conflicts = _conflicts(segments, active)
            confirmed = sum(item.authority is ObstacleAuthority.EXACT_ZONE
                            for item in conflicts)
            possible = len(conflicts) - confirmed
            feasibility = (Feasibility.REFUSED if confirmed else
                           Feasibility.UNKNOWN if possible else
                           Feasibility.FEASIBLE)
            candidate_reasons = (
                ("confirmed_path_intersection",) if confirmed else
                ("possible_path_intersection_with_outer_envelope",)
                if possible else ())
            candidates.append(LiftPlan(
                crane_id=crane.id, lift_id=lift.id,
                feasibility=feasibility, reasons=candidate_reasons,
                motion_order=order, travel_z_mm=travel_z,
                required_capacity_kg=lift.gross_load_kg,
                available_capacity_kg=available,
                segments=segments, keyframes=frames, conflicts=conflicts,
                approximation_error_mm=error))

    rank = {Feasibility.FEASIBLE: 0, Feasibility.UNKNOWN: 1,
            Feasibility.REFUSED: 2}
    return min(candidates, key=lambda item: (
        rank[item.feasibility],
        sum(conf.authority is ObstacleAuthority.EXACT_ZONE
            for conf in item.conflicts),
        len(item.conflicts), item.travel_z_mm or 0.0,
        item.duration_s, item.motion_order or ""))


@dataclass(frozen=True, slots=True)
class HoistStop:
    id: str
    elevation_mm: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "stop.id"))
        object.__setattr__(self, "elevation_mm", _number(
            self.elevation_mm, "elevation_mm"))


@dataclass(frozen=True, slots=True)
class MaterialHoist:
    id: str
    position_xy_mm: Point2
    stops: tuple[HoistStop, ...]
    max_gross_load_kg: float
    up_speed_mm_s: float
    down_speed_mm_s: float
    load_time_s: float
    unload_time_s: float
    door_cycle_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "hoist.id"))
        object.__setattr__(self, "position_xy_mm", _point2(
            self.position_xy_mm, "position_xy_mm"))
        stops = _unique_ids(self.stops, "stop")
        if not stops or not all(isinstance(item, HoistStop) for item in stops):
            raise ConstructionError("hoist stops must contain HoistStop values")
        elevations = [item.elevation_mm for item in stops]
        if len(elevations) != len(set(elevations)):
            raise ConstructionError("hoist stop elevations must be unique")
        object.__setattr__(self, "stops", stops)
        for field_name in ("max_gross_load_kg", "up_speed_mm_s",
                           "down_speed_mm_s"):
            object.__setattr__(self, field_name, _number(
                getattr(self, field_name), field_name, positive=True))
        for field_name in ("load_time_s", "unload_time_s", "door_cycle_s"):
            object.__setattr__(self, field_name, _number(
                getattr(self, field_name), field_name, nonnegative=True))

    def stop(self, stop_id: str) -> HoistStop | None:
        return next((item for item in self.stops if item.id == stop_id), None)


@dataclass(frozen=True, slots=True)
class HoistTripRequest:
    id: str
    from_stop: str
    to_stop: str
    gross_load_kg: float
    start_s: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "trip.id"))
        object.__setattr__(self, "from_stop", _identifier(
            self.from_stop, "from_stop"))
        object.__setattr__(self, "to_stop", _identifier(
            self.to_stop, "to_stop"))
        if self.from_stop == self.to_stop:
            raise ConstructionError("hoist trip must connect two stops")
        object.__setattr__(self, "gross_load_kg", _number(
            self.gross_load_kg, "gross_load_kg", positive=True))
        object.__setattr__(self, "start_s", _number(
            self.start_s, "start_s", nonnegative=True))


@dataclass(frozen=True, slots=True)
class HoistTripPlan:
    hoist_id: str
    trip_id: str
    feasibility: Feasibility
    reasons: tuple[str, ...]
    duration_s: float
    segments: tuple[MotionSegment, ...]
    keyframes: tuple[MotionKeyframe, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"schema": CONSTRUCTION_SCHEMA, "kind": "hoist_trip",
                "units": {"length": "mm", "mass": "kg", "time": "s"},
                "hoist_id": self.hoist_id, "trip_id": self.trip_id,
                "feasibility": self.feasibility.value,
                "reasons": list(self.reasons), "duration_s": self.duration_s,
                "segments": [item.to_dict() for item in self.segments],
                "keyframes": [item.to_dict() for item in self.keyframes]}


def plan_hoist_trip(hoist: MaterialHoist,
                    trip: HoistTripRequest) -> HoistTripPlan:
    if not isinstance(hoist, MaterialHoist) or not isinstance(
            trip, HoistTripRequest):
        raise ConstructionError("plan needs MaterialHoist and HoistTripRequest")
    source, target = hoist.stop(trip.from_stop), hoist.stop(trip.to_stop)
    reasons: list[str] = []
    if source is None:
        reasons.append("from_stop_unknown")
    if target is None:
        reasons.append("to_stop_unknown")
    if trip.gross_load_kg > hoist.max_gross_load_kg + _EPS:
        reasons.append("gross_load_exceeds_hoist_capacity")
    if reasons or source is None or target is None:
        return HoistTripPlan(
            hoist_id=hoist.id, trip_id=trip.id,
            feasibility=Feasibility.REFUSED,
            reasons=tuple(reasons), duration_s=0.0, segments=(), keyframes=())

    x, y = hoist.position_xy_mm
    start = (x, y, source.elevation_mm)
    end = (x, y, target.elevation_mm)
    depart_s = trip.start_s + hoist.load_time_s + hoist.door_cycle_s
    speed = (hoist.up_speed_mm_s if target.elevation_mm > source.elevation_mm
             else hoist.down_speed_mm_s)
    arrive_s = depart_s + abs(target.elevation_mm - source.elevation_mm) / speed
    finish_s = arrive_s + hoist.unload_time_s + hoist.door_cycle_s
    action = "hoist_up" if target.elevation_mm > source.elevation_mm else "hoist_down"
    frames = (
        MotionKeyframe(hoist.id, trip.start_s, start, "loading"),
        MotionKeyframe(hoist.id, depart_s, start, "depart"),
        MotionKeyframe(hoist.id, arrive_s, end, "arrive"),
        MotionKeyframe(hoist.id, finish_s, end, "complete"),
    )
    segment = MotionSegment(
        equipment_id=hoist.id, action=action, start_mm=start, end_mm=end,
        start_s=depart_s, end_s=arrive_s, envelope_radius_mm=0.0)
    return HoistTripPlan(
        hoist_id=hoist.id, trip_id=trip.id,
        feasibility=Feasibility.FEASIBLE, reasons=(),
        duration_s=finish_s - trip.start_s,
        segments=(segment,), keyframes=frames)


__all__ = (
    "CONSTRUCTION_SCHEMA", "CapacityBand", "ConstructionError",
    "CoverageAssessment", "CoverageReport", "CoverageState",
    "CoverageTarget", "CranePositionEvaluation", "Feasibility",
    "GeometryAuthority", "HoistStop", "HoistTripPlan", "HoistTripRequest", "LiftPlan",
    "LiftRequest", "MaterialHoist", "MotionKeyframe", "MotionSegment",
    "Obstacle", "ObstacleAuthority", "ObstacleConflict", "TowerCrane",
    "analyze_crane_coverage", "plan_hoist_trip", "plan_tower_crane_lift",
    "rank_crane_positions")
