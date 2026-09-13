"""VIEW-SPACE type core (Documentation invention). The load-bearing law:
PtView2D and PtModel3D are distinct types that never substitute — a 3D point
in a view-space field is a TYPED refusal with an explicit space-confusion
message, never silently accepted."""
import unittest

from kir import docspace


class ViewSpaceTypeLaw(unittest.TestCase):
    def test_view2d_accepts_uv(self):
        diags = []
        self.assertEqual(docspace.check_pt_view2d([100, 250], "T1", "at", diags),
                         [100.0, 250.0])
        self.assertEqual(diags, [])

    def test_3d_point_in_view_field_refused(self):
        """The invention's core: a [x,y,z] where [u,v] belongs is refused with
        a space-confusion message, not truncated or accepted."""
        diags = []
        out = docspace.check_pt_view2d([1000, 2000, 3000], "T1", "at", diags)
        self.assertIsNone(out)
        self.assertEqual(diags[0].code, "KIR-T001")
        self.assertIn("3D-точка", diags[0].message_ru)
        self.assertIn("вида", diags[0].message_ru)

    def test_annotation_far_from_the_view_origin_is_accepted(self):
        """Measured 27.07 on a real project: the plan's `View.Origin` = (0,0,0),
        the axes are the world axes, and the building's walls lie along Y at
        82 693 … 110 160 mm. The previous ±10 m boundary let NOT ONE element
        of this building be annotated.

        Telling apart "a model coordinate that leaked into the view field"
        and "a legitimate annotation far from the view origin" by MAGNITUDE
        is impossible — for a plan these are literally the same numbers. Only
        the point's dimensionality separates them, and that is checked
        separately (see the test below)."""
        diags = []
        out = docspace.check_pt_view2d([50000, 0], "T1", "at", diags)
        self.assertEqual(out, [50000.0, 0.0])
        self.assertEqual(diags, [])

        diags = []
        self.assertEqual(
            docspace.check_pt_view2d([200000, 105000], "T1", "at", diags),
            [200000.0, 105000.0])
        self.assertEqual(diags, [])

    def test_coordinate_sanity_bound_still_refuses_garbage(self):
        """The sanity bound remains — the same one used for model points (Revit's
        working limit ~16 km): a stray/garbage coordinate is still caught."""
        diags = []
        out = docspace.check_pt_view2d([99_000_000, 0], "T1", "at", diags)
        self.assertIsNone(out)
        self.assertEqual(diags[0].code, "KIR-T002")

    def test_malformed_point(self):
        for bad in (None, "at", [1], [1, "x"], [True, 2], []):
            diags = []
            self.assertIsNone(docspace.check_pt_view2d(bad, "T1", "at", diags))
            self.assertTrue(diags)

    def test_reject_model3d_guard(self):
        diags = []
        self.assertTrue(docspace.reject_model3d_in_annotation([0, 0, 0], "T1", "p", diags))
        self.assertEqual(diags[0].code, "KIR-T001")
        diags2 = []
        self.assertFalse(docspace.reject_model3d_in_annotation([0, 0], "T1", "p", diags2))
        self.assertEqual(diags2, [])

    def test_type_predicates_disjoint(self):
        self.assertTrue(docspace.is_pt_view2d([1, 2]))
        self.assertFalse(docspace.is_pt_view2d([1, 2, 3]))
        self.assertTrue(docspace.is_pt_model3d([1, 2, 3]))
        self.assertFalse(docspace.is_pt_model3d([1, 2]))


class ViewSpaceMaterialization(unittest.TestCase):
    def test_emit_uses_view_basis_not_hardcoded_z(self):
        cs = docspace.emit_view2d_to_xyz_cs("__vw", 100, 250)
        self.assertIn("__vw.Origin", cs)
        self.assertIn("RightDirection.Multiply(U(100", cs)
        self.assertIn("UpDirection.Multiply(U(250", cs)
        # the whole point: no literal Z, the basis carries the placement
        self.assertNotIn(", 0)", cs)

    def test_scale_from_intent(self):
        self.assertEqual(docspace.view_scale_to_model_mm(2.5, 50), 125.0)
        self.assertEqual(docspace.view_scale_to_model_mm(2.5, 100), 250.0)
        with self.assertRaises(ValueError):
            docspace.view_scale_to_model_mm(2.5, 0)


if __name__ == "__main__":
    unittest.main()
