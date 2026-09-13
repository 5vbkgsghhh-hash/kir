"""Minimum room-dimension rules (design §6): HAB020 area, HAB021 width, HAB022 height.

Pure, read-only per-room geometric checks. Severity and thresholds come from the
contract: areas/widths/heights live in `thresholds.py`, the function→threshold and
function→severity maps are the only rule-local 'common sense' (kept here, not magic
numbers — they reference Thresholds fields and RoomFunction members)."""
from __future__ import annotations

import networkx as nx
from shapely.geometry import Polygon

from kir.checker.flags import checker_v2_enabled
from kir.checker.function_provenance import (
    describe as describe_function,
)
from kir.checker.function_provenance import (
    is_authored as function_is_authored,
)
from kir.checker.height_provenance import describe, is_authored
from kir.checker.spatial_model import (
    RoomFunction,
    Severity,
    SpatialModel,
    Violation,
)
from kir.checker.thresholds import Thresholds


def _min_width_mm(boundary: list[tuple[float, float]],
                  holes: list[list[tuple[float, float]]] | None = None
                  ) -> float | None:
    """Minimum cross-section width (mm) of a room's outer boundary polygon.

    Width = 2 * sup{ r >= 0 : erosion at r leaves the polygon NONEMPTY AND CONNECTED }.

    🔴 THE CONNECTEDNESS CONDITION WAS ADDED 29.08.2026 (audit finding F-346,
    P0), AND WITHOUT IT THE MEASURE WAS NOT THE ONE DECLARED. The former
    docstring asserted: "a polygon of true minimum width w is erased at
    exactly an offset of w/2." This is true for CONVEX shapes and false for
    concave ones, and rooms are concave all the time.

    The live discriminator is a dumbbell: two 4000 mm squares joined by a
    500 mm neck. The neck disappears at r = 250, but the LOBES remain, and
    the bisection continues until the LARGER lobe disappears:

        was    _min_width_mm(dumbbell) = 3999.999999996 mm
        is now _min_width_mm(dumbbell) =  500.0 mm

    That is, the rule was certifying an impassable passage as a four-meter-
    wide room. What was being counted was NOT the minimum cross-section, but
    the diameter of the largest inscribed circle — a quantity that coincides
    with minimum width only in the convex case.

    Connectedness is exactly the missing condition: a passage's minimum
    cross-section is the radius at which the shape BREAKS APART, not merely
    shrinks. For a convex shape, breaking apart never happens, and the
    answer does not shift by a single step; for a concave one, it happens
    exactly at the narrow spot.

    🔴 THE BOUNDARY IS NAMED BY A NUMBER, NOT A WORD: TWO CASES OF THREE ARE
    FIXED. Measurement 29.08.2026 on five shapes, ground truth counted by
    hand:

        4000 square                 3999.8  ->  3999.8   (truth 4000)
        2000x8000 strip              2000.0  ->  2000.0   (truth 2000)
        dumbbell, 500 neck           4000.0  ->   500.0   (truth  500)  FIXED
        H-shaped, 800 bridge         2080.1  ->   800.0   (truth  800)  FIXED
        L-shaped, 2000 wing          2343.1  ->  2343.1   (truth 2000)  NO

    Connectedness closes the cases where the narrow spot TEARS the shape
    apart. It does not close the "thick corner" case: for an L-shaped room
    with 2000 mm wings, the largest inscribed circle sits in the corner and
    has a diameter of 2343 mm, because the shape there is thicker than the
    wing along the diagonal. Erosion does not tear apart there — the corner
    is the very last thing erased — and the measure still returns the
    inscribed circle's diameter, overstating the wing's width by 17%.

    This is NOT unfinished work but a named remainder: it is filed as a
    separate finding in the audit register (`E-16`) together with this
    measurement. It is fixed not by a condition but by a different measure —
    along the medial axis — and that is a separate wave.

    The 0.2 mm error on the 4000 square is `shapely.buffer`'s resolution; it
    existed before the fix too and does not affect the 1 mm threshold.

    Returns None when the boundary cannot form a valid polygon (< 3 points or
    zero area) — such a room is malformed, not a width violation, and is left to
    other rules.
    """
    if len(boundary) < 3:
        return None
    # 🔴 VOIDS ARE SUBTRACTED (F-041). Without them, width was overstated for
    # a "habitable" room wrapped around a shaft: erosion ran over the solid
    # shape. The `None` default is the former behavior, byte for byte.
    poly = Polygon(boundary, [h for h in (holes or ()) if len(h) >= 3])
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

    def _survives(radius: float) -> bool:
        """Whether a NONEMPTY AND CONNECTED shape remains after erosion.

        `buffer(-r)` returns a `MultiPolygon` as soon as the shape breaks
        apart — that is exactly the sign that the narrow spot has been
        passed. `geom_type` is queried, not `isinstance`: shapely returns a
        `GeometryCollection` for degenerate remainders, and that too means a
        break.
        """
        eroded = poly.buffer(-radius)
        if eroded.is_empty:
            return False
        return getattr(eroded, "geom_type", "") == "Polygon"

    # 40 bisection steps → sub-micron precision on mm-scale geometry; plenty for a 1 mm dial.
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if _survives(mid):
            lo = mid
        else:
            hi = mid
    return 2.0 * lo


