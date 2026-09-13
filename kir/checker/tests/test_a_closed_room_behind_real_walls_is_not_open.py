"""A CLOSED ROOM BEHIND REAL WALLS IS NOT "OPEN" (HAB042, 11.09.2026).

🔴 THE WALL WAS AN AXIS, THE ROOM BOUNDARY IS A FACE. HAB042 covered the
apartment perimeter with a ±50 mm strip around each wall's CENTERLINE
(`LineString(wall.curve).buffer(thr.wall_snap_tol_mm)`). A Revit room
boundary, however, runs along the wall FACE — half a thickness away from the
axis. Native witness 2026-09-09 (`kir-live-20260909/native-spatial-checker.json`,
BatchH1 `native_spatial_checker_extractor`): four walls at x=0/10000, y=0/8000,
room boundary at 100…9890 × 110…7900, area 76.26 m² as Revit computed it —
and the rule answered

    apartment apt:18565 envelope is open: only 2% of its perimeter is enclosed

BLOCKING, on a room Revit itself had closed. Raising the global snap would
have been a number nobody measured (the same disease as F-253); the fix is
DATA: `Wall.thickness_mm` (three-state, like `is_structural`), read by the
producers (`extractor.cs` — `Wall.Width`; `design_check` — `WALL_ATTR_WIDTH_PARAM`),
and a cover that reaches `snap + thickness / 2` from the axis, DIRECTION-aware
(both wall ends collinear with the edge), spans merged per edge.

What this file holds: the witness itself, literally, in both checker levers;
the two halves of the fix (with thickness → silent; without → fires AND names
the unknown thickness); a FAIL control (a wall really missing still fires);
the F-253 direction property on the new measure; and the three producers.
"""
from __future__ import annotations

import copy
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from kir.checker import engine
from kir.checker.extractor import normalize
from kir.checker.rules.clash import _apartment_envelope_coverage, _envelope_coverage_detail
from kir.checker.spatial_model import SpatialModel, Wall
from kir.checker.thresholds import THRESHOLDS

#: The native witness, verbatim from `native-spatial-checker.json` (key "0",
#: `normalized`), minus nothing that HAB042 reads. Four enclosing walls, one
#: stray wall 15 m away, one exterior door and one window on wall 2821, a
#: stair far outside the room. No `thickness_mm`: the extractor of 2026-09-09
#: did not read `Wall.Width`, and that absence is exactly the witness.
СВИДЕТЕЛЬ = {
    "building_id": "fixture",
    "levels": [
        {"id": "1959", "name": "Level 1", "elevation_mm": 0.0, "index": 0},
        {"id": "2797", "name": "APS_L0", "elevation_mm": 0.0, "index": 1},
        {"id": "2798", "name": "APS_L1", "elevation_mm": 3300.0, "index": 2},
        {"id": "2799", "name": "APS_L2", "elevation_mm": 6600.0, "index": 3},
    ],
    "rooms": [{
        "id": "18565", "name": "APS Living Room APS101", "number": "APS101",
        "level_id": "2797", "function": "прочее", "area_m2": 76.26, "height_mm": 3300.0,
        "boundary": [[100.0, 110.0], [9890.0, 110.0], [9890.0, 7900.0], [100.0, 7900.0]],
        "boundary_holes": [], "apartment_id": None, "has_window": True,
        "window_area_m2": 1.8, "height_source": None, "function_source": "room_name",
        "separator_ids": [],
    }],
    "doors": [{
        "id": "18569", "level_id": "2797", "location": [5000.0, 0.0], "width_mm": 900.0,
        "from_room_id": None, "to_room_id": "18565", "is_exterior": True,
        "host_wall_id": "2821",
    }],
    "windows": [{
        "id": "18567", "level_id": "2797", "host_wall_id": "2821", "room_id": "18565",
        "width_mm": 1200.0, "area_m2": 1.8, "height_mm": 1500.0,
        "location": [2000.0, 0.0], "area_source": "declared",
    }],
    "stairs": [{
        "id": "2856", "base_level_id": "2797", "top_level_id": "2798", "base_z": 0.0,
        "top_z": 3364.3, "run_width_mm": 1000.0, "riser_count": 19, "tread_depth_mm": 280.0,
        "footprint": [[30000.0, -550.0], [35050.0, -550.0], [35050.0, 550.0], [30000.0, 550.0]],
        "kind": "element", "top_level_source": "declared",
    }],
    "walls": [
        {"id": "2821", "level_id": "2797", "curve": [[0.0, 0.0], [10000.0, 0.0]],
         "height_mm": 3300.0, "is_structural": False},
        {"id": "2822", "level_id": "2797", "curve": [[10000.0, 0.0], [10000.0, 8000.0]],
         "height_mm": 3300.0, "is_structural": False},
        {"id": "2823", "level_id": "2797", "curve": [[10000.0, 8000.0], [0.0, 8000.0]],
         "height_mm": 3300.0, "is_structural": False},
        {"id": "2824", "level_id": "2797", "curve": [[0.0, 8000.0], [0.0, 0.0]],
         "height_mm": 3300.0, "is_structural": False},
        {"id": "2825", "level_id": "2797", "curve": [[15000.0, 0.0], [25000.0, 0.0]],
         "height_mm": 6000.0, "is_structural": False},
    ],
}
ОГРАЖДАЮЩИЕ = ("2821", "2822", "2823", "2824")
КВАРТИРА = "apt:18565"


