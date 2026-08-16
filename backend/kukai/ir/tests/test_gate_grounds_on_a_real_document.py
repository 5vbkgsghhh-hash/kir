"""ВТОРАЯ ПОЛОСА ВОРОТ: заземление НАСТОЯЩИМ документом, а не фикстурой.

Ворота отвечают «собирается ли C# на шести версиях», и всё, что требует
заземления, заземлялось СИНТЕТИЧЕСКОЙ фикстурой. Такое «OK» есть утверждение о
фикстуре. Вторая полоса отвечает на ДРУГОЙ вопрос — «существует ли настоящее
здание, которым эту программу можно заземлить» — и здесь пришпилено, что она
умеет отвечать НЕТ.

🔴 ЧЕГО ЭТИ ТЕСТЫ НЕ ДЕЛАЮТ. Они не требуют корпуса: он машинно-локален
(`KUKAI_DECOMPILE_DATA`), в чекауте его нет, и тест, падающий от его отсутствия,
был бы красным по чужой причине. Поэтому корпус здесь СОБИРАЕТСЯ РУКАМИ из двух
крошечных профилей — и ровно этого достаточно, чтобы проверить предикат отбора.
Что проверяется НА НАСТОЯЩЕМ корпусе — печатает сам прогон ворот.
"""
from __future__ import annotations

import os
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from kukai.ir.gate_runner import (            # noqa: E402
    REAL_PROFILE_FETCH_HINT,
    ground_on_real_document,
    load_real_profiles,
    pools_required_by,
)


def _wall_program() -> dict:
    """Стена по имени типа — требует `levels` и `wall_types`."""
    return {"ir_version": "1.0", "intent": "стена",
            "ops": [{"op": "create_wall", "id": "w1",
                     "p0_mm": [0, 0], "p1_mm": [6000, 0],
                     "level": {"by": "name", "value": "Этаж 1"},
                     "type": {"by": "name", "value": "Кирпич 380"}}]}


def _profile(run: str, pools: dict[str, list]) -> tuple[str, dict, frozenset]:
    """Профиль в той форме, в которой его отдаёт `load_real_profiles`."""
    snapshot = dict(pools)
    snapshot["__document_fingerprint"] = {"title": run}
    filled = frozenset(k for k, v in snapshot.items()
                       if isinstance(v, list) and v)
    return run, snapshot, filled


_RICH = _profile("rich_building", {
    "levels": [{"id": 42, "name": "Этаж 1", "elevation_mm": 0.0}],
    "wall_types": [{"id": 100, "name": "Кирпич 380"}],
})
#: Пулы ОБЪЯВЛЕНЫ и ПУСТЫ — каталог, из которого нечего выбрать.
_EMPTY_POOLS = _profile("declared_but_empty", {
    "levels": [], "wall_types": [],
})
#: Пулы есть, но словарь чужой: имена типов другие.
_OTHER_NAMES = _profile("other_vocabulary", {
    "levels": [{"id": 7, "name": "L_01_+0.000", "elevation_mm": 0.0}],
    "wall_types": [{"id": 9, "name": "Вн_(Вт-50х100)"}],
})


class ТребованиеПуловБерётсяУРеестра(unittest.TestCase):

    def test_wall_needs_levels_and_wall_types(self):
        self.assertEqual(pools_required_by(_wall_program()),
                         frozenset({"levels", "wall_types"}))

    def test_a_program_without_grounding_needs_nothing(self):
        """КОНТРОЛЬ: предикат обязан УМЕТЬ вернуть пустое множество, иначе
        «нужны пулы» истинно всегда и не различает ничего."""
        prog = {"ir_version": "1.0",
                "ops": [{"op": "query_types", "id": "q1", "pool": "levels"}]}
        self.assertEqual(pools_required_by(prog), frozenset())

    def test_macros_are_expanded_before_asking(self):
        """Стек прячет операции, а требование пула несёт спрятанная."""
        # Форма взята у САМИХ ворот (`programs["auth_stack"]`), а не сочинена:
        # без `h_mm` макрос отказывает, и предикат честно отвечает про
        # нераскрытую программу — это правильно, но проверяет не то.
        stacked = {"ir_version": "1.0", "ops": [{
            "op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
            "floor": [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                       "p1_mm": [6000, 0], "height_mm": 2800}]}]}
        self.assertIn("wall_types", pools_required_by(stacked),
                      "стек прячет стену — требование пула потерялось")

    # КОНТРОЛЯ «нераскрываемый макрос» здесь НЕТ, и это решение, а не пробел:
    # я не нашёл формы стека, на которой `macros.expand` бросает (`h_mm`
    # необязателен, лишний `level` у члена тоже принимается), а тест, чья
    # посылка не установлена, сторожит собственную выдумку. Ветка `except` в
    # `pools_required_by` остаётся НЕПРОВЕРЕННОЙ — сказано вслух.


