"""KIR PLANE — a SKETCH PLANE as a language VALUE (wave 21.08.2026).

WHY, BY THE ARITHMETIC OF A REAL BUILDING. The 20.08.2026 extraction of
family recipes turned up **27 shapes out of 283 (9.5%)**, and the largest
single refusal is `sketch_plane_not_horizontal`, **73 shapes**. The
reason is recorded in the refusal itself: "all four of our volumetric
operations are PLANAR (profile in XY, extrusion along +Z), they have no
transform". As long as this holds, there is no way to say a window or a
door: their shape lives on the FACE OF A WALL, not in plan.

═══ A KIND, NOT A SCATTERED SET OF FIELDS ═══════════════════════════════

    {"origin_mm": [x, y, z], "normal": [nx, ny, nz], "x_dir": [ux, uy, uz]}

ONE value with an internal law (x_dir ⊥ normal, both nonzero), exactly
like `mesh`, `surface`, and `solid_parts`. Three scattered fields would
mean orthogonality could be broken by editing ONE field and not
noticing: a law binding two carriers must live in the same place as both
of them.

🔴 `x_dir` IS MANDATORY, AND IT HAS NO DEFAULT. The argument is the same,
verbatim, as for `create_solid_sweep.ref_dir` in `ops_solid.py`: "A
choice the author does not see is, in this house, indistinguishable from
`.FirstOrDefault()`". `Plane.CreateByNormalAndOrigin(n, o)` and
`Plane.Create(Frame)` exist 6/6 and both choose the in-plane axes
THEMSELVES. For a window this is not a trifle: a profile rotated within
its own plane by an unknown angle passes the area witness, the volume
witness, and — for a symmetric profile — the bounding-box witness too.
That is, wrong geometry would be signed off by all three axes at once.

WHY NOT `y_dir` AS A THIRD FIELD. `y = normal × x_dir` is exact and
right-handed by construction. A third field would introduce a THIRD
carrier of one law, and carriers drift apart silently — the named-defect
class of this tree.

WHY NOT THREE POINTS (`Plane.CreateByThreePoints`, also 6/6). Three
points set the plane and the frame at once, but do not answer WHERE the
profile's origin is and where its +u points: the answer would have to be
derived by a rule the author does not see. The same argument as against
`CreateByNormalAndOrigin`.

═══ AN OMITTED PLANE = TODAY'S BEHAVIOR, BYTE FOR BYTE ══════════════════

The parameter is OPTIONAL and WITHOUT A DEFAULT. Its absence does not
substitute a horizontal plane "by default" — it leaves emission
UNTOUCHED: not one extra transform, not one changed literal. This is not
caution but a requirement of the parity ratchet: printing `+ 0 +` would
shift the bytes of EVERY existing body (the same argument already
recorded in `solid_emit._bbox_check`).

🔴 `plane` AND `base_z_mm` ARE MUTUALLY EXCLUSIVE, AND THIS IS NOT
NITPICKING. `base_z_mm` is exactly "the plane is horizontal at elevation
z", i.e. a degenerate case of this same kind. Allowing both would mean
introducing TWO ways to say one thing, and two carriers of one law drift
apart silently. The reverse pass uses this directly: a horizontal plane
is printed as `base_z_mm` (the program comes out byte-identical to
before the wave), a slanted one as `plane`.

═══ FOUR PLACES WHERE A VALUE KIND LIVES ════════════════════════════════

Recorded by the canon on 20.08.2026 ("a value kind lives in FOUR
places"), and paid for with the spline: emission and the witness recall
themselves, CANONICALIZATION and the REVERSE PASS are never recalled.
Here all four are named by name:

  1. CANONICALIZATION  `midend._canonical_json` — the value must be plain
                  JSON (a dict of number lists), otherwise the plan's
                  signature will lose it. Pinned by
                  `test_plane_kind_survives_the_plan`;
  2. EMISSION          `solid_emit` — the frame travels as a
                  `Transform`, the normal travels as the extrusion
                  direction;
  3. WITNESS           `solid_emit` — end faces are located by the
                  PLANE'S NORMAL, not by Z; the bounding box is computed
                  as the support function of the rotated profile;
  4. REVERSE PASS       `decompile.family_recipe` reads the frame from
                  Revit (`Sketch.SketchPlane.GetPlane()` ->
                  `Origin/Normal/XVec`), `decompile.program_source`
                  prints it back.

🔴 THE FOURTH PLACE NEARLY KILLED THE VALUE SILENTLY, and this is worth
recording. `program_source._round_mm` rounds every number list inside a
value of millimeter kind TO THE NEAREST WHOLE MILLIMETER, and `_shift`
subtracts the local frame's origin from EVERY list of length 2-3. For
`normal = [0.7071, 0.7071, 0]`, the first would give `[1.0, 1.0, 0.0]`
(a 45° plane would become one at 45° to a different axis and with length
1.41), the second would shift a DIRECTION as if it were a point. The
cure is to name `normal` and `x_dir` as dimensionless (`FREE_KEYS`) and
`origin_mm` as a millimeter one (`MM_KEYS`). Without this line, the kind
would have survived only three places out of four.

═══ API MEMBERS, MEASURED FROM `data/api_surface/`, 2021-2026 ═══════════

    Plane.CreateByOriginAndBasis(XYZ, XYZ, XYZ)      6/6
    Plane.CreateByNormalAndOrigin(XYZ, XYZ)          6/6   (not called — see above)
    Plane.CreateByThreePoints(XYZ, XYZ, XYZ)         6/6   (not called — see above)
    Plane.Origin · Normal · XVec · YVec              6/6   (READ BACK)
    SketchPlane.Create(Document, Plane)              6/6
    SketchPlane.GetPlane()                           6/6
    Transform.Identity · Origin · BasisX/Y/Z         6/6
    CurveLoop.CreateViaTransform(CurveLoop, Transform)               6/6
    GeometryCreationUtilities.CreateExtrusionGeometry(loops, dir, d) 6/6

🔴 `SketchPlane.Create` EXISTS 6/6 AND IS NOT CALLED HERE — A NAMED
DECISION, NOT AN OMISSION. The four volumetric operations put a body into
a `DirectShape` through `GeometryCreationUtilities`, and they have NO
real Revit sketch AT ALL: a `SketchPlane` is a document element, it
requires a transaction, it appears in `GetDependentElements`, and it
would be visible to a human as garbage in the model. The plane here is
the profile's COORDINATE FRAME, and its carrier is `Transform`, the very
same one `create_solid_revolve` already uses to move a contour from XY to
XZ (`solid_emit`, `CurveLoop.CreateViaTransform`, working live since
19.08). `SketchPlane.Create` will be needed by the op that builds a REAL
sketch inside a family — and that is a separate wave with its own
witness.
"""
from __future__ import annotations

