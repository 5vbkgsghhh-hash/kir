"""analysis_emit — emission of the loads and egress-path wave (the sibling file to
ops_analysis.py, exactly as mep_emit.py is to ops_mep.py and arch_emit.py is to
ops_arch.py).

Its own wave zone: the module does not touch ops_authoring.py, ops_struct.py,
ops_arch.py, ops_mep.py, connect.py, contour.py, or any other ops_*.py.
authoring.py gets an ADDITIVE import and four lines in `_EMITTERS` — the same
minimal seam through which the framing, architecture, and MEP waves were
connected.

Reused from authoring.py WITHOUT CHANGES (by import, not by copy): `_gid`,
`_eid`, `_cs`, `_safe`, `_pt3`, `_annot_view_res`, `_stamp_block`,
`_stamp_readback`, `EMIT_UNSUPPORTED`. The same caveat applies as for
struct_emit.py and mep_emit.py: some of the names are private, and the fix
for that is promoting them to public in authoring.py, not copying the
bodies here.

VARIABLE NAMES SHARE THE NAMESPACE WITH THE per_op WRAPPER, and this cost two
gate failures on the very first run (measured 09.08, both caught by Roslyn,
neither would have reached the user): the per_op wrapper sets up `__st_<oid>`
for its own SubTransaction — so the path-of-travel calculation status is
called `__potstatus_<oid>`, not `__st_<oid>`; and a point load has TWO
vectors in one post block, so the read variable's name carries the
OBLIGATION KEY (`__vec_force_vector_<oid>`), not just the op's id.

THE MAIN THING ABOUT THIS FILE — WHAT THE RESULT IS READ WITH HERE.

Four operations and not a single "the setter ran" check:

* `create_point_load` — `Point`, `ForceVector`, `MomentVector`, `OrientTo`,
  `LoadCaseId`, `GetTypeId()`. All six are properties of the BUILT element.
* `create_line_load` — the same, plus `StartPoint`/`EndPoint` instead of a
  point and `IsUniform` instead of the moment.
* `create_area_load` — `GetLoops()`, that is, the REAL edges of the built
  load, per vertex and with a vertex count; Revit derives the area from
  them itself, and it is not an obligation (see ops_analysis.py).
* `create_path_of_travel` — `PathStart`/`PathEnd`/`GetCurves()`/`OwnerViewId`
  plus a typed calculation status BEFORE the postconditions.

GEOMETRY TOLERANCE LIVES NEITHER IN THE REGISTRY NOR IN THE C#. Points are
compared against `doc.Application.VertexTolerance`, read from the running
application — the technique from `create_dimension` (09.08). Hence in
INTERNAL units (feet): converting both sides to millimeters would mean
comparing millimeters against a tolerance in feet. The expected number
travels into the C# as `U(<мм>)`, meaning that same Revit converts it.

WHY THE EXPECTED VALUES ARE WRITTEN OUT AGAIN IN post, rather than taken from
the create variables: `per_op` wraps create in its own scope, and a variable
from there in post is a CS0103 on the user's machine (the scope contract,
`tests/test_emitter_scope_contract.py`). The expectations are literals, and
this is also correct in substance: the witness is required to check against
what was ASKED FOR, not against what the emitter put into its own variable.
"""
from __future__ import annotations

import math

from kir.emit_core import (  # noqa: F401
    _gid, _eid, _cs, _safe,
    _pt3, _annot_view_res, _stamp_block, _stamp_readback,
    EMIT_UNSUPPORTED,
)
from kir.emit_model import WitnessCheck, tolerance
from kir.emit_utils import cs_line_comment_fragment, refuse_stmt
from kir.diag import Diagnostic, KirRefusal


def _si(value: float, unit: str) -> str:
    """An SI value -> Revit's internal units, BY ITS OWN MEANS.

    Not a single coefficient in this package: `UnitUtils` knows the internal
    unit of force, and asking it is cheaper than remembering a number that
    Autodesk has nowhere promised not to change. A wrapper helper
    (`double FN(double)`) is deliberately ABSENT from the preamble — the
    preamble is shared by all programs, and its growth would shift the
    frozen bytes of emissions this wave does not touch
    (`test_emit_model_byte_parity`).
    """

    return f"UnitUtils.ConvertToInternalUnits({value}, UnitTypeId.{unit})"


def _si_vec(values: tuple, unit: str) -> str:
    return (f"new XYZ({_si(values[0], unit)}, {_si(values[1], unit)}, "
            f"{_si(values[2], unit)})")

#: A load in which BOTH the force AND the moment are zero. Autodesk
#: documents `ArgumentsInconsistentException` inside the transaction for
#: this case; refusing STATICALLY is cheaper and more honest — a runtime
#: exception inside the transaction looks like our defect, while it is the
#: author's mistake, and it must be named as such.
#: A belt over the suspenders in the same sense as FOUNDATION_UNSUPPORTED_KIND
#: on the framing wave: the registry already holds the bounds of individual
#: numbers, but "all six zero at once" is not expressed by any single one of
#: their bounds.
# E012, NOT E007 (10.08.2026). `KIR-E007` carried FIVE names, and four of
# them are one thought: "a value from a closed enumeration is unsupported
# here". This name is NOT kin to that: a zero-magnitude load is not an
# unsupported enumeration value, it is a meaningless number, and its fix is
# different (set a magnitude, rather than pick a different option). The
# other four remain debt, named in `diag.CODES_WITH_KNOWN_ALIASES`.
ANALYSIS_ZERO_LOAD = "KIR-E012"

