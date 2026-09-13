from __future__ import annotations

import unittest

from kir.decompile.geometry_store import (
    GEOMETRY_HELPER_CS,
    ExtractedGeometry,
    parse_geometry,
)
from kir.decompile.schema import GeometryKind, L0SchemaError


class GeometryParserTests(unittest.TestCase):
    def test_curve(self) -> None:
        geometry = parse_geometry({
            "geom_kind": "curve",
            "p0_mm": [0, 1, 2],
            "p1_mm": [3, 4, 5],
            "rotation_deg": None,
            "bbox_min_mm": [-1, 0, 1],
            "bbox_max_mm": [4, 5, 6],
        })
        self.assertEqual(geometry.geom_kind, GeometryKind.CURVE)
        self.assertEqual(geometry.p0_mm, (0.0, 1.0, 2.0))
        self.assertEqual(geometry.p1_mm, (3.0, 4.0, 5.0))

    def test_point_with_rotation(self) -> None:
        geometry = parse_geometry({
            "geom_kind": "point",
            "p0_mm": [100, 200, 300],
            "p1_mm": None,
            "rotation_deg": 22.5,
            "bbox_min_mm": [90, 190, 290],
            "bbox_max_mm": [110, 210, 310],
        })
        self.assertEqual(geometry.geom_kind, GeometryKind.POINT)
        self.assertEqual(geometry.rotation_deg, 22.5)

    def test_bbox_only(self) -> None:
        geometry = parse_geometry({
            "geom_kind": "bbox_only",
            "p0_mm": None,
            "p1_mm": None,
            "rotation_deg": None,
            "bbox_min_mm": [0, 0, 0],
            "bbox_max_mm": [1, 2, 3],
        })
        self.assertEqual(geometry.geom_kind, GeometryKind.BBOX_ONLY)

    def test_absent_bbox_is_honest_not_synthetic(self) -> None:
        geometry = parse_geometry({
            "geom_kind": "bbox_only",
            "p0_mm": None,
            "p1_mm": None,
            "rotation_deg": None,
            "bbox_min_mm": None,
            "bbox_max_mm": None,
        })
        self.assertIsNone(geometry.bbox_min_mm)
        self.assertIsNone(geometry.bbox_max_mm)

    def test_half_bbox_refuses(self) -> None:
        with self.assertRaisesRegex(L0SchemaError, "both be present"):
            parse_geometry({
                "geom_kind": "bbox_only",
                "p0_mm": None,
                "p1_mm": None,
                "rotation_deg": None,
                "bbox_min_mm": [0, 0, 0],
                "bbox_max_mm": None,
            })

    def test_point_without_rotation_is_accepted(self) -> None:
        """Previously the opposite assertion stood here, and it entrenched the defect.

        The invariant "a point must carry a rotation" was written in
        the confidence that `LocationPoint.Rotation` is always
        available. Autodesk documents the opposite across all six
        versions: for rooms, zones, groups, and model text this
        property is unsupported and throws. By requiring the pair, the
        schema forced emission to lose the point ALONG WITH the
        rotation — measured 07-29: 12,369 rooms and 566 zones across
        four buildings, not a single point. Details and the
        counter-invariants are in `test_point_without_rotation.py`.
        """
        geometry = parse_geometry({
            "geom_kind": "point",
            "p0_mm": [0, 0, 0],
            "p1_mm": None,
            "rotation_deg": None,
            "bbox_min_mm": None,
            "bbox_max_mm": None,
        })
        self.assertIsNone(geometry.rotation_deg)
        self.assertEqual(list(geometry.p0_mm), [0.0, 0.0, 0.0])

    def test_bbox_min_must_not_exceed_max(self) -> None:
        with self.assertRaisesRegex(L0SchemaError, "must not exceed"):
            ExtractedGeometry(
                GeometryKind.BBOX_ONLY, None, None, None,
                (2.0, 0.0, 0.0), (1.0, 1.0, 1.0))


class GeometryCSharpContractTests(unittest.TestCase):
    def test_location_precedence_and_bbox_attempt(self) -> None:
        self.assertIn("get_BoundingBox(null)", GEOMETRY_HELPER_CS)
        self.assertIn("LocationCurve", GEOMETRY_HELPER_CS)
        self.assertIn("LocationPoint", GEOMETRY_HELPER_CS)
        self.assertIn("GetEndPoint(0)", GEOMETRY_HELPER_CS)
        self.assertIn("GetEndPoint(1)", GEOMETRY_HELPER_CS)
        self.assertIn("__lp.Rotation * 180.0 / Math.PI", GEOMETRY_HELPER_CS)
        self.assertLess(
            GEOMETRY_HELPER_CS.index("get_BoundingBox(null)"),
            GEOMETRY_HELPER_CS.index("var __lc"))

    def test_units_are_delegated_to_unitutils_helper(self) -> None:
        self.assertIn("__MM(__p.X)", GEOMETRY_HELPER_CS)
        self.assertNotIn("304.8", GEOMETRY_HELPER_CS)
        self.assertNotIn("Transaction", GEOMETRY_HELPER_CS)


if __name__ == "__main__":
    unittest.main()
