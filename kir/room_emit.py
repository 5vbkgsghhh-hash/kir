"""room_emit — emission of the ops_room.py ops (its paired file).

Its own wave zone: this module touches no other ops_*.py and no other
*_emit.py. authoring.py gets an additive import wrapper and one line in
_EMITTERS — the same minimal seam through which the framing, ceiling and
mesh waves plugged in.

Reused from authoring.py WITHOUT CHANGES (by import, not by copy): _gid,
_eid, _cs, _safe, _level_expr, _stamp_block, _stamp_readback. The same list
and the same caveat as in arch_emit.py's header: some names are private, and
a future clean seam is fixed by promoting them to public in authoring.py,
not by copying their bodies here.

═══ WHAT IS VISIBLE HERE IN THE CODE (the shape's justification is in
ops_room.py's header) ═══

* THE PLANE IS TAKEN FROM THE LEVEL, NOT COMPUTED BY US.
  `SketchPlane.Create(doc, __lv.Id)` — an overload documented by the trap
  index as "sketch plane from a grid, reference plane, or LEVEL" (6/6). The
  alternative — `Plane.CreateByNormalAndOrigin(XYZ.BasisZ, new
  XYZ(0,0,z))` with a z we computed ourselves — would introduce a SECOND
  JUDGE of where the level is, and would diverge from it on any model where
  the level moved after grounding. Curve point elevations are taken the
  same way: `MM(__lv.Elevation)`, read at runtime, not a number from
  emission.

* THE VIEW IS DERIVED FROM THE LEVEL, NOT TAKEN FROM doc.ActiveView.
  NewRoomBoundaryLines's third argument is `View`. Taking `doc.ActiveView`
  would make the result depend on whatever the user happens to be looking
  at right now — exactly the silent choice the NAMED DEFAULT (ground.py)
  was written to forbid. The rule here is CLOSED and deterministic:
      a floor plan (ViewType.FloorPlan), not a template (IsTemplate ==
      false), whose GenLevel is the operation's RESOLVED level, with the
      smallest ElementId among the matches.
  The view, the candidate count and the chosen one's name GO INTO THE
  RECEIPT (`view_id`, `view_name`, `view_candidates`): a default is named
  exactly when it is visible from outside. No candidates — a typed refusal,
  not a guess.

  WHY THIS IS NOT OVERLY RESTRICTIVE. A separator exists because it was
  DRAWN on a plan; a plan of that level exists by construction of the
  source. On K2, separators sit on 45 levels, and each one is a working
  floor with a plan.

  THE HONEST REMAINDER: WHAT exactly this argument decides is offline
  unverifiable — the trap index holds only the summary "Creates a new
  boundary line as an Room border" for the method, plus two traps about
  document ownership, not a word about the view's role. So the choice is
  made deterministic and NAMED, and the correctness of what is built is
  proven by the witnesses below (category, level, geometry), not by our
  faith in the argument.

* THE CATEGORY IS CHECKED THROUGH `Category.Id`, NOT THROUGH CONVENIENT
  MEMBERS. `Category.BuiltInCategory` exists only from 2023 on (4/6), and
  `ElementId.IntegerValue` was removed in 2026 (5/6, measured: CS1061).
  Exactly one thing is version-safe: comparing `.Category.Id` against
  `new ElementId(BuiltInCategory.OST_RoomSeparationLines)` by string.

* THIS FILE'S SECOND OPERATION IS `create_space` (2026-08-10), and it is
  built DIFFERENTLY from the separator: one identity instead of many,
  `doc.Create.NewSpace(Level, UV)` instead of `NewRoomBoundaryLines`, and
  it needs no view at all. The shape's justification and the whole API
  measurement are in ops_room.py's header; here is only what is visible in
  the code. It is worth reading separately the analysis of TWO DIFFERENT
  bad outcomes (not placed versus not enclosed) — it determines what counts
  as a refusal here and what as a violation.

* DECLARATIONS SIT IN THE OUTER SCOPE. With isolation="per_op" the creation
  block and the post-condition block land in DIFFERENT scopes, and a
  variable declared inside create is invisible to the witness (a live
  pitfall from the railings wave: CS0103 on six per_op runs). So
  `__segs_`, `__rsv_` and `__rsvn_` are declared in `decl`, and only
  assigned in `create`.
"""
from __future__ import annotations

