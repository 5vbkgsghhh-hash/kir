"""THE LAW OF THE BOOLEAN WITNESS — what it catches, what it does not,
and where it degenerates.

WHY THIS FILE EXISTS. The volume of a union or a difference cannot be
derived in closed form (the same argument by which `ops_solid` refuses
five factories). So the witness rests not on our own recomputation but
on the RELATIONS between four numbers, each computed by Revit itself.
Such a witness is easy to write in a way that can never fail — and that
is exactly what is checked here, by a table, not by eye.

🔴 THIS FILE HAS ALREADY REFUTED ITS OWN LAW ONCE, AND THE CORRECTION
HERE MATTERS MORE THAN THE LAW. The first draft claimed that the
identity and the direction catch DIFFERENT things and that neither
subsumes the other. A FAIL control refuted this: removing the direction
check from the union case did not turn a single test red.

The reason is arithmetic. The intersection is built by a separate Revit
call, so `V(A∩B)` is known, and the identity determines the result with
a SINGLE number: V(A∪B) = V(A)+V(B)−V(A∩B), V(A−B) = V(A)−V(A∩B). Any
deviation is caught by it, and the direction adds nothing once the
precondition is intact. The earlier "substitution table" had been
computed on the wrong substitution — I was swapping both the result and
the measured intersection, whereas the intersection does not depend on
the operation being patched.

What survives from the first draft, and is worth more: the direction
predicate says "no" both under a patch AND under a DEGENERATE operation.
One predicate for two outcomes is our own named defect, and the fixes
are opposite: fix the emission versus rewrite the program. That is why
degeneracy lives in a separate function with separate codes.
"""
from __future__ import annotations

import unittest

from kir import ops_boolean as B

# Two 2000×2000×1000 boxes, offset so the intersection is
# 1000×1000×1000. The numbers are exact and computable in one's head —
# this matters: a fixture that cannot be checked by arithmetic becomes
# itself an article of faith.
V_A = V_B = 4e9
V_I = 1e9
V_UNION = 7e9
V_DIFF = 3e9
DELTA = 1e6


class TheHonestResultPasses(unittest.TestCase):
    """A control in the positive direction: the law does not forbid
    what is correct."""

    def test_union(self) -> None:
        ok, why = B.witness_verdict(V_A, V_B, V_I, V_UNION, "union", DELTA)
        self.assertTrue(ok, why)

    def test_difference(self) -> None:
        ok, why = B.witness_verdict(V_A, V_B, V_I, V_DIFF, "difference", DELTA)
        self.assertTrue(ok, why)

    def test_intersect(self) -> None:
        ok, why = B.witness_verdict(V_A, V_B, V_I, V_I, "intersect", DELTA)
        self.assertTrue(ok, why)


class EverySubstitutionIsCaught(unittest.TestCase):
    """Five substitutions, each a real emitter typo, not an invention."""

    def _refused(self, v_r, op, *, v_i=V_I):
        ok, why = B.witness_verdict(V_A, V_B, v_i, v_r, op, DELTA)
        self.assertFalse(ok, f"подмена прошла незамеченной ({op}, V={v_r:g})")
        self.assertTrue(why, "отказ обязан назвать, ЧТО разошлось")
        return why

    def test_returned_A_instead_of_A_minus_B(self) -> None:
        self._refused(V_A, "difference")

    def test_returned_nothing_instead_of_A_minus_B(self) -> None:
        """Caught ONLY by the identity: the direction is satisfied here
        (0 < V(A))."""
        self._refused(0.0, "difference")

    def test_swapped_union_and_intersect(self) -> None:
        """The inclusion-exclusion identity is SYMMETRIC and lets this
        one through."""
        self._refused(V_I, "union")

    def test_returned_A_instead_of_union(self) -> None:
        self._refused(V_A, "union")

    def test_returned_B_instead_of_intersection(self) -> None:
        self._refused(V_B, "intersect")

    def test_the_overlap_was_not_removed(self) -> None:
        """🔴 A SUBSTITUTION CAUGHT ONLY BY THE IDENTITY — and without
        it, the whole suite passed even with the identity removed,
        meaning it could not tell the two halves of the law apart.

        The substitution has real meaning: the operation returned the
        SUM of the volumes, i.e. the overlap was never removed — the two
        bodies were simply added. The direction check is satisfied by
        this (the sum exceeds each), and lets it through.
        """
        self._refused(V_A + V_B, "union")

    def test_the_subtrahend_was_not_removed(self) -> None:
        """The same from the other side: LESS than the overlap was
        subtracted."""
        self._refused(V_A - V_I / 2.0, "difference")

    def test_an_unknown_operation_is_refused_not_ignored(self) -> None:
        ok, why = B.witness_verdict(V_A, V_B, V_I, V_UNION, "xor", DELTA)
        self.assertFalse(ok)
        self.assertIn("xor", why)


