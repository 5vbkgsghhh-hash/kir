"""Shared geometry laws for elements hosted by authoring operations.

This module is deliberately below planning and grounding. Both stages need
to apply the same law once wall endpoints are numeric, but neither stage may
import the other merely to reuse it.
"""
from __future__ import annotations

import math

from kukai.ir.diag import Diagnostic


def hosted_offset_check(hosted: dict, wall: dict, host_id: str,
                        idx: int | None, diags: list) -> bool:
    """Reject a hosted element whose offset lies beyond its wall.

    Planning calls this for literal endpoints; grounding calls it after
    model-relative addresses have become numbers. The normalized host shape
    is attached for the legacy emitter as part of the same law.
    """
    arc = wall.get("arc")
    if isinstance(arc, dict):
        length = abs(float(arc["radius_mm"]) * (
            float(arc["end_angle_rad"]) - float(arc["start_angle_rad"])))
    else:
        length = math.hypot(wall["p1_mm"][0] - wall["p0_mm"][0],
                            wall["p1_mm"][1] - wall["p0_mm"][1])
    offset = hosted.get("offset_mm", 0)
    if offset > length:
        diags.append(Diagnostic(
            code="KIR-T002", op_index=idx, op_id=hosted["id"],
            field_name="offset_mm", expected=f"0..{length:.0f}", got=offset,
            message_ru=(f"offset {offset}мм за пределами стены "
                        f"«{host_id}» ({length:.0f}мм)")))
        return False
    host_shape = {"p0_mm": wall["p0_mm"], "p1_mm": wall["p1_mm"]}
    if isinstance(arc, dict):
        host_shape["arc"] = arc
    hosted["__host_wall__"] = host_shape
    return True
