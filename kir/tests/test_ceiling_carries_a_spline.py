"""CEILING IS THE SECOND, AND FOR NOW THE LAST, OP FOR WHICH A SPLINE IS
ALLOWED.

WHY THIS FILE EXISTS AND WHAT IT REFUTES. The task sounded like "propagate
the spline to the whole `Sketch.Profile` family — slab, ceiling, roof,
foundation" and promised to quadruple the capability. The measurement
yielded ONE: the criterion consists of TWO conditions, and they overlap
less often than the canon makes it seem.

    (a) the op carries a parameter of kind `region`  — otherwise there is
        nothing to SAY the curve with
    (b) the op attaches a `sketch_loops_witness` — otherwise there is
        nothing to READ the curve with, because `spline_points_witness`
        reaches the same `Sketch.Profile` through `GetDependentElements`

A census of twelve ops with a region (20.08.2026): condition (b) is
satisfied by exactly `create_floor_by_contour` and `create_ceiling`.
`create_stairs_landing`, `create_beam_system`, `create_filled_region`,
`create_opening`, `create_building_pad`, and `create_site_subregion` have
no sketch witness; the four bodies (`create_solid_*`) have no sketch at
all — they are `DirectShape`.

🔴 THE SLAB, ROOF, AND FOUNDATION FELL OUT FOR A DIFFERENT REASON, AND IT
MATTERS MORE. The canon correctly says that their shape is read from
`Sketch.Profile` — but a spline cannot be added to them, because the
obstacle is NOT IN THE WITNESS BUT IN THE LANGUAGE: their shape arrives as
kind `pts`, a bare list of points that has neither arcs nor splines. This
was verified by execution, not by reading: `create_roof` with a `splines`
field was rejected with `KIR-P003 unknown field 'splines'`. To give the
roof a curved edge, a `_by_contour` twin is needed, the way it was already
made for the slab — separate work, not a line in a list. The test
`test_the_pts_family_CANNOT_be_given_a_spline` holds this fact so that the
next wave does not go looking for the defect in the witness.

WHAT EXACTLY IS PINNED DOWN HERE: the three ceiling branches behave
differently, and the difference matters — the spline loop loses the
bounding-box obligation and gains a curve witness, while the straight
contour and the `outline` branch do not move a byte.
"""
from __future__ import annotations

import unittest

from kir import contour as C
from kir import translation_cert as TC
from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT

_RING = [[0, 0], [12000, 0], [12000, 8000], [0, 8000]]
_VIA = [[9600, 9400], [6600, 6600]]
_LEVEL = {"by": "name", "value": "Этаж 1"}


def _compile(**fields):
    op = {"op": "create_ceiling", "id": "C1", "level": _LEVEL}
    op.update(fields)
    return compile_program({"ir_version": "1.0", "ops": [op]},
                           revit_version="2026", snapshot=GROUND_SNAPSHOT)


def _ok(**fields):
    out = _compile(**fields)
    assert out.ok, [str(d.message_ru)[:200] for d in out.diagnostics]
    return out


_PLAIN = {"outer": {"shape": "poly", "points_mm": _RING}}
_SPLINE = {"outer": {"shape": "poly", "points_mm": _RING,
                     "splines": [{"edge": 2, "via_mm": _VIA}]}}


