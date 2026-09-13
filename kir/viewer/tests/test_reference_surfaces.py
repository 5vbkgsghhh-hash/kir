"""Zero-thickness authored display controls, not Revit body conformance."""
from copy import deepcopy
import math
import os
from pathlib import Path
import subprocess
import sys

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from examples import residential_project
from kir import compiler, mesh as mesh_helpers, spec
from kir.geometry_materialization import materialize_project
from kir.project import _hash
from kir.viewer import reference_surfaces as surfaces


def level(identifier="L", elevation=5000):
    return {"op": "create_level", "id": identifier, "elev_mm": elevation}


def wall(**fields):
    return {"op": "create_wall", "id": "W", "p0_mm": [100000, -20000],
            "p1_mm": [105000, -17000], "level": {"by": "ref", "value": "L"},
            "height_mm": 2800, **fields}


def floor(**fields):
    return {"op": "create_floor_by_contour", "id": "F", "level": {"by": "ref", "value": "L"},
            "contour": {"outer": {"shape": "poly", "points_mm": [
                [0, 0], [10000, 0], [10000, 6000], [0, 6000]]},
                "holes": [{"shape": "poly", "points_mm": [[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]}]},
            **fields}


def program(*ops, **envelope):
    return {"ir_version": spec.IR_VERSION, "intent": "Reference surfaces only", "ops": list(ops), **envelope}


def preview(source):
    result = surfaces.preview_reference_surfaces(source)
    assert result["refusals"] == {}, result
    assert len(result["previews"]) == 1
    return result["previews"][0]


def triangle_polygons(value):
    mesh = value["mesh"]
    return [Polygon([mesh["vertices_mm"][index][:2] for index in triangle]) for triangle in mesh["triangles"]]


@pytest.mark.parametrize("elevation,offset,bottom,top", [(5000, -300, 4700, 7500), (-2000, 450, -1550, 1250), (1200, 0, 1200, 4000)])
def test_wall_uses_real_nonzero_level_and_base_offset_without_thickness(elevation, offset, bottom, top):
    source = program(level(elevation=elevation), wall(base_offset_mm=offset))
    value = preview(source)
    assert value["mesh"] == {"vertices_mm": [[100000, -20000, bottom], [105000, -17000, bottom],
                                            [105000, -17000, top], [100000, -20000, top]],
                             "triangles": [[0, 1, 2], [0, 2, 3]]}
    assert value["surface_kind"] == "wall_axis_surface"
    assert value["source"]["dependencies"] == [{"op_id": "L", "operation_sha256": _hash(source["ops"][0])}]


def test_attached_top_uses_level_offset_instead_of_unconnected_height():
    source = program(level(), level("T", 9200), wall(base_offset_mm=-300,
        top_level={"by": "ref", "value": "T"}, top_offset_mm=-500, height_mm=1234))
    value = preview(source)
    assert [point[2] for point in value["mesh"]["vertices_mm"]] == [4700, 4700, 8700, 8700]
    assert value["source"]["dependencies"] == [
        {"op_id": op["id"], "operation_sha256": _hash(op)} for op in source["ops"][:2]]
    built = compiler.compile_program(source, revit_version="2026")
    assert built.ok, built.diagnostics
    assert "WALL_BASE_OFFSET" in built.csharp and "WALL_TOP_OFFSET" in built.csharp
    assert "+ -300" in built.csharp and "+ -500" in built.csharp


def test_same_level_positive_top_offset_has_one_dependency_and_actual_span():
    value = preview(program(level(), wall(base_offset_mm=-300,
        top_level={"by": "ref", "value": "L"}, top_offset_mm=1000)))
    assert len(value["source"]["dependencies"]) == 1
    assert [point[2] for point in value["mesh"]["vertices_mm"]] == [4700, 4700, 6000, 6000]


def test_default_height_comes_from_plan_but_digest_still_binds_raw_omission():
    operation = wall()
    operation.pop("height_mm")
    source = program(level(), operation)
    value = preview(source)
    assert value["source"]["operation_sha256"] == _hash(operation)
    planned = compiler.plan_program(source)
    height = planned.to_ops()[1]["height_mm"]
    assert value["mesh"]["vertices_mm"][2][2] == 5000 + height
    assert value["source"]["compiler_plan_digest"] == planned.plan_digest
    explicit = preview(program(level(), {**operation, "height_mm": height}))
    assert explicit["mesh"] == value["mesh"]
    assert explicit["source"]["operation_sha256"] != value["source"]["operation_sha256"]


def test_legal_null_wall_fields_follow_the_actual_emitter_height_fallback():
    operation = wall(height_mm=None, base_offset_mm=None, top_level=None, top_offset_mm=None)
    source = program(level(elevation=1200), operation)
    planned = compiler.plan_program(source)
    assert not {"height_mm", "base_offset_mm", "top_level", "top_offset_mm"} & set(planned.to_ops()[1])
    built = compiler.compile_program(planned, revit_version="2026")
    assert built.ok, built.diagnostics
    value = preview(source)
    assert [point[2] for point in value["mesh"]["vertices_mm"]] == [
        1200, 1200, 1200 + spec.DEFAULTS["wall"]["height_mm"], 1200 + spec.DEFAULTS["wall"]["height_mm"]]
    assert value["source"]["operation_sha256"] == _hash(operation)


@pytest.mark.parametrize("explicit_null", [False, True])
def test_omitted_and_null_offsets_have_the_same_authored_datum_and_attached_top(explicit_null):
    floor_fields = {"height_offset_mm": None} if explicit_null else {}
    wall_fields = {"height_mm": None, "base_offset_mm": None, "top_offset_mm": None} if explicit_null else {}
    source = program(level(elevation=1200), level("T", 9200),
        wall(top_level={"by": "ref", "value": "T"}, **wall_fields), floor(**floor_fields))
    planned = compiler.plan_program(source)
    result = surfaces.preview_reference_surfaces(source)
    assert result["refusals"] == {} and len(result["previews"]) == 2
    by_id = {value["source"]["op_id"]: value for value in result["previews"]}
    assert [point[2] for point in by_id["W"]["mesh"]["vertices_mm"]] == [1200, 1200, 9200, 9200]
    assert {point[2] for point in by_id["F"]["mesh"]["vertices_mm"]} == {1200}
    assert {value["source"]["compiler_plan_digest"] for value in result["previews"]} == {planned.plan_digest}


@pytest.mark.parametrize("offset", [-700, 0, 450])
def test_floor_triangle_union_equals_full_region_and_excludes_actual_hole(offset):
    source = program(level(elevation=-2000), floor(height_offset_mm=offset))
    value = preview(source)
    expected = Polygon(source["ops"][1]["contour"]["outer"]["points_mm"],
                       [ring["points_mm"] for ring in source["ops"][1]["contour"]["holes"]])
    triangles = triangle_polygons(value)
    assert unary_union(triangles).equals(expected)
    assert sum(triangle.area for triangle in triangles) == pytest.approx(59_000_000)
    assert all(expected.covers(triangle) for triangle in triangles)
    hole = Polygon(source["ops"][1]["contour"]["holes"][0]["points_mm"])
    assert all(triangle.intersection(hole).area == 0 for triangle in triangles)
    assert {point[2] for point in value["mesh"]["vertices_mm"]} == {-2000 + offset}
    assert value["surface_kind"] == "floor_datum_surface"
    built = compiler.compile_program(source, revit_version="2023")
    assert built.ok and "FLOOR_HEIGHTABOVELEVEL_PARAM" in built.csharp


@pytest.mark.parametrize("clockwise", [False, True])
def test_concave_floor_with_multiple_holes_keeps_exact_coverage(clockwise):
    outer = [[0, 0], [12000, 0], [12000, 4000], [8000, 4000], [8000, 9000], [0, 9000]]
    holes = [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]],
             [[3000, 5000], [5000, 5000], [5000, 7000], [3000, 7000]]]
    if clockwise:
        outer, holes = outer[::-1], [ring[::-1] for ring in holes]
    region = {"outer": {"shape": "poly", "points_mm": outer},
              "holes": [{"shape": "poly", "points_mm": ring} for ring in holes]}
    value = preview(program(level(), floor(contour=region)))
    assert unary_union(triangle_polygons(value)).equals(Polygon(outer, holes))
    for triangle in value["mesh"]["triangles"]:
        a, b, c = [value["mesh"]["vertices_mm"][index] for index in triangle]
        assert (b[0]-a[0]) * (c[1]-a[1]) - (b[1]-a[1]) * (c[0]-a[0]) > 0


