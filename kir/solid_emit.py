"""solid_emit — emission of parametric solids (a paired file to
ops_solid.py).

Its own wave zone: this module touches no other `*_emit.py`. authoring.py
gets an additive import and two lines in `_EMITTERS` — the same minimal seam
through which the framing, AR, and mesh waves were plugged in.

Reused UNCHANGED (by import, not by copy): `_cs`, `_safe`, `_stamp_block`,
`_stamp_readback` from authoring.py; `emit_loop_cs` and the region measures —
from contour.py; `refuse_stmt` — from emit_utils (the sole owner of the
refusal's shape). The breakdown of WHY this wave, the 6/6 API measurement,
and the list of what is refused and why are in the header of ops_solid.py.

═══ WHAT'S INTERESTING HERE IN THE EMISSION ITSELF ════════════════════════

1. UNITS. `U(mm)` and `MM(foot)` are linear with no offset, so their
   COMPOSITION converts areas and volumes: `MM(MM(1.0))` — square feet to
   square mm, `MM(MM(MM(1.0)))` — cubic feet to cubic mm. This is exact and
   doesn't start a third home for 304.8 (the first two are `U` and `MM`, both
   already in the program header). It looks unfamiliar, so it's said plainly
   here: the triple composition is NOT a typo, it's the cube of the scale.

2. GEOMETRY OF THE REVOLVE PLANE. `emit_loop_cs` prints the contour in the XY
   plane (this is CONTOUR's PINNED decision, and this wave has no right to
   touch it). Revit, however, requires the revolve profile in the frame's XZ
   plane. The transition is done by ONE
   `CurveLoop.CreateViaTransform` (6/6) transform with basis X=(1,0,0),
   Y=(0,0,1), Z=(0,-1,0) — a right-handed triple mapping (u,v,0) to
   (axis.x+u, axis.y, base_z+v). A second contour emitter of its own would
   have meant a second set of arc arithmetic.

3. THE FACTORY'S EXCEPTION IS NOT CAUGHT. `CreateExtrusionGeometry` throws
   `Autodesk.Revit.Exceptions.ApplicationException` on an unfit profile, and
   catching it here would be tempting for the sake of a nice message. But the
   house's law (`__KirOpRefusal` is a TYPE, a Revit refusal has its own
   catch) states: a Revit API failure is recorded as `internal`, not as a
   decision of the compiler. Catching it would turn someone else's breakage
   into our own "refusal" — and from outside it would look like a decision we
   made.

═══ WITNESS TOLERANCE AND THE BAN ON VACUOUSNESS ══════════════════════════

The tolerance number is computed AT RUNTIME from Revit's own number:

    double __dt = MM(doc.Application.VertexTolerance) + EMIT_COORD_QUANTUM_MM;

and multiplied by the geometry: by the surface area — for volume, by the
length of the end-face boundaries — for the end-face area. The derivation is
in the header of ops_solid.py.

Next to every such witness a RUNTIME REFUSAL of vacuousness is emitted: a
tolerance no smaller than the measured quantity means a check that cannot
fail, and the op is required to refuse, by name. The threshold is not a
chosen number but a definition: `tolerance >= quantity`.
"""
from __future__ import annotations

import math

from kir import contour as C
from kir import plane as PL
from kir import sweep_path as SW
from kir.emit_core import (  # noqa: F401
    _cs, _safe, _stamp_block, _stamp_readback, element_identity_readback_cs,
)
from kir.diag import Diagnostic, KirRefusal, TYPE_GEOM_RELATION
from kir.emit_model import WitnessCheck
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.ops_shape import DIRECTSHAPE_CATEGORIES
# A SINGLE SOURCE FOR THE WORKING EXTENT. The same number `contour` uses to
# measure a flat shape's COMPUTED vertex; here it gets a second reader and a
# different subject — the WORLD bounding box of a solid body.
from kir.registry_base import COORD_LIMIT_MM

#: The same honest label as the mesh's, with the difference named: the body
#: is parametric, but it carries exactly as much BIM meaning — none at all.
HONEST_MARK = ("KIR Solid: параметрическое тело без BIM-смысла "
               "(нет типа/параметров)")

#: The cosine threshold for "a face normal is parallel/perpendicular to the
#: Z axis".
#:
#: THE SPLIT HERE IS EXACT BY CONSTRUCTION, NOT APPROXIMATE, and this is
#: worth saying outright, otherwise the threshold reads as picked by eye:
#:
#:  * for a PRISM, the ends lie in the plane of the profile (all contour
#:    points are printed with the SAME z coordinate), so their normal is
#:    exactly ±Z; the side faces contain the direction of extrusion, i.e. the
#:    Z axis itself, so their normal has exactly zero Z-component. Rounding
#:    the plan coordinates touches neither quantity at all;
#:  * for a SOLID OF REVOLUTION, the sector's ends are planes containing the
#:    axis, so their normal is ⊥ Z exactly; a horizontal edge of the profile
#:    gives a flat ring with a normal ∥ Z exactly; a slanted edge gives a
#:    cone, and that is not a `PlanarFace` and doesn't enter the sum by type.
#:
#: That is, mathematically the quantity equals EXACTLY 0 or EXACTLY 1, and the
#: threshold is only needed to absorb the double-precision arithmetic Revit
#: uses to compute the normal. 1e-6 is roughly ten million machine epsilons:
#: comfortably clear of the noise, and still a million times stricter than any
#: meaningful face tilt.
_AXIS_COS_EPS = 1e-6


def _n(value: float) -> str:
    """A number as a double-precision C# literal WITHOUT losing significant
    digits.

    Python's ``repr`` gives the shortest string that reads back into the SAME
    double. Rounding the expected volume "for tidiness" is not allowed: this
    is exactly the place where the witness compares against the reference,
    and a lost digit would become an error nobody ever accounted for.
    """
    return repr(float(value))


def _loops_cs(region: dict, s: str) -> str:
    """The C# for assembling the region's loops — the outer one and every
    opening.

    The loops are built by `contour.emit_loop_cs` UNCHANGED: the arc
    arithmetic lives in one place in the package, and a second home for it
    would be a second answer to one question.
    """
    parts = [C.emit_loop_cs(region["outer"], f"__ol_{s}")]
    for hi, hole in enumerate(region["holes"]):
        parts.append(C.emit_loop_cs(hole, f"__hl_{s}_{hi}"))
    return "\n".join(parts)


def _transform_cs(region: dict, s: str, transform_expr: str | None) -> str:
    """A list of CurveLoop, run through a transform if needed."""
    names = [f"__ol_{s}"] + [f"__hl_{s}_{i}" for i in range(len(region["holes"]))]
    out = [f"IList<CurveLoop> __lps_{s} = new List<CurveLoop>();"]
    for nm in names:
        if transform_expr is None:
            out.append(f"__lps_{s}.Add({nm});")
        else:
            out.append(f"__lps_{s}.Add(CurveLoop.CreateViaTransform({nm}, {transform_expr}));")
    return "\n".join(out)


# ── THE SKETCH PLANE: frame, bounding box, end-face normal (21.08.2026) ────
#
# 🔴 ALL THREE HELPERS ARE CALLED ONLY WHEN A PLANE IS DECLARED. Without one,
# the emitters take the old branch and print the OLD BYTES — not "equivalent
# text", the exact same ones. This is a requirement of the parity ratchet,
# not caution: a shared way of writing it (`DotProduct(new XYZ(0,0,1))`
# instead of `.Z`) would shift the bytes of EVERY existing body, and an edit
# touching none of them would paint the ratchet red. The same argument is
# already recorded at `_bbox_check` regarding `+ 0 +`.


def _plane_frame_cs(s: str, plane: dict) -> tuple[str, str]:
    """The plane frame's Transform. The SAME shape the revolve has used to
    move the contour from XY to XZ since 19.08 (`CurveLoop.CreateViaTransform`,
    verified live).

    Returns (declaration, variable name). The basis is a right-handed triple
    (X, Y, N), where Y = N × X is derived by `plane.frame`, not stored: a
    third carrier of one law would drift apart on the sign, and the sign
    decides which way the profile faces.
    """
    o, x, y, n = PL.frame(plane)
    var = f"__pf_tf_{s}"
    decl = (
        f"Transform {var} = Transform.Identity;\n"
        f"{var}.Origin = P({_n(o[0])}, {_n(o[1])}, {_n(o[2])});\n"
        f"{var}.BasisX = new XYZ({_n(x[0])}, {_n(x[1])}, {_n(x[2])});\n"
        f"{var}.BasisY = new XYZ({_n(y[0])}, {_n(y[1])}, {_n(y[2])});\n"
        f"{var}.BasisZ = new XYZ({_n(n[0])}, {_n(n[1])}, {_n(n[2])});")
    return decl, var


#: THE ANCHOR FUNCTION AND THE BOUNDING BOX ON A PLANE HAVE LIVED IN
#: `kir.plane` SINCE 01.09.2026. What's left here are the OLD NAMES as
#: aliases: two spots further down the file call them, and renaming would
#: shift the emission diff without a single byte actually changing. There is
#: one carrier, it's just lower down — the full argument is in the header of
#: `kir/plane.py`.
_profile_support = PL.profile_support
_plane_profile_box = PL.plane_profile_box


def _within_world_extent(box: tuple, oid, field: str, how: str) -> None:
    """A refusal if the solid's WORLD bounding box runs outside the model's
    working extent.

    🔴 WHAT THIS GAP IS AND WHY NEITHER OF THE TWO CLOSED IT. A body's
    location and its profile are checked SEPARATELY, and both honestly:
    `axis_xy_mm` (like any coordinate) — in `authoring_validation`, the
    profile's vertices — in `contour._shape_within_world_extent`. Neither of
    the two asks about the SUM, and a solid lives precisely in the sum.
    Measured 04.09.2026:

        CONTROL   revolve axis=[0, 0], profile 2000×1000    -> compiles
        EXPERIMENT revolve axis=[16,000,000, 0], same        -> ok=True,
                  diags 0, yet the world bounding box along x reaches
                  16,002,000 mm against a limit of 16,000,000
        NEIGHBOR  extrude with plane origin_x=16,000,000     -> ok=True,
                  world bounding box 16,000,000 .. 16,002,000 — THE SAME gap

    That is, there is one law but there were two gaps, and nobody had named
    the second one. So there is one guard for all solid operations, not one
    per operation: the number is taken from `registry_base.COORD_LIMIT_MM` —
    the same home `contour`, `mesh`, and `curveops` take it from — and no
    second law is set up here. Each operation computes its OWN bounding box,
    because what makes it its own is not the law but the geometry: for
    extrude and blend it comes from the profile's anchor function on the
    plane (`plane_profile_box`), for revolve it's the sector around the axis,
    for sweep it's the path inflated by the radius.
    """
    worst = max(box, key=abs)
    if abs(worst) <= COORD_LIMIT_MM:
        return
    raise KirRefusal([Diagnostic(
        code=TYPE_GEOM_RELATION, op_id=oid, field_name=field,
        got=round(worst, 2), expected=f"|координата| <= {COORD_LIMIT_MM:.0f} мм",
        message_ru=(
            f"{field}: и место, и профиль по отдельности законны, но тело "
            f"целиком уезжает за рабочий охват модели (~16 км от начала "
            f"координат): дальняя мировая координата {worst:.0f} мм при "
            f"пределе {COORD_LIMIT_MM:.0f}. Это НЕ то число, которое вы "
            f"написали, — оно сложено из {how} (мировой габарит тела "
            f"x {box[0]:.0f}..{box[3]:.0f}, y {box[1]:.0f}..{box[4]:.0f}, "
            f"z {box[2]:.0f}..{box[5]:.0f}). СЛЕДУЮЩИЙ ХОД: сдвинуть тело на "
            f"{abs(worst) - COORD_LIMIT_MM:.0f} мм внутрь либо уменьшить "
            f"профиль на столько же; если тело правда так далеко, перенеси "
            f"начало координат проекта"))])

