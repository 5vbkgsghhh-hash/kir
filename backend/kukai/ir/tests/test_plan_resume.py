"""ПЛАН СТРОИТЕЛЬСТВА: УКАЗАТЕЛЬ ВОЗОБНОВЛЕНИЯ ПЕРЕПРЫГИВАЛ ЧЕРЕЗ ФАЗУ.

ВОСПРОИЗВЕДЕНО (замер 11.08.2026, `/tmp/wiring/y1.py`, `_plan_receipt`
напрямую, три фазы, вторая записала и НЕ была принята):

    фаза 1 НЕ записала              -> resume_from=1  «встал на фазе №1 b»
    фаза 1 ЗАПИСАЛА, не ПРИНЯТА     -> resume_from=2  «встал на фазе №2 b»
                                                       ^^^^^^^^^^^^^^^^^^^
Фаза, ОСТАНОВИВШАЯ план, — первая. Указатель говорит продолжить со ВТОРОЙ,
то есть перепрыгнуть через неё. И имя в той же строке принадлежит фазе 1
(`steps[-1]`), а номер — фазе 2: строка называет «фазу №2 b», где `b` это
фаза 1.

ПОЧЕМУ ТАК ВЫШЛО — ТА ЖЕ ФОРМА, ЧТО У ВСЕЙ СЕРИИ. Цикл `_run_plan`
останавливается по `ok`, а `resume` считается по `committed`, и ничто не
заставляет эти два понятия «готово» совпасть. `_plan_step` РАЗВОДИТ их
намеренно и правильно (запись может быть закоммичена и НЕ принята —
нарушенное постусловие в режиме `report`), но дальше по течению одно
подменяет другое.

ЧТО ЭТО СТОИТ. Фаза, записавшая в модель и не принятая, — единственный
случай, где ПРОДОЛЖИТЬ и ПОВТОРИТЬ одинаково неверны: повтор продублирует
построенное, пропуск оставит нарушенное постусловие в здании и промолчит.
Этот случай требует РЕШЕНИЯ автора, а не указателя, и молчаливое
перепрыгивание — худший из трёх возможных ответов.

ВТОРАЯ НАХОДКА ТОГО ЖЕ ПРОГОНА: при отказе НУЛЕВОЙ фазы квитанция печатает
«фазы 0..-1 уже в модели» — утверждение о диапазоне, которого не бывает.

ТРЕТЬЯ: фазы, до которых план не дошёл, в отчёте не названы числом. `phases=3,
шагов=2` — читатель обязан вычесть сам, а «не запускалась» и «упала» весь
марафон были разными фактами.
"""
from __future__ import annotations

import unittest

from kukai.ir import serving as S


def _step(index, name, ops, ok, committed):
    return {"index": index, "name": name, "ops": ops, "ok": ok,
            "committed": committed}


class ThePointerNeverSkipsTheFailedPhase(unittest.TestCase):

    def _receipt(self, steps, total, ok=False):
        return S._plan_receipt({"ok": ok, "message_ru": "x"},
                               list(steps), total)

    def test_a_phase_that_did_not_write_is_the_resume_point(self):
        block = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, False, False)],
            3)["plan"]
        self.assertEqual(block["resume_from"], 1)
        self.assertEqual(block["stopped_at"], 1)

    def test_a_phase_that_wrote_and_was_not_accepted_gets_no_pointer(self):
        """ЕДИНСТВЕННЫЙ СЛУЧАЙ, ГДЕ УКАЗАТЕЛЬ БЫЛ БЫ ЛОЖЬЮ В ЛЮБУЮ СТОРОНУ.
        Повторить фазу — продублировать построенное; пропустить — оставить
        нарушенное постусловие в здании. Нужно РЕШЕНИЕ, а не число."""
        block = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, False, True)],
            3)["plan"]
        self.assertEqual(block["stopped_at"], 1)
        self.assertNotIn("resume_from", block)
        self.assertEqual(block["needs_decision"], 1)

    def test_the_number_and_the_name_agree(self):
        """Строка называла «фазу №2 b», где `b` — фаза 1."""
        result = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, False, True)], 3)
        head = result["message_ru"].splitlines()[0]
        self.assertIn("№1", head)
        self.assertNotIn("№2", head)
        self.assertIn("b", head)

    def test_nothing_built_never_claims_a_range(self):
        """«фазы 0..-1 уже в модели» — утверждение о диапазоне, которого нет."""
        result = self._receipt([_step(0, "a", 2, False, False)], 3)
        self.assertNotIn("0..-1", result["message_ru"])
        self.assertEqual(result["plan"]["committed"], 0)

    def test_phases_never_started_are_counted_by_name(self):
        """«не запускалась» и «упала» — разные факты весь марафон."""
        block = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, False, False)],
            5)["plan"]
        self.assertEqual(block["never_started"], 3)
        self.assertEqual(block["phases"], 5)
        self.assertEqual(len(block["steps"]), 2)

    def test_a_whole_plan_names_nothing_it_did_not_meet(self):
        """Пометки, стоящие всегда, перестают читаться: у прошедшего плана
        нет ни точки останова, ни незапущенных."""
        block = self._receipt(
            [_step(0, "a", 2, True, True), _step(1, "b", 2, True, True)],
            2, ok=True)["plan"]
        self.assertNotIn("resume_from", block)
        self.assertNotIn("stopped_at", block)
        self.assertNotIn("needs_decision", block)
        self.assertEqual(block["never_started"], 0)

    def test_the_counters_never_contradict_each_other(self):
        for steps, total in (
                ([_step(0, "a", 1, True, True)], 1),
                ([_step(0, "a", 1, False, False)], 4),
                ([_step(0, "a", 1, True, True), _step(1, "b", 1, False, True)], 2),
        ):
            block = self._receipt(steps, total)["plan"]
            self.assertEqual(
                block["never_started"], total - len(block["steps"]))
            self.assertLessEqual(block["committed"], len(block["steps"]))


if __name__ == "__main__":
    unittest.main()
