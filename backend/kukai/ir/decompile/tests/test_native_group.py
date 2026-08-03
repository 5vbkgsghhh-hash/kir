"""Property tests for the native Revit group layer (native_group.py) — the
forward `create_group` op's OFFLINE fidelity proof.

The native-group emission (``authoring._emit_group``) cannot be run without
Revit, so fidelity is proven at the KIR level: expanding a ``NativeGroupOp``
(definition members + per-occurrence deltas) must reproduce the SAME absolute
leaf multiset as the plain N-element rebuild the ``PlaceGroupOp`` already
produces — which ``component.py`` proves equals the source building.  Equality
is by CONSTRUCTION (both paths call ``instantiate(defn, offset)``), so this is a
guard against a placement-math regression (the LOT31 C-RT bug class), not luck.

Coverage:
  NG1  bridge derives a NativeGroupOp with deltas = occ_origin_k - occ_origin_0
       and a NONZERO base origin (the origin-dependence the old bug masked)
  NG2  expand_group_op == N-element expansion (fidelity), synthetic buildings
       incl. NONZERO dx/dy/dz (a (0,0,0)-origin fixture hides origin bugs)
  NG3  REAL building: whole-lot31 native-group substitution == source multiset
  NG4  fail-closed: single occurrence / empty definition -> bridge returns None
       (caller keeps N loose elements — geometry never lost)
  NG5  determinism + flag default OFF
"""
from __future__ import annotations

import os
import pickle
import tempfile
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("KIR_REJECTIONS_PATH",
                      os.path.join(tempfile.gettempdir(), "kir_ng_queue.jsonl"))

from kukai.ir.decompile.component import (  # noqa: E402
    ComponentFidelityProof,
    ComponentInstance,
    PlaceGroupOp,
    build_library,
    extract_component,
    instantiate,
    prove_execution_fidelity,
)
from kukai.ir.decompile.fold import (  # noqa: E402
    FidelityCanon,
    canon_op,
    iter_l1_leaves,
)
from kukai.ir.decompile.merkle import build_index  # noqa: E402
from kukai.ir.decompile.native_group import (  # noqa: E402
    ComponentSchemaError,
    NativeGroupOp,
    assert_group_matches_place_op,
    expand_group_op,
    group_op_from_place_op,
    native_group_enabled,
    native_group_op_to_ir,
)
from kukai.ir.decompile.tests.test_merkle import (  # noqa: E402
    _cluster_building,
    _fold,
    _grid_building,
)

_ZERO = (0.0, 0.0, 0.0)
_LOT31_TREE = Path("/home/claude/lot31_full/_tree_cache.pkl")


def _abs_multiset(leaves):
    return Counter(canon_op(leaf, _ZERO) for leaf in leaves)


def _n_element_multiset(place_op: PlaceGroupOp) -> Counter:
    """The multiset the plain N-loose-element rebuild of this op materializes."""
    leaves = []
    for inst in place_op.instances:
        leaves.extend(instantiate(
            place_op.definition, inst.offset_mm,
            instance_index=inst.instance_index, regenerate_ids=False))
    return _abs_multiset(leaves)


def _groupable_ops(tree):
    index = build_index(tree, label="ng")
    lib = prove_execution_fidelity(build_library(index), index)
    return lib, [op for op in lib.place_ops if op.occurrence_count >= 2]


def _placement_math_fixture(op: PlaceGroupOp) -> PlaceGroupOp:
    """Authorize an isolated placement-math test, not an execution candidate.

    Cross-storey fixtures deliberately differ in concrete Level bindings and
    are therefore rejected by the real bridge.  Some tests below exercise only
    O0+delta arithmetic; this helper makes that narrow test precondition
    explicit instead of weakening the production fidelity gate.
    """

    hashes = tuple(f"{index + 1:040x}" for index in range(
        op.occurrence_count))
    return replace(
        op,
        fidelity_proof=ComponentFidelityProof(
            canon_version=FidelityCanon.VERSION,
            instantiated_hashes=hashes,
            source_hashes=hashes,
        ),
    )


