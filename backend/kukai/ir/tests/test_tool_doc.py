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

from kukai.ir import dsl, spec
from kukai.ir.registry_base import DISCIPLINES
from kukai.ir.tool_doc import (
    NOTES, OP_NOTES, UNPROVEN, build_tool_description)


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
        ):
            self.assertIn(probe.lower(), self.text.lower(), probe)
        # `allow_destructive` УЕХАЛ, А НЕ ПРОПАЛ (09.08). Проба осталась в
        # тесте, но спрашивает НОВЫЙ адрес: требование конверта нужно тому,
        # кто `delete` уже написал, а не тому, кто выбирает операцию. Убрать
        # пробу вовсе значило бы снять храповик с замера, который её сюда и
        # поставил.
        self.assertIn("allow_destructive",
                      dsl.OP_FUNCTIONS["delete"].__doc__ or "")

    def test_ref_rule_matches_the_compiler(self):
        """`ref` is legal for what the program itself creates (level/host/
        target/refs) and NOT for catalog selectors — proven live 2026-07-27
        (окно по ref на свою стену, set_param и create_tag по ref). An earlier
        draft said "только для level" and would have talked the model out of
        three shapes that work."""
        self.assertIn("host", self.text)
        self.assertIn("target", self.text)
        self.assertIn("`type`/`symbol` ref НЕ работает", self.text)

    def test_the_op_list_is_grouped_by_discipline_not_by_a_compiler_field(self):
        """Перечень опов читают ПО РАЗДЕЛАМ, потому что работу ведут по ним.

        До 09.08 здесь печаталось внутреннее поле реестра (`element`,
        `category/element: create_column, create_wall`, `element/mep_system`).
        Прочитанный глазами автора, тот перечень не отвечал ни на один его
        вопрос: из текста не следовало, почему `create_wall` отделён от
        `create_floor`. Это тест не на красоту, а на то, что компиляторное
        поле больше не протекает на поверхность.
        """
        for discipline, names in spec.ops_by_discipline(writes=True):
            self.assertIn(f"  {spec.DISCIPLINE_RU[discipline]}: "
                          + ", ".join(names), self.text)
        # Свод из реестра не печатает `capability` НИ ОДНОЙ группой.
        for kind, _names in spec.ops_by_object_kind(writes=True):
            self.assertNotIn(f"\n  {kind}: ", self.text)

    def test_every_discipline_label_is_the_one_dictionary(self):
        """Ярлык — ПЕРЕВОД словаря разделов, а не второй словарь.

        Разойдись ключи — и в тексте появился бы раздел, которого реестр не
        знает, либо пропал бы раздел, который он знает. Оба случая молчаливы.
        """
        self.assertEqual(set(spec.DISCIPLINE_RU), set(DISCIPLINES))
        self.assertEqual(set(spec.DISCIPLINE_ORDER), set(DISCIPLINES))

    def test_the_discipline_of_every_op_is_derived_or_named_as_underived(self):
        """Каждый пишущий оп либо в разделе, либо в списке невыведенных.

        Третьего не дано: оп, пропавший из обоих, исчез бы из перечня целиком,
        а `shared` для невыведенного — прямая ложь (словарь говорит, что
        `shared` значит «принадлежит всем», а не «неизвестно»).
        """
        writing = {n for n, o in spec.OPS.items() if o.writes_model}
        placed = {n for _d, names in spec.ops_by_discipline(writes=True)
                  for n in names}
        undecided = {n for n, _why in spec.ops_without_discipline(writes=True)}
        self.assertEqual(placed | undecided, writing)
        self.assertEqual(placed & undecided, set())
        # У КАЖДОГО невыведенного причина СЛОВАМИ, а не пустая строка: пробел
        # учёта без причины неотличим от забытого опа.
        for name, why in spec.ops_without_discipline(writes=True):
            self.assertTrue(why.strip(), name)

    def test_a_single_op_trap_lives_in_that_op_and_not_in_the_description(self):
        """ВЫТЕСНЕНИЕ — ЭТО ПЕРЕЕЗД, А НЕ УДАЛЕНИЕ, и проверяется он с двух
        сторон сразу.

        Ловушка, называющая РОВНО ОДИН оп и нужная ПОСЛЕ того, как он выбран,
        не имеет права стоять в постоянно загружаемом тексте: описание
        платится каждым ходом, докстрока — только тем, где её спросили. Но
        «вытеснил» без второй половины проверки — это «удалил»: знание
        считается доехавшим, только если по новому адресу оно ЧИТАЕТСЯ.
        """
        self.assertTrue(OP_NOTES)
        for op_name, notes in OP_NOTES.items():
            self.assertIn(op_name, spec.OPS, op_name)
            doc = dsl.OP_FUNCTIONS[op_name].__doc__ or ""
            for note in notes:
                self.assertIn(note, doc, f"{op_name}: не доехало в докстроку")
                self.assertNotIn(note, self.text,
                                 f"{op_name}: осталось и в описании — "
                                 f"платим дважды")

    def test_the_displaced_traps_have_a_named_address_in_the_description(self):
        """Знание, до которого нет пути от постоянного текста, — тёмное.

        Тот же закон достижимости, что у указателя на курс: способность,
        о которой модель не может узнать, не существует. Поэтому вытеснение
        оплачивается ОДНОЙ строкой, называющей дверь.
        """
        self.assertIn("spec(", self.text)

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
