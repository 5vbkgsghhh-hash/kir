"""KIR static geometry law (v1.1, VISION §5а / slab-saga fixes).

Everything a runtime Revit refusal taught us on 2026-07-17 is caught at the
T stage now: the duplicate closing point (iter-1: ShortCurveTolerance) is
NORMALIZED away ("closed ring implied"), any other near-zero edge and any
self-intersection is a typed refusal, and a hole touching the outer boundary
(iter-2: "curve loops intersect") never reaches Revit. Pure python, shared
by validate() and future reference-interpreter (12.6c).
"""
from __future__ import annotations

import bisect
import math
from typing import Optional

from kir.diag import Diagnostic, TYPE_BOUNDS, TYPE_GEOM_RELATION

_EDGE_TOL = 1.0          # mm: edges shorter than this are runtime kills
_TOUCH_TOL = 1.0         # mm: hole vertex closer than this to the outline = touch

# ───────────────────── THE POLYGON PROFILE LAW ──────────────────────────────
#
# ONE OWNER FOR BOTH DIRECTIONS, and this is not a matter of taste. Before
# 10.08.2026 these four numbers sat as BARE LITERALS in three places at
# once, and the three places carry a DIFFERENT COST for disagreement:
#
#   * ``authoring_validation`` (the forward direction) — exceeding it is a
#     TYPED REFUSAL the user sees: KIR-T001 with `expected`/`got`;
#   * ``decompile/lift`` (the reverse direction) — exceeding it SILENTLY
#     turns the element into an atom. The lifter's own comment read
#     "Mirror the existing forward polygon laws," meaning it KNEW it was
#     repeating someone else's law, and still copied the numbers by hand;
#   * ``contour`` (the CONTOUR sublanguage) — the same profile, a third
#     set of literals.
#
# A mismatch between any pair produces the worst possible outcome for
# this compiler: the lifter hands back an atom where the compiler would
# have built, or builds a program the compiler will reject — and in both
# cases the diagnosis will name the consequence, not the cause. So here
# stands the NAME, and there a REFERENCE to the name; there is no longer
# a second answer anywhere in the tree to the question "how many points
# does a profile hold."
#
# THE PROVENANCE IS ASSIGNED, NOT MEASURED. The numbers arrived with the
# language itself: 3..64 points and an area of 0.01 m² — `693da3df`
# (16.07.2026, "v1 op-set full"), 8 openings of 32 points each — from the
# same commit, CONTOUR repeated them in `6875d574` (17.07.2026, "v2
# invention"), the lifter — `a0b689d9` (18.07.2026). Not one of them is
# derived from a Revit limit or measured against a building; this is the
# author's choice
#
# 🔴 THE NUMBERS ABOVE ARE HISTORY, NOT THE ACTIVE LIMIT (amendment
# 02.09.2026). The ring was raised 64 -> 256, the opening ring 32 -> 128
# on MEASURED harm (external inputs rejected 67 of 652 rings, 82 of 183
# openings). The active values are below, in the constants themselves;
# the provenance is kept here, and kept ON PURPOSE: this line answers
# "where it came from," not "what it is now." Whoever is looking for the
# limit takes the constant, not the comment.
# of the language, about which profile deserves to be expressed as an
# op-code, rather than a property of Revit. This is said outright,
# because "a boundary invented by reasoning" is a recurring defect of
# this code (`create_door.sill_mm min_val=0`, `_SHEET_LIMIT_MM`), and
# whoever next wants to move it must see that moving it is allowed.
#
# WHAT IS KNOWN ABOUT THEM BY MEASUREMENT, not by reasoning
# (`tools/bounds_audit.py --measure`, 10.08.2026, three saved decompiles:
# k2_ar_rd_v6 "13A-RD-AR-K2", demo-v3, sob62_fas_r23_v17). The figures sit
# next to each name below; their overall meaning is that TWO of the four
# reject real buildings, and TWO rejected nothing. Neither is fixed here:
# the 10.08 wave is about NAMES, and silently moving a value would mean
# burying a measurement under a refactor.
MIN_RING_POINTS = 3            # fewer than three points is not a polygon

