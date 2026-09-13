"""A DOOR'S HOST IS READ, NOT GUESSED (F-347).

🔴 WHAT USED TO HAPPEN. HAB041 took the FIRST wall of the level within tolerance and measured the
door's width against it. `Door.host_wall_id` — a MEASUREMENT read from Revit (`d.Host.Id`)
and from the decompile — was not consulted at all. The verdict therefore depended on the ORDER OF THE
WALL LIST, and list order is not a property of the building.

MY MEASUREMENT OVER THE CORPUS (30.08.2026, 81 decompiles, read-only):

    31 003 doors across 34 buildings · host DECLARED for 29 889
    guessed wall != declared one   821 doors across 30 buildings
    of them HAB041's VERDICT DIFFERS   92 doors across 12 buildings

Ninety-two doors in twelve real buildings get a width verdict
against SOMEONE ELSE'S wall — and "passed" or "failed" is decided by iteration order.

🔴 AMBIGUITY IS NAMED, NOT RESOLVED BY SORTING. When the host is not
declared and more than one wall is within tolerance, choosing the longest would
systematically EXONERATE the door (the building looks safer on paper), choosing the
short one would systematically CONVICT it. Both substitutions are worse than an honest "nothing to measure with",
so a finding with a list of candidates is issued instead.
"""
from __future__ import annotations

import unittest

import networkx as nx

from kir.checker.rules import clash
from kir.checker.spatial_model import SpatialModel
from kir.checker.thresholds import Thresholds

СТЕНЫ = {
    # a short OWN wall — the door hangs on it
    "Wshort": {"id": "Wshort", "level_id": "L0", "curve": [[0, 0], [800, 0]],
               "height_mm": 2700.0},
    # a long FOREIGN wall, 30 mm away — also falls within tolerance
    "Wlong": {"id": "Wlong", "level_id": "L0", "curve": [[-500, 30], [1500, 30]],
              "height_mm": 2700.0},
}


def _модель(порядок, *, хозяин="Wshort", уровень_двери="L0"):
    return SpatialModel.model_validate({
        "building_id": "b",
        "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0, "index": 0},
                   {"id": "L1", "name": "L1", "elevation_mm": 3000.0, "index": 1}],
        "rooms": [{"id": "r1", "name": "Спальня", "level_id": "L0",
                   "function": "жилая", "area_m2": 12.0, "height_mm": 2700.0,
                   "boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}],
        "doors": [{"id": "d1", "level_id": уровень_двери, "location": [400, 0],
                   "width_mm": 1000.0, "from_room_id": "r1", "to_room_id": None,
                   "is_exterior": False, "host_wall_id": хозяин}],
        "walls": [СТЕНЫ[k] for k in порядок]})


def _судить(m):
    return clash.check_hab041(m, nx.Graph(), Thresholds())


class ХозяинЧитаетсяАНеУгадывается(unittest.TestCase):

    def test_вердикт_не_зависит_от_ПОРЯДКА_списка_стен(self):
        """THE MAIN CLAIM. One building, the same doors — only the
        walls in the list are reordered."""
        прямо = [v.msg for v in _судить(_модель(["Wshort", "Wlong"]))]
        наоборот = [v.msg for v in _судить(_модель(["Wlong", "Wshort"]))]
        self.assertEqual(прямо, наоборот,
                         "вердикт HAB041 поехал за порядком списка стен — "
                         "порядок списка не есть свойство постройки")

    def test_мерится_ОБЪЯВЛЕННЫЙ_хозяин_а_не_ближайший(self):
        """And what is measured is exactly the one the provider named: a 1000 mm door on
        an 800 mm wall is a violation, no matter how many long walls lie nearby."""
        for порядок in (["Wshort", "Wlong"], ["Wlong", "Wshort"]):
            with self.subTest(порядок=порядок):
                v = _судить(_модель(порядок))
                self.assertTrue(v, "нарушение потерялось")
                self.assertIn("Wshort", v[0].msg,
                              "ширина померена против ЧУЖОЙ стены")

    def test_ВТОРАЯ_ПОЛОВИНА_здоровая_дверь_молчит(self):
        """Without it the fix is indistinguishable from "always convict"."""
        m = _модель(["Wshort", "Wlong"], хозяин="Wlong")
        self.assertEqual(_судить(m), [],
                         "дверь 1000 мм на стене 2000 мм обвинена — правка "
                         "красит всё подряд")

    def test_хозяин_с_ЧУЖОГО_уровня_не_хозяин(self):
        """A declared id is not a free pass: a wall from another level cannot
        be the host, and it must not be substituted in place of the check."""
        m = _модель(["Wshort", "Wlong"], уровень_двери="L1")
        v = _судить(m)
        self.assertEqual([x.msg for x in v if "Wshort" in x.msg], [],
                         "дверь померена против стены ЧУЖОГО уровня")

    def test_неоднозначность_НАЗЫВАЕТСЯ(self):
        """The host is not declared, two walls are within tolerance — a finding with a list of
        candidates, not a silent choice of one of them."""
        m = _модель(["Wshort", "Wlong"], хозяин=None)
        v = _судить(m)
        свои = [x for x in v if "d1" in x.refs]
        self.assertTrue(свои, "неоднозначность решена молча сортировкой")
        self.assertIn("NOT applied", свои[0].msg)
        self.assertIn("Wshort", свои[0].refs)
        self.assertIn("Wlong", свои[0].refs)

    def test_одна_стена_в_допуске_по_прежнему_меряется(self):
        """THE SECOND HALF of the ambiguity case: when there is ONE candidate, the rule
        must measure, not refuse. Otherwise "nothing to measure with" would swallow
        the ordinary case."""
        m = SpatialModel.model_validate({
            "building_id": "b",
            "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0,
                        "index": 0}],
            "rooms": [{"id": "r1", "name": "Спальня", "level_id": "L0",
                       "function": "жилая", "area_m2": 12.0,
                       "height_mm": 2700.0,
                       "boundary": [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]}],
            "doors": [{"id": "d1", "level_id": "L0", "location": [400, 0],
                       "width_mm": 1000.0, "from_room_id": "r1",
                       "to_room_id": None, "is_exterior": False}],
            "walls": [СТЕНЫ["Wshort"]]})
        v = _судить(m)
        self.assertTrue(v)
        self.assertIn("wider than its host wall", v[0].msg)


if __name__ == "__main__":
    unittest.main()
