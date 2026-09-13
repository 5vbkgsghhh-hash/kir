"""boolean_emit — emission of booleans over bodies (the paired file to
ops_boolean.py).

Its own wave zone: this module does not touch any other `*_emit.py`.
`authoring.py` receives an additive import and one line in `_EMITTERS` — the
same minimal seam by which the body, surface, and adaptive waves were
plugged in.

Reused WITHOUT CHANGES (by import, not by copy): `_shell_cs`, `_loops_cs`,
`_transform_cs`, `_read_solids_cs`, `_solid_count_check`, `_n` from
solid_emit — the boolean's DirectShape shell and contour-ring assembly are
the SAME as for extrusion, and a second home for them would drift apart at
the first edit. The breakdown of the witness's law, its two refutations by
its own control, and the ban on vacuity are in the header of
ops_boolean.py.

═══ WHAT MATTERS HERE: WE COMPUTE NOT A SINGLE VOLUME ═══════════════════

For extrusion and revolution, volume is derived in closed form AT COMPILE
TIME, and the witness compares Revit's measurement against our number. For
the boolean there is no such number and cannot be: the result's shape is
chosen by Revit's kernel.

So here ALL FOUR quantities at each step are measured by Revit itself —

    V(A)   the accumulator's volume BEFORE the step
    V(B)   the part's volume
    V(A∩B) the volume of the intersection, built by a SEPARATE call
    V(R)   the step's result volume

— and the witness checks the RELATIONS among them (inclusion-exclusion).
This is not a relaxation but a change of the kind of check: the identity
determines V(R) UNAMBIGUOUSLY, and any deviation is caught, even though not
one of the four quantities is known to us in advance.

🔴 THE INTERSECTION IS ALWAYS BUILT, AND SKIMPING ON IT IS NOT ALLOWED. The
temptation is real: it is an extra kernel call on every step. But without
V(A∩B) the identity is UNCHECKABLE AT ALL, and the direction check alone is
leaky — it misses "returned A∪B where A−B was asked for" exactly in the
cases where the volumes are close. The measurement and the refutation are
in the header of ops_boolean.py.

═══ THE TOLERANCE IS DERIVED FROM MEASUREMENTS, NOT ASSIGNED ═════════════

The identity sums FOUR measured volumes, so its residual cannot be smaller
than the sum of their own errors. A solid's volume error scales with its
SURFACE AREA (a face-position error δ over area S gives a volume error of
δ·S), so

    δ_step = (S(A) + S(B) + S(A∩B) + S(R)) · (MM(VertexTolerance) + quantum)

Revit measures all four areas in that same runtime. `VertexTolerance` is
its own number ("two points closer than this are considered coincident"),
the quantum is `contour.EMIT_COORD_QUANTUM_MM`, a direct consequence of
coordinates being printed with a fixed number of digits.

THE BAN ON VACUITY FOLLOWS RIGHT HERE, BY DEFINITION: if δ_step is not
smaller than V(A∩B), then the entire intersection vanishing would pass
under the tolerance — the check could not fail — and the op MUST refuse by
name, rather than sign it off as green.

═══ WHAT WE DO NOT CATCH, AND THIS IS STATED, NOT LEFT UNSAID ════════════

`ExecuteBooleanOperation` THROWS `InvalidOperationException` ("Failed to
perform the Boolean operation… geometric inaccuracies… coincident edges"),
and this is MEASURED via `data/api_traps` on all six versions. We do NOT
catch it — the law lives at home: a Revit API failure is recorded as
`internal`, not as a compiler decision. Catching it would turn someone
else's breakage into our "refusal," and from outside that would read as a
decision we made.

There is NO condition on the DOCUMENT KIND for this call, on any version —
unlike `FreeFormElement.Create`, which compiles 6/6 and throws "document is
not a family document." Booleans work in a project document.

THERE IS DELIBERATELY NO BOUNDING-BOX WITNESS HERE: the result's bounding
box is not derived in closed form. For union it equals the union of the
bounding boxes, but for difference and intersection it is only CONTAINED
in the base's bounding box, with no equality. A check valid for one
operation out of three would read as general.
"""
from __future__ import annotations