def _plane_vertices_world(plane: dict, region: dict, t: float) -> list:
    """Vertices of the outer loop in WORLD mm at elevation t along the
    normal."""
    o, x, y, n = PL.frame(plane)
    out = []
    for u, v in C.edges_vertices(region["outer"]):
        out.append((o[0] + u * x[0] + v * y[0] + t * n[0],
                    o[1] + u * x[1] + v * y[1] + t * n[1],
                    o[2] + u * x[2] + v * y[2] + t * n[2]))
    return out


def _shell_cs(s: str, oid: str, member: str, name: str, stamp: str,
              isolation: str) -> tuple[str, str, str]:
    """The DirectShape shell shared by both operations (declarations,
    creation).

    ONE shell for two ops, because it is one and the same fact: the solid
    goes into a DirectShape, a DirectShape has no type, and the honest label
    rides in Mark exactly when the field is free. Two copies of this code
    would have drifted apart on the first edit to the label's text.

    EVERYTHING THE POSTCONDITION AND THE RECEIPT READ IS DECLARED HERE —
    including the TOLERANCE NUMBERS THEMSELVES. With isolation="per_op" the
    creation block is wrapped in its own scope, and a variable declared
    inside it is invisible to the witness (CS0103 — the exact seam the first
    version of the enclosures emitter failed on). The tolerance is computed
    in create, but lives in decl.

    """
    decl = (f"DirectShape __el_{s} = null;\n"
            f"Solid __sol_{s} = null;\n"
            f"bool __lbl_{s} = false;\n"
            f"int __nsol_{s} = 0;\n"
            f"double __rvol_{s} = 0.0;\n"
            f"double __rcap_{s} = 0.0;\n"
            f"double __dt_{s} = 0.0;\n"
            f"double __tvol_{s} = 0.0;\n"
            f"double __tcap_{s} = 0.0;")
    head = (
        f"ElementId __cat_{s} = new ElementId(BuiltInCategory.{member});\n"
        # The category is checked ON THE DOCUMENT, not against our table: it
        # can be turned off by the project template, and then CreateElement
        # will return null already after we've decided everything is fine.
        f"if (!DirectShape.IsValidCategoryId(__cat_{s}, doc)) {{ "
        f"{refuse_stmt(oid, _cs('категория недопустима для DirectShape в этом документе'), isolation)} }}")
    tail = (
        f"if (__sol_{s} == null || __sol_{s}.Faces.Size == 0) {{ "
        f"{refuse_stmt(oid, _cs('Revit не построил тело из этого профиля (пустой Solid)'), isolation)} }}\n"
        f"__el_{s} = DirectShape.CreateElement(doc, __cat_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание DirectShape вернуло null'), isolation)} }}\n"
        f"IList<GeometryObject> __gos_{s} = new List<GeometryObject>();\n"
        f"__gos_{s}.Add(__sol_{s});\n"
        f"__el_{s}.SetShape(__gos_{s});\n"
        f"__el_{s}.Name = {_cs(name)};\n"
        # get_Parameter returns null if there is no such parameter — then
        # there simply will be no label, and the receipt will say so honestly
        # (false), not stay silent about it. A non-empty foreign value is
        # never touched.
        f"Parameter __mk_{s} = __el_{s}.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);\n"
        f"if (__mk_{s} != null && !__mk_{s}.IsReadOnly && "
        f"string.IsNullOrEmpty(__mk_{s}.AsString()))\n"
        f"    __lbl_{s} = __mk_{s}.Set({_cs(HONEST_MARK)});\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    return decl, head, tail


def _derived_tolerances_cs(s: str, oid: str, isolation: str, *,
                           surface_mm2: float, min_feature_vol_mm3: float,
                           cap_boundary_mm: float,
                           min_feature_cap_mm2: float) -> str:
    """Witness tolerances + the runtime ban on vacuousness.

    See the file header and the header of ops_solid.py: δ = Revit's own
    `VertexTolerance` plus our emission's quantum; the volume tolerance =
    δ·(surface area); the end-face area tolerance = δ·(length of the end-face
    boundaries). Both are DERIVED from this op's geometry, and so they live in
    the emission, not in the constants registry.
    """
    out = [
        f"__dt_{s} = MM(doc.Application.VertexTolerance) + "
        f"{_n(C.EMIT_COORD_QUANTUM_MM)};",
        f"__tvol_{s} = {_n(surface_mm2)} * __dt_{s};",
        # VACUOUSNESS IS A DEFINITION, NOT A TASTE: a tolerance no smaller
        # than the smallest declared quantity means its disappearance would
        # pass unnoticed. Such a witness is worse than having none, so here
        # there is a named refusal, not a signature.
        f"if (__tvol_{s} >= {_n(min_feature_vol_mm3)}) {{ "
        + refuse_stmt(
            oid,
            _cs('допуск объёмного свидетеля не меньше самой мелкой объявленной '
                'части профиля — проверка не смогла бы провалиться; тело '
                'слишком тонкое или проём слишком мелкий для честной сверки'),
            isolation) + " }",
    ]
    out += [
        f"__tcap_{s} = {_n(cap_boundary_mm)} * __dt_{s};",
        f"if (__tcap_{s} >= {_n(min_feature_cap_mm2)}) {{ "
        + refuse_stmt(
            oid,
            _cs('допуск свидетеля торцов не меньше самой мелкой объявленной '
                'части профиля — проверка не смогла бы провалиться'),
            isolation) + " }",
    ]
    return "\n".join(out)


def _read_solids_cs(s: str) -> str:
    """The reader of the BUILT geometry: sums over the element's actual
    solids.

    What is read is the RESULT, not our own call: `get_Geometry` returns what
    Revit actually put into the element. A `GeometryInstance` is unwrapped —
    a DirectShape is in principle allowed to hand back geometry wrapped, and a
    witness that can't do this would see ZERO solids and blame Revit for
    something it never did.
    """
    return (
        f"    var __ge_{s} = __el_{s}.get_Geometry(new Options());\n"
        f"    if (__ge_{s} != null)\n    {{\n"
        f"        foreach (GeometryObject __go_{s} in __ge_{s})\n        {{\n"
        f"            Solid __so_{s} = __go_{s} as Solid;\n"
        f"            if (__so_{s} != null && __so_{s}.Faces.Size > 0)\n"
        f"            {{ __nsol_{s}++; __rvol_{s} += __so_{s}.Volume; }}\n"
        f"            GeometryInstance __gi_{s} = __go_{s} as GeometryInstance;\n"
        f"            if (__gi_{s} != null)\n"
        f"                foreach (GeometryObject __g2_{s} in __gi_{s}.GetInstanceGeometry())\n"
        f"                {{\n"
        f"                    Solid __s2_{s} = __g2_{s} as Solid;\n"
        f"                    if (__s2_{s} != null && __s2_{s}.Faces.Size > 0)\n"
        f"                    {{ __nsol_{s}++; __rvol_{s} += __s2_{s}.Volume; }}\n"
        f"                }}\n"
        f"        }}\n    }}\n")


def _cap_reader_cs(s: str, axis_parallel: bool, axis=None) -> str:
    """The sum of areas of FLAT faces whose normal is defined relative to the
    AXIS.

    ``axis_parallel=True``  — the prism's end faces (normal ∥ axis);
    ``axis_parallel=False`` — the revolve sector's end faces (normal ⊥ axis).

    ``axis=None`` — the axis is the world Z, and the OLD text is printed,
    byte for byte. Otherwise the axis is the declared plane's normal.

    🔴 THE SPLIT STAYS EXACT ON A TILTED PLANE, AND THIS IS NOT AN
    ASSUMPTION. The argument in the header (`_AXIS_COS_EPS`) reads: for a
    prism the ends lie in the profile's plane, so their normal is exactly
    ±Z, and the side faces contain the extrusion direction, so their normal
    is exactly ⊥ Z. Both statements are about the EXTRUSION AXIS, not the
    world vertical: the solid is still a RIGHT prism, its axis is just the
    plane's normal. The quantity still equals EXACTLY 0 or EXACTLY 1, and the
    threshold still absorbs only double precision.

    🔴 WHAT THIS WITNESS DOES NOT DO ON A TILTED PLANE IS STATED HERE: it
    does not tell apart a rotation of the profile WITHIN its own plane. The
    end-face area does not depend on such a rotation, nor does the volume,
    and ONLY the bounding box catches such a rotation — which is why `x_dir`
    is mandatory in the language, while the bounding-box witness on the plane
    stays rigid on the outside.
    """
    if axis is None:
        proj = f"__pf_{s}.FaceNormal.Z"
    else:
        proj = (f"__pf_{s}.FaceNormal.DotProduct("
                f"new XYZ({_n(axis[0])}, {_n(axis[1])}, {_n(axis[2])}))")
    cond = (f"Math.Abs({proj}) > {_n(1.0 - _AXIS_COS_EPS)}"
            if axis_parallel
            else f"Math.Abs({proj}) < {_n(_AXIS_COS_EPS)}")
    return (
        f"    if (__sol_{s} != null)\n"
        f"        foreach (Face __f_{s} in __sol_{s}.Faces)\n        {{\n"
        f"            PlanarFace __pf_{s} = __f_{s} as PlanarFace;\n"
        f"            if (__pf_{s} != null && {cond})\n"
        f"                __rcap_{s} += MM(MM(__pf_{s}.Area));\n"
        f"        }}\n")


def _solid_count_check(s: str, oid: str) -> WitnessCheck:
    return WitnessCheck(
        obligation_key="solid_count",
        reader_cs=_read_solids_cs(s),
        verdict_cs=(
            f"    if (__nsol_{s} != 1)\n"
            f"        __post.Add({_cs(oid + ': built geometry does not hold exactly one solid (geometry)')});\n"),
        message="built geometry does not hold exactly one solid (geometry)",
        style="guard")


def _volume_check(s: str, oid: str, expected_mm3: float) -> WitnessCheck:
    # THE VOLUME IS SIGNED (RevitAPI.xml: "Returns the signed volume"). No
    # `abs` is taken here: an inside-out solid is not "roughly the same
    # thing", and a silent Math.Abs would make unknown behavior invisible.
    return WitnessCheck(
        obligation_key="volume",
        reader_cs=f"    double __vmm_{s} = __rvol_{s} * MM(MM(MM(1.0)));\n",
        verdict_cs=(
            f"    if (Math.Abs(__vmm_{s} - {_n(expected_mm3)}) > __tvol_{s})\n"
            f"        __post.Add({_cs(oid + ': solid volume mismatch (geometry)')});\n"),
        message="solid volume mismatch (geometry)",
        style="guard")


def _cap_area_check(s: str, oid: str, expected_mm2: float,
                    axis_parallel: bool, axis=None) -> WitnessCheck:
    return WitnessCheck(
        obligation_key="cap_area",
        reader_cs=_cap_reader_cs(s, axis_parallel, axis),
        verdict_cs=(
            f"    if (Math.Abs(__rcap_{s} - {_n(expected_mm2)}) > __tcap_{s})\n"
            f"        __post.Add({_cs(oid + ': planar cap area mismatch (geometry)')});\n"),
        message="planar cap area mismatch (geometry)",
        style="guard")


#: THE INWARD TESSELLATION MARGIN FOR A CURVED SOLID, as a fraction of the
#: radius of curvature.
#: 🔴 CHOSEN, NOT MEASURED — and here is exactly what was measured and what
#: was chosen.
#:
#: MEASURED 19.08.2026 (Revit 2023, the first live run of
#: `create_solid_revolve`, profile r=1000…1800): the largest bounding-box
#: shortfall was 1.0 mm at radius 1800 mm, i.e. 5.6e-4 of the radius. The
#: chord's sagitta equals r·(1−cos(Δφ/2)) and is PROPORTIONAL to the radius at
#: a fixed tessellation density — hence the margin is set as a fraction of the
#: radius, not in millimeters: a millimeter taken from r=1800 would become a
#: vacuum on a tower with r=30000.
#:
#: CHOSEN: the multiplier itself. Revit's tessellation density is documented
#: nowhere and not promised to stay the same across versions, so 2.0e-3 is
#: the measured 5.6e-4 with a margin of ~3.6×. It will be refined by the first
#: run that hits it; until then this is an UPPER-BOUND ESTIMATE, and it is
#: named as such, not hidden.
#:
#: NOT A VACUUM, and this is checkable: the class of miss the guard is meant
#: to catch — a wrong axis or a wrong radius — is hundreds or thousands of
#: millimeters. At r=1800 the margin is 3.6 mm, 500 times smaller. Outward,
#: NO MARGIN IS GIVEN AT ALL (see `_bbox_check`): tessellation cannot exceed
#: the derived bounding box.
TESSELLATION_INWARD_FRACTION = 2.0e-3

#: 🔴 THE INWARD MARGIN'S FLOOR: THE BOUNDING-BOX SHORTFALL DOES NOT DEPEND
#: ON THE RADIUS. MEASURED 21.08.
#:
#: The fraction-of-radius rule above is correct for LARGE radii and
#: understates it for small ones. A live measurement (Revit 2026, a circle
#: made of two half-arcs, `DirectShape`, the ELEMENT's bounding box after
#: `Regenerate`) gives an almost constant value:
#:
#:     radius mm     X max       Y max    Y shortfall
#:           50      50.000      50.000       0.000
#:          100     100.000     100.000       0.000
#:          200     200.000     198.542       1.458
#:          450     450.000     448.463       1.537
#:          900     900.000     898.477       1.523
#:         2000    2000.000    2000.000       0.000
#:         5000    5000.000    4998.446       1.554
#:
#: TWO OBSERVATIONS, BOTH IMPORTANT:
#: * along X there is NEVER a shortfall — there the extremum lies at the END
#:   of the arc, i.e. at an actual tessellation vertex. A shortfall only
#:   occurs at an extremum INSIDE an arc, which is not a vertex;
#: * the shortfall's size does not grow with the radius: 1.458 at 200 and
#:   1.554 at 5000. This is tessellation with a fixed CHORD TOLERANCE, not a
#:   fixed angle. The zeros at 50, 100, and 2000 are cases where a vertex
#:   landed exactly on the extremum.
#:
#: Hence the law: the inward margin is the MAXIMUM of the radius fraction and
#: this floor. The fraction is kept: at radius 5,000 it gives 10 mm, and
#: dropping it would mean claiming Revit gets more accurate at large radii,
#: which the measurement did not show. 2.0 mm = the largest measured
#: shortfall, 1.554, plus a margin of 1.29x.
BBOX_TESSELLATION_FLOOR_MM = 2.0


def tessellation_inward_mm(radius_mm: float) -> float:
    """The inward bounding-box margin for a curved silhouette. ONE carrier of
    the law."""
    return max(TESSELLATION_INWARD_FRACTION * float(radius_mm or 0.0),
               BBOX_TESSELLATION_FLOOR_MM)


def _curved_radius_mm(region: dict) -> float:
    """The profile's largest radius of curvature; 0.0 means the whole profile
    is straight.

    🔴 WHY. Revit's bounding box understates ONLY where an extremum lies
    INSIDE a curved edge (measured 21.08 for `BBOX_TESSELLATION_FLOOR_MM`:
    along X, where the extrema are the ends of arcs, there is never a
    shortfall). A straight profile needs no margin, and giving it one would
    weaken the check for no reason.

    The largest radius is taken: the radius fraction is the upper half of the
    law, and it must be computed from the shallowest arc. A spline has no
    radius, and for it only the floor is used.
    """
    best = 0.0
    curved = False
    for loop in (list(region.get("outer") or ()) +
                 [e for hole in (region.get("holes") or ()) for e in hole]):
        try:
            p0, p1, bulge = loop
        except (TypeError, ValueError):
            continue
        if C.is_spline(bulge):
            curved = True
            continue
        if not bulge or abs(float(bulge)) < 1e-9:
            continue
        curved = True
        try:
            _c, radius, _st, _sw = C._arc_geometry(p0, p1, float(bulge))
        except Exception:      # noqa: BLE001 — the radius couldn't be derived, the floor will do
            continue
        best = max(best, float(radius))
    return best if curved else 0.0


def _inward_axes(inward_mm) -> tuple[float, float, float]:
    """The inward margin, PER AXIS. A scalar -> the same three numbers, a
    tuple -> itself.

    🔴 WHY PER AXIS, NOT A SINGLE NUMBER (edit of 21.08, caught by reference
    drift). A bounding-box shortfall arises only where an extremum lies
    INSIDE a curved edge. For an extrusion, the extrema along the EXTRUSION
    axis are the flat end faces, actual vertices, and there is never a
    shortfall there (measured: along X, where the arc ends are, the shortfall
    is 0.000 across seven radii).

    A shared margin on all three axes would weaken the end-face check by
    5.8 mm exactly where it must be exact. The scalar is kept as the default
    form: for revolve the margin is legitimate on all three axes.
    """
    if isinstance(inward_mm, (tuple, list)) and len(inward_mm) == 3:
        return (float(inward_mm[0]), float(inward_mm[1]), float(inward_mm[2]))
    v = float(inward_mm or 0.0)
    return (v, v, v)


def _curved_inward_axes(region: dict, plane) -> tuple[float, float, float]:
    """The inward margin along world axes, for a profile lying in its own
    plane.

    Zero for a straight profile: a shortfall arises only on a curved edge, and
    giving a margin where there is no curvature would weaken the check for
    free.
    """
    radius = _curved_radius_mm(region)
    if not radius:
        return (0.0, 0.0, 0.0)
    allow = tessellation_inward_mm(radius)
    e1 = (1.0, 0.0, 0.0)
    e2 = (0.0, 1.0, 0.0)
    if plane is not None:
        try:
            from kir.plane import frame
            # `frame` returns FOUR values: origin, e1, e2, normal. Unpacking
            # into three was silently caught by the `except` below and
            # returned the plan frame — i.e. the "per axis" fix on a tilted
            # plane would not have worked while looking like it did. Caught
            # by the control on the vertical case.
            _origin, e1, e2, _n3 = frame(plane)
        except Exception:      # noqa: BLE001 — no frame, falls back to the plan one
            pass
    return tuple(allow * math.sqrt(e1[k] * e1[k] + e2[k] * e2[k])
                 for k in range(3))      # type: ignore[return-value]


def _bbox_check(s: str, oid: str, box: tuple, reader_cs: str,
                inward_mm=0.0, outward_mm: float = 0.0) -> WitnessCheck:
    """Bounding-box check. THE READER COMES FROM THE EMITTER, not built here:
    which ELEMENT and which of ITS bounding boxes to treat as the operation's
    body is the op's decision, not the shared check's; only the comparison
    against the derived reference lives here.

    🔴 THE TOLERANCE IS ASYMMETRIC, AND THIS IS A GEOMETRIC LAW, NOT
    CAUTION. Revit computes the bounding box from the TESSELLATED
    representation, and a facet's chord NEVER extends past its own arc — so a
    curved solid's bounding box can only come out SMALLER than the true one,
    a shortfall is legitimate, and an overshoot cannot be. So outward the
    tolerance stays rigid (`__dt`), while inward `inward_mm` is added, which
    the op passes in, because the facet's sagitta is proportional to the
    radius of curvature, which is known only there.

    🔴 `outward_mm` IS THE MIRROR OF THE SAME LAW, AND IT IS NOT SYMMETRY FOR
    ITS OWN SAKE (the free-form wave, 20.08.2026). For a prism and a sector
    the reference bounding box is EXACT, so outward the tolerance is rigid.
    For a blend it is a LOWER BOUND: the side surface between the profiles is
    built by Revit ("blending smoothly"), and a side that bulges outward
    legitimately extends past the union of the profiles. Keeping a rigid
    upper bound there would mean flagging CORRECT geometry as wrong. A
    shortfall there is still a violation, though: it would mean the end face
    is out of place — and an op that passes `outward_mm` is required to have
    a SEPARATE end-face witness, otherwise it weakened the check and replaced
    it with nothing.

    MEASURED 19.08, THE FIRST LIVE RUN OF `create_solid_revolve` (profile
    r=1000…1800, h=2400, axis x=1.3e6, Revit 2023):

        sector  90°  X 0..1800        Y 0..1800          matched EXACTLY
        sector 180°  X -1800..1800    Y 0..1800          matched EXACTLY
        sector 270°  X -1799.3..1800  Y -1800..1799.3    shortfall 0.7 mm
        sector 359°  X -1799..1800    Y -1799..1799.8    shortfall 1.0 mm
        full   360°  X -1800..1800    Y -1800..1800      matched EXACTLY

    The pattern explains EVERYTHING: at 90° and 180° the extrema lie on FLAT
    end faces and are captured exactly; at 270° and 359° they fall on the
    MIDDLE of an arc, where the chord falls short. At 360° there are no end
    faces, but the extrema again fall on the cardinal directions, where
    tessellation places its nodes.

    The `__dt` in force = vertex precision + emission quantum ≈ 0.25 mm, i.e.
    THREE TIMES smaller than the observed shortfall — and that is exactly why
    the first live run rolled back a CORRECTLY built solid (the volume at
    270° matched to the fourth digit: 12.6669 m³ against the closed-form
    formula). The bounding-box formula (`_sector_bbox`) was CORRECT all along
    and was not changed."""
    x0, y0, z0, x1, y1, z1 = box
    _inx, _iny, _inz = _inward_axes(inward_mm)
    # THE ZERO TERM IS NOT PRINTED AT ALL: `+ 0 +` in the text would shift
    # the bytes of EVERY existing body, and the parity ratchet would turn red
    # on an edit that does not touch them. Absence remains absence.
    _out = "" if not outward_mm else " + " + _n(outward_mm)
    _outm = "" if not outward_mm else " - " + _n(outward_mm)
    # 🔴 THE VIOLATION CARRIES NUMBERS, AND THIS WAS BOUGHT BY THE LIVE RUN OF
    # 19.08. The first live run of `create_solid_revolve` in history failed
    # exactly here — «bbox extents mismatch (geometry)», and NOTHING ELSE.
    # For the caps, in the same operation, the receipt gives
    # `cap_area_mm2_expected` and `..._measured` side by side, while for the
    # bounding box the author got a line without a single value. The
    # director searched for the cause by bisecting over the unroll angles —
    # that is, paid with live runs for what the guard already held in its
    # hands and did not say.
    #
    # An assertion that ROLLS BACK the model is obligated to return the
    # expected and the measured as numbers: without that, «fix the geometry»
    # is advice with no address. One `__post.Add` is kept deliberately: the
    # vacuum analysis looks for EXACTLY it, and splitting it into several
    # calls would weaken the guard of guards.
    expected_ru = (f"ожидалось X {x0:.1f}..{x1:.1f}"
                   f" · Y {y0:.1f}..{y1:.1f} · Z {z0:.1f}..{z1:.1f}")
    got_cs = (
        f'"; получено X " + Math.Round(MM(__bb_{s}.Min.X), 1) + ".." '
        f'+ Math.Round(MM(__bb_{s}.Max.X), 1)\n'
        f'          + " · Y " + Math.Round(MM(__bb_{s}.Min.Y), 1) + ".." '
        f'+ Math.Round(MM(__bb_{s}.Max.Y), 1)\n'
        f'          + " · Z " + Math.Round(MM(__bb_{s}.Min.Z), 1) + ".." '
        f'+ Math.Round(MM(__bb_{s}.Max.Z), 1)\n'
        f'          + " · допуск наружу " + Math.Round(__dt_{s}, 2) '
        f'+ " мм, внутрь " + Math.Round({_n(max(_inx, _iny, _inz))} + __dt_{s}, 2) + " мм"')
    return WitnessCheck(
        obligation_key="bbox",
        reader_cs=reader_cs,
        verdict_cs=(
            f"    if (__bb_{s} == null) __post.Add({_cs(oid + ': нет BoundingBox')});\n"
            f"    else if (MM(__bb_{s}.Min.X) < {_n(x0)}{_outm} - __dt_{s} || "
            f"MM(__bb_{s}.Min.X) > {_n(x0)} + {_n(_inx)} + __dt_{s} ||\n"
            f"             MM(__bb_{s}.Max.X) > {_n(x1)}{_out} + __dt_{s} || "
            f"MM(__bb_{s}.Max.X) < {_n(x1)} - {_n(_inx)} - __dt_{s} ||\n"
            f"             MM(__bb_{s}.Min.Y) < {_n(y0)}{_outm} - __dt_{s} || "
            f"MM(__bb_{s}.Min.Y) > {_n(y0)} + {_n(_iny)} + __dt_{s} ||\n"
            f"             MM(__bb_{s}.Max.Y) > {_n(y1)}{_out} + __dt_{s} || "
            f"MM(__bb_{s}.Max.Y) < {_n(y1)} - {_n(_iny)} - __dt_{s} ||\n"
            f"             MM(__bb_{s}.Min.Z) < {_n(z0)}{_outm} - __dt_{s} || "
            f"MM(__bb_{s}.Min.Z) > {_n(z0)} + {_n(_inz)} + __dt_{s} ||\n"
            f"             MM(__bb_{s}.Max.Z) > {_n(z1)}{_out} + __dt_{s} || "
            f"MM(__bb_{s}.Max.Z) < {_n(z1)} - {_n(_inz)} - __dt_{s})\n"
            f"        __post.Add({_cs(oid + ': bbox extents mismatch (geometry) — ' + expected_ru)}\n"
            f"          + {got_cs});\n"),
        message="bbox extents mismatch (geometry)",
        style="else_block")


def _readback(s: str, oid: str, kind: str, op: dict, expected: dict,
              *, identity_version: str | None = None) -> str:
    """Receipt. Its own, not `_readback_block`: the shared block reports
    LocationCurve and type_name, which DirectShape does not have BY
    CONSTRUCTION.

    THE RAW PAIR (expected/measured) travels OUTWARD deliberately: the
    residual error of `Solid.Volume` itself on curved surfaces is nowhere
    documented, and the first live run is obligated to MEASURE it, not
    estimate it. Without these two numbers in the receipt, there would be
    nothing to measure.
    """
    lines = [
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n",
        f"    var __rb = new Dictionary<string, object>();\n",
        (f"    try {{ __rb[\"id\"] = __el_{s}.Id.ToString(); }} catch {{ __rb[\"id\"] = null; }}\n"
         if identity_version is not None else
         f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"),
        f"    __rb[\"name\"] = __el_{s}.Name;\n",
        f"    __rb[\"category\"] = {_cs(op['category'])};\n",
        f"    __rb[\"kind\"] = {_cs(kind)};\n",
        f"    __rb[\"solids\"] = __nsol_{s};\n",
        # 🔴 AN UNCOMPUTED VALUE IS PRINTED AS `null`, NOT AS ZERO. The live
        # run of the twisted shape on 20.08.2026 produced a receipt with
        # `volume_mm3_expected: 0` against a measured 1.03e11 — and this
        # reads as «expected zero volume and got a mountain», that is, as a
        # GROSS ERROR, when in fact the volume simply WAS NOT COMPUTED: Revit
        # chooses the side surface between the profiles itself, and it
        # cannot be predicted (this is a named absence, see the block on the
        # lateral surface above). Zero in place of the unknown is a defect
        # shape we have on record; here it sat as a stub right in the code:
        # `{"volume_mm3": 0.0, ...}`.
        (f"    __rb[\"volume_mm3_expected\"] = {_n(expected['volume_mm3'])};\n"
         if expected.get("volume_mm3") is not None else
         f"    __rb[\"volume_mm3_expected\"] = null;\n"
         f"    __rb[\"volume_expectation_ru\"] = "
         f"{_cs(expected.get('volume_unknown_ru') or 'объём не предсказывается')};\n"),
        f"    __rb[\"volume_mm3_measured\"] = __rvol_{s} * MM(MM(MM(1.0)));\n",
        (f"    __rb[\"volume_tolerance_mm3\"] = __tvol_{s};\n"
         if expected.get("volume_mm3") is not None else ""),
        f"    __rb[\"profile_area_mm2\"] = {_n(expected['area_mm2'])};\n",
    ]
    # THE SAME LAW APPLIED TO VOLUME ABOVE, and for the same reason: for a
    # sweep, the cap witness does NOT ALWAYS travel (see `emit_solid_sweep` —
    # a segment perpendicular to the first one can produce a side face whose
    # normal runs along the cap's, and the sum would stop being a sum of
    # caps). Printing `cap_area_mm2_expected: 0` in that case against a
    # measured zero would mean passing off «did not look» as «matched».
    if expected.get("cap_area_mm2") is None:
        lines += [
            f"    __rb[\"cap_area_mm2_expected\"] = null;\n",
            f"    __rb[\"cap_expectation_ru\"] = "
            f"{_cs(expected.get('cap_unknown_ru') or 'площадь торцов не проверялась')};\n",
        ]
    else:
        lines += [
            f"    __rb[\"cap_area_mm2_expected\"] = {_n(expected['cap_area_mm2'])};\n",
            f"    __rb[\"cap_area_mm2_measured\"] = __rcap_{s};\n",
            f"    __rb[\"cap_area_tolerance_mm2\"] = __tcap_{s};\n",
        ]
    if expected.get("cap_semantics"):
        lines.append(
            f"    __rb[\"cap_area_meaning\"] = {_cs(expected['cap_semantics'])};\n")
    lines += [
        f"    __rb[\"vertex_tolerance_mm\"] = MM(doc.Application.VertexTolerance);\n",
        f"    __rb[\"bim_semantics\"] = \"none\";\n",
        f"    __rb[\"has_type\"] = false;\n",
        f"    __rb[\"schedulable_as_building_element\"] = false;\n",
        f"    __rb[\"human_editable\"] = false;\n",
        f"    __rb[\"honest_label_written\"] = __lbl_{s};\n",
        f"    __rb[\"warning\"] = {_cs('Параметрическое тело в DirectShape — геометрия без BIM-смысла: у элемента нет типа и параметров, в спецификации он не попадёт как строительный элемент, и вручную его не отредактировать. Это не стена/перекрытие/кровля, даже если объём совпадает.')};\n",
        _stamp_readback(f"__el_{s}"),
        (element_identity_readback_cs(f"__el_{s}", revit_version=identity_version)
         if identity_version is not None else ""),
        f"    __results[{_cs(oid)}] = __rb;\n}}",
    ]
    return "".join(lines)


# ── extrusion ─────────────────────────────────────────────────────────────

def emit_solid_extrusion(op: dict, ver: str, stamp: str,
                         isolation: str = "atomic") -> tuple:
    """CONTOUR profile + height -> Solid -> DirectShape.

    There is no version fork: everything named here is measured 6/6 (the
    table is in the header of ops_solid.py).

    THE VOLUME IS DERIVED, NOT MEASURED APPROXIMATELY. A prism over a flat
    region: V = A·h, where A is the area of the region computed by Green's
    integral over the boundary in CLOSED FORM (arcs enter via the exact
    circular-segment formula, not sampling). Openings are subtracted
    exactly, because CONTOUR has already proven their strict interiority and
    pairwise non-intersection.

    SURFACE AREA (needed to derive the tolerance) = 2A + P·h, where P is the
    full length of the boundary (the outer ring plus all openings): the
    lateral surface of a prism over a curve of length P and height h equals
    exactly P·h for any profile, including one with arcs.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    height = float(op["height_mm"])
    base_z = op.get("base_z_mm")

    m = C.region_measures(region)
    area = m["area_mm2"]
    perim = m["perimeter_mm"]
    volume = area * height
    surface = 2.0 * area + perim * height
    cap_area = 2.0 * area
    x0, y0, x1, y1 = C.region_bbox(region)
    z0 = 0.0 if base_z is None else float(base_z)
    # SKETCH PLANE (21.08.2026). `None` — the entire previous branch, down
    # to the byte.
    plane = op.get("plane")

    decl, head, tail = _shell_cs(s, oid, member, op["name"], stamp, isolation)
    loops_cs = _loops_cs(region, s)
    if plane is None:
        # ABSENCE REMAINS ABSENCE: without `base_z_mm`, not a single
        # transform is printed, and the emission is byte-for-byte the same
        # as it would be without the parameter.
        transform = (None if base_z is None
                     else f"Transform.CreateTranslation(new XYZ(0, 0, U({_n(base_z)})))")
        frame_cs = ""
        dir_cs = "XYZ.BasisZ"
        cap_axis = None
        box = (x0, y0, z0, x1, y1, z0 + height)
    else:
        frame_decl, transform = _plane_frame_cs(s, plane)
        frame_cs = frame_decl + "\n"
        _o, _x, _y, _n3 = PL.frame(plane)
        # THE EXTRUSION DIRECTION IS THE PLANE'S NORMAL, NOT +Z, AND THIS IS
        # NOT DECORATION. Leave `XYZ.BasisZ` here, and the body would become
        # an OBLIQUE prism: the volume would drop to A·h·|N·Z| (to ZERO on a
        # vertical wall face), the caps would stop being flat faces with
        # normal ±N, and the volume witness would blame Revit for
        # arithmetic that is not its own.
        dir_cs = f"new XYZ({_n(_n3[0])}, {_n(_n3[1])}, {_n(_n3[2])})"
        cap_axis = _n3
        box = _plane_profile_box(plane, (region, region), (0.0, height))
    _within_world_extent(box, oid, "plane" if plane is not None else "base_z_mm",
                         "места эскиза и габарита профиля")
    create = (
        f"// create_solid_extrusion {cs_line_comment_fragment(oid)} — "
        f"профиль {len(region['outer'])} рёбер, {len(region['holes'])} проёмов, "
        f"площадь {area:.1f} мм², объём {volume:.1f} мм³\n"
        f"{head}\n"
        f"{loops_cs}\n"
        f"{frame_cs}"
        f"{_transform_cs(region, s, transform)}\n"
        f"__sol_{s} = GeometryCreationUtilities.CreateExtrusionGeometry("
        f"__lps_{s}, {dir_cs}, U({_n(height)}));\n"
        f"{tail}\n"
        f"{_derived_tolerances_cs(s, oid, isolation, surface_mm2=surface, min_feature_vol_mm3=m['min_area_mm2'] * height, cap_boundary_mm=2.0 * perim, min_feature_cap_mm2=2.0 * m['min_area_mm2'])}")

    checks = [
        _solid_count_check(s, oid),
        # THE PLANE DOES NOT CHANGE THE VOLUME, AND THIS IS A PROOF, NOT A
        # HOPE: the plane's frame is a RIGID MOTION (a right-handed
        # orthonormal triad), and a rigid motion preserves volume and area.
        # For the same reason, neither the surface area nor the perimeter
        # from which the tolerances are derived changes.
        _volume_check(s, oid, volume),
        # The prism's caps are FLAT faces with normal along the EXTRUSION
        # AXIS, and only they: the lateral surface of a right prism contains
        # this axis by construction. Without a plane, the axis is world Z
        # and the previous text is printed.
        _cap_area_check(s, oid, cap_area, axis_parallel=True, axis=cap_axis),
        # An inward margin — only for a CURVED profile, and by a measured
        # law. Before 21.08 a hard zero stood here, and the very first
        # circle made of two half-arcs (radius 900) rolled back the
        # transaction: Revit returned 898.477 against an exact reference of
        # 900. The reference was right; it is Revit that undershoots the
        # bounding box. An inward margin — only for a CURVED profile and
        # ONLY ALONG THE AXES OF THE PROFILE'S PLANE. Along the extrusion
        # axis, the extrema are the flat caps, and there is never an
        # undershoot there; a blanket margin would weaken that check by
        # exactly 5.8 mm right where it is obligated to be exact.
        #
        # The per-axis share is computed from the profile's frame:
        # `sqrt(e1²+e2²)` for each world axis. For a horizontal profile that
        # is (1, 1, 0) — exactly what is needed; for a tilted plane the
        # world axes are mixed, and the formula spreads the margin in
        # proportion to how much EACH of them "sees" the profile's plane.
        _bbox_check(s, oid, box,
                    f"    var __bb_{s} = __el_{s}.get_BoundingBox(null);\n",
                    inward_mm=_curved_inward_axes(region, plane)),
    ]
    readback = _readback(s, oid, "direct_shape_solid_extrusion", op, {
        "volume_mm3": volume, "area_mm2": area, "cap_area_mm2": cap_area})
    return decl, create, checks, readback


# ── revolve ───────────────────────────────────────────────────────────────

def _cos_sin_deg(deg: float) -> tuple[float, float]:
    """(cos, sin) of the angle IN DEGREES, EXACT at multiples of 90°.

    Not pedantry: the angle arrives from the author in degrees, and
    `math.cos(math.pi/2)` gives 6.1e-17, which is why the bounding box of a
    quarter turn was printed in C# as `6.123233995736766e-14` instead of
    zero. The number is harmless (it is 6·10⁻¹⁴ mm), but a witness reference
    seeded with garbage reads as an error, and it can no longer be compared
    by eye against the drawing. Multiples of 90° are known exactly — so
    they must be printed exactly too.
    """
    quarter, rest = divmod(deg, 90.0)
    if abs(rest) < 1e-12:
        return [(1.0, 0.0), (0.0, 1.0), (-1.0, 0.0), (0.0, -1.0)][int(quarter) % 4]
    rad = math.radians(deg)
    return math.cos(rad), math.sin(rad)


def _sector_bbox(r0: float, r1: float, sweep_deg: float) -> tuple:
    """Bounding box of an annular sector {ρ∈[r0,r1], φ∈[0,sweep]} in plan.

    DERIVATION. For a fixed φ, the function ρ·cos φ is monotonic in ρ, so
    its extremum in ρ lies at an endpoint of the segment [r0, r1]; for a
    fixed ρ, the extrema in φ lie either at the ends of the range or at the
    cardinal directions that fall inside it. So the global extrema are
    contained in a FINITE set (two radii) × (endpoints plus cardinal
    angles), and enumerating it exactly is the same thing as solving the
    problem. This is exactly the technique by which `contour.edges_bbox`
    takes the extrema of an arc.
    """
    angles = [0.0, sweep_deg]
    angles += [c for c in (90.0, 180.0, 270.0) if c <= sweep_deg]
    xs, ys = [], []
    for radius in (r0, r1):
        for angle in angles:
            cos_a, sin_a = _cos_sin_deg(angle)
            xs.append(radius * cos_a)
            ys.append(radius * sin_a)
    return min(xs), min(ys), max(xs), max(ys)


def emit_solid_revolve(op: dict, ver: str, stamp: str,
                       isolation: str = "atomic") -> tuple:
    """CONTOUR profile, revolved around a vertical axis -> DirectShape.

    THE VOLUME IS DERIVED FROM FUBINI'S THEOREM, NOT TAKEN FROM A REFERENCE
    BOOK. A solid of revolution in cylindrical coordinates is
    {(ρ,φ,z) : (ρ,z) ∈ Ω, φ ∈ [0,θ]}, and the volume element equals
    ρ·dρ·dφ·dz. The integral over φ separates:

        V = ∫₀^θ dφ ∬_Ω ρ dρ dz = θ · ∬_Ω ρ dA = θ · M

    where M = ∬x dA is the profile's first moment about the axis. This is
    exactly Pappus's first theorem (V = 2π·x̄·A at θ=2π, since M = x̄·A), but
    written so that a partial revolution follows from the SAME derivation,
    not a separate assumption. The condition for applicability — the
    profile does not cross the axis — is not an assumption here: Revit
    ITSELF requires x ≥ 0, and we check this with an exact bounding box that
    accounts for arc extrema, refusing before emission.

    The moment M is computed as a boundary integral ∮(x²/2)dy in closed
    form (contour.edge_measures) — with arcs, with openings, without
    sampling.

    SURFACE AREA (to derive the tolerance) — Pappus's second theorem by the
    same reasoning: lateral surface = θ·∮x ds, plus two flat caps of area A
    each, when the revolution is incomplete.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    sweep_deg = float(op["sweep_deg"])
    sweep = math.radians(sweep_deg)
    axis = op["axis_xy_mm"]
    ax, ay = float(axis[0]), float(axis[1])
    base_z = op.get("base_z_mm")
    z_base = 0.0 if base_z is None else float(base_z)

    rx0, ry0, rx1, ry1 = C.region_bbox(region)
    if rx0 < 0.0:
        # REVIT'S LAW, NOT OUR TASTE: RevitAPI.xml, CreateRevolvedGeometry —
        # «The loops must lie on the 'right' side of the z axis (where
        # x >= 0)». A profile crossing the axis would produce either an
        # exception or — worse — a body to which Fubini's theorem does not
        # apply, and the volume witness would be comparing against a number
        # that means nothing.
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name="profile",
            got=round(rx0, 2), expected=">= 0",
            message_ru=("profile: контур вращения заходит за ось "
                        f"(минимальный радиус {rx0:.1f} мм < 0). Ось — "
                        "вертикаль через axis_xy_mm, x контура есть радиус "
                        "от неё, поэтому отрицательным он быть не может"))])

    m = C.region_measures(region)
    area = m["area_mm2"]
    moment = m["moment_x_mm3"]
    volume = sweep * moment
    full_turn = sweep_deg >= 360.0
    surface = sweep * m["x_ds_mm2"] + (0.0 if full_turn else 2.0 * area)
    # CAPS ALWAYS EXIST — AS A VALUE, NOT AS A FACE. For a sector their area
    # equals twice the profile's area; for a FULL revolution there must be
    # no caps at all, and the expected value is ZERO. The latter is not
    # «nothing to check» but a substantive check of WHETHER THE REVOLUTION
    # CLOSED: have Revit build a wedge instead of a ring, and 2·A shows up
    # where zero should be. A conditional witness here would leave the most
    # likely 360° failure with no reader at all.
    cap_area = 0.0 if full_turn else 2.0 * area

    sx0, sy0, sx1, sy1 = _sector_bbox(rx0, rx1, sweep_deg)
    # THE BODY'S WORLD BOUNDING BOX — BY NAME, NOT AS AN EXPRESSION INLINE
    # IN THE CALL. The value is now needed by two consumers: the
    # bounding-box witness and the working-extent guard. Two records of one
    # number drift apart silently — the same argument by which
    # `COORD_LIMIT_MM` and `MIN_EXTENT_MM` live in this tree.
    world_box = (ax + sx0, ay + sy0, z_base + ry0,
                 ax + sx1, ay + sy1, z_base + ry1)
    _within_world_extent(world_box, oid, "axis_xy_mm",
                         "положения оси и габарита профиля")

    decl, head, tail = _shell_cs(s, oid, member, op["name"], stamp, isolation)
    loops_cs = _loops_cs(region, s)
    # TRANSITION FROM THE SKETCH PLANE TO THE REVOLUTION PLANE. The
    # right-handed triad (X, Y, Z) = ((1,0,0), (0,0,1), (0,-1,0)) maps
    # (u, v, 0) to (axis.x + u, axis.y, base_z + v) — that is, radius along
    # world +X, elevation along world +Z, exactly as Revit's frame requires.
    transform = f"__tf_{s}"
    frame_cs = (
        f"Transform __tf_{s} = Transform.Identity;\n"
        f"__tf_{s}.Origin = P({_n(ax)}, {_n(ay)}, {_n(z_base)});\n"
        f"__tf_{s}.BasisX = new XYZ(1, 0, 0);\n"
        f"__tf_{s}.BasisY = new XYZ(0, 0, 1);\n"
        f"__tf_{s}.BasisZ = new XYZ(0, -1, 0);\n"
        f"Frame __fr_{s} = new Frame(P({_n(ax)}, {_n(ay)}, {_n(z_base)}), "
        f"new XYZ(1, 0, 0), new XYZ(0, 1, 0), new XYZ(0, 0, 1));")
    create = (
        f"// create_solid_revolve {cs_line_comment_fragment(oid)} — "
        f"профиль {len(region['outer'])} рёбер, {len(region['holes'])} проёмов, "
        f"поворот {sweep_deg:g}°, объём {volume:.1f} мм³\n"
        f"{head}\n"
        f"{loops_cs}\n"
        f"{frame_cs}\n"
        f"{_transform_cs(region, s, transform)}\n"
        f"__sol_{s} = GeometryCreationUtilities.CreateRevolvedGeometry("
        f"__fr_{s}, __lps_{s}, 0.0, {_n(sweep)});\n"
        f"{tail}\n"
        + _derived_tolerances_cs(
            s, oid, isolation,
            surface_mm2=surface,
            # The volume of the smallest declared part is θ·(its moment).
            # The moment, not «area × radius»: the profile is allowed to
            # TOUCH the axis, and an estimate via the bounding radius would
            # be an upper-bound estimate, that is, an inflated vacuum
            # threshold.
            min_feature_vol_mm3=sweep * m["min_moment_x_mm3"],
            cap_boundary_mm=2.0 * m["perimeter_mm"],
            min_feature_cap_mm2=2.0 * m["min_area_mm2"]))

    checks = [
        _solid_count_check(s, oid),
        _volume_check(s, oid, volume),
        # The sector's caps are FLAT faces with a normal PERPENDICULAR to
        # the axis. A horizontal edge of the profile produces a flat ring
        # with a normal ALONG the axis — that is not a cap, and the normal
        # filter excludes it.
        _cap_area_check(s, oid, cap_area, axis_parallel=False),
    ]
    # The inward margin — by the LARGEST radius of the profile: it is on
    # the most distant arc that the chord's sagitta is maximal, and it is
    # its extremum that lands in the bounding box.
    checks.append(_bbox_check(
        s, oid, world_box,
        f"    var __bb_{s} = __el_{s}.get_BoundingBox(null);\n",
        inward_mm=tessellation_inward_mm(rx1)))

    readback = _readback(s, oid, "direct_shape_solid_revolve", op, {
        "volume_mm3": volume, "area_mm2": area, "cap_area_mm2": cap_area,
        "cap_semantics": ("полный оборот: торцов быть не должно, ожидается ноль"
                          if full_turn else
                          "сектор: два плоских торца, ожидается удвоенная "
                          "площадь профиля")})
    return decl, create, checks, readback


