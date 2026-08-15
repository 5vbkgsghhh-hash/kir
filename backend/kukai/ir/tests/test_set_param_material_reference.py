"""ССЫЛОЧНОЕ ЗНАЧЕНИЕ `set_param`: материал и фаза задаются ССЫЛКОЙ, не строкой.

ЗАЧЕМ. Множество значений `set_param` было закрыто на `str | bool | число`, и
потому НЕДОСТИЖИМ был каждый параметр, чьё значение есть ССЫЛКА: материал, фаза,
помещение, уровень. `Parameter.Set(ElementId)` компилируется на всех шести
версиях — потолок был НАШ, а не Ревита.

ГРАНИЦА НАЗВАНА: открыто ТРИ признака — материал, фаза (ссылки) и рабочий набор
(НЕ ссылка, свой механизм), по одному за раз.
Четыре сразу дали бы четыре недоказанных вместо одного доказанного. Порядок не
алфавитный, а по тому, что мешает МОДЕЛИ: фаза второй, потому что каждый
настоящий проект фазирован, и элемент не в той фазе не показывается на нужных
видах — здание ВЫГЛЯДИТ построенным и не является им. Осталась марка, и её
дефект другого рода: адресация параметра ЛОКАЛИЗОВАННЫМ отображаемым именем.

ПРИЁМ ОДИН НА ВСЕ РОДА. Различаются ровно две вещи — класс Ревита и слово
отказа с его причастием; всё прочее (разрешение, отказ, `Set(<el>.Id)`,
свидетель) общее. Второй способ делать то же разошёлся бы с первым на роде,
который придёт третьим. Имя файла осталось от первого рода.

И РОВНО НА ТРЕТЬЕМ ЭТО ЕДВА НЕ СТОИЛО ДОРОГО. Рабочий набор выглядит четвёртым
родом ссылки и им не является: `Parameter.Set(WorksetId)` не существует,
`Workset` не наследует `Element`, коллектор свой, свидетель целый. Строка,
дописанная в таблицу по аналогии, дала бы способность, которая ВЫГЛЯДИТ как две
доказанные. **Проверка применимости есть ЦЕНА обобщения**, и она стоит перед
приёмом, а не после.

ЧТО ИМЕННО ЗДЕСЬ ДОКАЗЫВАЕТСЯ, кроме «компилируется»:

* отказ пришёл ОФЛАЙН. Образец (`create_type.material`) разрешает имя
  коллектором ВНУТРИ транзакции: отказ честный и типизированный, но приходит
  там, где круг стоит дороже всего. Пул переносит ту же проверку на АВТОРСТВО;
* живая проверка при этом ОСТАЛАСЬ. Пул — снимок, документ мог измениться между
  снятием и исполнением, и снять живого свидетеля ради офлайнового значило бы
  обменять доказательство на удобство;
* СВИДЕТЕЛЬ ЕСТЬ. Способность, добавленная без своего свидетеля, не «неполная»
  — она запрещённая: исполнение совершено, подтвердить нечем. Поэтому ветка
  записи (`Set(<el>.Id)`) и ветка перечитывания (`AsElementId()`) заведены ОДНОЙ
  правкой;
* УМОЛЧАНИЯ НЕТ ПО ПОСТРОЕНИЮ. Опускаемый материал разрешался бы правилом
  `sole_entry`, которое не ВЫБИРАЕТ, а констатирует безальтернативность
  (замерено 12.08.2026: на фикстуре так разрешаются 46 пар из 47, на настоящих
  зданиях 42 из 91 умолчания перестают работать). Здесь этот выбор не
  создаётся, а не «не рекомендуется».

МОЩНОСТЬ ПУЛА В ФИКСТУРЕ — ДВА, И ЭТО НЕ УКРАШЕНИЕ: при одном материале
«выбран правильный» доказывалось бы отсутствием второго кандидата, а не
сравнением.
"""
from __future__ import annotations

import unittest

from kukai.ir.compiler import compile_program
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT

KNOWN = "Бетон М300"
OTHER = "Кирпич керамический"


def program(value):
    return {"ir_version": "1.0", "intent": "материал несущей конструкции",
            "ops": [{"op": "set_param", "id": "SP1",
                     "target": {"by": "element_id", "value": 9001},
                     "param": "Материал несущих конструкций",
                     "value": value}]}


def codes(result):
    return [getattr(d, "code", "") for d in (result.diagnostics or [])]