import math

from kir import contour as C
from kir.emit_core import (  # noqa: F401
    _cs, _safe, _stamp_readback,
)
from kir.emit_model import WitnessCheck
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.ops_boolean import (BOOLEAN_DISJOINT, BOOLEAN_DISJOINT_RU,
                                  BOOLEAN_NESTED, BOOLEAN_NESTED_RU,
                                  lower_part_profile, part_bbox)
from kir.ops_shape import DIRECTSHAPE_CATEGORIES
from kir.plane import frame as _plane_frame
from kir.solid_emit import (_loops_cs, _n, _plane_frame_cs, _read_solids_cs,
                                 _shell_cs, _solid_count_check, _transform_cs)

#: THERE IS NO HONEST-LABEL CONSTANT OF ITS OWN HERE, AND THAT IS NOT AN
#: OVERSIGHT. It is written by `_shell_cs` from solid_emit — the same text
#: as for extrusion and revolution ("KIR Solid: a parametric body with no
#: BIM meaning"). A constant of its own here would NOT BE USED AT ALL: the
#: shell is emitted by someone else's function, and a variable declared
#: nearby would read as an active label without being one. A dead constant
#: that looks alive is the same class of problem as the zero of an
#: uncomputed quantity: an absence dressed as an answer.

#: The member name of `BooleanOperationsType`. Measured via
#: `data/api_surface`: exactly these three fields on all six versions, a
#: fourth boolean does not exist.
_MEMBER = {"union": "Union", "difference": "Difference",
           "intersect": "Intersect"}

#: FEET -> MM FOR AREA AND VOLUME. `U` and `MM` are linear and shift-free,
#: so their COMPOSITION carries powers: `MM(MM(1.0))` is ft² to mm²,
#: `MM(MM(MM(1.0)))` is ft³ to mm³. Not a typo but a power of scale; the
#: same technique and the same explanation appear in the header of
#: solid_emit.
_FT2 = "MM(MM(1.0))"
_FT3 = "MM(MM(MM(1.0)))"


def _p(x: float, y: float, z: float) -> str:
    return f"P({_n(x)}, {_n(y)}, {_n(z)})"


def _prism_part_cs(part: dict, lowered: dict, s: str, i: int) -> str:
    """PRISM PART: the same rings and the same factory as extrusion.

    🔴 NOT A SINGLE LINE OF GEOMETRY OF ITS OWN HERE, AND THAT IS THE MAIN
    POINT. The rings are assembled by `_loops_cs`, the transform is set by
    `_transform_cs`, the plane frame is printed by `_plane_frame_cs` — all
    three taken from `solid_emit` BY IMPORT. The prism part and
    `create_solid_extrusion` are the very same geometry, and a second home
    for it would drift from the first at the very first edit of the arc
    arithmetic.

    VARIABLE NAMES CARRY THE PART NUMBER (`<s>_p<i>`), not just the op id:
    `_loops_cs` prints `__ol_<s>`, and for two prisms in the same op that
    would be ONE name — CS0128 at build time, and before that, silently,
    the FIRST ring for both.

    THE EXTRUSION DIRECTION IS THE PLANE NORMAL, NOT +Z, by exactly the
    same argument written in `emit_solid_extrusion`: with `XYZ.BasisZ` the
    body would become a SKEWED prism, and on a wall's vertical face it
    would degenerate to zero.
    """
    ps = f"{s}_p{i}"
    height = float(part["height_mm"])
    plane = part.get("plane")
    base_z = part.get("base_z_mm")
    if plane is None:
        frame_cs = ""
        transform = (None if base_z is None
                     else f"Transform.CreateTranslation(new XYZ(0, 0, U({_n(base_z)})))")
        dir_cs = "XYZ.BasisZ"
    else:
        frame_decl, transform = _plane_frame_cs(ps, plane)
        frame_cs = frame_decl + "\n"
        _o, _x, _y, nrm = _plane_frame(plane)
        dir_cs = f"new XYZ({_n(nrm[0])}, {_n(nrm[1])}, {_n(nrm[2])})"
    return (f"{_loops_cs(lowered, ps)}\n"
            f"{frame_cs}"
            f"{_transform_cs(lowered, ps, transform)}\n"
            f"Solid __prt_{s}_{i} = "
            f"GeometryCreationUtilities.CreateExtrusionGeometry("
            f"__lps_{ps}, {dir_cs}, U({_n(height)}));")


