"""THE ENVELOPE MUST NOT COST A ROUND — a guard over the retired ritual and over what remains.

THE MEASUREMENT THAT PAID FOR THIS (17.08.2026)
======================================
An offline ring (`tools/design/kir_dojo.py`) against the production model
`deepseek-v4-flash`, two series of 10 rounds per hand, the task "a typical floor
of a residential tower"::

    total rounds                                       27
    rounds where NOT A SINGLE operation went through    16   ← 59%
    codes: KIR-P001 ×15 · KIR-P003 ×12 · KIR-P004 ×5

More than half of the model's turns died on the ENVELOPE, never reaching the building. A round
costs 17-18 s, of which 84.6% is waiting for the model: every such round is a
wasted round, not "the model made a mistake and learned."

WHAT WAS REMOVED, AND WHY THIS IS NOT A RELAXATION
=====================================
Exactly two rituals were removed, and both are cases where the form meant THE SAME THING:

* **`ir_version` is absent** — there is EXACTLY ONE version in the registry, requiring it
  to be printed distinguished nothing except "performed the ritual" from "did not";
* **a single operation without a list** — `{"ops": {"op": …}}` cannot mean anything
  other than a list of one element.

🔴 **AND WHAT WAS NOT REMOVED — RIGHT HERE, AND THIS IS HALF THE FILE'S POINT.** A named
WRONG version is refused. An empty list is refused. An unknown field
(`KIR-P003`) is refused and **deliberately keeps being refused**: it catches a
typo and already carries `candidates` — meaning the refusal TEACHES, not merely punishes.
The relaxation here is strictly one-directional: what is accepted is what already meant
one thing before, and nothing beyond that.
"""
from __future__ import annotations

import unittest

from kir import spec
from kir.compiler import compile_program
from kir.diag import (PARSE_BAD_VERSION, PARSE_NOT_OBJECT,
                           PARSE_UNKNOWN_FIELD)
from kir.tests.fixtures import GROUND_SNAPSHOT


WALL = {"op": "create_wall", "id": "W1",
        "p0_mm": [0, 0], "p1_mm": [6000, 0],
        "level": {"by": "name", "value": "Этаж 1"}}


def _compile(program):
    return compile_program(program, revit_version="2026",
                           snapshot=GROUND_SNAPSHOT)


def _codes(out) -> set[str]:
    return {d.code for d in (getattr(out, "diagnostics", None) or ())}


class TheCeremonyIsGone(unittest.TestCase):
    def test_a_program_without_ir_version_compiles(self):
        """There is one version; requiring it to be printed meant charging a tax for the ritual."""
        out = _compile({"ops": [dict(WALL)]})
        self.assertNotIn(PARSE_BAD_VERSION, _codes(out))
        self.assertTrue(out.csharp, _codes(out))

    def test_one_op_written_without_a_list_compiles(self):
        out = _compile({"ops": dict(WALL)})
        self.assertNotIn(PARSE_NOT_OBJECT, _codes(out))
        self.assertTrue(out.csharp, _codes(out))

    def test_both_at_once_compiles(self):
        out = _compile({"ops": dict(WALL)})
        self.assertTrue(out.csharp, _codes(out))


class WhatStaysRefusing(unittest.TestCase):
    """🔴 A FAIL CONTROL ON THE RELAXATION: it must be ONE-DIRECTIONAL.

    Without these four, "removed the ritual" would be indistinguishable from "removed the check," and
    the green above would prove nothing.
    """

    def test_a_named_wrong_version_still_refuses(self):
        out = _compile({"ir_version": "9.9", "ops": [dict(WALL)]})
        self.assertIn(PARSE_BAD_VERSION, _codes(out))

    def test_the_current_version_named_explicitly_still_works(self):
        out = _compile({"ir_version": spec.IR_VERSION, "ops": [dict(WALL)]})
        self.assertNotIn(PARSE_BAD_VERSION, _codes(out))
        self.assertTrue(out.csharp, _codes(out))

    def test_an_empty_ops_list_still_refuses(self):
        """An empty list is NOT "a single operation": the intent is unknown.

        The refusal arrives as DIAGNOSTICS, not as an exception: `compile_program`
        catches `KirRefusal` and returns `CompileOutput(ok=False)` — the first
        draft of this test expected `raises` and turned red on healthy code.
        """
        out = _compile({"ops": []})
        self.assertFalse(out.ok)
        self.assertIn(PARSE_NOT_OBJECT, _codes(out))

    def test_a_dict_that_is_not_an_op_still_refuses(self):
        """`{"ops": {"что-то": 1}}` cannot be guessed at — there is not even an `op` in it."""
        out = _compile({"ops": {"нечто": 1}})
        self.assertFalse(out.ok)
        self.assertIn(PARSE_NOT_OBJECT, _codes(out))

    def test_an_unknown_field_still_refuses_and_names_candidates(self):
        """`KIR-P003` must NOT be removed: it catches a typo and TEACHES."""
        bad = dict(WALL)
        bad["p0mm"] = [0, 0]                      # a typo instead of `p0_mm`
        out = _compile({"ops": [bad]})
        self.assertIn(PARSE_UNKNOWN_FIELD, _codes(out))
        named = [d for d in out.diagnostics if d.code == PARSE_UNKNOWN_FIELD]
        self.assertTrue(named[0].candidates,
                        "отказ обязан называть, чем поле могло быть")


if __name__ == "__main__":
    unittest.main()
