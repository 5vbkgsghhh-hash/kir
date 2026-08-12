"""Самая крупная причина отказа в корпусе не называла, ЧЕГО не хватает.

ЗАМЕР 10.08.2026, `tools/coverage_matrix.py` по 67 разборам на диске
(машинно-локальный корпус, 4.1 ГБ). Карта причин ранжирует их по числу
ЗАТРОНУТЫХ ДОКУМЕНТОВ, и первой строкой стоит:

    10 документов из 10, 77 733 элемента
    «category is outside the exact Part 5 lifter table»

Это не только самая массовая причина корпуса — это ЕДИНСТВЕННАЯ причина,
задевающая ВСЕ документы. И действовать по ней нельзя: она не говорит, какая
категория. Семьдесят семь тысяч элементов десяти зданий сложены в одну
непрозрачную строку, а решение, которое по ней принимают, — что строить
следующим.

Разложение по категориям и есть тот самый ранжир. Категория — это КЛАСС, а не
экземпляр, поэтому свёртка переменных данных в `coverage_matrix` (та, что
складывает индексы рёбер и id родителей, чтобы одна причина не рассыпалась в
строку на элемент) её намеренно не трогает: имя категории не берётся в
кавычки и не содержит отдельно стоящих чисел.

Цена молчания в этом же файле уже оплачена дважды и записана в `lift.py`:
одна и та же популяция стояла в карте причин ДВАЖДЫ под разными именами
(28 926 «outside the … lifter table» и 8 207 «absent from the family placement
side index»), и, цитируя тот комментарий, «двоение в нём дороже любого
процента покрытия». Здесь тот же класс на порядок крупнее.
"""
from __future__ import annotations

import copy
import unittest
from typing import Any

from kukai.ir.decompile.lift import AtomReason, lift_document_detailed
from kukai.ir.decompile.schema import L0Document
from kukai.ir.decompile.tests.fixtures_decompile import (
    make_element, project1_metadata,
)

#: Категория заведомо вне таблицы лифтеров — вопрос теста не в ней, а в том,
#: НАЗЫВАЕТ ли её отказ.
_UNSUPPORTED = "OST_RasterImages"


def _document(elements: list[dict[str, Any]]) -> L0Document:
    row = copy.deepcopy(project1_metadata())
    row["change_stamp"] = "synthetic-no-lifter-v1"
    row["elements"] = copy.deepcopy(elements)
    row["category_status"] = []
    return L0Document.from_dict(row)


class NoLifterNamesTheCategory(unittest.TestCase):

    def test_the_atom_says_which_category_has_no_lifter(self):
        row = make_element(_UNSUPPORTED, 9001, ordinal=0)
        result = lift_document_detailed(_document([row]))

        node = result.nodes[0]
        self.assertEqual(node["kind"], "atom")
        self.assertEqual(len(result.diagnostics), 1)
        diag = result.diagnostics[0]
        self.assertIs(diag.reason, AtomReason.NO_LIFTER)
        # Прежняя формулировка остаётся — по ней ищут и на неё ссылаются три
        # других теста и комментарии в lift.py; добавляется НЕДОСТАЮЩЕЕ.
        self.assertIn("outside the exact Part 5 lifter table", diag.detail)
        self.assertIn(_UNSUPPORTED, diag.detail)
        self.assertEqual(node["reason"]["detail"], diag.detail)

    def test_two_unsupported_categories_are_two_causes_not_one(self):
        """Ранжир обязан различать их: это две РАЗНЫЕ строки таблицы
        категорий и две разные работы, а не одна большая."""
        rows = [make_element(_UNSUPPORTED, 9002, ordinal=0),
                make_element("OST_MEPSpaces", 9003, ordinal=1)]
        result = lift_document_detailed(_document(rows))

        details = {d.detail for d in result.diagnostics}
        self.assertEqual(len(details), 2, details)


if __name__ == "__main__":
    unittest.main()