def _part_cs(part: dict, s: str, i: int,
             lowered: dict | None = None) -> str:
    """C# that assembles ONE part into `Solid __prt_<s>_<i>`.

    The three primitives are built by ONE call to a Revit factory from
    numbers: they need no contour, and no ground either. The fourth kind —
    PRISM OVER A CONTOUR — also needs no grounding, because its contour is
    given by explicit points; the breakdown is in the "PARTS" block of
    ops_boolean.py. Its `lowered` (lowered region) arrives as an argument.
    """
    shape = part["shape"]
    if shape == "prism":
        if lowered is None:
            raise ValueError("prism part needs its lowered profile")
        return _prism_part_cs(part, lowered, s, i)
    cx, cy, cz = part["center_mm"]
    lp, lps, sol = f"__plp_{s}_{i}", f"__pls_{s}_{i}", f"__prt_{s}_{i}"
    head = (f"CurveLoop {lp} = new CurveLoop();\n"
            f"IList<CurveLoop> {lps} = new List<CurveLoop>();")

    if shape == "box":
        dx, dy, dz = part["size_mm"]
        x0, x1 = cx - dx / 2.0, cx + dx / 2.0
        y0, y1 = cy - dy / 2.0, cy + dy / 2.0
        z0 = cz - dz / 2.0
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        lines = "\n".join(
            f"{lp}.Append(Line.CreateBound("
            f"{_p(corners[k][0], corners[k][1], z0)}, "
            f"{_p(corners[(k + 1) % 4][0], corners[(k + 1) % 4][1], z0)}));"
            for k in range(4))
        return (f"{head}\n{lines}\n"
                f"{lps}.Add({lp});\n"
                f"Solid {sol} = GeometryCreationUtilities.CreateExtrusionGeometry("
                f"{lps}, XYZ.BasisZ, U({_n(dz)}));")

    r = part["radius_mm"]
    if shape == "cylinder":
        h = part["height_mm"]
        base = _p(cx, cy, cz - h / 2.0)
        # A CIRCLE IS TWO ARCS, NOT ONE. `CurveLoop` does not accept a closed
        # curve whole: a segment must have distinct endpoints. Halves at π
        # are the minimal honest split, not an approximation: Revit's arc
        # is exact.
        return (f"{head}\n"
                f"XYZ __pc_{s}_{i} = {base};\n"
                f"{lp}.Append(Arc.Create(__pc_{s}_{i}, U({_n(r)}), 0.0, "
                f"Math.PI, XYZ.BasisX, XYZ.BasisY));\n"
                f"{lp}.Append(Arc.Create(__pc_{s}_{i}, U({_n(r)}), Math.PI, "
                f"2.0 * Math.PI, XYZ.BasisX, XYZ.BasisY));\n"
                f"{lps}.Add({lp});\n"
                f"Solid {sol} = GeometryCreationUtilities.CreateExtrusionGeometry("
                f"{lps}, XYZ.BasisZ, U({_n(h)}));")

    # A SPHERE IS THE REVOLUTION OF A HALF-DISK. The profile lies in the
    # frame's XZ plane, the arc runs from the lower pole to the upper one
    # through radius r along +X (i.e., x >= 0, as `CreateRevolvedGeometry`
    # requires), and the ring is closed by a segment RIGHT ALONG THE AXIS.
    # Touching the axis here is not a violation but the definition of the
    # pole.
    ctr = _p(cx, cy, cz)
    return (f"{head}\n"
            f"XYZ __pc_{s}_{i} = {ctr};\n"
            f"{lp}.Append(Arc.Create(__pc_{s}_{i}, U({_n(r)}), "
            f"-0.5 * Math.PI, 0.5 * Math.PI, XYZ.BasisX, XYZ.BasisZ));\n"
            f"{lp}.Append(Line.CreateBound({_p(cx, cy, cz + r)}, "
            f"{_p(cx, cy, cz - r)}));\n"
            f"{lps}.Add({lp});\n"
            f"Frame __pfr_{s}_{i} = new Frame(__pc_{s}_{i}, XYZ.BasisX, "
            f"XYZ.BasisY, XYZ.BasisZ);\n"
            f"Solid {sol} = GeometryCreationUtilities.CreateRevolvedGeometry("
            f"__pfr_{s}_{i}, {lps}, 0.0, 2.0 * Math.PI);")


