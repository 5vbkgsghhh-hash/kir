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

from kukai.ir.authoring import (
    _gid, _eid, _cs, _safe, _level_expr, _pt3,
    _stamp_block, _readback_block, _symbol_res,
    _loop_pts, EMIT_UNSUPPORTED, IN_EMIT_DEFAULT,
    # Wave A2: struct_emit consumes the PUBLIC witness-model helpers (the
    # long-flagged private-helper import shrinks to render-free utilities).
    endpoint_witness, level_chain_witness, bbox_extents_witness,
)
from kukai.ir.emit_model import WitnessCheck, tolerance
from kukai.ir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kukai.ir.diag import (
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

#: `create_beam_system.profile` пришёл с дырками. Отказ, а не тихое
#: отбрасывание: `BeamSystem.Create` принимает профиль ОДНИМ плоским
#: `IList<Curve>` — второго кольца в подписи нет ни на одной из шести версий
#: (замер компиляцией 09.08). Построить внешний контур и промолчать про
#: вырез значило бы вернуть `ok:true` за геометрию, которой автор не просил, —
#: запрещённое состояние. Ремонт называется прямо: вырез в балочной системе
#: делается отдельной операцией, а не полем профиля.

#: `create_beam_system.direction_edge` указывает не на прямое ребро (или
#: вовсе за пределы профиля). ОДИН код на оба случая сознательно: ремонт у
#: них ОДИН И ТОТ ЖЕ — «назови другой номер», и отказ везёт список номеров
#: прямых рёбер этого самого профиля. Autodesk требует, чтобы кривая
#: направления была `Line`; проверка стоит на компиляции, потому что после
#: опускания CONTOUR прямизна каждого ребра известна в питоне (bulge==0), а
#: тот же промах в рантайме прилетел бы `ArgumentException` изнутри
#: транзакции.
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
        endpoint_witness(f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
                         tolerance("create_beam", "endpoint_mm"), True),
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
            f"__el_{s}", oid, min(xs), max(xs), min(ys), max(ys),
            tolerance("create_foundation", "bbox_mm"), key="footprint"),
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


# ── create_wall_foundation ───────────────────────────────────────────────────

