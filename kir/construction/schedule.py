"""A deterministic state model of a constrained construction site.

Panels, cranes, a crew, and work zones. The model answers one question:
WHEN and IN WHAT ORDER the site's state changes, given the geometry,
dependencies, and resource unavailability windows.

What the module does
---------------------
* Typed tasks: panel i — ``deliver`` (crane) → ``install`` (crew)
  → ``release`` (the zone is freed).
* Dependencies: ``install`` after ``deliver`` of the same panel; ``release`` after
  ``install``; ``deliver`` of panel i+1 after ``install`` of panel i. Additional
  edges are given by the input; a cycle is the named refusal ``cyclic_dependency``.
* Resource occupancy: the crane is busy delivering, the crew is busy
  installing, a zone belongs to ONE panel from the start of delivery to the end of release.
* Discrete event simulation: a list of events with a time, a cause, and a
  sequence number. Identical input gives a byte-for-byte identical
  :meth:`ScheduleResult.to_json`.
* ``pause(t)`` / ``resume()``: the state is laid out as data
  (:class:`SiteState`), resumption continues from the same event, and already installed
  panels are not installed again. The outcome of a continuous run and an interrupted one
  match byte-for-byte.
* A delay (the crane is unavailable from t1 to t2) and an obstruction (a zone is occupied by an intrusion)
  — both are :class:`Unavailability`. They shift task start times, and the shift is visible in
  the cause of the ``task_started`` event, not only in the report text.
* Crane envelope: :class:`CraneEnvelope` — a ring from ``min_radius_mm ..
  max_radius_mm`` and a hook ceiling. If a panel is given a plan footprint
  (``plan_half_extent_mm``), its WHOLE footprint is checked, not the load's point;
  going outside the ring or above the ceiling is the named refusal ``panel_out_of_reach``, not
  a silent "lifted it."
* Delivery duration can be a CONSEQUENCE rather than an input. If the crane
  declares ``kinematics`` (a ready-made :class:`~kir.construction.site.TowerCrane`
  with speeds and a load chart), and the panel promised a rigging point
  (``pickup_mm``/``gross_load_kg``/``load_radius_mm``), the delivery is computed by
  :func:`~kir.construction.site.plan_tower_crane_lift` along a trajectory. Every
  event carries the PROVENANCE of its own number: ``duration_source`` — ``declared``
  or ``trajectory``. If the lift planner refuses, the refusal becomes a named one
  (``lift_path_blocked``, ``panel_over_capacity``,
  ``panel_out_of_reach``), and its ``unknown`` becomes a separate name
  ``lift_feasibility_unknown``: "maybe" is never passed off as a duration.
* A zone can be a POLYGON (``WorkZone.footprint_mm``, mm). Then a panel's
  footprint must lie inside the zone at the moment of installation, or the named refusal
  ``panel_outside_zone``. An intrusion can be a BODY (:class:`Intrusion` —
  a convex polygon × ``[z0, z1]`` and a time window): which zone it occupies,
  is decided by :func:`kir.clash.geom.signed_distance`, not by matching names.
* There can be several cranes and zones. A panel takes the FIRST crane, in declared
  order, that can reach it; the chain "next delivery after installing the
  previous one" runs PER ZONE. So two cranes with different reach zones
  give parallel deliveries, while one work zone still holds one
  panel.

🔴 BOUNDARY. WHAT THE MODULE DOES NOT ASSERT
----------------------------------------------
1. There is NO construction-safety conclusion here. The words «safety» and
   «безопасность» deliberately appear in no output field: a scenario that passed
   is the feasibility of the SCHEDULE given the stated numbers, and it is
   nothing else. Passing it off as a safety assessment is forbidden.
2. Real workers are not modeled. :class:`Crew` is a depersonalized resource with
   an identifier and a size; there are no names, no personal data, no tracking
   of any specific person's labor here, and there will not be.
3. There are no cameras, viewpoints, or animation here. :meth:`ScheduleResult.state_at`
   returns the STATE at a point in time; any animation must follow
   this state, not replace it and not invent frames between events.
4. The crane's body as an object (counter-jib, counterweight) is not checked — it doesn't exist
   in :mod:`kir.construction.site` either. The reach check speaks to a panel's plan
   footprint relative to the outreach ring, and only to that.
5. Collisions between two cranes are NOT checked: there is no crane body as an
   object, so there is nothing to check. Multiple cranes are simply multiple
   independent scheduling resources and nothing more.
6. A panel's containment within a zone is checked IN PLAN. The module makes no
   assertion that "the panel is within the zone by height"; a zone's ``[z0_mm, z1_mm]`` is needed
   only for an intrusion's body.
7. ``duration_source="trajectory"`` is the time of the LOAD'S PATH at the declared
   speeds. Rigging, unrigging, and fine positioning are not included: they
   don't exist in :mod:`kir.construction.site`.
8. The units are millimeters and seconds. No hidden conversions.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from kir.clash import geom as G

from .site import (
    ConstructionError,
    Feasibility,
    LiftRequest,
    Obstacle,
    Point2,
    Point3,
    TowerCrane,
    _identifier,
    _number,
    _point2,
    _point3,
    plan_tower_crane_lift,
)

SCHEDULE_SCHEMA = "kir-construction-schedule/2"
STATE_SCHEMA = "kir-construction-schedule-state/2"

_EPS = 1e-9
#: The GEOMETRY tolerance. Numbers here are millimeters, and areas are
#: square millimeters, so geometry has its own tolerance, and it is not
#: mixed with the time tolerance ``_EPS``: one constant for two subjects
#: silently carries an error from one into the other.
_GEOM_EPS = 1e-6
_QUANT = 6

#: The full closed list of this module's named refusals.
REFUSAL_CODES: tuple[str, ...] = (
    "cyclic_dependency",
    "dependency_unknown_task",
    "lift_feasibility_unknown",
    "lift_path_blocked",
    "panel_out_of_reach",
    "panel_outside_zone",
    "panel_over_capacity",
    "schedule_deadlock",
    "state_does_not_match_plan",
    "state_is_inconsistent",
)

TASK_DELIVER = "deliver"
TASK_INSTALL = "install"
TASK_RELEASE = "release"
_KIND_RANK = {TASK_DELIVER: 0, TASK_INSTALL: 1, TASK_RELEASE: 2}


class ScheduleRefused(ConstructionError):
    """A refusal with a NAME from :data:`REFUSAL_CODES`, not a silent result."""

    def __init__(self, reason: str, detail: str = "") -> None:
        if reason not in REFUSAL_CODES:
            raise ConstructionError(f"unknown refusal reason {reason!r}")
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


def _q(value: float) -> float:
    """Normalization of a time number: one representation, no ``-0.0``."""
    return round(float(value), _QUANT) + 0.0


def _convex_footprint(points: Any, name: str) -> tuple[Point2, ...]:
    """A convex footprint in plan.

    Convexity is not decoration: the containment predicate below is
    correct ONLY for a convex contour, so a concave input is rejected
    here, rather than silently giving a wrong "panel is in the zone" answer.
    """
    if isinstance(points, (str, bytes)) or not isinstance(points, Sequence):
        raise ConstructionError(f"{name} must be a sequence of 2D points")
    pts = tuple(_point2(item, f"{name}[{index}]")
                for index, item in enumerate(points))
    if len(pts) < 3:
        raise ConstructionError(f"{name} must contain at least three points")
    if len(set(pts)) != len(pts):
        raise ConstructionError(f"{name} must not repeat a point")
    count = len(pts)
    sign = 0
    doubled_area = 0.0
    for index in range(count):
        ax, ay = pts[index]
        bx, by = pts[(index + 1) % count]
        cx, cy = pts[(index + 2) % count]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        doubled_area += ax * by - bx * ay
        if abs(cross) <= _GEOM_EPS:
            continue
        current = 1 if cross > 0.0 else -1
        if sign and current != sign:
            raise ConstructionError(f"{name} must be a convex polygon")
        sign = current
    if sign == 0 or abs(doubled_area) <= _GEOM_EPS:
        raise ConstructionError(f"{name} must enclose a positive area")
    return pts


def _contains_point(footprint: Sequence[Point2], point: Point2) -> bool:
    """A point inside a CONVEX footprint; the boundary counts as belonging to it."""
    count = len(footprint)
    doubled_area = 0.0
    for index in range(count):
        ax, ay = footprint[index]
        bx, by = footprint[(index + 1) % count]
        doubled_area += ax * by - bx * ay
    turn = 1.0 if doubled_area > 0.0 else -1.0
    px, py = point
    for index in range(count):
        ax, ay = footprint[index]
        bx, by = footprint[(index + 1) % count]
        cross = ((bx - ax) * (py - ay) - (by - ay) * (px - ax)) * turn
        if cross < -_GEOM_EPS:
            return False
    return True


def _hull_dict(hull: Any) -> dict[str, Any]:
    """An intrusion's envelope as DATA: the plan footprint must be able to see it."""
    if isinstance(hull, G.Capsule):
        return {"kind": "capsule", "radius": hull.radius,
                "path": [list(item) for item in hull.path]}
    if isinstance(hull, G.Aabb):
        return {"kind": "aabb", "lo": list(hull.lo), "hi": list(hull.hi)}
    if isinstance(hull, G.Prism):
        return {"kind": "prism", "z0": hull.z0, "z1": hull.z1,
                "footprint": [list(item) for item in hull.footprint]}
    if isinstance(hull, G.PrismSet):
        return {"kind": "prism_set", "z0": hull.z0, "z1": hull.z1,
                "pieces": [[list(item) for item in piece]
                           for piece in hull.pieces]}
    raise ConstructionError("lift obstacle hull is not a kir.clash hull")