def test_rect_contour_uses_the_existing_normalizer():
    region = {"outer": {"shape": "rect", "origin": [100000, -50000], "size_mm": [4000, 3000]}}
    value = preview(program(level(elevation=1200), floor(contour=region)))
    assert unary_union(triangle_polygons(value)).bounds == (100000, -50000, 104000, -47000)


@pytest.mark.parametrize("selector", [{"by": "name", "value": "L"}, {"by": "element_id", "value": 123},
                                      {"by": "ref", "value": "missing"},
                                      {"__grounded__": {"via": "ref", "ref": "L"}}])
def test_unresolved_or_pre_grounded_levels_never_fall_back_to_zero(selector):
    source = program(level(), floor(level=selector), wall(level=selector))
    result = surfaces.preview_reference_surfaces(source)
    assert result["previews"] == [] and set(result["refusals"]) == {"W", "F"}
    assert all(item["code"] in {"unresolved_level", "compiler_plan_refused"} for item in result["refusals"].values())


def test_later_level_and_orphan_top_offset_do_not_get_invented_placement():
    later = surfaces.preview_reference_surfaces(program(wall(), level()))
    assert later["previews"] == [] and "W" in later["refusals"]
    orphan = surfaces.preview_reference_surfaces(program(level(), wall(top_offset_mm=500)))
    assert orphan["refusals"]["W"]["code"] == "orphan_top_offset"
    reversed_span = surfaces.preview_reference_surfaces(program(level(), level("T", 3000),
        wall(top_level={"by": "ref", "value": "T"})))
    assert reversed_span["refusals"]["W"]["code"] == "invalid_vertical_span"


