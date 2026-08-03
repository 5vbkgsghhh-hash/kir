"""3-way semantic merge of two authors' edits to one building (wave 10).

Merge the edits of TWO authors of one building (BCF-style collaboration): a
common ancestor ``base``, two divergent versions ``ours`` and ``theirs`` ->
a merged state that combines BOTH authors' changes, with TYPED conflicts where
they touched the same thing incompatibly (never a silent overwrite).  Built on
the Merkle diff (wave 1) and the state/delta model (wave 6).

State is the canon_op multiset (wave 6's ``BuildingState``).  Standard 3-way
merge on multisets: per canonical op ``c`` with counts ``o/a/b`` in
base/ours/theirs, ``da = a-o`` and ``db = b-o``; if the two sides agree or only
one touched ``c`` it merges automatically; if both changed ``c`` differently it
is a CONFLICT — recorded, and its effect on the merged state follows an explicit
policy (never swallowed).  The delete/modify and modify/modify semantic
conflicts are recovered through a source-id bridge (the same id pairing wave-1
diff uses), when the trees are supplied.

Merge theorem (T-MERGE, offline-provable): ``merge(O,A,A)==A``,
``merge(O,O,B)==B``, ``merge(O,A,O)==A``, and with no conflicts the merge is
symmetric in ours/theirs.

Discipline (forks in THREE_WAY_MERGE_SPEC.md):

* **3-way, not 2-way** — the ancestor O tells who changed what RELATIVE to base,
  so non-conflicting edits of both sides merge and a conflict is only where BOTH
  touched the same thing differently.
* **Conflicts are explicit** — always recorded in ``conflicts``; the resolution
  policy (ours/theirs/union/refuse) decides only their effect on the state; a
  conflict is never silently overwritten.
* **Inert, additive, opt-in.**  Nothing is touched; ``merge_enabled()`` is
  default OFF.  Frozen L0 untouched.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from kukai.ir.decompile.fold import TreeNode, canon_op, iter_l1_leaves
from kukai.ir.decompile.l1_schema import L1Node
from kukai.ir.decompile.rebuild import BuildingState

_ZERO = (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class MergeError(ValueError):
    """Base for every typed 3-way-merge failure."""


class MergeConflictError(MergeError):
    """Strict (refuse) policy: an unresolved conflict remains."""


class MergeSchemaError(MergeError):
    """A malformed base/ours/theirs input."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def merge_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return os.getenv("KUKAI_IR_MERGE3", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Conflict types
# ---------------------------------------------------------------------------

CONFLICT_ADD_ADD = "add_add"
CONFLICT_DELETE_MODIFY = "delete_modify"
CONFLICT_MODIFY_MODIFY = "modify_modify"
CONFLICT_COUNT = "count"

POLICY_OURS = "ours"
POLICY_THEIRS = "theirs"
POLICY_UNION = "union"
POLICY_REFUSE = "refuse"
_POLICIES = frozenset({POLICY_OURS, POLICY_THEIRS, POLICY_UNION, POLICY_REFUSE})


@dataclass(frozen=True, slots=True)
class Conflict:
    kind: str
    canon_op: str | None
    source_id: str | None
    base_count: int
    ours_count: int
    theirs_count: int
    ours: str | None
    theirs: str | None


@dataclass(frozen=True, slots=True)
class MergeResult:
    state: BuildingState
    conflicts: tuple[Conflict, ...]
    auto_merged: int
    policy: str

    @property
    def clean(self) -> bool:
        return not self.conflicts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_state(value: object, name: str) -> BuildingState:
    if isinstance(value, BuildingState):
        return value
    if isinstance(value, Mapping) or hasattr(value, "get"):
        # A TreeNode is a Mapping; distinguish by the fold node key set.
        if isinstance(value, dict) and "node_id" in value and "children" in value:
            return BuildingState.of_tree(value)  # type: ignore[arg-type]
    if _looks_like_tree(value):
        return BuildingState.of_tree(value)  # type: ignore[arg-type]
    raise MergeSchemaError(f"{name} must be a BuildingState or a fold TreeNode")


def _looks_like_tree(value: object) -> bool:
    return (
        isinstance(value, dict)
        and "node_id" in value and "children" in value and "payload" in value)


# ---------------------------------------------------------------------------
# Core multiset 3-way merge
# ---------------------------------------------------------------------------


