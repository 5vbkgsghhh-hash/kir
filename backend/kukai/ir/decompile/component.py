"""Component library and instancing over the Merkle DAG (wave 5).

A Merkle-deduped subtree (wave 1) becomes a reusable **component definition**
(drawn once, its leaves localized to the component origin) plus a set of
**instances** (each just an ``offset_mm`` taken from an occurrence).  This is
the forward "draw once, place N times" analytical form: expanding the instances
reproduces exactly the original *template-canonical* leaves.  Turning that
analysis into an executable operation requires the separate FidelityCanon proof
described below.

Because the key is the merkle-hash (a shape's equivalence class up to
translation — wave 1's invariance), the same shape anywhere is one component;
its occurrences are the instances.  A component is shared only among
TRANSLATION copies — rotated / mirrored copies hash differently and stay
distinct components (never falsely merged; honest by construction).

Discipline (forks in COMPONENT_LIBRARY_SPEC.md):

* **Localization is subtract-node_origin** — the same canonicalization the
  merkle-hash already uses, so a component's ``def_hash`` equals its
  occurrence hash (no new notion of shape).
* **Template round-trip is exact.**  ``instantiate(defn, offset)`` translates
  the localized leaves by ``+offset``; for an occurrence O it reproduces O's
  template-canonical leaves (property C1), and ``expand_library`` reproduces
  the whole tree's template multiset (property C-RT).  This deliberately broad
  identity is what discovers repeated floors whose concrete level bindings
  differ.
* **Execution fidelity is a separate proof.**  A ``PlaceGroupOp`` carries
  ``fidelity_proven`` only when every instantiated occurrence also matches the
  source under ``FidelityCanon`` (concrete levels and graph bindings survive).
  Native Revit-group emission consumes only such ops.  A visually identical
  floor bound to another Level therefore remains discoverable as a component,
  but cannot be executed as one shared Revit definition until an explicit
  per-instance binding model proves that mapping.
* **Instance ids are regenerated deterministically** so N copies never share an
  id; a residual collision is a typed ``ComponentSchemaError`` (fail-closed,
  like fold's ``assert_preservation``).
* **Inert, additive, opt-in.**  Nothing is touched; ``component_enabled()`` is
  default OFF.  Frozen L0 untouched.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from kukai.ir.decompile.fold import (
    FidelityCanon,
    TreeNode,
    canon_op,
    iter_l1_leaves,
)
from kukai.ir.decompile.fold import (  # canonicalization authority — reused
    _COORDINATE_FIELDS,
    _round_mm,
)
from kukai.ir.decompile.l1_schema import L1Node, stable_l1_id
from kukai.ir.decompile.merkle import (
    MerkleError,
    Occurrence,
    dedup_report,
    node_origin,
)

Vec3 = tuple[float, float, float]
_ZERO = (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Typed failures (fail-closed)
# ---------------------------------------------------------------------------


class ComponentError(ValueError):
    """Base for every typed component-layer failure."""


class ComponentRoundTripError(ComponentError):
    """Expanding a component does not reproduce its source leaves."""


class ComponentSchemaError(ComponentError):
    """A malformed component / instance, or a residual id collision."""


# ---------------------------------------------------------------------------
# Flag (inertness contract)
# ---------------------------------------------------------------------------


def component_enabled() -> bool:
    """Opt-in gate for future pipeline wiring; default OFF."""

    return os.getenv("KUKAI_IR_COMPONENT", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


# ---------------------------------------------------------------------------
# Coordinate translation (field-aware, deterministic, mm-grid exact)
# ---------------------------------------------------------------------------


def _translate_coord_value(value: Any, delta: Vec3, field_name: str | None) -> Any:
    """Translate coordinate vectors by ``+delta``; leave everything else."""

    if field_name in _COORDINATE_FIELDS and isinstance(value, list):
        if (len(value) in (2, 3)
                and all(isinstance(item, (int, float))
                        and not isinstance(item, bool) for item in value)):
            return [
                _round_mm(float(component) + delta[index])
                for index, component in enumerate(value)
            ]
        return [
            _translate_coord_value(item, delta, field_name) for item in value
        ]
    if isinstance(value, dict):
        # elevation is a z-relative scalar; translate it by delta.z.
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in ("elevation_mm", "elev_mm") and isinstance(
                    item, (int, float)) and not isinstance(item, bool):
                result[key] = _round_mm(float(item) + delta[2])
            else:
                result[key] = _translate_coord_value(item, delta, key)
        return result
    if isinstance(value, list):
        return [_translate_coord_value(item, delta, field_name) for item in value]
    return value


def _translate_leaf(leaf: L1Node, delta: Vec3) -> dict[str, Any]:
    """Return a deep copy of ``leaf`` with coordinates translated by ``delta``."""

    out: dict[str, Any] = {}
    for key, value in leaf.items():
        if key == "anchor_mm":
            out[key] = (
                None if value is None
                else [_round_mm(float(value[i]) + delta[i]) for i in range(3)])
        elif key in ("bbox_min_mm", "bbox_max_mm"):
            out[key] = (
                None if value is None
                else [_round_mm(float(value[i]) + delta[i]) for i in range(3)])
        elif key == "params":
            out[key] = _translate_coord_value(value, delta, None)
        else:
            out[key] = value
    return out  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Component definition / instance / place-group op
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComponentDefinition:
    """A reusable shape: leaves localized to the component origin, drawn once."""

    def_hash: str
    kind: str
    origin_mm: Vec3
    leaves: tuple[L1Node, ...]
    leaf_count: int
    label: str


@dataclass(frozen=True, slots=True)
class ComponentInstance:
    """One placement of a component.

    ``offset_mm`` is the ABSOLUTE placement point of the localized definition —
    i.e. the occurrence's own canonical origin.  Because ``extract_component``
    localizes the leaves by subtracting the DEFINITION origin, the leaves live
    at ``absolute - def_origin``; the shape at this occurrence therefore has its
    absolute leaves at ``localized + occ_origin`` (the ``def_origin`` cancels),
    so the reconstruction offset is exactly ``occ_origin`` — NOT
    ``occ_origin - def_origin``.  (That relative-delta form was the LOT31 C-RT
    bug: it silently coincided with the correct value only when ``def_origin``
    was ``(0,0,0)``, which is all the synthetic tests happened to produce.)

    ``origin_mm`` is the same absolute origin, kept for reporting; ``rel_mm``
    is the translation relative to the definition origin, for audit/emission.
    """

    def_hash: str
    instance_index: int
    offset_mm: Vec3
    origin_mm: Vec3
    rel_mm: Vec3


@dataclass(frozen=True, slots=True)
class ComponentFidelityProof:
    """Concrete per-occurrence identity evidence for execution eligibility.

    The two hash sequences are computed independently: one from the translated
    component definition, one from the exact source occurrence.  Equality under
    the pinned ``FidelityCanon`` version is the proof.  Keeping both sides makes
    a refusal auditable instead of reducing it to a forgeable boolean.
    """

    canon_version: str
    instantiated_hashes: tuple[str, ...]
    source_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.canon_version != FidelityCanon.VERSION:
            raise ComponentSchemaError(
                "component fidelity proof uses an unknown canon version")
        if len(self.instantiated_hashes) != len(self.source_hashes):
            raise ComponentSchemaError(
                "component fidelity proof cardinalities differ")
        for value in (*self.instantiated_hashes, *self.source_hashes):
            if (not isinstance(value, str) or len(value) != 40
                    or any(ch not in "0123456789abcdef" for ch in value)):
                raise ComponentSchemaError(
                    "component fidelity proof hash must be lowercase sha1")

    @property
    def verified(self) -> bool:
        return (
            bool(self.instantiated_hashes)
            and self.instantiated_hashes == self.source_hashes
        )

    @property
    def mismatch_indices(self) -> tuple[int, ...]:
        return tuple(
            index for index, (instantiated, source) in enumerate(
                zip(self.instantiated_hashes, self.source_hashes))
            if instantiated != source
        )


@dataclass(frozen=True, slots=True)
class PlaceGroupOp:
    """Forward op: place a component ``occurrence_count`` times."""

    def_hash: str
    definition: ComponentDefinition
    instances: tuple[ComponentInstance, ...]
    # TemplateCanon is intentionally broad enough to discover typical floors.
    # Revit execution needs the stronger proof: concrete external bindings
    # (Level/type ids) and graph targets must also reconstruct exactly.
    fidelity_proof: ComponentFidelityProof | None = None

    @property
    def occurrence_count(self) -> int:
        return len(self.instances)

    @property
    def savings_leaves(self) -> int:
        return self.definition.leaf_count * (self.occurrence_count - 1)

    @property
    def fidelity_proven(self) -> bool:
        proof = self.fidelity_proof
        return (
            proof is not None
            and len(proof.source_hashes) == self.occurrence_count
            and proof.verified
        )

    @property
    def fidelity_mismatch_indices(self) -> tuple[int, ...]:
        proof = self.fidelity_proof
        if proof is None or len(proof.source_hashes) != self.occurrence_count:
            return tuple(range(self.occurrence_count))
        return proof.mismatch_indices


def _neg(origin: Vec3) -> Vec3:
    return (-origin[0], -origin[1], -origin[2])


def extract_component(occurrence: Occurrence) -> ComponentDefinition:
    """Build a component definition from one occurrence (leaves localized)."""

    if not isinstance(occurrence, Occurrence):
        raise ComponentSchemaError("extract_component needs an Occurrence")
    origin = node_origin(occurrence.tree_node)
    localized = [
        _translate_leaf(leaf, _neg(origin))
        for leaf in iter_l1_leaves(occurrence.tree_node)
    ]
    localized.sort(key=lambda leaf: (
        canon_op(leaf, _ZERO), leaf["source_element_id"]))
    return ComponentDefinition(
        def_hash=occurrence.hash,
        kind=str(occurrence.tree_node["kind"]),
        origin_mm=origin,
        leaves=tuple(localized),
        leaf_count=len(localized),
        label=str(occurrence.tree_node["label"]),
    )


def _instance_source_id(def_hash: str, instance_index: int, source_id: str) -> str:
    return f"{def_hash[:12]}:{instance_index}:{source_id}"


def instantiate(
    defn: ComponentDefinition,
    offset_mm: Vec3,
    *,
    instance_index: int,
    regenerate_ids: bool = True,
) -> tuple[L1Node, ...]:
    """Return the component's leaves translated by ``offset_mm``.

    With ``regenerate_ids`` (the default for a placed instance) each leaf gets a
    deterministic, per-instance-unique source id / _id so N instances never
    share an id.  With ``regenerate_ids=False`` the localized leaves keep their
    ids — used by the round-trip proof to compare pure geometry.
    """

    if not isinstance(defn, ComponentDefinition):
        raise ComponentSchemaError("instantiate needs a ComponentDefinition")
    placed: list[L1Node] = []
    for leaf in defn.leaves:
        translated = _translate_leaf(leaf, offset_mm)
        if regenerate_ids:
            new_source = _instance_source_id(
                defn.def_hash, instance_index, leaf["source_element_id"])
            translated["source_element_id"] = new_source
            translated["_id"] = stable_l1_id(leaf["kind"], new_source)
        placed.append(translated)  # type: ignore[arg-type]
    return tuple(placed)


# ---------------------------------------------------------------------------
# Library assembly
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ComponentLibrary:
    definitions: Mapping[str, ComponentDefinition]
    place_ops: tuple[PlaceGroupOp, ...]
    singletons_leaves: tuple[L1Node, ...]

    def get(self, def_hash: str) -> ComponentDefinition | None:
        return self.definitions.get(def_hash)

    def has(self, def_hash: str) -> bool:
        return def_hash in self.definitions

    @property
    def total_defined_leaves(self) -> int:
        return sum(d.leaf_count for d in self.definitions.values())

    @property
    def total_instanced_leaves(self) -> int:
        return sum(
            op.definition.leaf_count * op.occurrence_count
            for op in self.place_ops)


def _place_op_reconstructs(
    place_op: "PlaceGroupOp", ordered_occs: Sequence[Occurrence],
) -> bool:
    """Whether every instance reproduces its occurrence's template multiset.

    This is the broad discovery/partition gate, not permission to emit a native
    Revit Group.  Concrete levels and graph targets are checked separately by
    :func:`_place_op_fidelity_proof`.
    """

    if len(place_op.instances) != len(ordered_occs):
        return False
    for instance, occ in zip(place_op.instances, ordered_occs):
        placed = instantiate(
            place_op.definition, instance.offset_mm,
            instance_index=instance.instance_index, regenerate_ids=False)
        if _abs_multiset(placed) != _abs_multiset(iter_l1_leaves(occ.tree_node)):
            return False
    return True


def _place_op_fidelity_proof(
    place_op: "PlaceGroupOp", ordered_occs: Sequence[Occurrence],
) -> ComponentFidelityProof | None:
    """Build concrete evidence for (or against) native-group eligibility.

    ``TemplateCanon`` intentionally erases storey labels/ids to discover a
    typical floor.  ``FidelityCanon`` retains concrete selectors and resolves
    graph references by structural identity.  A native Revit Group is eligible
    only when this stronger comparison succeeds for *every* occurrence.

    Any malformed graph or cardinality mismatch is a mismatch, never an
    exception that could accidentally turn the optimization on.
    """

    if len(place_op.instances) != len(ordered_occs):
        return None
    instantiated_hashes: list[str] = []
    source_hashes: list[str] = []
    for instance, occ in zip(place_op.instances, ordered_occs):
        placed = instantiate(
            place_op.definition, instance.offset_mm,
            instance_index=instance.instance_index, regenerate_ids=False)
        source = tuple(iter_l1_leaves(occ.tree_node))
        try:
            instantiated_hashes.append(
                FidelityCanon.multiset_hash(placed, _ZERO))
            source_hashes.append(
                FidelityCanon.multiset_hash(source, _ZERO))
        except (TypeError, ValueError):
            return None
    return ComponentFidelityProof(
        canon_version=FidelityCanon.VERSION,
        instantiated_hashes=tuple(instantiated_hashes),
        source_hashes=tuple(source_hashes),
    )


def _place_op_fidelity_mismatches(
    place_op: "PlaceGroupOp", ordered_occs: Sequence[Occurrence],
) -> tuple[int, ...]:
    """Compatibility helper returning the proof's mismatch indices."""

    proof = _place_op_fidelity_proof(place_op, ordered_occs)
    if proof is None:
        return tuple(range(max(len(place_op.instances), len(ordered_occs))))
    return proof.mismatch_indices


