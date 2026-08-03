"""Incremental delta-rebuild as an executable operation (wave 6).

Wave 1 gave ``diff(A, B) -> RebuildPlan`` — a CLASSIFICATION of every subtree as
reuse / relocate / emit / retire, with the offline P7 proof that the emitted set
is exactly right.  This module turns that classification into an executable
**delta operation**: an ordered, typed program of edits that, applied to the
abstract state of building A, produces the state of building B — emitting ONLY
the delta, never the whole of B.  That is the payoff of the Merkle diff for edit
workflows ("edit one floor -> rebuild one floor, not the building").

Abstract state is the multiset of canonical absolute ops of the leaves
(``canon_op(leaf, (0,0,0))``) — the same id-independent, observable
representation P7 (wave 1) and the component round-trip (wave 5) use.  The
transition theorem (T-APPLY) is proved offline on multisets, no Revit:

    apply(state(A), delta(A, B)) == state(B)

Order is deterministic and execution-safe: ``all RETIRE -> all RELOCATE ->
all EMIT`` (retire before emit so a changed element's old copy is gone before
its new copy lands — no transient id clash in live Revit); on the multiset the
order is commutative, but a fixed applicable order matters for real execution.

Discipline (forks in INCREMENTAL_REBUILD_SPEC.md):

* **State is the canon_op multiset**, not the tree — observable, id-independent,
  so T-APPLY is offline-provable and rename/renumber A->B does not break it.
* **relocate is marked separately** (carries offset + hash) so an executor can
  transfer the compile verdict (same shape, new place — wave-1 Р-3), though on
  the state it behaves as remove-from + add-to (the saving is on compilation,
  not exec — stated honestly).
* **Fail-closed on an inapplicable delta.**  Applying delta(A,B) to a state that
  lacks a retire target is a typed ``DeltaApplyError`` — a delta applies ONLY to
  its own A, never silently.
* **Inert, additive, opt-in.**  Nothing is touched; ``rebuild_enabled()`` is
  default OFF.  Frozen L0 untouched.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from kukai.ir.decompile.fold import (
    FidelityCanon,
    TreeNode,
    canon_op,
    iter_l1_leaves,
)
from kukai.ir.decompile.l1_schema import L1Node
from kukai.ir.decompile.merkle import (
    MerkleDiff,
    MerkleIndex,
    RebuildPlan,
    build_index,
    diff_trees,
    incremental_plan,
)

_ZERO = (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class RebuildError(ValueError):
    """Base for every typed delta-rebuild failure."""


class DeltaApplyError(RebuildError):
    """A delta is not applicable to the given state (wrong base building)."""


class RebuildSchemaError(RebuildError):
    """A malformed plan or state."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def rebuild_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return os.getenv("KUKAI_IR_REBUILD", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Abstract building state (canonical absolute-op multiset)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BuildingState:
    """The observable state of a building: a multiset of canonical ops."""

    multiset: tuple[tuple[str, int], ...]  # sorted (canon_op, count) pairs

    @classmethod
    def of_leaves(cls, leaves: Iterable[L1Node]) -> "BuildingState":
        counts: Counter[str] = Counter(
            canon_op(leaf, _ZERO) for leaf in leaves)
        return cls(multiset=tuple(sorted(counts.items())))

    @classmethod
    def of_tree(cls, tree: TreeNode) -> "BuildingState":
        return cls.of_leaves(iter_l1_leaves(tree))

    def as_counter(self) -> Counter[str]:
        return Counter(dict(self.multiset))

    @classmethod
    def from_counter(cls, counter: Counter[str]) -> "BuildingState":
        return cls(multiset=tuple(sorted(
            (op, count) for op, count in counter.items() if count != 0)))


# ---------------------------------------------------------------------------
# Delta operation / program
# ---------------------------------------------------------------------------

_ORDER = {"retire": 0, "relocate": 1, "emit": 2}


