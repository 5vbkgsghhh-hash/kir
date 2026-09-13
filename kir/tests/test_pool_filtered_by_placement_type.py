"""THE POOL RETURNED 320 CANDIDATES, NOT ONE OF WHICH WAS VALID.

🔴 WHY (24.08.2026, LIVE MEASUREMENT, «Проект1», Revit 2026).

`placement_type` has been reaching Python since 24.08 (`8b3e5f64` — capture,
and a same-evening profile fix — a round trip). There was NOWHERE to filter
by it. Live, it looked like this:

    create_adaptive_component symbol={"by":"default"}
    -> KIR-G102 «family_symbols: 320 вариантов — default невозможен,
       уточните через element_id»
       candidates: curtain wall mullions, callouts, railing supports;
       placement_type for all of them is ViewBased / OneLevelBased

The refusal called for enumerating 320 names. The correct answer is —
«адаптивных в модели НЕТ, перебирать нечего, загрузи семейство»: this is a
DIFFERENT next turn, and the difference between them is a whole loop
iteration, if not ten.

THE DECISION BELONGS TO THE REGISTRY (`registry_base.PLACEMENT_TYPES_REQUIRED`),
and exactly one entry is written into it — the one where WE have no choice:
`AdaptiveComponentInstanceUtils.CreateAdaptiveComponentInstance` requires an
adaptive family, that is an API fact. Pools where several kinds are
admissible (`place_family`: 26.0 % of corpus instances are invalid) are
deliberately not entered — their composition is decided by the registry's
owner, not by this fix.
"""
from __future__ import annotations

import unittest

from kir.ground import _pool_for_placement
from kir.registry_base import PLACEMENT_TYPES_REQUIRED

НЕГОДНЫЕ = [{"id": 1, "name": "Импост", "placement_type": "OneLevelBased"},
            {"id": 2, "name": "Выноска", "placement_type": "ViewBased"}]
ГОДНЫЙ = {"id": 3, "name": "Панель", "placement_type": "Adaptive"}


class ТриИсходаРАЗЛИЧАЮТСЯ(unittest.TestCase):

    def test_годные_есть_остаются_только_они(self):
        diags: list = []
        got = _pool_for_placement("create_adaptive_component", "symbol",
                                  НЕГОДНЫЕ + [ГОДНЫЙ], 0, "AC", diags)
        self.assertEqual(got, [ГОДНЫЙ])
        self.assertEqual(diags, [])

    def test_годных_НОЛЬ_отказ_называет_И_нужное_И_найденное(self):
        """🔴 RED before the fix: the whole pool leaked through, the refusal called for enumerating."""
        diags: list = []
        self.assertIsNone(_pool_for_placement(
            "create_adaptive_component", "symbol", НЕГОДНЫЕ, 0, "AC", diags))
        текст = diags[0].message_ru
        self.assertIn("Adaptive", текст)
        self.assertIn("OneLevelBased", текст)
        self.assertIn("ViewBased", текст)
        self.assertIn("load_family", текст)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", текст)

    def test_КОНТРОЛЬ_оп_без_требования_НЕ_ТРОГАЕТСЯ(self):
        """The fix has no right to narrow pools for which no decision has been made."""
        diags: list = []
        got = _pool_for_placement("create_beam", "symbol", НЕГОДНЫЕ,
                                  0, "B", diags)
        self.assertEqual(got, НЕГОДНЫЕ)
        self.assertEqual(diags, [])

    def test_КОНТРОЛЬ_пустой_пул_отдаётся_общему_правилу(self):
        """«В модели ничего нет» is a DIFFERENT fact, and a different refusal states it."""
        diags: list = []
        self.assertEqual(
            _pool_for_placement("create_adaptive_component", "symbol", [],
                                0, "AC", diags), [])
        self.assertEqual(diags, [])


class НепрочитанныйПризнакНЕ_ЕСТЬ_НЕГОДНОСТЬ(unittest.TestCase):

    def test_строка_без_признака_считается_ГОДНОЙ(self):
        """Discarding it would turn the instrument's refusal into a fact about the model.

        Same law as with `_candidate_rows`: "not read" and "read, and
        here's what's there" must be distinguished.
        """
        diags: list = []
        без = [{"id": 4, "name": "Без признака"}]
        self.assertEqual(
            _pool_for_placement("create_adaptive_component", "symbol", без,
                                0, "AC", diags), без)
        self.assertEqual(diags, [])

    def test_unreadable_тоже_НЕ_отбрасывается(self):
        """C# writes "unreadable" when a property fails to read.

        🔴 THE FIRST VERSION OF THIS TEST PINNED THE DEFECT (form 52, bought
        the same day): it required such a line to be DISCARDED — that is,
        for our blindness to become an assertion about the model.
        `Family.FamilyPlacementType` throws for part of the system
        families, and `"unreadable"` is written PRECISELY to distinguish
        "read it, and here's what's there" from "couldn't".
        """
        diags: list = []
        строки = [{"id": 5, "name": "X", "placement_type": "unreadable"}]
        self.assertEqual(
            _pool_for_placement("create_adaptive_component", "symbol",
                                строки, 0, "AC", diags), строки)
        self.assertEqual(diags, [])

    def test_отказ_НЕ_поминает_unreadable_как_встреченный_род(self):
        """«Встретились: unreadable» would read as a placement kind."""
        diags: list = []
        смесь = НЕГОДНЫЕ + [{"id": 6, "name": "Y",
                             "placement_type": "unreadable"}]
        got = _pool_for_placement("create_adaptive_component", "symbol",
                                  смесь, 0, "AC", diags)
        self.assertEqual(got, [{"id": 6, "name": "Y",
                                "placement_type": "unreadable"}])
        self.assertEqual(diags, [], "непрочитанная строка спасает от отказа")


class РешениеЖивётВРЕЕСТРЕ(unittest.TestCase):

    def test_таблица_закрыта_и_НЕ_ПОЛНА_и_это_сказано(self):
        self.assertEqual(
            PLACEMENT_TYPES_REQUIRED,
            {("create_adaptive_component", "symbol"): frozenset({"Adaptive"})},
            "новый вход — решение владельца реестра, а не правка ground.py")


if __name__ == "__main__":
    unittest.main()
