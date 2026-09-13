"""Negative controls for L2 acceptance — and proof that they can fail.

THIS FILE'S ORDER IS THE REVERSE OF THE USUAL ONE, AND THAT IS THE MAIN
POINT OF IT. The lead's design
(docs/2026-07-29-independent-acceptance-design.md, section 3 on build order)
says outright: a deliberately wrong build must fail every predicate, and this
is the FIRST thing to write, otherwise we would learn about a blind checker
at the same moment we learn about "looks correct." So the wrong builds come
first, the correct one sits right next to them (a checker that fails
everything is just as useless as one that lets everything through), and
after that comes something that usually isn't written at all: MUTATIONS that
prove each control fails NOT ON ITS OWN, but because of a specific rule. A
test that cannot fail is not a test; a test that cannot STOP failing when a
rule breaks does not prove the rule exists.
"""
from __future__ import annotations

import json
import re
import unittest
from unittest import mock

from kir import acceptance, spec
from kir.acceptance import (
    Certainty,
    MismatchCode,
    census_delta,
    check_acceptance,
    derive_expectation,
    expectation_digest,
    scope_census_from_elements,
)

L3 = "Этаж 3"
L4 = "Этаж 4"


def _walls_and_doors_program() -> dict:
    """12 walls on "Этаж 3" and 4 doors in them — the sample from the L2 design."""
    ops = [
        {"op": "create_wall", "id": f"w{i}",
         "p0_mm": [i * 1000.0, 0.0], "p1_mm": [i * 1000.0, 6000.0],
         "level": {"by": "name", "value": L3}, "height_mm": 3000.0}
        for i in range(12)
    ]
    ops += [
        {"op": "create_door", "id": f"d{i}",
         "host": {"by": "ref", "value": f"w{i}"}, "offset_mm": 1000.0}
        for i in range(4)
    ]
    return {"ir_version": "1.0", "ops": ops}


def _census(rows: dict[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    return dict(rows)


BEFORE = _census({("OST_Walls", L3): 100, ("OST_Doors", L3): 5,
                  ("OST_Walls", L4): 40})


def _unmerged_groups(groups):
    """A PER-GROUP check — exactly the one that stood before the F-094 fix.

    Lives at module level, not inside the test: two different controls use
    this substitution, and both must mutate THE SAME THING, otherwise
    "the defect comes back" and "inert" are talking about different
    subjects.
    """
    return [(categories, list(rows))
            for categories, rows in sorted(groups.items())]


class TestProgramIsReal(unittest.TestCase):
    """The anchor: the predicate is derived from a program the compiler
    ACCEPTS.

    Without this test, all the controls below would be checking acceptance
    of a made-up shape: an expectation derived from something the compiler
    would refuse to compile means nothing.
    """

    def test_the_control_program_compiles_and_yields_the_same_scopes(self) -> None:
        from kir.compiler import compile_program
        from kir.tests.fixtures import GROUND_SNAPSHOT

        level = GROUND_SNAPSHOT["levels"][0]["name"]
        ops = [
            {"op": "create_wall", "id": f"w{i}",
             "p0_mm": [i * 1000.0, 0.0], "p1_mm": [i * 1000.0, 6000.0],
             "level": {"by": "name", "value": level}, "height_mm": 3000.0}
            for i in range(12)
        ] + [
            {"op": "create_door", "id": f"d{i}",
             "host": {"by": "ref", "value": f"w{i}"}, "offset_mm": 1000.0}
            for i in range(4)
        ]
        program = {"ir_version": "1.0", "ops": ops}
        out = compile_program(program, revit_version="2023",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

        expectation = derive_expectation(program)
        rows = {r.categories: r for r in expectation.rows}
        self.assertEqual((rows[("OST_Walls",)].level,
                          rows[("OST_Walls",)].count), (level, 12))
        self.assertEqual((rows[("OST_Doors",)].level,
                          rows[("OST_Doors",)].count), (None, 4))


class TestNegativeControls(unittest.TestCase):
    """Deliberately wrong builds. EACH ONE must be rejected."""

    def setUp(self) -> None:
        self.expectation = derive_expectation(_walls_and_doors_program())
        # The predicate must be non-empty, otherwise "rejected" means nothing.
        self.assertTrue(self.expectation.checkable)

    def _verdict(self, after):
        return check_acceptance(self.expectation, BEFORE, after)

    def test_one_element_short_is_refused(self) -> None:
        """Built one element short of what the program calls for."""
        after = _census({("OST_Walls", L3): 111, ("OST_Doors", L3): 9,
                         ("OST_Walls", L4): 40})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        self.assertIn(MismatchCode.CATEGORY_SHORTFALL,
                      {m.code for m in verdict.mismatches})
        wall = next(m for m in verdict.mismatches
                    if m.categories == ("OST_Walls",)
                    and m.code is MismatchCode.CATEGORY_SHORTFALL)
        self.assertEqual((wall.expected, wall.observed), (12, 11))

    def test_one_element_short_in_a_floating_category_is_refused(self) -> None:
        """A shortfall where the level is NOT derivable (a door).

        A sixth control on top of the five mandatory ones, and it's not for
        completeness: for a door the per-level breakdown is empty, so the
        shortfall is caught by exactly one rule. A control caught by two
        rules at once does not prove that either one works.
        """
        after = _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 8,
                         ("OST_Walls", L4): 40})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        door = next(m for m in verdict.mismatches
                    if m.categories == ("OST_Doors",))
        self.assertEqual((door.code, door.expected, door.observed),
                         (MismatchCode.CATEGORY_SHORTFALL, 4, 3))

    def test_right_count_wrong_level_is_refused(self) -> None:
        """The total matches, the coverage doesn't: "built it somewhere
        else."

        This is exactly the class of case L2 exists for: any checker that
        only counts the total will silently say "it matches" here.
        """
        after = _census({("OST_Walls", L3): 100, ("OST_Doors", L3): 9,
                         ("OST_Walls", L4): 52})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        codes = {m.code for m in verdict.mismatches}
        self.assertIn(MismatchCode.LEVEL_SHORTFALL, codes)
        self.assertNotIn(MismatchCode.CATEGORY_SHORTFALL, codes,
                         "итог по категории сходится — обязан ловить именно "
                         "разрез по уровням")
        short = next(m for m in verdict.mismatches
                     if m.code is MismatchCode.LEVEL_SHORTFALL)
        self.assertEqual(short.level, L3)
        self.assertEqual((short.expected, short.observed), (12, 0))

    def test_built_twice_is_refused(self) -> None:
        """Built twice over — duplicates."""
        after = _census({("OST_Walls", L3): 124, ("OST_Doors", L3): 13,
                         ("OST_Walls", L4): 40})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        self.assertIn(MismatchCode.CATEGORY_OVERSHOOT,
                      {m.code for m in verdict.mismatches})

    def test_right_count_wrong_category_is_refused(self) -> None:
        """Exactly the right count, but in the wrong category."""
        after = _census({("OST_Walls", L3): 100, ("OST_Doors", L3): 5,
                         ("OST_Walls", L4): 40, ("OST_Floors", L3): 12})
        verdict = self._verdict(after)
        self.assertFalse(verdict.accepted)
        self.assertIn(("OST_Walls",),
                      {m.categories for m in verdict.mismatches})
        # The impostor category is named in the report, not silently ignored.
        self.assertIn(("OST_Floors", 12), verdict.unexpected)

    def test_empty_build_is_refused(self) -> None:
        """An empty build against a non-empty program."""
        verdict = self._verdict(BEFORE)
        self.assertFalse(verdict.accepted)
        self.assertEqual(
            {("OST_Walls",), ("OST_Doors",)},
            {m.categories for m in verdict.mismatches
             if m.code is MismatchCode.CATEGORY_SHORTFALL})


class TestPositiveControl(unittest.TestCase):
    """A correct build must PASS — otherwise the checker fails everything indiscriminately."""

    def test_correct_build_is_accepted(self) -> None:
        expectation = derive_expectation(_walls_and_doors_program())
        after = _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 9,
                         ("OST_Walls", L4): 40})
        verdict = check_acceptance(expectation, BEFORE, after)
        self.assertTrue(verdict.accepted, verdict.summary_ru())
        self.assertFalse(verdict.vacuous)
        self.assertGreaterEqual(verdict.checked_groups, 2)
        self.assertTrue(verdict.upper_bounds_checked)

    def test_doors_may_land_on_any_level(self) -> None:
        """Doors "float," and an honest build survives that.

        THE MEASUREMENT the rule rests on: a door's level differs from its
        host wall's level in 76 cases out of 15 569 (0.49%) across 31 saved
        parses — a door in wall L42 with a 400 mm offset gets the level
        "L42_+500." An expectation of "the door is on the host's level"
        would fail these builds, and invented precision is worse than no
        check at all.
        """
        expectation = derive_expectation(_walls_and_doors_program())
        after = _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 5,
                         ("OST_Doors", L4): 4, ("OST_Walls", L4): 40})
        verdict = check_acceptance(expectation, BEFORE, after)
        self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_derived_elements_do_not_break_a_correct_build(self) -> None:
        """Revit added its own (sketch lines, curtain wall panels) — this is not a refusal."""
        expectation = derive_expectation(_walls_and_doors_program())
        after = _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 9,
                         ("OST_Walls", L4): 40,
                         ("OST_CurtainWallPanels", L3): 300,
                         ("OST_SketchLines", ""): 4096})
        verdict = check_acceptance(expectation, BEFORE, after)
        self.assertTrue(verdict.accepted, verdict.summary_ru())
        # Panels are declared as derived for create_wall — they don't appear in the report.
        self.assertNotIn("OST_CurtainWallPanels",
                         {c for c, _ in verdict.unexpected})
        # create_wall does not generate sketch lines — they land in the
        # report, but the report is not a refusal.
        self.assertIn(("OST_SketchLines", 4096), verdict.unexpected)


