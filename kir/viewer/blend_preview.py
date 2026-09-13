"""Opt-in producer of a profile interpolation proxy, NOT native blend geometry.

Revit receives vertexPairs=null and chooses its own connections. This producer
does not reproduce that choice, bound the resulting body, or supply clash/BIM
geometry. Its output must not enter the legacy viewer as EXACT or SHAPED: the
consumer must explicitly support this approximate-representation policy first.
No scene, program, stored revision or native body is modified here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from kir import contour, plane, spec
from kir.project import ProjectError, _hash, _object, _thaw


PREVIEW_SCHEMA = "kir-native-blend-preview/1"
PREVIEW_POLICY = "indexed_rectangle_profile_proxy/1"
REQUIRED_CONSUMER_CAPABILITY = "display_approximate_profile_proxy/1"
SAMPLE_RINGS = 9
MAX_TWIST_DEG = 30.0


class BlendPreviewRefusal(ValueError):
    """Only this display recipe is unsupported; the KIR language is unchanged."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True, slots=True)
class BlendPreview:
    """Immutable factory result. Serialized claims are not execution evidence.

    There is deliberately no loader, compiler/materialize method, or implicit
    conversion to a KIR operation. The source remains the original native op.
    """

    source_op_id: str
    source_op_digest: str
    source_plan_digest: str
    ir_version: str
    mesh: Mapping
    scale: float
    rotation_deg: float
    fit_tolerance_mm: float
    input_winding: str

    def __post_init__(self):
        object.__setattr__(self, "mesh", _object(self.mesh, "preview_mesh"))

    def to_dict(self) -> dict:
        result = {
            "schema": PREVIEW_SCHEMA, "policy": PREVIEW_POLICY,
            "required_consumer_capability": REQUIRED_CONSUMER_CAPABILITY,
            "source": {"op_id": self.source_op_id, "operation_sha256": self.source_op_digest,
                       "ir_version": self.ir_version, "compiler_plan_digest": self.source_plan_digest},
            "representation": "approximate_profile_proxy", "units": "mm", "mesh_space": "project",
            "mesh": _thaw(self.mesh),
            "interpolation": {"correspondence": "authored_index_not_revit_vertex_pairs",
                              "sample_rings": SAMPLE_RINGS, "scale": self.scale,
                              "rotation_deg": self.rotation_deg,
                              "fit_tolerance_mm": self.fit_tolerance_mm,
                              "input_winding": self.input_winding,
                              "winding_normalization": "joint_reverse_keep_first" if self.input_winding == "cw" else "none"},
            "claims": {"profile_endpoints": "copied_from_normalized_authored_profiles",
                       "native_equivalence": "unverified", "native_execution": "not_run",
                       "containment": "not_claimed", "mesh_error_bound": "not_measured",
                       "clash_eligibility": "none", "bim_semantics": "not_claimed",
                       "side_surface": "display_interpolation_not_native_contract"},
        }
        return {**result, "preview_digest": _hash(result)}


def _rectangle(region: dict, oid: str, field: str):
    diagnostics = []
    normalized = contour.validate_region(region, [], oid, field, diagnostics)
    if normalized is None:
        raise BlendPreviewRefusal("unsupported_profile", f"{field}: unresolved or invalid contour")
    if normalized["holes"] or not contour.edges_are_straight(normalized["outer"]):
        raise BlendPreviewRefusal("unsupported_profile", f"{field}: only straight profiles without holes are displayed")
    points = contour.edges_vertices(normalized["outer"])
    if len(points) != 4:
        raise BlendPreviewRefusal("unsupported_profile", f"{field}: this display policy requires four rectangle corners")
    values = [complex(*point) for point in points]
    edges = [values[(index + 1) % 4] - value for index, value in enumerate(values)]
    span = max(abs(edge) for edge in edges)
    tolerance = max(1e-6, span * 1e-10)  # fit test only; never an output error bound
    if (min(abs(edge) for edge in edges) <= tolerance
            or abs(edges[0] + edges[2]) > tolerance or abs(edges[1] + edges[3]) > tolerance
            or abs((edges[0].conjugate() * edges[1]).real) > 1e-9 * abs(edges[0]) * abs(edges[1])):
        raise BlendPreviewRefusal("unsupported_profile", f"{field}: the four corners do not form a rectangle")
    winding = "ccw" if (edges[0].conjugate() * edges[1]).imag > 0 else "cw"
    return points, values, winding, tolerance


