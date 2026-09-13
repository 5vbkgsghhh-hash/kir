"""surface_emit — a grid of control points -> a NURBS face -> a Solid -> a DirectShape.

WHAT HAPPENS HERE, STEP BY STEP, AND WHY EXACTLY THIS WAY.

1. `BRepBuilderSurfaceGeometry.CreateNURBSSurface(du, dv, ku, kv, points[,
   weights], reverseOrientation, bboxUV)` — the surface itself. Measured
   6/6.

2. THE FOUR BOUNDARY EDGES — AS EXACT ISOPARAMETRIC CURVES, NOT CHORDS.
   This is a load-bearing decision, not pedantry. For a clamped NURBS, the
   boundary at u=0 IS, exactly, a curve of degree `degree_v` with the
   control points of the first row and the knot vector `knots_v` — an
   identity, not an approximation. A chord between the corners would
   coincide with the boundary only for a flat or ruled surface; on any
   curved one, BRepBuilder would get a loop that does not lie on the face,
   and would refuse — or, worse, would silently drop the face
   (`RemovedSomeFaces`). `NurbSpline.CreateCurve(degree, knots, points[,
   weights])` is measured 6/6 — it is exactly the full form with knots;
   without it we would have had to approximate.

3. `BRepBuilder` -> `Solid` -> `DirectShape.SetShape`. The shell is OPEN
   (`BRepType.OpenShell`): a single face does not form a closed body, and
   declaring a `Solid` would mean lying about the topology. It follows from
   this that the result has no volume — and there is deliberately no
   volume witness here, unlike in `ops_solid`, where one exists and is
   computed analytically.

THE WITNESS — FOUR LEVELS, AND EACH ANSWERS ITS OWN QUESTION.

    did it build              IsResultAvailable() + RemovedSomeFaces()
    how many faces            Solid.Faces.Size == 1
    is it the right surface   degree and control-point count, READ back
    are they the right points every control point, READ back

🔴 WHY THIS IS A READING OF THE RESULT, NOT A CONFIRMATION OF THE CALL. The
far side is read by `ExportUtils.GetNurbsSurfaceDataForSurface` — the SAME
instrument by which the compiler's read-back path
(`decompile/geom_extract.__gxNurbsSurface`) reads it. Revit is free to
reparametrize the surface, insert knots, raise the degree, reorder the
points — every such outcome pulls the read-back value apart from the
declared one and turns the witness red. This is exactly what distinguishes
a check from "the setter ran".

🔴 `RemovedSomeFaces` IS READ MANDATORILY, and this is not decoration.
Revit can drop a problematic face and return a result that is formally
"available". A shell without its one and only face is an empty element,
indistinguishable from success from the outside. The API offers a way to
ask; not asking would mean planting silence exactly where the answer is
free.

THE COMPARISON RUNS IN INTERNAL UNITS, NOT MILLIMETERS, and this saves
exactly what matters: the array of control points has already traveled
into C# for CONSTRUCTION, and a second copy of it in millimeters, just for
the comparison, would double the emission size on a grid of thousands of
points. The tolerance is converted to feet exactly once (`U(tol)`).
"""
from __future__ import annotations

from kir.emit_core import (  # noqa: F401
    _cs, _safe, _stamp_block,
)
from kir.emit_model import WitnessCheck, tolerance
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.ops_shape import DIRECTSHAPE_CATEGORIES
from kir.surface import col_v, row_u, sample_surface, surface_bbox

#: A label in ALL_MODEL_MARK. The same role and the same caution as for
#: the mesh: it is written ONLY into an empty field, someone else's value
#: is never overwritten.
HONEST_MARK = ("KIR NURBS-оболочка: геометрия без BIM-смысла "
               "(нет типа/параметров/спецификации)")

#: Decimal places in a coordinate literal. A load-bearing number, not
#: formatting: the witness's tolerance is derived EXACTLY from it, so it
#: must have a name rather than sit as six scattered `round(..., 2)` calls
#: through the text.
EMIT_DECIMALS = 2

#: The full consequence of `EMIT_DECIMALS`: a printed point is no farther
#: from the ideal one than the quantum, along each axis. The same
#: derivation and the same name as `contour.EMIT_COORD_QUANTUM_MM`, but no
#: OWN number is introduced here — it is imported below where it is
#: needed, so the two constants cannot drift apart.
EMIT_COORD_QUANTUM_MM = 10.0 ** (-EMIT_DECIMALS)


def _pt(p: list) -> str:
    return (f"P({round(p[0], EMIT_DECIMALS)}, {round(p[1], EMIT_DECIMALS)}, "
            f"{round(p[2], EMIT_DECIMALS)})")


