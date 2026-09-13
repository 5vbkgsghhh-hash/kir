"""THE CONSTRUCTOR'S REFUSAL WAS EATING THE AUTHOR'S FORM (LD-07).

The subject is `kir/promote.py`, `_native`. The geometry retraction (`_retract`)
stood BEFORE the constructor, and there was no `try` between them. A
constructor refusal left a THIRD state: the original form is already gone,
the native operation isn't there yet.

MEASUREMENT BEFORE (04.09.2026): a level at address `level1`, a loft, then
`promote(..., id='level1')` — an address collision:

    BEFORE promote: ['create_level', 'create_solid_blend']
    refusal:        DslRefusal KIR-P006 «id «level1» в этой программе уже занят»
    AFTER  promote: ['create_level']            <- the form disappeared

MEASUREMENT AFTER: `['create_level', 'create_solid_blend']`, the same
addresses, the refusal `KIR-P006` reaches the author unchanged.

🔴 WHY REORDERING IS THE WRONG FIX. The order was chosen DELIBERATELY, and the
argument is recorded in `_native`'s docstring: "the reverse order would leave
both operations in the program at the moment retraction fails, and the report
would call that success." Putting the constructor first means returning to
exactly the state the order was chosen to forbid — a building constructed
TWICE in the same place (by a body and by a wall), and the native share
cannot tell such a model apart from an honest one. So what is checked here is
not order but ATOMICITY: neither of the two has a third state, and both
directions are pinned by separate tests below.

The retraction is atomic on its own and already was before the fix:
`_retract` checks ALL addresses before taking the first one, and on a miss it
takes nothing. What was being fixed was the other half — the rollback on a
constructor refusal.

Addresses are NOT freed on rollback: `Program.take` deliberately holds them
in `_ids` ("reissuing an id that was once claimed would make two different
operations indistinguishable in the receipt"), and the rollback does not
repeal this law.
"""
from __future__ import annotations

import unittest

from kir import dsl
from kir import promote as P
from kir.course import rhino
from kir.diag import KirRefusal


def кольцо(w, h, x0=0.0, y0=0.0):
    return [(x0, y0), (x0 + w, y0), (x0 + w, y0 + h), (x0, y0 + h)]


def тело(w, h, t, *, x0=0.0, y0=0.0, z0=0.0):
    r = кольцо(w, h, x0, y0)
    return rhino.loft([(r, z0), (r, z0 + t)])


def роды() -> list[str]:
    return [op["op"] for op in dsl.current().ops]


def адреса() -> list[str]:
    return [op["id"] for op in dsl.current().ops]


class ARefusedConstructorLeavesTheProgramWhole(unittest.TestCase):

    def setUp(self) -> None:
        dsl.reset()
        self.этаж = dsl.create_level(elev_mm=0, name="Этаж 1", id="level1")

    def test_the_form_survives_a_constructor_refusal(self) -> None:
        """The whole defect. A constructor refusal is not a reason to lose what was written."""
        форма = тело(6000, 4000, 200)
        до, адреса_до = роды(), адреса()
        self.assertEqual(до, ["create_level", "create_solid_blend"])
        with self.assertRaises(KirRefusal):
            P.promote(форма, level=self.этаж, id="level1")
        self.assertEqual(роды(), до, "форма изъята, а родная не встала")
        self.assertEqual(адреса(), адреса_до)

    def test_the_refusal_itself_still_reaches_the_author(self) -> None:
        """The rollback has no right to SUPPRESS the refusal. This module does
        not mint new codes (the owner's word from 27.08), so what surfaces is
        the constructor's own body — `KIR-P006`, not "the form did not become
        a floor slab"."""
        with self.assertRaises(KirRefusal) as поймано:
            P.promote(тело(6000, 4000, 200), level=self.этаж, id="level1")
        self.assertIn("KIR-P006", str(поймано.exception))
        self.assertIn("level1", str(поймано.exception))

    def test_the_third_state_does_not_exist_in_either_direction(self) -> None:
        """🔴 BOTH HOLES AT ONCE, and this is the test that forbids "fixing"
        the defect by reordering. After a refusal, the program must have
        EXACTLY one of the form's two operations standing: not zero (LD-07)
        and not both (the state the order was chosen to forbid)."""
        with self.assertRaises(KirRefusal):
            P.promote(тело(6000, 4000, 200), level=self.этаж, id="level1")
        итог = роды()
        self.assertEqual(итог.count("create_solid_blend"), 1,
                         "форма потеряна — вернулся LD-07")
        self.assertEqual(итог.count("create_floor_by_contour"), 0,
                         "в программе стоят ОБЕ операции — здание построено дважды")

    def test_a_refused_promotion_can_be_retried_on_the_same_form(self) -> None:
        """Integrity is checked not by eye but by REPETITION: if the form is
        in place, the same call without an address collision must succeed."""
        форма = тело(6000, 4000, 200)
        with self.assertRaises(KirRefusal):
            P.promote(форма, level=self.этаж, id="level1")
        итог = P.promote(форма, level=self.этаж)
        self.assertTrue(итог["native"], итог.get("reason"))
        self.assertEqual(итог["retracted"], 1)
        self.assertEqual(роды(), ["create_level", "create_floor_by_contour"])


class TheReplacementLawIsUnchanged(unittest.TestCase):
    """🔴 CONTROL. The same input with ONE changed condition — the address
    does not collide — and promotion must REPLACE, as it did before. A
    rollback firing on the successful path would leave the building
    constructed twice, and would be far worse than the defect being fixed."""

    def setUp(self) -> None:
        dsl.reset()
        self.этаж = dsl.create_level(elev_mm=0, name="Этаж 1")

    def test_control_a_successful_promotion_still_retracts_the_form(self) -> None:
        итог = P.promote(тело(6000, 4000, 200), level=self.этаж)
        self.assertTrue(итог["native"], итог.get("reason"))
        self.assertEqual(итог["retracted"], 1)
        self.assertEqual(роды(), ["create_level", "create_floor_by_contour"])

    def test_control_a_named_id_survives_when_it_is_free(self) -> None:
        итог = P.promote(тело(6000, 4000, 200), level=self.этаж, id="плита1")
        self.assertTrue(итог["native"], итог.get("reason"))
        self.assertIn("плита1", адреса())
        self.assertNotIn("create_solid_blend", роды())

    def test_control_a_form_that_stays_a_form_keeps_its_ops(self) -> None:
        """The `_stay` branch runs PAST the retraction and is untouched by
        the fix: a body that is too thick remains geometry with its own
        cause."""
        итог = P.promote(тело(6000, 4000, 700), level=self.этаж)
        self.assertFalse(итог["native"])
        self.assertEqual(итог["reason_key"], "too_thick")
        self.assertEqual(итог["retracted"], 0)
        self.assertEqual(роды(), ["create_level", "create_solid_blend"])

    def test_control_a_dry_run_touches_nothing(self) -> None:
        """A dry run neither retracts nor sets — the rollback fix has no
        right to change that."""
        форма = тело(6000, 4000, 200)   # the loft itself places the op in the program
        до = роды()
        итог = P.classify(форма)
        self.assertEqual(итог["role"], "floors")
        self.assertEqual(роды(), до)


if __name__ == "__main__":
    unittest.main()