#: 🔴 A TWO-POINT RING IS LEGAL IF BOTH EDGES ARE ARCS. MEASURED 21.08.2026.
#:
#: The argument behind `MIN_RING_POINTS` — "fewer than three points is
#: not a polygon" — is true for a POLYGON and false for a ring carrying
#: arcs. Two half-arcs close a region; one segment or one arc does not.
#:
#: The cost of the mistake was measured on a real building: 18 family
#: forms were rejected for the sole reason that Revit represents a
#: CIRCLE as two half-arcs. That is a Ø130 flue, a Ø160 roof drain, a
#: round table, a fireplace — round things, which make up most of
#: engineering families. The language could express a circle with three
#: arcs and still can; what was being rejected was not a lack of
#: capability but SOMEONE ELSE'S way of writing the same shape.
#:
#: The rule is narrow ON PURPOSE: exactly two edges and BOTH arcs. Two
#: segments give a degenerate sliver, an arc with a segment gives an
#: unclosed crescent. The check sits AFTER `arcs` parsing, because
#: nothing is known about arcs before that.
MIN_RING_POINTS_ARCED = 2

#: Points in the OUTER ring of the profile.
#:
#: 🔴 IT USED TO BE 64. RAISED TO 256 BY MEASUREMENT ON 02.09.2026, AND
#: BOTH SIDES WERE MEASURED.
#:
#: THE HARM OF THE OLD NUMBER was re-measured with the same instrument
#: (`bounds_audit --measure`) on the same three buildings, and it
#: reproduced to the unit: 67 of 652 rings rejected (tower 65/317, demo
#: 2/235, facade 0/100), the worst ring at 130 points — TWICE the old
#: limit. On the forward pass this is a refusal the author will see; on
#: the reverse pass it is a silent atom, and these are exactly the
#: elements the 31.07 boundary census put at the top of the harm
#: ranking.
#:
#: THE COST OF THE UPPER BOUND IS MEASURED, NOT ESTIMATED, AND THE
#: MEASUREMENT HAD TO BE DONE TWICE (`create_floor_by_contour`, a
#: regular polygon, Revit 2026, the whole emission, minimum of five runs
#: — noise only ADDS):
#:
#:      points   C# chars   before ms   after ms
#:         32       19 457        4.4        3.6
#:         64       22 713        9.9        5.0
#:        128       29 209       28.7        9.2
#:        256       42 265       94.4       17.5
#:      per doubling            x2.2..3.3   x1.4..1.9
#:
#: CHARACTER COUNT is linear and always was: exactly ~102 chars per
#: point, not a single break. TIME WAS NOT LINEAR: before the fix it grew
#: as ~n^1.7, and the exponent ITSELF WAS GROWING — meaning the old limit
#: of 64 was not holding down the cost but the INVISIBILITY of the
#: quadratic self-intersection check (form 10: a cost that grows with
#: `n` is invisible to an instrument whose `n` equals three: at 64
#: points there are 1,952 pairs, and the walk drowned in noise). Raising
#: the limit would have made it reachable, so the all-pairs walk was
#: replaced with a SWEEP (`_first_self_intersection` below): 124x on the
#: check itself at 256 points, 500x at 1024, and 5.38x across the whole
#: ring emission.
#:
#: So 256 was chosen NOT for its cost, but for its MARGIN: twice the
#: worst observed ring (130), the same way the old 64 was twice BELOW
#: it.
#:
#: WHAT THIS LIMIT HOLDS DOWN, BESIDES ITSELF: the cost of emission and
#: of the bounding-box witness, and both are linear. It holds down
#: NEITHER a Revit limit (ShortCurveTolerance is guarded separately by
#: `_EDGE_TOL`) NOR human readability — the reader here is an LLM, and
#: "too many points to hold in your head" is an argument about a human
#: hand.
MAX_RING_POINTS = 256

#: Openings (inner rings) in one profile. MEASURED: 0 rejected across
#: three buildings. "Never fired" is not the same as "correct": a corpus
#: of three buildings simply does not reach it.
MAX_HOLES = 8