class TestControlsCanFail(unittest.TestCase):
    """MUTATIONS: proof that each control is held up by a rule.

    A control that fails for an incidental reason proves no more than a
    witness that signed an axis it never read. Here the rule is broken by
    address, and the control MUST stop failing — that is when it is about
    this rule.
    """

    def setUp(self) -> None:
        self.expectation = derive_expectation(_walls_and_doors_program())
        self.builds = {
            "short": _census({("OST_Walls", L3): 111, ("OST_Doors", L3): 9,
                              ("OST_Walls", L4): 40}),
            "wrong_level": _census({("OST_Walls", L3): 100,
                                    ("OST_Doors", L3): 9,
                                    ("OST_Walls", L4): 52}),
            "doubled": _census({("OST_Walls", L3): 124, ("OST_Doors", L3): 13,
                                ("OST_Walls", L4): 40}),
            "wrong_category": _census({("OST_Walls", L3): 100,
                                       ("OST_Doors", L3): 5,
                                       ("OST_Walls", L4): 40,
                                       ("OST_Floors", L3): 12}),
            "empty": dict(BEFORE),
            # A door "floats" (its level is not derivable), so a shortfall
            # in it is caught ONLY by the total rule — the per-level
            # breakdown has nothing to grab onto here.
            "door_short": _census({("OST_Walls", L3): 112,
                                   ("OST_Doors", L3): 8,
                                   ("OST_Walls", L4): 40}),
        }

    def test_every_bad_build_fails_on_the_real_checker(self) -> None:
        for name, after in self.builds.items():
            with self.subTest(build=name):
                self.assertFalse(
                    check_acceptance(self.expectation, BEFORE, after).accepted)

    def test_blinded_checker_accepts_every_bad_build(self) -> None:
        """Blind both rules — and EVERY wrong build "passes."

        This is exactly the checker yesterday's self-check used to be. If
        some control keeps failing here, it is failing for an unrelated
        reason and proves nothing.
        """
        import dataclasses
        blinded = dataclasses.replace(self.expectation,
                                      upper_bounds_valid=False)
        with mock.patch.object(acceptance, "_check_total",
                               lambda *a, **k: []), \
                mock.patch.object(acceptance, "_check_levels",
                                  lambda *a, **k: []):
            for name, after in self.builds.items():
                with self.subTest(build=name):
                    self.assertTrue(
                        check_acceptance(blinded, BEFORE, after).accepted)

    def test_doubled_control_is_owned_by_the_upper_bound(self) -> None:
        """Remove the upper bound — and only "double" stops failing."""
        import dataclasses
        weakened = dataclasses.replace(self.expectation,
                                       upper_bounds_valid=False)
        self.assertTrue(
            check_acceptance(weakened, BEFORE, self.builds["doubled"]).accepted,
            "контроль «построено вдвое» держится ИМЕННО верхней границей")
        for name in ("short", "wrong_level", "wrong_category", "empty",
                     "door_short"):
            with self.subTest(build=name):
                self.assertFalse(
                    check_acceptance(weakened, BEFORE,
                                     self.builds[name]).accepted,
                    "нижние границы обязаны пережить снятие верхних")

    def test_wrong_level_control_is_owned_by_the_level_rule(self) -> None:
        """Remove the per-level breakdown — and only "on the wrong level" passes."""
        with mock.patch.object(acceptance, "_check_levels", lambda *a, **k: []):
            self.assertTrue(
                check_acceptance(self.expectation, BEFORE,
                                 self.builds["wrong_level"]).accepted)
            for name in ("short", "doubled", "wrong_category", "empty",
                         "door_short"):
                with self.subTest(build=name):
                    self.assertFalse(
                        check_acceptance(self.expectation, BEFORE,
                                         self.builds[name]).accepted)

    def test_floating_shortfall_is_owned_by_the_total_rule(self) -> None:
        """A shortfall in a "floating" category is held up SPECIFICALLY by
        the total.

        A door's level is not derivable, so the per-level breakdown has
        nothing to grab onto: remove the total — and the missing door
        passes. A control caught by TWO rules at once does not prove that
        either one works.
        """
        after = self.builds["door_short"]
        with mock.patch.object(acceptance, "_check_levels", lambda *a, **k: []):
            self.assertFalse(
                check_acceptance(self.expectation, BEFORE, after).accepted)
        with mock.patch.object(acceptance, "_check_total", lambda *a, **k: []):
            self.assertTrue(
                check_acceptance(self.expectation, BEFORE, after).accepted)


