"""HAB022 JUDGED BY A STAND-IN, AND ONE UNREAD FIELD WAS ALL THAT SEPARATED THAT FROM A SILENT LIE.

MEASUREMENT OF 20.08.2026. On the parse path, a room's height was OUR OWN
STAND-IN — the bounding box's vertical span (`design_check`) — while the rule
read `Room.height_mm` and did not ask about its origin at all. That is, a
blocking verdict was issued on a number the author never declared. On the
tower the stand-in covered 2 154 rooms out of 2 442.

A live run the same day (`MNVNK_ATR_PD_B14_K6_AR_R2022`, Revit 2023,
read-only) showed that a real value EXISTS: `ROOM_UPPER_OFFSET` is carried by
1102 rooms out of 1102, 1081 of them non-zero, 0 failures. The parameter has
been added to the capture (`f4c35e51`), and the stand-in stopped being the
only path.

🔴 WHAT THIS FILE HOLDS IN PLACE IS PRECISELY THE DISTINCTION, NOT THE FIELD'S
MERE EXISTENCE. The `height_source` field existed even before the fix; what
did not exist was a READER, and so the field was decoration. The experiment
is built so that the distinction is obligated to be visible on the SAME room
at the same height: only the source changes.

    height 1200 mm, source `room_upper_offset` -> BLOCKING
    height 1200 mm, source `room_bbox`         -> WARNING

Were there no difference — the field would exist, but no distinction would,
and we would be reading a strict verdict where nothing was measured.
"""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("KUKAI_CHECKER_V2", "1")

import networkx as nx

from kir.checker.height_provenance import (AUTHORED, DERIVED,
                                                      describe,
                                                      height_authority,
                                                      is_authored)
from kir.checker.rules.dimensions import check_hab022
from kir.checker.spatial_model import (RoomFunction, Severity,
                                                  SpatialModel)
from kir.checker.thresholds import Thresholds


def _model(height_mm: float, source: str | None) -> SpatialModel:
    """One room. Everything except the source is deliberately held constant."""
    return SpatialModel.model_validate({
        "building_id": "b1",
        "levels": [{"id": "L1", "name": "L1", "elevation_mm": 0.0, "index": 0}],
        "rooms": [{
            "id": "R1", "name": "Жилая комната", "level_id": "L1",
            "function": RoomFunction.ЖИЛАЯ.value, "area_m2": 18.0,
            "height_mm": height_mm, "height_source": source,
            "boundary": [(0.0, 0.0), (6000.0, 0.0), (6000.0, 3000.0), (0.0, 3000.0)],
        }],
    })


def _verdicts(height_mm: float, source: str | None):
    thr = Thresholds()
    return check_hab022(_model(height_mm, source), nx.Graph(), thr)


class ОдноЧислоДваИсточникаДваВердикта(unittest.TestCase):

    def test_прочитанная_высота_БЛОКИРУЕТ(self):
        found = _verdicts(1200.0, "room_upper_offset")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, Severity.BLOCKING)

    def test_подставленная_высота_ПРЕДУПРЕЖДАЕТ_и_называет_причину(self):
        found = _verdicts(1200.0, "room_bbox")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].severity, Severity.WARNING)
        self.assertIn("ПОДСТАВЛЕНА", found[0].msg)

    def test_различие_наблюдаемо_НА_ОДНОЙ_КОМНАТЕ(self):
        """The file's main assertion, on its own line.

        EXACTLY the source changes; the height, function, area, and
        threshold are the same.
        """
        strict = _verdicts(1200.0, "room_upper_offset")[0].severity
        soft = _verdicts(1200.0, "room_bbox")[0].severity
        self.assertNotEqual(strict, soft,
                            "поле есть, а различия нет — правило не читает источник")

    def test_мягкий_порог_срабатывает_ОДИНАКОВО(self):
        """A stand-in is grounds not to call the verdict proven, not grounds to overlook it.

        Without this, "softer" would slide into "silent," and a low ceiling
        on the parse path would stop being visible at all.
        """
        for src in ("room_upper_offset", "room_bbox"):
            with self.subTest(источник=src):
                found = _verdicts(2200.0, src)
                self.assertEqual(len(found), 1, "низкий потолок обязан быть виден")
                self.assertEqual(found[0].severity, Severity.WARNING)

    def test_здоровая_высота_молчит_при_обоих_источниках(self):
        """Degeneracy control: the rule is also capable of NOT firing."""
        for src in ("room_upper_offset", "room_bbox"):
            with self.subTest(источник=src):
                self.assertEqual(_verdicts(3000.0, src), [])