def preview_native_blend(operation: Mapping, *, ir_version: str = spec.IR_VERSION) -> BlendPreview:
    """Produce a bounded, explicitly approximate display result without OCP/Revit.

    Supported subset: literal straight rectangular profiles, common winding,
    positive uniform similarity in authored index order, rotation at most 30°,
    and the compiler's actual height/base/plane contract. No cyclic rematching,
    guessed grounding, shape repair, or silent conversion to body-owned output.
    """
    from kir.compiler import KirRefusal, plan_program
    from kir.course.rhino import _loft_mesh

    if ir_version != spec.IR_VERSION:
        raise BlendPreviewRefusal("unsupported_ir_version", "this producer interprets only the current compiler contract")
    try:
        source = _thaw(_object(operation, "source_operation"))
    except ProjectError as exc:
        raise BlendPreviewRefusal("invalid_operation", str(exc)) from exc
    if source.get("op") != "create_solid_blend":
        raise BlendPreviewRefusal("not_native_blend", "expected create_solid_blend")
    if not isinstance(source.get("id"), str) or not source["id"]:
        raise BlendPreviewRefusal("missing_source_id", "an addressed authored operation is required")
    try:
        planned = plan_program({"ir_version": ir_version, "intent": "Inspect declared blend profiles", "ops": [source]})
    except KirRefusal as exc:
        raise BlendPreviewRefusal("invalid_operation", str(exc)) from exc
    normalized = planned.to_ops()[0]
    low, p, low_winding, low_tolerance = _rectangle(normalized["profile"], source["id"], "profile")
    high, q, high_winding, high_tolerance = _rectangle(normalized["profile_top"], source["id"], "profile_top")
    if low_winding != high_winding:
        raise BlendPreviewRefusal("unsupported_correspondence", "profile winding differs; no vertex matching is guessed")
    factor = (q[1] - q[0]) / (p[1] - p[0])
    shift = q[0] - factor * p[0]
    tolerance = max(low_tolerance, high_tolerance)
    if max(abs(top - (factor * bottom + shift)) for bottom, top in zip(p, q, strict=True)) > tolerance:
        raise BlendPreviewRefusal("unsupported_similarity", "profiles are not a uniform positive similarity in authored order")
    rotation = math.degrees(math.atan2(factor.imag, factor.real))
    if abs(rotation) > MAX_TWIST_DEG + 1e-9:
        raise BlendPreviewRefusal("unsupported_twist", "this display policy supports at most 30 degrees; no cyclic rematching")
    # The shared mesh helper assumes outward CCW side walls. Reverse BOTH
    # rings with the same permutation, retaining the starting corner/pairing.
    if low_winding == "cw":
        low, high = [low[index] for index in (0, 3, 2, 1)], [high[index] for index in (0, 3, 2, 1)]
    height = normalized["height_mm"]
    prepared = []
    for index in range(SAMPLE_RINGS):
        t = index / (SAMPLE_RINGS - 1)
        # Copy endpoints verbatim; an interpolated roundoff must not move caps.
        points = low if index == 0 else high if index == SAMPLE_RINGS - 1 else [
            [(1 - t) * bottom[axis] + t * top[axis] for axis in range(2)]
            for bottom, top in zip(low, high, strict=True)]
        prepared.append(({"outer": {"shape": "poly", "points_mm": points}}, t * height, points))
    mesh, reason = _loft_mesh(prepared)
    if mesh is None:
        raise BlendPreviewRefusal("preview_build_failed", reason or "profile proxy triangulation failed")
    declared_plane = normalized.get("plane")
    if declared_plane is not None:
        diagnostics = []
        frame = plane.validate_plane(declared_plane, source["id"], "plane", diagnostics)
        if frame is None:
            raise BlendPreviewRefusal("invalid_operation", "plane validation failed")
        origin, x_dir, y_dir, normal = plane.frame(frame)
        mesh["vertices_mm"] = [[origin[k] + u * x_dir[k] + v * y_dir[k] + z * normal[k]
                                for k in range(3)] for u, v, z in mesh["vertices_mm"]]
    else:
        z0 = normalized.get("base_z_mm") or 0.
        mesh["vertices_mm"] = [[u, v, z0 + z] for u, v, z in mesh["vertices_mm"]]
    if any(not math.isfinite(value) for point in mesh["vertices_mm"] for value in point):
        raise BlendPreviewRefusal("preview_build_failed", "transformed display coordinates are nonfinite")
    return BlendPreview(source["id"], _hash(source), planned.plan_digest, ir_version, mesh,
                        abs(factor), rotation, tolerance, low_winding)


__all__ = ["PREVIEW_SCHEMA", "PREVIEW_POLICY", "REQUIRED_CONSUMER_CAPABILITY",
           "BlendPreview", "BlendPreviewRefusal", "preview_native_blend"]