# ── BLEND: TRANSITION BETWEEN TWO PROFILES (free-form wave, 20.08.2026) ────
#
# WHY, IN THE OWNER'S WORDS: "in Revit you can do complex geometric things
# almost like in Grasshopper and Rhino, and I want to achieve that goal."
# Extrusion and revolution are a prism and a solid of revolution, that is,
# ONE profile. The transition between TWO different profiles is the first
# real free form: it is used to make twisted towers, tapering supports,
# double-curvature facade panels.
#
# 🔴 WHY THIS OP TRAVELS, EVEN THOUGH THE HEADER OF `ops_solid.py` REFUSED
# BLEND. The refusal was CORRECT by its own argument and remains so on its
# own subject: it is about VOLUME. Verbatim: "none of the three has a
# closed-form volume; linear interpolation (the Simpson prismatoid) is
# exact only for a ruled lateral surface, and Revit does not promise it
# will be one." This remains true, and there is no volume witness here.
# But volume is not the only value Revit has no right to move.
#
# WHAT REVIT IS OBLIGATED TO CARRY EXACTLY, AND THIS IS READ FROM ITS OWN
# DOCUMENTATION: `CreateBlendGeometry` — "Creates a solid by blending two
# closed curve loops lying in non-coincident planes." It smooths the
# LATERAL surface ("blending smoothly between the profiles" for the
# neighboring `CreateLoftGeometry`), while the profiles themselves are the
# input, and they become the CAPS. A cap is flat, its area is computed by
# Green's integral in closed form, and it is obligated to match. Hence two
# honest witnesses, neither of which recomputes our own input:
#
#   * the area of the FLAT caps == A(bottom) + A(top), closed form;
#   * EVERY declared vertex of BOTH profiles lies on the boundary of the
#     built body (a minimum of `Face.Project` over the faces) — a value
#     that was not in the input: Revit computes it from ITS OWN boundary,
#     and it will fail if it simplified, dropped, or shifted the profile.
#
# 🔴 WHAT THESE WITNESSES DO NOT CATCH — STATED HERE, NOT PASSED OVER IN
# SILENCE. The lateral surface between the profiles IS PINNED DOWN BY
# NOTHING. Revit is free to run it along a straight ruler, bow it outward,
# or bow it inward — all three outcomes pass both witnesses, because both
# look at the CAPS. This is a named absence, and it is obligated to reach
# the model through `named_absences`, not stay in a comment: a green
# triple with an unknown lateral surface is honest on each axis and
# incomplete as a whole. WHAT THIS OPENS UP: a live measurement of
# `Solid.Volume` against the Simpson prismatoid over a dozen profile pairs
# — if it converges, the lateral surface is ruled, and then the volume
# witness travels too, and the bounding box becomes exact.
#
# THE BOUNDING BOX HERE IS ASYMMETRIC IN THE OPPOSITE DIRECTION FROM
# REVOLUTION, AND THIS IS NOT A TYPO. For a revolution sector, Revit
# computes the bounding box by tessellation, and the chord does not go
# past the arc — so an UNDERSHOOT is legitimate there. Here it is the
# reverse: the bounding box over the union of the profiles is a LOWER
# bound, because a lateral surface bowed outward legitimately exceeds it.
# So an OVERSHOOT is legitimate, while an undershoot would mean a cap is
# out of place — and the first witness already catches that. The
# one-sidedness is named, not hidden in the tolerance.