def test_curved_floor_is_refused_without_flattening_valid_wall():
    curved = floor()
    curved["contour"]["outer"]["arcs"] = [{"edge": 0, "bulge": -.1}]
    result = surfaces.preview_reference_surfaces(program(level(), curved, wall()))
    assert [item["source"]["op_id"] for item in result["previews"]] == ["W"]
    assert result["refusals"]["F"]["code"] == "unsupported_floor_contour"


def test_valid_arc_wall_is_not_replaced_by_its_chord():
    curved = wall(p0_mm=[3000, 0], p1_mm=[0, 3000], arc={"curve_type": "Arc",
        "center_mm": [0, 0, 5000], "radius_mm": 3000,
        "x_axis": [1, 0, 0], "y_axis": [0, 1, 0],
        "start_angle_rad": 0, "end_angle_rad": math.pi / 2})
    source = program(level(), curved)
    assert compiler.plan_program(source).ops
    result = surfaces.preview_reference_surfaces(source)
    assert result["previews"] == []
    assert result["refusals"]["W"]["code"] == "unsupported_wall_axis"


@pytest.mark.parametrize("effect", [
    {"op": "set_param", "id": "effect", "target": {"by": "ref", "value": "L"}, "param": "Elevation", "value": {"mm": 8000}},
    {"op": "move_elements", "id": "effect", "targets": [{"by": "ref", "value": "W"}], "delta_mm": [100, 0, 0]},
    {"op": "delete", "id": "effect", "target": {"by": "ref", "value": "W"}},
    {"op": "query_levels", "id": "effect"},
    {"op": "unknown_operation", "id": "effect"},
    {"op": "stack", "id": "effect", "levels": 3, "floor": []},
])
def test_non_create_unknown_and_macro_contexts_are_explicitly_unsupported(effect):
    result = surfaces.preview_reference_surfaces(program(level(), wall(), floor(), effect))
    assert result["previews"] == [] and set(result["refusals"]) == {"W", "F"}
    assert {item["code"] for item in result["refusals"].values()} == {"unsupported_program_context"}


@pytest.mark.parametrize("field,value", [("defaults", {}), ("phases", []), ("units", []), ("allow_destructive", False), ("metadata", {})])
def test_envelope_context_is_not_dropped(field, value):
    result = surfaces.preview_reference_surfaces(program(level(), wall(), **{field: value}))
    assert result["refusals"]["W"]["code"] == "unsupported_program_context"


