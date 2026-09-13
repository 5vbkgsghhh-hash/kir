"""THE `defaults` ENVELOPE DID NOT REACH GROUP MEMBERS — AND REFUSED TWICE, BOTH TIMES WRONGLY.

🔴 WHY (25.08.2026, an audit finding, reproduced by a run).

```
{defaults: {level: ...},
 ops: [create_group(members=[create_wall without level], placements=[[0,0,0]])]}
```

produced TWO refusals, and both were false:

```
KIR-P003  defaults: «ни один оп программы не принимает эти defaults: ['level']»
          — the `accepted_anywhere` scan only walked the TOP level, and
            `create_group` has no `level` parameter. Its member accepts it.
KIR-P005  members[w1].level: «level обязателен»
          — the nested `plan_program` was called with the envelope
            {ir_version, intent, ops} WITHOUT a `defaults` key.
```

That is, the author was first told "nobody needs this key", and then "this
field is missing". The same field, two opposite claims, both wrong.

**Measured 22.08: 82.6% of a real building's operations live INSIDE
groups.** A scan blind to members is a scan blind to the building.
"""
from __future__ import annotations

import unittest

from kir.compiler import plan_program
from kir.diag import KirRefusal

СТЕНА_БЕЗ_УРОВНЯ = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
                    "p1_mm": [6000, 0], "height_mm": 3000}


def _программа(defaults=None, член=None):
    prog = {"ir_version": "1.0",
            "ops": [{"op": "create_group", "id": "g1",
                     "members": [dict(член or СТЕНА_БЕЗ_УРОВНЯ)],
                     "placements": [[0.0, 0.0, 0.0]]}]}
    if defaults:
        prog["defaults"] = defaults
    return prog


class УМОЛЧАНИЕДОЕЗЖАЕТДОЧЛЕНА(unittest.TestCase):

    def test_группа_с_умолчанием_СОБИРАЕТСЯ(self):
        """🔴 RED before the fix: two refusals at once."""
        план = plan_program(_программа(
            {"level": {"by": "element_id", "value": 42}}))
        self.assertEqual([o.op_id for o in план.ops], ["g1"])

    def test_ключ_НЕ_объявляется_мёртвым(self):
        """The first of the two false refusals."""
        try:
            plan_program(_программа({"level": {"by": "element_id",
                                               "value": 42}}))
        except KirRefusal as exc:
            коды = {d.code for d in exc.diagnostics}
            self.fail(f"отказ там, где всё задано: {коды}")

    def test_член_со_СВОИМ_значением_остаётся_при_нём(self):
        """The default is idempotent: only what is missing gets filled in."""
        свой = {**СТЕНА_БЕЗ_УРОВНЯ,
                "level": {"by": "element_id", "value": 77}}
        план = plan_program(_программа(
            {"level": {"by": "element_id", "value": 42}}, свой))
        члены = план.ops[0].to_dict()["members"]
        self.assertEqual(члены[0]["level"], {"by": "element_id", "value": 77})


class КОНТРОЛЬ_НАСТОЯЩИЙМЁРТВЫЙКЛЮЧВСЁЕЩЁЛОВИТСЯ(unittest.TestCase):
    """Without it, the fix would mean "the dead-key check was removed"."""

    def test_ключ_которого_нет_НИ_У_КОГО_отказывает(self):
        with self.assertRaises(KirRefusal) as поймано:
            plan_program(_программа({"такого_поля_нет": 1}))
        коды = {d.code for d in поймано.exception.diagnostics}
        self.assertIn("KIR-P003", коды)

    def test_ключ_нужный_ТОЛЬКО_члену_живой(self):
        """Exactly the case the fix was made for."""
        план = plan_program(_программа(
            {"level": {"by": "element_id", "value": 42}}))
        self.assertTrue(план.ops)

    def test_ключ_нужный_ТОЛЬКО_верхнему_опу_остался_живым(self):
        """The fix has no right to break the ordinary path."""
        prog = {"ir_version": "1.0",
                "defaults": {"level": {"by": "element_id", "value": 42}},
                "ops": [dict(СТЕНА_БЕЗ_УРОВНЯ)]}
        план = plan_program(prog)
        self.assertEqual([o.op_id for o in план.ops], ["w1"])


if __name__ == "__main__":
    unittest.main()
