"""Opt-in authored datum/axis surfaces, never native faces, bodies or clashes.

One CREATE-only flat program is planned once. Geometry uses that normalized
contract; source hashes always bind the original input, including omissions.
Only earlier directly authored literal levels determine Z. No model, OCP,
grounding, guessed thickness, hole repair or implicit program rewrite occurs.
"""
from __future__ import annotations

import math
from types import MappingProxyType

from kir import contour, spec
from kir.project import ProjectError, _hash, _object, _thaw
from kir.registry_base import EffectKind


SURFACE_SCHEMA = "kir-reference-surface/1"
SURFACE_POLICY = "authored_straight_reference_surface/1"
SURFACE_CAPABILITY = "display_authored_reference_surfaces/1"
SURFACE_CLAIMS = MappingProxyType({
    "geometry_basis": "authored_axis_or_contour",
    "vertical_placement": "authored_levels_and_offsets_not_observed",
    "native_equivalence": "not_claimed", "native_execution": "not_run",
    "thickness": "not_represented", "hosted_openings": "not_represented",
    "joins": "not_represented", "clash_eligibility": "none",
    "bim_semantics": "not_verified", "containment": "not_claimed",
})
MAX_SURFACE_VERTICES = 4096
MAX_SURFACE_TRIANGLES = 4096
_TARGETS = {"create_wall": "wall_axis_surface", "create_floor_by_contour": "floor_datum_surface"}


class ReferenceSurfaceRefusal(ValueError):
    """Input cannot be addressed, or this bounded display policy cannot derive it."""

    def __init__(self, code, detail):
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _level(selector, index, indexed):
    if (type(selector) is not dict or set(selector) != {"by", "value"}
            or selector["by"] != "ref" or type(selector["value"]) is not str):
        raise ReferenceSurfaceRefusal("unresolved_level", "only an exact authored by:ref level selector is supported")
    earlier = indexed.get(selector["value"])
    if (earlier is None or earlier[0] >= index or earlier[1]["op"] != "create_level"
            or not _finite(earlier[1].get("elev_mm"))):
        raise ReferenceSurfaceRefusal("unresolved_level", "reference must identify an earlier directly authored literal create_level")
    return earlier[1]["elev_mm"], earlier[1]


def _point(value):
    return type(value) is list and len(value) == 2 and all(_finite(axis) for axis in value)


def _wall(raw, normalized, index, indexed):
    if raw.get("arc") is not None or not all(_point(raw.get(field)) for field in ("p0_mm", "p1_mm")):
        raise ReferenceSurfaceRefusal("unsupported_wall_axis", "only literal straight XY wall axes are represented")
    if raw.get("top_offset_mm") is not None and raw.get("top_level") is None:
        raise ReferenceSurfaceRefusal("orphan_top_offset", "top_offset_mm without top_level is not a surface height")
    level_z, base_level = _level(raw.get("level"), index, indexed)
    bottom = level_z + normalized.get("base_offset_mm", 0.)
    dependencies = [base_level]
    if raw.get("top_level") is not None:
        top_z, top_level = _level(raw["top_level"], index, indexed)
        top = top_z + normalized.get("top_offset_mm", 0.)
        dependencies.append(top_level)
    else:
        # Validation removes an explicit null instead of inserting a default.
        # _emit_wall uses this same registry fallback after normalization.
        top = bottom + normalized.get("height_mm", spec.DEFAULTS["wall"]["height_mm"])
    if not _finite(bottom) or not _finite(top) or top <= bottom:
        raise ReferenceSurfaceRefusal("invalid_vertical_span", "authored wall top must be strictly above its base")
    start, end = normalized["p0_mm"], normalized["p1_mm"]
    if start == end:
        raise ReferenceSurfaceRefusal("unsupported_wall_axis", "wall axis has zero length")
    return {"vertices_mm": [[*start, bottom], [*end, bottom], [*end, top], [*start, top]],
            "triangles": [[0, 1, 2], [0, 2, 3]]}, dependencies


