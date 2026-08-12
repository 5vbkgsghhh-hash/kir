"""Boundary contract for the shared polygon/path laws.

The profile limits are deliberately language policy rather than inferred
Revit limits.  Their values are therefore less important here than the seam:
the forward validator, CONTOUR, reverse-lift references, and the audit tool
must all keep reading named owners instead of growing private copies.
"""
from __future__ import annotations

import ast
import copy
import inspect
import math

import pytest

from kukai.ir import authoring_validation, contour, geom
from kukai.ir.decompile.l1_schema import AtomReason
from kukai.ir.decompile.tests.test_lift_floor_contour import _lift as _lift_floor
from kukai.ir.decompile.tests.test_lift_railing_path import (
    _document as _railing_document,
    _node as _lift_railing,
    _row as _railing_row,
    _sketch_index as _railing_sketch,
)
from kukai.ir.diag import TYPE_BAD_TYPE, TYPE_BOUNDS
from tools import bounds_audit


def _regular_ring(count: int, *, radius: float = 1_000.0,
                  center: tuple[float, float] = (0.0, 0.0)) -> list[list[float]]:
    return [
        [
            center[0] + radius * math.cos(2.0 * math.pi * i / count),
            center[1] + radius * math.sin(2.0 * math.pi * i / count),
        ]
        for i in range(count)
    ]


def _validate(name: str, **params):
    diags = []
    norm = authoring_validation.validate(params, name, 0, "B1", diags)
    return norm, diags


def _field_diags(diags, field: str):
    return [d for d in diags if d.field_name == field]


def _assert_lifted_op_revalidates(node):
    params = copy.deepcopy(node["params"])

    def strip_reverse_only_ids(value):
        if isinstance(value, dict):
            return {
                key: strip_reverse_only_ids(item)
                for key, item in value.items()
                if key != "_id"
            }
        if isinstance(value, list):
            return [strip_reverse_only_ids(item) for item in value]
        return value

    params = strip_reverse_only_ids(params)
    diags = []
    authoring_validation.validate(
        params, node["op_name"], 0, "ROUNDTRIP", diags)
    assert not diags, [d.as_dict() for d in diags]


def _literal_assignment(module, name: str):
    tree = ast.parse(inspect.getsource(module))
    matches = [
        node.value
        for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets if isinstance(node, ast.Assign) else [node.target]
        )
        if isinstance(target, ast.Name) and target.id == name
    ]
    assert len(matches) == 1, f"expected one module-level owner for {name}"
    return matches[0]


def test_profile_and_path_limits_have_public_independent_owners():
    assert geom.MIN_RING_POINTS == 3
    assert geom.MAX_RING_POINTS == 64
    assert geom.MAX_HOLES == 8
    assert geom.MAX_HOLE_RING_POINTS == 32
    assert geom.MIN_RING_AREA_MM2 == 10_000.0
    assert geom.MIN_PATH_POINTS == 2
    assert geom.MAX_PATH_POINTS == 64
    assert contour.MIN_ARC_BULGE == 1e-6
    assert contour.MAX_ARC_BULGE == 1.5
    assert not hasattr(contour, "_MAX_BULGE")
    assert not hasattr(contour, "_MIN_AREA")

    # Equal values do not imply equal policy.  A future profile-limit change
    # must not silently widen open railing/flex paths as a side effect.
    assert isinstance(_literal_assignment(geom, "MAX_RING_POINTS"), ast.Constant)
    path_owner = _literal_assignment(geom, "MAX_PATH_POINTS")
    assert isinstance(path_owner, ast.Constant)
    assert path_owner.value == 64


@pytest.mark.parametrize(
    ("count", "accepted"),
    ((geom.MIN_RING_POINTS, True),
     (geom.MAX_RING_POINTS, True),
     (geom.MIN_RING_POINTS - 1, False),
     (geom.MAX_RING_POINTS + 1, False)),
)
def test_forward_outer_ring_point_boundaries(count: int, accepted: bool):
    norm, diags = _validate("create_ceiling", outline=_regular_ring(count))
    field = _field_diags(diags, "outline")
    assert ("outline" in norm) is accepted
    assert (not field) is accepted
    if not accepted:
        assert field[0].code == TYPE_BAD_TYPE


def test_forward_ring_area_boundary_is_inclusive():
    # Triangle area is exactly 200 * 100 / 2 == 10 000 mm².
    at_limit = [[0.0, 0.0], [200.0, 0.0], [0.0, 100.0]]
    below_limit = [[0.0, 0.0], [199.99, 0.0], [0.0, 100.0]]

    norm, diags = _validate("create_ceiling", outline=at_limit)
    assert "outline" in norm
    assert not _field_diags(diags, "outline")

    norm, diags = _validate("create_ceiling", outline=below_limit)
    assert "outline" not in norm
    field = _field_diags(diags, "outline")
    assert field and field[0].code == TYPE_BOUNDS


