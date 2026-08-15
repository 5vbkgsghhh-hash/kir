"""Пишущий оп без строки уточнения обязан ОТКАЗАТЬ типизированно, а не паниковать.

Страж шва, который до этой волны был открыт: `contract_for` поднимает
`OpContractError` (подкласс `ValueError`, но НЕ `PlanEncodingError`), а
обработчик в `plan_program` ловил только `PlanEncodingError`. Отказ уходил
насквозь и становился паникой компилятора на стадии `plan` — то есть отказ
переставал называть следующий ход.

Единственная предварительная проверка, что все контракты реестра вообще
строятся, — `audit_contract_kernel()`, и зовут её только из офлайн-ворот
(`gate_runner`). Гарантия объявлена в воротах, прочитана в компиляторе, и
совпасть их ничто не заставляет: ровно названный класс дефекта.

ПОЧЕМУ ТАБЛИЦА ПОДМЕНЯЕТСЯ, А НЕ ПРАВИТСЯ. `translation_cert.REFINEMENT` —
кэш уровня модуля. Мутировать его на месте (`table.pop(...)`) значит завести
тест, зависящий от порядка: при падении между `pop` и восстановлением все
последующие тесты увидят урезанный реестр. `patch.object` подменяет ССЫЛКУ на
копию и возвращает оригинал даже при исключении, поэтому настоящая таблица не
меняется ни на мгновение.
"""
from __future__ import annotations

import unittest
from unittest import mock

from kukai.ir import translation_cert
from kukai.ir.compiler import plan_program
from kukai.ir.diag import KirRefusal

OP = "create_wall"

PROGRAM = {
    "ir_version": "1.0",
    "ops": [
        {
            "op": OP,
            "id": "W1",
            "p0_mm": [0, 0],
            "p1_mm": [6000, 0],
            "level": {"by": "name", "value": "Gate L1"},
        }
    ],
}


class WriteOpWithoutRefinementRefuses(unittest.TestCase):
    def test_missing_refinement_row_is_a_typed_refusal_naming_the_op(self) -> None:
        table = translation_cert._ensure_table()
        self.assertIn(OP, table, "фикстура мертва: у опа уже нет уточнения")
        without_op = {name: spec for name, spec in table.items() if name != OP}

        with mock.patch.object(translation_cert, "REFINEMENT", without_op):
            with self.assertRaises(KirRefusal) as caught:
                plan_program(PROGRAM)

        # Настоящая таблица не пострадала — иначе тест сам стал бы
        # источником зависимости от порядка, которую он призван исключить.
        self.assertIn(OP, translation_cert._ensure_table())

        diagnostics = caught.exception.diagnostics
        self.assertTrue(diagnostics, "отказ без диагностики не называет ход")
        diagnostic = diagnostics[0]
        self.assertEqual(diagnostic.code, "KIR-L007")
        self.assertEqual(diagnostic.got, OP, "отказ не называет оп")
        self.assertEqual(diagnostic.op_id, "W1", "отказ не называет строку программы")

    def test_the_refusal_is_not_a_bare_value_error(self) -> None:
        """KirRefusal — не любой ValueError: паника стадии plan вернулась бы так."""
        table = translation_cert._ensure_table()
        without_op = {name: spec for name, spec in table.items() if name != OP}
        with mock.patch.object(translation_cert, "REFINEMENT", without_op):
            try:
                plan_program(PROGRAM)
            except KirRefusal:
                pass
            except ValueError as exc:  # pragma: no cover — это и есть регресс
                self.fail(
                    "отсутствие уточнения снова роняет запись нетипизированно: "
                    f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    unittest.main()
