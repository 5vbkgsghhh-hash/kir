"""KIR CURVEOPS — CONTOUR OFFSET AND THICKEN as author constructors.

WHY. In Grasshopper, offset and thicken make up half of facade and
pattern-making constructions: a strip comes from one line, a frame from a
contour, a mesh becomes a lattice. Until this day, the KIR author computed
offsets by hand, and computing them by hand goes wrong exactly where it
matters: at a concave corner, where offset edges must be INTERSECTED, not
shifted one at a time.

═══ WHY A PYTHON CONSTRUCTOR, NOT AN OPERATION AND NOT A CONTOUR SHAPE ═══════════

The fork in the road was real, and it was settled not by taste but by
three measured arguments.

1. **The CONTOUR canon, item 1, verbatim:** «ALL trigonometry happens at
   COMPILE time in python — emitted C# only ever sees three literal points
   per arc». Revit CAN offset on its own (`CurveLoop.CreateViaOffset` 6/6,
   even with its own offset per edge — the overload
   `(CurveLoop, IList<Double>, XYZ)`; `CreateViaThicken` 6/6 in two forms,
   including `(Curve, Double, XYZ)`; all of it checked by compiling on six
   versions, the CS0117 and CS1656 controls tell them apart). But then the
   canonical shape — edges — would be unknown AT COMPILE TIME, and at a
   stroke down would go: the static laws (self-intersection, area, a
   zero-length edge), the bounding-box witness, the shape witness, and the
   reverse pass. The canon itself calls this «Fable-level language change,
   not a patch».

2. **A precedent exists, and it works.** `extrude`, `sweep`, and `region`
   are already value constructors in the author's python. Verified by
   EXECUTION through the sandbox's prod policy: `КОНСТРУКТОРЫ ФОРМЫ:
   ['extrude', 'region']`, 106 names in the author's namespace. There is
   no need to open a second kind of door.

3. **Detachability** (the owner's law of 20.08: KIR must be able to
   detach from and attach to a different BIM program). A constructor in
   pure python knows NOTHING about Revit at all — a different backend gets
   it for free. A registry operation would drag an emitter along for every
   backend.

From this it also follows what is NOT here and never will be: neither
`ops_curveops.py` nor `curveops_emit.py`. The result is an ordinary `poly`
shape, already emitted and witnessed by the existing contour, and a second
emitter would be a second carrier of one law.

═══ THE COST, SAID OUT LOUD ════════════════════════════════════════════════

Revit is smarter than this module in two things, and both are named, not
hushed up:

* **collapse.** On an inward offset, a real offset drops edges that got
  "eaten" and changes the vertex count. There is NONE of that here: an
  eaten edge is caught as degeneracy and becomes a REFUSAL with the
  edge's number. A refusal is more honest than a silent drop — the author
  learns that their offset is larger than the shape allows, instead of
  silently getting a different figure;
* **the arc.** An arc's offset is exactly derivable (the same center,
  radius r ± d), but the JOINT of an offset arc with an offset line
  requires intersecting a line with a circle and choosing a root —
  separate work with its own degeneracies. Here an arc is a NAMED REFUSAL
  with a named next move, not a silent replacement of the arc by a chord.
  A chord and an arc share the same endpoints: the substitution would be
  invisible from the outside and would change the area.

═══ LAWS OF THE SHAPE (all static, all a refusal, not one silent fix) ══

A silent correction of the input has already cost this house 96.77% of
groups, so there is neither discarding of degenerate edges here, nor
merging of vertices, nor clamping at a limit:

  1. input shape: a list of points `[[x,y], ...]` OR the shape
     `{"shape": "poly", "points_mm": [...]}` — and nothing else;
  2. points: a ring needs 3..MAX_RING_POINTS, an open polyline needs
     2..MAX_RING_POINTS — a ring needs three because two points cannot
     bound an area, while a polyline is fine with two, because its area
     comes from its WIDTH, not from the path. Every coordinate is finite
     and within the working space;
  3. the offset is finite and at least `_MIN_DISTANCE_MM` in absolute
     value — Revit cannot tell anything smaller from zero (the same
     quantity and the same reason as `contour._EDGE_TOL`:
     ShortCurveTolerance, statically);
  4. an arc in the input — a refusal (see "the cost" above);
  5. a zero-length edge in the input — a refusal, not a skip;
  6. an offset edge collapsed (its ends met) — a refusal WITH THE edge's
     NUMBER;
  7. neighboring edges point the same way — the vertex is carried along
     the normal rather than found by intersection: parallel lines do not
     intersect, and "almost parallel" ones would put the vertex beyond the
     horizon;
  8. the result turned inside out — a refusal, and it is caught by the
     MONOTONICITY OF THE AREA (inward must decrease it, outward must
     increase it), NOT by the winding sign.
     🔴 The winding sign does not work here, and this is measured: a
     5000×4000 square, offset inward by 5000, keeps its orientation — both
     sides flipped sign, meaning the winding reflected TWICE — and the
     first edition missed it, returning 30.000 m² instead of the original
     20.000. The check was green exactly where it had to be red;
  9. the result self-intersects — a refusal by the SAME detector the
     contour uses to catch it, not by a second one of its own.

WHAT THE RESULT DOES NOT HAVE. This is a SHAPE, not an element: no type,
no material, no specification. It is good for exactly one thing — being
fed into a contour op (`create_floor_by_contour`, `create_ceiling`,
`create_filled_region`, …), which is what gives the element its meaning.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kir.diag import (
    Diagnostic, KirRefusal, TYPE_BAD_TYPE, TYPE_BOUNDS, TYPE_GEOM_RELATION,
)
from kir.registry_base import COORD_LIMIT_MM
from kir.emit_utils import is_finite_number
from kir.geom import MAX_RING_POINTS, MIN_RING_POINTS, _seg_intersect

#: A displacement smaller than this Revit cannot tell from zero. NOT assigned: the exact
#: same value and the same reason as `contour._EDGE_TOL` — ShortCurveTolerance,
#: verified statically. A second number here would split two thresholds
#: that are required to match.
_MIN_DISTANCE_MM = 1.0

#: A coordinate outside Revit's working space. Taken from `mesh._COORD_MAX_MM`
#: BY IMPORT, if it were not private; here it is repeated as a value with
#: the source named explicitly, because they must not silently diverge.
#: Source: Revit declares operation within 20 miles (32 186 880 mm) of the
#: internal origin, 10 km is taken with margin INSIDE that limit.
#: 🔴 THE HOUSE, NOT A COPY. Measurement 25.08.2026: this value had THREE carriers
#: and TWO values — 16 000 000 in `registry_base` (and in `authoring_validation`,
#: which has read the house since the same day) against 10 000 000 here and in its neighbor.
#: A point at 12 000 000 mm was legal at the wall and illegal here.
#:
#: Both smaller numbers are derived from "Revit declares operation within 20 miles",
#: the house — from "operating span ~16 km". NEITHER IS MEASURED, so the dispute is settled
#: by what does not break what works: the house is WIDER, and no program
#: currently accepted will become rejected. When Revit's limit is MEASURED,
#: ONE number will change.
#:
#: The earlier comment here honestly said: "repeated as a value with the source
#: named explicitly, because they must not silently diverge." They diverged.
_COORD_MAX_MM = COORD_LIMIT_MM

#: The sine of the angle between adjacent edges below which they are considered
#: co-directional and the vertex is collapsed along the normal, rather than found by intersection.
#: DERIVED, not tuned: at |sin| = s the intersection stands off from the source
#: vertex by ~d/s, and at s = 1e-6 a 1 mm offset carries the vertex a kilometer away
#: — that is, past the bound that law 2 catches. The threshold is set where the answer
#: stops being representable, not where it "looks small".
_PARALLEL_SIN_EPS = 1e-6


def _refuse(code: str, field: str, message: str, got: Any = None) -> None:
    raise KirRefusal([Diagnostic(code=code, op_id=None, field_name=field,
                                 message_ru=message, got=got)])


def _points_of(contour: Any, field: str, *, closed: bool = True) -> list:
    """Author's contour -> list of points. TWO forms, both named.

    There is deliberately no third: a form that cannot be written cannot
    be confused either (the same rule as the slot selector in `dsl.py`).
    """
    raw = contour
    if isinstance(contour, dict):
        unknown = set(contour) - {"shape", "points_mm", "arcs", "splines"}
        if unknown:
            _refuse(TYPE_BAD_TYPE, field,
                    f"{field}: неизвестные поля формы {sorted(unknown)} — "
                    f"смещается форма `poly`, а не произвольный словарь",
                    got=sorted(unknown))
        if contour.get("shape") != "poly":
            _refuse(TYPE_BAD_TYPE, field,
                    f"{field}: смещается только форма `poly` (список точек). "
                    f"У `rect` и `l` смещение выражается их собственными "
                    f"размерами и origin — считать его тут значило бы завести "
                    f"второй способ сказать то же самое",
                    got=contour.get("shape"))
        # 🔴 ARC AND SPLINE — REFUSAL, NOT A SILENT CHORD SUBSTITUTION. A chord and an arc
        # have THE SAME endpoints: the substitution would be invisible from outside and
        # would change the area. See "the cost" in the header.
        for kind, ru in (("arcs", "дуги"), ("splines", "сплайны")):
            if contour.get(kind):
                _refuse(TYPE_GEOM_RELATION, f"{field}.{kind}",
                        f"{field}: у контура есть {ru}, а этот конструктор "
                        f"смещает только прямые рёбра. Смещение кривой "
                        f"выводимо точно (тот же центр, радиус r±d), но стык "
                        f"смещённой кривой с прямой — отдельная работа, и до "
                        f"неё замена кривой хордой была бы НЕВИДИМОЙ снаружи. "
                        f"Следующий ход: сместить многоугольную часть, либо "
                        f"задать смещённый контур точками",
                        got=len(contour[kind]))
        raw = contour.get("points_mm")
    if not isinstance(raw, list):
        _refuse(TYPE_BAD_TYPE, field,
                f"{field}: контур — список точек [[x,y], …] либо форма "
                f"{{'shape': 'poly', 'points_mm': [...]}}", got=type(raw).__name__)
    # 🔴 A RING AND A POLYLINE HAVE DIFFERENT MINIMUMS, AND MERGING THEM WAS A DEFECT.
    # The first edition always required three points — and refused a strip FROM
    # A SEGMENT, i.e. exactly the case `thicken` was built for
    # ("a strip from a line", half of the facade layouts in GH). A ring needs three
    # points, because two cannot bound an area; an open polyline needs two,
    # because its area comes from WIDTH, not the path.
    low = MIN_RING_POINTS if closed else 2
    if not (low <= len(raw) <= MAX_RING_POINTS):
        _refuse(TYPE_BOUNDS, field,
                f"{field}: точек {len(raw)} — нужно от {low} до "
                f"{MAX_RING_POINTS}", got=len(raw))
    pts: list = []
    for i, p in enumerate(raw):
        if not isinstance(p, (list, tuple)) or len(p) != 2 \
                or not all(is_finite_number(c) for c in p):
            _refuse(TYPE_BAD_TYPE, f"{field}[{i}]",
                    f"{field}: точка — [x, y] из двух конечных чисел в мм",
                    got=p)
        if any(abs(float(c)) > _COORD_MAX_MM for c in p):
            _refuse(TYPE_BOUNDS, f"{field}[{i}]",
                    f"{field}: координата вне ±{_COORD_MAX_MM:.0f} мм — это "
                    f"вне рабочего пространства Revit, а не «далеко»", got=p)
        pts.append([float(p[0]), float(p[1])])
    # Closure is normalized by THE SAME law as in contour: a repeated
    # last point is removed rather than counted as a separate edge.
    # For a POLYLINE this is not done: a path that returns to its start is a legal
    # closed layout, and removing its last point would mean building
    # the WRONG strip, not the one that was sent.
    if closed and len(pts) >= MIN_RING_POINTS + 1 \
            and _dist(pts[0], pts[-1]) < _MIN_DISTANCE_MM:
        pts = pts[:-1]
    if len(pts) < low:
        _refuse(TYPE_BOUNDS, field,
                f"{field}: после нормализации замыкания осталось {len(pts)} "
                f"точек — нужно минимум {low}", got=len(pts))
    return pts


def _dist(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _shoelace(poly: list) -> float:
    s = 0.0
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def _check_distance(distance_mm: Any, field: str) -> float:
    if not is_finite_number(distance_mm):
        _refuse(TYPE_BAD_TYPE, field,
                f"{field}: смещение — конечное число в мм", got=distance_mm)
    d = float(distance_mm)
    if abs(d) < _MIN_DISTANCE_MM:
        _refuse(TYPE_BOUNDS, field,
                f"{field}: смещение {d:g} мм по модулю меньше "
                f"{_MIN_DISTANCE_MM:g} мм — Revit не отличит его от нуля "
                f"(ShortCurveTolerance). Нулевое смещение — это исходный "
                f"контур, и его не надо строить заново", got=d)
    if abs(d) > _COORD_MAX_MM:
        _refuse(TYPE_BOUNDS, field,
                f"{field}: смещение вне ±{_COORD_MAX_MM:.0f} мм", got=d)
    return d


def _self_intersects(poly: list) -> bool:
    """THE SAME detector that catches self-intersection for a contour.

    A second one of its own would be a second carrier of one law: they would
    silently drift apart, and a result legal here would be rejected there.
    """
    m = len(poly)
    for a in range(m):
        for b in range(a + 2, m):
            if a == 0 and b == m - 1:
                continue
            if _seg_intersect(poly[a], poly[(a + 1) % m],
                              poly[b], poly[(b + 1) % m]):
                return True
    return False


def _offset_line(a: list, b: list, d: float) -> tuple:
    """The offset LINE of edge a->b: a point on it, the direction, the normal.

    The normal is to the RIGHT of the direction. Which way it points "outward" is
    decided by the caller via the sign of `d`: for a ring it's the winding orientation, for a strip — the side.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    return ((a[0] + uy * d, a[1] - ux * d), (ux, uy), (uy, -ux))


