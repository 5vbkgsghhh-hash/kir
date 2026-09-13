"""TRANSLATION LOSS MUST BE A NUMBER WITH AN ADDRESS, NOT A WORD.

🔴 WHY THIS WAS SET UP (07.09.2026).

Today the entire inventory of untranslated remainder in the tree is TWO
LINES: `concept_twist_removed` and `concept_top_taper_removed`
(`examples/residential_refinement.py:52`). The measurement showed what they
cost: the twist — 8.97 % of the concept's volume, the top taper — 20.37 %.
The word "loss" does not distinguish 0.1 % from 20 %, and the reader cannot
tell them apart either.

WHAT THIS IS JUDGED BY HERE, AND WHY BY EXACTLY THIS.

* VOLUME — by number against a CLOSED-FORM FORMULA (circle against a
  regular N-gon): for an octagon circumscribed around an atrium of
  r = 2500, the remainder must be `(S_8gon − S_circle) × 3000` =
  3 227 172 101.2 mm³ across EIGHT bodies, coverage 0.999141731. OCCT does
  not know the formula.
* MAXIMUM DEVIATION — not a number but a LOWER BOUND, and that is a
  measurement: `DistShapeShape` and `ShapeProximity` give 0.0 where the
  oracle gives 190.3012 mm, while the grid converges from below and
  NON-MONOTONICALLY (steps of 200/50/20 mm → 145.81/184.78/187.95; on
  another zone a step of 200 gave the exact 21.3878, while a step of 50
  gave 17.72). That is why the pin here is one-sided, not "equal to".
* THICKNESS AND HEIGHT — from ops and types. The section carries 23
  outputs, and bodies are derived from 15 of them; the remaining 8
  (3 levels, 3 rooms, 2 types) must be NAMED `derived_has_no_body`,
  otherwise coverage is computed against an arbitrary denominator.
"""
from __future__ import annotations

import json
import math
import unittest

try:
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakePolygon
    from OCP.BRepOffsetAPI import BRepOffsetAPI_ThruSections
    from OCP.BRepPrimAPI import (BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder,
                                 BRepPrimAPI_MakePrism)
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopTools import TopTools_ListOfShape
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Vec
    OCP_READY = True
except ImportError:                                            # pragma: no cover
    OCP_READY = False

from kir import diag
from kir.refine import deviation as D


PODIUM = ((-2000.0, -5000.0, -3000.0), (65000.0, 14000.0, 0.0))
ATRIUM = {"cx": 19000.0, "cy": 4500.0, "r": 2500.0}
HEIGHT = 3000.0
#: Acceptance reference: the remainder of the octagon circumscribed around the atrium.
NGON8_RESIDUE_MM3 = 3_227_172_101.2
NGON8_COVERAGE = 0.999141731
NGON8_ZONES = 8
#: Acceptance reference: the shares of the tower's two loss lines.
TWIST_SHARE = 0.089698
TAPER_SHARE = 0.203659


def _volume(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return float(props.Mass())


def _box(corners):
    (x0, y0, z0), (x1, y1, z1) = corners
    return BRepPrimAPI_MakeBox(gp_Pnt(x0, y0, z0), gp_Pnt(x1, y1, z1)).Shape()


def _cut(argument, tool):
    operation = BRepAlgoAPI_Cut()
    left, right = TopTools_ListOfShape(), TopTools_ListOfShape()
    left.Append(argument)
    right.Append(tool)
    operation.SetArguments(left)
    operation.SetTools(right)
    operation.SetNonDestructive(True)
    operation.Build()
    assert operation.IsDone()
    return operation.Shape()


def _podium():
    """A box minus the atrium's CYLINDER: the same shape as the acceptance scene."""
    cylinder = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(ATRIUM["cx"], ATRIUM["cy"], -HEIGHT - 1000.0), gp_Dir(0, 0, 1)),
        ATRIUM["r"], HEIGHT + 2000.0).Shape()
    return _cut(_box(PODIUM), cylinder)


