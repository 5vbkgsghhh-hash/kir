"""site_emit — emission of create_topography / create_building_pad /
create_site_subregion (a paired file to ops_site.py, exactly as arch_emit.py
pairs with ops_arch.py and struct_emit.py with ops_struct.py).

Its own wave zone: the module touches no other ops_*.py and no other
*_emit.py. authoring.py gets an additive import and three lines in
_EMITTERS — the same minimal seam through which the framing and architecture
waves were plugged in.

Reused from authoring.py UNCHANGED (by import, not by copy): _gid, _eid, _cs,
_safe, _level_expr, _stamp_block, _stamp_readback, _readback_block,
EMIT_UNSUPPORTED, plus the PUBLIC witness models level_chain_witness and
bbox_extents_witness. The same caveat as in the headers of struct_emit.py and
arch_emit.py applies: some names are private, and the clean fix for the seam
is promoting them to public in authoring.py, not copying the bodies here.

THE MAIN THING ABOUT THIS FILE — THE WITNESSES, AND EACH HAS A DIFFERENT
STRENGTH. All three operations read the RESULT, not their own call, but they
read it differently, and the difference is named here, not hidden:

* the terrain surface witness is the STRONGEST witness in this whole file:
  `TopographySurface.GetPoints()` returns the built element's points, and
  every described point is looked up among them with a 1 mm tolerance. This
  is literally "read back what you asked for";
* the terrain solid (toposolid) is weaker by construction:
  `Toposolid.GetPoints()` DOES NOT EXIST (CS1061 on 2024/2025/2026 —
  measured). Its confident predicate is the bounding box; point-by-point
  reading goes through `GetSlabShapeEditor()`, and when the shape editor is
  unavailable, NO ASSERTION IS MADE — the receipt reports
  `slab_shape_vertices: -1`, and that is more honest than a check that cannot
  fail;
* the building pad — the boundary is read back (`GetBoundary()`), plus
  `AssociatedTopographySurfaceId`: Revit COMPUTES it itself, so this is a real
  read of the result, not an echo of our own argument (there is no owning
  argument for BuildingPad.Create at all);
* the sub-region — `IsSiteSubRegion` on the CREATED surface: a boolean fact
  about the result that our call did not write into any parameter.

THE PAD'S HOST — A PRECHECK, NOT AN EXCEPTION. `BuildingPad.Create` on all six
versions throws InvalidOperationException, "Cannot find an appropriate
hosting topography surface", if there is nothing to place the pad on. A Revit
exception is recorded by the pipeline as `internal` — i.e. as "something
broke on our end" — even though what the user actually needs is to create a
terrain surface FIRST. So before the call there is a count of candidate
hosts, and zero is a typed refusal that NAMES the next move. The check is
NECESSARY, not sufficient, and this is said out loud: zero candidates means
refusal for certain, while a nonzero count does not promise that the pad's
outline actually falls inside anyone's boundary (Revit decides that). The
remaining case still ends up as a Revit exception — but no longer one that
could have been foreseen.
"""
from __future__ import annotations

from kir.emit_core import (  # noqa: F401
    _gid, _eid, _cs, _safe,
    _level_expr, _stamp_block, _stamp_readback, _readback_block,
    EMIT_UNSUPPORTED, level_chain_witness, bbox_extents_witness,
)
from kir.emit_model import WitnessCheck, tolerances
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.diag import (
    Diagnostic, EMIT_UNSUPPORTED_ENUM, KirRefusal, PARSE_MISSING_FIELD)
from kir.ops_site import (
    TOPOGRAPHY_VARIETIES, TOPOSOLID_MIN_VERSION, toposolid_version_refusal)

#: A terrain variety outside the closed set {surface, toposolid}.
#: Belt over suspenders, exactly like RAILING_UNSUPPORTED_VARIETY in the
#: architecture wave and FOUNDATION_UNSUPPORTED_KIND in framing: `enum`
#: choices already catches this at authoring.validate(), and here stands a
#: defense in depth — whoever extends choices without adding the branch will
#: fail LOUDLY, not silently build the wrong thing.


# ── shared helpers ───────────────────────────────────────────────────────────