def _join(prev_line: tuple, cur_line: tuple, vertex: list, d: float,
          field: str, i: int) -> list:
    """The vertex of an offset polyline — the INTERSECTION of two offset lines.

    🔴 ONE CARRIER OF THE JOINT LAW FOR THE WHOLE MODULE (audit finding F-290,
    29.08.2026). There used to be two: `offset` intersected lines, `thicken`
    moved the vertex along the normal of the CHORD prev->next. The chord is not parallel
    to either of the two edges, so the vertex stood off from each of them by
    `d*cos(θ/2)`, not by `d`: at a right angle, 35.355 mm instead of 50, meaning
    a strip "100 wide" was 70.71 wide at every break. Neither the area, nor the
    vertex count, nor the self-intersection detector sees this — the shape
    is plausible, and no law in force caught it.

    This module's header names exactly this mistake the AUTHOR's mistake ("at a concave
    angle the offset edges must be INTERSECTED, not shifted individually") — and
    `thicken` was doing exactly that.
    """
    p_prev, u_prev, _ = prev_line
    p_cur, u_cur, n_cur = cur_line
    cross = u_prev[0] * u_cur[1] - u_prev[1] * u_cur[0]
    if abs(cross) < _PARALLEL_SIN_EPS:
        # Law 7 distinguishes TWO cases, not one: co-directional edges
        # (θ=0, the joint is an ordinary point on a line) and REVERSED ones (θ=π, the path
        # doubles back on itself, and the joint has no side at all). The earlier
        # `thicken` caught the reversal only via a SHORT CHORD, i.e. only for
        # equal arms; here it is caught by the directions of the segments.
        if u_prev[0] * u_cur[0] + u_prev[1] * u_cur[1] < 0.0:
            _refuse(TYPE_GEOM_RELATION, field,
                    f"{field}: рёбра вокруг точки {i} развёрнуты друг на "
                    f"друга — путь возвращается по себе, и у смещения там нет "
                    f"стороны. Следующий ход: убрать возврат либо разбить путь "
                    f"на два", got=i)
        # Co-directional: the intersection would run off to the horizon (`_PARALLEL_SIN_EPS`).
        return [vertex[0] + n_cur[0] * d, vertex[1] + n_cur[1] * d]
    wx, wy = p_cur[0] - p_prev[0], p_cur[1] - p_prev[1]
    t = (wx * u_cur[1] - wy * u_cur[0]) / cross
    return [p_prev[0] + u_prev[0] * t, p_prev[1] + u_prev[1] * t]


