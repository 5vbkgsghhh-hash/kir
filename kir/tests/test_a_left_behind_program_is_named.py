"""HALF THE HOUSE WAS DISAPPEARING SILENTLY: THE DOOR BUILDS ONLY THE SCRIPT'S LAST PROGRAM.

🔴 MEASURED ON LIVE REVIT ON 03.09.2026. Our own "housing" recipe is
written as TWO programs — that is what `KIR-L002` requires, and the recipe
explains this itself: "the staircase owns its own transactions and lives
in a separate program." Through the live door, only the SECOND was built;
the staircase disappeared without a refusal, without a line, and without a
field. The judge then honestly printed

    HAB011: лестниц в представлении НЕТ ВОВСЕ: `create_stairs` не вызван ни разу

— and sent the author off to fix the program in which the call IS present.
Three housing rules (HAB001, HAB010, HAB012) stayed silent for the same
reason, that is, the "13 rules out of 20" promised by the recipe were
unreachable: live, it came out to 11.

WHAT IS EXECUTED DOES NOT CHANGE HERE. One program per turn is a decision
about transactions, and it is not this file's business. What is named is
the LOSS — by the same law as `verdict_silent_because` and the reading
ledger: silence about what was left behind is indistinguishable from "the
author left nothing behind."

AFTER THE FIX, LIVE: the receipt says «ПОСТРОЕНА ТОЛЬКО ПОСЛЕДНЯЯ ПРОГРАММА
СКРИПТА. Оставлено 1: «судимое жильё: лестница» (1 оп)», the author sends
the staircase as a separate turn — and the judge gives 13 rules out of 20,
exactly the promised number.

🔴 THE INSTRUMENT NEARLY COUNTED ITS OWN TURN. The accounting is taken
BEFORE the program is collected: the collection itself goes through
`take_ops()`, and that starts a new program, so after collection the
accounting would hold the CURRENT program — the very one the door is in
the middle of building. The first draft declared "left behind: 1" on a
single-program script.
"""
from __future__ import annotations

import unittest

from kir import dsl, sandbox, serving


class ЯзыкСчитаетОставленное(unittest.TestCase):

    def setUp(self) -> None:
        dsl.forget_left_behind()
        dsl.reset()
        dsl.forget_left_behind()

    def tearDown(self) -> None:
        dsl.forget_left_behind()
        dsl.reset()
        dsl.forget_left_behind()

    def test_программа_с_операциями_уходит_в_учёт(self) -> None:
        dsl.envelope(intent="лестница")
        dsl.create_level(name="A", elev_mm=0)
        dsl.reset(intent="тело")
        self.assertEqual(dsl.left_behind(),
                         ({"intent": "лестница", "ops": 1},))

    def test_пустая_программа_в_учёт_не_идёт(self) -> None:
        """An author who started over lost nothing — and should not be
        told otherwise: a false positive here costs more than silence."""
        dsl.envelope(intent="черновик")
        dsl.reset(intent="тело")
        self.assertEqual(dsl.left_behind(), ())


class ПесочницаНесётУчёт(unittest.TestCase):

    def test_две_программы_оставляют_одну(self) -> None:
        r = sandbox.execute_author_script(
            'envelope(intent="лестница")\n'
            'create_level(name="A", elev_mm=0)\n'
            'p1 = build()\n'
            'reset(intent="тело")\n'
            'create_level(name="B", elev_mm=3000)\n')
        self.assertTrue(r.ok, "скрипт обязан исполниться")
        self.assertEqual(len(r.ops or ()), 1, "строится ПОСЛЕДНЯЯ программа")
        self.assertEqual(
            [dict(item) for item in r.left_behind],
            [{"intent": "лестница", "ops": 1}],
            "оставленная программа обязана быть названа")

    def test_одна_программа_ничего_не_оставляет(self) -> None:
        """A CONTROL IN THE OTHER DIRECTION: collection is not counted as a loss."""
        r = sandbox.execute_author_script('create_level(name="A", elev_mm=0)\n')
        self.assertTrue(r.ok)
        self.assertEqual(list(r.left_behind), [],
                         "прибор посчитал СВОЙ ЖЕ ход: `take_ops()` начинает "
                         "новую программу, и снимать учёт надо ДО сбора")


class КвитанцияНазываетПотерю(unittest.TestCase):

    class _Итог:
        author_digest = "x"
        ops = [{"op": "create_wall", "id": "w1"}]
        duration_s = 0.0
        isolation: dict = {}
        environment: dict = {}
        params: list = []
        stdout = ""
        course_reads: list = []
        program_digest = ""
        left_behind = [{"intent": "лестница", "ops": 3}]

    def test_строка_называет_замысел_и_число(self) -> None:
        блок = serving._authorship_receipt(self._Итог(), source_bytes=10)
        self.assertEqual(блок["left_behind"], [{"intent": "лестница", "ops": 3}])
        строка = блок["left_behind_note_ru"]
        self.assertIn("лестница", строка)
        self.assertIn("3 оп", строка)
        self.assertIn("отдельным ходом", строка,
                      "строка обязана называть СЛЕДУЮЩИЙ ХОД, а не только беду")

    def test_пусто_остаётся_отсутствием(self) -> None:
        итог = self._Итог()
        итог.left_behind = []
        блок = serving._authorship_receipt(итог, source_bytes=10)
        self.assertNotIn("left_behind", блок)
        self.assertNotIn("left_behind_note_ru", блок)


if __name__ == "__main__":
    unittest.main()
