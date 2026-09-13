"""Wiring the `rebuild` layer outward: rebuilding by DELTA, not by the whole building.

`rebuild.py` can turn the difference between two decompiles into an
executable typed delta (`delta_between`) and prove the transition
`apply(state(A), Δ) == state(B)` (`assert_transition`). What it CANNOT do is
tell the materializer exactly which leaves of B need to be turned into
programs. That was exactly what was missing: 362 lines and 14 tests sat in
storage carrying their own docstring's note "opt-in gate for future pipeline
wiring", while the single live rebuild entry point
(`serving.handle_revit_rebuild`) took ALL leaves of `tree.json` every time —
that is, it built the whole building even when the previous decompile of the
same building was sitting right there.

This module computes nothing new. It lives between `rebuild` and its two
consumers:

* `ir/serving.py::handle_revit_rebuild` — the live path: with the
  `KUKAI_IR_REBUILD` flag and an explicitly named `base_doc_stamp`, the
  rebuild materializes a SUBSET of B's leaves instead of the whole tree;
* `tools/kir_rebuild.py` — the operator's instrument: the same plan over two
  saved decompiles, with no Revit and no flag (an instrument, not a
  behaviour).

CLOSURE OVER REFERENCES — WHY A DELTA FROM A SINGLE CLASSIFICATION IS NOT
ENOUGH. The materializer resolves `{"ref": <l1_id>}` only WITHIN a run: a
reference whose target is not materialized also drops the op itself — a
typed `host_unmaterialized` skip (see `materialize.leaves_to_program`, the
loop to a fixed point). This means a naive "only the changed leaves" delta
SILENTLY loses exactly what the operator was ruling on: a changed door in an
unchanged wall would be left as a skip. So the set to materialize is closed
over the undirected `ref` graph — the same connected component the
materializer treats as indivisible (Д5a).

The closure does NOT break the T-APPLY theorem, and this is checked, not
promised: for every unchanged leaf X pulled in by the closure, a "retire X" +
"emit X" pair (`refresh`) is appended to the delta, which sums to zero on the
multiset, after which `assert_transition` is run on the EXPANDED program. If
A is not the right one, `apply_delta` refuses in a typed way
(`DeltaApplyError`), and that is the only correct outcome: a delta applied to
a base other than its own A is a silently wrong result — that is, a breach
of the main invariant.

The reference walk is taken from the materializer (`_iter_refs`) rather than
rewritten: that is the SOLE authority on what counts as a reference at all,
and two diverging walks would be worse than none.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from kir.decompile.fold import TreeNode, canon_op, iter_l1_leaves
from kir.decompile.l1_schema import L1Node
from kir.decompile.materialize import _iter_refs
from kir.decompile.rebuild import (
    DeltaOp,
    DeltaProgram,
    assert_transition,
    delta_between,
)

REBUILD_PLAN_SCHEMA = "kir-rebuild-plan/1"

_ZERO = (0.0, 0.0, 0.0)

__all__ = [
    "REBUILD_PLAN_SCHEMA",
    "DeltaRebuildPlan",
    "delta_rebuild_plan",
    "plan_refusal",
    "plan_report",
]


@dataclass(frozen=True, slots=True)
class DeltaRebuildPlan:
    """Exactly what to materialize so that building A becomes building B."""

    program: DeltaProgram
    # Leaves of B that the delta named itself (emit + relocate).
    emit_source_ids: frozenset[str]
    # Leaves of B pulled in by closure over `ref`: unchanged themselves, but
    # sharing a connected component with changed ones — without them the
    # reference would not resolve.
    closure_source_ids: frozenset[str]
    # Leaves of A that are no longer in B (or whose content changed).
    retire_source_ids: tuple[str, ...]
    leaves_total_a: int
    leaves_total_b: int

    @property
    def materialize_source_ids(self) -> frozenset[str]:
        return self.emit_source_ids | self.closure_source_ids

    @property
    def materialize_total(self) -> int:
        return len(self.emit_source_ids) + len(self.closure_source_ids)

    @property
    def is_empty(self) -> bool:
        """The buildings coincide: nothing to materialize and nothing to retire."""

        return not self.materialize_source_ids and not self.retire_source_ids


def _op_leaves_by_id(leaves: Iterable[L1Node]) -> dict[str, L1Node]:
    return {leaf["_id"]: leaf for leaf in leaves if leaf["kind"] == "op"}


def _close_over_refs(
    by_l1_id: dict[str, L1Node], seeds: frozenset[str],
) -> frozenset[str]:
    """Close the set of `source_element_id` over the undirected `ref` graph.

    Returns the ADDITION (without the seeds themselves), so the caller sees
    the cost of the closure as a separate number: a closure that cannot be
    seen is a silent growth of the delta — and the delta's size is exactly
    what all of this was undertaken for.
    """

    adjacency: dict[str, set[str]] = {leaf_id: set() for leaf_id in by_l1_id}
    for leaf_id, leaf in by_l1_id.items():
        for target in _iter_refs(leaf["params"]):
            if target in by_l1_id and target != leaf_id:
                adjacency[leaf_id].add(target)
                adjacency[target].add(leaf_id)

    seed_l1_ids = [
        leaf_id for leaf_id, leaf in by_l1_id.items()
        if leaf["source_element_id"] in seeds
    ]
    visited: set[str] = set(seed_l1_ids)
    stack = list(seed_l1_ids)
    while stack:
        current = stack.pop()
        for neighbour in adjacency[current]:
            if neighbour not in visited:
                visited.add(neighbour)
                stack.append(neighbour)
    return frozenset(
        by_l1_id[leaf_id]["source_element_id"] for leaf_id in visited
    ) - seeds


def _refresh_ops(leaves: Iterable[L1Node]) -> tuple[DeltaOp, ...]:
    """A "retire X" + "emit X" pair for every unchanged leaf pulled in.

    On the multiset this is zero, so T-APPLY is preserved; but the retiring
    goes through the very same `apply_delta`, which means the closure
    CANNOT pull in an element that was not in state A — the refusal will be
    a typed one.
    """

    ops: list[DeltaOp] = []
    for leaf in leaves:
        canonical = canon_op(leaf, _ZERO)
        source_id = leaf["source_element_id"]
        ops.append(DeltaOp(
            kind="retire", reason="refresh", path=None, hash=None,
            remove_ops=(canonical,), add_ops=(),
            remove_source_ids=(source_id,), add_source_ids=()))
        ops.append(DeltaOp(
            kind="emit", reason="refresh", path=None, hash=None,
            remove_ops=(), add_ops=(canonical,),
            remove_source_ids=(), add_source_ids=(source_id,)))
    return tuple(ops)


def delta_rebuild_plan(
    tree_a: TreeNode,
    tree_b: TreeNode,
    *,
    label_a: str = "a",
    label_b: str = "b",
) -> DeltaRebuildPlan:
    """The A→B delta, closed over references and PROVEN on the states.

    Raises `RebuildError`/`DeltaApplyError` if the delta does not transition
    state A into state B: failing loudly here is cheaper than building half
    a building in the live model.
    """

    program = delta_between(tree_a, tree_b, label_a=label_a, label_b=label_b)

    emit_ids: set[str] = set()
    retire_ids: set[str] = set()
    for op in program.ops:
        if op.kind in ("emit", "relocate"):
            emit_ids.update(op.add_source_ids)
        if op.kind in ("retire", "relocate"):
            retire_ids.update(op.remove_source_ids)

    leaves_b = list(iter_l1_leaves(tree_b))
    by_l1_id = _op_leaves_by_id(leaves_b)
    closure_ids = _close_over_refs(by_l1_id, frozenset(emit_ids))

    # The expanded program is checked as a whole — together with the closure's
    # addition. The `retire → relocate → emit` order is already set by
    # `_ORDER` in `rebuild.py`, and `apply_delta` walks the list as it lies,
    # so no re-sorting is needed here: `build_delta` handed back ops already
    # sorted, and the `refresh` pairs are appended afterwards and retire/emit
    # the very same token.
    closure_leaves = [
        leaf for leaf in by_l1_id.values()
        if leaf["source_element_id"] in closure_ids
    ]
    closed = DeltaProgram(
        ops=tuple(sorted(
            program.ops + _refresh_ops(closure_leaves),
            key=lambda op: (0 if op.kind == "retire"
                            else 1 if op.kind == "relocate" else 2,
                            op.path or (), op.hash or ""))),
        reused_count=program.reused_count,
        base_fidelity_hash=program.base_fidelity_hash,
        target_fidelity_hash=program.target_fidelity_hash,
    )
    assert_transition(closed, tree_a, tree_b)

    return DeltaRebuildPlan(
        program=closed,
        emit_source_ids=frozenset(emit_ids),
        closure_source_ids=closure_ids,
        retire_source_ids=tuple(sorted(retire_ids)),
        leaves_total_a=sum(1 for _ in iter_l1_leaves(tree_a)),
        leaves_total_b=len(leaves_b),
    )


def plan_report(plan: DeltaRebuildPlan) -> dict[str, Any]:
    """A JSON-compatible summary of the plan. Numbers, not adjectives."""

    return {
        "schema": REBUILD_PLAN_SCHEMA,
        "ok": True,
        "leaves_a": plan.leaves_total_a,
        "leaves_b": plan.leaves_total_b,
        # How many leaves of B a full materialization would have to build.
        "full_leaves": plan.leaves_total_b,
        # How many the delta builds: named by the delta + pulled in by closure.
        "delta_leaves": plan.materialize_total,
        "delta_named": len(plan.emit_source_ids),
        "delta_ref_closure": len(plan.closure_source_ids),
        "retire_leaves": len(plan.retire_source_ids),
        "reused_leaves": plan.program.reused_count,
        "identical": plan.is_empty,
    }


def plan_refusal(exc: BaseException) -> dict[str, Any]:
    """A refusal that can be seen. Never pretends to be an empty delta.

    An empty set with `ok:true` means "the buildings coincide"; with
    `ok:false` it means "the computation failed" — and the two must not be
    confused: that is exactly how "the delta is empty" once turns into a
    report about a broken instrument.
    """

    return {
        "schema": REBUILD_PLAN_SCHEMA,
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }
