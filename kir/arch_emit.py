"""arch_emit — emission of create_ceiling / create_railing (the counterpart
file to ops_arch.py, exactly as struct_emit.py is to ops_struct.py).

Its own wave zone: this module does not touch ops_authoring.py, ops_struct.py,
connect.py, contour.py, or any other ops_*.py. authoring.py gets an additive
import and two lines in _EMITTERS — the same minimal seam the framing wave
connected through.

Reused from authoring.py WITHOUT CHANGES (by import, not by copy): _gid,
_eid, _cs, _safe, _level_expr, _stamp_block, _readback_block, _loop_pts,
EMIT_UNSUPPORTED, plus the PUBLIC witness models level_chain_witness and
bbox_extents_witness. The same list as struct_emit.py's, with the same
caveat in its header: some of the names are private (underscore-prefixed),
and if a future pass wants a clean seam, the fix is promoting them to public
in authoring.py, not copying the bodies here.

THE MAIN POINT OF THIS FILE. Both operations are written from a MEASUREMENT
of the compile service across six versions (2021-2026), not from memory of
the API. The measurement and its consequences are laid out in ops_arch.py's
header; here is only what is visible in the code:

* the 2021 ceiling is a typed refusal OF THE WHOLE THING (not an emission
  fork, as with create_floor): Ceiling.Create does not exist before 2022, and
  doc.Create.NewCeiling does not exist on any version at all, so no
  alternative path exists;
* railing — two overloads of Railing.Create, and both live on all six;
* the railing's path is laid down as an OPEN polyline: _loop_pts (the shared
  contour helper) closes the ring via (k+1)%n and DOES NOT FIT here — it has
  its own reason to exist. A closing segment that is not in the source is
  invented geometry, not "a rounding triviality".
"""
from __future__ import annotations

from kir.emit_core import (  # noqa: F401
    _gid, _eid, _cs, _safe,
    _level_expr, _stamp_block, _stamp_readback, _readback_block,
    _loop_pts, EMIT_UNSUPPORTED, level_chain_witness, bbox_extents_witness,
    sketch_loops_witness, spline_points_witness, path_points_witness,
)
from kir.emit_model import WitnessCheck
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.diag import Diagnostic, KirRefusal, PARSE_MISSING_FIELD
from kir.ops_arch import RAILING_PLACEMENT_MEMBERS

#: A variant of create_railing outside the closed set {path, hosted}.
#: A belt on top of suspenders: the `enum`-choices of ParamSpec already catch
#: this at authoring.validate() (KIR-T003), and this check is defense in depth
#: inside the emitter itself, exactly like FOUNDATION_UNSUPPORTED_KIND in the
#: framing wave. Whoever extends the choices without adding a branch lands
#: here: let it fail LOUDLY, rather than silently build the wrong thing.
RAILING_UNSUPPORTED_VARIETY = "KIR-E006"


def _grounded_type_cs(op: dict, s: str, oid: str, ver: str, param: str,
                      cs_class: str, human: str, isolation: str) -> str:
    """Resolving the type into the variable __ty_<s>.

    There is NO doc_default branch here on purpose, and this is not a
    simplification. For a railing, a default type does not exist in the API at
    all (ElementTypeGroup.RailingType does not compile on any of the six
    versions — measured), while a ceiling has one but it is deliberately not
    used: "the default ceiling type" on someone else's building is almost
    never the type that stood in the source, and a type swap is
    indistinguishable from success from the outside. A missing `type` is
    resolved by ground.py under the general rule "the sole one in the pool,
    otherwise a typed question".
    """
    sel = op.get(param)
    g = _gid(op, param) if isinstance(sel, dict) and "__grounded__" in sel else None
    # A TYPE CREATED BY THIS SAME PROGRAM. Checked BEFORE the "no id" gate:
    # an in-program reference has no `id` and never will — it addresses a
    # variable, not a snapshot row — and the old gate used to refuse it with
    # "type not resolved at the ground stage", naming the wrong reason.
    if g and g.get("via") == "ref":
        return f"{cs_class} __ty_{s} = __el_{_safe(g['ref'])};"
    if not g or g.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name=param,
            message_ru=(f"{human}: тип не разрешён на стадии ground — у этой "
                        f"операции нет типа по умолчанию, подставить нечего"))])
    return (f"{cs_class} __ty_{s} = doc.GetElement({_eid(g['id'], ver, oid)}) "
            f"as {cs_class};\n"
            f"if (__ty_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs(human + ': тип не найден (модель изменилась после grounding)'), isolation)} }}")


