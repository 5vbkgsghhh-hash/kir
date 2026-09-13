"""sweep_path — SWEEP GEOMETRY COMPUTED AT COMPILE TIME.

Not a single line about Revit: only numbers here, so everything below is
verifiable offline, before any bridge. Paired with `solid_emit.emit_solid_sweep`,
exactly as `contour.py` is paired with the contour emitters.

═══ WHY THIS FILE EXISTS AT ALL ═══════════════════════════════════════════

The header of `ops_solid.py` refused the sweep FOR EXACTLY THIS REASON, verbatim:
«the volume of a sweep along a NON-PLANAR path of a closed shape has no…
Computing the volume by sampling the path means injecting the witness's own
error into it and baking it into the tolerance». And in the same place it
names what would open the operation: «a path constraint + a proof of
non-intersection, then V = A·L(centroid)».

This file is exactly that proof — in a form stronger than promised. It turned
out that the path does not need to be planar AT ALL, and only one thing is
needed: **the profile's centroid must lie ON the path**. Then the volume
equals `A·L` exactly, for ANY spatial polyline.

═══ THE CONCLUSION EVERYTHING IS FOR ══════════════════════════════════════

The sweep body is the set of points `γ(s) + u·e₁(s) + v·e₂(s)`, where `(u,v)`
ranges over the profile, and `(e₁,e₂)` is the basis of the plane perpendicular
to the path. The Jacobian of this map equals `1` on every STRAIGHT segment:
`∂/∂s = T`, and rotating the basis around `T` gives vectors lying in the plane
`(e₁,e₂)` itself, which the determinant kills. So a segment of length `L`
gives exactly `A·L`.

The whole subtlety is AT THE JOINTS. Where two segments meet, Revit trims both
by the bisector plane (the "miter"). For a profile point offset by `w`, the
trim shifts its end by `−(w·n)/(d·n)`, where `n` is the normal of the bisector
plane. The integral of this correction over the profile equals

    −(1/(d·n)) · ∬ w dA · n

and `∬ w dA` is the FIRST MOMENT OF THE PROFILE ABOUT THE AXIS. If the axis
passes through the centroid, it is zero in EVERY direction, so the correction
is zero at every joint, for any turning angle and any rotation of the profile
about the axis.

    ⇒  V = A · L_polyline,  EXACTLY.

This is exactly Pappus's theorem, extended to a spatial polyline: «volume =
area × the path traveled by the CENTROID». We simply place the centroid on
the path, and then the path of the centroid is the polyline itself.

═══ OFFSETTING THE PROFILE FROM THE PATH: THE COST WAS OVERSTATED, HERE IS THE MEASUREMENT ═════════════════

⛔ THE PREVIOUS TEXT AT THIS SPOT WAS RETRACTED ON 21.08.2026. It read: «the
author no longer decides where the profile sits on the path… an offset
profile cannot be expressed by this operation», and justified this by saying
the correction depends on the rotation, and Revit chooses the rotation. What
is retracted is not the arithmetic but the SCOPE of the conclusion: Revit
chooses the rotation ONLY for `variety="frame"`. For `fixed_reference`, the
frame at every segment is fixed by the input (`e1 = unit(T × ref)`), so the
correction is computable to the last digit, and the volume remains a property
of the input.

WHAT THE OFFSET COST, WHILE UNSTATED: 55 sweeps of the real building, i.e. THE
ENTIRE genus. In 55 of 55, the profile's centroid does NOT lie on the path
(measured 21.08 from `family_recipe`: closest 10.3 mm, farthest 505 mm, not a
single zero). Our op placed the centroid ON the path, and therefore expressed
NOT ONE family sweep.

THE CORRECTION, DERIVED BY THE SAME INTEGRAL. At joint `j` the miter trims the
profile fiber standing off from the path by `w` by `(w·n)/(d·n)`, where
`n = unit(d_{j−1} + d_j)` is the normal of the bisector plane. Both segments
give `d·n = cos(φ/2) = c`, and the sum over both gives the fiber length
`L + ((w_j − w_{j−1})·n)/c`. The integral over the profile replaces `w` with
its mean, i.e. with the centroid offset `w̄`:

    V = A · ( L + Σ_j ((w̄_j − w̄_{j−1})·n_j) / c_j ),   w̄_i = ou·e1_i + ov·e2_i

At `w̄ = 0` the sum vanishes at every joint — the earlier law `V = A·L` is a
SPECIAL CASE of this, not overturned by it. This is still Pappus: the length
of the path traveled by the centroid.

🔴 MEASURED AGAINST REVIT ITSELF, NOT AGAINST ITSELF. Across 34 family sweeps
for which Revit returned its own volume (`Solid.Volume` of the same shape):

    V = A·L                            0 of 34 matched (discrepancy up to 15.0 %)
    V with the offset correction      34 of 34 matched (worst 0.0024 %)

Thirty-four zeros in a row is not a tolerance, it is an identity; the 0.0024 %
on one shape is explained by coordinates arriving rounded to 0.001 mm.

🔴 WHAT REMAINS A NAMED ABSENCE. `variety="frame"` WITH AN OFFSET: there,
`e1_i` is chosen by Revit by minimal twist, the rule is undocumented, and
substituting our own would mean passing someone else's choice off as a
property of the input. The refusal is named explicitly in the emission.
Without an offset, `frame` works as it always did: the correction is zero for
ANY rotation, because the first moment of the profile about the centroid is
zero in every direction.

═══ WHAT THIS FILE DOES NOT DO ════════════════════════════════════════════

It does not compute arc arithmetic. It has no second home for that in this
package, and never will: everything needed about arcs is asked of `contour`
through its own public measures (`region_measures`, `edges_to_sample_poly`).
Hence the deliberate coarseness of `profile_circumradius` — see its header.
"""
from __future__ import annotations