def _модель(thickness_mm: float | None, *, без_стены: str | None = None) -> SpatialModel:
    данные = copy.deepcopy(СВИДЕТЕЛЬ)
    for wall in данные["walls"]:
        if thickness_mm is not None and wall["id"] in ОГРАЖДАЮЩИЕ:
            wall["thickness_mm"] = thickness_mm
    if без_стены is not None:
        данные["walls"] = [w for w in данные["walls"] if w["id"] != без_стены]
    return SpatialModel.model_validate(данные)


def _hab042(model: SpatialModel, v2: str) -> list:
    with mock.patch.dict(os.environ, {"KIR_CHECKER_V2": v2}):
        report = engine.run(model)
    return [v for v in report.blocking + report.warnings + report.info if v.rule_id == "HAB042"]


class ЗамкнутоеПомещениеЗаНастоящимиСтенами(unittest.TestCase):

    def test_СВИДЕТЕЛЬ_с_толщиной_стен_HAB042_молчит_в_обоих_рычагах(self):
        """THE MAIN CASE. Revit closed the room; with the walls' thickness known
        the rule agrees, on v2 (where it used to BLOCK) and on v1."""
        model = _модель(200.0)
        for v2 in ("1", "0"):
            with self.subTest(v2=v2):
                self.assertEqual(_hab042(model, v2), [],
                                 "закрытое помещение признано открытым")

    def test_покрытие_свидетеля_с_толщиной_полное(self):
        coverage, walls, unknown = _envelope_coverage_detail(
            _модель(200.0), КВАРТИРА, THRESHOLDS, room_ids={"18565"})
        self.assertAlmostEqual(coverage, 1.0, places=6)
        self.assertEqual((walls, unknown), (5, 1), "the stray wall 2825 keeps NO thickness")

    def test_БЕЗ_толщины_правило_СРАБАТЫВАЕТ_и_называет_источник(self):
        """🔴 THE MEASUREMENT INSIDE THE GUARD: the case was chosen for the subject.
        Without thickness the cover reaches the snap only (the old number) and
        the witness still reads ~2 % — but now the verdict SAYS why."""
        coverage, walls, unknown = _envelope_coverage_detail(
            _модель(None), КВАРТИРА, THRESHOLDS, room_ids={"18565"})
        self.assertLess(coverage, THRESHOLDS.min_envelope_coverage_ratio)
        self.assertEqual((walls, unknown), (5, 5))
        hits = _hab042(_модель(None), "1")
        self.assertEqual([v.rule_id for v in hits], ["HAB042"])
        self.assertIn("wall thickness unknown for 5 of 5 walls", hits[0].msg)

    def test_КОНТРОЛЬ_настоящая_дыра_с_толщиной_всё_равно_срабатывает(self):
        """Without it the fix is indistinguishable from "HAB042 never fires again".

        One side removed: 3 of 4 sides ≈ 0.72 of the perimeter — the missing
        side is MEASURED, but the rule's floor is "substantial enclosure"
        (0.10), so the verdict stays silent by design. Strip all four enclosing
        walls (the stray one keeps a known thickness) and the rule itself fires,
        with NO "thickness unknown" note — the source is the building, not the read.
        """
        one_side_gone = _модель(200.0, без_стены="2823")          # the north wall
        coverage, _walls, unknown = _envelope_coverage_detail(
            one_side_gone, КВАРТИРА, THRESHOLDS, room_ids={"18565"})
        self.assertLess(coverage, 0.80)
        self.assertGreater(coverage, 0.65)
        self.assertEqual(unknown, 1)                                # the stray 2825 only

        данные = copy.deepcopy(СВИДЕТЕЛЬ)
        данные["walls"] = [dict(w, thickness_mm=200.0) for w in данные["walls"]
                           if w["id"] == "2825"]                  # the stray wall only
        stripped = SpatialModel.model_validate(данные)
        coverage, walls, unknown = _envelope_coverage_detail(
            stripped, КВАРТИРА, THRESHOLDS, room_ids={"18565"})
        self.assertEqual((walls, unknown), (1, 0))
        self.assertLess(coverage, THRESHOLDS.min_envelope_coverage_ratio)   # the door's chord alone
        hits = _hab042(stripped, "1")
        self.assertEqual([v.rule_id for v in hits], ["HAB042"])
        self.assertNotIn("thickness unknown", hits[0].msg)

    def test_толщина_НЕ_добавляется_к_допуску_у_стены_без_толщины(self):
        """The reach is per WALL: a wall read without thickness does not borrow
        its neighbour's. Give thickness to three sides only — the fourth stays
        uncovered and the count says 2 (the fourth side and the stray wall)."""
        данные = copy.deepcopy(СВИДЕТЕЛЬ)
        for wall in данные["walls"]:
            if wall["id"] in ("2821", "2822", "2823"):
                wall["thickness_mm"] = 200.0
        model = SpatialModel.model_validate(данные)
        coverage, walls, unknown = _envelope_coverage_detail(
            model, КВАРТИРА, THRESHOLDS, room_ids={"18565"})
        self.assertEqual((walls, unknown), (5, 2))
        self.assertLess(coverage, 1.0)
        self.assertGreater(coverage, 0.70)