#: The first Revit version on which a free (unhosted) load is NO LONGER
#: present in the API. Measured, not remembered: on 2024/2025/2026 the
#: PointLoad/LineLoad/AreaLoad overloads without `ElementId hostElemId` give
#: CS1503/CS1501 against the reference assemblies. The number lives HERE,
#: one for all three operations, because their boundary is shared and must
#: not drift apart.
_FREE_LOAD_LAST_VER = "2023"

_LOAD_VERSION_MSG = (
    "свободная (нехостированная) нагрузка не создаётся на Revit {ver}: "
    "перегрузки {api} без носителя убраны из API в 2024 — замерено "
    "компиляцией против эталонных сборок. Все оставшиеся перегрузки требуют "
    "ElementId аналитического элемента-носителя, которого нет ни в снимке "
    "модели, ни в языке ссылок KIR; передать InvalidElementId компилятор "
    "может, но Autodesk документирует на этот аргумент ArgumentException "
    "«hostElemId is not permitted for this type of load» и нигде не обещает, "
    "что недействительный id означает «без носителя» — догадка о поведении "
    "здесь была бы тем же изобретением, что выдуманный допуск"
)


def _version_guard(ver: str, oid: str, api: str) -> None:
    """A typed KIR-E003 on 2024-2026 — BEFORE parsing anything at all.

    A refusal, not an emission fork: there is no fork by construction. The
    only alternatives are to build the load on a foreign host (a different
    element) or to build nothing and stay silent; both read from the
    outside as success.
    """
    if ver > _FREE_LOAD_LAST_VER:
        raise KirRefusal([Diagnostic(
            code=EMIT_UNSUPPORTED, op_id=oid, field_name=None,
            message_ru=_LOAD_VERSION_MSG.format(ver=ver, api=api))])


def _nz(op: dict, name: str) -> float:
    """A vector component: ABSENCE is zero, and WE are the ones who set the zero.

    The `num` kind does not substitute defaults (`validate` normalizes only
    what the author actually wrote), so a missing component never arrives
    here at all. The zero here is not a guess at intent, it is our own
    action: we pass it into the API and therefore HAVE THE RIGHT to attest
    to it (the law "either the emitter sets the value, or Revit decides it"
    — tests/test_silent_defaults.py).
    """
    value = op.get(name)
    return 0.0 if value is None else float(value)


def _zero_guard(op: dict, oid: str, names: tuple[str, ...]) -> None:
    if all(_nz(op, name) == 0.0 for name in names):
        raise KirRefusal([Diagnostic(
            code=ANALYSIS_ZERO_LOAD, op_id=oid, field_name=names[0],
            message_ru=("нагрузка нулевая по всем компонентам — Revit отвергнет "
                        "её внутри транзакции (ArgumentsInconsistentException); "
                        f"задайте хотя бы одну из {', '.join(names)}"))])


def _load_type_cs(op: dict, s: str, oid: str, ver: str, cs_class: str,
                  human: str, isolation: str) -> tuple[str, str]:
    """Resolving the load type into `__ty_<s>` + the C# expression for its id.

    There is NO doc_default branch here, and there cannot be one:
    `ElementTypeGroup` contains neither `PointLoadType`, nor `LineLoadType`,
    nor `AreaLoadType` — asking the document "what is your default load
    type" is impossible by construction, exactly as with a door or a
    railing. A missing selector is resolved by ground.py's general rule:
    "the only one in the pool, otherwise a typed question".
    """
    g = _gid(op, "load_type")
    idx = _eid(g["id"], ver, oid)
    res = (f"{cs_class} __ty_{s} = doc.GetElement({idx}) as {cs_class};\n"
           f"if (__ty_{s} == null) {{ "
           f"{refuse_stmt(oid, _cs(human + ': тип не найден (модель изменилась после grounding)'), isolation)} }}")
    return res, _cs(str(g["id"]))


def _load_case_cs(op: dict, s: str, oid: str, ver: str,
                  isolation: str) -> tuple[str, str]:
    g = _gid(op, "load_case")
    idx = _eid(g["id"], ver, oid)
    res = (f"Autodesk.Revit.DB.Structure.LoadCase __lc_{s} = "
           f"doc.GetElement({idx}) as Autodesk.Revit.DB.Structure.LoadCase;\n"
           f"if (__lc_{s} == null) {{ "
           f"{refuse_stmt(oid, _cs('случай загружения не найден (модель изменилась после grounding)'), isolation)} }}")
    return res, _cs(str(g["id"]))


#: Pinning the reference frame + re-recording the vector IN IT.
#: The order is mandatory: the frame first, then the numbers (see ops_analysis.py).
def _orient_and_set_cs(s: str, oid: str, isolation: str, vec_prop: str,
                       vec_expr: str, extra: str = "") -> str:
    lo = "Autodesk.Revit.DB.Structure.LoadOrientTo"
    return (
        f"if (!__el_{s}.IsOrientToPermitted({lo}.Project)) {{ "
        f"{refuse_stmt(oid, _cs('нагрузка не допускает проектную систему отсчёта'), isolation)} }}\n"
        f"__el_{s}.OrientTo = {lo}.Project;\n"
        f"__el_{s}.{vec_prop} = {vec_expr};\n"
        + extra)


