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
policy (never swallowed).  The add/add, delete/modify and modify/modify semantic
conflicts are recovered through a source-id bridge (the same id pairing wave-1
diff uses), when the trees are supplied.

A COUNT, however, cannot say WHICH element moved, and the bridge's domain used
to be strictly SMALLER than the merge's: it walked ancestor ids whose canonical
op had count 1, and outside that the address-free multiset answered alone with
nothing recorded.  Two authors adding one new source id with different bodies
merged into two physical elements; two authors deleting two canonically
indistinguishable elements merged into one deletion.  The bridge now spans the
UNION of the three trees' source ids and CHECKS every count the multiset merged
on the assumption of agreement — identity is read from the TREES and never
enters ``BuildingState``, which stays the address-free multiset the offline
T-APPLY proof stands on.

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
from kir import env  # noqa: E402  (dependency-free submodule — avoids an import cycle)
from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from kir.decompile.fold import TreeNode, canon_op, iter_l1_leaves
from kir.decompile.l1_schema import L1Node
from kir.decompile.rebuild import BuildingState

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

    return env.get("KIR_MERGE3", "").strip().lower() in {
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
) -> tuple[Counter[str], list[Conflict], int, set[str]]:
    """Return (auto-merged counter WITHOUT conflict effects, conflicts, auto,
    the canonical ops merged on the ASSUMPTION OF AGREEMENT).

    That fourth value is not bookkeeping.  ``da == db`` is read below as "both
    authors did the same thing", and a COUNT cannot say WHICH element moved: at
    base count 2, one author deleting element X and the other deleting element Y
    both show ``-1``, and this branch calls that one agreed deletion.  The op
    names go to the identity bridge so the assumption is CHECKED wherever the
    trees make identity visible, instead of standing silently.
    """

    keys = set(base) | set(ours) | set(theirs)
    merged: Counter[str] = Counter()
    conflicts: list[Conflict] = []
    agreed: set[str] = set()
    auto = 0
    for canonical in keys:
        o = base.get(canonical, 0)
        a = ours.get(canonical, 0)
        b = theirs.get(canonical, 0)
        da = a - o
        db = b - o
        if da == db:
            # both sides agree (including both unchanged) — ASSUMED from counts
            merged[canonical] = o + da
            agreed.add(canonical)
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
    return merged, conflicts, auto, agreed


def _identity_triples(
    base_by_id: Mapping[str, str],
    ours_by_id: Mapping[str, str],
    theirs_by_id: Mapping[str, str],
) -> dict[str, tuple[str | None, str | None, str | None]]:
    """``source_id -> (base_op, our_op, their_op)`` over the UNION of three maps.

    🔴 THIS DOMAIN IS THE WHOLE DEFECT CLASS, AND IT IS ONE LINE.  The bridge
    used to walk ``base_by_id`` alone and to skip every op whose base count was
    not 1.  Both of those are BASE-SIDE predicates, so the bridge's domain was
    strictly SMALLER than the merge's domain — and outside it the impersonal
    multiset answered alone, with nothing recorded.  Two carriers of that one
    silence were measured:

    * a source id ABSENT FROM THE ANCESTOR and introduced by both authors with
      different canonical ops (add/add) was invisible: the count merge read two
      unrelated additions and kept both bodies of one element, and even
      ``policy='refuse'`` had no conflict to refuse;
    * a canonical op with BASE COUNT 2 whose two authors deleted DIFFERENT
      elements was invisible: both sides show ``-1``, the count merge called it
      one agreed deletion, and one wall survived that both authors had removed.

    The union is therefore not a convenience — it is the repair.  Identity is
    read from the TREES and never enters ``BuildingState``: the merged state
    stays the address-free multiset the offline T-APPLY proof stands on.
    """

    ids = set(base_by_id) | set(ours_by_id) | set(theirs_by_id)
    return {
        source_id: (base_by_id.get(source_id),
                    ours_by_id.get(source_id),
                    theirs_by_id.get(source_id))
        for source_id in sorted(ids)
    }


