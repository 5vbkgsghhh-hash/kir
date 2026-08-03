"""Content-addressed learned priors over the Merkle DAG (wave 4).

From a corpus of decompiled buildings (each a ``MerkleIndex`` from wave 1),
fit a DETERMINISTIC statistical model keyed by the **merkle-hash of a SHAPE**,
never by a name or id:

* **shape frequency** — how many buildings contain a shape (document
  frequency) and how many times in total (a component library with learned
  weights);
* **parent -> child co-occurrence** — which child shapes appear under which
  parent shape and how often (a typical floor contains these apartments);
* **robust parameter priors** — typical numeric values per kind (a wall's
  height, a pipe's diameter) as nearest-rank quantiles.

Because the key is the merkle-hash (a shape's equivalence class up to
translation / renaming / renumbering — wave 1's invariance), the same shape in
two different buildings is one prior key: the model learns across buildings for
free, exactly as wave-1 dedup collapses repeats.  The model answers likelihood,
expected children, and anomaly queries, and is fail-closed on an unseen shape
(explicit "unknown", never a fabricated probability).

Discipline (forks in PRIORS_SPEC.md):

* **Counts, not smoothed density.**  The model stores honest document/total
  frequencies; "probability" is the derived ``df / n_buildings`` computed on
  query.  No random smoothing (it would break determinism and hide the unseen);
  an unseen shape is an explicit ``is_known() == False`` /
  ``UnknownShapeError``, never a small non-zero p.
* **df is per-BUILDING** — a floor repeated 20x in one building is df=1,
  total=20; industry-spread prior is ``df / n_buildings``, not total (so one
  tall building cannot dominate).
* **Quantiles are nearest-rank, deterministic** (no interpolation, which is
  float-unstable — the same trap wave 3 rounded away); values are canonicalized
  to a fixed precision on collection.
* **merge is associative/commutative and equals fit-of-union** — incremental
  training without a rebuild (the "part + part = whole" principle shared with
  wave-1 incremental-rebuild and wave-3 DAG==flat).
* **Inert, additive, opt-in.**  Nothing is touched; ``priors_enabled()`` is
  default OFF.  A prior changes HOW (adds a hint), never WHAT (not the
  decompile, not the measures).  Frozen L0 untouched.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from kukai.ir.decompile.fold import TreeNode, iter_l1_leaves
from kukai.ir.decompile.l1_schema import L1Node


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class PriorError(ValueError):
    """Base for every typed prior-layer failure."""


class PriorSchemaError(PriorError):
    """A malformed corpus, serialized model, or incompatible merge."""


class UnknownShapeError(PriorError):
    """A strict query referenced a shape the corpus never contained."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def priors_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return os.getenv("KUKAI_IR_PRIORS", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# Canonical precision for parameter values (mm / degree); float non-determinism
# must not leak into learned quantiles (same rounding discipline as wave 3).
_PARAM_DECIMALS = 6


def _round_param(value: float) -> float:
    rounded = round(value, _PARAM_DECIMALS)
    return 0.0 if rounded == 0.0 else rounded


# Numeric L1 op params worth a parameter prior, per op_name.  Kept explicit so
# the model never mines an arbitrary field (a coordinate would be meaningless).
_PARAM_FIELDS: dict[str, tuple[str, ...]] = {
    "create_wall": ("height_mm",),
    "create_pipe": ("diameter_mm",),
    "create_duct": ("diameter_mm",),
    "create_level": ("elev_mm",),
}


# ---------------------------------------------------------------------------
# Stat records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ShapeStat:
    hash: str
    kind: str
    document_frequency: int          # in how many buildings the shape appears
    total_occurrences: int           # across all buildings
    leaf_count: int
    sample_label: str


@dataclass(frozen=True, slots=True)
class ChildStat:
    parent_hash: str
    child_hash: str
    co_document_frequency: int       # buildings where child sits under parent
    co_total: int                    # total such parent->child edges


@dataclass(frozen=True, slots=True)
class ParamQuantiles:
    kind: str
    param: str
    count: int
    p10: float
    p50: float
    p90: float


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def _nearest_rank(sorted_values: Sequence[float], pct: float) -> float:
    """Deterministic nearest-rank percentile (no interpolation)."""

    n = len(sorted_values)
    if n == 0:
        raise PriorSchemaError("percentile of an empty sample")
    rank = max(1, math.ceil(pct * n))
    return sorted_values[min(rank, n) - 1]