def _points_cs(points: list, var: str) -> list[str]:
    """`List<XYZ>` from [x,y,z] mm points — a SINGLE source for both the
    creation and the witness.

    The array is NOT duplicated in the postcondition block: the witness
    compares the points it read against this same list, so the variable is
    declared in the OUTER scope (see the scope contract in
    tests/test_emitter_scope_contract.py), not `var`-ed inside create. A
    second copy of the same numbers would double the source and, more
    importantly, could drift apart from the first — and a witness that has
    drifted apart means nothing.
    """
    out = [f"{var} = new List<XYZ>();"]
    for pt in points:
        out.append(f"{var}.Add(P({pt[0]}, {pt[1]}, {pt[2]}));")
    return out


def _xy_extents(points: list) -> tuple[float, float, float, float]:
    """(xmin, xmax, ymin, ymax) over the points — the bounding-box witness's
    input."""
    xs = [pt[0] for pt in points]
    ys = [pt[1] for pt in points]
    return min(xs), max(xs), min(ys), max(ys)


def _host_readback(s: str, oid: str, stamp: str, host_expr: str,
                   type_name: bool = False) -> str:
    """The receipt with the HOST Revit chose, not us.

    Its own, not `_readback_block`, for exactly one reason, and it is a law,
    not a taste: the pad has no host in its signature at all, and the
    sub-region's host is OPTIONAL, i.e. in both cases the topography surface
    can be chosen by Revit itself. A choice the caller does not see is a
    `.FirstOrDefault()` with a proven track record (measured 02.08: the C#
    shoulder silently picked 1 door type out of 62). The witness checks that a
    host EXISTS; the receipt says WHICH ONE — different duties, so this is an
    id, not a verdict.
    """
    tn = (f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
          f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
          f"            var __te = doc.GetElement(__tid);\n"
          f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
          f"        }} }} catch {{ }}\n") if type_name else ""
    return (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    try {{ __rb[\"host_topography_id\"] = {host_expr}.ToString(); }} catch {{ }}\n"
        + _stamp_readback(f"__el_{s}") + tn +
        f"    __results[{_cs(oid)}] = __rb;\n}}")


def _region_loops_cs(region: dict, s: str) -> list[str]:
    """`List<CurveLoop> __loops_<s>` from the lowered CONTOUR region.

    All the arc trigonometry is computed in Python at the ground stage:
    emit_loop_cs writes three LITERAL points per arc into the C#
    (Arc.Create(start, end, point-on-arc), version-safe 2014+), so the
    versions do not diverge here.
    """
    from kir import contour as C
    out = [f"__loops_{s} = new List<CurveLoop>();",
           C.emit_loop_cs(region["outer"], f"__ol_{s}"),
           f"__loops_{s}.Add(__ol_{s});"]
    for hi, hole in enumerate(region["holes"]):
        out.append(C.emit_loop_cs(hole, f"__hl_{s}_{hi}"))
        out.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
    return out


def _boundary_bbox_witness(bnd_expr: str, s: str, oid: str, region: dict,
                           tol, key: str) -> WitnessCheck:
    """Bounding box of the BOUNDARY, read from the built element.

    The reader is not the solid's `get_BoundingBox` (for the pad it includes
    its thickness and the terrain cut-out), but the boundary itself:
    `GetBoundary()` -> `Curve.Tessellate()`. This is exactly the sketch we
    passed, read back.

    It is checked against `contour.edges_bbox`, not against the vertices: for
    an arc the extreme point is almost never a vertex, and edges_bbox adds the
    cardinal extrema (0/90/180/270°) that fall inside the unrolled shape.
    Checking an arc's boundary against vertices would mean blaming a correctly
    built element for exactly the arc sag the sketch was taken for in the
    first place.
    """
    from kir import contour as C
    x0, y0, x1, y1 = C.edges_bbox(region["outer"])
    xmin, xmax = round(x0, 1), round(x1, 1)
    ymin, ymax = round(y0, 1), round(y1, 1)
    return WitnessCheck(
        obligation_key=key,
        # ONE DECLARATION PER LINE, not `double a = 0, b = 0;`. This is not
        # style: the scope contract (tests/test_emitter_scope_contract.py)
        # parses declarations line by line, and for it the second variable in
        # the list is NOT DECLARED — i.e. the whole block would read as a
        # leak outside decl. An instrument that cannot see part of the range
        # is more dangerous than one that's missing, and here it's cheaper to
        # adjust the emission than the parser.
        reader_cs=(
            f"    double __bx0_{s} = 0;\n"
            f"    double __bx1_{s} = 0;\n"
            f"    double __by0_{s} = 0;\n"
            f"    double __by1_{s} = 0;\n"
            f"    bool __bany_{s} = false;\n"
            f"    var __bnd_{s} = {bnd_expr};\n"
            f"    if (__bnd_{s} != null)\n"
            f"        foreach (CurveLoop __bcl_{s} in __bnd_{s})\n"
            f"            foreach (Curve __bc_{s} in __bcl_{s})\n"
            f"                foreach (XYZ __bt_{s} in __bc_{s}.Tessellate())\n"
            f"                {{\n"
            f"                    double __bmx_{s} = MM(__bt_{s}.X);\n"
            f"                    double __bmy_{s} = MM(__bt_{s}.Y);\n"
            f"                    if (!__bany_{s})\n"
            f"                    {{\n"
            f"                        __bx0_{s} = __bmx_{s};\n"
            f"                        __bx1_{s} = __bmx_{s};\n"
            f"                        __by0_{s} = __bmy_{s};\n"
            f"                        __by1_{s} = __bmy_{s};\n"
            f"                        __bany_{s} = true;\n"
            f"                    }}\n"
            f"                    else\n"
            f"                    {{\n"
            f"                        if (__bmx_{s} < __bx0_{s}) __bx0_{s} = __bmx_{s};\n"
            f"                        if (__bmx_{s} > __bx1_{s}) __bx1_{s} = __bmx_{s};\n"
            f"                        if (__bmy_{s} < __by0_{s}) __by0_{s} = __bmy_{s};\n"
            f"                        if (__bmy_{s} > __by1_{s}) __by1_{s} = __bmy_{s};\n"
            f"                    }}\n"
            f"                }}\n"),
        verdict_cs=(
            f"    if (!__bany_{s})\n"
            f"        __post.Add({_cs(oid + ': GetBoundary() не вернул ни одной кривой (geometry)')});\n"
            f"    else if (Math.Abs(__bx0_{s} - {xmin}) > {tol} || Math.Abs(__bx1_{s} - {xmax}) > {tol} ||\n"
            f"             Math.Abs(__by0_{s} - {ymin}) > {tol} || Math.Abs(__by1_{s} - {ymax}) > {tol})\n"
            f"        __post.Add({_cs(oid + ': boundary bbox mismatch (geometry)')});\n"),
        message="boundary bbox mismatch (geometry)",
        tol=tol, style="else_block")


def _grounded_type_cs(op: dict, s: str, oid: str, ver: str, cs_class: str,
                      human: str, isolation: str) -> str:
    """Type resolution into the variable __ty_<s>.

    THERE IS NO doc_default BRANCH HERE, and for the two operations for
    DIFFERENT reasons — the difference is named because "cannot" and "chose
    not to" are not the same thing:

    * for the TERRAIN SOLID, a default type DOES NOT EXIST in the API at all:
      `ElementTypeGroup.ToposolidType` does not compile on any of the six
      versions (CS0117 — measured). Asking the document is impossible by
      construction, exactly as for the railing;
    * for the BUILDING PAD it does exist — `ElementTypeGroup.BuildingPadType`
      compiles 6/6, and this is worth recording separately, because our own
      API database (`data/revit_api_db.json`) does not know it — but it is
      deliberately NOT used, for the same reason as for the ceiling
      (arch_emit._grounded_type_cs): "the default pad" on someone else's
      building is almost never the type actually needed, and a type
      substitution is indistinguishable from success from the outside. An
      omitted `type` is resolved by ground's general rule, "the sole one in
      the pool, otherwise a typed question with candidates", and the author
      will see that question, unlike a substitution.

    The first draft of this file did carry a doc_default branch after all —
    and it was DEAD: `ground.py` yields `in_emit=default` for exactly four
    ops (wall/floor/roof/contoured floor), and the pad is not among them. The
    REFERENCE caught it: the generated C# had an id from the pool, not a call
    to GetDefaultElementTypeId. A dead branch that looks like behavior is the
    same class of bug as "a reference into the void" for create_type.
    """
    sel = op.get("type")
    g = _gid(op, "type") if isinstance(sel, dict) and "__grounded__" in sel else None
    if not g or g.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=(f"{human}: тип не разрешён на стадии ground — у этой "
                        f"операции нет типа по умолчанию, подставить нечего"))])
    return (f"{cs_class} __ty_{s} = doc.GetElement({_eid(g['id'], ver, oid)}) "
            f"as {cs_class};\n"
            f"if (__ty_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs(human + ': тип не найден (модель изменилась после grounding)'), isolation)} }}")


