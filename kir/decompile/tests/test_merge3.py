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
  M11 add/add on a source id the ANCESTOR never had (F-292)
  M12 identity-disjoint edits under one canonical op, base cardinality >= 2
      (F-295 and its mirror)
"""
from __future__ import annotations

import os
import tempfile
import unittest

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_merge3_queue.jsonl"))

from kir.decompile.rebuild import (  # noqa: E402
    BuildingState,
    apply_delta,
    delta_between,
)
from kir.decompile.fold import iter_l1_leaves  # noqa: E402
from kir.decompile.merge3 import (  # noqa: E402
    CONFLICT_ADD_ADD,
    CONFLICT_DELETE_MODIFY,
    CONFLICT_MODIFY_MODIFY,
    MergeConflictError,
    MergeSchemaError,
    conflicts_of,
    merge3,
    merge3_trees,
    merge_enabled,
)
from kir.decompile.tests.fixtures_decompile import make_element  # noqa: E402
from kir.decompile.tests.test_merkle import (  # noqa: E402
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


def _walls_building(name: str, *walls: tuple[int, float]):
    """A building carrying exactly the given ``(source id, length)`` walls.

    Built through the production path (`_document -> _fold`), never a
    hand-written counter: the whole subject is what the bridge reads off REAL
    L1 leaves (`source_element_id`), and a dict typed by hand would agree with
    whatever the test expected.
    """

    elements = [_wall(eid, _LEVEL, (0, 0, 0), (length, 0, 0))
                for eid, length in walls]
    elements += [_furniture(600 + index, float(index * 500))
                 for index in range(3)]
    return _fold(_document([_LEVEL], elements, name=name))


def _wall_ops(state: BuildingState) -> dict[str, int]:
    return {op: count for op, count in state.multiset
            if '"op_name":"create_wall"' in op}


def _wall_total(state: BuildingState) -> int:
    return sum(_wall_ops(state).values())


def _source_ids(tree) -> set[str]:
    return {leaf["source_element_id"] for leaf in iter_l1_leaves(tree)}


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


class IdentityDomain(unittest.TestCase):
    """M11/M12 — the bridge's domain used to be SMALLER than the merge's.

    Both defects are ONE silence: the identity bridge walked ancestor ids whose
    canonical op had count 1, and everywhere outside that the address-free
    multiset answered on its own, recording nothing.  Two carriers, one class:
    "the id is not in the base" (F-292) and "the count is not one" (F-295).

    Every input here is a REAL `lift -> fold` tree, and every assertion is a
    COUNT, not a word: a control that greps the module for `add_add` survives
    the mutation of the very condition it claims to pin.
    """

    def test_m11_add_add_on_an_id_the_ancestor_never_had(self) -> None:
        base = _walls_building("O")
        ours = _walls_building("A", (500, 6500.0))
        theirs = _walls_building("B", (500, 7000.0))

        # The carrier itself, stated as a number so the test cannot pass on a
        # degenerate input: the id is absent from the base and present in BOTH
        # branches (form 18 — there must be something to tell apart).
        self.assertNotIn("500", _source_ids(base))
        self.assertIn("500", _source_ids(ours))
        self.assertIn("500", _source_ids(theirs))

        result = merge3_trees(base, ours, theirs, policy="ours")
        add_add = [c for c in result.conflicts if c.kind == CONFLICT_ADD_ADD]
        self.assertEqual(len(add_add), 1,
                         "one element with two bodies is ONE conflict")
        self.assertEqual(add_add[0].source_id, "500")
        self.assertNotEqual(add_add[0].ours, add_add[0].theirs)
        # and the policy now actually picks a winner instead of keeping both
        self.assertEqual(_wall_total(result.state), 1)

    def test_m11_refuse_can_no_longer_stay_silent(self) -> None:
        with self.assertRaises(MergeConflictError):
            merge3_trees(
                _walls_building("O"),
                _walls_building("A", (500, 6500.0)),
                _walls_building("B", (500, 7000.0)),
                policy="refuse")

    def test_m11_one_author_adding_alone_is_still_clean(self) -> None:
        """The other direction: a NEW id only one author has is not a conflict.

        Without this the fix would be indistinguishable from "call every new id
        a conflict", which would be green on the case above and wrong.
        """

        result = merge3_trees(
            _walls_building("O"),
            _walls_building("A", (500, 6500.0)),
            _walls_building("B"),
            policy="refuse")
        self.assertTrue(result.clean)
        self.assertEqual(_wall_total(result.state), 1)

    def test_m11_both_authors_adding_the_SAME_body_is_not_a_conflict(
            self) -> None:
        result = merge3_trees(
            _walls_building("O"),
            _walls_building("A", (500, 6500.0)),
            _walls_building("B", (500, 6500.0)),
            policy="refuse")
        self.assertTrue(result.clean)
        self.assertEqual(_wall_total(result.state), 1)

    def test_m12_two_disjoint_deletes_at_base_cardinality_two(self) -> None:
        base = _walls_building("O", (500, 6000.0), (501, 6000.0))
        base_state = BuildingState.of_tree(base)

        # Form 18, spelled as numbers: the control is worthless at cardinality
        # 1 — it could not tell "identity was counted" from "there was only one
        # thing it could have been".  TWO elements, ONE canonical op.
        self.assertEqual(_wall_total(base_state), 2)
        self.assertEqual(len(_wall_ops(base_state)), 1,
                         "the two walls must be canonically INDISTINGUISHABLE")

        ours = _walls_building("A", (501, 6000.0))    # ours deletes 500
        theirs = _walls_building("B", (500, 6000.0))  # theirs deletes 501
        result = merge3_trees(base, ours, theirs, policy="ours")
        self.assertTrue(result.clean, "two disjoint deletes do not argue")
        self.assertEqual(
            _wall_total(result.state), 0,
            "both authors removed a wall; a building that keeps one keeps an "
            "element neither of them left standing")

    def test_m12_mirror_two_disjoint_adds_at_cardinality_two(self) -> None:
        """The same class from the other end (form 54).

        A guard written only against the DELETE it was first seen in would pin
        the shape of the first instance.  The property is "the two authors
        touched different identities", and it has an addition end.
        """

        base = _walls_building("O")
        ours = _walls_building("A", (500, 6000.0))
        theirs = _walls_building("B", (501, 6000.0))
        self.assertNotEqual(_source_ids(ours) - _source_ids(base),
                            _source_ids(theirs) - _source_ids(base))
        result = merge3_trees(base, ours, theirs, policy="ours")
        self.assertTrue(result.clean)
        self.assertEqual(
            _wall_total(result.state), 2,
            "two authors each added a DIFFERENT new element; merging them "
            "into one loses an author's work silently")

    def test_m12_both_deleting_the_SAME_element_still_merges_to_one(
            self) -> None:
        """The discriminating other side: equal deltas that really ARE agreed.

        Base 2, both authors delete element 500 -> exactly one wall left.  A
        fix that simply subtracted twice would be green on the case above and
        red here.
        """

        base = _walls_building("O", (500, 6000.0), (501, 6000.0))
        ours = _walls_building("A", (501, 6000.0))
        theirs = _walls_building("B", (501, 6000.0))
        result = merge3_trees(base, ours, theirs, policy="ours")
        self.assertTrue(result.clean)
        self.assertEqual(_wall_total(result.state), 1)

    def test_m12_identity_is_not_consulted_without_the_trees(self) -> None:
        """The address-free path is untouched: no trees, no identity, same answer.

        `BuildingState` stays a multiset of canonical op strings with no ids in
        it — that addresslessness is what the offline T-APPLY proof stands on,
        so the repair lives in the BRIDGE and nowhere else.
        """

        base = _walls_building("O", (500, 6000.0), (501, 6000.0))
        ours = _walls_building("A", (501, 6000.0))
        theirs = _walls_building("B", (500, 6000.0))
        stateless = merge3(BuildingState.of_tree(base),
                           BuildingState.of_tree(ours),
                           BuildingState.of_tree(theirs), policy="ours")
        self.assertEqual(_wall_total(stateless.state), 1)
        for op, _count in stateless.state.multiset:
            self.assertNotIn("source_element_id", op)

    def test_m12_an_identity_view_that_misses_a_leaf_refuses(self) -> None:
        """The correction's own denominator is checked, and the check can say no.

        The identity view is total for a well-formed fold, so a guard on it
        would be green by construction unless something can break it.  Here the
        subject is broken deliberately (form 8): two leaves put under ONE
        source id.  The canonical multiset does not move — a canon op carries
        no id — so the state still counts N while the view sees N-1, which is
        exactly the partial denominator the correction must never run on.
        """

        base = _walls_building("O", (500, 6000.0), (501, 6000.0))
        ours = _walls_building("A", (501, 6000.0))
        theirs = _walls_building("B", (500, 6000.0))
        leaves = list(iter_l1_leaves(base))
        self.assertGreaterEqual(len(leaves), 2)
        before = len(BuildingState.of_tree(base).as_counter())
        leaves[1]["source_element_id"] = leaves[0]["source_element_id"]
        self.assertEqual(len(BuildingState.of_tree(base).as_counter()), before,
                         "the state must be UNMOVED — otherwise the red below "
                         "would be about the multiset, not about identity")
        with self.assertRaises(MergeSchemaError):
            merge3_trees(base, ours, theirs, policy="ours")


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
