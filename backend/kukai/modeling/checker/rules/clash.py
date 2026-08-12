"""rules/clash.py — planar clash & enclosure rules (design §6: HAB040–042).

HAB040  room footprints on a level must not overlap (>0.05 m²)   BLOCKING
HAB041  door hosted in a wall, width <= wall, swings into a room  WARNING
HAB042  apartment/level envelope substantially enclosed           WARNING

Geometry uses shapely Polygons. A cheap inline AABB prefilter (computed from Room.boundary)
skips shapely intersection on non-touching pairs — the GROUND:geometry AABB-before-exact idea
applied to our own contract (see plan cross-component note); we deliberately do NOT import
execution/geometry_gate._aabb_overlap, which is typed for ElementGeometry, not our boundary.
"""
from __future__ import annotations

import math
from itertools import combinations

import networkx as nx
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union

from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.spatial_model import (
    Room, Severity, SpatialModel, Violation,
)
from kukai.modeling.checker.thresholds import Thresholds

# shapely areas are in mm² (boundary coords are mm); convert to m² with this factor.
_MM2_PER_M2 = 1_000_000.0


def _polygon(boundary: list[tuple[float, float]]) -> Polygon | None:
    """Build a shapely Polygon from a boundary loop; None if degenerate (<3 pts)."""
    if boundary is None or len(boundary) < 3:
        return None
    poly = Polygon(boundary)
    if not poly.is_valid:
        poly = poly.buffer(0)  # repair self-touching/ordering artifacts
    if poly.is_empty or poly.area <= 0.0:
        return None
    return poly


