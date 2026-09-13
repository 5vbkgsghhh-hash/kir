"""mep_emit — emission for the electrical/flexible/placeholder wave (the sibling
file to ops_mep.py, exactly as arch_emit.py is to ops_arch.py and struct_emit.py
is to ops_struct.py).

Its own wave zone: the module does not touch ops_authoring.py, ops_struct.py,
ops_arch.py, connect.py, contour.py, or any other ops_*.py. authoring.py gets an
ADDITIVE import and five lines in `_EMITTERS` — the same minimal seam that the
framing and architecture waves connected through.

Reused from authoring.py WITHOUT CHANGES (by import, not by copy): `_gid`,
`_eid`, `_cs`, `_safe`, `_pt3`, `_level_expr`, `_stamp_block`,
`_stamp_readback`, `_readback_block`, plus the PUBLIC witness models
`endpoint_witness` and `level_binding_witness`. The same caveat as for
struct_emit.py applies: some names are private, and the fix for that is to
promote them to public in authoring.py, not to copy their bodies here.

THE MAIN THING ABOUT THIS FILE — WHAT THE RESULT IS READ WITH HERE.

Five operations, four different ways to reread what was built, and none of them
is "check that the setter ran":

* `create_conduit` — the `LocationCurve` axis (computed by Revit, not by us) +
  the level via `RBS_START_LEVEL_PARAM` + the TYPE via `GetTypeId()`. The type
  is checked because `Conduit.Create` is documented to accept
  `InvalidElementId`, and in that case SILENTLY substitutes the document's
  default type: the only operation in the wave where the API itself offers a
  silent substitution.
* `create_pipe_placeholder` / `create_duct_placeholder` — the same, plus
  `IsPlaceholder`. This is the ENTIRE substantive remainder of "placeholder":
  without it the operation is indistinguishable from an ordinary pipe, and
  "placeholder" would be a word in the journal rather than a fact in the model.
* `create_flex_duct` / `create_flex_pipe` — `Points`, that is, the ENTIRE path,
  with the point count and order. The endpoints alone are not enough, on the
  merits: a discarded middle would leave the endpoints in place, and the route
  would have shifted under a green verdict.

WHY THE EXPECTED PATH IS WRITTEN OUT AGAIN IN post, rather than taken from the
`List<XYZ>` assembled in create: `per_op` wraps create in its own scope, and a
variable from there used in post is a CS0103 on the user's machine (the scope
contract, `tests/test_emitter_scope_contract.py`). The expectation is literals,
and that is also correct on the merits: the witness is required to check against
what was ASKED FOR, not against what the emitter put into its own variable.
"""
from __future__ import annotations

from kir.emit_core import (  # noqa: F401
    _gid, _eid, _cs, _safe,
    _pt3, _level_expr, _stamp_block, _stamp_readback,
    _readback_block, endpoint_witness, final_shift, level_binding_witness,
)
from kir.emit_model import WitnessCheck, tolerances
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt


def _type_witness(el_var: str, oid: str, type_id_expr: str, human: str,
                  *, key: str) -> WitnessCheck:
    """`GetTypeId()` of the built element == the grounded type (semantic).

    What is read is the RESULT: `Element.GetTypeId()` returns the type carried
    by the created element, not the argument we passed in. `ToString()` is the
    only form of id comparison that is safe across all six versions (`.Value` has
    existed since 2024, `.IntegerValue` dies after 2025).
    """

    return WitnessCheck(
        obligation_key=key,
        reader_cs=f"    var __ty = {el_var}.GetTypeId();\n",
        verdict_cs=(
            f"    if (__ty == null || __ty.ToString() != {type_id_expr})\n"
            f"        __post.Add({_cs(oid + f': {human} mismatch (semantic)')});\n"),
        message=f"{human} mismatch (semantic)",
        style="guard")


