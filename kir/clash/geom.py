"""Hulls and exact pair arithmetic. Not a single Revit call, not a single
network call.

Three MVP hulls and one law: a hull must CONTAIN the element. Then skipping
a hull pair means a clash is skipped as impossible at the geometry level,
and all coarsening goes only upward — into false positives, which are
visible and marked by a grade.

What is exact here and what is not (this is not decoration — the verdict
rests on it):

* `Prism` — a convex polyhedron: a convex base polygon × [z0, z1].
* `PrismSet` — a UNION of convex prisms sharing a [z0, z1]. The body is
  non-convex.
* `Capsule` — a polyline × radius (union of segments; joints are covered).
* `Aabb` — a box; a special case of a prism with a rectangular base.

WHY `PrismSet` IS A SEPARATE TYPE, NOT A PRISM WITH A CONCAVE BASE. SAT is a
theorem about CONVEX sets, and only about them. `_project` takes min/max
over vertices, i.e. the projection of the base's CONVEX HULL: feed it a
concave contour, and it will return a convex answer SILENTLY, with no error
and no flag. Concavity must therefore be visible in the TYPE, not hidden in
a field: `PrismSet` carries a list of CONVEX pieces, and code that does not
know the type stumbles loudly. For the same reason `PrismSet` does NOT
inherit from `Prism`: inheritance would make `isinstance(h, Prism)` true and
bring back exactly the silent convexification the type was set up to
eliminate.

The signed distance `signed_distance` is computed EXACTLY for every pair of
hulls (not for the real bodies — see `narrow.verdict_of`). "Exact" is
verifiable here: a prism is the Cartesian product of a convex polygon and a
segment, so the distance between two prisms decomposes into independent
factors, while the distance from a segment to a prism is taken as the
minimum over FACES — a closure of all "face/edge/vertex" cases without a
single approximation.

The clamp-by-z from v1 has been retracted (review #12): for a slanted
segment the minima over XY and over Z are attained at different points, and
comparing them independently declares a clash where there is no common
point.

THE DECOMPOSE WAVE (10.08.2026), second half. The gap between a pair of
CONVEX bases was computed by the best SAT separating axis and was a LOWER
BOUND on the Euclidean distance (review #7 counterexample: 1.0 against the
true √2). A lower-bound estimate overstates a clash and is therefore safe —
exactly as long as a hull is SINGLE. For a union of pieces it stops being
safe for a different reason: `dist(∪Aᵢ, ∪Bⱼ) = minᵢⱼ dist(Aᵢ, Bⱼ)` holds as
a set-theoretic equality, but a minimum over N·M LOWER BOUNDS is an estimate
that gets WORSE the more pieces there are, and splitting the base would
trade false overlaps for FALSE GAP VIOLATIONS. So together with the split,
`_convex_poly_distance` is introduced — the exact distance between a pair of
convex polygons by a "vertex–edge" enumeration, and it is applied to ALL
base pairs, not only the split ones. From this wave on, the published
distance is EXACT; the one quantity that remains a lower bound is the
overlap depth of UNIONS (see `signed_distance`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Sequence

Pt2 = tuple[float, float]
Pt3 = tuple[float, float, float]

#: Anything thinner than this is zero. Models arrive from Revit in feet and
#: are converted to mm, so "exactly zero" never occurs in the data: on the
#: SOB6.2 facade, an 1800 mm elevation is stored as 1799.9999999998602.
EPS_MM = 1e-6

#: Review #8: the SQUARE of a length cannot be compared with a length
#: threshold. A 0.0005 mm segment has a square of 2.5e-7 < EPS_MM and was
#: declared a point — the sign of the distance changed as a result
#: (measured: sd=+0.0001099 instead of -0.0003). The threshold for the
#: square is the square of the threshold, and this is not decoration but the
#: one thing that makes the comparison dimensionally meaningful.
EPS_MM2 = EPS_MM * EPS_MM

#: Degeneracy of a pair of directions is a RELATIVE quantity: `a*e - b*b`
#: has the dimension mm⁴, so it cannot be compared with millimeters at any
#: scene scale.
EPS_REL = 1e-12


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _norm_zero(x: float) -> float:
    """-0.0 -> 0.0. Otherwise two identical runs produce different JSON."""
    return 0.0 if x == 0 else float(x)


# ────────────────────────────────────────────────────────────────── hulls

@dataclass(frozen=True)
class Aabb:
    """An axis-aligned box. The coarsest hull, and the only one that can be
    built from a single bbox — i.e. from what exists for EVERY decompile
    element."""
    lo: Pt3
    hi: Pt3

    def bounds(self) -> tuple[Pt3, Pt3]:
        return self.lo, self.hi

    def as_prism(self) -> "Prism":
        (x0, y0, z0), (x1, y1, z1) = self.lo, self.hi
        return Prism(footprint=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
                     z0=z0, z1=z1)


@dataclass(frozen=True)
class Prism:
    """A convex base polygon (CCW or CW — normalized) × [z0, z1]."""
    footprint: tuple[Pt2, ...]
    z0: float
    z1: float

    def bounds(self) -> tuple[Pt3, Pt3]:
        xs = [p[0] for p in self.footprint]
        ys = [p[1] for p in self.footprint]
        return ((min(xs), min(ys), self.z0), (max(xs), max(ys), self.z1))


@dataclass(frozen=True)
class PrismSet:
    """A UNION of convex prisms sharing a [z0, z1]. The base is a concave
    region.

    The pieces come from `clash.decompose`, where it is proven that their
    union EQUALS the declared area (area cross-check + independent centroid
    check), rather than containing it or being contained in it. Here that is
    already a precondition: every piece must be CONVEX, or everything below
    lies silently.

    A shared [z0, z1] is not a simplification but the shape of the data: the
    base is extruded by one elevation to one height. A piece has nowhere to
    take its own Z-span from.

    DEGENERATE PIECES (a segment, a point) are not discarded: the sweep
    releases them at the scope's pinch points, and a discarded piece SHRINKS
    the hull. As convex sets they are legitimate, and all the arithmetic
    below holds for them.
    """
    pieces: tuple[tuple[Pt2, ...], ...]
    z0: float
    z1: float

    def bounds(self) -> tuple[Pt3, Pt3]:
        xs = [p[0] for fp in self.pieces for p in fp]
        ys = [p[1] for fp in self.pieces for p in fp]
        if not xs:
            # An empty body. The bounding box of an EMPTY set is an inverted
            # box, and this is not "no data" but a correct answer: it cannot
            # intersect with anything.
            return ((math.inf, math.inf, self.z0), (-math.inf, -math.inf, self.z1))
        return ((min(xs), min(ys), self.z0), (max(xs), max(ys), self.z1))

    def prisms(self) -> list["Prism"]:
        return [Prism(fp, self.z0, self.z1) for fp in self.pieces]


@dataclass(frozen=True)
class Capsule:
    """A polyline × radius. A single segment is the common case; a polyline
    is needed for arcs decomposed into chords, and for sloped runs."""
    path: tuple[Pt3, ...]
    radius: float

    def bounds(self) -> tuple[Pt3, Pt3]:
        r = self.radius
        xs = [p[0] for p in self.path]
        ys = [p[1] for p in self.path]
        zs = [p[2] for p in self.path]
        return ((min(xs) - r, min(ys) - r, min(zs) - r),
                (max(xs) + r, max(ys) + r, max(zs) + r))

    def segments(self) -> list[tuple[Pt3, Pt3]]:
        if len(self.path) == 1:
            return [(self.path[0], self.path[0])]
        return list(zip(self.path, self.path[1:]))


Hull = Aabb | Prism | PrismSet | Capsule

#: Hulls whose base DECOMPOSES into convex pieces. The single place where a
#: prism, a box, and a union are brought to one form: any code that iterates
#: over pieces by hand will sooner or later forget one of the three types.
def footprint_pieces(h: Hull) -> tuple[tuple[Pt2, ...], ...] | None:
    """The hull's convex bases, or `None` for a capsule (it has no base)."""
    if isinstance(h, PrismSet):
        return h.pieces
    if isinstance(h, Prism):
        return (h.footprint,)
    if isinstance(h, Aabb):
        return (h.as_prism().footprint,)
    return None