import math
from typing import Any, Optional

from kir.diag import (Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS,
                           TYPE_GEOM_RELATION)
from kir import contour as C
from kir.emit_utils import is_finite_number

#: Value fields. Closed list: an extra field is a refusal, not "just in case".
PLANE_FIELDS: tuple[str, ...] = ("origin_mm", "normal", "x_dir")

#: Plane-origin bounds, mm. A POSITION, not a size — and this distinction
#: was bought by the measurement of 21.08.2026.
#:
#: 🔴 IT USED TO BE 500 000, "THE SAME BOUNDS AS `base_z_mm` AND THE SHAPE SIDE".
#: The argument compared the plane origin to a SIZE limit, whereas the origin
#: is a POSITION. It had not been reconciled with the language's positions at
#: all:
#:
#:     pt_xy / pt_xyz-kind parameters in the registry    47
#:     of those with numeric bounds                       0
#:     plane origin                                 ±500 000 mm
#:
#: Forty-seven positions are bounded by nothing, the forty-eighth is bounded —
#: against a quantity of a different kind. A live case: a twisted tower of 112
#: walls is built at x ≈ 800 000 mm and accepted without complaint, while a
#: rack with a plane at the same spot is refused by this line.
#:
#: MEASURED IN LIVE REVIT (Project1, a 1000×1000×500 prism, volume drift from
#: the declared 500 000 000 mm³):
#:
#:       0.5 km   built   drift 8.6e-06 mm³
#:       5   km   built   drift 2.34e-04
#:      20   km   built   drift 2.34e-04
#:      32   km   built   drift 2.34e-04
#:      60   km   built   drift 2.34e-04
#:     100   km   built   drift 2.34e-04
#:
#: The drift does NOT GROW with distance: from 5 km to 100 km it is the same
#: value, meaning this is a step in number representation, not precision loss
#: from distance. Relative error 5e-13. Revit refused at no distance.
#:
#: 100 km is the largest value BUILT live; nothing above it was checked, and
#: nothing is claimed here about larger distances. The SIZE limit
#: (`MAX_EXTENT_MM`, `SHAPE_SIDE_MAX_MM` = 500 000) stays as it was: it is a
#: different quantity, and linking the two was a mistake.
PLANE_ORIGIN_ABS_MAX_MM = 100_000_000.0