class ТриРодаАНеДва(unittest.TestCase):

    def test_неизвестное_имя_источника_НЕ_становится_прочитанным(self):
        """There are four producers, they live in different files, there is one dictionary.

        Silently promoting an unfamiliar name to "read" is the one mistake
        that must never happen here, not even once.
        """
        self.assertEqual(height_authority("совершенно_новый_источник"), "unknown")
        self.assertFalse(is_authored("совершенно_новый_источник"))
        found = _verdicts(1200.0, "совершенно_новый_источник")
        self.assertEqual(found[0].severity, Severity.WARNING,
                         "незнакомый источник обязан судиться как неподтверждённый")

    def test_отсутствие_высоты_это_третий_исход_а_не_ноль(self):
        self.assertEqual(height_authority(None), "unknown")
        self.assertIn("судить нечем", describe(None))
        self.assertEqual(_verdicts(3000.0, None), [],
                         "правило не судит того, чего не знает")
        model = SpatialModel.model_validate({
            "building_id": "b1",
            "levels": [{"id": "L1", "name": "L1", "elevation_mm": 0.0, "index": 0}],
            "rooms": [{"id": "R1", "name": "Жилая комната", "level_id": "L1",
                       "function": RoomFunction.ЖИЛАЯ.value, "area_m2": 18.0,
                       "height_mm": None, "height_source": None, "boundary": []}],
        })
        self.assertEqual(check_hab022(model, nx.Graph(), Thresholds()), [])

    def test_словари_не_пересекаются(self):
        """A name in both sets would be read by the order of checks, not by meaning."""
        self.assertEqual(AUTHORED & DERIVED, frozenset())
        self.assertTrue(AUTHORED and DERIVED)

    def test_каждое_объявленное_имя_разбирается_своим_родом(self):
        for name in AUTHORED:
            self.assertEqual(height_authority(name), "authored", name)
        for name in DERIVED:
            self.assertEqual(height_authority(name), "derived", name)


class КвитанцияПереживаетСледующийШов(unittest.TestCase):
    """🔴 A DEFECT IS PINNED HERE THAT ALMOST GOT AWAY IN THIS VERY FIX.

    The first edition put three numbers about the height's provenance into
    `witness.counts` — but `counts` is assigned WHOLESALE further down the
    SAME path (`design_check.py`: `witness.counts = {...}`), and the counters
    died silently. Caught by the simple act of PRINTING them: the line about
    the source showed 2154, while the dictionary next to it was empty.

    This is the same form that this whole wave is fixing: a receipt getting
    lost at the next seam. The test holds not "the fields exist" but "the
    assignment to `counts` does not extinguish them" — that is, exactly the
    step where they were being lost.
    """

    def test_присвоение_counts_не_гасит_происхождение(self):
        from kir.design_check import BuildWitness, ModelSource
        w = BuildWitness(source=ModelSource.PARSE, building_id="b", doc_name="b")
        w.rooms_height_authored = 7
        w.rooms_height_substituted = 11
        w.rooms_height_disagree = 2
        # exactly what the production path does further down in the code
        w.counts = {"levels": 1, "rooms": 18, "walls": 0,
                    "doors": 0, "windows": 0, "stairs": 0}
        self.assertEqual((w.rooms_height_authored, w.rooms_height_substituted,
                          w.rooms_height_disagree), (7, 11, 2))

    def test_три_числа_РАЗНЫЕ_поля_а_не_одно(self):
        """Folding them into one would mean losing exactly that distinction."""
        from kir.design_check import BuildWitness, ModelSource
        w = BuildWitness(source=ModelSource.PARSE, building_id="b", doc_name="b")
        for name in ("rooms_height_authored", "rooms_height_substituted",
                     "rooms_height_disagree"):
            self.assertEqual(getattr(w, name), 0, name)