def _obstacle_dict(obstacle: Obstacle) -> dict[str, Any]:
    return {"id": obstacle.id, "authority": obstacle.authority.value,
            "label": obstacle.label, "hull": _hull_dict(obstacle.hull)}


# ---------------------------------------------------------------- resources


@dataclass(frozen=True, slots=True)
class CraneEnvelope:
    """A crane's envelope: the outreach ring and the hook ceiling. Not the load's point.

    ``kinematics`` is DECLARED kinematics (hoist, trolley, and slew
    speeds plus a load chart) in the form of a ready-made
    :class:`~kir.construction.site.TowerCrane`. While it is absent, delivery
    duration remains an INPUT (``duration_source="declared"``). Once it is
    declared and the panel promised a rigging point, delivery duration is COMPUTED by
    the trajectory of that same ``site.py`` (``duration_source="trajectory"``).
    """

    id: str
    base_mm: Point3
    min_radius_mm: float
    max_radius_mm: float
    max_hook_z_mm: float
    kinematics: TowerCrane | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "crane.id"))
        object.__setattr__(self, "base_mm", _point3(self.base_mm, "base_mm"))
        object.__setattr__(self, "min_radius_mm", _number(
            self.min_radius_mm, "min_radius_mm", nonnegative=True))
        object.__setattr__(self, "max_radius_mm", _number(
            self.max_radius_mm, "max_radius_mm", positive=True))
        object.__setattr__(self, "max_hook_z_mm", _number(
            self.max_hook_z_mm, "max_hook_z_mm"))
        if self.max_radius_mm <= self.min_radius_mm:
            raise ConstructionError(
                "max_radius_mm must exceed min_radius_mm")
        if self.kinematics is not None:
            source = self.kinematics
            if not isinstance(source, TowerCrane):
                raise ConstructionError(
                    "crane.kinematics must be a TowerCrane")
            # Two truths about one crane are a source of silent
            # divergence: the envelope would say one thing, the
            # trajectory would be computed from another. So the declared
            # kinematics must MATCH the declared envelope.
            agrees = (
                source.id == self.id
                and source.base_mm == self.base_mm
                and abs(source.min_radius_mm - self.min_radius_mm) <= _EPS
                and abs(source.max_radius_mm - self.max_radius_mm) <= _EPS
                and abs(source.max_hook_z_mm - self.max_hook_z_mm) <= _EPS)
            if not agrees:
                raise ConstructionError(
                    "crane.kinematics disagrees with the declared envelope")

    @classmethod
    def from_tower_crane(cls, crane: Any) -> "CraneEnvelope":
        """The envelope is taken from the existing :class:`~kir.construction.site.TowerCrane`."""
        try:
            return cls(id=crane.id, base_mm=crane.base_mm,
                       min_radius_mm=crane.min_radius_mm,
                       max_radius_mm=crane.max_radius_mm,
                       max_hook_z_mm=crane.max_hook_z_mm,
                       kinematics=crane if isinstance(crane, TowerCrane)
                       else None)
        except AttributeError as exc:
            raise ConstructionError(
                "from_tower_crane needs id/base_mm/min_radius_mm/"
                "max_radius_mm/max_hook_z_mm") from exc

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "base_mm": list(self.base_mm),
                "min_radius_mm": self.min_radius_mm,
                "max_radius_mm": self.max_radius_mm,
                "max_hook_z_mm": self.max_hook_z_mm,
                "kinematics": (None if self.kinematics is None
                               else self.kinematics.to_dict())}


@dataclass(frozen=True, slots=True)
class Crew:
    """A depersonalized crew. No names, no personal data."""

    id: str
    size: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "crew.id"))
        if isinstance(self.size, bool) or not isinstance(self.size, int) \
                or self.size < 1:
            raise ConstructionError("crew.size must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "size": self.size}


@dataclass(frozen=True, slots=True)
class WorkZone:
    """A work zone: one panel at a time, held until release.

    ``footprint_mm`` is the zone's CONVEX polygon in plan (mm) at height
    ``[z0_mm, z1_mm]``. When it is declared, a panel must lie inside the
    zone at the moment of installation (otherwise the named refusal
    ``panel_outside_zone`` fires), and an intrusion-BODY intersects the
    zone geometrically, not by matching identifiers. An empty polygon
    keeps the old regime: the zone remains a capacity-1 identifier, and
    this is visible in the input (``footprint_mm: []``).

    Containment is checked IN PLAN. The ``[z0_mm, z1_mm]`` extent is
    needed for an intrusion's body, not for the panel: the module makes
    no assertion that "the panel is within the zone by height."
    """

    id: str
    footprint_mm: tuple[Point2, ...] = ()
    z0_mm: float = 0.0
    z1_mm: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "zone.id"))
        object.__setattr__(self, "z0_mm", _number(self.z0_mm, "zone.z0_mm"))
        object.__setattr__(self, "z1_mm", _number(self.z1_mm, "zone.z1_mm"))
        if not self.footprint_mm:
            object.__setattr__(self, "footprint_mm", ())
            return
        object.__setattr__(self, "footprint_mm", _convex_footprint(
            self.footprint_mm, "zone.footprint_mm"))
        if self.z1_mm <= self.z0_mm:
            raise ConstructionError("zone z1_mm must exceed z0_mm")

    @property
    def prism(self) -> G.Prism | None:
        """The zone's body for geometry, or ``None`` — no polygon promised."""
        if not self.footprint_mm:
            return None
        return G.Prism(footprint=self.footprint_mm, z0=self.z0_mm,
                       z1=self.z1_mm)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "capacity_panels": 1,
                "footprint_mm": [list(item) for item in self.footprint_mm],
                "z0_mm": self.z0_mm, "z1_mm": self.z1_mm}


