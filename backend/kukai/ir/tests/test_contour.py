"""CONTOUR sublanguage gates: shapes-by-construction, arc math at compile
time, anchor grounding, static laws lifted to arcs, floor version divergence."""
import os
import tempfile
import unittest
import math

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_test_queue.jsonl"))

from kukai.ir.compiler import compile_program  # noqa: E402
from kukai.ir import contour as contour_mod  # noqa: E402
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT  # noqa: E402

LVL = {"by": "name", "value": "Этаж 1"}
LVL_ID = {"by": "element_id", "value": 42}


def _prog(contour, level=LVL, oid="F1"):
    return {"ir_version": "1.0", "intent": "contour-test", "ops": [
        {"op": "create_floor_by_contour", "id": oid,
         "contour": contour, "level": level}]}


class ShapesByConstruction(unittest.TestCase):
    def test_rect_lowers_to_four_lines(self):
        out = compile_program(_prog({"outer": {"shape": "rect", "origin": [0, 0],
                                               "size_mm": [8000, 6000]}}),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertEqual(out.csharp.count("__ol_F1.Append(Line.CreateBound"), 4)

    def test_rect_rotation(self):
        out = compile_program(_prog({"outer": {"shape": "rect", "origin": [1000, 1000],
                                               "size_mm": [8000, 6000],
                                               "rotation_deg": 30}}),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)

    def test_l_shape_all_corners(self):
        for corner in ("ne", "nw", "se", "sw"):
            out = compile_program(_prog({"outer": {
                "shape": "l", "origin": [0, 0], "size_mm": [16000, 10000],
                "cut_mm": [6000, 4000], "corner": corner}}),
                snapshot=GROUND_SNAPSHOT)
            self.assertTrue(out.ok, corner)
            self.assertEqual(out.csharp.count("__ol_F1.Append(Line.CreateBound"),
                             6, corner)

    def test_l_cut_bounds_by_construction(self):
        out = compile_program(_prog({"outer": {
            "shape": "l", "origin": [0, 0], "size_mm": [16000, 10000],
            "cut_mm": [16000, 4000]}}), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T002", [d.code for d in out.diagnostics])


class ArcLaws(unittest.TestCase):
    SQ = [[0, 0], [8000, 0], [8000, 6000], [0, 6000]]

    def test_poly_with_bulge_emits_arc(self):
        out = compile_program(_prog({"outer": {"shape": "poly",
                                               "points_mm": self.SQ,
                                               "arcs": [{"edge": 1, "bulge": 0.4}]}}),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        cs = out.csharp
        self.assertEqual(cs.count("Arc.Create"), 1)
        self.assertEqual(cs.count("__ol_F1.Append(Line.CreateBound"), 3)

    def test_radius_form_converts(self):
        out = compile_program(_prog({"outer": {"shape": "poly",
                                               "points_mm": self.SQ,
                                               "arcs": [{"edge": 0,
                                                         "radius_mm": 6000}]}}),
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok)
        self.assertIn("Arc.Create", out.csharp)

    def test_radius_smaller_than_half_chord_refused(self):
        out = compile_program(_prog({"outer": {"shape": "poly",
                                               "points_mm": self.SQ,
                                               "arcs": [{"edge": 0,
                                                         "radius_mm": 3000}]}}),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-T002"][0]
        self.assertIn("радиус меньше половины хорды", d.message_ru)

    def test_bulge_bounds(self):
        out = compile_program(_prog({"outer": {"shape": "poly",
                                               "points_mm": self.SQ,
                                               "arcs": [{"edge": 0, "bulge": 2.0}]}}),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)

    def test_arc_self_intersection_caught_by_sampling(self):
        """Flat 8000x1000 rect + clockwise bulge on the top edge: the arc dips
        2000mm down, crossing the bottom edge — visible only through arc
        sampling, invisible to a vertices-only check."""
        flat = [[0, 0], [8000, 0], [8000, 1000], [0, 1000]]
        out = compile_program(_prog({"outer": {"shape": "poly",
                                               "points_mm": flat,
                                               "arcs": [{"edge": 2, "bulge": -0.5}]}}),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T003", [d.code for d in out.diagnostics])

    def test_positive_bulge_ccw_sampling_matches_emitted_midpoint(self):
        p0, p1 = [0.0, 0.0], [10.0, 0.0]
        bulge = math.sqrt(2.0) - 1.0       # +90 degree CCW sweep
        emitted_mid = contour_mod.bulge_midpoint(p0, p1, bulge)
        sampled = contour_mod._sample_arc(p0, p1, bulge)
        self.assertLess(emitted_mid[1], 0.0)  # right of eastbound chord = CCW
        self.assertAlmostEqual(sampled[4][0], emitted_mid[0], places=9)
        self.assertAlmostEqual(sampled[4][1], emitted_mid[1], places=9)
        self.assertLess(math.dist(sampled[-2], sampled[-1]), 2.0)

    def test_arc_bbox_includes_exact_cardinal_extrema(self):
        p0, p1 = [0.0, 0.0], [10000.0, 3000.0]
        bulge = 0.7
        (cx, cy), radius, start, sweep = contour_mod._arc_geometry(p0, p1, bulge)
        bounds = contour_mod.edges_bbox([(p0, p1, bulge)])
        candidates = [p0, p1]
        for angle in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
            travelled = ((angle - start) % (2 * math.pi) if sweep > 0
                         else (start - angle) % (2 * math.pi))
            if travelled <= abs(sweep) + 1e-12:
                candidates.append([cx + radius * math.cos(angle),
                                   cy + radius * math.sin(angle)])
        self.assertEqual(bounds, (min(p[0] for p in candidates),
                                  min(p[1] for p in candidates),
                                  max(p[0] for p in candidates),
                                  max(p[1] for p in candidates)))

    def test_arc_descriptor_is_closed_and_unambiguous(self):
        bad_arcs = (
            [{"edge": True, "bulge": 0.2}],
            [{"edge": 0, "bulge": 0.2}, {"edge": 0, "bulge": 0.3}],
            [{"edge": 0, "bulge": 0.2, "radius_mm": 6000}],
            [{"edge": 0, "bulge": 0.2, "dir": "cw"}],
            [{"edge": 0, "radius_mm": float("nan")}],
            [{"edge": 0, "radius_mm": 6000, "dir": "sideways"}],
        )
        for arcs in bad_arcs:
            with self.subTest(arcs=arcs):
                out = compile_program(_prog({"outer": {"shape": "poly",
                                                        "points_mm": self.SQ,
                                                        "arcs": arcs}}),
                                      snapshot=GROUND_SNAPSHOT)
                self.assertFalse(out.ok)
                self.assertNotIn("KIR-P000", [d.code for d in out.diagnostics])

    def test_three_dimensional_anchor_is_not_silently_truncated(self):
        out = compile_program(_prog({"outer": {"shape": "rect",
                                               "origin": [0, 0, 5000],
                                               "size_mm": [8000, 6000]}}),
                              snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T001", [d.code for d in out.diagnostics])


class GridAnchors(unittest.TestCase):
    def test_at_grid_resolves_intersection(self):
        out = compile_program(_prog({"outer": {
            "shape": "rect",
            "origin": {"at_grid": ["1", "А"], "offset_mm": [200, 200]},
            "size_mm": [3800, 4300]}}), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        # grid 1 x grid А = (0,0); +offset 200 -> first corner at (200, 200)
        self.assertIn("P(200.0, 200.0, 0)", out.csharp)

    def test_unknown_grid_refused_with_candidates(self):
        out = compile_program(_prog({"outer": {
            "shape": "rect", "origin": {"at_grid": ["9", "А"]},
            "size_mm": [3000, 3000]}}), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        d = [x for x in out.diagnostics if x.code == "KIR-G105"][0]
        self.assertIn("1", d.candidates)

    def test_parallel_grids_refused(self):
        out = compile_program(_prog({"outer": {
            "shape": "rect", "origin": {"at_grid": ["1", "2"]},
            "size_mm": [3000, 3000]}}), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        codes = [d.code for d in out.diagnostics]
        self.assertIn("KIR-G105", codes)

    def test_literal_only_region_grounds_without_grids(self):
        """No at_grid + level by element_id -> no snapshot needed at all."""
        out = compile_program(_prog({"outer": {"shape": "rect", "origin": [0, 0],
                                               "size_mm": [5000, 5000]}},
                                    level=LVL_ID), snapshot=None)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])


class RegionComposition(unittest.TestCase):
    L_REGION = {"outer": {"shape": "l", "origin": [0, 0],
                          "size_mm": [16000, 10000], "cut_mm": [6000, 4000]},
                "holes": [{"shape": "rect", "origin": [1000, 1000],
                           "size_mm": [3000, 6000]}]}

    def test_l_with_rect_hole(self):
        out = compile_program(_prog(self.L_REGION), snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics][:2])
        self.assertIn("__hl_F1_0", out.csharp)

    def test_hole_touching_outer_refused(self):
        bad = {"outer": {"shape": "rect", "origin": [0, 0], "size_mm": [8000, 6000]},
               "holes": [{"shape": "rect", "origin": [0, 2000],
                          "size_mm": [3000, 3000]}]}   # shares x=0 edge
        out = compile_program(_prog(bad), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T003", [d.code for d in out.diagnostics])

    def test_crossing_holes_without_contained_vertices_are_refused(self):
        bad = {"outer": {"shape": "rect", "origin": [0, 0],
                         "size_mm": [10000, 10000]},
               "holes": [
                   {"shape": "rect", "origin": [1000, 4000],
                    "size_mm": [8000, 2000]},
                   {"shape": "rect", "origin": [4000, 1000],
                    "size_mm": [2000, 8000]},
               ]}
        out = compile_program(_prog(bad), snapshot=GROUND_SNAPSHOT)
        self.assertFalse(out.ok)
        self.assertIn("KIR-T003", [d.code for d in out.diagnostics])

    def test_2021_divergence(self):
        ok21 = compile_program(_prog({"outer": {"shape": "poly",
                                                "points_mm": ArcLaws.SQ,
                                                "arcs": [{"edge": 1, "bulge": 0.3}]}}),
                               revit_version="2021", snapshot=GROUND_SNAPSHOT)
        self.assertTrue(ok21.ok, [d.as_dict() for d in ok21.diagnostics][:2])
        self.assertIn("doc.Create.NewFloor(__ca_F1", ok21.csharp)
        self.assertIn("Arc.Create", ok21.csharp)   # arcs fine in CurveArray
        holes21 = compile_program(_prog(self.L_REGION), revit_version="2021",
                                  snapshot=GROUND_SNAPSHOT)
        self.assertFalse(holes21.ok)
        self.assertIn("KIR-E003", [d.code for d in holes21.diagnostics])


if __name__ == "__main__":
    unittest.main()