from kir.emit_core import (  # noqa: F401
    _gid, _eid, _cs, _safe,
    _level_expr, _stamp_block, _stamp_readback,
)
from kir.emit_model import WitnessCheck, tolerance
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.ops_room import ROOM_SEPARATOR_CATEGORY

#: The C# expression for the separator category id. Built ONCE and used both
#: in the view-choice refusal and in the witness: two spellings of one
#: constant would be two answers to the question "what are we even
#: building".
_SEPARATOR_CATEGORY_CS = (
    f"new ElementId(BuiltInCategory.{ROOM_SEPARATOR_CATEGORY})")


def _view_pick_cs(s: str, oid: str, isolation: str) -> str:
    """Choosing the level's plan — a closed rule, see the module header.

    The walk goes over ALL plans in the document, not stopping at the first
    match, precisely so the candidates can be counted: the number in the
    receipt is exactly the difference between "the only one was chosen" and
    "one of seven was chosen".
    """
    return (
        f"foreach (ViewPlan __vp_{s} in new FilteredElementCollector(doc)\n"
        f"        .OfClass(typeof(ViewPlan)).Cast<ViewPlan>())\n"
        f"{{\n"
        f"    if (__vp_{s}.IsTemplate) continue;\n"
        f"    if (__vp_{s}.ViewType != ViewType.FloorPlan) continue;\n"
        f"    Level __gl_{s} = null;\n"
        f"    try {{ __gl_{s} = __vp_{s}.GenLevel; }} catch {{ }}\n"
        f"    if (__gl_{s} == null "
        f"|| __gl_{s}.Id.ToString() != __lv_{s}.Id.ToString()) continue;\n"
        f"    __rsvn_{s}++;\n"
        f"    if (__rsv_{s} == null || __vp_{s}.Id < __rsv_{s}.Id) "
        f"__rsv_{s} = __vp_{s};\n"
        f"}}\n"
        f"if (__rsv_{s} == null) {{ "
        + refuse_stmt(
            oid,
            _cs("разделитель помещений: у разрешённого уровня нет ни одного "
                "плана этажа (не шаблона), а NewRoomBoundaryLines требует "
                "вид — подставить чужой план значило бы нарисовать границу "
                "не на том этаже"),
            isolation)
        + " }")