import math

from kir import contour as C

#: Largest turn at a polyline joint, degrees.
#: ⚠️ CHOSEN, NOT MEASURED, and here is the boundary between the two.
#: DERIVED: at a turn of `φ` the miter trims the segment by `R·tan(φ/2)`, and
#: as `φ → 180°` this amount goes to infinity — i.e. an in-place reversal is
#: not expressible by a miter for any profile. CHOSEN: exactly where to stop.
#: 120° gives `tan(60°) ≈ 1.73`, i.e. the trim is less than two profile
#: radii — a margin at which the feasibility check remains meaningful rather
#: than formal. It may be raised only by a live run showing that Revit builds
#: a sharper miter; it may be lowered freely.
MAX_TURN_DEG = 120.0

#: Smallest fraction of a segment remaining after BOTH miters. Below it the
#: segment degenerates: the two trims consume it entirely and the body tears.
#: ⚠️ CHOSEN. 0.05 means "at least 5% of the segment must remain."
MIN_SEGMENT_FRACTION = 0.05


def _mirror(edges: list) -> list:
    """Reflection of a ring across the diagonal `y = x`: `(x,y) → (y,x)`,
    `bulge → −bulge`.

    Needed for exactly one thing: `contour.region_measures` gives `∬x dA` and
    does not give `∬y dA`, while the centroid needs both. The reflection
    turns the second moment into the first, and no second home for
    integration gets built.

    The bulge sign flips because the reflection flips the side of the arc —
    the same law that canonicalization of a ring lives by in `decompile/fold`.

    🔴 A SPLINE WILL NEVER LAND HERE, and this is not an oversight: the
    grounding guard (`ground`, `contour.SPLINE_WITNESSED_OPS`) does not let a
    spline into an op whose witness does not prove it, and the sweep is not
    on that list. If it ever is added, the reflection will also have to
    reverse the spline's point list, and this line will become a defect.
    """
    return [((p0[1], p0[0]), (p1[1], p1[0]), -b) for p0, p1, b in edges]


