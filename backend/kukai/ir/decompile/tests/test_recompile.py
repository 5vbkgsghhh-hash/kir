from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, replace

from kukai.ir.decompile.recompile import (
    IDENTITY_TRANSFORM,
    ArcCurve,
    ConicalSurface,
    CylindricalSurface,
    EllipseCurve,
    EmittedCSharp,
    FrameDefinition,
    GbCoEdge,
    GbEdge,
    GbFace,
    GbLoop,
    GbSolid,
    GeometryNode,
    GeometrySchemaError,
    GmMesh,
    LineCurve,
    NurbsCurve,
    NurbsSurface,
    PlanarSurface,
    RevolvedSurface,
    RuledSurface,
    UVBounds,
    recompile,
    recompile_node,
    surface_from_dict,
)
from kukai.llm.revit_execution_pipeline import wrap_user_code
from kukai.security.validation import validate_code_safety


def _frame(
    origin=(0.0, 0.0, 0.0),
    x=(1.0, 0.0, 0.0),
    y=(0.0, 1.0, 0.0),
    z=(0.0, 0.0, 1.0),
) -> FrameDefinition:
    return FrameDefinition(origin, x, y, z)


def _box_mesh() -> GmMesh:
    vertices = (
        (0.0, 0.0, 0.0),
        (1000.0, 0.0, 0.0),
        (1000.0, 2000.0, 0.0),
        (0.0, 2000.0, 0.0),
        (0.0, 0.0, 3000.0),
        (1000.0, 0.0, 3000.0),
        (1000.0, 2000.0, 3000.0),
        (0.0, 2000.0, 3000.0),
    )
    triangles = (
        (0, 2, 1), (0, 3, 2),
        (4, 5, 6), (4, 6, 7),
        (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5),
        (2, 3, 7), (2, 7, 6),
        (3, 0, 4), (3, 4, 7),
    )
    return GmMesh(vertices, triangles)


def _loop(*coedges: tuple[str, bool]) -> GbLoop:
    return GbLoop(tuple(GbCoEdge(edge_id, reversed_) for edge_id, reversed_ in coedges))


def _box_solid(*, candidate_valid: bool = True) -> GbSolid:
    points = {
        "0": (0.0, 0.0, 0.0),
        "1": (1000.0, 0.0, 0.0),
        "2": (1000.0, 2000.0, 0.0),
        "3": (0.0, 2000.0, 0.0),
        "4": (0.0, 0.0, 3000.0),
        "5": (1000.0, 0.0, 3000.0),
        "6": (1000.0, 2000.0, 3000.0),
        "7": (0.0, 2000.0, 3000.0),
    }
    pairs = (
        ("e01", "0", "1"), ("e12", "1", "2"),
        ("e23", "2", "3"), ("e30", "3", "0"),
        ("e45", "4", "5"), ("e56", "5", "6"),
        ("e67", "6", "7"), ("e74", "7", "4"),
        ("e04", "0", "4"), ("e15", "1", "5"),
        ("e26", "2", "6"), ("e37", "3", "7"),
    )
    edges = tuple(
        GbEdge(edge_id, LineCurve(points[start], points[end]))
        for edge_id, start, end in pairs
    )
    faces = (
        GbFace(
            PlanarSurface(_frame(
                points["0"], (1.0, 0.0, 0.0),
                (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))),
            False,
            (_loop(("e30", True), ("e23", True),
                   ("e12", True), ("e01", True)),),
        ),
        GbFace(
            PlanarSurface(_frame(points["4"])),
            False,
            (_loop(("e45", False), ("e56", False),
                   ("e67", False), ("e74", False)),),
        ),
        GbFace(
            PlanarSurface(_frame(
                points["0"], (1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0), (0.0, -1.0, 0.0))),
            False,
            (_loop(("e01", False), ("e15", False),
                   ("e45", True), ("e04", True)),),
        ),
        GbFace(
            PlanarSurface(_frame(
                points["1"], (0.0, 1.0, 0.0),
                (0.0, 0.0, 1.0), (1.0, 0.0, 0.0))),
            False,
            (_loop(("e12", False), ("e26", False),
                   ("e56", True), ("e15", True)),),
        ),
        GbFace(
            PlanarSurface(_frame(
                points["2"], (-1.0, 0.0, 0.0),
                (0.0, 0.0, 1.0), (0.0, 1.0, 0.0))),
            False,
            (_loop(("e23", False), ("e37", False),
                   ("e67", True), ("e26", True)),),
        ),
        GbFace(
            PlanarSurface(_frame(
                points["3"], (0.0, -1.0, 0.0),
                (0.0, 0.0, 1.0), (-1.0, 0.0, 0.0))),
            False,
            (_loop(("e30", False), ("e04", False),
                   ("e74", True), ("e37", True)),),
        ),
    )
    return GbSolid(
        edges=edges,
        faces=faces,
        fallback_mesh=_box_mesh(),
        brep_candidate_valid=candidate_valid,
    )