def test_contour_reads_the_same_inclusive_area_owner():
    at_limit = {"shape": "poly",
                "points_mm": [[0.0, 0.0], [200.0, 0.0], [0.0, 100.0]]}
    below_limit = {"shape": "poly",
                   "points_mm": [[0.0, 0.0], [199.99, 0.0], [0.0, 100.0]]}

    diags = []
    assert contour._validate_shape(
        at_limit, [], "B1", "region", diags
    ) is not None
    assert not diags

    diags = []
    assert contour._validate_shape(
        below_limit, [], "B1", "region", diags
    ) is None
    assert diags and diags[0].code == TYPE_BOUNDS
    assert diags[0].field_name == "region"


@pytest.mark.parametrize(
    ("hole_count", "accepted"),
    ((1, True), (geom.MAX_HOLES, True), (geom.MAX_HOLES + 1, False)),
)
def test_forward_hole_count_boundaries(hole_count: int, accepted: bool):
    holes = [
        _regular_ring(geom.MIN_RING_POINTS, radius=100.0,
                      center=(float(i) * 1_000.0, 0.0))
        for i in range(hole_count)
    ]
    norm, diags = _validate("create_ceiling", holes=holes)
    field = _field_diags(diags, "holes")
    assert ("holes" in norm) is accepted
    assert (not field) is accepted
    if not accepted:
        assert field[0].code == TYPE_BAD_TYPE


@pytest.mark.parametrize(
    ("point_count", "accepted"),
    ((geom.MIN_RING_POINTS, True),
     (geom.MAX_HOLE_RING_POINTS, True),
     (geom.MIN_RING_POINTS - 1, False),
     (geom.MAX_HOLE_RING_POINTS + 1, False)),
)
def test_forward_hole_ring_point_boundaries(point_count: int, accepted: bool):
    norm, diags = _validate("create_ceiling", holes=[_regular_ring(point_count)])
    field = _field_diags(diags, "holes")
    assert ("holes" in norm) is accepted
    assert (not field) is accepted
    if not accepted:
        assert field[0].code == TYPE_BAD_TYPE


@pytest.mark.parametrize(
    ("op_name", "dims"),
    (("create_railing", 2), ("create_flex_duct", 3)),
)
@pytest.mark.parametrize(
    ("point_count", "accepted"),
    ((geom.MIN_PATH_POINTS, True),
     (geom.MAX_PATH_POINTS, True),
     (geom.MIN_PATH_POINTS - 1, False),
     (geom.MAX_PATH_POINTS + 1, False)),
)
def test_forward_open_path_boundaries(op_name: str, dims: int,
                                      point_count: int, accepted: bool):
    points = [
        [float(i) * 10.0, 0.0] + ([float(i)] if dims == 3 else [])
        for i in range(point_count)
    ]
    params = {"path": points}
    if op_name == "create_railing":
        params["variety"] = "path"
    norm, diags = _validate(op_name, **params)
    field = _field_diags(diags, "path")
    assert ("path" in norm) is accepted
    assert (not field) is accepted
    if not accepted:
        assert field[0].code == TYPE_BAD_TYPE


@pytest.mark.parametrize(
    ("bulge", "third_y", "accepted"),
    ((contour.MIN_ARC_BULGE, 10_000.0, True),
     (math.nextafter(contour.MIN_ARC_BULGE, 0.0), 10_000.0, False),
     (contour.MAX_ARC_BULGE, 10_000.0, True),
     (math.nextafter(contour.MAX_ARC_BULGE, math.inf), 10_000.0, False),
     (-contour.MIN_ARC_BULGE, -10_000.0, True),
     (-contour.MAX_ARC_BULGE, -10_000.0, True)),
)
def test_contour_bulge_boundaries(bulge: float, third_y: float,
                                  accepted: bool):
    shape = {
        "shape": "poly",
        "points_mm": [[0.0, 0.0], [1_000.0, 0.0], [500.0, third_y]],
        "arcs": [{"edge": 0, "bulge": bulge}],
    }
    diags = []
    lowered = contour._validate_shape(shape, [], "B1", "region", diags)
    assert (lowered is not None) is accepted
    assert (not diags) is accepted
    if not accepted:
        assert diags[0].code == TYPE_BOUNDS
        assert diags[0].field_name == "region.arcs[0].bulge"