def profile_centroid(region: dict) -> tuple[float, float, float]:
    """`(cx, cy, area)` of the profile — as a CLOSED-FORM SHAPE, not a
    sampling.

    Checked on 20.08.2026 against an INDEPENDENT answer: a dense sampling of
    the arcs, built from the definition of the bulge (sagitta = |b|·half-
    chord) via the circle through three points, and the shoelace formula
    over 20,000 points. Agreement to 1e-7 mm on shapes with two arcs and an
    opening; exact on a rectangle. The check caught itself too: its first
    version took the LEFT normal and diverged by exactly the segment's area
    — that is how the package's convention was discovered (a positive bulge
    is laid out to the RIGHT of `p0 → p1`).
    """
    m = C.region_measures(region)
    mirrored = C.region_measures({
        "outer": _mirror(region["outer"]),
        "holes": [_mirror(h) for h in region.get("holes", ())],
    })
    area = m["area_mm2"]
    return (m["moment_x_mm3"] / area, mirrored["moment_x_mm3"] / area, area)


def profile_circumradius(region: dict, cx: float, cy: float) -> float:
    """Largest distance from the profile boundary to the centroid — an UPPER
    BOUND ESTIMATE.

    🔴 DELIBERATELY COARSE, AND HERE IS EXACTLY WHY. The exact value for an
    arc requires its center and radius, i.e. a second home for arc
    arithmetic. Instead, this takes the sampling from
    `contour.edges_to_sample_poly` (its chords lie INSIDE the convex arc,
    i.e. they underestimate) plus half of the longest chord. A chord's
    sagitta never exceeds half the chord for any opening up to 180°
    (`s/c = tan(α/4)/2 ≤ 1/2`), so the sum is a strict upper bound.

    Where this coarseness is aimed: `R` enters ONLY the feasibility
    conditions and the bounding-box limit, and in both places an
    overestimate makes the check STRICTER, not looser. An overestimated `R`
    may refuse a legitimate program — that is a named refusal the author
    will see; an underestimate would sign off on a torn body silently.
    """
    worst = 0.0
    longest_chord = 0.0
    for ring in [region["outer"]] + list(region.get("holes", ())):
        poly = C.edges_to_sample_poly(ring)
        for i, (x, y) in enumerate(poly):
            worst = max(worst, math.hypot(x - cx, y - cy))
            nx, ny = poly[(i + 1) % len(poly)]
            longest_chord = max(longest_chord, math.hypot(nx - x, ny - y))
    return worst + longest_chord / 2.0


def _unit(v: tuple) -> tuple:
    n = math.sqrt(sum(c * c for c in v))
    return (v[0] / n, v[1] / n, v[2] / n)


def _sub(a, b) -> tuple:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b) -> tuple:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def path_directions(points: list) -> list:
    """Unit directions of the segments. Coincident points never occur here —
    the `path3` genus validation rejects them (a segment shorter than 1 mm =
    refusal)."""
    return [_unit(_sub(points[i + 1], points[i]))
            for i in range(len(points) - 1)]


def path_length_mm(points: list) -> float:
    return sum(math.dist(points[i], points[i + 1])
               for i in range(len(points) - 1))


