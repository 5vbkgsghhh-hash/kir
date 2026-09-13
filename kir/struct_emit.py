"""struct_emit — wave/struct (2026-07-17) support module for create_beam /
create_foundation. This module is MINE (wave/struct's own zone): it does not
touch ops_authoring.py, ops_connect.py, spec.py's registry-module list,
connect.py, docspace.py, or any other wave's ops_*.py. authoring.py itself
gets a small, additive touch (import + two _EMITTERS entries + one
name-tuple append for the beam 3D-dims check) exactly mirroring wave/mep's
precedent (see its authoring.py diff: route_mep.py holds the logic,
authoring.py gets the registration).

Reused from authoring.py UNCHANGED (imported, not copied): _gid, _eid, _cs,
_safe, _level_expr, _pt3, _endpoint_check, _level_chain_check, _stamp_block,
_readback_block, _symbol_res, EMIT_UNSUPPORTED, IN_EMIT_DEFAULT. These are
all leading-underscore (module-private) names — a real, more fragile
cross-module coupling than wave/mep's connect.py reuse (connect.py
deliberately exposes graph_validate/emit_segments_cs/emit_fittings_cs/
emit_connectivity_witness_cs as PUBLIC names for exactly this kind of
tiling). Flagged: if a future Fable pass wants a cleaner seam, promoting
these to public names in authoring.py (drop the underscore, no behavior
change) is the fix — not attempted here to keep this wave's authoring.py
diff minimal.

create_foundation(variety="slab") is deliberately NOT implemented by
calling authoring._emit_floor() directly, even though that function's
signature would accept a shimmed create_floor-shaped dict. Reason:
_emit_floor is private and its 2021-CurveArray-vs-2022-Floor.Create branch
plus its own holes-refusal messaging are shaped around being CALLED from
_EMITTERS as create_floor's own dispatch, not around being a public "build
me a structural floor" utility. Reaching into it would be tighter, more
surprising coupling than the mep precedent set. Instead, _emit_foundation_
slab below is a SMALL, self-contained mirror of _emit_floor's 2022+
Floor.Create(doc, loops, type, level, true, null, 0.0) structural path
(same geometry helper _loop_pts, same bbox postcondition shape, same
stamp/witness helpers) — genuine pattern-reuse (the task's own wording),
not function-reuse. The 2021 legacy NewFloor(CurveArray, ..., true) path
IS also mirrored (a foundation slab must work on Revit 2021 same as any
other floor) since the gate runs all six versions.

VARIETY-CONDITIONAL REQUIRED FIELDS (xy for isolated, outline for slab):
both are declared NON-required at the ParamSpec level (each only applies to
one variety, so a static required=True would wrongly demand it on the other
branch — the exact same reasoning as symbol/type being variety-conditional
in ground.py). validate()/ground.py have no per-branch concept and
correctly let a well-formed program with, say, variety="isolated" and no
"outline" through their generic checks. That means THIS module is the only
place that can know "xy is actually required, given variety=isolated" — so
emit_foundation's dispatch below explicitly checks presence and raises a
typed KirRefusal(PARSE_MISSING_FIELD) before touching op["xy"]/op["outline"],
rather than letting a bare KeyError escape (caught upstream by compiler.py's
own catch-all as KIR-P000 "internal error" — technically fail-closed, never
a silent wrong answer, but a worse diagnostic than a proper missing-field
refusal; fixed here instead of left as the lower-quality but still-safe
fallback).
"""
from __future__ import annotations

import math

from kir.emit_core import (  # noqa: F401
    _gid, _eid, _cs, _safe,
    _level_expr, _pt3, _stamp_block, _readback_block,
    _symbol_res, _loop_pts, EMIT_UNSUPPORTED, IN_EMIT_DEFAULT,
    endpoint_witness, final_shift, level_chain_witness, bbox_extents_witness,
    profile_loops_witness,
    sketch_loops_witness,
)
from kir.emit_model import WitnessCheck, tolerance
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.diag import (
    Diagnostic, EMIT_CONTOUR_HOLES, KirRefusal, PARSE_MISSING_FIELD)

# Typed refusal for a create_foundation.kind value outside the closed
# {isolated, slab} enum this wave implements with confidence. The registry's
# `enum` ParamSpec.choices already constrains this at authoring.validate()
# time (KIR-T001 for a value outside choices) — this code is the BELT-AND-
# SUSPENDERS backstop inside the emitter itself (defense in depth: an emitter
# must never silently do the wrong thing even if an upstream check is ever
# loosened), and is what a future third kind (e.g. a real ribbon/ростверк
# foundation) would hit if someone widened the enum choices without adding
# the matching emit branch — fail LOUD, not silently-wrong.
FOUNDATION_UNSUPPORTED_KIND = "KIR-E004"

#: `create_beam_system.profile` arrived with holes. A refusal, not a silent
#: drop: `BeamSystem.Create` takes the profile as ONE flat `IList<Curve>` —
#: there is no second ring in the signature on any of the six versions
#: (measured by compilation on 09.08). Building the outer contour and
#: staying silent about the void would mean returning `ok:true` for geometry
#: the author did not ask for — a forbidden state. The fix is named
#: directly: a void in a beam system is done as a separate operation, not as
#: a field of the profile.

#: `create_beam_system.direction_edge` points to a non-straight edge (or
#: even outside the profile altogether). ONE code for both cases,
#: deliberately: the fix for them is ONE AND THE SAME — «name a different
#: number» — and the refusal carries the list of straight-edge numbers of
#: this very profile. Autodesk requires the direction curve to be a `Line`;
#: the check sits at compile time, because after CONTOUR is lowered, the
#: straightness of every edge is known in Python (bulge==0), while the same
#: mistake at runtime would arrive as an `ArgumentException` from inside the
#: transaction.
BEAM_SYSTEM_BAD_DIRECTION_EDGE = "KIR-E009"


# ── create_beam ──────────────────────────────────────────────────────────────

def emit_beam(op: dict, ver: str, stamp: str,
              isolation: str = "atomic") -> tuple[str, str, str, str]:
    """FamilyInstance over a Line, StructuralType.Beam — gold pattern verified
    against /root/27B/harvest/sdk_samples/snapshot/2025/Samples/
    CreateBeamsColumnsBraces/CS/CreateBeamsColumnsBraces.cs PlaceBeam()
    (NewFamilyInstance(Line, FamilySymbol, Level, StructuralType) + an
    IsActive/Activate() guard — exactly _symbol_res()'s existing shape).
    p0_mm/p1_mm are REQUIRED 3D (see ops_struct.py's module docstring for why
    — a beam's two ends may sit at different elevations; silently defaulting
    a missing Z to 0 would float the beam at absolute Z=0)."""
    oid = op["id"]
    s = _safe(oid)
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    decl = f"FamilyInstance __el_{s} = null;"
    create = (
        f"// create_beam {cs_line_comment_fragment(oid)}\n"
        + _symbol_res(op, s, oid, ver, isolation) + f"\n{lv_res}\n"
        f"Line __ln_{s} = Line.CreateBound(P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}));\n"
        f"__el_{s} = doc.Create.NewFamilyInstance(__ln_{s}, __sy_{s}, __lv_{s}, "
        f"Autodesk.Revit.DB.Structure.StructuralType.Beam);\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewFamilyInstance (балка) вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # FOR A BEAM, THE REFERENCE LEVEL IS RESOLVED BY REVIT, NOT BY US. Measured
    # on 27.07 by a live trial: L_01 @ 0 mm was passed in, the curve was
    # placed at Z=3000 — Revit bound the beam to L_01ДОО1_+2.500, the nearest
    # level below. The `level` argument of NewFamilyInstance(Line, …,
    # StructuralType.Beam) is placement context, not a promise;
    # INSTANCE_REFERENCE_LEVEL_PARAM follows the curve's elevation.
    # The former postcondition «reference level == resolved level» demanded
    # something the API does not promise, and it rolled back a beam that was
    # built CORRECTLY.
    # Replaced with what actually is invariant: a reference level exists (a
    # beam without a level is a real defect), and WHICH one it is — is read
    # in the witness. The beam's position is meanwhile pinned completely:
    # both ends are checked in 3D with a 5 mm tolerance.
    checks: list[WitnessCheck] = [
        # THE RESULT OF THE LAST LEGITIMATE WRITER (E-3): the same law as for
        # `create_wall` (E-2) — `emit_core.final_shift`, one reader.
        endpoint_witness(f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
                         tolerance("create_beam", "endpoint_mm"), True,
                         shift=final_shift(op)),
        WitnessCheck(
            obligation_key="reference_level", reader_cs="",
            verdict_cs=(
                f"    {{ var __rl = __el_{s}.get_Parameter("
                f"BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);\n"
                f"      if (__rl == null || __rl.AsElementId() == null\n"
                f"          || __rl.AsElementId() == ElementId.InvalidElementId)\n"
                f"        __post.Add({_cs(oid + ': нет опорного уровня (topology)')}); }}\n"),
            message="нет опорного уровня (topology)", style="guard"),
        WitnessCheck(
            obligation_key="structural_type", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Beam)\n"
                f"        __post.Add({_cs(oid + ': StructuralType != Beam (semantic)')});\n"),
            message="StructuralType != Beam (semantic)", style="guard"),
    ]
    readback = _readback_block(s, oid, stamp, identity_version=ver).replace(
        f"    __results[{_cs(oid)}] = __rb;",
        f"    try {{ var __rlp = __el_{s}.get_Parameter("
        f"BuiltInParameter.INSTANCE_REFERENCE_LEVEL_PARAM);\n"
        f"        if (__rlp != null) {{ var __rle = doc.GetElement(__rlp.AsElementId());\n"
        f"            __rb[\"reference_level_id\"] = __rlp.AsElementId().ToString();\n"
        f"            if (__rle != null) __rb[\"reference_level\"] = __rle.Name; }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;", 1)
    return decl, create, checks, readback


