"""KIR docspace — the VIEW-SPACE type core (Documentation invention, 2026-07-17).

THE INVENTION, in code: the model lives in ONE 3D world space; annotation lives
in MANY 2D view spaces (one per view/sheet). A dimension/tag/text has NO 3D
coordinate — it lies in the 2D plane of a specific view and REFERENCES 3D
elements. Confusing the two spaces is the error class this module makes
UNEXPRESSIBLE, exactly like "window in the air" (v1) or "number without units"
(set_param): PtView2D and PtModel3D are distinct types that never substitute.

This is the type spine the annotation ops (tag/dimension/text/...) validate
against; the view-space→XYZ materialization is emitted as C# from the resolved
view basis at runtime (see KIR_DOC_SPEC.md §emitter) — never hardcoded, because
the ViewTransform is only known after ground. A pure-python proof of the core
type laws so the invention is fixed in CODE, not only prose. Domain-agnostic:
annotation ops import check_pt_view2d / reject_model3d_in_annotation from here.
"""
from __future__ import annotations

from typing import Any, Optional

from kir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS
from kir.emit_utils import is_finite_number

# Coordinate sanity, NOT a "flew-away tag" guard. Was 10 000 mm on the theory
# that a larger value must be a 3D coordinate leaked into a 2D field. Measured
# 27.07 on a real project and refuted: a plan view reports `Origin == (0,0,0)`
# with world-aligned Right/Up, so `[u,v]` there ARE the model's X,Y — and that
# building's walls sit 82 693 … 110 160 mm away in Y. The old bound therefore
# refused to annotate EVERY element of a real building.
#
# Magnitude cannot separate "model coordinate pasted into a view field" from
# "legitimate annotation far from the view origin" — for a plan they are the
# same numbers. What DOES separate them is the point's arity, and that is
# checked by is_pt_model3d/check_pt_view2d independently. So only the check
# that can discriminate is kept; this one falls back to the same workable-extent
# limit model points already use (authoring._COORD_LIMIT_MM), which still
# catches unit errors and garbage.
_SHEET_LIMIT_MM = 16_000_000.0


def _num(x) -> bool:
    return is_finite_number(x)


def is_pt_view2d(v: Any) -> bool:
    """A view-space point is EXACTLY [u, v] mm — two components. A third
    component is the signature of a 3D point in a 2D field, and is rejected."""
    return isinstance(v, list) and len(v) == 2 and all(_num(c) for c in v)


def is_pt_model3d(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 3 and all(_num(c) for c in v)


def check_pt_view2d(v: Any, oid, field: str, diags: list) -> Optional[list]:
    """Returns [u, v] floats, or None with a typed diagnostic. A 3-component
    (3D) value is refused with an explicit space-confusion message — this is
    the load-bearing law of the invention."""
    if is_pt_model3d(v):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=v,
            message_ru=(f"{field}: получена 3D-точка [x,y,z] в поле пространства ВИДА — "
                        "аннотация живёт в 2D-плоскости вида, дайте [u,v] мм листа")))
        return None
    if not is_pt_view2d(v):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=v,
            message_ru=f"{field}: точка вида — [u,v] мм в плоскости вида"))
        return None
    u, w = float(v[0]), float(v[1])
    if abs(u) > _SHEET_LIMIT_MM or abs(w) > _SHEET_LIMIT_MM:
        diags.append(Diagnostic(
            code=TYPE_BOUNDS, op_id=oid, field_name=field, got=v,
            expected=f"|u|,|v| <= {_SHEET_LIMIT_MM:.0f} мм",
            message_ru=(f"{field}: координата вне рабочего предела модели "
                        "(~16 км) — похоже на ошибку единиц")))
        return None
    return [u, w]


def reject_model3d_in_annotation(v: Any, oid, field: str, diags: list) -> bool:
    """Guard for annotation params that must NEVER carry a 3D point. Returns
    True if a violation was recorded (a 3D point where a view-space one belongs)."""
    if is_pt_model3d(v):
        diags.append(Diagnostic(
            code=TYPE_BAD_TYPE, op_id=oid, field_name=field, got=v,
            message_ru=f"{field}: 3D-точка недопустима в аннотации (пространство вида ≠ модель)"))
        return True
    return False


# ── view-space → XYZ materialization, emitted as C# (the runtime basis is only
#    known after ground; §emitter of KIR_DOC_SPEC.md) ──────────────────────────

def _view2d_to_xyz_expr(view_var: str, u_cs: str, v_cs: str) -> str:
    """The ONE place the forward view→world formula is written.

    Established 2026-08-09, when the family gained a SECOND consumer of the
    formula (fill, which sends not a single point through the view but a
    whole loop). While there was only one consumer, "one formula" held simply
    because there was nowhere else to write it; with a second consumer it
    became an author's discipline instead — the same thing that happened to
    CONTOUR with an edge's body (see ``contour._edge_curve_cs``), where two
    divergences out of three would have been invisible. ``u_cs``/``v_cs`` are
    C# EXPRESSIONS, not numbers, because for a loop the coordinate arrives as a
    local function's parameter rather than a literal.
    """
    return (f"({view_var}.Origin "
            f"+ {view_var}.RightDirection.Multiply({u_cs}) "
            f"+ {view_var}.UpDirection.Multiply({v_cs}))")


