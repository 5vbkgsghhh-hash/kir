"""KIR SURFACE — a SMOOTH NURBS surface as a language value (wave of 20.08.2026).

WHY. Until this day the language expressed free form with exactly one kind
— MESH (`mesh.py`, wave of 29.07): triangles, i.e. FACETS. An armchair, a
pouf, a sculptural volume can be said with a mesh; a SMOOTH double-curvature
shell cannot be said with it at all, no matter how many triangles you lay
down. This is a wall exactly where the owner set the bar: «in Revit you can
do complex geometric things almost like in Grasshopper and Rhino, and I
want to achieve that goal».

MEASURED BY COMPILATION ON 20.08.2026, six versions, the controls
distinguish (CS0117 on an invented member, CS1501 on a foreign arity):

    BRepBuilder + AddFace/AddEdge/AddLoop/AddCoEdge/FinishLoop/FinishFace/Finish   6/6
    BRepBuilderSurfaceGeometry.CreateNURBSSurface                                  6/6
    NurbSpline.CreateCurve(degree, knots, points[, weights])                       6/6
    ExportUtils.GetNurbsSurfaceDataForSurface  (READ BACK)                         6/6
    full assembly -> Solid -> DirectShape                                          6/6

═══ DECISION ONE: THE INPUT IS CONTROL POINTS, NOT INTERPOLATION ═══════════

The temptation ran the opposite way, and it is worth naming, because for a
CURVE in the contour the same choice was resolved DIFFERENTLY (there,
`HermiteSpline.Create` — interpolation through points, "draw a curve
through these"). Here three arguments outweighed it:

* **THE READ-BACK PATH READS EXACTLY CONTROL POINTS.** `geom_extract.__gxNurbsSurface`
  returns `degree_u/degree_v/knots_u/knots_v/control_points_mm/weights/
  reverse_orientation` — and nothing else. Had the language taken
  interpolation points, the round trip would not close BY CONSTRUCTION: we
  would say one thing going forward and read another coming back, and there
  would be nothing to compare;
* **THE WITNESS EXISTS ONLY IN THIS FORM.** `GetNurbsSurfaceDataForSurface`
  reads off the BUILT face exactly the quantities the author declared. This
  is a reading of the result, and it can fail: Revit is free to
  reparametrize the surface, insert knots, raise the degree. Had we taken
  interpolation, we would have had to compute the control points OURSELVES,
  and then OUR OWN approximation would stand between the author and Revit,
  with the witness comparing ours against ours (form 8);
* **the author's convenience is solved by a CONSTRUCTOR, not by the
  value's kind.** The mesh has already been through the same fork: the
  value's kind is vertices and triangles, and `mesh.extrude(contour,
  height)` is a separate function that computes them. For the surface, the
  constructor's place for "draw through a grid of points" is likewise a
  separate matter, and its absence today is named below, not passed over
  in silence.

═══ DECISION TWO: WHAT THE RESULT DOES NOT HAVE ════════════════════════════

The same as for the mesh, and for the same reason: `DirectShape` is
GEOMETRY WITHOUT BIM MEANING. No type, no layer parameters, it will not
land in a schedule as a construction, a person will not edit it by hand.
This is a device of Revit, not an unfinished piece of work. The only honest
behavior is to say this about the operation itself everywhere it is
visible, rather than stay silent and let the result be called a "building".

═══ LAWS OF THE SHAPE ═══════════════════════════════════════════════════

All static, all a typed refusal, not a single silent fix-up of the input.
The order is exactly the same as in `mesh.py`, and for the same reason: a
silent fix-up of the input has already cost this house 96.77 % of the
groups.

  1. the value's shape: exactly the declared keys, anything extra is a
     refusal;
  2. degrees 1..MAX_DEGREE in each direction;
  3. control points per direction no fewer than degree+1 — otherwise the
     basis is not defined at all;
  4. len(control_points_mm) == count_u * count_v — the grid is rectangular;
  5. a point is [x,y,z] made of finite numbers, coordinate within
     ±COORD_MAX_MM;
  6. len(knots_u) == count_u + degree_u + 1 (and likewise for v) — a NURBS
     identity, not a convention;
  7. knots are NON-DECREASING;
  8. knots are CLAMPED: the first degree+1 are equal to one another and the
     last degree+1 are equal to one another. The law is taken VERBATIM from
     the read-back path (`geom_extract.__gxClampedKnots`), which on an
     unclamped surface refuses with «NURBS surface is periodic, unclamped,
     or incomplete». The two ends of one wire are bound to demand the same
     thing;
  9. weights are optional (absence = a NON-rational surface, not "unit
     weights by default"); if present — the length equals the number of
     points and each is STRICTLY positive (the same law as the read-back
     path);
 10. the grid is not degenerate: its bounding box must be TWO-DIMENSIONAL.
     A surface collapsed into a curve or a point is not a surface, and BRep
     will not assemble it;
 11. the grid's four CORNERS are pairwise distinct. The boundary is built
     from exact isoparametric curves, and a matching corner would give a
     zero-length edge — ShortCurveTolerance at execution time instead of a
     refusal at parsing.

⚠️ WHAT THESE LAWS DO NOT CATCH is named so this does not read as
completeness: they do not see the surface self-intersecting. For the mesh
the same class is likewise open; the last word belongs to Revit, and its
refusal now reaches the receipt (`IsResultAvailable`/`RemovedSomeFaces` are
read and travel into the witness).

═══ POINT ORDER — A NAMED ASSUMPTION, NOT KNOWLEDGE ═══════════════════════

🔴 We accept `control_points_mm` in **u-major** order: index
``iu * count_v + iv``. Autodesk does NOT name the order in the
documentation available to us, and compilation cannot answer this question
by construction. This is an ASSUMPTION, and it is checkable: the witness
reads the control points back, and a mixed-up order will pull the preimage
apart from the image — that is, the very first live run will answer with
RED, not with silence. This is recorded here so that red is read as the
answer to a question, not as a breakage.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS, TYPE_GEOM_RELATION
from kir.emit_utils import is_finite_number
# ONE SOURCE FOR THE COORDINATE LIMIT. The mesh and the surface live in the
# same Revit and run into the same 20-mile boundary; two numbers that are
# bound to match drift apart silently — that is a named defect of the tree.
from kir.mesh import _COORD_MAX_MM as COORD_MAX_MM

#: The surface is degenerate: the grid's bounding box is not two-dimensional.
SURFACE_DEGENERATE = "KIR-S004"
# 🔴 CODE S004, NOT S001, AND THIS IS THE SAME COLLISION AS WITH E009
# (21.08.2026). `KIR-S001` carries `PASSPORT_NODE_NOT_FOUND`
# (`decompile/passport.py`, 18.07) — "the passport node is missing", a
# completely different fix. A model given one code for two outcomes cannot
# know which fix to make; that is exactly what the
# `test_one_answer_per_question` law guards against. The newcomer of the
# 20.08 wave moves, the senior code stays.
#: The knot vector is not clamped or is not monotonic.
SURFACE_KNOTS = "KIR-S002"
#: The grid's corners coincide — a boundary edge is degenerate.
SURFACE_CORNER = "KIR-S003"

#: The largest degree per direction.
#: ⚠️ ASSIGNED, not measured, and flagged just as honestly as `_COORD_MAX_MM`
#: in `mesh.py`. Reason: a degree above seven practically never occurs in
#: CAD (Rhino's limit is also 11, and reaching it is artificial), and every
#: extra degree requires one more control point per direction, i.e. it
#: makes checks more expensive while expressing nothing. It is allowed to
#: be lowered on a live run and forbidden to be raised silently — the same
#: formula as the mesh's limit.
MAX_DEGREE = 7

#: The largest number of control points in the grid.
#: ⚠️ ASSIGNED after the model of the mesh's `MAX_TRIANGLES`, with a
#: caveat: the Roslyn linearity measurement was taken on the MESH, not on
#: the surface, and carrying it over here as measured would be a number
#: about the wrong subject (the shape of "an instrument over part of the
#: range"). How long Revit takes to assemble a BRep from a grid of this
#: size INSIDE the transaction cannot be measured offline at all.
MAX_CONTROL_POINTS = 4096

#: The grid's bounding box must have at least two dimensions NO SMALLER
#: than this. The same value and the same reason as `_MIN_EDGE_MM` of the
#: mesh and `_EDGE_TOL` of the contour: Revit's ShortCurveTolerance, taken
#: statically.
MIN_EXTENT_MM = 1.0


def _bad(diags: list, code: str, oid, field: str, message: str,
         got: Any = None) -> None:
    diags.append(Diagnostic(code=code, op_id=oid, field_name=field, got=got,
                            message_ru=message))


def _knots_ok(knots: list, degree: int, count: int) -> Optional[str]:
    """The reason the knot vector is illegal, or None.

    Returns TEXT, not a boolean: three different ailments have three
    different remedies (append knots, sort them, weld the ends), and one
    code for three outcomes would leave the reader to interpret it alone.
    """
    need = count + degree + 1
    if len(knots) != need:
        return (f"узлов {len(knots)}, а тождество NURBS требует "
                f"count + degree + 1 = {count} + {degree} + 1 = {need}")
    for i in range(len(knots) - 1):
        if knots[i] > knots[i + 1]:
            return f"узлы не неубывают: knots[{i}]={knots[i]} > knots[{i+1}]={knots[i+1]}"
    head = knots[:degree + 1]
    tail = knots[-(degree + 1):]
    if len(set(head)) != 1:
        return (f"первые {degree + 1} узлов обязаны совпадать (clamped), "
                f"пришло {head}")
    if len(set(tail)) != 1:
        return (f"последние {degree + 1} узлов обязаны совпадать (clamped), "
                f"пришло {tail}")
    if head[0] == tail[0]:
        return "узловой вектор вырожден: начало равно концу"
    return None


def surface_bbox(points: list) -> tuple:
    """(xmin, ymin, zmin, xmax, ymax, zmax) of the grid, in mm."""
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def line_deviation_mm(points: list) -> float:
    """The largest distance of a grid point FROM THE LINE on which its two
    most widely separated points lie, mm. Zero means: all points are
    COLLINEAR.

    WHY A SECOND MEASURE OF DEGENERACY WHEN THERE IS A BOUNDING BOX. The
    bounding box answers the question "is the grid two-dimensional" ONLY IN
    WORLD AXES, and on a diagonal it lies. Measured 04.09.2026, a 2×2 grid
    of points `t·(1000, 1000, 1000)`:

        bounding box     3000 × 3000 × 3000 mm — the second span, 3000, ≫ 1 mm
        `validate_surface`  ACCEPTED, diags 0
        yet there IS NO surface: all four points lie on one line

    The line is taken through the two most widely separated points, not by
    fitting: fitting would introduce its own approximation exactly where a
    "yes or no" answer is needed. For a truly collinear set this line is
    THE line EXACTLY, and for a non-coplanar one the deviation is only
    UNDERSTATED — so a refusal from this check is always true, and what is
    not found stays not found (the same argument that
    `contour._shape_within_world_extent` lives by).
    """
    p0 = points[0]
    far = max(points, key=lambda p: (p[0] - p0[0]) ** 2 + (p[1] - p0[1]) ** 2
              + (p[2] - p0[2]) ** 2)
    d = [far[k] - p0[k] for k in range(3)]
    span = math.sqrt(sum(c * c for c in d))
    if span == 0.0:
        return 0.0                        # all points at one — there is no distance
    d = [c / span for c in d]
    worst = 0.0
    for p in points:
        w = [p[k] - p0[k] for k in range(3)]
        t = sum(w[k] * d[k] for k in range(3))
        perp = [w[k] - t * d[k] for k in range(3)]
        worst = max(worst, math.sqrt(sum(c * c for c in perp)))
    return worst


def surface_corners(points: list, count_u: int, count_v: int) -> list:
    """The grid's four corners in boundary-traversal order (u-major)."""
    return [points[0],
            points[count_v - 1],
            points[(count_u - 1) * count_v + count_v - 1],
            points[(count_u - 1) * count_v]]


