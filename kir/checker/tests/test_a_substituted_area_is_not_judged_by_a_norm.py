"""A SUBSTITUTED AREA IS NOT JUDGED BY A NORM (F-254).

🔴 WHAT USED TO HAPPEN. When an opening's height is unknown, live reading puts into `area_m2`
`width x 1.4`, while `design_check` uses the profile's nominal. `WindowDerivation` HONESTLY
wrote `area_measured=False`, and NO ONE ASKED for that value: the room's
accumulator took `w.area_m2` and carried a made-up number straight into the quantitative norm
HAB031. Our named class: a value is computed, recorded, and never read.

THE MEASUREMENT THAT MOTIVATES ALL OF THIS: on the tower, a dimension exists for 588 windows out of 2952 — that is,
**2364 substituted numbers** today either exonerate or convict a room.

    BEFORE glazing 2.10 · HAB031: ['big'] "0.105 below the norm" · HAB060 STAYS SILENT
    AFTER  glazing 0.00 · HAB031: SILENT · HAB060 names both rooms

🔴 THREE KINDS OF VALUE, NOT TWO. "measured" and "declared" are claims ABOUT THE BUILDING,
and they are judged; "nominal" is a claim about OUR OWN BLINDNESS, and it is judged by nothing.
The field's default is "declared", not None: a model assembled by anyone WITHOUT this
field carries the value its author named. Unconditional distrust would strip
the 1:8 norm off the entire reference corpus at once (all 58 windows of the 17 fixtures go without
`height_mm`), while measuring nothing in the process.

🔴 AND THE MAIN POINT: SILENCE MUST BE COUNTED. Without the HAB060 finding, the fix trades a
FALSE answer for SILENCE, and silence is indistinguishable from "checked and clean" — that
is, one defect would be traded for another of the same kind.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from kir.checker.derive import derive
from kir.checker.extractor import normalize
from kir.checker.rules import consistency, light
from kir.checker.graph import build_graph
from kir.checker.spatial_model import SpatialModel, Window
from kir.checker.thresholds import Thresholds

ТЬМА = {"KIR_CHECKER_V2": "1"}


def _дом(n, *, высота=None):
    rooms = [{"id": f"r{i}", "name": "Спальня", "level_id": "L0",
              "area_m2": 20.0, "height_mm": 2700.0,
              "boundary": [[i * 6000, 0], [i * 6000 + 5000, 0],
                           [i * 6000 + 5000, 4000], [i * 6000, 4000]]}
             for i in range(n)]
    wins = [{"id": f"w{i}", "level_id": "L0", "room_id": f"r{i}",
             "width_mm": 1500.0, "area_m2": 2.1, "height_mm": высота,
             "location": [i * 6000 + 2500.0, 0.0]} for i in range(n)]
    return {"building_id": "b",
            "levels": [{"id": "L0", "name": "L0", "elevation_mm": 0.0,
                        "index": 0}],
            "rooms": rooms, "windows": wins,
            "doors": [], "stairs": [], "walls": []}


def _судить(n, *, высота=None):
    """The model, the derivation, and the report — ALL under the raised lever.

    🔴 THE LEVER MUST BE HELD BOTH DURING NORMALIZATION AND DURING JUDGING, and this is not a detail
    of the test: the area's provenance is set in `normalize`, and the clause in
    `light.check_hab030` reads it. Run the first under v2 and the second under v1, and you get
    a model with an honest `area_source` and a rule judging it by the old law —
    a BLOCKING "cannot live without light" on a room with a confirmed window.
    The first edition of this file turned red exactly this way.
    """
    with mock.patch.dict(os.environ, ТЬМА):
        m = SpatialModel.model_validate(normalize(_дом(n, высота=высота)))
        thr = Thresholds()
        dm, rep = derive(m, thr)
        return m, dm, rep, thr


def _правило(fn, *a):
    with mock.patch.dict(os.environ, ТЬМА):
        return fn(*a)


class ПодставленнаяПлощадьНеСудится(unittest.TestCase):

    def test_норма_1к8_не_применяется_к_выдуманному_числу(self):
        m, dm, rep, thr = _судить(1)
        self.assertEqual(rep.windows["w0"].area_measured, False)
        self.assertEqual(dm.rooms[0].window_area_m2, 0.0,
                         "подставленная площадь доехала до накопителя комнаты")
        self.assertEqual(_правило(light.check_hab031, dm, build_graph(dm), thr), [],
                         "HAB031 обвиняет комнату по ВЫДУМАННОМУ числу")

    def test_измеренная_площадь_судится_как_прежде(self):
        """🔴 THE SECOND HALF. Without it the fix is indistinguishable from "turn off HAB031"."""
        m, dm, rep, thr = _судить(1, высота=400.0)
        self.assertEqual(rep.windows["w0"].area_measured, True)
        self.assertGreater(dm.rooms[0].window_area_m2, 0.0)
        self.assertTrue(_правило(light.check_hab031, dm, build_graph(dm), thr),
                        "измеренное остекление 0.6 м² на 20 м² пола обязано "
                        "нарушать норму 1:8 — правка сняла строгость и с него")

    def test_окно_подтверждено_значит_HAB030_молчит(self):
        """The size is not measured — but the WINDOW ITSELF is confirmed by geometry. Reading this
        as "there is no window" and issuing a BLOCKING verdict would be a conviction based on our own
        blindness."""
        m, dm, rep, thr = _судить(1)
        self.assertTrue(dm.rooms[0].has_window)
        self.assertEqual(_правило(light.check_hab030, dm, build_graph(dm), thr), [])

    def test_молчание_ПОСЧИТАНО_а_не_просто_наступило(self):
        m, dm, rep, thr = _судить(1)
        v = consistency.check_hab060(m, dm, rep, thr)
        self.assertTrue(v, "новая пустота не названа: молчание неотличимо от "
                           "«проверили и чисто»")
        self.assertIn("HAB031", v[0].msg)
        self.assertIn("r0", v[0].refs)

    def test_свёртка_ровно_на_пороге_и_адреса_не_теряются(self):
        """The threshold 3 is an ECHO of `render_verdict.max_examples`, not a standalone number."""
        for n, свёрнуто in ((3, False), (4, True)):
            with self.subTest(комнат=n):
                m, dm, rep, thr = _судить(n)
                v = consistency.check_hab060(m, dm, rep, thr)
                if свёрнуто:
                    self.assertEqual(len(v), 1)
                    self.assertEqual(len(v[0].refs), n,
                                     "адреса потеряны при сворачивании")
                    self.assertIn(str(n), v[0].msg, "число комнат не названо")
                else:
                    self.assertEqual(len(v), n)

    def test_порог_согласован_с_отрисовщиком(self):
        """🔴 TWO CARRIERS OF THE SAME NUMBER, AND THEY MUST AGREE. `max_examples`
        cannot be pulled in here by import — `checker` sits BELOW `design_check`, and
        a reverse import would create a cycle. So the number is repeated, and this guard
        holds the agreement: if they drifted apart, they would produce named lines that
        NEVER get printed."""
        import inspect
        from kir import design_check
        sig = inspect.signature(design_check.render_verdict)
        self.assertEqual(consistency._NAMED_ROOMS_LIMIT,
                         sig.parameters["max_examples"].default,
                         "порог сворачивания разошёлся с числом примеров "
                         "отрисовщика")

    def test_умолчание_поля_declared_а_не_nominal(self):
        """A model WITHOUT the field carries the author's value, not our own blindness."""
        w = Window(id="w", level_id="L0", width_mm=1500.0, area_m2=2.1)
        self.assertEqual(w.area_source, "declared")

    def test_под_v1_поведение_прежнее(self):
        """The fix does not introduce a THIRD exception to "v1 bit-for-bit"."""
        with mock.patch.dict(os.environ, {"KIR_CHECKER_V2": "0"}):
            d = normalize(_дом(1))
        self.assertNotIn("area_source", d["windows"][0],
                         "под v1 провенанс не ставится")


if __name__ == "__main__":
    unittest.main()