class BridgeAndDeltas(unittest.TestCase):
    def test_ng1_deltas_are_absolute_origin_differences(self) -> None:
        # A building translated far from origin so occ_origin_0 != (0,0,0):
        # the delta math must be occ_origin_k - occ_origin_0, never assume 0.
        tree = _fold(_grid_building(
            floors=4, dx=30_000.0, dy=23_000.0, dz=100_000.0))
        _lib, groupable = _groupable_ops(tree)
        self.assertTrue(groupable, "translated grid must repeat a floor")
        saw_nonzero_base = False
        for op in groupable:
            gop = group_op_from_place_op(_placement_math_fixture(op))
            self.assertIsNotNone(gop)
            if gop.base_origin_mm != _ZERO:
                saw_nonzero_base = True
            # base origin == occurrence 0's absolute offset
            self.assertEqual(gop.base_origin_mm, op.instances[0].offset_mm)
            # each delta == occ_origin_k - occ_origin_0, elementwise
            for k, inst in enumerate(op.instances[1:]):
                want = tuple(
                    round(inst.offset_mm[i] - op.instances[0].offset_mm[i], 3)
                    for i in range(3))
                self.assertEqual(gop.placement_deltas_mm[k], want)
            self.assertEqual(gop.occurrence_count, op.occurrence_count)
        self.assertTrue(
            saw_nonzero_base,
            "the translated building must exercise a NONZERO base origin "
            "(the origin-dependence the LOT31 C-RT bug masked)")


class Fidelity(unittest.TestCase):
    def _cases(self):
        return {
            "grid3": _fold(_grid_building(floors=3)),
            "grid4": _fold(_grid_building(floors=4)),
            "cluster3": _fold(_cluster_building(clusters=3)),
            # NONZERO-origin regressions — the LOT31 bug coincided with the
            # correct value only at def_origin == (0,0,0); these translate the
            # whole building so origin errors cannot hide.
            "grid4-hi": _fold(_grid_building(
                floors=4, dx=30_000.0, dy=23_000.0, dz=100_000.0)),
            "cluster3-lo": _fold(_grid_building(
                floors=3, dx=-45_000.0, dy=17_000.0, dz=50_000.0)),
        }

    def test_ng2_group_expansion_matches_n_elements(self) -> None:
        for name, tree in self._cases().items():
            with self.subTest(case=name):
                lib, groupable = _groupable_ops(tree)
                self.assertTrue(groupable, f"{name} must repeat a shape")
                for op in groupable:
                    gop = group_op_from_place_op(op)
                    if not op.fidelity_proven:
                        self.assertIsNone(
                            gop,
                            f"{name}: template equality cannot authorize a "
                            "native group with different BIM bindings")
                        continue
                    self.assertIsNotNone(gop)
                    # per-op fidelity: native group == N loose elements
                    self.assertEqual(
                        _abs_multiset(expand_group_op(gop)),
                        _n_element_multiset(op),
                        f"{name}: native group must reproduce the N-element "
                        "leaf multiset exactly")
                    assert_group_matches_place_op(gop, op)  # raises on drift

    def test_ng2b_whole_building_substitution_is_lossless(self) -> None:
        # Replace every groupable place-op with its native-group expansion,
        # keep the rest, and prove the WHOLE building still equals the source.
        for name, tree in self._cases().items():
            with self.subTest(case=name):
                lib, groupable = _groupable_ops(tree)
                grouped_hashes = {
                    op.def_hash for op in groupable
                    if group_op_from_place_op(op) is not None}
                combined = []
                for op in lib.place_ops:
                    if op.def_hash in grouped_hashes:
                        combined.extend(expand_group_op(
                            group_op_from_place_op(op)))
                    else:
                        for inst in op.instances:
                            combined.extend(instantiate(
                                op.definition, inst.offset_mm,
                                instance_index=inst.instance_index,
                                regenerate_ids=False))
                combined.extend(lib.singletons_leaves)
                self.assertEqual(
                    _abs_multiset(combined),
                    _abs_multiset(iter_l1_leaves(tree)),
                    f"{name}: native-group substitution lost/invented geometry")