#: How far the lateral surface is allowed to go beyond the profiles'
#: bounding box.
#: ⚠️ NOT A NUMBER, A FORMULA, and it is derived, not assigned: Revit does
#: not promise ruledness, but it does promise that the body is a
#: TRANSITION between two profiles, that is, its cross-section at any
#: height lies between them by construction. Outward, the lateral surface
#: can go no farther than the distance between the profiles: farther than
#: that it would no longer be a transition. We take the diagonal of the
#: combined bounding box — an upper bound on this distance, the only one
#: that can be derived from the input.
def _blend_outward_mm(box_lo: tuple, box_hi: tuple, height_mm: float) -> float:
    x0 = min(box_lo[0], box_hi[0]); y0 = min(box_lo[1], box_hi[1])
    x1 = max(box_lo[2], box_hi[2]); y1 = max(box_lo[3], box_hi[3])
    return math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + height_mm ** 2)


def _profiles_on_boundary_check(s: str, oid: str, points: list) -> WitnessCheck:
    """EVERY declared vertex of both profiles lies on the boundary of the
    body.

    WHAT THIS PROVES AND WHY IT CAN FAIL. The distance is computed by
    `Face.Project` over faces READ FROM THE BUILT element — not from our
    own variable and not from our own sample. Revit is free to simplify the
    profile, merge nearby vertices, drop a ring; each such outcome pulls
    the distance apart and turns the witness red. This is exactly what
    distinguishes the check from confirming a setter.

    THE TOLERANCE IS THE SAME `__dt` AS FOR THE OTHERS, AND WITHOUT A
    MULTIPLIER: here the value is LINEAR (a distance), not an area or a
    volume, so there is nothing to multiply δ by in the geometry, and no
    reason to.

    BOUNDARY CASE: `Face.Project` on some faces is allowed to return null
    (a point outside the face's domain) — this is NOT a violation but a
    fact about THAT face, so the MINIMUM is taken over all faces. If no
    face answered, the minimum stays infinite, and this is a separate
    violation with separate text: «границу прочитать не удалось» and
    «точка не на границе» are different failures.
    """
    pts_cs = ", ".join(f"new XYZ(U({_n(x)}), U({_n(y)}), U({_n(z)}))"
                       for x, y, z in points)
    return WitnessCheck(
        obligation_key="profiles_on_boundary",
        reader_cs=(
            # 🔴 THE BODY IS TAKEN FROM THE ELEMENT, NOT FROM OUR OWN
            # VARIABLE. `__sol_` is what the FACTORY returned; between it
            # and the element stands `SetShape`, and Revit is entitled to
            # transform the body. A witness reading `__sol_` would be
            # checking our own object and would pass even if something
            # else landed in the model. The first draft of this witness did
            # exactly that — caught by a control, not by reasoning.
            f"    double __pw_{s} = -1.0;\n"
            f"    bool __pr_{s} = true;\n"
            f"    Solid __bs_{s} = null;\n"
            f"    var __bge_{s} = __el_{s}.get_Geometry(new Options());\n"
            f"    if (__bge_{s} != null)\n"
            f"        foreach (GeometryObject __bgo_{s} in __bge_{s})\n"
            f"        {{\n"
            f"            Solid __bc_{s} = __bgo_{s} as Solid;\n"
            f"            if (__bc_{s} != null && __bc_{s}.Faces.Size > 0) {{ __bs_{s} = __bc_{s}; break; }}\n"
            f"            GeometryInstance __bgi_{s} = __bgo_{s} as GeometryInstance;\n"
            f"            if (__bgi_{s} != null)\n"
            f"                foreach (GeometryObject __bg2_{s} in __bgi_{s}.GetInstanceGeometry())\n"
            f"                {{\n"
            f"                    Solid __bc2_{s} = __bg2_{s} as Solid;\n"
            f"                    if (__bc2_{s} != null && __bc2_{s}.Faces.Size > 0) {{ __bs_{s} = __bc2_{s}; break; }}\n"
            f"                }}\n"
            f"        }}\n"
            f"    if (__bs_{s} == null) __pr_{s} = false;\n"
            f"    else\n    {{\n"
            f"        var __pp_{s} = new List<XYZ> {{ {pts_cs} }};\n"
            f"        foreach (XYZ __px_{s} in __pp_{s})\n        {{\n"
            f"            double __pb_{s} = double.MaxValue;\n"
            f"            foreach (Face __pf2_{s} in __bs_{s}.Faces)\n"
            f"            {{\n"
            f"                try {{ IntersectionResult __pi_{s} = __pf2_{s}.Project(__px_{s});\n"
            f"                       if (__pi_{s} != null) {{ double __pd_{s} = MM(__pi_{s}.Distance);\n"
            f"                           if (__pd_{s} < __pb_{s}) __pb_{s} = __pd_{s}; }} }}\n"
            f"                catch {{ }}\n"
            f"            }}\n"
            f"            if (__pb_{s} == double.MaxValue) __pr_{s} = false;\n"
            f"            else if (__pb_{s} > __pw_{s}) __pw_{s} = __pb_{s};\n"
            f"        }}\n    }}\n"),
        verdict_cs=(
            f"    if (!__pr_{s})\n"
            f"        __post.Add({_cs(oid + ': profile vertex could not be projected onto the built boundary (geometry)')});\n"
            f"    else if (__pw_{s} > __dt_{s})\n"
            f"        __post.Add({_cs(oid + ': declared profile does not lie on the built boundary (geometry)')});\n"),
        message="declared profile does not lie on the built boundary (geometry)",
        style="guard")