def _step_cs(s: str, oid: str, i: int, part: dict, operation: str,
             isolation: str, lowered: dict | None = None) -> str:
    """One step: helper body -> precondition -> operation -> tolerance.

    🔴 THE HELPER BODY IS ALWAYS BUILT BY A DIFFERENT CALL THAN THE RESULT,
    AND THAT IS THIS FUNCTION'S MAIN DECISION. The first draft built the
    intersection independently of the operation — and for `intersect` that
    gave TWO IDENTICAL CALLS: `Intersect(A,B)` was compared against
    `Intersect(A,B)`. A deterministic function always equals itself, so the
    identity for intersect COULD NOT FAIL — exactly the vacuity this same
    file forbids three paragraphs above. It was caught not by reasoning but
    by asking "what exactly were these two numbers obtained from."

    Hence:

        union, difference  ->  helper = INTERSECTION
        intersect          ->  helper = UNION

    and the inclusion-exclusion identity in both cases links FOUR bodies,
    two of which are built by DIFFERENT kernel calls.
    """
    acc, prt = f"__acc_{s}", f"__prt_{s}_{i}"
    aux, res = f"__bau_{s}_{i}", f"__brs_{s}_{i}"
    pre = f"__bpd_{s}_{i}"
    member = _MEMBER[operation]
    aux_member = "Union" if operation == "intersect" else "Intersect"

    build = (f"// шаг {i}: {member} с частью {part['shape']}\n"
             f"{_part_cs(part, s, i, lowered)}\n"
             f"if ({prt} == null || {prt}.Faces.Size == 0) {{ "
             + refuse_stmt(oid, _cs(f"часть {i} ({part['shape']}) не "
                                    f"построилась: Revit вернул пустое тело"),
                           isolation) + " }\n"
             f"__bva_{s}[{i}] = {acc}.Volume * {_FT3};\n"
             f"__bvb_{s}[{i}] = {prt}.Volume * {_FT3};\n")

    main = (f"Solid {res} = BooleanOperationsUtils.ExecuteBooleanOperation("
            f"{acc}, {prt}, BooleanOperationsType.{member});\n"
            f"if ({res} == null || {res}.Faces.Size == 0) {{ "
            + refuse_stmt(oid, _cs(f"шаг {i}: булева вернула пустое тело — "
                                   f"результата, который можно положить в "
                                   f"модель, нет"), isolation) + " }\n"
            f"__bvr_{s}[{i}] = {res}.Volume * {_FT3};\n")

    aux_cs = (f"Solid {aux} = BooleanOperationsUtils.ExecuteBooleanOperation("
              f"{acc}, {prt}, BooleanOperationsType.{aux_member});\n"
              f"__bvx_{s}[{i}] = ({aux} == null ? 0.0 : {aux}.Volume * {_FT3});\n")

    # THE VOLUME OF THE INTERSECTION is what measures both degeneracy and
    # vacuity. For the two [other] operations this is the helper body; for
    # intersect it is the result itself.
    inter_vol = (f"__bvi_{s}[{i}] = __bvr_{s}[{i}];\n"
                 if operation == "intersect"
                 else f"__bvi_{s}[{i}] = __bvx_{s}[{i}];\n")

    # THE PRECONDITION'S TOLERANCE is by the area of the body used to
    # measure the intersection.
    pre_area = (f"{res}.SurfaceArea" if operation == "intersect"
                else f"({aux} == null ? 0.0 : {aux}.SurfaceArea)")
    guards = (
        f"double {pre} = {pre_area} * {_FT2} * __dtq_{s};\n"
        f"if (__bvi_{s}[{i}] <= {pre}) {{ "
        + refuse_stmt(oid, _cs(f"{BOOLEAN_DISJOINT} шаг {i}: "
                               f"{BOOLEAN_DISJOINT_RU}"), isolation) + " }\n"
        f"if (__bvi_{s}[{i}] >= Math.Min(__bva_{s}[{i}], __bvb_{s}[{i}]) - {pre}) {{ "
        + refuse_stmt(oid, _cs(f"{BOOLEAN_NESTED} шаг {i}: {BOOLEAN_NESTED_RU}"),
                      isolation) + " }\n")

    # THE ORDER DIFFERS, AND IT IS NOT COSMETIC. For intersect, the
    # intersection's volume IS the result's volume, so the precondition
    # physically cannot come before the operation itself. The refusal is
    # still BEFORE THE EFFECT, though: a `Solid` is a body in memory, there
    # is no element in the model yet, and `DirectShape.CreateElement` sits
    # further downstream. The effect is the element, not the computation.
    ordered = ((main + aux_cs + inter_vol + guards) if operation == "intersect"
               else (aux_cs + inter_vol + guards + main))

    tol = (f"__bdl_{s}[{i}] = ({acc}.SurfaceArea + {prt}.SurfaceArea + "
           f"({aux} == null ? 0.0 : {aux}.SurfaceArea) + {res}.SurfaceArea)"
           f" * {_FT2} * __dtq_{s};\n"
           f"if (__bdl_{s}[{i}] >= __bvi_{s}[{i}]) {{ "
           + refuse_stmt(oid, _cs(f"шаг {i}: допуск тождества не меньше объёма "
                                  f"пересечения — проверка не смогла бы "
                                  f"провалиться. Тела перекрываются слишком "
                                  f"мелко для честной сверки на своём размере"),
                         isolation) + " }\n"
           f"{acc} = {res};")
    return build + ordered + tol