#: Points in an OPENING ring. THE MOST HARMFUL OF THE FOUR, and this is
#: visible only by measurement.
#:
#: 🔴 IT USED TO BE 32. RAISED TO 128 BY MEASUREMENT ON 02.09.2026. The
#: harm was re-measured and reproduced to the unit: 82 of 183 rings
#: rejected, with ALL 82 on one single building, where they are 82 of 85
#: (96%); the worst ring at 92 points. Because of this limit, the
#: demo-v3 building lost nearly all openings in its profiles. 128 is
#: twice the worst observed, by the same yardstick as the outer ring.
#:
#: The cost is the same linear one as the outer ring (see the table
#: above): an opening pays the same ~102 chars per point.
#:
#: 🔴 THE DISAGREEMENT WITH ITS NEIGHBOR REMAINS NAMED, NOT FIXED. The
#: CONTOUR route measures the opening ring with the same
#: `MAX_RING_POINTS`, meaning the same profile has two different answers
#: in the tree — 128 via the polygon route and 256 via the contour
#: route. It used to be 32 against 64: the same ratio, the same
#: dispute. It is deliberately NOT fixed here: reducing the two routes
#: to one number is a decision about the LANGUAGE, not about a limit,
#: and making it a side effect of the raise would mean adopting it
#: silently. After the raise, the dispute is harmless FOR THE FIRST
#: TIME: both numbers exceed the worst observed ring (92).
MAX_HOLE_RING_POINTS = 128

#: Below this area, a ring is treated as DEGENERATE — a line, not a
#: profile.
#:
#: 🔴 IT USED TO BE 10,000 mm² (0.01 m²). LOWERED TO 100 mm² BY
#: MEASUREMENT ON 21.08.2026.
#:
#: The old argument was honest and measured: "0 rejected out of 709
#: rings, the smallest real ring in the tower is 62,500 mm², six times
#: above the limit." The mistake was not in the measurement but in the
#: POPULATION: what was measured were BUILDING rings — walls, slabs,
#: floors. FAMILY profiles live two orders of magnitude smaller, and a
#: threshold harmless for the former rejects the latter wholesale.
#:
#: MEASURED ON FAMILY PROFILES (a real building, 110 families, 283
#: forms): under the code "degenerate contour," 20 forms were rejected,
#: and here is what they were —
#:
#:      200 mm²  (  2.0 cm²)  Труба_Полоса
#:      625 mm²  (  6.2 cm²)  Балясина — Квадратная 25×25 мм
#:      759 mm²  (  7.6 cm²)  Дверь_внутриквартирная ГОСТ 475
#:     2581 mm²  ( 25.8 cm²)  М_Стол кухонный_Круглый
#:
#: Not one of them is degenerate: a 25×25 mm baluster is an ordinary
#: element, and the 10,000 mm² threshold is a 100×100 mm square it
#: cannot fit inside BY CONSTRUCTION. The smallest real one is 200 mm².
#:
#: WHY EXACTLY 100, NOT LESS AND NOT MORE. From below, the threshold is
#: tied to `_EDGE_TOL = 1 mm` (an edge shorter than that dies at
#: runtime): a square with a side equal to the tolerance gives 1 mm²,
#: and everything above it is theoretically expressible. But a 1 mm²
#: ring with edges at the tolerance is a scrap, not a profile. 100 mm²
#: (1 cm²) sits twice below the smallest MEASURED real profile and a
#: hundred times above the limit derived from the edge tolerance.
#: Building rings are unaffected: the smallest of the 709 was 62,500
#: mm², 625 times above the new threshold.
#:
#: The relaxation works in ONE direction only — what was rejected before
#: will now be accepted. It cannot by construction break anything
#: already accepted.
MIN_RING_AREA_MM2 = 100.0


def degenerate_ring_ru(field: str) -> str:
    """The ONE AND ONLY carrier of the phrase "degenerate contour."

    🔴 WHY A FUNCTION, NOT TWO f-STRINGS. On 21.08.2026 the threshold was
    lowered from 10,000 to 100 mm². The refusal text in `contour.py` was
    fixed in the same commit, while the SECOND carrier of the same
    phrase — in `authoring_validation.py` — kept saying "area < 0.01
    m²," meaning 10,000 mm². The author was being told a threshold
    inflated BY A FACTOR OF A HUNDRED, and the receipts were green
    throughout: the refusal did happen, after all, and no one checked
    its content against the number it was about.

    As long as the phrase is assembled HERE, right next to the number,
    it has nowhere to drift apart. This is guarded by
    `agreements.отказ_несёт_свой_порог`.
    """
    return (f"{field}: вырожденный контур — площадь ниже "
            f"{MIN_RING_AREA_MM2:.0f} мм²")