def test_contour_hole_point_limit_is_explicitly_the_outer_ring_limit():
    """Pin the known 64-vs-32 policy split instead of hiding it.

    A direct polygon hole is capped by MAX_HOLE_RING_POINTS, while a CONTOUR
    hole is a recursively validated shape and currently uses MAX_RING_POINTS.
    Consolidating names must not silently pretend these two policies agree.
    """
    outer = {"shape": "rect", "origin": [0.0, 0.0],
             "size_mm": [10_000.0, 10_000.0]}
    at_limit = {"shape": "poly",
                "points_mm": _regular_ring(
                    geom.MAX_RING_POINTS, radius=1_000.0,
                    center=(5_000.0, 5_000.0))}
    over_limit = {"shape": "poly",
                  "points_mm": _regular_ring(
                      geom.MAX_RING_POINTS + 1, radius=1_000.0,
                      center=(5_000.0, 5_000.0))}

    diags = []
    assert contour.validate_region(
        {"outer": outer, "holes": [at_limit]}, [], "B1", "region", diags
    ) is not None
    assert not diags

    diags = []
    assert contour.validate_region(
        {"outer": outer, "holes": [over_limit]}, [], "B1", "region", diags
    ) is None
    assert diags and diags[0].field_name == "region.holes[0].points_mm"


def test_reverse_outer_ring_limit_revalidates_and_limit_plus_one_is_an_atom():
    def profile(count: int):
        points = _regular_ring(count, radius=5_000.0)
        return {
            "profile_available": True,
            "exterior_loop": points,
            "curve_kinds": [["line"] * count],
            "arc_midpoints": [[None] * count],
            "holes": [],
        }

    node = _lift_floor("4001", profile(geom.MAX_RING_POINTS))
    assert node["kind"] == "op", node.get("reason")
    assert node["op_name"] == "create_floor"
    assert len(node["params"]["outline"]) == geom.MAX_RING_POINTS
    _assert_lifted_op_revalidates(node)

    refused = _lift_floor("4001", profile(geom.MAX_RING_POINTS + 1))
    assert refused["kind"] == "atom"
    assert refused["reason"]["code"] == AtomReason.UNSUPPORTED_SIGNATURE.value
    assert f"{geom.MAX_RING_POINTS} pts" in refused["reason"]["detail"]


def test_reverse_path_limit_revalidates_and_limit_plus_one_is_an_atom():
    def row(count: int):
        return _railing_row(
            points_mm=[[float(i) * 10.0, 0.0] for i in range(count)],
            curve_kinds=["line"] * (count - 1),
            arc_midpoints_mm=[None] * (count - 1),
        )

    node = _lift_railing(
        _railing_document(), _railing_sketch(row(geom.MAX_PATH_POINTS)))
    assert node["kind"] == "op", node.get("reason")
    assert node["op_name"] == "create_railing"
    assert len(node["params"]["path"]) == geom.MAX_PATH_POINTS
    _assert_lifted_op_revalidates(node)

    refused = _lift_railing(
        _railing_document(), _railing_sketch(row(geom.MAX_PATH_POINTS + 1)))
    assert refused["kind"] == "atom"
    assert refused["reason"]["code"] == AtomReason.UNSUPPORTED_SIGNATURE.value
    assert f"2..{geom.MAX_PATH_POINTS}" in refused["reason"]["detail"]


def test_bounds_audit_classifies_owned_values_and_references():
    rows = bounds_audit.module_constants()

    def one(where_suffix: str, bound_id: str):
        found = [r for r in rows
                 if r["where"].endswith(where_suffix) and r["id"] == bound_id]
        assert len(found) == 1
        return found[0]

    path_limit = one("kukai/ir/geom.py", "MAX_PATH_POINTS")
    assert path_limit["kind"] == "constant"
    assert path_limit["value"] == geom.MAX_PATH_POINTS
    assert path_limit["boundish"] is True
    contour_bulge = one("kukai/ir/contour.py", "MAX_ARC_BULGE")
    assert contour_bulge["kind"] == "constant"
    assert contour_bulge["value"] == contour.MAX_ARC_BULGE
    lift_ref = one("kukai/ir/decompile/lift.py", "_CONTOUR_MAX_POINTS")
    assert lift_ref["kind"] == "reference"
    assert lift_ref["value"] == "_geom.MAX_RING_POINTS"


def test_bounds_audit_result_counts_strict_rejections_only():
    result = bounds_audit.Result("synthetic", "[10, 20]")
    for value in (10.0, 20.0, 9.5, 20.5):
        result.feed(value, 10.0, 20.0)

    assert result.denominator == 4
    assert result.below == 1
    assert result.above == 1
    assert result.rejected == 2
    assert result.worst_low == 9.5
    assert result.worst_high == 20.5
    assert result.observed_min == 9.5
    assert result.observed_max == 20.5