#: Which quadruple of volumes EACH law needs. A table, not "declare all
#: four": an unread local variable is CS0219, and a build with
#: "warning = error" would reject legitimate emission.
#:
#: At the same time the table READS as a statement about the law, and one
#: row in it carries the weight of a whole breakdown: for INTERSECT the
#: identity reads `x` as the UNION, built by a separate kernel call — not
#: "the intersection against itself." For why, see the docstring of
#: `_step_cs`.
_NEEDS = {
    ("identity", "union"): ("a", "b", "in", "r"),
    ("identity", "difference"): ("a", "in", "r"),
    ("identity", "intersect"): ("a", "b", "x", "r"),
    ("direction", "union"): ("a", "b", "r"),
    ("direction", "difference"): ("a", "r"),
    ("direction", "intersect"): ("a", "b", "r"),
}

_ARRAY = {"a": "__bva", "b": "__bvb", "in": "__bvi", "r": "__bvr",
          "x": "__bvx"}


def _loop_head(s: str, n: int, law: str, operation: str) -> str:
    """The loop-over-steps header — shared by the identity and the
    direction check.

    A real loop, not unrolled: the quantities already sit in arrays, and
    each step is judged by the SAME law. The step number is printed in the
    message, because "volume did not match" without a number, across eight
    parts, means yet another live turn spent finding which one.
    """
    locals_cs = "".join(
        f"        double __{nm} = {_ARRAY[nm]}_{s}[__bi];\n"
        for nm in _NEEDS[(law, operation)])
    return (f"    for (int __bi = 0; __bi < {n}; __bi++)\n    {{\n"
            + locals_cs
            + f"        double __d = __bdl_{s}[__bi];\n")


