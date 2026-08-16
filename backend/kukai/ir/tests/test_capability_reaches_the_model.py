"""СПОСОБНОСТЬ, О КОТОРОЙ МОДЕЛЬ НЕ МОЖЕТ ПРОЧИТАТЬ, НЕ ПОСТРОЕНА — ОНА НАПИСАНА.

🔴 ЗАКОН ВЛАДЕЛЬЦА, 15.08.2026: «режим КИР не должен работать без документации и
скиллов; всякая новая способность приезжает ВМЕСТЕ со своей дверью и своим
текстом».

ЧТО ЭТОТ ФАЙЛ ЧИНИТ — КЛАСС, А НЕ СЕМЬ СЛУЧАЕВ. За один день построили шесть
способностей, и модель не знала ни об одной: единица замысла, двери в типовом
этаже, каталог документа, поднятый бюджет, карта `element_map`, клеш против уже
стоящего здания. Ни одна не была забыта по небрежности — просто НИЧТО НЕ
ТРЕБОВАЛО написать текст, а реестр тем временем рос. Довод, что так будет и
дальше, записан в самом коде и стоил пяти недель: `sdk.py` — 493 строки,
недостижимые, потому что двери к ним не было.

КАК ЭТО РАБОТАЕТ. Ниже перечислены РЕЕСТРЫ СПОСОБНОСТЕЙ — авторитеты, каждый со
своим родом. Для каждого сказано, ГДЕ имя обязано быть названо, и почему именно
там. Добавление имени в реестр без строки в тексте краснит этот файл.

ДВЕ ДВЕРИ, И ЦЕНА У НИХ РАЗНАЯ — отсюда правило размещения:

  ОПИСАНИЕ ИНСТРУМЕНТА   платится КАЖДЫМ ходом. Здесь стоит то, без чего
                         модель выберет НЕ ТУ ФОРМУ.
  ПО ТРЕБОВАНИЮ          `spec(<оп>)`, `recipe()`, уроки — читается, когда
                         спросили. Здесь подробность и примеры.

Тест НЕ судит, где именно способность названа, если она названа хоть где-то
достижимом: спорить о размещении — работа автора, а вот молчание обеих дверей
это дефект, и его ловит машина.
"""
from __future__ import annotations

import io
import contextlib
import unittest

from kukai.ir import spec, tool_doc, skill
from kukai.ir.assembly_view import UNIT_READS
from kukai.ir.course import lessons
from kukai.ir.macros import _STACKABLE_HOSTED, MACRO_OPS


def _description() -> str:
    return tool_doc.build_tool_description()


def _on_demand() -> str:
    """Всё, что модель может ПРОЧИТАТЬ ПО ЗАПРОСУ, одной строкой.

    Уроки, каталог реестра (`spec()`), каталог рецептов (`recipe()`). Собрано
    вызовом, а не переписыванием: текст, собранный руками, сторожил бы фикстуру
    (форма 27).
    """
    from kukai.ir import course

    parts = [lessons.lesson(name) for name in lessons.ORDER]
    for door in ("spec", "recipe"):
        fn = getattr(course, door, None)
        if fn is None:
            continue
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            try:
                fn()
            except Exception:  # noqa: BLE001 — дверь, отказавшая, тоже факт
                pass
        parts.append(buffer.getvalue())
    return "\n".join(parts)


def _everything() -> str:
    return _description() + "\n" + _on_demand()


