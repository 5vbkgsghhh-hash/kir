"""AN OVER-COUNT SET UP FOR AN EXCLUSION LIST DOES NOT BECOME AN ASSERTION.

Audit finding `F-312`, `kir/acceptance.py` + `kir/viewer/graph.py`. Taken by
MY OWN coverage number (turn 1) — the largest in my holding.

`acceptance._OP_DERIVED` is declared, verbatim, as: "Derived categories:
elements that Revit makes ON ITS OWN following an op. NEVER CHECKED and do
not go into the 'unexpected' report." This is a list of EXCLUSIONS, and for
an exclusion, over-counting is SAFE: an extra exclusion accuses no one.

`viewer.graph.facts_for_programs` incremented EVERY row of this table and
signed the summary "Revit WILL ADD these categories beyond what was
declared." A conditional claim was presented as certain.

🔴 CORPUS COVERAGE MEASUREMENT (65 decompiles, 0 unread):

    create_wall total             196 110
    of which CURTAIN-WALL            1 968
    -> a false claim on           194 142 walls (99.0 %)

    BEFORE: "Revit WILL ADD", sum    630 699
    AFTER:  certain (will_derive)     42 369
            conditional (may_derive) 588 330   in 57 of 65 decompiles

For `create_group` the rows are outright MUTUALLY EXCLUSIVE: the wrapper is
either model-based OR node-based, never both at once — and the count
incremented both.

THE REASON FOR THE CONDITIONALITY IS NOT INVENTED. It already stood as
PROSE in the comments of the table itself ("the type is a selector, so
whether it is curtain wall cannot be seen from the program"; "depends on
the makeup of the members... counting it exactly would mean guessing"), and
here it got A NAME — `_OP_DERIVED_CONDITIONAL`, right next to the table, not
in a second location.

WHAT THE FIX DOES NOT DO, AND THIS IS STATED: it does NOT resolve the
condition. Whether a wall is curtain wall cannot be known from the program —
the type is a selector, and reading it requires a document snapshot.
Resolving it here would mean making up knowledge. The fix changes the KIND
of the claim, not adding an answer.
"""
from __future__ import annotations

import unittest

from kir import acceptance as A
from kir.viewer import graph as G


def _ops(*pairs) -> dict:
    return {oid: {"op": name, "id": oid} for oid, name in pairs}


class УсловноеНеСкладываетсяСДостоверным(unittest.TestCase):

    def test_a_plain_wall_does_not_promise_curtain_children(self) -> None:
        """🔴 THE SUBJECT: 99.0 % of the corpus's real walls are not
        curtain wall."""
        _f, note = G.facts_for_programs(_ops(("w", "create_wall")))
        self.assertEqual(note["will_derive"], {},
                         "витражные категории объявлены достоверными")
        self.assertIn("OST_CurtainGridsWall", note["may_derive"])

    def test_an_unconditional_derivation_stays_certain(self) -> None:
        """🔴 THE GREEN OUTCOME. A floor slab ALWAYS spawns sketch lines; a
        fix that "declares everything conditional" would pass the previous
        check and zero out the summary entirely."""
        _f, note = G.facts_for_programs(_ops(("f", "create_floor")))
        self.assertEqual(note["will_derive"], {"OST_SketchLines": 1})
        self.assertEqual(note["may_derive"], {})

    def test_mutually_exclusive_rows_are_not_both_certain(self) -> None:
        """A group wrapper is model-based OR node-based — never both at
        once."""
        _f, note = G.facts_for_programs(_ops(("g", "create_group")))
        self.assertEqual(note["will_derive"], {})
        self.assertEqual(set(note["may_derive"]),
                         {"OST_IOSModelGroups", "OST_IOSDetailGroups"})

    def test_the_conditional_half_names_its_condition(self) -> None:
        """An upper bound with no named condition is the same promise, just
        quieter. The condition must reach the reader."""
        _f, note = G.facts_for_programs(_ops(("w", "create_wall")))
        self.assertIn("create_wall", note["may_derive_why"])
        self.assertIn("витраж", note["may_derive_why"]["create_wall"])
        self.assertIn("ВЕРХНЯЯ ГРАНИЦА", note["may_derive_ru"])
        self.assertNotIn("ДОБАВИТ", note["may_derive_ru"])

    def test_both_halves_travel_out(self) -> None:
        """The `will_derive` key HAS NOT DISAPPEARED — its value changed to
        the correct one, and a second key appeared alongside it. An old
        reader does not break."""
        _f, note = G.facts_for_programs(
            _ops(("w", "create_wall"), ("f", "create_floor")))
        for key in ("will_derive", "will_derive_ru",
                    "may_derive", "may_derive_ru", "may_derive_why"):
            self.assertIn(key, note)


class ТаблицаКлассифицированаЦЕЛИКОМ(unittest.TestCase):

    def test_every_derived_op_is_classified(self) -> None:
        """🔴 A MECHANISM, NOT A LIST. A new op in `_OP_DERIVED` must DEMAND
        A DECISION — whether it is conditional or certain — rather than
        silently default back into "certain"."""
        unknown = sorted(set(A._OP_DERIVED_CONDITIONAL) - set(A._OP_DERIVED))
        self.assertEqual(unknown, [],
                         f"условным назван оп, которого нет в таблице: {unknown}")
        self.assertGreaterEqual(len(A._OP_DERIVED), 10)   # denominator control
        self.assertGreaterEqual(len(A._OP_DERIVED_CONDITIONAL), 2)

    def test_the_condition_is_a_sentence_not_a_flag(self) -> None:
        """The condition travels as A REASON. A `True` flag would say
        "something is off" and send the reader to go find out what."""
        for op, why in A._OP_DERIVED_CONDITIONAL.items():
            with self.subTest(op=op):
                self.assertIsInstance(why, str)
                self.assertGreater(len(why), 30)

    def test_the_exclusion_side_is_untouched(self) -> None:
        """🔴 WHAT THE FIX MUST NOT TOUCH. Acceptance testing uses the same
        table as a list of EXCLUSIONS, and there the over-count is CORRECT:
        an extra exclusion accuses no one. Narrowing it for the viewer's
        summary would mean accusing an honest decompile of an unexpected
        output."""
        self.assertIn("OST_CurtainGridsWall", A._OP_DERIVED["create_wall"])
        self.assertIn("OST_IOSDetailGroups", A._OP_DERIVED["create_group"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
