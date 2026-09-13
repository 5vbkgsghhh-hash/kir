"""surface_query — READING A BUILT SURFACE. Closing the round trip.

    create_surface   language -> model      (surface_emit.py)
    query_surface    model -> language      (this file)

WHY. Before 20.08.2026 the author could BUILD a smooth shell and could not
READ it back. A panel would not seat onto an existing shell: the 48-panel
paneling done that same day computed points from ITS OWN formula, not from
the surface standing in the model. That is the open loop — in Grasshopper,
"take a surface and divide it" is the single most common action there is.

═══════════════════════════════════════════════════════════════════════════════
THE SHAPE WAS CHOSEN BY MEASUREMENT, NOT BY TASTE. TWO REJECTED — WITH THE ARGUMENT
═══════════════════════════════════════════════════════════════════════════════

**REJECTED (a): return ONLY the NURBS definition, and let the author compute.**
The argument in its favor was strong — the round trip would close with the
SAME instrument the compiler's read-back path uses to read a surface, and a
second carrier of the knowledge would not spring up. Refuted by two
measured facts:

1. **The author has nothing to compute with.** The sandbox's whitelist is
   `math, itertools, functools, collections, dataclasses, typing,
   __future__` (plus `shapely`/`numpy` behind an operator flag).
   `kir.surface` is NOT in it, meaning the verified de Boor computation
   (`surface.py:397-543`, cross-checked against an INDEPENDENT answer —
   Bernstein polynomials and an exact quarter circle) is unavailable to the
   author. Handing them the control points would mean forcing them to
   write de Boor BY HAND in every program: a second carrier, and an
   unverified one at that — exactly what argument (a) wanted to avoid. And
   our verified one would remain uncalled — the very defect this day
   started with (`create_directshape` sat unused for 22 days).
2. **The definition may not exist AT ALL.** `ExportUtils
   .GetNurbsSurfaceDataForSurface` documents a throw on ALL SIX versions
   (`data/api_traps`, zero drift): `ArgumentException` «This surface type
   is not supported for this function» and `InvalidOperationException`
   «Couldn't get NURBS data from surface». A flat or cylindrical face has
   no NURBS data, and shape (a) has no answer for it at all.

**REJECTED (b): return a grid of points and normals, and only that.** Then
the grid's density is chosen by US, and the result cannot be fed back into
`create_surface` — the loop does not close, an arc remains.

**CHOSEN (c): one reading of one face, returning BOTH answers, each
named.** The NURBS definition — when the face gives one — in EXACTLY the
keys `create_surface` accepts (read → edit → build). The grid — when the
author NAMED its density (`u_count`/`v_count`); at zero it is not computed
at all.

🔴 THE TWO ANSWERS ARE TWO INDEPENDENT READINGS, and they must not diverge
silently. The definition is read by `GetNurbsSurfaceDataForSurface`, the
points by `Face.Evaluate`; these are DIFFERENT instruments, and Revit is
free to canonicalize the surface between them (what it canonicalizes was
measured live: a ruled saddle 4×4 of degree 3×3 read back as 1×1 with four
points). So both answers travel labeled with the instrument that produced
them, and are never passed off as one another.

═══════════════════════════════════════════════════════════════════════════════
WHAT THIS OP DOES NOT DO — NAMED, NOT PASSED OVER IN SILENCE
═══════════════════════════════════════════════════════════════════════════════

* **arbitrary (u,v) pairs are not accepted, only a UNIFORM grid.** The
  reason is technical and honest: a list of pairs would require a new kind
  in the CLOSED `spec.PARAM_KINDS` table, and that is someone else's file
  and a separate decision. A u×v grid is the same division `DividedSurface`
  itself divides by, so the common case is fully covered;
* **an element with SEVERAL faces is read only by count.** Which face is
  "the one" is a question we have no answer to without addressing faces,
  and a guessed face is worse than a named refusal;
* **a face's parametrization is NOT NORMALIZED in Revit.** `Face.Evaluate`
  takes the face's OWN domain (the knot range), not [0,1]². The author does
  not know it, so the op accepts normalized fractions and maps them onto
  the domain ITSELF — and returns the domain in the answer, so the mapping
  is visible, not magic;
* **trimming of the face.** A point inside the UV bounding box can lie
  OUTSIDE the face itself (the face is trimmed). `Face.Evaluate` will still
  return a point in that case — on the underlying surface, silently. So
  every point travels with `inside`, read from `Face.IsInside`, and the
  author sees which grid nodes fall outside the edge.
"""
from __future__ import annotations