def _floor(raw, normalized, index, indexed):
    from kir.compiler import KirRefusal
    from kir.mesh import _triangulate
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    from shapely.errors import GEOSException

    level_z, level = _level(raw.get("level"), index, indexed)
    z = level_z + normalized.get("height_offset_mm", 0.)
    diagnostics = []
    region = contour.validate_region(normalized["contour"], [], raw["id"], "contour", diagnostics)
    if region is None or not all(contour.edges_are_straight(ring) for ring in [region["outer"], *region["holes"]]):
        raise ReferenceSurfaceRefusal("unsupported_floor_contour", "only resolved straight contours and holes are represented")
    rings = [contour.edges_vertices(ring) for ring in [region["outer"], *region["holes"]]]
    if sum(map(len, rings)) > MAX_SURFACE_VERTICES:
        raise ReferenceSurfaceRefusal("surface_budget_exceeded", "floor input exceeds the reference-surface vertex budget")
    try:
        polygon = Polygon(rings[0], rings[1:])
        if not polygon.is_valid or polygon.is_empty or polygon.area <= 0 or not _finite(z):
            raise ReferenceSurfaceRefusal("unsupported_floor_contour", "floor datum polygon is invalid or degenerate")
        faces = _triangulate(polygon, "contour")
        if len(faces) > MAX_SURFACE_TRIANGLES:
            raise ReferenceSurfaceRefusal("surface_budget_exceeded", "floor triangulation exceeds the triangle budget")
        # The shared helper checks summed area. This consumer additionally
        # requires full triangle containment and topological union equality:
        # an equal-area omission/spill cannot pass, nor can a filled shaft.
        if (not faces or any(face.geom_type != "Polygon" or face.interiors
                or len(face.exterior.coords) != 4 or face.area <= 0 or not polygon.covers(face) for face in faces)
                or not unary_union(faces).equals(polygon)):
            raise ReferenceSurfaceRefusal("triangulation_coverage_mismatch", "triangle union differs from the declared floor region")
        vertices, triangles, indices = [], [], {}
        for face in faces:
            points = [list(point) for point in list(face.exterior.coords)[:-1]]
            a, b, c = points
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cross < 0:
                points.reverse()
            triangle = []
            for x, y in points:
                position = (x, y, z)  # No rounding, welding tolerance or coordinate repair.
                if position not in indices:
                    indices[position] = len(vertices)
                    vertices.append(list(position))
                triangle.append(indices[position])
            triangles.append(triangle)
        if len(vertices) > MAX_SURFACE_VERTICES:
            raise ReferenceSurfaceRefusal("surface_budget_exceeded", "floor triangulation exceeds the vertex budget")
        return {"vertices_mm": vertices, "triangles": triangles}, [level]
    except ReferenceSurfaceRefusal:
        raise
    except (KirRefusal, GEOSException, ValueError, TypeError, OverflowError) as error:
        raise ReferenceSurfaceRefusal("triangulation_failed", "floor triangulation could not establish exact region coverage") from error