def emit_wall_foundation(op: dict, ver: str, stamp: str,
                         isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Ленточный фундамент под стеной.

    WallFoundation.Create(Document, ElementId typeId, ElementId wallId) —
    ОДНА подпись на все шесть версий, проверено компиляцией 09.08 на :52412
    (2021-2026, 6/6 OK). Оси версий у этого опа нет, и это ЗАМЕР, а не
    предположение: тело ниже одинаково для всех шести, а единственное место,
    где версии вообще расходятся, — литерал ElementId, и его печатает общий
    `_eid` (2021-2023 знают только 32-битный конструктор).

    ПРЕДПОЛЁТНОЙ ПРОВЕРКИ НЕТ В API. `WallFoundation.WallAllowsWallFoundation`
    не существует ни на одной версии (CS0117 6/6) — это метод СОВСЕМ другого
    класса, `WallSweep.WallAllowsWallSweep`. Поэтому «а можно ли на эту
    стену» выясняется по факту: `as Wall` даёт null на не-стене, а
    Create возвращает null на негодной стене. Оба — типизированные отказы
    через refuse_stmt, ни одного молчаливого пропуска.
    """
    oid = op["id"]
    s = _safe(oid)
    wall_sel = op["wall"]

    # ХОСТ И ТИП ОБЪЯВЛЯЮТСЯ ВО ВНЕШНЕЙ ОБЛАСТИ. Не стиль: при
    # isolation="per_op" блок создания заворачивается в собственный try, и
    # переменная, объявленная внутри него, свидетелю не видна (CS0103 —
    # ровно тем и падал первый _emit_railing_hosted на живых воротах).
    # Свидетель читает ОБЕ: id стены и id запрошенного типа.
    if wall_sel.get("by") == "ref":
        # Ссылка внутри программы: create_wall этой же программы. Плановая
        # стадия уже проверила и существование цели (KIR-L003), и её
        # типизированный род (KIR-L004: ref обязан вести на результат рода
        # WALL), а per_op-обвязка добавляет ворота «опорный оп отказан».
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
    # Тип разрешается ЧЕРЕЗ ДОКУМЕНТ и проверяется на самом деле полученным
    # классом: у пути по умолчанию GetDefaultElementTypeId возвращает
    # InvalidElementId, когда типа в документе нет вовсе, и тогда GetElement
    # даёт null — то есть одна проверка закрывает обе ветви честно.
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

    # СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ, А НЕ ВЫЗОВ. Элемент перечитывается ИЗ
    # ДОКУМЕНТА по своему id (не берётся возвращённый объект на веру), и
    # обе проверки спрашивают то, что вычислил REVIT: чьим фундаментом
    # элемент себя считает и какого он типа. Ни одна из них не может быть
    # удовлетворена тем, что эмиттер что-то присвоил.
    #
    # Равенство id — ТОЧНОЕ, допуск здесь не нужен и был бы враньём: это
    # топология, а не измерение. Сравнение через Id.ToString() — единственная
    # идиома, законная на всех шести версиях (.Value — 2024+, .IntegerValue —
    # по 2025), тот же приём, что у HostId в arch_emit.
    # КАЖДАЯ ПРОВЕРКА ПЕРЕЧИТЫВАЕТ САМА, в собственных скобках. Раньше вторая
    # читала переменную, объявленную первой, — и это связывало две проверки
    # порядком: удали первую (а сертификат делает ровно это, вырезая свидетеля
    # мутационным тестом), и вторая осталась бы без объявления. Лишний
    # GetElement дешевле связанности в слое честности, а вложенные скобки не
    # дают одноимённым локалям соседей столкнуться (CS0128).
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
    return decl, create, checks, _readback_block(s, oid, stamp)


# ── create_beam_system ───────────────────────────────────────────────────────

def emit_beam_system(op: dict, ver: str, stamp: str,
                     isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Балочная система по замкнутому эскизу.

    ЗАМЕР API (компиляция на :52412 против настоящих сборок 2021-2026, 09.08):

      BeamSystem.Create(Document, IList<Curve>, Level, XYZ, bool)      → 6/6
      BeamSystem.Create(Document, IList<Curve>, Level, int, bool)      → 6/6
      BeamSystem.Create(Document, IList<Curve>, SketchPlane, XYZ, bool)→ 6/6
      BeamSystem.Create(Document, IList<Curve>, SketchPlane, int)      → 6/6
      BeamSystem.Profile   — это CurveArray                            → 6/6
      (`IList<Curve> x = bs.Profile;` — CS0266 на всех шести)
      BeamSystem.GetBeamIds().Count / .Direction / .Elevation / .Level → 6/6
      BeamSystem.BeamType  — ЧИТАЕТСЯ И ПИШЕТСЯ (FamilySymbol)         → 6/6
      ElementTypeGroup.BeamSystemType                                  → 6/6
      BuiltInParameter.BEAM_SYSTEM_LEVEL_PARAM                → 0/6 CS0117
      BuiltInParameter.BEAM_SYSTEM_ELEVATION_PARAM            → 0/6 CS0117
      ElementTypeGroup.StructuralFramingType                  → 0/6 CS0117

    Последние три строки — не педантизм: они закрывают три соблазна разом.
    Уровень читается СВОЙСТВОМ `bs.Level`, а не цепочкой BIP (её у балочной
    системы нет вовсе), отметка — свойством `bs.Elevation`, а «тип балки по
    умолчанию» спросить у документа нельзя, поэтому символ грунтуется пулом,
    как у create_beam.

    ВЫБРАНА ПЕРЕГРУЗКА С НОМЕРОМ РЕБРА, А НЕ С ВЕКТОРОМ, и это решение об
    ЧЕСТНОСТИ, а не о вкусе. У вектора нет проверяемого свидетеля: Revit
    отдаёт `Direction` уже нормализованным и, возможно, со своим знаком, а
    сверять два единичных вектора можно только через УГЛОВОЙ допуск, которого
    в этом доме никто не мерил. У номера предусловие ровно одно («кривая
    направления обязана быть Line»), и оно проверяемо ДО транзакции — рёбра
    уже опущены, прямизна каждого известна.

    `is3d` НЕ ВЫНЕСЕН В РЕЕСТР и всегда `false`. Трёхмерная балочная система
    следует за наклонной поверхностью, и ни одного входа, которым автор мог
    бы эту поверхность назвать, у операции нет; ручка, чьё действие нечем
    проверить, — это ручка, которой не должно быть.
    """
    from kukai.ir import contour as C

    oid = op["id"]
    s = _safe(oid)
    region = op["__region__"]

    # ДЫРКИ ОТКАЗЫВАЮТСЯ, А НЕ ОТБРАСЫВАЮТСЯ. `region` даёт бесплатно все
    # законы эскиза (адреса от осей, дуги, нулевые рёбра, самопересечение,
    # вырожденная площадь), и ровно одна его степень свободы вызову
    # недоступна — второе кольцо. Молчаливое отбрасывание построило бы
    # СПЛОШНУЮ систему там, где просили с вырезом.
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
        # УМОЛЧАНИЕ НАЗВАНО, А НЕ ПОДСТАВЛЕНО МОЛЧА. Ноль — не наша выдумка:
        # это документированное значение самого API («'0' means the default
        # direction — to use the first curve in profile»). Но если первое
        # ребро дуговое, брать его нельзя, и тогда берётся ПЕРВОЕ ПРЯМОЕ —
        # выбор компилятора, поэтому он уезжает в квитанцию (`direction_edge`
        # в readback), как того требует закон названного умолчания.
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

    # ХОСТЯЩИЕ ПЕРЕМЕННЫЕ — ВО ВНЕШНЕЙ ОБЛАСТИ. При isolation="per_op" блок
    # создания заворачивается в собственный try, и объявленное внутри него
    # свидетелю не видно (CS0103). Свидетелю нужен id запрошенного символа.
    decl = (f"BeamSystem __el_{s} = null;\n"
            f"ElementId __syid_{s} = null;")

    # ЛОВУШКА ТИПА РАЗМЕЩЕНИЯ НАСЛЕДУЕТСЯ, И ЗАКРЫТА ОНА ЗДЕСЬ ТОЖЕ. Пул
    # `beam_types` уже фильтрует по FamilyPlacementType (open_model.py), но
    # ветка `by: element_id` пула НЕ КАСАЕТСЯ вовсе — ground.py пропускает
    # сырой id насквозь, а проверяет его только рантайм. Значит фильтр пула
    # закрывает лишь половину входов, и вторую половину обязан закрыть
    # эмиттер: точечное семейство, назначенное `BeamType`, даёт систему без
    # единой балки (или исключение изнутри транзакции) вместо названного
    # отказа.
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
        # ПРОФИЛЬ КЛАДЁТСЯ НА ОТМЕТКУ СВОЕГО УРОВНЯ, а не на Z=0. Перегрузка
        # с `Level` берёт рабочую плоскость у уровня; кривые, оставленные на
        # нуле под уровнем на +3.000, либо отвергаются, либо дают систему с
        # отметкой -3000 — то есть МОЛЧА не на том этаже. Тот же приём и та
        # же причина, что у room_emit (`double __z = MM(__lv.Elevation)`).
        f"double __z_{s} = MM(__lv_{s}.Elevation);\n"
        f"{profile_cs}\n"
        # ИСКЛЮЧЕНИЕ ЛОВИТСЯ И ПЕРЕВОДИТСЯ В ОТКАЗ. Autodesk перечисляет для
        # этой перегрузки четыре разных ArgumentException (спиральная кривая
        # в профиле, у уровня нет плана этажа, план не годится, плоскость
        # эскиза с уровня не берётся) — ни один из них не предсказуем из
        # снапшота, и все четыре обязаны стать названным отказом, а не
        # «внутренней ошибкой».
        f"try {{ __el_{s} = BeamSystem.Create(doc, __prof_{s}, __lv_{s}, "
        f"{idx}, false); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid, f'"BeamSystem.Create: " + __ex_{s}.Message', isolation)
        + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("BeamSystem.Create вернул null"), isolation)
        + " }\n"
        # ТИП БАЛКИ НАЗНАЧАЕТСЯ НАМИ — значит и спрашивается с нас. Это ровно
        # инженерное различие: «либо значение ставит эмиттер (тогда
        # свидетель честен), либо его выбирает Revit (тогда свидетель требует
        # того, чего никто не просил)». Здесь — первое.
        f"try {{ __el_{s}.BeamType = __sy_{s}; }}\n"
        f"catch (Exception __exb_{s}) {{ "
        + refuse_stmt(oid, f'"BeamSystem.BeamType: " + __exb_{s}.Message', isolation)
        + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    # ГАБАРИТ СЧИТАЕТСЯ ПО ВЕРШИНАМ С ОБЕИХ СТОРОН. C# видит у прочитанного
    # профиля ровно концы кривых, поэтому и питоновская сторона обязана
    # считать по вершинам (`edges_vertex_bbox`), а не по `edges_bbox` с
    # кардинальными экстремумами дуг: иначе правильная система обвинялась бы
    # ровно на стрелку дуги. То, что остаётся непроверенным, названо в `post`.
    vx0, vy0, vx1, vy1 = C.edges_vertex_bbox(edges)
    btol = tolerance("create_beam_system", "bbox_mm")
    checks: list[WitnessCheck] = [
        # КАЖДАЯ ПРОВЕРКА ПЕРЕЧИТЫВАЕТ ЭЛЕМЕНТ САМА, в собственных скобках:
        # свидетели не должны быть связаны порядком (сертификат вырезает их
        # по одному мутационным тестом), а вложенные скобки не дают
        # одноимённым локалям столкнуться (CS0128).
        WitnessCheck(
            obligation_key="profile_bbox",
            reader_cs="",
            verdict_cs=(
                f"    {{ var __rdp_{s} = doc.GetElement(__el_{s}.Id) as BeamSystem;\n"
                f"      CurveArray __pr_{s} = __rdp_{s} == null ? null : __rdp_{s}.Profile;\n"
                f"      if (__rdp_{s} == null || __pr_{s} == null || __pr_{s}.Size == 0)\n"
                f"          __post.Add({_cs(oid + ': профиль балочной системы не читается обратно (geometry)')});\n"
                f"      else {{\n"
                # ПО ОДНОМУ ОБЪЯВЛЕНИЮ В СТРОКЕ, и это не стиль: контракт
                # области видимости (test_emitter_scope_contract) читает
                # объявления регулярным выражением и видит в `double a = 1,
                # b = 2;` только `a`. Вторая переменная стала бы для него
                # «нигде не объявленной» — то есть прибор, молчащий на части
                # диапазона. Держим форму, которую он читает целиком.
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
        # ЧИСЛА БАЛОК ЗДЕСЬ НЕТ И БЫТЬ НЕ МОЖЕТ. Шаг раскладки выбирает
        # LayoutRule, которого ни один аргумент `Create` не задаёт: автор
        # НИКАКОГО количества не называл, и потребовать его значило бы
        # проверять выдуманное. Проверяется РЕЗУЛЬТАТ, который автор всё же
        # заказал самим фактом операции: система обязана была положить хоть
        # что-то. Ноль балок — настоящий, наблюдавшийся исход (профиль мельче
        # шага раскладки), и снаружи он неотличим от успеха.
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
        # УРОВЕНЬ ЧИТАЕТСЯ СВОЙСТВОМ, А НЕ ЦЕПОЧКОЙ BIP: у балочной системы
        # BEAM_SYSTEM_LEVEL_PARAM не существует (0/6), зато есть `Level`.
        # Сравнение точное — это равенство id, а не измерение. И в отличие от
        # create_beam уровень здесь НАШ: он аргумент вызова, а не вывод Revit
        # из отметки кривой.
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

    # КВИТАНЦИЯ ВЕЗЁТ ТО, ЧЕГО СВИДЕТЕЛЬ НЕ ТРЕБУЕТ. Направление, отметку,
    # правило раскладки и ЧИСЛО ПОЛОЖЕННЫХ БАЛОК автор увидит — просто не в
    # виде требования. Ровно тот же приём, которым create_beam показывает
    # выведенный Revit опорный уровень.
    readback = _readback_block(s, oid, stamp).replace(
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
    """Ферма по базовому отрезку на плоскости уровня.

    ЗАМЕР API (компиляция на :52412 против настоящих сборок 2021-2026, 09.08):

      Truss.Create(Document, ElementId typeId, ElementId sketchPlaneId, Curve)
                                                                      → 6/6
      Truss.Curves — CurveArray, Truss.Members — ICollection<ElementId> → 6/6
      (`.Members.Size` — CS1061 на всех шести: это НЕ ElementIdSet)
      Truss.TrussType / GetTypeId / Location as LocationCurve          → 6/6
      TrussType — наследник FamilySymbol (IsActive/Activate)           → 6/6
      SketchPlane.Create(Document, ElementId уровня)                   → 6/6
      BuiltInParameter.TRUSS_ELEMENT_REFERENCE_LEVEL_PARAM             → 6/6
      ElementTypeGroup.TrussType                              → 0/6 CS0117

    Подпись ОДНА на все шесть версий — оси версий у операции нет.

    ПЛОСКОСТЬ ЭСКИЗА — ПЛОСКОСТЬ УРОВНЯ. Autodesk требует, чтобы базовая
    кривая лежала В плоскости эскиза и не была вертикальной. Золотой образец
    SDK (`Samples/Truss/CS/TrussForm.cs`) строит плоскость руками из
    `Plane.CreateByOriginAndBasis` в НУЛЕ и кладёт кривую на Z=0 — то есть на
    отметку «первого этажа» и никуда больше. Здесь взята перегрузка
    `SketchPlane.Create(doc, levelId)` (та же, что у create_room_separator,
    проверена живьём), а кривая кладётся на отметку этого уровня: тогда оба
    предусловия выполнены ПО ПОСТРОЕНИЮ, а не по удаче — «в плоскости»
    следует из одинакового Z, «не вертикальна» из ненулевой длины в плане,
    которую reject_zero_length уже проверил на валидации.

    ТИПА ПО УМОЛЧАНИЮ У ФЕРМЫ НЕТ. `ElementTypeGroup.TrussType` не
    компилируется ни на одной из шести версий — спросить документ «твоя ферма
    по умолчанию» нельзя ПО ПОСТРОЕНИЮ, ровно как у двери, окна и ограждения.
    Поэтому неразрешённый на стадии ground тип — типизированный отказ здесь,
    а не подстановка.
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

    # ВО ВНЕШНЕЙ ОБЛАСТИ — ровно то, что перечитывает свидетель: отметка
    # плоскости уровня и id запрошенного типа (при per_op блок создания живёт
    # в собственном try, и объявленное там свидетелю невидимо, CS0103).
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
        # TrussType — наследник FamilySymbol (замер), а неактивированный
        # типоразмер семейства — известная причина отказа размещения. Тот же
        # приём, что в общем `_symbol_res`.
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
        # Autodesk объявляет у Truss.Create И ArgumentException (кривая не
        # годится в базу фермы, id не тот класс), И InvalidOperationException
        # («функция доступна только в Revit Structure/Architecture» и «не
        # удалось создать ферму»). Последнее — про РЕДАКЦИЮ РЕВИТА у
        # пользователя, и вылететь наружу «внутренней ошибкой» оно не должно
        # ни в коем случае: это названный отказ с настоящей причиной.
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
        # ПЛАН — ОБЩИМ СВИДЕТЕЛЕМ. `endpoint_witness` сам разбирается с
        # порядком концов (Revit вправе отдать кривую в обратную сторону), и
        # это ровно та же сверка, что у create_beam: авторский отрезок против
        # LocationCurve несущего элемента. Что у фермы LocationCurve и есть
        # базовая кривая — не догадка: золотой образец SDK читает
        # `(m_truss.Location as LocationCurve).Curve as Line` именно как
        # начало и конец фермы.
        endpoint_witness(f"__el_{s}", oid, [x0, y0], [x1, y1], etol, False),
        # ВЫСОТА — ОТДЕЛЬНОЙ ПРОВЕРКОЙ, И ОЖИДАЕМОЕ ЧИСЛО СЧИТАЕТСЯ В
        # РАНТАЙМЕ. Общий свидетель сравнивает Z с литералом, а здесь литерала
        # нет и не должно быть: отметка плоскости — это отметка уровня,
        # известная только в модели. Обещание при этом НАШЕ (мы сами положили
        # кривую на __z), поэтому спрашивать его честно — в отличие от
        # опорного уровня ниже, который выводит Revit.
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
        # ЧТО ВНУТРИ ФЕРМЫ — РЕШАЕТ СЕМЕЙСТВО, А НЕ МЫ. Ни числа поясов, ни
        # числа раскосов, ни шага панелей операция не называет, поэтому
        # проверяется единственное, что заказано самим фактом постройки:
        # ферма обязана СОСТОЯТЬСЯ как сборка. Пустой `Members` — это
        # оболочка без стержней, снаружи неотличимая от успеха.
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
        # ОПОРНЫЙ УРОВЕНЬ: ПРОВЕРЯЕТСЯ СУЩЕСТВОВАНИЕ, А НЕ РАВЕНСТВО — и это
        # ПРЯМОЙ УРОК create_beam, оплаченный живым замером 27.07. Там
        # постусловие «опорный уровень == переданному» откатывало ПРАВИЛЬНО
        # построенные балки, потому что Revit выводит привязку сам. У фермы в
        # вызове уровня нет вовсе (есть плоскость эскиза), то есть требовать
        # равенства было бы ещё смелее. Какой уровень выбран — везёт квитанция.
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

    readback = _readback_block(s, oid, stamp).replace(
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

#: ОБА ОТКАЗА ЭТОЙ ОПЕРАЦИИ — РАНТАЙМНЫЕ, И КОДА У НИХ НЕТ НАМЕРЕННО.
#: Первая версия этого модуля объявила рядом две константы `KIR-E010`/
#: `KIR-E011` под «носитель не горизонтален» и «носитель не может нести
#: армирование» — и ни одна из них не была бы НИ РАЗУ упомянута в коде:
#: обе проверки живут в эмитированном C# и едут через `refuse_stmt`, который
#: кода не принимает вовсе. Имя, выглядящее как работающий механизм и не
#: вызываемое ниоткуда, — ровно то тёмное место, которое этот пакет ловит у
#: себя приборами достижимости; поэтому здесь стоит объяснение, а не пара
#: мёртвых констант. Сами причины отказов записаны у своих `if` в
#: :func:`emit_area_reinforcement`.


def emit_area_reinforcement(op: dict, ver: str, stamp: str,
                            isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Армирование по области — по ГРАНИЦЕ НОСИТЕЛЯ.

    ЗАМЕР API (компиляция на :52412 против настоящих сборок 2021-2026, 10.08 —
    арбитр компилятор, а не XML):

      AreaReinforcement.Create(Document, Element, XYZ, ElementId×3)     → 6/6
      AreaReinforcement.GetHostId / .GetTypeId / .Direction             → 6/6
      AreaReinforcement.GetRebarInSystemIds / .GetBoundaryCurveIds      → 6/6
      RebarHostData.IsValidHost(Element)                                → 6/6
      ReinforcementSettings.GetReinforcementSettings(doc)
          .HostStructuralRebar                                          → 6/6
      RebarInSystem.GetTypeId()                                         → 6/6
      ElementTypeGroup.AreaReinforcementType                            → 6/6

      AreaReinforcement.GetNumberOfLines()   → 0/6 (нет на 2021; на 2022+
                                               требует AreaReinforcementLayer-
                                               Type, которого на 2021 нет)
      AreaReinforcement.GetLayerDirection(i) → 5/6 (нет на 2021)
      BuiltInParameter.REBAR_BAR_TYPE        → 0/6  CS0117, НЕ СУЩЕСТВУЕТ

    ПОСЛОЙНОГО СВИДЕТЕЛЯ ЗДЕСЬ НЕТ, И ЭТО ЗАМЕР. Весь послойный слой API
    (число линий слоя, его направление, его активность) на 2021 отсутствует, а
    на 2022+ ключуется перечислением, которого на 2021 нет вовсе. Свидетель,
    работающий на пяти версиях из шести, — это «прибор на часть диапазона»,
    который в этом доме опаснее отсутствующего.

    ДОПУСКОВ У ЭТОГО ТЕЛА НЕТ НИ ОДНОГО. Все четыре проверки — равенства id и
    счётчик, то есть топология и семантика. Геометрия не сторожится намеренно:
    границу считает Revit по самому носителю (авторской величины в операции
    нет ни одной), а в 38 сохранённых разборах с переписью НОЛЬ элементов
    OST_AreaRein/OST_PathRein/OST_Rebar/OST_FabricAreas (замер 10.08), то есть
    вывести число неоткуда. См. шапку ops_struct.py.
    """
    oid = op["id"]
    s = _safe(oid)
    host_sel = op["host"]

    # ────────── ТИПЫ ──────────
    # Все три id объявляются во ВНЕШНЕЙ области: при isolation="per_op" блок
    # создания заворачивается в собственный try, и объявленное внутри него
    # свидетелю не видно (CS0103). Свидетель читает и тип системы, и тип
    # стержня.
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
    # Одна проверка закрывает ОБЕ ветви честно: у документного пути
    # GetDefaultElementTypeId возвращает InvalidElementId, когда типа в
    # документе нет вовсе, и тогда GetElement даёт null.
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

    # ПРОПУЩЕННЫЙ КРЮК = БЕЗ КРЮКОВ, значением САМОГО API. `InvalidElementId`
    # здесь документирован Autodesk («it means to create a rebar with no
    # hooks»), то есть это не подстановка компилятора, а прямая запись того,
    # что сказал автор: он крюка не называл.
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

    # ────────── НОСИТЕЛЬ ──────────
    if host_sel.get("by") == "ref":
        # Ссылка внутрь программы: плановая стадия уже проверила и
        # существование цели (KIR-L003), и её род (KIR-L004), а per_op-обвязка
        # добавила ворота «опорный оп отказан».
        host_res = f"__hh_{s} = __el_{_safe(host_sel['value'])};\n"
    else:
        host_res = (
            f"__hh_{s} = doc.GetElement({_eid(host_sel['value'], ver, oid)});\n")
    host_res += (
        f"if (__hh_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('носитель армирования не найден (модель изменилась после grounding)'), isolation)} }}\n"
        # ГОРИЗОНТАЛЬНОСТЬ — ПЕРВЫМ, потому что её нарушение даёт МОЛЧА неверный
        # результат, а не исключение: у стены `Create` отработает, но плановое
        # направление Revit спроецирует в ЕЁ вертикальную плоскость. У стены
        # вдоль Y угол 0° вырождается в ноль (тогда ещё повезло — прилетит
        # исключение), а у стены под 45° проекция ненулевая и НЕ ТА, которую
        # имел в виду автор: арматура встанет не туда, и снаружи это
        # неотличимо от успеха. Ровно тот исход, ради запрета которого написан
        # весь пакет, поэтому проверка стоит ДО вызова и называет следующий ход.
        f"if (!(__hh_{s} is Floor)) {{ "
        f"{refuse_stmt(oid, _cs('носитель армирования по области должен быть перекрытием/плитой: у вертикального носителя главное направление лежит в ЕГО плоскости, и плановым углом direction_deg оно не задаётся — армирование стены этой операцией невыразимо'), isolation)} }}\n"
        # ПРЕДПОЛЁТНАЯ ПРОВЕРКА САМОГО API, а не наша выдумка. Её текст
        # называет ровно те две починки, которые называет и Autodesk.
        f"if (!Autodesk.Revit.DB.Structure.RebarHostData.IsValidHost(__hh_{s})) {{ "
        f"{refuse_stmt(oid, _cs('носитель не может нести армирование (RebarHostData.IsValidHost = false): сделай перекрытие несущим или смени его материал на бетон'), isolation)} }}\n")

    # ────────── НАПРАВЛЕНИЕ ──────────
    # ВСЯ ТРИГОНОМЕТРИЯ НА КОМПИЛЯЦИИ, как того требует закон CONTOUR: в C#
    # уезжают два литерала. Длина вектора равна единице по построению, значит
    # документированное «majorDirection has zero length» здесь недостижимо.
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
        # ИСКЛЮЧЕНИЕ ЛОВИТСЯ И ПЕРЕВОДИТСЯ В ОТКАЗ. Autodesk перечисляет для
        # этой перегрузки пять разных ArgumentException (носителя нет в
        # документе; носитель не годен; каждый из трёх id не того класса) —
        # ни один не предсказуем из снапшота целиком, и все обязаны стать
        # названным отказом, а не «внутренней ошибкой».
        f"try {{ __el_{s} = Autodesk.Revit.DB.Structure.AreaReinforcement.Create("
        f"doc, __hh_{s}, __dir_{s}, __tyid_{s}, __btid_{s}, __hkid_{s}); }}\n"
        f"catch (Exception __ex_{s}) {{ "
        + refuse_stmt(oid, f'"AreaReinforcement.Create: " + __ex_{s}.Message', isolation)
        + " }\n"
        f"if (__el_{s} == null) {{ "
        + refuse_stmt(oid, _cs("AreaReinforcement.Create вернул null"), isolation)
        + " }\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))

    # СВИДЕТЕЛЬ ЧИТАЕТ РЕЗУЛЬТАТ, А НЕ ВЫЗОВ. Каждая проверка перечитывает
    # элемент ИЗ ДОКУМЕНТА по своему id, в собственных скобках: свидетели не
    # должны быть связаны порядком (сертификат вырезает их по одному
    # мутационным тестом), а вложенные скобки не дают одноимённым локалям
    # столкнуться (CS0128).
    ar_cs = "Autodesk.Revit.DB.Structure.AreaReinforcement"
    checks: list[WitnessCheck] = [
        # ТОПОЛОГИЯ БЕЗ ДОПУСКА: элемент сам называет свой носитель. Никакого
        # числа здесь нет и быть не может — это равенство id, а не измерение.
        # Сравнение через Id.ToString() — единственная идиома, законная на всех
        # шести версиях (.Value — 2024+, .IntegerValue — по 2025).
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
        # УСЛОВНЫЙ СВИДЕТЕЛЬ, И УСЛОВИЕ ЧИТАЕТСЯ ИЗ ДОКУМЕНТА. Autodesk пишет
        # прямым текстом: «The RebarInSystem elements are only created if
        # ReinforcementSettings.HostStructuralRebar is set to true. If that
        # setting is false, this function returns an empty array». Безусловное
        # «непусто» отвергало бы ПРАВИЛЬНО построенное армирование в каждом
        # документе с выключенной настройкой — то есть было бы проверкой,
        # отвергающей исправную работу. Под включённой настройкой ноль
        # стержней — настоящий отказ (шаг раскладки крупнее плиты), и снаружи
        # он неотличим от успеха; значение настройки едет в квитанцию ВСЕГДА,
        # поэтому ноль никогда не бывает молчаливым.
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
        # ТИП СТЕРЖНЯ НАЗНАЧАЕМ МЫ — значит и спрашивается с нас. Это ровно
        # инженерное различие: «либо значение ставит эмиттер (тогда
        # свидетель честен), либо его выбирает Revit (тогда свидетель требует
        # того, чего никто не просил)». Здесь — первое. Читается у САМОГО
        # СТЕРЖНЯ (`RebarInSystem.GetTypeId`), потому что параметра
        # BuiltInParameter.REBAR_BAR_TYPE не существует ни на одной версии.
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

    # КВИТАНЦИЯ ВЕЗЁТ ТО, ЧЕГО СВИДЕТЕЛЬ НЕ ТРЕБУЕТ, и в первую очередь САМУ
    # НАСТРОЙКУ: без неё «стержней ноль» читалось бы как поломка там, где это
    # штатное состояние документа. Тот же приём, которым create_beam
    # показывает выведенный Revit опорный уровень.
    readback = _readback_block(s, oid, stamp).replace(
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
