"""БЮДЖЕТ НЕСНИМАЕМОЙ ЧАСТИ КВИТАНЦИИ — НАЗВАННОЕ ЧИСЛО С ЗАМКОМ.

ЧТО ЭТО ЧИНИТ (замер 11.08.2026, `snowdon_plumb_v4`, живая пересборка).
Квитанция состоит из двух частей, и они конкурируют за один потолок:

  * НЕСНИМАЕМАЯ — «вот чего я НЕ смотрел»: тел столько-то, без тела столько-то
    и почему, чего проверка не видит вовсе, какая у неё область;
  * НАХОДКИ — «вот что я нашёл».

Первая росла всю неделю и росла МОЛЧА:

    было при выборе потолка (шапка `_TEXT_CAP`)   1 043 симв.
    стало                                          1 600 симв.  (+53%)
    из них добавлено этой серией волн               586 симв.
        ЧЕГО ЭТА ПРОВЕРКА НЕ ВИДИТ ВООБЩЕ           298
        ВНЕСЛА ЭТА ПАЧКА                            185
        ИЗ НИХ ПО ПРИЧИНАМ                          103

Следствие замерено: при потолке 2 700 находкам оставалось 1 100 симв., то есть
3.3 суждения из обещанных пяти, и отчёт печатал «список суждений обрезан».
Это ТОТ ЖЕ отказ, что шапка `_TEXT_CAP` объявляет уже почёненным однажды:
«при прежних 1 100 список находок обрезался до НУЛЯ строк — квитанция говорила
"спор есть" и не показывала ни одного».

ЗАКОН, КОТОРЫЙ ЗДЕСЬ ЗАПИРАЕТСЯ: когда текст ЧЕСТНОСТИ вытесняет находки,
честность начинает стоить ПРАВДЫ. Поэтому неснимаемая часть получает
названный бюджет, а не растёт по факту: следующая честная строка обязана
ВЫНУДИТЬ решение — сжать, убрать другую строку или принести замер под
поднятие потолка, — а не съесть ещё одно суждение молча.

ПОТОЛОК ЗДЕСЬ НЕ ПОДНИМАЕТСЯ. Не потому что нельзя, а потому что замера
того, что модель реально платит за эти символы, у нас нет; поднятие
защитимо только вместе с ним.
"""
from __future__ import annotations

import os
import unittest

from kukai.ir import clash_bundle as CB


class _Flag:
    def __enter__(self):
        self._prev = os.environ.get("KUKAI_IR_CLASH")
        os.environ["KUKAI_IR_CLASH"] = "1"
        CB._CACHE.clear()
        return self

    def __exit__(self, *exc):
        if self._prev is None:
            os.environ.pop("KUKAI_IR_CLASH", None)
        else:
            os.environ["KUKAI_IR_CLASH"] = self._prev
        CB._CACHE.clear()
        return False


