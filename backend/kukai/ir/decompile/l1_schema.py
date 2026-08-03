"""Frozen shared schema for the flat DECOMPILE L1 representation.

L1 is deliberately JSON-ready: it is the stable boundary between LIFT and
FOLD, not an in-process implementation detail.  Every source element is
represented by exactly one op or atom node, and both variants carry the same
deterministic leaf identity.
"""
from __future__ import annotations

import hashlib
import json
import math
from enum import Enum
from typing import Any, Literal, Mapping, Sequence, TypedDict, cast

from kukai.ir import spec


class L1SchemaError(ValueError):
    """An L1 node violates the frozen structural contract."""


class AtomReason(str, Enum):
    """Closed reasons for a conservative op-to-atom fallback."""

    NO_LIFTER = "no_lifter"
    # Retained as a readable legacy code for persisted Wave-B diagnostics.
    # LIFT authority is spec.OPS as of Wave C, so new nodes do not use it.
    REGISTRY_KIND_GAP = "registry_kind_gap"
    REGISTRY_OP_GAP = "registry_op_gap"
    MISSING_GEOMETRY = "missing_geometry"
    MISSING_METADATA = "missing_metadata"
    MISSING_PARAMETER = "missing_parameter"
    MISSING_REFERENCE = "missing_reference"
    UNSUPPORTED_GEOMETRY = "unsupported_geometry"
    UNSUPPORTED_SIGNATURE = "unsupported_forward_signature"
    INVALID_VALUE = "invalid_forward_value"
    INVALID_NODE = "invalid_l1_node"
    INTERNAL_ERROR = "internal_lift_error"
    # STEP-0 honesty contract.  These values are additive future-facing
    # refusal codes: current lifters do not pretend to know placement/state or
    # dependency facts that frozen L0 1.0 never captured.
    PLACEMENT_KIND_UNKNOWN = "placement_kind_unknown"
    FLIP_STATE_UNKNOWN = "flip_state_unknown"
    INSTANCE_PARAMS_INCOMPLETE = "instance_params_incomplete"
    DEPENDENCY_UNRESOLVED = "dependency_unresolved"
    GENERATOR_CHILD = "generator_child"
    # §18.1-следствие: LocationCurve не-Line, а выразить её нечем — ни
    # арочным параметром опа, ни точной дугой из бокового индекса. Отдельный
    # код нужен именно потому, что альтернативой была ХОРДА: молчаливое
    # спрямление проходило verify как exact (сравниваются только концы) и
    # выглядело успехом. Код НЕ входит в _SHAPE_REFUSALS: это отказ о
    # геометрии, которую нельзя отбросить, а не о форме, которую готов принять
    # другой оп.
    CURVE_KIND_UNSUPPORTED = "curve_kind_unsupported"
    # ОП ЕСТЬ, А ВХОДОВ ЕМУ НЕТ В ЧТЕНИИ — третье состояние, которого до 29.07
    # в этом перечислении не было, и его отсутствие стоило верного диагноза.
    #
    # `no_lifter` означает «операции под это нет вовсе», и ранжир причин читают
    # именно так: строка с 13 905 размерами под этим кодом говорит следующему
    # «напиши create_dimension». Но create_dimension НАПИСАН и лежит в
    # spec.OPS с 28.07 — вместе с create_tag и create_text. Не хватает не опа,
    # а полей: обязательные входы всех трёх (`in_view`, `refs`/`target`,
    # `at`/`line_at`, `content`) в замороженной строке L0 1.0 отсутствуют как
    # поля (см. schema.L0Element — вида-владельца среди её полей нет вовсе).
    #
    # Разница не косметическая, а адресная: `no_lifter` посылает работать в
    # реестр операций, `source_contract_gap` — в ЧТЕНИЕ. Ровно то же различие
    # 29.07 уже развели для стадии размещений («молчание стадии не есть факт об
    # элементе»), и цена там измерялась одной популяцией, стоявшей в ранжире
    # дважды под разными именами.
    #
    # Код НЕ входит в _SHAPE_REFUSALS: это отказ не о форме элемента, и второй
    # оп его не подберёт.
    SOURCE_CONTRACT_GAP = "source_contract_gap"


