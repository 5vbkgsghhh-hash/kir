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

from kukai.ir.authoring import (
    _gid, _eid, _cs, _safe, _level_expr, _pt3,
    _stamp_block, _readback_block, _symbol_res,
    _loop_pts, EMIT_UNSUPPORTED, IN_EMIT_DEFAULT,
    # Wave A2: struct_emit consumes the PUBLIC witness-model helpers (the
    # long-flagged private-helper import shrinks to render-free utilities).
    endpoint_witness, level_chain_witness, bbox_extents_witness,
)
from kukai.ir.emit_model import WitnessCheck
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.diag import Diagnostic, KirRefusal, PARSE_MISSING_FIELD

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
    # У БАЛКИ ОПОРНЫЙ УРОВЕНЬ ВЫВОДИТ REVIT, А НЕ МЫ. Замерено 27.07 живой
    # пробой: передан L_01 @ 0 мм, кривая положена на Z=3000 — Revit привязал
    # балку к L_01ДОО1_+2.500, ближайшему уровню снизу. Аргумент `level` у
    # NewFamilyInstance(Line, …, StructuralType.Beam) — контекст размещения,
    # а не обещание; INSTANCE_REFERENCE_LEVEL_PARAM следует за отметкой кривой.
    # Прежнее постусловие «reference level == resolved level» требовало того,
    # чего API не обещает, и откатывало ПРАВИЛЬНО построенную балку.
    # Заменено на то, что действительно инвариант: опорный уровень существует
    # (балка без уровня — реальный дефект), а КАКОЙ именно — читается в
    # свидетель. Положение балки при этом пришпилено полностью: оба конца
    # проверяются в 3D с допуском 5 мм.
    checks: list[WitnessCheck] = [
        endpoint_witness(f"__el_{s}", oid, op["p0_mm"], op["p1_mm"], 5.0, True),
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
    readback = _readback_block(s, oid, stamp).replace(
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
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="footprint",
            reader_cs=f"    var __loc = __el_{s}.Location as LocationPoint;\n",
            verdict_cs=(
                f"    if (__loc == null) __post.Add({_cs(oid + ': нет LocationPoint')});\n"
                f"    else if (Math.Abs(MM(__loc.Point.X) - {x}) > 5.0 || Math.Abs(MM(__loc.Point.Y) - {y}) > 5.0)\n"
                f"        __post.Add({_cs(oid + ': location mismatch (geometry)')});\n"),
            message="location mismatch (geometry)", style="else_block"),
        level_chain_witness(f"__el_{s}", oid, lv_idexpr),
        WitnessCheck(
            obligation_key="structural_type", reader_cs="",
            verdict_cs=(
                f"    if (__el_{s}.StructuralType != Autodesk.Revit.DB.Structure.StructuralType.Footing)\n"
                f"        __post.Add({_cs(oid + ': StructuralType != Footing (semantic)')});\n"),
            message="StructuralType != Footing (semantic)", style="guard"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp)


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
            f"__el_{s}", oid, min(xs), max(xs), min(ys), max(ys), 50.0,
            key="footprint"),
        WitnessCheck(
            obligation_key="structural_type",
            reader_cs=f"    var __sp = __el_{s}.get_Parameter(BuiltInParameter.FLOOR_PARAM_IS_STRUCTURAL);\n",
            verdict_cs=(
                f"    if (__sp == null || __sp.AsInteger() != 1)\n"
                f"        __post.Add({_cs(oid + ': структурный флаг не установлен (semantic)')});\n"),
            message="структурный флаг не установлен (semantic)", style="guard"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp)


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