# ── create_foundation ─────────────────────────────────────────────────────────

def _emit_foundation_isolated(op: dict, ver: str, stamp: str,
                              isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Isolated column footing: FamilyInstance at a point, StructuralType.
    Footing. Mirrors _emit_column exactly (same NewFamilyInstance(XYZ,
    FamilySymbol, Level, StructuralType) overload create_column already
    proves 6/6), enum member swapped Column->Footing. StructuralType.Footing
    verified as a real enum member via local SDK grep (BoundaryConditions
    sample reads it off existing FamilyInstance.StructuralType — no local
    sample CREATES a footing this way, so this specific call is
    confident-by-overload-analogy + enum-verified, not sample-verified;
    flagged in the wave report)."""
    oid = op["id"]
    s = _safe(oid)
    x, y = op["xy"][0], op["xy"][1]
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    decl = f"FamilyInstance __el_{s} = null;"
    create = (f"// create_foundation(isolated) {cs_line_comment_fragment(oid)}\n"
              + _symbol_res(op, s, oid, ver, isolation) + f"\n{lv_res}\n"
              f"__el_{s} = doc.Create.NewFamilyInstance(P({x}, {y}, 0), __sy_{s}, __lv_{s}, "
              f"Autodesk.Revit.DB.Structure.StructuralType.Footing);\n"
              f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('NewFamilyInstance (фундамент) вернул null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    ftol = tolerance("create_foundation", "location_mm")
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="footprint",
            reader_cs=f"    var __loc = __el_{s}.Location as LocationPoint;\n",
            verdict_cs=(
                f"    if (__loc == null) __post.Add({_cs(oid + ': нет LocationPoint')});\n"
                f"    else if (Math.Abs(MM(__loc.Point.X) - {x}) > {ftol} || Math.Abs(MM(__loc.Point.Y) - {y}) > {ftol})\n"
                f"        __post.Add({_cs(oid + ': location mismatch (geometry)')});\n"),
            message="location mismatch (geometry)", tol=ftol,
            style="else_block"),
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
        WitnessCheck(
            obligation_key="structural_type", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Footing)\n"
                f"        __post.Add({_cs(oid + ': StructuralType != Footing (semantic)')});\n"),
            message="StructuralType != Footing (semantic)", style="guard"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


def _emit_foundation_slab(op: dict, ver: str, stamp: str,
                          isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Slab/mat/strip foundation modeled as a STRUCTURAL Floor by contour —
    this IS create_floor's own structural=True path (create_floor's post
    already says "structural flag == requested (semantic)"); mirrored here
    (not called via a private cross-import — see module docstring) at the
    same fidelity: 2022+ Floor.Create(doc, loops, type, level, true, null,
    0.0) with holes, 2021 legacy NewFloor(CurveArray, type, level, true) with
    the SAME EMIT_UNSUPPORTED refusal create_floor gives for holes pre-2022."""
    oid = op["id"]
    s = _safe(oid)
    holes = op.get("holes") or []
    if holes and ver < "2022":
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, field_name="holes",
            message_ru=f"отверстия в фундаментной плите не поддержаны на Revit {ver} "
                       f"(NewFloor без holes; Floor.Create — с 2022)")])
    lv = _gid(op, "level")
    g_type = _gid(op, "type") if isinstance(op.get("type"), dict) and "__grounded__" in op["type"] else None
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    decl = f"Floor __el_{s} = null;"
    if g_type and g_type.get("in_emit") == IN_EMIT_DEFAULT:
        ft = (f"FloorType __ft_{s} = doc.GetElement(doc.GetDefaultElementTypeId(ElementTypeGroup.FloorType)) as FloorType;\n"
              f"if (__ft_{s} == null) {{ {refuse_stmt(oid, _cs('в документе нет типа перекрытия по умолчанию (фундамент)'), isolation)} }}")
    else:
        ft = (f"FloorType __ft_{s} = doc.GetElement({_eid(g_type['id'], ver, oid)}) as FloorType;\n"
              f"if (__ft_{s} == null) {{ {refuse_stmt(oid, _cs('тип фундаментной плиты не найден (модель изменилась после grounding)'), isolation)} }}")
    outline = op["outline"]
    if ver >= "2022":
        geo = [f"var __loops_{s} = new List<CurveLoop>();"]
        geo += _loop_pts(outline, f"__ol_{s}")
        geo.append(f"__loops_{s}.Add(__ol_{s});")
        for hi, hole in enumerate(holes):
            geo += _loop_pts(hole, f"__hl_{s}_{hi}")
            geo.append(f"__loops_{s}.Add(__hl_{s}_{hi});")
        make = (f"__el_{s} = Floor.Create(doc, __loops_{s}, __ft_{s}.Id, __lv_{s}.Id, "
                f"true, null, 0.0);")
    else:
        # 2021: legacy NewFloor over a CurveArray (mirrors create_floor's own
        # version-axis divergence, SPEC 11.2), structural forced true.
        geo = [f"CurveArray __ca_{s} = new CurveArray();"]
        n = len(outline)
        for k in range(n):
            a, b = outline[k], outline[(k + 1) % n]
            geo.append(f"__ca_{s}.Append(Line.CreateBound(P({a[0]}, {a[1]}, 0), P({b[0]}, {b[1]}, 0)));")
        make = f"__el_{s} = doc.Create.NewFloor(__ca_{s}, __ft_{s}, __lv_{s}, true);"
    create = (f"// create_foundation(slab) {cs_line_comment_fragment(oid)}\n{ft}\n{lv_res}\n"
              + "\n".join(geo) + f"\n{make}\n"
              f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('создание фундаментной плиты вернуло null'), isolation)} }}\n"
              + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    xs = [pt[0] for pt in outline]; ys = [pt[1] for pt in outline]
    checks: list[WitnessCheck] = [
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
        bbox_extents_witness(
            f"__el_{s}", oid, min(xs), max(xs), min(ys), max(ys),
            tolerance("create_foundation", "bbox_mm"), key="footprint"),
        # THE SHAPE OF THE SLAB'S FOOTING. The `slab` branch is built with
        # the same `Floor.Create` as a floor slab, so its dependent Sketch is
        # the same too — the reader used is the existing one.
        # The `isolated` branch does not fall here by construction: its
        # evidence of shape is a LocationPoint, and it is already witnessed.
        sketch_loops_witness(
            f"__el_{s}", oid,
            [[list(pt) for pt in outline]]
            + [[list(pt) for pt in h] for h in (holes or [])],
            tolerance("create_foundation", "sketch_mm"),
            key="slab_loops"),
        WitnessCheck(
            obligation_key="structural_type",
            reader_cs=f"    var __sp = __el_{s}.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL);\n",
            verdict_cs=(
                f"    if (__sp == null || __sp.AsInteger() != 1)\n"
                f"        __post.Add({_cs(oid + ': структурный флаг не установлен (semantic)')});\n"),
            message="структурный флаг не установлен (semantic)", style="guard"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


def emit_foundation(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple[str, str, str, str]:
    """Dispatch on the closed {isolated, slab} variety enum (param named
    "variety", not "kind" — this registry reserves "kind" for the
    Revit-object-kind vocabulary, see ops_struct.py's NAMING NOTE). Any other
    value is a typed refusal (FOUNDATION_UNSUPPORTED_KIND) — belt-and-
    suspenders backstop behind authoring.validate()'s own enum-choices check.

    Also enforces the variety-CONDITIONAL required fields (xy for isolated,
    outline for slab) that validate()/ground.py structurally cannot express
    (see module docstring) — a typed KIR-P005 refusal, never a bare KeyError
    reaching op["xy"]/op["outline"] inside the per-variety emitters below."""
    variety = op.get("variety")
    if variety == "isolated":
        if op.get("xy") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"), field_name="xy",
                message_ru="create_foundation(variety=isolated): xy обязателен")])
        return _emit_foundation_isolated(op, ver, stamp, isolation)
    if variety == "slab":
        if op.get("outline") is None:
            raise KirRefusal([Diagnostic(
                code=PARSE_MISSING_FIELD, op_id=op.get("id"), field_name="outline",
                message_ru="create_foundation(variety=slab): outline обязателен")])
        return _emit_foundation_slab(op, ver, stamp, isolation)
    raise KirRefusal([Diagnostic(
        code=FOUNDATION_UNSUPPORTED_KIND, op_id=op.get("id"), field_name="variety",
        got=variety, candidates=["isolated", "slab"],
        message_ru=(f"create_foundation: разновидность {variety!r} не поддержана "
                    f"(только isolated/slab — сложная геометрия ростверка/ленты "
                    f"вне уверенной реализации этой волны)"))])


