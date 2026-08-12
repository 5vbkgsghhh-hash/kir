"""What the component library is worth ON THE REAL CORPUS, pinned by number.

`test_component.py` proves the layer's properties (C1..C-RT) on seeded
fixtures.  Every assertion here is about the STORED corpus and about the two
sentences the corpus contradicts.

Measured 2026-08-11 over `backend/backend/data/decompile`, one run per
`doc_name` (10 runs, 368 313 folded leaves), indexes from `build_index`,
libraries from this layer's own `build_library` + `prove_execution_fidelity`:

* 595 components, 2 482 instances.  They cover 49 641 leaves (13.48%) and save
  35 292 (9.58%).
* **fidelity_proven: 316 of 595 = 53.11%.**  Executable saving 27 714 of
  35 292 = 78.53% of the analytical one.  The split is bimodal, not uniform:
  Snowdon Plumbing 220/221 and the facade 11/11, against the tower 32/145 and
  `демо` 22/70 -- exactly the case the module docstring predicts, where a
  visually identical floor is bound to another Level.
* **4 of the 10 runs produce ZERO components** (both SKLNK copies, Snowdon
  Electrical, Проект1).
* The fail-closed reconstruction gate has NEVER rejected anything: 0 of 460
  repeats over 7 buildings.  That is not a bug -- merkle's translation-
  invariant hash already guarantees what `_place_op_reconstructs` re-derives
  independently -- but the docstring must not sell an unexercised branch as
  the geometry-safety property.
* `dedup_report` already drops dominated repeats (`include_dominated=False` is
  its default), so `build_library`'s own `if entry.dominated` skip is
  unreachable: 0 of 460.

The layer is NOT dark code, which the shelf status hides: `materialize.py`
(live) imports `component._translate_leaf` at module scope and calls it "the
canonicalization authority" for coordinate translation.
"""
from __future__ import annotations

import dataclasses
import unittest
from unittest import mock

from kukai.ir.decompile.component import (
    ComponentSchemaError,
    build_library,
)
from kukai.ir.decompile.merkle import DedupEntry, build_index, dedup_report
from kukai.ir.decompile.tests.test_merkle import (
    _fold,
    _grid_building,
)


def _index(floors=3, name="a"):
    return build_index(_fold(_grid_building(floors=floors, name=name)),
                       label=name)


class DominatedFilterIsAContractNotADecorationTests(unittest.TestCase):
    """REFUTING.  `build_library` takes credit for a selection it never makes.

    Its docstring says it "chooses disjoint, non-dominated maximal repeats".
    It chooses disjoint -- that is the `_covered` walk.  Non-domination is done
    upstream: `dedup_report` defaults to `include_dominated=False` and filters
    those entries at the source, so every entry `build_library` sees already
    carries `dominated=False` and its own `if entry.dominated: continue` is
    unreachable.  Measured: 0 of 460 repeats over 7 real buildings, and 0
    dominated entries ever delivered.

    That inert line is the danger, not the waste.  The dependency on someone
    else's DEFAULT is nowhere stated, so flipping `include_dominated` upstream
    would silently change which repeats become components -- a value asserted
    in one module and read in another with nothing forcing them to agree.  A
    dominated entry arriving here is a broken upstream contract and must be a
    typed refusal, never a silent skip.
    """

    def test_a_dominated_entry_is_refused_not_silently_skipped(self) -> None:
        index = _index()
        real = dedup_report([index], min_occurrences=2, min_leaves=2)
        if not real:
            self.skipTest("fixture produced no repeats")
        poisoned = (dataclasses.replace(real[0], dominated=True),)
        self.assertIsInstance(poisoned[0], DedupEntry)
        with mock.patch(
            "kukai.ir.decompile.component.dedup_report",
            return_value=poisoned,
        ):
            with self.assertRaises(ComponentSchemaError) as caught:
                build_library(index)
        self.assertIn("dominated", str(caught.exception))

    def test_the_upstream_default_is_what_this_layer_relies_on(self) -> None:
        index = _index()
        entries = dedup_report([index], min_occurrences=2, min_leaves=2)
        # The whole reason the filter above can never fire.
        self.assertTrue(all(not entry.dominated for entry in entries))
        with_dominated = dedup_report(
            [index], min_occurrences=2, min_leaves=2, include_dominated=True)
        self.assertGreaterEqual(len(with_dominated), len(entries))

    def test_an_honest_corpus_still_builds_exactly_as_before(self) -> None:
        index = _index()
        library = build_library(index)
        self.assertTrue(all(
            op.definition.leaf_count >= 2 for op in library.place_ops))


class ExecutableSavingIsVisibleWithoutRecomputingItTests(unittest.TestCase):
    """REFUTING.  Nothing let a caller SEE how much of the library is
    executable.

    `build_library` returns the analytical library; `prove_execution_fidelity`
    attaches proofs one op at a time.  A caller wiring the native-group bridge
    had to walk `place_ops` itself to discover that on the real corpus
    **47% of discovered components cannot be executed** (316 proven of 595)
    and that the executable saving is 78.53% of the analytical one.  Measured
    per building the spread is 220/221 down to 32/145, so a single global
    intuition is wrong in both directions.

    This is the same law `ground.py` states for a named default: a choice the
    caller cannot see is `.FirstOrDefault()` with a better reputation.
    """

    def test_the_library_reports_its_own_proven_split(self) -> None:
        index = _index()
        analytical = build_library(index)
        summary = analytical.fidelity_summary
        self.assertEqual(summary["components"], len(analytical.place_ops))
        # No proof attached yet -> nothing may read as executable.
        self.assertEqual(summary["proven"], 0)
        self.assertEqual(summary["proven_saved_leaves"], 0)
        self.assertEqual(summary["saved_leaves"],
                         sum(op.savings_leaves for op in analytical.place_ops))

    def test_an_unproven_library_never_reads_as_executable(self) -> None:
        analytical = build_library(_index())
        for op in analytical.place_ops:
            self.assertFalse(op.fidelity_proven)
        self.assertEqual(analytical.fidelity_summary["proven"], 0)

    def test_the_proven_split_matches_a_hand_count(self) -> None:
        from kukai.ir.decompile.component import prove_execution_fidelity

        index = _index()
        proven = prove_execution_fidelity(build_library(index), index)
        summary = proven.fidelity_summary
        self.assertEqual(
            summary["proven"],
            sum(1 for op in proven.place_ops if op.fidelity_proven))
        self.assertEqual(
            summary["proven_saved_leaves"],
            sum(op.savings_leaves
                for op in proven.place_ops if op.fidelity_proven))


if __name__ == "__main__":
    unittest.main()