def _worst_case_pack():
    """Пачка, ВЫЖИМАЮЩАЯ из квитанции все условные строки сразу.

    Бюджет обязан держаться на ХУДШЕМ случае, а не на удобном: строка «без
    тела» появляется только когда есть безтелые, «стыки стен» — только когда
    есть оболочка стены, «только номинал» — только когда есть труба без
    таблицы размеров. Пачка, где ни одна из них не сработала, доказывала бы
    бюджет, которого никто не платит.
    """
    ops = [
        # трассы, которые СПОРЯТ: дают находки и суждения с ходом
        {"op": "create_duct", "id": "d1", "diameter_mm": 400.0,
         "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [0.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d2", "diameter_mm": 400.0,
         "p0_mm": [100.0, 0.0, 0.0], "p1_mm": [100.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d3", "diameter_mm": 400.0,
         "p0_mm": [200.0, 0.0, 0.0], "p1_mm": [200.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d4", "diameter_mm": 400.0,
         "p0_mm": [300.0, 0.0, 0.0], "p1_mm": [300.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d5", "diameter_mm": 400.0,
         "p0_mm": [400.0, 0.0, 0.0], "p1_mm": [400.0, 6000.0, 0.0]},
        {"op": "create_duct", "id": "d6", "diameter_mm": 400.0,
         "p0_mm": [500.0, 0.0, 0.0], "p1_mm": [500.0, 6000.0, 0.0]},
        # труба с номиналом и без таблицы размеров -> «только номинал»
        {"op": "create_pipe", "id": "pp1", "diameter_mm": 100.0,
         "p0_mm": [0.0, 0.0, 500.0], "p1_mm": [3000.0, 0.0, 500.0]},
        # безтелые РАЗНЫХ классов
        {"op": "create_room", "id": "r1"},
        {"op": "place_family", "id": "pf1"},
        {"op": "create_door", "id": "dr1"},
        {"op": "create_cable_tray", "id": "t1",
         "p0_mm": [0.0, 0.0, 0.0], "p1_mm": [1000.0, 0.0, 0.0]},
        {"op": "create_wall", "id": "w1", "p0_mm": [0.0, 0.0, 0.0],
         "p1_mm": [4000.0, 0.0, 0.0], "height_mm": 3000.0},
        {"op": "create_stairs", "id": "s1"},
    ]
    return [{"ops": ops[:7]}, {"ops": ops[7:]}]


class TheFixedPartHasANamedBudget(unittest.TestCase):
    """Замок. Растёт неснимаемая часть — падает ЭТОТ тест, а не число
    показанных суждений."""

    def test_the_worst_case_fits_the_named_budget(self):
        with _Flag():
            block = CB._report(_worst_case_pack(), new_from=2)
        budget = block["text_budget"]
        self.assertLessEqual(
            budget["fixed"], CB.FIXED_TEXT_BUDGET,
            f"неснимаемая часть {budget['fixed']} > бюджета "
            f"{CB.FIXED_TEXT_BUDGET}: следующая честная строка съест суждение. "
            f"Решай — сжать, убрать другую строку, или принести замер под "
            f"поднятие потолка.")

    def test_the_budget_arithmetic_is_stated_and_true(self):
        """Число без арифметики — назначенное, а не замеренное. Бюджет обязан
        отвечать на вопрос «сколько суждений он ГАРАНТИРУЕТ»."""
        room = CB._TEXT_CAP - CB.FIXED_TEXT_BUDGET
        self.assertGreaterEqual(room, CB.GUARANTEED_FINDINGS * CB.COST_PER_FINDING)
        self.assertLessEqual(CB.GUARANTEED_FINDINGS, CB._TOP)

    def test_the_promise_of_the_text_and_of_the_payload_are_both_named(self):
        """`_TOP` обещает пять суждений В ДАННЫХ, а текст гарантирует меньше —
        и до этой волны разница была молчаливой. Молчаливое расхождение между
        обещанием и доставкой и есть тот дефект."""
        self.assertGreater(CB._TOP, 0)
        self.assertGreater(CB.GUARANTEED_FINDINGS, 0)

    def test_the_budget_is_measured_on_the_worst_case_not_a_quiet_one(self):
        """Пачка теста обязана ЗАЖИГАТЬ условные строки — иначе бюджет
        доказан на квитанции, которой никто не получает."""
        with _Flag():
            block = CB._report(_worst_case_pack(), new_from=2)
        text = block["message_ru"]
        for must in ("БЕЗ ТЕЛА", "ВНЕСЛА ЭТА ПАЧКА", "НЕ ВИДИТ",
                     "ТОЛЬКО НОМИНАЛЬНЫЙ", "ВНЕ ПРОВЕРКИ"):
            self.assertIn(must, text, must)

    def test_at_least_the_guaranteed_number_of_findings_is_shown(self):
        """Смысл бюджета — не в самом числе, а в том, что находки доезжают."""
        with _Flag():
            block = CB._report(_worst_case_pack(), new_from=2)
        shown = block["text_budget"]["shown"]
        self.assertGreaterEqual(
            shown, min(CB.GUARANTEED_FINDINGS, block["text_budget"]["of"]))

    def test_the_budget_rides_in_the_payload_so_it_can_be_watched(self):
        """Бюджет, который виден только тесту, снова начнёт расти молча между
        прогонами. Он едет числом в ответе."""
        with _Flag():
            block = CB._report(_worst_case_pack())
        for key in ("fixed", "cap", "room", "shown", "of"):
            self.assertIn(key, block["text_budget"])
        self.assertEqual(block["text_budget"]["cap"], CB._TEXT_CAP)
        self.assertEqual(
            block["text_budget"]["room"],
            max(0, CB._TEXT_CAP - block["text_budget"]["fixed"]))


class TheCapDocstringDescribesTodayNotYesterday(unittest.TestCase):
    """«1 043 + 5×330 ≈ 2 700» описывало состояние, которого больше нет:
    неснимаемая часть 1 600, суждений влезает 3.3. Число, документирующее
    исчезнувшее состояние, — ровно тот дефект, за которым идёт охота."""

    def test_the_stale_arithmetic_is_gone(self):
        import inspect

        source = inspect.getsource(CB)
        head = source[source.index("_TEXT_CAP = "):]
        self.assertNotIn("1 043 + 5×330", head)

    def test_the_docstring_names_the_budget_constant(self):
        import inspect

        source = inspect.getsource(CB)
        anchor = source.index("#: Потолок текста в квитанции")
        window = source[anchor:anchor + 2_000]
        self.assertIn("FIXED_TEXT_BUDGET", window)


if __name__ == "__main__":
    unittest.main()