def _cylinder_mesh(segments: int = 8) -> GmMesh:
    radius = 500.0
    height = 1200.0
    bottom = tuple(
        (radius * math.cos(math.tau * index / segments),
         radius * math.sin(math.tau * index / segments), 0.0)
        for index in range(segments))
    top = tuple((x, y, height) for x, y, _z in bottom)
    vertices = bottom + top + ((0.0, 0.0, 0.0), (0.0, 0.0, height))
    bottom_center = 2 * segments
    top_center = bottom_center + 1
    triangles: list[tuple[int, int, int]] = []
    for index in range(segments):
        nxt = (index + 1) % segments
        triangles.append((bottom_center, nxt, index))
        triangles.append((top_center, segments + index, segments + nxt))
        triangles.append((index, nxt, segments + nxt))
        triangles.append((index, segments + nxt, segments + index))
    return GmMesh(vertices, tuple(triangles))


def _cylinder_solid() -> GbSolid:
    radius = 500.0
    height = 1200.0
    circle = dict(
        radius_mm=radius,
        x_axis=(1.0, 0.0, 0.0),
        y_axis=(0.0, 1.0, 0.0),
        start_angle_rad=0.0,
        end_angle_rad=math.tau,
    )
    edges = (
        GbEdge("bottom", ArcCurve(center_mm=(0.0, 0.0, 0.0), **circle)),
        GbEdge("top", ArcCurve(center_mm=(0.0, 0.0, height), **circle)),
    )
    faces = (
        GbFace(
            PlanarSurface(_frame(
                (0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))),
            False,
            (_loop(("bottom", True)),),
        ),
        GbFace(
            PlanarSurface(_frame((0.0, 0.0, height))),
            False,
            (_loop(("top", False)),),
        ),
        GbFace(
            CylindricalSurface(_frame(), radius),
            False,
            (_loop(("bottom", False)), _loop(("top", True))),
        ),
    )
    return GbSolid(edges, faces, _cylinder_mesh())


def _translated(dx_mm: float, dy_mm: float, dz_mm: float):
    return (
        1.0, 0.0, 0.0, dx_mm,
        0.0, 1.0, 0.0, dy_mm,
        0.0, 0.0, 1.0, dz_mm,
        0.0, 0.0, 0.0, 1.0,
    )


def _surface_probe_solid(
    surface,
    *,
    edge_curve=None,
    uv_bounds: UVBounds | None = None,
) -> GbSolid:
    """Compile-only topology probe for non-acceptance surface/curve branches.

    Two one-edge faces are not claimed as a runtime-valid solid. The fixture
    exists only to make Roslyn type-check every universal emitter branch; the
    actual acceptance solids remain the box and cylinder above.
    """

    curve = edge_curve or LineCurve(
        (0.0, 0.0, 0.0), (1000.0, 0.0, 0.0))
    return GbSolid(
        edges=(GbEdge("probe-edge", curve),),
        faces=(
            GbFace(
                surface,
                False,
                (_loop(("probe-edge", False)),),
                uv_bounds,
            ),
            GbFace(
                PlanarSurface(_frame()),
                False,
                (_loop(("probe-edge", True)),),
            ),
        ),
        fallback_mesh=GmMesh(
            ((0.0, 0.0, 0.0),
             (1000.0, 0.0, 0.0),
             (0.0, 1000.0, 0.0)),
            ((0, 1, 2),),
        ),
    )


