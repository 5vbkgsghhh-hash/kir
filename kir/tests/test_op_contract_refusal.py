"""A writing op with no refinement entry must REFUSE in a typed way, not
panic.

A guard on a seam that was open before this wave: `contract_for` raises
`OpContractError` (a subclass of `ValueError`, but NOT
`PlanEncodingError`), while the handler in `plan_program` caught only
`PlanEncodingError`. The refusal went straight through and became a
compiler panic at the `plan` stage — meaning the refusal stopped naming a
next move.

The only pre-check that all registry contracts even build at all is
`audit_contract_kernel()`, and it is called only from the offline gate
(`gate_runner`). The guarantee is declared in the gate, read in the
compiler, and nothing forces them to agree: exactly the named class of
defect.

WHY THE TABLE IS SUBSTITUTED, NOT EDITED. `translation_cert.REFINEMENT` is a
module-level cache. Mutating it in place (`table.pop(...)`) would start a
test dependent on ordering: on a failure between the `pop` and the
restoration, every subsequent test would see a truncated registry.
`patch.object` swaps the REFERENCE for a copy and restores the original
even on an exception, so the real table does not change for even a moment.
"""
from __future__ import annotations

import unittest
from unittest import mock

from kir import translation_cert
from kir.compiler import plan_program
from kir.diag import KirRefusal

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

        # The real table was left untouched — otherwise the test itself
        # would become a source of the order-dependence it exists to rule
        # out.
        self.assertIn(OP, translation_cert._ensure_table())

        diagnostics = caught.exception.diagnostics
        self.assertTrue(diagnostics, "отказ без диагностики не называет ход")
        diagnostic = diagnostics[0]
        self.assertEqual(diagnostic.code, "KIR-L007")
        self.assertEqual(diagnostic.got, OP, "отказ не называет оп")
        self.assertEqual(diagnostic.op_id, "W1", "отказ не называет строку программы")

    def test_the_refusal_is_not_a_bare_value_error(self) -> None:
        """KirRefusal — not just any ValueError: a plan-stage panic would
        come back looking exactly like that."""
        table = translation_cert._ensure_table()
        without_op = {name: spec for name, spec in table.items() if name != OP}
        with mock.patch.object(translation_cert, "REFINEMENT", without_op):
            try:
                plan_program(PROGRAM)
            except KirRefusal:
                pass
            except ValueError as exc:  # pragma: no cover — this is exactly the regression
                self.fail(
                    "отсутствие уточнения снова роняет запись нетипизированно: "
                    f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    unittest.main()
