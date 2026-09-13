"""`ELEMENT` WAS A SUPERTYPE OF EVERYTHING — AND THEREBY GAVE UP THE LANGUAGE'S GUARANTEE.

🔴 WHY (25.08.2026, an audit finding, confirmed AT THE DEFINITION SITE).

`accepts_reference` returned `True` for ANY producer if the slot's
`ref_kinds` contained `ELEMENT`. Narrow kinds exist for exactly the opposite
reason: the docstrings of `WALL_TYPE` and `FLOOR_TYPE` say this verbatim —
"a general kind would give up the very guarantee this language exists for…
a refusal AT RUNTIME instead of a refusal AT COMPILE TIME".

**The narrowness held only ONE end.** A narrow consumer rejected a foreign
kind (`create_wall.type` given a roof-type reference -> `KIR-L004`, verified),
while a wide one accepted a narrow one:

```
move_elements.targets accepted WALL_TYPE / FLOOR_TYPE / ROOF_TYPE
```

A type has neither a position nor geometry — `ElementTransformUtils.MoveElement`
dies in Revit, while compilation was GREEN. 18 of 71 slots are like this.

**Two slots legitimately accept a type, and that is an API fact, not a
relaxation:** a Revit type has its OWN parameters, and a type can be
deleted. They name the kind EXPLICITLY. `change_type.target` is deliberately
NOT among them: there the target is the instance whose type is being
changed, and a type has no type of its own.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.registry_base import TYPE_REFERENCE_KINDS
from kir.registry_base import ReferenceKind as RK

ТИПОВЫЕ = sorted(TYPE_REFERENCE_KINDS, key=lambda k: k.name)


def _слот(оп: str, поле: str):
    return next(p for p in spec.OPS[оп].params if p.name == поле)


class ТИПНЕЭКЗЕМПЛЯР(unittest.TestCase):

    def test_широкий_слот_ТИП_НЕ_принимает(self):
        """🔴 RED before the fix: accepted all four."""
        for оп, поле in (("move_elements", "targets"),
                         ("join_elements", "first"),
                         ("create_tag", "target"),
                         ("place_family", "host"),
                         ("change_type", "target")):
            for род in ТИПОВЫЕ:
                with self.subTest(слот=f"{оп}.{поле}", род=род.name):
                    self.assertFalse(_слот(оп, поле).accepts_reference(род))

    def test_КОНТРОЛЬ_экземпляр_по_прежнему_принимается(self):
        """Without it, the fix would mean "references were banned outright"."""
        for оп, поле in (("move_elements", "targets"),
                         ("join_elements", "first"),
                         ("create_tag", "target")):
            слот = _слот(оп, поле)
            self.assertTrue(слот.accepts_reference(RK.ELEMENT))
            self.assertTrue(слот.accepts_reference(RK.WALL))


class ГДЕТИПЗАКОНЕН_ОННАЗВАН(unittest.TestCase):

    def test_set_param_и_delete_принимают_тип(self):
        """A Revit type has its own parameters, and it can be deleted."""
        for оп in ("set_param", "delete"):
            слот = _слот(оп, "target")
            for род in ТИПОВЫЕ:
                with self.subTest(оп=оп, род=род.name):
                    self.assertTrue(слот.accepts_reference(род))

    def test_они_называют_род_ЯВНО_а_не_через_ELEMENT(self):
        """Silence no longer means "yes" — that is the whole fix."""
        for оп in ("set_param", "delete"):
            рода = set(_слот(оп, "target").ref_kinds)
            self.assertTrue(TYPE_REFERENCE_KINDS <= рода,
                            f"{оп}: тип обязан быть назван, а не подразумеваться")


class СЛОВАРЬТИПОВЫХРОДОВЗАКРЫТ(unittest.TestCase):

    def test_все_роды_с_TYPE_в_имени_объявлены_типовыми(self):
        """A new type-kind must land here by a DECISION, not by silence."""
        по_имени = {k for k in RK if k.name.endswith("_TYPE")}
        self.assertEqual(по_имени, set(TYPE_REFERENCE_KINDS))

    def test_ELEMENT_сам_НЕ_типовой(self):
        self.assertNotIn(RK.ELEMENT, TYPE_REFERENCE_KINDS)


if __name__ == "__main__":
    unittest.main()
