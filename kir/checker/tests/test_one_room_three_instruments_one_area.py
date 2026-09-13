"""ONE ROOM — THREE INSTRUMENTS — ONE GEOMETRY (F-041).

🔴 WHY A SEPARATE FILE. A room's void (a shaft, an atrium, a stair cutout) is
read by THREE independent instruments of the judge, and before 29.08.2026 NOT
A SINGLE one read it:

    derive._polygon                 derived area           -> HAB020/HAB021/HAB060
    rules.clash._polygon            area overlap           -> HAB040
    rules.dimensions._min_width_mm  width                  -> HAB021

Fixing one of the three is WORSE than not fixing any: then the same room is
measured by DIFFERENT geometry, and verdicts diverge between rules, not
between buildings. This file is exactly the guard that the F-041 package
demanded be set up TOGETHER with the fix, because the fix had none of its
own.

THE MEASUREMENT FOR WHOSE SAKE ALL OF THIS EXISTS (executed 29.08.2026): a
room 4x4 m with a 3x3 m shaft, Revit declared 7 m².

    BEFORE  derived 16.0 m² · HAB020 STAYS SILENT · HAB060 BLOCKING «Revit лжёт»
    AFTER   derived  7.0 m² · HAB020 finds a violation · HAB060 stays silent

Two findings moved in OPPOSITE directions from a single fix: a real violation
appeared, a false accusation disappeared. This cannot be a coincidence.
"""
from __future__ import annotations

import unittest

from shapely.geometry import Polygon

from kir.checker import derive as D
from kir.checker.rules import clash as C
from kir.checker.rules import dimensions as DIM
from kir.checker.spatial_model import SpatialModel
from kir.checker.thresholds import Thresholds

ВНЕШНИЙ = [[0, 0], [4000, 0], [4000, 4000], [0, 4000]]
ШАХТА = [[500, 500], [3500, 500], [3500, 3500], [500, 3500]]
ИСТИНА_М2 = 7.0          # 16 - 9
ИСТИНА_ММ2 = 7_000_000.0


def _модель(*, с_дырой: bool) -> SpatialModel:
    комната = {"id": "r1", "name": "Спальня", "level_id": "L0",
               "function": "жилая", "area_m2": ИСТИНА_М2, "height_mm": 2700.0,
               "boundary": ВНЕШНИЙ}
    if с_дырой:
        комната["boundary_holes"] = [ШАХТА]
    return SpatialModel.model_validate({
        "building_id": "b",
        "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0, "index": 0}],
        "rooms": [комната]})


