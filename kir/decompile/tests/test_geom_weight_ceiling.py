"""A shape-weight ceiling at capture time — protecting live Revit from hanging.

WHAT IS PROVEN HERE, AND WHY EXACTLY THIS. `Face.Triangulate` cannot be
interrupted, and time budgets are checked BEFORE and AFTER a stage —
meaning one heavy shape drags capture past any budget and takes
Revit's UI thread down with it. Measurement 2026-08-14: a pilaster
with 236 thousand triangles hung Revit 2023 dead for over half an
hour. That is why the ceiling must be CUMULATIVE and checked INSIDE
the traversal of faces, not before it: predicting weight in advance is
not cheap (measured across 351 shapes: heavy ones have 120..262 faces,
light ones up to 418 — a threshold on face count does not separate them).

The tests target three distinct claims, not one:
  1. the ceiling EXISTS in the emitted C# and stands at both gates of
     the traversal;
  2. the failure is TYPED and distinguishable from "could not read"
     and from budgets;
  3. the counter is reset PER ELEMENT, otherwise a second element
     would fail for the sins of the first.
"""
from __future__ import annotations

import unittest

from kir.decompile.geom_extract import (
    GEOMETRY_EXTRACT_SCHEMA_VERSION,
    GeometryFailureReason,
    build_geometry_extract_cs,
    extract_geometry,
)
from kir.decompile.schema import GEOM_WEIGHT_CEILING


def _payload(elements: list[dict]) -> dict:
    return {
        "schema_version": GEOMETRY_EXTRACT_SCHEMA_VERSION,
        "elements": elements,
    }


def _refused(element_id: str, reason: str, elapsed_ms: int = 7) -> dict:
    """A failure row of exactly the shape the production C# emits."""
    return {
        "element_id": element_id,
        "category": "OST_GenericModel",
        "status": "failed",
        "parts": [],
        "errors": [reason],
        "reason": reason,
        "elapsed_ms": elapsed_ms,
    }


class WeightCeilingConstant(unittest.TestCase):
    def test_ceiling_sits_between_storage_limit_and_measured_hang(self) -> None:
        """The number is not "round by eye," but pinned between two measurements.

        From below — the format limit of the authored op (`ir/mesh.py`,
        4096): below it, the ceiling would cut off shapes that could
        still be built. From above — the measured hang at 236 thousand
        triangles: the ceiling must be noticeably lower, so that the
        work done before failure stays bounded.
        """
        from kir.mesh import MAX_TRIANGLES

        self.assertGreaterEqual(GEOM_WEIGHT_CEILING, MAX_TRIANGLES)
        self.assertLess(GEOM_WEIGHT_CEILING, 236_000 // 4)


class WeightCeilingIsEmitted(unittest.TestCase):
    """The ceiling must MAKE IT to Revit, rather than staying a number in Python."""

    def setUp(self) -> None:
        self.cs = build_geometry_extract_cs(["12345"])

    def test_ceiling_value_reaches_the_emitted_csharp(self) -> None:
        self.assertIn(
            "int __gxWeightCeiling = %d;" % GEOM_WEIGHT_CEILING, self.cs)

    def test_no_placeholder_survives_into_live_revit(self) -> None:
        """The guard against an unresolved placeholder also looks into the helpers.

        Before the fix it checked only the body, while the ceiling
        lives in the helpers — an unsubstituted
        `__GX_WEIGHT_CEILING__` would have shipped to the user's
        machine and failed to compile there.
        """
        self.assertNotIn("__GX_", self.cs)

    def test_ceiling_is_checked_inside_the_face_loop_not_only_after(self) -> None:
        """Two gates: one charges for a face, the other prevents charging for the next.

        One check in `__gxAppendMesh` is not enough — it fires only
        AFTER the next face has already been tessellated. The second
        stands before `Triangulate`, and only together do they bound
        the work done before failure.
        """
        self.assertEqual(
            self.cs.count('__gxWeightSentinel + ": triangles="'), 2)
        loop_head = self.cs.index("foreach (Face __face in __solid.Faces)")
        triangulate = self.cs.index("__face.Triangulate(1.0)", loop_head)
        guard = self.cs.index("__gxWeightCeiling", loop_head)
        self.assertLess(
            guard, triangulate,
            "застава обязана стоять ДО тесселяции следующей грани")

    def test_counter_is_reset_per_element(self) -> None:
        """Otherwise the second element would fail for the weight of the first."""
        self.assertIn("__gxWeight[0] = 0;", self.cs)
        self.assertIn("__gxWeight[1] = 0;", self.cs)

    def test_refusal_is_emitted_as_a_typed_row_reason(self) -> None:
        self.assertIn('__row["reason"] = __gxWeightSentinel;', self.cs)
        self.assertIn('__row["status"] = "failed";', self.cs)


class WeightCeilingRefusalIsTyped(unittest.TestCase):
    """The failure must be DISTINGUISHABLE, not blend in with other failures."""

    def test_reason_exists_as_a_typed_enum_member(self) -> None:
        self.assertEqual(
            GeometryFailureReason("weight_ceiling_exceeded"),
            GeometryFailureReason.WEIGHT_CEILING_EXCEEDED)

    def test_payload_parses_into_a_failure_carrying_that_reason(self) -> None:
        result = extract_geometry(_payload([
            _refused("101", "weight_ceiling_exceeded")]))

        self.assertEqual(len(result.failures), 1)
        failure = result.failures[0]
        self.assertEqual(
            failure.reason, GeometryFailureReason.WEIGHT_CEILING_EXCEEDED)
        self.assertEqual(failure.element_id, "101")

    def test_heavy_shape_is_not_reported_as_empty_geometry(self) -> None:
        """A heavy shape is NOT "there is no geometry."

        Tier A means "there is nothing to capture for this element." A
        weight-based failure means "there is something to capture, but
        it costs us live Revit" — if it fell into Tier A, the element
        would silently lose its shape and look empty.
        """
        result = extract_geometry(_payload([
            _refused("101", "weight_ceiling_exceeded")]))

        self.assertEqual(result.index, ())
        self.assertEqual(len(result.failures), 1)

    def test_weight_refusal_is_distinct_from_the_time_budgets(self) -> None:
        """A permanent failure must not look like a temporary one.

        A budget says "time ran out here" — that is an invitation to
        retry. Weight says "this shape is unliftable" — a property of
        the shape, still true on the next run. One code for both would
        invite a pointless retry.
        """
        reasons = {member.value for member in GeometryFailureReason}
        self.assertIn("weight_ceiling_exceeded", reasons)
        self.assertNotEqual(
            GeometryFailureReason.WEIGHT_CEILING_EXCEEDED,
            GeometryFailureReason.TIME_BUDGET_EXCEEDED)
        self.assertNotEqual(
            GeometryFailureReason.WEIGHT_CEILING_EXCEEDED,
            GeometryFailureReason.CALL_BUDGET_EXHAUSTED)

    def test_one_heavy_shape_does_not_condemn_its_neighbours(self) -> None:
        """Neighbors in the batch must still be captured as if nothing happened."""
        result = extract_geometry(_payload([
            _refused("101", "weight_ceiling_exceeded"),
            {
                "element_id": "102",
                "category": "OST_GenericModel",
                "status": "empty",
                "parts": [],
                "errors": [],
            },
        ]))

        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].element_id, "101")
        self.assertEqual(len(result.index), 1)
        self.assertEqual(result.index[0].element_id, "102")


if __name__ == "__main__":
    unittest.main()