class TestOverlappingGroupsCannotPayOneElementTwice(unittest.TestCase):
    """F-094: ONE OBSERVED ELEMENT WAS CLOSING TWO INDEPENDENT LOWER BOUNDS.

    `create_floor` gives a group ("OST_Floors"), `create_foundation(slab)`
    gives ("OST_Floors", "OST_StructuralFoundation"). While the groups were
    checked SEPARATELY, both were reading the same `OST_Floors` delta, and a
    program of two ops was ACCEPTED after building one: `accepted=True,
    checked_groups=2, mismatches=[]`. Acceptance could not fail where it was
    supposed to.

    🔴 THE CARDINALITY WITHOUT WHICH THIS CONTROL IS GREEN BY CONSTRUCTION
    (shape 18). Double counting is only possible with TWO groups SHARING a
    category: a single group does not intersect itself, and the check on it
    can never fail. The predicate is pre-registered and checked by an
    assertion BEFORE the verdict — `_expectation()` refuses if the input is
    degenerate.

    THE INPUT IS BUILT BY PROD CODE (`derive_expectation` on a real
    program), not by hand: a hand-written `ExpectedRow` would only be
    guarding the fixture, while the intersection of groups here is a
    property OF THE REGISTRY, and it must be taken from the registry.
    """

    def _program(self) -> dict:
        return {"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": "f1",
             "outline": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 6000.0]],
             "level": {"by": "name", "value": L3}},
            {"op": "create_foundation", "id": "fd", "variety": "slab",
             "outline": [[0.0, 0.0], [3000.0, 0.0], [3000.0, 3000.0]],
             "level": {"by": "name", "value": L3}},
        ]}

    def _expectation(self):
        expectation = derive_expectation(self._program())
        groups = {row.categories for row in expectation.rows
                  if row.certainty is not Certainty.UNKNOWN and row.count}
        self.assertGreaterEqual(
            len(groups), 2,
            "вход выродился: групп меньше двух, двойной счёт невозможен")
        shared = set.intersection(*(set(group) for group in groups))
        self.assertTrue(
            shared,
            "вход выродился: группы не пересекаются, двойной счёт невозможен")
        return expectation

    def test_a_missing_foundation_is_refused(self) -> None:
        """THE ONE THING ALL OF THIS IS FOR: ONE floor was built instead of a floor AND a slab."""
        verdict = check_acceptance(
            self._expectation(), {}, {("OST_Floors", L3): 1})
        self.assertFalse(verdict.accepted, verdict.summary_ru())
        self.assertIn(MismatchCode.CATEGORY_SHORTFALL,
                      {m.code for m in verdict.mismatches})

    def test_the_honest_build_is_still_accepted(self) -> None:
        """The slab lands in EITHER of the two categories — both are honest."""
        for after in ({("OST_Floors", L3): 2},
                      {("OST_Floors", L3): 1,
                       ("OST_StructuralFoundation", L3): 1}):
            with self.subTest(after=tuple(sorted(after))):
                verdict = check_acceptance(self._expectation(), {}, after)
                self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_the_two_groups_become_one_comparison(self) -> None:
        """ONE check, not two: otherwise the element pays twice again."""
        verdict = check_acceptance(
            self._expectation(), {}, {("OST_Floors", L3): 2})
        self.assertEqual(verdict.checked_groups, 1)

    def test_overlap_no_longer_costs_the_upper_bound(self) -> None:
        """And the other side of the merge: "no more than" is provable
        again.

        After the merge an element is counted exactly once, so the
        arithmetic that used to lift the upper bound on intersection
        disappeared along with the double counting: three floors for a
        program of two ops is too many.
        """
        verdict = check_acceptance(
            self._expectation(), {}, {("OST_Floors", L3): 3})
        self.assertFalse(verdict.accepted, verdict.summary_ru())
        self.assertIn(MismatchCode.CATEGORY_OVERSHOOT,
                      {m.code for m in verdict.mismatches})

    def test_the_refusal_is_owned_by_the_merge(self) -> None:
        """A NARROW FAIL CONTROL: bring back the PER-GROUP check — the
        defect comes back to life.

        What is mutated is not a word or a message but the dispatch point
        itself: `_merge_overlapping_groups` is replaced by the identity
        "each group on its own," i.e., exactly the code that stood before
        the fix. If the refusal is held up by something else, it will
        remain, and the test will see it.
        """
        expectation = self._expectation()
        after = {("OST_Floors", L3): 1}
        self.assertFalse(check_acceptance(expectation, {}, after).accepted)

        with mock.patch.object(acceptance, "_merge_overlapping_groups",
                               _unmerged_groups):
            revived = check_acceptance(expectation, {}, after)
        self.assertTrue(
            revived.accepted,
            "отказ обязан держаться СЛИЯНИЕМ групп, а не посторонним поводом")
        self.assertEqual(revived.checked_groups, 2)

    def test_a_non_overlapping_program_is_untouched_by_the_merge(self) -> None:
        """Inertness: where there is no intersection, merging changes
        NOTHING.

        Twelve walls and four doors — the categories don't intersect, so the
        verdict must match the verdict WITHOUT merging, byte for byte.
        Without this assertion, the fix could glue everything to everything
        and stay green on its own example.
        """
        expectation = derive_expectation(_walls_and_doors_program())
        builds = {
            "good": _census({("OST_Walls", L3): 112, ("OST_Doors", L3): 9,
                             ("OST_Walls", L4): 40}),
            "short": _census({("OST_Walls", L3): 111, ("OST_Doors", L3): 9,
                              ("OST_Walls", L4): 40}),
        }
        for name, after in builds.items():
            with self.subTest(build=name):
                merged = check_acceptance(expectation, BEFORE, after)
                with mock.patch.object(acceptance,
                                       "_merge_overlapping_groups",
                                       _unmerged_groups):
                    plain = check_acceptance(expectation, BEFORE, after)
                self.assertEqual(merged.to_dict(), plain.to_dict())