def offset(contour: Any, distance_mm: Any) -> dict:
    """Offset contour: OUTWARD for positive, INWARD for negative.

    "Outward" is determined from the contour's own winding, not from a guess: the sign
    of the area (shoelace) gives the orientation, and the outward normal is computed from it.
    A contour recorded clockwise offsets outward by the same
    positive number as one recorded counterclockwise — otherwise the author would have to
    remember which way they listed the points.

    Returns a `poly` shape, ready to feed into any contour op.
    """
    pts = _points_of(contour, "contour")
    d = _check_distance(distance_mm, "distance_mm")
    n = len(pts)

    for i in range(n):
        if _dist(pts[i], pts[(i + 1) % n]) < _MIN_DISTANCE_MM:
            _refuse(TYPE_BOUNDS, "contour",
                    f"contour: ребро {i} короче {_MIN_DISTANCE_MM:g} мм — "
                    f"смещать нечего, и Revit отверг бы его как нулевое",
                    got=i)

    # 🔴 LAW 10: A RING MUST BE A RING, NOT A SLIVER (audit finding
    # F-291, 29.08.2026). The orientation below is read from the SIGN of the area, and a
    # degenerate ring has no sign: `_shoelace` returns 0.0, the `else` branch
    # fires, and "clockwise" is silently assigned to a figure whose winding
    # does not exist. Law 8 then goes blind too: at `area_src == 0` any
    # positive result is greater than zero, meaning "it grew outward". The blade
    # [[0,0],[10000,0],[5000,0.1]] with an area of 0.0005 m² thus became a `poly`
    # shape with an area of 2002 m² and a vertex at -10 000 000 mm — a growth of four
    # million times across all nine laws.
    #
    # THICKNESS, not area: `area/(perimeter/2)` for a convex ring is the radius
    # of the inscribed circle, and the requirement on it is exactly the same as for an edge —
    # `_MIN_DISTANCE_MM`. The threshold "area > 0" is unfit by measurement: the blade's
    # area of 500 mm² is strictly positive. No second NUMBER is introduced here:
    # the module has already said out loud why it has one length threshold, and has already
    # been caught with diverged copies of one value (`_COORD_MAX_MM`).
    area_src = abs(_shoelace(pts))
    perimeter = sum(_dist(pts[i], pts[(i + 1) % n]) for i in range(n))
    if area_src * 2.0 < _MIN_DISTANCE_MM * perimeter:
        _refuse(TYPE_GEOM_RELATION, "contour",
                f"contour: площадь кольца {area_src / 1e6:.6f} м² при периметре "
                f"{perimeter:.1f} мм — оно тоньше {_MIN_DISTANCE_MM:g} мм, то "
                f"есть это черта, а не контур. У черты нет ни обхода, ни "
                f"«наружу», и смещение вернуло бы форму, которой во входе не "
                f"было. Следующий ход: замкнуть контур настоящей площадью либо "
                f"взять `thicken`, который из пути и делает полосу",
                got=area_src)

    # Self-intersection of the INPUT is caught by THE SAME detector as the output's. It used to
    # look only at the result, and a figure-eight ring slipped through: its
    # area fractions cancel each other out, so law 8 too was decided by the difference of two
    # wrongs. A second detector of its own would be a second carrier of one law —
    # the argument is written in the docstring of `_self_intersects` itself.
    if _self_intersects(pts):
        _refuse(TYPE_GEOM_RELATION, "contour",
                f"contour: исходное кольцо самопересекается — у него нет "
                f"«внутри» и «снаружи», а знак площади считает пересечённые "
                f"доли со взаимным гашением. Это тот же закон, которым контур "
                f"отвергает самопересечение на разборе. Следующий ход: разбить "
                f"на непересекающиеся кольца", got=n)

    # Orientation is decided by the SIGN OF THE AREA, not by the order in which the author
    # entered the points. sign > 0 — counterclockwise winding.
    sign = 1.0 if _shoelace(pts) > 0 else -1.0

    # The offset LINE of each edge and the joint — ONE carrier per module
    # (F-290). Until `_join` is called by BOTH, there are still two carriers
    # of the joint law, and they can diverge again.
    lines = [_offset_line(pts[i], pts[(i + 1) % n], d * sign) for i in range(n)]
    out: list = [_join(lines[i - 1], lines[i], pts[i], d * sign, "contour", i)
                 for i in range(n)]

    for i in range(n):
        if _dist(out[i], out[(i + 1) % n]) < _MIN_DISTANCE_MM:
            _refuse(TYPE_GEOM_RELATION, "distance_mm",
                    f"смещение {d:g} мм схлопнуло ребро {i}: его концы сошлись "
                    f"ближе {_MIN_DISTANCE_MM:g} мм. Настоящий offset выбросил "
                    f"бы это ребро и отдал фигуру С ДРУГИМ ЧИСЛОМ ВЕРШИН — "
                    f"здесь это отказ, потому что молчаливая подмена формы "
                    f"неотличима снаружи от успеха. Следующий ход: смещение "
                    f"меньше по модулю", got=i)

    # 🔴 THE SIGN OF THE AREA DOES NOT CATCH INVERSION, AND THIS IS A MEASUREMENT, NOT CAUTION.
    # The first edition checked `_shoelace(out) * sign <= 0` — and a square
    # 5000×4000, offset inward by 5000, PASSED, yielding 30.000 m² instead of
    # the original 20.000: both sides changed sign, meaning the winding flipped
    # TWICE and the orientation survived. The check was green exactly where
    # it was supposed to go red.
    # The real law is not about the sign but about MONOTONICITY: an inward offset must
    # decrease the area, an outward one — increase it. It catches inversion and any
    # other outcome in which the figure stopped being an offset of the original.
    # `area_src` is computed above, in law 10: a second computation of the same
    # value would be a second carrier.
    area_out = abs(_shoelace(out))
    if (d < 0 and area_out >= area_src) or (d > 0 and area_out <= area_src):
        _refuse(TYPE_GEOM_RELATION, "distance_mm",
                f"смещение {d:g} мм не уменьшило площадь внутрь (или не "
                f"увеличило наружу): было {area_src / 1e6:.3f} м², стало "
                f"{area_out / 1e6:.3f} м². Контур вывернулся наизнанку — "
                f"съедено больше, чем в нём было. Следующий ход: смещение "
                f"меньше по модулю", got=d)

    if _self_intersects(out):
        _refuse(TYPE_GEOM_RELATION, "distance_mm",
                f"смещённый контур самопересекается: при {d:g} мм рёбра зашли "
                f"друг за друга. Это тот же закон, которым контур отвергает "
                f"самопересечение на разборе, — здесь он назван РАНЬШЕ, до "
                f"эмиссии", got=d)

    return {"shape": "poly", "points_mm": out}