@dataclass(frozen=True, slots=True)
class Unavailability:
    """A window during which a resource is occupied by something outside the model.

    A crane under maintenance is a delay. A zone occupied by an
    intrusion is an obstruction. A task holding the resource cannot
    cross the window and is pushed past its end.
    """

    resource_id: str
    start_s: float
    end_s: float
    cause: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_id", _identifier(
            self.resource_id, "unavailability.resource_id"))
        object.__setattr__(self, "start_s", _number(
            self.start_s, "unavailability.start_s", nonnegative=True))
        object.__setattr__(self, "end_s", _number(
            self.end_s, "unavailability.end_s", nonnegative=True))
        object.__setattr__(self, "cause", _identifier(
            self.cause, "unavailability.cause"))
        if self.end_s <= self.start_s:
            raise ConstructionError("unavailability end_s must exceed start_s")

    def to_dict(self) -> dict[str, Any]:
        return {"resource_id": self.resource_id, "start_s": _q(self.start_s),
                "end_s": _q(self.end_s), "cause": self.cause}


@dataclass(frozen=True, slots=True)
class Intrusion:
    """An intrusion as a BODY: a convex polygon × ``[z0, z1]`` and a time window.

    The difference from :class:`Unavailability` is not cosmetic. A
    window names the RESOURCE by its name, so "an intrusion in the zone"
    there is a matter of convention. Here a BODY is named, and which
    zone it intersects is decided by geometry
    (:func:`kir.clash.geom.signed_distance`). A body that touches no
    zone at all does not move the schedule, and this is recorded as the
    named shorthand ``intrusion_touches_no_zone``, rather than
    disappearing silently.
    """

    id: str
    footprint_mm: tuple[Point2, ...]
    z0_mm: float
    z1_mm: float
    start_s: float
    end_s: float
    cause: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "intrusion.id"))
        object.__setattr__(self, "footprint_mm", _convex_footprint(
            self.footprint_mm, "intrusion.footprint_mm"))
        object.__setattr__(self, "z0_mm", _number(
            self.z0_mm, "intrusion.z0_mm"))
        object.__setattr__(self, "z1_mm", _number(
            self.z1_mm, "intrusion.z1_mm"))
        if self.z1_mm <= self.z0_mm:
            raise ConstructionError("intrusion z1_mm must exceed z0_mm")
        object.__setattr__(self, "start_s", _number(
            self.start_s, "intrusion.start_s", nonnegative=True))
        object.__setattr__(self, "end_s", _number(
            self.end_s, "intrusion.end_s", nonnegative=True))
        object.__setattr__(self, "cause", _identifier(
            self.cause, "intrusion.cause"))
        if self.end_s <= self.start_s:
            raise ConstructionError("intrusion end_s must exceed start_s")

    @property
    def prism(self) -> G.Prism:
        return G.Prism(footprint=self.footprint_mm, z0=self.z0_mm,
                       z1=self.z1_mm)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id,
                "footprint_mm": [list(item) for item in self.footprint_mm],
                "z0_mm": self.z0_mm, "z1_mm": self.z1_mm,
                "start_s": _q(self.start_s), "end_s": _q(self.end_s),
                "cause": self.cause}


# ----------------------------------------------------------------- panel


@dataclass(frozen=True, slots=True)
class Panel:
    """A panel to be installed.

    ``plan_half_extent_mm`` is the promised plan footprint (a
    half-diagonal from the installation point). If it is promised, reach
    is checked over the whole footprint. If it is ``None``, the check
    shrinks to a point, and this is recorded as a named reduction in
    :attr:`ScheduleResult.reductions`.
    """

    id: str
    set_mm: Point3
    height_mm: float
    deliver_s: float
    install_s: float
    release_s: float
    plan_half_extent_mm: float | None = None
    zone_id: str | None = None
    pickup_mm: Point3 | None = None
    gross_load_kg: float | None = None
    load_radius_mm: float | None = None
    lift_clearance_mm: float = 500.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "panel.id"))
        object.__setattr__(self, "set_mm", _point3(self.set_mm, "set_mm"))
        object.__setattr__(self, "height_mm", _number(
            self.height_mm, "height_mm", positive=True))
        for name in ("deliver_s", "install_s", "release_s"):
            object.__setattr__(self, name, _number(
                getattr(self, name), name, positive=True))
        if self.plan_half_extent_mm is not None:
            object.__setattr__(self, "plan_half_extent_mm", _number(
                self.plan_half_extent_mm, "plan_half_extent_mm",
                nonnegative=True))
        if self.zone_id is not None:
            object.__setattr__(self, "zone_id", _identifier(
                self.zone_id, "panel.zone_id"))
        if self.pickup_mm is not None:
            object.__setattr__(self, "pickup_mm", _point3(
                self.pickup_mm, "pickup_mm"))
            if self.pickup_mm == self.set_mm:
                # Coincident points would give a trajectory of zero
                # duration, i.e. a delivery "in zero seconds." That is
                # not a schedule, it is an input defect, and it is named
                # here rather than surfacing as a zero later.
                raise ConstructionError(
                    "panel pickup_mm must differ from set_mm")
        if self.gross_load_kg is not None:
            object.__setattr__(self, "gross_load_kg", _number(
                self.gross_load_kg, "gross_load_kg", positive=True))
        if self.load_radius_mm is not None:
            object.__setattr__(self, "load_radius_mm", _number(
                self.load_radius_mm, "load_radius_mm", nonnegative=True))
        object.__setattr__(self, "lift_clearance_mm", _number(
            self.lift_clearance_mm, "lift_clearance_mm", nonnegative=True))

    @property
    def top_z_mm(self) -> float:
        return self.set_mm[2] + self.height_mm

    @property
    def lift_promised(self) -> bool:
        """Whether a rigging point is promised: the pickup point, mass, and load radius, all at once."""
        return (self.pickup_mm is not None and self.gross_load_kg is not None
                and self.load_radius_mm is not None)

    @property
    def plan_corners_mm(self) -> tuple[Point2, ...]:
        """The panel's plan footprint: a square from the half-diagonal, or a single point."""
        x, y = self.set_mm[0], self.set_mm[1]
        extent = self.plan_half_extent_mm or 0.0
        if extent <= 0.0:
            return ((x, y),)
        return ((x - extent, y - extent), (x + extent, y - extent),
                (x + extent, y + extent), (x - extent, y + extent))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "set_mm": list(self.set_mm),
                "height_mm": self.height_mm,
                "deliver_s": _q(self.deliver_s),
                "install_s": _q(self.install_s),
                "release_s": _q(self.release_s),
                "plan_half_extent_mm": self.plan_half_extent_mm,
                "zone_id": self.zone_id,
                "pickup_mm": (None if self.pickup_mm is None
                              else list(self.pickup_mm)),
                "gross_load_kg": self.gross_load_kg,
                "load_radius_mm": self.load_radius_mm,
                "lift_clearance_mm": self.lift_clearance_mm}


# ------------------------------------------------------------------ plan


@dataclass(frozen=True, slots=True)
class Task:
    """A typed task. Its identifier is ``<kind>:<panel_id>``."""

    id: str
    kind: str
    panel_id: str
    panel_index: int
    duration_s: float
    resources: tuple[str, ...]
    depends_on: tuple[str, ...]
    zone_id: str = ""
    crane_id: str = ""
    duration_source: str = "declared"

    @property
    def order_key(self) -> tuple[int, int, str]:
        return (self.panel_index, _KIND_RANK[self.kind], self.id)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "panel_id": self.panel_id,
                "duration_s": _q(self.duration_s),
                "duration_source": self.duration_source,
                "zone_id": self.zone_id, "crane_id": self.crane_id,
                "resources": list(self.resources),
                "depends_on": list(self.depends_on)}


