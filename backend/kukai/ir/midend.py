"""Typed, immutable KIR plan and grounded mid-end evidence.

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

``GroundedProgram`` is a parent-bound child of that exact plan.  It freezes the
model-dependent selector decisions that authoring emitters still consume as
legacy dictionaries and accounts for every nested ``__grounded__`` marker.
The digest names the exact trusted-grounder output; it does **not** attest the
identity or revision of the snapshot that produced it.  That requires a future
authoritative context contract and must not be inferred from ``ground_digest``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from kukai.ir.registry_base import EffectKind, ResultSpec


PLAN_SCHEMA = "kir-planned-program/1"
GROUND_SCHEMA = "kir-grounded-program/1"


class PlanEncodingError(ValueError):
    """A normalised payload cannot be represented by canonical JSON."""


def _canonical_json(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        # ``ensure_ascii=False`` otherwise accepts an isolated UTF-16
        # surrogate and fails only later, while hashing.  Reject it at the
        # canonical boundary: planning converts it to a typed input refusal,
        # while an impossible ground-stage payload becomes fail-closed
        # KIR-P000 at the public compiler facade instead of escaping.
        encoded.encode("utf-8", errors="strict")
        return encoded
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
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


@dataclass(frozen=True, slots=True)
class GroundingResolution:
    """One explicit model-dependent selector resolution."""

    op_id: str
    field_name: str
    via: str
    resolved_id: int | str | None
    resolved_name: str | None
    _detail_json: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.op_id, str) or not self.op_id:
            raise ValueError("grounding resolution needs an op id")
        if not isinstance(self.field_name, str) or not self.field_name:
            raise ValueError("grounding resolution needs a field path")
        if not isinstance(self.via, str) or not self.via:
            raise ValueError("grounding resolution needs a named rule")
        if isinstance(self.resolved_id, bool) or not isinstance(
                self.resolved_id, (int, str, type(None))):
            raise TypeError("resolved id must be int, str, or None")
        if self.resolved_name is not None and not isinstance(
                self.resolved_name, str):
            raise TypeError("resolved name must be a string or None")
        try:
            detail = json.loads(self._detail_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("grounding detail must be canonical JSON") from exc
        if (not isinstance(detail, dict)
                or _canonical_json(detail) != self._detail_json):
            raise ValueError("grounding detail must be a canonical object")

    @classmethod
    def from_dict(
        cls,
        *,
        op_id: str,
        field_name: str,
        detail: dict[str, Any],
    ) -> "GroundingResolution":
        via = detail.get("via")
        if not isinstance(via, str) or not via:
            # A missing rule is not evidence named "unknown".  Reject it:
            # inventing provenance here would make an unaccounted resolution
            # look complete merely because it was included in the digest.
            raise ValueError("grounding resolution needs a named rule")
        return cls(
            op_id=op_id,
            field_name=field_name,
            via=via,
            resolved_id=detail.get("id", detail.get("ref")),
            resolved_name=detail.get("name"),
            _detail_json=_canonical_json(detail),
        )

    @classmethod
    def collect(
        cls,
        *,
        op_id: str,
        payload: dict[str, Any],
    ) -> tuple["GroundingResolution", ...]:
        """Collect every nested marker once, with a stable field path.

        Selectors can be nested below lists (``levels[0]`` on multistory
        stairs) and below authored containers (group members).  Stopping at
        top-level fields would produce a green digest with unaccounted model
        choices, so traversal is recursive and deterministic.
        """
        found: list[GroundingResolution] = []

        def visit(value: Any, path: str) -> None:
            if isinstance(value, dict):
                if "__grounded__" in value:
                    detail = value["__grounded__"]
                    if not isinstance(detail, dict):
                        raise ValueError(
                            f"grounding marker at {path or '<root>'} "
                            "must be an object")
                    found.append(cls.from_dict(
                        op_id=op_id,
                        field_name=path or "<root>",
                        detail=detail,
                    ))
                for key in sorted(value):
                    child_path = f"{path}.{key}" if path else key
                    visit(value[key], child_path)
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")

        visit(payload, "")
        return tuple(found)

    def to_dict(self) -> dict[str, Any]:
        return {
            "op_id": self.op_id,
            "field_name": self.field_name,
            "via": self.via,
            "resolved_id": self.resolved_id,
            "resolved_name": self.resolved_name,
            "detail": json.loads(self._detail_json),
        }


@dataclass(frozen=True, slots=True)
class GroundedOp:
    """Canonical grounded payload corresponding to exactly one planned op."""

    op_id: str
    op_name: str
    _payload_json: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.op_id, str) or not self.op_id:
            raise ValueError("grounded op id must be a non-empty string")
        if not isinstance(self.op_name, str) or not self.op_name:
            raise ValueError("grounded op name must be a non-empty string")
        try:
            payload = json.loads(self._payload_json)
        except (TypeError, ValueError) as exc:
            raise ValueError("grounded op payload must be canonical JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("grounded op payload must be an object")
        if payload.get("id") != self.op_id or payload.get("op") != self.op_name:
            raise ValueError("grounded op identity disagrees with payload")
        if _canonical_json(payload) != self._payload_json:
            raise ValueError("grounded op payload is not canonical")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GroundedOp":
        if not isinstance(payload, dict):
            raise TypeError("grounded op payload must be an object")
        return cls(
            op_id=payload["id"],
            op_name=payload["op"],
            _payload_json=_canonical_json(payload),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a detached mutable copy for legacy emitters."""
        return json.loads(self._payload_json)

    @property
    def payload_digest(self) -> str:
        return hashlib.sha256(self._payload_json.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class GroundedProgram:
    """Immutable exact output of grounding one :class:`PlannedProgram`.

    Parent binding fixes operation order/identity and prevents a changed
    output from retaining the same digest.  It does not independently prove
    that each changed planned value was a legal lowering: ``ground_program``
    trusts the existing ground stage for that semantic transformation.
    """

    planned: PlannedProgram
    ops: tuple[GroundedOp, ...]
    resolutions: tuple[GroundingResolution, ...]
    ground_digest: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.planned, PlannedProgram):
            raise TypeError("grounded program needs a typed parent plan")
        if (not isinstance(self.ops, tuple)
                or any(not isinstance(op, GroundedOp) for op in self.ops)):
            raise TypeError("grounded operations must be a typed tuple")
        if (not isinstance(self.resolutions, tuple)
                or any(not isinstance(item, GroundingResolution)
                       for item in self.resolutions)):
            raise TypeError("grounding resolutions must be a typed tuple")

        planned_identity = [
            (op.op_id, op.op_name) for op in self.planned.ops
        ]
        grounded_identity = [(op.op_id, op.op_name) for op in self.ops]
        if grounded_identity != planned_identity:
            raise ValueError(
                "grounded operations must preserve parent order and identity")

        # Grounding legitimately replaces selectors and addressed geometry,
        # so equality with planned values is not a valid law here.  Preserve
        # every planned field, then bind the exact resulting values in the
        # payload digest below.  Legality remains the trusted grounder's job.
        for planned_op, grounded_op in zip(self.planned.ops, self.ops):
            if not set(planned_op.to_dict()).issubset(grounded_op.to_dict()):
                raise ValueError("grounding removed a planned field")

        known_ids = {op.op_id for op in self.ops}
        if any(item.op_id not in known_ids for item in self.resolutions):
            raise ValueError("grounding report references an unknown op")
        expected_resolutions = tuple(
            item
            for op in self.ops
            for item in GroundingResolution.collect(
                op_id=op.op_id,
                payload=op.to_dict(),
            )
        )
        if self.resolutions != expected_resolutions:
            raise ValueError(
                "grounding report must cover every grounded selector exactly")

        computed = hashlib.sha256(
            _canonical_json(self._unsigned_evidence()).encode("utf-8")
        ).hexdigest()
        if self.ground_digest and self.ground_digest != computed:
            raise ValueError("ground_digest disagrees with grounded payload")
        object.__setattr__(self, "ground_digest", computed)

    @classmethod
    def from_ops(
        cls,
        planned: PlannedProgram,
        ops: list[dict[str, Any]],
        resolutions: tuple[GroundingResolution, ...] | None = None,
    ) -> "GroundedProgram":
        grounded_ops = tuple(GroundedOp.from_dict(op) for op in ops)
        if resolutions is None:
            resolutions = tuple(
                item
                for op in grounded_ops
                for item in GroundingResolution.collect(
                    op_id=op.op_id,
                    payload=op.to_dict(),
                )
            )
        return cls(
            planned=planned,
            ops=grounded_ops,
            resolutions=resolutions,
        )

    def _unsigned_evidence(self) -> dict[str, Any]:
        return {
            "schema": GROUND_SCHEMA,
            "plan_digest": self.planned.plan_digest,
            "ops": [
                {"payload": op.to_dict(), "payload_digest": op.payload_digest}
                for op in self.ops
            ],
            "resolutions": [item.to_dict() for item in self.resolutions],
        }

    def to_ops(self) -> list[dict[str, Any]]:
        return [op.to_dict() for op in self.ops]

    def resolution_report(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.resolutions]

    def to_evidence_dict(self) -> dict[str, Any]:
        payload = self._unsigned_evidence()
        payload["ground_digest"] = self.ground_digest
        return payload
