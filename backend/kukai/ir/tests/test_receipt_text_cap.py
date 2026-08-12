"""ПОТОЛОК, НАЗВАННЫЙ ПОЛЕМ, А МЕРЯЮЩИЙ ЕГО ПОЛОВИНУ.

ВОСПРОИЗВЕДЕНО (замер 11.08.2026, `/tmp/wiring/w2.py`, флаг включён):

    snowdon_plumb_v4  ВЕРДИКТ  359 <=2600 | КОЛЛИЗИИ 2504 <=2700
                      ПОЛЕ message_ru 2865  -> ПРЕВЫШАЕТ потолок вердикта
    sob62_r23_v5      ВЕРДИКТ  353 | КОЛЛИЗИИ 1362 | ПОЛЕ 1717  -> ok

`verdict._TEXT_CAP` назван «потолок текста КВИТАНЦИИ» и обрезает по нему
`_describe`, то есть ТОЛЬКО вердиктную половину. Дальше `_with_clash`
дописывает в ТО ЖЕ поле `message_ru` текст проверки на коллизии, у которого
свой потолок 2 700. Поле, названное потолком 2 600, в худшем случае несёт
2 600 + 2 700 = 5 300.

ЭТО ТА ЖЕ ФОРМА, ЧТО И ОСТАЛЬНЫЕ ЧЕТЫРЕ СЛУЧАЯ МАРАФОНА: величина заявлена
одним местом и прочитана другим, и ничто не заставляет их совпасть.
  * потолок с именем «число ТЕЛ», сравнивавший число ЭЛЕМЕНТОВ;
  * ключ кэша без `new_from`, потом без четырёх потолков;
  * `bundle_sha256`, никогда не содержавший отпечатка пачки;
  * и этот — потолок с именем поля, меряющий половину поля.

ЧЕГО ЗДЕСЬ НЕ ДЕЛАЕТСЯ. Не вводится общий обрез, режущий находки коллизий:
это вернуло бы ровно то, что чинилось волной бюджета — текст честности,
вытесняющий правду. Половины остаются со СВОИМИ потолками, а сумма получает
ИМЯ и замок, чтобы поле больше не было больше того, чем названо.
"""
from __future__ import annotations

import os
import unittest

from kukai.ir import clash_bundle as CB
from kukai.live import journal, verdict as V


def _ducts(n, step=45.0):
    return [{"op": "create_duct", "id": f"d{i}", "diameter_mm": 400.0,
             "p0_mm": [i * step, 0.0, 0.0], "p1_mm": [i * step, 6000.0, 0.0]}
            for i in range(n)]


class TheCapNamesTheHalfItMeasures(unittest.TestCase):

    KEY = ("test-receipt-text-cap", "")

    def setUp(self):
        journal.reset(self.KEY)
        self._prev = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()

    def tearDown(self):
        journal.reset(self.KEY)
        if self._prev is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()

    def _judged(self, programs=6, per=30):
        for _ in range(programs):
            journal.append(self.KEY, {"ops": _ducts(per)}, source="chat")
        return V.judge(self.KEY, since_seq=programs - 1)

    def test_the_verdict_cap_is_named_for_the_verdict(self):
        """Имя обязано называть измеряемое. `_TEXT_CAP` мерил половину поля
        и назывался потолком поля."""
        self.assertTrue(hasattr(V, "_VERDICT_TEXT_CAP"))
        self.assertFalse(hasattr(V, "_TEXT_CAP"),
                         "старое имя пережило переименование")

    def test_the_field_has_a_budget_of_its_own(self):
        """У поля, которое несёт две половины, обязан быть СВОЙ бюджет, и он
        обязан быть выведен из обеих, а не назначен."""
        self.assertEqual(V.RECEIPT_TEXT_BUDGET,
                         V._VERDICT_TEXT_CAP + CB._TEXT_CAP)

    def test_the_receipt_never_exceeds_the_budget_of_its_own_field(self):
        block = self._judged()
        self.assertLessEqual(len(block["message_ru"]), V.RECEIPT_TEXT_BUDGET)

    def test_each_half_still_keeps_its_own_ceiling(self):
        """Общий бюджет не отменяет половинных: иначе одна половина съедала
        бы другую, а это ровно то, от чего лечился бюджет квитанции."""
        block = self._judged()
        clash = (block.get("clash") or {}).get("message_ru", "")
        verdict_part = block["message_ru"][
            :len(block["message_ru"]) - len(clash)].rstrip()
        self.assertLessEqual(len(verdict_part), V._VERDICT_TEXT_CAP)
        self.assertLessEqual(len(clash), CB._TEXT_CAP)

    def test_the_sum_is_visible_and_not_only_asserted(self):
        """Величина, которую никто не видит, растёт молча — тот же довод, что
        у `text_budget` в блоке коллизий."""
        block = self._judged()
        self.assertIn("receipt_chars", block)
        self.assertEqual(block["receipt_chars"], len(block["message_ru"]))

    def test_without_clash_the_receipt_is_unchanged(self):
        """Правка не имеет права трогать вердикт без коллизий: половина без
        второй половины остаётся ровно тем, чем была."""
        os.environ.pop("KUKAI_IR_CLASH", None)
        CB._CACHE.clear()
        block = self._judged()
        self.assertNotIn("clash", block)
        self.assertLessEqual(len(block["message_ru"]), V._VERDICT_TEXT_CAP)


if __name__ == "__main__":
    unittest.main()
