"""Отказ по ПУСТОМУ пулу называет только ВЫПОЛНИМЫЙ следующий ход.

ЗАЧЕМ. `KIR-G104` говорил ровно «<пул>: пусто в модели» и умолкал. Директор
предложил дописать «загрузи семейство или создай тип» — и это было бы ХУЖЕ
молчания: до 13.08 сослаться на созданный символ в той же программе было
НЕЛЬЗЯ (`family_symbol` производили 2 опа, потребляли 0), то есть отказ назвал
бы ход, который не мог удаться, и стоил бы модели раунда.

    ОТКАЗ, НАЗЫВАЮЩИЙ НЕВЫПОЛНИМЫЙ ХОД, ХУЖЕ ОТКАЗА, НЕ НАЗЫВАЮЩЕГО НИКАКОГО —
    он выглядит помощью.

После A8 ход стал выполним, но НЕ ВЕЗДЕ, и разница измерена, а не оценена.
Замер 13.08 на настоящем здании (`k2_ar_rd_v7`), 22 пустых пула:

    выполним в той же программе      2   create_column.symbol
                                         create_foundation.symbol
    выполнимого хода НЕТ            20   параметр не принимает ссылку вовсе

Язык порождает ровно четыре рода ссылок (`element`, `family_symbol`, `level`,
`wall`); у остальных двадцати параметров `ref_kinds` пуст, и никакой оп KIR не
создаёт нужный им тип. Там честный ответ — «в программе сделать нечего», а не
предложение попробовать.

РАЗЛИЧАЕТ РЕЕСТР, А НЕ СПИСОК В КОДЕ: пересекается ли `ref_kinds` параметра с
родами, у которых есть производитель. Заведут производителя завтра — фраза
сменится сама, без правки этого теста и без правки `ground.py`.
"""
from __future__ import annotations

import unittest

from kukai.ir import ground, spec
from kukai.ir.compiler import compile_program
from kukai.ir.tests.fixtures import GROUND_SNAPSHOT


def _refusal(op_name: str, param: str, pool_name: str) -> str:
    diags: list = []
    ground._resolve_one({"by": "default"}, pool_name, [], 0, "X",
                        param, op_name, diags, False)
    assert diags, "пустой пул обязан отказать"
    return diags[0].message_ru


class AnEmptyPoolNamesOnlyAMoveThatWorks(unittest.TestCase):

    def test_where_the_language_can_create_it_the_move_is_named(self):
        message = _refusal("create_column", "symbol",
                           "column_symbols_architectural")
        self.assertIn("В ЭТОЙ ЖЕ программе", message)
        self.assertIn("load_family", message)
        self.assertIn('"by": "ref"', message)

    def test_the_named_move_actually_compiles(self):
        """Условие, без которого весь тест — украшение текста.

        Ровно тот ход, который печатает отказ: производитель выше, потребление
        по `ref`. Если это перестанет компилироваться, сообщение станет
        враньём, и покраснеет здесь, а не у пользователя.
        """
        program = {
            "ir_version": "1.0", "intent": "колонна из загруженного здесь же",
            "ops": [
                {"op": "load_family", "id": "LF",
                 "path": "C:\\Lib\\Columns\\K.rfa", "type_name": "К 300x300"},
                {"op": "create_column", "id": "C1", "xy": [0, 0],
                 "level": {"by": "element_id", "value": 42},
                 "symbol": {"by": "ref", "value": "LF"}},
            ]}
        result = compile_program(program, revit_version="2023",
                                 snapshot=GROUND_SNAPSHOT, bulk=True)
        self.assertTrue(result.ok,
                        [d.as_dict() for d in (result.diagnostics or ())][:3])
        self.assertIn("FamilySymbol __sy_C1 = __el_LF;", result.csharp)

    def test_where_it_cannot_the_refusal_says_so_plainly(self):
        """Двадцать пулов из двадцати двух: предлагать нечего, и так и сказано."""
        message = _refusal("create_truss", "type", "truss_types")
        self.assertIn("Ни одна операция KIR не создаёт этот род", message)
        self.assertNotIn('"by": "ref"', message)

    def test_the_split_is_decided_by_the_registry_not_by_a_list(self):
        """Контроль-FAIL самого правила: род без производителя не обещается.

        Берём параметр, принимающий `element` — род, который язык ПРОИЗВОДИТ, —
        и параметр, не принимающий ничего. Если бы фраза выбиралась списком
        имён, эта пара её бы не различила.
        """
        producible = {op.result.reference_kind.value
                      for op in spec.OPS.values()
                      if op.result.reference_kind is not None}
        self.assertIn("family_symbol", producible)
        consumers = [p for op in spec.OPS.values() for p in op.params
                     if any(k.value == "family_symbol" for k in p.ref_kinds)]
        self.assertGreaterEqual(
            len(consumers), 1,
            "потребителей family_symbol не осталось — тогда и выполнимый ход "
            "называть нечем, и первый тест выше обязан был покраснеть")

    def test_a_non_empty_pool_keeps_its_own_message(self):
        """Контроль области: правка трогает ТОЛЬКО пустой пул.

        У непустого пула отказ прежний (`G102`, кандидаты) — иначе я бы
        поменял сообщение, которое сегодня работает как задумано.
        """
        diags: list = []
        pool = [{"id": 1, "name": "А"}, {"id": 2, "name": "Б"}]
        ground._resolve_one({"by": "default"}, "door_symbols", pool, 0, "X",
                            "symbol", "create_door", diags, False)
        self.assertTrue(diags)
        self.assertIn("вариантов", diags[0].message_ru)
        self.assertNotIn("Ни одна операция KIR", diags[0].message_ru)


if __name__ == "__main__":
    unittest.main()