def _ngon_prism(sides, radius, z0, z1):
    polygon = BRepBuilderAPI_MakePolygon()
    for index in range(sides):
        angle = 2 * math.pi * index / sides
        polygon.Add(gp_Pnt(ATRIUM["cx"] + radius * math.cos(angle),
                           ATRIUM["cy"] + radius * math.sin(angle), z0))
    polygon.Close()
    face = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, z1 - z0)).Shape()


def _translated(sides, mode):
    """"Translation" of the podium: the round atrium is replaced by an N-gon."""
    radius = ATRIUM["r"] if mode == "inscribed" else ATRIUM["r"] / math.cos(math.pi / sides)
    hole = _ngon_prism(sides, radius, PODIUM[0][2] - 1000.0, PODIUM[1][2] + 1000.0)
    return _cut(_box(PODIUM), hole)


TOWER = {"width": 14000.0, "depth": 9000.0, "height": 10800.0, "scale": 0.82}


def _blend(twist_deg):
    angle = math.radians(twist_deg)
    ring = [(0.0, 0.0), (TOWER["width"], 0.0),
            (TOWER["width"], TOWER["depth"]), (0.0, TOWER["depth"])]
    cx, cy = TOWER["width"] / 2, TOWER["depth"] / 2
    top = [(cx + TOWER["scale"] * ((x - cx) * math.cos(angle) - (y - cy) * math.sin(angle)),
            cy + TOWER["scale"] * ((x - cx) * math.sin(angle) + (y - cy) * math.cos(angle)))
           for x, y in ring]

    def wire(points, z):
        polygon = BRepBuilderAPI_MakePolygon()
        for x, y in points:
            polygon.Add(gp_Pnt(x, y, z))
        polygon.Close()
        return polygon.Wire()

    loft = BRepOffsetAPI_ThruSections(True, True, 1e-6)
    loft.AddWire(wire(ring, 0.0))
    loft.AddWire(wire(top, TOWER["height"]))
    loft.Build()
    assert loft.IsDone()
    return loft.Shape()


def _tower_prism():
    ring = [(0.0, 0.0), (TOWER["width"], 0.0),
            (TOWER["width"], TOWER["depth"]), (0.0, TOWER["depth"])]
    polygon = BRepBuilderAPI_MakePolygon()
    for x, y in ring:
        polygon.Add(gp_Pnt(x, y, 0.0))
    polygon.Close()
    face = BRepBuilderAPI_MakeFace(polygon.Wire()).Face()
    return BRepPrimAPI_MakePrism(face, gp_Vec(0, 0, TOWER["height"])).Shape()


