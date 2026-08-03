"""KIR docspace — the VIEW-SPACE type core (Documentation invention, 2026-07-17).

THE INVENTION, in code: the model lives in ONE 3D world space; annotation lives
in MANY 2D view spaces (one per view/sheet). A dimension/tag/text has NO 3D
coordinate — it lies in the 2D plane of a specific view and REFERENCES 3D
elements. Confusing the two spaces is the error class this module makes
UNEXPRESSIBLE, exactly like "window in the air" (v1) or "number without units"
(set_param): PtView2D and PtModel3D are distinct types that never substitute.

This is the type spine the annotation ops (tag/dimension/text/...) validate
against; the view-space→XYZ materialization is emitted as C# from the resolved
view basis at runtime (see KIR_DOC_SPEC.md §эмиттер) — never hardcoded, because
the ViewTransform is only known after ground. A pure-python proof of the core
type laws so the invention is fixed in CODE, not only prose. Domain-agnostic:
annotation ops import check_pt_view2d / reject_model3d_in_annotation from here.
"""
from __future__ import annotations

from typing import Any, Optional

from kukai.ir.diag import Diagnostic, TYPE_BAD_TYPE, TYPE_BOUNDS
from kukai.ir.emit_utils import is_finite_number

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
#    known after ground; §эмиттер of KIR_DOC_SPEC.md) ──────────────────────────

def emit_view2d_to_xyz_cs(view_var: str, u: float, w: float) -> str:
    """C# expression placing a view-space [u,v] mm point into 3D via the view's
    own basis (Origin + u*RightDirection + v*UpDirection). This is the invention
    materialized: the 2D sheet coordinate becomes a world point ONLY through the
    resolved view's transform, never by hardcoding a Z."""
    return (f"({view_var}.Origin "
            f"+ {view_var}.RightDirection.Multiply(U({round(u, 2)})) "
            f"+ {view_var}.UpDirection.Multiply(U({round(w, 2)})))")


def view_scale_to_model_mm(sheet_mm: float, view_scale: int) -> float:
    """Compiler-owned size-from-intent: a text height given as mm-on-SHEET maps
    to mm-in-MODEL by the view scale (1:50 -> ×50). The model states the sheet
    size; the compiler computes the world size (like units in v1, like
    diameter-from-flow in CONNECT)."""
    if not isinstance(view_scale, int) or view_scale <= 0:
        raise ValueError("view_scale must be a positive int (denominator of 1:N)")
    return sheet_mm * view_scale
