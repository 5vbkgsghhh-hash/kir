"""МОЛЧАЛИВОЕ УСЕЧЕНИЕ — ЭТО УТВЕРЖДЕНИЕ «ВОТ ВСЁ» ТАМ, ГДЕ ПРОЧИТАНО НЕ ВСЁ.

`_certify_translation` режет два списка по `_CERT_DIAGNOSTIC_LIMIT = 8`:

    receipt["diagnostics"]     = _certificate_diagnostics(...)[:8]
    receipt["vacuity_partial"] = partial[:8]

и НИ ОДИН ключ квитанции не говорит, что рез был. Читатель видит восемь
диагностик и не имеет ни одного повода думать, что их было двадцать.

ОСОБЕННО ЕДКО У `vacuity_partial`, потому что комментарий СТРОКОЙ ВЫШЕ в
самом `serving.py` говорит: «"Прочитано целиком" и "прочитано кусками" —
разные факты, и второе не смеет читаться как доказательство чистоты». Список,
несущий этот факт, обрезался молча.

ФОРМА ТА ЖЕ, ЧТО У ВСЕЙ СЕРИИ: величина УТВЕРЖДАЕТСЯ в одном месте («вот
диагностики») и ЧИТАЕТСЯ в другом (их было больше), и ничто не заставляет их
совпасть. Лекарство здесь второго рода — не «спросить авторитета», а НАЗВАТЬ
итог рядом с усечённым списком, ровно как это уже делает чек коллизий
(«… список суждений обрезан, показано N»).

ЧЕГО ЭТОТ ТЕСТ НЕ УТВЕРЖДАЕТ. Размер ущерба. Программы, дающей более восьми
диагностик, я не воспроизвёл; наличие дефекта от этого не зависит, а вот его
цена — да, и она здесь НЕ измерена.
"""
from __future__ import annotations

import unittest

from kukai.ir import serving as S


class _Cert:
    """Минимальный двойник сертификата: столько диагностик, сколько нужно."""

    def __init__(self, unproven: int, partial: int):
        self.vacuous = False
        self.proven = False
        self.ops = tuple(
            _OpCert(f"k{i}") for i in range(partial))
        self._unproven = unproven


class _OpCert:
    def __init__(self, key: str):
        self.vacuity_partial = (key,)
        self.op = "create_wall"
        self.clauses = ()


class _Out:
    """Скомпилированная программа ровно в той части, которую читает прибор."""

    def __init__(self, ops: int):
        self.grounded_ops = tuple({"op": "create_wall"} for _ in range(ops))


class TheTruncationNamesItself(unittest.TestCase):
    """Усечение обязано НАЗЫВАТЬСЯ числом, а не молчать."""

    LIMIT = S._CERT_DIAGNOSTIC_LIMIT

    def _receipt(self, diagnostics: int, partial: int) -> dict:
        """Квитанция прибора с заданным числом диагностик и частичных чтений.

        Подменяются ровно две вещи: сборщик диагностик и сертификатор. Всё
        остальное — настоящий `_certify_translation`, иначе тест проверял бы
        свою фантазию, а не прибор.
        """
        from unittest import mock

        from kukai.ir import translation_cert as _cert

        rows = [{"code": "CERT_UNPROVEN", "op_index": i, "op_id": f"o{i}",
                 "message_ru": f"обязательство {i} не разряжено"}
                for i in range(diagnostics)]
        certificate = _Cert(diagnostics, partial)
        with mock.patch.object(S, "_certificate_diagnostics",
                               return_value=rows), \
                mock.patch.object(_cert, "certify_program",
                                  return_value=certificate), \
                mock.patch.object(_cert, "certificate_mode",
                                  return_value="report"):
            return S._certify_translation(_Out(3), "2026")

    def test_a_short_list_is_not_marked_as_cut(self):
        """Пометка, стоящая всегда, — это не пометка: читатель перестаёт её
        видеть через два хода."""
        receipt = self._receipt(2, 2)
        self.assertEqual(len(receipt["diagnostics"]), 2)
        self.assertEqual(receipt.get("diagnostics_total"), 2)
        self.assertEqual(receipt.get("vacuity_partial_total"), 2)

    def test_a_cut_list_says_how_many_there_were(self):
        receipt = self._receipt(self.LIMIT + 12, 2)
        self.assertEqual(len(receipt["diagnostics"]), self.LIMIT)
        self.assertEqual(receipt["diagnostics_total"], self.LIMIT + 12,
                         "усечение молчит: «вот всё» там, где не всё")

    def test_the_partial_reads_say_how_many_there_were(self):
        """Тот самый список, чей собственный комментарий говорит, что
        «прочитано кусками» нельзя читать как доказательство чистоты."""
        receipt = self._receipt(1, self.LIMIT + 5)
        self.assertEqual(len(receipt["vacuity_partial"]), self.LIMIT)
        self.assertEqual(receipt["vacuity_partial_total"], self.LIMIT + 5)

    def test_the_total_is_never_smaller_than_what_is_shown(self):
        for diagnostics, partial in ((0, 0), (3, 1), (self.LIMIT, self.LIMIT),
                                     (self.LIMIT + 1, self.LIMIT + 1)):
            receipt = self._receipt(diagnostics, partial)
            shown = len(receipt.get("diagnostics") or ())
            self.assertGreaterEqual(receipt.get("diagnostics_total", 0), shown)
            shown_p = len(receipt.get("vacuity_partial") or ())
            self.assertGreaterEqual(
                receipt.get("vacuity_partial_total", 0), shown_p)

    def test_a_proven_receipt_carries_no_empty_counters(self):
        """Отсутствующее остаётся отсутствующим: у доказанной программы нет
        ни диагностик, ни их итога — ноль тут читался бы как «считали»."""
        from unittest import mock

        from kukai.ir import translation_cert as _cert

        certificate = _Cert(0, 0)
        certificate.proven = True
        with mock.patch.object(_cert, "certify_program",
                               return_value=certificate), \
                mock.patch.object(_cert, "certificate_mode",
                                  return_value="report"):
            receipt = S._certify_translation(_Out(3), "2026")
        self.assertEqual(receipt["status"], "proven")
        self.assertNotIn("diagnostics", receipt)
        self.assertNotIn("diagnostics_total", receipt)


if __name__ == "__main__":
    unittest.main()