class TestExpectationDerivation(unittest.TestCase):
    """The expectation is derived from the program mechanically — there is nothing to weaken."""

    def test_walls_are_scoped_by_level(self) -> None:
        expectation = derive_expectation(_walls_and_doors_program())
        walls = [r for r in expectation.rows if r.categories == ("OST_Walls",)]
        self.assertEqual(len(walls), 1)
        self.assertEqual((walls[0].level, walls[0].count, walls[0].certainty),
                         (L3, 12, Certainty.EXACT))

    def test_doors_are_floating_not_invented(self) -> None:
        expectation = derive_expectation(_walls_and_doors_program())
        doors = [r for r in expectation.rows if r.categories == ("OST_Doors",)]
        self.assertEqual(len(doors), 1)
        self.assertIsNone(doors[0].level,
                          "уровень двери не выводится из хозяина — замерено")
        self.assertEqual(doors[0].count, 4)

    def test_level_by_ref_resolves_to_the_declared_name(self) -> None:
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_level", "id": "lv", "elev_mm": 6000.0,
             "name": "Этаж 3"},
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [5000.0, 0.0], "level": {"by": "ref", "value": "lv"}},
        ]}
        rows = {r.categories: r for r in derive_expectation(program).rows}
        self.assertEqual(rows[("OST_Walls",)].level, "Этаж 3")
        self.assertEqual(rows[("OST_Levels",)].count, 1)

    def test_level_by_element_id_stays_unknown_without_the_lookup(self) -> None:
        """id is not a name; without the model's lookup there is nothing to substitute."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [5000.0, 0.0],
             "level": {"by": "element_id", "value": 1679}},
        ]}
        row = derive_expectation(program).rows[0]
        self.assertIsNone(row.level)

    def test_level_lookup_locates_a_pinned_level(self) -> None:
        """The level lookup returns L2 onto the rebuild path.

        The materializer pins the level by ElementId, and without the
        lookup, on a real building (11 programs, 2 720 ops), ZERO out of
        2 450 rows were placed — acceptance degenerated into a totals
        check.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [5000.0, 0.0],
             "level": {"by": "element_id", "value": 1679}},
        ]}
        expectation = derive_expectation(program,
                                         level_names_by_id={1679: L3})
        self.assertEqual(expectation.rows[0].level, L3)
        # And now "on the wrong level" is caught on the rebuild program.
        verdict = check_acceptance(expectation, {}, {("OST_Walls", L4): 1})
        self.assertFalse(verdict.accepted)
        self.assertIn(MismatchCode.LEVEL_SHORTFALL,
                      {m.code for m in verdict.mismatches})

    def test_stack_macro_expands_into_per_storey_scopes(self) -> None:
        """A macro is also a program, and the expectation is computed AFTER expansion."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "stack", "id": "s", "levels": 3, "h_mm": 3000,
            "name_prefix": "Этаж",
            "floor": [{"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
                       "p1_mm": [6000.0, 0.0], "height_mm": 3000.0}],
        }]}
        expectation = derive_expectation(program)
        walls = {r.level: r.count for r in expectation.rows
                 if r.categories == ("OST_Walls",)}
        self.assertEqual(walls, {"Этаж 1": 1, "Этаж 2": 1, "Этаж 3": 1})
        levels = [r for r in expectation.rows if r.categories == ("OST_Levels",)]
        self.assertEqual(levels[0].count, 3)

    def test_defaults_envelope_fills_the_level(self) -> None:
        program = {"ir_version": "1.0",
                   "defaults": {"level": {"by": "name", "value": L4}},
                   "ops": [{"op": "create_wall", "id": "w",
                            "p0_mm": [0.0, 0.0], "p1_mm": [6000.0, 0.0]}]}
        self.assertEqual(derive_expectation(program).rows[0].level, L4)

    def test_graph_op_counts_segments_and_leaves_fitting_count_unclaimed(self) -> None:
        """One op — many pipes; the NUMBER of fittings is not declared.

        The name and docstring were fixed on 10.08.2026. It used to say:
        "Revit makes the fittings itself," citing "2 652 fittings and 152
        pieces of rebar at ZERO authored." Both are wrong: the fittings are
        created by the op itself (`emit_fittings_cs` ->
        NewElbowFitting/NewTeeFitting/NewTransitionFitting at every node of
        degree >= 2), and the numbers come from the snowdon_plumb_v3 census
        (PF=2652, DF=152, PA=126), where "152" is duct fittings, not rebar,
        and no emitter in the package creates rebar at all.

        So the checked assertion is now both narrower and more honest: the
        op names the number of PIPES (= len(segments)) and does NOT name the
        number of fittings — it is not derivable from any measurement,
        because a joint can reduce to a bare Connector.ConnectTo with no
        element, and the family is chosen by routing preferences. Declaring
        it as a number would fail every honest run of piping.
        """
        program = {"ir_version": "1.0", "ops": [{
            "op": "route_pipe_system", "id": "r",
            "level": {"by": "name", "value": L3},
            "nodes": [{"id": "a", "xyz_mm": [0.0, 0.0, 0.0]},
                      {"id": "b", "xyz_mm": [3000.0, 0.0, 0.0]},
                      {"id": "c", "xyz_mm": [3000.0, 3000.0, 0.0]}],
            "segments": [{"from": "a", "to": "b"}, {"from": "b", "to": "c"}],
        }]}
        expectation = derive_expectation(program)
        pipes = [r for r in expectation.rows
                 if r.categories == ("OST_PipeCurves",)]
        self.assertEqual((pipes[0].count, pipes[0].certainty, pipes[0].level),
                         (2, Certainty.EXACT, L3))
        self.assertIn("OST_PipeFitting", expectation.derived_categories)
        self.assertIn("OST_PipeAccessory", expectation.derived_categories)

    def test_hosted_railing_is_at_least_one(self) -> None:
        """Railing.Create(host) hands back A COLLECTION — "exactly 1" would be made up."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_railing", "id": "r", "variety": "hosted",
            "host": {"by": "element_id", "value": 4242},
            "position": "treads",
        }]}
        row = derive_expectation(program).rows[0]
        self.assertEqual(row.certainty, Certainty.AT_LEAST)
        self.assertEqual(row.count, 1)
        self.assertEqual(row.categories, ("OST_Railings", "OST_StairsRailing"))

    def test_at_least_row_survives_extra_elements(self) -> None:
        """"At least" must let more through and refuse on fewer."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_railing", "id": "r", "variety": "hosted",
            "host": {"by": "element_id", "value": 4242},
            "position": "treads",
        }]}
        expectation = derive_expectation(program)
        before = {("OST_StairsRailing", L3): 10}
        self.assertTrue(check_acceptance(
            expectation, before, {("OST_StairsRailing", L3): 12}).accepted)
        self.assertFalse(check_acceptance(
            expectation, before, {("OST_StairsRailing", L3): 10}).accepted)

    def test_beam_and_stairs_levels_are_not_claimed(self) -> None:
        """Both "float," and both do so by measurement, not by caution.

        The beam: Revit derives the reference level from the curve's
        elevation, not from the argument (recorded in the op's own post,
        measured 27.07).
        The stair: 0 rows out of 351 across 31 parses carry level_name.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_beam", "id": "b", "p0_mm": [0.0, 0.0, 3000.0],
             "p1_mm": [6000.0, 0.0, 3000.0],
             "level": {"by": "name", "value": L3}},
            {"op": "create_stairs", "id": "s", "p0_mm": [0.0, 0.0],
             "p1_mm": [3000.0, 0.0],
             "base_level": {"by": "name", "value": L3},
             "top_level": {"by": "name", "value": L4}},
        ]}
        for row in derive_expectation(program).rows:
            with self.subTest(categories=row.categories):
                self.assertIsNone(row.level)

    def test_group_multiplies_members_by_occurrences(self) -> None:
        """Occupancy 0 is the members themselves; every placement adds one more."""
        member = {"op": "create_wall", "id": "m", "p0_mm": [0.0, 0.0],
                  "p1_mm": [6000.0, 0.0],
                  "level": {"by": "name", "value": L3}}
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_group", "id": "g", "members": [member],
            "placements": [[6000.0, 0.0, 0.0], [12000.0, 0.0, 0.0]],
        }]}
        expectation = derive_expectation(program)
        walls = [r for r in expectation.rows if r.categories == ("OST_Walls",)]
        self.assertEqual((walls[0].count, walls[0].level), (3, L3))
        self.assertIn("OST_IOSModelGroups", expectation.derived_categories)

    def test_overlapping_category_groups_are_checked_as_one(self) -> None:
        """A floor slab and a foundation slab share OST_Floors — ONE check.

        An honest build (3 floors + a slab, landing in OST_Floors) must read
        as "4 were added against 4 declared," not as "4 instead of 3": a
        check that lies on a correct result is the fastest way to get itself
        turned off.

        🔴 THE NAME AND DOCSTRING HERE WERE FIXED ON 03.09.2026, AND THE OLD
        ONES WERE WRONG. The test was called `..._lose_their_upper_bound` and
        explained removing the upper bound as THE CURE. It was not the cure:
        the upper bound was lifted while the lower bound stayed PER-GROUP,
        and one observed floor was closing both lower bounds — acceptance
        was accepting a program that built half of it (F-094). The test's
        assertions did not move a single character from the fix; what moved
        was the reason they are correct, and that is why the name had to be
        rewritten.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_floor", "id": f"f{i}",
             "outline": [[0.0, 0.0], [6000.0, 0.0], [6000.0, 6000.0]],
             "level": {"by": "name", "value": L3}} for i in range(3)
        ] + [
            {"op": "create_foundation", "id": "fd", "variety": "slab",
             "outline": [[0.0, 0.0], [3000.0, 0.0], [3000.0, 3000.0]],
             "level": {"by": "name", "value": L3}},
        ]}
        expectation = derive_expectation(program)
        self.assertTrue(expectation.upper_bounds_valid)
        verdict = check_acceptance(expectation, {}, {("OST_Floors", L3): 4})
        self.assertTrue(verdict.accepted, verdict.summary_ru())
        # And a shortfall is still caught.
        self.assertFalse(
            check_acceptance(expectation, {}, {("OST_Floors", L3): 2}).accepted)

    def test_a_derived_category_never_gets_an_upper_bound(self) -> None:
        """The stair makes its own railings — "exactly 1 railing" would
        lie.

        The program is SOLO, and this is not cosmetic. Before 04.08 this
        held a stair AND a railing together — a program `emit_program`
        always refused to assemble (KIR-L002: `StairsEditScope` owns its own
        transactions). The plan used to accept it back then, so the test
        passed while checking behavior on an input that would never have
        reached Revit. The rule moved onto the plan, and the input had to be
        brought in line with what's legal — the test's assertion did not
        change because of this: a railing is derived FROM THE STAIR, no
        `create_railing` of its own is needed for it.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_stairs", "id": "s", "p0_mm": [0.0, 0.0],
             "p1_mm": [3000.0, 0.0],
             "base_level": {"by": "name", "value": L3},
             "top_level": {"by": "name", "value": L4}},
        ]}
        expectation = derive_expectation(program)
        self.assertIn("OST_StairsRailing", expectation.derived_categories)
        verdict = check_acceptance(
            expectation, {},
            {("OST_Stairs", ""): 1, ("OST_StairsRailing", L3): 5})
        self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_a_stairs_program_with_a_neighbour_fails_closed_by_name(self) -> None:
        """And the other side: an illegal program must not "give an empty
        census," it must NAME the reason. Acceptance is fail-closed, and its
        refusal carries the rule's code, not a generic phrase."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_stairs", "id": "s", "p0_mm": [0.0, 0.0],
             "p1_mm": [3000.0, 0.0],
             "base_level": {"by": "name", "value": L3},
             "top_level": {"by": "name", "value": L4}},
            {"op": "create_railing", "id": "r", "variety": "path",
             "path": [[0.0, 0.0], [3000.0, 0.0]],
             "level": {"by": "name", "value": L3}},
        ]}
        expectation = derive_expectation(program)
        self.assertEqual(expectation.derived_categories, ())
        self.assertTrue(any("KIR-L002" in note for note in expectation.notes),
                        expectation.notes)

    def test_type_ops_add_no_elements(self) -> None:
        """The §18.1 census is WhereElementIsNotElementType(); types do not go into it."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "load_family", "id": "lf", "path": "C:/f.rfa"},
            {"op": "create_type", "id": "ct",
             "source_type": {"by": "name", "value": "К1"},
             "new_name": "К2", "width_mm": 400.0},
        ]}
        expectation = derive_expectation(program)
        self.assertEqual(expectation.rows, ())
        self.assertEqual(expectation.blind_ops, ())
        self.assertFalse(expectation.checkable)

    def test_unknown_category_op_is_named_and_disables_upper_bounds(self) -> None:
        """Blindness must be NAMED, and the upper bound honestly removed."""
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [6000.0, 0.0], "level": {"by": "name", "value": L3}},
            {"op": "place_family", "id": "p", "xyz": [0.0, 0.0, 0.0],
             "level": {"by": "name", "value": L3}},
        ]}
        expectation = derive_expectation(program)
        self.assertFalse(expectation.upper_bounds_valid)
        self.assertEqual([b.op_name for b in expectation.blind_ops],
                         ["place_family"])
        self.assertTrue(expectation.blind_ops[0].reason)
        verdict = check_acceptance(expectation, {}, {("OST_Walls", L3): 5})
        self.assertTrue(verdict.accepted, "верх открыт — 5 стен не отказ")
        self.assertFalse(verdict.upper_bounds_checked)
        self.assertEqual(verdict.blind_ops, expectation.blind_ops)

    def test_subtractive_blind_op_cannot_false_reject_a_mixed_create(self) -> None:
        """Net delta cannot prove creation while an old cell may be removed."""

        program = {"ir_version": "1.0", "allow_destructive": True, "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [6000.0, 0.0],
             "level": {"by": "name", "value": L3}},
            {"op": "delete", "id": "d",
             "target": {"by": "element_id", "value": 101}},
        ]}
        expectation = derive_expectation(program)

        self.assertFalse(expectation.lower_bounds_valid)
        self.assertFalse(expectation.checkable)
        # One wall was created and one old wall was deleted: net zero is a
        # correct execution, not a category_shortfall.  L2 must abstain.
        verdict = check_acceptance(
            expectation,
            {("OST_Walls", L3): 10},
            {("OST_Walls", L3): 10},
        )
        self.assertTrue(verdict.vacuous)
        self.assertEqual(verdict.mismatches, ())
        self.assertFalse(verdict.upper_bounds_checked)