@unittest.skipUnless(OCP_READY, "нужен профиль requirements-geometry-occt.txt")
class TheVolumeAgreesWithAClosedFormula(unittest.TestCase):
    """The instrument is verified against a formula that OCCT does not know."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _podium()
        cls.report = D.measure_refinement(
            cls.source, {"ngon8": _translated(8, "circumscribed")},
            source_address="podium", max_deviation_step_mm=200.0,
            max_deviation_points=4000)

    def test_the_residue_volume_matches_the_oracle(self) -> None:
        self.assertIsNotNone(self.report.residue_volume_mm3)
        self.assertLess(
            abs(self.report.residue_volume_mm3 - NGON8_RESIDUE_MM3) / NGON8_RESIDUE_MM3,
            1e-3, "остаток разошёлся с замкнутой формулой больше чем на 0.1 %")

    def test_the_coverage_matches_the_oracle(self) -> None:
        self.assertAlmostEqual(self.report.coverage, NGON8_COVERAGE, places=9)

    def test_the_residue_is_addressed_zone_by_zone(self) -> None:
        """Eight shares around the atrium, and EACH has an address, a volume, a center, a bounding box."""
        self.assertEqual(len(self.report.residue), NGON8_ZONES)
        total = 0.0
        for zone in self.report.residue:
            with self.subTest(zone=zone.zone_id):
                self.assertEqual(zone.address, "podium")
                self.assertGreater(zone.volume_mm3, 0.0)
                self.assertEqual(len(zone.centroid_mm), 3)
                self.assertEqual(len(zone.bbox_mm), 6)
                self.assertEqual(zone.nearest_derived, "ngon8")
                self.assertIsNotNone(zone.gap_to_nearest_mm)
                total += zone.volume_mm3
        self.assertLess(abs(total - self.report.residue_volume_mm3), 1.0,
                        "сумма зон обязана сходиться с общим остатком")

    def test_nothing_is_dropped_between_the_zones_and_the_total(self) -> None:
        """The dust does not disappear: it is named by a number and a counter, not by silence."""
        counted = sum(zone.volume_mm3 for zone in self.report.residue)
        self.assertAlmostEqual(counted + self.report.residue_dust_mm3,
                               self.report.residue_volume_mm3, places=3)

    def test_the_excess_is_measured_on_the_other_side(self) -> None:
        """An inscribed N-gon gives an EXCESS, not a remainder: 5 871 853 665.8 mm³."""
        report = D.measure_refinement(
            _podium(), {"ngon8": _translated(8, "inscribed")}, source_address="podium",
            max_deviation_points=1)
        self.assertAlmostEqual(report.coverage, 1.0, places=9)
        self.assertLess(abs(report.excess_mm3 - 5_871_853_665.8) / 5_871_853_665.8, 1e-3)


@unittest.skipUnless(OCP_READY, "нужен профиль requirements-geometry-occt.txt")
class TheMaxDeviationNamesItsMethod(unittest.TestCase):
    """A grid-based estimate must print the method, the step, and the direction of convergence."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.report = D.measure_refinement(
            _podium(), {"ngon8": _translated(8, "circumscribed")},
            source_address="podium", max_deviation_step_mm=200.0,
            max_deviation_points=4000)
        #: r·(1 − cos(π/8)) — the maximum gap from the circle to the octagon.
        cls.oracle = ATRIUM["r"] * (1.0 - math.cos(math.pi / 8))

    def test_the_method_is_named_and_cannot_be_switched_off(self) -> None:
        row = self.report.max_deviation
        self.assertEqual(row.method, "grid")
        self.assertEqual(row.step_mm, 200.0)
        self.assertTrue(row.converges_from_below)
        self.assertGreater(row.points_inside, 0)
        self.assertGreater(row.points_tried, row.points_inside)
        with self.assertRaises(AssertionError):
            D.MaxDeviation(value_mm=1.0, method="grid", step_mm=1.0,
                           converges_from_below=False, points_inside=1, points_tried=1)
        with self.assertRaises(AssertionError):
            D.MaxDeviation(value_mm=1.0, method="hausdorff", step_mm=1.0,
                           converges_from_below=True, points_inside=1, points_tried=1)

    def test_the_estimate_never_exceeds_the_oracle(self) -> None:
        """One-sided BY CONSTRUCTION: the grid cannot land above the maximum."""
        self.assertIsNotNone(self.report.max_deviation.value_mm)
        self.assertLessEqual(self.report.max_deviation.value_mm, self.oracle + 1e-6)
        self.assertGreater(self.report.max_deviation.value_mm, 0.9 * self.oracle,
                           "шаг 200 мм давал 183.06 при оракуле 190.30 — "
                           "провал ниже 90 % означает, что сетка перестала попадать")

    def test_the_upper_bound_comes_from_the_zone_not_from_the_grid(self) -> None:
        self.assertGreater(self.report.max_deviation.upper_bound_mm,
                           self.report.max_deviation.value_mm)


