"""Clash geometry branches: a body declared by the program must yield a
hull.

WHY, BY THE MEASUREMENT OF 19.08.2026. Of the registry's 28 operations, a
body is DECLARED for (`body_making_ops`), while a geometry branch in
`clash_bundle` existed for 16. Twelve went into the "silence lock" — it
named them (`{op}_geometry_not_expressed`), but they got no hull, and for
clash search the body did not exist.

The cost was measured on a live building the same day: a staircase and its
railings pierced a beam by 259.2 / 875.4 / 1075.0 mm, and a session
bundle would not have seen this AT ALL — neither op had a branch. It was
found only because the measurement was taken from the decompile, where
the bounding box is real.

🔴 WHAT IS PINNED DOWN HERE MOST OF ALL IS NOT COVERAGE BUT THE BAN ON
INVENTING. A hull assembled from defaults is WORSE than a missing one: it
produces findings that do not exist and hides the ones that do. So every
branch either derives the bounding box from what is declared, or returns
a NAMED reason, and the mutation tests below require that a cut branch
return the element to the silence lock, rather than slip it a default
bounding box.
"""
import math
import unittest

from kir import clash_bundle as cb


class _Ctx:
    """A stub snapshot: returns exactly what is declared in the test, and
    nothing beyond it."""

    def __init__(self, levels=None, sections=None):
        self._levels = levels or {}
        self._sections = sections or {}

    def level_mm(self, sel):
        if isinstance(sel, dict):
            sel = sel.get("value")
        return self._levels.get(sel)

    def section(self, pool, sel):
        if isinstance(sel, dict):
            sel = sel.get("value")
        return self._sections.get((pool, sel))


class SolidsNeedNoSnapshot(unittest.TestCase):
    """For both solids `grounded` is EMPTY — they need no snapshot by
    construction."""

    def test_extrusion_bbox_is_the_declared_contour_and_height(self):
        el = {}
        why = cb._solid_geometry(
            {"op": "create_solid_extrusion", "id": "SE",
             "profile": {"outer": {"shape": "rect", "origin": [1000, 2000],
                                   "size_mm": [4000, 3000]}},
             "height_mm": 2000, "base_z_mm": 500}, el, None)
        self.assertEqual(why, "")
        self.assertEqual(el["bbox_min_mm"], [1000.0, 2000.0, 500.0])
        self.assertEqual(el["bbox_max_mm"], [5000.0, 5000.0, 2500.0])

    def test_arc_bulges_outside_the_chord_and_the_bbox_contains_it(self):
        """The arc extends past the chord, and the bounding box must
        contain it.

        Measurement: a `poly` with bulge 0.4 on a 6000 mm edge gives 6800
        — 800 mm of the body OUTSIDE the chord. A bounding box on the
        chord would hide it.
        """
        el = {}
        why = cb._solid_geometry(
            {"op": "create_solid_extrusion", "id": "SE",
             "profile": {"outer": {"shape": "poly",
                                   "points_mm": [[0, 0], [6000, 0],
                                                 [6000, 4000], [0, 4000]],
                                   "arcs": [{"edge": 1, "bulge": 0.4}]}},
             "height_mm": 1000}, el, None)
        self.assertEqual(why, "")
        self.assertGreater(el["bbox_max_mm"][0], 6000.0)

    def test_revolve_uses_the_same_sector_bbox_as_the_emitter(self):
        el = {}
        why = cb._solid_geometry(
            {"op": "create_solid_revolve", "id": "SR",
             "profile": {"outer": {"shape": "rect", "origin": [1000, 0],
                                   "size_mm": [800, 2400]}},
             "axis_xy_mm": [10000, 0], "sweep_deg": 270}, el, None)
        self.assertEqual(why, "")
        from kir.solid_emit import _sector_bbox
        sx0, sy0, sx1, sy1 = _sector_bbox(1000.0, 1800.0, 270.0)
        self.assertAlmostEqual(el["bbox_min_mm"][0], 10000.0 + sx0, places=6)
        self.assertAlmostEqual(el["bbox_max_mm"][1], 0.0 + sy1, places=6)

    def test_a_region_addressed_by_grids_refuses_by_name(self):
        """The bundle has no axis pool — and this is a REFUSAL, not a
        made-up point."""
        el = {}
        why = cb._solid_geometry(
            {"op": "create_solid_extrusion", "id": "SE",
             "profile": {"outer": {"shape": "rect",
                                   "origin": {"at_grid": ["A", "1"]},
                                   "size_mm": [1000, 1000]}},
             "height_mm": 1000}, el, None)
        self.assertEqual(why, "region_addresses_grids")
        self.assertNotIn("bbox_min_mm", el)


