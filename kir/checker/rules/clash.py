"""rules/clash.py — planar clash & enclosure rules (design §6: HAB040–042).

HAB040  room footprints on a level must not overlap (>0.05 m²)   BLOCKING
HAB041  door hosted in a wall, width <= wall, swings into a room  WARNING
HAB042  apartment/level envelope substantially enclosed           WARNING (v1)
                                                                  BLOCKING (v2)

Geometry uses shapely Polygons. A cheap inline AABB prefilter (computed from Room.boundary)
skips shapely intersection on non-touching pairs — the GROUND:geometry AABB-before-exact idea
applied to our own contract (see plan cross-component note); we deliberately do NOT import
execution/geometry_gate._aabb_overlap, which is typed for ElementGeometry, not our boundary.
"""
from __future__ import annotations

import math
from itertools import combinations

import networkx as nx
from shapely.geometry import Polygon
from shapely.ops import unary_union

from kir.checker.flags import checker_v2_enabled
from kir.checker.spatial_model import (
    Room, Severity, SpatialModel, Violation,
)
from kir.checker.thresholds import Thresholds

# shapely areas are in mm² (boundary coords are mm); convert to m² with this factor.
_MM2_PER_M2 = 1_000_000.0


def _polygon(boundary: list[tuple[float, float]],
             holes: list[list[tuple[float, float]]] | None = None) -> Polygon | None:
    """Build a shapely Polygon from a boundary loop; None if degenerate (<3 pts).

    🔴 HOLES ARE SUBTRACTED (F-041, 29.08.2026). Without them HAB040 thinks a room
    also occupies its own shaft: two apartments around ONE shared shaft got a false
    "area overlap". The `None` default leaves previous inputs byte-for-byte.
    """
    if boundary is None or len(boundary) < 3:
        return None
    poly = Polygon(boundary, [h for h in (holes or ()) if len(h) >= 3])
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


def _wall_spans_on_edge(edge: tuple[tuple[float, float], tuple[float, float]],
                        curve: tuple[tuple[float, float], tuple[float, float]],
                        tol_mm: float) -> tuple[float, float] | None:
    """The part of a perimeter EDGE (as a [0, 1] parameter span) covered by a wall
    segment — or None when the wall is not collinear with it.

    🔴 DIRECTION FIRST, LENGTH SECOND (the F-253 law, `derive._seg_ring_overlap`).
    BOTH ends of the wall must lie within `tol_mm` of the edge's LINE; a wall
    crossing the perimeter at a right angle gets nothing, however long it is.
    The distance is taken to the LINE, not to the segment, so a wall longer
    than the edge still covers it — clamped to the edge itself.
    """
    (ex0, ey0), (ex1, ey1) = edge
    (wx0, wy0), (wx1, wy1) = curve
    edx, edy = ex1 - ex0, ey1 - ey0
    elen_sq = edx * edx + edy * edy
    if elen_sq <= 0.0:
        return None
    elen = math.sqrt(elen_sq)
    if (wx0 - wx1) * (wx0 - wx1) + (wy0 - wy1) * (wy0 - wy1) <= 0.0:
        return None                                    # a point-sized wall covers nothing
    # 1. collinearity: perpendicular distance of BOTH wall ends to the edge's line
    if max(abs((wx0 - ex0) * edy - (wy0 - ey0) * edx),
           abs((wx1 - ex0) * edy - (wy1 - ey0) * edx)) > tol_mm * elen:
        return None
    # 2. overlap: the wall's ends in the EDGE's parameter, clamped to the edge
    t0 = ((wx0 - ex0) * edx + (wy0 - ey0) * edy) / elen_sq
    t1 = ((wx1 - ex0) * edx + (wy1 - ey0) * edy) / elen_sq
    lo, hi = sorted((t0, t1))
    lo, hi = max(lo, 0.0), min(hi, 1.0)
    return (lo, hi) if hi > lo else None


def _disc_span_on_edge(edge: tuple[tuple[float, float], tuple[float, float]],
                       center: tuple[float, float], radius_mm: float) -> tuple[float, float] | None:
    """The [0, 1] span of a perimeter edge inside a disc — a door opening of
    clear width `2 * radius_mm` around the door's location. Same measure as the
    former `Point(location).buffer(width / 2) ∩ perimeter`, kept analytic so it
    can be MERGED with the wall spans instead of unioned as an area."""
    (ex0, ey0), (ex1, ey1) = edge
    cx, cy = center
    edx, edy = ex1 - ex0, ey1 - ey0
    elen_sq = edx * edx + edy * edy
    if elen_sq <= 0.0 or radius_mm <= 0.0:
        return None
    # |E0 + t·d − C|² = r²  →  a·t² + b·t + c = 0
    fx, fy = ex0 - cx, ey0 - cy
    b = 2.0 * (fx * edx + fy * edy)
    c = fx * fx + fy * fy - radius_mm * radius_mm
    disc = b * b - 4.0 * elen_sq * c
    if disc <= 0.0:
        return None
    root = math.sqrt(disc)
    lo, hi = (-b - root) / (2.0 * elen_sq), (-b + root) / (2.0 * elen_sq)
    lo, hi = max(lo, 0.0), min(hi, 1.0)
    return (lo, hi) if hi > lo else None


