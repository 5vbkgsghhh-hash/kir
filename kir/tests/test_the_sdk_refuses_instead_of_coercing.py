"""THE SDK REFUSES, IT DOES NOT COERCE A TYPE.

WHAT HAPPENED (29.08.2026; audit findings F-239, F-240). Two places
coerced a type instead of refusing, and both swallowed the refusal the
contract was written for.

    program(allow_destructive="false").to_dict()  ->  True
    program().stack(levels=2.5)                   ->  2

The first is about safety: `bool("false")` in Python is TRUE — every
non-empty string is true. An author who wrote the word with which they
FORBID demolition got back a program where demolition is ALLOWED. This is
the easiest place to make exactly this mistake: the envelope is written
both by hand and by a template, and from YAML/JSON, where "false" arrives
as a string all the time. The cost is an irreversible deletion in
someone's model.

The second is about fidelity: the author asked for 2.5 floors and got
two, learning nothing about it. The compiler DOES have an integer
contract; the SDK swallowed its refusal and handed back a program that is
legal and wrong.

WHY REFUSAL, NOT "SMART" COERCION. There is no correct reading of "a
string instead of a boolean". Treating `"false"` as false would mean
setting up our own truth dictionary next to Python's, and the very next
string ("no", "0", "нет", "off") would ask where it ends. A dictionary is
not a mechanism.

🔴 THE THIRD, FOURTH, AND FIFTH FORMS OF THE SAME THING (29.08.2026;
F-241, F-242, F-243). The same class — "the SDK handed the author the
plausible instead of the true" — turned up in three more places, and not
one of them coerced a TYPE:

    program().stack(levels=0).stats()   ->  {'ops_expanded': 1, 'elements': 0}
    create_wall(id='wall1') + create_wall()  ->  ids ['wall1', 'wall1']
    sel(np.int64(42))                   ->  TypeError: not a selector

`F-241` — a failed macro expansion was replaced by the UNEXPANDED input,
and `stats()` counted from the replacement: the author read "the macro
produced nothing" where the macro had REFUSED. `F-242` — an explicit id
did not take a slot in the auto-id counter, and the refusal arrived
later, from the compiler, pointing at an op whose id was not given by its
author. `F-243` — the module header's promise ("numpy becomes ordinary
values") was honored for floats and not honored for integers, because
`np.float64` is a subclass of `float`, while `np.int64` is NOT a subclass
of `int`.

Three different cures, one class: two places learn to REFUSE (`F-241`,
`F-242`), the third learns to HONOR a promise already made (`F-243`). The
`_exactly_*` form is put on only the first two; it is not put on the
third, and forcing it there would be a lie told by the label.
"""
from __future__ import annotations

import unittest

from kir import sdk


class TheEnvelopeFlagIsExactlyBoolean(unittest.TestCase):

    def test_true_and_false_pass_through(self) -> None:
        self.assertIs(sdk.program(allow_destructive=True).to_dict()
                      ["allow_destructive"], True)
        self.assertIs(sdk.program(allow_destructive=False).to_dict()
                      ["allow_destructive"], False)

    def test_none_omits_the_field(self) -> None:
        self.assertNotIn("allow_destructive",
                         sdk.program(allow_destructive=None).to_dict())

    def test_the_word_that_forbids_does_not_enable(self) -> None:
        """THIS VERY DEFECT, and it is checked by the author's own word, not by the type."""
        for word in ("false", "no", "нет", "off", "0"):
            with self.subTest(word=word):
                self.assertTrue(bool(word),
                                "проба негодна: в питоне это слово ЛОЖНО")
                with self.assertRaises(TypeError) as caught:
                    sdk.program(allow_destructive=word).to_dict()
                self.assertIn("allow_destructive", str(caught.exception))

    def test_numbers_are_refused_too(self) -> None:
        """0 and 1 would "work" too, and that is also coercion: the contract is boolean."""
        for number in (0, 1):
            with self.subTest(number=number):
                with self.assertRaises(TypeError):
                    sdk.program(allow_destructive=number).to_dict()