# ── create_wall_foundation ───────────────────────────────────────────────────

def emit_wall_foundation(op: dict, ver: str, stamp: str,
                         isolation: str = "atomic") -> tuple[str, str, list, str]:
    """A strip (wall) footing.

    WallFoundation.Create(Document, ElementId typeId, ElementId wallId) —
    ONE signature across all six versions, verified by compilation on 09.08
    against :52412 (2021-2026, 6/6 OK). This op has no version fork, and
    this is a MEASUREMENT, not an assumption: the body below is identical
    for all six, and the one place where the versions diverge at all — the
    ElementId literal — is printed by the shared `_eid` (2021-2023 know only
    the 32-bit constructor).

    THERE IS NO PREFLIGHT CHECK IN THE API. `WallFoundation.WallAllowsWallFoundation`
    does not exist on any version (CS0117 6/6) — that method belongs to an
    ENTIRELY different class, `WallSweep.WallAllowsWallSweep`. So «is this
    wall even allowed» is found out by fact: `as Wall` gives null on a
    non-wall, and Create returns null on an unsuitable wall. Both are typed
    refusals through refuse_stmt, not a single silent skip.
    """
    oid = op["id"]
    s = _safe(oid)
    wall_sel = op["wall"]

    # THE HOST AND THE TYPE ARE DECLARED IN THE OUTER SCOPE. Not a style
    # choice: with isolation="per_op" the creation block is wrapped in its
    # own try, and a variable declared inside it is invisible to the witness
    # (CS0103 — exactly what the first _emit_railing_hosted failed with on
    # the live gate).
    # The witness reads BOTH: the wall's id and the id of the requested type.
    if wall_sel.get("by") == "ref":
        # An in-program reference: create_wall of this very program. The
        # planning stage has already checked both the target's existence
        # (KIR-L003) and its typed kind (KIR-L004: a ref must lead to a
        # result of kind WALL), and the per_op wrapper adds the «reference
        # op refused» gate.
        wall_decl = ""
        wall_res = ""
        wall_id_cs = "__el_" + _safe(wall_sel["value"]) + ".Id"
    else:
        wall_decl = f"\nWall __hw_{s} = null;"
        wall_res = (
            f"__hw_{s} = doc.GetElement({_eid(wall_sel['value'], ver, oid)}) as Wall;\n"
            f"if (__hw_{s} == null) {{ "
            f"{refuse_stmt(oid, _cs('стена-носитель не найдена или не является стеной (модель изменилась после grounding, либо id указывает не на Wall)'), isolation)} }}\n")
        wall_id_cs = f"__hw_{s}.Id"

    g_type = (_gid(op, "type")
              if isinstance(op.get("type"), dict) and "__grounded__" in op["type"]
              else None)
    if g_type is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=("create_wall_foundation: тип не разрешён на стадии "
                        "ground — подставить нечего"))])
    if g_type.get("in_emit") == IN_EMIT_DEFAULT:
        type_res = (
            f"__tyid_{s} = doc.GetDefaultElementTypeId("
            f"ElementTypeGroup.WallFoundationType);\n")
    else:
        type_res = f"__tyid_{s} = {_eid(g_type['id'], ver, oid)};\n"
    # The type is resolved THROUGH THE DOCUMENT and checked by the class
    # actually obtained: on the default path GetDefaultElementTypeId returns
    # InvalidElementId when the document has no type at all, and then
    # GetElement gives null — i.e. one check honestly closes both branches.
    type_res += (
        f"if (doc.GetElement(__tyid_{s}) as WallFoundationType == null) {{ "
        f"{refuse_stmt(oid, _cs('тип ленточного фундамента не найден (в документе нет типа по умолчанию, либо модель изменилась после grounding)'), isolation)} }}\n")

    decl = (f"WallFoundation __el_{s} = null;\n"
            f"ElementId __tyid_{s} = null;" + wall_decl)
    create = (
        f"// create_wall_foundation {cs_line_comment_fragment(oid)}\n"
        f"{type_res}{wall_res}"
        f"__el_{s} = WallFoundation.Create(doc, __tyid_{s}, {wall_id_cs});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('WallFoundation.Create вернул null — стена не принимает ленточный фундамент'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    # THE WITNESS READS THE RESULT, NOT THE CALL. The element is re-read
    # FROM THE DOCUMENT by its own id (the returned object is not taken on
    # faith), and both checks ask what REVIT computed: whose foundation the
    # element considers itself to be, and what type it is. Neither of them
    # can be satisfied by the emitter having merely assigned something.
    #
    # Equality of id is EXACT, a tolerance is not needed here and would be a
    # lie: this is topology, not measurement. Comparing via Id.ToString() is
    # the only idiom legal on all six versions (.Value — 2024+,
    # .IntegerValue — through 2025), the same device as HostId in arch_emit.
    # EACH CHECK RE-READS ON ITS OWN, in its own braces. The second one used
    # to read a variable declared by the first — which tied the two checks
    # together by order: remove the first one (and the certificate does
    # exactly that, excising the witness with a mutation test), and the
    # second would be left without a declaration. An extra GetElement is
    # cheaper than coupling in the honesty layer, and nested braces keep
    # same-named neighboring locals from colliding (CS0128).
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="host_wall",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdw_{s} = doc.GetElement(__el_{s}.Id) as WallFoundation;\n"
                f"      if (__rdw_{s} == null)\n"
                f"          __post.Add({_cs(oid + ': созданный элемент не читается из документа как WallFoundation (topology)')});\n"
                f"      else if (__rdw_{s}.WallId == null\n"
                f"               || __rdw_{s}.WallId == ElementId.InvalidElementId\n"
                f"               || __rdw_{s}.WallId.ToString() != {wall_id_cs}.ToString())\n"
                f"          __post.Add({_cs(oid + ': WallId != стены-носителя (topology)')}); }}\n"),
            message="WallId != стены-носителя (topology)", style="else_block"),
        WitnessCheck(
            obligation_key="element_type",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdt_{s} = doc.GetElement(__el_{s}.Id) as WallFoundation;\n"
                f"      if (__rdt_{s} == null\n"
                f"          || __rdt_{s}.GetTypeId() == null\n"
                f"          || __rdt_{s}.GetTypeId().ToString() != __tyid_{s}.ToString())\n"
                f"          __post.Add({_cs(oid + ': тип фундамента != запрошенного (semantic)')}); }}\n"),
            message="тип фундамента != запрошенного (semantic)", style="guard"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


# ── create_beam_system ───────────────────────────────────────────────────────

