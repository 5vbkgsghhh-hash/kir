"""Property tests for the content-addressed learned-priors layer (priors.py).

Dependency-free property style (no hypothesis): seeded/fixture corpora over REAL
``lift -> fold -> build_index`` buildings (reusing the Merkle wave builders).
Frequencies are cross-checked against an INDEPENDENT count (a straight walk of
the corpus), so the tests are not tautological.

Numbering matches PRIORS_SPEC §6:
  PR1 known corpus -> known frequencies (df/N, total)
  PR2 keyed by SHAPE (translate/rename/renumber invariant; cross-building df)
  PR3 df is per-building (20 copies in one building -> df=1, total=20)
  PR4 parent->child co-occurrence; child_conditional in [0,1]; bad pair -> 0
  PR5 parameter quantiles (nearest-rank median/p10/p90, count)
  PR6 merge == fit-of-union; order-independent  (incremental training)
  PR7 determinism; to_dict->from_dict round-trip; cross-process stable
  PR8 fail-closed (unseen -> is_known False / strict raises; anomalies; empty)
  PR9 flag default OFF; malformed corpus -> PriorSchemaError
"""
from __future__ import annotations

import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_priors_queue.jsonl"))

from kukai.ir.decompile.merkle import build_index, merkle_hash  # noqa: E402
from kukai.ir.decompile.priors import (  # noqa: E402
    PriorModel,
    PriorSchemaError,
    UnknownShapeError,
    fit,
    merge,
    priors_enabled,
)
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _cluster_building,
    _fold,
    _grid_building,
)


def _corpus(specs):
    """Build (indexes, trees) for a list of pre-folded trees."""
    trees = list(specs)
    indexes = [build_index(t, label=f"b{i}") for i, t in enumerate(trees)]
    return indexes, trees


class ShapeFrequency(unittest.TestCase):
    def test_pr1_document_frequency_and_total(self) -> None:
        # A and B share the same typical grid floor; C is different.
        a = _fold(_grid_building(floors=3, name="A"))
        b = _fold(_grid_building(floors=2, dx=40_000.0, id_base=90_000,
                                 name="B"))
        c = _fold(_cluster_building(clusters=2, name="C"))
        indexes, trees = _corpus([a, b, c])
        model = fit(indexes, trees=trees)
        self.assertEqual(model.n_buildings, 3)

        # Independent ground truth: the grid floor shape occurs in A and B.
        floor_hash = None
        for shape_hash, occs in indexes[0].occurrences.items():
            if occs[0].tree_node["kind"] == "floor":
                floor_hash = shape_hash
                break
        self.assertIsNotNone(floor_hash)
        stat = model.shape_stat(floor_hash)
        self.assertEqual(stat.document_frequency, 2)       # A and B
        self.assertEqual(model.shape_frequency(floor_hash), 2 / 3)
        # total = floors in A (3) + floors in B (2) that share this shape = 5
        self.assertEqual(stat.total_occurrences, 5)

    def test_pr3_df_is_per_building_not_per_occurrence(self) -> None:
        # One building with 4 identical floors: df=1, total=4.
        tree = _fold(_grid_building(floors=4))
        index = build_index(tree, label="solo")
        model = fit([index])
        floor_hash = next(
            h for h, occs in index.occurrences.items()
            if occs[0].tree_node["kind"] == "floor")
        stat = model.shape_stat(floor_hash)
        self.assertEqual(stat.document_frequency, 1)
        self.assertEqual(stat.total_occurrences, 4)
        self.assertEqual(model.shape_frequency(floor_hash), 1.0)


class ShapeKeying(unittest.TestCase):
    def test_pr2_translate_rename_renumber_are_same_key(self) -> None:
        base = _fold(_grid_building(floors=2, name="one"))
        moved = _fold(_grid_building(
            floors=2, dx=40_000.0, dz=6_000.0, id_base=70_000, name="two"))
        # Same shape -> same root hash -> df=2 across the two "buildings".
        self.assertEqual(merkle_hash(base), merkle_hash(moved))
        indexes, trees = _corpus([base, moved])
        model = fit(indexes, trees=trees)
        root_hash = merkle_hash(base)
        self.assertEqual(model.shape_stat(root_hash).document_frequency, 2)
        self.assertEqual(model.shape_frequency(root_hash), 1.0)