#: An OPEN polyline (`path` for a railing, `path3` for a flexible run).
#: The lower bound is ITS OWN and justified in `registry_base.ParamSpec`:
#: a straight run is two points and zero area, which under the ring rule
#: would be rejected as a "degenerate contour." The upper value
#: historically matches the ring's, but this is a DIFFERENT policy: a
#: future measurement could raise the profile limit without
#: automatically widening railing/flex paths. So the value is kept as
#: its own, not borrowed through the name of a neighboring boundary.
MIN_PATH_POINTS = 2
MAX_PATH_POINTS = 64


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _cross(o, p, q) -> float:
    return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])


def _seg_intersect(a, b, c, d) -> bool:
    """Whether two closed 2D segments intersect, including touch/overlap.

    Callers that compare edges from the same ring already skip adjacent pairs;
    inclusive semantics are required for non-adjacent vertex touches, collinear
    overlaps, and hole-boundary contact (all invalid Revit curve-loop inputs).
    """
    eps = 1e-9

    def sign(x):
        return 1 if x > eps else -1 if x < -eps else 0

    def on_segment(p, q, r):
        return (min(p[0], r[0]) - eps <= q[0] <= max(p[0], r[0]) + eps
                and min(p[1], r[1]) - eps <= q[1] <= max(p[1], r[1]) + eps)

    o1, o2 = sign(_cross(a, b, c)), sign(_cross(a, b, d))
    o3, o4 = sign(_cross(c, d, a)), sign(_cross(c, d, b))
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return ((o1 == 0 and on_segment(a, c, b))
            or (o2 == 0 and on_segment(a, d, b))
            or (o3 == 0 and on_segment(c, a, d))
            or (o4 == 0 and on_segment(c, b, d)))


def _first_self_intersection(ring: list) -> Optional[tuple]:
    """The first (a, b) pair of self-intersecting ring edges, by index,
    or `None`.

    🔴 THERE USED TO BE AN ALL-PAIRS WALK HERE, AND IT BECAME REACHABLE
    ON 02.09.2026, WHEN `MAX_RING_POINTS` WAS RAISED FROM 64 TO 256.

    Measurement of the old code (`create_floor_by_contour`, a regular
    polygon, minimum of five runs — noise only ADDS, so the minimum is
    closer to the true cost):

        points        32       64      128      256
        emission   4.4 ms   9.9 ms  28.7 ms   94.4 ms
        per doubling         x2.23    x2.89     x3.29

    The exponent is not just greater than one — it GROWS, because the
    quadratic share crowds out the linear one: a 256-point profile
    produces **64,768 calls** to `_seg_intersect` for 42,275 characters
    of emitted C#. This is canon form 10 in pure form: a cost that
    grows with `n` is invisible to any instrument whose `n` equals
    three — at 64 points there are 2,016 pairs, and the walk drowned in
    noise.

    THE CULLING IS EXACT, NOT APPROXIMATE: if the bounding boxes of two
    segments do not overlap, the segments do not intersect either — this
    follows from the definition of a bounding box, not from a tolerance.
    The boxes' margins are widened by the same `eps` that
    `_seg_intersect` uses to count a touch, so no TOUCH is ever lost.
    The verdict must match the all-pairs walk BYTE FOR BYTE, including
    the edge NUMBERS in the refusal text — so candidates are enumerated
    in the same lexicographic order (a ascending, b ascending within
    it), not in sweep order.
    """
    n = len(ring)
    eps = 1e-9
    # Each edge's bounding box: the x-interval drives the sweep, the
    # y-interval culls.
    box = []
    for k in range(n):
        p, q = ring[k], ring[(k + 1) % n]
        box.append((min(p[0], q[0]) - eps, max(p[0], q[0]) + eps,
                    min(p[1], q[1]) - eps, max(p[1], q[1]) + eps))
    # SWEEPING ALONG x, NOT FILTERING PER EDGE. The first draft built a
    # candidate list for each `a` and stayed quadratic IN THE FILTER
    # ITSELF: `_seg_intersect` calls on a convex ring dropped to ZERO,
    # and the time still grew as ~n^1.7. A counter showed this; a clock
    # did not.
    order = sorted(range(n), key=lambda k: box[k][0])
    hits: list = []
    active: list = []          # edges whose x-interval has not ended yet
    for idx in order:
        x0, x1, y0, y1 = box[idx]
        if active:
            # Active edges that ended to the left of the current start
            # drop out. The pass over the active set is amortized: each
            # edge drops out exactly once.
            active = [k for k in active if box[k][1] >= x0]
        for k in active:
            a, b = (k, idx) if k < idx else (idx, k)
            if b <= a + 1 or (a == 0 and b == n - 1):
                continue       # adjacent, including across the closing edge
            ky0, ky1 = box[k][2], box[k][3]
            if ky1 < y0 or ky0 > y1:
                continue       # bounding boxes do not overlap => the segments do not either
            if _seg_intersect(ring[a], ring[(a + 1) % n],
                              ring[b], ring[(b + 1) % n]):
                hits.append((a, b))
        active.append(idx)
    # The order of pairs must match the all-pairs walk VERBATIM: edge
    # numbers travel into the refusal text, and the sweep finds them in
    # a different order.
    return min(hits) if hits else None


