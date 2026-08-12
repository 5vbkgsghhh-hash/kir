"""Content-addressed Merkle-DAG layer over the folded DECOMPILE tree.

``fold.py`` already owns the *value* canonicalization of subtree content:
``_canonical_l1`` / ``canon_op`` / ``_canonical_value`` strip volatile ids,
round to ``CANON_MM``, and localize coordinates against an origin.  This
module adds exactly one thing on top: **DAG structure** — a node references
its children by content hash plus a placement offset instead of by body.
From that single addition the layer derives, systemically:

* a **store** where a shared subtree (typical floor / apartment / bathroom)
  is held once, within one building and across buildings;
* a **dedup report** — "subtree X occurs N times";
* a **diff** of two buildings with early cutoff on matching hashes;
* an **incremental rebuild plan** whose reuse/emit split is provably
  equivalent to a full rebuild of the target tree (property P7).

Design decisions, trade-offs and the equivalence-class differences against
``fold.canon_hash`` are documented in ``MERKLE_SPEC.md`` at the worktree
root.  The headline points:

* Every node is hashed against its **own canonical origin** — ``node_origin``:
  the component-wise minimum over the located points of the subtree, with z
  taken from genuinely 3D points only — so translation invariance holds at
  *every* level, not only for whole floors.  It is deliberately NOT
  ``facts.bbox_min_mm``: fold zero-fills the z of 2D param points, which would
  pin every elevated floor's origin to world zero (measured 2026-08-09: 20 364
  such nodes on ``k2_ar_rd_v6``, 2 404 on ``sob62_fas_r23_v17``).  This
  paragraph named ``facts.bbox_min_mm`` until 2026-08-10 and was therefore the
  exact opposite of what ``node_origin``'s own docstring says; the line is held
  by ``test_node_origin_is_not_bbox_min_where_they_must_differ``.
* A parent edge carries
  ``offset = child_origin - parent_origin``; both terms are multiples of
  ``CANON_MM`` so the subtraction is float-exact.  Moving a child therefore
  changes the parent hash — equal root hashes still mean equal buildings
  (Р-3: the layer changes *how*, never *what*).
* Grid-cell instance data (``macro.cell`` / ``macro.cells`` /
  ``macro.base_z_mm``) is placement derived from member positions, not form;
  it is excluded from the content hash (the parent edge offset carries the
  same information losslessly).
* The store is an anonymous **shape library** (canonical content only — the
  volatile-field strip removes every element id).  Binding shapes to live
  ``TreeNode`` payloads is the per-building :class:`MerkleIndex`'s job; the
  rebuild plan takes exact L1 payloads from the index, never from the store.

LAW (risk register Р-3): a store/cache changes *how* an answer is produced,
never *what* it is.  Fail-closed: a hash collision, an unknown hash, or a
corrupt persisted node raises a typed :class:`MerkleError` — no silent merge.

Determinism: no wall clock, no randomness, no dict-order dependence; every
traversal, report and serialization is explicitly sorted.  Inert by default:
nothing in the pipeline imports this module; ``merkle_enabled()`` (env
``KUKAI_IR_MERKLE``, default off) gates any future wiring.
"""
from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from kukai.ir.decompile.fold import (
    TreeNode,
    canon_op,
    iter_l1_leaves,
)
from kukai.ir.decompile.fold import (  # canonicalization authority — reused, not reinvented
    _COORDINATE_FIELDS,
    _canonical_l1,
    _canonical_value,
    _round_mm,
)
from kukai.ir.decompile.l1_schema import L1Node

# Bump when the meaning of a hash changes (content derivation, edge shape,
# or the excluded-macro set).  Same discipline as COMPILE_CACHE_WRAPPER_VERSION.
MERKLE_VERSION = "merkle/2"

# fold._canonical_tree already excludes {levels, diffs, template_node_id}
# (membership metadata, not the repeated template).  The merkle content hash
# additionally excludes grid-cell instance data and the stack's absolute base
# elevation: they are *placement* derived from member positions.  The parent
# edge offset carries the same information, so nothing is lost (Р-3).
_MACRO_PLACEMENT_FIELDS = frozenset({
    "levels", "diffs", "template_node_id",  # fold's own exclusions
    "cell", "cells", "base_z_mm",            # placement-derived (merkle-only)
})

_TREE_NODE_FIELDS = frozenset({
    "node_id", "kind", "label", "children", "payload", "members", "macro",
    "facts", "verdict",
})

_ZERO_ORIGIN = (0.0, 0.0, 0.0)

Vec3 = tuple[float, float, float]


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class MerkleError(ValueError):
    """Base for every typed merkle-layer failure."""


class MerkleCollisionError(MerkleError):
    """One hash maps to two different canonical contents."""


class MerkleNodeMissingError(MerkleError, KeyError):
    """A referenced hash is absent from the store."""

    def __str__(self) -> str:  # KeyError quotes its arg; keep the message
        return MerkleError.__str__(self)