@unittest.skipUnless(_LOT31_TREE.exists(), "lot31 tree cache not present")
class RealBuilding(unittest.TestCase):
    """The proof that matters: a real building (LOT31), not synthetic."""

    @classmethod
    def setUpClass(cls) -> None:
        with _LOT31_TREE.open("rb") as stream:
            cls.tree = pickle.load(stream)
        cls.index = build_index(cls.tree, label="lot31")
        cls.lib = prove_execution_fidelity(
            build_library(cls.index), cls.index)
        cls.groupable = [
            op for op in cls.lib.place_ops
            if op.occurrence_count >= 2 and op.fidelity_proven]

    def test_ng3_real_building_has_repeated_components(self) -> None:
        self.assertGreater(
            len(self.groupable), 0,
            "LOT31 is expected to have repeated components (typical floors)")

    def test_ng3_real_building_bridge_and_nonzero_origins(self) -> None:
        derived = [group_op_from_place_op(op) for op in self.groupable]
        derived = [g for g in derived if g is not None]
        self.assertEqual(len(derived), len(self.groupable))
        nonzero = sum(1 for g in derived if g.base_origin_mm != _ZERO)
        # The LOT31 directive: repeats sit HIGH in the tower (z up to 100800);
        # the overwhelming majority must have a nonzero base origin.
        self.assertGreater(
            nonzero, len(derived) // 2,
            "most real repeats must sit at a nonzero origin (the C-RT bug case)")

    def test_ng3_real_building_per_op_fidelity(self) -> None:
        for op in self.groupable:
            gop = group_op_from_place_op(op)
            self.assertIsNotNone(gop)
            self.assertEqual(
                _abs_multiset(expand_group_op(gop)),
                _n_element_multiset(op),
                f"LOT31 component {op.def_hash[:12]}: native group must "
                "reproduce the N-element leaves exactly")
            assert_group_matches_place_op(gop, op)

    def test_ng3_real_building_whole_substitution_is_lossless(self) -> None:
        grouped_hashes = {op.def_hash for op in self.groupable}
        combined = []
        for op in self.lib.place_ops:
            if op.def_hash in grouped_hashes:
                combined.extend(expand_group_op(group_op_from_place_op(op)))
            else:
                for inst in op.instances:
                    combined.extend(instantiate(
                        op.definition, inst.offset_mm,
                        instance_index=inst.instance_index,
                        regenerate_ids=False))
        combined.extend(self.lib.singletons_leaves)
        self.assertEqual(
            _abs_multiset(combined),
            _abs_multiset(iter_l1_leaves(self.tree)),
            "LOT31: whole-building native-group substitution changed geometry")


