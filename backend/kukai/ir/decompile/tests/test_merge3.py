"""Property tests for 3-way semantic merge (merge3.py).

Dependency-free property style over REAL ``lift -> fold`` O/A/B triples with
controlled divergent edits.  Non-conflicting auto-merge (M1), symmetry (M3),
and typed conflict detection (M4/M6) are the heart: both authors' edits live,
merge is order-independent when clean, and a real conflict is surfaced (never
swallowed).

Numbering matches THREE_WAY_MERGE_SPEC §7:
  M1 disjoint edits -> both live, no conflict
  M2 T-MERGE degenerate (merge(O,A,A)==A etc.)
  M3 symmetry (clean merge is order-independent)
  M4 modify/modify conflict on the SAME unique element
  M5 policy (ours/theirs/union/refuse)
  M6 delete/modify conflict via the source-id bridge
  M7 determinism (sorted conflicts; cross-process)
  M8 clean merge == applying both deltas
  M9 fail-closed (malformed input; refuse raises)
  M10 flag default OFF
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_merge3_queue.jsonl"))

from kukai.ir.decompile.rebuild import (  # noqa: E402
    BuildingState,
    apply_delta,
    delta_between,
)
from kukai.ir.decompile.merge3 import (  # noqa: E402
    CONFLICT_DELETE_MODIFY,
    CONFLICT_MODIFY_MODIFY,
    MergeConflictError,
    MergeSchemaError,
    conflicts_of,
    merge3,
    merge3_trees,
    merge_enabled,
)
from kukai.ir.decompile.tests.fixtures_decompile import make_element  # noqa: E402
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _document,
    _fold,
    _grid_building,
    _on_level,
    _wall,
)

_LEVEL = ("100", "Этаж 1", 0.0)


def _furniture(eid: int, x: float):
    row = _on_level(make_element("OST_Furniture", eid, ordinal=0), _LEVEL)
    row.update({
        "geom_kind": "point", "p0_mm": [x, 2000.0, 0.0], "p1_mm": None,
        "rotation_deg": 0.0,
        "bbox_min_mm": [x, 1900.0, 0.0],
        "bbox_max_mm": [x + 300.0, 2100.0, 800.0]})
    return row


def _one_wall_building(wall_len: float, name: str, *, drop_wall: bool = False):
    """A building with ONE unique identifiable wall (id 500) + 3 furniture."""
    elements = []
    if not drop_wall:
        elements.append(_wall(500, _LEVEL, (0, 0, 0), (wall_len, 0, 0)))
    for i in range(3):
        elements.append(_furniture(600 + i, float(i * 500)))
    return _fold(_document([_LEVEL], elements, name=name))


class NonConflicting(unittest.TestCase):
    def test_m1_disjoint_edits_both_live(self) -> None:
        base = _fold(_grid_building(floors=3, name="O"))
        ours = _fold(_grid_building(
            floors=3, name="A", extra_furniture_on_floor=0))
        theirs = _fold(_grid_building(
            floors=3, name="B", drop_wall_on_floor=2))
        result = merge3_trees(base, ours, theirs, policy="ours")
        self.assertTrue(result.clean)
        self.assertEqual(len(result.conflicts), 0)
        self.assertGreater(result.auto_merged, 0)

    def test_m8_clean_merge_equals_applying_both_deltas(self) -> None:
        base = _fold(_grid_building(floors=3, name="O"))
        ours = _fold(_grid_building(
            floors=3, name="A", extra_furniture_on_floor=0))
        theirs = _fold(_grid_building(
            floors=3, name="B", drop_wall_on_floor=2))
        merged = merge3_trees(base, ours, theirs).state
        both = apply_delta(
            apply_delta(BuildingState.of_tree(base), delta_between(base, ours)),
            delta_between(base, theirs))
        self.assertEqual(merged, both)


class Degenerate(unittest.TestCase):
    def setUp(self) -> None:
        self.O = _fold(_grid_building(floors=3, name="O"))
        self.A = _fold(_grid_building(
            floors=3, name="A", extra_furniture_on_floor=0))
        self.B = _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=2))

    def test_m2_merge_ours_equals_ours_state(self) -> None:
        self.assertEqual(
            merge3_trees(self.O, self.A, self.A).state,
            BuildingState.of_tree(self.A))

    def test_m2_only_theirs_changed(self) -> None:
        self.assertEqual(
            merge3_trees(self.O, self.O, self.B).state,
            BuildingState.of_tree(self.B))

    def test_m2_only_ours_changed(self) -> None:
        self.assertEqual(
            merge3_trees(self.O, self.A, self.O).state,
            BuildingState.of_tree(self.A))

    def test_m3_clean_merge_is_symmetric(self) -> None:
        self.assertEqual(
            merge3_trees(self.O, self.A, self.B).state,
            merge3_trees(self.O, self.B, self.A).state)


class Conflicts(unittest.TestCase):
    def test_m4_modify_modify_same_element(self) -> None:
        base = _one_wall_building(6000.0, "O")
        ours = _one_wall_building(6500.0, "A")
        theirs = _one_wall_building(7000.0, "B")
        result = merge3_trees(base, ours, theirs, policy="ours")
        self.assertFalse(result.clean)
        kinds = {c.kind for c in result.conflicts}
        self.assertIn(CONFLICT_MODIFY_MODIFY, kinds)

    def test_m6_delete_modify(self) -> None:
        base = _one_wall_building(6000.0, "O")
        ours = _one_wall_building(0.0, "A", drop_wall=True)  # deletes the wall
        theirs = _one_wall_building(6500.0, "B")             # modifies the wall
        result = merge3_trees(base, ours, theirs, policy="ours")
        kinds = {c.kind for c in result.conflicts}
        self.assertIn(CONFLICT_DELETE_MODIFY, kinds)

    def test_conflict_carries_both_sides(self) -> None:
        base = _one_wall_building(6000.0, "O")
        ours = _one_wall_building(6500.0, "A")
        theirs = _one_wall_building(7000.0, "B")
        conflicts = conflicts_of(base, ours, theirs,
                                 base_tree=base, ours_tree=ours,
                                 theirs_tree=theirs)
        modify = [c for c in conflicts if c.kind == CONFLICT_MODIFY_MODIFY]
        self.assertTrue(modify)
        self.assertIsNotNone(modify[0].ours)
        self.assertIsNotNone(modify[0].theirs)
        self.assertNotEqual(modify[0].ours, modify[0].theirs)


class Policy(unittest.TestCase):
    def _triple(self):
        return (_one_wall_building(6000.0, "O"),
                _one_wall_building(6500.0, "A"),
                _one_wall_building(7000.0, "B"))

    def test_m5_ours_takes_ours(self) -> None:
        base, ours, theirs = self._triple()
        result = merge3_trees(base, ours, theirs, policy="ours")
        # The merged state must contain OUR wall length, not theirs.
        ours_ops = set(dict(BuildingState.of_tree(ours).multiset))
        theirs_ops = set(dict(BuildingState.of_tree(theirs).multiset))
        merged_ops = set(dict(result.state.multiset))
        our_only = ours_ops - theirs_ops
        their_only = theirs_ops - ours_ops
        self.assertTrue(our_only & merged_ops)
        self.assertFalse(their_only & merged_ops)

    def test_m5_theirs_takes_theirs(self) -> None:
        base, ours, theirs = self._triple()
        result = merge3_trees(base, ours, theirs, policy="theirs")
        merged_ops = set(dict(result.state.multiset))
        their_only = (set(dict(BuildingState.of_tree(theirs).multiset))
                      - set(dict(BuildingState.of_tree(ours).multiset)))
        self.assertTrue(their_only & merged_ops)

    def test_m5_union_keeps_both(self) -> None:
        base, ours, theirs = self._triple()
        result = merge3_trees(base, ours, theirs, policy="union")
        merged_ops = set(dict(result.state.multiset))
        our_only = (set(dict(BuildingState.of_tree(ours).multiset))
                    - set(dict(BuildingState.of_tree(theirs).multiset)))
        their_only = (set(dict(BuildingState.of_tree(theirs).multiset))
                      - set(dict(BuildingState.of_tree(ours).multiset)))
        self.assertTrue(our_only & merged_ops)
        self.assertTrue(their_only & merged_ops)

    def test_m5_refuse_raises_on_conflict(self) -> None:
        base, ours, theirs = self._triple()
        with self.assertRaises(MergeConflictError):
            merge3_trees(base, ours, theirs, policy="refuse")

    def test_m5_refuse_ok_when_clean(self) -> None:
        base = _fold(_grid_building(floors=3, name="O"))
        ours = _fold(_grid_building(
            floors=3, name="A", extra_furniture_on_floor=0))
        theirs = _fold(_grid_building(floors=3, name="B", drop_wall_on_floor=2))
        result = merge3_trees(base, ours, theirs, policy="refuse")
        self.assertTrue(result.clean)


class Determinism(unittest.TestCase):
    def test_m7_same_triple_same_result(self) -> None:
        a = merge3_trees(
            _one_wall_building(6000.0, "O"),
            _one_wall_building(6500.0, "A"),
            _one_wall_building(7000.0, "B"))
        b = merge3_trees(
            _one_wall_building(6000.0, "O"),
            _one_wall_building(6500.0, "A"),
            _one_wall_building(7000.0, "B"))
        self.assertEqual(a.state, b.state)
        self.assertEqual(a.conflicts, b.conflicts)

    def test_m7_conflicts_sorted(self) -> None:
        result = merge3_trees(
            _one_wall_building(6000.0, "O"),
            _one_wall_building(6500.0, "A"),
            _one_wall_building(7000.0, "B"))
        keys = [(c.kind, c.canon_op or "", c.source_id or "")
                for c in result.conflicts]
        self.assertEqual(keys, sorted(keys))


class FailClosedAndFlag(unittest.TestCase):
    def test_m9_malformed_input_fails_closed(self) -> None:
        with self.assertRaises(MergeSchemaError):
            merge3({"not": "a state"}, BuildingState(()), BuildingState(()))

    def test_m9_unknown_policy_fails_closed(self) -> None:
        with self.assertRaises(MergeSchemaError):
            merge3(BuildingState(()), BuildingState(()), BuildingState(()),
                   policy="nonsense")

    def test_m10_flag_default_off(self) -> None:
        previous = os.environ.pop("KUKAI_IR_MERGE3", None)
        try:
            self.assertFalse(merge_enabled())
        finally:
            if previous is not None:
                os.environ["KUKAI_IR_MERGE3"] = previous

    def test_m10_flag_opt_in(self) -> None:
        previous = os.environ.get("KUKAI_IR_MERGE3")
        os.environ["KUKAI_IR_MERGE3"] = "true"
        try:
            self.assertTrue(merge_enabled())
        finally:
            if previous is None:
                del os.environ["KUKAI_IR_MERGE3"]
            else:
                os.environ["KUKAI_IR_MERGE3"] = previous


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