# ── create_topography ────────────────────────────────────────────────────────

def _emit_topography_surface(op: dict, ver: str, stamp: str,
                             isolation: str) -> tuple[str, str, list, str]:
    """Terrain surface, Revit 2021-2026.

    `TopographySurface.Create(doc, IList<XYZ>)` — 6/6. IT HAS NO LEVEL, and
    that is not an omission in the signature: the ground elevation lives in
    the Z OF EACH POINT, not in a tie to a story. So there is neither
    `_level_expr` nor a level-binding witness here — a witness must sign the
    axis it actually read, and this element has no tie to a level to sign.

    [Obsolete] since 2024, but `error=false`, and the compile service compiles
    it with no warnings-as-errors (`CSharpCompilationOptions` without
    TreatWarningsAsErrors; only `DiagnosticSeverity.Error` gets compiled —
    verified against RoslynCompiler.cs, not assumed). Replacing it with
    Toposolid by version number is forbidden: it is an element of a DIFFERENT
    category.
    """
    oid = op["id"]
    s = _safe(oid)
    points = op["points_mm"]
    tol = tolerances("create_topography")
    decl = (f"TopographySurface __el_{s} = null;\n"
            f"List<XYZ> __pts_{s} = null;")
    create = (f"// create_topography(surface) {cs_line_comment_fragment(oid)}\n"
              + "\n".join(_points_cs(points, f"__pts_{s}")) + "\n"
              f"__el_{s} = TopographySurface.Create(doc, __pts_{s});\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание поверхности рельефа вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    xmin, xmax, ymin, ymax = _xy_extents(points)
    checks: list[WitnessCheck] = [
        WitnessCheck(
            # THE SHARED COMMITMENT KEY FOR BOTH VARIETIES IS "terrain_points",
            # what the built element is obligated to return: the surface
            # gives it via GetPoints(), the solid via the shape editor's
            # vertices. That is how the translation certificate closes one
            # commitment for either of the two emissions, exactly like
            # "anchor" for create_railing and "footprint" for
            # create_foundation.
            obligation_key="terrain_points",
            reader_cs=(f"    var __tp_{s} = __el_{s}.GetPoints();\n"
                       f"    int __miss_{s} = 0;\n"),
            verdict_cs=(
                f"    if (__tp_{s} == null || __tp_{s}.Count == 0)\n"
                f"        __post.Add({_cs(oid + ': GetPoints() не вернул ни одной точки (geometry)')});\n"
                f"    else\n"
                f"    {{\n"
                f"        foreach (XYZ __ep_{s} in __pts_{s})\n"
                f"        {{\n"
                f"            bool __hit_{s} = false;\n"
                f"            foreach (XYZ __q_{s} in __tp_{s})\n"
                f"                if (__ep_{s}.DistanceTo(__q_{s}) <= U({tol['point_mm']})) {{ __hit_{s} = true; break; }}\n"
                f"            if (!__hit_{s}) __miss_{s}++;\n"
                f"        }}\n"
                f"        if (__miss_{s} > 0)\n"
                f"            __post.Add(__miss_{s}.ToString() + \" из \" + __pts_{s}.Count.ToString() + \" \"\n"
                f"                + {_cs(oid + ': описанных точек рельефа нет в GetPoints() (geometry)')});\n"
                f"    }}\n"),
            message="описанных точек рельефа нет в GetPoints() (geometry)",
            tol=tol["point_mm"], style="else_block"),
        bbox_extents_witness(f"__el_{s}", oid, xmin, xmax, ymin, ymax,
                             tol["bbox_mm"]),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


def _emit_topography_toposolid(op: dict, ver: str, stamp: str,
                               isolation: str) -> tuple[str, str, list, str]:
    """Terrain solid (toposolid), Revit 2024-2026.

    `Toposolid.Create(doc, IList<XYZ>, ElementId typeId, ElementId levelId)` —
    2024/2025/2026, and NOT ONE version earlier (CS0246: the type `Toposolid`
    does not exist). The level here is REQUIRED by the signature itself,
    unlike for the surface — this is the real signature divergence for whose
    sake the operation got a variety at all.

    POINT-BY-POINT READING EXISTS, BUT IS WEAKER. `Toposolid.GetPoints()`
    does not exist (CS1061 on all three versions where the type itself
    exists), so the points are read through
    `GetSlabShapeEditor().SlabShapeVertices` (both lines compile, the editor
    is 2024+). Whether this editor returns a nonempty set of vertices for a
    solid built FROM POINTS cannot be checked offline at all: that is a fact
    about live Revit. So an unavailable editor is NOT declared a violation
    here — the assertion is simply not made, and the receipt carries
    `slab_shape_vertices: -1`, so that "didn't read it" doesn't read as
    "matched". The confident geometry predicate for the solid is the bounding
    box.
    """
    oid = op["id"]
    s = _safe(oid)
    points = op["points_mm"]
    tol = tolerances("create_topography")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    ty = _grounded_type_cs(op, s, oid, ver, "ToposolidType", "толща рельефа",
                           isolation)
    decl = (f"Toposolid __el_{s} = null;\n"
            f"List<XYZ> __pts_{s} = null;\n"
            f"int __vcnt_{s} = -1;")
    create = (f"// create_topography(toposolid) {cs_line_comment_fragment(oid)}\n"
              f"{ty}\n{lv_res}\n"
              + "\n".join(_points_cs(points, f"__pts_{s}")) + "\n"
              f"__el_{s} = Toposolid.Create(doc, __pts_{s}, __ty_{s}.Id, "
              f"__lv_{s}.Id);\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание толщи рельефа вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    xmin, xmax, ymin, ymax = _xy_extents(points)
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="terrain_points",   # see the comment in the surface branch
            reader_cs=(
                f"    SlabShapeEditor __sse_{s} = null;\n"
                f"    try {{ __sse_{s} = __el_{s}.GetSlabShapeEditor(); }} catch {{ }}\n"
                f"    var __sv_{s} = (__sse_{s} == null) ? null : __sse_{s}.SlabShapeVertices;\n"
                f"    __vcnt_{s} = (__sv_{s} == null) ? -1 : __sv_{s}.Size;\n"
                f"    int __miss_{s} = 0;\n"),
            verdict_cs=(
                # The assertion is made ONLY when the shape editor was read.
                # Otherwise it is not made at all, and this is visible in the
                # receipt (__vcnt_ == -1) — "didn't read it" must not read as
                # "matched", but a correct solid must not be blamed for
                # something we didn't measure either.
                f"    if (__vcnt_{s} > 0)\n"
                f"    {{\n"
                f"        foreach (XYZ __ep_{s} in __pts_{s})\n"
                f"        {{\n"
                f"            bool __hit_{s} = false;\n"
                f"            foreach (SlabShapeVertex __sq_{s} in __sv_{s})\n"
                f"                if (__sq_{s}.Position.DistanceTo(__ep_{s}) <= U({tol['point_mm']})) {{ __hit_{s} = true; break; }}\n"
                f"            if (!__hit_{s}) __miss_{s}++;\n"
                f"        }}\n"
                f"        if (__miss_{s} > 0)\n"
                f"            __post.Add(__miss_{s}.ToString() + \" из \" + __pts_{s}.Count.ToString() + \" \"\n"
                f"                + {_cs(oid + ': описанных точек рельефа нет среди вершин формы толщи (geometry)')});\n"
                f"    }}\n"),
            message="описанных точек рельефа нет среди вершин формы толщи (geometry)",
            tol=tol["point_mm"], style="guard"),
        bbox_extents_witness(f"__el_{s}", oid, xmin, xmax, ymin, ymax,
                             tol["bbox_mm"]),
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
    ]
    # Its own receipt, not _readback_block: it must say whether the shape
    # editor was read. The vertex count here is observation data, not a
    # verdict.
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    __rb[\"slab_shape_vertices\"] = __vcnt_{s};\n"
        f"    __rb[\"points_requested\"] = {len(points)};\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


def emit_topography(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple[str, str, list, str]:
    """The fork over the closed set {surface, toposolid}.

    Also here — CONDITIONALLY REQUIRED fields that ParamSpec.required cannot
    express by construction (`level`/`type` are needed only for the solid;
    a static required=True would demand them from the surface too, which has
    no level AT ALL). The same seam and the same reason as for emit_foundation
    and emit_railing: a typed KIR-P005 here, rather than a bare KeyError that
    would be caught further up as KIR-P000 "internal error" — fail-closed, but
    worse diagnostics.

    THE VERSION AXIS FOR THE SOLID IS A REFUSAL, NOT A FORK, and the refusal
    NAMES THE NEXT MOVE. Falling back to the surface silently is not allowed:
    it has a different category (OST_Topography vs. OST_Toposolid), a
    different binding, and a different witness, i.e. it would be a different
    element handed over as the one requested.
    """
    variety = op.get("variety")
    if variety == "surface":
        return _emit_topography_surface(op, ver, stamp, isolation)
    if variety == "toposolid":
        # ONE text, ONE threshold, TWO call sites. This one stays, because the
        # emitter is also called directly; the author's real protection sits
        # BEFORE grounding (`compiler`, the seam next to KIR-E001) — see the
        # docstring of `toposolid_version_refusal`.
        refusal = toposolid_version_refusal({**op, "op": "create_topography"},
                                            ver)
        if refusal is not None:
            raise KirRefusal([refusal])
        if op.get("level") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"),
                field_name="level",
                message_ru=("create_topography(variety=toposolid): level "
                            "обязателен — Toposolid.Create требует levelId, в "
                            "отличие от поверхности, у которой уровня нет "
                            "вовсе"))])
        return _emit_topography_toposolid(op, ver, stamp, isolation)
    raise KirRefusal([Diagnostic(
        code=EMIT_UNSUPPORTED_ENUM, op_id=op.get("id"),
        field_name="variety", got=variety, candidates=list(TOPOGRAPHY_VARIETIES),
        message_ru=(f"create_topography: разновидность {variety!r} не "
                    f"поддержана (в API ровно два элемента рельефа — "
                    f"поверхность и толща)"))])


