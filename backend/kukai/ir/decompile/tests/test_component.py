"""Property tests for the component-library / instancing layer (component.py).

Dependency-free property style over REAL ``lift -> fold -> build_index``
buildings (reusing the Merkle wave builders).  The round-trip (C-RT) and
partition (C7) are the heart: a component library must lose nothing.

Numbering matches COMPONENT_LIBRARY_SPEC §6:
  C1 single-instance round-trip (instance at occurrence offset == its leaves)
  C2 C-RT: expand_library == original leaf multiset (nothing lost/invented)
  C3 real dedup saving (typical floor -> one component, N instances)
  C4 universality (translate/rename/renumber -> same library)
  C5 instance id discipline (pairwise-distinct, deterministic, collision-closed)
  C6 determinism (dataclass equality; stable order; cross-process)
  C7 partition (instanced + singletons == all leaves, no overlap)
  C8 no repeats -> empty place_ops, all singletons, expand == original
  C9 flag default OFF; malformed input -> ComponentSchemaError
"""
from __future__ import annotations

import os
import random
import tempfile
import unittest
from collections import Counter

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_comp_queue.jsonl"))

from kukai.ir.decompile.fold import (  # noqa: E402
    FidelityCanon,
    canon_op,
    iter_l1_leaves,
)
from kukai.ir.decompile.merkle import build_index  # noqa: E402
from kukai.ir.decompile.component import (  # noqa: E402
    ComponentLibrary,
    ComponentFidelityProof,
    ComponentRoundTripError,
    ComponentSchemaError,
    PlaceGroupOp,
    _place_op_reconstructs,
    assert_round_trip,
    assert_unique_instance_ids,
    build_library,
    component_enabled,
    expand_library,
    extract_component,
    instantiate,
    prove_execution_fidelity,
)
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _cluster_building,
    _fold,
    _grid_building,
)

_ZERO = (0.0, 0.0, 0.0)


def _abs_multiset(leaves):
    return Counter(canon_op(leaf, _ZERO) for leaf in leaves)


class SingleInstanceRoundTrip(unittest.TestCase):
    def test_c1_instance_at_occurrence_offset_matches_leaves(self) -> None:
        tree = _fold(_cluster_building(clusters=3))
        index = build_index(tree, label="a")
        # Pick a repeated zone shape and one of its occurrences.
        repeated = [
            (h, occs) for h, occs in index.occurrences.items()
            if len(occs) >= 2 and occs[0].tree_node["kind"] == "zone"]
        self.assertTrue(repeated)
        _hash, occs = repeated[0]
        defn = extract_component(occs[0])
        for occ in occs:
            # The reconstruction offset is the occurrence's ABSOLUTE origin, not
            # occ_origin - def_origin (the LOT31 bug; see ComponentInstance doc).
            placed = instantiate(
                defn, occ.origin_mm, instance_index=0, regenerate_ids=False)
            self.assertEqual(
                _abs_multiset(placed),
                _abs_multiset(iter_l1_leaves(occ.tree_node)),
                "instance must reproduce the occurrence's leaves")