def path_nodes(points: list) -> list:
    """Indices of the polyline's JOINTS: places where segment `node−1` meets
    segment `node`.

    THE SINGLE CARRIER OF THE ANSWER TO "WHAT JOINTS DOES THIS PATH HAVE",
    and it was set up because the answer is DIFFERENT for an open and a
    closed polyline, and three places asked it separately and answered
    differently. For an open one, only the internal joints exist,
    `1 .. segments−1`. For a CLOSED one, the SEAM is added to them — joint
    `0`, where the last segment meets the first.

    🔴 THE SEAM IS A JOINT LIKE ANY OTHER, AND THIS IS NOT AN OPINION.
    `is_closed` says so directly («a closed path has an EXTRA joint — the
    seam… and the miter at this seam introduces the same correction as any
    other»), `_bisector` takes indices MODULO exactly for this reason, and
    `miter_correction_mm` does count the seam. The only thing that did not
    count it was the TURN LIMIT, and here is what that cost (measured
    04.09.2026, closed scalene triangle
    `[[0,0,0],[10000,0,0],[9000,3000,0],[0,0,0]]`):

        is_closed             True
        computed angles       [108.4°, 90.0°]
        SEAM                  161.6°   — limit 120°, and it is NOT in the list
        feasibility(R=200)    None     — "buildable", even though the miter
                                         at the seam trims the segment by 1232 mm

    A turn of 161.6° is not expressible by a miter at all (`R·tan(φ/2)` goes
    to infinity as `φ→180°`) — i.e. a refusal was owed, and did not arrive.
    """
    count = len(points) - 1
    nodes = list(range(1, count))
    if is_closed(points):
        nodes.append(0)
    return nodes


def turn_at_node(dirs: list, node: int) -> float:
    """Turn at joint `node` between segments `node−1` and `node`, degrees.

    Indices modulo — by the same rule as `_bisector`: for a closed polyline,
    joint `0` connects the LAST segment to the first.
    """
    count = len(dirs)
    c = max(-1.0, min(1.0, _dot(dirs[(node - 1) % count], dirs[node % count])))
    return math.degrees(math.acos(c))


def turn_angles_deg(points: list) -> list:
    """Turn at every INTERNAL joint, degrees. List length = segments − 1.

    🔴 THERE IS NO SEAM HERE, AND THIS IS NOW DECLARED, NOT IMPLIED. The list
    is indexed BY SEGMENT (`turns[i]` is joint `i+1`), and appending the seam
    to it would break this indexing for every reader. Whoever needs ALL
    joints — including the seam of a closed one — calls `turns_by_node`,
    which returns a `(joint, angle)` pair, where the joint number is named
    rather than inferred from position.
    """
    dirs = path_directions(points)
    return [turn_at_node(dirs, i + 1) for i in range(len(dirs) - 1)]


def turns_by_node(points: list) -> list:
    """`(joint, turn°)` for EVERY joint of the path — with the seam for a
    closed one.

    This is exactly what the `MAX_TURN_DEG` limit asks: the law "no sharper
    than this at a joint" speaks of a JOINT, and which joints exist is known
    by `path_nodes`.
    """
    dirs = path_directions(points)
    return [(node, turn_at_node(dirs, node)) for node in path_nodes(points)]


def frame_at(direction: tuple, reference: tuple) -> tuple:
    """Basis of the plane PERPENDICULAR to the path: `(e1, e2)`.

    `e1 = unit(T × ref)`, `e2 = T × e1`. The meaning is exactly the one
    `CreateFixedReferenceSweptGeometry` lives by: `e1` is perpendicular to
    the reference direction, so a profile line that starts out perpendicular
    to it stays that way along the whole path (RevitAPI.xml gives the
    example of a railing whose top must remain horizontal).

    `None` if the reference direction is collinear with the path's
    direction: then the plane is not defined by it at all, and choosing on
    the author's behalf is not allowed — exactly the case this house has
    named refusals for.
    """
    cr = _cross(direction, reference)
    if math.sqrt(sum(c * c for c in cr)) < 1e-9:
        return None
    e1 = _unit(cr)
    e2 = _unit(_cross(direction, e1))
    return e1, e2