class FidelityVerdict(str, Enum):
    """Closed STEP-0 fidelity scale, separate from legacy VERIFY status.

    Legacy ``exact`` remains a bounded point-geometry result.  It is not a
    synonym for :attr:`NATIVE_EXACT`; the latter requires resolved dependency
    fingerprints and native-state round-trip evidence that L0 1.0 lacks.
    """

    NATIVE_EXACT = "native_exact"
    FORM_EXACT = "form_exact"
    APPROXIMATE = "approximate"
    OPAQUE = "opaque"
    GENERATED_ACCOUNTED = "generated_accounted"


class FidelityReason(str, Enum):
    """Machine-readable reasons carried by STEP-0 fidelity assessments.

    Every :class:`AtomReason` has an identical value here so an atom's typed
    LIFT refusal reaches VERIFY and Passport losslessly.  The final values are
    assessment-only evidence codes used when mapping legacy VERIFY facts onto
    the stricter fidelity scale.
    """

    NO_LIFTER = AtomReason.NO_LIFTER.value
    REGISTRY_KIND_GAP = AtomReason.REGISTRY_KIND_GAP.value
    REGISTRY_OP_GAP = AtomReason.REGISTRY_OP_GAP.value
    MISSING_GEOMETRY = AtomReason.MISSING_GEOMETRY.value
    MISSING_METADATA = AtomReason.MISSING_METADATA.value
    MISSING_PARAMETER = AtomReason.MISSING_PARAMETER.value
    MISSING_REFERENCE = AtomReason.MISSING_REFERENCE.value
    UNSUPPORTED_GEOMETRY = AtomReason.UNSUPPORTED_GEOMETRY.value
    UNSUPPORTED_SIGNATURE = AtomReason.UNSUPPORTED_SIGNATURE.value
    INVALID_VALUE = AtomReason.INVALID_VALUE.value
    INVALID_NODE = AtomReason.INVALID_NODE.value
    INTERNAL_ERROR = AtomReason.INTERNAL_ERROR.value
    PLACEMENT_KIND_UNKNOWN = AtomReason.PLACEMENT_KIND_UNKNOWN.value
    FLIP_STATE_UNKNOWN = AtomReason.FLIP_STATE_UNKNOWN.value
    INSTANCE_PARAMS_INCOMPLETE = AtomReason.INSTANCE_PARAMS_INCOMPLETE.value
    DEPENDENCY_UNRESOLVED = AtomReason.DEPENDENCY_UNRESOLVED.value
    GENERATOR_CHILD = AtomReason.GENERATOR_CHILD.value
    CURVE_KIND_UNSUPPORTED = AtomReason.CURVE_KIND_UNSUPPORTED.value
    SOURCE_CONTRACT_GAP = AtomReason.SOURCE_CONTRACT_GAP.value
    LEGACY_VERIFY_SCOPE_LIMITED = "legacy_verify_scope_limited"
    GEOMETRY_EVIDENCE_INCOMPLETE = "geometry_evidence_incomplete"
    VERIFICATION_EVIDENCE_MISSING = "verification_evidence_missing"
    VERIFICATION_FAILED = "verification_failed"
    FORM_WITNESS_VERIFIED = "form_witness_verified"
    NATIVE_SEMANTICS_VERIFIED = "native_semantics_verified"


class L1NamedReference(TypedDict):
    by: Literal["name"]
    value: str
    _id: str


class L1FamilyReference(TypedDict):
    by: Literal["family_type"]
    category: str
    family_name: str
    type_name: str
    _id: str


class L1NodeReference(TypedDict):
    ref: str


class L1AtomReason(TypedDict):
    code: str
    detail: str


class L1OpNode(TypedDict):
    kind: Literal["op"]
    op_name: str
    _id: str
    type_name: str
    params: dict[str, Any]
    source_element_id: str
    level_name: str | None
    anchor_mm: list[float] | None


class L1AtomNode(TypedDict):
    kind: Literal["atom"]
    category: str
    category_ru: str
    type_name: str
    bbox_min_mm: list[float] | None
    bbox_max_mm: list[float] | None
    source_element_id: str
    level_name: str | None
    anchor_mm: list[float] | None
    _id: str
    reason: L1AtomReason


L1Node = L1OpNode | L1AtomNode