def check_hab020(model: SpatialModel, graph: nx.Graph, thr: Thresholds) -> list[Violation]:
    """HAB020 — minimum room area by function.

    habitable ≥ min_area_zhilaya_m2, kitchen ≥ min_area_kuhnya_m2 → BLOCKING when under.
    bathroom ≥ min_area_sanuzel_m2 → WARNING when under.
    Functions without a threshold are not checked.

    🔴 A BLOCKING VERDICT DOES NOT STAND ON A FUNCTION THE AUTHOR DID NOT NAME
    (22.08.2026). The threshold here is chosen BY FUNCTION, and since 22.08
    the function can be DERIVED from furnishing: `ROOM_NAME` = "Помещение"
    for 1102 of 1102 MNVNK rooms, and the kind is named by a toilet, not the
    author. "Habitable area 6 m² against a minimum of 8" on a derived kind
    accuses TWICE — of the area, and of the room being habitable — and we
    derived the second one ourselves. So such a finding is printed as
    WARNING with a named reason (`function_provenance`), exactly as HAB022
    treats a substituted height. The threshold itself is NOT softened: the
    comparison is the same, what changes is the authority.
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
            # 🔴 PROVENANCE IS ALWAYS NAMED, BUT STRICTNESS DROPS ONLY FOR A
            # STRICT ONE. "Bathroom too small" is already a WARNING, and its
            # authority does not change here — but the reader must know that
            # this room was named a bathroom by a TOILET, not the author.
            # MNVNK measurement: of 281 derived functions, 258 are bathrooms,
            # meaning that without this line, the overwhelming majority of
            # findings about a derived kind would sound exactly like findings
            # about a read one.
            named = function_is_authored(room.function_source)
            why = ""
            if not named:
                why = f" ({describe_function(room.function_source)})"
            if severity is Severity.BLOCKING and not named:
                severity = Severity.WARNING
                why = (f", но вердикт НЕ блокирующий: "
                       f"{describe_function(room.function_source)}")
            violations.append(
                Violation(
                    rule_id="HAB020",
                    severity=severity,
                    refs=sorted([room.id]),
                    msg=(
                        f"Room '{room.name}' ({room.function.value}) area "
                        f"{room.area_m2:g} m² is below the minimum {required:g} m²{why}."
                    ),
                    fix_hint=(
                        f"Enlarge '{room.name}' to at least {required:g} m² "
                        f"(currently {room.area_m2:g} m²)."
                        + ("" if named else
                           " Назовите помещение в модели (ROOM_NAME) — тогда вердикт "
                           "станет строгим.")
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
        width = _min_width_mm(room.boundary, room.boundary_holes)
        if width is None:
            continue
        if width < required:
            # The same law as HAB020 two functions above: the threshold is
            # chosen BY FUNCTION, and a verdict cannot be strict on a derived
            # function.
            named = function_is_authored(room.function_source)
            why = "" if named else f" ({describe_function(room.function_source)})"
            if severity is Severity.BLOCKING and not named:
                severity = Severity.WARNING
                why = (f", но вердикт НЕ блокирующий: "
                       f"{describe_function(room.function_source)}")
            violations.append(
                Violation(
                    rule_id="HAB021",
                    severity=severity,
                    refs=sorted([room.id]),
                    msg=(
                        f"Room '{room.name}' ({room.function.value}) minimum width "
                        f"{width:.0f} mm is below the minimum {required:.0f} mm{why}."
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
    them out of this rule's subjects, so an all-unknown model reads NOT_EVALUATED).

    🔴 A BLOCKING VERDICT DOES NOT STAND ON A VALUE THE AUTHOR DID NOT DECLARE
    (20.08.2026). Before this fix, the rule read `height_mm` and did not ask
    about its provenance — and on the parsing path this is OUR OWN
    SUBSTITUTE (the bounding box's vertical span), so the rule was passing
    judgment on a number that is not in the project. Now `height_provenance`
    splits sources into three kinds, and a substituted value gives a WARNING
    instead of a BLOCKING, with a named reason.

    The distinction is observable, not decorative: the same 1200 mm room
    gives BLOCKING with `room_upper_offset` and WARNING with `room_bbox`.
    Without the difference, the field would exist and the distinction would
    not, and we would be reading a strict verdict over something never
    measured. The soft threshold (`min_ceiling_height_mm`) still fires THE
    SAME WAY: a substitute is no reason to miss a low ceiling, only a reason
    not to call it proven.
    """
    required = thr.min_ceiling_height_mm
    v2 = checker_v2_enabled()
    violations: list[Violation] = []
    for room in model.rooms:
        if room.height_mm is None:
            continue  # unmeasured — surfaced via coverage (v2), never a silent pass
        authored = is_authored(room.height_source)
        if v2 and not authored and room.height_mm < thr.min_ceiling_hard_mm:
            violations.append(
                Violation(
                    rule_id="HAB022",
                    severity=Severity.WARNING,
                    refs=sorted([room.id]),
                    msg=(
                        f"Room '{room.name}' ceiling height {room.height_mm:.0f} mm "
                        f"is below the uninhabitable hard floor "
                        f"{thr.min_ceiling_hard_mm:.0f} mm, но вердикт НЕ "
                        f"блокирующий: {describe(room.height_source)}."
                    ),
                    fix_hint=(
                        f"Объявите высоту '{room.name}' в модели (ROOM_UPPER_OFFSET "
                        f"либо ROOM_HEIGHT) — тогда вердикт станет строгим; "
                        f"по подставленной величине сейчас {room.height_mm:.0f} мм "
                        f"против требуемых {required:.0f} мм."
                    ),
                )
            )
            continue
        if v2 and authored and room.height_mm < thr.min_ceiling_hard_mm:
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