def profile_support_mm(region: dict, direction_uv: tuple,
                       anchor_uv: tuple) -> float:
    """SUPPORT FUNCTION of the profile: how far it extends IN A GIVEN
    DIRECTION from the anchor point. AN UPPER-BOUND ESTIMATE, of the same
    coarseness and for the same reason as `profile_circumradius`: the arc
    sampling underestimates, half of the longest chord returns a strict
    upper bound.

    HOW THIS DIFFERS FROM THE RADIUS AND WHY IT IS SET UP SEPARATELY. The
    radius answers "how far does the profile extend IN ANY direction" —
    that is the right answer while the direction is unknown. Once the frame
    is fixed by the input (`fixed_reference`), the direction IS KNOWN: the
    miter at a joint trims the fiber by a linear function of (u, v), and its
    maximum over the profile is exactly the support function. The
    difference is not cosmetic: for a 600 × 900 profile standing off from
    the path by 355 mm, the radius gives 1065 mm in EVERY direction, while
    the real extent across the path is a third of that.

    🔴 THE MARGIN IS ADDED ONLY FOR A CURVED RING, AND THIS IS NOT AN
    ECONOMY, IT IS ACCURACY. `profile_circumradius` next door adds half the
    longest chord ALWAYS — there that is justified by its role (coarser
    means stricter, and the radius enters only one-sided checks). Here that
    will not do: for a STRAIGHT ring, the `edges_to_sample_poly` sampling
    returns the vertices themselves, the linear function reaches its
    maximum AT A VERTEX, and the margin would be added FOR NOTHING. Measured
    21.08: it was adding 355 mm and held back three family sweeps that Revit
    did build. Straightness is decided by CONTOUR's own predicate
    (`edges_are_straight`), not by its own threshold on the bulge.
    """
    best = None
    slack = 0.0
    du, dv = float(direction_uv[0]), float(direction_uv[1])
    au, av = float(anchor_uv[0]), float(anchor_uv[1])
    scale = math.hypot(du, dv)
    for ring in [region["outer"]] + list(region.get("holes", ())):
        poly = C.edges_to_sample_poly(ring)
        straight = C.edges_are_straight(ring)
        for i, (x, y) in enumerate(poly):
            value = (x - au) * du + (y - av) * dv
            best = value if best is None else max(best, value)
            if not straight:
                nx, ny = poly[(i + 1) % len(poly)]
                slack = max(slack, math.hypot(nx - x, ny - y) * scale / 2.0)
    if best is None:
        return 0.0
    return best + slack


def _bisector(dirs: list, node: int) -> tuple | None:
    """Normal of the bisector plane at joint `node` (between `node−1` and
    `node`).

    Indices are taken modulo: for a closed polyline the seam is a joint just
    like any other.
    """
    count = len(dirs)
    a, b = dirs[(node - 1) % count], dirs[node % count]
    n = tuple(a[k] + b[k] for k in range(3))
    length = math.sqrt(sum(c * c for c in n))
    if length < 1e-9:
        return None
    return tuple(c / length for c in n)


