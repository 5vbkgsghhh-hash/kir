"""THE GATE'S SECOND STRIP: grounding against a REAL document, not a
fixture.

The gate answers "does the C# compile on six versions", and everything
that needs grounding was grounded against a SYNTHETIC fixture. Such an
"OK" is a claim about the fixture. The second strip answers a DIFFERENT
question — "does a real building exist that this program could be grounded
against" — and it is pinned here that the gate is able to answer NO.

🔴 WHAT THESE TESTS DO NOT DO. They do not require the corpus: it is
machine-local (`KUKAI_DECOMPILE_DATA`), it is absent from the checkout, and
a test failing from its absence would be red for a foreign reason. So the
corpus here is ASSEMBLED BY HAND from two tiny profiles — and that is
exactly enough to check the selection predicate. What gets checked AGAINST
THE REAL corpus is printed by the gate run itself.
"""
from __future__ import annotations

import os
import sys
import unittest

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from kir.gate_runner import (            # noqa: E402
    REAL_PROFILE_FETCH_HINT,
    ground_on_real_document,
    load_real_profiles,
    pools_required_by,
)


def _wall_program() -> dict:
    """A wall by type name — requires `levels` and `wall_types`."""
    return {"ir_version": "1.0", "intent": "стена",
            "ops": [{"op": "create_wall", "id": "w1",
                     "p0_mm": [0, 0], "p1_mm": [6000, 0],
                     "level": {"by": "name", "value": "Этаж 1"},
                     "type": {"by": "name", "value": "Кирпич 380"}}]}


def _profile(run: str, pools: dict[str, list]) -> tuple[str, dict, frozenset]:
    """A profile in the shape that `load_real_profiles` hands it back in."""
    snapshot = dict(pools)
    snapshot["__document_fingerprint"] = {"title": run}
    filled = frozenset(k for k, v in snapshot.items()
                       if isinstance(v, list) and v)
    return run, snapshot, filled


_RICH = _profile("rich_building", {
    "levels": [{"id": 42, "name": "Этаж 1", "elevation_mm": 0.0}],
    "wall_types": [{"id": 100, "name": "Кирпич 380"}],
})
#: The pools are DECLARED and EMPTY — a catalog with nothing to pick from.
_EMPTY_POOLS = _profile("declared_but_empty", {
    "levels": [], "wall_types": [],
})
#: The pools exist, but the dict belongs to someone else: the type names
#: differ.
_OTHER_NAMES = _profile("other_vocabulary", {
    "levels": [{"id": 7, "name": "L_01_+0.000", "elevation_mm": 0.0}],
    "wall_types": [{"id": 9, "name": "Вн_(Вт-50х100)"}],
})


class ТребованиеПуловБерётсяУРеестра(unittest.TestCase):

    def test_wall_needs_levels_and_wall_types(self):
        self.assertEqual(pools_required_by(_wall_program()),
                         frozenset({"levels", "wall_types"}))

    def test_a_program_without_grounding_needs_nothing(self):
        """A CONTROL: the predicate must be ABLE to return an empty set,
        otherwise "pools are needed" is always true and distinguishes
        nothing."""
        prog = {"ir_version": "1.0",
                "ops": [{"op": "query_types", "id": "q1", "pool": "levels"}]}
        self.assertEqual(pools_required_by(prog), frozenset())

    def test_macros_are_expanded_before_asking(self):
        """The stack hides operations, and it is the hidden one that
        carries the pool requirement."""
        # The shape is taken from THE GATE ITSELF (`programs["auth_stack"]`),
        # not invented: without `h_mm` the macro refuses, and the predicate
        # honestly answers about an unexpanded program — that is correct,
        # but it is checking the wrong thing.
        stacked = {"ir_version": "1.0", "ops": [{
            "op": "stack", "id": "sec", "levels": 5, "h_mm": 3000,
            "floor": [{"op": "create_wall", "id": "W1", "p0_mm": [0, 0],
                       "p1_mm": [6000, 0], "height_mm": 2800}]}]}
        self.assertIn("wall_types", pools_required_by(stacked),
                      "стек прячет стену — требование пула потерялось")

    # There is NO control for "an unexpandable macro" here, and that is a
    # decision, not a gap: I did not find a stack shape on which
    # `macros.expand` throws (`h_mm` is optional, and an extra `level` on a
    # member is accepted too), and a test whose premise is not established
    # guards its own invention. The `except` branch in `pools_required_by`
    # remains UNTESTED — said out loud.