def row_u(points: list, iu: int, count_v: int) -> list:
    """A row of control points at fixed u — the boundary along v."""
    return [points[iu * count_v + iv] for iv in range(count_v)]


def col_v(points: list, iv: int, count_u: int, count_v: int) -> list:
    """A column of control points at fixed v — the boundary along u."""
    return [points[iu * count_v + iv] for iu in range(count_u)]


_FIELDS_REQUIRED = ("degree_u", "degree_v", "count_u", "count_v",
                    "knots_u", "knots_v", "control_points_mm")
_FIELDS_OPTIONAL = ("weights",)


def validate_surface(surface: Any, oid, field: str,
                     diags: list) -> Optional[dict]:
    """A surface value -> a normalized dict, or None plus a refusal.

    Fixes nothing and drops nothing: the input is either accepted whole, or
    a refusal is named. See "LAWS OF THE SHAPE" in the header.
    """
    if not isinstance(surface, dict):
        _bad(diags, TYPE_BAD_TYPE, oid, field,
             f"{field}: поверхность — словарь "
             f"{{{', '.join(_FIELDS_REQUIRED)}[, weights]}}", got=surface)
        return None
    unknown = set(surface) - set(_FIELDS_REQUIRED) - set(_FIELDS_OPTIONAL)
    missing = [f for f in _FIELDS_REQUIRED if f not in surface]
    if unknown or missing:
        _bad(diags, TYPE_BAD_TYPE, oid, field,
             f"{field}: поверхность знает только "
             f"{', '.join(_FIELDS_REQUIRED)} и необязательный weights"
             + (f"; лишнее: {sorted(unknown)}" if unknown else "")
             + (f"; не хватает: {missing}" if missing else ""),
             got=sorted(surface))
        return None

    degrees = {}
    for axis in ("u", "v"):
        d = surface[f"degree_{axis}"]
        if isinstance(d, bool) or not isinstance(d, int) \
                or not (1 <= d <= MAX_DEGREE):
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.degree_{axis}",
                 f"{field}: degree_{axis} — целое 1..{MAX_DEGREE} "
                 f"(предел НАЗНАЧЕН, см. шапку surface.py)", got=d)
            return None
        degrees[axis] = d

    counts = {}
    for axis in ("u", "v"):
        c = surface[f"count_{axis}"]
        if isinstance(c, bool) or not isinstance(c, int) \
                or c < degrees[axis] + 1:
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.count_{axis}",
                 f"{field}: контрольных точек по {axis} должно быть не меньше "
                 f"degree_{axis} + 1 = {degrees[axis] + 1}, иначе базис NURBS "
                 f"не определён", got=c)
            return None
        counts[axis] = c

    total = counts["u"] * counts["v"]
    if total > MAX_CONTROL_POINTS:
        _bad(diags, TYPE_BOUNDS, oid, field,
             f"{field}: сетка {counts['u']}×{counts['v']} = {total} точек, "
             f"предел {MAX_CONTROL_POINTS} (НАЗНАЧЕН, см. шапку)", got=total)
        return None

    raw_pts = surface["control_points_mm"]
    if not isinstance(raw_pts, list) or len(raw_pts) != total:
        _bad(diags, TYPE_BOUNDS, oid, f"{field}.control_points_mm",
             f"{field}: сетка прямоугольна — точек обязано быть "
             f"count_u × count_v = {counts['u']} × {counts['v']} = {total}, "
             f"пришло {len(raw_pts) if isinstance(raw_pts, list) else raw_pts}",
             got=(len(raw_pts) if isinstance(raw_pts, list) else raw_pts))
        return None
    points: list = []
    for pi, p in enumerate(raw_pts):
        if not isinstance(p, list) or len(p) != 3 \
                or not all(is_finite_number(c) for c in p):
            _bad(diags, TYPE_BAD_TYPE, oid, f"{field}.control_points_mm[{pi}]",
                 f"{field}: контрольная точка — [x,y,z] из трёх конечных "
                 f"чисел в мм", got=p)
            return None
        if any(abs(float(c)) > COORD_MAX_MM for c in p):
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.control_points_mm[{pi}]",
                 f"{field}: координата вне ±{COORD_MAX_MM:.0f} мм — это вне "
                 f"рабочего пространства Revit, а не «далеко»", got=p)
            return None
        points.append([float(p[0]), float(p[1]), float(p[2])])

    knots = {}
    for axis in ("u", "v"):
        raw_k = surface[f"knots_{axis}"]
        if not isinstance(raw_k, list) \
                or not all(is_finite_number(k) for k in raw_k):
            _bad(diags, TYPE_BAD_TYPE, oid, f"{field}.knots_{axis}",
                 f"{field}: knots_{axis} — список конечных чисел", got=raw_k)
            return None
        kk = [float(k) for k in raw_k]
        why = _knots_ok(kk, degrees[axis], counts[axis])
        if why is not None:
            _bad(diags, SURFACE_KNOTS, oid, f"{field}.knots_{axis}",
                 f"{field}: knots_{axis} — {why}. Обратный ход требует того же "
                 f"(clamped, непериодические), и два конца провода обязаны "
                 f"требовать одно", got=kk)
            return None
        knots[axis] = kk

    weights = None
    if "weights" in surface:
        raw_w = surface["weights"]
        if not isinstance(raw_w, list) or len(raw_w) != total \
                or not all(is_finite_number(w) for w in raw_w):
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.weights",
                 f"{field}: weights — либо ОТСУТСТВУЕТ (поверхность "
                 f"нерациональна), либо ровно {total} конечных чисел",
                 got=(len(raw_w) if isinstance(raw_w, list) else raw_w))
            return None
        for wi, w in enumerate(raw_w):
            if float(w) <= 0.0:
                _bad(diags, TYPE_BOUNDS, oid, f"{field}.weights[{wi}]",
                     f"{field}: вес обязан быть СТРОГО положительным — "
                     f"неположительный вес делает поверхность неопределённой "
                     f"(тот же закон у обратного хода)", got=w)
                return None
        weights = [float(w) for w in raw_w]

    x0, y0, z0, x1, y1, z1 = surface_bbox(points)
    spans = sorted((x1 - x0, y1 - y0, z1 - z0), reverse=True)
    if spans[1] < MIN_EXTENT_MM:
        _bad(diags, SURFACE_DEGENERATE, oid, field,
             f"{field}: габарит сетки {spans[0]:.3f}×{spans[1]:.3f}×"
             f"{spans[2]:.3f} мм — не меньше двух измерений обязаны быть "
             f"больше {MIN_EXTENT_MM} мм. Поверхность, схлопнутая в кривую "
             f"или точку, поверхностью не является", got=spans)
        return None

    # DEGENERACY IS ASKED TWICE, AND THIS IS NOT TWO LAWS BUT ONE QUESTION
    # IN TWO COORDINATE SYSTEMS. The bounding box above sees a collapse
    # ONLY in world axes; a grid lying on a diagonal line has 3000 mm along
    # each of the three axes and passes it. The number here is the same
    # one, `MIN_EXTENT_MM`, and the refusal code is the same: it is one
    # question — "is the grid two-dimensional".
    off_line = line_deviation_mm(points)
    if off_line < MIN_EXTENT_MM:
        _bad(diags, SURFACE_DEGENERATE, oid, field,
             f"{field}: все контрольные точки лежат на одной прямой — дальняя "
             f"отстоит от неё на {off_line:.4f} мм при пределе "
             f"{MIN_EXTENT_MM} мм. Габарит сетки при этом не нулевой "
             f"({spans[0]:.1f}×{spans[1]:.1f}×{spans[2]:.1f} мм), и именно "
             f"поэтому одного габарита мало: он мерит оси МИРА, а вырождение "
             f"бывает по диагонали. Поверхность, схлопнутая в кривую, "
             f"поверхностью не является", got=off_line)
        return None

    corners = surface_corners(points, counts["u"], counts["v"])
    for ci in range(4):
        a, b = corners[ci], corners[(ci + 1) % 4]
        d = max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))
        if d < MIN_EXTENT_MM:
            _bad(diags, SURFACE_CORNER, oid, field,
                 f"{field}: углы {ci} и {(ci + 1) % 4} сетки совпали "
                 f"({d:.4f} мм) — граничное ребро выродилось бы в точку. "
                 f"Граница строится ТОЧНЫМИ изопараметрическими кривыми, и "
                 f"нулевое ребро Revit отвергнет уже в исполнении",
                 got=[a, b])
            return None
    # OPPOSITE CORNERS ARE A DIFFERENT AILMENT OF THE SAME ORGAN, AND
    # BEFORE 04.09.2026 NOBODY ASKED IT. The loop above walks NEIGHBORING
    # pairs (0-1, 1-2, 2-3, 3-0) — the four boundary edges. There are six
    # corner pairs in total, and the two remaining ones are the DIAGONALS
    # (0-2 and 1-3). Measured: a 2×2 grid with `p00 == p11` was accepted
    # with empty diags — all four edges were non-zero, while the patch was
    # folded in half and pinched at a point. The edge itself does not
    # degenerate here, so the old wording ("a boundary edge would
    # degenerate") cannot say this; the code is the same — it is one
    # question, "did the grid's corners coincide".
    for ci in (0, 1):
        a, b = corners[ci], corners[ci + 2]
        d = max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))
        if d < MIN_EXTENT_MM:
            _bad(diags, SURFACE_CORNER, oid, field,
                 f"{field}: ПРОТИВОПОЛОЖНЫЕ углы {ci} и {ci + 2} сетки совпали "
                 f"({d:.4f} мм) — лоскут сложен вдвое и защемлён в этой точке. "
                 f"Рёбра при этом ненулевые, поэтому проверка соседних углов "
                 f"такое пропускает; граница же перестаёт быть простой "
                 f"замкнутой кривой, и площадь грани теряет смысл", got=[a, b])
            return None

    return {"degree_u": degrees["u"], "degree_v": degrees["v"],
            "count_u": counts["u"], "count_v": counts["v"],
            "knots_u": knots["u"], "knots_v": knots["v"],
            "control_points_mm": points,
            "weights": weights}