FURNITURE = "OST_Furniture"


def _symbol_pool(**overrides):
    """One row of the family_symbols pool — the shape is exactly like open_model's."""
    row = {"id": 800, "name": "Стол 1200", "category": FURNITURE,
           "family_name": "Стол офисный", "type_name": "Стол 1200",
           "instances": 4}
    row.update(overrides)
    return [row]


def _place_program(symbol=None, *, count=1):
    ops = []
    for index in range(count):
        op = {"op": "place_family", "id": f"f{index}",
              "xyz": [1000.0 * index, 1000.0, 0.0],
              "level": {"by": "name", "value": L3}}
        if symbol is not None:
            op["symbol"] = symbol
        ops.append(op)
    return {"ir_version": "1.0", "ops": ops}


_BY_TYPE = {"by": "family_type", "category": FURNITURE,
            "family_name": "Стол офисный", "type_name": "Стол 1200"}


class TestPlaceFamilyScope(unittest.TestCase):
    """The registry's most heavily loaded writing op is REQUIRED TO REACH acceptance.

    7,000 built instances against 6 accused — and before 09.08 not one of
    them could obtain an independent "match": `place_family` was
    unconditionally blind, and a blind op in the program makes the verdict
    INCONCLUSIVE for any construction, however correct. The blindness was
    NOT WHERE it was recorded: the category indeed cannot be read from the
    program, but it lies in the model snapshot — the same BuiltInCategory
    string that the live census keys on.

    The order of this class is the same as for the file: first refusal to
    judge (easy to lose silently), then a false refusal of a correct
    construction (the most expensive kind), and only then green.
    """

    def test_the_control_program_compiles_against_the_same_snapshot(self) -> None:
        """Anchor: the predicate is derived from a program the compiler ACCEPTS."""
        from kir.compiler import compile_program
        from kir.tests.fixtures import GROUND_SNAPSHOT

        program = _place_program(_BY_TYPE)
        program["ops"][0]["level"] = {
            "by": "name", "value": GROUND_SNAPSHOT["levels"][0]["name"]}
        out = compile_program(program, revit_version="2023",
                              snapshot=GROUND_SNAPSHOT)
        self.assertTrue(out.ok, [d.as_dict() for d in out.diagnostics])

        expectation = acceptance.derive_expectation(
            out.planned,
            family_symbols=acceptance.symbol_rows_from_snapshot(GROUND_SNAPSHOT))
        self.assertEqual(expectation.blind_ops, ())
        self.assertEqual(len(expectation.rows), 1)
        self.assertEqual(expectation.rows[0].categories, (FURNITURE,))
        self.assertTrue(expectation.checkable)

    # ── refusal to judge: every branch is NAMED ──────────────────────────

    def _blind_reason(self, expectation) -> str:
        self.assertEqual(expectation.rows, ())
        self.assertEqual([b.op_name for b in expectation.blind_ops],
                         ["place_family"])
        self.assertFalse(expectation.checkable,
                         "неизмеренная ветка обязана остаться ok:false")
        return expectation.blind_ops[0].reason

    def test_without_a_snapshot_pool_it_abstains(self) -> None:
        """There is no pool — there is nowhere to take the category from, and this is NAMED."""
        reason = self._blind_reason(
            acceptance.derive_expectation(_place_program(_BY_TYPE)))
        self.assertIn("пул family_symbols", reason)

    def test_a_truncated_pool_abstains(self) -> None:
        """A symbol of another category could remain behind the slice (the same argument as F7)."""
        snapshot = {"family_symbols": _symbol_pool(),
                    "family_symbols__truncated": True}
        self.assertIsNone(acceptance.symbol_rows_from_snapshot(snapshot))
        reason = self._blind_reason(acceptance.derive_expectation(
            _place_program(_BY_TYPE),
            family_symbols=acceptance.symbol_rows_from_snapshot(snapshot)))
        self.assertIn("обрезан", reason)

    def test_candidates_of_different_categories_abstain(self) -> None:
        """One name for two kinds of thing — which cell will grow is unknown."""
        pool = _symbol_pool() + [{
            "id": 801, "name": "Стол 1200", "category": "OST_Casework",
            "family_name": "Стол лабораторный", "type_name": "Стол 1200"}]
        reason = self._blind_reason(acceptance.derive_expectation(
            _place_program({"by": "name", "value": "Стол 1200"}),
            family_symbols=pool))
        self.assertIn("2 разных категорий", reason)

    def test_a_symbol_made_by_this_same_program_abstains(self) -> None:
        """create_type/load_family — that very partial_blind_scope of the contract.

        A symbol created within this same program is, by construction, not
        present in the snapshot taken BEFORE the write, and there is nothing
        from which to invent its category.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_type", "id": "t",
             "source_type": {"by": "name", "value": "К 300x300"},
             "new_name": "К2", "width_mm": 400.0},
            {"op": "place_family", "id": "f", "xyz": [0.0, 0.0, 0.0],
             "level": {"by": "name", "value": L3},
             "symbol": {"by": "name", "value": "К2"}},
        ]}
        reason = self._blind_reason(acceptance.derive_expectation(
            program, family_symbols=_symbol_pool()))
        self.assertIn("нет в снимке ДО записи", reason)

    def test_a_category_the_census_cannot_isolate_abstains(self) -> None:
        """The live census will NOT SINGLE OUT the snapshot's numeric key — hence refusal.

        The snapshot falls back to `__categoryId.ToString()` when there is no
        name in BuiltInCategory; the census, however, keys ONLY by name and
        will discard such a string. To assert about a cell that will not be
        in the census means rejecting a correct construction.
        """
        reason = self._blind_reason(acceptance.derive_expectation(
            _place_program({"by": "element_id", "value": 800}),
            family_symbols=_symbol_pool(category="-2000151")))
        self.assertIn("BuiltInCategory", reason)

    def test_the_census_key_rule_is_what_refuses(self) -> None:
        """MUTATION: break the keying rule — and the refusal STOPS happening.

        Otherwise the test above would prove only that something, somewhere, refused.
        """
        with mock.patch.object(acceptance, "_CENSUS_CATEGORY_RE",
                               re.compile(r".*")):
            expectation = acceptance.derive_expectation(
                _place_program({"by": "element_id", "value": 800}),
                family_symbols=_symbol_pool(category="-2000151"))
        self.assertEqual(expectation.blind_ops, ())

    # ── false refusal of a correct construction — the most expensive kind ─────────────────────

    def test_extra_nested_children_are_not_a_rejection(self) -> None:
        """Revit creates nested shared families ITSELF (21,555 on the tower).

        `EXACT` here would reject every honest construction of such a
        family, so the number is declared as "at least".
        """
        expectation = acceptance.derive_expectation(
            _place_program(_BY_TYPE), family_symbols=_symbol_pool())
        self.assertEqual(expectation.rows[0].certainty, Certainty.AT_LEAST)
        verdict = check_acceptance(expectation, {(FURNITURE, ""): 0},
                                   {(FURNITURE, ""): 4})
        self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_the_level_is_never_asserted(self) -> None:
        """The FamilyInstance level is not declared — measured on a door (76/15,569).

        The instance landed on the NEIGHBORING level: L2 is REQUIRED to stay
        silent, not reject the construction over an unmeasured axis.
        """
        expectation = acceptance.derive_expectation(
            _place_program(_BY_TYPE), family_symbols=_symbol_pool())
        self.assertIsNone(expectation.rows[0].level)
        verdict = check_acceptance(expectation, {}, {(FURNITURE, L4): 1})
        self.assertTrue(verdict.accepted, verdict.summary_ru())

    def test_upper_bounds_stay_off_for_the_whole_program(self) -> None:
        """A nested child may legitimately land in the category of a NEIGHBORING op.

        So the upper bound is removed entirely — exactly as it was under
        blindness, no loss occurs. The reason MUST be visible in the
        expectation itself.
        """
        program = {"ir_version": "1.0", "ops": [
            {"op": "create_wall", "id": "w", "p0_mm": [0.0, 0.0],
             "p1_mm": [6000.0, 0.0], "level": {"by": "name", "value": L3}},
            {"op": "place_family", "id": "f", "xyz": [0.0, 0.0, 0.0],
             "level": {"by": "name", "value": L3}, "symbol": _BY_TYPE},
        ]}
        expectation = acceptance.derive_expectation(
            program, family_symbols=_symbol_pool())
        self.assertEqual(expectation.blind_ops, ())
        self.assertFalse(expectation.upper_bounds_valid)
        self.assertTrue(any("верхние границы" in note
                            for note in expectation.notes))
        # One wall per the program, FOUR in the model: an overrun is not judged.
        verdict = check_acceptance(expectation, {},
                                   {("OST_Walls", L3): 4, (FURNITURE, ""): 1})
        self.assertTrue(verdict.accepted, verdict.summary_ru())
        self.assertFalse(verdict.upper_bounds_checked)

    # ── and only now, green and red ────────────────────────────────

    def test_a_placement_that_did_not_happen_is_refused(self) -> None:
        expectation = acceptance.derive_expectation(
            _place_program(_BY_TYPE), family_symbols=_symbol_pool())
        verdict = check_acceptance(expectation, {(FURNITURE, ""): 7},
                                   {(FURNITURE, ""): 7})
        self.assertFalse(verdict.accepted)
        self.assertEqual([m.code for m in verdict.mismatches],
                         [MismatchCode.CATEGORY_SHORTFALL])
        self.assertEqual((verdict.mismatches[0].expected,
                          verdict.mismatches[0].observed), (1, 0))

    def test_two_placements_short_by_one_are_refused(self) -> None:
        expectation = acceptance.derive_expectation(
            _place_program(_BY_TYPE, count=2), family_symbols=_symbol_pool())
        self.assertEqual(expectation.rows[0].count, 2)
        verdict = check_acceptance(expectation, {(FURNITURE, ""): 7},
                                   {(FURNITURE, ""): 8})
        self.assertFalse(verdict.accepted)

    def test_the_category_follows_the_SNAPSHOT_not_the_program(self) -> None:
        """The key difference from a "declared expectation": this is DATA ABOUT THE MODEL.

        The same name selector against a pool with a different category
        yields a different cell — meaning the assertion is not copied from
        the program, but read from Revit.
        """
        selector = {"by": "name", "value": "Стол 1200"}
        first = acceptance.derive_expectation(_place_program(selector),
                                              family_symbols=_symbol_pool())
        second = acceptance.derive_expectation(
            _place_program(selector),
            family_symbols=_symbol_pool(category="OST_Casework"))
        self.assertEqual(first.rows[0].categories, (FURNITURE,))
        self.assertEqual(second.rows[0].categories, ("OST_Casework",))
        self.assertNotEqual(expectation_digest(first), expectation_digest(second))

    def test_group_placements_multiply_the_member(self) -> None:
        """An op inside a group is counted by occupancy count, like all the others."""
        program = {"ir_version": "1.0", "ops": [{
            "op": "create_group", "id": "g",
            "members": [{"op": "place_family", "id": "f",
                         "xyz": [0.0, 0.0, 0.0],
                         "level": {"by": "name", "value": L3},
                         "symbol": _BY_TYPE}],
            "placements": [[5000.0, 0.0], [10000.0, 0.0]],
        }]}
        expectation = acceptance.derive_expectation(
            program, family_symbols=_symbol_pool())
        rows = [r for r in expectation.rows if r.categories == (FURNITURE,)]
        self.assertEqual([r.count for r in rows], [3])


class TestPurityAndStability(unittest.TestCase):
    """The expectation is serializable and identical across processes."""

    def test_expectation_is_json_serialisable_and_stable(self) -> None:
        program = _walls_and_doors_program()
        first = derive_expectation(program)
        # The order of independent ops must not change the expectation.
        # Dependencies remain topological: a door cannot precede its own wall.
        walls, doors = program["ops"][:12], program["ops"][12:]
        shuffled = {"ir_version": "1.0",
                    "ops": list(reversed(walls)) + list(reversed(doors))}
        second = derive_expectation(shuffled)
        self.assertEqual(expectation_digest(first), expectation_digest(second))
        payload = json.dumps(first.to_dict(), ensure_ascii=False,
                             sort_keys=True)
        self.assertEqual(json.loads(payload), first.to_dict())

    def test_digest_changes_when_the_program_changes(self) -> None:
        """The signature MUST DISTINGUISH — otherwise pre-registration gives nothing."""
        base = derive_expectation(_walls_and_doors_program())
        program = _walls_and_doors_program()
        program["ops"][0]["level"] = {"by": "name", "value": L4}
        self.assertNotEqual(expectation_digest(base),
                            expectation_digest(derive_expectation(program)))

    def test_derivation_does_not_mutate_the_program(self) -> None:
        program = _walls_and_doors_program()
        snapshot = json.dumps(program, ensure_ascii=False, sort_keys=True)
        derive_expectation(program)
        self.assertEqual(json.dumps(program, ensure_ascii=False,
                                    sort_keys=True), snapshot)

    def test_malformed_program_yields_an_empty_but_honest_expectation(self) -> None:
        """Unexpanded macros are a recorded cause, not a silent success."""
        broken = {"ir_version": "1.0", "ops": [
            {"op": "stack", "id": "s", "levels": 999, "floor": []}]}
        expectation = derive_expectation(broken)
        self.assertEqual(expectation.rows, ())
        self.assertTrue(expectation.notes)
        verdict = check_acceptance(expectation, {}, {})
        self.assertTrue(verdict.vacuous)
        self.assertIn("НИЧЕГО", verdict.summary_ru())


class TestRegistryCoverage(unittest.TestCase):
    """Structural guards: a new op cannot fail silently."""

    def test_every_writing_op_is_classified(self) -> None:
        """A registry op about which the tables are silent MUST fail the build.

        Otherwise it silently becomes "blind", removes upper bounds across
        the WHOLE program, and acceptance quietly weakens — exactly the
        class of defect where, on 30.07, the authoring stage answered with a
        field of the wrong name.
        """
        from kir.acceptance import (
            _LEVEL_FROM_PARAM, _OPS_BLIND, _OPS_WITHOUT_ELEMENTS,
            _OP_CATEGORIES,
        )
        # "special" — ops whose category is derived by a BRANCH in
        # _category_of_op, rather than by a table row (their category
        # depends on their own field). create_opening is here for the same
        # reason as create_foundation: the opening's `variety` decides —
        # wall_rect gives exactly OST_SWallRectOpening, while host_face
        # depends on the HOST's category, which cannot be read from the
        # program, and is checked against the sum over three kinds.
        # create_topography is here for the same reason as create_foundation:
        # the terrain variant chooses the CATEGORY (OST_Topography versus
        # OST_Toposolid), and the branch in _category_of_op names it
        # precisely — summing over two keys would conceal exactly the
        # substitution the operation forbids.
        # wave/solid (09.08): both bodies place the result into a DirectShape
        # of the same category from the same closed table, so they travel
        # the SAME branch as the mesh does — not a table row. The sets are
        # ADDED TOGETHER, not chosen one-or-the-other: each wave here has its
        # own ops and none knew about the others'.
        # 🔴 THE DirectShape FAMILY IS NOW ASKED FROM THE REGISTRY
        # (21.08.2026). Here its three ops were enumerated BY HAND, and the
        # comment above itself admits the reason: "each wave here has its own
        # ops and none knew about the others'". The 20.08 wave brought in
        # four more with the same enumeration of categories and the same
        # DirectShape — the list never learned about them, and the test was
        # red for a full day. The signature lives in
        # `spec._directshape_result_ops()`; this is already the THIRD place
        # where a hand-copied family diverged from the registry, and the
        # last of them.
        special = set(spec._directshape_result_ops()) | {
            "create_column", "create_foundation",
            "create_group", "create_opening", "create_topography"}
        classified = (set(_OP_CATEGORIES) | set(_OPS_BLIND)
                      | set(_OPS_WITHOUT_ELEMENTS) | special)
        writing = {name for name, op in spec.OPS.items() if op.writes_model}
        self.assertEqual(writing - classified, set(),
                         "оп реестра не разобран в acceptance.py")
        self.assertEqual(classified - writing, set(),
                         "в таблицах acceptance.py есть несуществующий оп")
        self.assertLessEqual(_LEVEL_FROM_PARAM, writing)

    def test_level_from_param_ops_actually_have_a_level_param(self) -> None:
        from kir.acceptance import _LEVEL_FROM_PARAM
        for name in sorted(_LEVEL_FROM_PARAM):
            with self.subTest(op=name):
                self.assertIn("level",
                              {p.name for p in spec.OPS[name].params})

    def test_every_non_census_write_enters_mutation_acceptance(self) -> None:
        from kir.acceptance import _OPS_WITHOUT_ELEMENTS
        from kir.acceptance_mutation import MUTATION_ACCEPTANCE_OPS

        self.assertEqual(
            set(_OPS_WITHOUT_ELEMENTS) | {"delete", "change_type"},
            set(MUTATION_ACCEPTANCE_OPS),
            "write op is invisible to census but missing from exact mutation "
            "acceptance (or vice versa)",
        )

    def test_categories_agree_with_the_lifter_table(self) -> None:
        """The forward and reverse pass MUST call the category the same way.

        The table here is EXPLICIT, not derived from lift.LIFTER_TABLE (they
        ask different questions), but wherever both speak about the same op,
        a discrepancy is a defect: one of the two calls the category by the
        wrong name.
        """
        from kir.decompile.lift import LIFTER_TABLE
        from kir.acceptance import _OP_CATEGORIES

        by_op: dict[str, set[str]] = {}
        for category, (_kind, op_name) in LIFTER_TABLE.items():
            by_op.setdefault(op_name, set()).add(category)
        for op_name, declared in _OP_CATEGORIES.items():
            if op_name not in by_op:
                continue
            with self.subTest(op=op_name):
                self.assertTrue(
                    set(declared) & by_op[op_name],
                    f"{op_name}: приёмка ждёт {sorted(declared)}, лифтер "
                    f"поднимает из {sorted(by_op[op_name])}")

    def test_derived_categories_are_never_also_expected(self) -> None:
        """A category cannot be both authored and derived at the same time."""
        from kir.acceptance import _OP_CATEGORIES, _OP_DERIVED
        for op_name, derived in _OP_DERIVED.items():
            with self.subTest(op=op_name):
                self.assertFalse(
                    set(derived) & set(_OP_CATEGORIES.get(op_name, ())))


class TestScopeCensusHelper(unittest.TestCase):
    """Scope census: (category, level) → how many."""

    def test_counts_rows_and_keeps_levelless_elements(self) -> None:
        rows = [
            {"category": "OST_Walls", "level_name": " Этаж 3 "},
            {"category": "OST_Walls", "level_name": "Этаж 3"},
            {"category": "OST_Stairs", "level_name": None},
            {"category": "OST_Dimensions"},
        ]
        self.assertEqual(scope_census_from_elements(rows), {
            ("OST_Walls", L3): 2,
            ("OST_Stairs", ""): 1,
            ("OST_Dimensions", ""): 1,
        })

    def test_delta_treats_a_new_category_as_zero_before(self) -> None:
        delta = census_delta({("OST_Walls", L3): 5},
                             {("OST_Walls", L3): 5, ("OST_Doors", L3): 3})
        self.assertEqual(delta[("OST_Doors", L3)], 3)
        self.assertEqual(delta[("OST_Walls", L3)], 0)


if __name__ == "__main__":
    unittest.main()