def stable_l1_id(kind: Literal["op", "atom"], source_element_id: str) -> str:
    """Return the Part 6.7 SHA-1 identity for one L1 leaf."""

    payload = json.dumps(
        [kind, [source_element_id]],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _json_ready(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return math.isfinite(float(value))
    if isinstance(value, list):
        return all(_json_ready(item) for item in value)
    if isinstance(value, dict):
        return (
            all(isinstance(key, str) for key in value)
            and all(_json_ready(item) for item in value.values())
        )
    return False


def _validate_vec3(value: Any, field_name: str, *, nullable: bool) -> None:
    if value is None:
        if nullable:
            return
        raise L1SchemaError(f"{field_name} must contain three finite numbers")
    if (not isinstance(value, list) or len(value) != 3
            or any(_finite(component) is None for component in value)):
        raise L1SchemaError(f"{field_name} must contain three finite numbers")


def _validate_reference_shapes(value: Any, field_name: str) -> None:
    """Validate the two frozen reference dialects wherever they occur."""

    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_reference_shapes(item, f"{field_name}[{index}]")
        return
    if not isinstance(value, dict):
        return
    if "by" in value:
        if value.get("by") == "family_type":
            if set(value) != {
                    "by", "category", "family_name", "type_name", "_id"}:
                raise L1SchemaError(
                    f"{field_name} family reference has unexpected fields")
            for key in ("category", "family_name", "type_name", "_id"):
                if not isinstance(value.get(key), str) or not value[key]:
                    raise L1SchemaError(
                        f"{field_name}.{key} must be a non-empty string")
            return
        if set(value) != {"by", "value", "_id"}:
            raise L1SchemaError(
                f"{field_name} named reference has unexpected fields")
        if value.get("by") != "name":
            raise L1SchemaError(
                f"{field_name}.by must be the literal 'name'")
        if not isinstance(value.get("value"), str) or not value["value"]:
            raise L1SchemaError(
                f"{field_name}.value must be a non-empty string")
        if not isinstance(value.get("_id"), str) or not value["_id"]:
            raise L1SchemaError(
                f"{field_name}._id must be a non-empty string")
        return
    if "ref" in value:
        if set(value) != {"ref"}:
            raise L1SchemaError(
                f"{field_name} node reference has unexpected fields")
        if not isinstance(value.get("ref"), str) or not value["ref"]:
            raise L1SchemaError(
                f"{field_name}.ref must be a non-empty string")
        return
    for key, item in value.items():
        _validate_reference_shapes(item, f"{field_name}.{key}")


def _require_common(value: Mapping[str, Any]) -> tuple[str, str]:
    source_id = value.get("source_element_id")
    node_id = value.get("_id")
    if not isinstance(source_id, str) or not source_id:
        raise L1SchemaError("source_element_id must be a non-empty string")
    if not isinstance(node_id, str) or not node_id:
        raise L1SchemaError("_id must be a non-empty string")
    level_name = value.get("level_name")
    if level_name is not None and not isinstance(level_name, str):
        raise L1SchemaError("level_name must be a string or null")
    _validate_vec3(value.get("anchor_mm"), "anchor_mm", nullable=True)
    return source_id, node_id


def validate_l1_node(value: Any) -> L1Node:
    """Validate and return one frozen L1 op/atom mapping.

    This is intentionally structural.  Forward semantic validation remains
    compiler-owned; the L1 boundary verifies registry membership, parameter
    names/required fields, finite JSON data, identity, and reference dialects.
    """

    if not isinstance(value, dict):
        raise L1SchemaError("L1 node must be an object")
    kind = value.get("kind")
    common = {
        "kind", "_id", "source_element_id", "level_name", "anchor_mm",
        "type_name",
    }
    source_id, node_id = _require_common(value)
    if not isinstance(value.get("type_name"), str):
        raise L1SchemaError("type_name must be a string")

    if kind == "atom":
        expected = common | {
            "category", "category_ru", "bbox_min_mm", "bbox_max_mm",
            "reason",
        }
        if set(value) != expected:
            raise L1SchemaError("atom node has unexpected or missing fields")
        if node_id != stable_l1_id("atom", source_id):
            raise L1SchemaError("atom _id is not deterministic for its source")
        if not isinstance(value.get("category"), str) or not value["category"]:
            raise L1SchemaError("atom category must be a non-empty string")
        if not isinstance(value.get("category_ru"), str):
            raise L1SchemaError("atom category_ru must be a string")
        bbox_min = value.get("bbox_min_mm")
        bbox_max = value.get("bbox_max_mm")
        if (bbox_min is None) != (bbox_max is None):
            raise L1SchemaError("atom bbox endpoints must both exist or be null")
        _validate_vec3(bbox_min, "bbox_min_mm", nullable=True)
        _validate_vec3(bbox_max, "bbox_max_mm", nullable=True)
        if bbox_min is not None and any(
                low > high for low, high in zip(bbox_min, bbox_max)):
            raise L1SchemaError("atom bbox min must not exceed bbox max")
        reason = value.get("reason")
        if not isinstance(reason, dict) or set(reason) != {"code", "detail"}:
            raise L1SchemaError("atom reason must contain code and detail")
        if reason.get("code") not in {item.value for item in AtomReason}:
            raise L1SchemaError("atom reason.code is not a known typed reason")
        if not isinstance(reason.get("detail"), str) or not reason["detail"]:
            raise L1SchemaError("atom reason.detail must be a non-empty string")
        return cast(L1AtomNode, value)

    if kind == "op":
        expected = common | {"op_name", "params"}
        if set(value) != expected:
            raise L1SchemaError("op node has unexpected or missing fields")
        if node_id != stable_l1_id("op", source_id):
            raise L1SchemaError("op _id is not deterministic for its source")
        op_name = value.get("op_name")
        params = value.get("params")
        if not isinstance(op_name, str) or op_name not in spec.OPS:
            raise L1SchemaError("op_name is absent from spec.OPS")
        if not isinstance(params, dict) or not _json_ready(params):
            raise L1SchemaError("op params must be finite JSON data")
        op_spec = spec.OPS[op_name]
        known = {param.name for param in op_spec.params}
        required = {
            param.name for param in op_spec.params if param.required
        }
        if not set(params) <= known:
            raise L1SchemaError("op params contain fields outside its OpSpec")
        if not required <= set(params):
            raise L1SchemaError("op params omit one or more required fields")
        _validate_reference_shapes(params, "params")
        return cast(L1OpNode, value)

    raise L1SchemaError("kind must be 'op' or 'atom'")


def is_valid_l1_node(value: Any) -> bool:
    """Return whether ``value`` satisfies the frozen L1 union."""

    try:
        validate_l1_node(value)
    except L1SchemaError:
        return False
    return True


def _node_refs(value: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(value, list):
        for item in value:
            refs.extend(_node_refs(item))
    elif isinstance(value, dict):
        if set(value) == {"ref"} and isinstance(value.get("ref"), str):
            refs.append(value["ref"])
        else:
            for item in value.values():
                refs.extend(_node_refs(item))
    return refs


def validate_l1_nodes(values: Sequence[Any]) -> tuple[L1Node, ...]:
    """Validate an L1 collection, including uniqueness and node references."""

    nodes = tuple(validate_l1_node(value) for value in values)
    source_ids = [node["source_element_id"] for node in nodes]
    node_ids = [node["_id"] for node in nodes]
    if len(source_ids) != len(set(source_ids)):
        raise L1SchemaError("L1 collection contains duplicate source ids")
    if len(node_ids) != len(set(node_ids)):
        raise L1SchemaError("L1 collection contains duplicate node ids")
    known_ids = set(node_ids)
    for node in nodes:
        if node["kind"] != "op":
            continue
        dangling = [
            ref for ref in _node_refs(node["params"])
            if ref not in known_ids
        ]
        if dangling:
            raise L1SchemaError(
                f"{node['_id']} contains a dangling L1 node reference")
    return nodes


__all__ = [
    "AtomReason",
    "FidelityReason",
    "FidelityVerdict",
    "L1AtomNode",
    "L1AtomReason",
    "L1FamilyReference",
    "L1NamedReference",
    "L1Node",
    "L1NodeReference",
    "L1OpNode",
    "L1SchemaError",
    "is_valid_l1_node",
    "stable_l1_id",
    "validate_l1_node",
    "validate_l1_nodes",
]