def _direction_check(s: str, oid: str, operation: str, n: int) -> WitnessCheck:
    """DIRECTION — THE SECOND CARRIER, AND ITS COST IS HONESTLY MEASURED.

    🔴 With a sound precondition, this check ADDS NOTHING: the intersection
    is built by a separate call, so the identity determines the result's
    volume UNAMBIGUOUSLY, and any deviation is caught by it. This is not a
    guess — a FAIL control in the header of ops_boolean.py removed the
    direction check from union and NOT A SINGLE test turned red.

    Why it is still a separate witness rather than dropped: if the
    precondition fails or is removed (the temptation to save one kernel
    call is real), the identity becomes ENTIRELY UNCHECKABLE, and the
    direction check alone at least catches a swapped operation. A second
    carrier is cheaper than trusting that the first will never be turned
    off.

    AS A SEPARATE KEY, NOT INSIDE THE IDENTITY: obligations are discharged
    BY KEY, and two different assertions under one key would mean that
    dropping one of them goes unnoticed by anyone.
    """
    body = {
        "union": (f"        if (!(__r > Math.Max(__a, __b) + __d))\n"
                  f"            __post.Add({_cs(oid + ': шаг ')} + __bi + "
                  f"{_cs(': объединение не больше каждого из операндов (geometry)')});\n"),
        "difference": (f"        if (!(__r < __a - __d))\n"
                       f"            __post.Add({_cs(oid + ': шаг ')} + __bi + "
                       f"{_cs(': разность не меньше уменьшаемого (geometry)')});\n"),
        "intersect": (f"        if (!(__r < Math.Min(__a, __b) - __d))\n"
                      f"            __post.Add({_cs(oid + ': шаг ')} + __bi + "
                      f"{_cs(': пересечение не меньше каждого из операндов (geometry)')});\n"),
    }[operation]
    return WitnessCheck(
        obligation_key="boolean_direction",
        reader_cs="",
        verdict_cs=_loop_head(s, n, "direction", operation) + body + "    }\n",
        message="boolean volume moved the wrong way (geometry)",
        style="guard")


def _identity_check(s: str, oid: str, operation: str, n: int) -> WitnessCheck:
    """THE INCLUSION-EXCLUSION IDENTITY AT EACH STEP.

    The loop here is real, not unrolled: the quantities already sit in
    arrays, and there is nothing to unroll — each step is judged by the
    SAME law. The step number is printed in the message, because "volume
    did not match" without a number, across eight parts, means yet another
    live turn spent finding which one.
    """
    body = {
        "union": (
            f"        if (Math.Abs((__r + __in) - (__a + __b)) > __d)\n"
            f"            __post.Add({_cs(oid + ': шаг ')} + __bi + "
            f"{_cs(': объём объединения не сходится с включением-исключением (geometry)')});\n"),
        "difference": (
            f"        if (Math.Abs((__r + __in) - __a) > __d)\n"
            f"            __post.Add({_cs(oid + ': шаг ')} + __bi + "
            f"{_cs(': объём разности плюс пересечение не даёт исходного (geometry)')});\n"),
        "intersect": (
            # FULL INCLUSION-EXCLUSION, not "the result equals itself." The
            # union is built by a SEPARATE kernel call, so the equality
            # V(A)+V(B) == V(A∪B)+V(A∩B) links two independently obtained
            # numbers and CAN fail. The breakdown is in the docstring of
            # `_step_cs`.
            f"        if (Math.Abs((__x + __r) - (__a + __b)) > __d)\n"
            f"            __post.Add({_cs(oid + ': шаг ')} + __bi + "
            f"{_cs(': объём пересечения не сходится с включением-исключением (geometry)')});\n"),
    }[operation]
    return WitnessCheck(
        obligation_key="boolean_identity",
        reader_cs="",
        verdict_cs=_loop_head(s, n, "identity", operation) + body + "    }\n",
        message="boolean volume identity mismatch (geometry)",
        style="guard")