class MerkleIntegrityError(MerkleError):
    """A node or a persisted entry violates the structural contract."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def merkle_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return os.getenv("KUKAI_IR_MERKLE", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------


def _require_tree_node(node: Any) -> TreeNode:
    if not isinstance(node, Mapping) or not _TREE_NODE_FIELDS <= set(node):
        raise MerkleIntegrityError(
            "merkle layer requires a fold TreeNode with its full field set")
    return node  # type: ignore[return-value]


def _norm_zero(value: float) -> float:
    return 0.0 if value == 0.0 else value


def _located_points(
    value: Any, field_name: str | None = None,
) -> Iterator[tuple[float, float, float | None]]:
    """Yield (x, y, z-or-None) for every coordinate vector in params.

    Unlike ``fold._points_from_params`` this does NOT zero-fill the third
    component of a 2-vector: many op params carry level-relative 2D points
    (``p0_mm: [x, y]``, ``xy: [x, y]``) whose fabricated ``z = 0`` must not
    drag a whole floor's origin down to world zero.  x/y come from every
    located vector; z only from genuinely 3D ones.
    """

    if field_name in _COORDINATE_FIELDS and isinstance(value, list):
        if (len(value) in (2, 3)
                and all(isinstance(item, (int, float))
                        and not isinstance(item, bool) for item in value)):
            z = float(value[2]) if len(value) == 3 else None
            yield (float(value[0]), float(value[1]), z)
            return
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _located_points(item, key)
    elif isinstance(value, list):
        for item in value:
            yield from _located_points(item, field_name)


def _leaf_points(leaf: L1Node) -> Iterator[tuple[float, float, float | None]]:
    anchor = leaf["anchor_mm"]
    if anchor is not None:
        yield (float(anchor[0]), float(anchor[1]), float(anchor[2]))
    if leaf["kind"] == "atom":
        for corner in (leaf["bbox_min_mm"], leaf["bbox_max_mm"]):
            if corner is not None:
                yield (float(corner[0]), float(corner[1]), float(corner[2]))
    else:
        yield from _located_points(leaf["params"])


def node_origin(node: TreeNode) -> Vec3:
    """Return the node's canonical self-origin.

    Component-wise minimum over every located point of the subtree's exact
    L1 leaves — x/y from all coordinate vectors, z from genuinely 3D ones
    only (``facts.bbox_min_mm`` is unsuitable: fold zero-fills the z of 2D
    param points, which would pin every elevated floor's origin to world
    zero).  The origin is a deterministic, translation-covariant function of
    content, so content localized against it is translation invariant at
    every level.  Axes with no located data default to ``0.0``.
    """

    _require_tree_node(node)
    min_x: float | None = None
    min_y: float | None = None
    min_z: float | None = None
    for leaf in iter_l1_leaves(node):
        for x, y, z in _leaf_points(leaf):
            min_x = x if min_x is None else min(min_x, x)
            min_y = y if min_y is None else min(min_y, y)
            if z is not None:
                min_z = z if min_z is None else min(min_z, z)
    return (
        _round_mm(min_x) if min_x is not None else 0.0,
        _round_mm(min_y) if min_y is not None else 0.0,
        _round_mm(min_z) if min_z is not None else 0.0,
    )


@dataclass(frozen=True, slots=True)
class MerkleEdge:
    """A parent→child reference: content by hash, placement by offset."""

    child_hash: str
    offset_mm: Vec3


@dataclass(frozen=True, slots=True)
class MerkleNode:
    """One stored canonical node: pure shape, zero identity."""

    hash: str
    kind: str
    content_json: str
    edges: tuple[MerkleEdge, ...]
    leaf_count: int


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True,
        separators=(",", ":"))


def _node_content(node: TreeNode, origin: Vec3) -> dict[str, Any]:
    """Own-level canonical content (children excluded — they live in edges)."""

    content: dict[str, Any] = {"kind": node["kind"]}
    payload = node["payload"]
    if payload is not None:
        content["payload"] = _canonical_l1(payload, origin)
    if node["members"]:
        content["members"] = sorted(
            canon_op(member, origin) for member in node["members"])
    macro = node["macro"]
    if macro is not None:
        filtered = {
            key: value for key, value in macro.items()
            if key not in _MACRO_PLACEMENT_FIELDS
        }
        content["macro"] = _canonical_value(filtered, origin)
    return content


def _hash_parts(content_json: str, edges: Sequence[MerkleEdge]) -> str:
    envelope = {
        "v": MERKLE_VERSION,
        "content": content_json,
        "edges": [
            [edge.child_hash, list(edge.offset_mm)] for edge in edges
        ],
    }
    return hashlib.sha256(
        _canonical_json(envelope).encode("utf-8")).hexdigest()


def _build_merkle_node(
    node: TreeNode,
    path: tuple[int, ...],
    visit: Any,
) -> tuple[str, Vec3, MerkleNode]:
    """Post-order construction; ``visit`` sees children before parents."""

    _require_tree_node(node)
    origin = node_origin(node)
    edges: list[MerkleEdge] = []
    leaf_count = (0 if node["payload"] is None else 1) + len(node["members"])
    for index, child in enumerate(node["children"]):
        child_hash, child_origin, child_node = _build_merkle_node(
            child, path + (index,), visit)
        offset = (
            _norm_zero(child_origin[0] - origin[0]),
            _norm_zero(child_origin[1] - origin[1]),
            _norm_zero(child_origin[2] - origin[2]),
        )
        edges.append(MerkleEdge(child_hash=child_hash, offset_mm=offset))
        leaf_count += child_node.leaf_count
    edges.sort(key=lambda edge: (edge.child_hash, edge.offset_mm))
    content_json = _canonical_json(_node_content(node, origin))
    node_hash = _hash_parts(content_json, edges)
    merkle_node = MerkleNode(
        hash=node_hash,
        kind=str(node["kind"]),
        content_json=content_json,
        edges=tuple(edges),
        leaf_count=leaf_count,
    )
    if visit is not None:
        visit(node, path, node_hash, origin, merkle_node)
    return node_hash, origin, merkle_node


def merkle_hash(node: TreeNode) -> str:
    """Return the content address of one folded subtree (form, not place)."""

    node_hash, _origin, _merkle = _build_merkle_node(node, (), None)
    return node_hash


# ---------------------------------------------------------------------------
# DAG store
# ---------------------------------------------------------------------------


class MerkleStore:
    """In-memory hash→node DAG store with optional deterministic JSONL dump.

    Shared subtrees are stored once; edges must always resolve (children are
    inserted before parents by construction, and persisted loads verify
    closure).  Every integrity violation raises a typed error — fail-closed.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, MerkleNode] = {}

    # -- low-level ----------------------------------------------------------
    def _put_merkle_node(self, node: MerkleNode) -> str:
        for edge in node.edges:
            if edge.child_hash not in self._nodes:
                raise MerkleIntegrityError(
                    f"edge target {edge.child_hash!r} is not in the store; "
                    "children must be inserted before parents")
        existing = self._nodes.get(node.hash)
        if existing is not None:
            if existing != node:
                raise MerkleCollisionError(
                    f"hash {node.hash!r} already maps to different content")
            return node.hash
        self._nodes[node.hash] = node
        return node.hash

    # -- public API ---------------------------------------------------------
    def put(self, node: TreeNode) -> str:
        """Insert a folded subtree recursively; return its root hash."""

        def visit(_tree: TreeNode, _path: tuple[int, ...], _h: str,
                  _origin: Vec3, merkle_node: MerkleNode) -> None:
            self._put_merkle_node(merkle_node)

        node_hash, _origin, _merkle = _build_merkle_node(node, (), visit)
        return node_hash

    def get(self, node_hash: str) -> MerkleNode:
        try:
            return self._nodes[node_hash]
        except KeyError:
            raise MerkleNodeMissingError(
                f"hash {node_hash!r} is not in the store") from None

    def has(self, node_hash: str) -> bool:
        return node_hash in self._nodes

    def __contains__(self, node_hash: object) -> bool:
        return node_hash in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)

    def hashes(self) -> tuple[str, ...]:
        return tuple(sorted(self._nodes))

    def reconstruct(self, node_hash: str) -> dict[str, Any]:
        """Return the canonical nested form of a stored subtree (audit view)."""

        node = self.get(node_hash)
        return {
            "hash": node.hash,
            "kind": node.kind,
            "content": json.loads(node.content_json),
            "leaf_count": node.leaf_count,
            "children": [
                {
                    "offset_mm": list(edge.offset_mm),
                    "node": self.reconstruct(edge.child_hash),
                }
                for edge in node.edges
            ],
        }

    # -- persistence --------------------------------------------------------
    def dump_jsonl(self, path: str | os.PathLike[str]) -> None:
        """Write every node, sorted by hash, as reproducible JSONL bytes."""

        lines = []
        for node_hash in sorted(self._nodes):
            node = self._nodes[node_hash]
            lines.append(_canonical_json({
                "hash": node.hash,
                "kind": node.kind,
                "content": json.loads(node.content_json),
                "edges": [
                    [edge.child_hash, list(edge.offset_mm)]
                    for edge in node.edges
                ],
                "leaf_count": node.leaf_count,
            }))
        Path(path).write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def load_jsonl(self, path: str | os.PathLike[str]) -> int:
        """Merge a dumped store; verify every hash and edge closure.

        Every entry's hash is *recomputed* from its content and edges — a
        tampered or truncated file fails with :class:`MerkleIntegrityError`
        instead of poisoning the store.  Returns the number of new nodes.
        """

        staged: dict[str, MerkleNode] = {}
        text = Path(path).read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise MerkleIntegrityError(
                    f"{path}:{line_no}: not valid JSON: {exc}") from exc
            if not isinstance(row, Mapping):
                raise MerkleIntegrityError(
                    f"{path}:{line_no}: entry must be an object")
            try:
                declared = row["hash"]
                kind = row["kind"]
                content = row["content"]
                raw_edges = row["edges"]
                leaf_count = row["leaf_count"]
            except KeyError as exc:
                raise MerkleIntegrityError(
                    f"{path}:{line_no}: missing field {exc}") from None
            if (not isinstance(raw_edges, list)
                    or not isinstance(leaf_count, int)
                    or not isinstance(kind, str)
                    or not isinstance(declared, str)):
                raise MerkleIntegrityError(
                    f"{path}:{line_no}: malformed entry field types")
            # kind/leaf_count are redundant metadata NOT covered by the hash;
            # cross-check them against the hash-covered content so a tampered
            # sidecar field cannot ride in on a valid hash.
            if not isinstance(content, Mapping) or content.get("kind") != kind:
                raise MerkleIntegrityError(
                    f"{path}:{line_no}: entry kind {kind!r} does not match "
                    "its hash-covered content")
            edges = []
            for raw in raw_edges:
                if (not isinstance(raw, list) or len(raw) != 2
                        or not isinstance(raw[0], str)
                        or not isinstance(raw[1], list) or len(raw[1]) != 3):
                    raise MerkleIntegrityError(
                        f"{path}:{line_no}: malformed edge")
                edges.append(MerkleEdge(
                    child_hash=raw[0],
                    offset_mm=(
                        float(raw[1][0]), float(raw[1][1]), float(raw[1][2])),
                ))
            content_json = _canonical_json(content)
            recomputed = _hash_parts(content_json, edges)
            if recomputed != declared:
                raise MerkleIntegrityError(
                    f"{path}:{line_no}: declared hash {declared!r} does not "
                    f"match recomputed {recomputed!r} (corrupt entry)")
            candidate = MerkleNode(
                hash=declared,
                kind=kind,
                content_json=content_json,
                edges=tuple(edges),
                leaf_count=leaf_count,
            )
            previous = staged.get(declared)
            if previous is not None and previous != candidate:
                raise MerkleCollisionError(
                    f"{path}:{line_no}: hash {declared!r} appears twice with "
                    "different content")
            staged[declared] = candidate

        known = set(self._nodes) | set(staged)
        for node in staged.values():
            for edge in node.edges:
                if edge.child_hash not in known:
                    raise MerkleIntegrityError(
                        f"{path}: edge target {edge.child_hash!r} of node "
                        f"{node.hash!r} is not present (broken closure)")

        added = 0
        # Commit children before parents so _put_merkle_node's closure check
        # holds during the merge as well.  A crafted file whose entries can
        # never topologically settle (a "cycle" — impossible for honestly
        # recomputed hashes, but the file is untrusted input) fails closed
        # instead of spinning.
        pending = deque(sorted(staged))
        stalled = 0
        while pending:
            node_hash = pending.popleft()
            node = staged[node_hash]
            if any(edge.child_hash not in self._nodes for edge in node.edges):
                pending.append(node_hash)
                stalled += 1
                if stalled > len(pending):
                    raise MerkleIntegrityError(
                        f"{path}: entries contain an unresolvable reference "
                        "cycle")
                continue
            stalled = 0
            # leaf_count is derived data outside the hash: recompute it from
            # the (hash-covered) content and the children's verified counts.
            content = json.loads(node.content_json)
            own = (1 if "payload" in content else 0) + len(
                content.get("members", ()))
            expected = own + sum(
                self._nodes[edge.child_hash].leaf_count
                for edge in node.edges)
            if node.leaf_count != expected:
                raise MerkleIntegrityError(
                    f"{path}: node {node.hash!r} declares leaf_count "
                    f"{node.leaf_count}, recomputed {expected}")
            if node_hash not in self._nodes:
                added += 1
            self._put_merkle_node(node)
        return added