@dataclass(frozen=True, slots=True)
class SitePlan:
    """The model's closed input. No hidden environment."""

    id: str
    panels: tuple[Panel, ...]
    crane: CraneEnvelope
    crew: Crew
    zone: WorkZone
    unavailabilities: tuple[Unavailability, ...] = ()
    extra_dependencies: tuple[tuple[str, str], ...] = ()
    rigging_height_mm: float = 1000.0
    extra_cranes: tuple[CraneEnvelope, ...] = ()
    extra_zones: tuple[WorkZone, ...] = ()
    intrusions: tuple[Intrusion, ...] = ()
    lift_obstacles: tuple[Obstacle, ...] = ()

    @property
    def cranes(self) -> tuple[CraneEnvelope, ...]:
        """Cranes in DECLARED order: the first one that can reach takes the panel."""
        return (self.crane,) + self.extra_cranes

    @property
    def zones(self) -> tuple[WorkZone, ...]:
        """Zones in declared order. ``zone`` is the primary one (the default)."""
        return (self.zone,) + self.extra_zones

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _identifier(self.id, "plan.id"))
        panels = tuple(self.panels)
        if not panels or not all(isinstance(p, Panel) for p in panels):
            raise ConstructionError("panels must contain Panel values")
        if len({p.id for p in panels}) != len(panels):
            raise ConstructionError("panel ids must be unique")
        object.__setattr__(self, "panels", panels)
        for name, kind in (("crane", CraneEnvelope), ("crew", Crew),
                           ("zone", WorkZone)):
            if not isinstance(getattr(self, name), kind):
                raise ConstructionError(f"{name} must be a {kind.__name__}")
        windows = tuple(self.unavailabilities)
        if not all(isinstance(w, Unavailability) for w in windows):
            raise ConstructionError(
                "unavailabilities must contain Unavailability values")
        cranes = (self.crane,) + tuple(self.extra_cranes)
        if not all(isinstance(item, CraneEnvelope) for item in cranes):
            raise ConstructionError(
                "extra_cranes must contain CraneEnvelope values")
        object.__setattr__(self, "extra_cranes", tuple(self.extra_cranes))
        zones = (self.zone,) + tuple(self.extra_zones)
        if not all(isinstance(item, WorkZone) for item in zones):
            raise ConstructionError("extra_zones must contain WorkZone values")
        object.__setattr__(self, "extra_zones", tuple(self.extra_zones))
        names = [item.id for item in cranes] + [self.crew.id] + [
            item.id for item in zones]
        if len(set(names)) != len(names):
            raise ConstructionError("crane, crew and zone ids must be unique")
        intrusions = tuple(self.intrusions)
        if not all(isinstance(item, Intrusion) for item in intrusions):
            raise ConstructionError("intrusions must contain Intrusion values")
        if len({item.id for item in intrusions}) != len(intrusions):
            raise ConstructionError("intrusion ids must be unique")
        object.__setattr__(self, "intrusions", tuple(sorted(
            intrusions, key=lambda item: (item.start_s, item.end_s, item.id))))
        obstacles = tuple(self.lift_obstacles)
        if not all(isinstance(item, Obstacle) for item in obstacles):
            raise ConstructionError(
                "lift_obstacles must contain Obstacle values")
        if len({item.id for item in obstacles}) != len(obstacles):
            raise ConstructionError("lift obstacle ids must be unique")
        object.__setattr__(self, "lift_obstacles", tuple(sorted(
            obstacles, key=lambda item: item.id)))
        zone_ids = {item.id for item in zones}
        for panel in panels:
            if panel.zone_id is not None and panel.zone_id not in zone_ids:
                raise ConstructionError(
                    f"panel {panel.id} names unknown zone {panel.zone_id!r}")
        known = set(names)
        for window in windows:
            if window.resource_id not in known:
                raise ConstructionError(
                    f"unavailability names unknown resource "
                    f"{window.resource_id!r}")
        object.__setattr__(self, "unavailabilities", tuple(sorted(
            windows, key=lambda w: (w.start_s, w.end_s, w.resource_id,
                                    w.cause))))
        extra = tuple((str(a), str(b)) for a, b in self.extra_dependencies)
        object.__setattr__(self, "extra_dependencies", extra)
        object.__setattr__(self, "rigging_height_mm", _number(
            self.rigging_height_mm, "rigging_height_mm", nonnegative=True))

    def fingerprint(self) -> str:
        """A fingerprint of the input. Another plan's state is never resumed by mistake."""
        payload = json.dumps(self.to_dict(), ensure_ascii=False,
                             sort_keys=True, separators=(",", ":"))
        return f"{len(payload)}:{sum(payload.encode('utf-8')) % 1_000_003}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEDULE_SCHEMA, "id": self.id,
            "panels": [p.to_dict() for p in self.panels],
            "crane": self.crane.to_dict(), "crew": self.crew.to_dict(),
            "zone": self.zone.to_dict(),
            "cranes": [item.to_dict() for item in self.cranes],
            "zones": [item.to_dict() for item in self.zones],
            "unavailabilities": [w.to_dict() for w in self.unavailabilities],
            "intrusions": [item.to_dict() for item in self.intrusions],
            "lift_obstacles": [_obstacle_dict(item)
                               for item in self.lift_obstacles],
            "extra_dependencies": [list(pair)
                                   for pair in self.extra_dependencies],
            "rigging_height_mm": self.rigging_height_mm,
        }


# --------------------------------------------------------- reach


def check_reach(plan: SitePlan, panel: Panel,
                crane: CraneEnvelope | None = None) -> str | None:
    """``None`` — the panel is within the crane's envelope; otherwise a detail string for the refusal."""
    envelope = plan.crane if crane is None else crane
    base = envelope.base_mm
    radius = math.hypot(panel.set_mm[0] - base[0], panel.set_mm[1] - base[1])
    extent = panel.plan_half_extent_mm or 0.0
    outer = radius + extent
    inner = max(0.0, radius - extent)
    hook_z = panel.top_z_mm + plan.rigging_height_mm
    if outer > envelope.max_radius_mm + _EPS:
        return (f"{panel.id}: outer radius {_q(outer)} mm exceeds "
                f"max_radius_mm {_q(envelope.max_radius_mm)}")
    if inner < envelope.min_radius_mm - _EPS:
        return (f"{panel.id}: inner radius {_q(inner)} mm is under "
                f"min_radius_mm {_q(envelope.min_radius_mm)}")
    if hook_z > envelope.max_hook_z_mm + _EPS:
        return (f"{panel.id}: hook height {_q(hook_z)} mm exceeds "
                f"max_hook_z_mm {_q(envelope.max_hook_z_mm)}")
    return None


def assign_crane(plan: SitePlan, panel: Panel) -> CraneEnvelope:
    """The first crane, by DECLARED order, that reaches the panel.

    There is one rule and it is deterministic: crane order is part of
    the input, just like panel order. If no crane reaches it, it's a
    named refusal, and the detail carries the reason for EVERY crane,
    not just the last one.
    """
    details: list[str] = []
    for crane in plan.cranes:
        detail = check_reach(plan, panel, crane)
        if detail is None:
            return crane
        details.append(f"{crane.id}: {detail}" if len(plan.cranes) > 1
                       else detail)
    raise ScheduleRefused("panel_out_of_reach", "; ".join(details))


def zone_of(plan: SitePlan, panel: Panel) -> WorkZone:
    """A panel's zone: explicitly declared, or the plan's primary zone."""
    wanted = panel.zone_id or plan.zone.id
    for zone in plan.zones:
        if zone.id == wanted:
            return zone
    raise ConstructionError(f"panel {panel.id} names unknown zone {wanted!r}")


def _panel_lies_in_zone(zone: WorkZone, panel: Panel) -> bool:
    """The panel's plan footprint lies ENTIRELY inside the zone's convex polygon."""
    return all(_contains_point(zone.footprint_mm, corner)
               for corner in panel.plan_corners_mm)


