"""A refusal over an EMPTY pool names only a FEASIBLE next move.

WHY. `KIR-G104` used to say exactly «<пул>: пусто в модели» and go quiet. The director
suggested adding "load a family or create a type" — and that would have been WORSE
than silence: before 13.08, referencing a symbol created in the same program was
IMPOSSIBLE (`family_symbol` was produced by 2 ops, consumed by 0), meaning the refusal would
have named a move that could not succeed, costing the model a round.

    A REFUSAL THAT NAMES AN INFEASIBLE MOVE IS WORSE THAN A REFUSAL NAMING NONE AT ALL —
    it looks like help.

After A8 the move became feasible, but NOT EVERYWHERE, and the difference is measured, not estimated.
Measurement of 13.08 on a real building (`k2_ar_rd_v7`), 22 empty pools:

    feasible in the same program       2   create_column.symbol
                                            create_foundation.symbol
    NO feasible move                  20   the parameter does not accept a reference at all

The language produces exactly four kinds of references (`element`, `family_symbol`, `level`,
`wall`); for the remaining twenty parameters `ref_kinds` is empty, and no KIR op
creates the type they need. There, the honest answer is "there is nothing to do in the program," not
a suggestion to try.

THE DISCRIMINATOR IS THE REGISTRY, NOT A LIST IN THE CODE: whether the parameter's `ref_kinds` intersects with
kinds that have a producer. Give it a producer tomorrow — the phrase
will change on its own, without editing this test and without editing `ground.py`.
"""
from __future__ import annotations

import unittest

from kir import ground, spec
from kir.compiler import compile_program
from kir.tests.fixtures import GROUND_SNAPSHOT


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
        """The condition without which the whole test is just decorative text.

        Exactly the move the refusal prints about: a producer above, consumption
        by `ref`. If this stops compiling, the message becomes
        a lie, and it will turn red here, not for the user.
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
        """Twenty pools out of twenty-two: there is nothing to suggest, and it is said exactly so."""
        message = _refusal("create_truss", "type", "truss_types")
        self.assertIn("Ни одна операция KIR не создаёт этот род", message)
        self.assertNotIn('"by": "ref"', message)

    def test_the_split_is_decided_by_the_registry_not_by_a_list(self):
        """A FAIL control on the rule itself: a kind without a producer is not promised.

        We take a parameter that accepts `element` — a kind the language DOES PRODUCE —
        and a parameter that accepts nothing. If the phrase were chosen from a list of
        names, this pair would not tell the two apart.
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
        """A scope control: the fix touches ONLY the empty pool.

        For a non-empty pool the refusal is unchanged (`G102`, candidates) — otherwise I would have
        changed a message that already works as intended today.
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
