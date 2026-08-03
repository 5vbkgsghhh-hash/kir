"""The tool description must not be able to lie about the registry.

Until 2026-07-27 the `revit_ir` description was a hand-written paragraph naming
"уровни/стены/окна/двери/перекрытия/колонны/помещения" — 7 of the 28 writing
ops. Nothing caught it, because prose has no ratchet: ops were added by six
separate waves and none of them touched the sentence. A model reading that text
could not know KIR authors beams, ducts, cable trays, groups, family types or
annotations at all.

These tests are that ratchet.
"""
from __future__ import annotations

import unittest

from kukai.ir import spec
from kukai.ir.tool_doc import NOTES, UNPROVEN, build_tool_description


class ToolDescriptionCoversRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.text = build_tool_description()

    def test_every_op_is_named(self):
        """Adding an op to the registry must not leave it undocumented."""
        missing = sorted(name for name in spec.OPS if name not in self.text)
        self.assertEqual(missing, [], f"опы отсутствуют в описании: {missing}")

    def test_writing_and_reading_counts_match_the_registry(self):
        writing = sum(1 for op in spec.OPS.values() if op.writes_model)
        reading = len(spec.OPS) - writing
        self.assertIn(f"ПИШУЩИЕ ({writing})", self.text)
        self.assertIn(f"ЧИТАЮЩИЕ ({reading})", self.text)

    def test_unproven_entries_name_real_ops(self):
        """A stale honesty note is worse than none — it sends the model away
        from an op that has since been fixed."""
        unknown = sorted(name for name in UNPROVEN if name not in spec.OPS)
        self.assertEqual(unknown, [], f"UNPROVEN называет несуществующие опы: {unknown}")
        for name in UNPROVEN:
            self.assertIn(name, self.text)

    def test_measured_idioms_are_present(self):
        """The idioms exist because the model failed without them; losing one
        silently re-opens the failure it closed."""
        self.assertGreaterEqual(len(NOTES), 10)
        for probe in (
            "толщина",          # тип, а не параметр операции
            "query_types",      # спроси каталог до селектора
            "create_stairs",    # единственный оп своей программы
            "ПРОСТРАНСТВО ВИДА",   # аннотации живут в 2D вида
            "allow_destructive",   # delete не бывает случайным
        ):
            self.assertIn(probe.lower(), self.text.lower(), probe)

    def test_ref_rule_matches_the_compiler(self):
        """`ref` is legal for what the program itself creates (level/host/
        target/refs) and NOT for catalog selectors — proven live 2026-07-27
        (окно по ref на свою стену, set_param и create_tag по ref). An earlier
        draft said "только для level" and would have talked the model out of
        three shapes that work."""
        self.assertIn("host", self.text)
        self.assertIn("target", self.text)
        self.assertIn("`type`/`symbol` ref НЕ работает", self.text)

    def test_description_stays_small_next_to_the_schema(self):
        """The generated JSON Schema already costs ~23k tokens per turn. The
        prose is worth its place only while it stays a small fraction of that.

        Порог поднимался дважды и оба раза ОСОЗНАННО, с арифметикой:
        8 000 -> 13 000 (30.07, въезд `skill.py` суждениями) -> 30 000 (30.07,
        решение оператора: «скилл может быть 10к токенов, это не страшно»,
        жанр сменился с памятки на КРАТКИЙ КУРС ПОДГОТОВКИ).

        Замер после смены жанра (tiktoken o200k; tiktoken намеренно НЕ вносится
        в зависимости теста, поэтому проверка идёт по СИМВОЛАМ, а токены
        остаются провенансом):

            схема           22 927 токенов   89 018 символов
            проза (итого)    8 929 токенов   26 786 символов
              из них курс    7 140 токенов   20 708 символов
            вся пачка       31 856 токенов

        Проза = 28.0% пачки (8 929 / 31 856). Оплачивается КАЖДЫЙ запрос, а
        сэкономленный раунд стоит целой пачки плюс раздумья (85% времени хода
        — раздумье модели, замер 28.07). Точка окупаемости: проза объёмом P
        окупается, если экономит один раунд на (пачка / P) ходов — сейчас
        31 856 / 8 929 = ОДИН РАУНД ИЗ 3.6. Это заметно более требовательный
        порог, чем был у памятки (1 из 7.5), и он осознан: курс обязан менять
        поведение ощутимо, иначе он не окупается.

        Почему 30 000 символов. Объявленный оператором потолок — ~10 000
        токенов прозы; на этом тексте замерено 3.00 символа на токен
        (26 786 / 8 929), значит 30 000 символов ≈ 10 000 токенов. Порог
        выражен в символах ровно потому, что токенизатор в тестах недоступен.

        Дальше текст обязан не расти, а вытеснять сам себя: при прозе больше
        трети пачки экономия должна быть уже почти в каждом втором ходе, а
        такого мы не мерили и обещать не можем.
        """
        self.assertLess(len(self.text), 30_000,
                        "описание разрослось — режь, схема и так дорогая")


if __name__ == "__main__":
    unittest.main()