def frame_feasibility(points: list, region: dict, anchor_uv: tuple,
                      reference: tuple) -> str | None:
    """`None` if the miter builds everywhere; otherwise the REASON in words.
    THE EXACT CHECK.

    HOW IT IS MORE EXACT THAN `feasibility` AND WHY BOTH ARE NEEDED. Both ask
    the same thing: will anything be left of the segment after the miters at
    both of its ends. The difference is in WHAT IS KNOWN about the profile's
    rotation.

      `feasibility`        the rotation is UNKNOWN (`variety="frame"`, Revit
                           chooses it) — the worst case over all rotations is
                           taken, i.e. the isotropic radius;
      `frame_feasibility`  the rotation is FIXED BY THE INPUT
                           (`fixed_reference`) — the trim computed is exactly
                           the one that will occur.

    This is not two copies of one law: the law is one (`MIN_SEGMENT_FRACTION`
    of the segment must survive both miters), but the inputs differ. The
    common part is factored out into `_segment_survives`.

    🔴 THE COST OF THE ISOTROPIC ESTIMATE, MEASURED 21.08.2026. It rejected
    six family sweeps of the real building as "the body will tear." The
    exact check rejected THREE of the six — exactly the three for which
    Revit itself did not return a volume for the shape; the other three do
    have a volume, and our law matched it down to zero. That is, the
    isotropic estimate was wrong on 3 shapes out of 6, and the exact one on
    none. This is the same named defect that `MIN_EXTENT_MM` was cleared of
    on the same day: our own limit, passed off as Revit's limit.

    DERIVATION OF THE TRIM. The profile fiber standing off from the path by
    `w`, on segment `i`, has length `L + (w·n_start)/c − (w·n_end)/c`, where
    `n` are the bisector normals at the segment's ends. Both corrections are
    linear in `(u, v)`, so their sum is a single linear function, and its
    minimum over the profile is the support function in the opposite
    direction.
    """
    frames = frames_along(points, reference)
    if frames is None:
        return ("опорное направление коллинеарно какому-то звену пути — рамки "
                "профиля на нём не существует")
    dirs = path_directions(points)
    count = len(dirs)
    closed = is_closed(points)
    for node, phi in turns_by_node(points):
        if phi >= MAX_TURN_DEG:
            seam = " (ШОВ замкнутого пути)" if node == 0 else ""
            return (f"поворот {phi:.1f}° в узле {node}{seam} — предел "
                    f"{MAX_TURN_DEG:g}°; усом такой разворот не выражается")
    for i, (e1, e2) in enumerate(frames):
        gu = gv = 0.0
        for node, sign in ((i, 1.0), (i + 1, -1.0)):
            if not closed and not (0 < node < count):
                continue                  # for an open polyline the end is not trimmed
            n = _bisector(dirs, node)
            if n is None:
                return f"в узле {node} разворот на месте — биссектрисы нет"
            c = _dot(dirs[i], n)
            if abs(c) < 1e-9:
                return f"в узле {node} биссектриса перпендикулярна звену {i}"
            gu += sign * _dot(e1, n) / c
            gv += sign * _dot(e2, n) / c
        seg = math.dist(points[i], points[i + 1])
        eaten = profile_support_mm(region, (-gu, -gv), anchor_uv)
        bad = _segment_survives(i, seg, eaten)
        if bad is not None:
            return bad
    return None


def _segment_survives(index: int, seg_mm: float, eaten_mm: float) -> str | None:
    """THE ONE carrier of the law "how much of the segment must survive the miters"."""
    if seg_mm - eaten_mm >= seg_mm * MIN_SEGMENT_FRACTION:
        return None
    return (f"звено {index}-{index + 1} длиной {seg_mm:.0f} мм: усы соседних "
            f"узлов съедают {eaten_mm:.0f} мм, остаётся меньше "
            f"{MIN_SEGMENT_FRACTION:.0%} — тело порвётся. Следующий ход: "
            f"удлинить звено, смягчить поворот, придвинуть профиль к пути "
            f"(`anchor_uv_mm`) либо уменьшить его")