class ТриПрибораМеряютОдноПомещение(unittest.TestCase):

    def test_истина_названа_shapely_а_не_мной(self):
        """The reference value is taken from the same library as the
        instruments — otherwise the test would be checking the instruments
        against my own arithmetic, not against geometry."""
        self.assertAlmostEqual(
            Polygon(ВНЕШНИЙ, [ШАХТА]).area / 1e6, ИСТИНА_М2, places=6)

    def test_derive_видит_дыру(self):
        m = _модель(с_дырой=True)
        _dm, rep = D.derive(m, Thresholds())
        self.assertAlmostEqual(rep.rooms["r1"].derived_area_m2, ИСТИНА_М2,
                               places=3)

    def test_clash_видит_ту_же_дыру(self):
        """HAB040 is obligated to compute the same area: without the void,
        two apartments around ONE shared shaft would get a false "area
        overlap"."""
        r = _модель(с_дырой=True).rooms[0]
        poly = C._polygon(r.boundary, r.boundary_holes)
        self.assertIsNotNone(poly)
        self.assertAlmostEqual(poly.area, ИСТИНА_ММ2, places=3)

    def test_dimensions_видит_ту_же_дыру(self):
        """The width of a "habitable" room around a shaft is the width of the
        RING (500 mm), not the outer contour's bounding size."""
        r = _модель(с_дырой=True).rooms[0]
        ширина = DIM._min_width_mm(r.boundary, r.boundary_holes)
        self.assertIsNotNone(ширина)
        self.assertLess(ширина, 1000.0,
                        "ширина посчитана по сплошной фигуре: дыра не учтена")

    def test_три_прибора_сходятся_числом(self):
        """THE MAIN ASSERTION: the area in derive and in clash is ONE AND THE SAME.

        Fixed separately, either one could be fixed without noticing that the
        other stayed on the old geometry. Here they are compared AGAINST EACH
        OTHER, not against a constant, so the discrepancy is visible even if
        both are wrong the same way relative to my expectation.
        """
        r = _модель(с_дырой=True).rooms[0]
        _dm, rep = D.derive(_модель(с_дырой=True), Thresholds())
        из_clash = C._polygon(r.boundary, r.boundary_holes).area / 1e6
        self.assertAlmostEqual(rep.rooms["r1"].derived_area_m2, из_clash,
                               places=3,
                               msg="derive и clash меряют одно помещение "
                                   "по РАЗНОЙ геометрии")

    def test_HAB040_гонится_ЦЕЛИКОМ_а_не_через_помощника(self):
        """🔴 THE FIRST EDITION OF THIS FILE FAILED ITS OWN CONTROL, AND THIS IS ON RECORD.

        It called `clash._polygon(r.boundary, r.boundary_holes)` DIRECTLY —
        that is, it checked the HELPER while bypassing the call sites. The
        mutation "revert `clash`'s calls to what they were, leaving the
        helper alone" left it GREEN: `6 passed`. The helper knows how to read
        voids, the rule does not feed them to it, and HAB040 still computes
        against the outer shell — exactly the defect this file was written
        for.

        So here the rule is exercised IN FULL. The geometry is physical: the
        stair core stands INSIDE the atrium's void. Without subtracting the
        void, the atrium is "occupied" by a large room, and the core is
        declared an overlap that does not exist.
        """
        import networkx as nx
        внешний = [[0, 0], [8000, 0], [8000, 8000], [0, 8000]]
        атриум = [[2000, 2000], [6000, 2000], [6000, 6000], [2000, 6000]]
        ядро = [[2500, 2500], [5500, 2500], [5500, 5500], [2500, 5500]]
        m = SpatialModel.model_validate({
            "building_id": "b",
            "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0,
                        "index": 0}],
            "rooms": [
                {"id": "зал", "name": "Холл", "level_id": "L0",
                 "function": "коридор", "area_m2": 48.0, "height_mm": 2700.0,
                 "boundary": внешний, "boundary_holes": [атриум]},
                {"id": "ядро", "name": "Лестница", "level_id": "L0",
                 "function": "лестница", "area_m2": 9.0, "height_mm": 2700.0,
                 "boundary": ядро}]})
        находки = C.check_hab040(m, nx.Graph(), Thresholds())
        self.assertEqual(
            [v.rule_id for v in находки], [],
            "HAB040 объявил наложением ядро, стоящее В ПУСТОТЕ атриума: "
            "правило считает по ВНЕШНЕЙ оболочке, дыра до него не доехала")

    def test_HAB040_настоящее_наложение_по_прежнему_находит(self):
        """THE SECOND HALF: the fix has no right to blind the rule.

        Without this case, "HAB040 always stays silent" would pass the
        previous test.
        """
        import networkx as nx
        a = [[0, 0], [4000, 0], [4000, 4000], [0, 4000]]
        b = [[1000, 1000], [5000, 1000], [5000, 5000], [1000, 5000]]
        m = SpatialModel.model_validate({
            "building_id": "b",
            "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0,
                        "index": 0}],
            "rooms": [
                {"id": "p1", "name": "Спальня", "level_id": "L0",
                 "function": "жилая", "area_m2": 16.0, "height_mm": 2700.0,
                 "boundary": a},
                {"id": "p2", "name": "Спальня", "level_id": "L0",
                 "function": "жилая", "area_m2": 16.0, "height_mm": 2700.0,
                 "boundary": b}]})
        находки = C.check_hab040(m, nx.Graph(), Thresholds())
        self.assertTrue(находки, "настоящее наложение перестало находиться")

    def test_без_дыры_поведение_прежнее(self):
        """THE SECOND HALF (rule 2). Without this case the fix is
        indistinguishable from "always subtract," while it is obligated to be
        PURELY ADDITIVE: on inputs with no voids, all three instruments give
        exactly what they gave before 29.08.2026."""
        r = _модель(с_дырой=False).rooms[0]
        self.assertEqual(r.boundary_holes, [])
        _dm, rep = D.derive(_модель(с_дырой=False), Thresholds())
        self.assertAlmostEqual(rep.rooms["r1"].derived_area_m2, 16.0, places=3)
        self.assertAlmostEqual(C._polygon(r.boundary, r.boundary_holes).area,
                               16_000_000.0, places=3)
        self.assertGreater(DIM._min_width_mm(r.boundary, r.boundary_holes),
                           3000.0)


if __name__ == "__main__":
    unittest.main()
