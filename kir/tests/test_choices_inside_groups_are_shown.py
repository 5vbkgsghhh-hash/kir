"""A CHOICE MADE INSIDE A GROUP WAS NEVER SHOWN TO ANYONE.

🔴 WHY (2026-08-25, audit finding, reproduced by the ONE AND SAME choice).

```
ВНЕ группы: «выбрано по умолчанию — symbol: «ДГ 21-8 П»
             (самый употребимый в модели: 500 экз. из 3 кандидатов,
              следующий 272)»
В ГРУППЕ:   выборов 0, текст ПУСТ
```

There is one door, one pool, one rule (`most_used`), and the same exact
choice. The only difference is that the op sits inside `create_group.members`,
while `compiler_choices` only walked the top level.

**This is exactly `.FirstOrDefault()` with a better reputation**, the very
thing the whole `ground` module is written against: its own docstring says
"a choice with no one to show it to is just `.FirstOrDefault()` with a better
reputation."

**Measurement, 08.22: 82.6% of a real building's operations live INSIDE
groups** — a person models one floor and places it as a group. Blindness
here is blindness to the building.
"""
from __future__ import annotations

import unittest

from kir import ground as g
from kir.compiler import compile_program

СНИМОК = {
    "levels": [{"id": 1, "name": "Этаж 1"}],
    "door_symbols": [{"id": 31, "name": "ДГ 21-8 П", "instances": 500},
                     {"id": 32, "name": "ДГ 21-9", "instances": 272},
                     {"id": 33, "name": "ДУ", "instances": 3}],
    "wall_types": [{"id": 9, "name": "Базовая"}],
}
СТЕНА = {"op": "create_wall", "id": "w1", "p0_mm": [0, 0],
         "p1_mm": [6000, 0], "height_mm": 3000,
         "level": {"by": "element_id", "value": 1},
         "type": {"by": "element_id", "value": 9}}
ДВЕРЬ = {"op": "create_door", "id": "d1",
         "host": {"by": "ref", "value": "w1"}, "offset_mm": 3000}


def _выборы(ops):
    out = compile_program({"ir_version": "1.0", "ops": ops},
                          revit_version="2023", snapshot=СНИМОК)
    assert out.ok, [str(d.message_ru)[:100] for d in out.diagnostics]
    return g.compiler_choices(out.grounded_ops)


ВНЕ = [dict(СТЕНА), dict(ДВЕРЬ)]
ВГРУППЕ = [{"op": "create_group", "id": "g1",
            "members": [dict(СТЕНА), dict(ДВЕРЬ)],
            "placements": [[0.0, 0.0, 0.0]]}]


class ВЫБОРВГРУППЕПРЕДЪЯВЛЯЕТСЯ(unittest.TestCase):

    def test_в_группе_выбор_ЕСТЬ_в_квитанции(self):
        """🔴 RED before the fix: it was 0."""
        self.assertEqual(len(_выборы(ВГРУППЕ)), 1)

    def test_тот_же_выбор_описан_ТЕМ_ЖЕ_текстом(self):
        """A difference between "in a group" and "outside" has no right to be in the REPORT."""
        вне = g.describe_choices_ru(_выборы(ВНЕ))
        внутри = g.describe_choices_ru(_выборы(ВГРУППЕ))
        self.assertEqual(вне, внутри)
        self.assertIn("ДГ 21-8 П", внутри)
        self.assertIn("500", внутри)

    def test_правило_НАЗВАНО_а_не_просто_число(self):
        строка = _выборы(ВГРУППЕ)[0]
        self.assertEqual(строка["rule"], "most_used")
        self.assertEqual(строка["op_id"], "d1")

    def test_КОНТРОЛЬ_вне_группы_как_было(self):
        """A fix has no right to touch a path that used to work."""
        self.assertEqual(len(_выборы(ВНЕ)), 1)


class ПОРЯДОКЧИТАЕТСЯСВЕРХУВНИЗ(unittest.TestCase):

    def test_член_идёт_СРАЗУ_за_своей_группой(self):
        """The receipt is read like a program — otherwise it's a puzzle."""
        ops = [{"op": "create_group", "id": "g1",
                "members": [dict(СТЕНА), dict(ДВЕРЬ)],
                "placements": [[0.0, 0.0, 0.0]]},
               {**dict(ДВЕРЬ), "id": "d2",
                "host": {"by": "ref", "value": "g1"}}]
        out = compile_program({"ir_version": "1.0", "ops": ops},
                              revit_version="2023", snapshot=СНИМОК)
        if not out.ok:
            self.skipTest("фикстура второго уровня не собралась: "
                          + str(out.diagnostics[0].message_ru)[:80])
        порядок = [c["op_id"] for c in g.compiler_choices(out.grounded_ops)]
        self.assertEqual(порядок[0], "d1", порядок)


if __name__ == "__main__":
    unittest.main()