class TheCeilingAcceptsACurvedEdge(unittest.TestCase):

    def test_the_guard_lets_a_spline_through(self) -> None:
        """The grounding guard (KIR-E009) must let exactly this op
        through."""
        self.assertIn("create_ceiling", C.SPLINE_WITNESSED_OPS)
        self.assertTrue(_compile(contour=_SPLINE).ok)

    def test_the_lowered_csharp_builds_a_HermiteSpline(self) -> None:
        self.assertIn("HermiteSpline.Create", _ok(contour=_SPLINE).csharp)
        self.assertNotIn("HermiteSpline.Create", _ok(contour=_PLAIN).csharp)

    def test_the_curve_gets_its_OWN_witness(self) -> None:
        """Both neighbors are blind to the curve: the shape reads the
        ENDPOINTS of edges, there is no bounding box."""
        cs = _ok(contour=_SPLINE).csharp
        self.assertIn("объявленная точка кривой", cs)
        self.assertNotIn("объявленная точка кривой", _ok(contour=_PLAIN).csharp)

    def test_a_spline_ring_does_NOT_claim_its_bbox(self) -> None:
        self.assertNotIn("bbox extents mismatch", _ok(contour=_SPLINE).csharp)

    def test_a_spline_ring_is_still_PROVEN(self) -> None:
        """A removed obligation without a shutter would give "could not
        prove"."""
        cert = TC.certify_program(list(_ok(contour=_SPLINE).grounded_ops), "2026")
        bbox = next(c for c in cert.ops[0].clauses if "bbox" in (c.clause or ""))
        self.assertFalse(bbox.required)
        self.assertTrue(cert.proven)


class TheOtherBranchesDoNotMove(unittest.TestCase):
    """NARROWNESS CONTROLS. Without them, a fix that removed the bounding
    box from ALL ceilings would pass every check above."""

    def test_a_plain_contour_still_OWES_and_shows_its_bbox(self) -> None:
        cs = _ok(contour=_PLAIN).csharp
        self.assertIn("bbox extents mismatch", cs)
        cert = TC.certify_program(list(_ok(contour=_PLAIN).grounded_ops), "2026")
        bbox = next(c for c in cert.ops[0].clauses if "bbox" in (c.clause or ""))
        self.assertTrue(bbox.required)
        self.assertTrue(cert.proven)

    def test_the_outline_branch_is_untouched(self) -> None:
        """On the `outline` branch the region is not built at all, so the
        shutter does not apply to it — and this is a DIFFERENT path, not
        the same one with different input."""
        cs = _ok(outline=_RING).csharp
        self.assertIn("bbox extents mismatch", cs)
        self.assertNotIn("объявленная точка кривой", cs)

    def test_the_pts_family_CANNOT_be_given_a_spline(self) -> None:
        """🔴 THE MAIN REFUTATION OF THE TASK, pinned down by execution.

        The roof, the slab, and the foundation read `Sketch.Profile` — and
        will still not accept a curve: their shape is of kind `pts`. The
        obstacle is in the LANGUAGE, and the next wave must not look for it
        in the witness.
        """
        out = compile_program({"ir_version": "1.0", "ops": [{
            "op": "create_roof", "id": "R1", "outline": _RING,
            "splines": [{"edge": 0, "via_mm": [[6000, -1500]]}],
            "level": _LEVEL}]}, revit_version="2026", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-P003", [d.code for d in out.diagnostics])


class TheToleranceIsRegisteredNotInvented(unittest.TestCase):

    def test_spline_point_mm_is_the_SAME_number_as_the_floors(self) -> None:
        """A different NUMBER would mean the ceiling is printed with a
        different coordinate quantum, which is not the case: they share
        the same witness."""
        from kir.emit_model import tolerances
        self.assertEqual(tolerances("create_ceiling")["spline_point_mm"].value,
                         tolerances("create_floor_by_contour")["spline_point_mm"].value)

    def test_the_tolerance_OBJECTS_are_deliberately_NOT_equal(self) -> None:
        """And this is not a triviality but the law of tolerances:
        `Tolerance` carries the OP'S NAME.

        A number cannot be borrowed from a neighbor even when it matches —
        the key is presented together with the number minted by the
        registry FOR THIS op. The first edit of the test compared objects
        and turned red on a correct fix; the check is kept so that the next
        reader does not "fix" the law, mistaking it for a defect.
        """
        from kir.emit_model import tolerances
        self.assertNotEqual(tolerances("create_ceiling")["spline_point_mm"],
                            tolerances("create_floor_by_contour")["spline_point_mm"])


if __name__ == "__main__":
    unittest.main()