class ОбъявленныйНольЭтоТретийИсход(unittest.TestCase):
    """🔴 LIVE MEASUREMENT OF 20.08.2026: 21 ROOMS OUT OF 1102 HAVE AN OFFSET OF
    EXACTLY ZERO.

    Zero is neither emptiness nor a refusal: the author spoke up. The first
    edition of the read (`> 0.0`) dropped it into the same branch as an
    absent parameter, and "the author wrote 0" once again turned into "we did
    not ask" — the same class already dealt with today for `room_link` and
    for `receipts()`. The third time in one day, and each time in
    neighboring lines of my own fresh code.

    Height does not follow from zero: the offset is measured from the UPPER
    LIMIT, whose level is not captured in L0. So the height is taken from the
    bounding box and honestly called `room_bbox`, while the fact of the
    author speaking up is counted SEPARATELY.
    """

    def _read(self, params):
        from kir.design_check import _room_upper_offset

        class _E:
            def __init__(self, p): self.params = p
        return _room_upper_offset(_E(params))

    def test_ноль_отличается_от_отсутствия(self):
        self.assertEqual(self._read({}), (None, "absent"))
        self.assertEqual(self._read({"ROOM_UPPER_OFFSET": 0}), (None, "authored_zero"))

    def test_положительное_даёт_высоту(self):
        value, state = self._read({"ROOM_UPPER_OFFSET": 3000})
        self.assertEqual((value, state), (3000.0, "authored"))

    def test_дробное_принимается_как_объявленное(self):
        """The kind alone does NOT establish authority — that is a convention.

        The live value 3493.7421314280423 is not round, and the temptation
        to read it as "derived by Revit" is strong. The author is free to
        type in any number; the real authority is `Parameter.IsReadOnly`, and
        it is asked live.
        """
        value, state = self._read({"ROOM_UPPER_OFFSET": 3493.7421314280423})
        self.assertEqual(state, "authored")
        self.assertAlmostEqual(value, 3493.7421314280423)

    def test_отрицательное_не_подставляется_молча(self):
        self.assertEqual(self._read({"ROOM_UPPER_OFFSET": -500}),
                         (None, "authored_negative"))

    def test_нечисло_и_bool_не_читаются_как_величина(self):
        for bad in ("", "3000", True, None, []):
            with self.subTest(значение=repr(bad)):
                self.assertEqual(self._read({"ROOM_UPPER_OFFSET": bad})[1], "absent")


class ПриборРасхожденияНеВЫДУМЫВАЕТ(unittest.TestCase):
    """The discrepancy between the declared value and the stand-in is counted
    WITHOUT a parse.

    The capture's body returns `params` and the bounding box in one response,
    so the question is settled on rows already collected.
    """

    def _run(self, rows):
        from kir.design_check import upper_offset_vs_bbox
        return upper_offset_vs_bbox(rows)

    def test_на_рядах_без_параметра_говорит_НЕ_ЗАХВАЧЕНО_а_не_ноль_расхождений(self):
        out = self._run([{"params": {}, "bbox_min_mm": [0, 0, 0],
                          "bbox_max_mm": [0, 0, 3000.0]}] * 5)
        self.assertEqual(out["absent"], 5)
        self.assertEqual(out["authored"], 0)
        self.assertEqual(out["disagree"], 0)
        self.assertEqual(out["agree_within_1mm"], 0,
                         "согласия тоже нет: сравнивать было не с чем")

    def test_расхождение_находится_и_НАЗЫВАЕТСЯ_худшим(self):
        out = self._run([
            {"params": {"ROOM_UPPER_OFFSET": 3000.0},
             "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [0, 0, 3000.0]},
            {"params": {"ROOM_UPPER_OFFSET": 3000.0},
             "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [0, 0, 5250.0]},
        ])
        self.assertEqual((out["agree_within_1mm"], out["disagree"]), (1, 1))
        self.assertEqual(out["worst_disagreement"], (2250.0, 3000.0, 5250.0))

    def test_дробные_считаются_но_ни_на_что_не_влияют(self):
        out = self._run([{"params": {"ROOM_UPPER_OFFSET": 3493.7421314280423},
                          "bbox_min_mm": [0, 0, 0],
                          "bbox_max_mm": [0, 0, 3493.7421314280423]}])
        self.assertEqual(out["fractional_count"], 1)
        self.assertEqual(out["authored"], 1)
        self.assertEqual(out["agree_within_1mm"], 1,
                         "некруглое значение судится ровно как круглое")

    def test_объявленный_ноль_не_попадает_ни_в_согласие_ни_в_расхождение(self):
        out = self._run([{"params": {"ROOM_UPPER_OFFSET": 0.0},
                          "bbox_min_mm": [0, 0, 0], "bbox_max_mm": [0, 0, 3000.0]}])
        self.assertEqual(out["authored_zero"], 1)
        self.assertEqual((out["agree_within_1mm"], out["disagree"]), (0, 0))


class ПричинаНазываетМеханизмАНеИсход(unittest.TestCase):

    def test_подстановка_объясняет_почему_вердикт_мягче(self):
        text = describe("room_bbox")
        self.assertIn("ПОДСТАВЛЕНА", text)
        self.assertIn("room_bbox", text)

    def test_прочитанное_называет_свой_источник(self):
        self.assertIn("room_upper_offset", describe("room_upper_offset"))


if __name__ == "__main__":
    unittest.main()