def _merged_span_length(spans: list[tuple[float, float]]) -> float:
    """Total length of the union of [lo, hi] spans on one edge — a wall and a
    door over the same stretch are counted ONCE."""
    total, cur_lo, cur_hi = 0.0, None, None
    for lo, hi in sorted(spans):
        if cur_hi is None or lo > cur_hi:
            if cur_hi is not None:
                total += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    if cur_hi is not None:
        total += cur_hi - cur_lo
    return total


def _envelope_coverage_detail(model: SpatialModel, apt_id: str, thr: Thresholds,
                              room_ids: set[str] | frozenset[str] | None = None
                              ) -> tuple[float | None, int, int]:
    """`(coverage, walls_on_level, walls_without_thickness)` for apartment `apt_id`.

    Coverage is the fraction (0..1) of the apartment's envelope perimeter that is
    actually enclosed — backed by a wall or spanned by a door opening. LENGTH-based:
    every cover is a span on a perimeter edge, spans are merged per edge, so a
    point-sized wall cannot fake enclosure, a door contributes its own width once,
    and a wall under a door is not counted twice. `None` if no usable room
    polygons / zero perimeter.

    🔴 A WALL IS NOT AN AXIS (11.09.2026). The cover used to be
    `LineString(wall.curve).buffer(thr.wall_snap_tol_mm)` — a ±50 mm strip
    around the wall's centerline. But a Revit room boundary lies on the wall
    FACE, half a thickness away from that centerline: native witness
    2026-09-09, four walls at x=0/10000 and y=0/8000, room boundary at
    100…9890 × 110…7900 — a CLOSED 76.26 m² room measured "2 % enclosed" and
    HAB042 blocked it. The strip was also blind to direction (F-253): a wall
    crossing the facade at a right angle picked up `2·tol` of "cover".

    Now each wall reaches `thr.wall_snap_tol_mm + thickness_mm / 2` from its
    axis when its thickness is KNOWN (`Wall.thickness_mm`, three-state), and
    only when BOTH its ends are collinear with the edge. When the thickness is
    unknown the reach stays at the snap alone — the same number as before —
    and the caller is told HOW MANY walls were read without a thickness, so a
    false "open" names its source rather than asking for a bigger constant.
    Window openings and per-edge gap>50 mm precision remain deferred (design §6 HAB042).
    """
    if room_ids is not None:
        rooms = [r for r in model.rooms if r.id in room_ids]
    else:
        rooms = [r for r in model.rooms if r.apartment_id == apt_id]
    if not rooms:
        return None, 0, 0
    level_id = rooms[0].level_id
    polys = [p for p in (_polygon(r.boundary, r.boundary_holes)
                         for r in rooms) if p is not None]
    if not polys:
        return None, 0, 0
    union = unary_union(polys)
    rings = [g.exterior for g in getattr(union, "geoms", [union])
             if not g.is_empty and hasattr(g, "exterior")]
    total = sum(ring.length for ring in rings)
    if total <= 0.0:
        return None, 0, 0

    walls = [w for w in model.walls if w.level_id == level_id]
    unknown = sum(1 for w in walls if w.thickness_mm is None)
    reach = [(w.curve, thr.wall_snap_tol_mm + (w.thickness_mm / 2.0 if w.thickness_mm is not None else 0.0))
             for w in walls]
    discs = [(tuple(d.location), max(d.width_mm, 1.0) / 2.0)
             for d in model.doors if d.level_id == level_id]
    if not reach and not discs:
        return 0.0, len(walls), unknown

    covered = 0.0
    for ring in rings:
        coords = list(ring.coords)
        for e0, e1 in zip(coords, coords[1:]):
            edge = ((float(e0[0]), float(e0[1])), (float(e1[0]), float(e1[1])))
            elen = _seg_length(edge)
            if elen <= 0.0:
                continue
            spans: list[tuple[float, float]] = []
            for curve, tol in reach:
                span = _wall_spans_on_edge(edge, curve, tol)
                if span is not None:
                    spans.append(span)
            for center, radius in discs:
                span = _disc_span_on_edge(edge, center, radius)
                if span is not None:
                    spans.append(span)
            if spans:
                covered += _merged_span_length(spans) * elen
    return min(covered / total, 1.0), len(walls), unknown


