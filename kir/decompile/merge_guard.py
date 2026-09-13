"""The guard between a delta and the document — the only wire `merge3` has
to the outside.

`merge3.py` can do a three-way semantic merge: a common ancestor, two
diverged versions, typed conflicts instead of a silent overwrite.  What it
does NOT know how to do is name WHERE, in this product, three versions of
one building come from.  That was exactly what was missing: 420 lines and 20
tests sat in the store carrying their own docstring note "opt-in gate for
future pipeline wiring".

The three versions come from wherever reassembly already has a NAMED HOLE
on record.  Delta reassembly (wave 6, wired in on 09.08.2026) says so about
itself:

    "the delta is correct only if the document already holds the base
    building; the offline compiler cannot check this" — `precondition_ru`

This is not caution, it is the one place where live reassembly can produce a
SILENTLY WRONG outcome: the operator read building (A), we computed delta
A→B, and meanwhile the operator was editing the document in Revit.  The
delta will build exactly the A→B difference and say nothing about the fact
that what's underneath it is no longer A.  The operator's edits do not
thereby "get lost with an error" — nobody simply notices them.

Three versions, and all three are ordinary decompiles on disk:

* **ancestor O** — `base_doc_stamp`, the decompile the delta was computed
  from;
* **our side** — `current_doc_stamp`, a FRESH decompile of the same
  document, i.e. what the operator has brought it to;
* **their side** — `doc_stamp`, the building we are about to build.

WHAT THIS LAYER DOES AND DOES NOT DO.  It is a GUARD, not a materializer.
`merge3` state is a multiset of canonical ops, and a program cannot be built
from it: a canonical op has neither identifiers nor references, and
`leaves_to_program` will not accept it.  So the delta A→B is still built the
same way as before, and merge answers exactly one question: IS IT SAFE to
build it.  Lying about this is not allowed — "we will merge the edits" would
sound much better than "we will refuse", and it would be untrue.

Hence the default policy is `refuse`.  A conflict is not a warning and not
advice: it is two edits to the same thing, one of which — ours — would
overwrite the other.  Only someone who has explicitly said they are ready
(`allow_conflicts`) has the right to silently ride through that — and even
then the conflicts still travel into the report in full.

AND, MOST IMPORTANTLY, WHAT THIS LAYER GIVES when there are no conflicts:
`precondition_ru` stops being a promise.  If the fresh decompile's state
matches the base state — the condition is VERIFIED, not merely claimed; if
it diverged with no conflicts — we say by exactly how much, and what the
delta will land on top of.
"""
from __future__ import annotations

from typing import Any

from kir.decompile.fold import TreeNode
from kir.decompile.merge3 import (
    POLICY_OURS,
    POLICY_REFUSE,
    Conflict,
    MergeError,
    merge3_trees,
)
from kir.decompile.rebuild import BuildingState

GUARD_SCHEMA = "kir-merge-guard/1"

#: How many conflicts to show in full.  The FULL count is always alongside:
#: a truncated list is about the length of the report, but a truncated count
#: would be a lie about the building.
_SAMPLE_LIMIT = 20

#: A canonical op is a long string; it is cut in the sample, and that is
#: exactly why `truncated: true` travels alongside it, so it is not mistaken
#: for the whole op.
_OP_CHARS = 160

VERDICT_CONFIRMED = "precondition_confirmed"
VERDICT_CLEAN = "diverged_clean"
VERDICT_CONFLICTING = "diverged_conflicting"

__all__ = [
    "GUARD_SCHEMA",
    "VERDICT_CLEAN",
    "VERDICT_CONFIRMED",
    "VERDICT_CONFLICTING",
    "guard_refusal",
    "guard_report",
]


def guard_refusal(exc: BaseException, **extra: Any) -> dict[str, Any]:
    """A refusal that is visible.  It never pretends there are "no conflicts"."""

    return {
        "schema": GUARD_SCHEMA,
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        **extra,
    }


def _sample(conflict: Conflict) -> dict[str, Any]:
    def _cut(value: str | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {
            "op": value[:_OP_CHARS],
            "truncated": len(value) > _OP_CHARS,
        }

    return {
        "kind": conflict.kind,
        "source_id": conflict.source_id,
        "base_count": conflict.base_count,
        "current_count": conflict.ours_count,
        "target_count": conflict.theirs_count,
        "current": _cut(conflict.ours),
        "target": _cut(conflict.theirs),
    }


def guard_report(
    base_tree: TreeNode,
    current_tree: TreeNode,
    target_tree: TreeNode,
    *,
    base_label: str = "base",
    current_label: str = "current",
    target_label: str = "target",
) -> dict[str, Any]:
    """Is it safe to build the base→target delta into a document that is
    currently `current`.

    Conflicts are computed with the `ours` policy, NOT `refuse`: under
    `refuse` the layer raises on the very first conflict and returns no
    list, while the guard must name ALL of them.  The decision to "refuse" is
    made by the caller based on `verdict` — this is only the measurement.
    """

    try:
        base_state = BuildingState.of_tree(base_tree)
        current_state = BuildingState.of_tree(current_tree)
        result = merge3_trees(
            base_tree, current_tree, target_tree, policy=POLICY_OURS)
    except (MergeError, KeyError, TypeError, ValueError) as exc:
        return guard_refusal(
            exc, base=base_label, current=current_label, target=target_label)

    by_kind: dict[str, int] = {}
    for conflict in result.conflicts:
        by_kind[conflict.kind] = by_kind.get(conflict.kind, 0) + 1

    # A match of states is the only honest "the base is what's in the
    # document".  Multisets of canonical ops are compared, i.e. the observed
    # building, not identifiers: a renumbered document must count as the
    # same one, otherwise the guard would cry wolf on every re-decompile.
    identical = current_state == base_state
    if identical:
        verdict = VERDICT_CONFIRMED
    elif result.conflicts:
        verdict = VERDICT_CONFLICTING
    else:
        verdict = VERDICT_CLEAN

    return {
        "schema": GUARD_SCHEMA,
        "ok": True,
        "base": base_label,
        "current": current_label,
        "target": target_label,
        "verdict": verdict,
        "policy": POLICY_REFUSE,
        "identical_to_base": identical,
        "conflicts_total": len(result.conflicts),
        "conflicts_by_kind": dict(sorted(by_kind.items())),
        "auto_merged": result.auto_merged,
        "conflicts": [_sample(c) for c in result.conflicts[:_SAMPLE_LIMIT]],
        "conflicts_shown": min(len(result.conflicts), _SAMPLE_LIMIT),
        "message_ru": _message_ru(verdict, len(result.conflicts),
                                  result.auto_merged),
    }


def _message_ru(verdict: str, conflicts: int, auto_merged: int) -> str:
    if verdict == VERDICT_CONFIRMED:
        return ("свежий разбор документа совпал с базой — условие дельты "
                "ПРОВЕРЕНО, а не заявлено")
    if verdict == VERDICT_CLEAN:
        return (f"документ ушёл от базы на {auto_merged} правок, но ни одна "
                "не спорит с дельтой — дельта встанет поверх них")
    return (f"документ ушёл от базы, и {conflicts} правок спорят с дельтой: "
            "построить её значит стереть чужую работу молча")