def _all_api_probe_nodes() -> tuple[GeometryNode, ...]:
    profile = LineCurve(
        (100.0, 0.0, 0.0), (100.0, 0.0, 1000.0))
    nurbs_surface = NurbsSurface(
        degree_u=1,
        degree_v=1,
        control_count_u=2,
        control_count_v=2,
        knots_u=(0.0, 0.0, 1.0, 1.0),
        knots_v=(0.0, 0.0, 1.0, 1.0),
        control_points_mm=(
            (0.0, 0.0, 0.0), (0.0, 1000.0, 0.0),
            (1000.0, 0.0, 0.0), (1000.0, 1000.0, 100.0),
        ),
        weights=(1.0, 1.0, 1.0, 1.0),
        reverse_orientation=True,
    )
    ellipse = EllipseCurve(
        center_mm=(0.0, 0.0, 0.0),
        radius_x_mm=500.0,
        radius_y_mm=250.0,
        x_axis=(1.0, 0.0, 0.0),
        y_axis=(0.0, 1.0, 0.0),
        start_angle_rad=0.0,
        end_angle_rad=math.pi,
    )
    nurbs_curve = NurbsCurve(
        degree=2,
        knots=(0.0, 0.0, 0.0, 1.0, 1.0, 1.0),
        control_points_mm=(
            (0.0, 0.0, 0.0),
            (500.0, 250.0, 0.0),
            (1000.0, 0.0, 0.0),
        ),
        weights=(1.0, 0.8, 1.0),
    )
    probes = (
        ("conical", _surface_probe_solid(
            ConicalSurface(_frame(), math.pi / 6.0))),
        ("revolved", _surface_probe_solid(
            RevolvedSurface(_frame(), profile))),
        ("ruled", _surface_probe_solid(
            RuledSurface(
                profile,
                profile_b=LineCurve(
                    (200.0, 0.0, 0.0),
                    (200.0, 0.0, 1000.0))))),
        ("nurbs-surface", _surface_probe_solid(
            nurbs_surface,
            uv_bounds=UVBounds(0.0, 0.0, 1.0, 1.0))),
        ("ellipse-edge", _surface_probe_solid(
            PlanarSurface(_frame()), edge_curve=ellipse)),
        ("nurbs-edge", _surface_probe_solid(
            PlanarSurface(_frame()), edge_curve=nurbs_curve)),
    )
    return tuple(
        GeometryNode(name, "OST_GenericModel", solid)
        for name, solid in probes)


def _gate_emissions() -> dict[str, EmittedCSharp]:
    """Canonical set whose wrapped bodies are gated 6/6 for Wave G."""

    categories = recompile(tuple(
        GeometryNode(
            f"category-{index}", category, _box_mesh())
        for index, category in enumerate((
            "OST_Walls", "OST_Floors", "OST_Furniture"))))
    return {
        "planar_box_gb": recompile_node(GeometryNode(
            "box", "OST_Walls", _box_solid())),
        "cylinder_gb": recompile_node(GeometryNode(
            "cylinder", "OST_Columns", _cylinder_solid())),
        "triangle_mesh_gm": recompile_node(GeometryNode(
            "mesh", "OST_GenericModel",
            GmMesh(
                ((0.0, 0.0, 0.0),
                 (1000.0, 0.0, 0.0),
                 (0.0, 1000.0, 0.0)),
                ((0, 1, 2),)))),
        "category_batch": categories,
        "two_instances": recompile_node(GeometryNode(
            "instances",
            "OST_StructuralColumns",
            _box_solid(),
            (IDENTITY_TRANSFORM, _translated(5000.0, 6000.0, 3000.0)))),
        "invalid_gb_preflight": recompile_node(GeometryNode(
            "invalid", "OST_Floors",
            _box_solid(candidate_valid=False))),
        "all_surface_curve_api": recompile(_all_api_probe_nodes()),
    }