@unittest.skipUnless(OCP_READY, "нужен профиль requirements-geometry-occt.txt")
class TheTwoWordsOfLossBecomeTwoNumbers(unittest.TestCase):
    """`concept_twist_removed` = 8.97 %, `concept_top_taper_removed` = 20.37 %."""

    def _symmetric_share(self, a, b):
        forward = D.measure_refinement(a, {"b": b}, source_address="a",
                                       max_deviation_points=1)
        backward = D.measure_refinement(b, {"a": a}, source_address="b",
                                        max_deviation_points=1)
        self.assertIsNotNone(forward.residue_volume_mm3, forward.refusal_codes())
        self.assertIsNotNone(backward.residue_volume_mm3, backward.refusal_codes())
        total = forward.residue_volume_mm3 + backward.residue_volume_mm3
        return total / forward.source_volume_mm3

    def test_twist_removed_is_almost_nine_percent(self) -> None:
        share = self._symmetric_share(_blend(12.0), _blend(0.0))
        self.assertAlmostEqual(share, TWIST_SHARE, places=6)

    def test_top_taper_removed_is_a_fifth_of_the_concept(self) -> None:
        share = self._symmetric_share(_blend(0.0), _tower_prism())
        self.assertAlmostEqual(share, TAPER_SHARE, places=6)


@unittest.skipUnless(OCP_READY, "нужен профиль requirements-geometry-occt.txt")
class ASilentBooleanCannotProduceACoverage(unittest.TestCase):
    """A silent zero from the kernel must become a refusal, not a "coverage 0" number."""

    def test_the_twisted_loft_refuses_instead_of_reporting_zero(self) -> None:
        report = D.measure_refinement(_blend(12.0), {"prism": _tower_prism()},
                                      source_address="tower-a", max_deviation_points=1)
        self.assertIsNone(report.coverage)
        self.assertFalse(report.ok)
        self.assertIn("boolean_contradicts_witness", report.refusal_codes())
        self.assertEqual([row["diag"] for row in report.refusals
                          if row["code"] == "boolean_contradicts_witness"], ["KIR-R006"])

    def test_without_the_witness_it_would_have_published_zero_coverage(self) -> None:
        """A/B ON A SINGLE LINE: a counterfactual, not an argument.

        The witness is switched off exactly where it is switched on — in
        the selection by curved face. With the selection disabled, the
        same input gives `coverage = 0.0` and "remainder = the whole
        tower": a number that looks honest and that the instrument would
        have published without a guard.
        """
        original = D.has_curved_faces
        try:
            D.has_curved_faces = lambda shape, k=None: False
            blind = D.measure_refinement(_blend(12.0), {"prism": _tower_prism()},
                                         source_address="tower-a", max_deviation_points=1)
        finally:
            D.has_curved_faces = original
        # An exact zero cannot be expected, and that too is evidence: `Cut`
        # returned 6.6 mm³ MORE than the source body (1122424596394.7
        # against 1122424596388.1) — meaning the kernel is not merely
        # wrong, it is also not self-consistent down to zero.
        self.assertAlmostEqual(blind.coverage, 0.0, places=9)
        self.assertNotIn("boolean_contradicts_witness", blind.refusal_codes(),
                         "с отключённым отбором сторож молчит — в этом контрфакт")
        self.assertGreater(blind.residue_volume_mm3, 1.1e12)


