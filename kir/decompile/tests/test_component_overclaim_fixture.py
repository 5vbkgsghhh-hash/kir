"""Excess claim of the component layer — a guard pulled OUT OF A REAL CASE.

WHY A SEPARATE FILE, not a line in `test_component.py`. The division of labor
between two instruments is named, because otherwise one substitutes for the
other:

    THE CORPUS OPENS      `test_component_corpus_reality.py` walks the runs
                       sitting on disk and finds what nobody planted; it is
                       also the only one that sees the scale.
    THE FIXTURE GUARDS    this file holds ONE pulled case of 34 sheets: it
                       lives in the tree, needs no corpus, and turns red in
                       seconds.

The property C-RT (library unfolding = multiset of source leaves) was
checked in `test_component.py` since 2026-08-09 and held — on seeded grids
of 1–4 floors. It turned false on a tower: 99 keys were claimed twice at a
source multiplicity of 1. This is form 10 of the canon verbatim — the cost
(here: the probability of two occurrences intersecting) grows with n, and an
instrument at n=3 doesn't see it. So the fixture is pulled from a real
defect, not invented.

ORIGIN, NAMED. Four subtrees are copied verbatim from tower
`13A-RD-AR-K2_v33`; the nodes are present in TWO runs, `k2_ar_rd_v7` and
`k2_ar_rd_v8` (`grep` over `tree.json`, 2026-08-13):

    cffd24b849…  room          «Жилая комната 4»       12 leaves
    285cc1ba9b…  room          «Жилая комната 4»
    ac915268fd…  atom_cluster  5 × OST_RoomSeparationLines
    710caf800b…  atom_cluster  5 × OST_RoomSeparationLines

A pair of rooms gives one repeat, a pair of clusters gives the second; the
disputed leaves are room-separation lines, exactly the category that
accounted for 100% of the tower's excess. The root carries the `facts` of
the source tree unedited.

THE CAPACITY AT WHICH THE CONTROL IS ABLE TO FAIL — stated as a number,
because a control on a degenerate input is green by construction:

    repeats in the fixture                     2   (needs >= 2: with one
                                                 component there is nothing
                                                 to divide with)
    occurrence counts they have             4 and 2  (needs >= 2 each,
                                                 otherwise `min_occurrences`
                                                 would reject them before
                                                 any claim)
    keys divided by two instances              12   (needs >= 1, otherwise
                                                 there is no dispute)
    of them OVER the source                    10   (+1 each = excess 10)
    source multiplicities of the exceeded   1 and 2  (needs at least 1: where
                                                 the source carries the same
                                                 amount, the claim is LEGAL
                                                 and the rule correctly stays
                                                 silent)
    divided WITHOUT exceeding                   2   (needs >= 1, otherwise
                                                 the fixture cannot tell
                                                 "don't exceed" from
                                                 "don't divide")

Below, these four numbers are checked executably: if the fixture degenerates
— from a canon edit, from a hash change, from anything — `TheFixtureIsSharpEnough`
will fail, rather than "C-RT holds" in a vacuum.
"""
from __future__ import annotations

import json
import pathlib
import unittest
from collections import Counter
from unittest import mock

from kir.decompile import component
from kir.decompile.component import (
    _abs_multiset, build_library, expand_library, instantiate)
from kir.decompile.fold import iter_l1_leaves
from kir.decompile.merkle import build_index, dedup_report

FIXTURE = (pathlib.Path(__file__).parent / "fixtures"
           / "component_overclaim_tower.json")

#: Excess of the unfixed code on THIS fixture, measured by the 2026-08-13 run
#: of `build_library` in the tree `/home/claude/kir-merge` (machine-local,
#: without the fix): 2 components, 6 instances, excess 10, deficit 0.
#: The number anchors BOTH ends: the FAIL control must reproduce exactly it,
#: otherwise the stub removed something other than what the absence of the fix removes.
UNFIXED_EXCESS = 10


def _tree():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _claimed_multiset(lib):
    """How many times each absolute op is claimed by PLACEMENTS (singles excluded)."""
    counts: Counter[str] = Counter()
    for op in lib.place_ops:
        for inst in op.instances:
            for leaf in instantiate(
                    op.definition, inst.offset_mm,
                    instance_index=inst.instance_index, regenerate_ids=False):
                key, = _abs_multiset([leaf])
                counts[key] += 1
    return counts