class EveryCapabilityRegistryIsNamedToTheModel(unittest.TestCase):
    """РАТЧЕТ. Реестр способностей -> имя обязано быть в тексте."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.description = _description()
        cls.everywhere = _everything()

    # ── реестры, чьи имена обязаны быть в ПОСТОЯННОМ тексте ────────────────

    def test_every_reading_predicate_is_named_in_the_description(self):
        """Прочтения единицы (`UNIT_READS`) — в ОПИСАНИИ, а не по требованию.

        Прочтение решает ФОРМУ высказывания: не зная, что `reads_as`
        существует, автор напишет набор без объявленного замысла, и находка об
        арности N не появится никогда. Спросить о том, чего не знаешь, нельзя.
        """
        for name in UNIT_READS:
            with self.subTest(reading=name):
                self.assertIn(name, self.description,
                              "прочтение %r есть в реестре и НЕ названо в "
                              "описании: модель не сможет его выбрать" % name)

    def test_the_unit_construct_itself_is_named(self):
        self.assertIn("unit(", self.description,
                      "конструкция `unit()` не названа — реестр прочтений "
                      "недостижим целиком")

    def test_the_element_map_is_named_in_the_description(self):
        """`element_map` — единственный способ сослаться на ПОСТРОЕННОЕ
        следующим ходом. Без него автор ищет элемент по имени заново, и это
        лишний раунд на каждом продолжении."""
        self.assertIn("element_map", self.description)

    def test_every_registry_op_is_named(self):
        """Дубль соседнего файла НАМЕРЕННЫЙ: там он про полноту описания,
        здесь — про закон «способность приезжает со своим текстом». Если
        `test_tool_doc` однажды ослабят, закон обязан продолжать держать."""
        missing = [n for n in spec.OPS if n not in self.description]
        self.assertEqual(missing, [], "опы реестра не названы: %s" % missing)

    # ── реестры, которым довольно двери ПО ТРЕБОВАНИЮ ──────────────────────

    def test_every_macro_is_named_somewhere_reachable(self):
        for name in MACRO_OPS:
            with self.subTest(macro=name):
                self.assertIn(name, self.everywhere,
                              "макрос %r нигде не назван" % name)

    def test_hosted_stackable_ops_are_named_in_the_macro_contract(self):
        """🔴 СПОСОБНОСТЬ ВОЛНЫ Е — И ПРОВЕРКА СМОТРИТ В КОНТРАКТ МАКРОСА, А НЕ
        В ВЕСЬ ТЕКСТ.

        Первая редакция искала `create_door` в объединённом тексте и была
        ЗЕЛЕНА ВАКУУМНО: это имя стоит в описании как имя ОПА, в списке
        разделов, и находилось бы, даже если про `stack` не было сказано ни
        слова. Проверка без акта различения — форма 18 канона, совершённая в
        тесте, который писался против неё же.

        Замер, поймавший это: урок «этаж» не называл ни `stack`, ни двери —
        способность действительно была невидима, а тест был зелёным.

        Теперь спрашивается ТА ДВЕРЬ, где контракт макроса и живёт.
        Названо ПО ТРЕБОВАНИЮ, а не в описании, и это решение с доводом:
        макросов в скрипте (`program_py`) нет вовсе — их работу там делает
        питон, — а описание учит прежде всего скрипту.

        🔴 ЧЕСТНАЯ ГРАНИЦА ЭТОЙ ПРОВЕРКИ, ЗАМЕРЕННАЯ МУТАЦИЕЙ (15.08.2026):
        она НЕ МОЖЕТ покраснеть от нового жильца `_STACKABLE_HOSTED`. Внесение
        `create_opening` в реестр оставило её зелёной — и это не дефект теста,
        а свойство ЛУЧШЕЕ, чем ратчет: `_macro_contract` ПОРОЖДАЕТ список из
        того же реестра, поэтому текст следует за реестром сам, и «добавить,
        не задокументировав» здесь физически нельзя.

        Отсюда общий вывод волны, и он важнее любой из семи способностей:
        **порождаемый текст не нуждается в ратчете, рукописный — нуждается.**
        Ратчет ниже стоит там, где текст пишут рукой (`UNIT_READS` в описании,
        `element_map`, имена опов), и мутация показывает, что там он кусает.
        Проверка здесь остаётся не как сторож, а как КОНТРОЛЬ ПОРОЖДЕНИЯ: она
        покраснеет, если контракт перестанет собираться из реестра и станет
        рукописным списком — то есть ровно тогда, когда ратчет понадобится.
        """
        from kukai.ir import course

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            course.spec("stack")
        contract = buffer.getvalue()
        self.assertTrue(contract.strip(), "spec('stack') не отдал ничего")
        for name in _STACKABLE_HOSTED:
            with self.subTest(op=name):
                self.assertIn(name, contract,
                              "хостящийся оп %r допущен в stack, а контракт "
                              "макроса о нём молчит" % name)
        # И САМА СПОСОБНОСТЬ, А НЕ ТОЛЬКО ИМЕНА: без этой строки автор не
        # узнает, что хозяин обязан ехать вместе с членом.
        self.assertIn("ХОЗЯИН", contract.upper(),
                      "контракт не говорит, что хозяин обязан быть членом "
                      "того же этажа — имена без правила бесполезны")

    def test_the_macro_contract_door_answers_for_every_macro(self):
        """У КАЖДОГО макроса обязана быть дверь контракта. До 15.08.2026
        `spec("stack")` отвечал «операции нет в реестре» — формально верно
        (макрос не оп) и практически неверно: автор спрашивал про
        существующую способность и слышал, что её не существует."""
        from kukai.ir import course

        for name in MACRO_OPS:
            with self.subTest(macro=name):
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    course.spec(name)
                text = buffer.getvalue()
                self.assertIn(name, text)
                self.assertGreater(len(text), 120,
                                   "контракт макроса %r пуст или отказ" % name)

    # ── контроль: ратчет обязан уметь покраснеть ───────────────────────────

    def test_the_ratchet_can_actually_fail(self):
        """КОНТРОЛЬ-FAIL. Проверка «имя есть в тексте» зелена по построению,
        если текст велик: почти любая короткая строка в нём найдётся. Контроль
        берёт имя, которого в реестрах НЕТ, и требует, чтобы оно не нашлось.
        """
        invented = "reads_as_совершенно_несуществующее_прочтение"
        self.assertNotIn(invented, self.everywhere,
                         "текст содержит выдуманное имя — проверка "
                         "вхождения ничего не различает")

    def test_naming_a_capability_did_not_break_the_permanent_budget(self):
        """🔴 ВТОРАЯ ПОЛОВИНА ЗАКОНА, БЕЗ КОТОРОЙ ПЕРВАЯ ВРЕДНА.

        «Способность обязана быть названа» без потолка превращается в «пиши в
        постоянный текст всё» — и ровно так он и был пробит: восемь
        способностей приехали за день, замер дал 30 427 при потолке 30 000, и
        НИЧТО не покраснело, потому что ратчета на бюджет здесь не было, а
        `test_tool_doc` о способностях ничего не знает.

        Две проверки обязаны стоять РЯДОМ: назвать и уложиться — это одно
        требование, а не два. Разведённые по файлам, они дают маятник, где
        каждая волна честно чинит одну половину и честно ломает другую.
        """
        self.assertLess(
            len(self.description), 30_000,
            "описание пробило потолок: способность названа ценой бюджета, "
            "который платится КАЖДЫМ ходом. Не поднимай потолок — перенеси "
            "подробность в канал спроса (`course(<тема>)`, `spec(<оп>)`, "
            "`recipe()`) и оставь в постоянном тексте одну строку")

    def test_the_registries_are_not_empty(self):
        """ЗНАМЕНАТЕЛЬ ПЕРВЫМ: пустой реестр прошёл бы каждую проверку выше
        вакуумно, и «все способности названы» читалось бы как факт."""
        self.assertTrue(UNIT_READS, "реестр прочтений пуст")
        self.assertTrue(_STACKABLE_HOSTED, "реестр хостящихся пуст")
        self.assertTrue(MACRO_OPS, "реестр макросов пуст")
        self.assertGreaterEqual(len(spec.OPS), 60)


class TheTwoDoorsAreBothReachable(unittest.TestCase):
    """Текст по требованию бесполезен, если о самой двери не сказано в
    постоянном тексте: спросить о том, чего не знаешь, нельзя."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.description = _description()

    def test_the_on_demand_doors_are_announced(self):
        for door in ("spec(", "recipe"):
            with self.subTest(door=door):
                self.assertIn(door, self.description,
                              "дверь %r не объявлена в постоянном тексте — "
                              "модель о ней не узнает" % door)

    def test_the_on_demand_text_is_not_empty(self):
        text = _on_demand()
        self.assertGreater(len(text), 5_000,
                           "двери по требованию отдали почти пустой текст — "
                           "проверки размещения выше судили бы ни о чём")


if __name__ == "__main__":
    unittest.main()
