"""Shared, side-effect-free building blocks for authoring emitters.

The monolithic authoring orchestrator and the domain emitters both consume
this layer. Keeping these helpers below dispatch prevents an emitter from
importing its own orchestrator and makes their dependency direction explicit.
"""
from __future__ import annotations

from kukai.ir.diag import Diagnostic, KirRefusal
from kukai.ir.emit_model import WitnessCheck
from kukai.ir.emit_utils import (
    ELEMENT_ID_MAX,
    cs_element_id_literal,
    cs_identifier_fragment,
    cs_line_comment_fragment,
    cs_string_literal,
    refuse_stmt,
)
from kukai.ir.ground import IN_EMIT_DEFAULT


EMIT_ID_RANGE = "KIR-E002"  # grounded id unrepresentable for target Revit
EMIT_UNSUPPORTED = "KIR-E003"  # feature unsupported on target Revit


def _cs(s: str) -> str:
    return cs_string_literal(s)


def _safe(s: str) -> str:
    return cs_identifier_fragment(s)


def _eid(val: int, ver: str, op_id: str) -> str:
    """ElementId literal, version-aware (the gate-caught divergence)."""
    try:
        return cs_element_id_literal(val, ver)
    except ValueError:
        if not (isinstance(val, int) and not isinstance(val, bool)
                and 1 <= val <= ELEMENT_ID_MAX):
            message = (
                f"id {val} вне положительного 64-битного пространства "
                "ElementId")
        else:
            message = (
                f"id {val} вне 32-битного пространства ElementId Revit {ver}")
        raise KirRefusal([Diagnostic(
            code=EMIT_ID_RANGE, op_id=op_id, got=val,
            message_ru=message)])


def _gid(op: dict, param: str) -> dict:
    return op[param]["__grounded__"]


def _level_expr(op: dict, s: str, ver: str, oid: str,
                isolation: str = "atomic") -> tuple[str, str]:
    """Return level-resolution C# and its id expression.

    The runtime guard deliberately distinguishes a vanished id from an id
    resolving to the wrong class. Both produce null after an as-Level cast,
    but only the former is evidence of model drift. The latter can also be a
    caller-supplied element id of the wrong kind, so diagnostics state the
    observed fact without inventing a cause.
    """
    lv = _gid(op, "level")
    if lv.get("via") == "ref":
        rv = "__el_" + _safe(lv["ref"])
        return (f"Level __lv_{s} = {rv};", f"{rv}.Id.ToString()")
    raw = f"__lv_raw_{s}"
    vanished = _cs("уровень не найден (модель изменилась после grounding)")
    wrong_type = _cs("id уровня резолвится не в Level, а в ")
    tail = _cs(" — причина (дрейф модели или неверный id) не определена рантаймом")
    msg_expr = (f"({raw} == null ? {vanished} : "
                f"{wrong_type} + __ClassName({raw}) + {tail})")
    res = (f"Element {raw} = doc.GetElement({_eid(lv['id'], ver, oid)});\n"
           f"Level __lv_{s} = {raw} as Level;\n"
           f"if (__lv_{s} == null) {{ {refuse_stmt(oid, msg_expr, isolation)} }}")
    return res, _cs(str(lv["id"]))


def _stamp_block(el_var: str, stamp: str) -> str:
    if not stamp.startswith("kir:a5:"):
        # Public/chat emission remains byte-compatible. Only A5 treats this
        # value as an authoritative ownership receipt for reconciliation.
        return (f'try {{ Parameter __cm = {el_var}.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); '
                f'if (__cm != null && !__cm.IsReadOnly) __cm.Set({_cs(stamp)}); }} catch {{ }}')
    return (
        f'try {{ Parameter __cm = {el_var}.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS); '
        f'if (__cm == null) throw new InvalidOperationException("A5 stamp parameter missing"); '
        f'if (__cm.IsReadOnly) throw new InvalidOperationException("A5 stamp parameter is read-only"); '
        f'if (!__cm.Set({_cs(stamp)}) || __cm.AsString() != {_cs(stamp)}) '
        f'throw new InvalidOperationException("A5 stamp readback mismatch"); }} '
        f'catch (Exception __stampEx) {{ throw new InvalidOperationException('
        f'"A5 stamp write failed: " + __stampEx.Message, __stampEx); }}')


def _stamp_readback(el_var: str, rb_var: str = "__rb",
                    type_level: bool = False) -> str:
    """Read the stamp from Revit; never echo the attempted value."""
    bip = ("ALL_MODEL_TYPE_COMMENTS" if type_level
           else "ALL_MODEL_INSTANCE_COMMENTS")
    return (f"    try {{ var __stampParam = {el_var}.get_Parameter(BuiltInParameter.{bip}); "
            f"if (__stampParam != null) {rb_var}[\"stamp\"] = __stampParam.AsString(); }} catch {{ }}\n")