def thicken(path: Any, width_mm: Any) -> dict:
    """A strip AROUND an open polyline: from a line — a contour of width `width_mm`.

    Exactly what Grasshopper uses to make mullions, layouts, and frames: the input
    has no area, the output does.

    The width is SPLIT IN HALF between both sides, not laid out on one.
    This is not a matter of taste: a strip laid out on one side would depend on
    the order in which the author entered the points — the same trap that the
    orientation in :func:`offset` removes.

    The strip's ends are STRAIGHT (butt joints), neither rounded nor projecting. This is named
    because Revit's `CreateViaThicken` makes the same choice silently, and
    they differ by half the width at each end.
    """
    pts = _points_of(path, "path", closed=False)
    w = _check_distance(width_mm, "width_mm")
    if w <= 0.0:
        _refuse(TYPE_BOUNDS, "width_mm",
                f"width_mm: ширина полосы {w:g} мм — полоса не бывает "
                f"отрицательной ширины. Сторону выбирает не знак, а порядок "
                f"точек", got=w)
    half = w / 2.0
    n = len(pts)

    for i in range(n - 1):
        if _dist(pts[i], pts[i + 1]) < _MIN_DISTANCE_MM:
            _refuse(TYPE_BOUNDS, "path",
                    f"path: звено {i} короче {_MIN_DISTANCE_MM:g} мм — "
                    f"утолщать нечего", got=i)

    def _side(sgn: float) -> list:
        # 🔴 THE JOINT IS AN INTERSECTION, NOT A COLLAPSE ALONG THE CHORD'S NORMAL (F-290). The earlier
        # edition took, at the interior point, the normal of the chord prev->next and
        # pushed the vertex out by `half`. The chord is not parallel to either of the two
        # segments, so the vertex stood off from EACH of them by
        # `half*cos(θ/2)`: at a right angle, 35.355 mm instead of 50, and a strip
        # "100 wide" was 70.71 wide at every break. The joint law is
        # now ONE per module (`_join`) — the same one `offset` uses to build
        # a concave angle.
        #
        # The strip's ends remain STRAIGHT (the normal of their own end segment) — this
        # is already named in `thicken`'s docstring and does not change.
        lines = [_offset_line(pts[i], pts[i + 1], half * sgn)
                 for i in range(n - 1)]
        side: list = [[pts[0][0] + lines[0][2][0] * half * sgn,
                       pts[0][1] + lines[0][2][1] * half * sgn]]
        for i in range(1, n - 1):
            side.append(_join(lines[i - 1], lines[i], pts[i],
                              half * sgn, "path", i))
        side.append([pts[n - 1][0] + lines[n - 2][2][0] * half * sgn,
                     pts[n - 1][1] + lines[n - 2][2][1] * half * sgn])
        return side

    left = _side(1.0)
    right = _side(-1.0)
    ring = left + list(reversed(right))

    if _self_intersects(ring):
        _refuse(TYPE_GEOM_RELATION, "width_mm",
                f"полоса шириной {w:g} мм самопересекается: на повороте "
                f"внутренняя сторона зашла за себя. Настоящий thicken срезал "
                f"бы угол и отдал фигуру ДРУГОЙ формы — здесь это отказ. "
                f"Следующий ход: уже полоса либо плавнее ломаная", got=w)

    if abs(_shoelace(ring)) < 1.0:
        _refuse(TYPE_GEOM_RELATION, "width_mm",
                f"полоса вырождена: площадь почти ноль", got=w)

    return {"shape": "poly", "points_mm": ring}
