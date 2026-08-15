"""Перепись различает «нет категории» и «спросить не удалось».

До 12.08.2026 в переписи §18.1 стояло `try { __anyCat = __any.Category; } catch { }`,
и элемент, у которого обращение БРОСИЛО, попадал в тот же ключ `no_category`, что
и настоящий бескатегорийный. Отказ ПРИБОРА становился ИЗМЕРЕНИЕМ о модели —
форма 3 канона.

Цена измерена, а не предположена: на `k2_ar_rd_v7` ключ `no_category` несёт
**53 896 элементов = 17.35% документа**, и разложить их по родам из артефактов
НЕЛЬЗЯ — ключ один. Это крупнейшая строка непрочитанного в главном здании
проекта.

ЗАРЯЖЕННАЯ ПРАВКА, а не сделанная: перепись — это эмитируемый C#, поэтому на 77
сохранённых прогонах она не действует ВООБЩЕ, их артефакты сняты старым кодом.
Эффект появится на первом живом извлечении. Тест проверяет ТЕКСТ эмиссии — то
единственное, что проверяемо офлайн.
"""

import unittest

from kukai.ir.decompile.census import (
    CATEGORY_READ_FAILED_KEY,
    NO_CATEGORY_KEY,
)
from kukai.ir.decompile.extract import build_metadata_cs


class CensusCategoryFailureTest(unittest.TestCase):

    def _body(self) -> str:
        return build_metadata_cs()

    def test_both_keys_reach_the_emitted_census(self) -> None:
        """КОНТРОЛЬ-PASS: в эмиссии есть ОБА ключа, а не один."""
        body = self._body()
        self.assertIn(f'"{NO_CATEGORY_KEY}"', body)
        self.assertIn(f'"{CATEGORY_READ_FAILED_KEY}"', body)

    def test_the_catch_no_longer_swallows_silently(self) -> None:
        """КОНТРОЛЬ-FAIL: возврат немого `catch { }` роняет тест.

        Различающее утверждение — именно ПУСТОЙ catch у обращения к категории.
        Пустые catch в других местах переписи законны (там отказ не подменяет
        измерение), поэтому проверяется точная площадка.
        """
        body = self._body()
        self.assertIn("__anyCat = __any.Category;", body,
                      "площадка обращения к категории исчезла из эмиссии")
        self.assertNotIn("try { __anyCat = __any.Category; } catch { }", body,
                         "немой catch вернулся: отказ прибора снова станет "
                         "измерением о модели")

    def test_the_flag_is_raised_only_in_the_catch(self) -> None:
        """Прогон, где ничего не бросает, обязан вести себя как прежде.

        Флаг ставится ТОЛЬКО в обработчике; если он окажется где-то ещё,
        ключ начнёт появляться на здоровых прогонах и раздует строку, которую
        эта правка заводит ради честности.
        """
        body = self._body()
        self.assertIn("catch { __anyCatThrew = true; }", body)
        self.assertEqual(body.count("__anyCatThrew = true"), 1)

    def test_the_two_keys_are_different_predicates(self) -> None:
        """Ключи обязаны различаться — иначе разделение косметическое."""
        self.assertNotEqual(NO_CATEGORY_KEY, CATEGORY_READ_FAILED_KEY)


if __name__ == "__main__":
    unittest.main()