def _orient_witness(s: str, oid: str) -> WitnessCheck:
    """`OrientTo` of the BUILT element == Project.

    Not decoration and not a setter check: `ForceVector` is documented as
    "oriented according to OrientTo setting", meaning that without this
    fact the three vector numbers do not mean anything definite. The force
    witness below relies on this one, not the other way around.
    """
    lo = "Autodesk.Revit.DB.Structure.LoadOrientTo"
    return WitnessCheck(
        obligation_key="orientation",
        reader_cs="",
        verdict_cs=(
            f"    if (__el_{s}.OrientTo != {lo}.Project)\n"
            f"        __post.Add({_cs(oid + ': OrientTo построенной нагрузки не Project — вектор силы прочитан бы в другой системе отсчёта (semantic)')});\n"),
        message="OrientTo построенной нагрузки не Project (semantic)",
        style="guard")


def _vector_witness(s: str, oid: str, prop: str, unit: str, values: tuple,
                    tol, human: str, *, key: str) -> WitnessCheck:
    """The three vector components of the built element against the ones ordered, in SI.

    The conversion from internal units is done by Revit itself
    (`UnitUtils.ConvertFromInternalUnits`), so there is not a single
    coefficient in the C# that could diverge from the one we wrote with.
    """
    fx, fy, fz = values
    # The variable name carries the OBLIGATION KEY, not just the op's id: a
    # point load has two vectors in ONE post block (force and moment), and
    # a shared name `__vec_<oid>` would give CS0128 on the user's machine.
    # Caught by the Roslyn gate on the very first run — exactly what it
    # stands there for.
    var = f"__vec_{key}_{s}"
    return WitnessCheck(
        obligation_key=key,
        reader_cs=f"    var {var} = __el_{s}.{prop};\n",
        verdict_cs=(
            f"    if (Math.Abs(UnitUtils.ConvertFromInternalUnits({var}.X, UnitTypeId.{unit}) - ({fx})) > {tol.cs} ||\n"
            f"        Math.Abs(UnitUtils.ConvertFromInternalUnits({var}.Y, UnitTypeId.{unit}) - ({fy})) > {tol.cs} ||\n"
            f"        Math.Abs(UnitUtils.ConvertFromInternalUnits({var}.Z, UnitTypeId.{unit}) - ({fz})) > {tol.cs})\n"
            f"        __post.Add({_cs(oid + f': {human} построенной нагрузки не совпал с заказанным (semantic)')});\n"),
        message=f"{human} mismatch (semantic)",
        tol=tol,
        style="guard")


def _load_case_witness(s: str, oid: str, id_expr: str) -> WitnessCheck:
    return WitnessCheck(
        obligation_key="load_case",
        reader_cs=f"    var __lcid_{s} = __el_{s}.LoadCaseId;\n",
        verdict_cs=(
            f"    if (__lcid_{s} == null || __lcid_{s}.ToString() != {id_expr})\n"
            f"        __post.Add({_cs(oid + ': случай загружения построенной нагрузки не тот, что заземлён (semantic)')});\n"),
        message="load case mismatch (semantic)",
        style="guard")


def _load_type_witness(s: str, oid: str, id_expr: str) -> WitnessCheck:
    """`GetTypeId()` of the built element == the grounded type (semantic).

    `ToString()` is the only form of comparing ids that is safe across all
    six versions (`.Value` has existed since 2024, `.IntegerValue` dies
    after 2025).
    """
    return WitnessCheck(
        obligation_key="load_type",
        reader_cs=f"    var __tyid_{s} = __el_{s}.GetTypeId();\n",
        verdict_cs=(
            f"    if (__tyid_{s} == null || __tyid_{s}.ToString() != {id_expr})\n"
            f"        __post.Add({_cs(oid + ': load_type построенной нагрузки не тот, что заземлён (semantic)')});\n"),
        message="load_type mismatch (semantic)",
        style="guard")


