"""What the priors layer is worth ON THE REAL CORPUS, pinned by number.

`test_priors.py` proves the layer is internally consistent on seeded fixtures
(PR1-PR9).  Every assertion here is about the STORED corpus instead, because
the layer's founding claim is a claim about buildings, not about arithmetic:

    "the same shape in two different buildings is one prior key: the model
     learns across buildings for free"

Measured 2026-08-11 over `backend/backend/data/decompile` -- 52 stored
`tree.json`, one run per `doc_name` (the latest), merkle indexes from
`build_index`, model assembled by the layer's own `fit` + `merge`:

* 10 `doc_name` values, 45 448 distinct shapes, 132 649 parent->child edges.
* Document frequency: 36 242 shapes in 1 building, 9 189 in 2, 17 in 3, none
  in 4 or more.  So 9 206 of 45 448 (20.26%) look shared.
* TWO of those 10 names are the SAME building saved twice --
  `13A-RD-AR-K2_v33` / `13A-RD-AR-K2_v33_kuklev.d.s`, and
  `SKLNK_...` / `копияSKLNK_...`.  The canon already named this effect for
  `journal` ("a save-as SPLITS the history into two logs"); here it runs the
  other way and INFLATES the corpus.  Those two pairs share 8 779 and 399
  shapes -- 9 178 of the 9 206.
* Collapsed onto the 8 genuinely different buildings: **45 shapes of 45 448 =
  0.099%** appear in more than one.  The founding claim overstates the corpus
  by a factor of about 200, and `df / n_buildings` is 1/8 for 99.9% of shapes.

The layer is not broken by that -- its arithmetic is exactly right.  What is
wrong is the SENTENCE, and a sentence that outlives its refutation is how a
shelved module gets wired on a promise the data does not carry.
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault(
    "KIR_REJECTIONS_PATH",
    os.path.join(tempfile.gettempdir(), "kir_priors_reality_queue.jsonl"))

from kukai.ir.decompile.merkle import build_index  # noqa: E402
from kukai.ir.decompile.priors import (  # noqa: E402
    PriorSchemaError,
    fit,
)
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _cluster_building,
    _fold,
    _grid_building,
)


def _index(building, label):
    return build_index(_fold(building), label=label)


class AnomalyThresholdCanFireTests(unittest.TestCase):
    """REFUTING.  The default rarity threshold cannot fire on our corpus.

    `anomalies(max_frequency=0.1)` keeps a shape when `df / N < 0.1`.  The
    smallest non-zero frequency a corpus of N buildings can express is exactly
    `1 / N`, so at N = 10 the strictest observable rarity -- a shape present in
    ONE building of ten -- scores 0.1000 and is NOT kept.  Measured on the
    stored corpus: 36 242 shapes of 45 448 (79.7%) sit at df = 1 and every one
    of them is excluded, while the only rows that can survive are shapes the
    corpus never contained.  That is a different question (unseen), and
    answering it under the name `anomalies` is a check signing an axis it did
    not read.

    The cure is the one this codebase already uses for an unsatisfiable
    bound: refuse with the number, never return a degenerate answer that reads
    like a measurement.
    """

    def test_a_threshold_no_shape_can_satisfy_is_refused_not_answered(
            self) -> None:
        corpus = [
            _index(_grid_building(floors=3, name="a"), "a"),
            _index(_cluster_building(clusters=4, name="b"), "b"),
        ]
        model = fit(corpus)
        self.assertEqual(model.n_buildings, 2)

        # 1/2 = 0.5 is the smallest frequency this corpus can express, so a
        # threshold at or below it can only ever select unseen shapes.
        with self.assertRaises(PriorSchemaError) as caught:
            model.anomalies(corpus[0], max_frequency=0.5)
        self.assertIn("0.5", str(caught.exception))

    def test_the_default_threshold_is_refused_on_a_small_corpus(self) -> None:
        corpus = [
            _index(_grid_building(floors=3, name="a"), "a"),
            _index(_cluster_building(clusters=4, name="b"), "b"),
        ]
        model = fit(corpus)
        with self.assertRaises(PriorSchemaError):
            model.anomalies(corpus[0])

    def test_an_empty_corpus_cannot_be_asked_for_rarity(self) -> None:
        model = fit([])
        self.assertEqual(model.n_buildings, 0)
        with self.assertRaises(PriorSchemaError):
            model.anomalies(
                _index(_grid_building(floors=2, name="a"), "a"),
                max_frequency=0.5)

    def test_a_satisfiable_threshold_still_answers_exactly_as_before(
            self) -> None:
        # PR8's own corpus: N = 3, threshold 0.5 > 1/3, so nothing changes for
        # the queries the layer was already able to answer.
        corpus_trees = [
            _fold(_grid_building(floors=3, name=f"grid{i}")) for i in range(3)
        ]
        model = fit([build_index(t) for t in corpus_trees])
        odd = build_index(
            _fold(_cluster_building(clusters=3, name="odd")), label="odd")
        rows = model.anomalies(odd, max_frequency=0.5)
        self.assertTrue(rows)
        for _hash, _kind, frequency, _known in rows:
            self.assertLess(frequency, 0.5)
        self.assertTrue(any(not known for *_rest, known in rows))


class OneBuildingCountedTwiceTests(unittest.TestCase):
    """A PIN on a limit that CANNOT be guarded away -- and the guard I nearly
    wrote is the reason this class exists.

    The obvious fix for the save-as inflation is to refuse a corpus holding
    the same building twice.  It is wrong, and the code says so: merkle is
    rename-invariant BY DESIGN, so two buildings that differ only in name
    carry the SAME root hash (verified below).  A duplicate-root guard would
    therefore refuse a legitimate corpus of two shape-identical buildings --
    exactly the case the invariance exists to serve -- and it would still miss
    the real save-as pair, whose revisions differ and whose root hashes do
    not match.

    So the inflation stays a NAMED LIMIT, like the journal key that is a file
    name: nothing in a `MerkleIndex` says which document it came from, and
    `fit` cannot learn it.  Measured cost of the limit: 9 178 of the corpus's
    9 206 apparently-shared shapes.
    """

    def test_rename_invariance_makes_a_duplicate_guard_impossible(
            self) -> None:
        first = _index(_grid_building(floors=3, name="grid0"), "a")
        second = _index(_grid_building(floors=3, name="grid1"), "b")
        # Same shape, different name -> ONE hash.  A guard keyed on this would
        # refuse two honest buildings.
        self.assertEqual(first.root_hash, second.root_hash)

        model = fit([first, second])
        self.assertEqual(model.n_buildings, 2)
        for stat in model.shapes.values():
            self.assertLessEqual(stat.document_frequency, 2)

    def test_df_cannot_tell_two_buildings_from_one_saved_twice(self) -> None:
        first = _index(_grid_building(floors=3, name="grid0"), "a")
        second = _index(_grid_building(floors=3, name="grid1"), "b")
        model = fit([first, second])
        root = model.shapes[first.root_hash]
        # df = 2 and frequency = 1.0 here mean "two indexes were supplied",
        # never "two buildings were built".  Nothing in the model separates
        # the two readings, and this assertion is what stops the next reader
        # from quoting 20% as cross-building learning.
        self.assertEqual(root.document_frequency, 2)
        self.assertEqual(model.shape_frequency(first.root_hash), 1.0)


class ParameterPriorsAreTheMeasuredValueTests(unittest.TestCase):
    """The one output nothing else in this tree produces.

    Measured over the 10-name corpus: `create_wall.height_mm` p10/p50/p90 =
    2250 / 3100 / 3300 over 58 172 real walls; `create_pipe.diameter_mm`
    12.7 / 25.4 / 101.6 over 15 351; `create_level.elev_mm` 5000 / 63 300 /
    147 280 over 442.  Those are OBSERVED distributions, and the defect class
    this codebase names as its worst is a bound authored by reasoning instead
    (`create_door.sill_mm min_val=0` against 140 negative sills in one real
    building).  Deleting this layer deletes the only producer of them.

    `create_duct.diameter_mm` is the counter-example, pinned as such: 908
    values, p10 = p50 = p90 = 101.600.  A duct type's Shape decides whether a
    diameter applies at all, so a single-valued "prior" there carries no
    information and must never be quoted as one.
    """

    def test_quantiles_are_nearest_rank_and_never_interpolated(self) -> None:
        from kukai.ir.decompile.priors import _nearest_rank

        values = (1.0, 2.0, 3.0, 4.0)
        for pct in (0.10, 0.50, 0.90):
            self.assertIn(_nearest_rank(values, pct), values)

    def test_an_unsampled_pair_is_none_never_a_fabricated_number(self) -> None:
        model = fit([_index(_grid_building(floors=3, name="a"), "a")])
        self.assertIsNone(model.param_quantiles("create_door", "sill_mm"))


if __name__ == "__main__":
    unittest.main()