def _readback(s: str, oid: str, op: dict, parts: list,
              lowered: list) -> str:
    """The receipt. THE RAW QUADRUPLES OF EACH STEP GO OUT deliberately.

    `Solid.Volume`'s own error on curved surfaces is documented nowhere,
    and for a boolean, curves appear from the very first sphere. The first
    live run must MEASURE it, not estimate it — without these numbers in
    the receipt there would be nothing to measure with.
    """
    lines = [
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n",
        f"    var __rb = new Dictionary<string, object>();\n",
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n",
        f"    __rb[\"name\"] = __el_{s}.Name;\n",
        f"    __rb[\"category\"] = {_cs(op['category'])};\n",
        f"    __rb[\"kind\"] = \"direct_shape_boolean\";\n",
        f"    __rb[\"operation\"] = {_cs(op['operation'])};\n",
        f"    __rb[\"parts\"] = {len(parts)};\n",
        f"    __rb[\"solids\"] = __nsol_{s};\n",
        f"    __rb[\"volume_mm3_measured\"] = __rvol_{s} * {_FT3};\n",
        f"    __rb[\"vertex_tolerance_mm\"] = MM(doc.Application.VertexTolerance);\n",
    ]
    for i, part in enumerate(parts):
        x0, y0, z0, x1, y1, z1 = part_bbox(part, lowered[i])
        lines += [
            f"    __rb[\"step{i}_shape\"] = {_cs(part['shape'])};\n",
            f"    __rb[\"step{i}_part_bbox_mm\"] = {_cs(f'{x0:.1f} {y0:.1f} {z0:.1f} .. {x1:.1f} {y1:.1f} {z1:.1f}')};\n",
            f"    __rb[\"step{i}_v_base_mm3\"] = __bva_{s}[{i}];\n",
            f"    __rb[\"step{i}_v_part_mm3\"] = __bvb_{s}[{i}];\n",
            f"    __rb[\"step{i}_v_intersection_mm3\"] = __bvi_{s}[{i}];\n",
            f"    __rb[\"step{i}_v_result_mm3\"] = __bvr_{s}[{i}];\n",
            f"    __rb[\"step{i}_v_auxiliary_mm3\"] = __bvx_{s}[{i}];\n",
            f"    __rb[\"step{i}_tolerance_mm3\"] = __bdl_{s}[{i}];\n",
        ]
    lines += [
        f"    __rb[\"bim_semantics\"] = \"none\";\n",
        f"    __rb[\"has_type\"] = false;\n",
        f"    __rb[\"schedulable_as_building_element\"] = false;\n",
        f"    __rb[\"human_editable\"] = false;\n",
        f"    __rb[\"honest_label_written\"] = __lbl_{s};\n",
        f"    __rb[\"warning\"] = {_cs('Результат булевой в DirectShape — геометрия без BIM-смысла: у элемента нет типа и параметров, в спецификацию как строительный элемент он не попадёт, вручную его не отредактировать. Это не стена/перекрытие/кровля, даже если форма похожа.')};\n",
        _stamp_readback(f"__el_{s}"),
        f"    __results[{_cs(oid)}] = __rb;\n}}",
    ]
    return "".join(lines)


