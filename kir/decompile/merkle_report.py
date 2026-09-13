"""Report for the `merkle` layer over the FOLDED tree — the only wire out.

`merkle.py` computes the content address (`build_index`), repeats
(`dedup_report`), and the difference between two buildings (`diff_trees`).
What it does NOT know how to do — turn that into an artifact anyone can
read. That was exactly what was missing: 1312 lines and 41 tests sat in the
store carrying their own docstring note "nothing in the pipeline imports
this module".

This module computes NOTHING new. It serializes what has already been
computed into a JSON-compatible dict and lives between `merkle` and its two
consumers:

* `decompile/pipeline.py` — the live path: after `tree.json` it places
  `merkle.json` next to it (flag `KUKAI_IR_MERKLE`, OFF by default);
* `tools/kir_merkle.py` — the operator's instrument: the same report, plus
  the DIFFERENCE between two stored decompiles, with no Revit and no flag
  (an instrument, not behavior).

REPORT LAW: there is no silence. `ok:false` with an error type and text is
NOT the same thing as an empty list of repeats or an empty diff, and looking
at the file the two must be distinguishable at a glance. An empty `entries`
under `ok:true` means "the buildings matched"; under `ok:false` it means
"could not be computed", and the two must not be confused: this is exactly
how "deduplication found nothing" once turns into a report about a broken
instrument.

Completeness instead of truncation: the list of repeats is written IN FULL.
It is three orders of magnitude smaller than `tree.json` itself (measured
09.08.2026: 232 entries against a 30 MB tree for `snowdon_plumb_v4`), and a
truncated list is a quiet lie about how many repeats exist in the building.
"""
from __future__ import annotations

from typing import Any

from kir.decompile.fold import TreeNode
from kir.decompile.merkle import (
    MERKLE_VERSION,
    MerkleError,
    MerkleIndex,
    build_index,
    dedup_report,
    diff_trees,
)

REPORT_SCHEMA = "kir-merkle-report/1"
DIFF_SCHEMA = "kir-merkle-diff/1"

__all__ = [
    "DIFF_SCHEMA",
    "REPORT_SCHEMA",
    "building_report",
    "diff_report",
]


def _refusal(schema: str, exc: BaseException, **extra: Any) -> dict[str, Any]:
    """A refusal that is visible. It never pretends to be an empty result."""

    return {
        "schema": schema,
        "merkle_version": MERKLE_VERSION,
        "ok": False,
        "error": {"type": type(exc).__name__, "message": str(exc)},
        **extra,
    }


def _index(tree: TreeNode, label: str) -> MerkleIndex:
    return build_index(tree, label=label)


def building_report(tree: Any, *, label: str = "") -> dict[str, Any]:
    """The building's content address + the full list of repeated subtrees.

    `savings` for one entry is how many leaves would not have to be built
    again if the shape were drawn once and placed `occurrences` times.
    Entries that lie entirely inside other repeats (a bathroom inside a
    repeated apartment) are hidden by `dedup_report` by default — otherwise
    the savings would be counted twice.
    """

    try:
        index = _index(tree, label)
        repeats = dedup_report([index])
    except (MerkleError, KeyError, TypeError, ValueError) as exc:
        return _refusal(REPORT_SCHEMA, exc, label=label)

    entries = [
        {
            "hash": entry.hash,
            "kind": entry.kind,
            "label": entry.sample_label,
            "leaf_count": entry.leaf_count,
            "occurrences": entry.occurrence_count,
            "savings": entry.savings,
        }
        for entry in repeats
    ]
    return {
        "schema": REPORT_SCHEMA,
        "merkle_version": MERKLE_VERSION,
        "ok": True,
        "label": label,
        "root_hash": index.root_hash,
        "root_origin_mm": list(index.root_origin),
        "nodes": index.node_count,
        "distinct_nodes": index.distinct_count,
        # How many times more compact the DAG is than the tree. 1.0 means no repeats at all.
        "share_ratio": (round(index.node_count / index.distinct_count, 3)
                        if index.distinct_count else 0.0),
        "repeats": entries,
        "repeats_total": len(entries),
        "leaves_saved": sum(entry.savings for entry in repeats),
    }


def _side(index: MerkleIndex) -> dict[str, Any]:
    return {
        "label": index.label,
        "root_hash": index.root_hash,
        "nodes": index.node_count,
        "distinct_nodes": index.distinct_count,
    }


def diff_report(
    tree_a: Any,
    tree_b: Any,
    *,
    label_a: str = "a",
    label_b: str = "b",
) -> dict[str, Any]:
    """The difference between two folded buildings: what appeared, left, changed, or moved.

    `pruned` is how many subtrees matched by hash and were pruned entirely,
    without descending into them. That is exactly the payoff of a content
    address: the unchanged part of the building is not re-read element by
    element.
    """

    try:
        index_a = _index(tree_a, label_a)
        index_b = _index(tree_b, label_b)
        diff = diff_trees(index_a, index_b)
    except (MerkleError, KeyError, TypeError, ValueError) as exc:
        return _refusal(DIFF_SCHEMA, exc, a={"label": label_a},
                        b={"label": label_b})

    counts: dict[str, int] = {
        "added": 0, "removed": 0, "changed": 0, "moved": 0}
    for entry in diff.entries:
        counts[entry.status] = counts.get(entry.status, 0) + 1

    return {
        "schema": DIFF_SCHEMA,
        "merkle_version": MERKLE_VERSION,
        "ok": True,
        "a": _side(index_a),
        "b": _side(index_b),
        # A match of the ROOT hashes is the only honest "the buildings are equal".
        "identical": index_a.root_hash == index_b.root_hash,
        "pruned": diff.pruned,
        "unchanged_subtrees": len(diff.unchanged),
        "unchanged_leaves": sum(pair.leaf_count for pair in diff.unchanged),
        "counts": counts,
        "changed_source_ids_a": len(diff.changed_source_ids_a),
        "changed_source_ids_b": len(diff.changed_source_ids_b),
        "entries": [
            {
                "status": entry.status,
                "kind": entry.kind,
                "path_a": list(entry.path_a) if entry.path_a is not None else None,
                "path_b": list(entry.path_b) if entry.path_b is not None else None,
                "hash_a": entry.hash_a,
                "hash_b": entry.hash_b,
                "origin_a": list(entry.origin_a) if entry.origin_a else None,
                "origin_b": list(entry.origin_b) if entry.origin_b else None,
                "leaves_a": len(entry.leaf_source_ids_a),
                "leaves_b": len(entry.leaf_source_ids_b),
            }
            for entry in diff.entries
        ],
        "entries_total": len(diff.entries),
    }