class StackLevelsAreExactlyInteger(unittest.TestCase):

    def test_an_integer_passes_through(self) -> None:
        program = sdk.program()
        program.stack(levels=3)
        self.assertEqual(program.ops[0]["levels"], 3)

    def test_a_fraction_is_refused_not_truncated(self) -> None:
        with self.assertRaises(TypeError) as caught:
            sdk.program().stack(levels=2.5)
        self.assertIn("2.5", str(caught.exception))

    def test_a_whole_float_is_refused_too(self) -> None:
        """3.0 is "harmless" — and therefore more dangerous: it trains people to expect coercion."""
        with self.assertRaises(TypeError):
            sdk.program().stack(levels=3.0)

    def test_a_string_is_refused(self) -> None:
        with self.assertRaises(TypeError):
            sdk.program().stack(levels="3")

    def test_a_bool_is_refused_although_it_is_an_int(self) -> None:
        """In Python `isinstance(True, int)` is TRUE, and without a
        separate line `levels=True` would have built one floor."""
        self.assertIsInstance(True, int)
        with self.assertRaises(TypeError):
            sdk.program().stack(levels=True)


class TheStatsDoNotCountAnUnexpandedProgram(unittest.TestCase):
    """F-241. `stats()` is declared as "how many elements will land in the model"."""

    def test_a_failed_macro_expansion_refuses_instead_of_counting(self) -> None:
        from kir.diag import KirRefusal
        p = sdk.program()
        p.stack(levels=0)
        with self.assertRaises(KirRefusal) as ctx:
            p.stats()
        self.assertIn("MAX_STACK_LEVELS",
                      ctx.exception.diagnostics[0].message_ru)

    def test_expanded_itself_refuses_too_not_only_stats(self) -> None:
        """THE OTHER END. `expanded()` is a public name, and it is called
        directly too; fixing `stats()` alone would leave the other half
        lying."""
        from kir.diag import KirRefusal
        p = sdk.program()
        p.stack(levels=0)
        with self.assertRaises(KirRefusal):
            p.expanded()

    def test_a_valid_macro_still_counts_exactly_as_before(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it the check would be "stats()
        always fails".

        The numbers were taken by execution BEFORE the fix and match
        byte-for-byte — so the fix is inert on a legal input.

        `level=sdk.OMIT` here is MANDATORY, not a style choice: the level
        for the floor's members is assigned by the expansion, and
        `macros` refuses if it is set by hand. With `level="Этаж 1"` this
        case would have gone red for a DIFFERENT reason — that is, it
        would be a bad green control in reverse.
        """
        p = sdk.program()
        p.stack(levels=2, h_mm=3000, floor=[sdk.create_wall(
            p0_mm=[0, 0], p1_mm=[1000, 0], level=sdk.OMIT)])
        self.assertEqual(p.stats(),
                         {"ops_written": 1, "ops_expanded": 4, "elements": 2})


class AnExplicitIdAndTheAutoCounterShareOneNamespace(unittest.TestCase):
    """F-242. The refusal must arrive on the AUTHOR'S OWN LINE and name a move the author can actually make."""

    @staticmethod
    def _wall(**kw):
        return sdk.create_wall(p0_mm=[0, 0], p1_mm=[1000, 0],
                               level="Этаж 1", **kw)

    def test_explicit_then_auto_collides(self) -> None:
        p = sdk.program()
        p.add(self._wall(id="wall1"))
        with self.assertRaises(ValueError) as ctx:
            p.add(self._wall())
        self.assertIn("уже занят", str(ctx.exception))

    def test_auto_then_explicit_collides_too(self) -> None:
        """THE OTHER HALF: the order is reversed, the defect is the same.
        A check only on the explicit id would have missed it."""
        p = sdk.program()
        p.add(self._wall())
        with self.assertRaises(ValueError):
            p.add(self._wall(id="wall1"))

    def test_the_macro_builders_share_that_namespace_as_well(self) -> None:
        """THE THIRD AND FOURTH SITES. `stack`/`grid_array` write into
        `ops` BYPASSING `add`; before the fix both gave a matching pair
        of ids (taken by execution)."""
        p = sdk.program()
        p.stack(levels=2, h_mm=3000, id="stack1")
        with self.assertRaises(ValueError):
            p.stack(levels=2, h_mm=3000)
        q = sdk.program()
        q.grid_array(nx=2, ny=2, id="grid_array1")
        with self.assertRaises(ValueError):
            q.grid_array(nx=2, ny=2)

    def test_a_non_colliding_explicit_id_still_works(self) -> None:
        """🔴 THE GREEN OUTCOME. Without it the check would be "an explicit id is forbidden"."""
        p = sdk.program()
        p.add(self._wall(id="north-wall"))
        p.add(self._wall())
        self.assertEqual([o["id"] for o in p.to_dict()["ops"]],
                         ["north-wall", "wall1"])


class TheModulesNumpyPromiseHoldsForEveryScalar(unittest.TestCase):
    """F-243. A promise honored for one of two kinds is worse than a promise never made."""

    def test_an_integer_numpy_scalar_is_a_selector(self) -> None:
        """🔴 THE CASE MUST BE AN INTEGER. `sel(np.float64(3.5))` is
        already green TODAY — `np.float64` is a subclass of `float` and
        passed by accident; a check like that would be a green,
        worthless control that gives no sign of itself."""
        np = __import__("numpy")
        for ctor in (np.int64, np.int32, np.uint64):
            with self.subTest(ctor=ctor.__name__):
                self.assertEqual(sdk.sel(ctor(42)),
                                 {"by": "element_id", "value": 42})

    def test_a_builder_takes_it_too_not_only_sel(self) -> None:
        """`_coerce` called `sel` BYPASSING `_plain` — the builder is
        exactly the path on which the author will meet this."""
        np = __import__("numpy")
        self.assertEqual(
            sdk.query_inspect(target=np.int64(42)),
            {"op": "query_inspect",
             "target": {"by": "element_id", "value": 42}})

    def test_every_other_selector_source_is_untouched(self) -> None:
        """🔴 THE GREEN OUTCOME THAT MUST SURVIVE: `_plain`'s first line
        must not move anything."""
        self.assertEqual(sdk.sel(42), {"by": "element_id", "value": 42})
        self.assertEqual(sdk.sel("Стена 1"), {"by": "name", "value": "Стена 1"})
        self.assertEqual(sdk.sel(sdk.DEFAULT), {"by": "default"})
        self.assertEqual(sdk.sel(sdk.Ref("w1")), {"by": "ref", "value": "w1"})
        self.assertEqual(sdk.sel({"by": "name", "value": "x"}),
                         {"by": "name", "value": "x"})
        with self.assertRaises(TypeError):
            sdk.sel(True)          # bool stays a refusal
        with self.assertRaises(TypeError):
            sdk.sel(object())


class TheLawItselfCanFail(unittest.TestCase):
    """FAIL CONTROL: show that the coercion is REALLY dangerous."""

    def test_python_truthiness_would_enable_demolition(self) -> None:
        self.assertTrue(bool("false"))
        self.assertTrue(bool("no"))

    def test_python_int_would_lose_a_floor(self) -> None:
        self.assertEqual(int(2.5), 2)
        self.assertEqual(int(True), 1)

    def test_a_numpy_integer_is_not_a_python_int(self) -> None:
        """THE REASON FOR F-243 AS A NUMBER: an asymmetry between the kinds, not something we made up."""
        np = __import__("numpy")
        self.assertFalse(isinstance(np.int64(42), int))
        self.assertTrue(isinstance(np.float64(3.5), float))


if __name__ == "__main__":
    unittest.main()