def emit_solid_blend(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple:
    """Two CONTOUR profiles at different elevations -> Solid -> DirectShape.

    There is no version fork: `CreateBlendGeometry(CurveLoop, CurveLoop,
    ICollection<VertexPair>, SolidOptions)` is measured 6/6 by the
    compilation probe of 20.08.2026; the CS0117 (invented member) and
    CS0200 (write to read-only) controls both discriminate.

    🔴 `null`, NOT AN EMPTY LIST — AND THIS WAS BOUGHT BY THE LIVE REFUSAL
    OF 20.08.2026. The first draft passed `new List<VertexPair>()`,
    reasoning like this: "both shapes assemble 6/6; an empty list means
    'the correspondence is chosen by Revit,' while `null` would read as
    'forgot to pass it.'" Live, this produced a raw Revit exception, not
    our own refusal:

        The input pVertexPairs are invalid.
        Parameter name: pVertexPairs

    The Autodesk contract speaks precisely about `null`, verbatim
    (RevitAPI.xml, param `vertexPairs`, all six versions): "This input
    specifies how the two profile loops should be connected. **If null,
    the function chooses vertex connections that will result in a
    geometrically reasonable blend**". About an empty collection it says
    NOTHING, and Revit reads it as "here is your correspondence: empty,"
    that is, as supplied and unusable.

    A DEFECT SHAPE, NOT A TYPO: the author reasoned about the MEANING of
    the value ("an empty list means the same as null") instead of reading
    the declared contract. This is form 36 in reverse — there, compiling
    was mistaken for running; here, one's own semantics was mistaken for
    the documented one. Both forms compile; one works.

    A CONSEQUENCE THAT REMOVES A WHOLE QUESTION: since Revit derives the
    correspondence, a DIFFERENT vertex count between the profiles is
    LEGITIMATE. There is no need, and it is harmful, to refuse on «square
    versus hexagon» — that is exactly the cross-section transition the
    blend exists for. We still have no right to set the pairs ourselves:
    that would be guessing on Revit's behalf, not the author's input.

    THE ELEMENT IS DirectShape, NOT FreeFormElement, AND THIS IS VERIFIED,
    NOT CHOSEN. `FreeFormElement.Create` compiles 6/6 and, per
    RevitAPI.xml, throws `ArgumentException` on ALL SIX versions when
    "document is not a family document, nor a document editing an in-place
    family". KIR writes to a project document — meaning a guaranteed
    throw. Read from `data/api_traps/revit_api_traps.sqlite` on
    20.08.2026, not from memory.
    """
    oid = op["id"]
    s = _safe(oid)
    # THE TWO REGIONS ARE READ BY PARAMETER NAME, not from the shared
    # `__region__`: for an op with two regions that key carries the LAST
    # one, and relying on it would mean building the blend from the top
    # profile twice — silently.
    region_lo = op["__region_profile__"]
    region_hi = op["__region_profile_top__"]
    # 🔴 OPENINGS CANNOT BE EXPRESSED BY A BLEND, AND UNTIL 04.09.2026 THEY
    # WERE SIMPLY LOST. `CreateBlendGeometry(CurveLoop, CurveLoop, …)` takes
    # ONE ring per profile — there is no second ring in its signature at
    # all — while the registry accepts a full region (`outer` + `holes`),
    # as extrusion does. The emitter printed only the outer rings, and here
    # is how that ended (measured 04.09.2026, profile 2000×2000 with a
    # 400×400 opening):
    #
    #     ok=True, `__hl_` rings in C#          ZERO  — the body came out SOLID
    #     `region_measures.area_mm2`      3 840 000  — the witness SUBTRACTED the opening
    #     area of the solid cap            4 000 000
    #
    # That is, the cap witness would compare the solid body Revit built
    # against an area with the opening subtracted, and would blame Revit
    # for arithmetic that is not its own — for OUR loss of the ring. This
    # is exactly the form the header of `emit_solid_extrusion` names out
    # loud ("the volume witness would blame Revit for arithmetic that is
    # not its own"), only here it is about the cap.
    #
    # A REFUSAL, NOT A SILENT FILL-IN: "the opening did not get built" is a
    # DIFFERENT BODY, not an approximation of what was ordered, and there
    # is no way to choose on the author's behalf between "I need the
    # opening" and "solid will do." The place for this is here, not in the
    # registry: the `region` kind is one for four volumetric operations,
    # and openings are expressible for the other three; the limitation
    # belongs to Revit's FACTORY, not to the value's kind.
    for side, region_side in (("profile", region_lo), ("profile_top", region_hi)):
        if region_side["holes"]:
            raise KirRefusal([Diagnostic(
                code=TYPE_GEOM_RELATION, op_id=op["id"], field_name=side,
                got=len(region_side["holes"]), expected="0",
                message_ru=(
                    f"{side}: у профиля бленда {len(region_side['holes'])} "
                    f"проём(ов), а `CreateBlendGeometry` принимает по ОДНОМУ "
                    f"замкнутому кольцу на профиль — второго кольца в её "
                    f"подписи нет. Построить проём этой фабрикой нечем, а "
                    f"промолчать нельзя: тело вышло бы СПЛОШНЫМ, тогда как "
                    f"свидетель площади торца проём вычитает, и он обвинил бы "
                    f"Revit в нашей же потере. СЛЕДУЮЩИЙ ХОД: собрать бленд "
                    f"без проёмов, а проём вычесть булевой разностью "
                    f"(`create_solid_boolean`) — либо, если профили плоские и "
                    f"одинаковые, взять `create_solid_extrusion`, которая "
                    f"проёмы выражает кольцами"))])
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    height = float(op["height_mm"])
    base_z = op.get("base_z_mm")
    z0 = 0.0 if base_z is None else float(base_z)

    m_lo = C.region_measures(region_lo)
    m_hi = C.region_measures(region_hi)
    cap_area = m_lo["area_mm2"] + m_hi["area_mm2"]
    cap_boundary = m_lo["perimeter_mm"] + m_hi["perimeter_mm"]
    min_cap = min(m_lo["min_area_mm2"], m_hi["min_area_mm2"])
    box_lo = C.region_bbox(region_lo)
    box_hi = C.region_bbox(region_hi)
    plane = op.get("plane")

    if plane is None:
        # Vertices of BOTH profiles in world coordinates — the boundary
        # witness's input.
        pts = ([(x, y, z0) for x, y in C.edges_vertices(region_lo["outer"])]
               + [(x, y, z0 + height)
                  for x, y in C.edges_vertices(region_hi["outer"])])
        box = (min(box_lo[0], box_hi[0]), min(box_lo[1], box_hi[1]), z0,
               max(box_lo[2], box_hi[2]), max(box_lo[3], box_hi[3]),
               z0 + height)
        cap_axis = None
    else:
        # THE SAME VERTICES, PLACED ONTO THE PLANE. The boundary witness
        # compares the DECLARED point against the BUILT body, so the point
        # must travel to where the frame places it, not to where it would
        # lie in plan.
        pts = (_plane_vertices_world(plane, region_lo, 0.0)
               + _plane_vertices_world(plane, region_hi, height))
        box = _plane_profile_box(plane, (region_lo, region_hi), (0.0, height))
        cap_axis = PL.frame(plane)[3]
    _within_world_extent(box, oid, "plane" if plane is not None else "base_z_mm",
                         "места эскиза и габаритов обоих профилей")

    decl, head, tail = _shell_cs(s, oid, member, op["name"], stamp, isolation)
    lo_cs = C.emit_loop_cs(region_lo["outer"], f"__blo_{s}")
    hi_cs = C.emit_loop_cs(region_hi["outer"], f"__bhi_{s}")
    if plane is None:
        frame_cs = ""
        tr_lo = (f"Transform.CreateTranslation(new XYZ(0, 0, U({_n(z0)})))")
        tr_hi = (f"Transform.CreateTranslation(new XYZ(0, 0, U({_n(z0 + height)})))")
    else:
        # TWO FRAMES, NOT ONE WITH A SHIFT AFTERWARD: the blend's profiles
        # lie in PARALLEL planes, offset along the NORMAL, and the second
        # frame is the first with its origin shifted by height·N. Treating
        # the shift as a second transform would mean multiplying matrices
        # in C# where the number is already known at compile time.
        _o, _x, _y, _n3 = PL.frame(plane)
        hi_plane = dict(plane, origin_mm=[_o[k] + height * _n3[k]
                                          for k in range(3)])
        d_lo, tr_lo = _plane_frame_cs(f"{s}_lo", plane)
        d_hi, tr_hi = _plane_frame_cs(f"{s}_hi", hi_plane)
        frame_cs = d_lo + "\n" + d_hi + "\n"
    create = (
        f"// create_solid_blend {cs_line_comment_fragment(oid)} — "
        f"низ {len(region_lo['outer'])} рёбер / {m_lo['area_mm2']:.1f} мм², "
        f"верх {len(region_hi['outer'])} рёбер / {m_hi['area_mm2']:.1f} мм², "
        f"переход {height:.1f} мм\n"
        f"{head}\n"
        f"{lo_cs}\n{hi_cs}\n"
        f"{frame_cs}"
        f"CurveLoop __tlo_{s} = CurveLoop.CreateViaTransform(__blo_{s}, {tr_lo});\n"
        f"CurveLoop __thi_{s} = CurveLoop.CreateViaTransform(__bhi_{s}, {tr_hi});\n"
        f"__sol_{s} = GeometryCreationUtilities.CreateBlendGeometry("
        # `(ICollection<VertexPair>)null` — the cast is mandatory: without
        # it C# cannot choose between the two overloads (with SolidOptions
        # and without) and gives CS0121. The type is named explicitly, not
        # inferred.
        f"__tlo_{s}, __thi_{s}, (ICollection<VertexPair>)null, "
        f"new SolidOptions(ElementId.InvalidElementId, ElementId.InvalidElementId));\n"
        f"{tail}\n"
        # THERE IS NO VOLUME WITNESS — so there is no vacuum prohibition
        # for it either. Passing a made-up surface area here for the sake
        # of symmetry would mean deriving a tolerance from a number we do
        # not know.
        f"__dt_{s} = MM(doc.Application.VertexTolerance) + "
        f"{_n(C.EMIT_COORD_QUANTUM_MM)};\n"
        f"__tcap_{s} = {_n(cap_boundary)} * __dt_{s};\n"
        f"if (__tcap_{s} >= {_n(min_cap)}) {{ "
        + refuse_stmt(
            oid,
            _cs('допуск свидетеля торцов не меньше самой мелкой объявленной '
                'части профиля — проверка не смогла бы провалиться'),
            isolation) + " }")

    checks = [
        _solid_count_check(s, oid),
        # The caps are FLAT faces with a normal along the AXIS: both
        # profiles lie in parallel planes by the op's construction, and
        # they share the same axis.
        _cap_area_check(s, oid, cap_area, axis_parallel=True, axis=cap_axis),
        _profiles_on_boundary_check(s, oid, pts),
        _bbox_check(s, oid, box,
                    f"    var __bb_{s} = __el_{s}.get_BoundingBox(null);\n",
                    inward_mm=0.0,
                    outward_mm=_blend_outward_mm(box_lo, box_hi, height)),
    ]
    readback = _readback(s, oid, "direct_shape_solid_blend", op, {
        # None, not 0.0: the value IS NOT COMPUTED, and the receipt is
        # obligated to say so with a word, not with a number that reads as
        # an expectation.
        "volume_mm3": None, "area_mm2": m_lo["area_mm2"],
        "volume_unknown_ru": ("объём бленда не предсказывается: форму боковины "
                              "между профилями выбирает Revit, и она не "
                              "документирована. Измеренное значение ниже — "
                              "факт о построенном теле, а не проверка"),
        "cap_area_mm2": cap_area}, identity_version=ver)
    return decl, create, checks, readback


# ── sweep ─────────────────────────────────────────────────────────────────

#: Cosine threshold for "the face normal is parallel to the segment
#: direction." The same order of magnitude and the same argument as for
#: `_AXIS_COS_EPS`: for a STRAIGHT sweep the cap is flat and its normal
#: equals the segment direction EXACTLY, and the threshold is needed only
#: to absorb Revit's double-precision arithmetic.
_SWEEP_COS_EPS = 1e-6


def _sweep_cap_reader_cs(s: str, d_first: tuple, d_last: tuple) -> str:
    """Sum of the areas of the flat faces whose normal runs along the FIRST or
    LAST segment. For a sweep this is exactly two caps — but only if no
    segment of the path is perpendicular to them (the emitter does this
    check, see `_caps_are_clean`)."""
    def _par(d):
        return (f"Math.Abs(__pf_{s}.FaceNormal.DotProduct("
                f"new XYZ({_n(d[0])}, {_n(d[1])}, {_n(d[2])}))) > "
                f"{_n(1.0 - _SWEEP_COS_EPS)}")
    return (
        f"    if (__sol_{s} != null)\n"
        f"        foreach (Face __f_{s} in __sol_{s}.Faces)\n        {{\n"
        f"            PlanarFace __pf_{s} = __f_{s} as PlanarFace;\n"
        f"            if (__pf_{s} != null && ({_par(d_first)} || {_par(d_last)}))\n"
        f"                __rcap_{s} += MM(MM(__pf_{s}.Area));\n"
        f"        }}\n")


def _caps_are_clean(dirs: list) -> bool:
    """Whether caps can be selected BY NORMAL without catching a side face.

    The side faces of segment `i` have their normal in the plane
    PERPENDICULAR to `d_i`. The cap direction `d_0` lies in that plane
    exactly when `d_0 ⟂ d_i`. So the contamination test is exact and is
    computed here: is there a segment perpendicular to the first or the
    last one.

    This gives more false positives than true contaminations (a side
    face's normal must also COINCIDE with the cap's, not merely lie in its
    plane), and this is deliberate: a skipped witness costs more than a
    refused one.
    """
    for d in dirs:
        for cap in (dirs[0], dirs[-1]):
            if abs(SW._dot(d, cap)) < 1e-6:
                return False
    return True


def _sweep_volume_check(s: str, oid: str, expected_mm3: float) -> WitnessCheck:
    """Sweep volume. The key is the same (`volume`), the text is ITS OWN,
    with numbers.

    The shared `_volume_check` prints "solid volume mismatch (geometry)"
    and not a single value. For a sweep that would cost a live run: volume
    here is the operation's MAIN assertion, and on a postcondition
    violation the transaction rolls back, meaning there would be no
    receipt with an expected/measured pair at all. The shared helper is
    deliberately LEFT UNTOUCHED: its text is pinned by the goldens of
    extrusion, revolution, blend, and boolean, and editing it would shift
    the bytes of four foreign operations for the sake of one's own.
    """
    return WitnessCheck(
        obligation_key="volume",
        reader_cs=f"    double __vmm_{s} = __rvol_{s} * MM(MM(MM(1.0)));\n",
        verdict_cs=(
            f"    if (Math.Abs(__vmm_{s} - {_n(expected_mm3)}) > __tvol_{s})\n"
            f"        __post.Add({_cs(oid + ': объём протяжки не сошёлся: ожидалось ')}\n"
            f"          + {_n(expected_mm3)} + \" мм³, получено \" + "
            f"Math.Round(__vmm_{s}, 1)\n"
            f"          + \" мм³, допуск \" + Math.Round(__tvol_{s}, 1) + "
            f"\" мм³ (geometry)\");\n"),
        message="swept volume mismatch (geometry)",
        style="guard")


def _sweep_containment_check(s: str, oid: str, box: tuple) -> WitnessCheck:
    """The body must FIT inside the box. The check is ONE-SIDED, and this
    is named in the operation's `post`: an exact bounding box does not
    exist for a sweep as a property of the input — the profile's rotation
    about the axis is chosen by Revit.

    What it catches: the wrong place, the wrong scale, the wrong profile,
    a reversed path. What it does not catch: a body SMALLER than declared
    inside the box — that is the volume witness's job, and together the
    two cover both sides.
    """
    x0, y0, z0, x1, y1, z1 = box
    got = (
        f'"; получено X " + Math.Round(MM(__bb_{s}.Min.X), 1) + ".." '
        f'+ Math.Round(MM(__bb_{s}.Max.X), 1)\n'
        f'          + " · Y " + Math.Round(MM(__bb_{s}.Min.Y), 1) + ".." '
        f'+ Math.Round(MM(__bb_{s}.Max.Y), 1)\n'
        f'          + " · Z " + Math.Round(MM(__bb_{s}.Min.Z), 1) + ".." '
        f'+ Math.Round(MM(__bb_{s}.Max.Z), 1)')
    expected_ru = (f"тело обязано лежать внутри X {x0:.1f}..{x1:.1f}"
                   f" · Y {y0:.1f}..{y1:.1f} · Z {z0:.1f}..{z1:.1f}")
    return WitnessCheck(
        obligation_key="bbox",
        reader_cs=f"    var __bb_{s} = __el_{s}.get_BoundingBox(null);\n",
        verdict_cs=(
            f"    if (__bb_{s} == null) __post.Add({_cs(oid + ': нет BoundingBox')});\n"
            f"    else if (MM(__bb_{s}.Min.X) < {_n(x0)} - __dt_{s} || "
            f"MM(__bb_{s}.Max.X) > {_n(x1)} + __dt_{s} ||\n"
            f"             MM(__bb_{s}.Min.Y) < {_n(y0)} - __dt_{s} || "
            f"MM(__bb_{s}.Max.Y) > {_n(y1)} + __dt_{s} ||\n"
            f"             MM(__bb_{s}.Min.Z) < {_n(z0)} - __dt_{s} || "
            f"MM(__bb_{s}.Max.Z) > {_n(z1)} + __dt_{s})\n"
            f"        __post.Add({_cs(oid + ': протяжка вышла за границу — ' + expected_ru)}\n"
            f"          + {got});\n"),
        message="swept solid outside its containment box (geometry)",
        style="else_block")


def emit_solid_sweep(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple:
    """CONTOUR profile + a spatial polyline -> Solid -> DirectShape.

    TWO FACTORIES UNDER ONE OP, differing in a single argument:

      variety="frame"            CreateSweptGeometry(path, 0, 0, profile)
      variety="fixed_reference"  ...FixedReferenceSweptGeometry(..., ref)

    WHERE THE PROFILE SITS IS NAMED BY `anchor_uv_mm` (21.08.2026), AND BY
    DEFAULT IT IS THE CENTROID. Before, "the law decides, not the author"
    stood here: the centroid was placed on the path because then the
    profile's first moment is zero in every direction and the miter
    correction at each joint vanishes to zero. The law is not repealed —
    it became a special case. The general form: `V = A·(L + correction)`,
    where the correction is computed by `sweep_path.miter_correction_mm`
    in closed form, and it is EXACT as long as the frame is given by the
    input. Measured against Revit itself — 34 of 34 family sweeps, header
    of `sweep_path.py`.

    🔴 FOUR REFUSALS BEFORE EFFECT, AND ALL FOUR ARE FROM REVIT'S
    DOCUMENTATION, not from caution. `data/api_traps` on all six versions:

      ArgumentNullException       any mandatory argument is null
      ArgumentException           "sweepPath should at least contain one
                                  curve"; "pathAttachmentCrvIdx is not
                                  valid"; "The given attachment point
                                  doesn't lie in the plane of the Curve
                                  Loop"; "profile CurveLoops do not satisfy
                                  the input requirements"
      ArgumentOutOfRangeException "fixedReferenceDirection is not length
                                  1.0" — ONLY for the second factory
      InvalidOperationException   "Failed to create the swept solid" —
                                  🔴 documented ONLY for 2023-2026. On
                                  2021-2022 the same failure is not
                                  documented at all, meaning its outcome is
                                  UNKNOWN. That is why the check for an
                                  empty body in `_shell_cs` here is not
                                  decoration but the sole protection on the
                                  two older versions.

    Of these four, three are removed BY CONSTRUCTION: the path is
    non-empty and connected (the `path3` kind), the attachment point is
    the start of the first curve (index 0, parameter 0, lying in the
    profile's plane by the construction of our own transform), the
    reference direction is normalized here and leaves for C# as a unit
    vector. The fourth — the geometric one — is closed off by the miter
    feasibility check.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    variety = op["variety"]
    path = [[float(c) for c in pt] for pt in op["path_mm"]]
    ref_raw = tuple(float(c) for c in op["ref_dir"])

    if math.sqrt(sum(c * c for c in ref_raw)) < 1e-9:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name="ref_dir",
            message_ru=("ref_dir нулевой длины — опорное направление им не "
                        "задаётся. Следующий ход: назвать вектор, не "
                        "коллинеарный первому звену пути"))])
    ref = SW._unit(ref_raw)

    dirs = SW.path_directions(path)
    frame = SW.frame_at(dirs[0], ref)
    if frame is None:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name="ref_dir",
            message_ru=("ref_dir коллинеарен первому звену пути — плоскость "
                        "профиля им не определяется. Следующий ход: взять "
                        "направление поперёк хода, например мировую вертикаль "
                        "для горизонтального пути"))])
    e1, e2 = frame

    cx, cy, area = SW.profile_centroid(region)
    # THE PROFILE POINT THAT TRAVELS ALONG THE PATH. The default is the
    # centroid, and it lives HERE, not in the registry: the registry's
    # `default` would travel into the plan's signature as a number, and
    # the centroid is never a number — it is a property of the profile.
    anchor = op.get("anchor_uv_mm")
    au, av = (float(anchor[0]), float(anchor[1])) if anchor else (cx, cy)
    offset = (cx - au, cy - av)           # CENTROID offset from the path
    offset_mm = math.hypot(offset[0], offset[1])

    # 🔴 OFFSET UNDER `frame` — A NAMED REFUSAL, NOT A TOLERANCE. For this
    # factory, Revit chooses the profile's rotation about the axis (minimum
    # twist, an undocumented rule). At zero offset this does not matter:
    # every term of the correction vanishes to zero on its own. At nonzero
    # offset, every term DEPENDS on the rotation, and substituting our own
    # would mean passing someone else's choice off as a property of the
    # input. The analysis is in the header of `sweep_path.py`.
    if variety == "frame" and offset_mm > 0.0:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name="anchor_uv_mm",
            message_ru=(
                f"вынос профиля {offset_mm:.1f} мм при variety=\"frame\": у "
                f"этой фабрики разворот профиля вокруг пути выбирает Revit, а "
                f"поправка уса от разворота зависит — объём перестал бы быть "
                f"свойством входа. Следующий ход: variety=\"fixed_reference\" "
                f"с опорным направлением, либо anchor_uv_mm по центроиду "
                f"[{cx:.3f}, {cy:.3f}]"))])

    # THE RADIUS IS MEASURED FROM THE ATTACHMENT POINT, NOT FROM THE
    # CENTROID, AND THIS IS NOT A TRIFLE: it enters the miter feasibility
    # check and the bounding box, and both values ask "how far does the
    # profile stand OFF THE PATH." From the centroid, this distance is
    # understated by exactly the offset — meaning the check would grow
    # softer exactly where the profile is farthest away.
    radius = SW.profile_circumradius(region, au, av)

    # MITER FEASIBILITY IS ASKED ACCORDING TO WHAT IS KNOWN ABOUT THE
    # ROTATION. For `fixed_reference` the frame is given by the input — we
    # compute exactly the cross-section that will occur. For `frame` the
    # rotation is chosen by Revit, and the honest answer is the worst case
    # over all rotations, that is, an isotropic radius. The analysis and
    # the measurement (the isotropic estimate was wrong on 3 of 6 family
    # sweeps) are in the header of `sweep_path.frame_feasibility`.
    bad = (SW.frame_feasibility(path, region, (au, av), ref)
           if variety == "fixed_reference" else SW.feasibility(path, radius))
    if bad is not None:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name="path_mm",
            message_ru=f"протяжка не строится: {bad}")])

    correction = SW.miter_correction_mm(path, ref, offset)
    if correction is None:
        raise KirRefusal([Diagnostic(
            code=TYPE_GEOM_RELATION, op_id=oid, field_name="ref_dir",
            message_ru=(
                "поправка уса не вычислилась: опорное направление коллинеарно "
                "какому-то звену пути либо в узле разворот на месте — рамки "
                "профиля на этом звене не существует. Следующий ход: взять "
                "направление поперёк ВСЕГО хода пути"))])

    m = C.region_measures(region)
    length = SW.path_length_mm(path)
    volume = SW.swept_volume_mm3(area, path, correction)
    surface = SW.swept_surface_estimate_mm2(area, m["perimeter_mm"], path, radius)
    box = SW.containment_box_mm(path, radius)
    _within_world_extent(box, oid, "path_mm",
                         "хода пути и выноса профиля от него")
    caps_clean = _caps_are_clean(dirs)

    # The start of the transform: the local point (au, av) is obligated to
    # land at path[0].
    origin = tuple(path[0][k] - au * e1[k] - av * e2[k] for k in range(3))

    decl, head, tail = _shell_cs(s, oid, member, op["name"], stamp, isolation)
    path_cs = [f"CurveLoop __pth_{s} = new CurveLoop();"]
    for i in range(len(path) - 1):
        a, b = path[i], path[i + 1]
        path_cs.append(
            f"__pth_{s}.Append(Line.CreateBound("
            f"P({_n(a[0])}, {_n(a[1])}, {_n(a[2])}), "
            f"P({_n(b[0])}, {_n(b[1])}, {_n(b[2])})));")
    frame_cs = (
        f"Transform __tf_{s} = Transform.Identity;\n"
        f"__tf_{s}.BasisX = new XYZ({_n(e1[0])}, {_n(e1[1])}, {_n(e1[2])});\n"
        f"__tf_{s}.BasisY = new XYZ({_n(e2[0])}, {_n(e2[1])}, {_n(e2[2])});\n"
        f"__tf_{s}.BasisZ = new XYZ({_n(dirs[0][0])}, {_n(dirs[0][1])}, {_n(dirs[0][2])});\n"
        f"__tf_{s}.Origin = P({_n(origin[0])}, {_n(origin[1])}, {_n(origin[2])});")
    if variety == "fixed_reference":
        call = (f"__sol_{s} = GeometryCreationUtilities"
                f".CreateFixedReferenceSweptGeometry(__pth_{s}, 0, 0.0, __lps_{s}, "
                f"new XYZ({_n(ref[0])}, {_n(ref[1])}, {_n(ref[2])}));")
    else:
        call = (f"__sol_{s} = GeometryCreationUtilities.CreateSweptGeometry("
                f"__pth_{s}, 0, 0.0, __lps_{s});")

    create = (
        f"// create_solid_sweep {cs_line_comment_fragment(oid)} — {variety}, "
        f"путь {len(path)} точек / {length:.1f} мм, профиль {area:.1f} мм², "
        f"вынос {offset_mm:.1f} мм, поправка уса {correction:.1f} мм, "
        f"объём {volume:.1f} мм³\n"
        f"{head}\n"
        f"{chr(10).join(path_cs)}\n"
        f"{frame_cs}\n"
        f"{_loops_cs(region, s)}\n"
        f"{_transform_cs(region, s, f'__tf_{s}')}\n"
        f"{call}\n"
        f"{tail}\n"
        f"{_derived_tolerances_cs(s, oid, isolation, surface_mm2=surface, min_feature_vol_mm3=m['min_area_mm2'] * length, cap_boundary_mm=2.0 * m['perimeter_mm'], min_feature_cap_mm2=2.0 * m['min_area_mm2'])}")

    checks = [
        _solid_count_check(s, oid),
        _sweep_volume_check(s, oid, volume),
        _sweep_containment_check(s, oid, box),
    ]
    if caps_clean:
        checks.append(_cap_area_check(s, oid, 2.0 * area, axis_parallel=True))
        checks[-1] = WitnessCheck(
            obligation_key="cap_area",
            reader_cs=_sweep_cap_reader_cs(s, dirs[0], dirs[-1]),
            verdict_cs=(
                f"    if (Math.Abs(__rcap_{s} - {_n(2.0 * area)}) > __tcap_{s})\n"
                f"        __post.Add({_cs(oid + ': площадь торцов не сошлась: ожидалось ')}\n"
                f"          + {_n(2.0 * area)} + \" мм², получено \" + "
                f"Math.Round(__rcap_{s}, 1) + \" мм² (geometry)\");\n"),
            message="planar cap area mismatch (geometry)",
            style="guard")

    readback = _readback(s, oid, "direct_shape_solid_sweep", op, {
        "volume_mm3": volume,
        "area_mm2": area,
        # THE REVERSE PATH SEES THE OFFSET AS A NUMBER, NOT RE-DERIVING IT.
        # The fourth of four places where the value's kind lives, and the
        # only one that is not recalled on its own (`plane.py`, header).
        "profile_offset_mm": round(offset_mm, 6),
        "miter_correction_mm": round(correction, 6),
        "cap_area_mm2": (2.0 * area) if caps_clean else None,
        "cap_unknown_ru": (
            "площадь торцов НЕ проверялась: у этого пути есть звено, "
            "перпендикулярное торцу, и боковая грань такого звена может иметь "
            "ту же нормаль, что торец — сумма перестала бы быть суммой торцов. "
            "Объём при этом проверен точно"),
    })
    return decl, create, checks, readback


#: WHAT THIS SPOKE EMITS IS DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Before, the "op -> body" correspondence lived in the handwritten
#: `authoring._EMITTERS`, while the body lived here, and a thin wrapper in
#: the hub connected the two (41 of them across 19 satellites). Two
#: records of one fact in different files is a named defect of this tree;
#: now there is ONE record, and the hub ASKS it.
EMITTERS = {
    "create_solid_blend": emit_solid_blend,
    "create_solid_extrusion": emit_solid_extrusion,
    "create_solid_revolve": emit_solid_revolve,
    "create_solid_sweep": emit_solid_sweep,
}