# ---------------------------------------------------------------------------
# Per-building index (binds shapes to live TreeNodes)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class Occurrence:
    """One placement of a shape inside one building's folded tree."""

    path: tuple[int, ...]
    node_id: str
    hash: str
    origin_mm: Vec3
    tree_node: TreeNode


class MerkleIndex:
    """Deterministic hash→occurrences view of one folded building."""

    def __init__(
        self,
        *,
        label: str,
        root_hash: str,
        root_origin: Vec3,
        occurrences: Mapping[str, tuple[Occurrence, ...]],
        by_path: Mapping[tuple[int, ...], Occurrence],
    ) -> None:
        self.label = label
        self.root_hash = root_hash
        self.root_origin = root_origin
        self.occurrences: dict[str, tuple[Occurrence, ...]] = dict(occurrences)
        self.by_path: dict[tuple[int, ...], Occurrence] = dict(by_path)

    @property
    def root(self) -> Occurrence:
        return self.by_path[()]

    def occurrences_of(self, node_hash: str) -> tuple[Occurrence, ...]:
        return self.occurrences.get(node_hash, ())

    @property
    def node_count(self) -> int:
        return len(self.by_path)

    @property
    def distinct_count(self) -> int:
        return len(self.occurrences)


def build_index(
    tree: TreeNode,
    *,
    label: str = "",
    store: MerkleStore | None = None,
) -> MerkleIndex:
    """Hash every subtree in one walk; optionally populate ``store``."""

    occurrences: dict[str, list[Occurrence]] = defaultdict(list)
    by_path: dict[tuple[int, ...], Occurrence] = {}

    def visit(node: TreeNode, path: tuple[int, ...], node_hash: str,
              origin: Vec3, merkle_node: MerkleNode) -> None:
        occurrence = Occurrence(
            path=path,
            node_id=str(node["node_id"]),
            hash=node_hash,
            origin_mm=origin,
            tree_node=node,
        )
        occurrences[node_hash].append(occurrence)
        by_path[path] = occurrence
        if store is not None:
            store._put_merkle_node(merkle_node)

    root_hash, root_origin, _merkle = _build_merkle_node(tree, (), visit)
    frozen = {
        node_hash: tuple(sorted(items, key=lambda occ: occ.path))
        for node_hash, items in occurrences.items()
    }
    return MerkleIndex(
        label=label,
        root_hash=root_hash,
        root_origin=root_origin,
        occurrences=frozen,
        by_path=by_path,
    )