from typing import Any

from kir.emit_utils import (cs_identifier_fragment,
                                 cs_line_comment_fragment,
                                 cs_string_literal)

#: The largest side of the sample grid.
#: ⚠️ ASSIGNED, not measured, and flagged just as honestly as `MAX_DEGREE`
#: in `surface.py`. The lower bound is derived: 1 gives a single point, so
#: the grid degenerates and the question "where is the panel" loses
#: meaning. The upper one is a decision: 64×64 is 4096 points, as many as
#: the mesh has triangles, and by then the cost of reading is already
#: comparable to the cost of building. It is allowed to be lowered on a
#: live run and FORBIDDEN to be raised silently — the same formula as the
#: mesh's limit.
GRID_MAX = 64

#: The keys with which `create_surface` accepts a surface. Read FROM HERE
#: by import, not retyped: two tables that are bound to match drift apart
#: silently — and here their matching is precisely what closes the round
#: trip.
from kir.surface import _FIELDS_REQUIRED as SURFACE_FIELDS  # noqa: E402


def validate_grid(op: dict, oid: str, diags: list, fail) -> None:
    """`u_count`/`v_count` — both or neither, and both within bounds.

    BOTH OR NEITHER — because a 5×0 grid makes no sense either as a grid or
    as a refusal of one, and silently filling in the second number would be
    a choice made on the author's behalf.
    """
    u, v = op.get("u_count"), op.get("v_count")
    if (u is None) != (v is None):
        fail(diags, code="KIR-T001", op_id=oid,
             field_name="u_count" if u is None else "v_count",
             message_ru=("сетка выборки задаётся ПАРОЙ u_count/v_count: "
                         "одно без другого не сетка. СЛЕДУЮЩИЙ ХОД: назови "
                         "оба числа либо не называй ни одного — тогда "
                         "вернётся только определение поверхности"))
        return
    for field, value in (("u_count", u), ("v_count", v)):
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool) \
                or not 2 <= value <= GRID_MAX:
            fail(diags, code="KIR-T002", op_id=oid, field_name=field,
                 got=value,
                 message_ru=(f"{field}: целое от 2 до {GRID_MAX}. Единица дала "
                             f"бы одну точку, то есть не сетку; предел "
                             f"{GRID_MAX} назначен по образцу предела меша и "
                             f"опускается по живому замеру, не молча"))


