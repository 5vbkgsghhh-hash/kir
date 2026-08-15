"""ПРИМЕР, КОТОРЫЙ МЫ ПОКАЗЫВАЕМ МОДЕЛИ, СВЕРЕН С КОМПИЛЯТОРОМ.

ЗАЧЕМ ЭТОТ ФАЙЛ. В постоянном описании инструмента (28 218 символов до этой
волны) слово `track` стояло ОДИН раз прозой и НИ РАЗУ JSON'ом: раздел про
повтор рассказывал про выигрыш и не показывал формы. Для ЛЛМ проработанный
пример плотнее абзаца, поэтому пример добавлен — и вместе с ним обязанность,
которой у прозы нет.

**ПРОЗУ НИКТО НЕ МУТИРУЕТ.** Форма 9 канона: обещание в тексте шире поведения
в коде, и ни один прогон не покраснеет оттого, что абзац соврал. Пример — это
проза, которая ВЫГЛЯДИТ как код, и потому опаснее обычной: модель скопирует её
буквально. Единственный способ не дать ей протухнуть — сверять её с тем самым
компилятором, который её примет или отвергнет.

ЧТО ЗАКРЕПЛЕНО:
  * показанная программа КОМПИЛИРУЕТСЯ и разворачивается в объявленное число
    операций (пример, который не компилируется, учит неверному с той же
    плотностью, с какой верный учит верному);
  * показанный ОТКАЗ — дословно тот, что выдаёт компилятор сегодня, а не
    пересказ по памяти;
  * оба доезжают до описания, которое реально уходит модели.

ГРАНИЦА. Файл проверяет ПЛАН (`compiler.plan_program`) — стадию, на которой
живут и развёртка макроса, и покрытие трека. Он не проверяет ни заземление, ни
эмиссию, ни поведение Ревита: у показанной программы селектор уровня по имени,
и в живом документе он может не разрешиться. Это и есть предмет примера —
форма записи повтора, а не готовность к постройке в конкретной модели.
"""

from __future__ import annotations

import copy
import unittest

from kukai.ir import compiler, skill, tool_doc

EXPECTED_OPS = 6


def _plan(program: dict):
    return compiler.plan_program(copy.deepcopy(program))


class TheShownProgramCompiles(unittest.TestCase):

    def test_it_expands_to_the_declared_number_of_ops(self) -> None:
        planned = _plan(skill.REPEAT_BY_TRACK)
        self.assertEqual(len(planned.ops), EXPECTED_OPS)

    def test_the_description_says_the_same_number(self) -> None:
        """Число в прозе и число из компилятора — одна величина.

        Ровно тот дефект, который этот дом ловит вторые сутки: величина
        объявлена в одном месте и читается в другом, и ничто не заставляет их
        совпасть.
        """
        self.assertIn(f"Разворачивается в {EXPECTED_OPS} операций",
                      tool_doc.build_tool_description())

    def test_the_program_reaches_the_description_verbatim(self) -> None:
        text = tool_doc.build_tool_description().replace(" ", "")
        self.assertIn('"op":"series"', text)
        self.assertIn('"$x@next"', text)


class TheShownRefusalIsTheRealOne(unittest.TestCase):
    """Отказ в описании — снимок компилятора, а не пересказ."""

    @staticmethod
    def _shorten_track() -> dict:
        """Та же программа с треком до 5 вместо 6 — единственная правка."""
        broken = copy.deepcopy(skill.REPEAT_BY_TRACK)
        broken["ops"][0]["track"]["x"] = [[0, 0], [5, 12000]]
        return broken

    def test_the_quoted_text_is_what_the_compiler_says_today(self) -> None:
        with self.assertRaises(Exception) as caught:
            _plan(self._shorten_track())
        diags = getattr(caught.exception, "diagnostics", None) or ()
        self.assertTrue(diags, "отказ без диагностик — сверять нечего")
        d = diags[0]
        quoted = skill.REPEAT_REFUSAL_RU[0]
        self.assertIn(d.code, quoted)
        self.assertIn(d.message_ru, quoted,
                      "текст отказа в описании разошёлся с компилятором")

    def test_the_refusal_reaches_the_description(self) -> None:
        text = tool_doc.build_tool_description()
        self.assertIn("KIR-M001", text)
        self.assertIn("ПОЧИНКА — ОДИН УЗЕЛ", text)


class TheCheckCanFail(unittest.TestCase):
    """Контроль-FAIL: без него зелёный цвет выше не сообщает ничего.

    Форма 8 канона. Проверяется не «что-то упало», а что падает ИМЕННО ТО, что
    эти тесты обещают ловить: испорченный пример и разошедшийся отказ.
    """

    def test_a_broken_example_would_be_caught(self) -> None:
        broken = copy.deepcopy(skill.REPEAT_BY_TRACK)
        broken["ops"][0]["track"]["x"] = [[0, 0], [5, 12000]]
        with self.assertRaises(Exception):
            _plan(broken)

    def test_a_drifted_refusal_text_would_be_caught(self) -> None:
        with self.assertRaises(Exception) as caught:
            _plan(TheShownRefusalIsTheRealOne._shorten_track())
        real = (getattr(caught.exception, "diagnostics", None) or ())[0]
        self.assertNotIn(real.message_ru, "KIR-M001 | поле x | подсаженный "
                                          "пересказ отказа по памяти")

    def test_the_op_count_assertion_is_not_vacuous(self) -> None:
        """Мощность названа: при count=1 развёртка неотличима от не-повтора."""
        self.assertGreaterEqual(EXPECTED_OPS, 2)
        one = copy.deepcopy(skill.REPEAT_BY_TRACK)
        one["ops"][0]["count"] = 2
        one["ops"][0]["track"] = {"x": [[0, 0], [2, 4000]],
                                  "h": [[0, 3300], [2, 3000]]}
        self.assertEqual(len(_plan(one).ops), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