def emit_beam_system(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple[str, str, list, str]:
    """A beam system on a closed sketch.

    API MEASUREMENT (compiled against :52412, against real 2021-2026 builds, 09.08):

      BeamSystem.Create(Document, IList<Curve>, Level, XYZ, bool)      → 6/6
      BeamSystem.Create(Document, IList<Curve>, Level, int, bool)      → 6/6
      BeamSystem.Create(Document, IList<Curve>, SketchPlane, XYZ, bool)→ 6/6
      BeamSystem.Create(Document, IList<Curve>, SketchPlane, int)      → 6/6
      BeamSystem.Profile   — is a CurveArray                            → 6/6
      (`IList<Curve> x = bs.Profile;` — CS0266 on all six)
      BeamSystem.GetBeamIds().Count / .Direction / .Elevation / .Level → 6/6
      BeamSystem.BeamType  — READ AND WRITTEN (FamilySymbol)           → 6/6
      ElementTypeGroup.BeamSystemType                                  → 6/6
      BuiltInParameter.BEAM_SYSTEM_LEVEL_PARAM                → 0/6 CS0117
      BuiltInParameter.BEAM_SYSTEM_ELEVATION_PARAM            → 0/6 CS0117
      ElementTypeGroup.StructuralFramingType                  → 0/6 CS0117

    The last three lines are not pedantry: they close three temptations at
    once. The level is read via the PROPERTY `bs.Level`, not a BIP chain (a
    beam system has none at all), the elevation via the property
    `bs.Elevation`, and the document cannot be asked for a "default beam
    type", so the symbol is primed by the pool, as in create_beam.

    THE OVERLOAD WITH AN EDGE NUMBER WAS CHOSEN, NOT THE ONE WITH A VECTOR,
    and this is a decision about HONESTY, not taste. A vector has no
    checkable witness: Revit returns `Direction` already normalized and
    possibly with its own sign, and comparing two unit vectors is only
    possible via an ANGULAR tolerance that nobody in this house has
    measured. A number has exactly one precondition ("the direction curve
    must be a Line"), and it is checkable BEFORE the transaction — the edges
    are already lowered, the straightness of each is known.

    `is3d` IS NOT EXPOSED IN THE REGISTRY and is always `false`. A
    three-dimensional beam system follows a sloped surface, and the
    operation has not a single input by which the author could name that
    surface; a handle whose effect has nothing to check it against is a
    handle that should not exist.
    """
    from kir import contour as C

    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]

    # HOLES ARE REFUSED, NOT DROPPED. `region` gives all the sketch laws for
    # free (addressing from grids, arcs, zero-length edges, self-intersection,
    # degenerate area), and exactly one of its degrees of freedom is
    # unavailable to the call — a second ring. A silent drop would have built
    # a SOLID system where a void was requested.
    if region["holes"]:
        raise KirRefusal([Diagnostic(
            code=EMIT_CONTOUR_HOLES, op_id=oid, field_name="profile.holes",
            got=len(region["holes"]),
            message_ru=("create_beam_system: BeamSystem.Create принимает "
                        "профиль одним плоским списком кривых — второго "
                        "кольца в подписи нет ни на одной версии 2021-2026. "
                        "Вырез в балочной системе задаётся не полем профиля"))])

    edges = region["outer"]
    straight = [k for k, edge in enumerate(edges)
                if abs(edge[2]) < C.STRAIGHT_BULGE_EPS]
    idx = op.get("direction_edge")
    if idx is None:
        # THE DEFAULT IS NAMED, NOT SILENTLY SUBSTITUTED. Zero is not our
        # invention: it is a documented value of the API itself («'0' means
        # the default direction — to use the first curve in profile»). But if
        # the first edge is an arc, it cannot be taken, and then the FIRST
        # STRAIGHT one is taken instead — a compiler choice, so it travels
        # into the receipt (`direction_edge` in readback), as the law of the
        # named default requires.
        idx = straight[0] if straight else 0
    if not straight:
        raise KirRefusal([Diagnostic(
            code=BEAM_SYSTEM_BAD_DIRECTION_EDGE, op_id=oid,
            field_name="direction_edge", got=idx, candidates=[],
            message_ru=("create_beam_system: в профиле нет ни одного прямого "
                        "ребра, а направление балочной системы Revit берёт "
                        "только с прямой кривой — целиком дуговой профиль "
                        "этой операцией невыразим"))])
    if not (0 <= idx < len(edges)) or idx not in straight:
        raise KirRefusal([Diagnostic(
            code=BEAM_SYSTEM_BAD_DIRECTION_EDGE, op_id=oid,
            field_name="direction_edge", got=idx, candidates=straight,
            message_ru=(f"create_beam_system: ребро направления {idx} "
                        f"{'вне профиля' if not (0 <= idx < len(edges)) else 'дуговое'} "
                        f"— Revit требует ПРЯМУЮ кривую; прямые рёбра этого "
                        f"профиля: {straight}"))])

    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)

    # HOSTING VARIABLES — IN THE OUTER SCOPE. With isolation="per_op" the
    # creation block is wrapped in its own try, and what is declared inside
    # it is invisible to the witness (CS0103). The witness needs the id of
    # the requested symbol.
    decl = (f"BeamSystem __el_{s} = null;\n"
            f"ElementId __syid_{s} = null;")

    # THE PLACEMENT-TYPE TRAP IS INHERITED, AND IT IS CLOSED HERE TOO. The
    # `beam_types` pool already filters by FamilyPlacementType
    # (open_model.py), but the `by: element_id` branch DOES NOT TOUCH the
    # pool at all — ground.py passes the raw id straight through, and only
    # the runtime checks it. So the pool's filter closes only half the
    # inputs, and the emitter must close the other half: a point-based
    # family assigned as `BeamType` yields a system with not a single beam
    # (or an exception from inside the transaction) instead of a named
    # refusal.
    placement_guard = (
        f"{{ var __pt_{s} = __sy_{s}.Family.FamilyPlacementType;\n"
        f"  if (__pt_{s} != FamilyPlacementType.CurveDrivenStructural "
        f"&& __pt_{s} != FamilyPlacementType.CurveBased) {{ "
        + refuse_stmt(oid, (
            f'"типоразмер балки размещается по точке (" + __pt_{s}.ToString() '
            f'+ "), а балочная система ставит балки по кривой — '
            f'этим типом она построена быть не может"'), isolation)
        + " } }")

    profile_cs = C.emit_curve_list_cs(edges, f"__prof_{s}", f"__z_{s}")
    create = (
        f"// create_beam_system {cs_line_comment_fragment(oid)}\n"
        + _symbol_res(op, s, oid, ver, isolation) + "\n"
        + placement_guard + "\n"
        f"__syid_{s} = __sy_{s}.Id;\n"
        f"{lv_res}\n"
        # THE PROFILE IS LAID ON ITS OWN LEVEL'S ELEVATION, not on Z=0. The
        # overload with `Level` takes the work plane from the level; curves
        # left at zero under a level at +3.000 are either rejected or yield a
        # system at elevation -3000 — i.e. SILENTLY on the wrong floor. The
        # same device and the same reason as in room_emit
        # (`double __z = MM(__lv.Elevation)`).
        f"double __z_{s} = MM(__lv_{s}.Elevation);\n"
        f"{profile_cs}\n"
        # THE EXCEPTION IS CAUGHT AND TRANSLATED INTO A REFUSAL. Autodesk
        # lists four different ArgumentExceptions for this overload (a
        # helical curve in the profile, the level has no floor plan, the plan
        # is unsuitable, the sketch plane cannot be taken from the level) —
        # none of them is predictable from the snapshot, and all four must
        # become a named refusal, not an «internal error».
        f"try {{ __el_{s} = BeamSystem.Create(doc, __prof_{s}, __lv_{s}, "
        f"{idx}, false); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid, f'"BeamSystem.Create: " + __ex_{s}.Message', isolation)
        + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("BeamSystem.Create вернул null"), isolation)
        + " }\n"
        # THE BEAM TYPE IS ASSIGNED BY US — so we are the ones accountable
        # for it. This is exactly the distinction from CLAUDE.md: «either the
        # emitter sets the value (then the witness is honest), or Revit
        # chooses it (then the witness demands something nobody asked for)».
        # Here it is the former.
        f"try {{ __el_{s}.BeamType = __sy_{s}; }}\n"
        f"catch (Exception __exb_{s}) {{ "
        + refuse_stmt(oid, f'"BeamSystem.BeamType: " + __exb_{s}.Message', isolation)
        + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    # THE BOUNDING BOX IS COMPUTED FROM VERTICES ON BOTH SIDES. C# sees
    # exactly the curve endpoints on the read-back profile, so the Python
    # side must also compute from vertices (`edges_vertex_bbox`), not from
    # `edges_bbox` with the cardinal extrema of arcs: otherwise a correctly
    # built system would be blamed for exactly the arc's sagitta. What
    # remains unchecked is named in `post`.
    vx0, vy0, vx1, vy1 = C.edges_vertex_bbox(edges)
    btol = tolerance("create_beam_system", "bbox_mm")
    checks: list[WitnessCheck] = [
        # 🔴 THE PROFILE-SHAPE WITNESS IS THE CHEAPEST OF THE SIX, BECAUSE
        # THE EVIDENCE WAS ALREADY IN HAND. The witness below walks EVERY
        # curve of `BeamSystem.Profile` and reads BOTH its ends — and then
        # collapses all of it into four bounding-box numbers. It was only the
        # comparison that discarded the evidence: for a six-edge profile only
        # 4 of 12 coordinates stayed under watch, and a shifted interior
        # corner passed green, signing off the axis (geometry).
        #
        # The bounding-box check is NOT removed: it stands on
        # `edges_vertex_bbox` (vertices, not `edges_bbox` with the arc
        # extrema) and catches its own share.
        profile_loops_witness(
            f"__el_{s}", oid, "BeamSystem",
            [C.edges_vertices(edges)],
            tolerance("create_beam_system", "sketch_mm")),
        # EACH CHECK RE-READS THE ELEMENT ON ITS OWN, in its own braces:
        # witnesses must not be tied together by order (the certificate
        # excises them one at a time with a mutation test), and nested
        # braces keep same-named locals from colliding (CS0128).
        WitnessCheck(
            obligation_key="profile_bbox",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdp_{s} = doc.GetElement(__el_{s}.Id) as BeamSystem;\n"
                f"      CurveArray __pr_{s} = __rdp_{s} == null ? null : __rdp_{s}.Profile;\n"
                f"      if (__rdp_{s} == null || __pr_{s} == null || __pr_{s}.Size == 0)\n"
                f"          __post.Add({_cs(oid + ': профиль балочной системы не читается обратно (geometry)')});\n"
                f"      else {{\n"
                # ONE DECLARATION PER LINE, and this is not a style choice:
                # the scope contract (test_emitter_scope_contract) reads
                # declarations with a regular expression and sees only `a`
                # in `double a = 1, b = 2;`. The second variable would become
                # «declared nowhere» to it — that is, an instrument silent
                # over part of the range. We keep the form it reads in full.
                f"          double __bx0_{s} = double.MaxValue;\n"
                f"          double __by0_{s} = double.MaxValue;\n"
                f"          double __bx1_{s} = double.MinValue;\n"
                f"          double __by1_{s} = double.MinValue;\n"
                f"          foreach (Curve __pc_{s} in __pr_{s})\n"
                f"          {{\n"
                f"              for (int __pk_{s} = 0; __pk_{s} < 2; __pk_{s}++)\n"
                f"              {{\n"
                f"                  XYZ __pp_{s} = __pc_{s}.GetEndPoint(__pk_{s});\n"
                f"                  double __px_{s} = MM(__pp_{s}.X);\n"
                f"                  double __py_{s} = MM(__pp_{s}.Y);\n"
                f"                  if (__px_{s} < __bx0_{s}) __bx0_{s} = __px_{s};\n"
                f"                  if (__px_{s} > __bx1_{s}) __bx1_{s} = __px_{s};\n"
                f"                  if (__py_{s} < __by0_{s}) __by0_{s} = __py_{s};\n"
                f"                  if (__py_{s} > __by1_{s}) __by1_{s} = __py_{s};\n"
                f"              }}\n"
                f"          }}\n"
                f"          if (Math.Abs(__bx0_{s} - {round(vx0, 1)}) > {btol} "
                f"|| Math.Abs(__bx1_{s} - {round(vx1, 1)}) > {btol}\n"
                f"              || Math.Abs(__by0_{s} - {round(vy0, 1)}) > {btol} "
                f"|| Math.Abs(__by1_{s} - {round(vy1, 1)}) > {btol})\n"
                f"              __post.Add({_cs(oid + ': profile bbox mismatch (geometry)')});\n"
                f"      }} }}\n"),
            message="profile bbox mismatch (geometry)", tol=btol,
            style="else_block"),
        # THE NUMBER OF BEAMS IS NOT HERE AND CANNOT BE. The layout spacing
        # is chosen by LayoutRule, which no argument of `Create` specifies:
        # the author named NO count at all, and demanding one would mean
        # checking something invented. What is checked is the RESULT that the
        # author did order by the very fact of the operation: the system was
        # obliged to lay down at least something. Zero beams is a real,
        # observed outcome (a profile smaller than the layout spacing), and
        # from the outside it is indistinguishable from success.
        WitnessCheck(
            obligation_key="beams_laid",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdn_{s} = doc.GetElement(__el_{s}.Id) as BeamSystem;\n"
                f"      if (__rdn_{s} == null || __rdn_{s}.GetBeamIds() == null\n"
                f"          || __rdn_{s}.GetBeamIds().Count == 0)\n"
                f"          __post.Add({_cs(oid + ': балочная система не положила ни одной балки (semantic)')}); }}\n"),
            message="балочная система не положила ни одной балки (semantic)",
            style="guard"),
        # THE LEVEL IS READ VIA A PROPERTY, NOT A BIP CHAIN: a beam system
        # has no BEAM_SYSTEM_LEVEL_PARAM (0/6), but it does have `Level`. The
        # comparison is exact — it is equality of id, not a measurement. And
        # unlike create_beam, the level here is OURS: it is an argument of
        # the call, not something Revit infers from the curve's elevation.
        WitnessCheck(
            obligation_key="level_binding",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdl_{s} = doc.GetElement(__el_{s}.Id) as BeamSystem;\n"
                f"      if (__rdl_{s} == null || __rdl_{s}.Level == null\n"
                f"          || __rdl_{s}.Level.Id.ToString() != {lv_idexpr})\n"
                f"          __post.Add({_cs(oid + ': level binding mismatch (topology)')}); }}\n"),
            message="level binding mismatch (topology)", style="guard"),
        WitnessCheck(
            obligation_key="beam_type",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdt_{s} = doc.GetElement(__el_{s}.Id) as BeamSystem;\n"
                f"      if (__rdt_{s} == null || __rdt_{s}.BeamType == null\n"
                f"          || __rdt_{s}.BeamType.Id.ToString() != __syid_{s}.ToString())\n"
                f"          __post.Add({_cs(oid + ': тип балки != запрошенного (semantic)')}); }}\n"),
            message="тип балки != запрошенного (semantic)", style="guard"),
    ]

    # THE RECEIPT CARRIES WHAT THE WITNESS DOES NOT DEMAND. The author will
    # see the direction, the elevation, the layout rule, and the NUMBER OF
    # BEAMS LAID — just not as a requirement. Exactly the same device by
    # which create_beam shows the reference level Revit inferred.
    readback = _readback_block(s, oid, stamp, identity_version=ver).replace(
        f"    __results[{_cs(oid)}] = __rb;",
        f"    __rb[\"direction_edge\"] = {idx};\n"
        f"    try {{ var __rbs_{s} = doc.GetElement(__el_{s}.Id) as BeamSystem;\n"
        f"        if (__rbs_{s} != null) {{\n"
        f"            __rb[\"beam_count\"] = __rbs_{s}.GetBeamIds().Count;\n"
        f"            __rb[\"elevation_mm\"] = Math.Round(MM(__rbs_{s}.Elevation), 1);\n"
        f"            __rb[\"layout_rule\"] = __rbs_{s}.LayoutRule.ToString();\n"
        f"            var __rbd_{s} = __rbs_{s}.Direction;\n"
        f"            if (__rbd_{s} != null) __rb[\"direction\"] = new double[] {{\n"
        f"                Math.Round(__rbd_{s}.X, 6), Math.Round(__rbd_{s}.Y, 6),\n"
        f"                Math.Round(__rbd_{s}.Z, 6) }};\n"
        f"            if (__rbs_{s}.Level != null) __rb[\"level_name\"] = __rbs_{s}.Level.Name;\n"
        f"            if (__rbs_{s}.BeamType != null) __rb[\"beam_type_name\"] = __rbs_{s}.BeamType.Name;\n"
        f"        }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;", 1)
    return decl, create, checks, readback


