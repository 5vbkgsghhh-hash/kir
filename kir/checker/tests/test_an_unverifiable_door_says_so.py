"""AN UNVERIFIABLE DOOR MUST SAY SO (F-355 + F-252).

Two halves of ONE fix, hence one file and one commit: `derive` stops
CONFIRMING a half-resolved door, `check_hab061` stops STAYING SILENT about
an unverifiable one. Apart, each is useless: without the first there is nothing to sound,
without the second the new status leaves mute.

🔴 MEASUREMENT OVER THE CORPUS — MINE, 30.08.2026, 81 decompiles, read-only corpus:

    buildings with doors        34   ·  doors total 31 003
    UNVERIFIABLE                4 271 across 23 buildings
    statuses: confirmed_interior 19603 · confirmed_exterior 4524 ·
             unknown 4271 · orphan 2489 · contradicted 116

🔴 AND A DISTINCTION WITHOUT WHICH THE NUMBER WOULD LIE. The same run with `derive` from
HEAD gives EXACTLY THE SAME 4271 across 23 buildings. Therefore:

  * all the measured harm belongs to **F-355**: 4271 doors across 23 buildings
    today leave SILENTLY, with their connectivity counted as confirmed;
  * **F-252** on this corpus gives a MEASURED ZERO — the case "both declared
    measurable ends agree, but the other end did not resolve" was not encountered once.
    The mechanism is correct and the discriminator is implemented, but the frequency here is zero, and
    attributing 4271 to it would be a lie.

The edge in the graph is NOT REMOVED in any case: removing it would mean asserting
that there IS no door, when all that is known is that it could not be checked. The WARNING severity
is a finding about OUR OWN READING, not a proven defect of the building.
"""
from __future__ import annotations

import unittest

from kir.checker.derive import derive
from kir.checker.graph import build_graph
from kir.checker.rules import consistency
from kir.checker.derive import DoorStatus
from kir.checker.spatial_model import SpatialModel
from kir.checker.thresholds import Thresholds

_КОНТУР = [[0, 0], [4000, 0], [4000, 3000], [0, 3000]]


def _модель(*, границы: bool, второй_конец: str | None = "r2") -> SpatialModel:
    комната = lambda rid, x, имя, ф: {
        "id": rid, "name": имя, "level_id": "L0", "function": ф,
        "area_m2": 12.0, "height_mm": 2700.0,
        "boundary": ([[x + a, b] for a, b in _КОНТУР] if границы else [])}
    return SpatialModel.model_validate({
        "building_id": "b",
        "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0, "index": 0}],
        "rooms": [комната("r1", 0, "Спальня", "жилая"),
                  комната("r2", 4000, "Коридор", "коридор")],
        "doors": [{"id": "d1", "level_id": "L0", "location": [4000.0, 1500.0],
                   "width_mm": 900.0, "from_room_id": "r1",
                   "to_room_id": второй_конец, "is_exterior": False}]})


def _судить(m):
    thr = Thresholds()
    dm, rep = derive(m, thr)
    return dm, rep, thr


class НепроверяемаяДверьГоворитОСебе(unittest.TestCase):

    def test_дверь_без_измеримых_сторон_НЕ_подтверждается(self):
        _dm, rep, _thr = _судить(_модель(границы=False))
        self.assertIs(rep.doors["d1"].status, DoorStatus.UNKNOWN)

    def test_и_она_получает_находку_а_не_молчание(self):
        m = _модель(границы=False)
        dm, rep, thr = _судить(m)
        v = consistency.check_hab061(m, dm, rep, thr)
        свои = [x for x in v if "d1" in x.refs]
        self.assertTrue(свои, "непроверяемая дверь ушла МОЛЧА: её связность "
                              "считается подтверждённой, а подтверждать её "
                              "нечем")
        self.assertIn("UNVERIFIABLE", свои[0].msg)

    def test_ребро_НЕ_снимается(self):
        """Removing the edge would mean asserting that there IS no door. We only know
        that we failed to check it — these are different facts."""
        m = _модель(границы=False)
        dm, _rep, _thr = _судить(m)
        g = build_graph(dm)
        self.assertTrue(g.has_edge("r1", "r2"),
                        "ребро снято: находка о НАШЕМ чтении превращена в "
                        "утверждение об отсутствии двери")

    def test_конец_ВНЕ_модели_называется_отдельно(self):
        """F-252: the two outcomes are DIFFERENT, and both must be named. A room
        that is not in the model at all loses its edge; a room without a boundary
        keeps its edge. One phrase for both cases would hide the difference."""
        m = _модель(границы=True, второй_конец="ghost")
        dm, rep, thr = _судить(m)
        d = rep.doors["d1"]
        self.assertIs(d.status, DoorStatus.UNKNOWN)
        self.assertIn("not in the model at all", d.note)
        self.assertIn("drops this door's edge", d.note)
        v = consistency.check_hab061(m, dm, rep, thr)
        self.assertTrue([x for x in v if "d1" in x.refs])

    def test_две_пустоты_различаются_ТЕКСТОМ(self):
        """Otherwise "there is a reason" would be satisfied by one phrase for both cases —
        the same mute value, just in words."""
        нет_границы = _судить(_модель(границы=False))[1].doors["d1"].note
        нет_комнаты = _судить(_модель(границы=True,
                                      второй_конец="ghost"))[1].doors["d1"].note
        self.assertNotEqual(нет_границы, нет_комнаты)

    def test_ЗДОРОВАЯ_дверь_по_прежнему_подтверждается(self):
        """🔴 THE SECOND HALF. Without it the fix is indistinguishable from "declare all doors
        unverifiable", and on the reference fixture this would remove connectivity entirely."""
        m = _модель(границы=True)
        dm, rep, thr = _судить(m)
        self.assertIs(rep.doors["d1"].status, DoorStatus.CONFIRMED_INTERIOR)
        self.assertEqual(
            [x for x in consistency.check_hab061(m, dm, rep, thr)
             if "d1" in x.refs], [],
            "здоровая дверь получила находку — правка красит всё подряд")

    def test_наружная_непроверяемая_сохранила_СВОЙ_текст(self):
        """The exterior branch already existed and must remain separate: it has
        its own next step ("an exit to the street must lie on the envelope")."""
        m = SpatialModel.model_validate({
            "building_id": "b",
            "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0,
                        "index": 0}],
            "rooms": [{"id": "r1", "name": "Спальня", "level_id": "L0",
                       "function": "жилая", "area_m2": 12.0,
                       "height_mm": 2700.0, "boundary": []}],
            "doors": [{"id": "dx", "level_id": "L0", "location": [0.0, 0.0],
                       "width_mm": 900.0, "from_room_id": "r1",
                       "to_room_id": None, "is_exterior": True}]})
        dm, rep, thr = _судить(m)
        v = [x for x in consistency.check_hab061(m, dm, rep, thr)
             if "dx" in x.refs]
        self.assertTrue(v)
        self.assertIn("declared EXTERIOR", v[0].msg,
                      "наружная непроверяемость съедена общей веткой")


if __name__ == "__main__":
    unittest.main()
