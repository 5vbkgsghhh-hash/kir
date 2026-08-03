"""KIR static geometry law (v1.1, VISION §5а / slab-saga fixes).

Everything a runtime Revit refusal taught us on 2026-07-17 is caught at the
T stage now: the duplicate closing point (iter-1: ShortCurveTolerance) is
NORMALIZED away ("closed ring implied"), any other near-zero edge and any
self-intersection is a typed refusal, and a hole touching the outer boundary
(iter-2: "curve loops intersect") never reaches Revit. Pure python, shared
by validate() and future reference-interpreter (12.6c).
"""
from __future__ import annotations

import math

from kukai.ir.diag import Diagnostic, TYPE_BOUNDS, TYPE_GEOM_RELATION

_EDGE_TOL = 1.0          # mm: edges shorter than this are runtime kills
_TOUCH_TOL = 1.0         # mm: hole vertex closer than this to the outline = touch


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
    if len(ring) >= 4 and _dist(ring[0], ring[-1]) < _EDGE_TOL:
        ring = ring[:-1]        # explicit closure tolerated -> normalized away
    if len(ring) < 3:
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
    for a in range(n):
        for b in range(a + 2, n):
            if a == 0 and b == n - 1:
                continue        # adjacent through the closing edge
            if _seg_intersect(ring[a], ring[(a + 1) % n], ring[b], ring[(b + 1) % n]):
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
