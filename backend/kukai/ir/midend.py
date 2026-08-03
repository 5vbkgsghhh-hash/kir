"""Typed, immutable KIR mid-end plan.

The parser historically returned a mutable ``list[dict]``.  That made the
normalised program an implicit convention: compilation, result checking and
independent acceptance could each expand/default the source again and quietly
reason about a different program.  This module gives that boundary a value
object with a stable digest and explicit top-level field provenance.

``PlannedProgram`` deliberately stores every normalised op as canonical JSON.
Callers receive a fresh object from :meth:`PlannedOp.to_dict`, so no downstream
stage can mutate the plan that was hashed.  The digest covers both executable
payload and typed registry contracts; changing an op's effect/result semantics
therefore changes the evidence identity even when its source spelling does not.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from kukai.ir.registry_base import EffectKind, ResultSpec


PLAN_SCHEMA = "kir-planned-program/1"


class PlanEncodingError(ValueError):
    """A normalised payload cannot be represented by canonical JSON."""


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
        raise PlanEncodingError(str(exc)) from exc


class FieldOrigin(str, Enum):
    """Origin of a normalised top-level operation field."""

    EXPLICIT = "explicit"
    MACRO_DERIVED = "macro_derived"
    ENVELOPE_DEFAULT = "envelope_default"
    REGISTRY_DEFAULT = "registry_default"
    COMPILER_DERIVED = "compiler_derived"


class OperationFamily(str, Enum):
    QUERY = "query"
    AUTHORING = "authoring"
    MODIFY = "modify"


class ProgramFamily(str, Enum):
    QUERY = "query"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class OpProvenance:
    """Where one planned op and each of its top-level fields came from.

    Provenance for macro bodies is intentionally coarse: any non-default field
    in an expanded op is ``MACRO_DERIVED``.  Claiming whether a nested value was
    copied, interpolated or generated would require a field-path trace inside
    every macro expander; this contract does not fabricate that precision.
    """

    source_index: int
    source_op: str | None
    source_id: str | None
    macro_name: str | None
    field_origins: tuple[tuple[str, FieldOrigin], ...]

    def __post_init__(self) -> None:
        if (isinstance(self.source_index, bool)
                or not isinstance(self.source_index, int)
                or self.source_index < 0):
            raise ValueError("source_index must be a non-negative int")
        if not isinstance(self.field_origins, tuple):
            raise TypeError("field_origins must be an immutable tuple")
        names = [name for name, _origin in self.field_origins]
        if any(not isinstance(name, str) or not name for name in names):
            raise TypeError("field origin names must be non-empty strings")
        if names != sorted(names) or len(names) != len(set(names)):
            raise ValueError("field_origins must be unique and sorted")
        if any(not isinstance(origin, FieldOrigin)
               for _name, origin in self.field_origins):
            raise TypeError("field origins must be typed")
        if self.macro_name is not None and not self.macro_name:
            raise ValueError("macro_name cannot be empty")

    def origin_for(self, field_name: str) -> FieldOrigin | None:
        return dict(self.field_origins).get(field_name)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source_index": self.source_index,
            "source_op": self.source_op,
            "source_id": self.source_id,
            "fields": {name: origin.value
                       for name, origin in self.field_origins},
        }
        if self.macro_name is not None:
            payload["macro_name"] = self.macro_name
        return payload


@dataclass(frozen=True, slots=True)
class PlannedOp:
    """One immutable, normalised operation and its typed registry contract."""

    op_id: str
    op_name: str
    family: OperationFamily
    effect: EffectKind
    result: ResultSpec
    provenance: OpProvenance
    _payload_json: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.op_id, str) or not self.op_id:
            raise ValueError("planned op id must be a non-empty string")
        if not isinstance(self.op_name, str) or not self.op_name:
            raise ValueError("planned op name must be a non-empty string")
        if not isinstance(self.family, OperationFamily):
            raise TypeError("planned op family must be typed")
        if not isinstance(self.effect, EffectKind):
            raise TypeError("planned op effect must be typed")
        if not isinstance(self.result, ResultSpec):
            raise TypeError("planned op result must be typed")
        if not isinstance(self.provenance, OpProvenance):
            raise TypeError("planned op provenance must be typed")
        try:
            payload = json.loads(self._payload_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("planned op payload must be canonical JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("planned op payload must be an object")
        if payload.get("id") != self.op_id or payload.get("op") != self.op_name:
            raise ValueError("planned op identity disagrees with payload")
        if _canonical_json(payload) != self._payload_json:
            raise ValueError("planned op payload is not canonical")
        if set(payload) != {name for name, _ in self.provenance.field_origins}:
            raise ValueError("field provenance must cover the whole payload")

    @classmethod
    def from_dict(
        cls,
        payload: dict[str, Any],
        *,
        family: OperationFamily,
        effect: EffectKind,
        result: ResultSpec,
        provenance: OpProvenance,
    ) -> "PlannedOp":
        return cls(
            op_id=payload["id"],
            op_name=payload["op"],
            family=family,
            effect=effect,
            result=result,
            provenance=provenance,
            _payload_json=_canonical_json(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a detached mutable copy for legacy emit/ground stages."""
        return json.loads(self._payload_json)

    @property
    def payload_digest(self) -> str:
        return hashlib.sha256(self._payload_json.encode("utf-8")).hexdigest()

    def to_evidence_dict(self) -> dict[str, Any]:
        return {
            "payload": self.to_dict(),
            "family": self.family.value,
            "effect": self.effect.value,
            "result": {
                "identity_cardinality": self.result.identity_cardinality.value,
                "identity_field": self.result.identity_field,
                "reference_kind": (
                    self.result.reference_kind.value
                    if self.result.reference_kind is not None else None
                ),
            },
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class PlannedProgram:
    """Validated KIR plan: the sole semantic input to downstream stages."""

    ir_version: str
    family: ProgramFamily
    ops: tuple[PlannedOp, ...]
    intent: str
    allow_destructive: bool
    bulk: bool
    source_op_count: int
    program_id: str | None = None
    plan_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.ir_version, str) or not self.ir_version:
            raise ValueError("planned IR version must be a non-empty string")
        if not isinstance(self.family, ProgramFamily):
            raise TypeError("planned program family must be typed")
        if not isinstance(self.ops, tuple):
            raise TypeError("planned operations must be an immutable tuple")
        if not self.ops or any(not isinstance(op, PlannedOp) for op in self.ops):
            raise ValueError("planned program needs typed operations")
        if (isinstance(self.source_op_count, bool)
                or not isinstance(self.source_op_count, int)
                or self.source_op_count < 1):
            raise ValueError("source_op_count must be positive")
        if not isinstance(self.intent, str):
            raise TypeError("planned intent must be a string")
        if not isinstance(self.allow_destructive, bool) or not isinstance(self.bulk, bool):
            raise TypeError("plan policy flags must be bool")
        op_families = {op.family for op in self.ops}
        if self.family is ProgramFamily.QUERY:
            if op_families != {OperationFamily.QUERY}:
                raise ValueError("query plan contains a write operation")
        elif OperationFamily.QUERY in op_families:
            raise ValueError("write plan contains a query operation")
        ids = [op.op_id for op in self.ops]
        if len(ids) != len(set(ids)):
            raise ValueError("planned op ids must be unique")
        computed = hashlib.sha256(
            _canonical_json(self._unsigned_evidence()).encode("utf-8")
        ).hexdigest()
        if self.plan_digest and self.plan_digest != computed:
            raise ValueError("plan_digest disagrees with planned payload")
        object.__setattr__(self, "plan_digest", computed)

    def _unsigned_evidence(self) -> dict[str, Any]:
        return {
            "schema": PLAN_SCHEMA,
            "ir_version": self.ir_version,
            "family": self.family.value,
            "intent": self.intent,
            "allow_destructive": self.allow_destructive,
            "bulk": self.bulk,
            "source_op_count": self.source_op_count,
            "program_id": self.program_id,
            "ops": [op.to_evidence_dict() for op in self.ops],
        }

    def to_ops(self) -> list[dict[str, Any]]:
        """Return detached mutable operations for grounders and emitters."""
        return [op.to_dict() for op in self.ops]

    def to_evidence_dict(self) -> dict[str, Any]:
        payload = self._unsigned_evidence()
        payload["plan_digest"] = self.plan_digest
        return payload