def feasibility(points: list, radius_mm: float) -> str | None:
    """`None` if the miter builds everywhere; otherwise the REASON in words.

    Two conditions, both derived:

    * the turn at the joint is less than `MAX_TURN_DEG` — as `φ → 180°` the
      trim `R·tan(φ/2)` goes to infinity;
    * after BOTH miters the segment retains at least `MIN_SEGMENT_FRACTION`
      of its length. The trim from each end equals `R·tan(φ/2)`; if it
      consumes the segment whole, the miters intersect and the body tears —
      Revit will then either throw `InvalidOperationException` (documented
      only for 2023-2026!) or build the WRONG thing, and the volume witness
      will accuse us.
    """
    turns = turns_by_node(points)
    for node, phi in turns:
        if phi >= MAX_TURN_DEG:
            seam = " (ШОВ замкнутого пути)" if node == 0 else ""
            return (f"поворот {phi:.1f}° в узле {node}{seam} — предел "
                    f"{MAX_TURN_DEG:g}°; ус при таком повороте срезает звено на "
                    f"{radius_mm * math.tan(math.radians(min(phi, 179.0)) / 2.0):.0f} мм")
    # THE TRIM IS KEYED BY JOINT NUMBER, NOT BY POSITION IN THE LIST. The
    # earlier record bracketed the internal joints with two zeros ("the ends
    # are not trimmed") — and for a CLOSED polyline both of those zeros were
    # lying: its end and its start are ONE joint, the seam, and it trims
    # both of its segments. Here the start of segment `i` is joint `i`, the
    # end is joint `(i+1) % segments`; for an open polyline neither of the
    # two outer joints is in the table, and `.get` honestly returns zero.
    cut_at = {node: radius_mm * math.tan(math.radians(phi) / 2.0)
              for node, phi in turns}
    count = len(points) - 1
    for i in range(count):
        bad = _segment_survives(i, math.dist(points[i], points[i + 1]),
                                cut_at.get(i, 0.0) + cut_at.get((i + 1) % count, 0.0))
        if bad is not None:
            return f"{bad} (изотропная оценка по радиусу {radius_mm:.0f} мм)"
    return None


def is_closed(points: list) -> bool:
    """Whether the polyline is closed — by the measure of THE LANGUAGE
    ITSELF, not its own.

    No threshold is assigned here: the `path3` genus has already declared
    that two points closer than `_MIN_SEGMENT_MM` to each other are ONE
    point (Revit does not build a segment shorter than that). There must not
    be a second measure of "the same point" in the package, so the number is
    asked of whoever declared it, rather than repeated here. This project
    paid for that same duplicate copy on 21.08 with `MIN_EXTENT_MM` — and it
    held back 55 shapes before it was found.

    A closed path matters for more than form: it has an EXTRA joint — the
    seam between the last segment and the first — and the miter at that seam
    introduces the same correction as any other. Six sweeps of the real
    building are closed, and without the seam their volume would have
    diverged from Revit's silently.
    """
    from kir.authoring_validation import _MIN_SEGMENT_MM

    return len(points) > 2 and math.dist(points[0], points[-1]) < _MIN_SEGMENT_MM


def frames_along(points: list, reference: tuple) -> list | None:
    """The `(e1, e2)` frame ON EVERY segment — the field that `fixed_reference`
    guides the profile with. `None` if on even one segment the reference
    direction is collinear with the direction of travel: then there is no
    field at all, and choosing on the author's behalf is not allowed.
    """
    out = []
    for direction in path_directions(points):
        frame = frame_at(direction, reference)
        if frame is None:
            return None
        out.append(frame)
    return out


def miter_correction_mm(points: list, reference: tuple,
                        offset_uv: tuple[float, float]) -> float | None:
    """THE LENGTH CORRECTION that the miters introduce when the centroid is
    NOT on the path.

    Returns `Σ_j ((w̄_j − w̄_{j−1})·n_j)/c_j` from the file header — the
    quantity that remains to be multiplied by the area to get the volume.
    `None` if there is no frame (the reference direction runs along the
    path) or a joint is degenerate.

    `offset_uv` is the CENTROID's offset from the path in profile
    coordinates: `(cx − au, cy − av)`, where `(au, av)` is the profile point
    that rides the path. At zero offset, exactly `0.0` is returned, and this
    is not an approximation: each term vanishes individually.

    🔴 THE ROTATION IS NOT CHOSEN HERE, IT IS ASKED FOR. The function takes
    `reference` and builds the frame field by the same law the emission
    builds it with (`frame_at`). Calling it with a `variety="frame"` path
    would mean substituting OUR OWN rotation for Revit's — so the caller
    must refuse that combination first, and `solid_emit` does refuse it.
    """
    ou, ov = float(offset_uv[0]), float(offset_uv[1])
    if ou == 0.0 and ov == 0.0:
        return 0.0
    frames = frames_along(points, reference)
    if frames is None:
        return None
    dirs = path_directions(points)
    offsets = [tuple(ou * e1[k] + ov * e2[k] for k in range(3))
               for e1, e2 in frames]
    total = 0.0
    for j in path_nodes(points):          # the SEAM of a closed path enters here by itself
        a, b = dirs[j - 1], dirs[j]
        n = tuple(a[k] + b[k] for k in range(3))
        length = math.sqrt(sum(c * c for c in n))
        if length < 1e-9:
            return None                   # an in-place reversal: there is no bisector
        n = tuple(c / length for c in n)
        c = _dot(a, n)
        if abs(c) < 1e-9:
            return None
        delta = _sub(offsets[j], offsets[j - 1])
        total += _dot(delta, n) / c
    return total


