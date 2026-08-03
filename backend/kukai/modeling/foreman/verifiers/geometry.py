"""Geometry verifier — grid-bounds, collisions, level-binding feasibility."""
from __future__ import annotations
import re

from kukai.modeling.bridge.mock_revit_session import MockRevitSession
from kukai.modeling.foreman.toolbox import ForemanToolBox
from kukai.modeling.schemas.foreman import ReviewIssue, ReviewSeverity
from kukai.modeling.schemas.llm import CodeProposal
from kukai.modeling.schemas.tasks import TaskBrief


_RE_XYZ = re.compile(
    r'new\s+XYZ\s*\(\s*(?P<x>[-\d.]+)\s*,\s*(?P<y>[-\d.]+)\s*,\s*(?P<z>[-\d.]+)\s*\)',
)
_RE_ZERO_LINE = re.compile(
    r'Line\.CreateBound\s*\(\s*'
    r'new\s+XYZ\s*\(\s*(?P<x1>[-\d.]+)\s*,\s*(?P<y1>[-\d.]+)\s*,\s*(?P<z1>[-\d.]+)\s*\)\s*,\s*'
    r'new\s+XYZ\s*\(\s*(?P<x2>[-\d.]+)\s*,\s*(?P<y2>[-\d.]+)\s*,\s*(?P<z2>[-\d.]+)\s*\)\s*\)',
)
_LEVEL_DELTA_MM = 10.0
_COLLISION_RADIUS_MM = 1.0

# Wave 7.5 Fix #3: only these categories use point-based collision detection.
# Line-based (walls, beams, partitions) and polygon-based (floors, ceilings)
# elements naturally share endpoints with their hosts/neighbors so single-
# point collision tests produce false positives. Real geometric collision
# for those uses bounding boxes via L6 GeometryGate post-execute.
_POINT_BASED_CATEGORIES: frozenset[str] = frozenset({
    "OST_StructuralColumns",
    "OST_Columns",
    "OST_Doors",
    "OST_Windows",
    "OST_GenericModel",
    "OST_StructuralFoundation",
})


def _block(category: str, detail: str) -> ReviewIssue:
    return ReviewIssue(
        severity=ReviewSeverity.BLOCKING, category=category, detail=detail,
        verifier_source="geometry",
    )


def _warn(category: str, detail: str) -> ReviewIssue:
    return ReviewIssue(
        severity=ReviewSeverity.WARNING, category=category, detail=detail,
        verifier_source="geometry",
    )


async def check_geometry(
    proposal: CodeProposal,
    brief: TaskBrief,
    toolbox: ForemanToolBox,
    session: MockRevitSession | None = None,
) -> list[ReviewIssue]:
    """Verify geometry intent.

    Wave 7.5 Fix #3 (Audit B5): the `_RE_XYZ` regex matches only numeric XYZ
    literals (e.g. `new XYZ(0.0, 0.0, 0.0)`). Production code typically uses
    variables — `new XYZ(x_ft, y_ft, z_ft)` after a
    `UnitUtils.ConvertToInternalUnits` line — so regex finds zero points and
    silently skips collision checks. Fix: include `brief.placement_point`
    in the COLLISION candidate set so cross-task overlaps are caught even
    when C# uses variables.

    Scoping rules (avoid false positives the sandbox surfaced):
      - Grid bounds + level drift checks remain regex-only. They depend on
        project-specific grids that mocks default to (0..6000) and the brief
        bay may legitimately exceed those defaults.
      - Same-category collision only blocks for POINT-based categories
        (columns, doors, windows). Line/polygon-based categories (walls,
        beams, floors, partitions) naturally share endpoints — checking them
        as point collisions produces false positives every time.
    """
    issues: list[ReviewIssue] = []

    grids = await toolbox.list_grids()
    h = [g.position_mm for g in grids if g.axis == "horizontal"]
    v = [g.position_mm for g in grids if g.axis == "vertical"]

    # csharp_literal candidate points — used by grid bounds + level drift.
    csharp_points: list[tuple[float, float, float]] = []
    for m in _RE_XYZ.finditer(proposal.csharp_code):
        try:
            csharp_points.append(
                (float(m["x"]), float(m["y"]), float(m["z"]))
            )
        except (TypeError, ValueError):
            continue

    # 1. Grid bounds (regex-only — relies on project-grid bounds matching
    # the C# coords' coordinate space; brief.placement_point uses different
    # scale assumptions in mock environments).
    for (x, y, _) in csharp_points:
        if h and not (min(h) <= y <= max(h)):
            issues.append(_block("geometry_out_of_grid_bounds",
                f"point (x={x}, y={y}) outside horizontal range [{min(h)}, {max(h)}]"))
            break
        if v and not (min(v) <= x <= max(v)):
            issues.append(_block("geometry_out_of_grid_bounds",
                f"point (x={x}, y={y}) outside vertical range [{min(v)}, {max(v)}]"))
            break

    # 2. Zero-length curves (regex-only — can't extract from variable form)
    for m in _RE_ZERO_LINE.finditer(proposal.csharp_code):
        if (m["x1"], m["y1"], m["z1"]) == (m["x2"], m["y2"], m["z2"]):
            issues.append(_block("zero_length_curve",
                f"Line.CreateBound with identical endpoints at "
                f"({m['x1']}, {m['y1']}, {m['z1']})"))
            break

    # 3. Level-binding drift (warning) — regex-only
    target_z = brief.placement_point.z
    for (_, _, z) in csharp_points:
        if abs(z - target_z) > _LEVEL_DELTA_MM:
            issues.append(_warn("level_binding_drift",
                f"z={z} drifts from brief.placement_point.z={target_z} "
                f"by > {_LEVEL_DELTA_MM}mm"))
            break

    # 4. Collisions (only with session, only for point-based categories).
    # Wave 7.5 Fix #3: include brief.placement_point in candidates so
    # variable-form C# still gets cross-task collision detection.
    # Z is checked too — columns on different floors share XY but differ
    # by floor height. Use the level-delta tolerance for Z matching.
    if session is not None and brief.expected_elements.category in _POINT_BASED_CATEGORIES:
        my_category = brief.expected_elements.category
        bp = brief.placement_point
        collision_candidates: list[tuple[float, float, float, str]] = [
            (bp.x, bp.y, bp.z, "brief.placement_point"),
        ]
        for (x, y, z) in csharp_points:
            collision_candidates.append((x, y, z, "csharp_literal"))

        placed_with_z = [
            (el.location_mm[0], el.location_mm[1], el.location_mm[2], el.category)
            for el in session.list_placed_elements()
        ]
        collision_found = False
        for (x, y, z, src) in collision_candidates:
            for (px, py, pz, pcat) in placed_with_z:
                if pcat != my_category:
                    continue  # cross-category overlap = valid architecture
                if abs(z - pz) > _LEVEL_DELTA_MM:
                    continue  # different floor / level — not a collision
                if (abs(x - px) <= _COLLISION_RADIUS_MM
                        and abs(y - py) <= _COLLISION_RADIUS_MM):
                    issues.append(_block("placement_collision",
                        f"point (x={x}, y={y}, z={z}, src={src}) collides with placed "
                        f"element at ({px}, {py}, {pz}) in same category {my_category}"))
                    collision_found = True
                    break
            if collision_found:
                break

    return issues
