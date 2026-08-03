"""Property tests for incremental delta-rebuild as an operation (rebuild.py).

Dependency-free property style over REAL ``lift -> fold`` A->B pairs with
controlled edits (reusing the Merkle diff-test builders).  T-APPLY (the state
transition) is the heart: applying the delta to A's state must yield B's state.

Numbering matches INCREMENTAL_REBUILD_SPEC §7:
  R1 T-APPLY: apply(state(A), delta(A,B)) == state(B)
  R2 A->A -> empty delta, apply == identity
  R3 delta size << full rebuild on a local edit; reused_count > 0
  R4 consistency with wave-1 plan (emitted+relocated == P7 emit+relocate)
  R5 order retire -> relocate -> emit
  R6 fail-closed (wrong base state -> DeltaApplyError; malformed -> schema err)
  R7 determinism (dataclass equality; cross-process)
  R8 moved -> relocate op with correct behaviour
  R9 flag default OFF; seeded random pairs always T-APPLY
"""
from __future__ import annotations

import os
import random
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_rebuild_queue.jsonl"))

from kukai.ir.decompile.fold import iter_l1_leaves  # noqa: E402
from kukai.ir.decompile.merkle import (  # noqa: E402
    build_index,
    diff_trees,
    incremental_plan,
)
from kukai.ir.decompile.rebuild import (  # noqa: E402
    BuildingState,
    DeltaApplyError,
    DeltaProgram,
    RebuildError,
    RebuildSchemaError,
    apply_delta,
    assert_transition,
    build_delta,
    delta_between,
    rebuild_enabled,
)
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _cluster_building,
    _fold,
    _grid_building,
    _single_edit_scenarios,
)


class Transition(unittest.TestCase):
    def test_r1_single_edits_transition_correctly(self) -> None:
        for name, a, b, _ta, _tb in _single_edit_scenarios():
            with self.subTest(scenario=name):
                program = delta_between(a, b)
                assert_transition(program, a, b)   # raises on mismatch
                self.assertEqual(
                    apply_delta(BuildingState.of_tree(a), program),
                    BuildingState.of_tree(b))

    def test_r2_identity_delta_is_empty(self) -> None:
        a = _fold(_grid_building(floors=3))
        program = delta_between(a, _fold(_grid_building(floors=3)))
        self.assertTrue(program.is_empty)
        self.assertEqual(program.touched_count, 0)
        self.assertEqual(
            apply_delta(BuildingState.of_tree(a), program),
            BuildingState.of_tree(a))

    def test_r3_delta_is_small_for_local_edit(self) -> None:
        name, a, b, _ta, _tb = _single_edit_scenarios()[0]
        program = delta_between(a, b)
        full_rebuild = sum(1 for _ in iter_l1_leaves(b))
        self.assertLess(program.touched_count, full_rebuild)
        self.assertGreater(program.reused_count, 0)
        # the reused leaves + touched cover the building (minus double-count of
        # changed pairs); at minimum reuse dominates a one-element edit.
        self.assertGreater(program.reused_count, program.touched_count)

    def test_r8_moved_cluster_is_relocate(self) -> None:
        a = _fold(_cluster_building(clusters=3, name="A"))
        b = _fold(_cluster_building(
            clusters=3, name="B", move_cluster=(2, 48_000.0)))
        program = delta_between(a, b)
        assert_transition(program, a, b)
        relocates = [op for op in program.ops if op.kind == "relocate"]
        self.assertEqual(len(relocates), 1)
        # relocate carries a hash (compile-verdict key) and moves content.
        self.assertIsNotNone(relocates[0].hash)


class PlanConsistency(unittest.TestCase):
    def test_r4_delta_matches_wave1_plan(self) -> None:
        for name, a, b, _ta, _tb in _single_edit_scenarios():
            with self.subTest(scenario=name):
                index_a = build_index(a, label="A")
                index_b = build_index(b, label="B")
                plan = incremental_plan(
                    diff_trees(index_a, index_b), index_a, index_b)
                program = build_delta(
                    diff_trees(index_a, index_b), index_a, index_b)
                # emitted+relocated adds == plan's emitted leaf total.
                self.assertEqual(
                    program.emitted_count + program.relocated_count,
                    plan.emitted_leaf_total)
                self.assertEqual(program.reused_count, plan.reused_leaf_total)