def emit_solid_boolean(op: dict, ver: str, stamp: str,
                       isolation: str = "atomic") -> tuple:
    """Prism over a contour + primitives -> chain of booleans -> DirectShape.

    There is no version axis: everything named here is measured 6/6
    (`BooleanOperationsUtils`,
    `BooleanOperationsType.{Union,Difference,Intersect}`, `Solid.Volume`,
    `Solid.SurfaceArea`, `Arc.Create`, `Line.CreateBound`, `CurveLoop.Append`).
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    parts = op["parts"]
    n = len(parts)
    height = float(op["height_mm"])
    base_z = op.get("base_z_mm")
    # 🔴 EACH PRISM-PART'S CONTOUR IS LOWERED EXACTLY ONCE PER OP, AND THE
    # RESULT GOES BOTH INTO THE RINGS AND INTO THE RECEIPT. Two calls to
    # `contour.validate_region` at one step would not set up a second
    # carrier of the law (it is one function), but they would set up a
    # second ANSWER in the receipt on exactly the day the first one gets
    # fixed — and such pairs drift apart silently.
    lowered_parts = [
        (lower_part_profile(part, oid, "parts", i, []) if part["shape"] == "prism"
         else None)
        for i, part in enumerate(parts)]
    for i, low in enumerate(lowered_parts):
        if parts[i]["shape"] == "prism" and low is None:
            # Unreachable: `validate_parts` has already accepted exactly
            # this contour with the same pure function. An error here would
            # mean lowering is NOT deterministic — and that cannot be left
            # unsaid.
            raise ValueError(f"{oid}: parts[{i}] profile lowering is not "
                             f"deterministic between validation and emission")

    decl, head, tail = _shell_cs(s, oid, DIRECTSHAPE_CATEGORIES[op["category"]],
                                 op["name"], stamp, isolation)
    # The arrays of quadruples are DECLARED NEXT TO THE SHELL, not inside
    # the creation block: with isolation="per_op" the creation block is
    # wrapped in its own scope, and a variable declared there is NOT
    # VISIBLE to the witness (CS0103).
    decl += (f"\ndouble __dtq_{s} = 0.0;"
             f"\ndouble[] __bva_{s} = new double[{n}];"
             f"\ndouble[] __bvb_{s} = new double[{n}];"
             f"\ndouble[] __bvi_{s} = new double[{n}];"
             f"\ndouble[] __bvr_{s} = new double[{n}];"
             f"\ndouble[] __bvx_{s} = new double[{n}];"
             f"\ndouble[] __bdl_{s} = new double[{n}];")

    # THE BASE IS A PRISM, AND IT IS SET UP EXACTLY LIKE A PRISM PART. The
    # absence of a plane leaves the old branch BYTE FOR BYTE: without
    # `base_z_mm` not a single transform is printed, the direction is
    # `XYZ.BasisZ`.
    plane = op.get("plane")
    if plane is None:
        frame_cs = ""
        transform = (None if base_z is None
                     else f"Transform.CreateTranslation(new XYZ(0, 0, U({_n(base_z)})))")
        dir_cs = "XYZ.BasisZ"
    else:
        frame_decl, transform = _plane_frame_cs(s, plane)
        frame_cs = frame_decl + "\n"
        _o, _x, _y, nrm = _plane_frame(plane)
        # THE DIRECTION IS THE NORMAL, NOT +Z: with `XYZ.BasisZ` the base
        # would become a SKEWED prism, and on a vertical face it would
        # degenerate to zero. The same argument is written verbatim in
        # `emit_solid_extrusion`.
        dir_cs = f"new XYZ({_n(nrm[0])}, {_n(nrm[1])}, {_n(nrm[2])})"
    shapes = ", ".join(p["shape"] for p in parts)
    member = _MEMBER[op["operation"]]
    create = (
        f"// create_solid_boolean {cs_line_comment_fragment(oid)} — "
        f"{op['operation']}: база {len(region['outer'])} рёбер x {height:g} мм, "
        f"части: {shapes}\n"
        f"{head}\n"
        f"{_loops_cs(region, s)}\n"
        f"{frame_cs}"
        f"{_transform_cs(region, s, transform)}\n"
        f"Solid __acc_{s} = GeometryCreationUtilities.CreateExtrusionGeometry("
        f"__lps_{s}, {dir_cs}, U({_n(height)}));\n"
        f"if (__acc_{s} == null || __acc_{s}.Faces.Size == 0) {{ "
        + refuse_stmt(oid, _cs("база булевой не построилась: Revit вернул "
                               "пустое тело из этого профиля"), isolation) + " }\n"
        # δ of Revit's own number plus the quantum of our coordinate
        # printing. One value for the whole chain: this is a property of
        # PRINTING and the KERNEL, not of a specific step.
        f"__dtq_{s} = MM(doc.Application.VertexTolerance) + "
        f"{_n(C.EMIT_COORD_QUANTUM_MM)};\n"
        + "\n".join(_step_cs(s, oid, i, part, op["operation"], isolation,
                              lowered_parts[i])
                    for i, part in enumerate(parts))
        + f"\n__sol_{s} = __acc_{s};\n"
        f"{tail}")

    checks = [
        _solid_count_check(s, oid),
        _identity_check(s, oid, op["operation"], n),
        _direction_check(s, oid, op["operation"], n),
    ]
    return decl, create, checks, _readback(s, oid, op, parts, lowered_parts)


#: WHAT THIS SPOKE EMITS — DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Previously the "op -> body" correspondence lived in the handwritten
#: `authoring._EMITTERS`, while the body lived here, and a thin wrapper in
#: the hub connected the two (41 entries across 19 satellites). Two records
#: of one fact in different files is this tree's named defect class; now
#: there is ONE record, and the hub ASKS it.
EMITTERS = {
    "create_solid_boolean": emit_solid_boolean,
}
