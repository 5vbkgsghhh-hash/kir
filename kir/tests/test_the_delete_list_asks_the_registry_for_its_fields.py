"""THE DELETION LIST ASKS THE REGISTRY FOR ITS FIELDS, RATHER THAN ENUMERATING THEM ITSELF.

🔴 WHY THIS FILE. `idempotence.collect_created_ids` gathers what A5 will
DELETE from the live model after a rebuild. Before 04.09.2026 it read a
LITERAL, `value.get("id") or value.get("element_id")` — a second carrier of
the knowledge "what an op calls the thing it created." The first carrier is
the registry (`ResultSpec.identity_field`), and
`created_ledger.created_keys()` now asks that one instead, declaring the
list "complete BY CONSTRUCTION."

The two carriers diverged on the very day `create_railing` became MANY:

    railing_ids: ["101", "102"]   ->  collect_created_ids returned  []

That is, on rollback NOT A SINGLE stair railing was deleted, even though
two had been created. `segment_ids` suffered the same illness. The cost
here is extreme and ASYMMETRIC: an omission leaves ORPHANS in the live
model, an extra name would delete SOMETHING ELSE'S.

WHAT THIS FILE HOLDS — not the list of fields (that belongs to the
registry), but the LINK: every identity field of something created must
reach the deletion list, and a plural one must reach it IN FULL.
"""
from __future__ import annotations

import unittest

from kir.address import created_identity_fields
from kir.idempotence import collect_created_ids


def _envelope(op_id: str, **поля: object) -> dict:
    return {"ok": True, "result": {op_id: dict(поля)}}


class СписокУдаленияЕдетЗаРеестром(unittest.TestCase):

    def test_каждое_реестровое_поле_доезжает_до_списка(self) -> None:
        """A link, not an enumeration: a new registry field lands here BY
        ITSELF."""
        for поле in created_identity_fields():
            with self.subTest(поле=поле):
                итог = collect_created_ids([_envelope("X1", **{поле: "4242"})])
                self.assertEqual(
                    итог, ["4242"],
                    f"поле {поле!r} объявлено реестром как идентичность "
                    f"созданного, но до списка удаления не доехало: элемент "
                    f"остался бы СИРОТОЙ в живой модели")

    def test_множественное_доезжает_ЦЕЛИКОМ(self) -> None:
        """Half of what was stripped is worse than zero: one railing out of
        two is garbage."""
        итог = collect_created_ids(
            [_envelope("R1", railing_ids=["101", "102"])])
        self.assertEqual(итог, ["101", "102"], итог)

    def test_квитанция_моста_не_потеряна(self) -> None:
        """`element_id` is a receipt form of the BRIDGE, the registry knows
        nothing of it."""
        self.assertEqual(
            collect_created_ids([_envelope("W1", element_id="7")]), ["7"])

    def test_изменённое_в_список_НЕ_идёт(self) -> None:
        """A CONTROL IN THE OTHER DIRECTION. Deleting something else's is
        worse than leaving your own.

        Without this experiment, a change that "puts everything into the
        list indiscriminately" would pass both assertions above and look
        just as green.
        """
        self.assertEqual(
            collect_created_ids([_envelope("W1", id="101", created=False)]), [])

    def test_булево_не_становится_адресом(self) -> None:
        """A CONTROL: `True` is not the element 1. The same kind that was
        closed in open_model."""
        self.assertEqual(collect_created_ids([_envelope("W1", id=True)]), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