def build_library(
    index: Any,
    *,
    min_occurrences: int = 2,
    min_leaves: int = 2,
) -> ComponentLibrary:
    """Turn a building's maximal repeated subtrees into components + instances.

    Chooses disjoint, non-dominated maximal repeats (like ``takeoff_dag`` /
    wave-1 dedup): each occurrence path is claimed by at most one component, and
    a repeat nested inside another is skipped.  Leaves outside every component
    become singletons.  Every original leaf is thus accounted exactly once
    (property C7).
    """

    if not (hasattr(index, "occurrences") and hasattr(index, "by_path")
            and hasattr(index, "root")):
        raise ComponentSchemaError("build_library needs a MerkleIndex")

    repeats = dedup_report(
        [index], min_occurrences=min_occurrences, min_leaves=min_leaves)

    claimed_paths: list[tuple[int, ...]] = []

    def _covered(path: tuple[int, ...]) -> bool:
        return any(
            len(base) < len(path) and path[:len(base)] == base
            for base in claimed_paths)

    definitions: dict[str, ComponentDefinition] = {}
    place_ops: list[PlaceGroupOp] = []

    for entry in repeats:
        if entry.dominated:
            continue
        occs = index.occurrences_of(entry.hash)
        paths = [occ.path for occ in occs]
        if any(_covered(path) for path in paths):
            continue
        # Deterministic instance order by absolute origin then path.
        ordered = sorted(occs, key=lambda o: (o.origin_mm, o.path))
        definition = extract_component(ordered[0])
        instances = tuple(
            ComponentInstance(
                def_hash=definition.def_hash,
                instance_index=idx,
                # ABSOLUTE placement of the localized definition (see the
                # ComponentInstance docstring for why occ_origin, not the delta).
                offset_mm=occ.origin_mm,
                origin_mm=occ.origin_mm,
                rel_mm=(
                    _round_mm(occ.origin_mm[0] - definition.origin_mm[0]),
                    _round_mm(occ.origin_mm[1] - definition.origin_mm[1]),
                    _round_mm(occ.origin_mm[2] - definition.origin_mm[2]),
                ),
            )
            for idx, occ in enumerate(ordered)
        )
        place_op = PlaceGroupOp(
            def_hash=definition.def_hash,
            definition=definition,
            instances=instances,
        )
        # FAIL-CLOSED (LOT31 directive): a component enters the library ONLY if
        # EVERY instance provably reconstructs its occurrence's exact leaves.
        # If any instance diverges (a shape the localize/translate model cannot
        # reproduce), the whole component is REJECTED and its leaves fall back
        # to singletons — geometry is never silently lost or distorted.
        if not _place_op_reconstructs(place_op, ordered):
            continue
        definitions[definition.def_hash] = definition
        place_ops.append(place_op)
        claimed_paths.extend(paths)

    # Singletons: every leaf not inside a claimed component occurrence.
    claimed_leaf_ids: set[str] = set()
    for path in claimed_paths:
        occ = index.by_path.get(path)
        if occ is None:
            continue
        for leaf in iter_l1_leaves(occ.tree_node):
            claimed_leaf_ids.add(leaf["_id"])
    singletons = [
        leaf for leaf in iter_l1_leaves(index.root.tree_node)
        if leaf["_id"] not in claimed_leaf_ids
    ]
    singletons.sort(key=lambda leaf: (
        canon_op(leaf, _ZERO), leaf["source_element_id"]))

    place_ops.sort(key=lambda op: (-op.savings_leaves, op.def_hash))
    return ComponentLibrary(
        definitions=dict(definitions),
        place_ops=tuple(place_ops),
        singletons_leaves=tuple(singletons),
    )