def _emit_conduit(op: dict, ver: str, stamp: str,
                  isolation: str = "atomic") -> tuple:
    """Electrical.Conduit.Create(Document, conduitTypeId, XYZ, XYZ, levelId).

    ARGUMENT ORDER LIKE A CABLE TRAY, NOT LIKE A PIPE: the level comes LAST,
    after both points. The signature was taken from reference assemblies and
    compiled against 2021-2026 before this line was written.
    """
    oid = op["id"]
    s = _safe(oid)
    ct = _gid(op, "conduit_type")
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    decl = f"Autodesk.Revit.DB.Electrical.Conduit __el_{s} = null;"
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    create = (
        f"// create_conduit {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"__el_{s} = Autodesk.Revit.DB.Electrical.Conduit.Create(doc, "
        f"{_eid(ct['id'], ver, oid)}, "
        f"P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}), __lv_{s}.Id);\n"
        f"if (__el_{s} == null) {{ {refuse_stmt(oid, _cs('Conduit.Create вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        # THE RESULT OF THE LAST LEGITIMATE WRITER (E-3): the same law as for
        # `create_wall` (E-2) — `emit_core.final_shift`, one reader.
        endpoint_witness(
            f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
            tolerances("create_conduit")["endpoint_mm"], True,
            shift=final_shift(op)),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level"),
        _type_witness(f"__el_{s}", oid, _cs(str(ct["id"])), "conduit type",
                      key="conduit_type"),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


def _emit_placeholder(op: dict, ver: str, stamp: str, isolation: str,
                      *, op_name: str, cs_class: str, type_param: str,
                      human_type: str, human_ru: str) -> tuple:
    """The shared body of `Pipe.CreatePlaceholder` / `Duct.CreatePlaceholder`.

    ONE implementation for two operations, deliberately: the signatures differ
    by exactly the namespace and the type parameter's name, while the witnesses
    match letter for letter. Two copies would have drifted apart at the very
    first edit — the same class of problem `route_mep` avoided by parameterizing
    `connect` instead of copying it.
    """
    oid = op["id"]
    s = _safe(oid)
    st = _gid(op, "system_type")
    tt = _gid(op, type_param)
    x0, y0, z0 = _pt3(op["p0_mm"])
    x1, y1, z1 = _pt3(op["p1_mm"])
    decl = f"{cs_class} __el_{s} = null;"
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    create = (
        f"// {op_name} {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"__el_{s} = {cs_class}.CreatePlaceholder(doc, "
        f"{_eid(st['id'], ver, oid)}, {_eid(tt['id'], ver, oid)}, "
        f"__lv_{s}.Id, P({x0}, {y0}, {z0}), P({x1}, {y1}, {z1}));\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs(f'{human_ru} вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        # THE RESULT OF THE LAST LEGITIMATE WRITER (E-3): the same law as for
        # `create_wall` (E-2) — `emit_core.final_shift`, one reader.
        endpoint_witness(
            f"__el_{s}", oid, op["p0_mm"], op["p1_mm"],
            tolerances(op_name)["endpoint_mm"], True, shift=final_shift(op)),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level"),
        # The one bit that distinguishes a placeholder from an ordinary run, and
        # therefore the one bit the operation exists for at all.
        # What is read is the PROPERTY OF THE BUILT ELEMENT (Pipe.IsPlaceholder /
        # Duct.IsPlaceholder, both present on 2021-2026), not the call's argument.
        WitnessCheck(
            obligation_key="is_placeholder",
            reader_cs="",
            verdict_cs=(
                f"    if (!__el_{s}.IsPlaceholder)\n"
                f"        __post.Add({_cs(oid + ': созданный элемент не заготовка (semantic)')});\n"),
            message="созданный элемент не заготовка (semantic)",
            style="guard"),
        _type_witness(f"__el_{s}", oid, _cs(str(tt["id"])), human_type,
                      key=type_param),
    ]
    return decl, create, checks, _readback_block(s, oid, stamp, identity_version=ver)


def _emit_pipe_placeholder(op: dict, ver: str, stamp: str,
                           isolation: str = "atomic") -> tuple:
    return _emit_placeholder(
        op, ver, stamp, isolation,
        op_name="create_pipe_placeholder",
        cs_class="Autodesk.Revit.DB.Plumbing.Pipe",
        type_param="pipe_type", human_type="pipe type",
        human_ru="Pipe.CreatePlaceholder")


def _emit_duct_placeholder(op: dict, ver: str, stamp: str,
                           isolation: str = "atomic") -> tuple:
    return _emit_placeholder(
        op, ver, stamp, isolation,
        op_name="create_duct_placeholder",
        cs_class="Autodesk.Revit.DB.Mechanical.Duct",
        type_param="duct_type", human_type="duct type",
        human_ru="Duct.CreatePlaceholder")


def _flex_readback(s: str, oid: str, stamp: str) -> str:
    """The receipt of a flexible run: the ENTIRE path, not a pair of endpoints.

    The shared `_readback_block` reads `Location as LocationCurve`; for a
    flexible element that holds a Hermite spline, and its endpoints are a
    derivative of the points. What goes into the receipt is the primary data:
    `Points` as a flat array in mm.
    """
    return (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ var __pp2 = __el_{s}.Points;\n"
        f"        if (__pp2 != null) {{\n"
        f"            var __path = new List<double[]>();\n"
        f"            for (int __k = 0; __k < __pp2.Count; __k++)\n"
        f"                __path.Add(new double[] {{ Math.Round(MM(__pp2[__k].X), 1), "
        f"Math.Round(MM(__pp2[__k].Y), 1), Math.Round(MM(__pp2[__k].Z), 1) }});\n"
        f"            __rb[\"path_mm\"] = __path;\n"
        f"        }} }} catch {{ }}\n"
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")


def _emit_flex(op: dict, ver: str, stamp: str, isolation: str,
               *, op_name: str, cs_class: str, type_param: str,
               human_type: str, human_ru: str) -> tuple:
    """The shared body of `FlexDuct.Create` / `FlexPipe.Create` (the overload
    without tangents: Document, systemTypeId, typeId, levelId, IList<XYZ>).

    The overload with tangents exists on all six versions and is NOT used: a
    tangent is the direction the route enters from, and this operation has no
    such entry; substituting a "reasonable" one would mean building a bend the
    author never asked for. Autodesk states that a zero/invalid vector is
    ignored, meaning the argument has no honest neutral value — it either carries
    intent, or must not be passed at all.
    """
    oid = op["id"]
    s = _safe(oid)
    st = _gid(op, "system_type")
    tt = _gid(op, type_param)
    path = op["path"]
    tol = tolerances(op_name)["point_mm"]
    decl = f"{cs_class} __el_{s} = null;"
    lv_res, lv_idexpr = _level_expr(op, s, ver, oid, isolation)
    pts_cs = "".join(
        f"__pts_{s}.Add(P({pt[0]}, {pt[1]}, {pt[2]}));\n" for pt in path)
    create = (
        f"// {op_name} {cs_line_comment_fragment(oid)}\n"
        + lv_res + "\n"
        f"var __pts_{s} = new List<XYZ>();\n"
        + pts_cs +
        f"__el_{s} = {cs_class}.Create(doc, {_eid(st['id'], ver, oid)}, "
        f"{_eid(tt['id'], ver, oid)}, __lv_{s}.Id, __pts_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs(f'{human_ru} вернул null'), isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    expected = ", ".join(f"{c}" for pt in path for c in (pt[0], pt[1], pt[2]))
    n = len(path)
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="path_points",
            reader_cs=f"    var __pp = __el_{s}.Points;\n",
            # TWO CASES KEPT SEPARATE, not one. The point count and the point
            # positions are different diagnoses: Autodesk documents that
            # coincident points "don't take into account" (are discarded), and
            # such a path would come back shorter than what was ordered. One
            # single word, "geometry mismatch", for both cases would have named
            # the symptom instead of the cause — the cost of that shortcut has
            # already been measured on the diameter of a rectangular duct
            # (30.07, Snowdon).
            verdict_cs=(
                f"    if (__pp == null || __pp.Count != {n})\n"
                f"        __post.Add({_cs(oid + f': flex path point count mismatch — Revit вернул другое число точек, чем {n} заказанных (geometry)')});\n"
                f"    else\n    {{\n"
                f"        double[] __ex = new double[] {{ {expected} }};\n"
                f"        bool __bad = false;\n"
                f"        for (int __i = 0; __i < {n}; __i++)\n"
                f"        {{\n"
                f"            var __q = __pp[__i];\n"
                f"            if (Math.Abs(MM(__q.X) - __ex[__i * 3]) > {tol} ||\n"
                f"                Math.Abs(MM(__q.Y) - __ex[__i * 3 + 1]) > {tol} ||\n"
                f"                Math.Abs(MM(__q.Z) - __ex[__i * 3 + 2]) > {tol})\n"
                f"                __bad = true;\n"
                f"        }}\n"
                f"        if (__bad) __post.Add({_cs(oid + ': flex path points mismatch (geometry)')});\n"
                f"    }}\n"),
            message="flex path points mismatch (geometry)",
            tol=tol,
            style="else_block"),
        level_binding_witness(
            f"__el_{s}", oid, "RBS_START_LEVEL_PARAM", lv_idexpr,
            key="reference_level"),
        _type_witness(f"__el_{s}", oid, _cs(str(tt["id"])), human_type,
                      key=type_param),
    ]
    return decl, create, checks, _flex_readback(s, oid, stamp)


def _emit_flex_duct(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple:
    return _emit_flex(
        op, ver, stamp, isolation,
        op_name="create_flex_duct",
        cs_class="Autodesk.Revit.DB.Mechanical.FlexDuct",
        type_param="flex_duct_type", human_type="flex duct type",
        human_ru="FlexDuct.Create")


def _emit_flex_pipe(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple:
    return _emit_flex(
        op, ver, stamp, isolation,
        op_name="create_flex_pipe",
        cs_class="Autodesk.Revit.DB.Plumbing.FlexPipe",
        type_param="flex_pipe_type", human_type="flex pipe type",
        human_ru="FlexPipe.Create")


#: WHAT THIS SPOKE EMITS IS DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Previously the "op -> body" correspondence lived in the hand-written
#: `authoring._EMITTERS`, while the body lived here, and a thin wrapper in the
#: hub connected the two (41 of them across 19 satellites). Two records of one
#: fact in different files is a named defect of this tree; now there is ONE
#: record, and the hub ASKS it.
EMITTERS = {
    "create_conduit": _emit_conduit,
    "create_duct_placeholder": _emit_duct_placeholder,
    "create_flex_duct": _emit_flex_duct,
    "create_flex_pipe": _emit_flex_pipe,
    "create_pipe_placeholder": _emit_pipe_placeholder,
}