def test_one_complete_batch_plan_matches_materialization_and_input_is_immutable(monkeypatch):
    _, _, project = residential_project.workflow()
    materialized = materialize_project(project, {}, bulk=True)
    source = materialized.to_program()
    before = deepcopy(source)
    calls, actual = [], compiler.plan_program
    def counted(value, *, bulk=False):
        calls.append((deepcopy(value), bulk))
        return actual(value, bulk=bulk)
    monkeypatch.setattr(compiler, "plan_program", counted)
    result = surfaces.preview_reference_surfaces(source, bulk=True)
    assert calls == [(source, True)] and source == before
    assert len(result["previews"]) == 15 and result["refusals"] == {}
    assert {item["source"]["compiler_plan_digest"] for item in result["previews"]} == {materialized.planned.plan_digest}
    indexed = {op["id"]: (index, op) for index, op in enumerate(source["ops"])}
    for value in result["previews"]:
        item = value["source"]
        assert item["operation_sha256"] == _hash(indexed[item["op_id"]][1])
        for dependency in item["dependencies"]:
            assert indexed[dependency["op_id"]][0] < indexed[item["op_id"]][0]
            assert dependency["operation_sha256"] == _hash(indexed[dependency["op_id"]][1])
        assert value["claims"] == dict(surfaces.SURFACE_CLAIMS)
        assert value["preview_digest"] == _hash({key: value for key, value in value.items() if key != "preview_digest"})
    result["previews"][0]["mesh"]["vertices_mm"][0][0] = 999
    assert source == before


@pytest.mark.parametrize("failure", ["filled_hole", "equal_area_spill", "kernel_error", "too_many_triangles"])
def test_bad_triangulation_never_becomes_a_reference_surface(monkeypatch, failure):
    from shapely.errors import GEOSException
    if failure == "filled_hole":
        faces = [Polygon([[0, 0], [10000, 0], [10000, 6000]]), Polygon([[0, 0], [10000, 6000], [0, 6000]])]
        # Both centroids are in the valid region: a centroid-only filter loses
        # the shaft. Full triangle containment/union must reject these faces.
        region = Polygon([[0, 0], [10000, 0], [10000, 6000], [0, 6000]],
                         [[[1000, 1000], [2000, 1000], [2000, 2000], [1000, 2000]]])
        assert all(region.contains(face.centroid) for face in faces)
    elif failure == "equal_area_spill":
        faces = [Polygon([[100, 0], [10100, 0], [10100, 5900]]), Polygon([[100, 0], [10100, 5900], [100, 5900]])]
        assert sum(face.area for face in faces) == 59_000_000
    elif failure == "too_many_triangles":
        faces = [Polygon([[0, 0], [1, 0], [0, 1]])] * (surfaces.MAX_SURFACE_TRIANGLES + 1)
    def bad(*args):
        if failure == "kernel_error": raise GEOSException("controlled triangulator failure")
        return faces
    monkeypatch.setattr(mesh_helpers, "_triangulate", bad)
    result = surfaces.preview_reference_surfaces(program(level(), floor()))
    assert result["previews"] == []
    expected = "triangulation_failed" if failure == "kernel_error" else "surface_budget_exceeded" if failure == "too_many_triangles" else "triangulation_coverage_mismatch"
    assert result["refusals"]["F"]["code"] == expected


@pytest.mark.parametrize("fault", ["duplicate", "missing_id", "nonfinite"])
def test_unaddressable_inputs_have_named_top_level_refusal(fault):
    source = program(level(), wall())
    if fault == "duplicate": source["ops"][1]["id"] = "L"
    elif fault == "missing_id": source["ops"][1].pop("id")
    else: source["ops"][1]["height_mm"] = float("nan")
    with pytest.raises(surfaces.ReferenceSurfaceRefusal): surfaces.preview_reference_surfaces(source)


def test_fresh_process_production_path_does_not_import_ocp_or_compile_native_source():
    child = subprocess.run([sys.executable, "-c", """
import importlib.abc, sys
class NoOcp(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'OCP' or fullname.startswith('OCP.'):
            raise AssertionError('reference display imported native geometry')
sys.meta_path.insert(0, NoOcp())
from kir import compiler
def forbidden(*args, **kwargs):
    raise AssertionError('reference display compiled native source')
compiler.compile_program = forbidden
from kir.viewer.reference_surfaces import preview_reference_surfaces
source = {'ir_version':'1.0', 'ops':[
    {'op':'create_level','id':'L','elev_mm':1200},
    {'op':'create_wall','id':'W','p0_mm':[0,0],'p1_mm':[5000,0],'level':{'by':'ref','value':'L'}},
    {'op':'create_floor_by_contour','id':'F','level':{'by':'ref','value':'L'},
     'contour':{'outer':{'shape':'rect','origin':[0,0],'size_mm':[5000,3000]}}}]}
result = preview_reference_surfaces(source)
assert len(result['previews']) == 2 and result['refusals'] == {}
assert all(point[2] >= 1200 for item in result['previews'] for point in item['mesh']['vertices_mm'])
print('two reference surfaces; no native backend')
"""], cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True, timeout=30,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "two reference surfaces; no native backend"
