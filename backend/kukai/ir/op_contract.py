"""Canonical, content-addressed contract for one KIR operation.

The registry, grounder and translation certificate historically described
different faces of the same operation.  This module does not introduce a
second registry.  It projects those existing authorities into one immutable
artifact whose digest can be bound by the compiler plan.

Changing an operand, grounding rule, result identity, tolerance or refinement
obligation must therefore change the operation contract digest even when the
authored payload is byte-identical.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from kukai.ir import spec
from kukai.ir.registry_base import OpSpec, ParamSpec


OP_CONTRACT_SCHEMA = "kir-op-contract/1"


class OpContractError(ValueError):
    """The existing operation authorities cannot form one honest contract."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise OpContractError(f"operation contract is not canonical JSON: {exc}") from exc


def _param_row(param: ParamSpec) -> dict[str, Any]:
    return {
        "name": param.name,
        "kind": param.kind,
        "required": param.required,
        "default": param.default,
        "min_val": param.min_val,
        "max_val": param.max_val,
        "choices": list(param.choices),
        "ref_kinds": [item.value for item in param.ref_kinds],
        "exact_string": param.exact_string,
    }


def _result_row(op_spec: OpSpec) -> dict[str, Any]:
    result = op_spec.result
    return {
        "identity_cardinality": result.identity_cardinality.value,
        "identity_field": result.identity_field,
        "reference_kind": (
            result.reference_kind.value if result.reference_kind is not None else None
        ),
    }


def _refinement_row(op_spec: OpSpec) -> dict[str, Any] | None:
    if op_spec.family not in spec.WRITE_FAMILIES:
        return None

    # Lazy import keeps the registry usable by schema generation without
    # importing the emitter.  At planning time a write contract must include
    # the exact certificate semantics that will judge its lowering.
    from kukai.ir import translation_cert

    refinement = translation_cert._ensure_table().get(op_spec.name)
    if refinement is None:
        raise OpContractError(
            f"{op_spec.name}: write operation has no translation refinement")
    return {
        "materializer": list(refinement.materializer),
        "refuse_on_null": refinement.refuse_on_null,
        "witness_source": refinement.witness_source,
        "obligations": [
            {
                "clause": obligation.clause,
                "kind": obligation.kind,
                "block": obligation.block,
                "witness_markers": list(obligation.witness_markers),
                "param": obligation.param,
                "conditional": obligation.conditional,
                "unless_param": obligation.unless_param,
                "param_truthy": obligation.param_truthy,
                "key": obligation.key,
            }
            for obligation in refinement.obligations
        ],
    }


@dataclass(frozen=True, slots=True)
class OpContract:
    """Canonical projection of registry and lowering-proof semantics."""

    op_name: str
    _payload_json: str
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.op_name, str) or not self.op_name:
            raise OpContractError("operation contract needs a non-empty name")
        try:
            payload = json.loads(self._payload_json)
        except (TypeError, ValueError) as exc:
            raise OpContractError("operation contract payload is invalid JSON") from exc
        if _canonical_json(payload) != self._payload_json:
            raise OpContractError("operation contract payload is not canonical")
        if payload.get("op_name") != self.op_name:
            raise OpContractError("operation contract identity disagrees with payload")
        expected = hashlib.sha256(self._payload_json.encode("utf-8")).hexdigest()
        if self.digest != expected:
            raise OpContractError("operation contract digest disagrees with payload")

    @classmethod
    def from_spec(cls, op_spec: OpSpec) -> "OpContract":
        if not isinstance(op_spec, OpSpec):
            raise TypeError("op_spec must be OpSpec")
        payload = {
            "schema": OP_CONTRACT_SCHEMA,
            "op_name": op_spec.name,
            "family": op_spec.family,
            "effect": op_spec.effect.value,
            "reads_model": op_spec.reads_model,
            "writes_model": op_spec.writes_model,
            "capability": [list(cell) for cell in op_spec.capability],
            "params": [_param_row(param) for param in op_spec.params],
            "grounded": [list(item) for item in op_spec.grounded],
            "post": op_spec.post,
            "tolerances": dict(sorted(op_spec.tolerances.items())),
            "result": _result_row(op_spec),
            "refinement": _refinement_row(op_spec),
        }
        encoded = _canonical_json(payload)
        return cls(
            op_name=op_spec.name,
            _payload_json=encoded,
            digest=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = json.loads(self._payload_json)
        payload["contract_digest"] = self.digest
        return payload


def contract_for(op_name: str) -> OpContract:
    try:
        op_spec = spec.OPS[op_name]
    except KeyError as exc:
        raise OpContractError(f"unknown operation {op_name!r}") from exc
    return OpContract.from_spec(op_spec)


def audit_contract_kernel() -> tuple[str, ...]:
    """Check the seams that used to drift independently.

    This is deliberately structural.  Dynamic witness mutation tests remain
    the stronger proof that an emitted check can actually fail.
    """

    problems: list[str] = []
    from kukai.ir import translation_cert

    problems.extend(translation_cert.audit_registry_coverage())
    table = translation_cert._ensure_table()

    for op_name, op_spec in sorted(spec.OPS.items()):
        param_names = {param.name for param in op_spec.params}
        grounded_names: set[str] = set()
        for field_name, _pool, required in op_spec.grounded:
            if field_name in grounded_names:
                problems.append(f"{op_name}: duplicate grounded field {field_name!r}")
            grounded_names.add(field_name)
            param = next((item for item in op_spec.params
                          if item.name == field_name), None)
            if param is None:
                problems.append(
                    f"{op_name}: grounded field {field_name!r} is not a parameter")
            elif required and not param.required:
                problems.append(
                    f"{op_name}: grounded field {field_name!r} is required by "
                    "grounding but optional in the registry")

        refinement = table.get(op_name)
        if refinement is not None:
            for obligation in refinement.obligations:
                for gate_name in (obligation.param, obligation.unless_param):
                    if (gate_name is not None
                            and gate_name not in param_names
                            and not gate_name.startswith("__")):
                        problems.append(
                            f"{op_name}: obligation gate {gate_name!r} is not "
                            "a registry parameter or named compiler-derived field")
        try:
            contract_for(op_name)
        except (OpContractError, TypeError, ValueError) as exc:
            problems.append(f"{op_name}: cannot build canonical contract: {exc}")

    return tuple(problems)


__all__ = [
    "OP_CONTRACT_SCHEMA",
    "OpContract",
    "OpContractError",
    "audit_contract_kernel",
    "contract_for",
]