def _holders(lib):
    """{absolute op: {(component, instance number), …}} — WHO claimed it."""
    out: dict[str, set] = {}
    for op in lib.place_ops:
        for inst in op.instances:
            for leaf in instantiate(
                    op.definition, inst.offset_mm,
                    instance_index=inst.instance_index, regenerate_ids=False):
                key, = _abs_multiset([leaf])
                out.setdefault(key, set()).add(
                    (op.def_hash, inst.instance_index))
    return out


def _overflow(lib, source_abs):
    """(excess, deficit) of the unfolding against the source multiset."""
    back = _abs_multiset(expand_library(lib))
    over = sum(back[k] - source_abs.get(k, 0)
               for k in back if back[k] > source_abs.get(k, 0))
    under = sum(source_abs[k] - back.get(k, 0)
                for k in source_abs if source_abs[k] > back.get(k, 0))
    return over, under


class TheLibraryPartitionsTheSource(unittest.TestCase):

    def test_expansion_is_a_partition_not_a_cover(self):
        """C-RT on the real case: neither excess nor deficit.

        THE ZERO HERE IS TWO-SIDED, and the second half matters as much as
        the first. Excess 0 says "we did not claim anything extra"; deficit 0
        says "in fixing the excess, we did not throw out the legitimate."
        The rule forbids not the DIVISION of a key between instances, but
        EXCEEDING the source multiplicity: on the corpus, 322 legitimate
        divisions were measured, up to multiplicities of 438 and 1507, and
        all of them must survive.
        """
        tree = _tree()
        index = build_index(tree, label="overclaim")
        lib = build_library(index)
        source_abs = _abs_multiset(iter_l1_leaves(index.root.tree_node))
        over, under = _overflow(lib, source_abs)
        self.assertEqual(
            (over, under), (0, 0),
            f"развёртка не есть разбиение источника: избыток {over}, "
            f"недостача {under}")


class TheFixtureIsSharpEnough(unittest.TestCase):
    """PASS control: the input has something to fail on.

    Not "the fixture is correct," but "the fixture is NOT DEGENERATE." Green
    above and green on a tree with not a single repeat print the same, and
    only this class tells them apart.
    """

    def test_the_fixture_carries_two_repeats_of_power_two_and_four(self):
        tree = _tree()
        index = build_index(tree, label="overclaim")
        reps = dedup_report([index], min_occurrences=2, min_leaves=2)
        powers = sorted(len(index.occurrences_of(e.hash)) for e in reps)
        self.assertEqual(
            powers, [2, 4],
            f"мощности повторов {powers}: нужны ДВА повтора со вхождениями "
            f">= 2 каждый — иначе делить нечего и C-RT зелен по построению")

    def test_the_fixture_carries_both_classes_not_only_the_easy_one(self):
        """There is a dispute, and next to it there is a LEGAL division —
        both must be present.

        THE FIRST EDITION OF THIS CLASS CLAIMED "5 disputed keys, source
        multiplicity 1 for all," and was wrong twice. The five were measured
        on the FIXED library, where the dispute was already resolved — i.e.
        the number described the disease using the state AFTER treatment;
        and "multiplicity is always 1" turned out to be my simplification:
        among the exceeded keys there is also a multiplicity of 2, claimed
        three times. This very PASS control caught it on the first run, and
        that is exactly what it was written for.

        Measured on the 2026-08-13 fixture, with the predicate stubbed out:

            divided by two or more instances      12
            of them OVER the source                10   (+1 each = excess 10)
            source multiplicities of the exceeded  1 and 2
            divided WITHOUT exceeding                2   (multiplicity 2, claimed 2)

        The last line is precisely the other side: the rule forbids not
        division, but exceeding, and the fixture IS ABLE to catch a rule
        that would forbid too much.
        """
        tree = _tree()
        index = build_index(tree, label="overclaim")
        source_abs = _abs_multiset(iter_l1_leaves(index.root.tree_node))
        with mock.patch.object(component, "_multiset_fits",
                               lambda *_a, **_k: True):
            unguarded = build_library(index)
        claimed = _claimed_multiset(unguarded)
        holders = _holders(unguarded)
        shared = {k for k, v in holders.items() if len(v) > 1}
        exceeding = {k for k in claimed if claimed[k] > source_abs.get(k, 0)}
        self.assertEqual(
            (len(shared), len(exceeding)), (12, 10),
            f"делимых {len(shared)}, превышающих {len(exceeding)} — фикстура "
            f"изменилась, пересними и объясни")
        self.assertEqual(
            sorted({source_abs.get(k, 0) for k in exceeding}), [1, 2],
            "превышение осталось только на кратности 1 — фикстура упростилась "
            "до самого лёгкого случая")
        self.assertTrue(
            shared - exceeding,
            "в фикстуре не осталось ЗАКОННОГО деления: она перестала различать "
            "правило «не превышай» от правила «не дели», а это разные правила")

    def test_the_legitimate_split_survives_the_guard(self):
        """The other side of the zero: the rule did not throw out the
        legitimate along with the excess.

        After the fix, division between instances CONTINUES — 5 keys, and
        for each of them the claim does not exceed the source multiplicity.
        Without this assertion, "excess 0" would be indistinguishable from a
        rule that forbade dividing altogether, and on the corpus there are
        322 such legitimate divisions, up to multiplicities of 438 and 1507.
        """
        tree = _tree()
        index = build_index(tree, label="overclaim")
        source_abs = _abs_multiset(iter_l1_leaves(index.root.tree_node))
        lib = build_library(index)
        holders = _holders(lib)
        claimed = _claimed_multiset(lib)
        shared = {k for k, v in holders.items() if len(v) > 1}
        self.assertEqual(
            len(shared), 5,
            f"делимых ключей после правки {len(shared)}, было 5")
        self.assertTrue(
            all(claimed[k] <= source_abs.get(k, 0) for k in shared),
            "деление после правки превышает источник — правило не сработало")

    def test_the_fixture_is_small_enough_to_read(self):
        """34 sheets: the guard must be readable by eye, otherwise it does not get fixed."""
        tree = _tree()
        index = build_index(tree, label="overclaim")
        leaves = list(iter_l1_leaves(index.root.tree_node))
        self.assertEqual(len(leaves), 34)
        self.assertEqual(len(tree["children"]), 4)


