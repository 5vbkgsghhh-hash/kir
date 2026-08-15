"""ОТКАЗ — ЭТО ИНТЕРФЕЙС, И ПРИБОР ОБЯЗАН ЕГО СОХРАНЯТЬ.

ЗАМЕР 11.08.2026, здание `sob62_r23_v6` из корпуса. `compile_gate_offline`
собирал из каждого отказа ТОЛЬКО `d.code`:

    refused[(version, tuple(sorted({d.code for d in out.diagnostics}))[:2])] += 1

и печатал `отказ эмиссии 1 ('2021', ('KIR-G102',))`. Всё остальное —
`field_name`, `message_ru`, `candidates` — вычислялось компилятором и
выбрасывалось.

ПОЧЕМУ ЭТО НЕ КОСМЕТИКА. Канон этого проекта: отказ обязан НАЗЫВАТЬ СЛЕДУЮЩИЙ
ХОД. Компилятор своё обязательство выполняет — настоящее сообщение той находки
звучит так:

    field      system_type
    message    «piping_system_types: несколько вариантов — default невозможен,
                уточните через {"by": "element_id", "value": <id из candidates>}»
    candidates [{'id': 246258, 'name': 'Приточная жидкость'}, …]

Прибор превращал это обратно в КОД ОШИБКИ. На своде из 55 зданий разница
между «где-то отказывают» и «отказывают ЗДЕСЬ и вот почему» — это и есть вся
ценность свода; без неё каждую находку приходится добывать заново отдельным
зондом, что и стоило двух прогонов в день, когда это заметили.

ЧЕГО ЭТОТ ТЕСТ НЕ ПОКРЫВАЕТ: он не проверяет, что сообщение ПОЛЕЗНО — только
что прибор его не теряет. Качество формулировки — обязательство компилятора, и
оно закрыто в другом месте (`test_diag_*`).
"""
from __future__ import annotations

import unittest

from kukai.ir import diag


class _Out:
    """Форма ответа компилятора ровно в той части, которую читает прибор."""

    def __init__(self, diagnostics):
        self.ok = False
        self.csharp = ""
        self.diagnostics = list(diagnostics)


def _ambiguous() -> diag.Diagnostic:
    """Настоящая находка корпуса, а не выдуманная: `sob62_r23_v6`, оп 191."""
    return diag.Diagnostic(
        code="KIR-G102",
        message_ru=("piping_system_types: несколько вариантов — default "
                    'невозможен, уточните через {"by": "element_id", '
                    '"value": <id из candidates>}'),
        op_index=191, op_id="e21201143", field_name="system_type",
        candidates=[{"id": 246258, "name": "Приточная жидкость"},
                    {"id": 246259, "name": "Обратная жидкость"}])


class TheGateKeepsWhatTheCompilerSaid(unittest.TestCase):

    def test_the_refusal_payload_survives_the_instrument(self) -> None:
        from tools import compile_gate_offline as gate

        rows = gate.refusal_rows([("2021", _ambiguous())])
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["code"], "KIR-G102")
        self.assertEqual(row["field"], "system_type")
        self.assertIn("piping_system_types", row["message"])
        # СЛЕДУЮЩИЙ ХОД — часть отказа, а не украшение: без него читатель
        # знает, что отказали, и не знает, что делать.
        self.assertIn('"by": "element_id"', row["message"])
        self.assertEqual(row["candidates"], 2)
        self.assertEqual(row["versions"], ["2021"])

    def test_one_cause_on_six_versions_is_one_row_not_six(self) -> None:
        """Один и тот же отказ на шести версиях — ОДНА причина. Шесть строк
        читались бы как шесть находок и раздували бы любой рейтинг."""
        from tools import compile_gate_offline as gate

        rows = gate.refusal_rows(
            [(v, _ambiguous()) for v in
             ("2021", "2022", "2023", "2024", "2025", "2026")])
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["versions"],
                         ["2021", "2022", "2023", "2024", "2025", "2026"])
        self.assertEqual(rows[0]["count"], 6)

    def test_a_version_specific_refusal_stays_distinguishable(self) -> None:
        """`KIR-E003` на 2021 и ни на одной другой — факт о ПОКРЫТИИ версий, и
        он обязан быть виден: здание, выразимое на пяти версиях из шести, — это
        свойство продукта, а не шум (замер: `sob62_fas_r23_v10`)."""
        from tools import compile_gate_offline as gate

        e003 = diag.Diagnostic(code="KIR-E003",
                               message_ru="оп не поддержан на этой версии",
                               field_name=None)
        rows = gate.refusal_rows([("2021", e003), ("2021", e003)])
        self.assertEqual(rows[0]["versions"], ["2021"])
        self.assertEqual(rows[0]["count"], 2)

    def test_a_diagnostic_without_extras_still_produces_a_row(self) -> None:
        """Граница: отказ без поля и без кандидатов не обязан их выдумывать, но
        обязан остаться СТРОКОЙ. Пустое поле и отсутствующая строка — разные
        факты, и второе — это снова потеря интерфейса."""
        from tools import compile_gate_offline as gate

        bare = diag.Diagnostic(code="KIR-X999", message_ru="")
        rows = gate.refusal_rows([("2026", bare)])
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["field"])
        self.assertEqual(rows[0]["candidates"], 0)
        self.assertEqual(rows[0]["message"], "")


if __name__ == "__main__":
    unittest.main()