#: The smallest vector length at which a direction is still defined.
#: Not "almost zero": shorter than this, normalization amplifies input noise
#: more than the value itself, and a typo in the sixteenth digit would become
#: enough to rotate the plane by an arbitrary angle.
MIN_VECTOR_LEN = 1e-9

#: Orthogonality tolerance |x̂·n̂|. The same number, for the same reason, as
#: `solid_emit._AXIS_COS_EPS` and `family_recipe.PLANE_NORMAL_TOL`: the
#: quantity is mathematically EXACTLY zero, and the threshold exists only to
#: absorb double-precision arithmetic. 1e-6 ≈ 0.00006°.
#:
#: 🔴 THERE IS NO ORTHOGONALIZATION HERE, ON PURPOSE. Projecting `x_dir` onto
#: the plane and silently accepting it is exactly the kind of quiet input fix
#: that has already cost this house 96.77% of the groups (`mesh.py`). The
#: author who wrote a non-perpendicular vector made a mistake either in the
#: normal or in the direction, and which one — only they know, not us.
ORTHOGONALITY_COS_TOL = 1e-6


def _bad(diags: list, code: str, oid, field: str, message: str,
         got: Any = None, expected: Any = None) -> None:
    diags.append(Diagnostic(code=code, op_id=oid, field_name=field, got=got,
                            expected=expected, message_ru=message))