def z_span(h: Hull) -> tuple[float, float] | None:
    """Z-span of the prism family. `None` means a capsule."""
    if isinstance(h, PrismSet):
        return (h.z0, h.z1)
    if isinstance(h, Prism):
        return (h.z0, h.z1)
    if isinstance(h, Aabb):
        return (h.lo[2], h.hi[2])
    return None


def hull_bounds(h: Hull) -> tuple[Pt3, Pt3]:
    return h.bounds()


# ──────────────────────────────────────────────────────── elementary work

def _sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, ...]:
    return tuple(x - y for x, y in zip(a, b))


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _len(a: Sequence[float]) -> float:
    return math.sqrt(_dot(a, a))


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _point_seg_closest(pt: Pt3, q0: Pt3, q1: Pt3) -> tuple[float, Pt3]:
    """Parameter and point of projecting `pt` onto segment q. A degenerate
    segment gives q0."""
    d = _sub(q1, q0)
    e = _dot(d, d)
    if e <= EPS_MM2:
        return 0.0, tuple(float(c) for c in q0)
    t = _clamp01(_dot(_sub(pt, q0), d) / e)
    return t, tuple(q0[i] + d[i] * t for i in range(3))


def seg_seg_closest_points(p0: Pt3, p1: Pt3, q0: Pt3, q1: Pt3
                           ) -> tuple[float, float, Pt3, Pt3, float]:
    """The closest pair of points on two 3D segments: `(s, t, cp, cq, distance)`.

    Review #5: a distance without POINTS is useless for repair — the
    separating direction was built from the segments' midpoints and did not
    separate the pair. So the closest points are now primary, and the
    distance is their consequence.

    The minimum distance between two segments is attained either at an
    interior point of both (Ericson's classic clamped parameter), or at an
    end of at least one of them. Both sets are enumerated in full, so
    parallel, collinear, and degenerate pairs are not special cases: for
    them the interior formula degenerates, and the end-point candidate wins.
    """
    d1, d2 = _sub(p1, p0), _sub(q1, q0)
    r = _sub(p0, q0)
    a, e, f = _dot(d1, d1), _dot(d2, d2), _dot(d2, r)
    cands: list[tuple[float, float]] = []
    if a > EPS_MM2 and e > EPS_MM2:
        b, c = _dot(d1, d2), _dot(d1, r)
        denom = a * e - b * b
        # A relative criterion (review #8): mm⁴ against mm⁴, not against mm.
        if denom > EPS_REL * a * e:
            s = _clamp01((b * f - c * e) / denom)
            cands.append((s, _clamp01((b * s + f) / e)))
    # End-point candidates — the same ones that close the parallel and
    # degenerate cases.
    for s in (0.0, 1.0):
        pt = tuple(p0[i] + d1[i] * s for i in range(3))
        t, _ = _point_seg_closest(pt, q0, q1)
        cands.append((s, t))
    for t in (0.0, 1.0):
        pt = tuple(q0[i] + d2[i] * t for i in range(3))
        s, _ = _point_seg_closest(pt, p0, p1)
        cands.append((s, t))
    best: tuple[float, float, Pt3, Pt3, float] | None = None
    for s, t in cands:
        cp = tuple(p0[i] + d1[i] * s for i in range(3))
        cq = tuple(q0[i] + d2[i] * t for i in range(3))
        dist = _len(_sub(cp, cq))
        if best is None or dist < best[4] - 1e-15:
            best = (s, t, cp, cq, dist)
    assert best is not None
    return best