# ---------------------------------------------------------------------------
# Dedup report (component library)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DedupEntry:
    """One repeated shape: draw once, place ``occurrence_count`` times."""

    hash: str
    kind: str
    leaf_count: int
    occurrence_count: int
    by_building: tuple[tuple[str, int], ...]
    sample_label: str
    savings: int
    dominated: bool


def dedup_report(
    indexes: Sequence[MerkleIndex],
    *,
    min_occurrences: int = 2,
    min_leaves: int = 2,
    include_dominated: bool = False,
) -> tuple[DedupEntry, ...]:
    """Report repeated subtrees within and across buildings.

    An entry is *dominated* when every one of its occurrences lies strictly
    inside occurrences of other reported repeats — e.g. the bathroom that
    only ever appears inside the already-reported repeated apartment.
    Dominated entries are hidden by default so the report surfaces maximal
    repeats; ``include_dominated=True`` returns everything flagged.
    """

    if min_occurrences < 2:
        raise MerkleError("min_occurrences must be at least 2")

    labels: list[str] = []
    for position, index in enumerate(indexes):
        labels.append(index.label or f"building_{position}")

    sites: dict[str, list[tuple[int, Occurrence]]] = defaultdict(list)
    for position, index in enumerate(indexes):
        for node_hash, occs in index.occurrences.items():
            for occurrence in occs:
                sites[node_hash].append((position, occurrence))

    candidates: dict[str, list[tuple[int, Occurrence]]] = {}
    for node_hash, placed in sites.items():
        if len(placed) < min_occurrences:
            continue
        sample = placed[0][1]
        merkle_leaves = sum(
            1 for _ in iter_l1_leaves(sample.tree_node))
        if merkle_leaves < min_leaves:
            continue
        candidates[node_hash] = sorted(
            placed, key=lambda item: (item[0], item[1].path))

    # Dominance: every occurrence strictly inside another entry's occurrence.
    covered: dict[str, set[tuple[int, tuple[int, ...]]]] = {
        node_hash: {(pos, occ.path) for pos, occ in placed}
        for node_hash, placed in candidates.items()
    }

    def _dominated(node_hash: str) -> bool:
        own = candidates[node_hash]
        for position, occurrence in own:
            inside_other = False
            for other_hash, other_sites in covered.items():
                if other_hash == node_hash:
                    continue
                for other_position, other_path in other_sites:
                    if other_position != position:
                        continue
                    if (len(other_path) < len(occurrence.path)
                            and occurrence.path[:len(other_path)]
                            == other_path):
                        inside_other = True
                        break
                if inside_other:
                    break
            if not inside_other:
                return False
        return True

    entries: list[DedupEntry] = []
    for node_hash in sorted(candidates):
        placed = candidates[node_hash]
        sample = placed[0][1]
        leaf_count = sum(1 for _ in iter_l1_leaves(sample.tree_node))
        per_building: dict[str, int] = defaultdict(int)
        for position, _occurrence in placed:
            per_building[labels[position]] += 1
        dominated = _dominated(node_hash)
        if dominated and not include_dominated:
            continue
        entries.append(DedupEntry(
            hash=node_hash,
            kind=str(sample.tree_node["kind"]),
            leaf_count=leaf_count,
            occurrence_count=len(placed),
            by_building=tuple(sorted(per_building.items())),
            sample_label=str(sample.tree_node["label"]),
            savings=leaf_count * (len(placed) - 1),
            dominated=dominated,
        ))
    entries.sort(key=lambda entry: (-entry.savings, entry.hash))
    return tuple(entries)


