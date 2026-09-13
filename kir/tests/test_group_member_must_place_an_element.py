""""ONE" IS A QUANTITY, NOT A WHAT.

🔴 WHY (25.08.2026, an audit finding, reproduced by a run).

`spec.group_member_yields_one` is the SOLE carrier of the rule "who
qualifies as a group member": BOTH consumers ask it, the validator and the
lifter. It only answered about `identity_cardinality` — that is, about
QUANTITY.

Of the registry's 82 ops, 61 passed as members, and FIVE of them place not
a single BUILDING element into the document: `create_wall_type`,
`create_type`, `create_floor_plan`, `load_family`, `transfer_material`.

Measured before the fix: `authoring_validation.validate()` on a group with a
`create_wall_type` member gave ZERO diagnostics, and `plan_program` on the
same program returned a finished plan. A Revit group is a set of MODEL
ELEMENTS; a wall type and a floor plan are not placed into it.

NO NEW AUTHORITY WAS SET UP: the list already existed —
`acceptance._OPS_WITHOUT_ELEMENTS`, with a reason and a date for every op. A
second such list would have diverged on the very first new op.
"""
from __future__ import annotations

import unittest

from kir import authoring_validation as av
from kir import spec
from kir.acceptance import _OPS_WITHOUT_ELEMENTS


def _группа_с(член: dict) -> dict:
    return {"op": "create_group", "id": "g1", "members": [член],
            "placements": [[0.0, 0.0, 0.0]]}


ТИП_СТЕНЫ = {"op": "create_wall_type", "id": "WT",
             "source_type": {"by": "name", "value": "X"}, "new_name": "Y",
             "layers": [{"width_mm": 100, "function": "Structure"}]}
СТЕНА = {"op": "create_wall", "id": "W", "p0_mm": [0, 0],
         "p1_mm": [6000, 0], "height_mm": 3000,
         "level": {"by": "element_id", "value": 42}}


class ЧленГруппыКЛАДЁТЭЛЕМЕНТ(unittest.TestCase):

    def test_оп_без_элемента_в_члены_НЕ_годится(self):
        """🔴 RED before the fix: the rule answered True."""
        for имя in sorted(_OPS_WITHOUT_ELEMENTS):
            if имя not in spec.OPS:
                continue
            with self.subTest(оп=имя):
                self.assertFalse(spec.group_member_yields_one(имя),
                                 f"{имя} не кладёт элемент здания")

    def test_валидатор_ОТКАЗЫВАЕТ_на_такой_группе(self):
        diags: list = []
        av.validate(_группа_с(ТИП_СТЕНЫ), "create_group", 0, "g1", diags)
        self.assertEqual(len(diags), 1, [str(d.message_ru)[:80] for d in diags])
        self.assertIn("create_wall_type", str(diags[0].as_dict()))

    def test_КОНТРОЛЬ_PASS_обычный_член_по_прежнему_годен(self):
        """Without it, the fix could have banned groups outright."""
        diags: list = []
        av.validate(_группа_с(СТЕНА), "create_group", 0, "g1", diags)
        self.assertEqual(diags, [])
        self.assertTrue(spec.group_member_yields_one("create_wall"))
        self.assertTrue(spec.group_member_yields_one("place_family"))

    def test_знаменатель_не_ноль(self):
        """"None qualifies" would be green and meaningless."""
        годных = [n for n in spec.OPS if spec.group_member_yields_one(n)]
        self.assertGreater(len(годных), 40, len(годных))
        self.assertLess(len(годных), len(spec.OPS))


class АВТОРИТЕТОДИН(unittest.TestCase):

    def test_правило_читает_список_приёмки_а_не_свой(self):
        """MUTATION: narrow the authority — the answer must follow it."""
        from unittest import mock
        # 🔴 THE MUTATION TRACKS THE AUTHORITY (28.08.2026): the list moved to
        # `spec`, and mutating `acceptance` instead would only change an ALIAS — the
        # mutation would stop affecting the actual subject, and the test would stay
        # green by construction. The name imported from `acceptance` at the top of
        # the file survives the move: it is the same object there.
        with mock.patch.object(spec, "OPS_WITHOUT_ELEMENTS",
                               frozenset({"create_wall"})):
            self.assertFalse(spec.group_member_yields_one("create_wall"))
            self.assertTrue(spec.group_member_yields_one("create_wall_type"))
        # and vice versa
        self.assertTrue(spec.group_member_yields_one("create_wall"))
        self.assertFalse(spec.group_member_yields_one("create_wall_type"))


if __name__ == "__main__":
    unittest.main()