def _point_in_poly(pt, poly) -> bool:
    x, y = pt[0], pt[1]
    inside = False
    n = len(poly)
    for k in range(n):
        x1, y1 = poly[k][0], poly[k][1]
        x2, y2 = poly[(k + 1) % n][0], poly[(k + 1) % n][1]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def _pt_seg_dist(pt, a, b) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    L2 = vx * vx + vy * vy
    if L2 == 0:
        return _dist(pt, a)
    t = max(0.0, min(1.0, ((pt[0] - a[0]) * vx + (pt[1] - a[1]) * vy) / L2))
    return _dist(pt, (a[0] + t * vx, a[1] + t * vy))


def ring_normalize(pts: list, oid, field: str, diags: list):
    """Cleaned open ring, or None with a typed diagnostic appended."""
    ring = [[p[0], p[1]] for p in pts]
    # Not ">= 4," but "a ring PLUS a repeated first point": the
    # duplicate can only be stripped where a legitimate polygon remains
    # underneath it.
    if len(ring) >= MIN_RING_POINTS + 1 and _dist(ring[0], ring[-1]) < _EDGE_TOL:
        ring = ring[:-1]        # explicit closure tolerated -> normalized away
    if len(ring) < MIN_RING_POINTS:
        diags.append(Diagnostic(code=TYPE_BOUNDS, op_id=oid, field_name=field,
                                message_ru=f"{field}: после нормализации замыкания меньше 3 точек"))
        return None
    n = len(ring)
    for k in range(n):
        if _dist(ring[k], ring[(k + 1) % n]) < _EDGE_TOL:
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=field,
                got=[ring[k], ring[(k + 1) % n]],
                message_ru=(f"{field}: нулевое ребро (точки {k}/{(k + 1) % n} совпадают) — "
                            "в рантайме это ShortCurveTolerance, ловится статически")))
            return None
    hit = _first_self_intersection(ring)
    if hit is not None:
        a, b = hit
        diags.append(Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
            message_ru=f"{field}: самопересечение контура (рёбра {a} и {b})"))
        return None
    return ring