def emit_view2d_to_xyz_cs(view_var: str, u: float, w: float) -> str:
    """C# expression placing a view-space [u,v] mm point into 3D via the view's
    own basis (Origin + u*RightDirection + v*UpDirection). This is the invention
    materialized: the 2D sheet coordinate becomes a world point ONLY through the
    resolved view's transform, never by hardcoding a Z."""
    return _view2d_to_xyz_expr(
        view_var, f"U({round(u, 2)})", f"U({round(w, 2)})")


def emit_view2d_to_uv_cs(u: float, w: float) -> str:
    """The ONE place a VIEW-space point is printed as ``UV``.

    Established 2026-09-04 together with the units fix for the spatial tag.
    ``UV`` is not a third kind of coordinate — it is the same view-space point
    WITHOUT a basis: for ``NewRoomTag``/``NewSpaceTag``/``NewAreaTag`` (and for
    ``NewRoom``/``NewSpace``) Revit already knows the view or level and asks
    only for a pair of numbers. And since it is the same point, its units must
    be the same as ``emit_view2d_to_xyz_cs``'s: INTERNAL, through ``U()``.

    🔴 WHY A FUNCTION, NOT AN INLINE LITERAL. It was exactly an inline literal
    that let the law diverge. `authoring._emit_tag` printed BOTH branches of
    one op: the ordinary tag went through `emit_view2d_to_xyz_cs` and got
    `U(3000.0)`, while the spatial one got `new UV(3000.0, 800.0)` — raw
    millimeters. One op, one `at` point, two different verdicts about units in
    neighboring lines of the same golden file (`auth_annotation.golden.cs`,
    lines 360 and 380). Revit reads `UV` in internal units, so the tag
    travelled 304.8 times too far.

    THIS IS ABOUT UNITS, NOT ABOUT AXES. Which axes `UV` uses for
    `NewRoomTag` is not settled by compilation and has not been checked
    live — that is exactly what is recorded at the top of the
    `authoring._emit_tag` branch, and nothing is assumed here either: the
    axis is still guarded by the `head_at` witness, which reads
    `TagHeadPosition` back through the same view basis. The mm → internal
    conversion is unambiguous and axis-independent: it already stands in the
    sibling branch of the SAME op and in `room_emit` (`NewRoom`, `NewSpace` —
    the same `doc.Create` and the same `UV`).
    """
    return f"new UV(U({round(u, 2)}), U({round(w, 2)}))"


def emit_view2d_point_fn_cs(view_var: str, fn_name: str,
                            u_param: str = "__u", v_param: str = "__v") -> str:
    """A local C# function ``fn_name(u, v) -> XYZ`` — the same forward formula.

    Needed where there are MANY points and they are not literals: a fill's
    loop lies entirely in the view plane, and expanding the expression at
    every vertex would multiply the formula across the emission. Declared in
    ``decl`` (the scope contract: ``per_op`` wraps create in its own scope),
    so both the creation block and the postcondition block can see it.
    """
    return (f"XYZ {fn_name}(double {u_param}, double {v_param}) => "
            f"{_view2d_to_xyz_expr(view_var, f'U({u_param})', f'U({v_param})')};")


def emit_xyz_to_view2d_cs(view_var: str, point_cs: str, rel_var: str,
                          u_var: str, v_var: str, indent: str = "") -> str:
    """The INVERSE formula, and it must be IDENTICAL to the forward one, not
    merely similar.

    ``rel = P - Origin; u = MM(rel·Right); v = MM(rel·Up)`` — exactly the
    inversion of ``Origin + u*Right + v*Up`` in the view's orthonormal basis.
    The law is recorded in KIR CLAUDE.md ("An inverse must be identical, not
    similar"); until 2026-08-09 it held only because both sides were typed by
    hand in two emitters — the tag's and the text's — and they moved here
    BYTE FOR BYTE (the golden files did not move).
    """
    return (f"{indent}var {rel_var} = {point_cs} - {view_var}.Origin;\n"
            f"{indent}double {u_var} = MM({rel_var}.DotProduct({view_var}.RightDirection));\n"
            f"{indent}double {v_var} = MM({rel_var}.DotProduct({view_var}.UpDirection));\n")


def view_scale_to_model_mm(sheet_mm: float, view_scale: int) -> float:
    """Compiler-owned size-from-intent: a text height given as mm-on-SHEET maps
    to mm-in-MODEL by the view scale (1:50 -> ×50). The model states the sheet
    size; the compiler computes the world size (like units in v1, like
    diameter-from-flow in CONNECT)."""
    if not isinstance(view_scale, int) or view_scale <= 0:
        raise ValueError("view_scale must be a positive int (denominator of 1:N)")
    return sheet_mm * view_scale