# ---------------------------------------------------------------------------
# Diff (hash-guided, early cutoff)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UnchangedPair:
    """A maximal shared subtree: same hash AND same absolute placement."""

    hash: str
    path_a: tuple[int, ...]
    path_b: tuple[int, ...]
    origin_mm: Vec3
    leaf_count: int


@dataclass(frozen=True, slots=True)
class DiffEntry:
    """One changed/added/removed/moved subtree (typed, deterministic)."""

    status: str  # "added" | "removed" | "changed" | "moved"
    kind: str
    path_a: tuple[int, ...] | None
    path_b: tuple[int, ...] | None
    node_id_a: str | None
    node_id_b: str | None
    hash_a: str | None
    hash_b: str | None
    origin_a: Vec3 | None
    origin_b: Vec3 | None
    # Leaf rollups.  For added/removed/moved these cover the whole subtree.
    # For a changed pair they cover only the pair's OWN level (payload +
    # members); differing children produce their own entries.
    leaf_source_ids_a: tuple[str, ...]
    leaf_source_ids_b: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MerkleDiff:
    """Minimal set of differing subtrees between two folded buildings."""

    entries: tuple[DiffEntry, ...]
    unchanged: tuple[UnchangedPair, ...]
    pruned: int

    @property
    def changed_source_ids_a(self) -> frozenset[str]:
        return frozenset(
            source_id for entry in self.entries
            for source_id in entry.leaf_source_ids_a)

    @property
    def changed_source_ids_b(self) -> frozenset[str]:
        return frozenset(
            source_id for entry in self.entries
            for source_id in entry.leaf_source_ids_b)

    @property
    def is_empty(self) -> bool:
        return not self.entries


def _subtree_source_ids(node: TreeNode) -> tuple[str, ...]:
    return tuple(sorted(
        leaf["source_element_id"] for leaf in iter_l1_leaves(node)))


def _own_leaves(node: TreeNode) -> list[L1Node]:
    leaves: list[L1Node] = []
    if node["payload"] is not None:
        leaves.append(node["payload"])
    leaves.extend(node["members"])
    return leaves


def _own_level_delta(
    node_a: TreeNode, node_b: TreeNode,
) -> tuple[tuple[str, ...], tuple[str, ...], list[tuple[L1Node, L1Node]]]:
    """Own-level leaf diff at ABSOLUTE coordinates.

    Returns (removed_a_ids, added_b_ids, matched_pairs) where matched pairs
    are canonically byte-identical at origin (0,0,0) — reusable in place.
    """

    buckets_a: dict[str, list[L1Node]] = defaultdict(list)
    for leaf in _own_leaves(node_a):
        buckets_a[canon_op(leaf, _ZERO_ORIGIN)].append(leaf)
    for bucket in buckets_a.values():
        bucket.sort(key=lambda leaf: leaf["source_element_id"])

    matched: list[tuple[L1Node, L1Node]] = []
    added: list[L1Node] = []
    for leaf in sorted(
            _own_leaves(node_b),
            key=lambda item: (canon_op(item, _ZERO_ORIGIN),
                              item["source_element_id"])):
        canonical = canon_op(leaf, _ZERO_ORIGIN)
        bucket = buckets_a.get(canonical)
        if bucket:
            matched.append((bucket.pop(0), leaf))
        else:
            added.append(leaf)
    removed = [leaf for bucket in buckets_a.values() for leaf in bucket]
    return (
        tuple(sorted(leaf["source_element_id"] for leaf in removed)),
        tuple(sorted(leaf["source_element_id"] for leaf in added)),
        matched,
    )