def prove_execution_fidelity(
    library: ComponentLibrary,
    index: Any,
) -> ComponentLibrary:
    """Return the same analytical library with execution proofs attached.

    Discovery and authorization are deliberately separate stages.  Merkle /
    TemplateCanon is the cheap, broad analysis pass; ``FidelityCanon`` is paid
    only before a caller considers a model-writing optimization.  This keeps
    ordinary naming, cost and dedup workloads fast while making native-group
    eligibility explicit and fail-closed.
    """

    if not isinstance(library, ComponentLibrary):
        raise ComponentSchemaError(
            "prove_execution_fidelity needs a ComponentLibrary")
    if not (hasattr(index, "occurrences_of") and hasattr(index, "root_hash")):
        raise ComponentSchemaError(
            "prove_execution_fidelity needs a MerkleIndex")

    proven: list[PlaceGroupOp] = []
    for place_op in library.place_ops:
        ordered = sorted(
            index.occurrences_of(place_op.def_hash),
            key=lambda occurrence: (occurrence.origin_mm, occurrence.path),
        )
        proof = _place_op_fidelity_proof(place_op, ordered)
        proven.append(PlaceGroupOp(
            def_hash=place_op.def_hash,
            definition=place_op.definition,
            instances=place_op.instances,
            fidelity_proof=proof,
        ))
    return ComponentLibrary(
        definitions=library.definitions,
        place_ops=tuple(proven),
        singletons_leaves=library.singletons_leaves,
    )