def check_holes_relation(outline: list, holes: list, oid, diags: list,
                         field_prefix: str = "holes") -> bool:
    """Holes strictly inside the outline (touching an edge == runtime
    'curve loops intersect'), pairwise disjoint, edges non-crossing."""
    ok = True
    no = len(outline)
    for hi, hole in enumerate(holes):
        for pt in hole:
            if not _point_in_poly(pt, outline):
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid,
                    field_name=f"{field_prefix}[{hi}]",
                    got=pt, message_ru=f"{field_prefix}[{hi}]: точка вне внешнего контура"))
                ok = False
                break
            if any(_pt_seg_dist(pt, outline[k], outline[(k + 1) % no]) < _TOUCH_TOL
                   for k in range(no)):
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid,
                    field_name=f"{field_prefix}[{hi}]",
                    got=pt,
                    message_ru=(f"{field_prefix}[{hi}]: касание внешней границы — в рантайме "
                                "'curve loops intersect'; отступите внутрь")))
                ok = False
                break
        if not ok:
            continue
        nh = len(hole)
        for k in range(nh):
            if any(_seg_intersect(hole[k], hole[(k + 1) % nh],
                                  outline[m], outline[(m + 1) % no])
                   for m in range(no)):
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid,
                    field_name=f"{field_prefix}[{hi}]",
                    message_ru=f"{field_prefix}[{hi}]: ребро пересекает внешний контур"))
                ok = False
                break
    for hi in range(len(holes)):
        for hj in range(hi + 1, len(holes)):
            hit = (any(_point_in_poly(pt, holes[hj]) for pt in holes[hi])
                   or any(_point_in_poly(pt, holes[hi]) for pt in holes[hj])
                   or any(_seg_intersect(holes[hi][a], holes[hi][(a + 1) % len(holes[hi])],
                                         holes[hj][b], holes[hj][(b + 1) % len(holes[hj])])
                          for a in range(len(holes[hi]))
                          for b in range(len(holes[hj]))))
            if hit:
                diags.append(Diagnostic(
                    code=TYPE_GEOM_RELATION, op_id=oid,
                    field_name=f"{field_prefix}[{hj}]",
                    message_ru=(f"{field_prefix}[{hi}] и {field_prefix}[{hj}] "
                                "пересекаются/вложены")))
                ok = False
    return ok


# ── SURFACE POINT CLOUD (kind `pts_xyz`, wave/site 2026-08-09) ─────────────
#
# A separate kind, not `pts` and not `mesh`. What sets it apart from
# `pts` is the third coordinate, and here it is LOAD-BEARING: for
# terrain, the ground elevation lives in the Z of every point, and
# TopographySurface.Create does not accept a level at all — a flat [x,y]
# would silently flatten the whole terrain into a plane. What sets it
# apart from `mesh` is that there are no triangles: Revit builds them,
# and demanding them from the author would mean demanding work the
# platform already does on its own.
#
# THE LIMITS ARE BORROWED, NOT INVENTED, and borrowed from a
# measurement, not from taste: MAX_VERTICES/_COORD_MAX_MM are taken from
# mesh.py, where they rest on the compile-service measurement table of
# 29.07 (emission of a literal point array grows linearly, ~33
# characters per element, no break) and a derivation from Revit's
# 20-mile limit. Emission here has THE SAME shape — a literal array of
# points — so setting up a number of its own here would mean setting up
# a second boundary about the exact same thing.