def _load_readback(s: str, oid: str, stamp: str, extra: str = "") -> str:
    """The load's receipt: what was READ from the built element.

    Values that are not obligations travel here too (the area of an area
    load, the load case's name): a receipt is an observation, not a
    promise, and confusing the two is forbidden (`_stamp_readback` does not
    echo a stamp we merely attempted to write, for the same reason).
    """
    return (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ __rb[\"load_case_name\"] = __el_{s}.LoadCaseName; }} catch {{ }}\n"
        f"    try {{ __rb[\"load_nature_name\"] = __el_{s}.LoadNatureName; }} catch {{ }}\n"
        f"    try {{ __rb[\"orient_to\"] = __el_{s}.OrientTo.ToString(); }} catch {{ }}\n"
        f"    try {{ __rb[\"is_hosted\"] = __el_{s}.IsHosted; }} catch {{ }}\n"
        f"    try {{ var __tid = __el_{s}.GetTypeId();\n"
        f"        if (__tid != null && __tid != ElementId.InvalidElementId) {{\n"
        f"            var __te = doc.GetElement(__tid);\n"
        f"            if (__te != null && __te.Name != null) __rb[\"type_name\"] = __te.Name;\n"
        f"        }} }} catch {{ }}\n"
        + extra +
        f"    __results[{_cs(oid)}] = __rb;\n}}")


# ── create_point_load ────────────────────────────────────────────────────────

def emit_point_load(op: dict, ver: str, stamp: str,
                    isolation: str = "atomic") -> tuple[str, str, list, str]:
    """PointLoad.Create(doc, XYZ, XYZ force, XYZ moment, PointLoadType, SketchPlane).

    The work plane is BUILT HERE, horizontal, through the load point
    itself. The argument allows `null` ("use default plane"), and here is
    why it is not `null` here: the default is the work plane of the ACTIVE
    VIEW, that is, an input that is not in the program and that we do not
    know on the user's machine. The load's elevation would then depend on
    which tab the person last had open. With its own plane, `Point` is
    required to coincide with the ordered point — and the witness demands
    exactly that.
    """
    oid = op["id"]
    s = _safe(oid)
    _version_guard(ver, oid, "PointLoad.Create")
    _zero_guard(op, oid, ("fx_n", "fy_n", "fz_n", "mx_nm", "my_nm", "mz_nm"))
    x, y, z = _pt3(op["xyz"])
    f = (_nz(op, "fx_n"), _nz(op, "fy_n"), _nz(op, "fz_n"))
    m = (_nz(op, "mx_nm"), _nz(op, "my_nm"), _nz(op, "mz_nm"))
    ty_res, ty_idexpr = _load_type_cs(
        op, s, oid, ver, "Autodesk.Revit.DB.Structure.PointLoadType",
        "точечная нагрузка", isolation)
    lc_res, lc_idexpr = _load_case_cs(op, s, oid, ver, isolation)
    fvec = _si_vec(f, "Newtons")
    mvec = _si_vec(m, "NewtonMeters")
    decl = f"Autodesk.Revit.DB.Structure.PointLoad __el_{s} = null;"
    create = (
        f"// create_point_load {cs_line_comment_fragment(oid)}\n"
        f"{ty_res}\n{lc_res}\n"
        f"SketchPlane __sp_{s} = SketchPlane.Create(doc, "
        f"Plane.CreateByNormalAndOrigin(XYZ.BasisZ, P({x}, {y}, {z})));\n"
        f"if (__sp_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('не удалось построить рабочую плоскость точечной нагрузки'), isolation)} }}\n"
        f"__el_{s} = Autodesk.Revit.DB.Structure.PointLoad.Create(doc, "
        f"P({x}, {y}, {z}), {fvec}, {mvec}, __ty_{s}, __sp_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('PointLoad.Create вернул null'), isolation)} }}\n"
        + _orient_and_set_cs(
            s, oid, isolation, "ForceVector", fvec,
            extra=(f"__el_{s}.MomentVector = {mvec};\n"
                   f"__el_{s}.LoadCaseId = __lc_{s}.Id;\n"))
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="position",
            reader_cs=(f"    var __pt_{s} = __el_{s}.Point;\n"
                       f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            verdict_cs=(
                f"    if (__pt_{s} == null\n"
                f"        || Math.Abs(__pt_{s}.X - U({x})) > __vtol_{s}\n"
                f"        || Math.Abs(__pt_{s}.Y - U({y})) > __vtol_{s}\n"
                f"        || Math.Abs(__pt_{s}.Z - U({z})) > __vtol_{s})\n"
                f"        __post.Add({_cs(oid + ': Point построенной нагрузки не совпал с заказанной точкой (geometry)')});\n"),
            message="point mismatch (geometry)",
            style="guard"),
        _orient_witness(s, oid),
        _vector_witness(s, oid, "ForceVector", "Newtons", f,
                        tolerance("create_point_load", "force_n"),
                        "вектор силы", key="force_vector"),
        _vector_witness(s, oid, "MomentVector", "NewtonMeters", m,
                        tolerance("create_point_load", "moment_nm"),
                        "вектор момента", key="moment_vector"),
        _load_case_witness(s, oid, lc_idexpr),
        _load_type_witness(s, oid, ty_idexpr),
    ]
    return decl, create, checks, _load_readback(s, oid, stamp)


# ── create_line_load ─────────────────────────────────────────────────────────

def _plane_normal(p0: tuple, p1: tuple) -> tuple[float, float, float]:
    """The normal of the work plane CONTAINING the load's segment.

    The rule is deterministic and computed HERE, in Python, so that the C#
    carries literals (the same technique as for CONTOUR's arcs):

      * both ends at the same elevation -> the plane is horizontal (normal Z);
      * otherwise -> a VERTICAL plane through the segment: its normal is
        perpendicular to both the segment's direction and the vertical,
        that is, `normalize(cross(d, Z))`;
      * the segment is strictly vertical (both horizontal projections are
        zero) -> `cross(d, Z)` degenerates, and any vertical plane contains
        the segment; we take the normal X — an arbitrary choice, but a
        NAMED one, not a random one, and it does not affect the load's
        position: both ends are pinned by the witness.
    """
    dx, dy, dz = p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]
    if dz == 0.0:
        return (0.0, 0.0, 1.0)
    nx, ny = dy, -dx
    norm = math.hypot(nx, ny)
    if norm == 0.0:
        return (1.0, 0.0, 0.0)
    return (nx / norm, ny / norm, 0.0)