class BodiesComeFromOpsAndTypesNotFromConstants(unittest.TestCase):
    """The type carries the thickness, the op carries the height; whatever is missing is NAMED, not substituted."""

    LEVEL = {"op": "create_level", "elev_mm": 0.0, "name": "L1", "id": "level-1"}
    WALL_TYPE = {"op": "create_wall_type", "host_kind": "wall", "new_name": "W230",
                 "layers": [{"width_mm": 15, "function": "Finish1"},
                            {"width_mm": 200, "function": "Structure"},
                            {"width_mm": 15, "function": "Finish2"}],
                 "id": "type-wall"}
    WALL = {"op": "create_wall", "p0_mm": [0.0, 0.0], "p1_mm": [14000.0, 0.0],
            "height_mm": 4200.0, "level": {"by": "ref", "value": "level-1"},
            "type": {"by": "ref", "value": "type-wall"}, "id": "wall-1"}
    ROOM = {"op": "create_room", "xy": [100.0, 100.0], "name": "R",
            "level": {"by": "ref", "value": "level-1"}, "id": "room-1"}

    @unittest.skipUnless(OCP_READY, "нужен OCP")
    def test_the_wall_thickness_is_the_sum_of_the_declared_layers(self) -> None:
        bodies, missing = D.bodies_from_ops([self.LEVEL, self.WALL_TYPE, self.WALL])
        self.assertEqual(sorted(bodies), ["wall-1"])
        expected = 14000.0 * (15 + 200 + 15) * 4200.0
        self.assertAlmostEqual(_volume(bodies["wall-1"]) / expected, 1.0, places=9)

    @unittest.skipUnless(OCP_READY, "нужен OCP")
    def test_an_output_without_a_body_is_named_not_skipped(self) -> None:
        ops = [self.LEVEL, self.WALL_TYPE, self.WALL, self.ROOM]
        bodies, missing = D.bodies_from_ops(ops)
        self.assertEqual(len(bodies) + len(missing), len(ops),
                         "сумма построенных и названных обязана давать ВСЕ выходы")
        named = {row["address"] for row in missing}
        self.assertEqual(named, {"level-1", "type-wall", "room-1"})
        for row in missing:
            self.assertEqual(row["code"], "derived_has_no_body")
            self.assertEqual(row["diag"], "KIR-R008")
            self.assertTrue(row["detail"])

    @unittest.skipUnless(OCP_READY, "нужен OCP")
    def test_a_type_without_layers_does_not_get_a_default_thickness(self) -> None:
        """A substituted constant would be indistinguishable from a measurement. There is none."""
        empty = dict(self.WALL_TYPE, layers=[], id="type-empty")
        wall = dict(self.WALL, type={"by": "ref", "value": "type-empty"})
        bodies, missing = D.bodies_from_ops([self.LEVEL, empty, wall])
        self.assertEqual(bodies, {})
        self.assertIn("толщина не выводится",
                      " ".join(row["detail"] for row in missing))


class ThePlanDeltaIsMeasuredPerFloor(unittest.TestCase):
    """Acceptance measure (c): plan area by floor, `shapely`."""

    def _floor(self, hole, level, outer=((0.0, 0.0), (14000.0, 9000.0)), key="f"):
        (x0, y0), (x1, y1) = outer
        (hx0, hy0), (hx1, hy1) = hole
        return {"op": "create_floor_by_contour", "id": key,
                "level": {"by": "ref", "value": level},
                "contour": {"outer": {"shape": "poly",
                                      "points_mm": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]},
                            "holes": [{"shape": "poly",
                                       "points_mm": [[hx0, hy0], [hx1, hy0],
                                                     [hx1, hy1], [hx0, hy1]]}]}}

    def test_the_atrium_edit_costs_five_million_per_floor(self) -> None:
        before = [self._floor(((5000.0, 3000.0), (7000.0, 5000.0)), "L1")]
        after = [self._floor(((4500.0, 2500.0), (7500.0, 5500.0)), "L1")]
        delta, problems = D.plan_area_delta(before, after)
        self.assertEqual(problems, [])
        self.assertAlmostEqual(delta["L1"], -5_000_000.0, places=6)

    def test_the_facade_edit_costs_eleven_point_two_million(self) -> None:
        hole = ((5000.0, 3000.0), (7000.0, 5000.0))
        before = [self._floor(hole, "L1")]
        after = [self._floor(hole, "L1", outer=((0.0, -800.0), (14000.0, 9000.0)))]
        delta, _ = D.plan_area_delta(before, after)
        self.assertAlmostEqual(delta["L1"], 11_200_000.0, places=6)

    def test_a_floor_present_on_one_side_only_is_named(self) -> None:
        hole = ((5000.0, 3000.0), (7000.0, 5000.0))
        delta, problems = D.plan_area_delta([self._floor(hole, "L1")],
                                            [self._floor(hole, "L2")])
        self.assertEqual(delta, {})
        self.assertEqual(sorted(row["address"] for row in problems), ["L1", "L2"])
        for row in problems:
            self.assertEqual(row["diag"], "KIR-R015")