def emit_room_separator(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, list, str]:
    """A room separator as a polyline on the level's plane.

    ``Autodesk.Revit.Creation.Document.NewRoomBoundaryLines(SketchPlane,
    CurveArray, View) -> ModelCurveArray`` — confirmed by the trap index
    (6/6) and live compilation on all six versions. The operation has no
    version axis.
    """
    oid = op["id"]
    s = _safe(oid)
    path = op["path"]
    n_segments = len(path) - 1
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)

    # Curves are placed AT THE LEVEL'S ELEVATION, read at runtime: the same
    # plane as SketchPlane.Create(doc, levelId)'s, otherwise a curve would
    # not lie on its own sketch.
    geo = [f"double __z_{s} = MM(__lv_{s}.Elevation);",
           f"CurveArray __ca_{s} = new CurveArray();"]
    for k in range(n_segments):
        a, b = path[k], path[k + 1]
        geo.append(
            f"__ca_{s}.Append(Line.CreateBound("
            f"P({a[0]}, {a[1]}, __z_{s}), P({b[0]}, {b[1]}, __z_{s})));")

    # 🔴 WHAT THE RECEIPT SEES IS DECLARED HERE. The `create` body is a
    # nested scope: a variable declared inside it is unreachable from the
    # witness. Paid for by the gate 6/6 (2026-08-30): the first draft of
    # F-257 declared `__sp_{s}` inside `create` and gave CS0103 on ALL six
    # versions, 36 refusals.
    decl = (f"List<ModelCurve> __segs_{s} = new List<ModelCurve>();\n"
            f"ViewPlan __rsv_{s} = null;\n"
            f"int __rsvn_{s} = 0;\n"
            f"SketchPlane __sp_{s} = null;\n"
            f"bool __spst_{s} = false;")

    create = (
        f"// create_room_separator {cs_line_comment_fragment(oid)}\n"
        f"{lv_res}\n"
        f"{_view_pick_cs(s, oid, isolation)}\n"
        f"__sp_{s} = SketchPlane.Create(doc, __lv_{s}.Id);\n"
        f"if (__sp_{s} == null) {{ "
        + refuse_stmt(oid, _cs("плоскость эскиза уровня не построена"),
                      isolation)
        + " }\n"
        # 🔴 THE SKETCH PLANE IS ALSO A CREATED ELEMENT (2026-08-30, an
        # F-257 audit finding). `NewRoomBoundaryLines` requires ITS OWN
        # plane on every call, so creating one cannot be avoided — it is
        # part of the call's own contract. But a `SketchPlane` is a
        # PERMANENT document Element, not a transient API object: stamps,
        # witnesses and the receipt covered ONLY the segments (`__segs`),
        # and a successful operation left an unaccounted element in the
        # model that could be neither reconciled nor cleaned up by the
        # receipt. Measured coverage: 16 buildings, 27,135 separators.
        #
        # THE `:sketchplane` SUFFIX — to tell the plane's stamp apart from
        # the segments' stamp during reconciliation and cleanup, rather than
        # hanging ONE stamp on elements with DIFFERENT roles.
        #
        # 🔴 THE STAMP IS BEST-EFFORT, AND THIS IS NOT A CONCESSION BUT A
        # MEASUREMENT BOUNDARY. `_stamp_block` in mode A5 THROWS if the
        # parameter is absent or read-only. Whether `SketchPlane` carries
        # the ALL_MODEL_INSTANCE_COMMENTS parameter is a question about the
        # live Revit API, and it cannot be checked without a host; a strict
        # stamp here could bring down the ENTIRE A5 run over 27,135
        # separators for the sake of an element that today is not accounted
        # for anyway. So the attempt is wrapped, and its OUTCOME is NAMED in
        # the receipt as the `sketch_plane_stamped` field — no silence
        # remains, and no risk of bringing down a live run appears.
        #
        # Orphan cleanup does not suffer from this: its sweep
        # (`_ORPHAN_SWEEP_TEMPLATE`) goes over ALL non-type elements and is
        # itself wrapped in try/catch, so it will find the plane if the
        # stamp landed.
        f"try {{ Parameter __spcm_{s} = __sp_{s}.get_Parameter("
        f"BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS);\n"
        f"  if (__spcm_{s} != null && !__spcm_{s}.IsReadOnly) {{\n"
        f"    __spcm_{s}.Set({_cs(f"{stamp}:{oid}:sketchplane")});\n"
        f"    __spst_{s} = (__spcm_{s}.AsString() == "
        f"{_cs(f"{stamp}:{oid}:sketchplane")});\n"
        f"  }} }} catch {{ __spst_{s} = false; }}\n"
        + "\n".join(geo) + "\n"
        f"ModelCurveArray __mca_{s} = null;\n"
        f"try {{ __mca_{s} = doc.Create.NewRoomBoundaryLines("
        f"__sp_{s}, __ca_{s}, __rsv_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid,
                      f'"NewRoomBoundaryLines: " + __ex_{s}.Message',
                      isolation)
        + " }\n"
        f"if (__mca_{s} == null) {{ "
        + refuse_stmt(oid,
                      _cs("создание разделителя помещений вернуло null"),
                      isolation)
        + " }\n"
        # Every created segment is an INDEPENDENT element, and every one
        # must be stamped: an unstamped element is foreign to A5, i.e. an
        # orphan that cleanup will not collect.
        f"foreach (ModelCurve __mc_{s} in __mca_{s})\n{{\n"
        f"    if (__mc_{s} == null) {{ "
        + refuse_stmt(oid,
                      _cs("созданный сегмент границы не читается как "
                          "ModelCurve"),
                      isolation)
        + " }\n"
        f"    " + _stamp_block(f"__mc_{s}", f"{stamp}:{oid}") + "\n"
        f"    __segs_{s}.Add(__mc_{s});\n}}\n"
        f"if (__segs_{s}.Count == 0) {{ "
        + refuse_stmt(oid,
                      _cs("создание разделителя помещений не вернуло ни "
                          "одного сегмента"),
                      isolation)
        + " }")

    tol = tolerance("create_room_separator", "endpoint_mm")
    # The expected endpoint pairs are exactly the ones that went into the
    # CurveArray. The list is built HERE from the same `path`, not
    # recomputed by the witness from C#: otherwise the check would confirm
    # our own call, not the result.
    expected = ", ".join(
        f"new double[] {{ {path[k][0]}, {path[k][1]}, "
        f"{path[k + 1][0]}, {path[k + 1][1]} }}"
        for k in range(n_segments))

    checks: list[WitnessCheck] = [
        # 1. HOW MANY. Fewer means a loss, more means litter; and from
        # outside both look like success, because an element WAS created.
        WitnessCheck(
            obligation_key="segment_count",
            reader_cs="",
            verdict_cs=(
                f"    if (__segs_{s}.Count != {n_segments})\n"
                f"        __post.Add({_cs(oid + ': room separator segment count mismatch (identity)')});\n"),
            message="room separator segment count mismatch (identity)",
            style="guard"),
        # 2. WHAT EXACTLY. The heart of the operation: prove that a
        # SEPARATOR was built, not an ordinary model line. A line "in the
        # same place" bounds nothing, and from outside it is
        # indistinguishable from a separator — exactly the class of
        # substitution the ceiling wave refused to build a floor for.
        WitnessCheck(
            obligation_key="category",
            reader_cs=(
                f"    var __rsc_{s} = {_SEPARATOR_CATEGORY_CS}.ToString();\n"),
            verdict_cs=(
                f"    foreach (var __cs_{s} in __segs_{s})\n"
                f"        if (__cs_{s}.Category == null "
                f"|| __cs_{s}.Category.Id == null\n"
                f"            || __cs_{s}.Category.Id.ToString() != __rsc_{s})\n"
                f"            __post.Add({_cs(oid + ': сегмент не является разделителем помещений (topology)')});\n"),
            message="сегмент не является разделителем помещений (topology)",
            style="guard"),
        # 3. WHERE. The level is read by the SAME Element.LevelId that the
        # extraction side reads it with (revit_read_helpers: the chain's
        # first link) — one question, one judge.
        WitnessCheck(
            obligation_key="level_binding",
            reader_cs="",
            verdict_cs=(
                f"    foreach (var __ls_{s} in __segs_{s})\n"
                f"        if (__ls_{s}.LevelId == null\n"
                f"            || __ls_{s}.LevelId == ElementId.InvalidElementId\n"
                f"            || __ls_{s}.LevelId.ToString() != {lv_idexpr})\n"
                f"            __post.Add({_cs(oid + ': level binding mismatch (topology)')});\n"),
            message="level binding mismatch (topology)",
            style="guard"),
        # 4. IS IT EXACTLY THERE. Endpoints are checked INDEPENDENTLY OF
        # ORDER within a segment (Revit is entitled to reverse a curve), but
        # NOT independently of the order of segments: shuffled segments are
        # a different polyline.
        WitnessCheck(
            obligation_key="endpoints",
            reader_cs=(
                f"    var __exp_{s} = new List<double[]>() {{ {expected} }};\n"),
            verdict_cs=(
                f"    for (int __i_{s} = 0; "
                f"__i_{s} < Math.Min(__exp_{s}.Count, __segs_{s}.Count); "
                f"__i_{s}++)\n"
                f"    {{\n"
                f"        var __gc_{s} = __segs_{s}[__i_{s}].GeometryCurve;\n"
                f"        if (__gc_{s} == null) {{ "
                f"__post.Add({_cs(oid + ': сегмент без геометрии (geometry)')}); continue; }}\n"
                f"        var __e0_{s} = __gc_{s}.GetEndPoint(0);\n"
                f"        var __e1_{s} = __gc_{s}.GetEndPoint(1);\n"
                f"        var __w_{s} = __exp_{s}[__i_{s}];\n"
                f"        bool __fwd_{s} = "
                f"Math.Abs(MM(__e0_{s}.X) - __w_{s}[0]) <= {tol}\n"
                f"            && Math.Abs(MM(__e0_{s}.Y) - __w_{s}[1]) <= {tol}\n"
                f"            && Math.Abs(MM(__e1_{s}.X) - __w_{s}[2]) <= {tol}\n"
                f"            && Math.Abs(MM(__e1_{s}.Y) - __w_{s}[3]) <= {tol};\n"
                f"        bool __rev_{s} = "
                f"Math.Abs(MM(__e1_{s}.X) - __w_{s}[0]) <= {tol}\n"
                f"            && Math.Abs(MM(__e1_{s}.Y) - __w_{s}[1]) <= {tol}\n"
                f"            && Math.Abs(MM(__e0_{s}.X) - __w_{s}[2]) <= {tol}\n"
                f"            && Math.Abs(MM(__e0_{s}.Y) - __w_{s}[3]) <= {tol};\n"
                f"        if (!__fwd_{s} && !__rev_{s})\n"
                f"            __post.Add({_cs(oid + ': endpoints mismatch (geometry)')});\n"
                f"    }}\n"),
            message="endpoints mismatch (geometry)",
            tol=tol,
            # `plain`, not `guard`/`else_block`: this check has a free
            # form — a reader, a loop over segments and two boolean
            # temporaries. The style kind changes nothing in the render (the
            # fragments themselves carry the bytes); it exists precisely so
            # an audit sees the check's SHAPE rather than guessing at it.
            style="plain"),
    ]

    # The receipt is its OWN, not _readback_block: that one reports EXACTLY
    # ONE id and a LocationCurve, while this operation has many identities
    # and a segment has no Location at all (a ModelCurve carries its
    # geometry in GeometryCurve). Here the view choice is also NAMED — a
    # default that cannot be seen is not a default.
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"segment_ids\"] = __segs_{s}.Select("
        f"__i => __i.Id.ToString()).ToArray();\n"
        f"    __rb[\"segment_count\"] = __segs_{s}.Count;\n"
        f"    __rb[\"view_id\"] = __rsv_{s}.Id.ToString();\n"
        f"    try {{ __rb[\"view_name\"] = __rsv_{s}.Name; }} catch {{ }}\n"
        f"    __rb[\"view_candidates\"] = __rsvn_{s};\n"
        # The sketch plane is named BY ID: this id lets it be reconciled and
        # cleaned up even when the stamp did not land (F-257).
        f"    __rb[\"sketch_plane_id\"] = __sp_{s}.Id.ToString();\n"
        f"    __rb[\"sketch_plane_stamped\"] = __spst_{s};\n"
        + _stamp_readback(f"__segs_{s}[0]") +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