# ── create_truss ─────────────────────────────────────────────────────────────

_TRUSS_CS = "Autodesk.Revit.DB.Structure.Truss"
_TRUSS_TYPE_CS = "Autodesk.Revit.DB.Structure.TrussType"


def emit_truss(op: dict, ver: str, stamp: str,
               isolation: str = "atomic") -> tuple[str, str, list, str]:
    """A truss on a base segment on the level's plane.

    API MEASUREMENT (compiled against :52412, against real 2021-2026 builds, 09.08):

      Truss.Create(Document, ElementId typeId, ElementId sketchPlaneId, Curve)
                                                                      → 6/6
      Truss.Curves — CurveArray, Truss.Members — ICollection<ElementId> → 6/6
      (`.Members.Size` — CS1061 on all six: this is NOT ElementIdSet)
      Truss.TrussType / GetTypeId / Location as LocationCurve          → 6/6
      TrussType — a FamilySymbol descendant (IsActive/Activate)         → 6/6
      SketchPlane.Create(Document, ElementId of the level)              → 6/6
      BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM             → 6/6
      ElementTypeGroup.TrussType                              → 0/6 CS0117

    There is ONE signature across all six versions — the operation has no
    version fork.

    THE SKETCH PLANE IS THE LEVEL'S PLANE. Autodesk requires the base curve
    to lie IN the sketch plane and not be vertical. The SDK's golden sample
    (`Samples/Truss/CS/TrussForm.cs`) builds the plane by hand from
    `Plane.CreateByOriginAndBasis` at ZERO and lays the curve at Z=0 — that
    is, at the elevation of "the first floor" and nowhere else. Here the
    overload `SketchPlane.Create(doc, levelId)` is used instead (the same
    one as in create_room_separator, verified live), and the curve is laid
    at that level's elevation: then both preconditions hold BY
    CONSTRUCTION, not by luck — "in the plane" follows from an identical Z,
    "not vertical" from a non-zero length in plan, which reject_zero_length
    has already checked at validation.

    THE TRUSS HAS NO DEFAULT TYPE. `ElementTypeGroup.TrussType` does not
    compile on any of the six versions — asking the document "your default
    truss" is impossible BY CONSTRUCTION, exactly as for a door, a window,
    and a railing. So a type left unresolved at the ground stage is a typed
    refusal here, not a substitution.
    """
    oid = op["id"]
    s = _safe(oid)
    x0, y0 = op["p0_mm"][0], op["p0_mm"][1]
    x1, y1 = op["p1_mm"][0], op["p1_mm"][1]

    g_type = (_gid(op, "type")
              if isinstance(op.get("type"), dict) and "__grounded__" in op["type"]
              else None)
    if g_type is None or g_type.get("id") is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=("create_truss: тип фермы не разрешён на стадии ground "
                        "— типа по умолчанию у фермы в API нет "
                        "(ElementTypeGroup.TrussType отсутствует на всех "
                        "версиях 2021-2026), подставить нечего"))])

    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)

    # IN THE OUTER SCOPE — exactly what the witness re-reads: the elevation
    # of the level's plane and the id of the requested type (with per_op the
    # creation block lives in its own try, and what is declared there is
    # invisible to the witness, CS0103).
    decl = (f"{_TRUSS_CS} __el_{s} = null;\n"
            f"double __z_{s} = 0;\n"
            f"ElementId __tyid_{s} = null;")

    create = (
        f"// create_truss {cs_line_comment_fragment(oid)}\n"
        f"{_TRUSS_TYPE_CS} __ty_{s} = doc.GetElement("
        f"{_eid(g_type['id'], ver, oid)}) as {_TRUSS_TYPE_CS};\n"
        f"if (__ty_{s} == null) {{ "
        + refuse_stmt(oid, _cs("тип фермы не найден или не является TrussType "
                               "(модель изменилась после grounding, либо id "
                               "указывает не на тип фермы)"), isolation)
        + " }\n"
        # TrussType is a FamilySymbol descendant (measured), and an
        # unactivated family type is a known cause of placement failure. The
        # same device as in the common `_symbol_res`.
        f"if (!__ty_{s}.IsActive) {{ __ty_{s}.Activate(); doc.Regenerate(); }}\n"
        f"__tyid_{s} = __ty_{s}.Id;\n"
        f"{lv_res}\n"
        f"SketchPlane __sp_{s} = SketchPlane.Create(doc, __lv_{s}.Id);\n"
        f"if (__sp_{s} == null) {{ "
        + refuse_stmt(oid, _cs("плоскость эскиза уровня не построена — ферме "
                               "негде лежать"), isolation)
        + " }\n"
        f"__z_{s} = MM(__lv_{s}.Elevation);\n"
        f"Line __base_{s} = Line.CreateBound(P({x0}, {y0}, __z_{s}), "
        f"P({x1}, {y1}, __z_{s}));\n"
        # Autodesk declares for Truss.Create BOTH an ArgumentException (the
        # curve is unfit as the truss base, the id is the wrong class) AND an
        # InvalidOperationException («the function is available only in
        # Revit Structure/Architecture» and «failed to create the truss»).
        # The latter is about the user's REVIT EDITION, and it must not
        # surface as an «internal error» under any circumstances: it is a
        # named refusal with a real reason.
        f"try {{ __el_{s} = {_TRUSS_CS}.Create(doc, __tyid_{s}, __sp_{s}.Id, "
        f"__base_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid, f'"Truss.Create: " + __ex_{s}.Message', isolation)
        + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("Truss.Create вернул null"), isolation)
        + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    etol = tolerance("create_truss", "endpoint_mm")
    checks: list[WitnessCheck] = [
        # THE PLAN — via the common witness. `endpoint_witness` handles the
        # order of the endpoints itself (Revit is entitled to return the
        # curve reversed), and this is exactly the same check as for
        # create_beam: the author's segment against the LocationCurve of the
        # load-bearing element. That a truss's LocationCurve is precisely its
        # base curve is not a guess: the SDK's golden sample reads
        # `(m_truss.Location as LocationCurve).Curve as Line` exactly as the
        # truss's start and end.
        # THE RESULT OF THE LAST LEGITIMATE WRITER (E-3), AND PLAN-ONLY:
        # the truss's base is a two-dimensional point, `shifted_point` takes
        # exactly the axes the point HAS. A vertical shift of the truss is
        # checked by this witness NEITHER BEFORE NOR AFTER the edit — Z is
        # not compared here at all (the elevation is taken from the plane at
        # runtime, see base_elevation).
        endpoint_witness(f"__el_{s}", oid, [x0, y0], [x1, y1], etol, False,
                         shift=final_shift(op)),
        # THE HEIGHT — as a separate check, and the expected number is
        # computed AT RUNTIME. The common witness compares Z against a
        # literal, but here there is no literal and there should not be: the
        # plane's elevation is the level's elevation, known only in the
        # model. The promise here is OURS (we ourselves laid the curve at
        # __z), so asking for it is honest — unlike the reference level
        # below, which Revit infers.
        WitnessCheck(
            obligation_key="base_elevation",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __tz_{s} = __el_{s}.Location as LocationCurve;\n"
                f"      if (__tz_{s} == null)\n"
                f"          __post.Add({_cs(oid + ': нет LocationCurve (geometry)')});\n"
                f"      else if (Math.Abs(MM(__tz_{s}.Curve.GetEndPoint(0).Z) - __z_{s}) > {etol}\n"
                f"               || Math.Abs(MM(__tz_{s}.Curve.GetEndPoint(1).Z) - __z_{s}) > {etol})\n"
                f"          __post.Add({_cs(oid + ': base elevation mismatch (geometry)')}); }}\n"),
            message="base elevation mismatch (geometry)", tol=etol,
            style="else_block"),
        WitnessCheck(
            obligation_key="element_type",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdt_{s} = doc.GetElement(__el_{s}.Id);\n"
                f"      if (__rdt_{s} == null || __rdt_{s}.GetTypeId() == null\n"
                f"          || __rdt_{s}.GetTypeId().ToString() != __tyid_{s}.ToString())\n"
                f"          __post.Add({_cs(oid + ': тип фермы != запрошенного (semantic)')}); }}\n"),
            message="тип фермы != запрошенного (semantic)", style="guard"),
        # WHAT IS INSIDE THE TRUSS IS DECIDED BY THE FAMILY, NOT BY US.
        # The operation names neither the number of chords, nor the number
        # of diagonals, nor the panel spacing, so the only thing checked is
        # what is ordered by the very fact of construction: the truss must
        # COME INTO BEING as an assembly. An empty `Members` is a shell
        # without members, indistinguishable from the outside from success.
        WitnessCheck(
            obligation_key="members_derived",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdm_{s} = doc.GetElement(__el_{s}.Id) as {_TRUSS_CS};\n"
                f"      if (__rdm_{s} == null || __rdm_{s}.Members == null\n"
                f"          || __rdm_{s}.Members.Count == 0)\n"
                f"          __post.Add({_cs(oid + ': ферма не породила ни одного стержня (semantic)')}); }}\n"),
            message="ферма не породила ни одного стержня (semantic)",
            style="guard"),
        # REFERENCE LEVEL: EXISTENCE IS CHECKED, NOT EQUALITY — and this is
        # a DIRECT LESSON from create_beam, paid for by the live measurement
        # of 27.07. There the postcondition «reference level == the one
        # passed in» rolled back beams that were built CORRECTLY, because
        # Revit infers the binding itself. A truss's call has no level at
        # all (there is a sketch plane instead), so demanding equality would
        # be even bolder. Which level was chosen — the receipt carries that.
        WitnessCheck(
            obligation_key="reference_level",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rl_{s} = __el_{s}.get_Parameter("
                f"BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM);\n"
                f"      if (__rl_{s} == null || __rl_{s}.AsElementId() == null\n"
                f"          || __rl_{s}.AsElementId() == ElementId.InvalidElementId)\n"
                f"          __post.Add({_cs(oid + ': нет опорного уровня (topology)')}); }}\n"),
            message="нет опорного уровня (topology)", style="guard"),
    ]

    readback = _readback_block(s, oid, stamp, identity_version=ver).replace(
        f"    __results[{_cs(oid)}] = __rb;",
        f"    try {{ var __rbt_{s} = doc.GetElement(__el_{s}.Id) as {_TRUSS_CS};\n"
        f"        if (__rbt_{s} != null) {{\n"
        f"            __rb[\"member_count\"] = __rbt_{s}.Members.Count;\n"
        f"            if (__rbt_{s}.Curves != null) __rb[\"curve_count\"] = __rbt_{s}.Curves.Size;\n"
        f"        }}\n"
        f"        var __rlp_{s} = __el_{s}.get_Parameter("
        f"BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM);\n"
        f"        if (__rlp_{s} != null) {{\n"
        f"            __rb[\"reference_level_id\"] = __rlp_{s}.AsElementId().ToString();\n"
        f"            var __rle_{s} = doc.GetElement(__rlp_{s}.AsElementId());\n"
        f"            if (__rle_{s} != null) __rb[\"reference_level\"] = __rle_{s}.Name;\n"
        f"        }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;", 1)
    return decl, create, checks, readback