class StairsAndRailing(unittest.TestCase):

    def test_stairs_bbox_is_path_width_and_levels(self):
        el = {}
        ctx = _Ctx(levels={"Э1": 0.0, "Э2": 3900.0})
        why = cb._stairs_geometry(
            {"op": "create_stairs", "id": "S", "p0_mm": [0, 0],
             "p1_mm": [6160, 0], "width_mm": 1400,
             "base_level": {"value": "Э1"}, "top_level": {"value": "Э2"}},
            el, ctx)
        self.assertEqual(why, "")
        self.assertEqual(el["bbox_min_mm"], [-700.0, -700.0, 0.0])
        self.assertEqual(el["bbox_max_mm"][0], 6860.0)
        # the top CONTAINS the tread material: underestimating it hides a
        # clash with the slab
        self.assertGreater(el["bbox_max_mm"][2], 3900.0)

    def test_spiral_refuses_because_its_extent_is_not_declared(self):
        el = {}
        why = cb._stairs_geometry(
            {"op": "create_stairs", "id": "S", "spiral": {"turns": 1},
             "base_level": {"value": "Э1"}, "top_level": {"value": "Э2"}},
            el, _Ctx(levels={"Э1": 0.0, "Э2": 3900.0}))
        self.assertEqual(why, "stairs_spiral_extent_not_expressed")

    def test_railing_height_comes_from_the_type_or_it_refuses(self):
        """The height is NOT invented: without a type cross-section — a
        named refusal.

        Measurement of 19.08: the railing-versus-beam clash depths came
        out to 875.4 and 1075.0 mm — exactly the heights of the «900 мм»
        and «1100 мм» types. Substituting 1000 "by default" here would
        have shifted both findings.
        """
        op = {"op": "create_railing", "id": "R", "variety": "path",
              "path": [[0, 0], [5000, 0]], "level": {"value": "Э1"},
              "type": {"value": "1100 мм"}}
        el = {}
        why = cb._railing_geometry(op, el, _Ctx(levels={"Э1": 0.0}))
        self.assertEqual(why, "railing_type_not_in_snapshot")
        el = {}
        ctx = _Ctx(levels={"Э1": 0.0},
                   sections={("railing_types", "1100 мм"):
                             {"height_mm": 1100.0, "thickness_mm": 60.0}})
        why = cb._railing_geometry(op, el, ctx)
        self.assertEqual(why, "")
        self.assertEqual(el["bbox_max_mm"][2], 1100.0)


class FlexAndContourAndRoof(unittest.TestCase):

    def test_flex_radius_comes_from_the_type_or_it_refuses(self):
        op = {"op": "create_flex_duct", "id": "F",
              "path": [[0, 0, 3000], [4000, 0, 3000]],
              "level": {"value": "Э1"},
              "flex_duct_type": {"value": "гибкий"}}
        el = {}
        why = cb._flex_geometry(op, el, _Ctx(levels={"Э1": 0.0}))
        self.assertEqual(why, "create_flex_duct_type_not_in_snapshot")
        el = {}
        ctx = _Ctx(levels={"Э1": 0.0},
                   sections={("flex_duct_types", "гибкий"):
                             {"diameter_mm": 300.0}})
        self.assertEqual(cb._flex_geometry(op, el, ctx), "")
        self.assertEqual(el["bbox_min_mm"][2], 3000.0 - 150.0)

    def test_contour_slab_doubles_z_like_its_numeric_twin(self):
        """[z−t, z+t] — the UNION of interpretations, the same as in
        `_slab_geometry`."""
        el = {}
        ctx = _Ctx(levels={"Э1": 5400.0},
                   sections={("floor_types", "Типовой 150мм"):
                             {"kind": "plate", "thickness_mm": 150.0}})
        why = cb._contour_slab_geometry(
            {"op": "create_floor_by_contour", "id": "SL",
             "contour": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [6000, 4000]}},
             "level": {"value": "Э1"},
             "type": {"value": "Типовой 150мм"}}, el, ctx)
        self.assertEqual(why, "")
        self.assertEqual(el["bbox_min_mm"][2], 5400.0 - 150.0)
        self.assertEqual(el["bbox_max_mm"][2], 5400.0 + 150.0)

    def test_extrusion_roof_spans_both_ends_of_the_run(self):
        """The runtime decides the sign of the normal — the bounding box
        takes BOTH ends of the run."""
        el = {}
        why = cb._extrusion_roof_geometry(
            {"op": "create_extrusion_roof", "id": "R",
             "p0_mm": [0, 0], "p1_mm": [10000, 0],
             "profile_mm": [[0, 3000], [5000, 4500], [10000, 3000]],
             "start_mm": -2000, "end_mm": 6000}, el, None)
        self.assertEqual(why, "")
        self.assertEqual(el["bbox_min_mm"][2], 3000.0)
        self.assertEqual(el["bbox_max_mm"][2], 4500.0)
        self.assertAlmostEqual(el["bbox_max_mm"][1] - el["bbox_min_mm"][1],
                               8000.0, places=6)