class IdentitySUBSUMESDirection(unittest.TestCase):
    """🔴 THIS CLASS IS A CORRECTION, NOT A CHECK. READ IT FIRST.

    It used to be called `NeitherHalfSubsumesTheOther` and claimed that
    the identity and the direction catch different things. A FAIL
    control REFUTED this: removing the direction check from the union
    case did not turn a single test red.

    The reason is arithmetic. The intersection is built by a SEPARATE
    Revit call, so the identity determines the result with a single
    number, and any deviation is caught by it. The direction check is
    redundant once the precondition holds.

    What is pinned here instead of the earlier falsehood: subsumption,
    first, and the cost of skimping on the intersection, second.
    """

    @staticmethod
    def _identity_only(v_a, v_b, v_i, v_r, op):
        if op == "union":
            return abs((v_r + v_i) - (v_a + v_b)) <= DELTA
        return abs((v_r + v_i) - v_a) <= DELTA

    @staticmethod
    def _direction_only(v_a, v_b, v_r, op):
        if op == "union":
            return v_r > max(v_a, v_b) + DELTA
        return v_r < v_a - DELTA

    def test_identity_alone_catches_every_substitution(self) -> None:
        """Subsumption, shown across all substitutions at once."""
        for v_r, op in ((V_I, "union"), (V_A, "union"), (V_A + V_B, "union"),
                        (V_A, "difference"), (0.0, "difference")):
            with self.subTest(op=op, v_r=v_r):
                self.assertFalse(
                    self._identity_only(V_A, V_B, V_I, v_r, op),
                    "тождество обязано ловить каждую подмену в одиночку")

    def test_the_identity_pins_a_SINGLE_value(self) -> None:
        """Why subsumption is inevitable: the identity has exactly one
        root."""
        self.assertTrue(self._identity_only(V_A, V_B, V_I, V_A + V_B - V_I, "union"))
        self.assertTrue(self._identity_only(V_A, V_B, V_I, V_A - V_I, "difference"))

    def test_WITHOUT_the_intersection_direction_alone_is_LEAKY(self) -> None:
        """The cost of skimping on building the intersection, named as
        a number.

        Not building the intersection is cheaper by one body, and the
        temptation is real. Then the identity cannot be checked at all,
        and the direction check, alone, lets through an operation that
        NEVER REMOVED the overlap.
        """
        self.assertTrue(self._direction_only(V_A, V_B, V_A + V_B, "union"),
                        "направление довольно суммой — вот дыра")
        self.assertFalse(self._identity_only(V_A, V_B, V_I, V_A + V_B, "union"),
                         "а тождество её ловит")