# ── create_area_reinforcement ────────────────────────────────────────────────

#: BOTH REFUSALS OF THIS OPERATION ARE RUNTIME ONES, AND DELIBERATELY HAVE
#: NO CODE. The first version of this module declared, side by side, two
#: constants `KIR-E010`/`KIR-E011` for «the host is not horizontal» and «the
#: host cannot carry reinforcement» — and neither of them would EVER be
#: referenced in the code: both checks live in the emitted C# and travel
#: through `refuse_stmt`, which does not accept a code at all. A name that
#: looks like a working mechanism and is called from nowhere is exactly the
#: dark spot this package's own reachability instruments catch; hence an
#: explanation stands here, not a pair of dead constants. The refusal
#: reasons themselves are recorded at their own `if`s in
#: :func:`emit_area_reinforcement`.


def emit_area_reinforcement(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Area reinforcement — by the HOST BOUNDARY.

    API MEASUREMENT (compiled against :52412, against real 2021-2026 builds,
    10.08 — the arbiter is the compiler, not the XML):

      AreaReinforcement.Create(Document, Element, XYZ, ElementId×3)     → 6/6
      AreaReinforcement.GetHostId / .GetTypeId / .Direction             → 6/6
      AreaReinforcement.GetRebarInSystemIds / .GetBoundaryCurveIds      → 6/6
      RebarHostData.IsValidHost(Element)                                → 6/6
      ReinforcementSettings.GetReinforcementSettings(doc)
          .HostStructuralRebar                                          → 6/6
      RebarInSystem.GetTypeId()                                         → 6/6
      ElementTypeGroup.AreaReinforcementType                            → 6/6

      AreaReinforcement.GetNumberOfLines()   → 0/6 (absent on 2021; on 2022+
                                               requires AreaReinforcementLayer-
                                               Type, which 2021 does not have)
      AreaReinforcement.GetLayerDirection(i) → 5/6 (absent on 2021)
      BuiltInParameter.REBAR_BAR_TYPE        → 0/6  CS0117, DOES NOT EXIST

    THERE IS NO PER-LAYER WITNESS HERE, AND THIS IS A MEASUREMENT. The
    entire per-layer slice of the API (the number of layer lines, its
    direction, its activity) is absent on 2021, and on 2022+ it is keyed by
    an enum that 2021 does not have at all. A witness that works on five of
    six versions is an «instrument over part of the range», which in this
    house is more dangerous than a missing one.

    THIS BODY HAS NOT A SINGLE TOLERANCE. All four checks are equalities of
    id and a count, i.e. topology and semantics. The geometry is
    deliberately not guarded: the boundary is computed by Revit from the
    host itself (the operation carries not a single authored quantity), and
    across 38 saved decompiles with a census there are ZERO elements of
    OST_AreaRein/OST_PathRein/OST_Rebar/OST_FabricAreas (measured 10.08),
    i.e. there is nowhere to derive a number from. See the header of
    ops_struct.py.
    """
    oid = op["id"]
    s = _safe(oid)
    host_sel = op["host"]

    # ────────── TYPES ──────────
    # All three ids are declared in the OUTER scope: with isolation="per_op"
    # the creation block is wrapped in its own try, and what is declared
    # inside it is invisible to the witness (CS0103). The witness reads both
    # the system type and the bar type.
    g_type = (_gid(op, "type")
              if isinstance(op.get("type"), dict) and "__grounded__" in op["type"]
              else None)
    if g_type is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="type",
            message_ru=("create_area_reinforcement: тип армирования не "
                        "разрешён на стадии ground — подставить нечего"))])
    if g_type.get("in_emit") == IN_EMIT_DEFAULT:
        type_res = (f"__tyid_{s} = doc.GetDefaultElementTypeId("
                    f"ElementTypeGroup.AreaReinforcementType);\n")
    else:
        type_res = f"__tyid_{s} = {_eid(g_type['id'], ver, oid)};\n"
    # One check honestly closes BOTH branches: on the document path
    # GetDefaultElementTypeId returns InvalidElementId when the document has
    # no type at all, and then GetElement gives null.
    type_res += (
        f"if (doc.GetElement(__tyid_{s}) as "
        f"Autodesk.Revit.DB.Structure.AreaReinforcementType == null) {{ "
        f"{refuse_stmt(oid, _cs('тип армирования по области не найден (в документе нет типа по умолчанию, либо модель изменилась после grounding)'), isolation)} }}\n")

    g_bar = (_gid(op, "bar_type")
             if isinstance(op.get("bar_type"), dict)
             and "__grounded__" in op["bar_type"] else None)
    if g_bar is None:
        raise KirRefusal([Diagnostic(
            code=PARSE_MISSING_FIELD, op_id=oid, field_name="bar_type",
            message_ru=("create_area_reinforcement: тип стержня не разрешён "
                        "на стадии ground — армирование без диаметра "
                        "невыразимо"))])
    type_res += f"__btid_{s} = {_eid(g_bar['id'], ver, oid)};\n"
    type_res += (
        f"if (doc.GetElement(__btid_{s}) as "
        f"Autodesk.Revit.DB.Structure.RebarBarType == null) {{ "
        f"{refuse_stmt(oid, _cs('тип стержня не найден или не является RebarBarType (модель изменилась после grounding)'), isolation)} }}\n")

    # A SKIPPED HOOK = NO HOOKS, by the value of the API ITSELF.
    # `InvalidElementId` is documented here by Autodesk («it means to create
    # a rebar with no hooks»), i.e. this is not a compiler substitution but
    # a direct record of what the author said: they named no hook.
    g_hook = (_gid(op, "hook_type")
              if isinstance(op.get("hook_type"), dict)
              and "__grounded__" in op["hook_type"] else None)
    if g_hook is None:
        type_res += f"__hkid_{s} = ElementId.InvalidElementId;\n"
    else:
        type_res += f"__hkid_{s} = {_eid(g_hook['id'], ver, oid)};\n"
        type_res += (
            f"if (doc.GetElement(__hkid_{s}) as "
            f"Autodesk.Revit.DB.Structure.RebarHookType == null) {{ "
            f"{refuse_stmt(oid, _cs('тип крюка не найден или не является RebarHookType (модель изменилась после grounding)'), isolation)} }}\n")

    # ────────── HOST ──────────
    if host_sel.get("by") == "ref":
        # An in-program reference: the planning stage has already checked
        # both the target's existence (KIR-L003) and its kind (KIR-L004),
        # and the per_op wrapper adds the «reference op refused» gate.
        host_res = f"__hh_{s} = __el_{_safe(host_sel['value'])};\n"
    else:
        host_res = (
            f"__hh_{s} = doc.GetElement({_eid(host_sel['value'], ver, oid)});\n")
    host_res += (
        f"if (__hh_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('носитель армирования не найден (модель изменилась после grounding)'), isolation)} }}\n"
        # HORIZONTALITY — FIRST, because its violation SILENTLY gives a
        # wrong result, not an exception: for a wall, `Create` will succeed,
        # but Revit will project the plan direction onto ITS vertical plane.
        # For a wall along Y, a 0° angle degenerates to zero (a lucky case —
        # an exception will fly), but for a wall at 45° the projection is
        # non-zero and NOT the one the author meant: the reinforcement will
        # land in the wrong place, and from the outside this is
        # indistinguishable from success. Exactly the outcome this whole
        # package was written to forbid, so the check stands BEFORE the call
        # and names the next move.
        f"if (!(__hh_{s} is Floor)) {{ "
        f"{refuse_stmt(oid, _cs('носитель армирования по области должен быть перекрытием/плитой: у вертикального носителя главное направление лежит в ЕГО плоскости, и плановым углом direction_deg оно не задаётся — армирование стены этой операцией невыразимо'), isolation)} }}\n"
        # A PREFLIGHT CHECK OF THE API ITSELF, not our invention. Its text
        # names exactly the two fixes that Autodesk also names.
        f"if (!Autodesk.Revit.DB.Structure.RebarHostData.IsValidHost(__hh_{s})) {{ "
        f"{refuse_stmt(oid, _cs('носитель не может нести армирование (RebarHostData.IsValidHost = false): сделай перекрытие несущим или смени его материал на бетон'), isolation)} }}\n")

    # ────────── DIRECTION ──────────
    # ALL TRIGONOMETRY AT COMPILE TIME, as the CONTOUR law requires: two
    # literals travel into C#. The vector's length equals one by
    # construction, so the documented «majorDirection has zero length» is
    # unreachable here.
    ang = math.radians(float(op["direction_deg"]))
    dx, dy = round(math.cos(ang), 9), round(math.sin(ang), 9)

    decl = (f"Autodesk.Revit.DB.Structure.AreaReinforcement __el_{s} = null;\n"
            f"ElementId __tyid_{s} = null;\n"
            f"ElementId __btid_{s} = null;\n"
            f"ElementId __hkid_{s} = null;\n"
            f"Element __hh_{s} = null;")

    create = (
        f"// create_area_reinforcement {cs_line_comment_fragment(oid)}\n"
        f"{type_res}{host_res}"
        f"XYZ __dir_{s} = new XYZ({dx}, {dy}, 0.0);\n"
        # THE EXCEPTION IS CAUGHT AND TRANSLATED INTO A REFUSAL. Autodesk
        # lists five different ArgumentExceptions for this overload (the
        # host is not in the document; the host is unfit; each of the three
        # ids is the wrong class) — none of them is fully predictable from
        # the snapshot, and all of them must become a named refusal, not an
        # «internal error».
        f"try {{ __el_{s} = Autodesk.Revit.DB.Structure.AreaReinforcement.Create("
        f"doc, __hh_{s}, __dir_{s}, __tyid_{s}, __btid_{s}, __hkid_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid, f'"AreaReinforcement.Create: " + __ex_{s}.Message', isolation)
        + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("AreaReinforcement.Create вернул null"), isolation)
        + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    # THE WITNESS READS THE RESULT, NOT THE CALL. Each check re-reads the
    # element FROM THE DOCUMENT by its own id, in its own braces: witnesses
    # must not be tied together by order (the certificate excises them one
    # at a time with a mutation test), and nested braces keep same-named
    # locals from colliding (CS0128).
    ar_cs = "Autodesk.Revit.DB.Structure.AreaReinforcement"
    checks: list[WitnessCheck] = [
        # TOPOLOGY WITHOUT A TOLERANCE: the element itself names its host.
        # There is no number here and cannot be — this is equality of id,
        # not measurement. Comparing via Id.ToString() is the only idiom
        # legal on all six versions (.Value — 2024+, .IntegerValue —
        # through 2025).
        WitnessCheck(
            obligation_key="host",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdh_{s} = doc.GetElement(__el_{s}.Id) as {ar_cs};\n"
                f"      if (__rdh_{s} == null)\n"
                f"          __post.Add({_cs(oid + ': созданный элемент не читается из документа как AreaReinforcement (topology)')});\n"
                f"      else if (__rdh_{s}.GetHostId() == null\n"
                f"               || __rdh_{s}.GetHostId() == ElementId.InvalidElementId\n"
                f"               || __rdh_{s}.GetHostId().ToString() != __hh_{s}.Id.ToString())\n"
                f"          __post.Add({_cs(oid + ': GetHostId != носителя (topology)')}); }}\n"),
            message="GetHostId != носителя (topology)", style="else_block"),
        WitnessCheck(
            obligation_key="element_type",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdt_{s} = doc.GetElement(__el_{s}.Id) as {ar_cs};\n"
                f"      if (__rdt_{s} == null || __rdt_{s}.GetTypeId() == null\n"
                f"          || __rdt_{s}.GetTypeId().ToString() != __tyid_{s}.ToString())\n"
                f"          __post.Add({_cs(oid + ': тип армирования != запрошенного (semantic)')}); }}\n"),
            message="тип армирования != запрошенного (semantic)", style="guard"),
        # A CONDITIONAL WITNESS, AND THE CONDITION IS READ FROM THE
        # DOCUMENT. Autodesk writes in plain text: «The RebarInSystem
        # elements are only created if ReinforcementSettings.HostStructuralRebar
        # is set to true. If that setting is false, this function returns
        # an empty array». An unconditional "non-empty" would reject
        # CORRECTLY built reinforcement in every document with the setting
        # turned off — i.e. it would be a check that rejects working code.
        # With the setting turned on, zero bars is a real failure (the
        # layout spacing is larger than the slab), and from the outside it
        # is indistinguishable from success; the setting's value ALWAYS
        # travels into the receipt, so a zero is never silent.
        WitnessCheck(
            obligation_key="bars_laid",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdb_{s} = doc.GetElement(__el_{s}.Id) as {ar_cs};\n"
                f"      var __rsb_{s} = Autodesk.Revit.DB.Structure."
                f"ReinforcementSettings.GetReinforcementSettings(doc);\n"
                f"      if (__rsb_{s} != null && __rsb_{s}.HostStructuralRebar\n"
                f"          && (__rdb_{s} == null || __rdb_{s}.GetRebarInSystemIds() == null\n"
                f"              || __rdb_{s}.GetRebarInSystemIds().Count == 0))\n"
                f"          __post.Add({_cs(oid + ': армирование не положило ни одного стержня при включённой HostStructuralRebar (semantic)')}); }}\n"),
            message=("армирование не положило ни одного стержня при включённой "
                     "HostStructuralRebar (semantic)"),
            style="guard"),
        # THE BAR TYPE IS ASSIGNED BY US — so we are accountable for it.
        # This is exactly the distinction from CLAUDE.md: «either the
        # emitter sets the value (then the witness is honest), or Revit
        # chooses it (then the witness demands something nobody asked
        # for)». Here it is the former. It is read off the BAR ITSELF
        # (`RebarInSystem.GetTypeId`), because
        # BuiltInParameter.REBAR_BAR_TYPE does not exist on any version.
        WitnessCheck(
            obligation_key="bar_type",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdr_{s} = doc.GetElement(__el_{s}.Id) as {ar_cs};\n"
                f"      var __rss_{s} = Autodesk.Revit.DB.Structure."
                f"ReinforcementSettings.GetReinforcementSettings(doc);\n"
                f"      if (__rdr_{s} != null && __rss_{s} != null && __rss_{s}.HostStructuralRebar)\n"
                f"      {{\n"
                f"          var __rbi_{s} = __rdr_{s}.GetRebarInSystemIds();\n"
                f"          if (__rbi_{s} != null)\n"
                f"          {{\n"
                f"              foreach (ElementId __rid_{s} in __rbi_{s})\n"
                f"              {{\n"
                f"                  var __rbe_{s} = doc.GetElement(__rid_{s}) as "
                f"Autodesk.Revit.DB.Structure.RebarInSystem;\n"
                f"                  if (__rbe_{s} == null) continue;\n"
                f"                  if (__rbe_{s}.GetTypeId() == null\n"
                f"                      || __rbe_{s}.GetTypeId().ToString() != __btid_{s}.ToString())\n"
                f"                  {{\n"
                f"                      __post.Add({_cs(oid + ': тип стержня != запрошенного (semantic)')});\n"
                f"                      break;\n"
                f"                  }}\n"
                f"              }}\n"
                f"          }}\n"
                f"      }} }}\n"),
            message="тип стержня != запрошенного (semantic)", style="else_block"),
    ]

    # THE RECEIPT CARRIES WHAT THE WITNESS DOES NOT DEMAND, first and
    # foremost THE SETTING ITSELF: without it, "zero bars" would read as a
    # breakage where it is in fact the document's normal state. The same
    # device by which create_beam shows the reference level Revit inferred.
    readback = _readback_block(s, oid, stamp, identity_version=ver).replace(
        f"    __results[{_cs(oid)}] = __rb;",
        f"    try {{ var __rba_{s} = doc.GetElement(__el_{s}.Id) as {ar_cs};\n"
        f"        var __rbs_{s} = Autodesk.Revit.DB.Structure."
        f"ReinforcementSettings.GetReinforcementSettings(doc);\n"
        f"        if (__rbs_{s} != null) __rb[\"host_structural_rebar\"] = "
        f"__rbs_{s}.HostStructuralRebar;\n"
        f"        if (__rba_{s} != null) {{\n"
        f"            var __rbn_{s} = __rba_{s}.GetRebarInSystemIds();\n"
        f"            if (__rbn_{s} != null) __rb[\"bar_count\"] = __rbn_{s}.Count;\n"
        f"            var __rbc_{s} = __rba_{s}.GetBoundaryCurveIds();\n"
        f"            if (__rbc_{s} != null) __rb[\"boundary_curve_count\"] = __rbc_{s}.Count;\n"
        f"            var __rbd_{s} = __rba_{s}.Direction;\n"
        f"            if (__rbd_{s} != null) __rb[\"direction\"] = new double[] {{\n"
        f"                Math.Round(__rbd_{s}.X, 6), Math.Round(__rbd_{s}.Y, 6),\n"
        f"                Math.Round(__rbd_{s}.Z, 6) }};\n"
        f"            var __rbt_{s} = doc.GetElement(__rba_{s}.GetTypeId());\n"
        f"            if (__rbt_{s} != null) __rb[\"type_name\"] = __rbt_{s}.Name;\n"
        f"        }}\n"
        f"        var __rbb_{s} = doc.GetElement(__btid_{s});\n"
        f"        if (__rbb_{s} != null) __rb[\"bar_type_name\"] = __rbb_{s}.Name;\n"
        f"    }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;", 1)
    return decl, create, checks, readback


#: WHAT THIS SPOKE EMITS IS DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: The "op -> body" mapping used to live in the hand-written
#: `authoring._EMITTERS`, with the body here, and a thin wrapper in the hub
#: linked the two (41 of them across 19 satellites). Two records of one
#: fact in different files is a named defect of this tree; now there is
#: ONE record, and the hub ASKS it.
EMITTERS = {
    "create_area_reinforcement": emit_area_reinforcement,
    "create_beam": emit_beam,
    "create_beam_system": emit_beam_system,
    "create_foundation": emit_foundation,
    "create_truss": emit_truss,
    "create_wall_foundation": emit_wall_foundation,
}