#: Lift-planner reasons that THIS module calls unreachability. Anything
#: that falls into none of the branches below must remain a refusal: a
#: classifier that drops the unclassified into the nearest branch lies silently.
_REACH_REFUSALS = frozenset({
    "pickup_outside_radial_reach",
    "set_outside_radial_reach",
    "endpoint_above_hook_height",
    "no_travel_level_below_hook_limit",
})


def deliver_duration(plan: SitePlan, panel: Panel,
                     crane: CraneEnvelope) -> tuple[float, str]:
    """The delivery duration and ITS PROVENANCE.

    ``declared`` — the number came in as input. ``trajectory`` — the
    number was computed by
    :func:`~kir.construction.site.plan_tower_crane_lift` from the
    crane's declared kinematics: hoisting, slewing/trolleying, and
    lowering at their speeds, routing around declared obstacles by
    height. There is no third outcome: a refusal from the lift planner
    becomes a NAMED schedule refusal.
    """
    if crane.kinematics is None or not panel.lift_promised:
        return panel.deliver_s, "declared"
    request = LiftRequest(
        id=f"{TASK_DELIVER}:{panel.id}", pickup_mm=panel.pickup_mm,
        set_mm=panel.set_mm, gross_load_kg=panel.gross_load_kg,
        load_radius_mm=panel.load_radius_mm,
        clearance_mm=panel.lift_clearance_mm)
    lift = plan_tower_crane_lift(crane.kinematics, request,
                                 plan.lift_obstacles)
    if lift.feasibility is Feasibility.UNKNOWN:
        # The obstacle's shell contains the body but is not the body itself.
        # Taking its time as truth would mean passing off "maybe" as "yes".
        raise ScheduleRefused(
            "lift_feasibility_unknown",
            f"{panel.id}: {','.join(sorted(lift.reasons)) or 'unknown'}")
    if lift.feasibility is Feasibility.REFUSED:
        # Names are hoisted as LITERALS. A refusal assembled through a
        # variable is invisible to the `ast` parse that the closed list is
        # checked against — and the list would silently stop guarding the
        # very thing it was set up for.
        reasons = set(lift.reasons)
        detail = f"{panel.id}: {','.join(sorted(lift.reasons)) or 'none'}"
        if "confirmed_path_intersection" in reasons:
            raise ScheduleRefused("lift_path_blocked", detail)
        if "gross_load_exceeds_chart_at_worst_radius" in reasons:
            raise ScheduleRefused("panel_over_capacity", detail)
        if reasons and reasons <= _REACH_REFUSALS:
            raise ScheduleRefused("panel_out_of_reach", detail)
        raise ScheduleRefused(
            "lift_feasibility_unknown",
            f"{panel.id}: unclassified lift refusal "
            f"{','.join(sorted(lift.reasons)) or 'none'}")
    duration = _q(lift.duration_s)
    if duration <= 0.0:
        raise ScheduleRefused(
            "lift_feasibility_unknown",
            f"{panel.id}: trajectory duration is not positive")
    return duration, "trajectory"


def _compile(plan: SitePlan) -> tuple[tuple[Task, ...], tuple[str, ...]]:
    """Tasks and named REDUCTIONS. Refusals — by name, before simulation."""
    any_kinematics = any(crane.kinematics is not None for crane in plan.cranes)
    any_footprint = any(zone.footprint_mm for zone in plan.zones)
    reductions: list[str] = []
    if any_kinematics:
        reductions.extend(f"crane_kinematics_not_promised:{crane.id}"
                          for crane in plan.cranes if crane.kinematics is None)

    tasks: list[Task] = []
    last_in_zone: dict[str, str] = {}
    lift_gaps: list[str] = []
    for index, panel in enumerate(plan.panels):
        crane = assign_crane(plan, panel)
        zone = zone_of(plan, panel)
        if zone.footprint_mm and not _panel_lies_in_zone(zone, panel):
            raise ScheduleRefused(
                "panel_outside_zone",
                f"{panel.id}: plan extent is not inside zone {zone.id}")
        duration, source = deliver_duration(plan, panel, crane)
        if crane.kinematics is not None and not panel.lift_promised:
            lift_gaps.append(f"panel_lift_not_promised:{panel.id}")
        previous = last_in_zone.get(zone.id)
        deliver_deps: tuple[str, ...] = (
            (f"{TASK_INSTALL}:{previous}",) if previous else ())
        last_in_zone[zone.id] = panel.id
        tasks.append(Task(
            id=f"{TASK_DELIVER}:{panel.id}", kind=TASK_DELIVER,
            panel_id=panel.id, panel_index=index, duration_s=duration,
            resources=(crane.id, zone.id), depends_on=deliver_deps,
            zone_id=zone.id, crane_id=crane.id, duration_source=source))
        tasks.append(Task(
            id=f"{TASK_INSTALL}:{panel.id}", kind=TASK_INSTALL,
            panel_id=panel.id, panel_index=index,
            duration_s=panel.install_s,
            resources=(plan.crew.id, zone.id),
            depends_on=(f"{TASK_DELIVER}:{panel.id}",),
            zone_id=zone.id, crane_id=crane.id, duration_source="declared"))
        tasks.append(Task(
            id=f"{TASK_RELEASE}:{panel.id}", kind=TASK_RELEASE,
            panel_id=panel.id, panel_index=index,
            duration_s=panel.release_s, resources=(zone.id,),
            depends_on=(f"{TASK_INSTALL}:{panel.id}",),
            zone_id=zone.id, crane_id=crane.id, duration_source="declared"))

    reductions.extend(f"panel_extent_not_promised:{panel.id}"
                      for panel in plan.panels
                      if panel.plan_half_extent_mm is None)
    reductions.extend(lift_gaps)
    if any_footprint:
        reductions.extend(f"zone_footprint_not_promised:{zone.id}"
                          for zone in plan.zones if not zone.footprint_mm)

    by_id = {task.id: task for task in tasks}
    for before, after in plan.extra_dependencies:
        for name in (before, after):
            if name not in by_id:
                raise ScheduleRefused("dependency_unknown_task", name)
        current = by_id[after]
        if before not in current.depends_on:
            by_id[after] = Task(
                id=current.id, kind=current.kind, panel_id=current.panel_id,
                panel_index=current.panel_index,
                duration_s=current.duration_s, resources=current.resources,
                depends_on=tuple(sorted(current.depends_on + (before,))),
                zone_id=current.zone_id, crane_id=current.crane_id,
                duration_source=current.duration_source)
    ordered = tuple(sorted(by_id.values(), key=lambda t: t.order_key))
    _refuse_on_cycle(ordered)
    return ordered, tuple(reductions)


def derived_windows(plan: SitePlan) -> tuple[tuple[Unavailability, ...],
                                             tuple[str, ...]]:
    """Foreign bodies → zone-unavailability windows, resolved by GEOMETRY."""
    windows: list[Unavailability] = []
    reductions: list[str] = []
    for intrusion in plan.intrusions:
        body = intrusion.prism
        touched = 0
        for zone in plan.zones:
            prism = zone.prism
            if prism is None:
                continue
            if G.signed_distance(body, prism) <= _GEOM_EPS:
                touched += 1
                windows.append(Unavailability(
                    resource_id=zone.id, start_s=intrusion.start_s,
                    end_s=intrusion.end_s, cause=intrusion.cause))
        if not touched:
            reductions.append(f"intrusion_touches_no_zone:{intrusion.id}")
    return tuple(windows), tuple(reductions)


def build_tasks(plan: SitePlan) -> tuple[Task, ...]:
    """Tasks and dependencies. Refusals — by name, before any simulation."""
    return _compile(plan)[0]