class _DiffState:
    def __init__(self) -> None:
        self.entries: list[DiffEntry] = []
        self.unchanged: list[UnchangedPair] = []
        self.pruned = 0


def _entry_added(occurrence: Occurrence) -> DiffEntry:
    return DiffEntry(
        status="added",
        kind=str(occurrence.tree_node["kind"]),
        path_a=None,
        path_b=occurrence.path,
        node_id_a=None,
        node_id_b=occurrence.node_id,
        hash_a=None,
        hash_b=occurrence.hash,
        origin_a=None,
        origin_b=occurrence.origin_mm,
        leaf_source_ids_a=(),
        leaf_source_ids_b=_subtree_source_ids(occurrence.tree_node),
    )


def _entry_removed(occurrence: Occurrence) -> DiffEntry:
    return DiffEntry(
        status="removed",
        kind=str(occurrence.tree_node["kind"]),
        path_a=occurrence.path,
        path_b=None,
        node_id_a=occurrence.node_id,
        node_id_b=None,
        hash_a=occurrence.hash,
        hash_b=None,
        origin_a=occurrence.origin_mm,
        origin_b=None,
        leaf_source_ids_a=_subtree_source_ids(occurrence.tree_node),
        leaf_source_ids_b=(),
    )


def _entry_moved(occ_a: Occurrence, occ_b: Occurrence) -> DiffEntry:
    return DiffEntry(
        status="moved",
        kind=str(occ_a.tree_node["kind"]),
        path_a=occ_a.path,
        path_b=occ_b.path,
        node_id_a=occ_a.node_id,
        node_id_b=occ_b.node_id,
        hash_a=occ_a.hash,
        hash_b=occ_b.hash,
        origin_a=occ_a.origin_mm,
        origin_b=occ_b.origin_mm,
        leaf_source_ids_a=_subtree_source_ids(occ_a.tree_node),
        leaf_source_ids_b=_subtree_source_ids(occ_b.tree_node),
    )


def _child_occurrences(
    index: MerkleIndex, occurrence: Occurrence,
) -> list[Occurrence]:
    return [
        index.by_path[occurrence.path + (child_index,)]
        for child_index in range(len(occurrence.tree_node["children"]))
    ]


def _diff_pair(
    occ_a: Occurrence,
    occ_b: Occurrence,
    index_a: MerkleIndex,
    index_b: MerkleIndex,
    state: _DiffState,
) -> None:
    if occ_a.hash == occ_b.hash:
        if occ_a.origin_mm == occ_b.origin_mm:
            state.pruned += 1
            state.unchanged.append(UnchangedPair(
                hash=occ_a.hash,
                path_a=occ_a.path,
                path_b=occ_b.path,
                origin_mm=occ_a.origin_mm,
                leaf_count=sum(1 for _ in iter_l1_leaves(occ_a.tree_node)),
            ))
            return
        state.pruned += 1
        state.entries.append(_entry_moved(occ_a, occ_b))
        return

    removed_own, added_own, _matched = _own_level_delta(
        occ_a.tree_node, occ_b.tree_node)
    state.entries.append(DiffEntry(
        status="changed",
        kind=str(occ_b.tree_node["kind"]),
        path_a=occ_a.path,
        path_b=occ_b.path,
        node_id_a=occ_a.node_id,
        node_id_b=occ_b.node_id,
        hash_a=occ_a.hash,
        hash_b=occ_b.hash,
        origin_a=occ_a.origin_mm,
        origin_b=occ_b.origin_mm,
        leaf_source_ids_a=removed_own,
        leaf_source_ids_b=added_own,
    ))

    children_a = _child_occurrences(index_a, occ_a)
    children_b = _child_occurrences(index_b, occ_b)

    unmatched_a: list[Occurrence] = []
    unmatched_b: list[Occurrence] = list(children_b)

    # Round 1: exact content match by hash; equal origin -> unchanged,
    # different origin -> moved.  Multiset semantics, deterministic order.
    by_hash_b: dict[str, list[Occurrence]] = defaultdict(list)
    for child in children_b:
        by_hash_b[child.hash].append(child)
    consumed_b: set[tuple[int, ...]] = set()
    for child_a in children_a:
        bucket = by_hash_b.get(child_a.hash, [])
        same_origin = next(
            (child_b for child_b in bucket
             if child_b.path not in consumed_b
             and child_b.origin_mm == child_a.origin_mm),
            None,
        )
        if same_origin is not None:
            consumed_b.add(same_origin.path)
            state.pruned += 1
            state.unchanged.append(UnchangedPair(
                hash=child_a.hash,
                path_a=child_a.path,
                path_b=same_origin.path,
                origin_mm=child_a.origin_mm,
                leaf_count=sum(
                    1 for _ in iter_l1_leaves(child_a.tree_node)),
            ))
            continue
        unmatched_a.append(child_a)
    unmatched_b = [
        child for child in unmatched_b if child.path not in consumed_b]

    # Same hash, different place -> moved (pair leftovers deterministically).
    still_a: list[Occurrence] = []
    by_hash_rem_b: dict[str, list[Occurrence]] = defaultdict(list)
    for child in unmatched_b:
        by_hash_rem_b[child.hash].append(child)
    for bucket in by_hash_rem_b.values():
        bucket.sort(key=lambda occ: (occ.origin_mm, occ.path))
    for child_a in sorted(
            unmatched_a, key=lambda occ: (occ.origin_mm, occ.path)):
        bucket = by_hash_rem_b.get(child_a.hash)
        if bucket:
            child_b = bucket.pop(0)
            consumed_b.add(child_b.path)
            state.pruned += 1
            state.entries.append(_entry_moved(child_a, child_b))
        else:
            still_a.append(child_a)
    unmatched_a = sorted(still_a, key=lambda occ: occ.path)
    unmatched_b = [
        child for child in unmatched_b if child.path not in consumed_b]

    # Round 2: same live identity (stable_tree_id = kind + source ids).
    by_node_id_b = {child.node_id: child for child in unmatched_b}
    recurse_pairs: list[tuple[Occurrence, Occurrence]] = []
    still_a = []
    for child_a in unmatched_a:
        child_b = by_node_id_b.get(child_a.node_id)
        if child_b is not None and child_b.path not in consumed_b:
            consumed_b.add(child_b.path)
            recurse_pairs.append((child_a, child_b))
        else:
            still_a.append(child_a)
    unmatched_a = still_a
    unmatched_b = [
        child for child in unmatched_b if child.path not in consumed_b]

    # Round 3: greedy pairing by shared source ids (same kind, overlap > 0).
    if unmatched_a and unmatched_b:
        ids_a = {
            child.path: frozenset(_subtree_source_ids(child.tree_node))
            for child in unmatched_a
        }
        ids_b = {
            child.path: frozenset(_subtree_source_ids(child.tree_node))
            for child in unmatched_b
        }
        scored: list[tuple[int, tuple[int, ...], tuple[int, ...]]] = []
        pos_a = {child.path: child for child in unmatched_a}
        pos_b = {child.path: child for child in unmatched_b}
        for child_a in unmatched_a:
            for child_b in unmatched_b:
                if child_a.tree_node["kind"] != child_b.tree_node["kind"]:
                    continue
                overlap = len(ids_a[child_a.path] & ids_b[child_b.path])
                if overlap > 0:
                    scored.append((-overlap, child_a.path, child_b.path))
        scored.sort()
        used_a: set[tuple[int, ...]] = set()
        used_b: set[tuple[int, ...]] = set()
        for _neg_overlap, path_a, path_b in scored:
            if path_a in used_a or path_b in used_b:
                continue
            used_a.add(path_a)
            used_b.add(path_b)
            recurse_pairs.append((pos_a[path_a], pos_b[path_b]))
        unmatched_a = [c for c in unmatched_a if c.path not in used_a]
        unmatched_b = [c for c in unmatched_b if c.path not in used_b]

    for child_a, child_b in sorted(
            recurse_pairs, key=lambda pair: pair[0].path):
        _diff_pair(child_a, child_b, index_a, index_b, state)

    for child_a in sorted(unmatched_a, key=lambda occ: occ.path):
        state.entries.append(_entry_removed(child_a))
    for child_b in sorted(unmatched_b, key=lambda occ: occ.path):
        state.entries.append(_entry_added(child_b))