def _multiset_merge(
    base: Counter[str], ours: Counter[str], theirs: Counter[str],
) -> tuple[Counter[str], list[Conflict], int]:
    """Return (auto-merged counter WITHOUT conflict effects, conflicts, auto)."""

    keys = set(base) | set(ours) | set(theirs)
    merged: Counter[str] = Counter()
    conflicts: list[Conflict] = []
    auto = 0
    for canonical in keys:
        o = base.get(canonical, 0)
        a = ours.get(canonical, 0)
        b = theirs.get(canonical, 0)
        da = a - o
        db = b - o
        if da == db:
            # both sides agree (including both unchanged)
            merged[canonical] = o + da
            if da != 0:
                auto += abs(da)
        elif da == 0:
            merged[canonical] = o + db      # only theirs touched
            auto += abs(db)
        elif db == 0:
            merged[canonical] = o + da       # only ours touched
            auto += abs(da)
        else:
            # both changed this op's count differently -> conflict
            conflicts.append(Conflict(
                kind=CONFLICT_COUNT,
                canon_op=canonical,
                source_id=None,
                base_count=o, ours_count=a, theirs_count=b,
                ours=canonical, theirs=canonical,
            ))
            merged[canonical] = o           # placeholder; policy applies later
    return merged, conflicts, auto


def _bridge_semantic_conflicts(
    base_tree: TreeNode | None,
    ours_tree: TreeNode | None,
    theirs_tree: TreeNode | None,
    base_c: Counter[str],
    ours_c: Counter[str],
    theirs_c: Counter[str],
) -> list[Conflict]:
    """Recover delete/modify and modify/modify via the source-id bridge.

    IMPORTANT — the source-id bridge is only sound for id-STABLE elements.  The
    fold assigns source ids to canonical *slots* inside grid-arrays/stacks, so a
    structural refold can reshuffle which physical element carries an id; naively
    trusting "same id, different canon" would raise false delete/modify
    conflicts (an element that merely moved slot).  We therefore gate the bridge
    on TWO conditions that a genuine semantic conflict must satisfy:

      1. the id's canonical op must be UNIQUE in the base (count == 1) — an
         ambiguous multi-count op is a slot, not an identity;
      2. the change must be visible in the multiset delta — the base op is net
         removed on the deleting/modifying side AND the modified op is net added.

    When the id-bridge cannot prove both, it stays silent and the plain COUNT
    conflict (if any) stands — fail-closed toward FEWER, provable conflicts, not
    fabricated ones (SPEC Р3: fall back to COUNT, never invent).
    """

    if base_tree is None or ours_tree is None or theirs_tree is None:
        return []
    base_by_id = _by_id(base_tree)
    ours_by_id = _by_id(ours_tree)
    theirs_by_id = _by_id(theirs_tree)
    conflicts: list[Conflict] = []
    for source_id, base_op in sorted(base_by_id.items()):
        # (1) identity must be unambiguous: a unique canonical op in the base.
        if base_c.get(base_op, 0) != 1:
            continue
        our_op = ours_by_id.get(source_id)
        their_op = theirs_by_id.get(source_id)
        ours_deleted = our_op is None or our_op != base_op
        theirs_deleted = their_op is None or their_op != base_op
        ours_modified = our_op is not None and our_op != base_op
        theirs_modified = their_op is not None and their_op != base_op

        def _net_removed(counter: Counter[str]) -> bool:
            # base op genuinely gone from this side (count dropped to < base).
            return counter.get(base_op, 0) < base_c.get(base_op, 0)

        def _net_added(op: str | None, counter: Counter[str]) -> bool:
            return op is not None and counter.get(op, 0) > base_c.get(op, 0)

        # ours deletes the base op, theirs modifies it into a new op.
        if (not ours_modified and ours_deleted and theirs_modified
                and _net_removed(ours_c) and _net_added(their_op, theirs_c)):
            conflicts.append(Conflict(
                kind=CONFLICT_DELETE_MODIFY, canon_op=base_op,
                source_id=source_id, base_count=1, ours_count=0,
                theirs_count=1, ours=None, theirs=their_op))
        elif (not theirs_modified and theirs_deleted and ours_modified
                and _net_removed(theirs_c) and _net_added(our_op, ours_c)):
            conflicts.append(Conflict(
                kind=CONFLICT_DELETE_MODIFY, canon_op=base_op,
                source_id=source_id, base_count=1, ours_count=1,
                theirs_count=0, ours=our_op, theirs=None))
        elif (ours_modified and theirs_modified and our_op != their_op
                and _net_added(our_op, ours_c)
                and _net_added(their_op, theirs_c)):
            conflicts.append(Conflict(
                kind=CONFLICT_MODIFY_MODIFY, canon_op=base_op,
                source_id=source_id, base_count=1, ours_count=1,
                theirs_count=1, ours=our_op, theirs=their_op))
    conflicts.sort(key=lambda c: (c.kind, c.source_id or ""))
    return conflicts


def _by_id(tree: TreeNode) -> dict[str, str]:
    return {
        leaf["source_element_id"]: canon_op(leaf, _ZERO)
        for leaf in iter_l1_leaves(tree)
    }