def _vec3(value: Any, diags: list, oid, field: str,
          ) -> Optional[tuple[float, float, float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 3 \
            or not all(is_finite_number(c) for c in value):
        _bad(diags, TYPE_BAD_TYPE, oid, field,
             f"{field} — [x, y, z] из трёх конечных чисел", got=value)
        return None
    return (float(value[0]), float(value[1]), float(value[2]))


def _norm(v: tuple[float, float, float]) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _unit(v: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _norm(v)
    return (v[0] / length, v[1] / length, v[2] / length)


def cross(a, b) -> tuple[float, float, float]:
    """Cross product. ONE for the whole package — a second one would disagree
    in sign.

    The sign already cost this tree a round column turned inside out into a
    concave star (`family_recipe._bulge_from_midpoint`, 20.08.2026): the
    argument "the sign is obvious" turned out to be wrong exactly half the
    time.
    """
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def validate_plane(plane: Any, oid, field: str,
                   diags: list) -> Optional[dict]:
    """Plane value -> normalized dict, or None plus a refusal.

    Fixes nothing and discards nothing: the input is either accepted whole
    or a refusal is named. The returned `normal` and `x_dir` are UNIT
    vectors, and that is the only transformation applied to the input,
    because it changes none of the author's decisions: the length of the
    direction vector carries no meaning at all, and an arbitrary length
    would make the plan's signature depend on the record's scale.
    """
    if not isinstance(plane, dict):
        _bad(diags, TYPE_BAD_TYPE, oid, field,
             f"{field}: плоскость — словарь "
             f"{{{', '.join(PLANE_FIELDS)}}}", got=plane)
        return None
    unknown = sorted(set(plane) - set(PLANE_FIELDS))
    missing = [f for f in PLANE_FIELDS if f not in plane]
    if unknown or missing:
        _bad(diags, TYPE_BAD_TYPE, oid, field,
             f"{field}: плоскость знает РОВНО {', '.join(PLANE_FIELDS)}"
             + (f"; лишнее: {unknown}" if unknown else "")
             + (f"; не хватает: {missing}" if missing else "")
             + ". x_dir обязателен: без него оси В плоскости выбрал бы Revit, "
               "и профиль приехал бы повёрнутым на неизвестный угол — "
               "свидетели площади, объёма и (у симметричного профиля) "
               "габарита этого НЕ ЗАМЕТЯТ",
             got=sorted(plane))
        return None

    origin = _vec3(plane["origin_mm"], diags, oid, f"{field}.origin_mm")
    normal = _vec3(plane["normal"], diags, oid, f"{field}.normal")
    x_dir = _vec3(plane["x_dir"], diags, oid, f"{field}.x_dir")
    if origin is None or normal is None or x_dir is None:
        return None

    for axis, value in zip("xyz", origin):
        if abs(value) > PLANE_ORIGIN_ABS_MAX_MM:
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.origin_mm",
                 f"{field}: начало плоскости по {axis} = {value:.1f} мм вне "
                 f"±{PLANE_ORIGIN_ABS_MAX_MM:.0f} мм — те же границы, что у "
                 f"base_z_mm и у стороны формы контура",
                 got=value, expected=f"|{axis}| <= {PLANE_ORIGIN_ABS_MAX_MM:.0f}")
            return None

    for name, vec in (("normal", normal), ("x_dir", x_dir)):
        length = _norm(vec)
        # 🔴 THE THRESHOLD ONLY GUARDED THE BOTTOM, AND OVERFLOW SLIPPED IN
        # FROM ABOVE (fixed 04.09.2026). `_vec3` lets `1e308` through — each
        # component is FINITE — while `_norm` squares them and gets `inf`.
        # Downstream the chain broke in three places in a row and NEVER went
        # red: `inf < 1e-9` is false, so the length guard stayed silent;
        # `_unit` divided finite components by `inf` and returned EXACTLY
        # `(0,0,0)`; the orthogonality check `|x̂·n̂| = 0` passed trivially,
        # because a dot product with zero is zero. A "plane" with no
        # direction went out, with an EMPTY diagnostics list — measured:
        # `normal=[1e308, 1e308, 0]` -> accepted, `normal` became
        # `[0.0,0.0,0.0]`.
        #
        # This is NOT a second tolerance and not a "maximum length": the
        # direction's length still carries no meaning and is still not
        # bounded from above. The refusal is about exactly one thing — a
        # number whose square is not representable as a double defines NO
        # direction at all, and there is nothing to normalize here.
        if not math.isfinite(length):
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.{name}",
                 f"{field}: {name} = {list(vec)} — длина вектора переполняет "
                 f"double ({length}), направления нет. Компоненты по "
                 f"отдельности конечны, а их сумма квадратов уже нет: "
                 f"нормировка дала бы РОВНО нулевой вектор, и плоскость "
                 f"уехала бы без направления. Длина смысла не несёт — "
                 f"запишите то же направление числами поменьше",
                 got=list(vec), expected="конечная длина вектора")
            return None
        if length < MIN_VECTOR_LEN:
            _bad(diags, TYPE_BOUNDS, oid, f"{field}.{name}",
                 f"{field}: {name} длиной {length:.3e} — направления нет. "
                 f"Короче {MIN_VECTOR_LEN:g} нормировка усиливает шум входа "
                 f"сильнее самого значения",
                 got=list(vec), expected=f"длина >= {MIN_VECTOR_LEN:g}")
            return None

    n = _unit(normal)
    x = _unit(x_dir)
    skew = abs(dot(n, x))
    if skew > ORTHOGONALITY_COS_TOL:
        _bad(diags, TYPE_GEOM_RELATION, oid, f"{field}.x_dir",
             f"{field}: x_dir не лежит В плоскости — |cos(x_dir, normal)| = "
             f"{skew:.6g} при допуске {ORTHOGONALITY_COS_TOL:g} "
             f"(угол с плоскостью {math.degrees(math.asin(min(1.0, skew))):.4f}°). "
             f"Спроецировать за автора нельзя: ошибка либо в нормали, либо в "
             f"направлении, и какая именно — знает он",
             got=round(skew, 12), expected=f"<= {ORTHOGONALITY_COS_TOL:g}")
        return None

    # 🔴 LISTS, NOT TUPLES — AND THIS IS ABOUT THE FOURTH SPOT. The value must
    # survive `json.dumps -> json.loads` UNCHANGED: a tuple goes into JSON as
    # an array and comes back as a LIST, meaning a plan re-read from its
    # signature would stop being equal to itself as a Python object. It was
    # exactly this shape that cost the spline its kind on 20.08.
    return {"origin_mm": [float(origin[0]), float(origin[1]), float(origin[2])],
            "normal": [n[0], n[1], n[2]],
            "x_dir": [x[0], x[1], x[2]]}


def _pz(value) -> float:
    """Collapse MINUS ZERO into zero, without touching anything else.

    `x + 0.0 == x` for every finite x, and the one exception is `-0.0`, which
    becomes `+0.0`. This is needed because the cross product produces minus
    zeros on axis-aligned frames (a -Y normal gives `BasisY = (-0.0, 0, 1)`),
    and `repr` prints them into C# as `-0.0`. The value is the same, the TEXT
    is different — meaning two identical planes would produce a different
    program and a different plan signature. This is exactly the class of bug
    that made `_cos_sin_deg` in solid_emit print exact zeros at multiples of
    90°.
    """
    return float(value) + 0.0


def frame(plane: dict) -> tuple[tuple[float, float, float],
                                tuple[float, float, float],
                                tuple[float, float, float],
                                tuple[float, float, float]]:
    """Normalized plane -> (origin, X, Y, N). Y is derived, not stored.

    The ONE place where `y = n × x` is computed, because a second one would
    diverge in sign, and the sign of the right-handed triple decides which
    way the profile faces.
    """
    o = tuple(_pz(c) for c in plane["origin_mm"])
    n = tuple(_pz(c) for c in plane["normal"])
    xd = tuple(_pz(c) for c in plane["x_dir"])
    y = tuple(_pz(c) for c in cross(n, xd))
    return o, xd, y, n  # type: ignore[return-value]


def to_world(plane: dict, u: float, v: float) -> tuple[float, float, float]:
    """Sketch-plane point (u, v) -> world point in mm."""
    o, x, y, _n = frame(plane)
    return (o[0] + u * x[0] + v * y[0],
            o[1] + u * x[1] + v * y[1],
            o[2] + u * x[2] + v * y[2])


#: THE PROFILE SUPPORT FUNCTION AND THE PLANE-BOUND BBOX MOVED HERE ON
#: 01.09.2026. They used to live in `solid_emit`, and that was the ONLY
#: carrier — a copy in the registry would have silently diverged from the
#: one the extrusion uses to compute its bbox. But the carrier has TWO
#: readers, and the second is the registry (`ops_boolean` computes the
#: prism's bbox), so the house was moved DOWN below both, rather than
#: duplicated. While the house was in emission, the registry pulled in the
#: emitter, and through that edge the live-plan renderer reached all the way
#: to the compiler: a `capability_graph` traversal gave 10 solvers out of 15.
#: The subject is purely geometric: a plane plus a contour, not a line of C#.

def profile_support(region: dict, a: float, b: float) -> tuple[float, float]:
    """(min, max) of the linear function a·u + b·v over the OUTER ring —
    EXACTLY.

    Candidates are taken from `contour.extreme_candidates` — the same single
    carrier of the arc law from which the planar `edges_bbox` is also
    derived. Openings are not examined: CONTOUR has already proven their
    strict interiority, exactly as in `region_bbox`.
    """
    pts = C.extreme_candidates(region["outer"], ((a, b),))
    vals = [a * pt[0] + b * pt[1] for pt in pts]
    return min(vals), max(vals)


def plane_profile_box(plane: dict, regions, offsets) -> tuple:
    """World axis-aligned bbox of profiles laid onto the plane and shifted
    along its normal by `offsets`.

    A DERIVATION, NOT A SAMPLING. A world point is O + u·X + v·Y + t·N, so
    its k-th coordinate equals O[k] + (X[k])·u + (Y[k])·v + t·N[k] — a
    LINEAR function of (u, v). Its extremum over the profile is given by the
    support function above, exact for arcs too; the shift's contribution is
    additive. So the bbox here is EXACT, not estimated — and the bbox
    witness keeps the right to go red.

    🔴 A SPLINE DOES NOT REACH HERE, AND THIS IS NOT WHERE IT IS CHECKED.
    `edges_bbox` states its own boundary plainly: for a spline the bbox is a
    LOWER bound, because Revit chooses the shape between the points. The
    guard stands earlier, in `ground.py` (`region_has_spline`), and
    generalizing the support function does not weaken it: sampling enters
    the candidates exactly as it did before.
    """
    o, x, y, n = frame(plane)
    lo = [0.0, 0.0, 0.0]
    hi = [0.0, 0.0, 0.0]
    for k in range(3):
        vlo = []
        vhi = []
        for region, t in zip(regions, offsets):
            smin, smax = profile_support(region, x[k], y[k])
            vlo.append(o[k] + smin + t * n[k])
            vhi.append(o[k] + smax + t * n[k])
        lo[k], hi[k] = min(vlo), max(vhi)
    return (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])