class TierGSchemaTests(unittest.TestCase):
    def test_box_node_is_frozen_json_ready_and_round_trips(self) -> None:
        node = GeometryNode(
            "box-def",
            "OST_Walls",
            _box_solid(),
            (IDENTITY_TRANSFORM, _translated(5000.0, 0.0, 0.0)),
        )

        encoded = json.dumps(node.to_dict(), ensure_ascii=False, sort_keys=True)
        decoded = GeometryNode.from_dict(json.loads(encoded))

        self.assertEqual(decoded, node)
        self.assertEqual(decoded.geometry.tier.value, "Gb")
        self.assertEqual(len(decoded.transforms), 2)
        with self.assertRaises(FrozenInstanceError):
            node.category = "OST_Floors"  # type: ignore[misc]

    def test_cylinder_has_explicit_cylindrical_surface_and_mesh_floor(self) -> None:
        solid = _cylinder_solid()
        self.assertEqual(len(solid.faces), 3)
        self.assertTrue(any(
            isinstance(face.surface, CylindricalSurface)
            for face in solid.faces))
        self.assertGreater(len(solid.fallback_mesh.triangles), 0)

    def test_all_surface_contracts_round_trip(self) -> None:
        profile = LineCurve((100.0, 0.0, 0.0), (100.0, 0.0, 1000.0))
        surfaces = (
            PlanarSurface(_frame()),
            CylindricalSurface(_frame(), 250.0),
            ConicalSurface(_frame(), math.pi / 6.0),
            RevolvedSurface(_frame(), profile),
            RuledSurface(
                profile,
                profile_b=LineCurve(
                    (200.0, 0.0, 0.0), (200.0, 0.0, 1000.0))),
            NurbsSurface(
                degree_u=1,
                degree_v=1,
                control_count_u=2,
                control_count_v=2,
                knots_u=(0.0, 0.0, 1.0, 1.0),
                knots_v=(0.0, 0.0, 1.0, 1.0),
                control_points_mm=(
                    (0.0, 0.0, 0.0), (0.0, 1000.0, 0.0),
                    (1000.0, 0.0, 0.0), (1000.0, 1000.0, 100.0),
                ),
            ),
        )

        for surface in surfaces:
            with self.subTest(surface=surface.surface_type.value):
                self.assertEqual(surface_from_dict(surface.to_dict()), surface)

        bspline = surfaces[-1].to_dict()
        bspline["surface_type"] = "BSpline"
        self.assertEqual(surface_from_dict(bspline), surfaces[-1])

    def test_bad_face_without_loop_is_typed_refusal(self) -> None:
        with self.assertRaisesRegex(GeometrySchemaError, "at least one edge loop"):
            GbFace(PlanarSurface(_frame()), False, ())

    def test_dangling_face_edge_is_typed_refusal(self) -> None:
        solid = _box_solid()
        bad_loop = replace(
            solid.faces[0].loops[0],
            coedges=(GbCoEdge("missing", True),)
        )
        bad_face = replace(solid.faces[0], loops=(bad_loop,))
        with self.assertRaisesRegex(GeometrySchemaError, "unknown edge"):
            replace(solid, faces=(bad_face,) + solid.faces[1:])

    def test_non_manifold_edge_is_typed_refusal(self) -> None:
        solid = _box_solid()
        first_loop = solid.faces[0].loops[0]
        bad_loop = replace(
            first_loop,
            coedges=first_loop.coedges[:-1],
        )
        with self.assertRaisesRegex(GeometrySchemaError, "exactly two coedges"):
            replace(
                solid,
                faces=(replace(solid.faces[0], loops=(bad_loop,)),)
                + solid.faces[1:],
            )

    def test_degenerate_triangle_is_typed_refusal(self) -> None:
        with self.assertRaisesRegex(GeometrySchemaError, "degenerate"):
            GmMesh(
                ((0.0, 0.0, 0.0),
                 (1.0, 0.0, 0.0),
                 (2.0, 0.0, 0.0)),
                ((0, 1, 2),),
            )

    def test_triangle_index_out_of_range_is_typed_refusal(self) -> None:
        with self.assertRaisesRegex(GeometrySchemaError, "out of range"):
            GmMesh(
                ((0.0, 0.0, 0.0),
                 (1.0, 0.0, 0.0),
                 (0.0, 1.0, 0.0)),
                ((0, 1, 3),),
            )

    def test_non_16_transform_is_typed_refusal(self) -> None:
        with self.assertRaisesRegex(GeometrySchemaError, "exactly 16"):
            GeometryNode(
                "mesh",
                "OST_GenericModel",
                _box_mesh(),
                ((1.0, 0.0, 0.0),),  # type: ignore[arg-type]
            )

    def test_singular_transform_is_typed_refusal(self) -> None:
        singular = (
            0.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        )
        with self.assertRaisesRegex(GeometrySchemaError, "invertible"):
            GeometryNode(
                "mesh", "OST_GenericModel", _box_mesh(), (singular,))

    def test_category_is_syntax_checked_not_spliced(self) -> None:
        with self.assertRaisesRegex(GeometrySchemaError, r"OST_\*"):
            GeometryNode(
                "mesh", "OST_Walls); DROP", _box_mesh(),
                (IDENTITY_TRANSFORM,))

    def test_nurbs_face_requires_native_parameter_envelope(self) -> None:
        surface = NurbsSurface(
            degree_u=1,
            degree_v=1,
            control_count_u=2,
            control_count_v=2,
            knots_u=(0.0, 0.0, 1.0, 1.0),
            knots_v=(0.0, 0.0, 1.0, 1.0),
            control_points_mm=(
                (0.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                (1.0, 0.0, 0.0), (1.0, 1.0, 0.0),
            ),
        )
        with self.assertRaisesRegex(GeometrySchemaError, "uv_bounds"):
            GbFace(surface, False, (_loop(("edge", False)),))
        face = GbFace(
            surface, False, (_loop(("edge", False)),),
            UVBounds(0.0, 0.0, 1.0, 1.0))
        self.assertEqual(face.uv_bounds.max_u, 1.0)


class RecompileEmitterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.emissions = _gate_emissions()

    def test_planar_box_emits_exact_brep_and_guarded_mesh_floor(self) -> None:
        result = self.emissions["planar_box_gb"]
        body = result.csharp

        self.assertEqual(result.chosen_tier.value, "Gb")
        self.assertFalse(result.degraded_to_gm)
        self.assertEqual(result.direct_shape_count, 1)
        self.assertIn("new BRepBuilder(BRepType.Solid)", body)
        self.assertEqual(body.count("BRepBuilderSurfaceGeometry.Create(Plane.Create"), 6)
        # Six explicit BRep faces; the fallback's 12 triangles use one looped
        # TessellatedShapeBuilder.AddFace call over the frozen index table.
        self.assertEqual(body.count(".AddFace("), 7)
        self.assertIn("BRepBuilderOutcome.Success", body)
        self.assertIn("GetResult()", body)
        self.assertIn("TessellatedShapeBuilder", body)
        self.assertIn("catch (Exception __g0_gbEx)", body)

    def test_cylinder_emits_cylindrical_surface_and_circular_edges(self) -> None:
        body = self.emissions["cylinder_gb"].csharp

        self.assertIn("CylindricalSurface.Create", body)
        self.assertEqual(body.count("Arc.Create("), 2)
        self.assertIn("__U(500.0)", body)
        self.assertIn("BRepBuilderOutcome.Success", body)

    def test_gm_mesh_uses_tessellated_builder_result(self) -> None:
        result = self.emissions["triangle_mesh_gm"]
        body = result.csharp

        self.assertEqual(result.chosen_tier.value, "Gm")
        self.assertFalse(result.degraded_to_gm)
        self.assertNotIn("new BRepBuilder(", body)
        self.assertIn("new TessellatedShapeBuilder()", body)
        self.assertIn("OpenConnectedFaceSet(false)", body)
        self.assertIn("TessellatedShapeBuilderTarget.AnyGeometry", body)
        self.assertIn("TessellatedShapeBuilderFallback.Mesh", body)
        self.assertIn("GetBuildResult().GetGeometricalObjects()", body)

    def test_original_category_is_runtime_parsed_and_never_reclassified(self) -> None:
        body = self.emissions["category_batch"].csharp

        for category in ("OST_Walls", "OST_Floors", "OST_Furniture"):
            self.assertIn(
                f'Enum.TryParse<BuiltInCategory>("{category}", false', body)
            self.assertIn(
                f'"category"] = "{category}"', body)
        self.assertEqual(body.count("DirectShape.IsValidCategoryId"), 3)
        self.assertNotIn("BuiltInCategory.OST_GenericModel", body)

    def test_one_definition_two_transforms_creates_two_direct_shapes(self) -> None:
        result = self.emissions["two_instances"]
        body = result.csharp

        self.assertEqual(result.direct_shape_count, 2)
        self.assertEqual(body.count("new BRepBuilder(BRepType.Solid)"), 1)
        self.assertEqual(body.count("var __g0_meshVertices = new XYZ[]"), 1)
        self.assertIn("__g0_i0_xf.Origin = __P(0.0, 0.0, 0.0)", body)
        self.assertIn(
            "__g0_i1_xf.Origin = __P(5000.0, 6000.0, 3000.0)", body)
        # Each instance has mutually exclusive Gb and Gm creation sites.
        self.assertEqual(body.count("DirectShape.CreateElement(doc, __g0_categoryId)"), 4)

    def test_invalid_gb_is_preflight_degraded_and_never_builds_brep(self) -> None:
        result = self.emissions["invalid_gb_preflight"]
        body = result.csharp

        self.assertEqual(result.chosen_tier.value, "Gm")
        self.assertTrue(result.degraded_to_gm)
        self.assertEqual(result.nodes[0].requested_tier.value, "Gb")
        self.assertTrue(result.nodes[0].degraded_to_gm)
        self.assertNotIn("new BRepBuilder(", body)
        self.assertIn('string __g0_gbError = "brep_candidate_valid=false";', body)
        self.assertIn("bool __g0_degraded = true;", body)
        self.assertIn("new TessellatedShapeBuilder()", body)

    def test_runtime_failures_are_local_and_return_typed_results(self) -> None:
        body = self.emissions["planar_box_gb"].csharp

        self.assertIn("SubTransaction", body)
        self.assertIn("RollBack()", body)
        self.assertIn('result["degraded_to_gm"]', body)
        self.assertIn('result["degradation_reason"]', body)
        self.assertIn('__results["failed_count"]', body)
        self.assertNotIn("throw;", body)
        self.assertNotIn("throw new", body)

    def test_all_surface_and_curve_api_branches_are_emitted(self) -> None:
        body = self.emissions["all_surface_curve_api"].csharp

        for token in (
            "ConicalSurface.Create",
            "RevolvedSurface.Create",
            "RuledSurface.Create",
            "BRepBuilderSurfaceGeometry.CreateNURBSSurface",
            "Ellipse.CreateCurve",
            "NurbSpline.CreateCurve",
        ):
            self.assertIn(token, body)

    def test_batch_has_one_transaction_and_json_ready_static_result(self) -> None:
        result = self.emissions["category_batch"]

        self.assertEqual(result.direct_shape_count, 3)
        self.assertEqual(len(result.nodes), 3)
        self.assertEqual(result.csharp.count("new Transaction(doc"), 1)
        self.assertEqual(result.csharp.count("return __results;"), 4)
        json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True)

    def test_every_canonical_body_uses_standard_wrapper_and_passes_safety(self) -> None:
        for name, result in self.emissions.items():
            with self.subTest(name=name):
                self.assertIsNone(validate_code_safety(result.csharp))
                wrapped = wrap_user_code(result.csharp)
                self.assertIn(
                    "public static object Execute(Document doc, UIDocument uidoc)",
                    wrapped,
                )
                self.assertNotIn("304.8", result.csharp)
                self.assertIn("UnitUtils.ConvertToInternalUnits", result.csharp)
                self.assertIn(".Id.ToString()", result.csharp)

    def test_same_node_is_byte_identical_under_two_hash_seeds(self) -> None:
        script = (
            "import hashlib; "
            "from kukai.ir.decompile.recompile import GeometryNode,recompile_node; "
            "from kukai.ir.decompile.tests.test_recompile import _box_solid; "
            "body=recompile_node(GeometryNode('box','OST_Walls',_box_solid())).csharp; "
            "print(hashlib.sha256(body.encode('utf-8')).hexdigest())"
        )
        hashes = []
        for seed in ("1", "8675309"):
            env = dict(os.environ)
            env["PYTHONHASHSEED"] = seed
            hashes.append(subprocess.check_output(
                [sys.executable, "-c", script],
                env=env,
                text=True,
            ).strip())
        self.assertEqual(hashes[0], hashes[1])

    def test_duplicate_batch_node_id_refuses(self) -> None:
        node = GeometryNode("same", "OST_GenericModel", _box_mesh())
        with self.assertRaisesRegex(GeometrySchemaError, "unique"):
            recompile((node, node))


if __name__ == "__main__":
    unittest.main()
