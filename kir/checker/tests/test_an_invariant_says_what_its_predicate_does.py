"""AN INVARIANT'S STATEMENT AND ITS PREDICATE MUST SAY THE SAME THING.

WHAT HAPPENED (29.08.2026, audit finding F-356). `one_kitchen` claimed "the
dwelling has EXACTLY one kitchen", yet was implemented as `_count(...) <= 1`. A component with
zero kitchens passed the invariant, while a reader of the registry, taking the statement at
face value, would think the opposite. No instrument ever asked this question:
the statement is prose, the predicate is code, and there was nothing to check them against each other.

WHY THE STATEMENT WAS FIXED, NOT THE PREDICATE. This is not a choice between two equals.
"Exactly one" = "no more than one" AND "at least one". The first half was caught
live twice. The second is a strengthening the module DELIBERATELY refuses to
make: `at_least_one_bathroom` sits in `UNSOURCED_CANDIDATES` with the argument
"the definition of a dwelling is kitchen OR bathroom, a disjunction; strengthening it is not
backed by a norm". The requirement "at least one kitchen" is the same step from the other side of
the same disjunction, and it would contradict `is_a_dwelling`.

THE LAW GUARDED HERE IS GENERAL AND NOT ABOUT KITCHENS:

    an invariant that HOLDS on an empty component has no right to
    claim "exactly one <something>"

An empty component is a degenerate input on which "exactly one" must
be violated by the meaning of the word. If the predicate lets it through, the word "exactly" in
the statement is a promise the code does not keep.

THE BOUNDARY IS NAMED: the law catches a mismatch at the LOWER bound (zero), not the
upper one. An invariant that claims "no more than one" and is implemented as `== 1`
is not caught by this test — no such case exists in the registry, and setting up a check for a
nonexistent case would mean building an instrument with no subject.
"""
from __future__ import annotations

import unittest

from kir.checker.dwelling_invariants import INVARIANTS, Invariant

#: Words by which a statement promises an EXACT number. The list is closed: "один" ("one") without
#: "ровно" ("exactly") is not a promise of precision ("the dwelling has one entrance" reads as "no
#: more than one"), and padding the list with synonyms would mean catching prose, not
#: meaning.
_EXACTLY = ("ровно",)


def _claims_exactly(statement: str) -> bool:
    return any(word in statement.lower() for word in _EXACTLY)


class AnInvariantSaysWhatItsPredicateDoes(unittest.TestCase):

    def test_the_registry_is_not_empty(self) -> None:
        """THE DENOMINATOR FIRST: an empty registry would pass everything below vacuously."""
        self.assertGreaterEqual(
            len(INVARIANTS), 3,
            "инвариантов меньше трёх — это заявление о ЗАГРУЗКЕ реестра, "
            "а не о его содержимом")

    def test_exactly_one_is_violated_by_an_empty_component(self) -> None:
        for inv in INVARIANTS:
            if not _claims_exactly(inv.statement):
                continue
            with self.subTest(invariant=inv.id):
                self.assertFalse(
                    inv.holds(frozenset(), {}),
                    f"{inv.id} заявляет «ровно один», но ДЕРЖИТСЯ на пустой "
                    f"компоненте: заявление обещает больше, чем делает код. "
                    f"Либо предикат обязан отвергать ноль, либо заявление "
                    f"обязано сказать «не больше одного» — как это уже "
                    f"сделано у `one_prihozhaya` при том же предикате")

    def test_every_statement_and_predicate_were_actually_asked(self) -> None:
        """The check above is silent when NO ONE says "exactly".

        This is a legal state of the registry, and it is exactly what came about after the
        29.08 fix. But silence from agreement and silence from non-execution print
        the same way, so what is asked for is the NUMBER of items asked, not the result.
        """
        asked = 0
        for inv in INVARIANTS:
            self.assertTrue(inv.statement.strip(), f"{inv.id}: пустое заявление")
            self.assertTrue(callable(inv.holds), f"{inv.id}: предикат не зовётся")
            inv.holds(frozenset(), {})      # the predicate must SURVIVE emptiness
            asked += 1
        self.assertEqual(asked, len(INVARIANTS))


class TheLawItselfCanFail(unittest.TestCase):
    """FAIL CONTROL. A law that never turns red holds nothing."""

    def test_it_catches_the_defect_it_was_written_for(self) -> None:
        """The exact pair that stood in the registry before 29.08."""
        bad = Invariant(
            id="проба_контроля",
            statement="в жилище РОВНО одна кухня",
            source_kind="definition",
            source="контроль-FAIL этого файла: заявление обещает точное число, "
                   "а предикат пропускает ноль",
            holds=lambda ids, func: len(ids) <= 1,
        )
        self.assertTrue(_claims_exactly(bad.statement),
                        "проба обязана заявлять точное число")
        self.assertTrue(bad.holds(frozenset(), {}),
                        "проба обязана ДЕРЖАТЬСЯ на пустой компоненте")
        # That is, the check above must turn red on this pair.

    def test_a_matching_pair_is_not_accused(self) -> None:
        """And the other side: a correct pair has no right to turn red."""
        good = Invariant(
            id="проба_верная",
            statement="в жилище РОВНО одна кухня",
            source_kind="definition",
            source="контроль-FAIL этого файла: заявление и предикат сходятся",
            holds=lambda ids, func: len(ids) == 1,
        )
        self.assertFalse(good.holds(frozenset(), {}))


if __name__ == "__main__":
    unittest.main()
