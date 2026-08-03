"""Offline assembly and navigation for the DECOMPILE L4 Passport.

SERVE is deliberately a read-only stage.  It combines the already-computed
FOLD, NAME, and VERIFY results, but never calls Revit, the bridge, or an
extractor.  First-time decompilation remains an operator/admin workflow; this
module only provides the inert JSON/cache primitives needed by that workflow.

``Passport`` is a deeply frozen ``dict``/``list``-compatible value.  Standard
``json.dumps`` can serialize it directly, while :meth:`Passport.to_dict`
returns a detached mutable copy for a persistence or serving boundary.  An
optional geometry section joins the exact Tier-G store and instance index
without changing the legacy semantic-only representation.
"""
from __future__ import annotations

import copy
import json
import math
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, TypeAlias, cast

from kukai.ir.decompile.dependencies import (
    DependencyManifest,
    TargetContract,
    build_dependency_manifest,
)
from kukai.ir.decompile.fold import TreeNode, iter_l1_leaves
from kukai.ir.decompile.geom_extract import (
    GeometryExtraction,
    GeometryExtractionError,
    geometry_hash,
)
from kukai.ir.decompile.group_extract import GroupIndexPayloadError
from kukai.ir.decompile.group_relations import (
    GroupIndexInput,
    GroupRelationsAnalysis,
    analyze_group_relations,
)
from kukai.ir.decompile.name import NameResult, ShapeClassification
from kukai.ir.decompile.honesty import (
    BuildStageState,
    BuildStatuses,
    EquivalenceClaim,
    EquivalenceScope,
    EquivalenceState,
    FidelityAssessment,
    require_scope_for_equivalence_text,
)
from kukai.ir.decompile.recompile import (
    GbSolid,
    GeometryNode,
    GeometrySchemaError,
    GmMesh,
    validate_transform,
)
from kukai.ir.decompile.schema import L0Document, PASSPORT_INJECT_TOKENS
from kukai.ir.decompile.verify import NodeVerdict, VerifyResult


Unknown: TypeAlias = Literal["unknown"]
CacheStatus: TypeAlias = Literal["hit", "stale"]
GeometryPassportInput: TypeAlias = GeometryExtraction | Mapping[str, Any]

PASSPORT_QUERY_PAGE_SIZE = 100
PASSPORT_QUERY_MAX_PAGE_SIZE = 500
PASSPORT_NODE_NOT_FOUND = "KIR-S001"

_TOP_UNIT_KINDS = frozenset({
    "apartment", "core", "mop", "room", "zone",
})
_LEAF_DETAIL_KINDS = frozenset({
    "op", "atom", "grid_array", "row", "atom_cluster", "atom_summary",
})


class PassportError(ValueError):
    """Base class for fail-closed Passport contract errors."""


class PassportAssemblyError(PassportError):
    """FOLD/NAME/VERIFY inputs cannot safely be assembled as one Passport."""


class PassportQueryRefusal(PassportError):
    """Typed fail-closed result for an unknown cached Passport node id."""

    code = PASSPORT_NODE_NOT_FOUND

    def __init__(self, node_id: Any) -> None:
        self.node_id = node_id
        super().__init__(f"Passport contains no node_id {node_id!r}")

    def to_dict(self) -> dict[str, Any]:
        """Return the endpoint-ready typed diagnostic envelope."""

        return {
            "ok": False,
            "diagnostics": [{
                "code": self.code,
                "field_name": "node_id",
                "message_ru": (
                    "узел отсутствует в кэшированном паспорте; "
                    "идентификатор не угадан"
                ),
                "got": self.node_id,
            }],
        }


