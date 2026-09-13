"""Independent geometry controls for an opt-in, non-native profile proxy."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from examples.residential_project import concept
from kir import compile_program, sdk, spec
from kir.project import _hash
from kir.viewer.blend_preview import (BlendPreviewRefusal, REQUIRED_CONSUMER_CAPABILITY,
                                      preview_native_blend)


def operation():
    return concept().to_program()["ops"][0]


def area(points):
    return sum(p[0] * q[1] - p[1] * q[0]
               for p, q in zip(points, points[1:] + points[:1])) / 2


def cap_area(mesh, z):
    result = 0.
    for triangle in mesh["triangles"]:
        a, b, c = [mesh["vertices_mm"][index] for index in triangle]
        if all(point[2] == z for point in (a, b, c)):
            result += abs((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])) / 2
    return result


@pytest.mark.parametrize("tower,angle", [(0, 12.), (1, -9.), (2, 18.)])
def test_actual_twist_taper_rings_and_cap_areas_are_retained_not_only_output_ids(tower, angle):
    op = concept().to_program()["ops"][tower]
    preview = preview_native_blend(op)
    mesh = preview.to_dict()["mesh"]
    low, high = [op[field]["outer"]["points_mm"] for field in ("profile", "profile_top")]
    assert mesh["vertices_mm"][:4] == [[*point, 0.] for point in low]
    assert mesh["vertices_mm"][-4:] == [[*point, op["height_mm"]] for point in high]
    assert len(mesh["vertices_mm"]) == 36 and len(mesh["triangles"]) == 68
    for index, (a, b) in enumerate(zip(low, high)):
        assert mesh["vertices_mm"][4 * 4 + index] == pytest.approx(
            [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, op["height_mm"] / 2])
    assert preview.scale == pytest.approx(.82)
    assert preview.rotation_deg == pytest.approx(angle)
    assert cap_area(mesh, 0.) == pytest.approx(abs(area(low)))
    assert cap_area(mesh, op["height_mm"]) == pytest.approx(abs(area(high)))
    assert cap_area(mesh, op["height_mm"]) / cap_area(mesh, 0.) == pytest.approx(.6724)


def test_negative_base_and_arbitrary_valid_plane_apply_once_without_guessing_z():
    op = operation()
    op["base_z_mm"] = -1200
    mesh = preview_native_blend(op).to_dict()["mesh"]
    assert min(point[2] for point in mesh["vertices_mm"]) == -1200
    assert max(point[2] for point in mesh["vertices_mm"]) == op["height_mm"] - 1200
    op.pop("base_z_mm")
    # The profile's v axis becomes +Z; extrusion normal points along -Y.
    op["plane"] = {"origin_mm": [100000, -50000, 1200],
                   "normal": [0, -2, 0], "x_dir": [3, 0, 0]}
    moved = preview_native_blend(op).to_dict()["mesh"]["vertices_mm"]
    low, high = [op[field]["outer"]["points_mm"] for field in ("profile", "profile_top")]
    assert moved[:4] == [[100000 + x, -50000., 1200 + y] for x, y in low]
    assert moved[-4:] == [[100000 + x, -50000. - op["height_mm"], 1200 + y] for x, y in high]
    # Compiler output must still be native Blend, not a replacement mesh op.
    built = compile_program({"ir_version": spec.IR_VERSION, "ops": [op]}, revit_version="2026")
    assert built.ok
    assert "(ICollection<VertexPair>)null" in built.csharp
    assert "__bhi_" in built.csharp and "Transform" in built.csharp


def test_common_clockwise_order_is_normalized_together_without_changing_pairing_or_caps():
    op = operation()
    for key in ("profile", "profile_top"):
        pts = op[key]["outer"]["points_mm"]
        op[key]["outer"]["points_mm"] = [pts[index] for index in (0, 3, 2, 1)]
    preview = preview_native_blend(op)
    assert preview.input_winding == "cw"
    mesh = preview.to_dict()["mesh"]
    # Every undirected edge appears twice with opposite direction: helper side
    # winding and cap winding agree even when both authored rings were CW.
    edges = {}
    for a, b, c in mesh["triangles"]:
        for start, end in ((a, b), (b, c), (c, a)):
            edges.setdefault(tuple(sorted((start, end))), []).append((start, end))
    assert all(len(pair) == 2 and pair[0] == pair[1][::-1] for pair in edges.values())
    for offset, field in ((0, "profile"), (-4, "profile_top")):
        points = mesh["vertices_mm"][offset:offset + 4 if offset == 0 else None]
        assert {tuple(point[:2]) for point in points} == {tuple(point) for point in op[field]["outer"]["points_mm"]}


@pytest.mark.parametrize("case,code", [
    ("cyclic_shift", "unsupported_similarity"), ("opposite_winding", "unsupported_correspondence"),
    ("anisotropic_top", "unsupported_similarity"), ("different_corner_count", "unsupported_profile"),
    ("hole", "unsupported_profile"), ("arc", "unsupported_profile"),
    ("reflected_top", "unsupported_correspondence"), ("concave", "unsupported_profile"),
])
def test_legal_or_draft_inputs_outside_preview_policy_have_named_refusals_without_mutation(case, code):
    op = operation()
    top = op["profile_top"]["outer"]["points_mm"]
    if case == "cyclic_shift":
        op["profile_top"]["outer"]["points_mm"] = top[1:] + top[:1]
    elif case == "opposite_winding":
        op["profile_top"]["outer"]["points_mm"] = top[::-1]
    elif case == "anisotropic_top":
        # Rectangle remains a rectangle, but scales along its axes differ.
        op["profile_top"] = {"outer": {"shape": "poly", "points_mm": [[0, 0], [12000, 0], [12000, 5000], [0, 5000]]}}
    elif case == "different_corner_count":
        op["profile_top"] = {"outer": {"shape": "poly", "points_mm": [[0, 0], [14000, 0], [7000, 9000]]}}
    elif case == "hole":
        op["profile"]["holes"] = [{"shape": "poly", "points_mm": [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]}]
    elif case == "arc":
        op["profile"]["outer"]["arcs"] = [{"edge": 0, "bulge": -.1}]
    elif case == "reflected_top":
        op["profile_top"]["outer"]["points_mm"] = [[-x, y] for x, y in top]
    else:
        op["profile"] = {"outer": {"shape": "poly", "points_mm": [[0, 0], [14000, 0], [7000, 1000], [0, 9000]]}}
    before = deepcopy(op)
    with pytest.raises(BlendPreviewRefusal) as result:
        preview_native_blend(op)
    assert result.value.code == code
    assert op == before


@pytest.mark.parametrize("change", [{"height_mm": True}, {"height_mm": 0},
                                      {"height_mm": float("inf")}, {"base_z_mm": "1200"},
                                      {"plane": {"origin_mm": [0, 0, 0], "normal": [0, 0, 1], "x_dir": [1, 0, 0]}}])
def test_actual_compiler_rejects_invalid_height_units_and_plane_plus_base(change):
    op = operation()
    op.update(change)
    with pytest.raises(BlendPreviewRefusal, match="invalid_operation"):
        preview_native_blend(op)


def test_source_digest_keeps_scalar_encoding_and_immutability_no_program_rewrite():
    op = operation()
    original = deepcopy(op)
    preview = preview_native_blend(op)
    assert preview.source_op_digest == _hash(op)
    alternate = deepcopy(op)
    alternate["base_z_mm"] = -0.
    changed = preview_native_blend(alternate)
    assert changed.source_op_digest != preview.source_op_digest
    assert changed.mesh == preview.mesh
    with pytest.raises(FrozenInstanceError):
        preview.scale = 1
    with pytest.raises(TypeError):
        preview.mesh["vertices_mm"][0][0] = 5
    exported = preview.to_dict()
    exported["mesh"]["vertices_mm"][0][0] = 999
    assert preview.mesh["vertices_mm"][0][0] != 999 and op == original
    assert not hasattr(preview, "materialize") and not hasattr(preview, "loads")


def test_changed_top_alters_real_geometry_and_claim_is_never_native_or_conservative():
    op = operation()
    before = preview_native_blend(op)
    for point in op["profile_top"]["outer"]["points_mm"]:
        point[0] += 3000
    after = preview_native_blend(op)
    assert after.mesh != before.mesh and after.source_op_digest != before.source_op_digest
    assert after.mesh["vertices_mm"][0] == before.mesh["vertices_mm"][0]
    assert after.mesh["vertices_mm"][-1][0] - before.mesh["vertices_mm"][-1][0] == pytest.approx(3000)
    report = after.to_dict()
    assert report["required_consumer_capability"] == REQUIRED_CONSUMER_CAPABILITY
    assert report["representation"] == "approximate_profile_proxy"
    assert report["claims"]["native_equivalence"] == "unverified"
    assert report["claims"]["containment"] == "not_claimed"
    assert report["claims"]["clash_eligibility"] == "none"
    assert report["claims"]["mesh_error_bound"] == "not_measured"


def test_rect_form_uses_the_actual_contour_normalizer_and_no_shape_guess():
    op = sdk.create_solid_blend(id="rectangle", category="mass", name="Rectangles", height_mm=3000,
        profile={"outer": {"shape": "rect", "origin": [0, 0], "size_mm": [14000, 9000]}},
        profile_top={"outer": {"shape": "rect", "origin": [0, 0], "size_mm": [11480, 7380]}})
    preview = preview_native_blend(op)
    assert preview.scale == pytest.approx(.82)
    assert cap_area(preview.to_dict()["mesh"], 0.) == 126e6


@pytest.mark.parametrize("angle,accepted", [(30., True), (-30., True), (30.01, False), (90., False)])
def test_twist_policy_boundary_is_explicit_even_for_valid_square_similarity(angle, accepted):
    points = [[0., 0.], [10000., 0.], [10000., 10000.], [0., 10000.]]
    sine, cosine = math.sin(math.radians(angle)), math.cos(math.radians(angle))
    top = [[cosine * x - sine * y, sine * x + cosine * y] for x, y in points]
    op = sdk.create_solid_blend(id="square", name="Square", category="mass", height_mm=3000,
        profile={"outer": {"shape": "poly", "points_mm": points}},
        profile_top={"outer": {"shape": "poly", "points_mm": top}})
    if accepted:
        assert preview_native_blend(op).rotation_deg == pytest.approx(angle)
    else:
        with pytest.raises(BlendPreviewRefusal, match="unsupported_twist"):
            preview_native_blend(op)


def test_unknown_ir_or_nonblend_or_missing_address_refuses_by_name():
    with pytest.raises(BlendPreviewRefusal, match="unsupported_ir_version"):
        preview_native_blend(operation(), ir_version="999")
    with pytest.raises(BlendPreviewRefusal, match="not_native_blend"):
        preview_native_blend({"op": "create_level", "id": "L"})
    op = operation()
    op.pop("id")
    with pytest.raises(BlendPreviewRefusal, match="missing_source_id"):
        preview_native_blend(op)


def test_producer_runs_without_native_backend_and_is_not_implicitly_routed_to_legacy_scene():
    root = Path(__file__).resolve().parents[3]
    child = subprocess.run([sys.executable, "-c", """
import importlib.abc, json, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('profile proxy entered native backend')
sys.meta_path.insert(0, NoOcp())
from examples.residential_project import concept
from kir.viewer.blend_preview import preview_native_blend
from kir.viewer.live_scene import scene_from_programs
program = concept().to_program()
before, bm = scene_from_programs([program])
preview_native_blend(program['ops'][0])
after, am = scene_from_programs([program])
assert bm['display_bodies'] == am['display_bodies'] == 0
assert bm['blind_by_class'] == am['blind_by_class']
assert not any(name == 'OCP' or name.startswith('OCP.') for name in sys.modules)
print('producer-only')
"""], text=True, capture_output=True, cwd=root, timeout=20,
       env=dict(os.environ, PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "producer-only"
