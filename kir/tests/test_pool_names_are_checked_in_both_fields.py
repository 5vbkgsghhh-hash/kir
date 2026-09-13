"""THE CLOSED POOL DICTIONARY GUARD READ ONLY HALF OF ITS INPUT.

🔴 WHY (24.08.2026, audit finding, confirmed against the DEFINITION SITES).

An op's pool name lives in TWO fields:

    `OpSpec.grounded`                  static: (param, pool, required)
    `OpSpec.grounded_pool_by_param`    table: parameter -> value -> pool

The second is not decoration: it is exactly what `grounded_for(op)` reads,
that is EXECUTION (`ground.py`) and the static consumers
(`open_model.required_grounding_pools`, which assembles the snapshot).

`spec._lint_registry` iterated ONLY over the first. `registry_base.__post_init__`
does check the table — but only for the fact that it names GROUNDED FIELDS;
POOL names are not checked against anything there.

**The price is a refusal that names the wrong cause.** A typo in the table
slips through silently, `create_wall_type(host_kind="roof")` grounds into a
pool that does not exist, the snapshot for that pool never arrives, and the
author gets `KIR-G101 «тип не найден»` — they go looking for a missing
type, when what is actually missing is the POOL. Exactly the kind of
refusal this table was set up to eliminate.
"""
from __future__ import annotations

import copy
import unittest

from kir import spec


class ИмяПулаСверяетсяВОБОИХПолях(unittest.TestCase):

    def setUp(self):
        self.op = spec.OPS["create_wall_type"]
        self.assertIsNotNone(self.op.grounded_pool_by_param,
                             "проба опирается на оп С таблицей по параметру")

    def _с_подменой(self, table):
        gname, _ = self.op.grounded_pool_by_param
        поддельный = copy.copy(self.op)
        object.__setattr__(поддельный, "grounded_pool_by_param",
                           (gname, table))
        return поддельный

    def test_реестр_как_есть_ЗЕЛЁН(self):
        """PASS CONTROL: without it, the red below would mean nothing."""
        spec._lint_registry()

    def test_опечатка_в_таблице_по_параметру_КРАСНИТ(self):
        """🔴 RED before the fix: the guard did not see this half."""
        _, gtable = self.op.grounded_pool_by_param
        битая = {k: dict(v) for k, v in gtable.items()}
        битая["roof"]["source_type"] = "ROOF_TYPES_TYPO"
        старый = spec.OPS["create_wall_type"]
        try:
            spec.OPS["create_wall_type"] = self._с_подменой(битая)
            with self.assertRaises(AssertionError) as поймано:
                spec._lint_registry()
            self.assertIn("ROOF_TYPES_TYPO", str(поймано.exception))
        finally:
            spec.OPS["create_wall_type"] = старый

    def test_опечатка_в_СТАТИЧЕСКОМ_поле_по_прежнему_КРАСНИТ(self):
        """CONTROL: the fix has no right to weaken the half that worked."""
        старый = spec.OPS["create_wall_type"]
        поддельный = copy.copy(старый)
        object.__setattr__(поддельный, "grounded",
                           (("source_type", "WALL_TYPES_TYPO", True),))
        try:
            spec.OPS["create_wall_type"] = поддельный
            with self.assertRaises(AssertionError) as поймано:
                spec._lint_registry()
            self.assertIn("WALL_TYPES_TYPO", str(поймано.exception))
        finally:
            spec.OPS["create_wall_type"] = старый

    def test_все_пулы_таблиц_реально_попадают_в_проверку(self):
        """Denominator not zero: how many ops even have such a table at all.

        "No reds" with zero places examined is not a result.
        """
        с_таблицей = [o.name for o in spec.OPS.values()
                      if o.grounded_pool_by_param is not None]
        self.assertGreaterEqual(len(с_таблицей), 1, с_таблицей)
        пулов = sum(len(pools)
                    for o in spec.OPS.values()
                    if o.grounded_pool_by_param is not None
                    for pools in o.grounded_pool_by_param[1].values())
        self.assertGreaterEqual(пулов, 4,
                                "проверка обязана видеть НЕСКОЛЬКО имён")


if __name__ == "__main__":
    unittest.main()
