"""A RECIPE THAT IS CALLED TO BE COPIED AND EDITED IS OBLIGATED TO NAME ITS OWN EDGES.

An audit finding, `F-305` (2026-08-29), `kir/course/recipes.py`, the "silhouette" recipe.

A recipe is a working script that the author takes and edits the numbers of:
this is its declared purpose, and the first lines are pulled out into
parameters exactly for that. `STOREYS` is the second parameter from the top.
Measured with a REAL sandbox:

    STOREYS=12  ok, ops=108  «ломаная против синуса: 67 мм по радиусу»
    STOREYS= 2  ok, ops=18   «ломаная против синуса: 6600 мм по радиусу»
    STOREYS= 1  REFUSAL KIR-B006 | ZeroDivisionError: float division by zero

🔴 TWO EDGES, AND THE SECOND IS QUIETER THAN THE FIRST.

The first: at `STOREYS=1` the script divides by zero in TWO places — in the
construction and in measuring the deviation. The author gets a refusal WITH
NO CAUSE AND NO NEXT MOVE for putting a one exactly where the recipe itself
invites them to put a number.

The second, and it matters more: at `STOREYS=2` a deviation of 6600 mm on a
radius of 22,000 — almost A THIRD of the radius — was printed in the SAME
calm tone as 67 mm. The author got a "tower with a waist" that has no waist,
and the number that says so was read as reference information. The recipe
ALREADY knows how to name the cost as a number; it simply was not put to use
here.

WHY `raise`, NOT `assert`: `assert` disappears under `-O`, and a script that
stops checking itself because of an interpreter flag is exactly the silent
kind this whole bundle is written against. The sandbox lets both through and
hands the author `KIR-B006` with ITS OWN text (verified by execution).

THE 5% THRESHOLD IS ASSIGNED, NOT MEASURED, and this is said out loud right
in the recipe itself — otherwise it would be one more unnamed number.

THE FINDING DOES NOT GENERALIZE: an edge of this kind exists in exactly ONE
recipe out of eight, and both its lines are here. There is nothing here to
justify inflating the fix.
"""
from __future__ import annotations

import re
import unittest

from kir.course.recipes import RECIPES
from kir.sandbox import execute_author_script


def _run(storeys: int):
    src = re.sub(r"^STOREYS, H = \d+, ", f"STOREYS, H = {storeys}, ",
                 RECIPES["силуэт"].source, flags=re.M)
    assert f"STOREYS, H = {storeys}," in src, "подстановка не сработала"
    return execute_author_script(src)


class РецептНазываетСвойКрай(unittest.TestCase):

    def test_one_storey_refuses_with_a_cause_and_a_next_move(self) -> None:
        """🔴 THE FIRST EDGE. It used to be `ZeroDivisionError` — a refusal with no cause."""
        r = _run(1)
        self.assertFalse(r.ok)
        msg = r.refusal.message_ru
        self.assertNotIn("ZeroDivisionError", msg)
        self.assertIn("минимум ДВУМ этажам", msg)
        self.assertIn("recipe(", msg)          # the next move is NAMED

    def test_two_storeys_build_but_say_the_waist_is_gone(self) -> None:
        """🔴 THE SECOND EDGE, THE QUIET ONE. The program builds — and is obligated
        to build — but the number stops being printed in a calm tone."""
        r = _run(2)
        self.assertTrue(r.ok, r.refusal and r.refusal.message_ru)
        self.assertEqual(len(r.ops), 18)
        self.assertIn("6600 мм", r.stdout)
        self.assertIn("«талии» на такой ломаной НЕТ", r.stdout)

    def test_a_dense_enough_silhouette_stays_quiet(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it, the warning would print ALWAYS and
        guard nothing at all. Twelve floors — 67 mm; four — 884 mm, i.e. 4%
        of the radius, STILL UNDER the threshold: the edge is checked from
        both sides, not only where the answer is obvious."""
        for storeys in (12, 4):
            with self.subTest(storeys=storeys):
                r = _run(storeys)
                self.assertTrue(r.ok, r.refusal and r.refusal.message_ru)
                self.assertIn("ломаная против синуса", r.stdout)
                self.assertNotIn("«талии» на такой ломаной НЕТ", r.stdout)

    def test_the_unedited_recipe_still_runs(self) -> None:
        """The recipe as it stands is obligated to work: a fix has no right to touch
        the very thing it was written for."""
        r = execute_author_script(RECIPES["силуэт"].source)
        self.assertTrue(r.ok, r.refusal and r.refusal.message_ru)
        self.assertEqual(len(r.ops), 108)

    def test_the_named_threshold_is_declared_in_the_recipe_itself(self) -> None:
        """The threshold is ASSIGNED — and this is said in the text the author
        reads, not only in the test's docstring."""
        src = RECIPES["силуэт"].source
        self.assertIn("НАЗНАЧЕНО, не измерено", src)

    def test_no_other_recipe_has_this_edge(self) -> None:
        """SCOPE CONTROL: the finding does not generalize. Dividing by "a number
        minus one" exists in exactly one recipe out of eight — if a second
        one appears, this check will demand that someone come and decide."""
        risky = [name for name, r in RECIPES.items()
                 if re.search(r"/\s*(float\()?\s*[A-Z_]+\s*-\s*1", r.source)]
        self.assertEqual(risky, ["силуэт"], f"новый рецепт с тем же краем: {risky}")
        self.assertGreaterEqual(len(RECIPES), 8)   # denominator control


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