class Ordering(unittest.TestCase):
    def test_r5_order_retire_relocate_emit(self) -> None:
        a = _fold(_cluster_building(clusters=3, name="A"))
        b = _fold(_cluster_building(
            clusters=3, name="B", move_cluster=(2, 48_000.0)))
        program = delta_between(a, b)
        rank = {"retire": 0, "relocate": 1, "emit": 2}
        ranks = [rank[op.kind] for op in program.ops]
        self.assertEqual(ranks, sorted(ranks))

    def test_r5_order_on_mixed_edit(self) -> None:
        # An edit producing both removals and additions.
        a = _fold(_grid_building(floors=3, name="A"))
        b = _fold(_grid_building(
            floors=3, name="B", drop_wall_on_floor=1,
            extra_furniture_on_floor=0))
        program = delta_between(a, b)
        assert_transition(program, a, b)
        rank = {"retire": 0, "relocate": 1, "emit": 2}
        ranks = [rank[op.kind] for op in program.ops]
        self.assertEqual(ranks, sorted(ranks))


class FailClosed(unittest.TestCase):
    def test_r6_wrong_base_state_fails_closed(self) -> None:
        # A delta computed for A->B, applied to an unrelated C, must refuse
        # (its retire/relocate removals are not present in C's state).
        a = _fold(_grid_building(floors=3, name="A"))
        b = _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=1))
        program = delta_between(a, b)
        # program has a retire; apply to a state missing that element.
        self.assertTrue(any(op.remove_ops for op in program.ops))
        c = _fold(_cluster_building(clusters=2, name="C"))
        with self.assertRaises(DeltaApplyError):
            apply_delta(BuildingState.of_tree(c), program)

    def test_r6_malformed_state_fails_closed(self) -> None:
        a = _fold(_grid_building(floors=1))
        program = delta_between(a, _fold(_grid_building(floors=1)))
        with self.assertRaises(RebuildSchemaError):
            apply_delta({"not": "a state"}, program)  # type: ignore[arg-type]

    def test_r6_transition_guard_catches_wrong_delta(self) -> None:
        a = _fold(_grid_building(floors=3, name="A"))
        b = _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=1))
        c = _fold(_grid_building(floors=3, name="C", drop_wall_on_floor=2))
        program_ab = delta_between(a, b)
        # delta(A,B) does not transition A into C.
        with self.assertRaises(RebuildError):
            assert_transition(program_ab, a, c)


class Determinism(unittest.TestCase):
    def test_r7_same_pair_same_program(self) -> None:
        a1 = _fold(_grid_building(floors=3, name="A"))
        b1 = _fold(_grid_building(floors=3, name="B", stretch_wall_on_floor=1))
        a2 = _fold(_grid_building(floors=3, name="A"))
        b2 = _fold(_grid_building(floors=3, name="B", stretch_wall_on_floor=1))
        self.assertEqual(delta_between(a1, b1), delta_between(a2, b2))

    def test_r9_random_pairs_transition(self) -> None:
        rng = random.Random(24680)
        for _ in range(6):
            floors = rng.randint(2, 3)
            a = _fold(_grid_building(floors=floors, name="A"))
            b = _fold(_grid_building(
                floors=floors, name="B",
                stretch_wall_on_floor=(
                    rng.randrange(floors) if rng.random() < 0.6 else None),
                extra_furniture_on_floor=(
                    rng.randrange(floors) if rng.random() < 0.6 else None),
                drop_wall_on_floor=(
                    rng.randrange(floors) if rng.random() < 0.6 else None),
            ))
            program = delta_between(a, b)
            assert_transition(program, a, b)


class Flag(unittest.TestCase):
    def test_r9_flag_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_REBUILD", None)
        try:
            self.assertFalse(rebuild_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_REBUILD"] = previous

    def test_r9_flag_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_REBUILD")
        os.environ["KUKAI_IR_REBUILD"] = "on"
        try:
            self.assertTrue(rebuild_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_REBUILD"]
            else:
                os.environ["KUKAI_IR_REBUILD"] = previous


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