class FailClosed(unittest.TestCase):
    def _single_occurrence_op(self) -> PlaceGroupOp:
        # A place-op with exactly ONE instance (nothing to group).
        tree = _fold(_grid_building(floors=3))
        _lib, groupable = _groupable_ops(tree)
        template = groupable[0]
        one = ComponentInstance(
            def_hash=template.def_hash, instance_index=0,
            offset_mm=template.instances[0].offset_mm,
            origin_mm=template.instances[0].origin_mm,
            rel_mm=template.instances[0].rel_mm)
        return PlaceGroupOp(
            def_hash=template.def_hash, definition=template.definition,
            instances=(one,))

    def test_ng4_single_occurrence_refuses_grouping(self) -> None:
        # Fail-closed: one occurrence -> None -> caller keeps it as N=1 loose
        # elements.  Grouping a single instance buys nothing and only risks
        # divergence.
        self.assertIsNone(group_op_from_place_op(self._single_occurrence_op()))

    def test_ng4_bad_input_is_typed(self) -> None:
        with self.assertRaises(ComponentSchemaError):
            group_op_from_place_op({"not": "a place op"})  # type: ignore[arg-type]
        with self.assertRaises(ComponentSchemaError):
            expand_group_op({"not": "a native group op"})  # type: ignore[arg-type]

    def test_ng4_placement_math_divergence_is_caught(self) -> None:
        # A native-group op whose deltas are deliberately WRONG (relative-delta
        # form: occ_origin_k - def_origin instead of occ_origin_k -
        # occ_origin_0) must be caught by assert_group_matches_place_op — the
        # exact LOT31 bug, fail-closed BEFORE emission.
        tree = _fold(_grid_building(
            floors=4, dx=30_000.0, dy=23_000.0, dz=100_000.0))
        _lib, groupable = _groupable_ops(tree)
        op = next(o for o in groupable if o.occurrence_count >= 2)
        good = group_op_from_place_op(_placement_math_fixture(op))
        self.assertIsNotNone(good)
        # Corrupt the deltas with the def-origin (the buggy relative form).
        def_origin = op.definition.origin_mm
        bad_deltas = tuple(
            (d[0] + def_origin[0], d[1] + def_origin[1], d[2] + def_origin[2])
            for d in good.placement_deltas_mm)
        # only meaningful if the def origin is actually nonzero here
        if def_origin != _ZERO:
            bad = NativeGroupOp(
                def_hash=good.def_hash, definition=good.definition,
                base_origin_mm=good.base_origin_mm,
                placement_deltas_mm=bad_deltas, label=good.label)
            with self.assertRaises(ComponentSchemaError):
                assert_group_matches_place_op(bad, op)


class IrSeam(unittest.TestCase):
    def test_ng6_to_ir_carries_deltas_and_name(self) -> None:
        tree = _fold(_grid_building(floors=4, dx=30_000.0, dz=100_000.0))
        _lib, groupable = _groupable_ops(tree)
        gop = group_op_from_place_op(
            _placement_math_fixture(groupable[0]))
        # a stand-in member op-dict (the leaf->authoring-op materializer is the
        # documented next step; this seam owns only placements+name).
        members = [{"op": "create_wall", "id": "W1"}]
        ir = native_group_op_to_ir(gop, members, op_id="GRP1", name="Этаж")
        self.assertEqual(ir["op"], "create_group")
        self.assertEqual(ir["id"], "GRP1")
        self.assertEqual(ir["name"], "Этаж")
        self.assertEqual(ir["members"], members)
        self.assertEqual(
            ir["placements"],
            [list(d) for d in gop.placement_deltas_mm])
        # placements count == occurrences - 1 (occurrence 0 is the members).
        self.assertEqual(len(ir["placements"]), gop.occurrence_count - 1)

    def test_ng6_to_ir_typed_on_bad_input(self) -> None:
        with self.assertRaises(ComponentSchemaError):
            native_group_op_to_ir({"x": 1}, [], op_id="G")  # type: ignore[arg-type]


class Determinism(unittest.TestCase):
    def test_ng5_deterministic(self) -> None:
        tree = _fold(_grid_building(floors=4, dx=12_000.0, dz=9_000.0))
        _lib, groupable = _groupable_ops(tree)
        a = [group_op_from_place_op(op) for op in groupable]
        b = [group_op_from_place_op(op) for op in groupable]
        self.assertEqual(a, b)  # frozen dataclasses -> value equality

    def test_ng5_flag_default_off(self) -> None:
        saved = os.environ.pop("KUKAI_IR_NATIVE_GROUP", None)
        try:
            self.assertFalse(native_group_enabled())
            os.environ["KUKAI_IR_NATIVE_GROUP"] = "1"
            self.assertTrue(native_group_enabled())
            os.environ["KUKAI_IR_NATIVE_GROUP"] = "off"
            self.assertFalse(native_group_enabled())
        finally:
            os.environ.pop("KUKAI_IR_NATIVE_GROUP", None)
            if saved is not None:
                os.environ["KUKAI_IR_NATIVE_GROUP"] = saved


if __name__ == "__main__":
    unittest.main()