def _apartment_envelope_coverage(model: SpatialModel, apt_id: str, thr: Thresholds,
                                 room_ids: set[str] | frozenset[str] | None = None) -> float | None:
    """Fraction (0..1) of apartment apt_id's envelope perimeter that is actually enclosed.
    See `_envelope_coverage_detail` for the measure; this keeps the float | None contract."""
    return _envelope_coverage_detail(model, apt_id, thr, room_ids=room_ids)[0]


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
            poly_a = polys.get(a.id) or _polygon(a.boundary, a.boundary_holes)
            poly_b = polys.get(b.id) or _polygon(b.boundary, b.boundary_holes)
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

    # The host is addressed BY NAME, not by search: see F-347 below.
    walls_by_id = {wall.id: wall for wall in model.walls}
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
        #
        # 🔴 THE HOST IS READ, NOT GUESSED (F-347, 30.08.2026). It used to be
        # "the first wall of the level within tolerance", and the verdict depended on
        # LIST ORDER: the same door on the same building would pass
        # against a long foreign wall and fail against its own short one.
        # The order of the wall list is not a property of the building.
        #
        # `Door.host_wall_id` is a MEASUREMENT, not a declaration: both sides put
        # there the host read from Revit (`extractor.cs` — `d.Host.Id`,
        # `design_check` — the decompile's host). Asking geometry when you have the
        # provider's answer means trading a measurement for a guess.
        #
        # MEASUREMENT 30.08 across 81 decompiles: 31 003 doors across 34 buildings, of
        # which 29 889 have a DECLARED host. The guessed wall disagrees with the declared
        # one for 821 doors across 30 buildings, and for 92 doors across 12 buildings this
        # CHANGES THE VERDICT ITSELF of HAB041.
        host = walls_by_id.get(door.host_wall_id or "")
        if host is not None and host.level_id != door.level_id:
            host = None                     # a host from another level is not a host
        near: list = []
        if host is None and not door.host_wall_id:
            near = [wall for wall in walls_by_level.get(door.level_id, [])
                    if _point_on_segment(door.location, wall.curve,
                                         thr.wall_snap_tol_mm)]
            if len(near) == 1:
                host = near[0]
        if host is None:
            if len(near) > 1:
                # AMBIGUITY IS NAMED, NOT RESOLVED BY SORTING. Picking
                # the longest would systematically EXONERATE the door (the building
                # looks safer on paper); picking the shortest would systematically
                # CONVICT it. Both substitutions are worse than an honest "nothing to measure with".
                violations.append(Violation(
                    rule_id="HAB041",
                    severity=Severity.WARNING,
                    refs=sorted([door.id] + [wall.id for wall in near]),
                    msg=(f"door {door.id} declares no host wall and {len(near)} wall "
                         f"segments lie within {thr.wall_snap_tol_mm:.0f} mm of it "
                         f"({', '.join(sorted(w.id for w in near))}) — the width check "
                         f"was NOT applied"),
                    fix_hint="stamp the door's host wall (Door.host_wall_id) or move "
                             "the neighbouring wall segment out of the snap tolerance",
                ))
                continue
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
        from kir.checker.graph import derive_apartments
        targets = [(apt.apartment_id, set(apt.room_ids))
                   for apt in derive_apartments(model, graph)]
    else:
        targets = [(apt_id, None)
                   for apt_id in sorted({r.apartment_id for r in model.rooms
                                         if r.apartment_id})]

    for apt_id, room_ids in targets:
        coverage, wall_count, unknown = _envelope_coverage_detail(
            model, apt_id, thr, room_ids=room_ids)
        if coverage is None:
            continue
        if coverage < thr.min_envelope_coverage_ratio:
            # A false "open" must NAME its source: a wall read without a
            # thickness reaches only the snap (50 mm) from its axis, while a
            # Revit room boundary sits on the FACE — up to half a thickness
            # further out (native witness 2026-09-09).
            source = ""
            if unknown:
                source = (f"; wall thickness unknown for {unknown} of {wall_count} walls on "
                          f"this level — a room boundary on the wall FACE may lie beyond the "
                          f"{thr.wall_snap_tol_mm:.0f} mm snap around the axis")
            violations.append(Violation(
                rule_id="HAB042",
                severity=Severity.BLOCKING if v2 else Severity.WARNING,
                refs=[apt_id],
                msg=(f"apartment {apt_id} envelope is open: only {coverage * 100:.0f}% of its "
                     f"perimeter is enclosed by walls/door openings "
                     f"(coverage < {thr.min_envelope_coverage_ratio:.0%}){source}"),
                fix_hint="close the apartment envelope with walls; leave openings only for "
                         "doors/windows",
            ))
    return violations