@dataclass(frozen=True, slots=True)
class DeltaOp:
    """One typed edit: subtract ``remove_ops``, add ``add_ops`` on the state."""

    kind: str            # "retire" | "emit" | "relocate"
    reason: str          # "removed" | "added" | "changed" | "moved"
    path: tuple[int, ...] | None
    hash: str | None
    remove_ops: tuple[str, ...]
    add_ops: tuple[str, ...]
    remove_source_ids: tuple[str, ...]
    add_source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeltaProgram:
    """An ordered, applicable delta: retire -> relocate -> emit."""

    ops: tuple[DeltaOp, ...]
    reused_count: int
    # The legacy executable multiset uses TemplateCanon-compatible tokens for
    # merge/journal stability.  These graph-aware bindings prevent that broad
    # template equivalence from accepting the right edit against the wrong
    # floor/host topology (F1 transition-guard seam).
    base_fidelity_hash: str | None = None
    target_fidelity_hash: str | None = None

    @property
    def emitted_count(self) -> int:
        return sum(len(op.add_ops) for op in self.ops if op.kind == "emit")

    @property
    def retired_count(self) -> int:
        return sum(len(op.remove_ops) for op in self.ops if op.kind == "retire")

    @property
    def relocated_count(self) -> int:
        return sum(
            len(op.add_ops) for op in self.ops if op.kind == "relocate")

    @property
    def touched_count(self) -> int:
        return self.emitted_count + self.retired_count + self.relocated_count

    @property
    def is_empty(self) -> bool:
        return not self.ops


# ---------------------------------------------------------------------------
# Build a delta program from a plan
# ---------------------------------------------------------------------------


def _canon_ops(leaves: Iterable[L1Node]) -> tuple[str, ...]:
    return tuple(sorted(canon_op(leaf, _ZERO) for leaf in leaves))


def _source_ids(leaves: Iterable[L1Node]) -> tuple[str, ...]:
    return tuple(sorted(leaf["source_element_id"] for leaf in leaves))


def build_delta(
    diff: MerkleDiff,
    index_a: MerkleIndex,
    index_b: MerkleIndex,
) -> DeltaProgram:
    """Turn a diff into an ordered, applicable delta program."""

    plan: RebuildPlan = incremental_plan(diff, index_a, index_b)
    ops: list[DeltaOp] = []

    # RETIRE: removed subtrees + changed-out own leaves.
    for entry in plan.retire:
        occ = index_a.by_path.get(entry.path_a)
        if occ is None:
            raise RebuildSchemaError(
                f"retire path {entry.path_a} absent from index A")
        if entry.reason == "removed":
            leaves = list(iter_l1_leaves(occ.tree_node))
        else:  # changed: only the removed own-level leaves
            removed = set(entry.source_ids_a)
            leaves = [
                leaf for leaf in _own_leaves_of(occ.tree_node)
                if leaf["source_element_id"] in removed
            ]
        ops.append(DeltaOp(
            kind="retire",
            reason=entry.reason,
            path=entry.path_a,
            hash=entry.hash_a,
            remove_ops=_canon_ops(leaves),
            add_ops=(),
            remove_source_ids=_source_ids(leaves),
            add_source_ids=(),
        ))

    # RELOCATE: moved subtrees (verdict transfers; state = remove-from+add-to).
    for entry in plan.relocate:
        occ_b = index_b.by_path.get(entry.path_b)
        if occ_b is None:
            raise RebuildSchemaError(
                f"relocate path {entry.path_b} absent from index B")
        from_leaves = (
            list(iter_l1_leaves(index_a.by_path[entry.path_a].tree_node))
            if entry.path_a is not None
            and entry.path_a in index_a.by_path else [])
        to_leaves = list(entry.payloads_b)
        ops.append(DeltaOp(
            kind="relocate",
            reason="moved",
            path=entry.path_b,
            hash=entry.hash,
            remove_ops=_canon_ops(from_leaves),
            add_ops=_canon_ops(to_leaves),
            remove_source_ids=entry.source_ids_a,
            add_source_ids=_source_ids(to_leaves),
        ))

    # EMIT: added subtrees + changed-in own leaves.
    for entry in plan.emit:
        leaves = list(entry.payloads_b)
        ops.append(DeltaOp(
            kind="emit",
            reason=entry.reason,
            path=entry.path_b,
            hash=entry.hash_b,
            remove_ops=(),
            add_ops=_canon_ops(leaves),
            remove_source_ids=(),
            add_source_ids=_source_ids(leaves),
        ))

    ops.sort(key=lambda op: (_ORDER[op.kind], op.path or (), op.hash or ""))
    return DeltaProgram(ops=tuple(ops), reused_count=plan.reused_leaf_total)