class НаправлениеАНеДлина(unittest.TestCase):
    """The F-253 law on the new measure: a wall crossing the perimeter at a right
    angle is NOT cover, however long; a wall along the edge is."""

    def _room(self, walls):
        данные = copy.deepcopy(СВИДЕТЕЛЬ)
        данные["doors"], данные["windows"], данные["stairs"] = [], [], []
        данные["walls"] = walls
        return SpatialModel.model_validate(данные)

    def test_перпендикуляр_сквозь_периметр_НЕ_покрывает_ничего(self):
        wall = {"id": "x", "level_id": "2797", "curve": [[5000.0, -3000.0], [5000.0, 3000.0]],
                "height_mm": 3000.0, "thickness_mm": 200.0}
        model = self._room([wall])
        self.assertEqual(_apartment_envelope_coverage(model, КВАРТИРА, THRESHOLDS,
                                                       room_ids={"18565"}), 0.0)

    def test_стена_вдоль_ребра_покрывает_ровно_своё_перекрытие(self):
        wall = {"id": "s", "level_id": "2797", "curve": [[2000.0, 0.0], [6000.0, 0.0]],
                "height_mm": 3000.0, "thickness_mm": 220.0}     # face at y=110
        model = self._room([wall])
        perimeter = 2 * (9790.0 + 7790.0)
        self.assertAlmostEqual(
            _apartment_envelope_coverage(model, КВАРТИРА, THRESHOLDS, room_ids={"18565"}),
            4000.0 / perimeter, places=6)

    def test_дверь_и_стена_на_одном_участке_считаются_ОДИН_раз(self):
        """Merged spans: a door over a wall must not push coverage past what the
        edge has. The full witness with thickness reads exactly 1.0, never more."""
        coverage = _apartment_envelope_coverage(_модель(200.0), КВАРТИРА, THRESHOLDS,
                                                room_ids={"18565"})
        self.assertLessEqual(coverage, 1.0)
        self.assertAlmostEqual(coverage, 1.0, places=6)