def seg_seg_distance(p0: Pt3, p1: Pt3, q0: Pt3, q1: Pt3) -> float:
    """Exact distance between two 3D segments, including degenerate ones."""
    return seg_seg_closest_points(p0, p1, q0, q1)[4]


def _convex_hull_2d(pts: Iterable[Pt2]) -> tuple[Pt2, ...]:
    """Convex hull of the base (Andrew's algorithm). A concave overlap
    contour must become CONVEX — otherwise SAT does not apply, and coarsening
    outward is legitimate."""
    ps = sorted(set((float(x), float(y)) for x, y in pts))
    if len(ps) <= 2:
        return tuple(ps)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Pt2] = []
    for p in ps:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Pt2] = []
    for p in reversed(ps):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return tuple(lower[:-1] + upper[:-1])


def convex_footprint(pts: Iterable[Pt2]) -> tuple[Pt2, ...]:
    return _convex_hull_2d(pts)


# ─────────────────────────────────────────────────── 2D: convex polygons

def _poly_axes(poly: Sequence[Pt2]) -> list[Pt2]:
    """Separating axes: the NORMAL AND THE TANGENT at each edge.

    🔴 THE TANGENT WAS ADDED 30.08.2026 (F-136). SAT is a theorem about
    convex polygons of FULL DIMENSION: for them, edge normals are enough for
    a separating axis to be found. For a DEGENERATE base (a segment, a
    point — they are legitimate and are not discarded, see `PrismSet`) the
    theorem's condition does not hold: a segment yields only a
    PERPENDICULAR axis, while the separating axis of two collinear segments
    lies ALONG them. Two segments on the same line with a 200 mm gap gave a
    zero gap, i.e. CONTACT.

    THE EXTRA AXIS IS SAFE BY CONSTRUCTION, and this is a consequence of the
    theorem, not a hope: for a genuinely intersecting pair the gap is
    non-positive on EVERY axis, and `_poly_sat_gap` takes the MAXIMUM. So
    adding an axis can only turn a false "not separated" into a true
    "separated" and never the other way around. The fix cannot create missed
    clashes.

    MEASUREMENT ON THE CORPUS (30.08.2026, 68 parses, read-only). The
    mechanism was CAUGHT on real buildings: 40 false zeros of `poly_poly_gap`
    across four buildings (`len_ar_me_r24_v1` 36, `k2_ar_rd_v6` 2,
    `snowdon_plumb_v5` 1, `k4_geom_wave2` 1). NOT A SINGLE ONE reached a
    VERDICT: 14 of 40 had overlap along Z (i.e. `hypot` did not cancel them),
    but for `PrismSet` the signed distance is the MINIMUM over piece pairs,
    and the minimum there was set by a different pair with a genuine overlap
    of −1100…−2350 mm. The number of "false contacts in the report" on
    today's corpus is ZERO, and it is named here so the next person does not
    mistake this fix for a repair of a common case: it fixes the MECHANISM,
    whose only shield is a neighboring piece.
    """
    axes = []
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L > EPS_MM:
            axes.append((-ey / L, ex / L))
            axes.append((ex / L, ey / L))
    return axes


def _project(poly: Sequence[Pt2], axis: Pt2) -> tuple[float, float]:
    vals = [p[0] * axis[0] + p[1] * axis[1] for p in poly]
    return min(vals), max(vals)