#: The "area equals zero" threshold in Revit's INTERNAL units (square
#: feet). This is a CHECK FOR ZERO, not a size threshold: a space with no
#: bounding geometry gives Revit exactly 0.0, and the question is "is
#: there an area or not", not "is it enough". The literal is the same one
#: create_room uses (`authoring._emit_room`), and this is DELIBERATE: two
#: numbers for one question would be two judges of what "not enclosed"
#: means. The number is ASSIGNED, not measured; it is named here precisely
#: because a bare literal in a comparison is the kind of boundary the
#: bounds_audit census only finds by eye.
_SPACE_ZERO_AREA_FT2 = 1e-6


def emit_space(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, list, str]:
    """An MEP space at a point on a level.

    ``Autodesk.Revit.Creation.Document.NewSpace(Level, UV) -> Space`` —
    measured 2026-08-10 by TWO instruments: reflection over six
    ``RevitAPI.dll`` (``data/api_surface/api_signatures_*.json``) and live
    compilation at :52412 with a separate run for each of the six versions.
    The return type is proven by a compiler error (CS0029 names
    ``Autodesk.Revit.DB.Mechanical.Space``), not by documentation prose.

    THERE IS NO VERSION AXIS — see ops_room.py's header. The emitter
    therefore does not branch: a version branch here would be code
    unreachable on any target.
    """
    oid = op["id"]
    s = _safe(oid)
    x, y = op["xy"][0], op["xy"][1]
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)

    # The type is written with its FULL NAME exactly as create_room does
    # with `Autodesk.Revit.DB.Architecture.Room`: the live-path wrapper
    # pulls in `using Autodesk.Revit.DB.Mechanical`, but the emitter has no
    # right to rely on someone else's using list — it has already changed
    # once.
    decl = f"Autodesk.Revit.DB.Mechanical.Space __el_{s} = null;"

    create = (
        f"// create_space {cs_line_comment_fragment(oid)}\n"
        f"{lv_res}\n"
        f"try {{ __el_{s} = doc.Create.NewSpace("
        f"__lv_{s}, new UV(U({x}), U({y}))); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid, f'"NewSpace: " + __ex_{s}.Message', isolation)
        + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("NewSpace вернул null"), isolation)
        + " }\n"
        # ═══ AN UNPLACED SPACE IS A TYPED REFUSAL ═══
        #
        # A refusal, not a post-condition violation, and this split is
        # DELIBERATE (the analysis is in ops_room.py's header). For an
        # unplaced space there is NOTHING to check: it has no level, no
        # point, no area, and a witness that "found no discrepancies" would
        # sign a green verdict over an element that exists nowhere. A silent
        # rollback is also excluded: the reason is named in words and goes
        # out to the user.
        #
        # HONESTLY, WHAT IS NOT MEASURED HERE: whether the "level + point"
        # overload can even return an unplaced space at all is not
        # decidable offline — this wave had no live Revit. The check stands
        # on the fail-closed principle and costs nothing, NOT because the
        # path is proven live; it must not be passed off as a measured
        # scenario. It has no reverse path either: `Space.Unplace()` does
        # not exist on any of the six versions (CS1061), unlike
        # `Room.Unplace()`.
        f"if ((__el_{s}.Location as LocationPoint) == null) {{ "
        + refuse_stmt(
            oid,
            _cs("пространство создано, но НЕ РАЗМЕЩЕНО (Location == null): "
                "точка не попала ни в одну область заданного уровня — "
                "проверьте xy и level"),
            isolation)
        + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    tol = tolerance("create_space", "location_mm")
    checks: list[WitnessCheck] = [
        # WHERE — the level. Element.LevelId, the same first link the
        # extraction side reads the level with: one question, one judge.
        WitnessCheck(
            obligation_key="level_binding",
            reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.LevelId == null\n"
                f"        || __el_{s}.LevelId == ElementId.InvalidElementId\n"
                f"        || __el_{s}.LevelId.ToString() != {lv_idexpr})\n"
                f"        __post.Add({_cs(oid + ': level binding mismatch (topology)')});\n"),
            message="level binding mismatch (topology)", style="guard"),
        # WHERE — the point. Location is read, which REVIT COMPUTES, not a
        # parameter we wrote: under §18.3 the "(geometry)" label is
        # legitimate exactly for such a reader.
        #
        # Z IS NOT CHECKED, and this is not an omission:
        # `SpatialElement.Location` is documented as "Z location should be
        # the elevation of the level and NOT CHANGEABLE" — demanding from
        # Revit something it manages itself would mean writing a witness
        # that will one day reject a correct build. create_room does
        # exactly the same.
        WitnessCheck(
            obligation_key="location",
            reader_cs=f"    var __sloc_{s} = __el_{s}.Location as LocationPoint;\n",
            verdict_cs=(
                f"    if (__sloc_{s} == null\n"
                f"        || Math.Abs(MM(__sloc_{s}.Point.X) - {x}) > {tol}\n"
                f"        || Math.Abs(MM(__sloc_{s}.Point.Y) - {y}) > {tol})\n"
                f"        __post.Add({_cs(oid + ': space placement mismatch (geometry)')});\n"),
            message="space placement mismatch (geometry)",
            tol=tol, style="guard"),
        # IS IT ENCLOSED — THE MAGNITUDE. Revit computes Area from the
        # bounding geometry; zero means there was nothing to enclose with.
        # The "(geometry)" label follows from what is READ: area is a
        # geometric quantity, and calling it topology would sign an axis
        # this reader never touched.
        #
        # VOLUME IS DELIBERATELY NOT CHECKED. `Space.Volume` exists 6/6, but
        # its value depends on a DOCUMENT SETTING (volume computation), not
        # on the built element; a witness on it would be checking a
        # checkbox in the project settings. This wave has no measurement
        # proving otherwise — so there is no obligation either.
        WitnessCheck(
            obligation_key="area",
            reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.Area <= {_SPACE_ZERO_AREA_FT2})\n"
                f"        __post.Add({_cs(oid + ': space is not enclosed: zero area (geometry)')});\n"),
            message="space is not enclosed: zero area (geometry)",
            style="guard"),
        # IS IT ENCLOSED — THE RELATION. The second check does NOT
        # duplicate the first: area is HOW MUCH, while the boundary loops
        # are WHAT WITH. Only the second discharges the topology axis,
        # because only it reads the space's relation to its bounding
        # elements. Labelling an area read as "(topology)" would be exactly
        # the defect test_witness_axis_honesty was written against.
        #
        # A READ FAILURE DOES NOT STAY SILENT: it has its own message, not
        # one shared with "no boundary" — "the instrument failed" and "the
        # boundary is absent" are different facts, and merging them into one
        # line loses the cause.
        WitnessCheck(
            obligation_key="boundary",
            reader_cs=(
                f"    int __bl_{s} = 0;\n"
                f"    bool __bread_{s} = true;\n"
                f"    try\n"
                f"    {{\n"
                f"        var __bopt_{s} = new SpatialElementBoundaryOptions();\n"
                f"        IList<IList<BoundarySegment>> __bsegs_{s} = "
                f"__el_{s}.GetBoundarySegments(__bopt_{s});\n"
                f"        if (__bsegs_{s} != null)\n"
                f"            foreach (var __bloop_{s} in __bsegs_{s})\n"
                f"                if (__bloop_{s} != null && __bloop_{s}.Count > 0) "
                f"__bl_{s}++;\n"
                f"    }}\n"
                f"    catch {{ __bread_{s} = false; }}\n"),
            verdict_cs=(
                f"    if (!__bread_{s})\n"
                f"        __post.Add({_cs(oid + ': space boundary unreadable (topology)')});\n"
                f"    else if (__bl_{s} == 0)\n"
                f"        __post.Add({_cs(oid + ': space has no bounding loop (topology)')});\n"),
            message="space has no bounding loop (topology)",
            style="plain"),
    ]

    # The receipt is its OWN, not _readback_block: that one reads
    # LocationCurve, which a spatial element has none of at all.
    #
    # THE NAME AND NUMBER GO INTO THE RECEIPT, BUT NOT INTO THE WITNESS, and
    # the keys differ. `name` is whatever `Space.Name` returns, and for a
    # Room that is measured to be a CONCATENATION of the name with the
    # number (08-04, live Revit 2026), so the key is named
    # `name_and_number`: useful to a human, unusable as a check. The op
    # does not set a name at all (see ops_room.py's header), so there is
    # nothing to reconcile either — this reads what was built, it does not
    # check a promise.
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        f"    try {{ __rb[\"name_and_number\"] = __el_{s}.Name; }} catch {{ }}\n"
        f"    try {{ __rb[\"number\"] = __el_{s}.Number; }} catch {{ }}\n"
        f"    try {{ __rb[\"level_id\"] = __el_{s}.LevelId.ToString(); }} catch {{ }}\n"
        f"    try {{ __rb[\"area_m2\"] = Math.Round("
        f"UnitUtils.ConvertFromInternalUnits(__el_{s}.Area, "
        f"UnitTypeId.SquareMeters), 2); }} catch {{ }}\n"
        f"    try {{ __rb[\"volume_m3\"] = Math.Round("
        f"UnitUtils.ConvertFromInternalUnits(__el_{s}.Volume, "
        f"UnitTypeId.CubicMeters), 3); }} catch {{ }}\n"
        f"    try {{ var __rbc_{s} = __el_{s}.Category;\n"
        f"        __rb[\"category_id\"] = __rbc_{s} == null ? null : "
        f"__rbc_{s}.Id.ToString(); }} catch {{ }}\n"
        + _stamp_readback(f"__el_{s}") +
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


#: WHAT THIS SPOKE EMITS IS DECLARED HERE, NOT IN THE HUB (2026-09-02).
#: Before, the "op -> body" mapping lived in the handwritten
#: `authoring._EMITTERS`, while the body lived here, and a thin wrapper in
#: the hub linked them (41 of them across 19 satellites). Two records of
#: one fact in different files is this tree's named defect; now there is
#: ONE record, and the hub ASKS it.
EMITTERS = {
    "create_room_separator": emit_room_separator,
    "create_space": emit_space,
}