def is_horizontal(plane: dict, tol: float = ORTHOGONALITY_COS_TOL) -> bool:
    """Whether the plane matches today's planar case COMPLETELY.

    🔴 "HORIZONTAL" HERE MEANS MORE THAN "NORMAL ALONG Z". The reverse pass
    prints a horizontal plane as `base_z_mm`, and `base_z_mm` carries EXACTLY
    one thing: an elevation — origin at zero in plan and +u along world +X. A
    plane with a +Z normal but a shifted or rotated origin is a DIFFERENT
    geometry, and calling it `base_z_mm` would silently lose the shift and
    the rotation. That is why all three conditions are checked, not just one.
    """
    o, x, _y, n = frame(plane)
    return (abs(n[2] - 1.0) <= tol
            and abs(n[0]) <= tol and abs(n[1]) <= tol
            and abs(x[0] - 1.0) <= tol
            and abs(x[1]) <= tol and abs(x[2]) <= tol
            and abs(o[0]) <= 1e-9 and abs(o[1]) <= 1e-9)


def horizontal_at(z_mm: float) -> dict:
    """The plane identical to today's `base_z_mm=z`.

    Needed by the REVERSE PASS and by tests as the REFERENCE for the
    degenerate case: the claim "an omitted plane means exactly this" is
    checkable only once "this" is written down as a value, not as prose.
    """
    return {"origin_mm": [0.0, 0.0, float(z_mm)],
            "normal": [0.0, 0.0, 1.0],
            "x_dir": [1.0, 0.0, 0.0]}
