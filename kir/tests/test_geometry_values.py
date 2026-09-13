"""Shadow parity gate for the Python layer of geometric values."""
from __future__ import annotations

import pytest

from kir import sdk
from kir.geometry_values import (
    Blend,
    BooleanSolid,
    Extrude,
    GeometryValueError,
    MeshValue,
    NurbsSurfaceValue,
    PlaneFrame,
    Polyline3,
    Profile2D,
    Revolve,
    SolidPart,
    Sweep,
)


PROFILE = {"outer": {"shape": "rect", "origin": [0, 0],
                     "size_mm": [1000, 800]}, "holes": []}
TOP = {"outer": {"shape": "rect", "origin": [100, 0],
                 "size_mm": [700, 600]}, "holes": []}
PLANE = {"origin_mm": [10, 20, 30], "normal": [0, 1, 0],
         "x_dir": [1, 0, 0]}


def test_profile_is_immutable_and_returns_fresh_kir_values() -> None:
    source = {"outer": {"shape": "poly", "points_mm": [[0, 0], [1000, 0],
                                                           [0, 1000]]},
              "holes": []}
    profile = Profile2D(source)
    source["outer"]["points_mm"][0][0] = 999
    first = profile.to_kir()
    first["outer"]["points_mm"][0][0] = 777
    assert profile.to_kir()["outer"]["points_mm"][0][0] == 0


def test_geometry_values_are_reachable_from_the_llm_authoring_sdk() -> None:
    assert sdk.geometry.Profile2D is Profile2D
    assert sdk.geometry.Extrude is Extrude


def test_program_add_geometry_is_one_step_but_emits_the_same_operation() -> None:
    program = sdk.program()
    ref = program.add_geometry(
        Extrude(Profile2D(PROFILE), 3000),
        category="generic_model", name="Body", id="body1")
    assert ref == sdk.Ref("body1")
    assert program.to_dict()["ops"] == [sdk.create_solid_extrusion(
        profile=PROFILE, height_mm=3000,
        category="generic_model", name="Body", id="body1")]


def test_program_never_falls_back_unknown_objects_to_directshape() -> None:
    with pytest.raises(TypeError, match="materialize"):
        sdk.program().add_geometry(
            object(), category="generic_model", name="Unknown")


def test_non_json_value_refuses_at_the_authoring_edge() -> None:
    with pytest.raises(GeometryValueError, match="JSON-shaped"):
        Profile2D({"outer": object()})


def test_expression_vectors_do_not_keep_mutable_author_lists() -> None:
    direction = [0, 1, 0]
    axis = [10, 20]
    sweep = Sweep(Profile2D(PROFILE), Polyline3([[0, 0, 0], [0, 0, 1000]]),
                  ref_dir=direction)
    revolve = Revolve(Profile2D(PROFILE), axis, 90)
    direction[1] = 999
    axis[0] = 999
    assert sweep.ref_dir == (0, 1, 0)
    assert revolve.axis_xy_mm == (10, 20)


def test_expression_scalars_are_snapshotted_at_construction() -> None:
    class MutableScalar:
        def __init__(self, value: int) -> None:
            self.value = value

        def item(self) -> int:
            return self.value

    height = MutableScalar(3000)
    value = Extrude(Profile2D(PROFILE), height)
    height.value = 9000
    first = value.materialize(category="generic_model", name="E")
    second = value.materialize(category="generic_model", name="E")
    assert first["height_mm"] == 3000
    assert second == first


def test_expression_scalar_slots_refuse_containers() -> None:
    with pytest.raises(GeometryValueError, match="expected a scalar"):
        Extrude(Profile2D(PROFILE), [3000])