def validate_points_xyz(value, oid, field: str, diags: list, *,
                        min_points: int = 3):
    """A point cloud [x,y,z] in mm -> a normalized list, or None + a refusal.

    Three laws, and not one silent fix-up of the input (a silent edit in
    this house has already cost 96.77% of the groups):

    1. SHAPE AND LIMITS: 3..MAX_VERTICES points, each three finite
       numbers within ±_COORD_MAX_MM.
    2. ONE XY — ONE ELEVATION. Two points with a matching plan position
       (closer than _WELD_TOL_MM) are contradictory: a terrain surface
       is 2.5-dimensional, and "what is the ground here" has exactly one
       answer for it. Accepting both would mean letting Revit silently
       pick one — building the wrong terrain. The refusal NAMES both
       points. The law is DERIVED from the element's 2.5-dimensionality,
       not measured on live Revit, and this is stated here outright.
    3. NOT A LINE. All points collinear in plan give a degenerate
       surface of zero area. The check is exact and linear: take the
       point farthest from the first one, measure the maximum distance
       of the rest from that line. A bounding box would not catch
       this — a diagonal chain of points has both box dimensions
       non-zero (an instrument covering part of the range is more
       dangerous than none at all).
    """
    from kir.emit_utils import is_finite_number
    from kir.mesh import MAX_VERTICES, _COORD_MAX_MM, _WELD_TOL_MM

    if not (isinstance(value, list) and min_points <= len(value) <= MAX_VERTICES):
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid, field_name=field, got=value,
            message_ru=(f"{field} — {min_points}..{MAX_VERTICES} точек "
                        f"[x,y,z] в мм")))
        return None
    pts = []
    for k, pt in enumerate(value):
        if not (isinstance(pt, list) and len(pt) == 3
                and all(is_finite_number(c) for c in pt)):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}[{k}]", got=pt,
                message_ru=(f"{field}[{k}] — точка [x,y,z] мм из трёх "
                            f"конечных чисел")))
            return None
        if any(abs(float(c)) > _COORD_MAX_MM for c in pt):
            diags.append(Diagnostic(
                code=TYPE_BOUNDS, op_id=oid, field_name=f"{field}[{k}]", got=pt,
                message_ru=(f"{field}[{k}]: координата вне ±{_COORD_MAX_MM:.0f} "
                            f"мм от начала координат")))
            return None
        pts.append([float(pt[0]), float(pt[1]), float(pt[2])])
    # Law 2 — plan duplicates. A grid instead of a pairwise scan: 4096
    # points would give 8 million comparisons on every compilation.
    #
    # 🔴 A CELL HOLDS EVERYONE, NOT JUST THE LAST ONE, AND THE DIFFERENCE
    # IS A DROPPED PIECE OF TERRAIN. Before 02.09.2026 this held
    # `cell[(gx, gy)] = k`: a cell's second point OVERWROTE the first,
    # and the first stopped existing for anyone arriving after it.
    # Measured: [[0,0,0], [0.09,0.09,1000], [0.01,0,2000], …] with a
    # tolerance of 0.1 mm — points 0 and 1 are 0.127 mm apart and both
    # are legal, so 1 overwrote 0; point 2 is 0.120 mm from 1 and also
    # passed, while against the FORGOTTEN point 0 it sits at 0.01 mm
    # with elevations 0 and 2000. The whole cloud was accepted, and
    # Revit silently picked which one was the ground here.
    #
    # A grid with a cell side equal to the tolerance still stands: two
    # points closer than the tolerance lie in the same cell or an
    # adjacent one, so a walk over 9 cells is COMPLETE. All that was
    # needed was to stop losing candidates within a cell. This does not
    # blow up the comparison count by construction: a 0.1×0.1 mm cell
    # cannot hold more than a handful of points that are all pairwise
    # farther than 0.1 mm apart — and any that are closer end the check
    # with a refusal on the very first pair.
    cell: dict = {}
    for k, pt in enumerate(pts):
        gx, gy = int(pt[0] / _WELD_TOL_MM), int(pt[1] / _WELD_TOL_MM)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in cell.get((gx + dx, gy + dy), ()):
                    if _dist(pts[other], pt) < _WELD_TOL_MM:
                        diags.append(Diagnostic(
                            code=TYPE_GEOM_RELATION, op_id=oid,
                            field_name=field,
                            got=[pts[other], pt],
                            message_ru=(
                                f"{field}: точки {other} и {k} стоят в одном "
                                f"плане и расходятся на "
                                f"{_dist(pts[other], pt):.3f} мм при допуске "
                                f"{_WELD_TOL_MM} мм — отметки "
                                f"{pts[other][2]:g} и {pt[2]:g}. У рельефа в "
                                f"одной точке плана ровно одна земля, и "
                                f"выбирать между ними за вас компилятор не "
                                f"станет")))
                        return None
        cell.setdefault((gx, gy), []).append(k)
    # Law 3 — degeneration into a line.
    far = max(range(len(pts)), key=lambda i: _dist(pts[0], pts[i]))
    base = _dist(pts[0], pts[far])
    if base < _EDGE_TOL or max(
            abs(_cross(pts[0], pts[far], p)) / base for p in pts) < _EDGE_TOL:
        diags.append(Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
            message_ru=(f"{field}: все точки лежат на одной прямой в плане — "
                        f"поверхности нулевой площади в модели не бывает")))
        return None
    return pts