def _refuse_on_cycle(tasks: Sequence[Task]) -> None:
    remaining = {task.id: set(task.depends_on) for task in tasks}
    order = [task.id for task in tasks]
    settled: set[str] = set()
    progress = True
    while progress:
        progress = False
        for name in order:
            if name in settled:
                continue
            if remaining[name] <= settled:
                settled.add(name)
                progress = True
    if len(settled) != len(order):
        stuck = sorted(name for name in order if name not in settled)
        raise ScheduleRefused("cyclic_dependency", ",".join(stuck))


# --------------------------------------------------------------- events


@dataclass(frozen=True, slots=True)
class ScheduleEvent:
    seq: int
    time_s: float
    kind: str
    task_id: str
    panel_id: str
    resources: tuple[str, ...]
    cause: str
    duration_source: str = "declared"

    def to_dict(self) -> dict[str, Any]:
        return {"seq": self.seq, "time_s": _q(self.time_s), "kind": self.kind,
                "task_id": self.task_id, "panel_id": self.panel_id,
                "resources": list(self.resources), "cause": self.cause,
                "duration_source": self.duration_source}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScheduleEvent":
        return cls(seq=int(data["seq"]), time_s=float(data["time_s"]),
                   kind=str(data["kind"]), task_id=str(data["task_id"]),
                   panel_id=str(data["panel_id"]),
                   resources=tuple(str(item) for item in data["resources"]),
                   cause=str(data["cause"]),
                   duration_source=str(data["duration_source"]))


@dataclass(frozen=True, slots=True)
class PanelTiming:
    panel_id: str
    deliver_start_s: float
    deliver_end_s: float
    install_start_s: float
    install_end_s: float
    released_s: float
    zone_id: str = ""
    crane_id: str = ""
    deliver_source: str = "declared"

    def to_dict(self) -> dict[str, Any]:
        return {"panel_id": self.panel_id,
                "deliver_start_s": _q(self.deliver_start_s),
                "deliver_end_s": _q(self.deliver_end_s),
                "install_start_s": _q(self.install_start_s),
                "install_end_s": _q(self.install_end_s),
                "released_s": _q(self.released_s),
                "zone_id": self.zone_id, "crane_id": self.crane_id,
                "deliver_source": self.deliver_source}


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    plan_id: str
    total_time_s: float
    installation_order: tuple[str, ...]
    panels: tuple[PanelTiming, ...]
    events: tuple[ScheduleEvent, ...]
    resource_busy_s: tuple[tuple[str, float], ...]
    reductions: tuple[str, ...]
    zones: tuple[str, ...] = ()
    cranes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEDULE_SCHEMA, "plan_id": self.plan_id,
            "units": {"length": "mm", "time": "s"},
            "total_time_s": _q(self.total_time_s),
            "zones": list(self.zones), "cranes": list(self.cranes),
            "installation_order": list(self.installation_order),
            "panels": [item.to_dict() for item in self.panels],
            "events": [item.to_dict() for item in self.events],
            "resource_busy_s": [[name, _q(value)]
                                for name, value in self.resource_busy_s],
            "reductions": list(self.reductions),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    def state_at(self, time_s: float) -> dict[str, Any]:
        """State at ``time_s``. The animation is required to follow it."""
        moment = _number(time_s, "time_s", nonnegative=True)
        panels: dict[str, str] = {}
        for timing in self.panels:
            if moment < timing.deliver_start_s - _EPS:
                status = "waiting"
            elif moment < timing.deliver_end_s - _EPS:
                status = "in_delivery"
            elif moment < timing.install_start_s - _EPS:
                status = "delivered"
            elif moment < timing.install_end_s - _EPS:
                status = "installing"
            elif moment < timing.released_s - _EPS:
                status = "installed"
            else:
                status = "released"
            panels[timing.panel_id] = status
        owners: dict[str, str | None] = {zone: None for zone in self.zones}
        for timing in self.panels:
            if (timing.deliver_start_s - _EPS <= moment
                    < timing.released_s - _EPS):
                owners[timing.zone_id] = timing.panel_id
        # ``zone_owner`` is the owner of the plan's MAIN zone. The full
        # mapping sits alongside it in ``zone_owners``: with several zones a
        # single field physically cannot name every owner, and pretending
        # that it can means losing the panel.
        owner = owners.get(self.zones[0]) if self.zones else None
        return {"schema": SCHEDULE_SCHEMA, "time_s": _q(moment),
                "panels": panels, "zone_owner": owner,
                "zone_owners": owners,
                "installed": [timing.panel_id for timing in self.panels
                              if moment >= timing.install_end_s - _EPS]}


# -------------------------------------------------------------- state