class FrozenJSONList(list[Any]):
    """A JSON-serializable list whose contents cannot be changed."""

    def __init__(self, values: Iterable[Any] = ()) -> None:
        list.__init__(self, (_freeze_json(value) for value in values))

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("frozen JSON values cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __copy__(self) -> "FrozenJSONList":
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> "FrozenJSONList":
        return self


class FrozenJSONDict(dict[str, Any]):
    """A JSON-serializable mapping whose values are recursively frozen."""

    def __init__(self, values: Mapping[str, Any] | None = None) -> None:
        materialized = values or {}
        if any(not isinstance(key, str) for key in materialized):
            raise TypeError("frozen JSON object keys must be strings")
        dict.__init__(self, (
            (key, _freeze_json(value)) for key, value in materialized.items()
        ))

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("frozen JSON values cannot be mutated")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __ior__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable

    def __copy__(self) -> "FrozenJSONDict":
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> "FrozenJSONDict":
        return self


def _freeze_json(value: Any) -> Any:
    if isinstance(value, (FrozenJSONDict, FrozenJSONList)):
        return value
    if isinstance(value, Mapping):
        return FrozenJSONDict(cast(Mapping[str, Any], value))
    if isinstance(value, (list, tuple)):
        return FrozenJSONList(value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PassportAssemblyError("Passport facts must be finite JSON")
        return value
    raise PassportAssemblyError(
        f"Passport contains a non-JSON value: {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    return value


class Passport(FrozenJSONDict):
    """A deeply immutable, directly JSON-serializable L4 Passport."""

    def to_dict(self) -> dict[str, Any]:
        """Return a detached mutable JSON object."""

        return cast(dict[str, Any], _thaw_json(self))

    def to_bytes(self) -> bytes:
        """Return the canonical byte representation used for determinism."""

        return passport_bytes(self)


def _walk_tree(root: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        children = node.get("children", [])
        if not isinstance(children, Sequence) or isinstance(
                children, (str, bytes, bytearray)):
            raise PassportAssemblyError("tree.children must be a JSON array")
        for child in reversed(children):
            if not isinstance(child, Mapping):
                raise PassportAssemblyError("tree child must be an object")
            stack.append(child)


def _tree_structure_signature(root: Mapping[str, Any]) -> tuple[Any, ...]:
    """Capture identity-bearing structure that NAME is not allowed to alter."""

    payload = root.get("payload")
    payload_id = payload.get("_id") if isinstance(payload, Mapping) else None
    members = root.get("members", [])
    if not isinstance(members, Sequence) or isinstance(
            members, (str, bytes, bytearray)):
        raise PassportAssemblyError("tree.members must be a JSON array")
    member_ids: list[str] = []
    for member in members:
        if not isinstance(member, Mapping) or not isinstance(
                member.get("_id"), str):
            raise PassportAssemblyError("tree member has no typed L1 _id")
        member_ids.append(member["_id"])
    children = root.get("children", [])
    if not isinstance(children, Sequence) or isinstance(
            children, (str, bytes, bytearray)):
        raise PassportAssemblyError("tree.children must be a JSON array")
    return (
        root.get("node_id"),
        root.get("kind"),
        payload_id,
        tuple(member_ids),
        tuple(_tree_structure_signature(cast(Mapping[str, Any], child))
              for child in children),
    )


def _l1_by_id(root: TreeNode) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for leaf in iter_l1_leaves(root):
        leaf_id = leaf.get("_id")
        if not isinstance(leaf_id, str) or not leaf_id:
            raise PassportAssemblyError("tree leaf has no typed L1 _id")
        if leaf_id in result:
            raise PassportAssemblyError(f"duplicate L1 _id in tree: {leaf_id}")
        result[leaf_id] = leaf
    return result


def _validate_name_tree(fold_tree: TreeNode, named_tree: TreeNode) -> None:
    if fold_tree.get("kind") != "building" or named_tree.get("kind") != "building":
        raise PassportAssemblyError("Passport requires a building root")
    if _tree_structure_signature(fold_tree) != _tree_structure_signature(named_tree):
        raise PassportAssemblyError(
            "NAME tree identity/structure does not match the supplied FOLD tree")
    folded = _l1_by_id(fold_tree)
    named = _l1_by_id(named_tree)
    if folded.keys() != named.keys():
        raise PassportAssemblyError("NAME tree does not preserve FOLD leaf ids")
    for leaf_id in folded:
        if folded[leaf_id] != named[leaf_id]:
            raise PassportAssemblyError(
                f"NAME tree mutated L1 payload {leaf_id!r}")


def _unknown_shape() -> ShapeClassification:
    return {
        "shape": "unknown",
        "corners": 0,
        "aspect": None,
        "convex": False,
        "courtyard": False,
        "curvilinear_perimeter": False,
        "dims_mm": None,
        "area_m2": None,
        "valid": False,
        "description": "контур не определён",
    }


def _shape_from_name(name_result: Mapping[str, Any]) -> dict[str, Any]:
    raw = name_result.get("shape")
    if not isinstance(raw, Mapping):
        return copy.deepcopy(_unknown_shape())
    shape = copy.deepcopy(dict(raw))
    if not isinstance(shape.get("shape"), str) or not shape["shape"]:
        shape["shape"] = "unknown"
    if not isinstance(shape.get("description"), str) \
            or not shape["description"]:
        shape["description"] = "unknown"
    return shape


def _verdict_index(
    verdicts: Sequence[NodeVerdict],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for verdict in verdicts:
        if verdict.node_id in result:
            raise PassportAssemblyError(
                f"VERIFY returned duplicate verdict {verdict.node_id!r}")
        result[verdict.node_id] = verdict.to_dict()
    return result


def _fidelity_index(
    assessments: Sequence[FidelityAssessment],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for assessment in assessments:
        if assessment.node_id in result:
            raise PassportAssemblyError(
                "VERIFY returned duplicate fidelity assessment "
                f"{assessment.node_id!r}")
        result[assessment.node_id] = assessment.to_dict()
    return result


def _unknown_verdict(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "node_id": payload.get("_id", "unknown"),
        "source_element_id": payload.get("source_element_id", "unknown"),
        "status": "unknown",
        "detail": "VERIFY supplied no verdict for this L1 leaf",
        "max_deviation_mm": None,
    }


def _unknown_fidelity(payload: Mapping[str, Any]) -> dict[str, Any]:
    kind = payload.get("kind")
    return {
        "node_id": payload.get("_id", "unknown"),
        "source_element_id": payload.get("source_element_id", "unknown"),
        "verdict": "opaque" if kind == "atom" else "approximate",
        "reasons": [
            "verification_evidence_missing",
            "dependency_unresolved",
        ],
        "detail": (
            "VERIFY supplied no strict fidelity assessment for this L1 leaf; "
            "Passport did not infer a stronger verdict"
        ),
        "dependency_resolved": False,
        "legacy_verify_status": "unknown",
        "source_reason": (
            copy.deepcopy(payload.get("reason")) if kind == "atom" else None
        ),
    }


def _aggregate_verdict(counts: Counter[str]) -> dict[str, Any]:
    total = sum(counts.values())
    ordered_counts = {
        status: counts.get(status, 0)
        for status in ("exact", "approximate", "failed", "unknown")
    }
    if total == 0:
        return {
            "status": "unknown",
            "detail": "node contains no L1 leaves to verify",
            "counts": ordered_counts,
        }
    if counts.get("failed", 0):
        status = "failed"
    elif counts.get("unknown", 0):
        status = "unknown"
    elif counts.get("approximate", 0):
        status = "approximate"
    else:
        status = "exact"
    return {
        "status": status,
        "detail": f"aggregate of {total} descendant L1 leaf verdict(s)",
        "counts": ordered_counts,
    }


def _aggregate_fidelity(counts: Counter[str]) -> dict[str, Any]:
    total = sum(counts.values())
    ordered_counts = {
        verdict: counts.get(verdict, 0)
        for verdict in (
            "native_exact",
            "form_exact",
            "approximate",
            "opaque",
            "generated_accounted",
        )
    }
    if total == 0:
        return {
            "verdict": "opaque",
            "detail": "node contains no L1 leaves for fidelity assessment",
            "counts": ordered_counts,
            "dependency_resolved": 0,
            "dependency_unresolved": 0,
        }
    # An aggregate is no stronger than its weakest represented leaf.  The
    # counts remain authoritative; the scalar only supports compact browsing.
    if counts.get("opaque", 0):
        verdict = "opaque"
    elif counts.get("approximate", 0):
        verdict = "approximate"
    elif counts.get("generated_accounted", 0):
        verdict = "generated_accounted"
    elif counts.get("form_exact", 0):
        verdict = "form_exact"
    else:
        verdict = "native_exact"
    return {
        "verdict": verdict,
        "detail": f"aggregate of {total} descendant fidelity assessment(s)",
        "counts": ordered_counts,
    }


def _join_verdicts(
    node: dict[str, Any],
    verdicts: Mapping[str, dict[str, Any]],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    direct: list[dict[str, Any]] = []
    payload = node.get("payload")
    if isinstance(payload, Mapping):
        leaf_verdict = copy.deepcopy(
            verdicts.get(cast(str, payload.get("_id")), _unknown_verdict(payload)))
        direct.append(leaf_verdict)
        counts[cast(str, leaf_verdict["status"])] += 1

    members = node.get("members", [])
    if not isinstance(members, list):
        raise PassportAssemblyError("copied tree.members must be an array")
    for member in members:
        if not isinstance(member, Mapping):
            raise PassportAssemblyError("copied tree member must be an object")
        member_verdict = copy.deepcopy(
            verdicts.get(cast(str, member.get("_id")), _unknown_verdict(member)))
        direct.append(member_verdict)
        counts[cast(str, member_verdict["status"])] += 1
    if members:
        node["member_verdicts"] = direct[-len(members):]

    children = node.get("children", [])
    if not isinstance(children, list):
        raise PassportAssemblyError("copied tree.children must be an array")
    for child in children:
        if not isinstance(child, dict):
            raise PassportAssemblyError("copied tree child must be an object")
        counts.update(_join_verdicts(child, verdicts))

    if len(direct) == 1 and payload is not None and not children and not members:
        node["verdict"] = direct[0]
    else:
        node["verdict"] = _aggregate_verdict(counts)
    return counts


def _join_fidelity(
    node: dict[str, Any],
    fidelity: Mapping[str, dict[str, Any]],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    direct: list[dict[str, Any]] = []
    payload = node.get("payload")
    if isinstance(payload, Mapping):
        assessment = copy.deepcopy(
            fidelity.get(
                cast(str, payload.get("_id")),
                _unknown_fidelity(payload),
            )
        )
        direct.append(assessment)
        counts[cast(str, assessment["verdict"])] += 1

    members = node.get("members", [])
    if not isinstance(members, list):
        raise PassportAssemblyError("copied tree.members must be an array")
    for member in members:
        if not isinstance(member, Mapping):
            raise PassportAssemblyError("copied tree member must be an object")
        assessment = copy.deepcopy(
            fidelity.get(
                cast(str, member.get("_id")),
                _unknown_fidelity(member),
            )
        )
        direct.append(assessment)
        counts[cast(str, assessment["verdict"])] += 1
    if members:
        node["member_fidelity"] = direct[-len(members):]

    children = node.get("children", [])
    if not isinstance(children, list):
        raise PassportAssemblyError("copied tree.children must be an array")
    for child in children:
        if not isinstance(child, dict):
            raise PassportAssemblyError("copied tree child must be an object")
        counts.update(_join_fidelity(child, fidelity))

    if len(direct) == 1 and payload is not None and not children and not members:
        node["fidelity"] = direct[0]
    else:
        node["fidelity"] = _aggregate_fidelity(counts)
    return counts


def _node_counts(root: Mapping[str, Any]) -> Counter[str]:
    return Counter(cast(str, node.get("kind", "unknown"))
                   for node in _walk_tree(root))


def _known_height(root: Mapping[str, Any]) -> float | Unknown:
    facts = root.get("facts")
    dims = facts.get("dims_mm") if isinstance(facts, Mapping) else None
    if isinstance(dims, Sequence) and not isinstance(
            dims, (str, bytes, bytearray)) and len(dims) == 3:
        height = dims[2]
        if isinstance(height, (int, float)) and not isinstance(height, bool) \
                and math.isfinite(float(height)):
            return float(height)
    return "unknown"


def _known_footprint_dims(shape: Mapping[str, Any]) -> list[float] | Unknown:
    dims = shape.get("dims_mm")
    if isinstance(dims, Sequence) and not isinstance(
            dims, (str, bytes, bytearray)) and len(dims) >= 2:
        values = dims[:2]
        if all(isinstance(value, (int, float)) and not isinstance(value, bool)
               and math.isfinite(float(value)) for value in values):
            return [float(value) for value in values]
    return "unknown"


def _geometry_definition(
    value: Any,
    field_name: str,
) -> GbSolid | GmMesh:
    if not isinstance(value, Mapping):
        raise PassportAssemblyError(f"{field_name} must be an object")
    try:
        if value.get("tier") == "Gb":
            return GbSolid.from_dict(value, field_name)
        if value.get("tier") == "Gm":
            return GmMesh.from_dict(value, field_name)
    except GeometrySchemaError as exc:
        raise PassportAssemblyError(
            f"{field_name} is invalid: {exc}") from exc
    raise PassportAssemblyError(
        f"{field_name}.tier must be 'Gb' or 'Gm'")


def _geometry_payload(
    geometry: GeometryPassportInput,
) -> Mapping[str, Any]:
    if isinstance(geometry, GeometryExtraction):
        return geometry.to_dict()
    if isinstance(geometry, Mapping):
        return geometry
    raise PassportAssemblyError(
        "geometry must be a GeometryExtraction or geometry bundle")


def _geometry_section(
    document: L0Document,
    geometry: GeometryPassportInput,
) -> dict[str, Any]:
    """Validate and detach the complete EXTRACT → RECOMPILE geometry join."""

    raw_input = _geometry_payload(geometry)
    required = {"geometry_index", "geometry_store", "nodes"}
    missing = sorted(required - set(raw_input))
    if missing:
        raise PassportAssemblyError(
            "geometry bundle is missing: " + ", ".join(missing))

    # The frozen index deliberately does not repeat category identity: nodes
    # own it.  Rehydrate the complete typed bundle here so the join cannot
    # infer a category from L0 by accident.  This matters for class-only L0
    # pseudo categories such as ``DirectShape``: its real OST_* category is
    # carried only by the geometry node.  A unique match is accepted; an
    # ambiguous or ordinary-category mismatch fails closed.
    elements_by_id = {
        element.element_id: element for element in document.elements
    }
    persisted_bundle: dict[str, Any] = {
        "geometry_store": raw_input["geometry_store"],
        "geometry_index": raw_input["geometry_index"],
        "nodes": raw_input["nodes"],
        "degradations": raw_input.get("degradations", []),
        "failures": raw_input.get("failures", []),
    }
    if "detail_levels" in raw_input:
        persisted_bundle["detail_levels"] = raw_input["detail_levels"]
    try:
        typed_geometry = GeometryExtraction.from_dict(
            persisted_bundle,
            categories_by_id={
                element_id: element.category
                for element_id, element in elements_by_id.items()
            },
        )
    except GeometryExtractionError as exc:
        raise PassportAssemblyError(
            f"geometry bundle cannot be rehydrated: {exc}") from exc
    raw = typed_geometry.to_dict()
    resolved_categories = {
        record.element_id: record.category
        for record in typed_geometry.index
    }

    raw_store = raw.get("geometry_store")
    if not isinstance(raw_store, Mapping):
        raise PassportAssemblyError("geometry.geometry_store must be an object")
    if any(not isinstance(geo_hash, str) for geo_hash in raw_store):
        raise PassportAssemblyError(
            "geometry.geometry_store keys must be geometry hashes")
    store: dict[str, Any] = {}
    for geo_hash in sorted(raw_store):
        if not isinstance(geo_hash, str) or not geo_hash:
            raise PassportAssemblyError(
                "geometry.geometry_store keys must be geometry hashes")
        definition = _geometry_definition(
            raw_store[geo_hash],
            f"geometry.geometry_store[{geo_hash!r}]",
        )
        try:
            computed_hash = geometry_hash(definition)
        except GeometryExtractionError as exc:
            raise PassportAssemblyError(
                f"geometry definition {geo_hash!r} cannot be hashed: {exc}"
            ) from exc
        if computed_hash != geo_hash:
            raise PassportAssemblyError(
                f"geometry store hash mismatch for {geo_hash!r}")
        store[geo_hash] = definition.to_dict()

    raw_index = raw.get("geometry_index")
    if not isinstance(raw_index, Mapping):
        raise PassportAssemblyError("geometry.geometry_index must be an object")
    if any(not isinstance(element_id, str) for element_id in raw_index):
        raise PassportAssemblyError(
            "geometry.geometry_index keys must be element-id strings")
    foreign_ids = sorted(set(raw_index) - set(elements_by_id))
    if foreign_ids:
        raise PassportAssemblyError(
            "geometry index contains ids absent from L0: "
            + ", ".join(foreign_ids[:5]))

    index: dict[str, dict[str, Any]] = {}
    expected_occurrences: dict[
        tuple[str, str], list[tuple[float, ...]]
    ] = {}
    for element_id in sorted(raw_index):
        if not isinstance(element_id, str) or not element_id:
            raise PassportAssemblyError(
                "geometry.geometry_index keys must be element-id strings")
        row = raw_index[element_id]
        if not isinstance(row, Mapping) or set(row) != {
                "tier", "geo_hash", "transform"}:
            raise PassportAssemblyError(
                f"geometry.geometry_index[{element_id!r}] has invalid fields")
        tier = row.get("tier")
        geo_hash = row.get("geo_hash")
        transform = row.get("transform")
        if tier == "A":
            if geo_hash is not None or transform is not None:
                raise PassportAssemblyError(
                    f"Tier A geometry row {element_id!r} cannot carry a ref")
            index[element_id] = {
                "tier": "A", "geo_hash": None, "transform": None,
            }
            continue
        if tier not in {"Gb", "Gm"}:
            raise PassportAssemblyError(
                f"geometry row {element_id!r} has unsupported tier {tier!r}")
        if not isinstance(geo_hash, str) or geo_hash not in store:
            raise PassportAssemblyError(
                f"geometry row {element_id!r} has an unresolved geo_hash")
        if store[geo_hash].get("tier") != tier:
            raise PassportAssemblyError(
                f"geometry row {element_id!r} tier disagrees with its store")
        if not isinstance(transform, Sequence) or isinstance(
                transform, (str, bytes, bytearray)):
            raise PassportAssemblyError(
                f"geometry row {element_id!r} has invalid transform")
        try:
            validated_transform = validate_transform(
                tuple(transform),
                f"geometry.geometry_index[{element_id!r}].transform",
            )
        except GeometrySchemaError as exc:
            raise PassportAssemblyError(
                f"geometry row {element_id!r} has invalid transform: {exc}"
            ) from exc
        index[element_id] = {
            "tier": tier,
            "geo_hash": geo_hash,
            "transform": list(validated_transform),
        }
        occurrence_key = (geo_hash, resolved_categories[element_id])
        expected_occurrences.setdefault(occurrence_key, []).append(
            validated_transform)

    raw_nodes = raw.get("nodes")
    if not isinstance(raw_nodes, Sequence) or isinstance(
            raw_nodes, (str, bytes, bytearray)):
        raise PassportAssemblyError("geometry.nodes must be an array")
    nodes: list[GeometryNode] = []
    seen_node_ids: set[str] = set()
    node_occurrences: dict[
        tuple[str, str], list[tuple[float, ...]]
    ] = {}
    for node_index, value in enumerate(raw_nodes):
        try:
            node = (
                value if isinstance(value, GeometryNode)
                else GeometryNode.from_dict(
                    value, f"geometry.nodes[{node_index}]")
            )
            node_hash = geometry_hash(node.geometry)
        except (GeometrySchemaError, GeometryExtractionError) as exc:
            raise PassportAssemblyError(
                f"geometry.nodes[{node_index}] is invalid: {exc}") from exc
        if node.node_id in seen_node_ids:
            raise PassportAssemblyError(
                f"geometry.nodes repeats node_id {node.node_id!r}")
        seen_node_ids.add(node.node_id)
        if node_hash not in store:
            raise PassportAssemblyError(
                f"geometry node {node.node_id!r} is absent from the store")
        if node.geometry.to_dict() != store[node_hash]:
            raise PassportAssemblyError(
                f"geometry node {node.node_id!r} disagrees with the store")
        occurrence_key = (node_hash, node.category)
        if occurrence_key in node_occurrences:
            raise PassportAssemblyError(
                "geometry nodes duplicate one category/definition group")
        node_occurrences[occurrence_key] = list(node.transforms)
        nodes.append(node)

    if set(node_occurrences) != set(expected_occurrences):
        raise PassportAssemblyError(
            "geometry nodes do not cover the Tier-G index groups exactly")
    for occurrence_key, transforms in expected_occurrences.items():
        if sorted(transforms) != sorted(node_occurrences[occurrence_key]):
            raise PassportAssemblyError(
                "geometry node transforms disagree with the element index")

    return {
        "geometry_index": index,
        "geometry_store": store,
        "nodes": [node.to_dict() for node in sorted(
            nodes, key=lambda item: item.node_id)],
    }


def assemble_passport(
    document: L0Document,
    fold_tree: TreeNode,
    name_result: NameResult,
    verify_result: VerifyResult,
    geometry: GeometryPassportInput | None = None,
    *,
    dependencies: DependencyManifest | None = None,
    target_contract: TargetContract | str | None = None,
    build_status: BuildStatuses | None = None,
    equivalence: EquivalenceClaim | None = None,
    group_index: GroupIndexInput | None = None,
) -> Passport:
    """Assemble immutable L4 from matching, already-computed stage results.

    No input is mutated.  NAME's copied/labeled tree becomes the source for a
    second deep copy, and VERIFY's standalone L1 verdicts are joined there.
    Missing individual verdict facts are represented as ``"unknown"`` rather
    than guessed; verdicts for foreign leaves are rejected as a mismatched
    pipeline invocation.  When supplied, ``geometry`` is validated against L0
    and the frozen Tier-G schema before it is joined and recursively frozen.
    STEP-0 dependency, build-status, equivalence, and fidelity sections are
    additive and never upgrade legacy VERIFY evidence.  An optional group
    index adds relations/definitions only; it never reparents the named tree.
    """

    named_tree = name_result.get("tree")
    if not isinstance(named_tree, dict):
        raise PassportAssemblyError("NAME result has no tree object")
    _validate_name_tree(fold_tree, cast(TreeNode, named_tree))
    folded_leaves = _l1_by_id(fold_tree)
    verdicts = _verdict_index(verify_result.verdicts)
    foreign = sorted(verdicts.keys() - folded_leaves.keys())
    if foreign:
        raise PassportAssemblyError(
            "VERIFY verdicts belong to another tree: " + ", ".join(foreign[:5]))
    fidelity = _fidelity_index(verify_result.fidelity_verdicts)
    foreign_fidelity = sorted(fidelity.keys() - folded_leaves.keys())
    if foreign_fidelity:
        raise PassportAssemblyError(
            "VERIFY fidelity assessments belong to another tree: "
            + ", ".join(foreign_fidelity[:5]))

    if dependencies is None:
        dependencies = build_dependency_manifest(
            document,
            target_contract=(
                TargetContract.SAME_ENVIRONMENT
                if target_contract is None else target_contract
            ),
        )
    elif not isinstance(dependencies, DependencyManifest):
        raise PassportAssemblyError(
            "dependencies must be a DependencyManifest or null")
    elif target_contract is not None:
        try:
            requested_contract = (
                target_contract if isinstance(target_contract, TargetContract)
                else TargetContract(target_contract)
            )
        except (TypeError, ValueError) as exc:
            raise PassportAssemblyError(
                f"unsupported target_contract: {target_contract!r}") from exc
        if requested_contract is not dependencies.target_contract:
            raise PassportAssemblyError(
                "target_contract disagrees with dependency manifest")
    source_environment = dependencies.source_environment
    if (
        source_environment.doc_name != document.doc_name
        or source_environment.revit_version != document.revit_version
        or source_environment.units != document.units
    ):
        raise PassportAssemblyError(
            "dependency manifest belongs to another source environment")
    source_by_id = {
        element.element_id: element for element in document.elements
    }
    source_ids = set(source_by_id)
    foreign_dependency_ids = sorted({
        source_id
        for definition in dependencies.definitions
        for source_id in definition.required_by
        if source_id not in source_ids
    })
    if foreign_dependency_ids:
        raise PassportAssemblyError(
            "dependency manifest references element ids absent from L0: "
            + ", ".join(foreign_dependency_ids[:5]))
    matching_type_identity_ids = {
        source_id
        for definition in dependencies.definitions
        for source_id in definition.required_by
        if (
            definition.identity.category
            == source_by_id[source_id].category
            and definition.identity.type_name
            == source_by_id[source_id].type_name
        )
    }
    missing_type_identity_ids = sorted(
        source_ids - matching_type_identity_ids)
    if missing_type_identity_ids:
        raise PassportAssemblyError(
            "dependency manifest has no matching category/type identity for "
            "element ids: " + ", ".join(missing_type_identity_ids[:5]))
    represented_dependency_ids = {
        source_id
        for definition in dependencies.definitions
        for source_id in definition.required_by
    }
    missing_dependency_ids = sorted(source_ids - represented_dependency_ids)
    if missing_dependency_ids:
        raise PassportAssemblyError(
            "dependency manifest omits L0 source element ids: "
            + ", ".join(missing_dependency_ids[:5]))

    group_analysis: GroupRelationsAnalysis | None = None
    if group_index is not None:
        folded_source_ids = []
        for leaf_id, leaf in folded_leaves.items():
            source_id = leaf.get("source_element_id")
            if not isinstance(source_id, str) or not source_id:
                raise PassportAssemblyError(
                    f"tree leaf {leaf_id!r} has no source_element_id")
            folded_source_ids.append(source_id)
        if Counter(folded_source_ids) != Counter(source_ids):
            raise PassportAssemblyError(
                "group relations require one canonical tree leaf per L0 "
                "source element")
        try:
            group_analysis = analyze_group_relations(
                group_index, source_ids)
        except (GroupIndexPayloadError, TypeError, ValueError) as exc:
            raise PassportAssemblyError(
                f"invalid group_index: {exc}") from exc

    if build_status is None:
        build_status = BuildStatuses.initial(
            unresolved_dependencies=dependencies.unresolved_count)
    elif not isinstance(build_status, BuildStatuses):
        raise PassportAssemblyError(
            "build_status must be BuildStatuses or null")
    if (build_status.groundable.state is BuildStageState.PASSED
            and dependencies.unresolved_count):
        raise PassportAssemblyError(
            "groundable=passed conflicts with unresolved dependencies")
    if equivalence is None:
        equivalence = EquivalenceClaim.unverified(
            EquivalenceScope.NATIVE_SEMANTIC)
    elif not isinstance(equivalence, EquivalenceClaim):
        raise PassportAssemblyError(
            "equivalence must be EquivalenceClaim or null")
    if equivalence.state is EquivalenceState.VERIFIED:
        if (len(fidelity) != len(folded_leaves)
                or verify_result.fidelity_summary.fidelity_total
                != len(folded_leaves)):
            raise PassportAssemblyError(
                "verified equivalence requires one fidelity assessment per leaf")
        if (build_status.roundtrip_verified.state
                is not BuildStageState.PASSED):
            raise PassportAssemblyError(
                "verified equivalence requires roundtrip_verified=passed")
        fidelity_summary = verify_result.fidelity_summary
        native_supported = fidelity_summary.native_exact
        form_supported = native_supported + fidelity_summary.form_exact
        if (equivalence.scope is EquivalenceScope.NATIVE_SEMANTIC
                and native_supported != fidelity_summary.fidelity_total):
            raise PassportAssemblyError(
                "native_semantic equivalence requires every leaf to be "
                "native_exact")
        if (equivalence.scope in {
                EquivalenceScope.FORM, EquivalenceScope.DOCUMENT}
                and form_supported != fidelity_summary.fidelity_total):
            raise PassportAssemblyError(
                f"{equivalence.scope.value} equivalence requires every leaf "
                "to have exact native/form evidence")
        if (equivalence.scope is EquivalenceScope.DOCUMENT
                and dependencies.unresolved_count):
            raise PassportAssemblyError(
                "document equivalence cannot be verified with unresolved "
                "dependency records")

    joined_tree = copy.deepcopy(named_tree)
    joined_counts = _join_verdicts(joined_tree, verdicts)
    _join_fidelity(joined_tree, fidelity)
    shape = _shape_from_name(name_result)
    kinds = _node_counts(joined_tree)
    verify_summary = verify_result.summary.to_dict()
    verify_summary.update(verify_result.fidelity_summary.to_dict())
    verify_summary.update({
        "reversible": verify_result.reversible,
        "reversibility_detail": verify_result.reversibility_detail,
        "verdicts_joined": len(verdicts),
        "unknown_verdicts": joined_counts.get("unknown", 0),
        "fidelity_assessments_joined": len(fidelity),
        "unknown_fidelity_assessments": len(folded_leaves) - len(fidelity),
    })
    gestalt = name_result.get("gestalt")
    if not isinstance(gestalt, str) or not gestalt.strip():
        gestalt = "unknown"

    stats: dict[str, Any] = {
        "floors": kinds.get("floor", 0),
        "total_height_mm": _known_height(joined_tree),
        "footprint_shape": shape.get("shape", "unknown"),
        "footprint_dims_mm": _known_footprint_dims(shape),
        "apartments": kinds.get("apartment", 0),
        "rooms": kinds.get("room", 0),
        "elements_total": len(document.elements),
        "ops_lifted": verify_result.summary.op_count,
        "atoms": verify_result.summary.atom_count,
        "compression_ratio": verify_result.summary.compression_ratio,
    }
    payload = {
        "doc_name": document.doc_name,
        "revit_version": document.revit_version,
        "change_stamp": document.change_stamp,
        "gestalt": gestalt.strip(),
        # NAME carries richer honest facts than §2.4's class/dims pair.  Keep
        # that losslessly while retaining the exact §2.4 summary fields above.
        "footprint": shape,
        "tree": joined_tree,
        "stats": stats,
        "verify_summary": verify_summary,
        "dependencies": dependencies.to_dict(),
        "build_status": build_status.to_dict(),
        "equivalence": equivalence.to_dict(),
    }
    if geometry is not None:
        payload["geometry"] = _geometry_section(document, geometry)
    if group_analysis is not None:
        payload["relations"] = group_analysis.relations_dict()
        payload["definitions"] = group_analysis.definitions_dict()
    return Passport(payload)


def build_passport(
    document: L0Document,
    fold_tree: TreeNode,
    name_result: NameResult,
    verify_result: VerifyResult,
    geometry: GeometryPassportInput | None = None,
    *,
    dependencies: DependencyManifest | None = None,
    target_contract: TargetContract | str | None = None,
    build_status: BuildStatuses | None = None,
    equivalence: EquivalenceClaim | None = None,
    group_index: GroupIndexInput | None = None,
) -> Passport:
    """Pipeline-friendly alias for :func:`assemble_passport`."""

    return assemble_passport(
        document,
        fold_tree,
        name_result,
        verify_result,
        geometry,
        dependencies=dependencies,
        target_contract=target_contract,
        build_status=build_status,
        equivalence=equivalence,
        group_index=group_index,
    )


def passport_bytes(passport: Mapping[str, Any]) -> bytes:
    """Serialize a Passport as stable UTF-8 JSON bytes."""

    try:
        rendered = json.dumps(
            passport,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PassportError(f"Passport is not finite JSON: {exc}") from exc
    return rendered.encode("utf-8")


def passport_cache_key(passport: Mapping[str, Any]) -> str:
    """Return the document-scoped §9.3 cache key carried by a Passport."""

    change_stamp = passport.get("change_stamp")
    if not isinstance(change_stamp, str) or not change_stamp:
        raise PassportError("Passport change_stamp must be a non-empty string")
    return change_stamp


def passport_cache_status(
    passport: Mapping[str, Any],
    current_change_stamp: str,
) -> CacheStatus:
    """Decide cache hit/stale without triggering any decompilation work."""

    if not isinstance(current_change_stamp, str) or not current_change_stamp:
        raise PassportError("current_change_stamp must be a non-empty string")
    return (
        "hit"
        if passport_cache_key(passport) == current_change_stamp
        else "stale"
    )


def is_passport_cache_hit(
    passport: Mapping[str, Any],
    current_change_stamp: str,
) -> bool:
    """Boolean convenience wrapper for :func:`passport_cache_status`."""

    return passport_cache_status(passport, current_change_stamp) == "hit"


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PassportError(f"value is not finite JSON: {exc}") from exc


def estimate_passport_tokens(value: str | Mapping[str, Any]) -> int:
    """Return SERVE's deterministic conservative context-token estimate.

    The repository's Russian/mixed-context budget convention is one token per
    three Unicode characters.  Rounding up prevents a sub-token remainder
    from escaping the hard 800-token injection ceiling.
    """

    rendered = value if isinstance(value, str) else _canonical_json(value)
    return 0 if not rendered else (len(rendered) + 2) // 3


def _compact_macro(macro: Any) -> dict[str, Any] | None:
    if not isinstance(macro, Mapping):
        return None
    result: dict[str, Any] = {}
    for key in sorted(macro):
        value = macro[key]
        if key == "diffs" and isinstance(value, Mapping):
            added_total = 0
            removed_total = 0
            for level_name in sorted(value):
                diff = value[level_name]
                if not isinstance(diff, Mapping):
                    continue
                added = diff.get("added", [])
                removed = diff.get("removed", [])
                added_total += len(added) if isinstance(added, Sequence) else 0
                removed_total += (
                    len(removed) if isinstance(removed, Sequence) else 0)
            result["diff_summary"] = {
                "changed_levels": len(value),
                "added": added_total,
                "removed": removed_total,
            }
        elif key in {"levels", "cells"} and isinstance(value, Sequence) \
                and not isinstance(value, (str, bytes, bytearray)):
            singular = "level" if key == "levels" else "cell"
            result[f"{singular}_count"] = len(value)
            if value:
                result[f"{singular}_range"] = [
                    _thaw_json(value[0]), _thaw_json(value[-1])]
        else:
            result[key] = _thaw_json(value)
    return result


def _verdict_status(node: Mapping[str, Any]) -> str:
    verdict = node.get("verdict")
    status = verdict.get("status") if isinstance(verdict, Mapping) else None
    return status if isinstance(status, str) and status else "unknown"


def _toc_node(node: Mapping[str, Any]) -> dict[str, Any]:
    facts = node.get("facts")
    compact_facts: dict[str, Any] = {}
    if isinstance(facts, Mapping):
        for key in ("element_count", "area_m2", "shape"):
            value = facts.get(key)
            if value is not None:
                compact_facts[key] = _thaw_json(value)
    summary: dict[str, Any] = {
        "node_id": node.get("node_id", "unknown"),
        "kind": node.get("kind", "unknown"),
        "label": node.get("label", "unknown") or "unknown",
        "facts": compact_facts,
        "verify_status": _verdict_status(node),
        "children": [],
    }
    macro = node.get("macro")
    if isinstance(macro, Mapping):
        compact: dict[str, Any] = {}
        for key in (
            "type", "base_z_mm", "dz_mm", "level_name",
            "elevation_mm", "semantic_mode", "cell", "cell_mm",
            "discipline", "has_stairs",
        ):
            if key in macro:
                compact[key] = _thaw_json(macro[key])
        levels = macro.get("levels")
        if isinstance(levels, Sequence) and not isinstance(
                levels, (str, bytes, bytearray)) and levels:
            compact["level_count"] = len(levels)
            compact["level_range"] = [
                _thaw_json(levels[0]), _thaw_json(levels[-1])]
        if compact:
            summary["macro"] = compact
    return summary


def _is_leaf_detail(node: Mapping[str, Any]) -> bool:
    if node.get("kind") in _LEAF_DETAIL_KINDS:
        return True
    if isinstance(node.get("payload"), Mapping):
        return True
    members = node.get("members")
    return (
        isinstance(members, Sequence)
        and not isinstance(members, (str, bytes, bytearray))
        and bool(members)
    )


def _top_tree_records(
    root: Mapping[str, Any],
) -> list[tuple[Mapping[str, Any], str | None]]:
    """Return building→sections/stacks→floors→units in breadth-first order."""

    root_id = root.get("node_id")
    if not isinstance(root_id, str) or not root_id:
        raise PassportError("Passport tree root has no node_id")
    records: list[tuple[Mapping[str, Any], str | None]] = []
    queue: deque[tuple[Mapping[str, Any], str | None, bool]] = deque([
        (root, None, False),
    ])
    seen: set[str] = set()
    while queue:
        node, parent_id, below_floor = queue.popleft()
        node_id = node.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise PassportError("Passport tree node has no node_id")
        if node_id in seen:
            raise PassportError(f"duplicate Passport node_id {node_id!r}")
        seen.add(node_id)
        records.append((node, parent_id))

        kind = node.get("kind")
        if below_floor or kind in _TOP_UNIT_KINDS:
            continue
        children = node.get("children", [])
        if not isinstance(children, Sequence) or isinstance(
                children, (str, bytes, bytearray)):
            raise PassportError("Passport tree.children must be an array")
        child_below_floor = kind == "floor"
        for child in children:
            if not isinstance(child, Mapping):
                raise PassportError("Passport tree child must be an object")
            if _is_leaf_detail(child):
                continue
            queue.append((child, node_id, child_below_floor))
    return records


def _inject_base(passport: Mapping[str, Any]) -> dict[str, Any]:
    gestalt = passport.get("gestalt")
    if not isinstance(gestalt, str) or not gestalt:
        gestalt = "unknown"
    stats = passport.get("stats")
    verify = passport.get("verify_summary")
    if not isinstance(stats, Mapping) or not isinstance(verify, Mapping):
        raise PassportError("Passport has no typed stats/verify_summary")
    equivalence = passport.get("equivalence")
    build_status = passport.get("build_status")
    dependencies = passport.get("dependencies")
    legacy_quality_keys = (
        "reversible",
        "exact_pct",
        "approximate_pct",
        "failed_count",
        "lift_coverage",
        "point_geometry_passthrough_pct",
        "compression_ratio",
        "unknown_verdicts",
    )
    fidelity_quality_keys = (
        "native_exact_pct",
        "form_exact_pct",
        "fidelity_approximate_pct",
        "opaque_pct",
        "generated_accounted_pct",
        "dependency_resolved",
        "dependency_unresolved",
        "dependency_resolved_pct",
    )
    result = {
        "gestalt": gestalt,
        "stats": _thaw_json(stats),
        "verify_quality": {
            key: _thaw_json(verify.get(key, "unknown"))
            for key in legacy_quality_keys
        },
        "navigation": (
            "top-level table of contents; use query_passport(node_id) "
            "to reveal cached leaf operations"
        ),
    }
    for key in fidelity_quality_keys:
        if key in verify:
            result["verify_quality"][key] = _thaw_json(verify[key])

    if dependencies is not None:
        target_contract = (
            dependencies.get("target_contract")
            if isinstance(dependencies, Mapping) else None
        )
        if not isinstance(target_contract, str) or not target_contract:
            raise PassportError("Passport dependencies section is malformed")
        result["target_contract"] = target_contract

    # Persisted pre-STEP-0 Passports remain renderable.  Absence means the old
    # artifact made no such claim; do not invent a scope or gate outcome.
    if equivalence is not None:
        if not isinstance(equivalence, Mapping):
            raise PassportError("Passport equivalence section is malformed")
        equivalence_scope = equivalence.get("scope")
        equivalence_state = equivalence.get("state")
        equivalence_detail = equivalence.get("detail")
        if (not isinstance(equivalence_scope, str)
                or not isinstance(equivalence_state, str)
                or not isinstance(equivalence_detail, str)):
            raise PassportError("Passport equivalence section is malformed")
        try:
            require_scope_for_equivalence_text(
                equivalence_detail, equivalence_scope)
        except ValueError as exc:
            raise PassportError(
                f"Passport equivalence claim is invalid: {exc}") from exc
        result["equivalence"] = {
            "scope": equivalence_scope,
            "state": equivalence_state,
        }

    if build_status is not None:
        if not isinstance(build_status, Mapping):
            raise PassportError("Passport build_status section is malformed")
        compact_build_status: dict[str, str] = {}
        for key in (
            "compilable", "groundable", "executed", "roundtrip_verified",
        ):
            evidence = build_status.get(key)
            state = (
                evidence.get("state") if isinstance(evidence, Mapping) else None
            )
            if not isinstance(state, str) or not state:
                raise PassportError(
                    f"Passport build_status.{key} is malformed")
            compact_build_status[key] = state
        result["build_status"] = compact_build_status
    return result


def _fit_inject_base(
    result: dict[str, Any],
    total_more: int,
) -> None:
    """Make pathological labels/gestalt honest without breaking the ceiling."""

    if total_more:
        result["more"] = f"+{total_more} more"
    if estimate_passport_tokens(result) <= PASSPORT_INJECT_TOKENS:
        return

    tree = result["tree"]
    if isinstance(tree, dict):
        label = tree.get("label")
        if isinstance(label, str) and len(label) > 32:
            tree["label"] = label[:31] + "…"
            tree["label_more"] = f"+{len(label) - 31} chars"
    if estimate_passport_tokens(result) <= PASSPORT_INJECT_TOKENS:
        return

    gestalt = result.get("gestalt")
    if not isinstance(gestalt, str):
        raise PassportError("Passport gestalt must be a string")
    original_length = len(gestalt)
    low = 0
    high = original_length
    best: str | None = None
    while low <= high:
        middle = (low + high) // 2
        candidate = gestalt[:middle] + ("…" if middle < original_length else "")
        result["gestalt"] = candidate
        result["gestalt_more"] = f"+{original_length - middle} chars"
        if estimate_passport_tokens(result) <= PASSPORT_INJECT_TOKENS:
            best = candidate
            low = middle + 1
        else:
            high = middle - 1
    if best is None:
        raise PassportError(
            "mandatory Passport stats exceed PASSPORT_INJECT_TOKENS")
    kept = len(best[:-1]) if best.endswith("…") else len(best)
    result["gestalt"] = best
    result["gestalt_more"] = f"+{original_length - kept} chars"


def passport_inject(passport: Mapping[str, Any]) -> str:
    """Render the always-on ≤800-token building table of contents.

    Leaf payloads and compressed ``members`` ledgers are never included.
    Eligible top nodes are admitted breadth-first.  If the next breadth-first
    node would overflow the deterministic budget, the remainder is represented
    by an explicit ``"+N more"`` marker.
    """

    tree = passport.get("tree")
    if not isinstance(tree, Mapping):
        raise PassportError("Passport has no tree object")
    records = _top_tree_records(tree)
    if not records:
        raise PassportError("Passport tree is empty")
    result = _inject_base(passport)
    root_summary = _toc_node(records[0][0])
    result["tree"] = root_summary
    remaining = len(records) - 1
    _fit_inject_base(result, remaining)

    output_by_id = {cast(str, root_summary["node_id"]): root_summary}
    for index, (node, parent_id) in enumerate(records[1:]):
        if parent_id not in output_by_id:
            break
        summary = _toc_node(node)
        parent = output_by_id[parent_id]
        children = cast(list[dict[str, Any]], parent["children"])
        children.append(summary)
        after = remaining - index - 1
        if after:
            result["more"] = f"+{after} more"
        else:
            result.pop("more", None)
        if estimate_passport_tokens(result) > PASSPORT_INJECT_TOKENS:
            children.pop()
            result["more"] = f"+{remaining - index} more"
            break
        output_by_id[cast(str, summary["node_id"])] = summary

    rendered = _canonical_json(result)
    if estimate_passport_tokens(rendered) > PASSPORT_INJECT_TOKENS:
        raise AssertionError("Passport injection escaped its token budget")
    return rendered


def _page_args(offset: int, limit: int) -> None:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PassportError("query offset must be a non-negative integer")
    if (isinstance(limit, bool) or not isinstance(limit, int)
            or not 1 <= limit <= PASSPORT_QUERY_MAX_PAGE_SIZE):
        raise PassportError(
            "query limit must be an integer in 1.."
            f"{PASSPORT_QUERY_MAX_PAGE_SIZE}")


def _page_metadata(
    total: int,
    offset: int,
    limit: int,
    returned: int,
) -> dict[str, Any]:
    omitted = max(0, total - offset - returned)
    return {
        "offset": offset,
        "limit": limit,
        "returned": returned,
        "total": total,
        "more": f"+{omitted} more" if omitted else None,
    }


def _find_passport_node(
    root: Mapping[str, Any],
    node_id: Any,
) -> Mapping[str, Any]:
    found: Mapping[str, Any] | None = None
    for node in _walk_tree(root):
        if node.get("node_id") != node_id:
            continue
        if found is not None:
            raise PassportError(f"duplicate Passport node_id {node_id!r}")
        found = node
    if found is None:
        raise PassportQueryRefusal(node_id)
    return found


def _geometry_ref(
    geometry: Any,
    source_element_id: Any,
) -> dict[str, Any] | None:
    if geometry is None or not isinstance(source_element_id, str):
        return None
    if not isinstance(geometry, Mapping):
        raise PassportError("Passport geometry section must be an object")
    index = geometry.get("geometry_index")
    store = geometry.get("geometry_store")
    if not isinstance(index, Mapping) or not isinstance(store, Mapping):
        raise PassportError("Passport geometry index/store is malformed")
    row = index.get(source_element_id)
    if row is None:
        return None
    if not isinstance(row, Mapping) or set(row) != {
            "tier", "geo_hash", "transform"}:
        raise PassportError("Passport geometry index row is malformed")
    tier = row.get("tier")
    geo_hash = row.get("geo_hash")
    transform = row.get("transform")
    if tier == "A":
        if geo_hash is not None or transform is not None:
            raise PassportError("Passport Tier A row cannot carry geometry")
        return None
    if tier not in {"Gb", "Gm"} or not isinstance(geo_hash, str):
        raise PassportError("Passport geometry ref is malformed")
    if not isinstance(transform, Sequence) or isinstance(
            transform, (str, bytes, bytearray)):
        raise PassportError("Passport geometry transform is malformed")
    try:
        validated_transform = validate_transform(
            tuple(transform), "Passport geometry transform")
    except GeometrySchemaError as exc:
        raise PassportError(
            f"Passport geometry transform is malformed: {exc}") from exc
    definition = store.get(geo_hash)
    if not isinstance(definition, Mapping) \
            or definition.get("tier") != tier:
        raise PassportError("Passport geometry ref cannot resolve its store")
    return {
        "tier": tier,
        "geo_hash": geo_hash,
        "transform": list(validated_transform),
        "definition": _thaw_json(definition),
    }


def _payload_geometry_ref(
    payload: Mapping[str, Any],
    geometry: Any,
) -> dict[str, Any] | None:
    return _geometry_ref(geometry, payload.get("source_element_id"))


def _node_view_header(
    node: Mapping[str, Any],
    geometry: Any = None,
) -> dict[str, Any]:
    result = {
        "node_id": node.get("node_id", "unknown"),
        "kind": node.get("kind", "unknown"),
        "label": node.get("label", "unknown") or "unknown",
        "facts": _thaw_json(node.get("facts", {})),
        "verdict": _thaw_json(node.get("verdict", {
            "status": "unknown",
            "detail": "Passport node has no joined VERIFY fact",
        })),
        "fidelity": _thaw_json(node.get("fidelity", {
            "verdict": "opaque",
            "detail": "Passport node has no joined fidelity assessment",
        })),
        "macro": _compact_macro(node.get("macro")),
    }
    payload = node.get("payload")
    if isinstance(payload, Mapping):
        result["payload"] = _thaw_json(payload)
        geometry_ref = _payload_geometry_ref(payload, geometry)
        if geometry_ref is not None:
            result["geometry_ref"] = geometry_ref
    members = node.get("members")
    if isinstance(members, Sequence) and not isinstance(
            members, (str, bytes, bytearray)):
        result["member_count"] = len(members)
    return result


def _member_verdicts(node: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = node.get("member_verdicts", [])
    if not isinstance(raw, Sequence) or isinstance(
            raw, (str, bytes, bytearray)):
        return {}
    return {
        cast(str, verdict.get("node_id")): verdict
        for verdict in raw
        if isinstance(verdict, Mapping) and isinstance(verdict.get("node_id"), str)
    }


def _member_fidelity(node: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw = node.get("member_fidelity", [])
    if not isinstance(raw, Sequence) or isinstance(
            raw, (str, bytes, bytearray)):
        return {}
    return {
        cast(str, assessment.get("node_id")): assessment
        for assessment in raw
        if isinstance(assessment, Mapping)
        and isinstance(assessment.get("node_id"), str)
    }


def _member_view(
    member: Mapping[str, Any],
    verdicts: Mapping[str, Mapping[str, Any]],
    fidelity: Mapping[str, Mapping[str, Any]],
    *,
    include_payload: bool,
    geometry: Any = None,
) -> dict[str, Any]:
    member_id = member.get("_id", "unknown")
    result: dict[str, Any] = {
        "l1_node_id": member_id,
        "source_element_id": member.get("source_element_id", "unknown"),
        "kind": member.get("kind", "unknown"),
        "type_name": member.get("type_name", "unknown") or "unknown",
        "anchor_mm": _thaw_json(member.get("anchor_mm")),
        "verdict": _thaw_json(verdicts.get(cast(str, member_id), {
            "status": "unknown",
            "detail": "Passport member has no joined VERIFY fact",
        })),
        "fidelity": _thaw_json(fidelity.get(cast(str, member_id), {
            "verdict": "opaque" if member.get("kind") == "atom" else "approximate",
            "detail": "Passport member has no joined fidelity assessment",
        })),
    }
    if member.get("kind") == "op":
        result["op_name"] = member.get("op_name", "unknown")
    else:
        result["category"] = member.get("category", "unknown")
    if include_payload:
        result["payload"] = _thaw_json(member)
    geometry_ref = _payload_geometry_ref(member, geometry)
    if geometry_ref is not None:
        result["geometry_ref"] = geometry_ref
    return result


def _represented_leaves(
    node: Mapping[str, Any],
) -> Iterable[
    tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]
]:
    payload = node.get("payload")
    if isinstance(payload, Mapping):
        verdict = node.get("verdict", {
            "status": "unknown",
            "detail": "Passport leaf has no joined VERIFY fact",
        })
        if not isinstance(verdict, Mapping):
            verdict = {
                "status": "unknown",
                "detail": "Passport leaf has a malformed VERIFY fact",
            }
        fidelity = node.get("fidelity", {
            "verdict": "opaque" if payload.get("kind") == "atom" else "approximate",
            "detail": "Passport leaf has no joined fidelity assessment",
        })
        if not isinstance(fidelity, Mapping):
            fidelity = {
                "verdict": "opaque" if payload.get("kind") == "atom" else "approximate",
                "detail": "Passport leaf has a malformed fidelity assessment",
            }
        yield payload, verdict, fidelity
    members = node.get("members", [])
    if isinstance(members, Sequence) and not isinstance(
            members, (str, bytes, bytearray)):
        verdicts = _member_verdicts(node)
        fidelity = _member_fidelity(node)
        for member in members:
            if not isinstance(member, Mapping):
                continue
            member_id = member.get("_id")
            verdict = verdicts.get(cast(str, member_id), {
                "status": "unknown",
                "detail": "Passport member has no joined VERIFY fact",
            })
            assessment = fidelity.get(cast(str, member_id), {
                "verdict": (
                    "opaque" if member.get("kind") == "atom" else "approximate"
                ),
                "detail": "Passport member has no joined fidelity assessment",
            })
            yield member, verdict, assessment
    children = node.get("children", [])
    if isinstance(children, Sequence) and not isinstance(
            children, (str, bytes, bytearray)):
        for child in children:
            if isinstance(child, Mapping):
                yield from _represented_leaves(child)


def _operation_view(
    payload: Mapping[str, Any],
    verdict: Mapping[str, Any],
    fidelity: Mapping[str, Any],
    geometry: Any = None,
) -> dict[str, Any]:
    result = {
        "l1_node_id": payload.get("_id", "unknown"),
        "source_element_id": payload.get("source_element_id", "unknown"),
        "payload": _thaw_json(payload),
        "verdict": _thaw_json(verdict),
        "fidelity": _thaw_json(fidelity),
    }
    geometry_ref = _payload_geometry_ref(payload, geometry)
    if geometry_ref is not None:
        result["geometry_ref"] = geometry_ref
    return result


def _room_operations_page(
    node: Mapping[str, Any],
    offset: int,
    limit: int,
    geometry: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    facts = node.get("facts")
    stated_total = facts.get("element_count") if isinstance(facts, Mapping) else None
    known_total = (
        stated_total
        if isinstance(stated_total, int) and not isinstance(stated_total, bool)
        and stated_total >= 0
        else None
    )
    result: list[dict[str, Any]] = []
    observed = 0
    for index, (payload, verdict, fidelity) in enumerate(
            _represented_leaves(node)):
        observed = index + 1
        if index < offset:
            continue
        if len(result) < limit:
            result.append(_operation_view(
                payload, verdict, fidelity, geometry))
        if known_total is not None and len(result) == limit:
            break
    total = known_total if known_total is not None else observed
    return result, _page_metadata(total, offset, limit, len(result))


def _macro_expansion(
    node: Mapping[str, Any],
    offset: int,
    limit: int,
    geometry: Any = None,
) -> dict[str, Any] | None:
    kind = node.get("kind")
    macro = node.get("macro")
    macro_type = macro.get("type") if isinstance(macro, Mapping) else None
    children = node.get("children", [])
    if macro_type in {"stack", "repeat_on_levels"}:
        levels: list[dict[str, Any]] = []
        total_levels = 0
        if isinstance(children, Sequence) and not isinstance(
                children, (str, bytes, bytearray)):
            for child in children:
                if not isinstance(child, Mapping) or child.get("kind") != "floor":
                    continue
                level_index = total_levels
                total_levels += 1
                if not offset <= level_index < offset + limit:
                    continue
                floor_macro = child.get("macro")
                levels.append({
                    "node_id": child.get("node_id", "unknown"),
                    "label": child.get("label", "unknown") or "unknown",
                    "level_name": (
                        floor_macro.get("level_name", "unknown")
                        if isinstance(floor_macro, Mapping) else "unknown"
                    ),
                    "elevation_mm": (
                        floor_macro.get("elevation_mm", "unknown")
                        if isinstance(floor_macro, Mapping) else "unknown"
                    ),
                    "verify_status": _verdict_status(child),
                })
        return {
            "type": macro_type,
            "levels": levels,
            "page": _page_metadata(
                total_levels, offset, limit, len(levels)),
        }

    members = node.get("members", [])
    if isinstance(members, Sequence) and not isinstance(
            members, (str, bytes, bytearray)) and members:
        verdicts = _member_verdicts(node)
        fidelity = _member_fidelity(node)
        include_payload = macro_type not in {"grid_array", "row"}
        member_page = members[offset:offset + limit]
        views = [
            _member_view(
                member,
                verdicts,
                fidelity,
                include_payload=include_payload,
                geometry=geometry,
            )
            for member in member_page if isinstance(member, Mapping)
        ]
        field = "positions" if macro_type in {"grid_array", "row"} else "members"
        return {
            "type": macro_type or cast(str, kind or "members"),
            field: views,
            "page": _page_metadata(
                len(members), offset, limit, len(views)),
        }

    if kind == "room":
        operations, page = _room_operations_page(
            node, offset, limit, geometry)
        return {"type": "room", "operations": operations, "page": page}
    return None


def _group_id_key(value: str) -> tuple[int, int | str, str]:
    try:
        return 0, int(value), value
    except ValueError:
        return 1, value, value


def _virtual_group_type_id(group_type_id: str) -> str:
    return "group-type:" + group_type_id


def _virtual_group_instance_id(group_instance_id: str) -> str:
    return "group-instance:" + group_instance_id


def _group_projection_data(
    passport: Mapping[str, Any],
    tree: Mapping[str, Any],
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, str],
    Mapping[str, Any],
]:
    definitions = passport.get("definitions")
    relations = passport.get("relations")
    if definitions is None and relations is None:
        raise PassportQueryRefusal("groups")
    if not isinstance(definitions, Mapping) or not isinstance(relations, Mapping):
        raise PassportError(
            "Passport group definitions/relations must both be objects")
    raw_types = definitions.get("group_types")
    raw_memberships = relations.get("group_membership")
    unmatched = relations.get("group_membership_unmatched")
    if (not isinstance(raw_types, Mapping)
            or not isinstance(raw_memberships, Mapping)
            or not isinstance(unmatched, Mapping)):
        raise PassportError("Passport group projection is malformed")

    group_types: dict[str, Mapping[str, Any]] = {}
    instance_to_type: dict[str, str] = {}
    required_type_fields = {
        "name", "reference_instance_id", "slot_count", "instance_count",
        "instance_ids", "has_composition_mismatch",
        "mismatch_instance_count", "slot_comparison_basis",
    }
    for group_type_id in sorted(raw_types, key=lambda value: _group_id_key(
            cast(str, value)) if isinstance(value, str) else (2, "", "")):
        if not isinstance(group_type_id, str) or not group_type_id:
            raise PassportError("Passport group type id must be non-empty")
        row = raw_types[group_type_id]
        if not isinstance(row, Mapping) or not required_type_fields <= set(row):
            raise PassportError(
                f"Passport group type {group_type_id!r} is malformed")
        name = row.get("name")
        reference_id = row.get("reference_instance_id")
        slot_count = row.get("slot_count")
        instance_count = row.get("instance_count")
        instance_ids = row.get("instance_ids")
        mismatch = row.get("has_composition_mismatch")
        mismatch_count = row.get("mismatch_instance_count")
        comparison_basis = row.get("slot_comparison_basis")
        if (not isinstance(name, str) or not name
                or not isinstance(reference_id, str) or not reference_id
                or isinstance(slot_count, bool) or not isinstance(slot_count, int)
                or slot_count < 0
                or isinstance(instance_count, bool)
                or not isinstance(instance_count, int) or instance_count < 0
                or not isinstance(instance_ids, Sequence)
                or isinstance(instance_ids, (str, bytes, bytearray))
                or not isinstance(mismatch, bool)
                or isinstance(mismatch_count, bool)
                or not isinstance(mismatch_count, int) or mismatch_count < 0):
            raise PassportError(
                f"Passport group type {group_type_id!r} is malformed")
        normalized_instance_ids = list(instance_ids)
        if (not all(isinstance(item, str) and item
                    for item in normalized_instance_ids)
                or len(normalized_instance_ids) != len(set(normalized_instance_ids))
                or instance_count != len(normalized_instance_ids)
                or reference_id not in normalized_instance_ids
                or comparison_basis != "ordered_cardinality_only"
                or mismatch != (mismatch_count > 0)
                or mismatch_count > instance_count):
            raise PassportError(
                f"Passport group type {group_type_id!r} is inconsistent")
        for instance_id in normalized_instance_ids:
            if instance_id in instance_to_type:
                raise PassportError(
                    f"Passport repeats group instance {instance_id!r}")
            instance_to_type[instance_id] = group_type_id
        group_types[group_type_id] = row

    memberships: dict[str, Mapping[str, Any]] = {}
    for source_id in sorted(raw_memberships, key=lambda value: _group_id_key(
            cast(str, value)) if isinstance(value, str) else (2, "", "")):
        if not isinstance(source_id, str) or not source_id:
            raise PassportError("Passport group member id must be non-empty")
        row = raw_memberships[source_id]
        if not isinstance(row, Mapping) or not {
                "group_instance_id", "group_type_id"} <= set(row):
            raise PassportError(
                f"Passport group membership {source_id!r} is malformed")
        instance_id = row.get("group_instance_id")
        group_type_id = row.get("group_type_id")
        ordinal = row.get("ordinal")
        if (not isinstance(instance_id, str) or not instance_id
                or not isinstance(group_type_id, str) or not group_type_id
                or instance_to_type.get(instance_id) != group_type_id
                or ("ordinal" in row and (
                    isinstance(ordinal, bool) or not isinstance(ordinal, int)
                    or ordinal < 0))):
            raise PassportError(
                f"Passport group membership {source_id!r} is inconsistent")
        if "ordinal" in row:
            slot_count = group_types[group_type_id].get("slot_count")
            if not isinstance(slot_count, int) or ordinal >= slot_count:
                raise PassportError(
                    f"Passport group membership {source_id!r} has invalid ordinal")
        memberships[source_id] = row

    unmatched_fields = {
        "total", "absent_from_l0_count", "ambiguous_group_claim_count",
        "index_member_occurrences", "index_unique_member_ids",
        "matched_leaf_count",
    }
    if not unmatched_fields <= set(unmatched):
        raise PassportError("Passport group unmatched statistics are malformed")
    unmatched_values = {
        key: unmatched.get(key) for key in unmatched_fields
    }
    if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in unmatched_values.values()):
        raise PassportError("Passport group unmatched statistics are malformed")
    if (unmatched_values["matched_leaf_count"] != len(memberships)
            or unmatched_values["total"] != (
                unmatched_values["absent_from_l0_count"]
                + unmatched_values["ambiguous_group_claim_count"])
            or unmatched_values["index_unique_member_ids"] != (
                len(memberships) + unmatched_values["total"])
            or unmatched_values["index_member_occurrences"]
            < unmatched_values["index_unique_member_ids"]):
        raise PassportError(
            "Passport group unmatched statistics are inconsistent")
    return group_types, memberships, instance_to_type, unmatched


def _group_leaf_index(
    tree: Mapping[str, Any],
    source_ids: Sequence[str],
) -> dict[
        str,
        tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
]:
    targets = set(source_ids)
    leaves_by_source: dict[
        str,
        tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]],
    ] = {}
    for payload, verdict, fidelity in _represented_leaves(tree):
        source_id = payload.get("source_element_id")
        if not isinstance(source_id, str) or not source_id:
            raise PassportError("Passport tree leaf has no source_element_id")
        if source_id not in targets:
            continue
        if source_id in leaves_by_source:
            raise PassportError(
                f"Passport tree repeats source leaf {source_id!r}")
        leaves_by_source[source_id] = (payload, verdict, fidelity)
    missing = sorted(targets - set(leaves_by_source), key=_group_id_key)
    if missing:
        raise PassportError(
            "Passport group membership references absent leaves: "
            + ", ".join(missing[:5]))
    return leaves_by_source


def _group_type_view(
    group_type_id: str,
    row: Mapping[str, Any],
    matched_by_instance: Counter[str],
) -> dict[str, Any]:
    instance_ids = cast(Sequence[str], row["instance_ids"])
    return {
        "node_id": _virtual_group_type_id(group_type_id),
        "kind": "group_type",
        "label": row["name"],
        "group_type_id": group_type_id,
        "name": row["name"],
        "reference_instance_id": row["reference_instance_id"],
        "slot_count": row["slot_count"],
        "instance_count": row["instance_count"],
        "matched_member_count": sum(
            matched_by_instance[instance_id] for instance_id in instance_ids),
        "has_composition_mismatch": row["has_composition_mismatch"],
        "mismatch_instance_count": row["mismatch_instance_count"],
        "slot_comparison_basis": row["slot_comparison_basis"],
    }


def _group_instance_view(
    group_instance_id: str,
    group_type_id: str,
    group_type: Mapping[str, Any],
    matched_count: int,
) -> dict[str, Any]:
    return {
        "node_id": _virtual_group_instance_id(group_instance_id),
        "kind": "group_instance",
        "label": f"{group_type['name']} / {group_instance_id}",
        "group_instance_id": group_instance_id,
        "group_type_id": group_type_id,
        "matched_member_count": matched_count,
    }


def _query_group_projection(
    passport: Mapping[str, Any],
    node_id: str,
    offset: int,
    limit: int,
) -> FrozenJSONDict:
    tree = passport.get("tree")
    if not isinstance(tree, Mapping):
        raise PassportError("Passport has no tree object")
    (
        group_types,
        memberships,
        instance_to_type,
        unmatched,
    ) = _group_projection_data(passport, tree)
    geometry = passport.get("geometry")
    matched_by_instance: Counter[str] = Counter(
        cast(str, row["group_instance_id"])
        for row in memberships.values()
    )

    root_id = tree.get("node_id")
    if node_id == "groups" or node_id == root_id:
        ordered_type_ids = sorted(group_types, key=_group_id_key)
        page_ids = ordered_type_ids[offset:offset + limit]
        children = [
            _group_type_view(
                group_type_id,
                group_types[group_type_id],
                matched_by_instance,
            )
            for group_type_id in page_ids
        ]
        return FrozenJSONDict({
            "projection": "groups",
            "node_id": "groups",
            "kind": "group_types",
            "label": "model group types",
            "children": children,
            "children_page": _page_metadata(
                len(ordered_type_ids), offset, limit, len(children)),
            "membership_unmatched": _thaw_json(unmatched),
        })

    type_by_virtual = {
        _virtual_group_type_id(group_type_id): group_type_id
        for group_type_id in group_types
    }
    if node_id in type_by_virtual:
        group_type_id = type_by_virtual[node_id]
        group_type = group_types[group_type_id]
        instance_ids = cast(Sequence[str], group_type["instance_ids"])
        page_ids = instance_ids[offset:offset + limit]
        result = _group_type_view(
            group_type_id, group_type, matched_by_instance)
        result["projection"] = "groups"
        result["children"] = [
            _group_instance_view(
                instance_id,
                group_type_id,
                group_type,
                matched_by_instance[instance_id],
            )
            for instance_id in page_ids
        ]
        result["children_page"] = _page_metadata(
            len(instance_ids), offset, limit, len(page_ids))
        return FrozenJSONDict(result)

    instance_by_virtual = {
        _virtual_group_instance_id(instance_id): instance_id
        for instance_id in instance_to_type
    }
    if node_id in instance_by_virtual:
        instance_id = instance_by_virtual[node_id]
        group_type_id = instance_to_type[instance_id]
        group_type = group_types[group_type_id]
        member_ids = [
            source_id for source_id, row in memberships.items()
            if row["group_instance_id"] == instance_id
        ]
        member_ids.sort(key=lambda source_id: (
            "ordinal" not in memberships[source_id],
            memberships[source_id].get("ordinal", 0),
            _group_id_key(source_id),
        ))
        leaves_by_source = _group_leaf_index(tree, member_ids)
        page_ids = member_ids[offset:offset + limit]
        member_views = []
        for source_id in page_ids:
            payload, verdict, fidelity = leaves_by_source[source_id]
            member_view = _operation_view(
                payload, verdict, fidelity, geometry)
            member_view["membership"] = _thaw_json(memberships[source_id])
            member_views.append(member_view)
        result = _group_instance_view(
            instance_id,
            group_type_id,
            group_type,
            len(member_ids),
        )
        result.update({
            "projection": "groups",
            "members": member_views,
            "members_page": _page_metadata(
                len(member_ids), offset, limit, len(member_views)),
        })
        return FrozenJSONDict(result)

    raise PassportQueryRefusal(node_id)


def query_passport(
    passport: Mapping[str, Any],
    node_id: str,
    *,
    offset: int = 0,
    limit: int = PASSPORT_QUERY_PAGE_SIZE,
    projection: Literal["tree", "groups"] | None = None,
) -> FrozenJSONDict:
    """Reveal one cached subtree level or macro expansion by stable node id.

    This performs only in-memory JSON navigation.  It never queries or mutates
    the live model.  Returned pages are frozen and detached from mutable input
    mappings.  Unknown ids raise :class:`PassportQueryRefusal`, whose
    :meth:`~PassportQueryRefusal.to_dict` method is the typed serving envelope.
    """

    _page_args(offset, limit)
    if projection not in (None, "tree", "groups"):
        raise PassportError(
            "query projection must be 'tree', 'groups', or null")
    if projection == "groups":
        return _query_group_projection(
            passport, node_id, offset, limit)
    tree = passport.get("tree")
    if not isinstance(tree, Mapping):
        raise PassportError("Passport has no tree object")
    node = _find_passport_node(tree, node_id)
    geometry = passport.get("geometry")
    result = _node_view_header(node, geometry)
    raw_children = node.get("children", [])
    if not isinstance(raw_children, Sequence) or isinstance(
            raw_children, (str, bytes, bytearray)):
        raise PassportError("Passport tree.children must be an array")
    child_page = raw_children[offset:offset + limit]
    children = [
        _node_view_header(child, geometry)
        for child in child_page if isinstance(child, Mapping)
    ]
    result["children"] = children
    result["children_page"] = _page_metadata(
        len(raw_children), offset, limit, len(children))
    expansion = _macro_expansion(node, offset, limit, geometry)
    if expansion is not None:
        result["expansion"] = expansion
    return FrozenJSONDict(result)


__all__ = [
    "CacheStatus",
    "FrozenJSONDict",
    "FrozenJSONList",
    "PASSPORT_NODE_NOT_FOUND",
    "PASSPORT_INJECT_TOKENS",
    "PASSPORT_QUERY_MAX_PAGE_SIZE",
    "PASSPORT_QUERY_PAGE_SIZE",
    "Passport",
    "PassportAssemblyError",
    "PassportError",
    "PassportQueryRefusal",
    "assemble_passport",
    "build_passport",
    "estimate_passport_tokens",
    "is_passport_cache_hit",
    "passport_bytes",
    "passport_cache_key",
    "passport_cache_status",
    "passport_inject",
    "query_passport",
]