def diff_trees(index_a: MerkleIndex, index_b: MerkleIndex) -> MerkleDiff:
    """Hash-guided recursive diff with early cutoff on matching subtrees."""

    state = _DiffState()
    _diff_pair(index_a.root, index_b.root, index_a, index_b, state)
    return MerkleDiff(
        entries=tuple(state.entries),
        unchanged=tuple(state.unchanged),
        pruned=state.pruned,
    )


# ---------------------------------------------------------------------------
# Incremental rebuild plan (interface; no live Revit here)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanReuse:
    """Same hash, same absolute placement: skip entirely (verdict + exec)."""

    hash: str
    path_a: tuple[int, ...]
    path_b: tuple[int, ...]
    leaf_count: int
    source_ids_a: tuple[str, ...]
    source_ids_b: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PlanLeafReuse:
    """Own-level leaf of a changed pair, byte-identical at absolute coords."""

    path_b: tuple[int, ...]
    source_id_a: str
    source_id_b: str


@dataclass(frozen=True, slots=True)
class PlanRelocate:
    """Same shape, new place: compile verdict transfers, exec re-runs.

    The verdict transfer is sound *by compile_cache's own construction*: its
    normalizer erases numeric literals, so a placement change cannot change
    the compile outcome (see MERKLE_SPEC §5).
    """

    hash: str
    path_a: tuple[int, ...] | None
    path_b: tuple[int, ...]
    offset_mm: Vec3
    source_ids_a: tuple[str, ...]
    payloads_b: tuple[L1Node, ...]


@dataclass(frozen=True, slots=True)
class PlanEmit:
    """Leaves of B that must be re-emitted (added or changed content)."""

    reason: str  # "added" | "changed"
    path_b: tuple[int, ...]
    hash_b: str | None
    payloads_b: tuple[L1Node, ...]


@dataclass(frozen=True, slots=True)
class PlanRetire:
    """Leaves of A that no longer exist in B."""

    reason: str  # "removed" | "changed"
    path_a: tuple[int, ...]
    hash_a: str | None
    source_ids_a: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RebuildPlan:
    """Typed incremental rebuild: reuse ∪ relocate ∪ emit covers all of B.

    Property P7 (test_merkle) proves the equivalence offline: the canonical
    absolute op multiset of reused A-leaves plus relocated and emitted
    B-leaves equals the multiset of *every* leaf of B — an incremental
    rebuild produces exactly what a full rebuild of B would.
    """

    reuse: tuple[PlanReuse, ...]
    leaf_reuse: tuple[PlanLeafReuse, ...]
    relocate: tuple[PlanRelocate, ...]
    emit: tuple[PlanEmit, ...]
    retire: tuple[PlanRetire, ...]

    @property
    def emitted_leaf_total(self) -> int:
        return (
            sum(len(entry.payloads_b) for entry in self.emit)
            + sum(len(entry.payloads_b) for entry in self.relocate)
        )

    @property
    def reused_leaf_total(self) -> int:
        return (
            sum(entry.leaf_count for entry in self.reuse)
            + len(self.leaf_reuse)
        )