class PriorModel:
    """An immutable, deterministic learned-prior model."""

    def __init__(
        self,
        *,
        n_buildings: int,
        shapes: Mapping[str, ShapeStat],
        children: Mapping[tuple[str, str], ChildStat],
        param_values: Mapping[tuple[str, str], tuple[float, ...]],
    ) -> None:
        self.n_buildings = int(n_buildings)
        self.shapes: dict[str, ShapeStat] = dict(shapes)
        self.children: dict[tuple[str, str], ChildStat] = dict(children)
        # Raw sorted value multisets per (kind, param) — kept so merge stays
        # exact and quantiles are recomputable (v1: full multiset).
        self._param_values: dict[tuple[str, str], tuple[float, ...]] = {
            key: tuple(sorted(values))
            for key, values in param_values.items()
        }

    # -- shape frequency ----------------------------------------------------
    def is_known(self, shape_hash: str) -> bool:
        return shape_hash in self.shapes

    def shape_stat(self, shape_hash: str) -> ShapeStat | None:
        return self.shapes.get(shape_hash)

    def shape_frequency(
        self, shape_hash: str, *, strict: bool = False,
    ) -> float:
        """Per-building document frequency df / n_buildings in [0, 1]."""

        stat = self.shapes.get(shape_hash)
        if stat is None:
            if strict:
                raise UnknownShapeError(f"shape {shape_hash!r} not in corpus")
            return 0.0
        if self.n_buildings == 0:
            return 0.0
        return stat.document_frequency / self.n_buildings

    # -- parent -> child ----------------------------------------------------
    def expected_children(self, parent_hash: str) -> tuple[ChildStat, ...]:
        stats = [
            stat for (parent, _child), stat in self.children.items()
            if parent == parent_hash
        ]
        stats.sort(key=lambda s: (-s.co_document_frequency, -s.co_total,
                                  s.child_hash))
        return tuple(stats)

    def child_conditional(
        self, parent_hash: str, child_hash: str, *, strict: bool = False,
    ) -> float:
        """P(child under parent) = co_df / df(parent), in [0, 1]."""

        parent = self.shapes.get(parent_hash)
        if parent is None:
            if strict:
                raise UnknownShapeError(f"parent {parent_hash!r} not in corpus")
            return 0.0
        edge = self.children.get((parent_hash, child_hash))
        if edge is None or parent.document_frequency == 0:
            return 0.0
        return edge.co_document_frequency / parent.document_frequency

    # -- parameter priors ---------------------------------------------------
    def param_quantiles(self, kind: str, param: str) -> ParamQuantiles | None:
        values = self._param_values.get((kind, param))
        if not values:
            return None
        return ParamQuantiles(
            kind=kind,
            param=param,
            count=len(values),
            p10=_nearest_rank(values, 0.10),
            p50=_nearest_rank(values, 0.50),
            p90=_nearest_rank(values, 0.90),
        )

    # -- anomalies ----------------------------------------------------------
    def anomalies(
        self, index: Any, *, max_frequency: float = 0.1,
    ) -> tuple[tuple[str, str, float, bool], ...]:
        """Return (hash, kind, frequency, known) for a building's shapes that
        are rare relative to the corpus (frequency < ``max_frequency``).

        A shape unseen in the corpus is maximally anomalous (frequency 0,
        known=False) — an explicit signal, never a fabricated small p.
        """

        seen: dict[str, str] = {}
        for shape_hash, occs in index.occurrences.items():
            seen[shape_hash] = str(occs[0].tree_node["kind"])
        result: list[tuple[str, str, float, bool]] = []
        for shape_hash in sorted(seen):
            freq = self.shape_frequency(shape_hash)
            known = self.is_known(shape_hash)
            if freq < max_frequency:
                result.append((shape_hash, seen[shape_hash], freq, known))
        result.sort(key=lambda row: (row[2], row[0]))
        return tuple(result)

    # -- serialization ------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": "priors/1",
            "n_buildings": self.n_buildings,
            "shapes": [
                {
                    "hash": s.hash, "kind": s.kind,
                    "document_frequency": s.document_frequency,
                    "total_occurrences": s.total_occurrences,
                    "leaf_count": s.leaf_count, "sample_label": s.sample_label,
                }
                for s in sorted(self.shapes.values(), key=lambda x: x.hash)
            ],
            "children": [
                {
                    "parent_hash": c.parent_hash, "child_hash": c.child_hash,
                    "co_document_frequency": c.co_document_frequency,
                    "co_total": c.co_total,
                }
                for _key, c in sorted(self.children.items())
            ],
            "param_values": [
                {"kind": key[0], "param": key[1], "values": list(values)}
                for key, values in sorted(self._param_values.items())
            ],
        }

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True,
            separators=(",", ":"))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PriorModel":
        if not isinstance(payload, Mapping):
            raise PriorSchemaError("prior model payload must be a mapping")
        try:
            shapes = {
                row["hash"]: ShapeStat(
                    hash=row["hash"], kind=row["kind"],
                    document_frequency=int(row["document_frequency"]),
                    total_occurrences=int(row["total_occurrences"]),
                    leaf_count=int(row["leaf_count"]),
                    sample_label=str(row["sample_label"]))
                for row in payload["shapes"]
            }
            children = {
                (row["parent_hash"], row["child_hash"]): ChildStat(
                    parent_hash=row["parent_hash"],
                    child_hash=row["child_hash"],
                    co_document_frequency=int(row["co_document_frequency"]),
                    co_total=int(row["co_total"]))
                for row in payload["children"]
            }
            param_values = {
                (row["kind"], row["param"]): tuple(
                    float(v) for v in row["values"])
                for row in payload["param_values"]
            }
            n_buildings = int(payload["n_buildings"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PriorSchemaError(f"malformed prior model: {exc}") from exc
        return cls(
            n_buildings=n_buildings, shapes=shapes, children=children,
            param_values=param_values)

    # -- equality (deterministic model comparison for tests/merge proofs) ---
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PriorModel):
            return NotImplemented
        return (
            self.n_buildings == other.n_buildings
            and self.shapes == other.shapes
            and self.children == other.children
            and self._param_values == other._param_values
        )

    def __hash__(self) -> int:  # pragma: no cover - models are not dict keys
        return hash((self.n_buildings, tuple(sorted(self.shapes))))


# ---------------------------------------------------------------------------
# Fitting
# ---------------------------------------------------------------------------


def _require_index(index: Any) -> None:
    if not (hasattr(index, "occurrences") and hasattr(index, "by_path")
            and hasattr(index, "root")):
        raise PriorSchemaError(
            "corpus entries must be MerkleIndex instances")


def _fit_one(
    index: Any,
    trees_by_root: Mapping[str, TreeNode] | None,
) -> tuple[
    dict[str, ShapeStat],
    dict[tuple[str, str], ChildStat],
    dict[tuple[str, str], list[float]],
]:
    """Per-building contribution: df counted once, total per occurrence."""

    _require_index(index)

    # Shapes: this building contributes df=1 per distinct hash, total=#occs.
    shapes: dict[str, ShapeStat] = {}
    for shape_hash, occs in index.occurrences.items():
        sample = occs[0]
        leaf_count = sum(1 for _ in iter_l1_leaves(sample.tree_node))
        shapes[shape_hash] = ShapeStat(
            hash=shape_hash,
            kind=str(sample.tree_node["kind"]),
            document_frequency=1,
            total_occurrences=len(occs),
            leaf_count=leaf_count,
            sample_label=str(sample.tree_node["label"]),
        )

    # Parent -> child edges from by_path (child path = parent path + (i,)).
    # co_total = number of such edges in THIS building; co_df = 1 if present.
    edge_totals: dict[tuple[str, str], int] = defaultdict(int)
    for path, occ in index.by_path.items():
        parent_hash = occ.hash
        node = occ.tree_node
        for child_index in range(len(node["children"])):
            child = index.by_path[path + (child_index,)]
            edge_totals[(parent_hash, child.hash)] += 1
    children: dict[tuple[str, str], ChildStat] = {
        key: ChildStat(
            parent_hash=key[0], child_hash=key[1],
            co_document_frequency=1, co_total=total)
        for key, total in edge_totals.items()
    }

    # Parameter values from the exact L1 leaves (only when trees supplied).
    param_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    if trees_by_root is not None:
        tree = trees_by_root.get(index.root_hash)
        if tree is not None:
            for leaf in iter_l1_leaves(tree):
                if leaf["kind"] != "op":
                    continue
                op_name = leaf["op_name"]  # type: ignore[typeddict-item]
                fields = _PARAM_FIELDS.get(op_name)
                if not fields:
                    continue
                params = leaf["params"]  # type: ignore[typeddict-item]
                for field in fields:
                    value = params.get(field)
                    if (isinstance(value, (int, float))
                            and not isinstance(value, bool)
                            and math.isfinite(float(value))):
                        param_values[(op_name, field)].append(
                            _round_param(float(value)))
    return shapes, children, param_values


def _accumulate(
    contributions: Iterable[tuple[
        dict[str, ShapeStat],
        dict[tuple[str, str], ChildStat],
        dict[tuple[str, str], list[float]],
    ]],
    n_buildings: int,
) -> PriorModel:
    shapes: dict[str, ShapeStat] = {}
    children: dict[tuple[str, str], ChildStat] = {}
    param_values: dict[tuple[str, str], list[float]] = defaultdict(list)

    for one_shapes, one_children, one_params in contributions:
        for shape_hash, stat in one_shapes.items():
            existing = shapes.get(shape_hash)
            if existing is None:
                shapes[shape_hash] = stat
            else:
                shapes[shape_hash] = ShapeStat(
                    hash=shape_hash,
                    kind=existing.kind,
                    document_frequency=(
                        existing.document_frequency + stat.document_frequency),
                    total_occurrences=(
                        existing.total_occurrences + stat.total_occurrences),
                    leaf_count=existing.leaf_count,
                    sample_label=min(existing.sample_label, stat.sample_label),
                )
        for key, edge in one_children.items():
            existing_edge = children.get(key)
            if existing_edge is None:
                children[key] = edge
            else:
                children[key] = ChildStat(
                    parent_hash=key[0], child_hash=key[1],
                    co_document_frequency=(
                        existing_edge.co_document_frequency
                        + edge.co_document_frequency),
                    co_total=existing_edge.co_total + edge.co_total,
                )
        for key, values in one_params.items():
            param_values[key].extend(values)

    return PriorModel(
        n_buildings=n_buildings,
        shapes=shapes,
        children=children,
        param_values={k: tuple(sorted(v)) for k, v in param_values.items()},
    )


def fit(
    indexes: Sequence[Any],
    *,
    trees: Sequence[TreeNode] | None = None,
) -> PriorModel:
    """Fit a prior model over a corpus of MerkleIndex buildings.

    ``trees`` (optional, aligned by root hash) enables parameter priors from
    the exact L1 leaves; without it the model carries shape + child priors only.
    """

    trees_by_root: dict[str, TreeNode] | None = None
    if trees is not None:
        trees_by_root = {}
        for tree in trees:
            # A tree's root hash matches its index's root hash by construction.
            from kukai.ir.decompile.merkle import merkle_hash
            trees_by_root[merkle_hash(tree)] = tree

    contributions = [_fit_one(index, trees_by_root) for index in indexes]
    return _accumulate(contributions, n_buildings=len(indexes))


def merge(a: PriorModel, b: PriorModel) -> PriorModel:
    """Combine two models as if fit over the concatenated corpora.

    Associative and commutative: ``fit(A+B) == merge(fit(A), fit(B))`` and the
    order of merges does not matter (deterministic incremental training).
    """

    if not isinstance(a, PriorModel) or not isinstance(b, PriorModel):
        raise PriorSchemaError("merge operands must be PriorModel instances")

    def _contrib(model: PriorModel):
        return (
            dict(model.shapes),
            dict(model.children),
            {k: list(v) for k, v in model._param_values.items()},
        )

    return _accumulate(
        [_contrib(a), _contrib(b)],
        n_buildings=a.n_buildings + b.n_buildings,
    )


__all__ = [
    "ChildStat",
    "ParamQuantiles",
    "PriorError",
    "PriorModel",
    "PriorSchemaError",
    "ShapeStat",
    "UnknownShapeError",
    "fit",
    "merge",
    "priors_enabled",
]