def _aabb(boundary: list[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    """Axis-aligned bounding box (min_x, min_y, max_x, max_y) of a boundary loop."""
    if boundary is None or len(boundary) < 3:
        return None
    xs = [p[0] for p in boundary]
    ys = [p[1] for p in boundary]
    return (min(xs), min(ys), max(xs), max(ys))


def _aabb_overlap(a: tuple[float, float, float, float],
                  b: tuple[float, float, float, float]) -> bool:
    """True if two AABBs (min_x,min_y,max_x,max_y) overlap (touching edges count as no overlap)."""
    if a[2] <= b[0] or b[2] <= a[0]:   # a entirely left of b, or vice versa
        return False
    if a[3] <= b[1] or b[3] <= a[1]:   # a entirely below b, or vice versa
        return False
    return True


def _seg_length(curve: tuple[tuple[float, float], tuple[float, float]]) -> float:
    (x1, y1), (x2, y2) = curve
    return math.hypot(x2 - x1, y2 - y1)


def _point_on_segment(pt: tuple[float, float],
                      curve: tuple[tuple[float, float], tuple[float, float]],
                      tol_mm: float = 50.0) -> bool:
    """True if pt lies within tol_mm of the segment curve (perpendicular distance + within span)."""
    (x1, y1), (x2, y2) = curve
    px, py = pt
    dx, dy = x2 - x1, y2 - y1
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return math.hypot(px - x1, py - y1) <= tol_mm
    t = ((px - x1) * dx + (py - y1) * dy) / seg_len_sq
    t = max(0.0, min(1.0, t))
    proj_x, proj_y = x1 + t * dx, y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y) <= tol_mm


def _apartment_envelope_coverage(model: SpatialModel, apt_id: str, thr: Thresholds,
                                 room_ids: set[str] | frozenset[str] | None = None) -> float | None:
    """Fraction (0..1) of apartment apt_id's envelope perimeter that is actually enclosed —
    backed by a wall (within thr.wall_snap_tol_mm of the perimeter) or spanned by a door
    opening (~its clear width). LENGTH-based (review fix): walls and doors cover only their
    real overlap with the perimeter, computed via shapely, so a point-sized wall cannot fake
    enclosure and a door contributes only its own width — not a whole edge per midpoint.
    Returns None if no usable room polygons / zero perimeter. Window openings and per-edge
    gap>50 mm precision remain deferred (design §6 HAB042).
    """
    if room_ids is not None:
        rooms = [r for r in model.rooms if r.id in room_ids]
    else:
        rooms = [r for r in model.rooms if r.apartment_id == apt_id]
    if not rooms:
        return None
    level_id = rooms[0].level_id
    polys = [p for p in (_polygon(r.boundary) for r in rooms) if p is not None]
    if not polys:
        return None
    union = unary_union(polys)
    rings = [LineString(g.exterior.coords) for g in getattr(union, "geoms", [union])]
    perimeter = unary_union(rings)
    total = perimeter.length
    if total <= 0.0:
        return None

    covers = []
    for w in model.walls:
        if w.level_id == level_id:
            covers.append(LineString(w.curve).buffer(thr.wall_snap_tol_mm))
    for d in model.doors:
        if d.level_id == level_id:
            covers.append(Point(d.location).buffer(max(d.width_mm, 1.0) / 2.0))
    if not covers:
        return 0.0
    covered = perimeter.intersection(unary_union(covers)).length
    return covered / total


def check_hab040(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB040: room footprints on the same level must not overlap by more than the tolerance."""
    violations: list[Violation] = []
    by_level: dict[str, list[Room]] = {}
    for room in model.rooms:
        by_level.setdefault(room.level_id, []).append(room)

    for rooms in by_level.values():
        # Precompute AABBs once; pairs whose AABBs miss can't overlap → skip shapely.
        boxes = {r.id: _aabb(r.boundary) for r in rooms}
        polys: dict[str, Polygon] = {}
        for a, b in combinations(rooms, 2):
            box_a, box_b = boxes[a.id], boxes[b.id]
            if box_a is None or box_b is None:
                continue
            if not _aabb_overlap(box_a, box_b):
                continue
            poly_a = polys.get(a.id) or _polygon(a.boundary)
            poly_b = polys.get(b.id) or _polygon(b.boundary)
            if poly_a is None or poly_b is None:
                continue
            polys[a.id], polys[b.id] = poly_a, poly_b
            overlap_m2 = poly_a.intersection(poly_b).area / _MM2_PER_M2
            if overlap_m2 > thr.max_room_overlap_m2:
                violations.append(Violation(
                    rule_id="HAB040",
                    severity=Severity.BLOCKING,
                    refs=sorted([a.id, b.id]),  # D12: deterministic ordering under pytest-randomly
                    msg=(f"rooms '{a.name}' ({a.id}) and '{b.name}' ({b.id}) on level "
                         f"{a.level_id} overlap by {overlap_m2:.2f} m² "
                         f"(> {thr.max_room_overlap_m2} m²)"),
                    fix_hint=("separate the two room boundaries so their footprints do not "
                              "intersect; check generator placement of these rooms"),
                ))
    return violations


def check_hab041(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB041: each door is hosted in a wall, no wider than that wall, and swings into a room.

    GOOD-silence (single, final rule): when no host wall is found, emit ONLY for exterior doors
    (which must sit on the envelope); interior doors with no matching declared wall are treated as
    "wall not modeled" and skipped. The width check only triggers when a host WAS found.
    """
    violations: list[Violation] = []
    walls_by_level: dict[str, list] = {}
    for wall in model.walls:
        walls_by_level.setdefault(wall.level_id, []).append(wall)

    for door in model.doors:
        # (a) swings into a room: must connect at least one real room (exterior counts).
        connects_room = bool(door.from_room_id) or bool(door.to_room_id)
        if not connects_room and not door.is_exterior:
            violations.append(Violation(
                rule_id="HAB041",
                severity=Severity.WARNING,
                refs=[door.id],
                msg=(f"door {door.id} on level {door.level_id} connects no room "
                     f"(from/to both empty, not exterior) — it swings into a wall, not a room"),
                fix_hint="host the door between two rooms (or set is_exterior for an entrance)",
            ))
            continue

        # (b) hosted in a wall on its level, and no wider than that wall segment.
        host = None
        for wall in walls_by_level.get(door.level_id, []):
            if _point_on_segment(door.location, wall.curve, thr.wall_snap_tol_mm):
                host = wall
                break
        if host is None:
            # interior wall may simply not be modeled in this fixture; only flag exterior doors,
            # which must be hosted in the building envelope.
            if door.is_exterior:
                violations.append(Violation(
                    rule_id="HAB041",
                    severity=Severity.WARNING,
                    refs=[door.id],
                    msg=(f"exterior door {door.id} at {tuple(door.location)} on level "
                         f"{door.level_id} is not hosted in any wall"),
                    fix_hint="place the exterior door on an envelope wall segment",
                ))
            continue
        seg_len = _seg_length(host.curve)
        if door.width_mm > seg_len:
            violations.append(Violation(
                rule_id="HAB041",
                severity=Severity.WARNING,
                refs=sorted([door.id, host.id]),  # D12: deterministic ordering
                msg=(f"door {door.id} width {door.width_mm:.0f} mm is wider than its host "
                     f"wall {host.id} segment ({seg_len:.0f} mm)"),
                fix_hint="narrow the door or widen/relocate the hosting wall",
            ))
    return violations


def check_hab042(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB042: each apartment's outer envelope must be substantially enclosed (walls + door openings).

    v1 scope: measures envelope-perimeter coverage by walls + door openings and fires below
    thr.min_envelope_coverage_ratio. Per-edge "gap > 50 mm" precision AND window openings are
    DEFERRED (spec §6 HAB042 full precision is tracked separately); v1 enforces substantial
    enclosure coverage only.
    """
    violations: list[Violation] = []
    v2 = checker_v2_enabled()
    if v2:
        # v2: consume DERIVED apartments (stamp-free), so the rule is never vacuous on
        # live extractions (apartment_id is not extracted from Revit — roadmap probe G:
        # a wall-stripped building must FAIL, not pass because no room was stamped).
        # Local import: graph.py does not import rules modules, so no cycle.
        from kukai.modeling.checker.graph import derive_apartments
        targets = [(apt.apartment_id, set(apt.room_ids))
                   for apt in derive_apartments(model, graph)]
    else:
        targets = [(apt_id, None)
                   for apt_id in sorted({r.apartment_id for r in model.rooms
                                         if r.apartment_id})]

    for apt_id, room_ids in targets:
        coverage = _apartment_envelope_coverage(model, apt_id, thr, room_ids=room_ids)
        if coverage is None:
            continue
        if coverage < thr.min_envelope_coverage_ratio:
            violations.append(Violation(
                rule_id="HAB042",
                severity=Severity.BLOCKING if v2 else Severity.WARNING,
                refs=[apt_id],
                msg=(f"apartment {apt_id} envelope is open: only {coverage * 100:.0f}% of its "
                     f"perimeter is enclosed by walls/door openings "
                     f"(coverage < {thr.min_envelope_coverage_ratio:.0%})"),
                fix_hint="close the apartment envelope with walls; leave openings only for "
                         "doors/windows",
            ))
    return violations