class EveryBodyMakingOpIsAnsweredFor(unittest.TestCase):
    """Closedness: every op with a declared body has EITHER a branch OR a
    reason."""

    def test_no_body_making_op_is_silently_unanswered(self):
        body = set(cb.body_making_ops())
        branched = (set(cb._GRAPH_OPS) | set(cb._AXIS_OPS)
                    | set(cb._SECTION_BBOX_OPS) | set(cb._SLAB_OPS)
                    | set(cb._SOLID_OPS) | set(cb._FLEX_OPS)
                    | {"create_wall", "create_directshape", "create_stairs",
                       "create_railing", "create_floor_by_contour",
                       "create_foundation", "create_extrusion_roof"})
        unanswered = sorted(body - branched - set(cb._BLIND_OPS))
        self.assertEqual(unanswered, [],
                         f"оп с телом, без ветки и без объявленной слепоты: "
                         f"{unanswered}")

    def test_the_loud_warning_covers_every_op_without_a_branch(self):
        """The row "MAY BE HIDING A CLASH" is computed from `_BLIND_OPS`.

        Before 19.08, not one of the twelve ops with a body and no branch
        was listed in it: the silence lock named them in the census,
        while the loudest warning stayed silent.
        """
        body = set(cb.body_making_ops())
        branched = (set(cb._GRAPH_OPS) | set(cb._AXIS_OPS)
                    | set(cb._SECTION_BBOX_OPS) | set(cb._SLAB_OPS)
                    | set(cb._SOLID_OPS) | set(cb._FLEX_OPS)
                    | {"create_wall", "create_directshape", "create_stairs",
                       "create_railing", "create_floor_by_contour",
                       "create_foundation", "create_extrusion_roof"})
        for name in sorted(body - branched):
            self.assertIn(name, cb._BLIND_OPS, name)


class CuttingABranchReturnsTheOpToSilence(unittest.TestCase):
    """MUTATION. A cut branch must return the element to the silence
    lock.

    A form from `test_witness_vacuity`: a check that cannot be made to
    fail is not a check. Here it is more dangerous: a branch that slips
    in a default bounding box instead of a refusal looks like coverage
    and silently distorts EVERY finding.
    """

    def _cut(self, fn_name):
        original = getattr(cb, fn_name)

        def dead(op, el, ctx):
            return f"{op.get('op')}_geometry_not_expressed"

        setattr(cb, fn_name, dead)
        return original

    def test_solid_branch_cut_gives_a_named_reason_not_a_bbox(self):
        original = self._cut("_solid_geometry")
        try:
            el = {}
            why = cb._solid_geometry(
                {"op": "create_solid_extrusion", "id": "SE"}, el, None)
            self.assertEqual(why, "create_solid_extrusion_geometry_not_expressed")
            self.assertNotIn("bbox_min_mm", el)
        finally:
            cb._solid_geometry = original
        el = {}
        why = cb._solid_geometry(
            {"op": "create_solid_extrusion", "id": "SE",
             "profile": {"outer": {"shape": "rect", "origin": [0, 0],
                                   "size_mm": [100, 100]}},
             "height_mm": 100}, el, None)
        self.assertEqual(why, "")
        self.assertIn("bbox_min_mm", el)

    def test_a_branch_never_invents_a_bbox_when_it_refuses(self):
        """Every refusal must leave the element WITHOUT a bounding box."""
        cases = [
            (cb._solid_geometry, {"op": "create_solid_extrusion", "id": "a"}),
            (cb._stairs_geometry, {"op": "create_stairs", "id": "b"}),
            (cb._railing_geometry, {"op": "create_railing", "id": "c"}),
            (cb._flex_geometry, {"op": "create_flex_duct", "id": "d"}),
            (cb._contour_slab_geometry,
             {"op": "create_floor_by_contour", "id": "e"}),
            (cb._extrusion_roof_geometry,
             {"op": "create_extrusion_roof", "id": "f"}),
        ]
        for fn, op in cases:
            with self.subTest(op=op["op"]):
                el = {}
                why = fn(op, el, None)
                self.assertNotEqual(why, "", "отказ обязан быть именным")
                self.assertNotIn("bbox_min_mm", el)
                self.assertNotIn("bbox_max_mm", el)


if __name__ == "__main__":
    unittest.main()