class LibraryRoundTrip(unittest.TestCase):
    def _cases(self):
        return {
            "grid1": _fold(_grid_building(floors=1)),
            "grid3": _fold(_grid_building(floors=3)),
            "grid4": _fold(_grid_building(floors=4)),
            "cluster3": _fold(_cluster_building(clusters=3)),
            # REGRESSION (LOT31 C-RT bug): buildings whose repeated components
            # sit at a NONZERO origin.  Every earlier synthetic case had
            # def_origin == (0,0,0), which accidentally masked a wrong
            # reconstruction offset.  These translate the whole building so the
            # component's def_origin is far from zero, exercising the macro
            # (grid_array / atom_cluster / stack) members at real positions.
            "grid4-hi": _fold(_grid_building(
                floors=4, dx=30_000.0, dy=23_000.0, dz=100_000.0)),
            "cluster3-hi": _fold(_grid_building(
                floors=3, dx=-45_000.0, dy=17_000.0, dz=50_000.0)),
        }

    def test_c2_expand_equals_original(self) -> None:
        for name, tree in self._cases().items():
            with self.subTest(case=name):
                lib = build_library(build_index(tree, label="a"))
                assert_round_trip(lib, tree)  # raises on mismatch
                self.assertEqual(
                    _abs_multiset(expand_library(lib)),
                    _abs_multiset(iter_l1_leaves(tree)))

    def test_c7_partition_no_overlap_full_cover(self) -> None:
        for name, tree in self._cases().items():
            with self.subTest(case=name):
                lib = build_library(build_index(tree, label="a"))
                n_leaves = sum(1 for _ in iter_l1_leaves(tree))
                instanced = lib.total_instanced_leaves
                self.assertEqual(
                    instanced + len(lib.singletons_leaves), n_leaves)
                # Distinct component defs are counted once each.
                self.assertEqual(
                    lib.total_defined_leaves,
                    sum(d.leaf_count for d in lib.definitions.values()))

    def test_c8_unique_building_is_all_singletons(self) -> None:
        tree = _fold(_grid_building(floors=1))
        lib = build_library(build_index(tree, label="a"))
        self.assertEqual(lib.place_ops, ())
        self.assertEqual(
            len(lib.singletons_leaves),
            sum(1 for _ in iter_l1_leaves(tree)))
        assert_round_trip(lib, tree)


def _macro_leaf_count(defn) -> int:
    """Atoms in a definition are macro (grid_array / atom_cluster) members."""
    return sum(1 for leaf in defn.leaves if leaf["kind"] == "atom")


class NonZeroOriginMacroRoundTrip(unittest.TestCase):
    """REGRESSION for the LOT31 C-RT bug (43% divergence on the real model).

    The reconstruction offset must be the occurrence's ABSOLUTE origin, not
    occ_origin - def_origin.  The two coincide only when def_origin == (0,0,0),
    which every earlier synthetic case happened to produce — so a whole class
    (repeated MACRO components at a nonzero origin, exactly LOT31's furniture
    grid_arrays high up the building) went untested.  These fixtures put the
    repeated component far from the origin and assert an exact round-trip.
    """

    def _hi_building(self):
        # 4 identical floors translated up/over -> a repeated floor component
        # whose def_origin is nonzero and whose leaves include macro members.
        return _fold(_grid_building(
            floors=4, dx=30_000.0, dy=23_000.0, dz=100_000.0))

    def test_nonzero_origin_component_round_trips(self) -> None:
        tree = self._hi_building()
        lib = build_library(build_index(tree, label="a"))
        # The component really does sit at a nonzero origin AND carry macro
        # (atom) members — otherwise this test would not exercise the bug.
        self.assertTrue(lib.place_ops)
        comp = lib.place_ops[0].definition
        self.assertNotEqual(comp.origin_mm, (0.0, 0.0, 0.0))
        self.assertGreater(_macro_leaf_count(comp), 0)
        # The fix: exact round-trip on the real (translated) geometry.
        assert_round_trip(lib, tree)
        self.assertEqual(
            _abs_multiset(expand_library(lib)),
            _abs_multiset(iter_l1_leaves(tree)))

    def test_offset_is_absolute_not_relative(self) -> None:
        # Directly guard the exact bug: instancing with the RELATIVE delta
        # (rel_mm) must NOT reproduce the occurrence, while the absolute
        # offset_mm must.  This pins the regression precisely.
        tree = self._hi_building()
        lib = build_library(build_index(tree, label="a"))
        op = lib.place_ops[0]
        instance = op.instances[0]
        self.assertNotEqual(instance.offset_mm, instance.rel_mm)  # def_origin != 0
        correct = instantiate(
            op.definition, instance.offset_mm,
            instance_index=0, regenerate_ids=False)
        wrong = instantiate(
            op.definition, instance.rel_mm,
            instance_index=0, regenerate_ids=False)
        self.assertNotEqual(_abs_multiset(correct), _abs_multiset(wrong))

    def test_fail_closed_keeps_geometry_as_singletons(self) -> None:
        # Whatever build_library decides, the union of instanced + singleton
        # leaves must ALWAYS equal the building — a component it cannot
        # reconstruct is rejected (its leaves fall back to singletons), never
        # silently lost.  This holds even under the nonzero-origin fixture.
        tree = self._hi_building()
        lib = build_library(build_index(tree, label="a"))
        assert_round_trip(lib, tree)
        total = lib.total_instanced_leaves + len(lib.singletons_leaves)
        self.assertEqual(total, sum(1 for _ in iter_l1_leaves(tree)))

    def test_reconstruction_gate_rejects_a_bad_place_op(self) -> None:
        # The fail-closed gate itself: a place-op whose instance offsets are
        # wrong (here the buggy relative delta) must be rejected, so it would
        # never enter the library and corrupt geometry.
        tree = self._hi_building()
        index = build_index(tree, label="a")
        lib = build_library(index)
        good_op = lib.place_ops[0]
        occs = sorted(
            index.occurrences_of(good_op.def_hash),
            key=lambda o: (o.origin_mm, o.path))
        # A correctly-built op passes the gate.
        self.assertTrue(_place_op_reconstructs(good_op, occs))
        # An op whose offsets are the (wrong) relative delta fails the gate.
        bad_op = PlaceGroupOp(
            def_hash=good_op.def_hash,
            definition=good_op.definition,
            instances=tuple(
                type(inst)(
                    def_hash=inst.def_hash,
                    instance_index=inst.instance_index,
                    offset_mm=inst.rel_mm,        # deliberately wrong
                    origin_mm=inst.origin_mm,
                    rel_mm=inst.rel_mm,
                )
                for inst in good_op.instances),
        )
        self.assertFalse(_place_op_reconstructs(bad_op, occs))