def _pt3(pt: list) -> tuple:
    return (pt[0], pt[1], pt[2] if len(pt) > 2 else 0)


def _endpoint_check(el_var: str, oid: str, p0, p1, tol: float,
                    three_d: bool) -> str:
    x0, y0, z0 = _pt3(p0)
    x1, y1, z1 = _pt3(p1)
    orient_z = (f' + Math.Pow(MM(__a.Z) - {z0}, 2)' if three_d else '')
    orient_z_b = (f' + Math.Pow(MM(__b.Z) - {z0}, 2)' if three_d else '')
    zc = (f' || Math.Abs(MM(__e0.Z) - {z0}) > {tol} || Math.Abs(MM(__e1.Z) - {z1}) > {tol}'
          if three_d else "")
    return (
        f"var __lc = {el_var}.Location as LocationCurve;\n"
        f"    if (__lc == null) __post.Add({_cs(oid + ': нет LocationCurve')});\n"
        f"    else\n    {{\n"
        f"        var __a = __lc.Curve.GetEndPoint(0); var __b = __lc.Curve.GetEndPoint(1);\n"
        f"        double __da = Math.Pow(MM(__a.X) - {x0}, 2) + Math.Pow(MM(__a.Y) - {y0}, 2){orient_z};\n"
        f"        double __db = Math.Pow(MM(__b.X) - {x0}, 2) + Math.Pow(MM(__b.Y) - {y0}, 2){orient_z_b};\n"
        f"        var __e0 = __da <= __db ? __a : __b; var __e1 = __da <= __db ? __b : __a;\n"
        f"        if (Math.Abs(MM(__e0.X) - {x0}) > {tol} || Math.Abs(MM(__e0.Y) - {y0}) > {tol} ||\n"
        f"            Math.Abs(MM(__e1.X) - {x1}) > {tol} || Math.Abs(MM(__e1.Y) - {y1}) > {tol}{zc})\n"
        f"            __post.Add({_cs(oid + ': endpoints mismatch (geometry)')});\n"
        f"    }}")


def _level_check_expr(el_var: str, oid: str, bip: str, id_expr: str) -> str:
    """id_expr is a C# string expression, not an interpolated raw id."""
    return (
        f"var __bp = {el_var}.get_Parameter(BuiltInParameter.{bip});\n"
        f"    if (__bp == null || __bp.AsElementId() == null || __bp.AsElementId().ToString() != {id_expr})\n"
        f"        __post.Add({_cs(oid + ': level binding mismatch (topology)')});")


def _level_chain_check(el_var: str, oid: str, id_expr: str) -> str:
    """Check level binding through the version-safe parameter chain.

    A link is accepted only when it holds a real ElementId. Revit parameters
    can report HasValue=True while AsElementId is InvalidElementId; stopping
    there used to reject correct beams before reaching their real level link.
    """
    def link(bip: str, first: bool = False) -> str:
        return (f"Parameter __lp = {el_var}.get_Parameter(BuiltInParameter.{bip});\n"
                if first else
                f"    if (__lp == null || !__lp.HasValue "
                f"|| __lp.AsElementId() == null "
                f"|| __lp.AsElementId() == ElementId.InvalidElementId) "
                f"__lp = {el_var}.get_Parameter(BuiltInParameter.{bip});\n")
    return (
        link("FAMILY_BASE_LEVEL_PARAM", first=True)
        + link("FAMILY_LEVEL_PARAM")
        + link("SCHEDULE_LEVEL_PARAM")
        + link("LEVEL_PARAM")
        + f"    if (__lp == null || __lp.AsElementId() == null || __lp.AsElementId().ToString() != {id_expr})\n"
        f"        __post.Add({_cs(oid + ': level binding mismatch (topology)')});")


def _split_witness(
    key: str, body: str, message: str, *,
    lead: str = "    ", tail: str = "\n",
    tol=None,
    style: str = "else_block",
) -> WitnessCheck:
    reader, sep, verdict = body.partition("\n")
    return WitnessCheck(
        obligation_key=key,
        reader_cs=lead + reader + sep,
        verdict_cs=verdict + tail,
        message=message,
        tol=tol,
        style=style,  # type: ignore[arg-type]
    )


def endpoint_witness(
    el_var: str, oid: str, p0, p1, tol, three_d: bool,
    *, lead: str = "    ", tail: str = "\n",
) -> WitnessCheck:
    """Model the endpoint witness with registry-minted tolerance provenance."""
    return _split_witness(
        "endpoints", _endpoint_check(el_var, oid, p0, p1, tol, three_d),
        "endpoints mismatch (geometry)", lead=lead, tail=tail,
        tol=tol, style="else_block")