def emit_query_surface(op: dict, revit_version: str) -> str:
    """C# for a single read. Returns a body that puts the answer into `__results[oid]`."""
    oid = op["id"]
    s = cs_identifier_fragment(oid)
    tgt = op["target"]
    u_count, v_count = op.get("u_count"), op.get("v_count")

    # ── find the element. The same fork as in `query_inspect`, and for
    # the same reason: 64-bit ElementId only exists from 2024 onward.
    if tgt["by"] == "element_id":
        val = tgt["value"]
        if val <= 0x7FFFFFFF:
            find = (f"Element __t_{s} = null;\n"
                    f"try {{ __t_{s} = doc.GetElement(new ElementId({val})); }} catch {{ }}")
        elif revit_version >= "2024":
            find = (f"Element __t_{s} = null;\n"
                    f"try {{ __t_{s} = doc.GetElement(new ElementId({val}L)); }} catch {{ }}")
        else:
            find = (f"Element __t_{s} = null; // id вне 32-битного "
                    f"пространства ElementId на Revit {revit_version}")
    else:
        # THE SEARCH BY NAME IS RESTRICTED TO THE KIND, not run over the
        # whole document — the same law as in `query_inspect`, and it is
        # not about speed: scanning the document by name finds namesakes
        # from other categories and silently takes the first one. The
        # kind's collector is taken from `spec.KINDS`, not retyped here:
        # two tables that are bound to match drift apart.
        from kir import spec as _spec
        ks = _spec.KINDS[tgt["kind"]]
        base = (f"new FilteredElementCollector(doc){ks.collector_cs}"
                f".Cast<Element>()")
        if ks.where_cs:
            base += f".Where(e => {ks.where_cs})"
        find = (f"var __m_{s} = {base}\n"
                f"    .Where(e => (e.Name ?? \"\").Trim().Equals("
                f"{cs_string_literal(str(tgt['value']))}, "
                f"StringComparison.OrdinalIgnoreCase))\n"
                # 🔴 NOT `e.Id.IntegerValue`: it is REMOVED in Revit 2026
                # (CS1061), and only the six-version Roslyn check caught
                # this — the `by=element_id` path does not touch it, so
                # five versions out of six were green. This house has a
                # common helper for exactly this, `__IdOf`, and that is
                # what is used: a private idiom here would have been a
                # second carrier of the rule about ElementId.
                f"    .OrderBy(e => __IdOf(e)).ToList();\n"
                f"Element __t_{s} = (__m_{s}.Count == 1) ? __m_{s}[0] : null;")

    mm = "UnitUtils.ConvertFromInternalUnits({0}, UnitTypeId.Millimeters)"

    grid = ""
    if u_count:
        grid = (
            f"        var __smp_{s} = new List<object>();\n"
            f"        for (int __iu_{s} = 0; __iu_{s} < {u_count}; __iu_{s}++)\n"
            f"        for (int __iv_{s} = 0; __iv_{s} < {v_count}; __iv_{s}++)\n"
            f"        {{\n"
            f"            double __fu_{s} = {u_count} == 1 ? 0.0 : "
            f"(double)__iu_{s} / ({u_count} - 1);\n"
            f"            double __fv_{s} = {v_count} == 1 ? 0.0 : "
            f"(double)__iv_{s} / ({v_count} - 1);\n"
            f"            UV __uv_{s} = new UV(\n"
            f"                __ub_{s}.Min.U + __fu_{s} * (__ub_{s}.Max.U - __ub_{s}.Min.U),\n"
            f"                __ub_{s}.Min.V + __fv_{s} * (__ub_{s}.Max.V - __ub_{s}.Min.V));\n"
            f"            var __row_{s} = new Dictionary<string, object>();\n"
            f"            __row_{s}[\"uv_norm\"] = new double[] "
            f"{{ Math.Round(__fu_{s}, 6), Math.Round(__fv_{s}, 6) }};\n"
            f"            __row_{s}[\"uv_face\"] = new double[] "
            f"{{ Math.Round(__uv_{s}.U, 9), Math.Round(__uv_{s}.V, 9) }};\n"
            # 🔴 TRIMMING: a point inside the UV bounding box can lie
            # OUTSIDE the face, and Evaluate will return it silently — on
            # the underlying surface. The flag travels alongside the
            # point, not instead of it: the author is entitled to build
            # from exterior nodes too, but must KNOW they are exterior.
            f"            bool __in_{s} = false;\n"
            f"            try {{ __in_{s} = __f_{s}.IsInside(__uv_{s}); }} catch {{ }}\n"
            f"            __row_{s}[\"inside\"] = __in_{s};\n"
            f"            try {{\n"
            f"                XYZ __p_{s} = __f_{s}.Evaluate(__uv_{s});\n"
            f"                __row_{s}[\"point_mm\"] = new double[] {{\n"
            f"                    Math.Round({mm.format(f'__p_{s}.X')}, 3),\n"
            f"                    Math.Round({mm.format(f'__p_{s}.Y')}, 3),\n"
            f"                    Math.Round({mm.format(f'__p_{s}.Z')}, 3) }};\n"
            # The normal is dimensionless — there is nothing to convert.
            # It belongs to the FACE, not the underlying surface:
            # `Face.ComputeNormal` already accounts for the face's flip
            # (`OrientationMatchesSurfaceOrientation`), and that is what
            # the author needs when seating a panel outward.
            f"                XYZ __n_{s} = __f_{s}.ComputeNormal(__uv_{s});\n"
            f"                __row_{s}[\"normal\"] = new double[] {{\n"
            f"                    Math.Round(__n_{s}.X, 6), Math.Round(__n_{s}.Y, 6),\n"
            f"                    Math.Round(__n_{s}.Z, 6) }};\n"
            f"            }}\n"
            # Something not computed is `null` WITH A WORD, not a number.
            # A sentinel-as-number (a plausible-looking value standing in
            # for the unknown) was closed five times today in the
            # surface's receipt; we are not opening a new one.
            f"            catch (Exception __ex_{s})\n            {{\n"
            f"                __row_{s}[\"point_mm\"] = null;\n"
            f"                __row_{s}[\"normal\"] = null;\n"
            f"                __row_{s}[\"sample_absence_ru\"] = "
            f"\"точка не вычислена: \" + __ex_{s}.GetType().Name;\n"
            f"            }}\n"
            f"            __smp_{s}.Add(__row_{s});\n"
            f"        }}\n"
            f"        __r_{s}[\"samples\"] = __smp_{s};\n"
            f"        __r_{s}[\"samples_read_by\"] = \"Face.Evaluate + Face.ComputeNormal\";\n")
    else:
        grid = (f"        __r_{s}[\"samples\"] = null;\n"
                f"        __r_{s}[\"samples_absence_ru\"] = \"сетка не запрошена: "
                f"u_count/v_count не заданы\";\n")

    body = (
        f"// query_surface {cs_line_comment_fragment(oid)}\n{find}\n"
        f"{{\n"
        f"    var __r_{s} = new Dictionary<string, object>();\n"
        f"    if (__t_{s} == null) {{ __r_{s}[\"error\"] = \"not_found\"; }}\n"
        f"    else\n    {{\n"
        f"        __r_{s}[\"id\"] = __t_{s}.Id.ToString();\n"
        f"        __r_{s}[\"name\"] = __t_{s}.Name;\n"
        # ── collect faces. One level of instance nesting: DirectShape
        # gives solids directly, a family gives them through
        # GeometryInstance.
        f"        var __faces_{s} = new List<Face>();\n"
        f"        Options __o_{s} = new Options();\n"
        f"        __o_{s}.ComputeReferences = false;\n"
        f"        __o_{s}.DetailLevel = ViewDetailLevel.Fine;\n"
        f"        GeometryElement __ge_{s} = __t_{s}.get_Geometry(__o_{s});\n"
        f"        if (__ge_{s} != null)\n        foreach (GeometryObject __go_{s} in __ge_{s})\n"
        f"        {{\n"
        f"            Solid __so_{s} = __go_{s} as Solid;\n"
        f"            if (__so_{s} != null)\n"
        f"                foreach (Face __ff_{s} in __so_{s}.Faces) __faces_{s}.Add(__ff_{s});\n"
        f"            GeometryInstance __gi_{s} = __go_{s} as GeometryInstance;\n"
        f"            if (__gi_{s} != null)\n"
        f"                foreach (GeometryObject __g2_{s} in __gi_{s}.GetInstanceGeometry())\n"
        f"                {{\n"
        f"                    Solid __s2_{s} = __g2_{s} as Solid;\n"
        f"                    if (__s2_{s} != null)\n"
        f"                        foreach (Face __f2_{s} in __s2_{s}.Faces) __faces_{s}.Add(__f2_{s});\n"
        f"                }}\n"
        f"        }}\n"
        f"        __r_{s}[\"faces\"] = __faces_{s}.Count;\n"
        # NOT EXACTLY ONE FACE — A NAMED REFUSAL, NOT PICKING THE FIRST
        # ONE. A guessed face is worse than a named hole: the author would
        # end up building panels on a random side.
        f"        if (__faces_{s}.Count != 1)\n        {{\n"
        f"            __r_{s}[\"surface\"] = null;\n"
        f"            __r_{s}[\"samples\"] = null;\n"
        f"            __r_{s}[\"absence_ru\"] = \"у элемента граней \" + "
        f"__faces_{s}.Count + \", а читать эта операция умеет РОВНО ОДНУ: "
        f"какая из них «та» — вопрос без ответа, пока у граней нет адреса\";\n"
        f"        }}\n"
        f"        else\n        {{\n"
        f"            Face __f_{s} = __faces_{s}[0];\n"
        f"            var __ub_{s} = __f_{s}.GetBoundingBox();\n"
        f"            __r_{s}[\"domain_uv\"] = new double[] {{\n"
        f"                Math.Round(__ub_{s}.Min.U, 9), Math.Round(__ub_{s}.Max.U, 9),\n"
        f"                Math.Round(__ub_{s}.Min.V, 9), Math.Round(__ub_{s}.Max.V, 9) }};\n"
        f"            __r_{s}[\"area_mm2\"] = Math.Round("
        f"__f_{s}.Area * {mm.format('1.0')} * {mm.format('1.0')}, 3);\n"
        # ── the NURBS definition. Throws on all six versions — see the header.
        f"            NurbsSurfaceData __nd_{s} = null;\n"
        f"            try {{ Surface __su_{s} = __f_{s}.GetSurface();\n"
        f"                   if (__su_{s} != null) __nd_{s} = Autodesk.Revit.DB"
        f".ExportUtils.GetNurbsSurfaceDataForSurface(__su_{s}); }}\n"
        f"            catch (Autodesk.Revit.Exceptions.ArgumentException) {{ }}\n"
        f"            catch (Autodesk.Revit.Exceptions.InvalidOperationException) {{ }}\n"
        f"            if (__nd_{s} == null || !__nd_{s}.IsValid())\n            {{\n"
        f"                __r_{s}[\"surface\"] = null;\n"
        f"                __r_{s}[\"surface_absence_ru\"] = \"грань не читается как "
        f"NURBS: Revit держит её другим родом поверхности (плоскость, цилиндр, "
        f"конус) либо не отдал данные. Это устройство Revit, а не отказ "
        f"операции — сетка точек ниже прочитана и верна\";\n"
        f"            }}\n"
        f"            else\n            {{\n"
        f"                var __sf_{s} = new Dictionary<string, object>();\n"
        f"                __sf_{s}[\"degree_u\"] = __nd_{s}.DegreeU;\n"
        f"                __sf_{s}[\"degree_v\"] = __nd_{s}.DegreeV;\n"
        f"                IList<XYZ> __cp_{s} = __nd_{s}.GetControlPoints();\n"
        f"                IList<double> __ku_{s} = __nd_{s}.GetKnotsU();\n"
        f"                IList<double> __kv_{s} = __nd_{s}.GetKnotsV();\n"
        # count_u/count_v are derived from the number of knots: count =
        # knots - degree - 1. A B-spline identity, not a guess; checked by
        # a round-trip test.
        f"                int __cu_{s} = __ku_{s}.Count - __nd_{s}.DegreeU - 1;\n"
        f"                int __cv_{s} = __kv_{s}.Count - __nd_{s}.DegreeV - 1;\n"
        f"                __sf_{s}[\"count_u\"] = __cu_{s};\n"
        f"                __sf_{s}[\"count_v\"] = __cv_{s};\n"
        f"                __sf_{s}[\"knots_u\"] = __ku_{s}.Select("
        f"k => Math.Round(k, 9)).ToList();\n"
        f"                __sf_{s}[\"knots_v\"] = __kv_{s}.Select("
        f"k => Math.Round(k, 9)).ToList();\n"
        f"                var __pts_{s} = new List<object>();\n"
        f"                foreach (XYZ __q_{s} in __cp_{s})\n"
        f"                    __pts_{s}.Add(new double[] {{\n"
        f"                        Math.Round({mm.format(f'__q_{s}.X')}, 3),\n"
        f"                        Math.Round({mm.format(f'__q_{s}.Y')}, 3),\n"
        f"                        Math.Round({mm.format(f'__q_{s}.Z')}, 3) }});\n"
        f"                __sf_{s}[\"control_points_mm\"] = __pts_{s};\n"
        f"                if (__nd_{s}.IsRational)\n"
        f"                    __sf_{s}[\"weights\"] = __nd_{s}.GetWeights()"
        f".Select(w => Math.Round(w, 9)).ToList();\n"
        f"                __r_{s}[\"surface\"] = __sf_{s};\n"
        f"                __r_{s}[\"surface_read_by\"] = "
        f"\"ExportUtils.GetNurbsSurfaceDataForSurface\";\n"
        f"            }}\n"
        f"{grid}"
        f"        }}\n"
        f"    }}\n"
        f"    __results[{cs_string_literal(oid)}] = __r_{s};\n"
        f"}}")
    return body