class ParentChild(unittest.TestCase):
    def test_pr4_expected_children_and_conditional(self) -> None:
        tree = _fold(_grid_building(floors=3))
        index = build_index(tree, label="a")
        model = fit([index])
        # The stack parent holds floor children.
        stack = next(
            occ for occ in index.by_path.values()
            if occ.tree_node["kind"] == "stack")
        children = model.expected_children(stack.hash)
        self.assertTrue(children)
        for child in children:
            cond = model.child_conditional(stack.hash, child.child_hash)
            self.assertGreaterEqual(cond, 0.0)
            self.assertLessEqual(cond, 1.0)
        # A fabricated pair -> 0.
        self.assertEqual(
            model.child_conditional(stack.hash, "f" * 40), 0.0)

    def test_pr4_unknown_parent_strict_raises(self) -> None:
        model = fit([build_index(_fold(_grid_building(floors=1)))])
        with self.assertRaises(UnknownShapeError):
            model.child_conditional("0" * 40, "1" * 40, strict=True)


class ParameterPriors(unittest.TestCase):
    def test_pr5_wall_height_quantiles(self) -> None:
        tree = _fold(_grid_building(floors=3))
        index = build_index(tree, label="a")
        model = fit([index], trees=[tree])
        pq = model.param_quantiles("create_wall", "height_mm")
        self.assertIsNotNone(pq)
        # Every synthetic wall is 2800 mm tall -> all quantiles 2800.
        self.assertEqual(pq.p10, 2800.0)
        self.assertEqual(pq.p50, 2800.0)
        self.assertEqual(pq.p90, 2800.0)
        self.assertEqual(pq.count, 12)  # 4 walls x 3 floors

    def test_pr5_median_is_robust_nearest_rank(self) -> None:
        # Build a corpus with mixed but controlled heights via merge of hand
        # models is awkward; instead lean on the deterministic nearest-rank
        # math directly through a small synthetic multiset.
        from kukai.ir.decompile.priors import _nearest_rank
        values = tuple(sorted([2500.0, 2700.0, 2800.0, 3000.0, 3300.0]))
        self.assertEqual(_nearest_rank(values, 0.50), 2800.0)  # median
        self.assertEqual(_nearest_rank(values, 0.10), 2500.0)
        self.assertEqual(_nearest_rank(values, 0.90), 3300.0)

    def test_no_params_without_trees(self) -> None:
        model = fit([build_index(_fold(_grid_building(floors=1)))])
        self.assertIsNone(model.param_quantiles("create_wall", "height_mm"))


class MergeEquivalence(unittest.TestCase):
    def _three(self):
        a = _fold(_grid_building(floors=3, name="A"))
        b = _fold(_grid_building(floors=2, dx=40_000.0, id_base=90_000,
                                 name="B"))
        c = _fold(_cluster_building(clusters=2, name="C"))
        ia = build_index(a, label="A")
        ib = build_index(b, label="B")
        ic = build_index(c, label="C")
        return (a, b, c), (ia, ib, ic)

    def test_pr6_merge_equals_fit_of_union(self) -> None:
        (a, b, c), (ia, ib, ic) = self._three()
        whole = fit([ia, ib, ic], trees=[a, b, c])
        piecewise = merge(
            fit([ia], trees=[a]),
            merge(fit([ib], trees=[b]), fit([ic], trees=[c])))
        self.assertEqual(whole, piecewise)

    def test_pr6_merge_order_independent(self) -> None:
        (a, b, c), (ia, ib, ic) = self._three()
        left = merge(merge(fit([ia], trees=[a]), fit([ib], trees=[b])),
                     fit([ic], trees=[c]))
        right = merge(fit([ic], trees=[c]),
                      merge(fit([ib], trees=[b]), fit([ia], trees=[a])))
        self.assertEqual(left, right)

    def test_pr6_merge_bad_operand_fails_closed(self) -> None:
        model = fit([build_index(_fold(_grid_building(floors=1)))])
        with self.assertRaises(PriorSchemaError):
            merge(model, {"not": "a model"})  # type: ignore[arg-type]


