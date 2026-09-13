"""DEBT F-334 WAS CLOSED ON 01.09.2026 BY FLIPPING THE DEFAULT — AND CLOSED, NOT SILENTLY.

🔴 READ THIS FIRST. This file used to hold a DEBT: under the package's
default, the rule was certifying constants that it had substituted itself.
The `KIR_CHECKER_V2` default was switched to "1" by the owner's word on
01.09.2026, and the v1 half turned red exactly as promised below in this very
file. The record was retired by the order this same file prescribed, not by
a silent edit of the expectation.

WHAT CHANGED, IN ONE LINE: the harm remained POSSIBLE, but stopped being the
DEFAULT. It now only reaches whoever EXPLICITLY asks for v1
(`KIR_CHECKER_V2=0`). 901 synthetic flights across 18 buildings are no longer
judged by the invented 1100/17/280, not for production (which was already on
v2 via `.env` anyway), and not for a reader of the package — who, before this
fix, was getting exactly those numbers.

Below is the FULL prior record of the debt, and it is left in place on
purpose: it is evidence of what the debt was and how its harm was measured.
Both outcomes of the two levers are still presented here, by the numbers.

────────────────────────────────────────────────────────────────────────────
PRIOR RECORD (true in its time): UNDER THE PACKAGE'S DEFAULT, THE RULE
CERTIFIES CONSTANTS THAT IT SUBSTITUTED ITSELF (F-334) — A DEBT PINNED BY A
NUMBER.

🔴 THIS FILE FIXES NOTHING AND HAS NO RIGHT TO FIX ANYTHING. Editing checker
v1 is forbidden by the owner's decision, and flipping the `KIR_CHECKER_V2`
default is likewise the owner's decision, not the executor's. The cure is
BUILT IN FULL and stands green under v2; what is held here is exactly what
can be held: THE DIFFERENCE BETWEEN THE TWO LEVERS, named by a number.

THE HARM. For aligned stair landings with not a single extracted stair
element, v1 synthesizes a connection and substitutes `run_width_mm=1100`,
`riser_count=17`, `tread_depth_mm=280`. HAB011 takes these for the element's
own parameters and FINDS NO VIOLATIONS — that is, the rule certifies
constants that we ourselves substituted. The rise is computed as
`(top_z - base_z) / riser_count` = 3000/17 ≈ 176.5 mm, and 17 is chosen so
that, for a typical 3 m floor, the result is knowingly below the maximum: the
threshold CANNOT be violated, because the divisor was chosen by us. The miss
runs in one direction — the building looks more fit than it is.

🔴 MY MEASUREMENT ACROSS THE CORPUS (30.08.2026, FULL denominator):

    catalogs 91 · with an L0 stream (including .gz) 81 · read failures 0
    buildings with rooms and levels 37
    SYNTHETIC flights 901 across 18 buildings
    of which with the invented 1100/17/280 — ALL 901

🔴 AND THE DENOMINATOR HERE WAS BOUGHT WITH A MISTAKE. My first run used
`glob("*/L0.jsonl")` and saw 44 parses out of 81: the cooled-down ones sit
compressed (`L0.jsonl.gz`, 37 of them) and were invisible BY CONSTRUCTION —
the same blindness to `.gz` already caught in S-01 and in `journal_store`.
With the full denominator the number rose 898 -> 901 and 17 -> 18 buildings.
Existence should be asked of `snapshot_file_exists`, not of a file name.

BOTH OUTCOMES ARE PRESENTED HERE, AND THAT IS THE WHOLE FILE:

    v1 (default)  width=1100 risers=17 tread=280  kind=None      HAB011 STAYS SILENT
    v2            width=None risers=None tread=None kind=inferred HAB011 SPEAKS

🔴 WHY THIS IS NOT ENSHRINING THE DEFECT. An instrument that simply asserts
"v1 substitutes 1100" would indeed be cementing it in place. The assertion
here is DIFFERENT: "v1 substitutes, v2 does not, and this is a DEBT." When
the default is flipped, the v1 half will TURN RED and demand the record be
removed — that is, the debt cannot close silently, exactly like
`ЦЕЛЬ_МОЛЧИТ` in `test_a_fixture_breaks_what_it_says`. Silently closing a
debt and silently extending it are equally forbidden.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from kir.checker.extractor import normalize
from kir.checker.flags import checker_v2_enabled
from kir.checker.graph import build_graph
from kir.checker.rules import vertical
from kir.checker.spatial_model import SpatialModel
from kir.checker.thresholds import Thresholds

#: The constants that v1 substitutes in place of a measurement. Not the
#: test's "magic numbers": this is a DEBT, recorded by name, and its closing
#: is obligated to be noticeable.
ВЫДУМАННЫЕ = {"run_width_mm": 1100.0, "riser_count": 17, "tread_depth_mm": 280.0}

#: Measured 30.08.2026 across the FULL corpus (81 parses, `.gz` included).
ПРОЛЁТОВ_НА_КОРПУСЕ = 901
ЗДАНИЙ_НА_КОРПУСЕ = 18


def _кв(x, y, s=3000):
    return [[x, y], [x + s, y], [x + s, y + s], [x, y + s]]


СЫРОЕ = {
    "building_id": "b",
    "levels": [{"id": f"L{i}", "name": f"L{i}", "elevation_mm": 3000.0 * i,
                "index": i} for i in range(2)],
    "rooms": [{"id": "a1", "name": "Лестница", "level_id": "L0",
               "area_m2": 9.0, "boundary": _кв(0, 0)},
              {"id": "a2", "name": "Лестница", "level_id": "L1",
               "area_m2": 9.0, "boundary": _кв(0, 0)}],
    "doors": [], "windows": [], "stairs": [], "walls": [],
}


def _под(рычаг: str):
    with mock.patch.dict(os.environ, {"KIR_CHECKER_V2": рычаг}):
        n = normalize(СЫРОЕ)
        синт = [s for s in n["stairs"] if str(s["id"]).startswith("synth_")]
        m = SpatialModel.model_validate(n)
        находки = vertical.check_hab011(m, build_graph(m), Thresholds())
    return синт, находки


class V1УдостоверяетСвоиЖеКонстанты(unittest.TestCase):

    def test_ДОЛГ_БОЛЬШЕ_НЕ_УМОЛЧАНИЕ(self):
        """The F-334 harm reaches only whoever EXPLICITLY asks for v1.

        🔴 THIS IS NOT A DUPLICATE OF `test_the_judge_speaks_by_default`. That
        one guards the lever's MECHANICS (a silent environment, a rollback, an
        alias). What is guarded here is the DEBT'S REACH: with a silent
        environment, the invented constants never reach the rule at all. Two
        different quantities, and merging them into one assertion would strip
        the debt of its own number.

        Before 01.09.2026 the reverse stood here —
        `умолчание_пакета_ВСЁ_ЕЩЁ_v1` — and it turned red the very hour the
        default was flipped. That was by design: silently closing a debt and
        silently extending it are equally forbidden.
        """
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("KIR_CHECKER_V2", None)
            os.environ.pop("KUKAI_CHECKER_V2", None)
            self.assertTrue(
                checker_v2_enabled(),
                "умолчание вернулось на v1 — значит ДОЛГ F-334 СНОВА достаётся "
                "каждому, кто ничего не настраивал: 901 синтетический пролёт на "
                "18 зданиях опять судится выдуманными 1100/17/280. Верни "
                "умолчание «1» либо переоткрой запись в реестре")

    def test_ДОЛГ_v1_подставляет_и_правило_молчит(self):
        синт, находки = _под("0")
        self.assertEqual(len(синт), 1, "синтез не сработал — вход не тот")
        for поле, значение in ВЫДУМАННЫЕ.items():
            with self.subTest(поле=поле):
                self.assertEqual(синт[0][поле], значение,
                                 "константа изменилась: долг описан неверно")
        self.assertIsNone(синт[0].get("kind"),
                          "v1 стал называть род связи — долг сдвинулся")
        self.assertEqual(
            [x.msg for x in находки], [],
            "HAB011 заговорил под v1 — долг ЗАКРЫТ, обнови запись")

    def test_ЛЕЧЕНИЕ_v2_не_выдумывает_и_правило_говорит(self):
        """The second half, and it carries the argument for the owner: the
        cure does not need to be written, it is already built and green."""
        синт, находки = _под("1")
        self.assertEqual(len(синт), 1)
        for поле in ВЫДУМАННЫЕ:
            with self.subTest(поле=поле):
                self.assertIsNone(синт[0][поле],
                                  "v2 подставляет размер — лечение сломано")
        self.assertEqual(синт[0].get("kind"), "inferred",
                         "провенанс связи под v2 потерян")
        self.assertTrue(находки, "HAB011 под v2 замолчал — лечение сломано")
        self.assertIn("INFERRED", находки[0].msg)

    def test_подъём_под_v1_НЕ_МОЖЕТ_нарушить_порог(self):
        """🔴 WHY THIS IS NOT JUST AN "IMPRECISE NUMBER." The divisor was
        chosen by us so that the result knowingly passes: the rule checks
        ITSELF."""
        синт, _ = _под("0")
        s = синт[0]
        подъём = (s["top_z"] - s["base_z"]) / s["riser_count"]
        thr = Thresholds()
        максимум = getattr(thr, "stair_max_rise_mm", None)
        self.assertIsNotNone(максимум, "порог подъёма исчез из Thresholds")
        self.assertLess(подъём, максимум,
                        "подъём перестал быть заведомо проходным — долг "
                        "изменил форму, пересними замер")

    def test_замер_корпуса_записан_числом(self):
        """The number is part of the debt's record, not prose. It stands
        here so it cannot be lost while editing the docstring."""
        self.assertEqual(ПРОЛЁТОВ_НА_КОРПУСЕ, 901)
        self.assertEqual(ЗДАНИЙ_НА_КОРПУСЕ, 18)
        self.assertGreater(ПРОЛЁТОВ_НА_КОРПУСЕ, 0,
                           "долг с нулевым охватом записывать незачем")


if __name__ == "__main__":
    unittest.main()