def _apply_policy(
    merged: Counter[str],
    conflicts: list[Conflict],
    base: Counter[str],
    ours: Counter[str],
    theirs: Counter[str],
    policy: str,
) -> Counter[str]:
    """Resolve conflicts in ``merged`` per the chosen policy.

    COUNT conflicts set the op's count directly from the winning side.
    Semantic (delete/modify, modify/modify) conflicts, which the multiset merge
    auto-applied as two disjoint changes (both ``ours``/``theirs`` ops present),
    must additionally drop the LOSING side's op so a policy actually picks a
    winner rather than keeping both.
    """

    for conflict in conflicts:
        if conflict.kind == CONFLICT_COUNT and conflict.canon_op is not None:
            c = conflict.canon_op
            if policy == POLICY_OURS:
                merged[c] = ours.get(c, 0)
            elif policy == POLICY_THEIRS:
                merged[c] = theirs.get(c, 0)
            elif policy == POLICY_UNION:
                merged[c] = max(ours.get(c, 0), theirs.get(c, 0))
            # refuse: leave placeholder (base); caller raises before returning
            continue

        # Semantic conflict: our_op / their_op are the two sides' resulting ops
        # (either may be None for a delete).  The multiset merge already added
        # both; the policy drops the loser.
        our_op = conflict.ours
        their_op = conflict.theirs
        if policy == POLICY_UNION:
            continue  # keep both (whatever the merge produced)
        loser = their_op if policy == POLICY_OURS else our_op
        if loser is not None and merged.get(loser, 0) > 0:
            merged[loser] -= 1
            if merged[loser] == 0:
                del merged[loser]
    return merged


def merge3(
    base: object,
    ours: object,
    theirs: object,
    *,
    policy: str = POLICY_OURS,
    base_tree: TreeNode | None = None,
    ours_tree: TreeNode | None = None,
    theirs_tree: TreeNode | None = None,
) -> MergeResult:
    """3-way merge of ``ours`` and ``theirs`` over common ancestor ``base``.

    ``base/ours/theirs`` may be BuildingState or fold TreeNode.  Passing the
    trees (directly or via ``*_tree``) enables the source-id semantic-conflict
    bridge (delete/modify, modify/modify).
    """

    if policy not in _POLICIES:
        raise MergeSchemaError(f"unknown policy {policy!r}")

    base_state = _as_state(base, "base")
    ours_state = _as_state(ours, "ours")
    theirs_state = _as_state(theirs, "theirs")

    # Trees for the bridge: explicit args, else infer from inputs when they
    # are trees.
    bt = base_tree if base_tree is not None else (
        base if _looks_like_tree(base) else None)
    ot = ours_tree if ours_tree is not None else (
        ours if _looks_like_tree(ours) else None)
    tt = theirs_tree if theirs_tree is not None else (
        theirs if _looks_like_tree(theirs) else None)

    base_c = base_state.as_counter()
    ours_c = ours_state.as_counter()
    theirs_c = theirs_state.as_counter()

    merged, count_conflicts, auto = _multiset_merge(base_c, ours_c, theirs_c)
    semantic = _bridge_semantic_conflicts(
        bt, ot, tt, base_c, ours_c, theirs_c)  # type: ignore[arg-type]

    resolved = _apply_policy(
        merged, count_conflicts + semantic, base_c, ours_c, theirs_c, policy)

    all_conflicts = tuple(sorted(
        count_conflicts + semantic,
        key=lambda c: (c.kind, c.canon_op or "", c.source_id or "")))

    if all_conflicts and policy == POLICY_REFUSE:
        raise MergeConflictError(
            f"{len(all_conflicts)} unresolved conflict(s) under refuse policy")

    return MergeResult(
        state=BuildingState.from_counter(resolved),
        conflicts=all_conflicts,
        auto_merged=auto,
        policy=policy,
    )


def merge3_trees(
    base_tree: TreeNode,
    ours_tree: TreeNode,
    theirs_tree: TreeNode,
    *,
    policy: str = POLICY_OURS,
) -> MergeResult:
    """3-way merge over trees, with the semantic-conflict bridge enabled."""

    return merge3(
        BuildingState.of_tree(base_tree),
        BuildingState.of_tree(ours_tree),
        BuildingState.of_tree(theirs_tree),
        policy=policy,
        base_tree=base_tree, ours_tree=ours_tree, theirs_tree=theirs_tree)


def conflicts_of(
    base: object, ours: object, theirs: object,
    *,
    base_tree: TreeNode | None = None,
    ours_tree: TreeNode | None = None,
    theirs_tree: TreeNode | None = None,
) -> tuple[Conflict, ...]:
    """Detect conflicts without committing to a resolution."""

    return merge3(
        base, ours, theirs, policy=POLICY_OURS,
        base_tree=base_tree, ours_tree=ours_tree,
        theirs_tree=theirs_tree).conflicts


__all__ = [
    "CONFLICT_ADD_ADD",
    "CONFLICT_COUNT",
    "CONFLICT_DELETE_MODIFY",
    "CONFLICT_MODIFY_MODIFY",
    "Conflict",
    "MergeConflictError",
    "MergeError",
    "MergeResult",
    "MergeSchemaError",
    "POLICY_OURS",
    "POLICY_REFUSE",
    "POLICY_THEIRS",
    "POLICY_UNION",
    "conflicts_of",
    "merge3",
    "merge3_trees",
    "merge_enabled",
]