class TheRedundancyIsPINNED(unittest.TestCase):
    """🔴 THE DIRECTION CHECK'S REDUNDANCY IS PINNED AS A FACT, NOT LEFT
    AS AN ARTICLE OF FAITH.

    A FAIL control showed: removing the direction check from the union
    case turns not a single test red, because the identity determines
    the result with a single number. Such a check is easy to mistake for
    protection — it looks like reinforcement and is not.

    So an assertion about the redundancy ITSELF stands here. As long as
    it stays green, the direction check is a second road to the same
    answer; if someone ever makes it load-bearing (for instance, by no
    longer building the intersection), this test will turn red and force
    the law to be rewritten, rather than silently producing a witness
    full of holes.
    """

    def test_the_identity_alone_decides_every_case_the_law_decides(self) -> None:
        cases = [(V_UNION, "union", True), (V_I, "union", False),
                 (V_A, "union", False), (V_A + V_B, "union", False),
                 (V_DIFF, "difference", True), (V_A, "difference", False),
                 (0.0, "difference", False), (V_A - V_I / 2.0, "difference", False)]
        for v_r, op, expected in cases:
            with self.subTest(op=op, v_r=v_r):
                law_ok, _ = B.witness_verdict(V_A, V_B, V_I, v_r, op, DELTA)
                if op == "union":
                    ident = abs((v_r + V_I) - (V_A + V_B)) <= DELTA
                else:
                    ident = abs((v_r + V_I) - V_A) <= DELTA
                self.assertIs(law_ok, expected)
                self.assertIs(ident, expected,
                              "тождество в одиночку обязано решать так же — "
                              "если нет, направление стало несущим и закон "
                              "надо переписать, а не оставить как есть")


class DegeneracyIsItsOwnOutcome(unittest.TestCase):
    """Degeneracy is a refusal FROM THE OP, not a witness failure. Two
    outcomes, two codes."""

    def test_disjoint_bodies_are_named(self) -> None:
        got = B.degenerate_reason(V_A, V_B, 0.0, DELTA)
        self.assertIsNotNone(got)
        code, why = got
        self.assertEqual(code, B.BOOLEAN_DISJOINT)
        self.assertIn("Следующий ход", why)

    def test_nested_bodies_are_named_DIFFERENTLY(self) -> None:
        """Pulling the operands apart versus removing an extra one are
        opposite fixes."""
        got = B.degenerate_reason(V_A, 1e9, 1e9, DELTA)
        self.assertIsNotNone(got)
        code, why = got
        self.assertEqual(code, B.BOOLEAN_NESTED)
        self.assertNotEqual(B.BOOLEAN_NESTED, B.BOOLEAN_DISJOINT)
        self.assertIn("Следующий ход", why)

    def test_a_healthy_pair_is_not_degenerate(self) -> None:
        """CONTROL: the refusal must be NARROW, or the op will never fly
        at all."""
        self.assertIsNone(B.degenerate_reason(V_A, V_B, V_I, DELTA))

    def test_the_witness_is_GREEN_on_a_degenerate_pair(self) -> None:
        """🔴 THIS IS WHY THE PRECONDITION EXISTS AT ALL.

        For non-intersecting bodies, the difference equals the minuend,
        and the difference witness passes — meaning it signs off on an
        operation that did nothing. Without the precondition, this would
        be a green indistinguishable from an honest one.
        """
        ok, _ = B.witness_verdict(V_A, V_B, 0.0, V_A, "difference", DELTA)
        self.assertFalse(ok, "направление обязано поймать хотя бы это")
        # Whereas the union of non-intersecting ones passes BOTH checks:
        ok2, _ = B.witness_verdict(V_A, V_B, 0.0, V_A + V_B, "union", DELTA)
        self.assertTrue(ok2, "и вот он, зелёный без содержания")
        self.assertIsNotNone(B.degenerate_reason(V_A, V_B, 0.0, DELTA),
                             "поймать его может ТОЛЬКО предусловие")


class TheClosedListsSayWhatTheyAre(unittest.TestCase):

    def test_operations_are_exactly_revit_s_three(self) -> None:
        self.assertEqual(set(B.BOOLEAN_OPS),
                         {"union", "difference", "intersect"})

    def test_the_lower_bound_is_derived_not_chosen(self) -> None:
        """A boolean over a single body is not an operation."""
        self.assertEqual(B.BOOLEAN_PARTS_MIN, 2)
        self.assertGreater(B.BOOLEAN_PARTS_MAX, B.BOOLEAN_PARTS_MIN)


if __name__ == "__main__":
    unittest.main()
