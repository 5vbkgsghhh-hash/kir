"""СТОРОЖ ВЕРСИОННОЙ ХРУПКОСТИ ОБЯЗАН ЛОВИТЬ ВЕТКУ, А НЕ ЯРЛЫК.

ЧЕМ КУПЛЕН ЭТОТ ФАЙЛ (16.08.2026). Два теста — `test_open_model` и
`test_serving` — держали правило «`IntegerValue` не упоминать» ДВУМЯ копиями
голой подстроки. Волна рабочих наборов законно написала
`__wr["id"] = __w.Id.IntegerValue;`, и оба покраснели. Красный простоял и
читался как дефект компилятора, хотя компилятор был исправен.

ЗАМЕР, РАЗРЕШИВШИЙ СПОР (живой Roslyn, шесть версий, 16.08.2026):

    ElementId.IntegerValue   2021 OK · 2022 OK · 2023 OK · 2024 OK · 2025 OK
                             2026 FAIL (CS1061: нет такого члена)
    WorksetId.IntegerValue   2021 OK · 2022 OK · 2023 OK · 2024 OK · 2025 OK
                             2026 OK

То есть запрет ВЕРЕН и нужен — но ровно для `ElementId`. Подстрока не
различает тип получателя и потому запрещает исправное вместе с опасным.

🔴 ПОЧЕМУ НЕ ПРОСТО СНЯЛИ ПРОВЕРКУ. Снять — значит потерять единственного
сторожа реального версионного отказа на 2026. Поэтому список исключений
ЗАКРЫТ, каждое несёт СВОЙ замер, а этот файл принуждает оба свойства:
исключение работает И правило по-прежнему ловит то, ради чего написано.
"""
from __future__ import annotations

import unittest

from kukai.ir.tests.open_model_guard import (INTEGER_VALUE_EXCEPTIONS,
                                             integer_value_offenders)


class TheGuardMatchesTheBranchNotTheLabel(unittest.TestCase):

    def test_the_measured_safe_use_is_allowed(self):
        """`WorksetId.IntegerValue` — исправен на всех шести, не красный."""
        cs = 'var __w = 1;\n__wr["id"] = __w.Id.IntegerValue;\nreturn "{}";'
        self.assertEqual(integer_value_offenders(cs), [])

    def test_the_measured_dangerous_use_still_reddens(self):
        """ОБРАТНЫЙ ПОЛЮС, без него послабление стало бы глушилкой.

        `ElementId.IntegerValue` отказывает на 2026 — сторож обязан его
        поймать, иначе исключение выродилось в «разрешено всё».
        """
        cs = 'foreach (var __e in xs) { __n += __e.Id.IntegerValue; }'
        offenders = integer_value_offenders(cs)
        self.assertEqual(len(offenders), 1, msg=offenders)
        self.assertIn("__e.Id.IntegerValue", offenders[0])

    def test_a_comment_is_not_code(self):
        """Упоминание в комментарии — не использование.

        Иначе объяснить, ПОЧЕМУ имя запрещено, стало бы невозможно: правило
        запрещало бы собственную документацию. Этот дефект в тот же день был
        куплен на соседнем сторо́же (`_MIGRATION_ADMIN_DEVICE`).
        """
        cs = '// старое имя ElementId.IntegerValue исчезло в 2026\nreturn "{}";'
        self.assertEqual(integer_value_offenders(cs), [])

    def test_the_exception_list_is_closed_and_each_entry_carries_a_measurement(self):
        """Закрытый список объявляет свой род, и каждая строка — с замером."""
        self.assertTrue(INTEGER_VALUE_EXCEPTIONS)
        self.assertLess(len(INTEGER_VALUE_EXCEPTIONS), 5,
                        msg="список исключений разрастается — это уже не "
                            "исключения, а отмена правила")
        for fragment, why in INTEGER_VALUE_EXCEPTIONS.items():
            self.assertIn("IntegerValue", fragment)
            self.assertIn("замер", why.lower(),
                          msg=f"исключение «{fragment}» обосновано доводом, "
                              f"а не замером: {why}")


if __name__ == "__main__":
    unittest.main()
