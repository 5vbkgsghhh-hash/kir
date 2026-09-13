"""A REFUSAL MUST LEAVE THE PROGRAM THE SAME AS IT WAS.

Audit finding `F-097` (29.08.2026), `kir/dsl._coerce_members`.

`create_group(members=[...])` retracts ops from the program: a group member
is an op that MUST NOT be in the program — it lives inside the group. The
retraction stood INSIDE the parsing: `prog.take` was called on each handle
right away, while the check of the remaining members ran AFTER. An illegal
member N+1 took members 0..N down with it.

    ops before:                ['wall1']
    refusal:                   members[1]: член группы — это ОПЕРАЦИЯ…
    ops AFTER the refusal:     []                      <- eaten
    repeat of the LEGAL one:   REFUSED, members[0]: операции «wall1» в программе нет

🔴 THE THIRD LINE IS THE PRICE. The author fixes exactly what the refusal
pointed to, repeats the call legally — and gets a SECOND refusal, about a
DIFFERENT member, whose cause lies in the FIRST attempt. A model reading only
the last refusal will go fix `wall1`, which does not exist, because we ate
it. `create_group` is, moreover, the language's sole repeater: in the
marathon building the ENTIRE frame lived inside its members, 372 placements.

THE CURE IS TWO PASSES, NOT RETURNING WHAT WAS RETRACTED. Returning it would
have to restore not only the COMPOSITION but also the ORDER of the ops — that
is, stand up a second implementation of the rule "where an op stands," which
would diverge from the first. Leaving it untouched is cheaper than fixing it.

A CORRECT REFUSAL FOR THE WRONG REASON WAS INCIDENTALLY CURED. A duplicate
handle within one list used to give «операции «wall1» в программе нет» —
because the first occurrence had already eaten it. Now the cause is named for
what it actually is: "stands in this list TWICE." The `claimed` set makes
the cause correct without minting a new kind of refusal.

AN UNFIT CHECK, NAMED EXPLICITLY: "the refusal contains `members[1]`." It is
green even TODAY — the refusal's text is correct, the STATE is corrupted.
What must be checked is the repeat.
"""
from __future__ import annotations

import unittest

from kir import dsl

# 🔴 THE REFUSAL CLASS IS TAKEN FROM THE MODULE BY LOCATION, NOT IMPORTED BY
# NAME. `test_dsl.py` calls `importlib.reload(dsl)` (lines 408, 413, 450), and
# this mints a NEW `DslRefusal` class object. A module-level `from kir.dsl
# import DslRefusal` would have captured the OLD one, and `assertRaises`
# would stop catching — the checks were green INDIVIDUALLY and red AS A
# GROUP, exactly the trap named in `BASELINE.md`. The tree knows about it and
# warns:
# `test_dsl.test_a_reload_of_dsl_does_not_poison_who_imported_it_with_a_star`.
# Caught by running the group, not by reasoning.
def _refusal_class():
    return dsl.DslRefusal


class ОтказНеСъедаетПрограмму(unittest.TestCase):

    def setUp(self) -> None:
        dsl.reset()
        self.addCleanup(dsl.reset)

    def _wall(self, y: float = 0.0):
        return dsl.create_wall(p0_mm=[0, y], p1_mm=[1000, y], level="Этаж 1")

    def test_a_bad_member_does_not_eat_the_good_ones(self) -> None:
        """🔴 THE SUBJECT OF THE FINDING. What is checked is not the
        refusal's text but the REPEAT: the author fixes what was named and
        tries again."""
        w = self._wall()
        before = [o["id"] for o in dsl.ops()]
        with self.assertRaises(_refusal_class()):
            dsl.create_group(members=[w, 7], placements=[[0, 0]])
        self.assertEqual([o["id"] for o in dsl.ops()], before,
                         "отказ съел операции программы")
        # THE REPEAT OF THE LEGAL CALL must succeed — today it was refused
        # for a reason the author did not create.
        self.assertTrue(dsl.create_group(members=[w], placements=[[0, 0]]))

    def test_the_order_of_the_surviving_ops_is_untouched(self) -> None:
        """Not only the COMPOSITION but also the ORDER: a fix that "returns
        what was retracted" would pass the composition check and could still
        reorder the ops."""
        walls = [self._wall(0), self._wall(1000), self._wall(2000)]
        before = [o["id"] for o in dsl.ops()]
        self.assertEqual(len(before), 3)
        with self.assertRaises(_refusal_class()):
            dsl.create_group(members=[walls[0], walls[2], "не оп"],
                             placements=[[0, 0]])
        self.assertEqual([o["id"] for o in dsl.ops()], before)

    def test_the_happy_path_still_takes_the_members_out(self) -> None:
        """🔴 THE GREEN OUTCOME WITHOUT WHICH EVERYTHING ABOVE IS WORTHLESS.
        A legal call must still RETRACT the op into a member — otherwise a
        fix that "retracts nothing" would pass both checks and break the
        language's main multiplier."""
        w = self._wall()
        dsl.create_group(members=[w], placements=[[0, 0]])
        self.assertNotIn("wall1", [o["id"] for o in dsl.ops()])
        self.assertIn("group1", [o["id"] for o in dsl.ops()])

    def test_a_dict_member_is_still_accepted_and_takes_nothing(self) -> None:
        """A ready-made operation given as a dict is a legal member, and it
        does NOT retract anything from the program. The second pass must
        skip it rather than call `take`."""
        w = self._wall()
        dsl.create_group(
            members=[w, {"op": "create_wall", "id": "raw1", "p0_mm": [0, 0],
                         "p1_mm": [1, 0], "level": "Этаж 1"}],
            placements=[[0, 0]])
        self.assertEqual([o["id"] for o in dsl.ops()], ["group1"])

    def test_a_handle_listed_twice_says_so_instead_of_saying_it_is_missing(self) -> None:
        """🔴 A CORRECT REFUSAL FOR THE WRONG REASON. Today the second
        occurrence reported «операции нет» — because the first one had
        already eaten it — and sent the author to look for the missing thing
        instead of removing the duplicate."""
        w = self._wall()
        with self.assertRaises(_refusal_class()) as ctx:
            dsl.create_group(members=[w, w], placements=[[0, 0]])
        msg = str(ctx.exception)
        self.assertIn("ДВАЖДЫ", msg)
        self.assertNotIn("в программе нет", msg)
        self.assertEqual([o["id"] for o in dsl.ops()], ["wall1"])

    def test_a_handle_from_a_finished_program_still_says_it_is_missing(self) -> None:
        """THE GREEN OUTCOME OF THE FIRST REFUSAL: it must SURVIVE. A handle
        from a program finished with `reset()` is still «операции нет», and
        that is a different case with a different next move."""
        w = self._wall()
        dsl.reset()
        self._wall()                       # a new program, its own wall1
        stale = dsl.Handle("нет-такого-опа", w.op, w._spec)
        with self.assertRaises(_refusal_class()) as ctx:
            dsl.create_group(members=[stale], placements=[[0, 0]])
        self.assertIn("в программе нет", str(ctx.exception))
        self.assertEqual([o["id"] for o in dsl.ops()], ["wall1"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