def uniform_clamped_knots(degree: int, count: int) -> list:
    """A uniform clamped knot vector — a HELPER, not a default.

    There is deliberately no default here: the knot vector is part of the
    surface's DEFINITION, and silently substituting one would mean building
    a different surface than the one that was sent. The author calls this
    function THEMSELVES, and then the choice belongs to them and is visible
    in the program.
    """
    if count < degree + 1:
        raise ValueError(
            f"контрольных точек {count} меньше degree + 1 = {degree + 1}")
    inner = count - degree - 1
    return ([0.0] * (degree + 1)
            + [float(i + 1) / (inner + 1) for i in range(inner)]
            + [1.0] * (degree + 1))


# ═════════════════════════════════════════════════════════════════════════════
# SURFACE EVALUATION — WHY IT APPEARED ON THE EVENING OF 20.08.2026
#
# The first live run answered the question left open in the header of
# `ops_surface.py` ("will Revit accept control points WITHOUT RECOMPUTING
# them, cannot be checked offline at all"). The answer: NOT ALWAYS, and this
# is not a failure.
#
#     dome 4×4, degree 3×3, interior points raised  -> read back 3×3, 16 points,
#                                                       worst discrepancy 5.4e-13 mm
#     saddle 4×4, degree 3×3 (hypar)                -> read back 1×1, 4 points
#
# A hyperbolic paraboloid is a RULED surface: it is EXACTLY representable by
# a bilinear patch, and Revit's kernel collapsed the representation to the
# minimal one. The geometry is the same down to machine zero; what changed
# was the PARAMETRIZATION.
#
# 🔴 IT FOLLOWS THAT THE FORMER WITNESS LAW WAS WRONG IN KIND, not in
# number. It compared the REPRESENTATION (degree, point count, control-grid
# coordinates), while Revit only guarantees that the SURFACE matches. Such a
# law produces a FALSE RED — the worst kind of instrument error: it forbids
# correct work and teaches the author to route around the witness.
#
# WHAT IT WAS REPLACED WITH: the surface is compared AS A SET OF POINTS. A
# grid of samples is computed HERE, at compile time, from the same numbers
# that traveled into C#, and each sample is checked against the built face
# (`Face.Project`). The assertion becomes invariant to reparametrization,
# because it never mentions parametrization at all.
#
# WHY THE EVALUATION IS OURS, NOT REVIT'S. There is nobody to ask "where
# does point (u,v) of the author's surface lie": the author's surface does
# not exist in any form before it is built, other than these numbers.
# Having Revit compute it would mean comparing the built against the built
# — form 8 ("the witness checks ours against ours").
#
# THE ALGORITHM is Cox–de Boor as presented by Piegl & Tiller in «The NURBS
# Book», A2.1 (`_find_span`) and A2.2 (`_basis_functions`). Not our own
# invention, DELIBERATELY: the classical algorithm has an independent check
# — Bernstein polynomials on a Bézier patch — and the test cross-checks one
# against the other (see `test_surface_evaluation.py`).
# ═════════════════════════════════════════════════════════════════════════════