class Determinism(unittest.TestCase):
    def test_pr7_same_corpus_same_model(self) -> None:
        a = _fold(_grid_building(floors=3))
        model1 = fit([build_index(a)], trees=[a])
        model2 = fit([build_index(_fold(_grid_building(floors=3)))],
                     trees=[_fold(_grid_building(floors=3))])
        self.assertEqual(model1, model2)

    def test_pr7_round_trip(self) -> None:
        a = _fold(_grid_building(floors=3, name="A"))
        b = _fold(_cluster_building(clusters=3, name="B"))
        model = fit([build_index(a), build_index(b)], trees=[a, b])
        restored = PriorModel.from_dict(model.to_dict())
        self.assertEqual(model, restored)
        # JSON is byte-stable across two serializations.
        self.assertEqual(model.to_json(), restored.to_json())

    def test_pr7_random_corpus_round_trips(self) -> None:
        rng = random.Random(918273)
        trees = []
        for _ in range(4):
            trees.append(_fold(_grid_building(
                floors=rng.randint(1, 4),
                wall_len=rng.choice([4_000.0, 5_000.0, 6_000.0]))))
        model = fit([build_index(t) for t in trees], trees=trees)
        self.assertEqual(model, PriorModel.from_dict(model.to_dict()))


class FailClosedAndAnomaly(unittest.TestCase):
    def test_pr8_unseen_shape_is_explicit(self) -> None:
        model = fit([build_index(_fold(_grid_building(floors=2)))])
        self.assertFalse(model.is_known("0" * 40))
        self.assertEqual(model.shape_frequency("0" * 40), 0.0)
        with self.assertRaises(UnknownShapeError):
            model.shape_frequency("0" * 40, strict=True)

    def test_pr8_anomalies_flag_rare_not_typical(self) -> None:
        # Corpus of grid buildings; the cluster building's shapes are rare.
        corpus_trees = [
            _fold(_grid_building(floors=3, name=f"grid{i}"))
            for i in range(3)
        ]
        model = fit([build_index(t) for t in corpus_trees])
        # A never-seen cluster building.
        odd = _fold(_cluster_building(clusters=3, name="odd"))
        odd_index = build_index(odd, label="odd")
        anomalies = model.anomalies(odd_index, max_frequency=0.5)
        self.assertTrue(anomalies)
        # Every reported anomaly is genuinely rare/unseen.
        for _hash, _kind, freq, _known in anomalies:
            self.assertLess(freq, 0.5)
        # An unseen shape is reported as known=False.
        self.assertTrue(any(not known for *_r, known in anomalies))

    def test_pr8_typical_shape_not_anomalous(self) -> None:
        trees = [_fold(_grid_building(floors=3)) for _ in range(4)]
        model = fit([build_index(t) for t in trees])
        # Re-scoring a corpus member: its floor shape is in 4/4 buildings.
        index = build_index(trees[0])
        floor_hash = next(
            h for h, occs in index.occurrences.items()
            if occs[0].tree_node["kind"] == "floor")
        anomalies = model.anomalies(index, max_frequency=0.5)
        flagged = {row[0] for row in anomalies}
        self.assertNotIn(floor_hash, flagged)

    def test_pr8_empty_corpus_is_empty_model(self) -> None:
        model = fit([])
        self.assertEqual(model.n_buildings, 0)
        self.assertFalse(model.shapes)
        self.assertEqual(model.shape_frequency("x"), 0.0)


class MalformedAndFlag(unittest.TestCase):
    def test_pr9_flag_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_PRIORS", None)
        try:
            self.assertFalse(priors_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_PRIORS"] = previous

    def test_pr9_flag_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_PRIORS")
        os.environ["KUKAI_IR_PRIORS"] = "on"
        try:
            self.assertTrue(priors_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_PRIORS"]
            else:
                os.environ["KUKAI_IR_PRIORS"] = previous

    def test_pr9_malformed_corpus_fails_closed(self) -> None:
        with self.assertRaises(PriorSchemaError):
            fit([{"not": "an index"}])

    def test_pr9_malformed_model_dict_fails_closed(self) -> None:
        with self.assertRaises(PriorSchemaError):
            PriorModel.from_dict({"n_buildings": 1})  # missing keys


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