class ПолосаУмеетОтвечатьНЕТ(unittest.TestCase):
    """КОНТРОЛЬ-FAIL. Полоса, которая не умеет сказать «нет», не сторожит
    ничего: её «да» тогда получено без акта различения."""

    def test_a_real_document_grounds_the_program(self):
        got = ground_on_real_document(_wall_program(), [_RICH])
        self.assertIsInstance(got, tuple, msg=f"ожидалось заземление, дано {got}")
        self.assertEqual(got[0], "rich_building")

    def test_declared_but_EMPTY_pools_do_not_count_as_having_them(self):
        """Пул объявлен и пуст — выбирать не из чего. Считать его наличием
        значило бы получить зелёное там, где нет альтернатив (форма 18)."""
        got = ground_on_real_document(_wall_program(), [_EMPTY_POOLS])
        self.assertIsInstance(got, str)
        self.assertIn("нет профиля", got)

    def test_pools_present_but_the_vocabulary_is_someone_elses(self):
        """Каталоги есть, имён нет: это факт о ПРОГРАММЕ, и он обязан
        отличаться от факта о КОРПУСЕ."""
        got = ground_on_real_document(_wall_program(), [_OTHER_NAMES])
        self.assertIsInstance(got, str)
        self.assertIn("KIR-G", got)
        self.assertNotIn("нет профиля", got)

    def test_the_search_does_not_stop_at_the_first_candidate(self):
        """ПОЧЕМУ ПЕРЕБОР. Первая редакция брала первый профиль с непустыми
        пулами и объявляла отказ; здесь подходящий стоит ВТОРЫМ, и «нет»
        было бы неправдой о существовании."""
        got = ground_on_real_document(_wall_program(), [_OTHER_NAMES, _RICH])
        self.assertIsInstance(got, tuple, msg=f"перебор не дошёл до второго: {got}")
        self.assertEqual(got[0], "rich_building")

    def test_a_program_needing_no_pool_is_NOT_counted_as_grounded(self):
        """🔴 ОБРАТНЫЙ КОНТРОЛЬ, ПОЙМАВШИЙ АВТОРА. `need <= filled` истинно
        для ПУСТОГО `need` при любом профиле, включая заведомо пустой, — и
        первая редакция считала такое заземлением. Зелёное без акта
        различения. Заземлять нечего — это третий исход."""
        prog = {"ir_version": "1.0",
                "ops": [{"op": "create_path_of_travel", "id": "t1",
                         "in_view": {"by": "name", "value": "Level 1"},
                         "p0_mm": [0, 0], "p1_mm": [1000, 0]}]}
        self.assertEqual(pools_required_by(prog), frozenset())
        got = ground_on_real_document(prog, [_EMPTY_POOLS])
        self.assertIsInstance(got, str)
        self.assertIn("заземлять нечего", got)

    def test_an_empty_corpus_is_a_REFUSAL_not_a_zero(self):
        """«Настоящих документов программа не выдерживает» и «мы не смотрели»
        — разные факты. Пустой корпус обязан называться отказом, и способ его
        достать обязан стоять рядом с отказом, а не в чьей-то памяти."""
        self.assertEqual(load_real_profiles("/nonexistent/decompile"), [])
        self.assertIn("KUKAI_DECOMPILE_DATA", REAL_PROFILE_FETCH_HINT)


class ОтборДетерминирован(unittest.TestCase):

    def test_two_runs_agree(self):
        """Ворота обязаны отвечать одинаково дважды подряд: порядок каталога
        детерминированным не является, поэтому список сортируется по имени."""
        a = ground_on_real_document(_wall_program(), [_OTHER_NAMES, _RICH])
        b = ground_on_real_document(_wall_program(), [_OTHER_NAMES, _RICH])
        self.assertEqual(a[0], b[0])

    def test_loader_sorts_by_run_name(self):
        rows = load_real_profiles(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "no_such_corpus"))
        self.assertEqual(rows, [], "несуществующий корпус обязан дать пусто")


if __name__ == "__main__":
    unittest.main()