#: How many samples fall on one non-empty knot span per direction.
#: ⚠️ ASSIGNED, and here is the boundary of knowledge: samples catch a
#: discrepancy in shape, but proving "the surface did not drift between the
#: samples" with a finite sample cannot be done with ANY number. Three per
#: span is chosen as the smallest number that distinguishes a line, a
#: parabola, and a cubic inside a span; raising it is allowed on a live run,
#: lowering it silently is not.
SAMPLES_PER_SPAN = 3

#: The ceiling of samples per direction. Holds the emission size in check:
#: each sample is a point in a C# literal, and a 21×21 = 441-point grid is
#: already ~13 KB of text.
MAX_SAMPLES_PER_DIR = 21


def _find_span(count: int, degree: int, t: float, knots: list) -> int:
    """The index of the knot span containing ``t`` (A2.1, NURBS Book).

    A binary search, not a linear one, for the same reason it is one there:
    on a grid of thousands of points a linear pass gets multiplied by the
    number of samples.
    """
    n = count - 1
    if t >= knots[n + 1]:
        return n
    if t <= knots[degree]:
        return degree
    lo, hi = degree, n + 1
    mid = (lo + hi) // 2
    while t < knots[mid] or t >= knots[mid + 1]:
        if t < knots[mid]:
            hi = mid
        else:
            lo = mid
        mid = (lo + hi) // 2
    return mid