class AReferenceValueCompiles(unittest.TestCase):

    def test_the_emission_resolves_writes_and_witnesses(self):
        r = compile_program(program({"material": KNOWN}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(r.ok, codes(r))
        cs = r.csharp
        self.assertIn("OfClass(typeof(Material))", cs)   # разрешение
        self.assertIn(KNOWN, cs)
        self.assertIn("Set(__rf_SP1.Id)", cs)            # ЗАПИСЬ ссылкой
        self.assertIn("AsElementId()", cs)               # СВИДЕТЕЛЬ
        self.assertIn("не найден в документе", cs)       # живой отказ ОСТАЛСЯ

    def test_the_pool_has_more_than_one_entry(self):
        """Иначе «выбран правильный» доказано отсутствием конкурента."""
        self.assertGreaterEqual(len(GROUND_SNAPSHOT["materials"]), 2)


class TheRefusalArrivesOffline(unittest.TestCase):
    """Контроль-FAIL, без которого зелёное выше ничего не значит."""

    def test_an_unknown_material_refuses_before_revit(self):
        r = compile_program(program({"material": "Такого материала нет"}),
                            "2024", snapshot=GROUND_SNAPSHOT)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G101", codes(r))
        self.assertIn("известно", r.diagnostics[0].message_ru,
                      "отказ обязан печатать ЗНАМЕНАТЕЛЬ — сколько материалов "
                      "он вообще видел")

    def test_an_empty_pool_refuses_and_does_not_pass_silently(self):
        snap = {**GROUND_SNAPSHOT, "materials": []}
        r = compile_program(program({"material": KNOWN}), "2024", snapshot=snap)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G104", codes(r))

    def test_both_pool_entries_are_reachable_not_just_the_first(self):
        for name in (KNOWN, OTHER):
            with self.subTest(material=name):
                r = compile_program(program({"material": name}), "2024",
                                    snapshot=GROUND_SNAPSHOT)
                self.assertTrue(r.ok, codes(r))
                self.assertIn(name, r.csharp)


class PhaseIsTheSecondKindAndUsesTheSameMachinery(unittest.TestCase):
    """Второй род ссылки. Приём ОДИН, различаются класс Ревита и слово отказа.

    Фаза взята второй по тому, что мешает МОДЕЛИ, а не по алфавиту: каждый
    настоящий проект фазирован, и элемент, легший не в ту фазу, не показывается
    на нужных видах — здание ВЫГЛЯДИТ построенным и не является им.
    """

    def test_a_known_phase_compiles_with_its_own_revit_class(self):
        r = compile_program(program({"phase": "Новая конструкция"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(r.ok, codes(r))
        self.assertIn("OfClass(typeof(Phase))", r.csharp)
        self.assertIn("Set(__rf_SP1.Id)", r.csharp)
        self.assertIn("AsElementId()", r.csharp)

    def test_an_unknown_phase_refuses_offline(self):
        r = compile_program(program({"phase": "Такой фазы нет"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G101", codes(r))

    def test_an_empty_phase_pool_refuses(self):
        r = compile_program(program({"phase": "Новая конструкция"}), "2024",
                            snapshot={**GROUND_SNAPSHOT, "phases": []})
        self.assertFalse(r.ok)
        self.assertIn("KIR-G104", codes(r))

    def test_the_refusal_agrees_with_the_gender_of_the_thing_it_names(self):
        """«фаза не найден» — не опечатка, а английская грамматика в русском
        продукте. Проверяется потому, что причастие пишется РЯДОМ с родом и
        разъезжается молча."""
        r = compile_program(program({"phase": "Нет такой"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertIn("не найдена", r.diagnostics[0].message_ru)
        r = compile_program(program({"material": "Нет такого"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertIn("не найден", r.diagnostics[0].message_ru)

    def test_the_two_kinds_do_not_leak_into_each_other(self):
        mat = compile_program(program({"material": KNOWN}), "2024",
                              snapshot=GROUND_SNAPSHOT)
        pha = compile_program(program({"phase": "Существующие"}), "2024",
                              snapshot=GROUND_SNAPSHOT)
        self.assertNotIn("typeof(Phase)", mat.csharp)
        self.assertNotIn("typeof(Material)", pha.csharp)


class AWorksetIsNotAReferenceAndUsesItsOwnMachinery(unittest.TestCase):
    """ТРЕТИЙ ПРИЗНАК — И ОН НЕ ТРЕТИЙ РОД ССЫЛКИ.

    Замерено по индексу ловушек 13.08.2026 и подтверждено Roslyn на шести
    версиях зоной «ворота»: `Parameter.Set(WorksetId)` не существует (CS1503
    6/6), `Workset` не наследует `Element`, `.Id` у него нет, коллектор свой,
    адрес — `WorksetId.IntegerValue`. Приём ссылки не применим НИ В ОДНОМ из
    четырёх шагов, поэтому у набора свой род значения, своя запись `Set(int)`
    и свой свидетель `AsInteger()`.

    ПОЧЕМУ ЭТО ВАЖНЕЕ САМОЙ СПОСОБНОСТИ: таблица `_REF_POOLS` сделала второй
    род дешёвым и ровно поэтому опасна на третьем — строка, добавленная по
    аналогии, дала бы способность, которая ВЫГЛЯДИТ как две доказанные.
    Проверка применимости есть ЦЕНА обобщения.
    """

    def test_the_emission_uses_the_workset_collector_not_the_element_one(self):
        r = compile_program(program({"workset": "АР_Стены"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(r.ok, codes(r))
        cs = r.csharp
        self.assertIn("FilteredWorksetCollector", cs)
        self.assertIn("Id.IntegerValue", cs)
        self.assertIn("AsInteger()", cs)          # свидетель ТОГО ЖЕ рода
        self.assertNotIn("typeof(Workset)", cs,   # Workset не Element
                         "набор не собирается коллектором ЭЛЕМЕНТОВ")

    def test_the_document_must_be_workshared_and_the_guard_is_emitted(self):
        r = compile_program(program({"workset": "АР_Стены"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertIn("!doc.IsWorkshared", r.csharp,
                      "живая проверка разделённости обязана остаться: снимок "
                      "мог устареть между съёмкой и исполнением")

    def test_an_unshared_document_refuses_with_its_own_reason(self):
        """Пустой пул на два исхода — форма 11. Здесь их различает флаг."""
        snap = {**GROUND_SNAPSHOT, "worksets__workshared": False,
                "worksets": []}
        r = compile_program(program({"workset": "АР_Стены"}), "2024",
                            snapshot=snap)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G104", codes(r))
        self.assertIn("не разделён", r.diagnostics[0].message_ru)

    def test_a_workset_with_id_zero_is_reachable(self):
        """`WorksetId.IntegerValue` начинается с НУЛЯ, а пул элементов — с 1.

        Именно на этом компилятор поймал первую редакцию: `snapshot_pool`
        требует `1 <= id`, потому что «пул» здесь означает пул ЭЛЕМЕНТОВ.
        Проверка была права; неверной была попытка объявить набор пулом.
        """
        r = compile_program(program({"workset": "Общие уровни и оси"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertTrue(r.ok, codes(r))

    def test_an_unknown_workset_refuses_offline(self):
        r = compile_program(program({"workset": "Нет такого"}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G101", codes(r))

    def test_a_malformed_workset_row_is_refused_not_silently_skipped(self):
        snap = {**GROUND_SNAPSHOT,
                "worksets": [{"id": -1, "name": "битый"}]}
        r = compile_program(program({"workset": "битый"}), "2024",
                            snapshot=snap)
        self.assertFalse(r.ok)
        self.assertIn("KIR-G106", codes(r))


class TheOldValueKindsAreUntouched(unittest.TestCase):
    """Ветка добавлена РЯДОМ, а не вместо: три прежних рода обязаны работать."""

    def test_string_number_and_flag_still_compile(self):
        for value, label in (("МаркаТекстом", "строка"),
                             ({"value": 250.0, "unit": "mm"}, "мм"),
                             (True, "флаг")):
            with self.subTest(kind=label):
                r = compile_program(program(value), "2024",
                                    snapshot=GROUND_SNAPSHOT)
                self.assertTrue(r.ok, f"{label}: {codes(r)}")
                self.assertNotIn("__rf_SP1", r.csharp,
                                 "не-ссылочное значение не должно тянуть "
                                 "разрешение материала")


class TheShapeIsRefusedLoudlyWhenMalformed(unittest.TestCase):

    def test_an_empty_material_name_is_refused_not_coerced(self):
        r = compile_program(program({"material": "   "}), "2024",
                            snapshot=GROUND_SNAPSHOT)
        self.assertFalse(r.ok)


if __name__ == "__main__":
    unittest.main()
