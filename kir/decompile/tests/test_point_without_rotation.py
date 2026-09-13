"""A point is not required to carry a rotation — otherwise the point itself is lost too.

A trap-index finding from 29.07, and its cost, measured before the fix.

``LocationPoint.Rotation`` is documented by Autodesk as UNSUPPORTED for some
elements and throws ``InvalidOperationException`` (RevitAPI.xml, all six
versions 2021–2026, ``P:Autodesk.Revit.DB.LocationPoint.Rotation``): *"This
property is not supported for some elements supporting LocationPoints, such as
AssemblyInstances, Groups, ModelText, Room, and SpotDimensions."*

In ``geometry_store`` this read stood BEFORE the three assignments and inside
the shared ``catch`` covering the entire location block. That means a room, a zone, model text
silently lost not only the rotation but the POINT ITSELF, and the element went into L0 as
``bbox_only``. A measurement over 55 saved runs of four buildings: **12 369
rooms and 566 zones, every single one with ``geom_kind: bbox_only``, ``p0_mm:
null``** — not one room in any model ever got its point.

The same handwriting, by exactly the same API member, already cost us 96.77% of the groups
(commit 3f54267f); here it is found as the second site of the same class.

A second invariant, lifted together with the first: strict parsing REQUIRED a rotation for
point-based geometry. The requirement was written in the confidence that rotation
is always available, and it was this same requirement that forced emission to choose between
"point without rotation" and "nothing"; "nothing" was chosen. The absence of a rotation on a room is
a fact about the model, and the lift already refuses in a typed way wherever it needs a rotation.

Discipline §18.7: a refuting test BEFORE the fix.
"""
from __future__ import annotations

import unittest

from kir.decompile.geometry_store import (
    GEOMETRY_HELPER_CS,
    parse_geometry,
)
from kir.decompile.schema import L0Element, L0SchemaError
from kir.decompile.tests.fixtures_decompile import make_element


def _point_row(**overrides):
    row = {
        "geom_kind": "point",
        "curve_kind": None,
        "p0_mm": [1000.0, 2000.0, 0.0],
        "p1_mm": None,
        "rotation_deg": None,
        "bbox_min_mm": None,
        "bbox_max_mm": None,
    }
    row.update(overrides)
    return row


class PointWithoutRotationParses(unittest.TestCase):
    """A room arrives with a point and without a rotation — this is a legitimate line."""

    def test_geometry_store_accepts_point_without_rotation(self):
        geometry = parse_geometry(_point_row())
        self.assertEqual(list(geometry.p0_mm), [1000.0, 2000.0, 0.0])
        self.assertIsNone(geometry.rotation_deg)

    def test_l0_element_accepts_point_without_rotation(self):
        row = make_element("OST_Rooms", 77001)
        row.update(_point_row())
        element = L0Element.from_dict(row)
        self.assertIsNone(element.rotation_deg)
        self.assertEqual(list(element.p0_mm), [1000.0, 2000.0, 0.0])

    def test_point_still_requires_its_point(self):
        """The relaxation concerns ONLY the rotation: a point without a point is still
        a schema error, otherwise `geom_kind: point` would stop meaning anything."""
        with self.assertRaises(L0SchemaError):
            parse_geometry(_point_row(p0_mm=None))

    def test_curve_still_refuses_rotation(self):
        """The counter-invariant is untouched: a curve cannot have a rotation."""
        with self.assertRaises(L0SchemaError):
            parse_geometry({
                **_point_row(),
                "geom_kind": "curve",
                "curve_kind": "line",
                "p1_mm": [2000.0, 2000.0, 0.0],
                "rotation_deg": 30.0,
            })


class EmissionOrderIsTheFix(unittest.TestCase):
    """The order in the emitted C# is exactly the fix, and that is why it is under test."""

    def test_point_is_written_before_rotation_is_read(self):
        body = GEOMETRY_HELPER_CS
        point_write = body.index('__row["p0_mm"] = __point;')
        rotation_read = body.index("__lp.Rotation")
        self.assertLess(
            point_write, rotation_read,
            "чтение поворота обязано идти ПОСЛЕ записи точки: у помещений и "
            "зон оно бросает, и всё, что стоит за ним, теряется")

    def test_rotation_read_has_its_own_guard(self):
        """Between reading the rotation and writing the point there must stand its own try —
        a single guard over the whole location block is not enough, and that was the cause."""
        body = GEOMETRY_HELPER_CS
        point_write = body.index('__row["p0_mm"] = __point;')
        rotation_read = body.index("__lp.Rotation")
        between = body[point_write:rotation_read]
        self.assertIn(
            "try", between,
            "поворот обязан читаться под СВОИМ стражем, иначе исключение "
            "уносит запись, стоящую рядом")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
