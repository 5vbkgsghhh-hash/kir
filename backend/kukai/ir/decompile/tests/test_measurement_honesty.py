"""Метрика не должна льстить себе.

Два инварианта честного измерения (арх-разбор 2026-07-25, §3.6):

1. То, что НЕ удалось поднять (атом), обязано остаться в знаменателе.
   Иначе непонятое компилятором молча исчезает из оценки вместо того,
   чтобы её понижать.
2. Нарушенное постусловие не может сосуществовать с вердиктом «успех».
   В режиме ``postconditions="report"`` программа коммитит, записав
   нарушения в ``__results["postcondition_violations"]`` — их обязан
   кто-то прочитать.
"""

from __future__ import annotations

import unittest

from kukai.ir import serving


def _op(l1_id: str, level: str = "Этаж 1") -> dict:
    return {
        "kind": "op",
        "op_name": "create_wall",
        "_id": l1_id,
        "level_name": level,
        "params": {"p0_mm": [0.0, 0.0], "p1_mm": [1000.0, 0.0],
                   "height_mm": 3000.0},
    }


def _atom(l1_id: str, level: str = "Этаж 1") -> dict:
    """Лист, который лифт не смог поднять — типизированный отказ."""
    return {
        "kind": "atom",
        "_id": l1_id,
        "level_name": level,
        "reason": "unsupported_category",
        "params": {},
    }


class AtomsStayInTheDenominator(unittest.TestCase):
    """§3.6: ``atoms_excluded`` структурно 0 — атомы срезаются до замера."""

    def test_unscoped_run_keeps_atoms_visible(self) -> None:
        leaves = [_op("w1"), _atom("a1"), _op("w2")]
        scoped = serving._scope_leaves(leaves)
        atoms = [leaf for leaf in scoped if leaf.get("kind") == "atom"]
        self.assertEqual(
            len(atoms), 1,
            "неподнятый лист обязан дожить до знаменателя метрики, "
            "иначе непонятое компилятором не понижает оценку")

    def test_level_scope_keeps_in_scope_atoms(self) -> None:
        leaves = [_op("w1", "Этаж 1"), _atom("a1", "Этаж 1"),
                  _atom("a2", "Этаж 2")]
        scoped = serving._scope_leaves(leaves, level_scope="Этаж 1")
        atoms = [leaf for leaf in scoped if leaf.get("kind") == "atom"]
        self.assertEqual(
            [leaf["_id"] for leaf in atoms], ["a1"],
            "атом в скоупе обязан остаться; атом вне скоупа — нет")

    def test_only_kinds_keeps_atoms(self) -> None:
        leaves = [_op("w1"), _atom("a1")]
        scoped = serving._scope_leaves(leaves, only_kinds=["create_wall"])
        self.assertEqual(
            sum(1 for leaf in scoped if leaf.get("kind") == "atom"), 1,
            "фильтр по родам не должен прятать неподнятое")


class ReportedViolationsReachTheVerdict(unittest.TestCase):
    """§3.6: нарушения из режима ``report`` не читает никто."""

    def test_violations_in_payload_break_the_all_true_witness(self) -> None:
        payload = {
            "postcondition_violations": [
                "wall w1: length 0 (geometry)",
                "door d1: host missing (topology)",
            ],
        }
        witness = serving._witness_for_success("write", payload)
        self.assertFalse(witness["geometry_ok"])
        self.assertFalse(witness["topology_ok"])
        self.assertTrue(witness["semantic_ok"])
        self.assertEqual(len(witness["violations"]), 2)

    def test_clean_payload_keeps_the_proven_triple(self) -> None:
        witness = serving._witness_for_success("write", {"created": ["1"]})
        self.assertTrue(witness["geometry_ok"])
        self.assertTrue(witness["semantic_ok"])
        self.assertTrue(witness["topology_ok"])
        self.assertNotIn("violations", witness)

    def test_query_family_is_read_only(self) -> None:
        self.assertEqual(
            serving._witness_for_success("query", {}), {"read_only": True})


if __name__ == "__main__":
    unittest.main()