def emit_line_load(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """LineLoad.Create(doc, XYZ start, XYZ end, XYZ force, XYZ moment,
    LineLoadType, SketchPlane).

    THE MOMENT IS PASSED AS ZERO AND IS NOT ATTESTED HERE. The argument is
    mandatory, the operation has no distributed torsional load (a named
    gap, ops_analysis.py), and zero is zero in any units — so the question
    of a moment-per-meter unit does not arise here and there is no need to
    invent one.
    """
    oid = op["id"]
    s = _safe(oid)
    _version_guard(ver, oid, "LineLoad.Create")
    _zero_guard(op, oid, ("fx_n_per_m", "fy_n_per_m", "fz_n_per_m"))
    p0 = _pt3(op["p0_mm"])
    p1 = _pt3(op["p1_mm"])
    f = (_nz(op, "fx_n_per_m"), _nz(op, "fy_n_per_m"), _nz(op, "fz_n_per_m"))
    nx, ny, nz = _plane_normal(p0, p1)
    ty_res, ty_idexpr = _load_type_cs(
        op, s, oid, ver, "Autodesk.Revit.DB.Structure.LineLoadType",
        "линейная нагрузка", isolation)
    lc_res, lc_idexpr = _load_case_cs(op, s, oid, ver, isolation)
    fvec = _si_vec(f, "NewtonsPerMeter")
    decl = f"Autodesk.Revit.DB.Structure.LineLoad __el_{s} = null;"
    create = (
        f"// create_line_load {cs_line_comment_fragment(oid)}\n"
        f"{ty_res}\n{lc_res}\n"
        f"SketchPlane __sp_{s} = SketchPlane.Create(doc, "
        f"Plane.CreateByNormalAndOrigin(new XYZ({nx}, {ny}, {nz}), "
        f"P({p0[0]}, {p0[1]}, {p0[2]})));\n"
        f"if (__sp_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('не удалось построить рабочую плоскость линейной нагрузки'), isolation)} }}\n"
        f"__el_{s} = Autodesk.Revit.DB.Structure.LineLoad.Create(doc, "
        f"P({p0[0]}, {p0[1]}, {p0[2]}), P({p1[0]}, {p1[1]}, {p1[2]}), "
        f"{fvec}, new XYZ(0, 0, 0), __ty_{s}, __sp_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('LineLoad.Create вернул null'), isolation)} }}\n"
        + _orient_and_set_cs(
            s, oid, isolation, "ForceVector1", fvec,
            extra=f"__el_{s}.LoadCaseId = __lc_{s}.Id;\n")
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="endpoints",
            reader_cs=(f"    var __sp0_{s} = __el_{s}.StartPoint;\n"
                       f"    var __sp1_{s} = __el_{s}.EndPoint;\n"
                       f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            # THE ENDS ARE CHECKED STRICTLY BY POSITION, not "nearest to
            # nearest", as with the linear MEP ops. The reason is
            # substantive: a pipe's axis is symmetric and swapping the ends
            # changes nothing, while for a line load `ForceVector1` refers
            # SPECIFICALLY TO THE START, and swapping the ends is a
            # different load at the same geometry.
            verdict_cs=(
                f"    if (__sp0_{s} == null || __sp1_{s} == null\n"
                f"        || Math.Abs(__sp0_{s}.X - U({p0[0]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp0_{s}.Y - U({p0[1]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp0_{s}.Z - U({p0[2]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp1_{s}.X - U({p1[0]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp1_{s}.Y - U({p1[1]})) > __vtol_{s}\n"
                f"        || Math.Abs(__sp1_{s}.Z - U({p1[2]})) > __vtol_{s})\n"
                f"        __post.Add({_cs(oid + ': StartPoint/EndPoint построенной нагрузки не совпали с заказанными (geometry)')});\n"),
            message="endpoints mismatch (geometry)",
            style="guard"),
        _orient_witness(s, oid),
        _vector_witness(s, oid, "ForceVector1", "NewtonsPerMeter", f,
                        tolerance("create_line_load", "force_n_per_m"),
                        "вектор погонной силы", key="force_vector"),
        # UNIFORMITY IS A PROMISE OF OUR CALL SHAPE, NOT DECORATION. The
        # overload accepts a SINGLE force vector, meaning that per the
        # documentation ("load is uniform when force and moment vectors
        # assigned to the start and the end point are equal") the built
        # load is required to be uniform. If it is not — that is a
        # different load with the right ends and the right first vector,
        # exactly the outcome the geometry witness would have missed.
        WitnessCheck(
            obligation_key="uniform",
            reader_cs="",
            verdict_cs=(
                f"    if (!__el_{s}.IsUniform)\n"
                f"        __post.Add({_cs(oid + ': построенная линейная нагрузка не равномерна, хотя задан один вектор силы (semantic)')});\n"),
            message="line load is not uniform (semantic)",
            style="guard"),
        _load_case_witness(s, oid, lc_idexpr),
        _load_type_witness(s, oid, ty_idexpr),
    ]
    return decl, create, checks, _load_readback(s, oid, stamp)


# ── create_area_load ─────────────────────────────────────────────────────────

def emit_area_load(op: dict, ver: str, stamp: str,
                   isolation: str = "atomic") -> tuple[str, str, list, str]:
    """AreaLoad.Create(doc, IList<CurveLoop>, XYZ force, AreaLoadType).

    This overload has NO work-plane argument: the rings themselves define
    the plane. That is why the ring here is flat and horizontal at
    `elev_mm` — and that is exactly what the witness reads back from the
    built element.
    """
    oid = op["id"]
    s = _safe(oid)
    _version_guard(ver, oid, "AreaLoad.Create")
    _zero_guard(op, oid, ("fx_n_per_m2", "fy_n_per_m2", "fz_n_per_m2"))
    ring = op["outline"]
    z = op["elev_mm"]
    f = (_nz(op, "fx_n_per_m2"), _nz(op, "fy_n_per_m2"), _nz(op, "fz_n_per_m2"))
    ty_res, ty_idexpr = _load_type_cs(
        op, s, oid, ver, "Autodesk.Revit.DB.Structure.AreaLoadType",
        "площадная нагрузка", isolation)
    lc_res, lc_idexpr = _load_case_cs(op, s, oid, ver, isolation)
    fvec = _si_vec(f, "NewtonsPerSquareMeter")
    n = len(ring)
    edges = "".join(
        f"__ol_{s}.Append(Line.CreateBound("
        f"P({ring[k][0]}, {ring[k][1]}, {z}), "
        f"P({ring[(k + 1) % n][0]}, {ring[(k + 1) % n][1]}, {z})));\n"
        for k in range(n))
    decl = f"Autodesk.Revit.DB.Structure.AreaLoad __el_{s} = null;"
    create = (
        f"// create_area_load {cs_line_comment_fragment(oid)}\n"
        f"{ty_res}\n{lc_res}\n"
        f"CurveLoop __ol_{s} = new CurveLoop();\n"
        + edges +
        f"var __loops_{s} = new List<CurveLoop>();\n"
        f"__loops_{s}.Add(__ol_{s});\n"
        f"__el_{s} = Autodesk.Revit.DB.Structure.AreaLoad.Create(doc, "
        f"__loops_{s}, {fvec}, __ty_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('AreaLoad.Create вернул null'), isolation)} }}\n"
        + _orient_and_set_cs(
            s, oid, isolation, "ForceVector1", fvec,
            extra=f"__el_{s}.LoadCaseId = __lc_{s}.Id;\n")
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    expected = ", ".join(f"{c}" for pt in ring for c in (pt[0], pt[1]))
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="loop_vertices",
            reader_cs=(f"    var __lps_{s} = __el_{s}.GetLoops();\n"
                       f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            # TWO DIAGNOSES, KEPT APART. The number of rings/vertices and
            # their position are different causes: Revit canonicalizes the
            # ring (the starting vertex and the winding direction are its
            # own business), so a positional comparison would blame a
            # correct load. The check runs as a SET: every ordered vertex
            # must be found among the returned ones, and the vertex count
            # must match — together this rules out an extra, a lost, and a
            # shifted vertex alike.
            verdict_cs=(
                f"    if (__lps_{s} == null || __lps_{s}.Count != 1)\n"
                f"        __post.Add({_cs(oid + ': GetLoops построенной нагрузки вернул не одно кольцо (geometry)')});\n"
                f"    else\n    {{\n"
                f"        var __vs_{s} = new List<XYZ>();\n"
                f"        foreach (Curve __c_{s} in __lps_{s}[0]) __vs_{s}.Add(__c_{s}.GetEndPoint(0));\n"
                f"        double[] __ex_{s} = new double[] {{ {expected} }};\n"
                f"        bool __bad_{s} = __vs_{s}.Count != {n};\n"
                f"        for (int __i = 0; __i < {n} && !__bad_{s}; __i++)\n"
                f"        {{\n"
                f"            bool __hit = false;\n"
                f"            for (int __j = 0; __j < __vs_{s}.Count; __j++)\n"
                f"                if (Math.Abs(__vs_{s}[__j].X - U(__ex_{s}[__i * 2])) <= __vtol_{s}\n"
                f"                    && Math.Abs(__vs_{s}[__j].Y - U(__ex_{s}[__i * 2 + 1])) <= __vtol_{s}\n"
                f"                    && Math.Abs(__vs_{s}[__j].Z - U({z})) <= __vtol_{s})\n"
                f"                    __hit = true;\n"
                f"            if (!__hit) __bad_{s} = true;\n"
                f"        }}\n"
                f"        if (__bad_{s}) __post.Add({_cs(oid + ': вершины кольца построенной нагрузки не совпали с заказанным контуром на отметке elev_mm (geometry)')});\n"
                f"    }}\n"),
            message="loop vertices mismatch (geometry)",
            style="else_block"),
        _orient_witness(s, oid),
        _vector_witness(s, oid, "ForceVector1", "NewtonsPerSquareMeter", f,
                        tolerance("create_area_load", "force_n_per_m2"),
                        "вектор площадной силы", key="force_vector"),
        _load_case_witness(s, oid, lc_idexpr),
        _load_type_witness(s, oid, ty_idexpr),
    ]
    # The area is an OBSERVATION, not a promise: Revit derives it from the
    # same rings the witness has already pinned vertex by vertex. A
    # separate obligation on it would require a second, area-based
    # tolerance for the sake of a consequence of a fact already proven —
    # that is, a number that there is nowhere to derive from.
    area_rb = (f"    try {{ __rb[\"area_m2\"] = Math.Round("
               f"UnitUtils.ConvertFromInternalUnits(__el_{s}.Area, "
               f"UnitTypeId.SquareMeters), 3); }} catch {{ }}\n")
    return decl, create, checks, _load_readback(s, oid, stamp, extra=area_rb)


# ── create_path_of_travel ────────────────────────────────────────────────────

def emit_path_of_travel(op: dict, ver: str, stamp: str,
                        isolation: str = "atomic") -> tuple[str, str, list, str]:
    """Analysis.PathOfTravel.Create(View, XYZ, XYZ, out PathOfTravelCalculationStatus).

    THE OVERLOAD WITH A STATUS IS TAKEN DELIBERATELY. Without it, `null`
    would mean several different things at once ("no route", "points too
    close", "the view is cropped", "too much geometry"), and the refusal
    would name the consequence instead of the cause. The
    `PathOfTravelCalculationStatus` enumeration is identical across all six
    versions (12 members, checked by name), so the status travels into the
    refusal text as is.

    THE STATUS IS CHECKED IN create, NOT IN post, and this is not a matter
    of taste: `Success` is the precondition for everything that follows
    making sense. `ResultAffectedByCrop`, for example, will return an
    ELEMENT with a route computed against a cropped view, that is, a
    demonstrably wrong route; it would pass a postcondition about length.
    """
    oid = op["id"]
    s = _safe(oid)
    ns = "Autodesk.Revit.DB.Analysis"
    x0, y0, _ = _pt3(op["p0_mm"])
    x1, y1, _ = _pt3(op["p1_mm"])
    # The straight line between the ordered points is IN PLAN, because the
    # API discards the third coordinate per the documentation. The number
    # is computed HERE and travels as a literal in millimeters, converted
    # in the C# by the same `U()` as the points themselves.
    straight_mm = math.hypot(x1 - x0, y1 - y0)
    # `__vw_<s>` and `__vp_<s>` are declared in decl, not set up in create:
    # create bodies are wrapped in their own scope under per_op isolation,
    # and a declaration from there is a CS0103 on the user's machine
    # (`tests/test_emitter_scope_contract.py`). Only create reads them
    # here, but this file's rule is to declare in decl everything that
    # survives the seam.
    decl = (f"{ns}.PathOfTravel __el_{s} = null;\n"
            f"View __vw_{s} = null;\n"
            f"ViewPlan __vp_{s} = null;")
    create = (
        f"// create_path_of_travel {cs_line_comment_fragment(oid)}\n"
        # THE VIEW IS RESOLVED BY THE SAME HELPER AS FOR ANNOTATIONS, not
        # its own: it already refuses with a typed error on `by=ref` (no
        # KIR op creates a View, so `as View` there is a guaranteed
        # CS0039, measured 28.07), and it already checks that the id
        # resolves to a view SPECIFICALLY. A private copy would diverge
        # from it on the very first edit.
        + _annot_view_res(op, s, ver, oid, isolation) + "\n"
        f"__vp_{s} = __vw_{s} as ViewPlan;\n"
        f"if (__vp_{s} == null || __vp_{s}.IsTemplate "
        f"|| __vp_{s}.ViewType != ViewType.FloorPlan) {{ "
        f"{refuse_stmt(oid, _cs('in_view не план этажа — PathOfTravel.Create принимает только вид в плане (документировано ArgumentException «View is not a floor plan view»)'), isolation)} }}\n"
        f"{ns}.PathOfTravelCalculationStatus __potstatus_{s};\n"
        f"__el_{s} = {ns}.PathOfTravel.Create(__vp_{s}, "
        f"P({x0}, {y0}, 0), P({x1}, {y1}, 0), out __potstatus_{s});\n"
        f"if (__el_{s} == null) {{ "
        f"{refuse_stmt(oid, _cs('маршрут между заданными точками не найден, статус расчёта: ') + f' + __potstatus_{s}.ToString()', isolation)} }}\n"
        f"if (__potstatus_{s} != {ns}.PathOfTravelCalculationStatus.Success) {{ "
        f"{refuse_stmt(oid, _cs('расчёт маршрута завершился не успехом, статус: ') + f' + __potstatus_{s}.ToString()', isolation)} }}\n"
        + _stamp_block(f"__el_{s}", f"{stamp}:{oid}"))
    # `by=ref` never arrives here: `_annot_view_res` would have refused
    # upstream. So the expected view id is a literal, and that is exactly
    # what the witness needs: the comparison must be against what was
    # ASKED FOR, not against a variable the emitter put into its own scope
    # (and which is no longer in scope in post anyway).
    view_id_expr = _cs(str(op["in_view"]["value"]))
    checks: list[WitnessCheck] = [
        WitnessCheck(
            obligation_key="endpoints",
            reader_cs=(f"    var __ps_{s} = __el_{s}.PathStart;\n"
                       f"    var __pe_{s} = __el_{s}.PathEnd;\n"
                       f"    double __vtol_{s} = doc.Application.VertexTolerance;\n"),
            # Z IS NOT CHECKED, PER THE DOCUMENTATION, NOT OUT OF LENIENCY:
            # «The input Z coordinates are ignored and set to the view's
            # level elevation». Checking it would mean demanding of Revit
            # exactly what it explicitly promises not to do — and
            # rejecting a correct route.
            verdict_cs=(
                f"    if (__ps_{s} == null || __pe_{s} == null\n"
                f"        || Math.Abs(__ps_{s}.X - U({x0})) > __vtol_{s}\n"
                f"        || Math.Abs(__ps_{s}.Y - U({y0})) > __vtol_{s}\n"
                f"        || Math.Abs(__pe_{s}.X - U({x1})) > __vtol_{s}\n"
                f"        || Math.Abs(__pe_{s}.Y - U({y1})) > __vtol_{s})\n"
                f"        __post.Add({_cs(oid + ': PathStart/PathEnd построенного маршрута не совпали с заданными точками в плане (geometry)')});\n"),
            message="path endpoints mismatch (geometry)",
            style="guard"),
        WitnessCheck(
            obligation_key="route",
            reader_cs=(f"    var __cvs_{s} = __el_{s}.GetCurves();\n"
                       f"    double __len_{s} = 0.0;\n"
                       f"    if (__cvs_{s} != null)\n"
                       f"        for (int __k = 0; __k < __cvs_{s}.Count; __k++)\n"
                       f"            __len_{s} += __cvs_{s}[__k].Length;\n"),
            # WHAT IS ASSERTED HERE, AND WHAT IS NOT. Revit computes the
            # route's shape from the view's obstacles, and there is
            # nothing to check "did it go around them correctly" with: we
            # have no independent model of the obstacles, and comparing
            # Revit's output against Revit's output is meaningless. Two
            # facts are checked that do NOT DEPEND on its calculation: the
            # route exists as geometry (an empty curve list with a green
            # status is an element with no content), and it is not shorter
            # than the straight line between its own ends. The second is a
            # geometrically impossible state, that is, a genuine failure;
            # equality here would be an invention.
            verdict_cs=(
                f"    if (__cvs_{s} == null || __cvs_{s}.Count < 1)\n"
                f"        __post.Add({_cs(oid + ': маршрут построен без единой кривой (geometry)')});\n"
                f"    else if (__len_{s} < U({straight_mm}) - __vtol_{s})\n"
                f"        __post.Add({_cs(oid + ': длина построенного маршрута меньше прямой между заданными точками (geometry)')});\n"),
            message="route is empty or shorter than the straight line (geometry)",
            style="guard"),
        WitnessCheck(
            obligation_key="owner_view",
            reader_cs=f"    var __ov_{s} = __el_{s}.OwnerViewId;\n",
            verdict_cs=(
                f"    if (__ov_{s} == null || __ov_{s}.ToString() != {view_id_expr})\n"
                f"        __post.Add({_cs(oid + ': построенный маршрут принадлежит не заказанному виду (topology)')});\n"),
            message="owner view mismatch (topology)",
            style="guard"),
    ]
    readback = (
        f"// witness {cs_line_comment_fragment(oid)}\n{{\n"
        f"    var __rb = new Dictionary<string, object>();\n"
        f"    __rb[\"id\"] = __el_{s}.Id.ToString();\n"
        + _stamp_readback(f"__el_{s}") +
        f"    try {{ __rb[\"start_mm\"] = new double[] {{ "
        f"Math.Round(MM(__el_{s}.PathStart.X), 1), "
        f"Math.Round(MM(__el_{s}.PathStart.Y), 1), "
        f"Math.Round(MM(__el_{s}.PathStart.Z), 1) }}; }} catch {{ }}\n"
        f"    try {{ __rb[\"end_mm\"] = new double[] {{ "
        f"Math.Round(MM(__el_{s}.PathEnd.X), 1), "
        f"Math.Round(MM(__el_{s}.PathEnd.Y), 1), "
        f"Math.Round(MM(__el_{s}.PathEnd.Z), 1) }}; }} catch {{ }}\n"
        f"    try {{ var __rbc = __el_{s}.GetCurves();\n"
        f"        double __rbl = 0.0;\n"
        f"        if (__rbc != null)\n"
        f"            for (int __q = 0; __q < __rbc.Count; __q++) __rbl += __rbc[__q].Length;\n"
        f"        __rb[\"segments\"] = __rbc == null ? 0 : __rbc.Count;\n"
        f"        __rb[\"length_mm\"] = Math.Round(MM(__rbl), 1);\n"
        f"    }} catch {{ }}\n"
        f"    try {{ __rb[\"view_id\"] = __el_{s}.OwnerViewId.ToString(); }} catch {{ }}\n"
        f"    __results[{_cs(oid)}] = __rb;\n}}")
    return decl, create, checks, readback


#: WHAT THIS SPOKE EMITS IS DECLARED HERE, NOT IN THE HUB (02.09.2026).
#: Previously the "op -> body" correspondence lived in the handwritten
#: `authoring._EMITTERS`, with the body here, and a thin wrapper in the hub
#: linked the two (41 of them across 19 satellites). Two records of one
#: fact in different files are this tree's named defect; now there is ONE
#: record, and the hub ASKS for it.
EMITTERS = {
    "create_area_load": emit_area_load,
    "create_line_load": emit_line_load,
    "create_path_of_travel": emit_path_of_travel,
    "create_point_load": emit_point_load,
}
