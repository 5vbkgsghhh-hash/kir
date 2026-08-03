"""Structural-continuity rules (design §6): HAB050 vertical structural continuity.

Pure function over SpatialModel; no I/O, no mutation. Every numeric constant comes from
`thr` (Thresholds) — no magic numbers (design §11.4). HAB050 is WARNING: mid-air structure
is almost certainly a modelling error but the v1 ruleset stays lenient on structure and
tightens later (design §6 severity model).

v1 scope: the contract carries load only as structural `Wall`s (no Column/Beam yet), so
'load reaches ground' is checked wall-to-wall, floor-by-floor. A structural wall on level i
is supported if a structural wall on level i-1 lies (near-)collinear under its footprint
with enough projected overlap; the lowest level is the ground and is always supported.
Support is transitive: because every ground-level structural wall is supported, a wall
supported by a supported wall reaches the ground floor-by-floor."""
from __future__ import annotations

import math

import networkx as nx

from kukai.modeling.checker.spatial_model import SpatialModel, Severity, Violation, Wall
from kukai.modeling.checker.thresholds import Thresholds


def _segment(wall: Wall) -> tuple[tuple[float, float], tuple[float, float]]:
    """The wall's 2D curve as ((x1, y1), (x2, y2))."""
    (x1, y1), (x2, y2) = wall.curve
    return (x1, y1), (x2, y2)


def _point_to_line_distance(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    """Perpendicular distance from point p to the INFINITE line through a→b (mm).
    If a == b the segment is degenerate and we fall back to point-to-point distance."""
    px, py = p
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    seg_len = math.hypot(dx, dy)
    if seg_len == 0.0:
        return math.hypot(px - ax, py - ay)
    # |cross((b-a), (p-a))| / |b-a|
    cross = abs(dx * (py - ay) - dy * (px - ax))
    return cross / seg_len


def _projected_overlap_length(
    lower: tuple[tuple[float, float], tuple[float, float]],
    upper: tuple[tuple[float, float], tuple[float, float]],
) -> float:
    """Length (mm) of the upper segment's projection that overlaps the lower segment,
    measured along the upper segment's direction. 0 if the upper segment is degenerate."""
    (ux1, uy1), (ux2, uy2) = upper
    dx, dy = ux2 - ux1, uy2 - uy1
    u_len = math.hypot(dx, dy)
    if u_len == 0.0:
        return 0.0
    ux, uy = dx / u_len, dy / u_len  # unit direction of the upper segment

    def project(pt: tuple[float, float]) -> float:
        return (pt[0] - ux1) * ux + (pt[1] - uy1) * uy

    # Upper segment spans [0, u_len] in its own parameter.
    lo_lower, hi_lower = sorted((project(lower[0]), project(lower[1])))
    lo = max(0.0, lo_lower)
    hi = min(u_len, hi_lower)
    return max(0.0, hi - lo)


def _supports(lower: Wall, upper: Wall, thr: Thresholds) -> bool:
    """True if `lower` lies under `upper`'s footprint within tolerance: both endpoints of
    `lower` are within struct_support_offset_mm of the upper line AND the projected overlap
    is at least struct_min_support_overlap_mm."""
    a, b = _segment(upper)
    la, lb = _segment(lower)
    if _point_to_line_distance(la, a, b) > thr.struct_support_offset_mm:
        return False
    if _point_to_line_distance(lb, a, b) > thr.struct_support_offset_mm:
        return False
    overlap = _projected_overlap_length((la, lb), (a, b))
    return overlap >= thr.struct_min_support_overlap_mm


def check_hab050(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB050 — vertical structural continuity (load reaches ground). WARNING.

    Each structural wall above the ground level must have a structural wall under its
    footprint on the level immediately below (within tolerance). A structural wall with
    nothing under it is mid-air structure (design §6)."""
    violations: list[Violation] = []

    levels_sorted = sorted(model.levels, key=lambda lvl: lvl.index)
    if not levels_sorted:
        return violations
    # index -> the level immediately below (None for the ground level).
    below_of: dict[str, str | None] = {}
    prev_id: str | None = None
    for lvl in levels_sorted:
        below_of[lvl.id] = prev_id
        prev_id = lvl.id

    # Structural walls grouped by level for O(1) lookup of the level below.
    struct_by_level: dict[str, list[Wall]] = {}
    for wall in model.walls:
        if wall.is_structural:
            struct_by_level.setdefault(wall.level_id, []).append(wall)

    for level_id, walls in struct_by_level.items():
        below_id = below_of.get(level_id)
        if below_id is None:
            continue  # ground level — supported by the ground, never flagged
        lower_walls = struct_by_level.get(below_id, [])
        for upper in walls:
            if any(_supports(lower, upper, thr) for lower in lower_walls):
                continue
            violations.append(
                Violation(
                    rule_id="HAB050",
                    severity=Severity.WARNING,
                    refs=sorted([upper.id]),
                    msg=(
                        f"Structural wall {upper.id!r} on level {level_id!r} has no "
                        f"support below it (mid-air structure): no structural wall on "
                        f"level {below_id!r} lies under its footprint within "
                        f"{thr.struct_support_offset_mm:.0f} mm."
                    ),
                    fix_hint=(
                        "Add a structural wall (or load path) on the level below, under "
                        f"this wall's footprint with >= "
                        f"{thr.struct_min_support_overlap_mm:.0f} mm of overlap, so the "
                        "load reaches the ground."
                    ),
                )
            )
    return violations