@pytest.mark.parametrize("actual,expected", [
    (
        Extrude(Profile2D(PROFILE), 3000, base_z_mm=500).materialize(
            category="generic_model", name="E", id="E1"),
        sdk.create_solid_extrusion(
            profile=PROFILE, height_mm=3000, base_z_mm=500,
            category="generic_model", name="E", id="E1"),
    ),
    (
        Extrude(Profile2D(PROFILE), 3000,
                plane=PlaneFrame(**PLANE)).materialize(
                    category="mass", name="EP"),
        sdk.create_solid_extrusion(
            profile=PROFILE, height_mm=3000, plane=PLANE,
            category="mass", name="EP"),
    ),
    (
        Blend(Profile2D(PROFILE), Profile2D(TOP), 2400).materialize(
            category="generic_model", name="B"),
        sdk.create_solid_blend(
            profile=PROFILE, profile_top=TOP, height_mm=2400,
            category="generic_model", name="B"),
    ),
    (
        Sweep(Profile2D(PROFILE),
              Polyline3([[0, 0, 0], [0, 0, 1000], [1000, 0, 1000]]),
              ref_dir=[0, 1, 0], anchor_uv_mm=[0, 0]).materialize(
                  category="generic_model", name="S"),
        sdk.create_solid_sweep(
            variety="frame", profile=PROFILE, anchor_uv_mm=[0, 0],
            path_mm=[[0, 0, 0], [0, 0, 1000], [1000, 0, 1000]],
            ref_dir=[0, 1, 0], category="generic_model", name="S"),
    ),
    (
        Revolve(Profile2D(PROFILE), [0, 0], 180).materialize(
            category="generic_model", name="R"),
        sdk.create_solid_revolve(
            profile=PROFILE, axis_xy_mm=[0, 0], sweep_deg=180,
            category="generic_model", name="R"),
    ),
    (
        BooleanSolid(
            "difference", Profile2D(PROFILE), 3000,
            (SolidPart({"shape": "box", "center_mm": [0, 0, 1500],
                        "size_mm": [200, 200, 200]}),),
        ).materialize(category="generic_model", name="C"),
        sdk.create_solid_boolean(
            operation="difference", profile=PROFILE, height_mm=3000,
            parts=[{"shape": "box", "center_mm": [0, 0, 1500],
                    "size_mm": [200, 200, 200]}],
            category="generic_model", name="C"),
    ),
])
def test_solid_expression_lowering_is_exactly_sdk_parity(
        actual: dict, expected: dict) -> None:
    assert actual == expected


def test_mesh_materialization_is_exactly_sdk_parity() -> None:
    mesh = MeshValue(vertices_mm=[[0, 0, 0], [1000, 0, 0], [0, 1000, 0]],
                     triangles=[[0, 1, 2]])
    assert mesh.materialize(category="generic_model", name="M") == \
        sdk.create_directshape(
            mesh={"vertices_mm": [[0, 0, 0], [1000, 0, 0], [0, 1000, 0]],
                  "triangles": [[0, 1, 2]]},
            category="generic_model", name="M")


def test_surface_materialization_is_exactly_sdk_parity() -> None:
    surface_value = {
        "degree_u": 1, "degree_v": 1, "count_u": 2, "count_v": 2,
        "knots_u": [0, 0, 1, 1], "knots_v": [0, 0, 1, 1],
        "control_points_mm": [[0, 0, 0], [0, 1000, 0],
                              [1000, 0, 0], [1000, 1000, 0]],
    }
    surface = NurbsSurfaceValue(surface_value)
    assert surface.materialize(category="mass", name="N") == \
        sdk.create_surface(surface=surface_value, category="mass", name="N")


def test_value_lowering_keeps_csharp_identical_for_all_revit_versions() -> None:
    value_program = sdk.program(intent="geometry value parity")
    value_program.add(
        Extrude(Profile2D(PROFILE), 3000, base_z_mm=250).materialize(
            category="generic_model", name="E", id="E1"))
    manual_program = sdk.program(intent="geometry value parity")
    manual_program.add(sdk.create_solid_extrusion(
        profile=PROFILE, height_mm=3000, base_z_mm=250,
        category="generic_model", name="E", id="E1"))

    values = value_program.compile_all()
    manual = manual_program.compile_all()
    assert set(values) == set(manual)
    for version in values:
        assert values[version].ok and manual[version].ok
        assert values[version].csharp == manual[version].csharp
        assert values[version].planned is not None
        assert manual[version].planned is not None
        assert (values[version].planned.plan_digest
                == manual[version].planned.plan_digest)