class DedupSaving(unittest.TestCase):
    def test_c3_typical_floor_one_component_n_instances(self) -> None:
        tree = _fold(_grid_building(floors=4))
        index = build_index(tree, label="a")
        lib = prove_execution_fidelity(build_library(index), index)
        floor_ops = [op for op in lib.place_ops
                     if op.definition.kind == "floor"]
        self.assertEqual(len(floor_ops), 1)
        op = floor_ops[0]
        self.assertEqual(op.occurrence_count, 4)
        self.assertGreater(op.savings_leaves, 0)
        # defined < instanced: the win of "draw once".
        self.assertLess(lib.total_defined_leaves, lib.total_instanced_leaves)
        # TemplateCanon correctly discovers the repeated shape, but the four
        # source floors carry four concrete Level bindings.  Until an explicit
        # per-instance binding contract exists, this is analysis-only and must
        # not silently become one native Revit Group definition.
        self.assertFalse(op.fidelity_proven)
        self.assertEqual(op.fidelity_mismatch_indices, (1, 2, 3))

    def test_c3_clusters_component(self) -> None:
        tree = _fold(_cluster_building(clusters=3))
        index = build_index(tree, label="a")
        analytical = build_library(index)
        self.assertIsNone(analytical.place_ops[0].fidelity_proof)
        self.assertFalse(analytical.place_ops[0].fidelity_proven)
        lib = prove_execution_fidelity(analytical, index)
        self.assertTrue(lib.place_ops)
        self.assertEqual(lib.place_ops[0].occurrence_count, 3)
        # Same-level translated clusters preserve their concrete bindings and
        # are eligible for the native-group bridge.
        self.assertTrue(lib.place_ops[0].fidelity_proven)
        self.assertEqual(lib.place_ops[0].fidelity_mismatch_indices, ())

    def test_c3_fidelity_proof_contract_is_versioned_and_typed(self) -> None:
        with self.assertRaises(ComponentSchemaError):
            ComponentFidelityProof(
                canon_version="unknown-canon/99",
                instantiated_hashes=("0" * 40,),
                source_hashes=("0" * 40,),
            )
        with self.assertRaises(ComponentSchemaError):
            ComponentFidelityProof(
                canon_version=FidelityCanon.VERSION,
                instantiated_hashes=("not-a-hash",),
                source_hashes=("not-a-hash",),
            )
        with self.assertRaises(ComponentSchemaError):
            ComponentFidelityProof(
                canon_version=FidelityCanon.VERSION,
                instantiated_hashes=("0" * 40,),
                source_hashes=(),
            )