def _own_leaves_of(node: TreeNode) -> list[L1Node]:
    leaves: list[L1Node] = []
    if node["payload"] is not None:
        leaves.append(node["payload"])
    leaves.extend(node["members"])
    return leaves


def delta_between(
    tree_a: TreeNode,
    tree_b: TreeNode,
    *,
    label_a: str = "A",
    label_b: str = "B",
) -> DeltaProgram:
    """Full path: index both trees, diff, and build the delta program."""

    index_a = build_index(tree_a, label=label_a)
    index_b = build_index(tree_b, label=label_b)
    diff = diff_trees(index_a, index_b)
    program = build_delta(diff, index_a, index_b)
    leaves_a = tuple(iter_l1_leaves(tree_a))
    leaves_b = tuple(iter_l1_leaves(tree_b))
    return DeltaProgram(
        ops=program.ops,
        reused_count=program.reused_count,
        base_fidelity_hash=FidelityCanon.multiset_hash(leaves_a, _ZERO),
        target_fidelity_hash=FidelityCanon.multiset_hash(leaves_b, _ZERO),
    )


# ---------------------------------------------------------------------------
# Application + transition proof
# ---------------------------------------------------------------------------


def apply_delta(
    state: BuildingState, program: DeltaProgram,
) -> BuildingState:
    """Apply the ordered delta; fail-closed on any inapplicable removal."""

    if not isinstance(state, BuildingState):
        raise RebuildSchemaError("apply_delta needs a BuildingState")
    counter = state.as_counter()
    for op in program.ops:
        for canonical in op.remove_ops:
            if counter.get(canonical, 0) <= 0:
                raise DeltaApplyError(
                    f"{op.kind}/{op.reason}: cannot remove absent element "
                    f"(delta not applicable to this state)")
            counter[canonical] -= 1
            if counter[canonical] == 0:
                del counter[canonical]
        for canonical in op.add_ops:
            counter[canonical] += 1
    return BuildingState.from_counter(counter)


def assert_transition(
    program: DeltaProgram, tree_a: TreeNode, tree_b: TreeNode,
) -> None:
    """T-APPLY: applying the delta to A's state yields B's state, or raise."""

    if program.base_fidelity_hash is not None:
        actual_base = FidelityCanon.multiset_hash(
            tuple(iter_l1_leaves(tree_a)), _ZERO)
        if actual_base != program.base_fidelity_hash:
            raise RebuildError(
                "delta base fidelity identity does not match state(A)")
    if program.target_fidelity_hash is not None:
        actual_target = FidelityCanon.multiset_hash(
            tuple(iter_l1_leaves(tree_b)), _ZERO)
        if actual_target != program.target_fidelity_hash:
            raise RebuildError(
                "delta target fidelity identity does not match state(B)")

    result = apply_delta(BuildingState.of_tree(tree_a), program)
    target = BuildingState.of_tree(tree_b)
    if result != target:
        raise RebuildError(
            "delta does not transition state(A) into state(B)")


__all__ = [
    "BuildingState",
    "DeltaApplyError",
    "DeltaOp",
    "DeltaProgram",
    "RebuildError",
    "RebuildSchemaError",
    "apply_delta",
    "assert_transition",
    "build_delta",
    "delta_between",
    "rebuild_enabled",
]
