"""Independent native checks of the body-to-mesh ownership boundary."""
from __future__ import annotations

import base64
from collections import Counter
import hashlib
import io

import pytest

from kir.geometry_materialization import materialize_project
from kir.occt_geometry import GeometryBundle, capture_body
from kir.project import (BodyRepresentation, ModuleDefinition, ModuleInstance,
                         NamedOutput, PROJECT_SCHEMA_V2, ProjectRevision,
                         RecipePin, _hash)
from kir.project_store import GEOMETRY_STORE_SCHEMA, ProjectStore


PIN = RecipePin("independent analytic box fixture; not executed on load", "a" * 64)


def _box_with_contradictory_embedded_triangulation():
    pytest.importorskip("OCP")
    from OCP import (BRep, BRepMesh, BRepPrimAPI, BRepTools, Poly, TopAbs,
                     TopExp, TopLoc, TopoDS, TopTools)
    from OCP.gp import gp_Pnt, gp_Pnt2d

    captured = capture_body(BRepPrimAPI.BRepPrimAPI_MakeBox(1000, 2000, 3000).Shape(),
        project_id="p", instance_key="i", output_key="body", recipe=PIN, parameters={})
    body = captured.read_body()
    BRepMesh.BRepMesh_IncrementalMesh(body, 20., False, .3, False)
    face = TopoDS.TopoDS.Face_s(TopExp.TopExp_Explorer(body, TopAbs.TopAbs_FACE).Current())
    triangulation = BRep.BRep_Tool.Triangulation_s(face, TopLoc.TopLoc_Location())
    edges = []
    for index in range(1, triangulation.NbTriangles() + 1):
        a, b, c = triangulation.Triangle(index).Get()
        edges.extend(((a, b), (b, c), (c, a)))
    counts = Counter(tuple(sorted(edge)) for edge in edges)
    boundary = [edge for edge in edges if counts[tuple(sorted(edge))] == 1]
    count = triangulation.NbNodes()
    assert count == 4 and len(boundary) == 4
    points = [triangulation.Node(index) for index in range(1, count + 1)]
    uv_points = [triangulation.UVNode(index) for index in range(1, count + 1)]

    # Preserve every geometric surface, edge and triangulation boundary node.
    # Only an interior cached mesh point lies far outside the actual box.
    triangulation.ResizeNodes(count + 1, True)
    triangulation.SetNode(count + 1, gp_Pnt(
        sum(point.X() for point in points) / count + 10000,
        sum(point.Y() for point in points) / count,
        sum(point.Z() for point in points) / count))
    triangulation.SetUVNode(count + 1, gp_Pnt2d(
        sum(point.X() for point in uv_points) / count,
        sum(point.Y() for point in uv_points) / count))
    triangulation.ResizeTriangles(len(boundary), False)
    for index, (a, b) in enumerate(boundary, 1):
        triangulation.SetTriangle(index, Poly.Poly_Triangle(a, b, count + 1))
    assert max(triangulation.Node(index).X()
               for index in range(1, triangulation.NbNodes() + 1)) == 10000

    stream = io.BytesIO()
    BRepTools.BRepTools.Write_s(body, stream, True, False,
        TopTools.TopTools_FormatVersion.TopTools_FormatVersion_VERSION_3)
    raw = stream.getvalue()
    data = captured.to_dict()
    digest = hashlib.sha256(raw).hexdigest()
    data["brep_base64"] = base64.b64encode(raw).decode("ascii")
    data["manifest"]["brep"].update(sha256=digest, size_bytes=len(raw))
    data["manifest"]["preview"]["body_sha256"] = digest
    data["bundle_sha256"] = _hash({key: value for key, value in data.items()
                                   if key != "bundle_sha256"})
    # Inert loading validates hashes, not the claimed no-mesh representation.
    return GeometryBundle(data)


def _project(bundle):
    return ProjectRevision("p", [ModuleDefinition("m", "sealed_evaluation", PIN)],
        [ModuleInstance("i", "m", [NamedOutput("body",
            {"op": "create_directshape", "name": "Actual box", "category": "mass"},
            BodyRepresentation(bundle.digest, bundle.body_digest))])], schema=PROJECT_SCHEMA_V2)


@pytest.mark.parametrize("through_store", [False, True])
def test_native_materialization_discards_embedded_polygon_cache(tmp_path, through_store):
    bundle = _box_with_contradictory_embedded_triangulation()
    project = _project(bundle)
    before = bundle.dumps(), project.dumps()
    # Actual native BRepCheck/analytic measurement accept the geometric box.
    facts = bundle.measure()
    assert facts["bbox_min_mm"] == pytest.approx([0, 0, 0])
    assert facts["bbox_max_mm"] == pytest.approx([1000, 2000, 3000])
    assert facts["volume_mm3"] == pytest.approx(6e9)
    if through_store:
        path = tmp_path / "body.sqlite"
        ProjectStore.create(path, project, schema=GEOMETRY_STORE_SCHEMA, assets=[bundle])
        store = ProjectStore.open(path)
        project, bundle = store.head(), store.get_asset(bundle.digest)

    materialized = materialize_project(project, {bundle.digest: bundle})
    mesh = materialized.to_program()["ops"][0]["mesh"]
    assert max(point[0] for point in mesh["vertices_mm"]) == pytest.approx(1000)
    assert materialized.sources[0]["mesh_origin"] == "rederived_from_brep"
    assert materialized.sources[0]["measurements"]["bbox_max_mm"] == pytest.approx([1000, 2000, 3000])
    assert materialized.sources[0]["source_bundle_sha256"] == bundle.digest
    assert materialized.sources[0]["source_body_sha256"] == bundle.body_digest
    assert (bundle.dumps(), project.dumps()) == before