def _subtree_payloads(node: TreeNode) -> tuple[L1Node, ...]:
    return tuple(sorted(
        iter_l1_leaves(node),
        key=lambda leaf: leaf["source_element_id"]))


def incremental_plan(
    diff: MerkleDiff,
    index_a: MerkleIndex,
    index_b: MerkleIndex,
) -> RebuildPlan:
    """Derive the typed reuse/relocate/emit/retire split from a diff."""

    reuse: list[PlanReuse] = []
    leaf_reuse: list[PlanLeafReuse] = []
    relocate: list[PlanRelocate] = []
    emit: list[PlanEmit] = []
    retire: list[PlanRetire] = []

    for pair in diff.unchanged:
        occ_a = index_a.by_path[pair.path_a]
        occ_b = index_b.by_path[pair.path_b]
        reuse.append(PlanReuse(
            hash=pair.hash,
            path_a=pair.path_a,
            path_b=pair.path_b,
            leaf_count=pair.leaf_count,
            source_ids_a=_subtree_source_ids(occ_a.tree_node),
            source_ids_b=_subtree_source_ids(occ_b.tree_node),
        ))

    for entry in diff.entries:
        if entry.status == "moved":
            assert entry.path_a is not None and entry.path_b is not None
            occ_a = index_a.by_path[entry.path_a]
            occ_b = index_b.by_path[entry.path_b]
            assert entry.origin_a is not None and entry.origin_b is not None
            offset = (
                _norm_zero(entry.origin_b[0] - entry.origin_a[0]),
                _norm_zero(entry.origin_b[1] - entry.origin_a[1]),
                _norm_zero(entry.origin_b[2] - entry.origin_a[2]),
            )
            relocate.append(PlanRelocate(
                hash=occ_b.hash,
                path_a=entry.path_a,
                path_b=entry.path_b,
                offset_mm=offset,
                source_ids_a=entry.leaf_source_ids_a,
                payloads_b=_subtree_payloads(occ_b.tree_node),
            ))
        elif entry.status == "added":
            assert entry.path_b is not None
            occ_b = index_b.by_path[entry.path_b]
            emit.append(PlanEmit(
                reason="added",
                path_b=entry.path_b,
                hash_b=entry.hash_b,
                payloads_b=_subtree_payloads(occ_b.tree_node),
            ))
        elif entry.status == "removed":
            assert entry.path_a is not None
            retire.append(PlanRetire(
                reason="removed",
                path_a=entry.path_a,
                hash_a=entry.hash_a,
                source_ids_a=entry.leaf_source_ids_a,
            ))
        elif entry.status == "changed":
            assert entry.path_a is not None and entry.path_b is not None
            occ_a = index_a.by_path[entry.path_a]
            occ_b = index_b.by_path[entry.path_b]
            removed_ids, added_ids, matched = _own_level_delta(
                occ_a.tree_node, occ_b.tree_node)
            id_filter_b = set(added_ids)
            changed_payloads = tuple(sorted(
                (leaf for leaf in _own_leaves(occ_b.tree_node)
                 if leaf["source_element_id"] in id_filter_b),
                key=lambda leaf: leaf["source_element_id"]))
            if changed_payloads:
                emit.append(PlanEmit(
                    reason="changed",
                    path_b=entry.path_b,
                    hash_b=entry.hash_b,
                    payloads_b=changed_payloads,
                ))
            if removed_ids:
                retire.append(PlanRetire(
                    reason="changed",
                    path_a=entry.path_a,
                    hash_a=entry.hash_a,
                    source_ids_a=removed_ids,
                ))
            for leaf_a, leaf_b in matched:
                leaf_reuse.append(PlanLeafReuse(
                    path_b=entry.path_b,
                    source_id_a=leaf_a["source_element_id"],
                    source_id_b=leaf_b["source_element_id"],
                ))
        else:  # pragma: no cover - closed status set
            raise MerkleError(f"unknown diff status {entry.status!r}")

    return RebuildPlan(
        reuse=tuple(sorted(reuse, key=lambda item: item.path_b)),
        leaf_reuse=tuple(sorted(
            leaf_reuse,
            key=lambda item: (item.path_b, item.source_id_b))),
        relocate=tuple(sorted(relocate, key=lambda item: item.path_b)),
        emit=tuple(sorted(emit, key=lambda item: item.path_b)),
        retire=tuple(sorted(retire, key=lambda item: item.path_a)),
    )


__all__ = [
    "MERKLE_VERSION",
    "DedupEntry",
    "DiffEntry",
    "MerkleCollisionError",
    "MerkleDiff",
    "MerkleEdge",
    "MerkleError",
    "MerkleIndex",
    "MerkleIntegrityError",
    "MerkleNode",
    "MerkleNodeMissingError",
    "MerkleStore",
    "Occurrence",
    "PlanEmit",
    "PlanLeafReuse",
    "PlanRelocate",
    "PlanReuse",
    "PlanRetire",
    "RebuildPlan",
    "UnchangedPair",
    "build_index",
    "dedup_report",
    "diff_trees",
    "incremental_plan",
    "merkle_enabled",
    "merkle_hash",
    "node_origin",
]
