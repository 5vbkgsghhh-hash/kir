"""A flat area -> CONVEX cells. Not a single hull, not a single Revit call.

WHY. `hulls.hull_from_profile` was reducing ANY footprint to a CONVEX hull
and filling in its holes. Measurement across the corpus
(`/tmp/clashwork/w1_value.py`, 10.08.2026): on `k2_ar_rd_v15`, out of 341
readable contours, 215 (63.0%) are NON-CONVEX, 42 carry holes, and the
convex hull's area exceeds the declared area of the region by a median of
5.8%, by 57.5% at p90, and by 95.5% at the extreme. That is, for the worst
floor, only the first twenty-one percent of the hull was the actual body,
and the rest was our own coarsening. Coarsening is legitimate (the
conservativeness law), but every finding inside it is invented, and a reader
cannot tell it apart from a real one.

WHY A VERTICAL TRAPEZOIDAL DECOMPOSITION, and not ear clipping, and not
Hertel–Mehlhorn:

* holes are not a special case, just more edges in the sweep; ear clipping
  cannot handle them at all and requires a preliminary "bridge" to every
  hole;
* every cell is convex BY CONSTRUCTION (a trapezoid with two vertical
  sides), not by a check performed afterward;
* the decomposition is DETERMINISTIC: the strips run by the sorted
  coordinates of the vertices, intersections inside a strip — by sorted y.
  A byte-for-byte identical report on a repeat run is a requirement of
  canonicity, not a convenience.

WHAT IS ABSENT HERE, AND WHY. There is not a single "merge tolerance" here
and not a single rounding of coordinates. Strips are cut at the EXACT x
values of the vertices (a float equality comparison, not one within an
epsilon): merging two nearly-coincident coordinates means discarding the
thin strip between them, and a discarded strip SHRINKS the area — exactly
what the conservativeness law forbids. So there can be many strips; a work
ceiling is placed on this, and beyond the ceiling the answer is a NAMED
refusal, not silent coarsening.

THE MODULE'S LAW, literally: "we do not silently discard — we refuse."
So the decomposition CHECKS ITSELF by two independent methods and, should
they disagree, refuses in full:

  1. AREA. The sum of the cells' areas is obligated to match the region's
     declared area (the outer contour minus the holes). A discrepancy
     catches a self-intersecting contour, an incorrect inside/outside
     placement, and a lost strip alike.
  2. CELL CENTER. Every cell's centroid is obligated to lie INSIDE the
     region by an independent ray-intersection count against the ORIGINAL
     contours. This check knows nothing about the strips at all and
     therefore cannot fail together with them.

Both checks are cheaper than the decomposition itself, and both are
mandatory: area catches a shortfall, the centroid catches an excess.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

Pt2 = tuple[float, float]

#: The sweep's work ceiling: (number of strips) x (number of edges). The
#: meaning is the same as with `clash_judgement._MAX_LOOP_WORK`: a cheap
#: refinement has no right to become expensive. MEASUREMENT (`w1_decomp.py`,
#: 11.08.2026, the whole corpus, 1 436 decomposed contours): work p50 = 380,
#: p90 = 3 245, MAXIMUM 3 660 (`k2_ar_rd_v14`, element 11894479: 60 strips
#: over 61 edges). The ceiling of 250 000 leaves a 68x margin over the worst
#: observation, while also keeping a contour of a thousand vertices (work on
#: the order of 1e6) out of the narrow phase. There is not a single refusal
#: on this ceiling in the corpus — it guards against a degenerate input, not
#: against today's data.
MAX_SWEEP_WORK = 250_000

#: The ceiling on the number of cells. This is NOT a matter of taste: the
#: narrow phase counts a pair of hulls as N x M pairs of cells, so the
#: pair's cost grows together with this number.
#:
#: THE NUMBER WAS RE-DERIVED AFTER THE MERGE FIX (11.08.2026). The former 64
#: stood against a distribution taken BEFORE merging neighbors; the merge
#: shifted the distribution, and leaving the ceiling "with margin" would
#: mean assigning the boundary rather than deriving it.
#:
#: MEASUREMENT 1 — THE DISTRIBUTION (the whole corpus, 1 564 decomposed
#: contours, with no ceiling): cells p50 = 18, p90 = 48, MAXIMUM 78. Before
#: the merge the same contours gave p50 = 19, p90 = 59, maximum 94.
#:
#: MEASUREMENT 2 — THE COST OF THE TOLERANCE, over DISTINCT contours, not
#: over snapshots. Above 64 cells, the corpus turned out to have 19 DISTINCT
#: floors (all on `k2_ar_rd`; across six snapshots of one building they add
#: up to 114 rows, and that is one building, not a hundred and fourteen
#: floors). The same 11 883 candidate pairs, counted twice:
#:
#:     ceiling 64  (footprint convexified)  2.329 s,   196 μs/pair, 11 056 overlaps
#:     ceiling 128 (footprint decomposed)  14.607 s,  1 229 μs/pair,  4 179 overlaps
#:
#: That is, the tolerance costs 6.27x the narrow phase's time ON THESE PAIRS
#: and removes 6 877 overlaps — 62.2% of everything the convex hull was
#: giving. Twelve seconds per building against nearly seven thousand
#: invented findings: an obvious trade, and it is presented, not merely
#: claimed.
#:
#: WHERE 128 COMES FROM. The ceiling is set so that in today's corpus it
#: NEVER FIRES A SINGLE TIME (maximum 78), while still remaining a stop
#: against a degenerate contour. What exactly it stops is also named by a
#: number: the pair's cost grows, by measurement, almost linearly,
#: 196 + 13.6*N μs, so at the ceiling it amounts to about 1.9 ms. This is
#: exactly the value beyond which the ceiling is obligated to be
#: reconsidered — not "whenever it starts looking like a lot."
MAX_CELLS = 128

#: The ceiling on RAW sweep cells — before the merge. It exists only so that
#: a degenerate contour does not eat up memory before things reach the
#: merge step; it has no bearing on the meaningfulness of the answer,
#: because the real ceiling (`MAX_CELLS`) is applied AFTER the merge.
#: Measured 11.08.2026: raw cells p90 = 57, maximum 62 against a ceiling of
#: 64 — that is, before the merge the corpus never comes anywhere near 512,
#: and this ceiling does not fire a single time today.
RAW_CELL_CAP = 512


#: The relative area residual at which the decomposition is considered to
#: have failed to converge.
#:
#: The number is DERIVED and CONFIRMED, not chosen. The derivation: a double
#: carries 2^-52, about 2.2e-16, of relative precision; accumulation over
#: <= MAX_CELLS cells and <= a hundred edges gives an order of 1e-13 in the
#: worst case.
#:
#: MEASUREMENT (`w1_decomp.py`, 11.08.2026, 1 436 decomposed contours across
#: the whole corpus): residual p50 = 1.6e-16, p90 = 5.1e-15, MAXIMUM 1.15e-12
#: (`sob62_fas_r23_v12`, element 11423944, 7 cells). That is, the 1e-9
#: threshold stands 868 times above the worst observation — there is
#: margin, but it is THREE ORDERS OF MAGNITUDE, not seven; if the corpus
#: grows and the residual creeps toward 1e-10, the threshold will have to
#: be reconsidered by measurement, not by reasoning.
#:
#: The threshold sits exactly where an arithmetic error is already
#: impossible, while a geometry error (a self-intersection, a foreign hole)
#: is still visible: on the corpus it caught exactly one contour, and that
#: was a real breakage, not noise.
AREA_REL_TOL = 1e-9

#: The names of the refusals. The list is closed: a decomposition that
#: failed to prove itself is obligated to name itself, otherwise "the hull
#: is convex" is indistinguishable from "the hull is convex because we gave
#: up."
REASONS = (
    "decomposition_over_cap",
    "decomposition_too_many_cells",
    "decomposition_odd_crossings",
    "decomposition_area_mismatch",
    "decomposition_cell_outside_region",
    "decomposition_slab_underflow",
    "decomposition_loop_too_short",
    "decomposition_zero_area",
    "decomposition_cell_not_convex",
)


@dataclass(frozen=True)
class Decomposition:
    """Either a decomposition or a named refusal of one. There is no third state."""
    #: The convex cells. Empty exactly when `reason` is non-empty.
    cells: tuple[tuple[Pt2, ...], ...] = ()
    #: Why there is no decomposition. `None` — there is one.
    reason: str | None = None
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.reason is None and bool(self.cells)


# ─────────────────────────────────────────────────────────── elementary

def _clean(loop: Sequence[Sequence[float]]) -> list[Pt2] | None:
    """A contour -> a list of points with no CONSECUTIVE REPEATS. `None` — not a contour.

    Only a literal repetition of coordinates is removed: the polygon's set
    of points does not change because of this, so this is normalization, not
    a discard. Everything else (a coincidence every other point,
    self-intersection) is left to the checks below.
    """
    pts: list[Pt2] = []
    for p in loop:
        if not (isinstance(p, (list, tuple)) and len(p) >= 2):
            return None
        x, y = p[0], p[1]
        if not (isinstance(x, (int, float)) and isinstance(y, (int, float))
                and math.isfinite(x) and math.isfinite(y)):
            return None
        q = (float(x), float(y))
        if pts and q == pts[-1]:
            continue
        pts.append(q)
    while len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    return pts if len(pts) >= 3 else None


def signed_area(loop: Sequence[Pt2]) -> float:
    n = len(loop)
    return 0.5 * sum(loop[i][0] * loop[(i + 1) % n][1]
                     - loop[(i + 1) % n][0] * loop[i][1] for i in range(n))


def polygon_area(loop: Sequence[Pt2]) -> float:
    return abs(signed_area(loop))


def loop_is_convex(loop: Sequence[Pt2]) -> bool:
    """Convexity AS A FACT ABOUT THE CONTOUR, not about its convex hull.

    This is not needed for elegance: for a convex contour with no holes the
    decomposition refines nothing, and the record is obligated to stay
    BYTE-FOR-BYTE the same as before — otherwise the report's diff stops
    being readable, and along with it the question "what exactly changed
    because of this wave."
    """
    n = len(loop)
    if n < 3:
        return True
    sign = 0
    for i in range(n):
        a, b, c = loop[i], loop[(i + 1) % n], loop[(i + 2) % n]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if cr == 0.0:
            continue
        s = 1 if cr > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def point_in_region(pt: Pt2, loops: Sequence[Sequence[Pt2]]) -> bool:
    """Whether a point lies in the region by the EVEN-ODD rule against the ORIGINAL contours.

    The rule is chosen over non-zero winding deliberately: winding depends
    on the contours' ORIENTATION, and Revit makes no promise that a hole
    will arrive traversed in the opposite direction. Even-odd does not
    depend on orientation at all — and the case where the two rules
    disagree (intersecting contours) is caught by the area check.

    There is not a single line of sweep code here: the check is obligated
    to be INDEPENDENT of what it is checking.
    """
    x, y = pt
    inside = False
    for loop in loops:
        n = len(loop)
        for i in range(n):
            x0, y0 = loop[i]
            x1, y1 = loop[(i + 1) % n]
            if (y0 > y) != (y1 > y):
                xc = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                if x < xc:
                    inside = not inside
    return inside


def interior_witness(cell: Sequence[Pt2]) -> Pt2:
    """A point inside a CONVEX cell — the average of its vertices.

    WHY NOT THE AREA CENTROID. It divides by the area, and for a thin cell
    the area is the difference of nearly equal numbers. Measured
    10.08.2026 (facade floor 9981227, a cell 2.3e-9 mm wide at a length of
    24 844 mm, area 2.9e-5 mm²): the area centroid landed 0.0126 mm OUTSIDE
    the cell's own x range, that is, it pointed outside the very body it
    was describing. The check on it was refusing a perfectly sound
    decomposition.

    The average of the vertices has none of these properties by
    construction: it is a convex combination with POSITIVE weights 1/n, so
    it lies inside the convex hull of the vertices under any configuration
    of them, and there is not a single division by a small quantity in it.
    """
    n = len(cell)
    return (math.fsum(p[0] for p in cell) / n, math.fsum(p[1] for p in cell) / n)


def clip_to_box(cell: Sequence[Pt2], x0: float, y0: float,
                x1: float, y1: float) -> tuple[Pt2, ...]:
    """A CONVEX cell ∩ an axis-aligned rectangle. Exact, with no tolerances.

    Sutherland–Hodgman clipping by four half-planes. Convexity of the input
    is a precondition (this algorithm lies on a concave one), and here it
    holds by construction: sweep cells are what go in.

    WHY THIS IS NEEDED BY EXACTLY ONE CONSUMER. An arc's outer rectangle
    (`hulls._arc_outward_rect`) contains the arc, but its CORNERS stick out
    past the element's bounding box: for a quarter-circle of radius R, the
    outer rectangle's corner sits 1.207R from the center against a bounding
    box of R. Measurement of 10.08.2026 (`snowdon_plumb_v5`, floor
    1424071): 21.06% of the new footprint's area lay OUTSIDE the element's
    bounding box, and this produced 10 findings that did not exist under the
    prior code. The bounding box contains the body — so the intersection
    with it contains the body too, and the extra corner falls away.
    """
    out = list(cell)
    for inside, cut in (
            (lambda p: p[0] >= x0, lambda a, b: _cut(a, b, 0, x0)),
            (lambda p: p[0] <= x1, lambda a, b: _cut(a, b, 0, x1)),
            (lambda p: p[1] >= y0, lambda a, b: _cut(a, b, 1, y0)),
            (lambda p: p[1] <= y1, lambda a, b: _cut(a, b, 1, y1))):
        src, out = out, []
        n = len(src)
        for i in range(n):
            a, b = src[i], src[(i + 1) % n]
            ia, ib = inside(a), inside(b)
            if ia:
                out.append(a)
            if ia != ib:
                out.append(cut(a, b))
        if not out:
            return ()
    dedup: list[Pt2] = []
    for p in out:
        if not dedup or p != dedup[-1]:
            dedup.append(p)
    while len(dedup) > 1 and dedup[0] == dedup[-1]:
        dedup.pop()
    return tuple(dedup)


def _cut(a: Pt2, b: Pt2, ax: int, v: float) -> Pt2:
    d = b[ax] - a[ax]
    t = 0.0 if d == 0.0 else (v - a[ax]) / d
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _distance_to_boundary(pt: Pt2, loops: Sequence[Sequence[Pt2]]) -> float:
    best = math.inf
    for loop in loops:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            dx, dy = b[0] - a[0], b[1] - a[1]
            e = dx * dx + dy * dy
            t = 0.0 if e == 0.0 else max(0.0, min(
                1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / e))
            d = math.hypot(pt[0] - a[0] - dx * t, pt[1] - a[1] - dy * t)
            if d < best:
                best = d
    return best


def _convex_hull(pts: Sequence[Pt2]) -> tuple[Pt2, ...]:
    """The convex hull of a set of points (Andrew's algorithm). Its own, not from `geom`.

    `decompose` does not import `geom` on purpose: the decomposition is
    obligated to remain verifiable independently of whatever the pair
    arithmetic does.
    """
    ps = sorted(set((float(x), float(y)) for x, y in pts))
    if len(ps) <= 2:
        return tuple(ps)

    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])

    lower: list[Pt2] = []
    for q in ps:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], q) <= 0:
            lower.pop()
        lower.append(q)
    upper: list[Pt2] = []
    for q in reversed(ps):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], q) <= 0:
            upper.pop()
        upper.append(q)
    return tuple(lower[:-1] + upper[:-1])


def _vside(cell: Sequence[Pt2], right: bool) -> tuple[float, float, float] | None:
    """A cell's vertical side: `(x, y_низ, y_верх)`. `None` — there is no side.

    A sweep cell is always bounded on the left and right by VERTICALS
    (these are the strip's boundaries), and after the merge this property
    is preserved: a merged cell's left side is its left neighbor's, its
    right side is its right neighbor's. So the chain can be continued any
    number of times with no special case.
    """
    xs = [p[0] for p in cell]
    x = max(xs) if right else min(xs)
    ys = sorted(p[1] for p in cell if p[0] == x)
    if len(ys) < 2 or ys[0] == ys[-1]:
        return None
    return (x, ys[0], ys[-1])


def _join(a: Sequence[Pt2], b: Sequence[Pt2],
          shared: tuple[float, float, float]) -> tuple[Pt2, ...] | None:
    """The union of two neighbors, if it is CONVEX. Otherwise `None`.

    There are two checks, and both are mandatory:

    * CONVEXITY — otherwise the union cannot be handed to SAT, which is the
      whole reason the decomposition is done in the first place;
    * AREA — the sum of the neighbors' areas is obligated to match the
      union's area. Without this check the merge would silently SUBSTITUTE
      the union with its convex hull and add area that does not exist in
      the region. Coarsening outward is not forbidden by the law, but it is
      obligated to be NAMED, and doing it silently is exactly what this
      wave was cleaning out of the module.
    """
    x1, ylo, yhi = shared
    xa = min(p[0] for p in a)
    xb = max(p[0] for p in b)
    ay = sorted(p[1] for p in a if p[0] == xa)
    by = sorted(p[1] for p in b if p[0] == xb)
    if len(ay) < 2 or len(by) < 2:
        return None
    hexa = [(xa, ay[0]), (x1, ylo), (xb, by[0]),
            (xb, by[-1]), (x1, yhi), (xa, ay[-1])]
    poly: list[Pt2] = []
    for p in hexa:
        if not poly or p != poly[-1]:
            poly.append(p)
    while len(poly) > 1 and poly[0] == poly[-1]:
        poly.pop()
    if len(poly) < 3 or not loop_is_convex(poly):
        return None
    want = polygon_area(a) + polygon_area(b)
    if want <= 0.0:
        return None
    if abs(polygon_area(poly) - want) > AREA_REL_TOL * want:
        return None
    return tuple(poly)


def merge_convex_neighbours(cells: Sequence[Sequence[Pt2]]
                            ) -> tuple[tuple[tuple[Pt2, ...], ...], int]:
    """Merge neighboring cells whose union is convex. Returns `(cells, merges)`.

    WHY. The sweep extends a cell to the right only while it is bounded by
    THE SAME TWO EDGES. The moment the lower boundary switches to a
    neighboring edge, the cell closes, even though the union of two
    neighbors is convex more often than not and has every right to be one
    cell. MEASUREMENT before the fix (`w3_merge_probe.py`, 11.08.2026, the
    whole corpus): out of 16 052 pairs of neighboring cells, 6 265 (39.0%)
    have a CONVEX union, meaning every third boundary was drawn for
    nothing.

    The cost of fragmentation is twofold, and both halves are measured: 162
    contours out of 1 598 hit `MAX_CELLS` and fall back to a convex hull,
    while for the rest a pair of hulls in the narrow phase costs N*M
    footprint comparisons.

    WHY THE COINCIDENCE OF COORDINATES IS CHECKED EXACTLY, WITH NO
    TOLERANCE. A strip boundary always sits at a vertex's x, and
    `y_at(edge, x)` at an x equal to an edge's endpoint returns that
    vertex's coordinate BIT FOR BIT (the multiplier resolves to exactly 0
    or 1). An edge, in turn, only changes at a strip boundary at a vertex.
    So two neighbors' shared side coincides exactly, and a tolerance here
    would not be insurance but a way to glue together things that are not
    actually adjacent.

    The merge is DETERMINISTIC: cells are traversed in sorted order by
    coordinates, not in order of appearance.
    """
    cur = [tuple(c) for c in cells]
    joins = 0
    while len(cur) > 1:
        by_left: dict[tuple[float, float, float], list[int]] = {}
        for i, c in enumerate(cur):
            s = _vside(c, right=False)
            if s is not None:
                by_left.setdefault(s, []).append(i)
        order = sorted(range(len(cur)), key=lambda i: tuple(sorted(cur[i])))
        used: set[int] = set()
        out: list[tuple[Pt2, ...]] = []
        made = 0
        for i in order:
            if i in used:
                continue
            used.add(i)
            cell = cur[i]
            while True:
                r = _vside(cell, right=True)
                if r is None:
                    break
                cands = [j for j in by_left.get(r, ()) if j not in used]
                got = None
                for j in sorted(cands, key=lambda j: tuple(sorted(cur[j]))):
                    m = _join(cell, cur[j], r)
                    if m is not None:
                        got = (j, m)
                        break
                if got is None:
                    break
                used.add(got[0])
                cell = got[1]
                made += 1
            out.append(cell)
        joins += made
        cur = out
        if made == 0:
            break
    return tuple(cur), joins


# ─────────────────────────────────────────────────────────────── the sweep

def decompose(exterior: Sequence[Sequence[float]],
              holes: Sequence[Sequence[Sequence[float]]] = (),
              *, max_work: int = MAX_SWEEP_WORK,
              max_cells: int = MAX_CELLS) -> Decomposition:
    """A region (outer contour + holes) -> convex cells or a refusal.

    The invariant PROVEN here, not merely declared:

        the union of the cells == the declared region,

    to within double-precision arithmetic (see `AREA_REL_TOL`). Not
    "contains" and not "is contained" — EQUALS. This is precisely why a
    footprint stops being a coarsening for the first time; why the grade
    still does NOT become `exact` is stated in
    `hulls.UNREACHABLE_GRADE_REASONS` — a hull is also a Z, and that is
    still taken from the declared elevation rather than from the body's
    direction of growth.
    """
    ext = _clean(exterior)
    if ext is None:
        return Decomposition(reason="decomposition_loop_too_short")
    loops: list[list[Pt2]] = [ext]
    for h in holes or ():
        c = _clean(h)
        if c is not None:                 # a degenerate hole carries no area
            loops.append(c)

    area_declared = polygon_area(ext) - sum(polygon_area(h) for h in loops[1:])
    if area_declared <= 0.0:
        return Decomposition(reason="decomposition_zero_area",
                             stats={"area_declared": area_declared})

    # Edges. Vertical ones are skipped NOT as "small," but as carrying no
    # area: the x-strip is cut exactly along them, they never fall inside a
    # strip.
    edges: list[tuple[Pt2, Pt2]] = []
    for loop in loops:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            if a[0] == b[0]:
                continue
            edges.append((a, b) if a[0] < b[0] else (b, a))
    if not edges:
        return Decomposition(reason="decomposition_zero_area",
                             stats={"area_declared": area_declared})

    # Strip boundaries are the vertices' x values. Merging CLOSE values here
    # would mean discarding a thin strip, that is, shrinking the region, and
    # is therefore forbidden. What is subject to merging is exactly
    # ADJACENT DOUBLES — those between which NO REPRESENTABLE NUMBER
    # exists: such a strip has no middle, and therefore no point at which
    # one could ask "inside or outside."
    #
    # THE MEASUREMENT this was written for (11.08.2026, the whole corpus):
    # without the merge, 640 contours out of 1 633 (39.2%) were refusing
    # with `slab_underflow` and falling back to a convex hull — because
    # converting feet to mm leaves vertices like 1410.9127015655997 and
    # 1410.9127015655999. This is ONE drawing vertex that drifted apart in
    # its last digit. After the merge, refusals for this reason across the
    # corpus are ZERO.
    #
    # The merge shrinks the region by no more than (number of merges) x
    # (double's step) x (height) — a quantity that does not exist in mm. But
    # promising this is not enough: the shrinkage is CHECKED by the area
    # reconciliation below, and a contour where the merge broke something
    # refuses under the name `decomposition_area_mismatch`.
    xs_all = sorted({p[0] for loop in loops for p in loop})
    xs = [xs_all[0]] if xs_all else []
    merged_x = 0
    for v in xs_all[1:]:
        if math.nextafter(xs[-1], math.inf) >= v:
            merged_x += 1
            continue
        xs.append(v)
    if len(xs) < 2:
        return Decomposition(reason="decomposition_zero_area",
                             stats={"area_declared": area_declared,
                                    "merged_x": merged_x})
    n_slabs = len(xs) - 1
    work = n_slabs * len(edges)
    if work > max_work:
        return Decomposition(reason="decomposition_over_cap",
                             stats={"work": work, "slabs": n_slabs,
                                    "edges": len(edges)})

    def y_at(e: tuple[Pt2, Pt2], x: float) -> float:
        (x0, y0), (x1, y1) = e
        return y0 + (y1 - y0) * ((x - x0) / (x1 - x0))

#: A cell lives as (x_левый, x_правый, ребро_низа, ребро_верха) and GROWS
#: to the right for as long as the same two edges bound it. The merge is
#: exact: two neighboring strips with the same pair of bounding LINES give
#: exactly the same trapezoid as one wide one. Without the merge, a contour
#: of 108 vertices would give a hundred cells where a handful would do.
    open_cells: dict[tuple[int, int], int] = {}
    raw: list[list] = []
    degenerate = 0

    for s in range(n_slabs):
        xl, xr = xs[s], xs[s + 1]
        xm = 0.5 * (xl + xr)
        if not (xl < xm < xr):
            # After merging adjacent doubles this cannot happen; if it did
            # happen anyway — one must not stay silent, the strip can be
            # neither counted nor discarded.
            return Decomposition(reason="decomposition_slab_underflow",
                                 stats={"x_left": xl, "x_right": xr})
        cross: list[tuple[float, int]] = []
        for ei, e in enumerate(edges):
            if e[0][0] < xm < e[1][0]:
                cross.append((y_at(e, xm), ei))
        if not cross:
            open_cells = {}
            continue
        if len(cross) % 2:
            # An odd number of intersections — the contour either
            # self-intersects or is not closed. There is nothing to place
            # "inside/outside" with.
            return Decomposition(reason="decomposition_odd_crossings",
                                 stats={"x_mid": xm, "crossings": len(cross)})
        cross.sort()
        nxt: dict[tuple[int, int], int] = {}
        for k in range(0, len(cross), 2):
            key = (cross[k][1], cross[k + 1][1])
            idx = open_cells.get(key)
            if idx is not None:
                raw[idx][1] = xr                      # extending to the right
            else:
                raw.append([xl, xr, key[0], key[1]])
                idx = len(raw) - 1
                if len(raw) > RAW_CELL_CAP:
                    # The ceiling on RAW cells is only so the sweep does not
                    # eat memory on a degenerate contour. The real ceiling
                    # (`max_cells`) is applied AFTER the merge: before it,
                    # the cell count is not yet the cell count.
                    return Decomposition(
                        reason="decomposition_too_many_cells",
                        stats={"cells_raw": len(raw), "slabs": n_slabs,
                               "edges": len(edges)})
            nxt[key] = idx
        open_cells = nxt

    cells: list[tuple[Pt2, ...]] = []
    for xl, xr, lo_i, hi_i in raw:
        lo, hi = edges[lo_i], edges[hi_i]
        quad = [(xl, y_at(lo, xl)), (xr, y_at(lo, xr)),
                (xr, y_at(hi, xr)), (xl, y_at(hi, xl))]
        poly: list[Pt2] = []
        for p in quad:
            if not poly or p != poly[-1]:
                poly.append(p)
        if len(poly) > 1 and poly[0] == poly[-1]:
            poly.pop()
        # A degenerate cell (a segment/point) carries no area, but it cannot
        # be discarded either: these are points of the region, and "we do
        # not silently discard."
        if len(poly) < 3:
            degenerate += 1
        cells.append(tuple(poly))

    if not cells:
        return Decomposition(reason="decomposition_zero_area",
                             stats={"area_declared": area_declared})

    # ── check 1: area
    area_cells = sum(polygon_area(c) for c in cells if len(c) >= 3)
    residual = abs(area_cells - area_declared) / area_declared
    if residual > AREA_REL_TOL:
        return Decomposition(
            reason="decomposition_area_mismatch",
            stats={"area_declared": area_declared, "area_cells": area_cells,
                   "residual_rel": residual, "cells": len(cells)})

    # ── check 2: an interior point of every cell — inside the ORIGINAL region
    #
    # A TRI-STATE, NOT YES/NO. The even-odd ray decides the question by
    # comparing coordinates, and for a cell thinner than a double's step
    # there is nothing left to compare: its interior point sits a mere
    # handful of ULPs from the boundary, and the "inside" predicate stops
    # being defined — not "false," but precisely UNDEFINED. Such cells are
    # counted as UNVERIFIED and published as a number, exactly as
    # `loops_overlap` publishes its own `None`. Their area, meanwhile, is
    # already accounted for by the reconciliation above, so they create no
    # gap: only something thinner than the arithmetic itself can hide in
    # them.
    #
    # The threshold is named by arithmetic, not by taste: `math.ulp(scale)`
    # is the true step of a double at a point of that scale, and an
    # eightfold margin covers the spread of roundings in the distance
    # formula itself.
    unverified = 0
    for c in cells:
        if len(c) < 3 or polygon_area(c) <= 0.0:
            unverified += 1
            continue
        w = interior_witness(c)
        if point_in_region(w, loops):
            continue
        scale = max(abs(w[0]), abs(w[1]), 1.0)
        if _distance_to_boundary(w, loops) <= 8.0 * math.ulp(scale):
            unverified += 1
            continue
        return Decomposition(
            reason="decomposition_cell_outside_region",
            stats={"cell": [list(p) for p in c], "cells": len(cells),
                   "witness": list(w)})

    # ── merging convex neighbors. The union of the cells DOES NOT CHANGE as
    #    a set (this is checked by `_join` via an area reconciliation), so
    #    all the checks above remain valid; what changes is only how many
    #    convex pieces it is written as.
    raw_cells = len(cells)
    merged, joins = merge_convex_neighbours(cells)
    area_merged = sum(polygon_area(c) for c in merged if len(c) >= 3)
    if abs(area_merged - area_cells) > AREA_REL_TOL * max(area_declared, 1.0):
        # A merge is obligated to preserve the area down to the last digit.
        # If it did not — we do not merge at all, rather than "merge and
        # hope."
        merged, joins = tuple(tuple(c) for c in cells), 0
    # ── A SET INVARIANT, not a property of the algorithm. Everything
    #    further down the pipeline — SAT, exact distance, the closed-form
    #    minimal exit — are all theorems about CONVEX sets. A non-convex
    #    piece that gets into the set will not raise an error: it will
    #    silently return the convex hull's answer, that is, exactly the
    #    defect `geom.PrismSet` was set up to eliminate. So the convexity of
    #    EVERY cell is checked here, rather than inferred from the sweep
    #    producing trapezoids and the merge supposedly preserving that.
    repaired = 0
    fixed_cells: list[tuple[Pt2, ...]] = []
    for c in merged:
        if len(c) < 3 or loop_is_convex(c):
            fixed_cells.append(tuple(c))
            continue
        # WHERE THIS COMES FROM. Measurement of 11.08.2026: all 20 such
        # cells in the corpus are produced by the SWEEP, not one by the
        # merge. All twenty are degenerate: in the example
        # (`k2_ar_rd_v14`, element 15949387) four vertices differ in x at
        # the eighteenth digit (18800.000000019340 versus
        # 18800.000000019358), three of the four y's coincide. This is not
        # a polygon, it is arithmetic dust on an almost-vertical edge.
        #
        # FIXING IT WITH A CONVEX HULL IS LEGITIMATE EXACTLY AS LONG AS THE
        # AREA DOES NOT GROW. The hull of a degenerate set of points is
        # itself degenerate, so the area stays at zero, the union does not
        # change by a single mm², and the pieces are convex again. But if
        # the area DID grow, the piece was non-convex IN SUBSTANCE, and then
        # the answer is a refusal, not a fix: silently substituting the
        # region with its convex hull is forbidden by the very same law as
        # everything else here.
        hull = _convex_hull(c)
        if len(hull) >= 3 and abs(polygon_area(hull) - polygon_area(c)) >                 AREA_REL_TOL * max(area_declared, 1.0):
            return Decomposition(
                reason="decomposition_cell_not_convex",
                stats={"cell": [list(q) for q in c], "cells": len(merged),
                       "merges": joins})
        repaired += 1
        fixed_cells.append(tuple(hull) if hull else tuple(c))
    merged = tuple(fixed_cells)
    if len(merged) > max_cells:
        return Decomposition(
            reason="decomposition_too_many_cells",
            stats={"cells": len(merged), "cells_raw": raw_cells,
                   "merges": joins, "slabs": n_slabs, "edges": len(edges)})
    cells = list(merged)

    return Decomposition(
        cells=tuple(cells),
        stats={"cells": len(cells), "cells_raw": raw_cells, "merges": joins,
               "slabs": n_slabs, "edges": len(edges),
               "work": work, "degenerate_cells": degenerate,
               "cells_unverified": unverified, "merged_x": merged_x,
               "cells_repaired": repaired,
               "holes": len(loops) - 1,
               "area_declared": area_declared, "area_cells": area_cells,
               "residual_rel": residual})