def _seg_seg_distance_2d(p0: Pt2, p1: Pt2, q0: Pt2, q1: Pt2) -> float:
    """Distance between two segments on a plane. Exact, including degenerate
    ones."""
    def pt_seg(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        e = dx * dx + dy * dy
        if e <= EPS_MM2:
            return math.hypot(p[0] - a[0], p[1] - a[1])
        t = _clamp01(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / e)
        return math.hypot(p[0] - a[0] - dx * t, p[1] - a[1] - dy * t)

    # A genuine intersection gives a distance of zero, and none of the four
    # "end onto segment" projections will produce it.
    d1x, d1y = p1[0] - p0[0], p1[1] - p0[1]
    d2x, d2y = q1[0] - q0[0], q1[1] - q0[1]
    den = d1x * d2y - d1y * d2x
    if den != 0.0:
        rx, ry = q0[0] - p0[0], q0[1] - p0[1]
        t = (rx * d2y - ry * d2x) / den
        u = (rx * d1y - ry * d1x) / den
        if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
            return 0.0
    return min(pt_seg(p0, q0, q1), pt_seg(p1, q0, q1),
               pt_seg(q0, p0, p1), pt_seg(q1, p0, p1))


def _convex_poly_distance(a: Sequence[Pt2], b: Sequence[Pt2]) -> float:
    """The EXACT Euclidean distance between two NON-INTERSECTING convex
    polygons.

    The closest pair of points of two non-intersecting convex sets always
    contains at least one VERTEX (even when the closest elements are two
    parallel sides: a vertex of one of them attains the same minimum). So an
    enumeration of "side × side" closes all cases without approximation.

    Cost O(n·m). This does not matter here: a prism's base after splitting
    has from three to six vertices, and the worst pair costs a few dozen
    multiplications.

    Call this ONLY when SAT has already said "separated": for intersecting
    polygons, an enumeration over boundaries would return 0 and lose the
    depth.
    """
    na, nb = len(a), len(b)
    if na == 0 or nb == 0:
        return math.inf
    if na == 1 and nb == 1:
        return math.hypot(a[0][0] - b[0][0], a[0][1] - b[0][1])
    if na == 1:
        return min(_seg_seg_distance_2d(a[0], a[0], b[j], b[(j + 1) % nb])
                   for j in range(nb))
    if nb == 1:
        return min(_seg_seg_distance_2d(a[i], a[(i + 1) % na], b[0], b[0])
                   for i in range(na))
    best = math.inf
    for i in range(na):
        ai, aj = a[i], a[(i + 1) % na]
        for j in range(nb):
            d = _seg_seg_distance_2d(ai, aj, b[j], b[(j + 1) % nb])
            if d < best:
                best = d
    return best


def _poly_sat_gap(a: Sequence[Pt2], b: Sequence[Pt2]) -> float:
    """The SAT gap: the SIGN is exact, the positive value is a LOWER-BOUND
    estimate.

    Factored out of `poly_poly_gap` not for elegance but for pruning: for a
    union of pieces the minimum is sought over N·M pairs, and there is no
    need to compute the exact distance (a "vertex–edge" enumeration) for a
    pair whose cheap lower-bound estimate is already worse than the minimum
    found so far. The pruning is EXACT: refinement can only raise the value,
    so a pair pruned by its lower bound could never have won.
    """
    best = -math.inf
    for axis in (_poly_axes(a) + _poly_axes(b)) or [(1.0, 0.0), (0.0, 1.0)]:
        amin, amax = _project(a, axis)
        bmin, bmax = _project(b, axis)
        gap = max(bmin - amax, amin - bmax)
        if gap > best:
            best = gap
    return best


def _xy_range(poly: Sequence[Pt2]) -> tuple[float, float, float, float]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return (min(xs), min(ys), max(xs), max(ys))


def poly_poly_gap(a: Sequence[Pt2], b: Sequence[Pt2]) -> float:
    """Gap between two CONVEX polygons: >0 is the EXACT Euclidean distance,
    <=0 is the penetration depth (also the length of the smallest separating
    translation).

    Review #7 is closed IN FULL. The first half (permutation instability)
    did not reproduce for the operator; the second — "1.0 against the true
    √2" — was real and could only be fixed by the formula. It is fixed here:
    SAT decides THE QUESTION OF SIGN (separated or not) — that is exactly
    what the theorem is for — while the magnitude in the separated case is
    given by the exact enumeration `_convex_poly_distance`.

    WHY THIS WAS NEEDED RIGHT NOW. While there was a single base, the lower
    bound was safe: it overstates a clash, i.e. it produces extra findings,
    not misses. For a UNION of bases the distance is taken as the minimum
    over piece pairs, and a minimum over N·M lower bounds is an estimate
    that gets looser the finer the split. Splitting without this fix would
    have traded false overlaps for false gap violations, i.e. moved the
    error around rather than removing it.

    In the intersecting case the value is the same as before and exact: the
    maximum over axes of the negative gaps is the smallest overlap of
    projections, i.e. the length of the MTV of a pair of CONVEX polygons.
    """
    if not a or not b:
        return math.inf
    if len(a) == 1 and len(b) == 1:
        return math.hypot(a[0][0] - b[0][0], a[0][1] - b[0][1])
    best = _poly_sat_gap(a, b)
    if best <= 0.0:
        return best
    # Separated — SAT said THAT, the exact enumeration says HOW MUCH.
    # The exact distance is never smaller than the lower-bound estimate; the
    # comparison is kept as a safeguard against degenerate bases, where an
    # enumeration over boundaries can give 0.
    exact = _convex_poly_distance(a, b)
    return exact if exact >= best else best


def _interval_gap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(b0 - a1, a0 - b1)


# ───────────────────────────────────────────── segment × convex polyhedron

def _prism_faces(p: Prism) -> list[tuple[Pt3, ...]]:
    """Faces of a prism: the base, the cap, and one quadrilateral per base
    edge."""
    fp = p.footprint
    if len(fp) < 3:
        # A degenerate base (segment/point): there are no faces, we work
        # with edges.
        return []
    bottom = tuple((x, y, p.z0) for x, y in fp)
    top = tuple((x, y, p.z1) for x, y in reversed(fp))
    faces = [bottom, top]
    n = len(fp)
    for i in range(n):
        (x0, y0), (x1, y1) = fp[i], fp[(i + 1) % n]
        faces.append(((x0, y0, p.z0), (x1, y1, p.z0),
                      (x1, y1, p.z1), (x0, y0, p.z1)))
    return faces


def _point_in_prism(pt: Pt3, p: Prism) -> bool:
    if not (p.z0 - EPS_MM <= pt[2] <= p.z1 + EPS_MM):
        return False
    fp = p.footprint
    if len(fp) < 3:
        return False
    n = len(fp)
    sign = 0
    for i in range(n):
        ax, ay = fp[i]
        bx, by = fp[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        cr = ex * (pt[1] - ay) - ey * (pt[0] - ax)
        # Review #8, the same law in a new place: `cr` has the dimension
        # mm², and comparing it with a threshold in MILLIMETERS is invalid
        # at any scale. The distance from a point to the edge's line is
        # `cr / |edge|`, so the threshold is multiplied by the edge length —
        # then millimeters are compared with millimeters.
        #
        # THE MEASUREMENT that found this (10.08.2026, a dense containment
        # probe over 1 621 617 points of the corpus): 893 points lying ON a
        # cell's boundary were declared outside the hull. For a cell with a
        # 5 500 mm edge, a point 1e-9 mm from the edge gave cr ≈ 5.5e-6 >
        # EPS_MM = 1e-6 and was recognized as strictly outside. Before the
        # split the defect was almost invisible: a single convex base has no
        # internal boundaries, while after the split it has dozens.
        L = math.hypot(ex, ey)
        if abs(cr) <= EPS_MM * (L if L > 1.0 else 1.0):
            continue
        s = 1 if cr > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def _seg_polygon_distance(s0: Pt3, s1: Pt3, poly: Sequence[Pt3]) -> float:
    """Distance from a segment to a CONVEX polygon in 3D — exact.

    The closest pair of points lies either on an edge of the polygon (found
    by segment-segment), or within its plane (found by projecting the
    segment's endpoint). Both cases are enumerated in full, so there is no
    approximation.
    """
    best = math.inf
    n = len(poly)
    for i in range(n):
        best = min(best, seg_seg_distance(s0, s1, poly[i], poly[(i + 1) % n]))
    # Projections of the segment's endpoints onto the face's plane.
    if n >= 3:
        e1 = _sub(poly[1], poly[0])
        e2 = _sub(poly[2], poly[0])
        nx = (e1[1] * e2[2] - e1[2] * e2[1],
              e1[2] * e2[0] - e1[0] * e2[2],
              e1[0] * e2[1] - e1[1] * e2[0])
        nl = _len(nx)
        if nl > EPS_MM:
            unit = tuple(c / nl for c in nx)
            for p in (s0, s1):
                d = _dot(_sub(p, poly[0]), unit)
                proj = tuple(p[i] - d * unit[i] for i in range(3))
                if _point_in_polygon_3d(proj, poly, unit):
                    best = min(best, abs(d))
    return best


def _point_in_polygon_3d(pt: Pt3, poly: Sequence[Pt3], normal: Pt3) -> bool:
    n = len(poly)
    sign = 0
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        e = _sub(b, a)
        w = _sub(pt, a)
        cr = (e[1] * w[2] - e[2] * w[1],
              e[2] * w[0] - e[0] * w[2],
              e[0] * w[1] - e[1] * w[0])
        d = _dot(cr, normal)
        if abs(d) <= EPS_MM:
            continue
        s = 1 if d > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def _halfspaces(p: Prism) -> list[tuple[Pt3, float]]:
    """A prism as the intersection of half-spaces n·x + d <= 0 with UNIT n."""
    out: list[tuple[Pt3, float]] = [((0.0, 0.0, -1.0), p.z0), ((0.0, 0.0, 1.0), -p.z1)]
    fp = p.footprint
    n = len(fp)
    if n < 3:
        return out
    # Orientation: the sign of the area sets which way is "outward".
    area2 = sum(fp[i][0] * fp[(i + 1) % n][1] - fp[(i + 1) % n][0] * fp[i][1]
                for i in range(n))
    ccw = area2 > 0
    for i in range(n):
        (ax, ay), (bx, by) = fp[i], fp[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L <= EPS_MM:
            continue
        nx, ny = (ey / L, -ex / L) if ccw else (-ey / L, ex / L)
        out.append(((nx, ny, 0.0), -(nx * ax + ny * ay)))
    return out


def seg_prism_signed_distance(s0: Pt3, s1: Pt3, p: Prism) -> float:
    """Signed distance from a 3D SEGMENT to a prism. Inside is negative.

    This is the retracted clamp-by-z, done honestly: one segment parameter,
    one uniform criterion. Penetration is computed exactly — the depth is
    the maximum over the segment of the concave piecewise-linear function
    `min_i(-h_i)`, and its maximum is attained either at an end of the
    segment or where two linear pieces cross; both groups of points are
    enumerated in full.
    """
    hs = _halfspaces(p)
    if not hs:
        return math.inf

    def h_vals(t: float) -> list[float]:
        pt = tuple(s0[i] + (s1[i] - s0[i]) * t for i in range(3))
        return [_dot(n, pt) + d for n, d in hs]

    cands = {0.0, 1.0}
    # Points where the active face changes: intersections of pairs of linear
    # functions.
    a_lin = [(_dot(n, _sub(s1, s0)), _dot(n, s0) + d) for n, d in hs]
    for i in range(len(a_lin)):
        for j in range(i + 1, len(a_lin)):
            (ka, ba), (kb, bb) = a_lin[i], a_lin[j]
            dk = ka - kb
            if abs(dk) > EPS_MM:
                t = (bb - ba) / dk
                if 0.0 < t < 1.0:
                    cands.add(t)
    # m(t) = max_i h_i is a CONVEX piecewise-linear function of the
    # parameter, so its minimum (the deepest point of the segment) is
    # attained at an end or at a kink, and both sets are already in `cands`.
    best_inside = math.inf
    for t in cands:
        m = max(h_vals(t))
        if m < best_inside:
            best_inside = m
    if best_inside < 0:
        return best_inside          # negative: penetration depth
    # Outside — the exact distance as a minimum over the faces.
    faces = _prism_faces(p)
    if not faces:
        return math.inf
    return min(_seg_polygon_distance(s0, s1, f) for f in faces)


# ────────────────────────────────────────────────────── hull pairs

def _prism_pair_sd(fa: Sequence[Pt2], fb: Sequence[Pt2],
                   za: tuple[float, float], zb: tuple[float, float]) -> float:
    """Signed distance of ONE pair of convex prisms.

    A prism is the Cartesian product of a base and an interval ALONG THE
    SAME axes, so the squares of the distances add up: `hypot` is exact
    here, not an approximation. The composition must happen WITHIN a pair of
    pieces and only then go into the minimum over pairs: a `hypot` of the
    minimum over XY of one pair and the minimum over Z of ANOTHER pair
    describes a point that exists in neither body.
    """
    gxy = poly_poly_gap(fa, fb)
    gz = _interval_gap(za[0], za[1], zb[0], zb[1])
    if gxy > 0 or gz > 0:
        return math.hypot(max(0.0, gxy), max(0.0, gz))
    return max(gxy, gz)


def signed_distance(a: Hull, b: Hull) -> float:
    """Signed distance between TWO HULLS (not bodies).

    Negative means penetration. The function is symmetric by construction:
    pairs are brought to a canonical order of types.

    WHAT THE NUMBER MEANS FOR A UNION (`PrismSet`) — two different things on
    either side of zero, and they must not be confused:

    * THE SIGN IS ALWAYS EXACT. `∪Aᵢ ∩ ∪Bⱼ ≠ ∅` holds if and only if at
      least one pair of pieces intersects, so the minimum over pairs changes
      sign exactly where the real body changes it. The split creates neither
      a miss nor an extra finding — it REMOVES them.
    * THE POSITIVE VALUE IS EXACT. `dist(∪Aᵢ, ∪Bⱼ) = minᵢⱼ dist(Aᵢ, Bⱼ)` is
      a set equality, and every term has been exact since this wave.
    * THE NEGATIVE VALUE IS A LOWER BOUND, and this is fundamental.
      Separating two UNIONS requires ONE translation that cancels ALL
      intersecting piece pairs at once, so |MTV(A,B)| ≥ maxᵢⱼ|MTV(Aᵢ,Bⱼ)|
      and, generally, strictly greater than any one of them. The depth
      published here is the deepest pair of pieces, i.e. a lower bound on
      the move required. Passing it off as the MTV would mean signing a
      certificate that was never checked; hence
      `detect.Finding.separation_is_lower_bound` is true for such pairs, and
      the separating translation is taken not from here but from
      `certified_separating_
      translation`, where it IS VERIFIED by the translation.
    """
    ka, kb = type(a).__name__, type(b).__name__
    if (ka, kb) == ("Capsule", "Capsule"):
        best = math.inf
        for p0, p1 in a.segments():
            for q0, q1 in b.segments():
                best = min(best, seg_seg_distance(p0, p1, q0, q1))
        return best - (a.radius + b.radius)
    if ka == "Capsule":
        best = math.inf
        segs = a.segments()
        for pr in _as_prisms(b):
            # Pruning requires a bounding box, and a DEGENERATE base (an
            # empty vertex list) has none. Then there simply is no pruning:
            # the distance is computed as before and will return `inf`
            # through the faces, which such a prism also lacks. No silent
            # exclusion from the enumeration occurs.
            plo, phi = (pr.bounds() if pr.footprint else (None, None))
            for p0, p1 in segs:
                # The same exact pruning: the bounding-box gap between the
                # segment and the piece is no larger than the real distance,
                # so a pair that lost on it could not have won for real.
                if best < math.inf and plo is not None:
                    g = 0.0
                    for k in range(3):
                        lo_k, hi_k = min(p0[k], p1[k]), max(p0[k], p1[k])
                        gk = max(plo[k] - hi_k, lo_k - phi[k])
                        if gk > 0.0:
                            g += gk * gk
                    if g > 0.0 and math.sqrt(g) >= best:
                        continue
                d = seg_prism_signed_distance(p0, p1, pr)
                if d < best:
                    best = d
        return best - a.radius
    if kb == "Capsule":
        return signed_distance(b, a)
    fa, fb = footprint_pieces(a), footprint_pieces(b)
    za, zb = z_span(a), z_span(b)
    if fa is None or fb is None or za is None or zb is None:
        return math.inf
    gz = _interval_gap(za[0], za[1], zb[0], zb[1])
    if len(fa) == 1 and len(fb) == 1:
        return _prism_pair_sd(fa[0], fb[0], za, zb)
    # ── PRUNING BY LOWER-BOUND ESTIMATES. The answer does not depend on it
    #    by even one digit: every discarded piece pair is discarded by a
    #    value that is NO GREATER than its real distance, and already loses
    #    to the minimum found so far. Measurement 11.08.2026 (median 19
    #    pieces per split base, maximum 62): without pruning a hull pair cost
    #    ~1.4 ms against 0.05 ms for a convex one, i.e. a thirtyfold increase
    #    in the cost of the narrow phase — that alone would have been reason
    #    to shelve the wave. The pruning is EXACT, and this was checked
    #    separately: 4 000 random union pairs against a full enumeration of
    #    all piece pairs, 0 discrepancies.
    zc = max(0.0, gz)
    ra = [_xy_range(p) for p in fa]
    rb = [_xy_range(p) for p in fb]
    best = math.inf
    for i, pa in enumerate(fa):
        ax0, ay0, ax1, ay1 = ra[i]
        for j, pb in enumerate(fb):
            bx0, by0, bx1, by1 = rb[j]
            # (1) the bounding-box gap between pieces — a lower-bound
            # estimate, three subtractions
            gx = max(bx0 - ax1, ax0 - bx1)
            gy = max(by0 - ay1, ay0 - by1)
            if gx > 0.0 or gy > 0.0:
                lb = math.hypot(math.hypot(max(0.0, gx), max(0.0, gy)), zc)
                if lb >= best:
                    continue
            elif zc > 0.0 and zc >= best:
                continue
            # (2) SAT — a tighter lower-bound estimate, still cheap
            sat = _poly_sat_gap(pa, pb)
            if sat > 0.0:
                if math.hypot(sat, zc) >= best:
                    continue
                # `max` is the same safeguard as in `poly_poly_gap`: for a
                # degenerate base, an enumeration over boundaries can give 0
                # where SAT is right.
                d = math.hypot(max(sat, _convex_poly_distance(pa, pb)), zc)
            elif gz > 0.0:
                d = zc
            else:
                d = max(sat, gz)
            if d < best:
                best = d
    return best


def _as_prisms(h: Hull) -> list[Prism]:
    """A prism family -> a list of CONVEX prisms. A capsule -> empty."""
    if isinstance(h, PrismSet):
        return h.prisms()
    if isinstance(h, Prism):
        return [h]
    if isinstance(h, Aabb):
        return [h.as_prism()]
    return []


#: Tolerance of the separation postcondition: the translation must bring the
#: pair to `sd >= -SEP_EPS`.
SEP_EPS_MM = 1e-6


def translate(h: Hull, v: Sequence[float]) -> Hull:
    """Translating a hull by a vector. Needed by both the postcondition and
    the repair."""
    def sh(p):
        return tuple(p[i] + v[i] for i in range(3))

    if isinstance(h, Capsule):
        return Capsule(tuple(sh(p) for p in h.path), h.radius)
    if isinstance(h, Aabb):
        return Aabb(sh(h.lo), sh(h.hi))
    if isinstance(h, PrismSet):
        return PrismSet(
            tuple(tuple((x + v[0], y + v[1]) for x, y in fp) for fp in h.pieces),
            h.z0 + v[2], h.z1 + v[2])
    fp = tuple((x + v[0], y + v[1]) for x, y in h.footprint)
    return Prism(fp, h.z0 + v[2], h.z1 + v[2])


def separates(a: Hull, b: Hull, v: Sequence[float]) -> bool:
    """Checking the promise: after the translation the pair is genuinely
    separated."""
    return signed_distance(translate(a, v), b) >= -SEP_EPS_MM


def certified_separating_translation(a: Hull, b: Hull
                                     ) -> tuple[float, float, float] | None:
    """Translation of A with B FIXED, PROVABLY moving the pair out of
    penetration.

    The name is literal (review #6). This is NOT a minimal translation and
    not an MTV: we have no minimum without GJK/EPA, and promising minimality
    while computing it from faces is exactly the lie the review caught (a
    diagonal capsule got a vector of length 101 where ~8.07 would have
    sufficed). Exactly one thing is promised: after this translation
    `signed_distance >= -SEP_EPS_MM`, and this IS VERIFIED right here, not
    declared.

    Order: the typical candidate → verification → a certified fallback by
    bounding boxes (it always separates) → verification → `None` with a
    named reason (`mtv_unavailable_reason`). There is no silent `None`.

    HOW MUCH LONGER THIS MOVE IS THAN THE MINIMUM ONE — MEASURED, not
    estimated. `clash.resolve.minimal_exit` searches for the smallest
    translation by bisection along the direction (the set `{t : (A+t·d) ∩ B
    ≠ ∅}` for convex bodies is a SEGMENT, so bisection is valid). Checked
    against 600 real findings from `sob62_r23_v5` (10.08.2026): the move used
    here is longer than the minimal one by a factor of 5.892 at the median,
    56.667 at p90, and 112 066.5 in the worst case.

    This is NOT a contradiction with the paragraph above: minimality was
    never promised here. The reference exists so that the alternative is
    VISIBLE from the point where the vector is chosen — otherwise it is
    chosen without knowing its cost.
    """
    sd = signed_distance(a, b)
    if sd >= 0:
        return None
    for v in _separation_candidates(a, b, sd):
        if v is not None and separates(a, b, v):
            return tuple(_norm_zero(c) for c in v)
    v = _aabb_separation(a, b)
    if v is not None and separates(a, b, v):
        return tuple(_norm_zero(c) for c in v)
    return None


def mtv_unavailable_reason(a: Hull, b: Hull) -> str | None:
    """Why there is no separation. `None` means there is one (or the pair
    does not penetrate)."""
    if signed_distance(a, b) >= 0:
        return None
    if certified_separating_translation(a, b) is not None:
        return None
    if not all(math.isfinite(c) for h in (a, b) for p in hull_bounds(h) for c in p):
        return "non_finite_hull"
    return "no_certified_direction"


def _separation_candidates(a: Hull, b: Hull, sd: float) -> list[Sequence[float] | None]:
    """Candidates for a separating translation. EACH ONE is verified by the
    caller.

    For a union, a candidate is taken over the WHOLE body, not per piece: a
    translation that moves one piece out sends it into the neighboring one,
    and the pair remains in penetration. So projections are computed over
    the union of vertices of both bodies, and the set of axes over the faces
    of all pieces. For a single convex piece this is exactly the previous
    formula with the previous answer, so findings the wave does not touch do
    not shift by even one digit.
    """
    ka, kb = type(a).__name__, type(b).__name__
    fa, fb = footprint_pieces(a), footprint_pieces(b)
    za, zb = z_span(a), z_span(b)
    if fa is not None and fb is not None and za is not None and zb is not None:
        out: list[Sequence[float] | None] = []
        up, down = zb[1] - za[0], za[1] - zb[0]
        out.append((0.0, 0.0, up if up <= down else -down))
        pts_a = [p for fp in fa for p in fp]
        pts_b = [p for fp in fb for p in fp]
        axes: list[Pt2] = []
        for fp in fa:
            axes += _poly_axes(fp)
        for fp in fb:
            axes += _poly_axes(fp)
        axis, depth = _best_axis_over(pts_a, pts_b, axes)
        if axis is not None:
            out.append((axis[0] * depth, axis[1] * depth, 0.0))
        return out
    if ka == "Capsule" and fb is not None:
        # Each piece contributes its own move; none is promised to work, so
        # ALL are offered, and verification by translation decides.
        return [_capsule_prism_push(a, pr) for pr in _as_prisms(b)]
    if kb == "Capsule" and fa is not None:
        out2: list[Sequence[float] | None] = []
        for pr in _as_prisms(a):
            v = _capsule_prism_push(b, pr)
            out2.append(None if v is None else tuple(-c for c in v))
        return out2
    return [_capsule_capsule_push(a, b)]


def _capsule_capsule_push(a: Capsule, b: Capsule) -> Sequence[float] | None:
    """Separating two capsules by their CLOSEST POINTS (review #5).

    Before: the direction was between the MIDPOINTS of the closest segments,
    the length was the distance shortfall. On the counterexample
    (0,0,0)→(10,0,0) against (9,1,-5)→(9,1,5) this left sd=-0.7575, i.e. the
    pair still in penetration. The correct axis runs from the closest point
    of B to the closest point of A; the length is how much is missing to the
    sum of the radii along this axis.
    """
    best = None
    for p0, p1 in a.segments():
        for q0, q1 in b.segments():
            s, t, cp, cq, dist = seg_seg_closest_points(p0, p1, q0, q1)
            if best is None or dist < best[0]:
                best = (dist, cp, cq, (p0, p1))
    if best is None:
        return None
    dist, cp, cq, (p0, p1) = best
    need = (a.radius + b.radius) - dist
    if need <= 0:
        return None
    v = _sub(cp, cq)
    L = _len(v)
    if L > EPS_MM:
        return tuple(c / L * need for c in v)
    # The axes coincide/intersect: the direction between the points is
    # undefined. We take a DETERMINISTIC normal to axis A and separate by the
    # full sum of the radii.
    n = _any_perpendicular(_sub(p1, p0))
    full = a.radius + b.radius
    return tuple(c * full for c in n)


def _any_perpendicular(d: Sequence[float]) -> Pt3:
    """A deterministic unit normal to a direction (and to any zero direction
    — then simply the X axis). Determinism here is part of the contract: one
    input must produce one report."""
    if _len(d) <= EPS_MM:
        return (1.0, 0.0, 0.0)
    ux, uy, uz = (c / _len(d) for c in d)
    ref = (0.0, 0.0, 1.0) if abs(uz) < 0.9 else (1.0, 0.0, 0.0)
    cx = uy * ref[2] - uz * ref[1]
    cy = uz * ref[0] - ux * ref[2]
    cz = ux * ref[1] - uy * ref[0]
    L = _len((cx, cy, cz))
    if L <= EPS_MM:
        return (1.0, 0.0, 0.0)
    return (cx / L, cy / L, cz / L)


def _aabb_separation(a: Hull, b: Hull) -> Sequence[float] | None:
    """A certified fallback: move the bounding box of A outside the bounding
    box of B via the cheapest of the six sides. Always works, because a hull
    lies inside its bounding box; the length is not minimal and does not
    claim to be."""
    alo, ahi = hull_bounds(a)
    blo, bhi = hull_bounds(b)
    if not all(math.isfinite(c) for c in (*alo, *ahi, *blo, *bhi)):
        return None
    best: tuple[float, tuple[float, float, float]] | None = None
    for k in range(3):
        for d in (bhi[k] - alo[k] + SEP_EPS_MM, -(ahi[k] - blo[k] + SEP_EPS_MM)):
            v = [0.0, 0.0, 0.0]
            v[k] = d
            if best is None or abs(d) < best[0]:
                best = (abs(d), (v[0], v[1], v[2]))
    return None if best is None else best[1]


def _best_axis_over(a: Sequence[Pt2], b: Sequence[Pt2],
                    axes: Sequence[Pt2]) -> tuple[Pt2 | None, float]:
    """The axis of least projection overlap and the length of the move along
    it.

    Points and axes are deliberately kept on different parameters: for a
    union of pieces the projection must be computed over ALL vertices of the
    body, while the axes are the face normals of EACH piece. They cannot be
    merged into one list — an "edge" between vertices of different pieces is
    not a face of either body.
    """
    best_axis, best_gap = None, -math.inf
    for axis in axes:
        amin, amax = _project(a, axis)
        bmin, bmax = _project(b, axis)
        gap = max(bmin - amax, amin - bmax)
        if gap > best_gap or (gap == best_gap and best_axis is not None
                              and axis < best_axis):
            best_axis, best_gap = axis, gap
    if best_axis is None:
        return None, 0.0
    amin, amax = _project(a, best_axis)
    bmin, bmax = _project(b, best_axis)
    out = bmax - amin
    back = amax - bmin
    return (best_axis, out) if out <= back else (
        (-best_axis[0], -best_axis[1]), back)


def _best_axis(a: Sequence[Pt2], b: Sequence[Pt2]) -> tuple[Pt2 | None, float]:
    return _best_axis_over(a, b, _poly_axes(a) + _poly_axes(b))


def _capsule_prism_push(cap: Capsule, pr: Prism) -> tuple[float, float, float] | None:
    """Separating a capsule and a prism by the prism's faces, not by a
    numerical gradient.

    The gradient degenerates exactly in the most common case: a pipe
    PIERCING a wall clean through stays at the same depth after a
    micron-sized shift, and the derivative of the signed distance is zero
    along all three axes. The correct answer is the smallest translation
    along the normal of one of the faces that puts the ENTIRE segment
    outside: it is finite, computed exactly, and guaranteed to separate the
    pair.
    """
    hs = _halfspaces(pr)
    if not hs:
        return None
    best: tuple[float, Pt3] | None = None
    for n, d in hs:
        # h_i(p) <= 0 inside; to move the capsule past face i, `h_i` of
        # every point of the segment must be raised to +radius.
        worst = min(_dot(n, p) + d for p in cap.path)
        need = cap.radius - worst
        if need <= 0:
            return None                      # already outside
        if best is None or need < best[0] - 1e-12 or (
                abs(need - best[0]) <= 1e-12 and n < best[1]):
            best = (need, n)
    if best is None:
        return None
    need, n = best
    return (_norm_zero(n[0] * need), _norm_zero(n[1] * need), _norm_zero(n[2] * need))


def _translate(h: Hull, axis: int, d: float) -> Hull:
    def shift3(p):
        q = list(p)
        q[axis] += d
        return tuple(q)

    v = [0.0, 0.0, 0.0]
    v[axis] = d
    return translate(h, v)


def contains_point(h: Hull, pt: Pt3) -> bool:
    """Whether a hull contains a point — the basis of the property test "a
    hull contains the element".

    For a union, membership is a disjunction over pieces: a point is in the
    body if and only if it is in at least one piece. This is precisely the
    definition of a union, not an approximation to it.
    """
    if isinstance(h, Capsule):
        return min(seg_seg_distance(p0, p1, pt, pt)
                   for p0, p1 in h.segments()) <= h.radius + 1e-6
    return any(_point_in_prism(pt, p) for p in _as_prisms(h))