def _identity_counts(
    triples: Mapping[str, tuple[str | None, str | None, str | None]],
) -> tuple[dict[str, int], tuple[Counter[str], Counter[str], Counter[str]]]:
    """Per canonical op: the count a 3-way merge over IDENTITIES yields, plus
    the identity view's OWN CENSUS of each of the three sides.

    The census is returned because a count computed from an identity view that
    does not see every leaf is not an answer about the building — it is an
    answer about what the view happened to hold (form 4: read the denominator
    before believing the number).  ``_require_total_identity`` puts it against
    the multiset counters and REFUSES on any disagreement.
    """

    base_ids: dict[str, set[str]] = {}
    ours_ids: dict[str, set[str]] = {}
    theirs_ids: dict[str, set[str]] = {}
    for source_id, (base_op, our_op, their_op) in triples.items():
        if base_op is not None:
            base_ids.setdefault(base_op, set()).add(source_id)
        if our_op is not None:
            ours_ids.setdefault(our_op, set()).add(source_id)
        if their_op is not None:
            theirs_ids.setdefault(their_op, set()).add(source_id)

    counts: dict[str, int] = {}
    for op in set(base_ids) | set(ours_ids) | set(theirs_ids):
        b = base_ids.get(op, set())
        a = ours_ids.get(op, set())
        t = theirs_ids.get(op, set())
        removed = (b - a) | (b - t)      # every identity either author dropped
        added = (a - b) | (t - b)        # every identity either author brought
        counts[op] = len((b - removed) | added)
    census = tuple(
        Counter({op: len(ids) for op, ids in side.items()})
        for side in (base_ids, ours_ids, theirs_ids))
    return counts, census  # type: ignore[return-value]


def _require_total_identity(
    census: tuple[Counter[str], Counter[str], Counter[str]],
    base_c: Counter[str],
    ours_c: Counter[str],
    theirs_c: Counter[str],
) -> None:
    """Refuse to correct a count from an identity view that does not see it all.

    The view IS total for a well-formed fold — ``_make_node`` refuses a node
    that would carry one ``source_element_id`` twice, so one leaf has exactly
    one id and ``len(_by_id(tree))`` equals the tree's leaf count.  That is a
    property of the input, not of this module, and a check that can only ever
    be true is not a check (form 18): this one CAN say no, and does, on a tree
    whose leaves share an id or on a state handed in beside a tree that
    describes another building.  Silently falling back would be worse than
    refusing — the correction below would then be computed on a denominator
    nobody read.
    """

    for name, seen, declared in (
            ("base", census[0], base_c),
            ("ours", census[1], ours_c),
            ("theirs", census[2], theirs_c)):
        if seen != declared:
            raise MergeSchemaError(
                f"{name}: the source-id view accounts for "
                f"{sum(seen.values())} leaves of {sum(declared.values())} in "
                f"the state — identity cannot arbitrate what it cannot see")


def _bridge_semantic_conflicts(
    triples: Mapping[str, tuple[str | None, str | None, str | None]],
    base_c: Counter[str],
    ours_c: Counter[str],
    theirs_c: Counter[str],
) -> list[Conflict]:
    """Recover add/add, delete/modify and modify/modify via the source-id bridge.

    IMPORTANT — the source-id bridge is only sound for id-STABLE elements.  The
    fold assigns source ids to canonical *slots* inside grid-arrays/stacks, so a
    structural refold can reshuffle which physical element carries an id; naively
    trusting "same id, different canon" would raise false delete/modify
    conflicts (an element that merely moved slot).  For an identity that EXISTS
    IN THE ANCESTOR we therefore gate the bridge on TWO conditions that a
    genuine semantic conflict must satisfy:

      1. the id's canonical op must be UNIQUE in the base (count == 1) — an
         ambiguous multi-count op is a slot, not an identity;
      2. the change must be visible in the multiset delta — the base op is net
         removed on the deleting/modifying side AND the modified op is net added.

    When the id-bridge cannot prove both, it stays silent and the plain COUNT
    conflict (if any) stands — fail-closed toward FEWER, provable conflicts, not
    fabricated ones (SPEC Р3: fall back to COUNT, never invent).

    🔴 AND AN IDENTITY THE ANCESTOR NEVER HAD IS NOT SUBJECT TO EITHER GATE.
    Both gates ask a question ABOUT THE BASE OP, and for a source id absent from
    the base there is no base op to ask about; the old loop, walking base ids
    only, therefore could not reach the case at all.  Two authors who introduce
    the SAME source id with DIFFERENT canonical ops have written two bodies for
    one element, and no refold ambiguity is involved — the ancestor is not a
    party to it.  That is ``CONFLICT_ADD_ADD``, declared in this module since
    wave 10 and, until this line existed, never once emitted.
    """

    conflicts: list[Conflict] = []
    for source_id, (base_op, our_op, their_op) in triples.items():
        if our_op == their_op:
            # Both authors say the SAME thing about this identity (including
            # both deleting it, and both leaving it alone).  Nothing to arbitrate.
            continue

        if base_op is None:
            if our_op is not None and their_op is not None:
                conflicts.append(Conflict(
                    kind=CONFLICT_ADD_ADD, canon_op=None,
                    source_id=source_id, base_count=0,
                    ours_count=1, theirs_count=1,
                    ours=our_op, theirs=their_op))
            # else: only ONE author introduced the id — a clean add, not a
            # conflict; the count merge already carries it.
            continue

        # (1) identity must be unambiguous: a unique canonical op in the base.
        if base_c.get(base_op, 0) != 1:
            continue
        ours_deleted = our_op is None or our_op != base_op
        theirs_deleted = their_op is None or their_op != base_op
        ours_modified = our_op is not None and our_op != base_op
        theirs_modified = their_op is not None and their_op != base_op

        def _net_removed(counter: Counter[str], base_op: str = base_op) -> bool:
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