class Universality(unittest.TestCase):
    def test_c4_translate_rename_renumber_same_library(self) -> None:
        base = build_library(build_index(
            _fold(_grid_building(floors=3, name="one")), label="A"))
        moved = build_library(build_index(
            _fold(_grid_building(
                floors=3, dx=40_000.0, dz=6_000.0, id_base=70_000,
                name="two")), label="B"))
        # Same component shape (def_hash) survives translation/rename/renumber.
        self.assertEqual(
            sorted(base.definitions), sorted(moved.definitions))
        for def_hash, defn in base.definitions.items():
            self.assertEqual(
                defn.leaf_count, moved.definitions[def_hash].leaf_count)
            self.assertEqual(defn.kind, moved.definitions[def_hash].kind)


class InstanceIds(unittest.TestCase):
    def test_c5_instances_have_distinct_ids(self) -> None:
        tree = _fold(_grid_building(floors=4))
        lib = build_library(build_index(tree, label="a"))
        for op in lib.place_ops:
            assert_unique_instance_ids(op)   # raises on collision
            all_ids = []
            for instance in op.instances:
                for leaf in instantiate(
                        op.definition, instance.offset_mm,
                        instance_index=instance.instance_index,
                        regenerate_ids=True):
                    all_ids.append(leaf["source_element_id"])
            self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_c5_id_regeneration_is_deterministic(self) -> None:
        tree = _fold(_grid_building(floors=3))
        lib = build_library(build_index(tree, label="a"))
        op = lib.place_ops[0]
        first = [
            leaf["source_element_id"]
            for leaf in instantiate(op.definition, op.instances[0].offset_mm,
                                    instance_index=0, regenerate_ids=True)]
        second = [
            leaf["source_element_id"]
            for leaf in instantiate(op.definition, op.instances[0].offset_mm,
                                    instance_index=0, regenerate_ids=True)]
        self.assertEqual(first, second)


class Determinism(unittest.TestCase):
    def test_c6_same_building_same_library(self) -> None:
        a = build_library(build_index(_fold(_grid_building(floors=3))))
        b = build_library(build_index(_fold(_grid_building(floors=3))))
        self.assertEqual(a.place_ops, b.place_ops)
        self.assertEqual(a.singletons_leaves, b.singletons_leaves)

    def test_c6_instance_order_stable_by_origin(self) -> None:
        lib = build_library(build_index(_fold(_grid_building(floors=4))))
        op = lib.place_ops[0]
        origins = [inst.origin_mm for inst in op.instances]
        self.assertEqual(origins, sorted(origins))

    def test_c6_random_buildings_round_trip(self) -> None:
        rng = random.Random(55555)
        for _ in range(5):
            tree = _fold(_grid_building(
                floors=rng.randint(1, 4),
                wall_len=rng.choice([4_000.0, 5_000.0, 6_000.0])))
            lib = build_library(build_index(tree, label="a"))
            assert_round_trip(lib, tree)


class FailClosedAndFlag(unittest.TestCase):
    def test_c9_flag_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_COMPONENT", None)
        try:
            self.assertFalse(component_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_COMPONENT"] = previous

    def test_c9_flag_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_COMPONENT")
        os.environ["KUKAI_IR_COMPONENT"] = "1"
        try:
            self.assertTrue(component_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_COMPONENT"]
            else:
                os.environ["KUKAI_IR_COMPONENT"] = previous

    def test_c9_malformed_index_fails_closed(self) -> None:
        with self.assertRaises(ComponentSchemaError):
            build_library({"not": "an index"})

    def test_c9_malformed_occurrence_fails_closed(self) -> None:
        with self.assertRaises(ComponentSchemaError):
            extract_component({"not": "an occurrence"})  # type: ignore[arg-type]

    def test_c9_round_trip_guard_detects_corruption(self) -> None:
        # A hand-corrupted library (dropped singletons) must fail the guard.
        tree = _fold(_grid_building(floors=1))
        lib = build_library(build_index(tree, label="a"))
        broken = ComponentLibrary(
            definitions=lib.definitions,
            place_ops=lib.place_ops,
            singletons_leaves=lib.singletons_leaves[:-1],
        )
        with self.assertRaises(ComponentRoundTripError):
            assert_round_trip(broken, tree)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