# ─── A HOST SHIFTED BY THE SAME PROGRAM — ONE LAW, THREE READERS ──────────
#
# 07.09.2026, mandate F1, "silently wrong chains." A host wall's shape
# for a door/window (`__host_wall__`) was taken from the wall's AUTHORED
# endpoints, and if the same program had already moved the wall with
# `move_elements` BEFORE the door: wall (0,0)–(6000,0), shift +1000
# along X, offset 3000 → the door lands at (3000,0), that is 2000 mm
# from the NEW start. The point lands on the wall, Revit accepts it, the
# door's witness checks against that same constant — a green run of a
# different building.
#
# Readers: `compiler.hosted_offset_check` (plan, literal endpoints),
# `ground._check_addressed_hosts` (endpoints from grids), and the
# independent control `midend._assert_payload_refinement`, which MUST
# recompute the same shape itself — otherwise the control would be
# catching not a forgery but the law.
def same_program_shift(ops: list, upto: int, target_id: str
                       ) -> tuple[float, float, float]:
    """The summed `delta_mm` of every `move_elements` BEFORE position
    `upto` whose `targets` reference (`by: ref`) `target_id`. Program
    order is effect order: shifts AFTER an op do not change its
    point."""
    dx = dy = dz = 0.0
    for op in ops[:upto]:
        if not isinstance(op, dict) or op.get("op") != "move_elements":
            continue
        targets = op.get("targets") or ()
        if not any(isinstance(t, dict) and t.get("by") == "ref"
                   and str(t.get("value")) == target_id for t in targets):
            continue
        delta = op.get("delta_mm") or (0, 0, 0)
        try:
            dx += float(delta[0]); dy += float(delta[1]); dz += float(delta[2])
        except (TypeError, ValueError, IndexError):
            continue        # the shape of delta_mm is judged by the op's own parsing, not by this
# summer
    return dx, dy, dz


def program_shift_after(ops: list, index: int, target_id: str
                        ) -> tuple[float, float, float]:
    """The summed `delta_mm` of every `move_elements` AFTER position
    `index` whose `targets` reference (`by: ref`) `target_id`.

    🔴 A MIRROR OF `same_program_shift`, AND THEY SHARE ONE LAW — it
    does the counting. `same_program_shift` answers the INPUT question
    ("where did the host stand when the door reached it"), this one
    answers the OUTCOME question ("where will my result end up once the
    program is done"). A second law would set up a second truth about
    what a shift is: here the TAIL of the program is taken and counted
    by the same body.

    Program order is effect order, so `index` is excluded: an op does
    not move itself, and a `move_elements` standing BEFORE creation
    cannot refer to a `ref` that does not exist yet.
    """
    tail = list(ops[index + 1:])
    return same_program_shift(tail, len(tail), target_id)


def program_result_shift(ops: list, index: int) -> tuple[float, float, float]:
    """Final displacement of a result, including moves of a hosted result's wall.

    A single move naming both host and result contributes its delta once.
    Moves before creation affect placement and are excluded from this tail.
    """
    origin = ops[index]
    if origin.get("op") not in ("create_window", "create_door"):
        return program_shift_after(ops, index, origin["id"])
    selectors = ({"by": "ref", "value": origin["id"]}, origin["host"])
    shift = [0.0, 0.0, 0.0]
    for later in ops[index + 1:]:
        if later.get("op") == "move_elements" and any(
                target == selector for target in later.get("targets", ()) for selector in selectors):
            for axis, value in enumerate(later["delta_mm"]):
                shift[axis] += float(value)
    return tuple(shift)


def shifted_host_shape(wall: dict, shift: tuple[float, float, float]) -> dict:
    """The host's `__host_wall__` in the position shifted by `shift` (Z
    is excluded: a door's height is measured from the level, a vertical
    shift is a refusal at the judge)."""
    sx, sy = float(shift[0]), float(shift[1])

    def _shifted(pt):
        return [pt[0] + sx, pt[1] + sy] + list(pt[2:])

    moved = bool(sx or sy)
    shape = {"p0_mm": _shifted(wall["p0_mm"]) if moved else wall["p0_mm"],
             "p1_mm": _shifted(wall["p1_mm"]) if moved else wall["p1_mm"]}
    arc = wall.get("arc")
    if isinstance(arc, dict):
        if moved and isinstance(arc.get("center_mm"), (list, tuple)):
            arc = dict(arc, center_mm=_shifted(arc["center_mm"]))
        shape["arc"] = arc
    return shape
