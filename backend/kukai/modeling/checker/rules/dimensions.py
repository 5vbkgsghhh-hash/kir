"""Minimum room-dimension rules (design §6): HAB020 area, HAB021 width, HAB022 height.

Pure, read-only per-room geometric checks. Severity and thresholds come from the
contract: areas/widths/heights live in `thresholds.py`, the function→threshold and
function→severity maps are the only rule-local 'common sense' (kept here, not magic
numbers — they reference Thresholds fields and RoomFunction members)."""
from __future__ import annotations

import networkx as nx
from shapely.geometry import Polygon

from kukai.modeling.checker.flags import checker_v2_enabled
from kukai.modeling.checker.spatial_model import (
    RoomFunction,
    Severity,
    SpatialModel,
    Violation,
)
from kukai.modeling.checker.thresholds import Thresholds


def _min_width_mm(boundary: list[tuple[float, float]]) -> float | None:
    """Minimum cross-section width (mm) of a room's outer boundary polygon.

    A polygon of true minimum width `w` is eroded to empty exactly when buffered
    inward by `w / 2`. We bisect the erosion radius to find that threshold:
    min_width = 2 * sup{ r >= 0 : polygon.buffer(-r) is non-empty }.

    Returns None when the boundary cannot form a valid polygon (< 3 points or
    zero area) — such a room is malformed, not a width violation, and is left to
    other rules.
    """
    if len(boundary) < 3:
        return None
    poly = Polygon(boundary)
    if not poly.is_valid:
        poly = poly.buffer(0)  # repair self-touching/duplicate-vertex loops
    if poly.is_empty or poly.area <= 0.0:
        return None

    # Upper bound for the half-width: a polygon can be no wider than its bbox short side.
    minx, miny, maxx, maxy = poly.bounds
    hi = min(maxx - minx, maxy - miny) / 2.0
    if hi <= 0.0:
        return None
    lo = 0.0
    # 40 bisection steps → sub-micron precision on mm-scale geometry; plenty for a 1 mm dial.
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if poly.buffer(-mid).is_empty:
            hi = mid
        else:
            lo = mid
    return 2.0 * lo


def check_hab020(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB020 — minimum room area by function.

    жилая ≥ min_area_zhilaya_m2, кухня ≥ min_area_kuhnya_m2 → BLOCKING when under.
    санузел ≥ min_area_sanuzel_m2 → WARNING when under.
    Functions without a threshold are not checked.
    """
    # function → (required area m², severity). Only functions listed are checked.
    area_rules: dict[RoomFunction, tuple[float, Severity]] = {
        RoomFunction.ЖИЛАЯ: (thr.min_area_zhilaya_m2, Severity.BLOCKING),
        RoomFunction.КУХНЯ: (thr.min_area_kuhnya_m2, Severity.BLOCKING),
        RoomFunction.САНУЗЕЛ: (thr.min_area_sanuzel_m2, Severity.WARNING),
    }
    violations: list[Violation] = []
    for room in model.rooms:
        rule = area_rules.get(room.function)
        if rule is None:
            continue
        required, severity = rule
        if room.area_m2 < required:
            violations.append(
                Violation(
                    rule_id="HAB020",
                    severity=severity,
                    refs=sorted([room.id]),
                    msg=(
                        f"Room '{room.name}' ({room.function.value}) area "
                        f"{room.area_m2:g} m² is below the minimum {required:g} m²."
                    ),
                    fix_hint=(
                        f"Enlarge '{room.name}' to at least {required:g} m² "
                        f"(currently {room.area_m2:g} m²)."
                    ),
                )
            )
    return violations


def check_hab021(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB021 — minimum room width (WARNING).

    жилая ≥ min_width_zhilaya_mm, коридор ≥ min_width_koridor_mm. Width is the
    minimum cross-section of the boundary polygon (shapely negative buffer).
    Rooms whose function has no width threshold, or whose boundary is unusable,
    are skipped.
    """
    width_rules: dict[RoomFunction, tuple[float, Severity]] = {
        RoomFunction.ЖИЛАЯ: (thr.min_width_zhilaya_mm, Severity.WARNING),
        RoomFunction.КОРИДОР: (thr.min_width_koridor_mm, Severity.WARNING),
    }
    if checker_v2_enabled():
        # v2: kitchens/bathrooms gain width floors. A 1.3 m 'kitchen' physically cannot
        # hold a counter + passage — measured impossibility is BLOCKING (probe F).
        width_rules[RoomFunction.КУХНЯ] = (thr.min_width_kuhnya_mm, Severity.BLOCKING)
        width_rules[RoomFunction.САНУЗЕЛ] = (thr.min_width_sanuzel_mm, Severity.WARNING)
    violations: list[Violation] = []
    for room in model.rooms:
        rule = width_rules.get(room.function)
        if rule is None:
            continue
        required, severity = rule
        width = _min_width_mm(room.boundary)
        if width is None:
            continue
        if width < required:
            violations.append(
                Violation(
                    rule_id="HAB021",
                    severity=severity,
                    refs=sorted([room.id]),
                    msg=(
                        f"Room '{room.name}' ({room.function.value}) minimum width "
                        f"{width:.0f} mm is below the minimum {required:.0f} mm."
                    ),
                    fix_hint=(
                        f"Widen '{room.name}' so its narrowest cross-section is at "
                        f"least {required:.0f} mm (currently {width:.0f} mm)."
                    ),
                )
            )
    return violations


def check_hab022(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB022 — minimum ceiling height. Applies to every room with a KNOWN height.

    v1: WARNING below min_ceiling_height_mm. v2: additionally BLOCKING below the hard
    uninhabitable floor (min_ceiling_hard_mm) — a 1.2 m 'bedroom' must fail, not warn.
    Rooms with height_mm=None are skipped here (unknown ≠ pass: the v2 engine counts
    them out of this rule's subjects, so an all-unknown model reads NOT_EVALUATED)."""
    required = thr.min_ceiling_height_mm
    v2 = checker_v2_enabled()
    violations: list[Violation] = []
    for room in model.rooms:
        if room.height_mm is None:
            continue  # unmeasured — surfaced via coverage (v2), never a silent pass
        if v2 and room.height_mm < thr.min_ceiling_hard_mm:
            violations.append(
                Violation(
                    rule_id="HAB022",
                    severity=Severity.BLOCKING,
                    refs=sorted([room.id]),
                    msg=(
                        f"Room '{room.name}' ceiling height {room.height_mm:.0f} mm "
                        f"is below the uninhabitable hard floor "
                        f"{thr.min_ceiling_hard_mm:.0f} mm."
                    ),
                    fix_hint=(
                        f"Raise the ceiling of '{room.name}' to at least "
                        f"{required:.0f} mm (currently {room.height_mm:.0f} mm)."
                    ),
                )
            )
            continue
        if room.height_mm < required:
            violations.append(
                Violation(
                    rule_id="HAB022",
                    severity=Severity.WARNING,
                    refs=sorted([room.id]),
                    msg=(
                        f"Room '{room.name}' ceiling height {room.height_mm:.0f} mm "
                        f"is below the minimum {required:.0f} mm."
                    ),
                    fix_hint=(
                        f"Raise the ceiling of '{room.name}' to at least "
                        f"{required:.0f} mm (currently {room.height_mm:.0f} mm)."
                    ),
                )
            )
    return violations