def _identity_corrections(
    merged: Counter[str],
    triples: Mapping[str, tuple[str | None, str | None, str | None]],
    agreed: set[str],
    base_c: Counter[str],
    ours_c: Counter[str],
    theirs_c: Counter[str],
) -> int:
    """Ask identity to CHECK the counts the multiset merged as "agreed".

    ``_multiset_merge`` reads ``da == db`` as "both authors did the same thing".
    A count cannot say WHICH element moved, so at base count 2 two authors
    deleting two DIFFERENT elements both show ``-1`` and the merge keeps one
    wall that neither author left standing; the mirror case is two authors each
    adding a different NEW element of indistinguishable geometry, merged into
    one.  Where the trees make identity visible the assumption is decidable, so
    it is decided here instead of standing silent.

    Only the AGREED branch is revisited: a COUNT conflict is already recorded
    (not silent), and a one-sided change has no second author to disagree with.
    And only after ``_require_total_identity`` has proved the view sees every
    leaf: a count derived from a partial view would be form 4's false zero
    wearing a fix.

    THE ASSUMPTION THIS RESTS ON, NAMED SO IT CAN BE ATTACKED: that a
    ``source_element_id`` is an IDENTITY and not a slot label — measured for
    this tree shape as a bijection ``source_element_id`` <-> L0 ``element_id``
    on 52 trees of 52 (540 461 leaves, 0 duplicate addresses).  Where that
    stopped holding — a decompiler that renumbered the same physical element
    between two reads — this correction would inflate a count instead of
    fixing one, and it would do so on the AGREED branch, i.e. quietly.  The
    conflict scan above keeps its own base-count gate against exactly that
    doubt; this one does not, because a count of 2 is the very case it exists
    for, so the doubt is answered by the bijection or not at all.

    Returns the number of leaves the corrections moved (added to ``auto``).
    """

    counts, census = _identity_counts(triples)
    _require_total_identity(census, base_c, ours_c, theirs_c)
    moved = 0
    for canonical in sorted(agreed):
        # Total by the check above: every op of any of the three sides is here.
        was = merged.get(canonical, 0)
        now = counts[canonical]
        if now == was:
            continue
        merged[canonical] = now
        moved += abs(now - was)
    return moved


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

    merged, count_conflicts, auto, agreed = _multiset_merge(
        base_c, ours_c, theirs_c)

    # ONE identity view, TWO consumers.  The conflicts and the count check are
    # not two repairs: they are the two ends of one domain that used to stop
    # short of the merge's own.  Whatever narrows this table blinds both.
    #
    # WHAT STAYS SILENT BY CONSTRUCTION, said out loud rather than left to be
    # rediscovered: WITHOUT the three trees there is no identity to consult at
    # all, and this branch is skipped — a caller who hands in bare
    # ``BuildingState`` gets exactly the pre-wave answer, two indistinguishable
    # deletions included.  That is not a leftover; the address-free state is
    # the merge's contract, and identity is an EXTRA the trees may or may not
    # supply.
    semantic: list[Conflict] = []
    if bt is not None and ot is not None and tt is not None:
        triples = _identity_triples(_by_id(bt), _by_id(ot), _by_id(tt))
        semantic = _bridge_semantic_conflicts(
            triples, base_c, ours_c, theirs_c)
        auto += _identity_corrections(
            merged, triples, agreed, base_c, ours_c, theirs_c)

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