# ── create_building_pad ──────────────────────────────────────────────────────

def _host_candidate_count_cs(s: str, ver: str) -> str:
    """A C# expression for "how many building-pad host candidates are in the
    document".

    THE VERSION DIVERGES HERE, and this is not decoration: on 2024+ the
    terrain in the document can be a solid, and the type `Toposolid` does not
    exist at all on 2021-2023 (CS0246) — one line for all six versions would
    not have compiled. What is counted is INSTANCES, not types
    (`WhereElementIsNotElementType`).
    """
    base = (f"int __hosts_{s} = new FilteredElementCollector(doc)"
            f".OfClass(typeof(TopographySurface)).WhereElementIsNotElementType()"
            f".GetElementCount();")
    if ver >= TOPOSOLID_MIN_VERSION:
        base += (f"\n__hosts_{s} += new FilteredElementCollector(doc)"
                 f".OfClass(typeof(Toposolid)).WhereElementIsNotElementType()"
                 f".GetElementCount();")
    return base


def emit_building_pad(op: dict, ver: str, stamp: str,
                      isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Building pad from a CONTOUR sketch, Revit 2021-2026.

    `BuildingPad.Create(doc, ElementId typeId, ElementId levelId,
    IList<CurveLoop>)` — 6/6, never [Obsolete]. The argument order is exactly
    this (type and level BEFORE the boundary) — verified by compilation, not
    reconstructed from memory of neighboring Create calls.

    THERE IS NO HOST IN THE SIGNATURE: Revit looks for the topography surface
    itself and throws an InvalidOperationException if it doesn't find one.
    That is exactly why the candidate precheck sits BEFORE the call — see the
    module header.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    tol = tolerances("create_building_pad")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    ty = _grounded_type_cs(op, s, oid, ver, "BuildingPadType",
                           "площадка под здание", isolation)
    decl = (f"BuildingPad __el_{s} = null;\n"
            f"List<CurveLoop> __loops_{s} = null;")
    create = (f"// create_building_pad {cs_line_comment_fragment(oid)}\n"
              f"{ty}\n{lv_res}\n"
              + _host_candidate_count_cs(s, ver) + "\n"
              f"if (__hosts_{s} == 0) {{ "
              + refuse_stmt(
                  oid,
                  _cs("площадку под здание не на что сажать: в документе нет "
                      "ни одной топоповерхности. Следующий ход — создать "
                      "рельеф операцией create_topography, и только потом "
                      "площадку (Revit ищет хозяина сам и без него бросает "
                      "«Cannot find an appropriate hosting topography "
                      "surface»)"),
                  isolation)
              + " }\n"
              + "\n".join(_region_loops_cs(region, s)) + "\n"
              f"__el_{s} = BuildingPad.Create(doc, __ty_{s}.Id, __lv_{s}.Id, "
              f"__loops_{s});\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание площадки под здание вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
        _boundary_bbox_witness(f"__el_{s}.GetBoundary()", s, oid, region,
                               tol["bbox_mm"], "bbox"),
        WitnessCheck(
            # A REAL READ OF THE RESULT, NOT AN ECHO OF AN ARGUMENT: we did
            # not pass a host — Revit found it, and this is its answer. The
            # check sits after doc.Regenerate() (the program emitter inserts
            # it between the creations and the postconditions), and the
            # binding itself is established inside Create: it is precisely
            # its absence that turns Create into an
            # InvalidOperationException. So a successful Create plus an
            # invalid id is a state that must not exist, and staying silent
            # about it is not allowed.
            obligation_key="hosting_topography",
            reader_cs=(f"    var __atid_{s} = __el_{s}.AssociatedTopographySurfaceId;\n"),
            verdict_cs=(
                f"    if (__atid_{s} == null || __atid_{s} == ElementId.InvalidElementId)\n"
                f"        __post.Add({_cs(oid + ': площадка не привязана к топоповерхности (topology)')});\n"),
            message="площадка не привязана к топоповерхности (topology)",
            style="guard"),
    ]
    return decl, create, checks, _host_readback(
        s, oid, stamp, f"__el_{s}.AssociatedTopographySurfaceId",
        type_name=True)


# ── create_site_subregion ────────────────────────────────────────────────────

def emit_site_subregion(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Site sub-region from a CONTOUR sketch, Revit 2021-2026.

    Two overloads, both 6/6: `SiteSubRegion.Create(doc, IList<CurveLoop>)` —
    Revit looks for the host; `SiteSubRegion.Create(doc, IList<CurveLoop>,
    ElementId)` — the host is named. [Obsolete] since 2024 (same as
    TopographySurface.Create), but `error=false`.

    THE MAIN TRAP OF THIS OP: `SiteSubRegion` is NOT an `Element`. It has no
    `.Id` and no `get_Parameter` (CS1061/CS0029 on all six). The created
    ELEMENT is `sr.TopographySurface`, and the stamp, the receipt, and the
    witnesses all work with that. Writing `__sr.Id` would be a sixfold
    CS1061; silently not writing the stamp would lose ownership, because A5
    checks it against the receipt.
    """
    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]
    host_sel = op.get("host")
    tol = tolerances("create_site_subregion")
    # THE HOST IS DECLARED IN THE OUTER SCOPE, not in the creation block: with
    # isolation="per_op" create and post land in DIFFERENT scopes, and a
    # variable declared inside create is invisible to the witness (CS0103 —
    # the exact seam on which the enclosures wave got six gate failures).
    host_decl, host_res, host_id_cs = "", "", None
    if isinstance(host_sel, dict):
        if host_sel.get("by") == "ref":
            host_id_cs = "__el_" + _safe(host_sel["value"]) + ".Id"
        else:
            host_decl = f"\nElement __hst_{s} = null;"
            host_res = (
                f"__hst_{s} = doc.GetElement("
                f"{_eid(host_sel['value'], ver, oid)});\n"
                f"if (__hst_{s} == null) {{ "
                f"{refuse_stmt(oid, _cs('топоповерхность-хозяин не найдена (модель изменилась после grounding)'), isolation)} }}\n")
            host_id_cs = f"__hst_{s}.Id"
    make = (f"__sr_{s} = SiteSubRegion.Create(doc, __loops_{s}, {host_id_cs});"
            if host_id_cs else
            f"__sr_{s} = SiteSubRegion.Create(doc, __loops_{s});")
    decl = (f"SiteSubRegion __sr_{s} = null;\n"
            f"TopographySurface __el_{s} = null;\n"
            f"List<CurveLoop> __loops_{s} = null;" + host_decl)
    create = (f"// create_site_subregion {cs_line_comment_fragment(oid)}\n"
              + host_res
              + "\n".join(_region_loops_cs(region, s)) + "\n"
              + make + "\n"
              f"if (__sr_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание подобласти площадки вернуло null'), isolation)} }}\n"
              f"__el_{s} = __sr_{s}.TopographySurface;\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('подобласть создана, но её поверхность не читается — элемента, которым можно владеть, нет'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    host_verdict = (
        f"    if (__hid_{s} == null || __hid_{s} == ElementId.InvalidElementId)\n"
        f"        __post.Add({_cs(oid + ': подобласть не принадлежит ни одной топоповерхности (topology)')});\n")
    if host_id_cs:
        host_verdict += (
            f"    else if (__hid_{s}.ToString() != {host_id_cs}.ToString())\n"
            f"        __post.Add({_cs(oid + ': подобласть принадлежит не запрошенной топоповерхности (topology)')});\n")
    checks: list[WitnessCheck] = [
        WitnessCheck(
            # A BOOLEAN FACT ABOUT THE RESULT that our call never wrote
            # anywhere: Revit itself marks the created surface as a
            # sub-region. If Create had returned an ordinary surface, from
            # outside this would be indistinguishable from success — right up
            # to the day someone noticed the sub-region wasn't in the model.
            obligation_key="is_subregion",
            reader_cs="",
            verdict_cs=(
                f"    if (!__el_{s}.IsSiteSubRegion)\n"
                f"        __post.Add({_cs(oid + ': созданная поверхность не помечена как подобласть (semantic)')});\n"),
            message="созданная поверхность не помечена как подобласть (semantic)",
            style="guard"),
        _boundary_bbox_witness(f"__sr_{s}.GetBoundary()", s, oid, region,
                               tol["bbox_mm"], "bbox"),
        WitnessCheck(
            obligation_key="host_binding",
            reader_cs=(f"    var __hid_{s} = __sr_{s}.HostId;\n"),
            verdict_cs=host_verdict,
            message="подобласть не принадлежит запрошенной топоповерхности (topology)",
            style="guard"),
    ]
    return decl, create, checks, _host_readback(
        s, oid, stamp, f"__sr_{s}.HostId")


#: WHAT THIS SPOKE EMITS — DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Previously the "op -> body" mapping lived in the hand-written
#: `authoring._EMITTERS`, with the body here, and a thin wrapper in the hub
#: tied them together (41 entries across 19 companions). Two records of one
#: fact in different files is a named defect of this tree; now there is ONE
#: record, and the hub QUERIES it.
EMITTERS = {
    "create_building_pad": emit_building_pad,
    "create_site_subregion": emit_site_subregion,
    "create_topography": emit_topography,
}