@dataclass(frozen=True, slots=True)
class SiteState:
    """The run's snapshot as DATA. Resumption continues from the same event."""

    plan_fingerprint: str
    now_s: float
    next_seq: int
    completed: tuple[str, ...]
    running: tuple[tuple[str, float, float], ...]
    zone_owner: tuple[tuple[str, str | None], ...]
    resource_free_s: tuple[tuple[str, float], ...]
    events: tuple[ScheduleEvent, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": STATE_SCHEMA,
            "plan_fingerprint": self.plan_fingerprint,
            "now_s": _q(self.now_s), "next_seq": self.next_seq,
            "completed": list(self.completed),
            "running": [[name, _q(start), _q(end)]
                        for name, start, end in self.running],
            "zone_owner": {zone: owner for zone, owner in self.zone_owner},
            "resource_free_s": [[name, _q(value)]
                                for name, value in self.resource_free_s],
            "events": [item.to_dict() for item in self.events],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"))

    def check_shape(self) -> None:
        """The snapshot must be self-consistent, before any plan at all.

        A forged snapshot must not reach the engine and fail there with a
        ``KeyError``: such a crash is not a refusal — it names nothing.
        """
        if self.now_s < 0.0:
            raise ScheduleRefused("state_is_inconsistent",
                                  f"now_s={_q(self.now_s)} is negative")
        if self.next_seq < 0 or self.next_seq != len(self.events):
            raise ScheduleRefused(
                "state_is_inconsistent",
                f"next_seq={self.next_seq} against {len(self.events)} events")
        previous = -1
        for event in self.events:
            if event.seq <= previous or event.time_s < 0.0:
                raise ScheduleRefused("state_is_inconsistent",
                                      f"event seq={event.seq} is out of order")
            if event.time_s > self.now_s + _EPS:
                raise ScheduleRefused(
                    "state_is_inconsistent",
                    f"event seq={event.seq} lies ahead of now_s")
            previous = event.seq
        names = [name for name, _start, _end in self.running]
        if len(set(names)) != len(names):
            raise ScheduleRefused("state_is_inconsistent", "running ids repeat")
        for name, start, end in self.running:
            if start < 0.0 or end < start - _EPS:
                raise ScheduleRefused("state_is_inconsistent",
                                      f"running {name} has a broken span")
        if len(set(self.completed)) != len(self.completed):
            raise ScheduleRefused("state_is_inconsistent",
                                  "completed ids repeat")
        overlap = sorted(set(self.completed) & set(names))
        if overlap:
            raise ScheduleRefused("state_is_inconsistent",
                                  f"both completed and running: {overlap[0]}")
        zones = [zone for zone, _owner in self.zone_owner]
        if len(set(zones)) != len(zones):
            raise ScheduleRefused("state_is_inconsistent",
                                  "zone_owner ids repeat")
        for zone, owner in self.zone_owner:
            if not isinstance(zone, str) or not zone:
                raise ScheduleRefused("state_is_inconsistent",
                                      "zone_owner key is not an identifier")
            if owner is not None and (not isinstance(owner, str) or not owner):
                raise ScheduleRefused(
                    "state_is_inconsistent",
                    f"zone_owner[{zone}] is not an identifier")
        resources = [name for name, _value in self.resource_free_s]
        if len(set(resources)) != len(resources):
            raise ScheduleRefused("state_is_inconsistent",
                                  "resource ids repeat")
        for name, value in self.resource_free_s:
            if value < 0.0:
                raise ScheduleRefused("state_is_inconsistent",
                                      f"resource_free_s[{name}] is negative")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SiteState":
        if data.get("schema") != STATE_SCHEMA:
            raise ConstructionError("state schema mismatch")
        raw_owner = data["zone_owner"]
        if not isinstance(raw_owner, Mapping):
            # A single field was true about exactly one zone. A snapshot of
            # the old shape must refuse BY NAME, not be reinterpreted.
            raise ScheduleRefused(
                "state_does_not_match_plan",
                f"zone_owner must be a mapping of zones, got "
                f"{type(raw_owner).__name__}")
        state = cls(
            plan_fingerprint=str(data["plan_fingerprint"]),
            now_s=float(data["now_s"]), next_seq=int(data["next_seq"]),
            completed=tuple(str(item) for item in data["completed"]),
            running=tuple((str(a), float(b), float(c))
                          for a, b, c in data["running"]),
            zone_owner=tuple(sorted(
                ((str(zone), None if owner is None else str(owner))
                 for zone, owner in raw_owner.items()),
                key=lambda item: item[0])),
            resource_free_s=tuple((str(a), float(b))
                                  for a, b in data["resource_free_s"]),
            events=tuple(ScheduleEvent.from_dict(item)
                         for item in data["events"]))
        state.check_shape()
        return state


# ------------------------------------------------------------- simulation


class SiteSimulation:
    """Discrete event simulation. The order is fixed; there is no randomness."""

    def __init__(self, plan: SitePlan, state: SiteState | None = None) -> None:
        if not isinstance(plan, SitePlan):
            raise ConstructionError("plan must be a SitePlan")
        self.plan = plan
        self.tasks, compiled_reductions = _compile(plan)
        self._by_id = {task.id: task for task in self.tasks}
        intrusion_windows, intrusion_reductions = derived_windows(plan)
        self._windows = tuple(sorted(
            plan.unavailabilities + intrusion_windows,
            key=lambda w: (w.start_s, w.end_s, w.resource_id, w.cause)))
        self._zone_ids = tuple(zone.id for zone in plan.zones)
        self._resource_ids = (tuple(crane.id for crane in plan.cranes)
                              + (plan.crew.id,) + self._zone_ids)
        self._reductions = compiled_reductions + intrusion_reductions
        self.control_log: list[str] = []
        if state is None:
            self._now = 0.0
            self._seq = 0
            self._completed: dict[str, float] = {}
            self._running: dict[str, tuple[float, float]] = {}
            self._zone_owners: dict[str, str | None] = {
                name: None for name in self._zone_ids}
            self._free = {name: 0.0 for name in self._resource_ids}
            self._events: list[ScheduleEvent] = []
        else:
            self._load(state)

    # ---- state as data

    def _load(self, state: SiteState) -> None:
        state.check_shape()
        if state.plan_fingerprint != self.plan.fingerprint():
            raise ScheduleRefused("state_does_not_match_plan",
                                  state.plan_fingerprint)
        mentioned = ({name for name in state.completed}
                     | {name for name, _s, _e in state.running}
                     | {event.task_id for event in state.events})
        unknown = sorted(mentioned - set(self._by_id))
        if unknown:
            raise ScheduleRefused("state_does_not_match_plan",
                                  ",".join(unknown))
        named = {name for name, _value in state.resource_free_s}
        if named != set(self._resource_ids):
            raise ScheduleRefused(
                "state_does_not_match_plan",
                ",".join(sorted(named ^ set(self._resource_ids))))
        panel_ids = {panel.id for panel in self.plan.panels}
        declared_zones = {zone for zone, _owner in state.zone_owner}
        if declared_zones != set(self._zone_ids):
            raise ScheduleRefused(
                "state_does_not_match_plan",
                ",".join(sorted(declared_zones ^ set(self._zone_ids))))
        for _zone, owner in state.zone_owner:
            if owner is not None and owner not in panel_ids:
                raise ScheduleRefused("state_does_not_match_plan",
                                      f"zone_owner={owner}")

        started = {event.task_id for event in state.events
                   if event.kind == "task_started"}
        finished = {event.task_id for event in state.events
                    if event.kind == "task_finished"}
        if set(state.completed) != finished:
            raise ScheduleRefused(
                "state_is_inconsistent",
                ",".join(sorted(set(state.completed) ^ finished)))
        running_names = {name for name, _s, _e in state.running}
        if running_names != started - finished:
            raise ScheduleRefused(
                "state_is_inconsistent",
                ",".join(sorted(running_names ^ (started - finished))))
        start_times = {event.task_id: event.time_s for event in state.events
                       if event.kind == "task_started"}
        for name, start, end in state.running:
            if abs(start_times[name] - start) > _EPS:
                raise ScheduleRefused("state_is_inconsistent",
                                      f"{name} start disagrees with its event")
            if end + _EPS < state.now_s:
                raise ScheduleRefused("state_is_inconsistent",
                                      f"{name} should have finished already")
        for name in state.completed:
            missing = [dep for dep in self._by_id[name].depends_on
                       if dep not in finished]
            if missing:
                raise ScheduleRefused(
                    "state_is_inconsistent",
                    f"{name} is completed while {missing[0]} is not")
        owners: dict[str, str | None] = {name: None
                                         for name in self._zone_ids}
        for panel in self.plan.panels:
            task = self._by_id[f"{TASK_DELIVER}:{panel.id}"]
            if (task.id in started
                    and f"{TASK_RELEASE}:{panel.id}" not in finished):
                if owners[task.zone_id] is not None:
                    raise ScheduleRefused(
                        "state_is_inconsistent",
                        f"zone {task.zone_id} is held by two panels")
                owners[task.zone_id] = panel.id
        declared = dict(state.zone_owner)
        if declared != owners:
            raise ScheduleRefused(
                "state_is_inconsistent",
                f"zone_owner={sorted(declared.items())} against events "
                f"{sorted(owners.items())}")

        self._now = state.now_s
        self._seq = state.next_seq
        self._running = {name: (start, end) for name, start, end in state.running}
        self._completed = {event.task_id: event.time_s for event in state.events
                           if event.kind == "task_finished"}
        self._zone_owners = dict(state.zone_owner)
        self._free = {name: value for name, value in state.resource_free_s}
        for name in self._resource_ids:
            self._free.setdefault(name, 0.0)
        self._events = list(state.events)

    def state(self) -> SiteState:
        return SiteState(
            plan_fingerprint=self.plan.fingerprint(), now_s=_q(self._now),
            next_seq=self._seq,
            completed=tuple(sorted(self._completed)),
            running=tuple(sorted((name, _q(start), _q(end))
                                 for name, (start, end) in self._running.items())),
            zone_owner=tuple((name, self._zone_owners.get(name))
                             for name in sorted(self._zone_owners)),
            resource_free_s=tuple(sorted((name, _q(value))
                                         for name, value in self._free.items())),
            events=tuple(self._events))

    # ---- mechanics

    def _emit(self, time_s: float, kind: str, task: Task, cause: str) -> None:
        self._events.append(ScheduleEvent(
            seq=self._seq, time_s=_q(time_s), kind=kind, task_id=task.id,
            panel_id=task.panel_id, resources=task.resources, cause=cause,
            duration_source=task.duration_source))
        self._seq += 1

    def _window_shift(self, task: Task, start: float) -> tuple[float, str | None]:
        moment = start
        cause: str | None = None
        for _ in range(len(self._windows) + 1):
            moved = False
            for window in self._windows:
                if window.resource_id not in task.resources:
                    continue
                if _overlaps(moment, task.duration_s, window):
                    moment = window.end_s
                    cause = f"unavailable:{window.resource_id}:{window.cause}"
                    moved = True
            if not moved:
                return moment, cause
        raise ScheduleRefused("schedule_deadlock",
                              f"{task.id} cannot leave unavailability windows")

    def _earliest(self, task: Task) -> tuple[float, str] | None:
        """The earliest honest start of a task, or ``None`` — still closed.

        The number is ABSOLUTE: it is computed from dependency readiness and
        resource release, not from the current ``now``. Otherwise the reason
        for the start goes stale the instant time reaches the shifted start,
        and the delay disappears from the event, surviving only in the numbers.
        """
        moment, cause = 0.0, "ready"
        for name in task.depends_on:
            if name not in self._completed:
                return None
            done = self._completed[name]
            if done > moment + _EPS:
                moment, cause = done, f"after:{name}"
        for name in task.resources:
            if name in self._zone_ids:
                owner = self._zone_owners.get(name)
                if owner not in (None, task.panel_id):
                    return None
                if owner is None and task.kind != TASK_DELIVER:
                    return None
            free = self._free.get(name, 0.0)
            if free > moment + _EPS:
                moment, cause = free, f"resource_busy:{name}"
        shifted, window_cause = self._window_shift(task, moment)
        if window_cause is not None:
            cause = window_cause
        return _q(shifted), cause

    def _complete_due(self) -> bool:
        due = sorted(((end, self._by_id[name].order_key, name)
                      for name, (_start, end) in self._running.items()
                      if end <= self._now + _EPS))
        for _end, _key, name in due:
            task = self._by_id[name]
            start, end = self._running.pop(name)
            self._completed[name] = _q(end)
            for resource in task.resources:
                self._free[resource] = max(self._free.get(resource, 0.0), _q(end))
            if task.kind == TASK_RELEASE:
                self._zone_owners[task.zone_id] = None
            self._emit(end, "task_finished", task,
                       f"duration_s={_q(task.duration_s)}")
            if task.kind == TASK_INSTALL:
                self._emit(end, "panel_installed", task, "install_finished")
            if task.kind == TASK_RELEASE:
                self._emit(end, "zone_released", task, "zone_free")
        return bool(due)

    def _start_ready(self, horizon: float | None) -> bool:
        started = False
        again = True
        while again:
            again = False
            for task in self.tasks:
                if task.id in self._completed or task.id in self._running:
                    continue
                found = self._earliest(task)
                if found is None:
                    continue
                moment, cause = found
                if moment > self._now + _EPS:
                    continue
                moment = max(moment, self._now)
                if horizon is not None and moment > horizon + _EPS:
                    continue
                end = _q(moment + task.duration_s)
                self._running[task.id] = (moment, end)
                for resource in task.resources:
                    self._free[resource] = end
                if task.kind == TASK_DELIVER:
                    self._zone_owners[task.zone_id] = task.panel_id
                self._emit(moment, "task_started", task, cause)
                started = again = True
        return started

    def _next_time(self) -> float | None:
        candidates = [end for _start, end in self._running.values()
                      if end > self._now + _EPS]
        for task in self.tasks:
            if task.id in self._completed or task.id in self._running:
                continue
            found = self._earliest(task)
            if found is not None and found[0] > self._now + _EPS:
                candidates.append(found[0])
        return min(candidates) if candidates else None

    def _pending(self) -> bool:
        return any(task.id not in self._completed for task in self.tasks)

    def advance_to(self, time_s: float | None) -> None:
        """Advance the model to ``time_s`` (or to the end when ``None``)."""
        horizon = (None if time_s is None
                   else _number(time_s, "time_s", nonnegative=True))
        if horizon is not None and horizon + _EPS < self._now:
            raise ConstructionError("cannot rewind a simulation")
        guard = 0
        limit = 16 * (len(self.tasks) + len(self._windows) + 4) ** 2
        while self._pending():
            guard += 1
            if guard > limit:
                raise ScheduleRefused("schedule_deadlock", "step limit reached")
            self._complete_due()
            self._start_ready(horizon)
            if not self._pending():
                break
            nxt = self._next_time()
            if nxt is None:
                raise ScheduleRefused(
                    "schedule_deadlock",
                    ",".join(sorted(task.id for task in self.tasks
                                    if task.id not in self._completed)))
            if horizon is not None and nxt > horizon + _EPS:
                self._now = horizon
                return
            self._now = nxt
        if horizon is not None:
            self._now = max(self._now, horizon)

    # ---- public workflow

    def pause(self, time_s: float) -> SiteState:
        """Reach ``time_s`` and lay out the state as data."""
        self.advance_to(time_s)
        self.control_log.append(f"paused_at={_q(self._now)}")
        return self.state()

    def resume(self, state: SiteState | None = None) -> "ScheduleResult":
        """Resume from the same event and run to completion."""
        if state is not None:
            self._load(state)
        self.control_log.append(f"resumed_at={_q(self._now)}")
        return self.run()

    def run(self) -> ScheduleResult:
        self.advance_to(None)
        return self._result()

    def _result(self) -> ScheduleResult:
        starts: dict[str, float] = {}
        ends: dict[str, float] = {}
        for event in self._events:
            if event.kind == "task_started":
                starts[event.task_id] = event.time_s
            elif event.kind == "task_finished":
                ends[event.task_id] = event.time_s
        timings: list[PanelTiming] = []
        for panel in self.plan.panels:
            deliver = self._by_id[f"{TASK_DELIVER}:{panel.id}"]
            timings.append(PanelTiming(
                panel_id=panel.id,
                deliver_start_s=starts[f"{TASK_DELIVER}:{panel.id}"],
                deliver_end_s=ends[f"{TASK_DELIVER}:{panel.id}"],
                install_start_s=starts[f"{TASK_INSTALL}:{panel.id}"],
                install_end_s=ends[f"{TASK_INSTALL}:{panel.id}"],
                released_s=ends[f"{TASK_RELEASE}:{panel.id}"],
                zone_id=deliver.zone_id, crane_id=deliver.crane_id,
                deliver_source=deliver.duration_source))
        order = tuple(item.panel_id for item in sorted(
            timings, key=lambda t: (t.install_end_s, t.panel_id)))
        busy: dict[str, float] = {name: 0.0 for name in self._resource_ids}
        for task in self.tasks:
            span = ends[task.id] - starts[task.id]
            for resource in task.resources:
                if resource in self._zone_ids:
                    continue
                busy[resource] = _q(busy[resource] + span)
        # The zone is occupied by the PANEL, not by the sum of its tasks:
        # occupancy runs from the start of feed to the end of release,
        # including idle time inside the panel.
        zone_busy: dict[str, float] = {name: 0.0 for name in self._zone_ids}
        for timing in timings:
            zone_busy[timing.zone_id] += (timing.released_s
                                          - timing.deliver_start_s)
        for name, value in zone_busy.items():
            busy[name] = _q(value)
        total = max(ends.values()) if ends else 0.0
        return ScheduleResult(
            plan_id=self.plan.id, total_time_s=_q(total),
            installation_order=order, panels=tuple(timings),
            events=tuple(self._events),
            resource_busy_s=tuple(sorted(busy.items())),
            reductions=self._reductions,
            zones=self._zone_ids,
            cranes=tuple(crane.id for crane in self.plan.cranes))


def _overlaps(start: float, duration: float, window: Unavailability) -> bool:
    if duration <= _EPS:
        return window.start_s - _EPS <= start < window.end_s - _EPS
    return (start < window.end_s - _EPS
            and start + duration > window.start_s + _EPS)


def simulate_site(plan: SitePlan) -> ScheduleResult:
    """A continuous run from zero to the end."""
    return SiteSimulation(plan).run()
