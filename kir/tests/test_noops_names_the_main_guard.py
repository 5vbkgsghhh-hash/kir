"""THE LANGUAGE'S MOST FREQUENT REFUSAL MUST NAME ITS MOST FREQUENT CAUSE.

MEASURED ON THE OVERNIGHT RIG 17.08.2026, a run of a nineteen-step staircase
across three wings: the language's door was called **463 times**, and
`KIR-B007` ("the script ran, but did not yield a single operation") —
**176 of them, 38% of all calls**. This is the language's top refusal by a
wide margin: the runner-up, `KIR-L001`, has 36. The program came out lawful
in only 33% of calls.

ONE OF THE CAUSES IS THE MOST ORDINARY PYTHON IDIOM, and here it is SILENTLY
EMPTY:

    def build(): create_wall(...)
    if __name__ == "__main__": build()

The sandbox child executes the source through `compile(..., "exec")`, and
`__name__` in that namespace is not equal to `"__main__"` — the block simply
does not run. The script runs WITHOUT errors and creates not a single
operation.

The previous refusal text named the correct way ("the program is assembled
by calls to the language") and said nothing about what specifically ate the
program for THIS author. The tree's law demands something else: a refusal
carries a cause AND a next move. Measured the same day, the ground the law
stands on: a refusal with a named move fixes the program in four seconds, a
refusal without one kills the turn.

A CONTROL ON BOTH SIDES — this is exactly what this file is about: the hint
must appear when the guard is present, and must NOT appear when it is not;
and a script without a guard must go on collecting operations as before.
"""
from __future__ import annotations

import unittest

from kir import sandbox

WITH_GUARD = '''
def build():
    create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                level={"by": "name", "value": "Уровень 1"}, height_mm=3000)

if __name__ == "__main__":
    build()
'''

WITHOUT_GUARD = '''
def build():
    create_wall(p0_mm=[0, 0], p1_mm=[6000, 0],
                level={"by": "name", "value": "Уровень 1"}, height_mm=3000)

build()
'''

NO_OPS_AT_ALL = "x = 1\n"


class NoOpsNamesTheMainGuard(unittest.TestCase):

    def test_the_guard_is_named_when_it_is_what_ate_the_program(self):
        out = sandbox.execute_author_script(WITH_GUARD)
        self.assertFalse(out.ok)
        text = str(getattr(out.refusal, "message_ru", "") or out.refusal)
        self.assertIn("__main__", text)
        self.assertIn("СЛЕДУЮЩИЙ ХОД", text)

    def test_a_script_without_the_guard_still_builds(self):
        """A control in the other direction: fixing the text does not touch the behavior."""
        out = sandbox.execute_author_script(WITHOUT_GUARD)
        self.assertTrue(out.ok, str(getattr(out, "refusal", "")))
        self.assertEqual(1, len(out.ops))

    def test_the_hint_is_silent_when_the_guard_is_absent(self):
        """A hint has no right to appear where it is wrong.

        Advice to "remove the guard" on a script that has no guard is a
        refusal that leads the author astray; that is worse than silence,
        because it gets checked with a turn.
        """
        out = sandbox.execute_author_script(NO_OPS_AT_ALL)
        self.assertFalse(out.ok)
        text = str(getattr(out.refusal, "message_ru", "") or out.refusal)
        self.assertNotIn("__main__", text)


if __name__ == "__main__":
    unittest.main()