def _basis_functions(span: int, t: float, degree: int, knots: list) -> list:
    """The non-zero basis functions at point ``t`` (A2.2, NURBS Book).

    There are exactly ``degree + 1`` of them, they are non-negative, and
    they sum to one — the latter is checked by a test, not merely assumed.
    """
    out = [0.0] * (degree + 1)
    out[0] = 1.0
    left = [0.0] * (degree + 1)
    right = [0.0] * (degree + 1)
    for j in range(1, degree + 1):
        left[j] = t - knots[span + 1 - j]
        right[j] = knots[span + j] - t
        saved = 0.0
        for r in range(j):
            denom = right[r + 1] + left[j - r]
            if denom == 0.0:
                # UNREACHABLE with legal knots: `validate_surface` requires
                # the vector to be non-decreasing, clamped, and
                # non-degenerate. If we are here nonetheless — silence is
                # not allowed: a zero denominator does NOT give zero in the
                # answer, it gives a silently wrong point.
                raise ValueError(
                    f"вырожденный узловой пролёт при t={t}, span={span}: "
                    f"knots[{span + 1 - (j - r)}..{span + r + 1}] совпали")
            temp = out[r] / denom
            out[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        out[j] = saved
    return out


def surface_domain(surface: dict) -> tuple:
    """((u0, u1), (v0, v1)) — the domain of a clamped surface.

    For a clamped vector this is exactly ``knots[degree] .. knots[count]``,
    not "from the first knot to the last": outside the domain the basis
    does not form a partition of unity, and the point there is undefined.

    🔴 A MUTATION CONTROL ON THIS FUNCTION DOES NOT TURN RED, AND THIS IS
    RECORDED, NOT PASSED OVER IN SILENCE. The mutation "take
    ``knots[0] .. knots[-1]``" leaves all 15 checks green. The reason is
    not leaky tests: `validate_surface` requires CLAMPEDNESS, and for a
    clamped vector the first ``degree + 1`` knots are equal to one another
    and so are the last ones — that is, ``knots[0] == knots[degree]`` and
    ``knots[-1] == knots[count]`` IDENTICALLY. Two spellings of one number
    are indistinguishable by any legal input.

    The general form is left in on purpose: it states WHERE the domain
    comes from, and it will survive the day the language admits
    non-periodic, unclamped surfaces. But it must not be passed off as
    verified — what is verified here is exactly that, on a legal input, it
    coincides with the trivial one.
    """
    du, dv = surface["degree_u"], surface["degree_v"]
    cu, cv = surface["count_u"], surface["count_v"]
    ku, kv = surface["knots_u"], surface["knots_v"]
    return ((ku[du], ku[cu]), (kv[dv], kv[cv]))


def evaluate_surface(surface: dict, u: float, v: float) -> list:
    """The point [x, y, z] of a tensor-product NURBS surface at parameters (u, v).

    The rational case (weights) is computed as an HONEST DIVISION by the
    sum of the weights, not approximated: the weight is part of the
    surface's definition, and a rational arc computed as if non-rational
    will drift from the real one by a percentage of the radius.

    The point order is u-major (``iu * count_v + iv``), the same one
    `validate_surface` accepts and the emitter prints. This is a NAMED
    ASSUMPTION (see the header), and it is exactly one for the whole tree.
    """
    du, dv = surface["degree_u"], surface["degree_v"]
    cu, cv = surface["count_u"], surface["count_v"]
    ku, kv = surface["knots_u"], surface["knots_v"]
    pts = surface["control_points_mm"]
    weights = surface.get("weights")

    su = _find_span(cu, du, u, ku)
    sv = _find_span(cv, dv, v, kv)
    nu = _basis_functions(su, u, du, ku)
    nv = _basis_functions(sv, v, dv, kv)

    x = y = z = 0.0
    den = 0.0
    for k in range(du + 1):
        iu = su - du + k
        for m in range(dv + 1):
            iv = sv - dv + m
            idx = iu * cv + iv
            b = nu[k] * nv[m]
            w = 1.0 if weights is None else weights[idx]
            bw = b * w
            p = pts[idx]
            x += bw * p[0]
            y += bw * p[1]
            z += bw * p[2]
            den += bw
    if den == 0.0:
        raise ValueError(f"разбиение единицы дало ноль в (u={u}, v={v})")
    return [x / den, y / den, z / den]


def span_breaks(t0: float, t1: float, knots: list) -> list:
    """The boundaries of the NON-EMPTY knot spans inside the domain — in
    ascending order.

    Repeated knots collapse: a span between two EQUAL knots is empty, there
    is no shape in it, and a sample there would distinguish nothing.
    """
    out: list = []
    for k in knots:
        if t0 <= k <= t1 and (not out or k > out[-1]):
            out.append(float(k))
    if not out or out[0] > t0:
        out.insert(0, float(t0))
    if out[-1] < t1:
        out.append(float(t1))
    return out


def sample_parameters(t0: float, t1: float, knots: list) -> list:
    """Sample parameters along ONE direction: span boundaries EXACTLY plus
    `SAMPLES_PER_SPAN` interior points in every non-empty span.

    🔴 WHY NOT UNIFORM OVER THE DOMAIN, WHICH IS WHAT THIS WAS BEFORE
    04.09.2026. A NURBS shape changes polynomial at EVERY span boundary, so
    it is the knot vector, not the domain's length, that knows "where to
    look for a discrepancy". A uniform step does not know this and simply
    steps over a narrow span. Measured (degree 1,
    `knots_u = [0, 0, 0.400, 0.402, 1, 1]`, a Z peak of 10000 mm sits on the
    narrow span):

        40 samples, max_z OF THE SAMPLES     9290.2 mm
        z(u = 0.401)                         10000.0 mm   — the peak, and it is outside the sample
        samples in the span [0.400, 0.402]   ZERO

    That is, the shape witness declared that it had checked the face
    without ever looking at the place where the face is highest. The
    docstring promised "in every non-empty span", the code stepped across
    the domain — and the discrepancy was SILENT.

    WHAT IS PROMISED NOW, VERBATIM AND WITH A NAMED LIMIT. The boundaries
    of every non-empty span enter the sample EXACTLY; between neighboring
    boundaries, `SAMPLES_PER_SPAN` interior points are placed. If this does
    not fit within `MAX_SAMPLES_PER_DIR`, the interior points per span
    shrink (down to zero), while the boundaries are held onto until the
    last moment. When even the boundaries alone do not fit — there are more
    spans than the sample ceiling — the sample becomes uniform over the
    domain, and this is the ONLY case in which a narrow span can be
    skipped. It is named here, not passed over in silence.
    """
    breaks = span_breaks(t0, t1, knots)
    spans = len(breaks) - 1
    if spans < 1:
        return [float(t0)]
    if len(breaks) > MAX_SAMPLES_PER_DIR:
        # There are more spans than the ceiling: the per-span promise is
        # unfulfillable under any distribution, and the honest fallback is
        # a uniform grid.
        n = MAX_SAMPLES_PER_DIR
        return [t0 + (t1 - t0) * (i / (n - 1)) for i in range(n)]
    inner = SAMPLES_PER_SPAN
    while inner > 0 and len(breaks) + spans * inner > MAX_SAMPLES_PER_DIR:
        inner -= 1
    out: list = []
    for i in range(spans):
        a, b = breaks[i], breaks[i + 1]
        out.append(a)
        for k in range(1, inner + 1):
            out.append(a + (b - a) * k / (inner + 1))
    out.append(breaks[-1])
    return out


def sample_surface(surface: dict, nu: int = 0, nv: int = 0) -> list:
    """A grid of surface samples. The domain's corners are INCLUDED
    deliberately.

    The corners of a clamped surface coincide with the corner control
    points EXACTLY — this is an identity, not an approximation — so four
    samples from the grid also check that the face was built in the same
    place it was ordered, and was not shifted wholesale.

    ``nu``/``nv`` = 0 means "choose for yourself, BY THE KNOT VECTOR": the
    boundaries of every non-empty span plus `SAMPLES_PER_SPAN` interior
    points in each. Exactly what is promised here and where the promise
    ends is spelled out verbatim in `sample_parameters`; explicit
    ``nu``/``nv`` still mean a uniform grid of that size.
    """
    (u0, u1), (v0, v1) = surface_domain(surface)
    us = (sample_parameters(u0, u1, surface["knots_u"]) if nu <= 0 else
          [u0 + (u1 - u0) * (i / (nu - 1) if nu > 1 else 0.0) for i in range(nu)])
    vs = (sample_parameters(v0, v1, surface["knots_v"]) if nv <= 0 else
          [v0 + (v1 - v0) * (j / (nv - 1) if nv > 1 else 0.0) for j in range(nv)])
    return [evaluate_surface(surface, u, v) for u in us for v in vs]