def swept_volume_mm3(area_mm2: float, points: list,
                     correction_mm: float = 0.0) -> float:
    """`V = A · (L + miter correction)`. EXACT — the derivation is in the
    file header.

    The correction defaults to zero, and this is not a "safe value" but a
    LAW: with the centroid on the path it is identically zero. The number
    comes from `miter_correction_mm`, and there is no second place where it
    would be computed.
    """
    return area_mm2 * (path_length_mm(points) + correction_mm)


def swept_surface_estimate_mm2(area_mm2: float, perimeter_mm: float,
                               points: list, radius_mm: float) -> float:
    """AN UPPER-BOUND ESTIMATE of surface area — for deriving the tolerance
    only.

    Not a witness and not a claim: the lateral area equals `P·L` plus the
    miter correction `∮ w ds`, and this integral is taken over the BOUNDARY
    and does not vanish at the AREA's centroid. So this is an honest upper
    bound, not a value: to `P·L` a miter margin `P·Σ R·tan(φ/2)` is added.
    Overstating a tolerance is itself dangerous (a witness that cannot
    fail), and the ban on emitting a vacuous solid stands separately against
    exactly that.

    🔴 THE SEAM OF A CLOSED PATH IS NOT IN THIS SUM, AND THIS IS A CHOICE,
    NOT AN OVERSIGHT (04.09.2026). The `Σ` is taken over `turn_angles_deg`,
    i.e. over the INTERNAL joints; a closed polyline also has a miter at the
    seam, and its contribution is not included here. The turn limit now asks
    the seam (`turns_by_node`), but the margin does not, and here is why they
    were kept apart: the missing term makes the bound SMALLER, i.e. the
    tolerance TIGHTER and the witness STRICTER. Adding the seam in would mean
    widening a live tolerance for the sake of a tidy formula — exactly the
    "overstated tolerance" the paragraph above warns against. So the word
    "complete" was removed from the promise, rather than the number bent to
    fit the word: the discrepancy is named and has stopped being silent.
    Adding the seam in is allowed only after a live run showing that the
    tight bound turns red on a valid body.
    """
    turns = turn_angles_deg(points)
    miter = sum(radius_mm * math.tan(math.radians(p) / 2.0) for p in turns)
    return 2.0 * area_mm2 + perimeter_mm * (path_length_mm(points) + 2.0 * miter)


def containment_box_mm(points: list, radius_mm: float) -> tuple:
    """The bounding box the body must FIT INSIDE: the path inflated by `R`.

    A one-sided check, and this is named: an exact bounding box for
    `variety="frame"` does not exist as a property of the input — Revit
    chooses the profile's rotation about the axis, and the bounding box
    depends on that rotation. What the check CATCHES: the wrong place, the
    wrong scale, the wrong profile. What it does NOT catch: a body smaller
    than declared sitting inside the box — that is the volume witness's job.
    """
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs) - radius_mm, min(ys) - radius_mm, min(zs) - radius_mm,
            max(xs) + radius_mm, max(ys) + radius_mm, max(zs) + radius_mm)