# ── create_ceiling ───────────────────────────────────────────────────────────

def emit_ceiling(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Ceiling by a closed contour, Revit 2022+.

    Ceiling.Create(doc, IList<CurveLoop>, ElementId typeId, ElementId levelId)
    — confirmed by compilation on 2022/2023/2024/2025/2026 and refuted on
    2021 (CS0117: 'Ceiling' does not contain a definition for 'Create').

    TWO SHAPE INPUTS, ONE EMISSION (09.08.2026). The profile arrives either as
    a direct `outline` polyline (+ flat `holes`), or as a CONTOUR sketch left
    behind (`__region__`, placed there by the ground stage). Exactly one of
    the two — the plan refuses with KIR-P007 both on "both at once" and on
    "neither", so the fork here is COMPLETE, not "just in case neither one
    shows up".

    Exactly two things differ: the assembly of the ``List<CurveLoop>``
    (straight segments versus Line/Arc from the canonical edges) and the
    number the bounding box is checked against (the polyline's extreme points
    versus ``contour.edges_bbox``, which knows the cardinal extrema of arcs).
    Everything else — type, level, offset, the stamp, the witnesses, the
    receipt — is shared, and this is not a line-count saving: two copies of
    this tail drift apart, and a drifted witness means nothing.

    THE SKETCH'S VERSION ADDS NO BRANCH. create_floor_by_contour has
    somewhere to fall back to on 2021 — doc.Create.NewFloor(CurveArray, ...) —
    and so it has emit_curvearray_cs. The ceiling has nowhere to fall back to
    (see the header of ops_arch.py, re-checked 09.08 against RevitAPI.xml/dll
    2021: zero ``Ceiling.*`` members, no ``NewCeiling`` string), so the
    refusal below sits BEFORE the shape is parsed and covers both branches
    alike.
    """
    oid = op["id"]
    s = _safe(oid)
    if ver < "2022":
        # THE VERSION AXIS HERE IS A REFUSAL, NOT A FORK. create_floor has
        # somewhere to fall back to on 2021 (legacy doc.Create.NewFloor); the
        # ceiling has nowhere: NewCeiling does not exist on ANY of the six
        # versions (measured, CS1061). The only alternatives to a refusal are
        # building something that is not a ceiling (a floor) or building
        # nothing and staying silent; both read as success from the outside,
        # and both are forbidden by §18.1.
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, field_name=None,
            message_ru=(
                f"потолок не создаётся на Revit {ver}: Ceiling.Create "
                f"появился только в 2022, а legacy-пути к потолку "
                f"(doc.Create.NewCeiling) в API нет ни на одной версии "
                f"2021-2026 — замерено компиляцией. Обходного пути нет: "
                f"перекрытие вместо потолка было бы другим элементом, "
                f"другой категории"))])
    region = op.get("__region__")
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    ct = _grounded_type_cs(op, s, oid, ver, "type", "CeilingType",
                           "потолок", isolation)
    geo = [f"var __loops_{s} = new List<CurveLoop>();"]
    if region is not None:
        # CONTOUR sketch. All arc trigonometry is already computed in python
        # at the ground stage: emit_loop_cs places three LITERAL points per
        # arc into the C# (Arc.Create(start, end, point-on-arc), version-safe
        # 2014+), meaning versions do not diverge here, and after 2022 there
        # is nothing left to diverge.
        from kir import contour as C
        geo.append(C.emit_loop_cs(region["outer"], f"__ol_{s}"))
        geo.append(f"__loops_{s}.Add(__ol_{s});")
        for hi, hole in enumerate(region["holes"]):
            geo.append(C.emit_loop_cs(hole, f"__hl_{s}_{hi}"))
            geo.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
    else:
        outline = op["outline"]
        geo += _loop_pts(outline, f"__ol_{s}")
        geo.append(f"__loops_{s}.Add(__ol_{s});")
        for hi, hole in enumerate(op.get("holes") or []):
            geo += _loop_pts(hole, f"__hl_{s}_{hi}")
            geo.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
    make = (f"__el_{s} = Ceiling.Create(doc, __loops_{s}, __ty_{s}.Id, "
            f"__lv_{s}.Id);")
    # Offset from the level. The ceiling's only vertical degree of freedom,
    # with a MEASURED parameter (CEILING_HEIGHTABOVELEVEL_PARAM, 6/6). The
    # parameter's absence leaves the C# without a single line about it — an
    # absence stays an absence, not a zero.
    height_offset = op.get("height_offset_mm")
    ho_set = ""
    if height_offset is not None:
        ho_set = (
            f"\nParameter __cho_{s} = __el_{s}.get_Parameter("
            f"BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM);\n"
            f"if (__cho_{s} == null || __cho_{s}.IsReadOnly) {{ "
            f"{refuse_stmt(oid, _cs('CEILING_HEIGHTABOVELEVEL_PARAM недоступен у потолка'), isolation)} }}\n"
            f"__cho_{s}.Set(U({height_offset}));")
    decl = f"Ceiling __el_{s} = null;"
    create = (f"// create_ceiling {cs_line_comment_fragment(oid)}\n{ct}\n{lv_res}\n"
              + "\n".join(geo) + f"\n{make}\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание потолка вернуло null'), isolation)} }}\n"
              + ho_set
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    from kir.emit_model import tolerances
    tol = tolerances("create_ceiling")
    if region is not None:
        # THE BOUNDING BOX IS COMPUTED FROM THE DROPPED EDGES, NOT FROM THE
        # VERTICES. For an arc, the extreme point is almost never a vertex:
        # edges_bbox adds the cardinal extrema (0/90/180/270 degrees) that
        # fall inside the sweep. Checking an arced ceiling against its
        # vertices would mean accusing a correctly built element of exactly
        # the arc's own sagitta — the reason the sketch was taken in the
        # first place.
        #
        # The tolerance is NOT NEW and was not derived by reasoning: it takes
        # the same registered key create_ceiling.bbox_mm = 50.0 as the direct
        # branch, and it also numerically matches
        # create_floor_by_contour.bbox_mm — for the contoured slab this is
        # exactly the same witness over the same edges_bbox. The ceiling's
        # contour branch does not start a number of its own: a new number
        # here would be a boundary assigned by reasoning, not by measurement
        # (this house's class of defect).
        from kir import contour as C
        x0, y0, x1, y1 = C.edges_bbox(region["outer"])
        bbox_args = (round(x0, 1), round(x1, 1), round(y0, 1), round(y1, 1))
    else:
        xs = [pt[0] for pt in op["outline"]]
        ys = [pt[1] for pt in op["outline"]]
        bbox_args = (min(xs), max(xs), min(ys), max(ys))
    # SHAPE ALONGSIDE THE BOUNDING BOX. The bounding box over the dropped
    # edges catches the ARC'S SAGITTA (cardinal extrema), which the multiset
    # of vertices does not see; vertices catch a shifted corner and a lost
    # opening, which the bounding box does not see.
    #
    # 🔴 THE ARC IS NOT A NUISANCE HERE, AND THIS IS A MEASUREMENT, NOT AN
    # ASSUMPTION. The comment above warns: "checking an arced ceiling BY
    # VERTICES would mean accusing a correctly built element". That is true
    # for comparing a SAMPLING of the arc (`edges_to_sample_poly` breaks it
    # into 8 chords). The shape witness compares something ELSE — the start
    # of each edge — and Revit hands back an arc as ONE curve: measurement
    # 19.08.2026 across 67 corpus decompiles, 10,463 rings, 259 of them with
    # arcs, 331 curves of kind `arc` arrive as separate records mixed in with
    # `line`, not a single tessellation pass. So `GetEndPoint(0)` gives
    # exactly one vertex per authored edge for an arc too.
    #
    # 🔴 BOTH BRANCHES HAVE OPENINGS, AND THE DIRECT ONE WAS LOSING THEM
    # (04.09.2026). `rings` on the `outline` branch was returning EXACTLY ONE
    # ring, even though the creation block above puts into `__loops_` and
    # `__ol_`, and each `__hl_`: a ceiling with an opening was being built
    # CORRECTLY, and the witness expected one ring and rolled back correct
    # work — `sketch loops mismatch, expected 1 loop(s)` on a program with not
    # a single authoring error. The `region` branch had always accounted for
    # openings, meaning the law was declared twice and drifted apart exactly
    # where it was not re-read. The source of the rings is now the ONE AND
    # SAME source as `__loops_` four dozen lines above: the outer contour
    # plus all openings, in the same order.
    from kir import contour as _C
    rings = ([_C.edges_vertices(region["outer"])]
             + [_C.edges_vertices(h) for h in region["holes"]]
             if region is not None else
             [[list(p) for p in op["outline"]]]
             + [[list(p) for p in hole] for hole in (op.get("holes") or [])])
    # 🔴 THE BOUNDING BOX OF A RING WITH A SPLINE CANNOT BE PINNED DOWN, AND
    # THIS WAS MEASURED LIVE ON A NEIGHBORING OP (a slab with a wavy edge,
    # Revit 2026, 20.08.2026): Revit gave 9705.3 mm along Y, our
    # compile-time sample expected 9426.0 — a 279 mm gap against a 50
    # tolerance. This is not measurement error but DIFFERENT CURVES: we
    # approximate the edge with Catmull-Rom, Revit builds a `HermiteSpline`
    # with its own tangents, and the algorithm is undocumented. The extrema
    # will not coincide at any tolerance, and a tolerance stretched to cover
    # the gap would also sign off on a real error — that is, a witness that
    # cannot fail.
    #
    # WHY A NUMBER FROM A DIFFERENT OP IS LEGITIMATE HERE: what diverges is
    # not the elements but TWO CURVES between the same two points, and both
    # sides — our `contour.sample_spline` versus `HermiteSpline.Create` — are
    # exactly the same for a ceiling. What is measured is a property of the
    # pair of instruments, not a property of the ceiling.
    # ⚠️ A live run of a ceiling with a spline is still mandatory: it checks
    # not the bounding box (it no longer exists here) but whether
    # `Ceiling.Create` accepts a ring with a curve at all and hands it back
    # through `Sketch.Profile`.
    from kir import contour as _CS
    ring_has_spline = bool(region is not None and (
        any(_CS.is_spline(b) for _p0, _p1, b in region["outer"])
        or any(_CS.is_spline(b) for h in region["holes"]
               for _p0, _p1, b in h)))
    checks: list[WitnessCheck] = [
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
    ]
    if not ring_has_spline:
        checks.append(
            bbox_extents_witness(f"__el_{s}", oid, *bbox_args, tol["bbox_mm"]))
    checks.append(
        sketch_loops_witness(f"__el_{s}", oid, rings, tol["sketch_mm"]))
    # THE CURVE IS PROVEN SEPARATELY, BECAUSE BOTH NEIGHBORS ARE BLIND TO IT:
    # `sketch_loops_witness` reads the edge ENDPOINTS (`GetEndPoint(0)`), and
    # the endpoints are the same for a straight line and for any curve between
    # them; the bounding box on a spline is understated by construction and
    # was dropped in the line above. The check is added ONLY when a spline is
    # present: a witness that always runs is paid for by every program and
    # tells nothing apart.
    if ring_has_spline:
        spline_pts = [pt for _k, pts in _CS.spline_witness_points(region["outer"])
                      for pt in pts]
        for _h in region["holes"]:
            spline_pts += [pt for _k, pts in _CS.spline_witness_points(_h)
                           for pt in pts]
        if spline_pts:
            checks.append(spline_points_witness(
                f"__el_{s}", oid, spline_pts, tol["spline_point_mm"]))
    if height_offset is not None:
        checks.append(WitnessCheck(
            obligation_key="height_offset",
            reader_cs=(f"    var __chop = __el_{s}.get_Parameter("
                       f"BuiltInParameter.CEILING_HEIGHTABOVELEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__chop == null || Math.Abs(MM(__chop.AsDouble()) - "
                f"{height_offset}) > {tol['height_offset_mm']})\n"
                f"        __post.Add({_cs(oid + ': height offset mismatch (geometry)')});\n"),
            message="height offset mismatch (geometry)",
            tol=tol["height_offset_mm"], style="guard"))
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


# ── create_railing ───────────────────────────────────────────────────────────

def _path_pts(pts: list, name: str, z: str = "0") -> list:
    """An OPEN polyline in a CurveLoop — n points give n-1 segments.

    A separate helper, not an argument to _loop_pts: in _loop_pts, closing
    the loop is hardwired into `(k + 1) % n` and IS its purpose (a floor's
    contour must be a ring). A railing is not a ring: a straight flight is
    two points, and a closing segment would put geometry into the model that
    is not in the source. A CurveLoop in Revit is not required to be closed,
    so the same container type suits both.
    """
    out = [f"CurveLoop {name} = new CurveLoop();"]
    for k in range(len(pts) - 1):
        a, b = pts[k], pts[k + 1]
        out.append(f"{name}.Append(Line.CreateBound("
                   f"P({a[0]}, {a[1]}, {z}), P({b[0]}, {b[1]}, {z})));")
    return out


def _emit_railing_path(op: dict, ver: str, stamp: str,
                       isolation: str) -> tuple[str, str, list, str]:
    """A free-standing railing along its own path.

    Railing.Create(doc, CurveLoop, ElementId railingTypeId,
                   ElementId baseLevelId) — 6/6.
    """
    oid = op["id"]
    s = _safe(oid)
    path = op["path"]
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    rt = _grounded_type_cs(op, s, oid, ver, "type", "RailingType",
                           "ограждение", isolation)
    geo = _path_pts(path, f"__pth_{s}")
    decl = f"Railing __el_{s} = null;"
    create = (f"// create_railing(path) {cs_line_comment_fragment(oid)}\n"
              f"{rt}\n{lv_res}\n" + "\n".join(geo) + "\n"
              f"__el_{s} = Railing.Create(doc, __pth_{s}, __ty_{s}.Id, "
              f"__lv_{s}.Id);\n"
              f"if (__el_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('создание ограждения вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    from kir.emit_model import tolerance
    checks: list[WitnessCheck] = [
        # The railing's level is NOT caught by the shared BIP chain
        # (level_chain_witness): its links are FAMILY_BASE_LEVEL/FAMILY_LEVEL/
        # SCHEDULE_LEVEL/LEVEL_PARAM, while a railing's base level lives in
        # STAIRS_RAILING_BASE_LEVEL_PARAM (measured, 6/6). Its own witness, not
        # "close enough": a foreign chain would silently return null and
        # accuse a correctly built element.
        WitnessCheck(
            # The obligation key is SHARED between both branches — "anchor",
            # what the railing is tied to: free-standing to the LEVEL, a stair
            # one to its HOST. This way the translation certificate
            # (translation_cert.py) closes one obligation for either of the
            # two emissions, exactly as create_foundation does with its shared
            # "footprint" for isolated/slab.
            obligation_key="anchor",
            reader_cs=(f"    var __rlp_{s} = __el_{s}.get_Parameter("
                       f"BuiltInParameter.STAIRS_RAILING_BASE_LEVEL_PARAM);\n"),
            verdict_cs=(
                f"    if (__rlp_{s} == null || __rlp_{s}.AsElementId() == null\n"
                f"        || __rlp_{s}.AsElementId().ToString() != {lv_idexpr})\n"
                f"        __post.Add({_cs(oid + ': base level mismatch (topology)')});\n"),
            message="base level mismatch (topology)", style="guard"),
        # 🔴 BODY BOUNDING BOX AGAINST THE PATH LINE — REMOVED 25.08.2026, A
        # LIVE MEASUREMENT (Проект1, Revit 2026, q14). bbox_extents_witness
        # stood here, inherited from floor/roof/ceiling — but there the
        # comparison is LEGITIMATE (the story is flat sketch == the extruded
        # body's boundary), and for a railing it is NOT: the path is a LINE
        # of zero thickness, while the built Railing is a BODY with balusters
        # and a handrail, whose bbox is wider than the path by the physical
        # width/end offset PER REVIT'S OWN DEVICE. Measured: path
        # y=[921000, 921000], body y=[920975, 921050] — the authored line
        # had NOT been violated, the witness was accusing CORRECT geometry.
        # The live-run share of 13.0% (3 built / 20 accused / 140 incidental
        # rollbacks) held on exactly this comparison, not on the rig — the
        # neighboring ops of the same run (create_pipe/create_duct/create_cable_tray)
        # scored 100%.
        #
        # NOT FIXED BY WIDENING THE TOLERANCE: the gap is not measurement
        # noise but a PROPERTY OF DISSIMILAR QUANTITIES (a body versus a
        # line), and a tolerance tuned to it would also sign off on a real
        # path shift — the same reasoning as the ceiling's spline earlier in
        # this file. Removed EXPLICITLY (not silently): the "bbox" obligation
        # was deleted from translation_cert.py together with this line — see
        # the comment there.
        #
        # WHAT REMAINS PROVABLE: the path. path_points_witness below compares
        # LIKE WITH LIKE — a re-read GetPath() (also a line) against the
        # authored path, by edge endpoints, on a ±1mm grid — and does this
        # MORE PRECISELY than the old bbox±50mm, without losing a single fact
        # the old one actually proved.
        #
        # SHAPE OF THE PATH. The path is OPEN, so BOTH ends of every curve are
        # taken: one point per edge would lose the path's END, and a shift of
        # the last vertex would pass by silently.
        path_points_witness(
            f"__el_{s}", oid, path,
            tolerance("create_railing", "path_mm")),
    ]
    # THE OP'S IDENTITY FIELD IS ONE FOR BOTH BRANCHES — `railing_ids` (see
    # the cardinality breakdown in ops_arch.py). A free-standing railing has a
    # list of exactly one id, and this is NOT a formality: `address.element_addresses`
    # and `created_ledger.created_keys()` ask for EXACTLY the field the
    # registry declares, and the MANY contract does not know an `id` field at
    # all — without this line, a path railing would be left WITHOUT identity,
    # and `element_addresses(strict)` would refuse with KIR-X008.
    # (`decompile.lineage` reads not the field but the ARITY: ONE requires
    # exactly one id, MANY a non-empty list.)
    return decl, create, checks, _readback_block(
        s, oid, stamp,
        extra_rows_cs=(f"    __rb[\"railing_ids\"] = new string[] {{ "
                       f"__el_{s}.Id.ToString() }};\n"), identity_version=ver)


def _emit_railing_hosted(op: dict, ver: str, stamp: str,
                         isolation: str) -> tuple[str, str, list, str]:
    """A railing that BELONGS to a stair or a ramp.

    Railing.Create(doc, ElementId hostId, ElementId railingTypeId,
                   RailingPlacementPosition) — 6/6.

    This, not the path, is the entire railing population of a real building:
    203 OST_StairsRailing on K2. Reducing them to the `path` variant would
    mean INVENTING a path where the source gives a host, and losing the very
    binding — the "binding to a stair/ramp" that must be expressed or
    refused, but never swapped out.
    """
    oid = op["id"]
    s = _safe(oid)
    host_sel = op["host"]
    position = op.get("position")
    if position is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="position",
            message_ru=(
                "create_railing(variety=hosted): position обязателен — "
                "RailingPlacementPosition решает, где на лестнице встанет "
                "ограждение (по проступям или по косоуру), и подставить одно "
                "из двух за пользователя значит поставить его не туда молча"))])
    member = RAILING_PLACEMENT_MEMBERS[position]
    # THE HOST IS DECLARED IN THE OUTER SCOPE, not inside the creation block.
    # This is not a style choice: under isolation="per_op", the creation and
    # postcondition blocks land in DIFFERENT scopes, and a variable declared
    # inside create is invisible to the witness. The first version of this
    # emitter failed exactly this way — the live gate gave CS0103
    # '__hst_R1 does not exist in the current context' on all six per_op
    # runs. The same seam that compile_gate_offline.py's header warns about
    # ("the gate must compile exactly what will ship into the model").
    if host_sel.get("by") == "ref":
        # A reference within the program: create_stairs of the same program.
        # The planning stage has already checked the target's existence via the DAG.
        host_decl = ""
        host_res = ""
        host_id_cs = "__el_" + _safe(host_sel["value"]) + ".Id"
    else:
        host_decl = f"\nElement __hst_{s} = null;"
        host_res = (
            f"__hst_{s} = doc.GetElement("
            f"{_eid(host_sel['value'], ver, oid)});\n"
            f"if (__hst_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs('лестница/пандус-хост не найден (модель изменилась после grounding)'), isolation)} }}\n")
        host_id_cs = f"__hst_{s}.Id"
    rt = _grounded_type_cs(op, s, oid, ver, "type", "RailingType",
                           "ограждение", isolation)
    # THIS OVERLOAD RETURNS A COLLECTION, NOT AN ELEMENT. Measured by
    # assignment into a declared type: Railing.Create(doc, hostId, typeId,
    # position) -> ICollection<ElementId> on all six versions. The first
    # round of probing missed this, because it checked `var __r = ...` — such
    # a line compiles for ANY type on the right and so proves nothing; the
    # gate returned CS0266. The collection's meaning is physical: a flight
    # can get a railing on BOTH sides at once, and one operation creates
    # several elements. The "extra" ones cannot be hidden in the receipt —
    # something created and not shown is indistinguishable from garbage in
    # the model, and A5 checks ownership precisely by the id in the receipt.
    decl = (f"Railing __el_{s} = null;\n"
            f"ICollection<ElementId> __ids_{s} = null;" + host_decl)
    create = (f"// create_railing(hosted) {cs_line_comment_fragment(oid)}\n"
              f"{rt}\n{host_res}"
              f"__ids_{s} = Railing.Create(doc, {host_id_cs}, __ty_{s}.Id, "
              f"RailingPlacementPosition.{member});\n"
              f"if (__ids_{s} == null || __ids_{s}.Count == 0) {{ "
              f"{refuse_stmt(oid, _cs('создание ограждения на хосте не вернуло ни одного элемента'), isolation)} }}\n"
              f"foreach (var __rid_{s} in __ids_{s})\n{{\n"
              f"    var __rr_{s} = doc.GetElement(__rid_{s}) as Railing;\n"
              f"    if (__rr_{s} == null) {{ "
              f"{refuse_stmt(oid, _cs('созданное ограждение не читается как Railing'), isolation)} }}\n"
              f"    " + _stamp_block(f"__rr_{s}", f"{stamp}:{oid}") + "\n"
              f"    if (__el_{s} == null) __el_{s} = __rr_{s};\n}}")
    checks: list[WitnessCheck] = [
        # Belonging to the host is topology, and it is the element itself
        # that must confirm it, not our intent. EVERY created railing is
        # checked, not just the first: if the API returned two and the host
        # owns one, the program has not been carried out. Railing.HasHost
        # (bool) and Railing.HostId (ElementId — measured by assignment) 6/6.
        WitnessCheck(
            obligation_key="anchor",   # see the comment in the path branch
            reader_cs="",
            verdict_cs=(
                f"    foreach (var __hid_{s} in __ids_{s})\n    {{\n"
                f"        var __hr_{s} = doc.GetElement(__hid_{s}) as Railing;\n"
                f"        if (__hr_{s} == null || !__hr_{s}.HasHost\n"
                f"            || __hr_{s}.HostId == null\n"
                f"            || __hr_{s}.HostId == ElementId.InvalidElementId\n"
                f"            || __hr_{s}.HostId.ToString() != {host_id_cs}.ToString())\n"
                f"            __post.Add({_cs(oid + ': ограждение не принадлежит запрошенному хосту (topology)')});\n"
                f"    }}\n"),
            message="ограждение не принадлежит запрошенному хосту (topology)",
            style="guard"),
    ]
    # Its own receipt, not _readback_block: that one reports EXACTLY ONE id,
    # and on this branch would stay silent about the flight's second railing.
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        # 🔴 THE FIELD NAME WAS ASKED OF THE REGISTRY, NOT GUESSED
        # (04.09.2026). `created_ids` used to stand here — a name that NOT A
        # SINGLE op declared
        # (`test_address_bridge.test_the_hand_written_names_are_gone`), and so
        # NOBODY read the list of created items: not `element_addresses`, not
        # `created_keys()`. The flight's second railing existed in the model
        # and existed in not a single check.
        # 🔴 `id` STAYS ALONGSIDE, AND ITS COST IS NAMED. Two readers ask not
        # the registry but the LITERAL `id`: `idempotence.collect_created_ids`
        # (the deletion list for a rollback delta) and `collect_created_by_op`
        # (binding an op to an element for Tier-G acceptance). Removing `id`
        # would mean giving them ZERO instead of one, i.e. making both worse
        # for the sake of tidiness. Measured on the row
        # {"id":"101","railing_ids":["101","102"]}: `element_addresses` gives
        # both (used to give one), `collect_created_ids` still gives ONE
        # ("102" is not deleted on rollback, and that is a leftover IN
        # SOMEONE ELSE'S FILE), `created_ledger.extract_created` gives
        # ["101","101","102"], i.e. a duplicate: it collects ALL identity
        # fields of the registry, and `id` is declared by 59 other ops. A
        # duplicate in the registry is noise, not loss; loss would be the
        # opposite.
        f"    __rb[\"railing_ids\"] = __ids_{s}.Select("
        f"__i => __i.ToString()).ToArray();\n"
        f"    __rb[\"created_count\"] = __ids_{s}.Count;\n"
        + _stamp_readback(f"__el_{s}") +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


def emit_railing(op: dict, ver: str, stamp: str,
                 isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Branch over the closed set {path, hosted}.

    This is also where the CONDITIONALLY REQUIRED fields live — fields that
    ParamSpec.required cannot express by construction (`path`+`level` are
    needed only by the path variant, `host` — only by hosted; a static
    required=True would demand them of both branches). Same seam and the
    same reason as in emit_foundation: a typed KIR-P005 here, rather than a
    bare KeyError that above would be caught as KIR-P000 «внутренняя
    ошибка» — fail-closed, but with worse diagnostics.
    """
    variety = op.get("variety")
    if variety == "path":
        if op.get("path") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"), field_name="path",
                message_ru="create_railing(variety=path): path обязателен")])
        if op.get("level") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"),
                field_name="level",
                message_ru=("create_railing(variety=path): level обязателен — "
                            "у свободного ограждения базовый уровень задаём "
                            "мы, вывести его неоткуда"))])
        return _emit_railing_path(op, ver, stamp, isolation)
    if variety == "hosted":
        if op.get("host") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"), field_name="host",
                message_ru=("create_railing(variety=hosted): host обязателен "
                            "— это и есть лестница/пандус, которому "
                            "ограждение принадлежит"))])
        return _emit_railing_hosted(op, ver, stamp, isolation)
    raise KirRefusal([Diagnostic(
        code=RAILING_UNSUPPORTED_VARIETY, op_id=op.get("id"),
        field_name="variety", got=variety, candidates=["path", "hosted"],
        message_ru=(f"create_railing: разновидность {variety!r} не поддержана "
                    f"(в API ровно две перегрузки Railing.Create — по пути и "
                    f"по хосту)"))])


#: WHAT THIS SPOKE EMITS — DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Previously the «оп -> тело» mapping lived in the hand-written
#: `authoring._EMITTERS`, with the body here, and a thin wrapper in the hub
#: linked them (41 entries across 19 satellites). Two records of one fact in
#: different files is this tree's named defect; now there is ONE record, and
#: the hub ASKS it.
EMITTERS = {
    "create_ceiling": emit_ceiling,
    "create_railing": emit_railing,
}