def preview_reference_surfaces(program, *, bulk=False):
    """Return detached {previews, refusals}; at most one whole-batch plan call.

    Every addressed wall/floor is accounted for. An invalid batch plan refuses
    all its targets, not just the compiler's first diagnostic. Unaddressable
    input raises ReferenceSurfaceRefusal because an op-id map cannot name it.
    Other CREATE operations may coexist, but their hosted cuts, joins and final
    native effects are not evaluated. Query/mutation/delete, macros, nested
    members, phases/units/defaults and unknown envelopes are outside this policy.
    """
    from kir.compiler import KirRefusal, plan_program

    try:
        source = _thaw(_object(program, "surface_source_program"))
    except ProjectError as error:
        raise ReferenceSurfaceRefusal("invalid_source_program", "expected an inert finite JSON program object") from error
    operations = source.get("ops")
    if (type(operations) is not list or any(type(op) is not dict or type(op.get("id")) is not str
            or not op["id"] or type(op.get("op")) is not str for op in operations)
            or len({op["id"] for op in operations}) != len(operations)):
        raise ReferenceSurfaceRefusal("unaddressable_source_program", "unique explicit operation IDs and operation names are required")
    targets = [op for op in operations if op["op"] in _TARGETS]

    def refuse_all(code, detail):
        return {"previews": [], "refusals": {op["id"]: {"code": code, "detail": detail} for op in targets}}

    if type(bulk) is not bool:
        return refuse_all("invalid_policy", "bulk must be an explicit boolean")
    if source.get("ir_version") != spec.IR_VERSION:
        return refuse_all("unsupported_ir_version", "only the current IR/compiler contract is interpreted")
    # 🔴 `lineage` IS A LEGITIMATE ENVELOPE KEY, NOT "AN EXTRA FIELD". It is
    # read by the type-marker emitter (`emit_core.lineage_token`), and since
    # 06.09.2026 `geometry_materialization` puts it INTO EVERY envelope of a
    # materialized program, so that the type's address stays stable across a
    # neighboring edit. The closed list here did not know about it, and all
    # 15 operations got `unsupported_program_context` — a refusal TRUE to
    # its letter and FALSE in substance: the envelope is not "with defaults,
    # units, or phases", it is exactly the same flat CREATE envelope plus A
    # KIND NAME. Surfaces do not care about the kind — they are derived from
    # the operations' geometry, not from the type's address — so the name is
    # accepted rather than serving as grounds for refusal.
    #
    # WHY EXACTLY HERE, AND NOT BY ROLLING BACK `lineage`. The producer's
    # list is the ONLY one in the tree that did not know about this key:
    # `compiler.known_top` has accepted it since 06.09, the sandbox does not
    # even keep a second list (comment at `sandbox.py:392`), the recipe
    # projection and `staged_submission` work with the PROJECTION, not with
    # the authored envelope. The sweep of every list is in
    # `stageA/REPORT.md`, section "lineage regression".
    if (set(source) - {"ir_version", "intent", "ops", "lineage"}
            or any(spec.OPS.get(op["op"]) is None or spec.OPS[op["op"]].effect is not EffectKind.CREATE
                   or "member_ops" in op or "members" in op for op in operations)):
        return refuse_all("unsupported_program_context", "reference surfaces require a flat CREATE-only program without envelope defaults, units or phases")
    if not targets:
        return {"previews": [], "refusals": {}}
    try:
        planned = plan_program(source, bulk=bulk)
    except KirRefusal:
        return refuse_all("compiler_plan_refused", "the complete source program did not pass the current compiler planner")
    normalized = planned.to_ops()
    if [(op["id"], op["op"]) for op in normalized] != [(op["id"], op["op"]) for op in operations]:
        return refuse_all("unsupported_program_context", "planning changed operation identity/cardinality; no derived source mapping is guessed")
    indexed = {op["id"]: (index, op) for index, op in enumerate(operations)}
    previews, refusals = [], {}
    for index, (raw, norm) in enumerate(zip(operations, normalized, strict=True)):
        if raw["op"] not in _TARGETS:
            continue
        try:
            mesh, dependencies = (_wall if raw["op"] == "create_wall" else _floor)(raw, norm, index, indexed)
            dependencies = {dependency["id"]: dependency for dependency in dependencies}
            preview = {"schema": SURFACE_SCHEMA, "policy": SURFACE_POLICY,
                "required_consumer_capability": SURFACE_CAPABILITY,
                "source": {"op_id": raw["id"], "operation_sha256": _hash(raw),
                    "ir_version": planned.ir_version, "compiler_plan_digest": planned.plan_digest,
                    "dependencies": [{"op_id": oid, "operation_sha256": _hash(dependencies[oid])}
                                     for oid in sorted(dependencies, key=lambda oid: indexed[oid][0])]},
                "representation": "authored_reference_surface", "surface_kind": _TARGETS[raw["op"]],
                "units": "mm", "mesh_space": "project", "mesh": mesh, "claims": dict(SURFACE_CLAIMS)}
            previews.append({**preview, "preview_digest": _hash(preview)})
        except ReferenceSurfaceRefusal as error:
            refusals[raw["id"]] = {"code": error.code, "detail": error.detail}
    return {"previews": previews, "refusals": refusals}


__all__ = ["SURFACE_SCHEMA", "SURFACE_POLICY", "SURFACE_CAPABILITY", "SURFACE_CLAIMS",
           "MAX_SURFACE_VERTICES", "MAX_SURFACE_TRIANGLES", "ReferenceSurfaceRefusal", "preview_reference_surfaces"]