class TheRefusalListIsClosedAndRegistered(unittest.TestCase):
    """A refusal without a dispatcher code is a refusal without a repair address."""

    def test_every_refusal_has_exactly_one_registered_code(self) -> None:
        self.assertEqual(sorted(D.REFUSALS), sorted(D.REFUSAL_CODES))
        codes = list(D.REFUSAL_CODES.values())
        self.assertEqual(len(codes), len(set(codes)), "два отказа на один код")
        # The only refusal the author FIXES THEMSELVES is a self-
        # intersecting contour: the author writes the contour. Everything
        # else is the kernel, the call, or our own ceiling, and sending the
        # author to fix a correct program would be a lie.
        authors_own = {"plan_contour_unusable"}
        for name, code in sorted(D.REFUSAL_CODES.items()):
            with self.subTest(refusal=name):
                self.assertIn(code, diag.CODES, f"{code} не заведён у распорядителя")
                blame = diag.CODES[code].blame
                if name in authors_own:
                    self.assertEqual(blame, diag.BLAME_AUTHOR)
                else:
                    self.assertNotEqual(
                        blame, diag.BLAME_AUTHOR,
                        f"{name}: автор верной программы этого не чинит")

    def test_an_unknown_refusal_cannot_be_raised(self) -> None:
        with self.assertRaises(AssertionError):
            D.DeviationRefusal("whatever", "нет такого отказа")

    def test_a_missing_source_body_is_named_not_guessed(self) -> None:
        report = D.measure_refinement(None, {"a": None}, source_address="concept")
        self.assertIsNone(report.coverage)
        self.assertEqual(sorted(report.refusal_codes()),
                         ["derived_has_no_body", "source_has_no_body"])
        self.assertEqual([row["address"] for row in report.refusals],
                         ["concept", "a"])

    def test_the_policy_digest_travels_with_the_number(self) -> None:
        report = D.measure_refinement(None, {}, source_address="x")
        self.assertEqual(len(report.tolerance_policy_digest), 64)
        self.assertIn("witness_grid_n", report.declared)
        self.assertIn("floor_grows", report.declared)

    def test_two_tolerance_sources_are_refused(self) -> None:
        from kir.clash.exact import DEFAULT_POLICY
        with self.assertRaises(ValueError):
            D.measure_refinement(None, {}, tolerance=0.1, policy=DEFAULT_POLICY)


if __name__ == "__main__":                                     # pragma: no cover
    unittest.main()


@unittest.skipUnless(OCP_READY, "нужен профиль requirements-geometry-occt.txt")
class ACurvedSourceIsJudgedByBoundsAndSaysSo(unittest.TestCase):
    """A loft cannot be checked by a number — and the report must SAY so,
    not imply it.

    Measurement: the podium `bulge_mm=2000` gives 3.8716e+12 mm³ against
    two-sided bounds of 3.7601e+12 … 3.9881e+12; the one-sided "loft ⊇
    prism" is wrong — the loft dips INSIDE the prism by 4.297e+08 mm³. The
    spline has no closed-form formula.
    """

    def test_a_planar_pair_says_a_closed_form_is_possible(self) -> None:
        report = D.measure_refinement(
            _box(((0., 0., 0.), (1000., 1000., 1000.))),
            {"half": _box(((0., 0., 0.), (500., 1000., 1000.)))},
            source_address="cube", max_deviation_points=1)
        self.assertEqual(report.declared["volume_check"], "closed_form_possible")
        self.assertEqual(report.declared["curved_sides"], [])

    def test_a_curved_side_is_named_and_downgrades_the_check(self) -> None:
        report = D.measure_refinement(
            _podium(), {"ngon8": _translated(8, "circumscribed")},
            source_address="podium", max_deviation_points=1)
        self.assertEqual(report.declared["volume_check"], "bounds_only")
        self.assertEqual(report.declared["curved_sides"], ["source:podium"],
                         "криволинейная сторона названа поимённо, а не флагом")