def place_group_ops(index: Any) -> tuple[PlaceGroupOp, ...]:
    """Analytical place-group ops; no execution proof is implied."""

    return build_library(index).place_ops


# ---------------------------------------------------------------------------
# Expansion + round-trip proof
# ---------------------------------------------------------------------------


def expand_library(lib: ComponentLibrary) -> list[L1Node]:
    """Expand every instance + singletons back into a flat leaf list.

    Property C-RT: the canonical absolute-op multiset of this equals that of
    the original tree's leaves — the library reproduces the building exactly.
    Ids are NOT regenerated here so the geometry round-trip is comparable to the
    source; a placed emission would use ``instantiate(..., regenerate_ids=True)``.
    """

    if not isinstance(lib, ComponentLibrary):
        raise ComponentSchemaError("expand_library needs a ComponentLibrary")
    out: list[L1Node] = []
    for op in lib.place_ops:
        for instance in op.instances:
            out.extend(instantiate(
                op.definition, instance.offset_mm,
                instance_index=instance.instance_index,
                regenerate_ids=False))
    out.extend(lib.singletons_leaves)
    return out


def _abs_multiset(leaves: Iterable[L1Node]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for leaf in leaves:
        key = canon_op(leaf, _ZERO)
        counts[key] = counts.get(key, 0) + 1
    return counts


def assert_round_trip(lib: ComponentLibrary, tree: TreeNode) -> None:
    """Raise unless expanding the library reproduces the tree's leaf multiset."""

    expanded = _abs_multiset(expand_library(lib))
    original = _abs_multiset(iter_l1_leaves(tree))
    if expanded != original:
        raise ComponentRoundTripError(
            "component library does not reproduce the source leaf multiset")


def assert_unique_instance_ids(op: PlaceGroupOp) -> None:
    """Raise if two instances of a place-group would share a leaf id."""

    seen: set[str] = set()
    for instance in op.instances:
        for leaf in instantiate(
                op.definition, instance.offset_mm,
                instance_index=instance.instance_index, regenerate_ids=True):
            if leaf["source_element_id"] in seen:
                raise ComponentSchemaError(
                    "instances share a source_element_id after regeneration")
            seen.add(leaf["source_element_id"])


__all__ = [
    "ComponentDefinition",
    "ComponentError",
    "ComponentFidelityProof",
    "ComponentInstance",
    "ComponentLibrary",
    "ComponentRoundTripError",
    "ComponentSchemaError",
    "PlaceGroupOp",
    "_place_op_fidelity_proof",
    "_place_op_fidelity_mismatches",
    "assert_round_trip",
    "assert_unique_instance_ids",
    "build_library",
    "component_enabled",
    "expand_library",
    "extract_component",
    "instantiate",
    "place_group_ops",
    "prove_execution_fidelity",
]