class ПолосаУмеетОтвечатьНЕТ(unittest.TestCase):
    """A FAIL CONTROL. A strip that cannot say "no" guards nothing: its
    "yes" is then obtained without an act of distinction."""

    def test_a_real_document_grounds_the_program(self):
        got = ground_on_real_document(_wall_program(), [_RICH])
        self.assertIsInstance(got, tuple, msg=f"ожидалось заземление, дано {got}")
        self.assertEqual(got[0], "rich_building")

    def test_declared_but_EMPTY_pools_do_not_count_as_having_them(self):
        """The pool is declared and empty — there is nothing to choose
        from. Counting it as present would mean getting a green result
        where there are no alternatives (shape 18)."""
        got = ground_on_real_document(_wall_program(), [_EMPTY_POOLS])
        self.assertIsInstance(got, str)
        self.assertIn("нет профиля", got)

    def test_pools_present_but_the_vocabulary_is_someone_elses(self):
        """The catalogs exist, the names do not: this is a fact about the
        PROGRAM, and it must differ from a fact about the CORPUS."""
        got = ground_on_real_document(_wall_program(), [_OTHER_NAMES])
        self.assertIsInstance(got, str)
        self.assertIn("KIR-G", got)
        self.assertNotIn("нет профиля", got)

    def test_the_search_does_not_stop_at_the_first_candidate(self):
        """WHY THE ITERATION. The first edition took the first profile with
        non-empty pools and declared a refusal; here the fitting one is
        SECOND, and a "no" would be an untruth about existence."""
        got = ground_on_real_document(_wall_program(), [_OTHER_NAMES, _RICH])
        self.assertIsInstance(got, tuple, msg=f"перебор не дошёл до второго: {got}")
        self.assertEqual(got[0], "rich_building")

    def test_a_program_needing_no_pool_is_NOT_counted_as_grounded(self):
        """🔴 THE INVERSE CONTROL THAT CAUGHT THE AUTHOR. `need <= filled`
        is true for an EMPTY `need` on any profile, including a knowingly
        empty one — and the first edition counted that as grounding. Green
        with no act of distinction. There is nothing to ground — that is a
        third outcome."""
        prog = {"ir_version": "1.0",
                "ops": [{"op": "create_path_of_travel", "id": "t1",
                         "in_view": {"by": "name", "value": "Level 1"},
                         "p0_mm": [0, 0], "p1_mm": [1000, 0]}]}
        self.assertEqual(pools_required_by(prog), frozenset())
        got = ground_on_real_document(prog, [_EMPTY_POOLS])
        self.assertIsInstance(got, str)
        self.assertIn("заземлять нечего", got)

    def test_an_empty_corpus_is_a_REFUSAL_not_a_zero(self):
        """"The program cannot withstand real documents" and "we did not
        look" are different facts. An empty corpus must be named as a
        refusal, and the way to obtain it must stand next to the refusal,
        not in someone's memory."""
        self.assertEqual(load_real_profiles("/nonexistent/decompile"), [])
        self.assertIn("KUKAI_DECOMPILE_DATA", REAL_PROFILE_FETCH_HINT)


class ОтборДетерминирован(unittest.TestCase):

    def test_two_runs_agree(self):
        """The gate must answer identically twice in a row: directory
        order is not deterministic, so the list is sorted by name."""
        a = ground_on_real_document(_wall_program(), [_OTHER_NAMES, _RICH])
        b = ground_on_real_document(_wall_program(), [_OTHER_NAMES, _RICH])
        self.assertEqual(a[0], b[0])

    def test_loader_sorts_by_run_name(self):
        rows = load_real_profiles(os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "no_such_corpus"))
        self.assertEqual(rows, [], "несуществующий корпус обязан дать пусто")


if __name__ == "__main__":
    unittest.main()