def level_chain_witness(
    el_var: str, oid: str, id_expr: str,
    *, key: str = "level_binding", lead: str = "    ", tail: str = "\n",
) -> WitnessCheck:
    """Model the version-safe level-chain witness."""
    return _split_witness(
        key, _level_chain_check(el_var, oid, id_expr),
        "level binding mismatch (topology)", lead=lead, tail=tail,
        style="guard")


def bbox_extents_witness(
    el_var: str, oid: str, xmin, xmax, ymin, ymax, tol,
    *, key: str = "bbox",
) -> WitnessCheck:
    """Model the shared floor/roof/slab bounding-box witness."""
    return WitnessCheck(
        obligation_key=key,
        reader_cs=f"    var __bb = {el_var}.get_BoundingBox(null);\n",
        verdict_cs=(
            f"    if (__bb == null) __post.Add({_cs(oid + ': нет BoundingBox')});\n"
            f"    else if (Math.Abs(MM(__bb.Min.X) - {xmin}) > {tol} || Math.Abs(MM(__bb.Max.X) - {xmax}) > {tol} ||\n"
            f"             Math.Abs(MM(__bb.Min.Y) - {ymin}) > {tol} || Math.Abs(MM(__bb.Max.Y) - {ymax}) > {tol})\n"
            f"        __post.Add({_cs(oid + ': bbox extents mismatch (geometry)')});\n"),
        message="bbox extents mismatch (geometry)",
        tol=tol,
        style="else_block")


def level_binding_witness(
    el_var: str, oid: str, bip: str, id_expr: str,
    *, key: str = "base_constraint", lead: str = "    ", tail: str = "\n",
) -> WitnessCheck:
    """Model a direct built-in-parameter level-binding witness."""
    return _split_witness(
        key, _level_check_expr(el_var, oid, bip, id_expr),
        "level binding mismatch (topology)", lead=lead, tail=tail,
        style="guard")


def _readback_block(
    s: str,
    oid: str,
    stamp: str,
    *,
    location_rotation: bool = False,
    family_state: bool = False,
) -> str:
    rotation = (
        f"    try {{ var __lp2 = __el_{s}.Location as LocationPoint;\n"
        f"        if (__lp2 != null) __rb[\"rotation_deg\"] = "
        f"Math.Round(__lp2.Rotation * 180.0 / Math.PI, 6); }} catch {{ }}\n"
        if location_rotation else ""
    )
    state = (
        f"    try {{ var __fi2 = __el_{s} as FamilyInstance;\n"
        f"        if (__fi2 != null) {{\n"
        f"            __rb[\"mirrored\"] = __fi2.Mirrored;\n"
        f"            __rb[\"hand_flipped\"] = __fi2.HandFlipped;\n"
        f"            __rb[\"facing_flipped\"] = __fi2.FacingFlipped;\n"
        f"        }} }} catch {{ }}\n"
        if family_state else ""
    )
    return (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __lc2 = __el_{s}.Location as LocationCurve;\n"
        f"        if (__lc2 != null) {{\n"
        f"            var __s2 = __lc2.Curve.GetEndPoint(0); var __e2 = __lc2.Curve.GetEndPoint(1);\n"
        f"            __rb[\"start_mm\"] = new double[] {{ Math.Round(MM(__s2.X), 1), Math.Round(MM(__s2.Y), 1), Math.Round(MM(__s2.Z), 1) }};\n"
        f"            __rb[\"end_mm\"] = new double[] {{ Math.Round(MM(__e2.X), 1), Math.Round(MM(__e2.Y), 1), Math.Round(MM(__e2.Z), 1) }};\n"
        f"        }} }} catch {{ }}\n"
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        + rotation +
        state +
        f"    __results[{_cs(oid)}] = __rb;\n}}")


def _symbol_res(op: dict, s: str, oid: str, ver: str,
                isolation: str = "atomic") -> str:
    g = _gid(op, "symbol")
    return (f"FamilySymbol __sy_{s} = doc.GetElement({_eid(g['id'], ver, oid)}) as FamilySymbol;\n"
            f"if (__sy_{s} == null) {{ {refuse_stmt(oid, _cs('типоразмер не найден (модель изменилась после grounding)'), isolation)} }}\n"
            f"if (!__sy_{s}.IsActive) {{ __sy_{s}.Activate(); doc.Regenerate(); }}")


def _loop_pts(pts: list, name: str, z: str = "0") -> list:
    out = [f"CurveLoop {name} = new CurveLoop();"]
    n = len(pts)
    for k in range(n):
        a, b = pts[k], pts[(k + 1) % n]
        out.append(f"{name}.Append(Line.CreateBound(P({a[0]}, {a[1]}, {z}), P({b[0]}, {b[1]}, {z})));")
    return out
