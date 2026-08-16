"""КАРТА АДРЕСОВ ОБЯЗАНА ПЕРЕЖИТЬ СВОРАЧИВАНИЕ ИСТОРИИ.

🔴 ЗАЧЕМ ЭТОТ ФАЙЛ. Мост `op_id → element_id` гарантирован аппаратом
корректности: `_result_contract_diagnostic` не выпускает наружу ни одной
успешной пишущей программы, у которой хоть у одной операции нет типизированной
идентичности элемента. Ради потребителя этого моста прошли две волны.

И он испарялся через тридцать сообщений. Замер 15.08.2026 НАСТОЯЩИМ
сворачивателем на ПРОД-форме квитанции:

    "assembly_note": "сборка: …"                    ->  строка целиком
    "element_map":   {"w1": ["9001"], "d1": ["5"]}  ->  "<объект, 2 полей — свёрнуто>"

`chat_helpers._summarize_tool_result` сохраняет ТОЛЬКО СКАЛЯРЫ и заменяет
всякий словарь и список на «свёрнуто» — НА ЛЮБОМ УРОВНЕ, верхний не спасает.
Модель пользовалась картой в пределах хода и не могла сослаться на построенное
потом, то есть ровно тогда, когда ссылка и нужна.

🔴 ЭТОТ ТЕСТ ЗОВЁТ ПРОД-КОД, А НЕ СТРОИТ ФОРМУ РУКАМИ (форма 27, куплена
15.08). Тест Ш2 держал форму, которой прод не производит: он был зелен при
разомкнутой петле, потому что сторожил фикстуру. Поэтому здесь зовётся
`serving.lift_element_map` — ровно то, что зовёт живой путь, — и настоящий
`_summarize_tool_result`, а не его пересказ.
"""
from __future__ import annotations

import json
import unittest

from kukai.api.chat_helpers import _summarize_tool_result
from kukai.ir.serving import (ELEMENT_MAP_NOTE_LIMIT, element_map_note,
                              lift_element_map)

#: Прод-форма: словарь на верхнем уровне квитанции, как его кладёт
#: `_handle_revit_ir_inner` рядом с `element_map_error`.
PROD_RECEIPT = {
    "ok": True,
    "kir": {"schema": "kir-result/1"},
    "element_map": {"w1": ["9001"], "d1": ["5"], "m1": ["7", "8"]},
}


def _through_history(receipt: dict) -> dict:
    """Прогнать квитанцию через НАСТОЯЩИЙ сворачиватель и вернуть, что выжило."""
    collapsed = _summarize_tool_result(json.dumps(receipt, ensure_ascii=False), 600)
    body = collapsed[collapsed.index("] ") + 2:]
    return json.loads(body)


class TheMapSurvivesTheCollapse(unittest.TestCase):

    def test_the_flat_note_survives_verbatim(self):
        receipt = dict(PROD_RECEIPT)
        lift_element_map(receipt)                      # то же, что зовёт прод
        survived = _through_history(receipt)
        self.assertIn("element_map_note", survived)
        self.assertIn("w1=9001", survived["element_map_note"])
        self.assertIn("m1=7,8", survived["element_map_note"])

    def test_the_dictionary_is_STILL_collapsed_and_that_is_the_control(self):
        """КОНТРОЛЬ: без него выживание строки ничего не доказывает.

        Если бы сворачиватель хранил и словари, тест выше был бы зелен по
        построению, а починка — лишней."""
        receipt = dict(PROD_RECEIPT)
        lift_element_map(receipt)
        survived = _through_history(receipt)
        self.assertEqual(survived["element_map"], "<объект, 3 полей — свёрнуто>")

    def test_without_the_lift_the_map_is_LOST(self):
        """КОНТРОЛЬ-FAIL: снять подъём — и мост исчезает из истории."""
        survived = _through_history(dict(PROD_RECEIPT))   # подъёма НЕТ
        self.assertNotIn("element_map_note", survived)
        self.assertEqual(survived["element_map"], "<объект, 3 полей — свёрнуто>")

    def test_the_machine_form_is_not_replaced(self):
        """Две формы одного факта, и обе законны: словарь читают в ходу."""
        receipt = dict(PROD_RECEIPT)
        lift_element_map(receipt)
        self.assertEqual(receipt["element_map"], PROD_RECEIPT["element_map"])


class TheNoteNeverLooksCompleteWhileTruncated(unittest.TestCase):
    """Строка, молча оборвавшаяся, хуже отсутствующей: по ней принимают решение
    как по полной. Хвост считается ЗАРАНЕЕ и входит в потолок."""

    def test_a_big_map_declares_what_it_hid(self):
        big = {"op%02d" % i: ["%d" % (9000 + i)] for i in range(40)}
        note = element_map_note(big)
        self.assertLessEqual(len(note), ELEMENT_MAP_NOTE_LIMIT)
        shown = note.count("=")
        hidden = int(note.rsplit("+", 1)[1])
        self.assertEqual(shown + hidden, len(big),
                         "показанное плюс скрытое обязано давать целое")

    def test_a_small_map_has_no_tail(self):
        """КОНТРОЛЬ: хвост появляется только когда есть что скрывать."""
        self.assertNotIn("+", element_map_note({"w1": ["1"]}))

    def test_an_empty_map_says_so_and_is_not_confused_with_a_failed_one(self):
        """Пустая карта и НЕСОБРАВШАЯСЯ — разные факты. Второй несёт
        `element_map_error`, и он скаляр, то есть переживает историю сам."""
        self.assertEqual(element_map_note({}), "элементы: не названы")
        receipt = {"ok": True, "element_map": {}}
        lift_element_map(receipt)
        self.assertNotIn("element_map_note", receipt,
                         "пустой словарь не поднимается: строки о нём нет")


if __name__ == "__main__":
    unittest.main()