def _pts(points: list) -> str:
    return ", ".join(_pt(p) for p in points)


def _doubles(values: list) -> str:
    return ", ".join(repr(float(v)) for v in values)


def emit_surface(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Surface -> DirectShape. There is no version fork: everything named
    is measured 6/6.

    Returns (decl, create, checks, readback) — the package's emitter
    contract.
    """
    oid = op["id"]
    s = _safe(oid)
    srf = op["surface"]
    pts = srf["control_points_mm"]
    du, dv = srf["degree_u"], srf["degree_v"]
    cu, cv = srf["count_u"], srf["count_v"]
    weights = srf.get("weights")
    member = DIRECTSHAPE_CATEGORIES[op["category"]]
    n_pts = len(pts)

    # ═══ SURFACE SAMPLES — COMPUTED FROM THE SAME NUMBERS THAT WILL TRAVEL
    # INTO C# ═══
    #
    # 🔴 THE ROUNDING HERE IS LOAD-BEARING, NOT COSMETIC. Revit builds the
    # surface from the PRINTED control points (`_pt` rounds to
    # EMIT_DECIMALS). Had we computed the samples from the EXACT points, the
    # witness would be comparing a surface through one grid with a surface
    # through another, and it would turn red on its own rounding — that is,
    # on a quantity it introduced itself. Computing from the rounded points
    # leaves exactly one source of discrepancy: the printing of the samples
    # themselves, and the tolerance equals the printing quantum.
    _rounded = dict(srf)
    _rounded["control_points_mm"] = [
        [round(c, EMIT_DECIMALS) for c in q] for q in pts]
    samples = sample_surface(_rounded)
    n_samples = len(samples)

    # DECLARATIONS — IN THE OUTER SCOPE: with isolation="per_op" the
    # creation block and the postcondition blocks fall into DIFFERENT
    # scopes, and a variable declared inside create is invisible to the
    # witness (CS0103 — the same seam the first version of the railing
    # emitter failed on).
    decl = (f"DirectShape __el_{s} = null;\n"
            f"Solid __sol_{s} = null;\n"
            f"XYZ[] __cp_{s} = null;\n"
            f"bool __avail_{s} = false;\n"
            f"bool __removed_{s} = true;\n"
            f"bool __lbl_{s} = false;\n"
            # 🔴 THE FOUR QUANTITIES THE RECEIPT READS LIVE IN `decl`, NOT
            # IN THE WITNESS'S `reader_cs`. The canonical scope contract:
            # `per_op` wraps create in its own brace, and a name declared
            # inside it dies at the closing one — class CS0103. Paid for by
            # the live run of 20.08: `CS0103: __bdu_S1 does not exist in the
            # current context`, and this is the SAME form the surface wave
            # had already fixed for the `__need_`/`__want_` pair and missed
            # here. A second carrier in the same file is our named case.
            f"int __bdu_{s} = -1, __bdv_{s} = -1, __bpc_{s} = -1;\n"
            f"double __bw_{s} = -1.0;\n"
            # A GEOMETRIC comparison (see the "KIND OF LAW" block below):
            # the worst distance from an author sample to the built face,
            # and the number of the sample that did not project at all.
            f"XYZ[] __sp_{s} = null;\n"
            f"double __sw_{s} = -1.0;\n"
            f"int __sbad_{s} = -1;\n"
            # The outcome of `Finish()` is read by THE RECEIPT, so the
            # declaration lives here, not inside `create` — the same scope
            # contract as the degree pair above (class CS0103).
            f"string __outcome_{s} = null;")

    w_arg = (f"new List<double> {{ {_doubles(weights)} }}, "
             if weights is not None else "")

    # Boundaries: rows and columns of control points. Computed IN PYTHON,
    # so that C# does not end up with a second arithmetic over the same
    # data.
    edge_u0 = row_u(pts, 0, cv)
    edge_u1 = row_u(pts, cu - 1, cv)
    edge_v0 = col_v(pts, 0, cu, cv)
    edge_v1 = col_v(pts, cv - 1, cu, cv)

    def _edge_cs(var: str, degree: int, knots: list, row: list,
                 w_row: list | None) -> str:
        wa = (f", new List<double> {{ {_doubles(w_row)} }}"
              if w_row is not None else "")
        return (f"Curve {var} = NurbSpline.CreateCurve({degree}, "
                f"new List<double> {{ {_doubles(knots)} }}, "
                f"new List<XYZ> {{ {_pts(row)} }}{wa});")

    w_u0 = w_u1 = w_v0 = w_v1 = None
    if weights is not None:
        w_u0 = row_u(weights, 0, cv)
        w_u1 = row_u(weights, cu - 1, cv)
        w_v0 = col_v(weights, 0, cu, cv)
        w_v1 = col_v(weights, cv - 1, cu, cv)

    # THE REFUSAL CARRIES THE OUTCOME, NOT JUST THE FACT. "Produced no
    # result" is a consequence; `BRepBuilderOutcome` is what Revit itself
    # said. The expression is assembled HERE, not in an f-string: a quote
    # inside an f-string expression does not parse on Python 3.10, and an
    # instrument has no right to depend on which interpreter called it.
    # 🔴 THE REFUSAL CARRIES EVERYTHING WE HAVE ALREADY MEASURED, NOT ONE
    # OF THREE. `IsResultAvailable()` and `RemovedSomeFaces()` are read one
    # line above and, before 20.08.2026, never traveled anywhere: the
    # refusal named only `Finish()`. This is the same form that was closed
    # for the bounding box and for the surface on the same day — the
    # message stays silent about a value that is already sitting in a
    # variable. Here it is more costly than usual: a live measurement
    # yielded 46 built patches out of 48, with the reason for the other
    # two's failure UNKNOWN, and every unnamed sign is one more live
    # attempt.
    #
    # THE NEXT MOVE in the text is not politeness, it is a requirement of
    # the canon: a refusal that names a code without a move offloads the
    # work onto the reader. Here there is exactly one move and it is
    # honest: this patch is independent of its neighbors, so it is
    # restarted SEPARATELY, and the neighbors were rolled back through no
    # fault of their own.
    _outcome_msg = (
        '"BRepBuilder не собрал оболочку: Finish() -> " + __outcome_' + s
        + ' + ", результат доступен: " + (__avail_' + s + ' ? "да" : "нет")'
        + ' + ", грань выброшена: " + (__removed_' + s + ' ? "да" : "нет")'
        + ' + ". СЛЕДУЮЩИЙ ХОД: причина отказа BRepBuilder на законном входе '
        'НЕ НАЗВАНА (сняты замером: положение, ориентация, плоскостность, '
        'амплитуда, округление, регулярность). Этот лоскут независим от '
        'соседей — перезапусти его отдельной программой; соседи в этой '
        'транзакции откатились не по своей вине."')
    _no_shell_refusal = refuse_stmt(oid, _outcome_msg, isolation)

    create = (
        f"// create_surface {cs_line_comment_fragment(oid)} — "
        f"сетка {cu}×{cv} = {n_pts} контрольных точек, степень {du}×{dv}\n"
        f"ElementId __cat_{s} = new ElementId(BuiltInCategory.{member});\n"
        # The category is asked OF THE DOCUMENT, not from our table: it
        # can be disabled in the project template, and then CreateElement
        # will return null after we have already decided everything is
        # fine.
        f"if (!DirectShape.IsValidCategoryId(__cat_{s}, doc)) {{ "
        f"{refuse_stmt(oid, _cs('категория недопустима для DirectShape в этом документе'), isolation)} }}\n"
        f"__cp_{s} = new XYZ[] {{ {_pts(pts)} }};\n"
        f"__sp_{s} = new XYZ[] {{ {_pts(samples)} }};\n"
        f"BRepBuilderSurfaceGeometry __srf_{s} = "
        f"BRepBuilderSurfaceGeometry.CreateNURBSSurface({du}, {dv}, "
        f"new List<double> {{ {_doubles(srf['knots_u'])} }}, "
        f"new List<double> {{ {_doubles(srf['knots_v'])} }}, "
        f"new List<XYZ>(__cp_{s}), {w_arg}false, null);\n"
        # EXACT BOUNDARY CURVES — see item 2 of the header.
        + _edge_cs(f"__eu0_{s}", dv, srf["knots_v"], edge_u0, w_u0) + "\n"
        + _edge_cs(f"__eu1_{s}", dv, srf["knots_v"], edge_u1, w_u1) + "\n"
        + _edge_cs(f"__ev0_{s}", du, srf["knots_u"], edge_v0, w_v0) + "\n"
        + _edge_cs(f"__ev1_{s}", du, srf["knots_u"], edge_v1, w_v1) + "\n"
        f"BRepBuilder __bb_{s} = new BRepBuilder(BRepType.OpenShell);\n"
        # 🔴 THIS IS NOT A RELAXATION, IT IS A QUESTION TO REVIT — and it
        # answered.
        #
        # Measured 20.08.2026. A `Finish() -> Failure` refusal on a legal
        # patch was not explained by ANY computable measure of the input:
        # ruled out were position, orientation (transposition), planarity,
        # amplitude (the dependency is non-monotonic), print rounding,
        # regularity (|Su x Sv| was the LARGEST of the 48 among the ones
        # that failed), knot-vector scale (×1, ×10, ×3000), and shifting
        # one interior point (0, ±0.01, ±0.1, +1, +10 mm — all seven failed
        # the same way).
        #
        # With this call the builder for the first time SAID what exactly
        # it dislikes: `RemovedSomeFaces()` became `true` under what used
        # to be `Failure`. So Revit considers THE FACE ITSELF the problem,
        # not the edges, the loop, or the orientation — and this narrows
        # the search from "unknown" to "the kernel rejects the surface".
        # The device is taken from the production converter
        # Rhino.Inside.Revit (`BrepEncoder.cs`), which turns it on
        # unconditionally.
        #
        # THERE IS NO SILENT SUBSTITUTION HERE BY CONSTRUCTION: we always
        # have exactly ONE face, so removing it leaves an empty shell,
        # `IsResultAvailable()` stays `false`, and the op refuses as
        # before. A partial result cannot be obtained.
        #
        # `SetAllowShortEdges()` is called by that same converter right
        # next to it — ours does NOT SET it: on this input it changed
        # nothing measurable, and a change justified by someone else's
        # practice instead of our own measurement is exactly the shape
        # this house forbids. A named candidate, not a decision.
        f"__bb_{s}.AllowRemovalOfProblematicFaces();\n"
        f"BRepBuilderGeometryId __f_{s} = __bb_{s}.AddFace(__srf_{s}, false);\n"
        f"BRepBuilderGeometryId __a_{s} = __bb_{s}.AddEdge("
        f"BRepBuilderEdgeGeometry.Create(__eu0_{s}));\n"
        f"BRepBuilderGeometryId __b_{s} = __bb_{s}.AddEdge("
        f"BRepBuilderEdgeGeometry.Create(__ev1_{s}));\n"
        f"BRepBuilderGeometryId __c_{s} = __bb_{s}.AddEdge("
        f"BRepBuilderEdgeGeometry.Create(__eu1_{s}));\n"
        f"BRepBuilderGeometryId __d_{s} = __bb_{s}.AddEdge("
        f"BRepBuilderEdgeGeometry.Create(__ev0_{s}));\n"
        f"BRepBuilderGeometryId __lp_{s} = __bb_{s}.AddLoop(__f_{s});\n"
        # 🔴 THE OUTER CONTOUR IS TRAVERSED COUNTER-CLOCKWISE IN THE UV
        # PLANE, AND THIS IS AN AUTODESK REQUIREMENT, NOT TASTE. `AddCoEdge`,
        # verbatim (RevitAPI.xml, param `bCoEdgeIsReversed`, all six
        # versions): «the loop orientations so defined must follow the
        # convention that outer loops are oriented COUNTER-CLOCKWISE and
        # inner loops are oriented clockwise».
        #
        # The first edition went CLOCKWISE: the traversal
        # (0,0)->(0,v_max)->(u_max,v_max)->(u_max,0)->(0,0) gives a doubled
        # area of −18 on a 4×4 grid, i.e. negative. Live, this produced our
        # own typed refusal "Revit did not assemble the shell (BRepBuilder
        # gave no result)" — honest, but unnamed: it named the CONSEQUENCE
        # and stayed silent about the cause.
        #
        # The co-edge order is reversed wholesale, together with the flags:
        # d, c, b, a with opposite `bCoEdgeIsReversed`. A half-fix (only the
        # order, or only the flags) would have given a torn contour, not a
        # reversed one.
        f"__bb_{s}.AddCoEdge(__lp_{s}, __d_{s}, false);\n"
        f"__bb_{s}.AddCoEdge(__lp_{s}, __c_{s}, false);\n"
        f"__bb_{s}.AddCoEdge(__lp_{s}, __b_{s}, true);\n"
        f"__bb_{s}.AddCoEdge(__lp_{s}, __a_{s}, true);\n"
        f"__bb_{s}.FinishLoop(__lp_{s});\n"
        f"__bb_{s}.FinishFace(__f_{s});\n"
        # 🔴 THE OUTCOME OF `Finish()` IS READ, NOT DISCARDED. The method
        # RETURNS `BRepBuilderOutcome` (Success|Failure) — a direct answer
        # to the question "did it assemble". The first edition called it as
        # a procedure and derived the answer from `IsResultAvailable()`,
        # i.e. it asked the CONSEQUENCE while holding the CAUSE in hand. The
        # enum exists on all six versions (checked against
        # `data/api_surface/`), so there is no version fork here.
        f"BRepBuilderOutcome __out_{s} = __bb_{s}.Finish();\n"
        f"__outcome_{s} = __out_{s}.ToString();\n"
        f"__avail_{s} = __bb_{s}.IsResultAvailable();\n"
        f"__removed_{s} = __bb_{s}.RemovedSomeFaces();\n"
        # REFUSAL BEFORE THE EFFECT. A shell whose one and only face Revit
        # dropped is an empty element, indistinguishable from success from
        # the outside.
        # THE REFUSAL CARRIES THE OUTCOME, NOT JUST THE FACT. "Produced no
        # result" is a consequence; `BRepBuilderOutcome` is what Revit
        # itself said, and whoever reads the refusal must see exactly
        # that.
        f"if (!__avail_{s}) {{ {_no_shell_refusal} }}\n"
        f"if (__removed_{s}) {{ "
        f"{refuse_stmt(oid, _cs('Revit выбросил грань как проблемную — построенная оболочка не та, что заказана'), isolation)} }}\n"
        f"__sol_{s} = __bb_{s}.GetResult();\n"
        f"__el_{s} = DirectShape.CreateElement(doc, __cat_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('создание DirectShape вернуло null'), isolation)} }}\n"
        f"__el_{s}.SetShape(new List<GeometryObject> {{ __sol_{s} }});\n"
        f"__el_{s}.Name = {_cs(op['name'])};\n"
        f"Parameter __mk_{s} = __el_{s}.get_Parameter(BuiltInParameter.ALL_MODEL_MARK);\n"
        f"if (__mk_{s} != null && !__mk_{s}.IsReadOnly && "
        f"string.IsNullOrEmpty(__mk_{s}.AsString()))\n"
        f"    __lbl_{s} = __mk_{s}.Set({_cs(HONEST_MARK)});\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    tol = tolerance("create_surface", "control_point_mm")

    checks: list[WitnessCheck] = [
        # ONE FACE. A shell built from a single surface must give exactly
        # one face; two would mean Revit cut it along a seam, and the
        # read-back below would be comparing half against the whole.
        WitnessCheck(
            obligation_key="faces",
            reader_cs=(f"    int __fn_{s} = __sol_{s} == null ? -1 : "
                       f"__sol_{s}.Faces.Size;\n"),
            verdict_cs=(
                f"    if (__fn_{s} != 1)\n"
                f"        __post.Add({_cs(oid + ': built shell face count != 1 (geometry)')});\n"),
            message="built shell face count != 1 (geometry)",
            style="guard"),
        # IS IT THE RIGHT SURFACE: the degrees and the control-point count,
        # read BACK with the same instrument the compiler's read-back path
        # uses to read them.
        WitnessCheck(
            obligation_key="nurbs_shape",
            reader_cs=(
                f"    if (__sol_{s} != null)\n    {{\n"
                f"        foreach (Face __fc_{s} in __sol_{s}.Faces)\n        {{\n"
                f"            Surface __su_{s} = __fc_{s}.GetSurface();\n"
                f"            if (__su_{s} == null) continue;\n"
                # 🔴 THIS CALL THROWS, AND THE GUARD WAS CHECKING FOR
                # `null` (20.08.2026, found by a query against
                # `data/api_traps`). `GetNurbsSurfaceDataForSurface`
                # documents two throws on ALL SIX versions, zero drift:
                #   ArgumentException «This surface type is not supported
                #   for this function» — the face is the wrong kind (flat,
                #   cylindrical, conical);
                #   InvalidOperationException «Couldn't get NURBS data from
                #   surface».
                # A check for `null` does not save us from the throw AT
                # ALL: execution never reaches it. The program would die
                # with an unhandled Revit exception, i.e. the author would
                # get an "internal error" instead of a named outcome.
                #
                # WHEN THIS FIRES. Exactly when Revit COLLAPSES the
                # representation to a non-NURBS one. What it collapses was
                # measured live that same day: a ruled saddle 4×4 of degree
                # 3×3 read back as 1×1 with four points. A flat grid by the
                # same logic becomes a `PlanarFace`, and then the face has
                # NO NURBS DATA AT ALL.
                #
                # WHY THE `catch` IS SILENT, NOT A REFUSAL. The witness
                # here is TRYING to read; being unable to read is not a
                # postcondition violation but a named absence, and it is
                # already expressed: the sentinel `__bdu` stays unread, and
                # the verdict below prints "the built surface does not read
                # back as NURBS". Swallowing the exception here is honest
                # precisely because its consequence HAS A NAME one line
                # below.
                f"            NurbsSurfaceData __nd_{s} = null;\n"
                f"            try {{ __nd_{s} = Autodesk.Revit.DB.ExportUtils"
                f".GetNurbsSurfaceDataForSurface(__su_{s}); }}\n"
                f"            catch (Autodesk.Revit.Exceptions.ArgumentException) {{ }}\n"
                f"            catch (Autodesk.Revit.Exceptions.InvalidOperationException) {{ }}\n"
                f"            if (__nd_{s} == null || !__nd_{s}.IsValid()) continue;\n"
                f"            __bdu_{s} = __nd_{s}.DegreeU;\n"
                f"            __bdv_{s} = __nd_{s}.DegreeV;\n"
                f"            IList<XYZ> __bp_{s} = __nd_{s}.GetControlPoints();\n"
                f"            __bpc_{s} = __bp_{s}.Count;\n"
                # THE DISCREPANCY IS COMPUTED IN INTERNAL UNITS — see the header.
                f"            if (__bpc_{s} == __cp_{s}.Length)\n            {{\n"
                f"                __bw_{s} = 0.0;\n"
                f"                for (int __i_{s} = 0; __i_{s} < __bpc_{s}; __i_{s}++)\n"
                f"                {{\n"
                f"                    double __dd_{s} = Math.Max(Math.Max(\n"
                f"                        Math.Abs(__bp_{s}[__i_{s}].X - __cp_{s}[__i_{s}].X),\n"
                f"                        Math.Abs(__bp_{s}[__i_{s}].Y - __cp_{s}[__i_{s}].Y)),\n"
                f"                        Math.Abs(__bp_{s}[__i_{s}].Z - __cp_{s}[__i_{s}].Z));\n"
                f"                    if (__dd_{s} > __bw_{s}) __bw_{s} = __dd_{s};\n"
                f"                }}\n"
                f"            }}\n"
                f"            __nd_{s}.Dispose();\n"
                f"            break;\n"
                f"        }}\n"
                f"    }}\n"),
            # 🔴 THE VIOLATION CARRIES THE MEASURED NUMBER, NOT ONLY THE
            # EXPECTED ONE. Found by the first live run of 20.08.2026: the
            # witness refused with "read-back NURBS degree != authored
            # 3x3" and did NOT SAY what it had read. The number had, in
            # fact, been measured — it sits in `__bdu` and lands in the
            # receipt as the `read_back_degree_u` field — but on a
            # postcondition violation the transaction is rolled back, the
            # receipt is not assembled, and the sole carrier left is the
            # violation's text. That is, the instrument stayed silent
            # exactly where it knew the answer, and the next move became
            # one more live attempt instead of a fix.
            # THE GENERAL RULE, worth more than this one fix: a message of
            # the form "X != expected Y" must print X. The reader already
            # sees the expected value in the program; the measured one is
            # seen by NOBODY, EVER.
            # 🔴 THE KIND OF LAW WAS CHANGED ON THE EVENING OF 20.08.2026,
            # BY A LIVE MEASUREMENT.
            #
            # The former law required the degree and control-point count
            # read back to EQUAL the authored ones. The live run showed
            # this to be a demand on REVIT that Revit never took on:
            #
            #   dome 4×4 degree 3×3    -> read back 3×3, 16 points, 5.4e-13 mm
            #   saddle 4×4 degree 3×3  -> read back 1×1, 4 points
            #
            # The saddle is a hyperbolic paraboloid, a RULED surface and
            # therefore EXACTLY representable by a bilinear patch; the
            # kernel collapsed the representation to the minimal one. The
            # geometry matched, the parametrization did not. The former law
            # gave a FALSE RED here — the worst kind of instrument error:
            # it forbids correct work and teaches the author to route
            # around the witness.
            #
            # What remains a violation: a face that could not be read as
            # NURBS at all. This still means "what was built is not what
            # was ordered", and it cannot be passed over in silence.
            #
            # What became a FACT, not a violation: a different degree and
            # a different point count. They travel into the receipt
            # (`representation_changed`, `read_back_degree_u/v`,
            # `read_back_control_points`), because knowing this is useful —
            # but it cannot be used to judge.
            verdict_cs=(
                f"    if (__bdu_{s} < 0)\n"
                f"        __post.Add({_cs(oid + ': построенная грань не читается как NURBS — ни одна грань не отдала NurbsSurfaceData (geometry)')});\n"),
            message="built face is not readable as NURBS (geometry)",
            style="guard"),
        # GEOMETRIC EQUALITY — THE MAIN LAW OF THIS OPERATION.
        #
        # The assertion: EVERY sample of the author's surface lies ON the
        # built face. It does not mention parametrization by a single word,
        # and so it survives any collapse of the representation.
        #
        # `Face.Project` returns the face's nearest point; the distance to
        # it is the discrepancy. `null` means "the projection falls outside
        # the face's boundary" — a separate outcome with a separate
        # message, because "the surface is not there" and "the face is
        # trimmed differently" are fixed differently.
        WitnessCheck(
            obligation_key="surface_samples",
            reader_cs=(
                f"    if (__sol_{s} != null && __sol_{s}.Faces.Size == 1 "
                f"&& __sp_{s} != null)\n    {{\n"
                f"        Face __pf_{s} = __sol_{s}.Faces.get_Item(0);\n"
                f"        __sw_{s} = 0.0;\n"
                f"        for (int __j_{s} = 0; __j_{s} < __sp_{s}.Length; __j_{s}++)\n"
                f"        {{\n"
                f"            IntersectionResult __ir_{s} = __pf_{s}.Project(__sp_{s}[__j_{s}]);\n"
                f"            if (__ir_{s} == null) {{ __sbad_{s} = __j_{s}; break; }}\n"
                f"            double __dp_{s} = __ir_{s}.XYZPoint.DistanceTo(__sp_{s}[__j_{s}]);\n"
                f"            if (__dp_{s} > __sw_{s}) __sw_{s} = __dp_{s};\n"
                f"        }}\n"
                f"    }}\n"),
            verdict_cs=(
                f"    if (__sbad_{s} >= 0)\n"
                f"        __post.Add({_cs(oid + ': образец №')} + __sbad_{s} + {_cs(f' из {n_samples} не спроецировался на построенную грань — грань обрезана не по заказанной границе (geometry)')});\n"
                f"    else if (__sw_{s} < 0.0)\n"
                f"        __post.Add({_cs(oid + ': образцы поверхности не сверялись — грань недоступна (geometry)')});\n"
                f"    else if (__sw_{s} > U({tol}))\n"
                f"        __post.Add({_cs(oid + ': авторская поверхность не лежит на построенной: худший из ')} + {n_samples} + {_cs(' образцов ')} + MM(__sw_{s}).ToString(\"F4\") + {_cs(f' мм при допуске {tol} мм (geometry)')});\n"),
            message="authored surface does not lie on the built face (geometry)",
            tol=tol,
            style="guard"),
        # ARE THEY THE RIGHT POINTS. A separate check from the previous
        # one, DELIBERATELY: "the degree is the same but the points differ"
        # and "the degree differs" require different fixes, and one code
        # for two outcomes is a named defect of this tree.
        WitnessCheck(
            obligation_key="control_points",
            reader_cs="",
            # A STRONG ASSERTION WHEN IT IS POSSIBLE. If the degree and
            # the point count match, we compare the grids point by point:
            # this is EXACT and cheap, and it says more than a sample. If
            # they do not match, we stay silent HERE, but not silent
            # overall: the geometric law above checks the same thing
            # invariantly. One "not compared" without the second law would
            # be a hole; with it, it is a division of labor.
            verdict_cs=(
                f"    if (__bw_{s} >= 0.0 && __bw_{s} > U({tol}))\n"
                f"        __post.Add({_cs(oid + ': read-back control points differ from the authored grid: худшая ')} + MM(__bw_{s}).ToString(\"F4\") + {_cs(f' мм при допуске {tol} мм (geometry)')});\n"),
            message="read-back control points mismatch (geometry)",
            tol=tol,
            style="guard"),
    ]

    x0, y0, z0, x1, y1, z1 = surface_bbox(pts)
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"name\"] = __el_{s}.Name;\n"
        f"    __rb[\"category\"] = {_cs(op['category'])};\n"
        f"    __rb[\"kind\"] = \"direct_shape_nurbs_surface\";\n"
        f"    __rb[\"degree_u\"] = {du};\n"
        f"    __rb[\"degree_v\"] = {dv};\n"
        f"    __rb[\"control_points\"] = {n_pts};\n"
        f"    __rb[\"rational\"] = {'true' if weights is not None else 'false'};\n"
        # What Revit actually did to the shell. On the first live run
        # this is the first thing worth reading, and it is worth two
        # lines.
        f"    __rb[\"finish_outcome\"] = __outcome_{s};\n"
        f"    __rb[\"result_available\"] = __avail_{s};\n"
        f"    __rb[\"faces_removed\"] = __removed_{s};\n"
        # 🔴 A SENTINEL MUST NOT LEAVE AS A NUMBER. Found by the director
        # on the saddle's live receipt of 20.08: `worst_control_point_mm:
        # -304.8`. This is not a discrepancy of a third of a meter — it is
        # the sentinel −1.0 in internal feet, passed through `MM()`. The
        # worst part of it is not the error itself but its PLAUSIBILITY:
        # −304.8 looks like a measurement, so nobody will argue with it, and
        # the reader of the receipt will walk away with "an error of 304
        # mm" where in fact it was "not compared".
        #
        # A rule of the tree, paid for three times today (for the blend —
        # `volume_mm3_expected: 0` against a measured 1.03e11, here —
        # twice): AN UNCOMPARED QUANTITY IS PRINTED AS null WITH A WORDED
        # REASON. Zero and a sentinel both look like a value; null looks
        # like nothing, and that is exactly what needs to be said.
        f"    __rb[\"read_back_degree_u\"] = __bdu_{s} < 0 ? (object)null : (object)__bdu_{s};\n"
        f"    __rb[\"read_back_degree_v\"] = __bdv_{s} < 0 ? (object)null : (object)__bdv_{s};\n"
        f"    __rb[\"read_back_control_points\"] = __bpc_{s} < 0 ? (object)null : (object)__bpc_{s};\n"
        f"    __rb[\"worst_control_point_mm\"] = __bw_{s} < 0.0 ? (object)null : (object)MM(__bw_{s});\n"
        f"    __rb[\"control_point_comparison_ru\"] = __bw_{s} < 0.0\n"
        f"        ? {_cs('контрольные точки не сверялись: прочитано ')} + "
        f"(__bpc_{s} < 0 ? {_cs('ничего')} : __bpc_{s}.ToString()) + "
        f"{_cs(f' против {n_pts} авторских — Revit сменил представление. Поверхность доказана ВЫБОРКОЙ, см. worst_sample_mm')}\n"
        f"        : {_cs('сетки сверены поточечно, худшая ')} + MM(__bw_{s}).ToString(\"F6\") + {_cs(' мм')};\n"
        # 🔴 A COLLAPSE OF THE REPRESENTATION IS A RECEIPT FACT, NOT A
        # VIOLATION. Revit is entitled to represent the same surface
        # differently (the saddle 4×4 of degree 3×3 read back as a
        # bilinear 1×1). This cannot be used to judge, but it IS useful to
        # KNOW: the read-back path will read exactly the collapsed form,
        # and the round trip "built -> read -> reassembled" will return a
        # different program than the one that was sent. Silently, this
        # would look like a loss of the author's intent; named, it looks
        # like a property of Revit.
        # The same law: "we could not read it" and "it did not change" are
        # different things.
        f"    __rb[\"representation_changed\"] = __bdu_{s} < 0 ? (object)null "
        f": (object)(__bdu_{s} != {du} || __bdv_{s} != {dv} "
        f"|| __bpc_{s} != {n_pts});\n"
        f"    __rb[\"samples\"] = {n_samples};\n"
        f"    __rb[\"worst_sample_mm\"] = __sw_{s} < 0.0 ? (object)null : (object)MM(__sw_{s});\n"
        f"    __rb[\"sample_comparison_ru\"] = __sw_{s} < 0.0\n"
        f"        ? {_cs('образцы не сверялись: построенная грань недоступна — это НЕ «расхождения нет»')}\n"
        f"        : {_cs(f'{n_samples} образцов авторской поверхности спроецированы на грань, худший ')} + MM(__sw_{s}).ToString(\"F6\") + {_cs(' мм')};\n"
        # AN HONEST LABEL — the same as for the mesh, and for the same reason.
        f"    __rb[\"bim_semantics\"] = \"none\";\n"
        f"    __rb[\"has_type\"] = false;\n"
        f"    __rb[\"schedulable_as_building_element\"] = false;\n"
        f"    __rb[\"human_editable\"] = false;\n"
        f"    __rb[\"honest_label_written\"] = __lbl_{s};\n"
        f"    __rb[\"authored_bbox_mm\"] = new double[] {{ "
        f"{round(x0, 2)}, {round(y0, 2)}, {round(z0, 2)}, "
        f"{round(x1, 2)}, {round(y1, 2)}, {round(z1, 2)} }};\n"
        f"    __results[{_cs(oid)}] = __rb;\n"
        f"}}\n")

    return decl, create, checks, readback


#: WHAT THIS SPOKE EMITS IS DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: The "op -> body" mapping used to live in the hand-written
#: `authoring._EMITTERS`, with the body here, and a thin wrapper in the hub
#: linked the two (41 of them across 19 satellites). Two records of one
#: fact in different files is a named defect of this tree; now there is
#: ONE record, and the hub ASKS it.
EMITTERS = {
    "create_surface": emit_surface,
}