class ТриПроизводителяТолщины(unittest.TestCase):

    def test_модель_стены_три_состояния(self):
        base = dict(id="w", level_id="L", curve=((0.0, 0.0), (1.0, 0.0)), height_mm=1.0)
        self.assertIsNone(Wall(**base).thickness_mm)
        self.assertEqual(Wall(**base, thickness_mm=0.0).thickness_mm, 0.0)
        self.assertEqual(Wall(**base, thickness_mm=250.5).thickness_mm, 250.5)
        with self.assertRaises(ValueError):
            Wall(**base, thickness_mm=-1.0)

    def test_extractor_cs_читает_Wall_Width_в_мм(self):
        text = (Path(__file__).resolve().parents[1] / "extractor.cs").read_text(encoding="utf-8")
        walls = text.split("// --- walls", 1)[1]
        self.assertIn('{"thickness_mm", Math.Round(wl.Width * FT, 1)}', walls)

    def test_normalize_проносит_толщину_в_модель_и_её_отсутствие_тоже(self):
        raw = copy.deepcopy(СВИДЕТЕЛЬ)
        raw["walls"][0]["thickness_mm"] = 200.0
        for v2 in ("0", "1"):
            with mock.patch.dict(os.environ, {"KIR_CHECKER_V2": v2}):
                model = SpatialModel.model_validate(normalize(raw))
            by_id = {w.id: w for w in model.walls}
            self.assertEqual(by_id["2821"].thickness_mm, 200.0)
            self.assertIsNone(by_id["2822"].thickness_mm)

    def test_design_check_читает_WALL_ATTR_WIDTH_PARAM_или_молчит(self):
        from kir.design_check import _thickness_mm
        self.assertEqual(_thickness_mm(SimpleNamespace(params={"WALL_ATTR_WIDTH_PARAM": 200.0})), 200.0)
        self.assertEqual(_thickness_mm(SimpleNamespace(params={"WALL_ATTR_WIDTH_PARAM": 300})), 300.0)
        self.assertIsNone(_thickness_mm(SimpleNamespace(params={})))
        self.assertIsNone(_thickness_mm(SimpleNamespace(params=None)))
        self.assertIsNone(_thickness_mm(SimpleNamespace(params={"WALL_ATTR_WIDTH_PARAM": ""})))
        self.assertIsNone(_thickness_mm(SimpleNamespace(params={"WALL_ATTR_WIDTH_PARAM": True})))
        self.assertIsNone(_thickness_mm(SimpleNamespace(params={"WALL_ATTR_WIDTH_PARAM": float("nan")})))
        self.assertIsNone(_thickness_mm(SimpleNamespace(params={"WALL_ATTR_WIDTH_PARAM": -5.0})))
        self.assertIsNone(_thickness_mm(SimpleNamespace()))


if __name__ == "__main__":
    unittest.main()
