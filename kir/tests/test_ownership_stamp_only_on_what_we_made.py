"""AN OWNERSHIP STAMP ON A FOREIGN VIEW IS A DELETED VIEW OF THE OWNER'S.

🔴 WHY (24.08.2026, audit finding, confirmed by reading the emission).

`create_floor_plan` is idempotent: if the level already has a plan, the op
finds it and does NOT create one. It KNOWS the difference — it records
`already_present` in the receipt. But the ownership stamp stood AFTER the
closing brace of the creation block, i.e. it ran on BOTH branches.

**The cost is not ordering but a DELETED VIEW.** Under an A5 run the stamp
looks like `kir:a5:<doc>:<run>:…`, and orphan cleanup walks
`FilteredElementCollector(doc).WhereElementIsNotElementType()` — a ViewPlan
is NOT an ElementType, so it falls into that walk — and DELETES every
element whose `ALL_MODEL_INSTANCE_COMMENTS` begins with the run's prefix.

The scenario is from the op's own docstring: a K3 transfer, 917 partitions,
each needing a plan; the target levels ALREADY HAD plans.

Ownership is the claim "we created this." On a foreign view it is false, and
the lie here costs a view.
"""
from __future__ import annotations

import unittest

from kir.compiler import compile_program

ПРОГРАММА = {"ir_version": "1.0", "ops": [
    {"op": "create_floor_plan", "id": "FP",
     "level": {"by": "element_id", "value": 42}}]}


def _эмиссия() -> str:
    out = compile_program(ПРОГРАММА, revit_version="2026")
    assert out.ok, [str(d.message_ru)[:200] for d in out.diagnostics]
    return out.csharp


class ШтампПодСТРАЖЕЙ_СОЗДАНИЯ(unittest.TestCase):

    def test_штамп_стоит_внутри_проверки_что_план_создан_НАМИ(self):
        """🔴 RED before the fix: the stamp stood outside either branch."""
        cs = _эмиссия()
        охрана = cs.find("if (__vpnew_FP)")
        штамп = cs.find("ALL_MODEL_INSTANCE_COMMENTS")
        self.assertNotEqual(охрана, -1, "стража создания в эмиссии нет")
        self.assertNotEqual(штамп, -1, "штампа в эмиссии нет")
        self.assertLess(охрана, штамп,
                        "штамп обязан стоять ПОСЛЕ стражи, то есть внутри неё")

    def test_между_стражей_и_штампом_только_открывающая_скобка(self):
        """Otherwise "inside" would be proven by ordering, not by nesting."""
        cs = _эмиссия()
        охрана = cs.find("if (__vpnew_FP)")
        штамп = cs.find("ALL_MODEL_INSTANCE_COMMENTS")
        между = cs[охрана + len("if (__vpnew_FP)"):штамп]
        self.assertNotIn("}", между.split("{", 1)[-1],
                         "блок стражи закрылся ДО штампа — штамп снаружи")
        self.assertIn("{", между)

    def test_флаг_создания_ставится_ТОЛЬКО_в_ветке_создания(self):
        """A CONTROL ON THE GUARD ITSELF: it must be false on a foreign
        plan."""
        cs = _эмиссия()
        self.assertIn("__vpnew_FP = true;", cs)
        self.assertEqual(cs.count("__vpnew_FP = true;"), 1,
                         "второе присваивание сделало бы стража всегда-истиной")

    def test_КОНТРОЛЬ_идемпотентная_ветка_в_эмиссии_ЕСТЬ(self):
        """Without it the test would be guarding an op that has no such
        branch at all."""
        cs = _эмиссия()
        self.assertIn("if (__vp_FP == null)", cs,
                      "оп обязан искать существующий план ДО создания")


if __name__ == "__main__":
    unittest.main()