class TheGuardCanBeDisabled(unittest.TestCase):
    """FAIL control: the experiment COULD have ended differently, and this
    is shown on this input.

    The REAL predicate in the real `build_library` is stubbed out, not a
    loop rewritten in the test: "the instrument lies to its own author" is
    only caught when the control walks the same path as what is being checked.
    """

    def test_without_the_predicate_the_defect_returns_at_its_measured_size(self):
        tree = _tree()
        index = build_index(tree, label="overclaim")
        source_abs = _abs_multiset(iter_l1_leaves(index.root.tree_node))
        with mock.patch.object(component, "_multiset_fits",
                               lambda *_a, **_k: True):
            lib = build_library(index)
        over, under = _overflow(lib, source_abs)
        self.assertEqual(
            (over, under), (UNFIXED_EXCESS, 0),
            f"с заглушённым правилом избыток {over} (недостача {under}), а "
            f"неправленый код даёт {UNFIXED_EXCESS}: заглушка сняла не то, что "
            f"снимает отсутствие правки — контроль ничего не доказывает")

    def test_the_price_of_the_guard_is_stated(self):
        """The price is stated as a number: the rule costs a component and
        two placements.

        The INSTANCE is rejected, but if fewer than `min_occurrences` remain
        after the rejection, the whole component goes away — here that is
        exactly what happens. This is not a defect of the rule, but its
        price, and it must stand in the test: a component silently
        disappearing would read as "there was no repeat."
        """
        tree = _tree()
        index = build_index(tree, label="overclaim")
        guarded = build_library(index)
        with mock.patch.object(component, "_multiset_fits",
                               lambda *_a, **_k: True):
            unguarded = build_library(index)
        self.assertEqual(
            (len(unguarded.definitions),
             sum(len(o.instances) for o in unguarded.place_ops)),
            (2, 6))
        self.assertEqual(
            (len(guarded.definitions),
             sum(len(o.instances) for o in guarded.place_ops)),
            (1, 4),
            "цена правила изменилась: пересними число и объясни, почему")
        self.assertEqual(len(guarded.singletons_leaves), 14)


if __name__ == "__main__":
    unittest.main()
